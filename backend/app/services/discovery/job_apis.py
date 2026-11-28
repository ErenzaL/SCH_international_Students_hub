"""Recruitment data through OFFICIAL APIs only (never by scraping). Both need a key the owner obtains; without it a check ends
with ``api_key_missing`` and the source is shown as blocked. Fixed hosts, https, GET; keys never reach logs, URLs or the database.

saramin_api        https://oapi.saramin.co.kr/guide/job-search   SARAMIN_ACCESS_KEY   at most 500 calls a day
data_go_kr_jobs    https://www.data.go.kr/data/15125273/openapi.do (public institutions)   DATA_GO_KR_SERVICE_KEY
work24_api         고용24 OPEN-API 채용정보 (callOpenApiSvcInfo210L01, XML)                 WORK24_AUTH_KEY

Only what a student needs to find the posting is kept: title, employer, place, dates, link. Nothing is published: items are review
candidates like every other discovery. Tested with fixtures of the documented response shapes, NOT with a real key.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.discovery.connectors import ConnectorResult, Entry
from app.services.ingestion.errors import FetchError

log = logging.getLogger("app.discovery.jobs")
KST = timezone(timedelta(hours=9))
KINDS = {"saramin_api": ("https://oapi.saramin.co.kr/job-search", "saramin_access_key", "SARAMIN_ACCESS_KEY", "사람인"),
         "data_go_kr_jobs": ("https://apis.data.go.kr/1051000/recruitment/list", "data_go_kr_service_key", "DATA_GO_KR_SERVICE_KEY",
                             "재정경제부 공공기관 채용정보"),
         "work24_api": ("https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do", "work24_auth_key",
                        "WORK24_AUTH_KEY", "고용24 채용정보")}
#: the page an administrator and a student see as the source (the API address itself contains nothing readable)
HOME = {"saramin_api": "https://www.saramin.co.kr/", "data_go_kr_jobs": "https://job.alio.go.kr/",
        "work24_api": "https://www.work24.go.kr/"}
LINK_HOSTS = {"saramin_api": ("saramin.co.kr",), "data_go_kr_jobs": ("alio.go.kr", "go.kr", "or.kr", "re.kr", "ac.kr", "co.kr", "kr"),
              "work24_api": ("work24.go.kr", "work.go.kr")}
RELEVANT = re.compile(r"외국인|유학생|글로벌|해외|통역|번역|다국어|영어|중국어|베트남|인도네시아|foreign|international|global|interpret", re.I)
MAX = 2_000_000


class JobApiError(FetchError):
    pass


def check_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    from app.core.errors import ValidationFailed

    allowed = {"keywords", "max_items", "only_relevant"}
    if set(config) - allowed:
        raise ValidationFailed(f"Unknown settings: {', '.join(sorted(set(config) - allowed))}.")
    out: dict[str, Any] = {"max_items": max(1, min(int(config.get("max_items") or 10), 30)),
                           "only_relevant": bool(config.get("only_relevant", True))}
    kw = str(config.get("keywords") or "").strip()
    if len(kw) > 100:
        raise ValidationFailed("keywords is too long.")
    if kw:
        out["keywords"] = kw
    return out


def run(source: dict[str, Any], settings: Any, limit: int, http: httpx.Client | None = None) -> ConnectorResult:
    kind = source["kind"]
    url, attr, env, _name = KINDS[kind]
    key = str(getattr(settings, attr, "") or "").strip()
    if not key:
        raise JobApiError("api_key_missing", f"{env} is not set: this source needs an API key from the provider.")
    cfg = source.get("config") or {}
    if kind == "saramin_api":
        params: dict[str, str] = {"access-key": key, "count": "50", "sort": "pd", "fields": "posting-date,expiration-date"}
    elif kind == "work24_api":       # only postings registered within the last week: one weekly check sees each once
        params = {"authKey": key, "callTp": "L", "returnType": "XML", "startPage": "1", "display": "50", "regDate": "W-1"}
    else:
        params = {"serviceKey": key, "numOfRows": "50", "pageNo": "1", "ongoingYn": "Y", "resultType": "json"}
    if cfg.get("keywords"):
        params[{"saramin_api": "keywords", "work24_api": "keyword"}.get(kind, "recrutPbancTtl")] = cfg["keywords"]
    client = http or httpx.Client(timeout=20, follow_redirects=False, trust_env=False)
    try:
        r = client.get(url, params=params, headers={"Accept": "application/xml" if kind == "work24_api" else "application/json"})
    except httpx.HTTPError as exc:       # the exception text contains the URL with the key: only its type is kept
        raise JobApiError("timeout" if isinstance(exc, httpx.TimeoutException) else "connect_error", "The API could not be reached.") from None
    finally:
        if http is None:
            client.close()
    if r.status_code != 200:
        raise JobApiError(f"http_{r.status_code}", "The API refused the request.")
    if len(r.content) > MAX:
        raise JobApiError("too_large", "The API answer is too large.")
    if kind == "work24_api":
        rows = _work24(r.content)
    else:
        try:
            data = r.json()
        except ValueError:
            raise JobApiError("invalid_answer", "The API answer is not JSON (is the key valid?).") from None
        rows = _saramin(data) if kind == "saramin_api" else _public(data)
    entries, seen = [], set()
    for row in rows:
        if len(entries) >= limit:
            break
        e = _entry(kind, row)
        # relevance from the posting itself, never from the employer's name ("(주)OO글로벌" is not a foreign-language job)
        about = " ".join(_plain(row.get(k)) for k in ("title", "type", "need"))
        if e is None or e.key in seen or (cfg.get("only_relevant", True) and not RELEVANT.search(about)):
            continue
        seen.add(e.key)
        entries.append(e)
    digest = hashlib.sha256("|".join(sorted(e.key for e in entries)).encode()).hexdigest()
    return ConnectorResult(entries, digest, 1)


def _saramin(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and "code" in data and "jobs" not in data:
        code = str(data["code"])
        raise JobApiError({"1": "api_key_missing", "2": "api_key_invalid", "4": "http_429"}.get(code, f"api_error_{code[:6]}"), "The API reported an error.")
    jobs = ((data or {}).get("jobs") or {}).get("job") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise JobApiError("structure_changed", "The API answer has an unknown structure.")
    out = []
    for j in jobs:
        p, c = j.get("position") or {}, ((j.get("company") or {}).get("detail") or {})
        out.append(dict(id=str(j.get("id") or ""), url=j.get("url"), title=p.get("title"), org=c.get("name"), place=(p.get("location") or {}).get("name"),
                        type=(p.get("job-type") or {}).get("name"), need=(p.get("required-education-level") or {}).get("name"),
                        start=_stamp(j.get("posting-timestamp") or j.get("posting-date")), end=_stamp(j.get("expiration-timestamp") or j.get("expiration-date")),
                        open=str(j.get("active", "1")) == "1"))
    return out


def _public(data: Any) -> list[dict[str, Any]]:
    rows = (data or {}).get("result") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise JobApiError("api_key_invalid" if "SERVICE" in json.dumps(data)[:500].upper() and "KEY" in json.dumps(data)[:500].upper() else "structure_changed",
                          "The API answer has an unknown structure.")
    return [dict(id=str(j.get("recrutPblntSn") or ""), url=j.get("srcUrl"), title=j.get("recrutPbancTtl"), org=j.get("instNm"), place=j.get("workRgnNmLst"),
                 type=j.get("hireTypeNmLst"), need=j.get("acbgCondNmLst"), start=_ymd(j.get("pbancBgngYmd")), end=_ymd(j.get("pbancEndYmd")),
                 open=j.get("ongoingYn") != "N") for j in rows]


def _work24(raw: bytes) -> list[dict[str, Any]]:
    """<wantedRoot><total/><wanted>...</wanted></wantedRoot> (field names from the official 고용24 page). Documents with
    a DOCTYPE or entities are refused before parsing (no entity expansion)."""
    import xml.etree.ElementTree as ET  # noqa: S405 - DOCTYPE / ENTITY refused below

    head = raw[:4096].decode("utf-8", "replace").upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in head:
        raise JobApiError("invalid_answer", "The API answer contains a document type declaration.")
    try:
        root = ET.fromstring(raw)  # noqa: S314
    except ET.ParseError:
        raise JobApiError("invalid_answer", "The API answer is not XML (is the key valid?).") from None
    if root.tag != "wantedRoot":
        text = " ".join(root.itertext())[:300]
        raise JobApiError("api_key_invalid" if re.search(r"인증|auth|key", text, re.I) else "structure_changed",
                          "The API reported an error or changed its structure.")
    out = []
    for w in root.findall("wanted"):
        g = lambda k: (w.findtext(k) or "").strip()  # noqa: E731, B023
        out.append(dict(id=g("wantedAuthNo"), url=g("wantedInfoUrl") or g("wantedMobileInfoUrl"), title=g("title"),
                        org=g("company"), place=g("region"), type=g("holidayTpNm"), need=g("minEdubg"),
                        start=_yy(g("regDt")), end=_yy(g("closeDt")), open=True, pay=" ".join(x for x in (g("salTpNm"), g("sal")) if x),
                        until_filled=bool(re.search(r"채용시|상시|까지", g("closeDt"))) and _yy(g("closeDt")) is None))
    return out


def _yy(v: str) -> str | None:
    """2026-12-31 | 20261231 | 26-12-31 -> 2026-12-31; '채용시까지' (until filled) and anything else -> None."""
    m = re.search(r"(?<!\d)(20\d{2}|\d{2})[-./]?(\d{2})[-./]?(\d{2})(?!\d)", v or "")
    if not m:
        return None
    y = int(m[1]) if len(m[1]) == 4 else 2000 + int(m[1])
    try:
        return datetime(y, int(m[2]), int(m[3])).date().isoformat()
    except ValueError:
        return None


def _stamp(v: Any) -> str | None:
    if v is None or v == "":
        return None
    try:
        return datetime.fromtimestamp(int(v), UTC).astimezone(KST).date().isoformat()
    except (ValueError, OverflowError, OSError):
        m = re.match(r"(20\d{2}-\d{2}-\d{2})", str(v))
        return m[1] if m else None


def _ymd(v: Any) -> str | None:
    m = re.fullmatch(r"(20\d{2})-?(\d{2})-?(\d{2})", str(v or ""))
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def _plain(v: Any, n: int = 200) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]{0,200}>", " ", str(v or ""))).strip()[:n]


def _entry(kind: str, row: dict[str, Any]) -> Entry | None:
    title, org = _plain(row["title"]), _plain(row["org"])
    if not row["id"] or not title or not row["open"]:
        return None
    url = str(row["url"] or "")
    m = re.match(r"https?://([^/:?#@]+)(?:[/?#]|$)", url)
    if not m or not any(m[1] == h or m[1].endswith("." + h) for h in LINK_HOSTS[kind]):
        url = HOME[kind]
    lines = [f"기관·기업: {org}" if org else "", f"근무지: {_plain(row['place'])}" if row["place"] else "", f"고용 형태: {_plain(row['type'])}" if row["type"] else "",
             f"학력 조건: {_plain(row['need'])}" if row["need"] else "", f"급여: {_plain(row['pay'])}" if row.get("pay") else "",
             f"접수 마감: {row['end']}" if row["end"] else ("접수 마감: 채용 시까지 (날짜 없음)" if row.get("until_filled") else ""),
             f"원문: {url}",
             f"출처: {KINDS[kind][3]}. 지원 자격과 체류자격별 취업 허가는 원문과 출입국에서 확인하십시오."]
    return Entry(key=f"{HOME[kind]}#{kind}-{row['id'][:80]}", url=url[:1000], title=f"[채용] {org} {title}".replace("[채용]  ", "[채용] ")[:500], published_on=row["start"],
                 text="\n".join(x for x in lines if x), links=[{"text": "지원하기 (원문)", "href": url}], flags=["api_item"])

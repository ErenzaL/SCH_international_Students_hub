"""Deterministic facts from an official notice: dates, deadlines, eligibility lines, application links, category,
opportunity kind and whether it is open - plus flags for everything that is missing or uncertain.

Nothing is inferred beyond the text: every date and eligibility line is quoted from the source, links come from the
page's own anchors, and an opportunity is only "open" when the source states a deadline that has not passed (or
explicitly says applications are open) and does not say they are closed. External text is treated as data only.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.services.agents.tools import extract_dates

# ------------------------------------------------------------------------------------------- classification
# (category slug, pattern) - first match wins; the matched word is returned so the choice is explainable
CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("scholarships", re.compile(r"장학|scholarship|GKS|beasiswa|học bổng|奖学金|등록금\s*(?:감면|지원)", re.I)),
    ("visa-immigration", re.compile(r"비자|사증|체류|출입국|외국인\s*등록|visa|immigration|residence card", re.I)),
    ("dormitory-housing", re.compile(r"생활관|기숙사|글로벌빌리지|dormitor|housing", re.I)),
    ("health-insurance", re.compile(r"건강\s*보험|보험료|의료|health insurance|헬스케어", re.I)),
    ("topik-korean", re.compile(r"TOPIK|한국어\s*능력|한국어\s*(?:교육|강좌|말하기)|Korean language", re.I)),
    ("part-time-employment", re.compile(r"아르바이트|시간제\s*취업|불법\s*취업|part[- ]time", re.I)),
    ("employment-internships", re.compile(r"채용|인턴|취업|일자리|구인|박람회|job fair|recruit|\binternships?\b|employment", re.I)),
    ("academic-life", re.compile(r"수강|학사|성적|졸업|휴학|복학|등록금|학점|course|semester|graduat", re.I)),
]
KIND_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("scholarship", re.compile(r"장학|scholarship|GKS|beasiswa|học bổng|奖学金|tuition (?:waiver|reduction)", re.I)),
    ("competition", re.compile(r"공모전|대회|경진|경연|챌린지|해커톤|contest|competition|hackathon|challenge", re.I)),
    ("job", re.compile(r"채용|인턴십?|구인|일자리|\bjobs?\b|\bintern(?:ship)?s?\b|recruit(?:ment)? of staff|employment fair|채용박람회", re.I)),
    ("program", re.compile(r"서포터즈|참가자|참여자|프로그램|연수|캠프|교환학생|문화체험|컨퍼런스|program|exchange|camp|"
                           r"conference|ambassador|supporters", re.I)),
]

ELIGIBILITY = re.compile(r"(?:지원|신청|응시|참가)?\s*자격|대상\s*[:：]|모집\s*대상|지원\s*대상|eligib|who can apply|"
                         r"requirements?\s*[:：]|applicants? must|persyaratan|đối tượng|điều kiện|申请资格|对象", re.I)
APPLY_TEXT = re.compile(r"신청|지원하기|접수|apply|application|register|registration|등록|지원서|신청서|form|"
                        r"daftar|đăng ký|报名|申请", re.I)
APPLY_URL = re.compile(r"apply|application|signup|sign-up|register|form|forms\.gle|docs\.google\.com/forms|recruit", re.I)
# explicit statements only: "접수 마감: 11/27" means "the deadline is", not "it has closed"
CLOSED = re.compile(r"접수\s*기간이\s*아닙니다|(?:접수|모집|신청)(?:이|가)?\s*마감되었|마감되었습니다|조기\s*마감|종료되었습니다|"
                    r"applications? (?:are|is) (?:now )?closed|no longer accepting|not (?:currently )?accepting|"
                    r"pendaftaran (?:telah )?ditutup|đã đóng|已截止", re.I)
# "[대학일자리플러스센터] ..." names the office that posted it; it says nothing about what the notice offers
_ORG_PREFIX = re.compile(r"\[\s*[^\]]*?(?:센터|사업단|교류처|본부|위원회|협회|재단|진흥원|연구원|대학원|학과|팀|처|과|원|단|실|청|부)\s*\]")
OPEN = re.compile(r"접수\s*중|모집\s*중|applications? (?:are|is) (?:now )?open|now accepting|sedang dibuka|đang mở|正在接受", re.I)


def classify(title: str, text: str) -> dict[str, Any]:
    category, word = "university-announcements", None
    # the title decides when it can; the opening of the body only when the title says nothing
    for part in (title, text[:600]):
        for slug, rx in CATEGORY_RULES:
            m = rx.search(part)
            if m:
                category, word = slug, m.group(0)
                break
        if word:
            break
    kind, kind_word = None, None
    offer = _ORG_PREFIX.sub(" ", title)
    for k, rx in KIND_RULES:
        m = rx.search(offer)          # the title states what a notice offers; body words are too noisy
        if m:
            kind, kind_word = k, m.group(0)
            break
    return dict(category=category, category_reason=word, opportunity_kind=kind, kind_reason=kind_word)


def eligibility_lines(text: str, limit: int = 5) -> list[str]:
    out: list[str] = []
    lines = [x.strip(" -•·*#\t") for x in text.splitlines()]
    lines = [x for x in lines if x]
    for i, line in enumerate(lines):
        if not ELIGIBILITY.search(line):
            continue
        quote = line
        if len(line) < 25 and i + 1 < len(lines):   # a "지원 자격" heading: the next line holds the rule
            quote = f"{line}: {lines[i + 1]}"
        out.append(quote[:300])
        if len(out) >= limit:
            break
    return out


def application_links(links: list[dict[str, str]], attachments: list[dict[str, str]] | None = None,
                      limit: int = 6) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in [*(links or []), *(attachments or [])]:
        url = str(link.get("url") or link.get("href") or "")
        text = str(link.get("text") or link.get("name") or "")
        if not url.startswith(("https://", "http://")) or url in seen:
            continue
        if APPLY_TEXT.search(text) or APPLY_URL.search(url):
            seen.add(url)
            out.append(dict(url=url[:1000], text=text[:200], kind="attachment" if link in (attachments or []) else "link"))
        if len(out) >= limit:
            break
    return out


def analyse(title: str, text: str, *, published_on: str | None, links: list[dict[str, str]] | None = None,
            attachments: list[dict[str, str]] | None = None, today: date | None = None,
            min_body_chars: int = 40, watched: bool = False, list_only: bool = False) -> dict[str, Any]:
    """Everything the agents show about one item; ``flags`` lists what is missing or uncertain."""
    today = today or date.today()
    year = int(published_on[:4]) if published_on else today.year
    dates = extract_dates(f"{title}\n{text}", default_year=year, limit=20)
    deadlines = [d for d in dates if d["kind"] == "deadline"]
    # "(~11/6)" in a title is a deadline written without a keyword
    for m in re.finditer(r"[~∼～]\s*(\d{1,2})\s*[/.]\s*(\d{1,2})", title):
        try:
            deadlines.append(dict(date=date(year, int(m[1]), int(m[2])).isoformat(), kind="deadline", quote=title[:240],
                                  year_assumed=True))
        except ValueError:
            pass
    cls = classify(title, text)
    flags: list[str] = []
    if not published_on:
        if not watched:
            flags.append("missing_published_date")
    elif published_on > today.isoformat():
        flags.append("published_in_future")
    if len(text.strip()) < min_body_chars and not list_only:
        flags.append("little_text")
    if any(d.get("year_assumed") for d in deadlines):
        flags.append("year_assumed")
    if published_on and any(d["date"] < published_on for d in deadlines if not d.get("year_assumed")):
        flags.append("deadline_before_published")
    if len({d["date"] for d in deadlines}) > 2:
        flags.append("several_deadlines")
    elig = eligibility_lines(text)
    apply = application_links(links or [], attachments)
    is_opportunity = cls["opportunity_kind"] is not None
    if is_opportunity:
        if not deadlines:
            flags.append("missing_deadline")
        if not elig:
            flags.append("missing_eligibility")
        if not apply:
            flags.append("missing_application_link")

    # open only when the source supports it
    future = sorted(d["date"] for d in deadlines if d["date"] >= today.isoformat())
    past = [d for d in deadlines if d["date"] < today.isoformat()]
    if CLOSED.search(text) or CLOSED.search(title):
        open_status, reason = "closed", "source_says_closed"
    elif future and "deadline_before_published" not in flags:
        open_status, reason = "open", "deadline_in_future"
    elif deadlines and past and not future:
        open_status, reason = "closed", "deadline_passed"
    elif OPEN.search(text) or OPEN.search(title):
        open_status, reason = "open", "source_says_open"
    else:
        open_status, reason = "unknown", "no_deadline"
    if open_status == "open" and "year_assumed" in flags:
        flags.append("open_status_uncertain")
    return dict(**cls, dates=dates[:10], deadlines=deadlines[:5], next_deadline=future[0] if future else None,
                eligibility=elig, application_links=apply, open_status=open_status, open_reason=reason,
                flags=sorted(set(flags)))

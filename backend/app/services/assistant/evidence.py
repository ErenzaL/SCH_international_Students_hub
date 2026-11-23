"""Evidence sufficiency: does the selected evidence contain the *kind* of information the question asks for?

Optional layer between evidence selection and generation (``ASSISTANT_EVIDENCE_CHECK``, off by default):

1. ``required_information`` - which information types the question needs: a quantity (fee, hours, amount), a
   date/deadline, required documents/requirements, an eligibility condition, or a procedure. Detected with generic
   multilingual cue words (en / ko / id / vi / zh); no policy values or immigration rules are encoded.
2. ``check`` - whether any selected passage contains that information type (a number with a unit, a date or time
   limit, a list of documents, a condition, a sequence of steps). Purely textual: it says the evidence *has the shape*
   of an answer, never that a claim is true.
3. ``complete`` - when something is missing: (a) the neighbouring chunks (chunk_index +/- 1) of the best passages of
   documents already cited - text cut at a chunk boundary is the most common cause of a missing figure; (b) one
   bounded, targeted second search (question + generic vocabulary for the missing type). Added passages keep their
   own document, version, chunk and page, so citations stay exact.
4. The report records what was needed, what was found, what was added and what is *still missing*. Nothing is
   inferred and no LLM is asked to vouch for the evidence. Differing figures for the same unit across documents are
   reported as a *potential conflict* (not resolved).
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any

from app.repositories.base import Query, Store

NEED_TYPES = ("quantity", "date", "requirement", "eligibility", "procedure")

# --- what the question asks for (generic cue words, five languages) ---------------------------------------------
_NEEDS = {
    "quantity": re.compile(
        r"\bhow (much|many|long|often)\b|\b(fee|fees|cost|costs|price|amount|premium|maximum|minimum|limit|hours?)\b|"
        r"얼마|몇|비용|수수료|요금|금액|보험료|최대|최소|시간|"
        r"\bberapa\b|\bbiaya\b|\btarif\b|\bjam\b|bao nhiêu|\bphí\b|\bgiá\b|mấy|多少|几|费用|价格|小时", re.I),
    "date": re.compile(
        r"\bwhen\b|\bdeadline\b|\bby when\b|\buntil\b|\bhow soon\b|\bexpire|\bperiod\b|언제|기한|마감|까지|기간|만료|"
        r"\bkapan\b|batas waktu|tenggat|khi nào|\bhạn\b|bao giờ|什么时候|何时|截止|期限|多久", re.I),
    "requirement": re.compile(
        r"\bdocuments?\b|\brequire(d|ments?)?\b|\bwhat do i need\b|\bneed to (submit|bring|prepare)\b|\bsubmit\b|"
        r"서류|필요|준비물|제출|구비|\bdokumen\b|\bsyarat\b|\bpersyaratan\b|giấy tờ|hồ sơ|cần (gì|những gì)|"
        r"材料|文件|需要|准备", re.I),
    "eligibility": re.compile(
        r"\bcan i\b|\bam i (allowed|eligible)\b|\bis it (ok|okay|allowed|possible)\b|\beligib|\ballowed\b|\bpermitted\b|"
        r"\bdo i (have|need) to\b|\bmust i\b|가능|할 수 있|되나요|돼요|되나|해야 하나|해야 돼|\bbisakah\b|\bboleh\b|"
        r"\bapakah saya (bisa|boleh|harus)\b|có được|được không|có thể|có phải|可以|能否|能不能|是否需要|必须", re.I),
    "procedure": re.compile(
        r"\bhow (do|can|should) i\b|\bhow to\b|\bprocess\b|\bprocedure\b|\bsteps?\b|\bapply\b|\bregister\b|"
        r"어떻게|방법|절차|신청|등록|\bbagaimana\b|\bcara\b|\bprosedur\b|làm thế nào|cách|thủ tục|đăng ký|"
        r"如何|怎么|怎样|办理|申请|流程", re.I),
}

# --- what a passage must contain to carry that information (shape, not truth) -----------------------------------
_UNIT = (r"%|원|만\s*원|₩|won|krw|usd|\$|달러|dollars?|시간|hours?|hrs?|일|days?|주|weeks?|개월|months?|년|years?|"
         r"회|times|급|level|학점|credits?|분|minutes?|명|people|점|points?|jam|hari|minggu|bulan|tahun|giờ|ngày|tuần|"
         r"tháng|năm|lần|đồng|rupiah|小时|天|周|个月|年|元|韩元|次|级")
_MONEY = r"원|만\s*원|₩|won|krw|usd|\$|달러|dollars?|rupiah|rp\.?|đồng|vnd|元|韩元"
_HOURS = r"시간|hours?|hrs?|jam|giờ|小时"
_DURATION = r"일|days?|주|weeks?|개월|months?|년|years?|hari|minggu|bulan|tahun|ngày|tuần|tháng|năm|天|周|个月|年"
# what kind of quantity is asked (selects the unit class a passage must state); generic cue words only
_QUANTITY_KIND = {
    "money": re.compile(r"\b(fee|fees|cost|costs|price|premium|pay|charge)\b|how much|비용|수수료|요금|금액|보험료|얼마|"
                        r"\bbiaya\b|\btarif\b|\bphí\b|\bgiá\b|费用|价格|多少钱|收费", re.I),
    "hours": re.compile(r"\bhours?\b|시간|\bjam\b|\bgiờ\b|小时", re.I),
    "duration": re.compile(r"how long|\bperiod\b|기간|며칠|몇 ?달|몇 ?년|berapa lama|bao lâu|多久|多长时间", re.I),
}
_SIGNALS = {
    "quantity": re.compile(rf"\d[\d,.]*\s*(?:{_UNIT})(?![A-Za-z])|(?:{_UNIT})\s*\d", re.I),
    "money": re.compile(rf"\d[\d,.]*\s*(?:{_MONEY})(?![A-Za-z])|(?:{_MONEY})\s*\d", re.I),
    "hours": re.compile(rf"\d[\d,.]*\s*(?:{_HOURS})(?![A-Za-z])", re.I),
    "duration": re.compile(rf"\d[\d,.]*\s*(?:{_DURATION})(?![A-Za-z])", re.I),
    "date": re.compile(
        r"\b(19|20)\d{2}\s*[.\-/년]\s*\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일|\b\d{1,2}[./]\d{1,2}\b|"
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}|"
        r"\d+\s*(일|days?|weeks?|months?|개월|주|hari|ngày|天)\s*(이내|이전|전|within|before|after|후|of)|"
        r"\b(within|before|after|by|until|no later than)\s+\d", re.I),
    "requirement": re.compile(
        r"(서류|신청서|여권|증명서|사진|통장|계약서|외국인등록증|documents?|passport|certificate|application form|photo|"
        r"statement|receipt|dokumen|paspor|sertifikat|giấy|hộ chiếu|chứng nhận|护照|证明|照片|申请表)", re.I),
    "eligibility": re.compile(
        r"(이상|이하|미만|초과|불가|허용|제한|자격|한하여|한함|한해|금지|"
        r"\bmust\b|\bonly\b|\bnot allowed\b|\bnot permitted\b|\bprohibited\b|\beligib\w*|\brequired\b|\bat least\b|"
        r"\bno more than\b|\bwajib\b|\btidak boleh\b|\bhanya\b|không được|bắt buộc|chỉ được|仅限|不得|必须|禁止)", re.I),
    "procedure": re.compile(
        r"(→|->|①|②|③|\bstep \d|\bfirst\b|\bthen\b|\bnext\b|\bvisit\b|\bsubmit\b|\bapply\b|\bonline\b|\bbook\b|"
        r"방문|제출|신청|접수|발급|온라인|예약|\blangkah\b|\bajukan\b|bước|nộp|đặt lịch|步骤|提交|办理|预约)", re.I),
}
# how many DISTINCT markers a passage needs for list-like information types
_MIN_DISTINCT = {"requirement": 2, "procedure": 2}


# generic vocabulary added to a targeted second search for a missing type (no policy values)
_EXPANSION = {
    "quantity": "fee cost amount hours 비용 수수료 금액 시간",
    "date": "deadline period within days 기한 기간 이내 까지",
    "requirement": "required documents submit 제출서류 구비서류 신청서",
    "eligibility": "eligible allowed conditions only 대상 자격 허용 제한",
    "procedure": "procedure how to apply steps 절차 신청 방법",
}
_CONFLICT_UNIT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(시간|hours?|원|won|일|days?|개월|months?|%)", re.I)
_UNIT_NORMAL = {"hour": "hours", "hours": "hours", "시간": "hours", "원": "won", "won": "won", "일": "days", "day": "days",
                "days": "days", "개월": "months", "month": "months", "months": "months", "%": "%"}


def required_information(question: str) -> list[str]:
    return [n for n in NEED_TYPES if _NEEDS[n].search(question or "")]


def quantity_kind(question: str) -> str | None:
    """money / hours / duration when the question names one, else None (any number with a unit)."""
    return next((k for k, rx in _QUANTITY_KIND.items() if rx.search(question or "")), None)


def has_signal(need: str, text: str, kind: str | None = None) -> bool:
    """Does the text have the *shape* of this information type? (quantity: a number with a unit of the asked kind;
    requirement / procedure: at least two distinct markers; date: an explicit date or time limit)."""
    rx = _SIGNALS[kind] if need == "quantity" and kind else _SIGNALS[need]
    if need in _MIN_DISTINCT:
        return len({m.group(0).lower() for m in rx.finditer(text or "")}) >= _MIN_DISTINCT[need]
    return bool(rx.search(text or ""))


@dataclass
class EvidenceConfig:
    adjacent: bool = True             # (a) neighbouring chunks of cited documents
    check_sources: int = 1            # answer-bearing scope: passages of the top N sources (+ added passages)
    adjacent_sources: int = 2         # best N sources whose passages get neighbours
    second_search: bool = True        # (b) one bounded targeted search
    second_search_top_k: int = 5
    # "selected_documents": the targeted search may only add passages of documents already selected (fills a gap in a
    # cited source); "any": may add one new source. Development data: "any" added mostly passages of non-relevant
    # documents, so the default is the narrow scope.
    second_search_scope: str = "selected_documents"
    max_added_passages: int = 4
    max_added_chars: int = 3000
    # topical gate: an added passage must be at least as similar to the question (dense cosine) as the weakest
    # answer-bearing passage, minus this margin. Shape alone is not evidence - a fee table of another procedure has the
    # same "shape" as the answer.
    relevance_margin: float = 0.0
    relevance_floor: float = 0.80     # used when the answer-bearing passages carry no similarity


class EvidenceChecker:
    def __init__(self, store: Store, retrieval: Any, config: EvidenceConfig | None = None):
        self.store = store
        self.retrieval = retrieval
        self.config = config or EvidenceConfig()

    # ---------------------------------------------------------------- check
    @staticmethod
    def check(question: str, sources: list[dict[str, Any]], needs: list[str] | None = None,
              check_sources: int | None = None) -> dict[str, Any]:
        """Which needed information types appear in the ANSWER-BEARING evidence: the passages of the top
        ``check_sources`` sources (retrieval order) plus every passage this layer added. Checking the whole context
        would almost always find *some* number or condition and say nothing about the answer."""
        needs = required_information(question) if needs is None else needs
        kind = quantity_kind(question)
        scope = sources if check_sources is None else sources[:check_sources]
        passages = [p for s in scope for p in s["passages"]] + [
            p for s in sources[len(scope):] for p in s["passages"] if p.get("evidence_added")]
        met = {n: [p.get("chunk_id") for p in passages
                   if has_signal(n, f"{p.get('heading') or ''} {p.get('passage') or ''}", kind)] for n in needs}
        return dict(needs=needs, quantity_kind=kind if "quantity" in needs else None,
                    met=[n for n in needs if met[n]], missing=[n for n in needs if not met[n]],
                    supporting_chunks={n: v[:5] for n, v in met.items() if v})

    @staticmethod
    def conflicts(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Potential conflict: two DIFFERENT documents state figures for the same unit and the figures do not overlap
        at all (document A only says 20 hours, document B only 30 hours). Reported, never resolved."""
        per_doc: dict[str, dict[str, set[str]]] = {}
        for s in sources:
            for p in s["passages"]:
                for num, unit in _CONFLICT_UNIT.findall(p.get("passage") or ""):
                    u = _UNIT_NORMAL.get(unit.lower(), unit.lower())
                    per_doc.setdefault(u, {}).setdefault(str(s["document_id"]), set()).add(num.replace(",", ""))
        out = []
        for unit, docs in per_doc.items():
            ids = sorted(docs)
            pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:] if not (docs[a] & docs[b])]
            if pairs:
                out.append(dict(unit=unit, documents=sorted({d for pr in pairs for d in pr}),
                                values={d: sorted(docs[d])[:6] for d in sorted({d for pr in pairs for d in pr})}))
        return out

    # ---------------------------------------------------------------- complete
    def complete(self, question: str, sources: list[dict[str, Any]], *, max_sources: int | None = None
                 ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        t0 = time.perf_counter()
        cs = self.config.check_sources
        kind = quantity_kind(question)
        first = self.check(question, sources, check_sources=cs)
        report: dict[str, Any] = dict(needs=first["needs"], quantity_kind=first["quantity_kind"],
                                      initially_missing=list(first["missing"]), actions=[],
                                      added_chunks=[])
        if not first["needs"]:
            report.update(status="no_requirement", still_missing=[], latency_ms=0.0, conflicts=self.conflicts(sources))
            return sources, report
        sources = [dict(s, passages=list(s["passages"])) for s in sources]
        seen = {p.get("chunk_id") for s in sources for p in s["passages"]}
        scope_sims = [float(p["similarity"]) for s in sources[:cs] for p in s["passages"] if p.get("similarity") is not None]
        floor = (min(scope_sims) if scope_sims else self.config.relevance_floor) - self.config.relevance_margin
        qvec = self._query_vector(question)
        report["relevance_floor"] = round(floor, 4)
        rejected = 0

        def relevant(p: dict[str, Any]) -> bool:
            nonlocal rejected
            sim = p.get("similarity")
            if sim is None and qvec is not None:
                sim = self._similarity(qvec, p.get("chunk_id"))
            ok = sim is not None and float(sim) >= floor
            rejected += not ok
            return ok
        added_chars = 0
        missing = list(first["missing"])

        def add(src: dict[str, Any], p: dict[str, Any], why: str) -> bool:
            nonlocal added_chars
            size = len(p.get("passage") or "")
            if p.get("chunk_id") in seen or len(report["added_chunks"]) >= self.config.max_added_passages \
                    or added_chars + size > self.config.max_added_chars:
                return False
            src["passages"].append(dict(p, evidence_added=why))
            seen.add(p.get("chunk_id"))
            added_chars += size
            report["added_chunks"].append(dict(chunk_id=p.get("chunk_id"), document_id=src["document_id"], reason=why,
                                               page=p.get("page")))
            return True

        if missing and self.config.adjacent:
            n = 0
            for src in sources[: self.config.adjacent_sources]:
                for p in list(src["passages"])[:2]:
                    for nb in self._neighbours(p):
                        if any(has_signal(m, nb.get("passage") or "", kind) for m in missing) and relevant(nb) \
                                and add(src, nb, "adjacent"):
                            n += 1
            report["actions"].append(dict(action="adjacent", added=n))
            missing = self.check(question, sources, missing, cs)["missing"]
        if missing and self.config.second_search and self.retrieval is not None:
            q = f"{question} {' '.join(_EXPANSION[m] for m in missing)}"
            top_k = self.config.second_search_top_k * (3 if self.config.second_search_scope == "selected_documents" else 1)
            res = self.retrieval.search(q, top_k=min(top_k, 20), max_per_document=3)
            n = 0
            by_doc = {s["document_id"]: s for s in sources}
            for h in res["results"]:
                if not any(has_signal(m, f"{h.get('heading') or ''} {h.get('passage') or ''}", kind) for m in missing) \
                        or not relevant(h):
                    continue
                src = by_doc.get(h["document_id"])
                if src is None and self.config.second_search_scope == "selected_documents":
                    continue
                if src is None:
                    if max_sources is not None and len(sources) >= max_sources + 1:
                        continue                  # at most one extra source document
                    src = dict(document_id=h["document_id"], passages=[])
                    by_doc[h["document_id"]] = src
                    sources.append(src)
                if add(src, h, "second_search"):
                    n += 1
            sources = [s for s in sources if s["passages"]]
            report["actions"].append(dict(action="second_search", added=n))
            missing = self.check(question, sources, missing, cs)["missing"]
        report.update(still_missing=missing, status="sufficient" if not missing else "insufficient",
                      rejected_off_topic=rejected,
                      latency_ms=round((time.perf_counter() - t0) * 1000, 1), conflicts=self.conflicts(sources))
        return sources, report

    def _query_vector(self, question: str) -> list[float] | None:
        emb = getattr(self.retrieval, "embedder", None)
        try:
            return emb.embed_query(question) if emb is not None else None
        except Exception:  # noqa: BLE001 - without a query vector nothing can pass the topical gate
            return None

    def _similarity(self, qvec: list[float], chunk_id: str | None) -> float | None:
        if not chunk_id:
            return None
        rows, _ = self.store.select("document_chunks", Query(eq={"id": chunk_id}, cols="id,embedding"))
        emb = rows[0].get("embedding") if rows else None
        if isinstance(emb, str):                       # PostgREST returns pgvector as text
            emb = [float(x) for x in emb.strip().strip("[]").split(",") if x.strip()]
        if not emb or len(emb) != len(qvec):
            return None
        dot = sum(a * b for a, b in zip(qvec, emb, strict=True))
        na = math.sqrt(sum(a * a for a in qvec)) or 1.0
        nb = math.sqrt(sum(b * b for b in emb)) or 1.0
        return dot / (na * nb)

    def _neighbours(self, p: dict[str, Any]) -> list[dict[str, Any]]:
        """Chunks right before/after a passage in the SAME searchable version (approved, current, valid)."""
        vid, cid = p.get("version_id"), p.get("chunk_id")
        if not vid or not cid:
            return []
        own, _ = self.store.select("document_chunks", Query(eq={"id": cid}, cols="id,chunk_index"))
        if not own:
            return []
        idx = int(own[0]["chunk_index"])
        rows, _ = self.store.select("searchable_chunks", Query(
            eq={"version_id": vid}, in_={"chunk_index": [idx - 1, idx + 1]},
            cols="chunk_id,version_id,chunk_index,heading,content,page_start"))
        out = []
        for r in sorted(rows, key=lambda r: r["chunk_index"]):
            out.append(dict(p, chunk_id=r["chunk_id"], heading=r.get("heading"), passage=r.get("content") or "",
                            page=r.get("page_start"), similarity=None, keyword_rank=None, lexical_coverage=None,
                            best_lexical=0.0, score=None))
        return out

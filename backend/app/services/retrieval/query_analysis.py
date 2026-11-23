"""Query analysis for retrieval: terminology normalization, a small multilingual glossary and lexical scoring.

* Visa / status codes are normalized (``D2``, ``d 2``, ``D-2`` -> ``D-2``; ``F2R`` -> ``F-2-R``) and sent to the
  keyword leg in every spelling documents use (``D-2`` and ``D2``), so a document written "D2 visa extension" is
  found for "D-2". Only the letters D-H are treated as codes (A1-C2 are CEFR language levels).
* Glossary concepts group equivalent terms across the five site languages and Korean source wording (ARC =
  residence card = 외국인등록증 ...). A concept found in the query adds its other surface forms to the keyword leg;
  this is what lets an English "dormitory" question match a Korean "생활관" notice lexically. It is a domain
  glossary (no model, no network) and is deliberately small; extend it in ``CONCEPTS``.
* ``lexical_scores`` weights each query term by its rarity among the retrieved candidates (BM25-style IDF), so a
  broad word that appears in nearly every candidate ("visa") contributes almost nothing, while the rare, specific
  term ("extension", "D-2", "생활관") carries the match.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

CODE_LETTERS = "DEFGH"
# letter, optional separator, 1-2 digits, optional subtype "-<digits>" or "-R"/"R" (a subtype needs the hyphen, so
# "F-2 3 years" stays F-2); never glued to other letters/digits
_CODE = re.compile(rf"(?<![A-Za-z0-9])([{CODE_LETTERS}{CODE_LETTERS.lower()}])[ -]?(\d{{1,2}})"
                   r"(?:-(\d{1,2})(?![A-Za-z0-9])|-?([Rr])(?![A-Za-z0-9]))?(?![A-Za-z0-9])")
_COUNTDOWN_BEFORE = re.compile(r"(마감|접수|신청|deadline|due)\s*[(:]?\s*$", re.I)


def _is_countdown(text: str, m: re.Match[str]) -> bool:
    """'마감 D-7', 'D-3일', 'D-1 day' are deadline countdowns, not the D-7 / D-3 visa codes."""
    if m.group(1).upper() != "D":
        return False
    after = text[m.end(): m.end() + 5]
    return bool(re.match(r"\s?(일|days?\b)", after, re.I) or _COUNTDOWN_BEFORE.search(text[max(0, m.start() - 12): m.start()]))

CONCEPTS: list[tuple[str, tuple[str, ...]]] = [
    ("residence_card", ("arc", "residence card", "resident card", "alien registration", "foreigner registration",
                        "외국인등록증", "외국인등록", "외국인 등록", "등록증", "kartu registrasi orang asing",
                        "kartu izin tinggal", "thẻ cư trú", "thẻ đăng ký người nước ngoài", "外国人登录证",
                        "外国人登记证", "外国人登录", "居留证", "居留卡")),
    ("health_insurance", ("national health insurance", "health insurance", "nhis", "nhi", "국민건강보험", "건강보험",
                          "asuransi kesehatan", "bảo hiểm y tế", "bảo hiểm sức khỏe", "国民健康保险", "健康保险",
                          "医疗保险")),
    ("dormitory", ("dormitory", "dorm", "residence hall", "생활관", "기숙사", "asrama", "ký túc xá", "宿舍")),
    ("part_time_work", ("part-time", "part time", "parttime", "시간제 취업", "시간제취업", "아르바이트", "알바",
                        "paruh waktu", "kerja sambilan", "làm thêm", "việc làm thêm", "打工", "兼职")),
    ("stay_extension", ("extension of stay", "stay extension", "extend", "extension", "체류기간 연장", "체류기간연장",
                        "extending", "extended", "연장", "perpanjang", "perpanjangan", "memperpanjang", "diperpanjang", "gia hạn", "延长", "延期")),
    ("tuition", ("tuition", "등록금", "uang kuliah", "biaya kuliah", "học phí", "学费")),
    ("scholarship", ("scholarship", "장학금", "장학", "beasiswa", "học bổng", "奖学金")),
    ("course_registration", ("course registration", "register for courses", "class registration", "수강신청",
                             "수강 신청", "pendaftaran mata kuliah", "đăng ký môn học", "đăng ký học phần", "选课")),
    ("topik", ("topik", "한국어능력시험", "韩国语能力考试", "韩语能力考试")),
    ("address_change", ("change of address", "address change", "change my address", "체류지 변경", "체류지변경",
                        "전입신고", "주소 변경", "perubahan alamat", "pindah alamat", "đổi địa chỉ",
                        "thay đổi địa chỉ", "地址变更", "变更地址", "住址变更")),
    ("reentry", ("re-entry", "reentry", "re-enter", "재입국", "masuk kembali", "tái nhập cảnh", "再入境")),
    ("hospital", ("hospital", "clinic", "병원", "rumah sakit", "bệnh viện", "医院")),
    ("luggage_storage", ("luggage", "baggage storage", "짐 보관", "짐보관", "penyimpanan barang", "bagasi",
                         "gửi đồ", "giữ đồ", "hành lý", "行李")),
    ("admission", ("admission", "admissions", "모집요강", "입학", "penerimaan mahasiswa", "tuyển sinh", "招生", "入学")),
    ("visa_status_change", ("change of status", "change visa status", "change my visa", "체류자격 변경",
                            "체류자격변경", "perubahan status visa", "đổi loại visa", "chuyển đổi visa", "变更签证",
                            "签证变更")),
    ("per_week", ("per week", "a week", "each week", "weekly", "주당", "일주일에", "일주일 동안", "mỗi tuần", "một tuần",
                  "hàng tuần", "per minggu", "seminggu", "setiap minggu", "每周", "每星期", "一周")),
    ("working_hours", ("working hours", "work hours", "hours of work", "hours can i work", "근무 시간", "근무시간",
                       "근로 시간", "근로시간", "취업 시간", "giờ làm", "số giờ làm", "giờ làm việc", "jam kerja",
                       "工作时间", "打工时间", "工作时长")),
    ("illegal_work", ("illegal employment", "unauthorized work", "불법 취업", "불법취업", "무단 아르바이트",
                      "kerja ilegal", "làm việc bất hợp pháp", "非法就业", "非法打工")),
]

# question words and fillers that carry no topic (in addition to 1-letter tokens)
STOPWORDS = {
    # en
    "the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "at", "by", "is", "are", "am", "be", "was", "how",
    "do", "does", "did", "i", "my", "me", "we", "our", "you", "your", "what", "which", "when", "where", "who", "why",
    "can", "could", "should", "would", "will", "need", "needs", "have", "has", "get", "it", "this", "that", "there",
    "about", "with", "from", "much", "many", "any", "some", "please", "tell", "want", "if", "as", "still",
    # id
    "yang", "dan", "di", "ke", "dari", "untuk", "dengan", "apa", "bagaimana", "saya", "aku", "cara", "bisa", "apakah",
    "kapan", "berapa", "ini", "itu", "ada", "harus", "perlu", "mau", "ingin", "tentang", "jika", "kalau", "dimana",
    # vi
    "tôi", "có", "không", "được", "là", "gì", "nào", "thế", "làm", "để", "cần", "bao", "nhiêu", "của", "và", "cho",
    "khi", "nếu", "ở", "đâu", "những", "các", "một", "mình", "em", "phải", "như",
    # ko (whole tokens only)
    "어떻게", "하나요", "있나요", "무엇", "언제", "어디", "합니까", "해야", "하면", "되나요", "인가요", "뭐예요",
    "알려주세요", "있어요", "해요", "저는", "제가", "그리고",
}
_TOKEN = re.compile(r"[^\W_]+(?:-[^\W_]+)*", re.UNICODE)
_HANGUL = re.compile(r"^[가-힣]+$")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_KO_ENDINGS = ("까지인가요", "인가요", "할까요", "하나요", "되나요", "있나요", "습니까", "합니까", "이에요", "예요", "에요",
               "해요", "세요", "나요", "까요", "죠")
_HAN_ONLY = re.compile(r"^[㐀-鿿]+$")
_KO_PARTICLES = ("에서는", "으로는", "에서", "으로", "에는", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "의",
                 "에", "로", "와", "과", "도", "만")
MAX_KEYWORD_TOKENS = 24


def canonical_code(letter: str, num: str, sub: str | None) -> str:
    return f"{letter.upper()}-{int(num)}" + (f"-{sub.upper()}" if sub else "")


def _canon(m: re.Match[str]) -> str:
    return canonical_code(m.group(1), m.group(2), m.group(3) or m.group(4))


def find_codes(text: str) -> set[str]:
    text = text or ""
    return {_canon(m) for m in _CODE.finditer(text) if not _is_countdown(text, m)}


def normalize_codes(text: str) -> str:
    text = text or ""
    return _CODE.sub(lambda m: m.group(0) if _is_countdown(text, m) else _canon(m), text)


def code_variants(code: str) -> list[str]:
    """Spellings documents use for a code: D-2 -> [D-2, D2]; F-2-R -> [F-2-R, F2R, F-2R]."""
    compact = code.replace("-", "")
    out = [code, compact]
    parts = code.split("-")
    if len(parts) == 3 and parts[2] == "R":        # F-2-R is also written F-2R; D-2-2 has no such spelling
        out.append(f"{parts[0]}-{parts[1]}{parts[2]}")
    return list(dict.fromkeys(out))


def code_matches(asked: set[str], present: set[str]) -> bool:
    """True if a passage code satisfies an asked code (D-2 is satisfied by D-2 or a subtype such as D-2-2)."""
    return any(p == a or p.startswith(a + "-") for a in asked for p in present)


def _form_pattern(form: str) -> re.Pattern[str]:
    f = re.escape(form.lower())
    if _CJK.search(form):
        return re.compile(f)                       # CJK/Hangul: no word boundaries (particles attach)
    if len(form) <= 6 and " " not in form:
        # short words must match whole words ("nhi" must not match Vietnamese "nhiều", "arc" not "archive",
        # "clinic" not "clinical"); a plural -s/-es is allowed
        return re.compile(rf"(?<![a-z0-9]){f}(?:e?s)?(?![a-z0-9À-ɏḀ-ỿ])")
    return re.compile(rf"(?<![a-z0-9]){f}")         # longer words: word-start match ("hospital" -> "hospitals")


@dataclass
class Term:
    key: str
    forms: tuple[str, ...]
    patterns: list[re.Pattern[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.patterns = [_form_pattern(f) for f in self.forms if f]

    def found_in(self, text_lower: str) -> bool:
        return any(p.search(text_lower) for p in self.patterns)


@dataclass
class QueryAnalysis:
    normalized: str
    codes: set[str]
    terms: list[Term]
    keyword_tokens: list[str]      # sent to the keyword leg (original terms first, then glossary expansions)
    exact_terms: list[str]         # identifier spellings matched on word boundaries
    concepts: list[str]


def analyze(query: str) -> QueryAnalysis:
    normalized = normalize_codes(query)
    low = normalized.lower()
    codes = find_codes(normalized)
    concepts = [(key, forms) for key, forms in CONCEPTS if any(_form_pattern(f).search(low) for f in forms)]
    concept_forms = {f.lower() for _k, forms in concepts for f in forms}
    # words that are part of a glossary phrase found in the query ("đổi địa chỉ") belong to that concept
    phrase_words = {w for _k, forms in concepts for f in forms if " " in f and _form_pattern(f).search(low)
                    for w in f.lower().split()}

    terms: list[Term] = []
    seen: set[str] = set()
    for key, forms in concepts:
        terms.append(Term(f"concept:{key}", tuple(dict.fromkeys(f.lower() for f in forms))))
    for code in sorted(codes):
        terms.append(Term(f"code:{code}", tuple(v.lower() for v in code_variants(code))))
        seen.add(code.lower())
    for raw in _TOKEN.findall(low):
        if _HANGUL.match(raw):           # strip a Korean question ending ("언제까지인가요" -> "언제까지")
            for e in _KO_ENDINGS:
                if raw.endswith(e) and len(raw) > len(e):
                    raw = raw[: -len(e)]
                    break
        if _HAN_ONLY.match(raw) and len(raw) > 4:
            continue                     # an unsegmented Chinese sentence cannot be matched as a keyword
        if raw in STOPWORDS or raw in seen or raw in concept_forms or raw in phrase_words:
            continue
        if any(raw.upper() == c or raw.upper().replace("-", "") == c.replace("-", "") for c in codes):
            continue
        if len(raw) < 2 and not _CJK.search(raw):
            continue
        forms = [raw]
        if _HANGUL.match(raw) and len(raw) >= 3:
            for p in _KO_PARTICLES:
                if raw.endswith(p) and len(raw) - len(p) >= 2:
                    forms.append(raw[: -len(p)])
                    break
        if any(f in STOPWORDS for f in forms[1:]):
            continue
        if any(f in concept_forms for f in forms):   # e.g. "생활관에" -> "생활관" is already a concept
            continue
        seen.add(raw)
        terms.append(Term(f"tok:{raw}", tuple(forms)))

    keyword: list[str] = []
    for t in terms:                       # the query's own words first ...
        if t.key.startswith("tok:"):
            keyword.extend(t.forms)
    for t in terms:                       # ... then the matched concept's wording in the query ...
        if t.key.startswith("concept:"):
            keyword.extend(f for f in t.forms if _form_pattern(f).search(low))
    for t in terms:                       # ... then its equivalents in other languages
        if t.key.startswith("concept:"):
            keyword.extend(t.forms)
    # very short Latin forms (arc, nhi) would substring-match everything in SQL ILIKE; acronyms go via exact terms
    keyword = [k for k in dict.fromkeys(keyword) if k and (len(k) > 3 or _CJK.search(k))][:MAX_KEYWORD_TOKENS]
    exact = [v for c in sorted(codes) for v in code_variants(c)]
    exact += [m.group(0).upper() for m in re.finditer(r"(?<![A-Za-z])(TOPIK|NHIS|NHI|ARC|HiKorea)(?![A-Za-z])", normalized,
                                                     re.I)]
    exact = [e for e in dict.fromkeys(exact) if re.fullmatch(r"[A-Za-z0-9]+([ -][A-Za-z0-9]+)*", e)][:8]
    return QueryAnalysis(normalized=normalized, codes=codes, terms=terms, keyword_tokens=keyword, exact_terms=exact,
                         concepts=[k for k, _ in concepts])


def lexical_scores(qa: QueryAnalysis, texts: dict[str, str]) -> dict[str, tuple[float, list[str]]]:
    """Rarity-weighted coverage of the query terms for each candidate text: {id: (score 0..1, matched term keys)}.

    IDF is computed over the candidate set itself (the only collection statistics available without a schema
    change); with very few candidates every term gets a similar weight, which degrades gracefully to plain coverage."""
    if not qa.terms or not texts:
        return {cid: (0.0, []) for cid in texts}
    lowered = {cid: t.lower() for cid, t in texts.items()}
    hits = {cid: [term for term in qa.terms if term.found_in(lt)] for cid, lt in lowered.items()}
    n = len(texts)
    df = {term.key: sum(1 for hs in hits.values() if term in hs) for term in qa.terms}

    def idf(key: str) -> float:
        return math.log(1 + (n - df[key] + 0.5) / (df[key] + 0.5))

    out: dict[str, tuple[float, list[str]]] = {}
    for cid, hs in hits.items():
        # script-aware coverage: a plain query word written in a script the passage does not use (an English word
        # against a Korean notice) could never match, so it does not count against that passage. Glossary concepts
        # and codes always count - they carry forms in every script.
        script = _script(lowered[cid])
        counted = [t for t in qa.terms if not t.key.startswith("tok:") or _term_script(t) in (script, "mixed")
                   or script == "mixed"]
        total = sum(idf(t.key) for t in counted) or 1.0
        full = sum(idf(t.key) for t in qa.terms) or 1.0
        checkable = total / full            # share of the query (by weight) this passage could have matched at all
        coverage = min(1.0, sum(idf(t.key) for t in hs) / total)
        # less checkable -> less confident: a single concept match on a document in another script is a candidate,
        # not proof (keeps a long Korean guide that mentions "TOPIK" once from outranking the TOPIK guide)
        out[cid] = (coverage * (0.5 + 0.5 * checkable), [t.key for t in hs])
    return out


def _script(text: str) -> str:
    """Dominant script of a text: 'hangul', 'han', 'latin' or 'mixed'."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "mixed"
    hangul = sum(1 for c in letters if "가" <= c <= "힣") / len(letters)
    han = sum(1 for c in letters if "一" <= c <= "鿿") / len(letters)
    if hangul >= 0.6:
        return "hangul"
    if han >= 0.6:
        return "han"
    if hangul + han <= 0.1:
        return "latin"
    return "mixed"


def _term_script(term: Term) -> str:
    return _script(" ".join(term.forms))


def token_set(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))

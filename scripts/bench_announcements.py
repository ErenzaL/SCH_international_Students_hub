"""Translation benchmark on real public SCH announcements (Korean -> en, id, vi, zh-CN) with the GPU worker's own code.

    cd backend
    .venv/bin/python ../scripts/build_announcement_corpus.py                 # once: the texts (never committed)
    .venv/bin/python ../scripts/bench_announcements.py --name current
    .venv/bin/python ../scripts/bench_announcements.py --name current --rescore   # score the cached outputs again

Outputs stay in backend/.eval-cache (git-ignored). Only numbers go to scripts/benchmarks/results/.
The facts are extracted by this script, NOT by the production checks, so it can tell correct drafts that the checks
flag from drafts that really lost something. Sampling is seeded (temperature as in production).

Measured per draft: dates, times, money, links (URL / domain / mail / phone), terminology and proper nouns (glossary),
structure (missing lines), unsupported additions (numbers, links), leftover Korean / stray Chinese, time, tokens.
Not measured: fluency and wrong words outside the glossary. The glossary was written by an AI assistant and needs
confirmation by native speakers.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import Settings  # noqa: E402
from app.gpu_worker.generate import generate  # noqa: E402
from app.services.llm.base import LLMError  # noqa: E402
from app.services.llm.ollama import OllamaProvider  # noqa: E402
from app.services.translation import quality  # noqa: E402

CACHE = ROOT / "backend" / ".eval-cache"
RESULTS = ROOT / "scripts" / "benchmarks" / "results"
LANGS = ("en", "id", "vi", "zh-CN")
MONTHS = {
    "en": "january february march april may june july august september october november december".split(),
    "id": "januari februari maret april mei juni juli agustus september oktober november desember".split(),
}
# Korean term -> accepted translations (regular expressions, case-insensitive) per language
GLOSSARY: dict[str, dict[str, str]] = {
    "생활관|기숙사": dict(en=r"dorm|residence hall|living hall|student housing|residen", id=r"asrama", vi=r"ký túc xá|ktx", zh=r"宿舍|生活馆|公寓"),
    "외국인등록증": dict(en=r"(alien|foreign\w*|residence)( resident)?( registration)? card|registration card|\barc\b", id=r"kartu (registrasi|pendaftaran|identitas|tanda)\w*( penduduk| orang)? ?(orang )?asing|kartu izin tinggal|kartu registrasi", vi=r"thẻ (đăng ký|cư trú|chứng minh)[^.\n]{0,12}(người nước ngoài|ngoại kiều)?|thẻ ngoại kiều", zh=r"外国人(登录|登陆|登记|居留)证|外籍人士?登"),
    "출입국": dict(en=r"immigration", id=r"imigrasi", vi=r"xuất nhập cảnh|nhập cư|di trú", zh=r"出入境|入境管理|移民"),
    "시간제취업": dict(en=r"part[- ]time (work|employment|job)", id=r"paruh waktu", vi=r"bán thời gian|làm thêm", zh=r"(时间制|小时制|非全日制|兼职|计时)[^。\n]{0,4}(就业|工作|打工|就職|职)?"),
    "불법취업|불법 취업": dict(en=r"illegal (employment|work)|unauthorized (employment|work)", id=r"(kerja|pekerjaan|bekerja|ketenagakerjaan)[^.\n]{0,12}ilegal", vi=r"(làm việc|lao động|việc làm|tuyển dụng)[^.\n]{0,15}(bất hợp pháp|trái phép)", zh=r"非法(就业|打工|务工|工作)"),
    "강제퇴거": dict(en=r"deport|forced (departure|removal|exit)|compulsory", id=r"deportasi|pengusiran|diusir", vi=r"trục xuất", zh=r"强制(出境|离境|驱逐|遣返|退去|退出)|驱逐"),
    "범칙금": dict(en=r"fine|penalt", id=r"denda", vi=r"phạt", zh=r"罚款|罚金|违约金|犯则金"),
    "벌점": dict(en=r"(demerit|penalty) ?point|demerit|penalt", id=r"poin (penalti|hukuman|pelanggaran|minus|denda|negatif)|penalti", vi=r"điểm (phạt|trừ)|phạt|trừ", zh=r"(罚|扣|违纪|处罚)(分|点)|扣\d+分|罚\d+分|分数处罚"),
    "보증금": dict(en=r"deposit", id=r"deposit|jaminan", vi=r"(tiền|phí)? ?(đặt cọc|cọc|bảo chứng|thế chấp|ký quỹ|bảo đảm|đảm bảo)", zh=r"保证金|押金"),
    "수강신청|수강 신청": dict(en=r"course registration|(course|class) (enrol|regist|applic)|regist\w+ for (the )?course", id=r"(pendaftaran|registrasi|daftar|pengambilan)[^.\n]{0,20}(kuliah|kelas|kursus|mata)", vi=r"đăng ký[^.\n]{0,15}(học|môn|khóa|tín)", zh=r"选课|(课程|修课|听课)(申请|注册|报名)|申请(课程|选课)"),
    "계절학기": dict(en=r"(seasonal|winter|summer|intersession)[- ]?(semester|session|term)?", id=r"semester (musim|pendek|antara)|musim dingin", vi=r"học kỳ (mùa|phụ|hè|đông)|mùa đông", zh=r"(季节|冬季|寒假|夏季|小)学期"),
    "전과": dict(en=r"(change|transfer)[^.\n]{0,20}(major|department)|department (change|transfer)|major (change|transfer)|transfer", id=r"(pindah|perpindahan|pergantian|transfer|ganti|alih)[^.\n]{0,12}(jurusan|program|departemen|fakultas)?", vi=r"chuyển (ngành|khoa|chuyên ngành)", zh=r"转(专业|系|学科|科)"),
    "휴학": dict(en=r"leave of absence|on leave", id=r"cuti", vi=r"bảo lưu|nghỉ học|tạm nghỉ|nghỉ phép", zh=r"休学"),
    "기말평가|기말고사": dict(en=r"final (exam|evaluation|assessment)|end[- ]of[- ](term|semester)", id=r"(ujian|evaluasi|penilaian)[^.\n]{0,8}akhir", vi=r"cuối kỳ|kết thúc học kỳ|thi cuối", zh=r"期末(考试|评价|考核|评估|考)"),
    "중간평가": dict(en=r"mid[- ]?term", id=r"(ujian|evaluasi|penilaian)?[^.\n]{0,8}tengah", vi=r"giữa kỳ", zh=r"期中"),
    "학자금": dict(en=r"tuition|student (aid|loan|fund)|education\w* (fund|fee|expens)|school (fee|expens)|scholarship|financial aid", id=r"(biaya|dana|uang|bantuan) (kuliah|pendidikan|sekolah|studi)|beasiswa", vi=r"học phí|tài chính|học bổng|tiền học", zh=r"学费|学资金|助学|奖学金|学业资助"),
    "건강검진": dict(en=r"(health|medical) (check|exam|screen)|physical exam|check-?up", id=r"(pemeriksaan|cek|tes) (kesehatan|medis)", vi=r"(khám|kiểm tra) sức khỏe", zh=r"(健康|身体)(检查|体检)|体检|健康检"),
    "결핵": dict(en=r"tubercul|\btb\b", id=r"tuberkul|\btbc?\b", vi=r"lao\b", zh=r"结核"),
    "가상계좌": dict(en=r"virtual (bank )?account", id=r"(rekening|akun) virtual|virtual account", vi=r"tài khoản ảo", zh=r"虚拟(账户|帐户|账号|帐号)"),
    "셔틀버스": dict(en=r"shuttle", id=r"shuttle|antar[- ]jemput", vi=r"(xe )?(đưa đón|buýt|bus|shuttle|trung chuyển)", zh=r"班车|穿梭|校车|接驳"),
    "소방|화재대피": dict(en=r"fire", id=r"kebakaran", vi=r"cháy|hỏa hoạn", zh=r"火|消防"),
    "지식재산권": dict(en=r"intellectual property", id=r"kekayaan intelektual|hak cipta", vi=r"sở hữu trí tuệ", zh=r"知识产权"),
    "여권": dict(en=r"passport", id=r"paspor", vi=r"hộ chiếu", zh=r"护照"),
    "휴무": dict(en=r"holiday|day off|closed|clos", id=r"libur|tutup|cuti", vi=r"nghỉ|lễ", zh=r"休|假|放假"),
    "한국어능력시험|TOPIK": dict(en=r"topik", id=r"topik", vi=r"topik", zh=r"topik"),
}
# proper nouns: Latin transliteration, an established name, or the Korean name kept as it is
NAMES: dict[str, dict[str, str]] = {
    "순천향": dict(en=r"soonchunhyang|순천향|\bsch\b", id=r"soonchunhyang|순천향|\bsch\b", vi=r"soonchunhyang|순천향|\bsch\b", zh=r"顺天乡|順天鄉|순천향|soonchunhyang|\bsch\b"),
    "글로벌빌리지": dict(en=r"global village|글로벌빌리지", id=r"global village|desa global|글로벌빌리지", vi=r"global village|làng toàn cầu|글로벌빌리지", zh=r"global village|全球村|国际村|地球村|글로벌빌리지"),
    "학성사": dict(en=r"hak ?-?s[eu]o?ng|학성사", id=r"hak ?-?s[eu]o?ng|학성사", vi=r"hak ?-?s[eu]o?ng|học (thành|tinh|sinh) xá|학성사", zh=r"学(成|城|星|诚|晟|圣)(舍|社|寺|司|馆)|학성사|hak ?-?s[eu]o?ng"),
    "향설": dict(en=r"hyang ?-?s(eo|u)l|향설", id=r"hyang ?-?s(eo|u)l|향설", vi=r"hyang ?-?s(eo|u)l|향설", zh=r"香雪|乡雪|享雪|향설|hyang ?-?s(eo|u)l"),
    "국제교육교류처": dict(en=r"(international|global) education[^.\n]{0,14}(exchange|office)|국제교육교류처|office of (international|global)|international (exchange|education)", id=r"pertukaran[^.\n]{0,14}internasional|(pendidikan|kantor)[^.\n]{0,25}internasional|국제교육교류처|internasional", vi=r"(giáo dục|giao lưu|trao đổi)[^.\n]{0,20}quốc tế|quốc tế|국제교육교류처", zh=r"国际教育(交流)?(处|部|中心|办|院|所)|국제교육교류처|国际教育交流"),
    "유학생지원센터": dict(en=r"(international|foreign) student[s']* (support|service)\w* (center|centre)|유학생지원센터|student support center", id=r"pusat (dukungan|layanan|bantuan)[^.\n]{0,25}(internasional|asing)|유학생지원센터|pusat", vi=r"trung tâm hỗ trợ", zh=r"(留学生|国际学生)(支援|支持|服务)中心|유학생지원센터"),
    "신창역": dict(en=r"sin-?chang|신창", id=r"sin-?chang|신창", vi=r"sin-?chang|신창|tân xương", zh=r"新昌|新仓|신창|sinchang"),
    "남서울대": dict(en=r"namseoul|nam ?seoul|\bnsu\b", id=r"namseoul|nam ?seoul|\bnsu\b", vi=r"namseoul|nam ?seoul|\bnsu\b", zh=r"南首尔|南汉城|\bnsu\b"),
    "국기원": dict(en=r"kukkiwon|gukgiwon|국기원", id=r"kukkiwon|gukgiwon|국기원", vi=r"kukkiwon|gukgiwon|국기원|quốc kỹ viện", zh=r"国技院|국기원|kukkiwon"),
    "충청남도": dict(en=r"chung-?cheong-?nam|chungnam|south chungcheong|충청남도", id=r"chung-?cheong-?nam|chungnam|chungcheong selatan|충청남도", vi=r"chung-?cheong-?nam|chungnam|chungcheong nam|nam chungcheong|충청남도", zh=r"忠清南道|忠南"),
    "한국장학재단": dict(en=r"korea(n)? (student aid|scholarship) foundation|kosaf|한국장학재단", id=r"(yayasan|korea)[^.\n]{0,25}(beasiswa|student aid)[^.\n]{0,15}(korea)?|kosaf|한국장학재단", vi=r"quỹ[^.\n]{0,15}học bổng[^.\n]{0,15}hàn quốc|học bổng hàn quốc|kosaf|한국장학재단", zh=r"韩国奖学(财团|基金)|韩国奖学金(财团|基金)|kosaf"),
    "서울시립미술관": dict(en=r"seoul (museum of art|municipal (museum|art)|metropolitan (museum|art)|city (museum|art))|sema", id=r"(museum|galeri) seni[^.\n]{0,15}seoul|seoul museum|sema", vi=r"bảo tàng (mỹ thuật|nghệ thuật)[^.\n]{0,15}seoul|sema", zh=r"首尔(市立)?美术馆|sema"),
}


# ------------------------------------------------------------------------------- facts
URL = re.compile(r"https?://[\x21-\x7e]+?(?=[)\]>\"'.,;:]*(?:\s|$|[^\x21-\x7e]))")
DOMAIN = re.compile(r"(?<![@\w.])(?:[a-z0-9-]+\.)+(?:kr|com|org|net)(?![\w@])", re.I)
MAIL = re.compile(r"[A-Za-z0-9._+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
PHONE = re.compile(r"(?<!\d)0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}(?!\d)")


def clean(text: str) -> str:
    text = re.sub(r"\[(https?://[^\]\s]+)\]\((https?://[^)\s]+)\)", r"\2", text)       # [url](url)
    return re.sub(r"\\([~_\[\]*])", r"\1", text)


def without_links(text: str) -> str:
    return PHONE.sub(" ", MAIL.sub(" ", re.sub(r"https?://[\x21-\x7e]+", " ", text)))


def ok_date(m: int, d: int) -> bool:
    return 1 <= m <= 12 and 1 <= d <= 31


def ko_dates(text: str) -> set[tuple[int, int]]:
    t = without_links(clean(text))
    out = set()
    for rx in (r"20\d\d\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})", r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일",
               r"(?<![\d.,])(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*\([월화수목금토일]\)", r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])"):
        for m in re.finditer(rx, t):
            if ok_date(int(m[1]), int(m[2])):
                out.add((int(m[1]), int(m[2])))
    return out


def dates(text: str, lang: str) -> set[tuple[int, int]]:
    t = without_links(clean(text)).lower()
    out: set[tuple[int, int]] = set()

    def add(m: str | int, d: str | int) -> None:
        if ok_date(int(m), int(d)):
            out.add((int(m), int(d)))

    for m in re.finditer(r"20\d\d\s*[.\-/年]\s*(\d{1,2})\s*[.\-/月]\s*(\d{1,2})", t):
        add(m[1], m[2])
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[./-]\s*(\d{1,2})(?:\s*[./-]\s*20\d\d)?(?!\d)", t):   # 11/12, 12.11, d/m/y
        add(m[1], m[2])
        add(m[2], m[1])
    for m in re.finditer(r"(\d{1,2})\s*月\s*(\d{1,2})", t):
        add(m[1], m[2])
    for m in re.finditer(r"(\d{1,2})\s*(?:tháng|/)\s*(\d{1,2})", t):
        add(m[2], m[1])
    for i, name in enumerate(MONTHS.get(lang, []), 1):
        s = name if len(name) <= 4 else f"{name[:3]}(?:{name[3:]}|\\.|t\\.)?"
        for m in re.finditer(rf"\b{s}\s*\.?\s*(\d{{1,2}})(?:st|nd|rd|th)?\b(?!:)(?:\s*(?:-|–|to|hingga|sampai|and|dan)\s*(\d{{1,2}})\b(?!:))?", t):
            add(i, m[1])
            if m[2]:
                add(i, m[2])
        for m in re.finditer(rf"(?:(\d{{1,2}})\s*(?:-|–|to|hingga|sampai|and|dan)\s*)?\b(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?{s}\b", t):
            add(i, m[2])
            if m[1]:
                add(i, m[1])
    return out


def ko_money(text: str) -> set[int]:
    out = set()
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(천만|백만|십만|만|천|억)?\s*원", clean(text)):
        v = float(m[1].replace(",", "")) * {None: 1, "천": 1e3, "만": 1e4, "십만": 1e5, "백만": 1e6, "천만": 1e7, "억": 1e8}[m[2]]
        if v >= 100:
            out.add(int(v))
    return out


def amounts(text: str) -> set[int]:
    out: set[int] = set()
    unit = {"thousand": 1e3, "million": 1e6, "ribu": 1e3, "juta": 1e6, "nghìn": 1e3, "ngàn": 1e3, "triệu": 1e6, "k": 1e3,
            "千": 1e3, "万": 1e4, "百万": 1e6, "千万": 1e7, "vạn": 1e4, "만": 1e4, "천": 1e3, "천만": 1e7, "": 1}
    for m in re.finditer(r"(\d[\d.,]*)\s*(thousand|million|ribu|juta|nghìn|ngàn|triệu|vạn|千万|百万|万|千|천만|만|천)?", clean(text).lower()):
        raw, u = m[1].rstrip(".,"), m[2] or ""
        for v in {re.sub(r"[.,]", "", raw), re.sub(r",", ".", raw) if re.fullmatch(r"\d+[.,]\d{1,2}", raw) else ""}:
            try:
                out.add(int(round(float(v) * unit[u])))
            except ValueError:
                pass
    return out


def times(text: str) -> set[str]:
    return {f"{int(h):02d}:{m}" for h, m in re.findall(r"(?<!\d)(\d{1,2})\s*:\s*([0-5]\d)(?!\d)", clean(text)) if int(h) <= 24}


def target_times(text: str) -> set[str]:
    out = set(times(text))
    t = clean(text).lower()
    for h, m, ap in re.findall(r"(?<!\d)(\d{1,2})(?:[:.]([0-5]\d))?\s*([ap])\.?m", t):
        hh = int(h) % 12 + (12 if ap == "p" else 0)
        out |= {f"{hh:02d}:{m or '00'}", f"{24 if hh == 0 else hh:02d}:{m or '00'}"}
    for h, m in re.findall(r"(?<!\d)(\d{1,2})[.h]([0-5]\d)(?!\d)", t):
        out.add(f"{int(h):02d}:{m}")
    for h, m in re.findall(r"(?<!\d)(\d{1,2})\s*[时時点]\s*(\d{2})\s*分", t):
        out.add(f"{int(h):02d}:{m}")
    for h, m in re.findall(r"(?<!\d)(\d{1,2})\s*(?:giờ|点|时|時|h\b)\s*(\d{2})?", t):
        out.add(f"{int(h):02d}:{m or '00'}")
    for _w, h in re.findall(r"(下午|晚上)\s*(\d{1,2})", t):
        out.add(f"{int(h) + (12 if int(h) < 12 else 0):02d}:00")
    return out


def links(text: str) -> set[str]:
    t = clean(text)
    out = {m.group(0).rstrip("/").lower() for m in URL.finditer(t)}
    rest = re.sub(r"https?://[\x21-\x7e]+", " ", t)
    out |= {m.lower() for m in MAIL.findall(rest)}
    out |= {m.lower() for m in DOMAIN.findall(MAIL.sub(" ", rest))}
    return out | {re.sub(r"\D", "", p) for p in PHONE.findall(rest)}


WEEK = {"en": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "id": ["senin", "selasa", "rabu", "kamis", "jum", "sabtu", "minggu"],
        "vi": ["hai", "ba", "tư", "năm", "sáu", "bảy", "nhật"], "zh-CN": ["一", "二", "三", "四", "五", "六", "日天"]}


def weekdays(src: str, out: str, lang: str) -> list[int]:
    """[right, wrong]: dates that carry a weekday in the source, compared with the weekday next to them in the draft."""
    want = {}
    for m in re.finditer(r"(\d{1,2})\s*[.월/]\s*(\d{1,2})\s*[.일]?\s*\(([월화수목금토일])\)", clean(src)):
        if ok_date(int(m[1]), int(m[2])):
            want[int(m[1]), int(m[2])] = "월화수목금토일".index(m[3])
    right = wrong = 0
    names = WEEK[lang]
    if lang == "vi":
        rx = r"(?:thứ\s*)?(hai|ba|tư|năm|sáu|bảy|chủ nhật|nhật|[2-7])"
    elif lang == "zh-CN":
        rx = r"(?:周|星期|礼拜)\s*([一二三四五六日天])"
    else:
        rx = "(" + "|".join(names) + r")\w*"
    for m in re.finditer(r"([^\n()（）]{0,28})[(（]\s*" + rx + r"\s*[)）]", clean(out).lower()):
        found = sorted(dates(m[1], lang), key=lambda d: 0)
        hit = [d for d in found if d in want]
        if not hit:
            continue
        w = m[2]
        if lang == "vi":
            idx = int(w) - 2 if w.isdigit() else 6 if "nhật" in w else names.index(w)
        else:
            idx = next(i for i, n in enumerate(names) if w in n or n in w)
        if any(want[d] == idx for d in hit):
            right += 1
        else:
            wrong += 1
    return [right, wrong]


ITEM = re.compile(r"^\s*(?:#{1,4}\s|\*{1,2}\S|>|[-*•■▣▶▸○◦∘ㅇ※·⇓|①-⑳Ⅰ-Ⅹ]|\d{1,2}\s*[.)]|[가-하A-Za-z]\s*[.)])", re.M)
LEAK = re.compile(r"source_?text|copied? exactly|exactly as written|D-4-1|F-2-7|直接翻译|不会添加|Output only|do not add|jangan menambah|không thêm, bớt|"
                  r"here is the translation|以下是翻译|translated text", re.I)


def score(src: dict, out: dict, lang: str) -> dict:  # type: ignore[type-arg]
    s, t = f"{src['title']}\n{src['text']}", f"{out['title']}\n{out['body']}"
    z = "zh" if lang == "zh-CN" else lang
    r: dict = {}
    sd, td = ko_dates(s), dates(t, lang)
    r["dates"] = [len(sd & td), len(sd)]
    r["dates_lost"] = sorted(f"{m}-{d}" for m, d in sd - td)
    sm = ko_money(s)
    r["money"] = [len(sm & amounts(t)), len(sm)]
    r["money_lost"] = sorted(sm - amounts(t))
    st = times(s)
    r["times"] = [len(st & target_times(t)), len(st)]
    sl, tl = links(s), links(t)
    flat = re.sub(r"\s", "", clean(t).lower())
    kept = {x for x in sl if x in tl or x in flat or (x.isdigit() and x in re.sub(r"\D", "", t))}
    r["links"] = [len(kept), len(sl)]
    r["links_added"] = sorted(x for x in tl if not x.isdigit() and x not in re.sub(r"\s", "", clean(s).lower()))
    for key, table in (("terms", GLOSSARY), ("names", NAMES)):
        used = [k for k in table if re.search(k, s)]
        bad = [k for k in used if not re.search(table[k][z], t, re.I)]
        r[key], r[f"{key}_wrong"] = [len(used) - len(bad), len(used)], bad
    lines = lambda x: len([ln for ln in x.splitlines() if ln.strip()])  # noqa: E731
    r["lines"] = [lines(out["body"]), lines(src["text"])]
    si, ti = len(ITEM.findall(src["text"])), len(ITEM.findall(out["body"]))
    r["items"] = [ti, si]
    r["missing_lines"] = ti < si - 1 or len(t) < 0.45 * len(s) * (1 if z == "zh" else 2.2 if z != "en" else 2.0)
    r["weekdays"] = weekdays(s, t, lang)
    r["leak"] = bool(LEAK.search(t) and not LEAK.search(s))
    known = {re.sub(r"\D", "", n) for n in re.findall(r"\d[\d.,]*", clean(s))} | {str(int(x)) for x in re.findall(r"\d+", clean(s))}
    known |= {f"{d[1]:02d}{d[0]:02d}{y}" for d in sd for y in ("", "2026", "2027")} | {f"{d[1]}{d[0]}{y}" for d in sd for y in ("", "2026", "2027")}
    known |= {re.sub(":", "", x) for x in st} | {f"{int(h):02d}00" for h in re.findall(r"(\d{1,2})\s*시", s)} | {f"{int(h)}00" for h in re.findall(r"(\d{1,2})\s*시", s)}
    known |= {f"{int(h) + 12}00" for h in re.findall(r"(?:오후\s*|~)(\d)\s*시", s)}
    known |= {n for d in sd for n in (str(d[0]), str(d[1]), f"{d[0]:02d}", f"{d[1]:02d}")} | {str(v) for v in sm}
    known |= {str(v) for v in (int(v / 1e4) for v in sm)} | {str(v) for v in (int(v / 1e6) for v in sm)}
    known |= {str(int(x[:2]) % 12 or 12) for x in st} | {str(int(h) + 12) for h in re.findall(r"오후\s*(\d{1,2})", s)}
    new = {re.sub(r"[.,]", "", n) for n in re.findall(r"\d[\d.,]*", without_links(clean(t)))}
    r["numbers_added"] = sorted(n for n in new if len(n.lstrip("0")) >= 2 and n not in known and n.lstrip("0") not in known
                                and n not in re.sub(r"\D", "", s))
    body = without_links(t)
    letters = len(re.findall(r"[^\W\d_]", body)) or 1
    r["hangul_share"] = round(len(re.findall(r"[가-힣]", body)) / letters, 3)
    r["stray_han"] = 0 if z == "zh" else len(set(re.findall(r"[一-鿿]", t)) - set(re.findall(r"[一-鿿]", s)))
    r["latin_words_zh"] = len(re.findall(r"\b[a-z]{4,}\b", re.sub(r"[a-z0-9.-]+\.[a-z]{2,}", " ", without_links(t)))) if z == "zh" else 0
    sl_, tl_ = len(s), len(t)
    r["length_ratio"] = round(tl_ / sl_, 2)
    # a real loss of information, independent of the production checks
    r["fact_error"] = bool(r["dates_lost"] or r["money_lost"] or r["links"][0] < r["links"][1] or r["links_added"]
                           or r["numbers_added"] or r["missing_lines"] or r["times"][0] < r["times"][1])
    r["fact_error"] = r["fact_error"] or r["weekdays"][1] > 0 or r["leak"]
    # an untranslated title counts too (N22 in the first run)
    r["language_error"] = r["hangul_share"] > 0.05 or r["stray_han"] > 0 or len(re.findall(r"[가-힣]", out["title"])) > 6
    return r


class Gpu(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.rows: list[tuple[float, float, float]] = []
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.wait(1.0):
            try:
                o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu,power.draw",
                                    "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
                self.rows.append(tuple(float(x) for x in o.strip().splitlines()[0].split(",")))  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                return

    def summary(self) -> dict:  # type: ignore[type-arg]
        if not self.rows:
            return {}
        mem, util, power = zip(*self.rows, strict=True)
        return dict(memory_mib_peak=max(mem), memory_mib_median=statistics.median(mem), utilization_median=statistics.median(util),
                    power_w_median=statistics.median(power), power_w_peak=max(power), samples=len(mem))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--langs", default=",".join(LANGS))
    ap.add_argument("--set", default="", help="corpus set, e.g. heldout")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--checks", choices=["local", "shared"], default="local", help="shared: the checks every provider gets")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-repair", action="store_true")
    ap.add_argument("--rescore", action="store_true")
    ap.add_argument("--style", choices=["auto", "shared", "native"], default="auto",
                    help="prompt style of the GPU worker (native = TranslateGemma's own prompt, no hints or repairs)")
    ap.add_argument("--model", default="", help="Ollama model (default: OLLAMA_MODEL / the worker's default)")
    a = ap.parse_args()
    corpus = json.loads((CACHE / f"announcement_corpus{'_' + a.set if a.set else ''}.json").read_text())[: a.limit or None]
    path = CACHE / f"announcement_outputs_{a.name}.json"
    s = Settings(_env_file=None)
    gpu_info: dict = {}  # type: ignore[type-arg]
    if a.rescore:
        saved = json.loads(path.read_text())
        rows, gpu_info = saved["rows"], saved["gpu"]
    else:
        llm = OllamaProvider(a.model or s.ollama_model, base_url=s.ollama_base_url, num_ctx=s.ollama_num_ctx,
                             temperature=s.ollama_temperature, seed=a.seed, job_timeout=180, request_timeout=180)
        llm.complete("Reply OK.", "OK?", max_tokens=16)
        gpu = Gpu()
        gpu.start()
        rows = []
        for src in corpus:
            for lang in a.langs.split(","):
                job = dict(mode="translate", source_language="ko", target_language=lang, title=src["title"], body=src["text"],
                           chunk_chars=s.gpu_worker_chunk_chars, max_source_chars=s.gpu_worker_max_source_chars)
                t0 = time.perf_counter()
                try:
                    out, model = generate(llm, job, threading.Event(), repair=not a.no_repair, style=a.style)
                except LLMError as exc:
                    rows.append(dict(id=src["id"], lang=lang, error=exc.code))
                    continue
                rows.append(dict(id=src["id"], lang=lang, title=out["title"], body=out["body"], seconds=round(time.perf_counter() - t0, 2),
                                 calls=model.calls, repairs=model.repairs, input_tokens=model.input_tokens,
                                 output_tokens=model.output_tokens, parts=out["chunks"]))
                print(f"{src['id']} {lang:6} {rows[-1]['seconds']:6.1f}s", flush=True)
        gpu.stop.set()
        gpu_info = gpu.summary()
        llm.close()
        path.write_text(json.dumps(dict(rows=rows, gpu=gpu_info), ensure_ascii=False, indent=1))
    by_id = {c["id"]: c for c in corpus}
    good = [r for r in rows if "error" not in r and r["id"] in by_id]
    for r in good:
        c = by_id[r["id"]]
        o, t = f"{c['title']}\n{c['text']}", f"{r['title']}\n{r['body']}"
        r["score"] = score(c, r, r["lang"])
        r["warnings"] = (quality.validate_translation(o, t, "ko", r["lang"]) + quality.local_model_warnings(o, t, "ko", r["lang"])
                         if a.checks == "shared" else quality.local_translation_warnings(o, t, "ko", r["lang"]))
    table = {}
    for lang in [*a.langs.split(","), "all"]:
        g = [r for r in good if lang in (r["lang"], "all")]
        if not g:
            continue
        rate = lambda k: [sum(r["score"][k][0] for r in g), sum(r["score"][k][1] for r in g)]  # noqa: B023, E731
        flagged = [r for r in g if r["warnings"]]
        bad = [r for r in g if r["score"]["fact_error"] or r["score"]["language_error"]]
        table[lang] = dict(
            drafts=len(g), dates=rate("dates"), times=rate("times"), money=rate("money"), links=rate("links"),
            weekdays=[sum(r["score"]["weekdays"][0] for r in g), sum(sum(r["score"]["weekdays"]) for r in g)],
            drafts_with_wrong_weekday=sum(r["score"]["weekdays"][1] > 0 for r in g),
            drafts_with_leaked_instructions=sum(r["score"]["leak"] for r in g),
            terminology=rate("terms"), proper_nouns=rate("names"),
            drafts_missing_lines=sum(r["score"]["missing_lines"] for r in g),
            drafts_with_added_numbers=sum(bool(r["score"]["numbers_added"]) for r in g),
            drafts_with_added_links=sum(bool(r["score"]["links_added"]) for r in g),
            drafts_with_korean_left=sum(r["score"]["hangul_share"] > 0.05 for r in g),
            drafts_with_stray_chinese=sum(r["score"]["stray_han"] > 0 for r in g),
            fact_errors=sum(r["score"]["fact_error"] for r in g),
            drafts_without_any_measured_error=len(g) - len(bad),
            passed_production_checks=len(g) - len(flagged),
            checks_flagged_and_error=sum(r in bad for r in flagged), checks_flagged_no_error=sum(r not in bad for r in flagged),
            checks_missed_error=sum(r not in flagged for r in bad),
            warning_types=dict(Counter(w["type"] for r in flagged for w in r["warnings"]).most_common()),
            drafts_per_warning_type=dict(Counter(x for r in flagged for x in {w["type"] for w in r["warnings"]}).most_common()),
            seconds_median=round(statistics.median(r["seconds"] for r in g), 1),
            seconds_p95=sorted(r["seconds"] for r in g)[max(0, int(len(g) * 0.95) - 1)], seconds_max=max(r["seconds"] for r in g),
            input_tokens=sum(r["input_tokens"] for r in g), output_tokens=sum(r["output_tokens"] for r in g),
            repairs=sum(r["repairs"] for r in g))
    res = dict(name=a.name, at=datetime.now(UTC).isoformat(timespec="seconds"), model=a.model or s.ollama_model,
               style=a.style, repair=not a.no_repair, seed=a.seed,
               temperature=s.ollama_temperature, num_ctx=s.ollama_num_ctx, notices=len(corpus), errors=len(rows) - len(good),
               gpu=gpu_info, results=table)
    (RESULTS / f"announcements_{a.name}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    path.write_text(json.dumps(dict(rows=rows, gpu=gpu_info), ensure_ascii=False, indent=1))
    pct = lambda x: f"{x[0]}/{x[1]}"  # noqa: E731
    print(f"\n{'':6}" + "".join(f"{h:>12}" for h in ("drafts", "dates", "times", "money", "links", "weekdays", "terms", "names", "no error", "checks ok", "median s", "max s")))
    for lang, x in table.items():
        print(f"{lang:6}" + "".join(f"{v:>12}" for v in (x["drafts"], pct(x["dates"]), pct(x["times"]), pct(x["money"]), pct(x["links"]), pct(x["weekdays"]),
              pct(x["terminology"]), pct(x["proper_nouns"]), x["drafts_without_any_measured_error"], x["passed_production_checks"],
              x["seconds_median"], x["seconds_max"])))
    print("all:", {k: v for k, v in table["all"].items() if k.startswith(("checks", "drafts_", "fact", "warning"))}, gpu_info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Per-language retrieval evaluation for the multilingual RAG index.

The authoritative index holds ORIGINAL documents only (Korean and English here). Each topic is queried in all five
site languages; we measure whether the correct original document is retrieved (Recall@1, Recall@3, MRR) - i.e.
whether multilingual E5 bridges the language gap without indexing translations.

Local (real E5 ONNX model, in-memory store, the production indexing + retrieval code):
    cd backend && .venv/bin/python ../scripts/eval_multilingual_retrieval.py [--mode hybrid|vector] [--json out.json]
Against a deployed API (uses its real documents; pass expectations as title substrings):
    .venv/bin/python ../scripts/eval_multilingual_retrieval.py --api https://sch-hub-api.onrender.com --live-set study_in_korea

The corpus below is EVALUATION FIXTURE TEXT written for this test (not official guidance).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

LANGS = ("ko", "en", "id", "vi", "zh-CN")

CORPUS: dict[str, tuple[str, str, str]] = {   # key: (language, title, text)
    "visa_extension": ("en", "Extending your D-2 student visa", """# Extending your D-2 student visa
International students holding a D-2 (student) visa must apply for an extension of their period of stay before the
current period expires. Apply online through HiKorea or visit the immigration office with your passport, alien
registration card, certificate of enrollment, tuition payment receipt and proof of financial ability.
Late applications may result in a fine."""),
    "alien_registration": ("en", "Alien registration after arrival", """# Alien registration after arrival
Foreigners staying in Korea for more than 90 days must register with the local immigration office within 90 days of
entry. Bring your passport, one passport photo, the application form, the fee and proof of address such as a
dormitory certificate. The alien registration card (residence card) is issued a few weeks later."""),
    "health_insurance": ("ko", "외국인 유학생 국민건강보험 가입 안내", """# 외국인 유학생 국민건강보험 가입 안내
D-2, D-4 체류자격 유학생은 입국 후 6개월이 지나면 국민건강보험에 자동으로 가입됩니다. 매월 보험료를 납부해야 하며,
보험료를 체납하면 비자 연장에 불이익이 있을 수 있습니다. 병원 진료 시 외국인등록증을 제시하면 보험 혜택을 받을 수 있습니다."""),
    "dormitory": ("ko", "기숙사 입사 신청 안내", """# 기숙사 입사 신청 안내
학기별 기숙사 입사 신청은 온라인으로 접수합니다. 신청 기간 내에 신청서를 제출하고 기숙사비를 납부해야 하며,
입사 시 결핵 검사 결과서를 제출해야 합니다. 방학 중 기숙사 이용은 별도로 신청합니다."""),
    "scholarship": ("en", "TOPIK merit scholarship for international students", """# TOPIK merit scholarship
International students with a TOPIK level 4 or higher may receive a tuition reduction each semester. The reduction
depends on the TOPIK level and the grade point average of the previous semester. Submit your TOPIK certificate to the
international office before the scholarship deadline."""),
    "part_time_work": ("en", "Part-time work permission for students", """# Part-time work permission
Students on a D-2 visa may work part-time only after receiving permission for activities outside their status of
sojourn from the immigration office. Weekly working hours are limited during the semester and depend on your
Korean language ability. Working without permission can lead to fines or cancellation of the visa."""),
    "tuition": ("ko", "등록금 납부 안내", """# 등록금 납부 안내
등록금은 지정된 납부 기간 내에 가상계좌로 납부합니다. 분할 납부를 원하는 학생은 사전에 신청해야 하며,
기간 내 미납 시 제적될 수 있습니다. 납부 확인서는 포털에서 출력할 수 있습니다."""),
    "graduation": ("ko", "졸업 요건 안내", """# 졸업 요건 안내
졸업하려면 소속 학과의 졸업 학점을 이수하고 졸업 인증 요건을 충족해야 합니다. 외국인 유학생은 TOPIK 4급 이상
또는 학교가 정한 한국어 능력 기준을 충족해야 합니다. 졸업 논문 또는 대체 과목 이수도 필요합니다."""),
}

QUERIES: dict[str, dict[str, str]] = {
    "visa_extension": {
        "ko": "학생 비자 체류 기간 연장은 어떻게 신청하나요?",
        "en": "How do I extend my student visa period of stay?",
        "id": "Bagaimana cara memperpanjang masa tinggal visa pelajar saya?",
        "vi": "Làm thế nào để gia hạn thời gian lưu trú visa du học?",
        "zh-CN": "如何申请延长学生签证的居留期限？"},
    "alien_registration": {
        "ko": "입국 후 외국인 등록은 언제까지 해야 하나요?",
        "en": "When do I have to do alien registration after entering Korea?",
        "id": "Kapan saya harus melakukan registrasi orang asing setelah tiba di Korea?",
        "vi": "Sau khi nhập cảnh tôi phải đăng ký người nước ngoài trong bao lâu?",
        "zh-CN": "入境后需要在多长时间内办理外国人登记？"},
    "health_insurance": {
        "ko": "유학생 건강보험은 언제 가입되나요?",
        "en": "When are international students enrolled in national health insurance?",
        "id": "Kapan mahasiswa asing terdaftar di asuransi kesehatan nasional?",
        "vi": "Khi nào du học sinh được tham gia bảo hiểm y tế quốc dân?",
        "zh-CN": "留学生什么时候加入国民健康保险？"},
    "dormitory": {
        "ko": "기숙사 신청은 어떻게 하나요?",
        "en": "How do I apply for the dormitory?",
        "id": "Bagaimana cara mendaftar asrama?",
        "vi": "Làm thế nào để đăng ký ký túc xá?",
        "zh-CN": "怎么申请宿舍？"},
    "scholarship": {
        "ko": "토픽 성적으로 받을 수 있는 장학금이 있나요?",
        "en": "Is there a scholarship based on TOPIK level?",
        "id": "Apakah ada beasiswa berdasarkan level TOPIK?",
        "vi": "Có học bổng dựa trên cấp độ TOPIK không?",
        "zh-CN": "有根据TOPIK等级发放的奖学金吗？"},
    "part_time_work": {
        "ko": "유학생이 아르바이트를 하려면 허가가 필요한가요?",
        "en": "Do I need permission to work part-time as a student?",
        "id": "Apakah saya perlu izin untuk kerja paruh waktu sebagai mahasiswa?",
        "vi": "Du học sinh có cần xin phép để làm thêm không?",
        "zh-CN": "留学生打工需要许可吗？"},
    "tuition": {
        "ko": "등록금은 어떻게 내나요?",
        "en": "How do I pay tuition fees?",
        "id": "Bagaimana cara membayar uang kuliah?",
        "vi": "Làm thế nào để đóng học phí?",
        "zh-CN": "学费怎么缴纳？"},
    "graduation": {
        "ko": "졸업하려면 어떤 요건이 필요한가요?",
        "en": "What are the requirements to graduate?",
        "id": "Apa saja syarat untuk lulus?",
        "vi": "Điều kiện để tốt nghiệp là gì?",
        "zh-CN": "毕业需要满足哪些条件？"},
}

# live check against the deployed Knowledge Center (expectation = substring of the original document title)
LIVE_SETS = {
    "study_in_korea": {"expect": "Study in Korea", "queries": {
        "ko": "유학생 비자 신청에 필요한 서류는 무엇인가요?",
        "en": "What documents do I need to apply for a student visa?",
        "id": "Dokumen apa yang diperlukan untuk mengajukan visa pelajar?",
        "vi": "Cần những giấy tờ gì để xin visa du học?",
        "zh-CN": "申请学生签证需要哪些材料？"}},
}


def summarize(ranks: dict[str, list[int | None]]) -> dict[str, dict[str, float]]:
    out = {}
    for lang, rs in ranks.items():
        n = len(rs)
        out[lang] = dict(n=n, recall_at_1=round(sum(1 for r in rs if r == 1) / n, 3),
                         recall_at_3=round(sum(1 for r in rs if r and r <= 3) / n, 3),
                         mrr=round(sum(1 / r for r in rs if r) / n, 3))
    return out


def print_table(title: str, summary: dict[str, dict[str, float]]) -> None:
    print(f"\n{title}\n{'lang':6} {'n':>3} {'R@1':>6} {'R@3':>6} {'MRR':>6}")
    for lang in LANGS:
        s = summary.get(lang)
        if s:
            print(f"{lang:6} {s['n']:>3} {s['recall_at_1']:>6.3f} {s['recall_at_3']:>6.3f} {s['mrr']:>6.3f}")


def run_local(mode: str) -> dict:  # type: ignore[type-arg]
    from app.core.config import Settings
    from app.repositories.memory_store import MemoryFileStorage, MemoryStore, seed_categories
    from app.services.container import build_services
    from app.services.embeddings.factory import build_embedding_provider
    from app.services.llm.base import NullLLMProvider

    settings = Settings(_env_file=None, embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "e5_onnx"),
                        job_execution="inline", environment="test", supabase_jwt_secret="x" * 32)
    store = MemoryStore()
    seed_categories(store)
    t0 = time.perf_counter()
    emb = build_embedding_provider(settings)
    svc = build_services(settings, store, MemoryFileStorage(), emb, NullLLMProvider())
    admin = store.insert("profiles", dict(id="00000000-0000-0000-0000-00000000ad01", email="eval@example.test",
                                          display_name="Eval", role="admin"))
    doc_of: dict[str, str] = {}
    for key, (lang, title, text) in CORPUS.items():
        src = store.insert("knowledge_sources", dict(title=title, organization="SCH (evaluation fixture)",
                                                     source_type="manual_text", authority_type="official_university",
                                                     scope="university", category="academic-life", language=lang))
        job = svc.ingestion.ingest_text(src, title=title, text=text, requested_by=admin["id"])
        v = store.select("document_versions", __import__("app.repositories.base", fromlist=["Query"]).Query(
            eq={"id": job["version_id"]}))[0][0]
        if v["verification_status"] == "draft":
            store.update("document_versions", {"verification_status": "pending_review"}, {"id": v["id"]})
            v["verification_status"] = "pending_review"
        act = svc.ingestion.request_activation(v, admin["id"], "evaluation")
        svc.ingestion.run_job(act["id"])
        doc_of[key] = job["document_id"]
    index_s = time.perf_counter() - t0
    ranks: dict[str, list[int | None]] = {lang: [] for lang in LANGS}
    misses = []
    for key, qs in QUERIES.items():
        for lang, q in qs.items():
            res = svc.retrieval.search(q, language=lang, top_k=5, mode=mode)["results"]
            docs = list(dict.fromkeys(r["document_id"] for r in res))
            rank = docs.index(doc_of[key]) + 1 if doc_of[key] in docs else None
            ranks[lang].append(rank)
            if rank != 1:
                misses.append(dict(topic=key, lang=lang, query=q, rank=rank,
                                   top=[r["document_title"] for r in res[:3]]))
    return dict(mode=mode, model=emb.model_id, documents=len(CORPUS), queries=sum(len(q) for q in QUERIES.values()),
                index_seconds=round(index_s, 1), per_language=summarize(ranks), misses=misses)


def run_api(base: str, set_name: str) -> dict:  # type: ignore[type-arg]
    spec = LIVE_SETS[set_name]
    ranks: dict[str, list[int | None]] = {}
    detail = []
    for lang, q in spec["queries"].items():
        req = urllib.request.Request(f"{base.rstrip('/')}/api/v1/knowledge/search", method="POST",
                                     data=json.dumps({"query": q, "language": lang, "top_k": 5}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "sch-hub-eval"})
        res = json.load(urllib.request.urlopen(req, timeout=120))
        titles = [r["document_title"] for r in res["results"]]
        rank = next((i + 1 for i, t in enumerate(titles) if spec["expect"].lower() in t.lower()), None)
        ranks[lang] = [rank]
        top = res["results"][0] if res["results"] else {}
        detail.append(dict(lang=lang, query=q, rank=rank, mode=res["retrieval"]["mode"],
                           top_title=top.get("document_title"), top_source_url=top.get("source_url"),
                           similarity=top.get("similarity")))
    return dict(api=base, set=set_name, per_language=summarize(ranks), detail=detail)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "vector", "keyword"])
    ap.add_argument("--api")
    ap.add_argument("--live-set", default="study_in_korea", choices=sorted(LIVE_SETS))
    ap.add_argument("--json")
    a = ap.parse_args()
    out = run_api(a.api, a.live_set) if a.api else run_local(a.mode)
    print_table(f"{'API ' + a.api if a.api else 'local ' + out['model']} — mode {a.mode}", out["per_language"])
    for m in out.get("misses", []):
        print(f"  miss {m['lang']:5} {m['topic']:18} rank={m['rank']} top={m['top'][:2]}")
    for d in out.get("detail", []):
        print(f"  {d['lang']:5} rank={d['rank']} mode={d['mode']} sim={d['similarity']} -> {d['top_title']} "
              f"<{d['top_source_url']}>")
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

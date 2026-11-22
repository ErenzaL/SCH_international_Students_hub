"""Offline end-to-end demonstration of the ingestion + review + retrieval pipeline.

Uses an in-memory store (no Supabase needed) but REAL network fetching, extraction, chunking and
embeddings. It demonstrates:
  1. one accessible official government webpage (Study in Korea - visa & stay)
  2. one manually submitted SCH notice (clearly labelled TEST DATA, not a real notice)
and then approves both and runs multilingual searches.

    cd backend
    EMBEDDING_PROVIDER=e5 .venv/bin/python ../scripts/demo_pipeline.py     # real multilingual-e5-small
    EMBEDDING_PROVIDER=hash .venv/bin/python ../scripts/demo_pipeline.py   # lexical stand-in, no download
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.config import Settings  # noqa: E402
from app.repositories.memory_store import MemoryFileStorage, MemoryStore, seed_categories  # noqa: E402
from app.security.auth import AuthUser  # noqa: E402
from app.services.container import build_services  # noqa: E402
from app.services.embeddings.factory import build_embedding_provider  # noqa: E402
from app.services.llm.base import NullLLMProvider  # noqa: E402

URL = "https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do"


def main() -> None:
    settings = Settings(_env_file=None, embedding_provider=os.environ.get("EMBEDDING_PROVIDER", "hash"))
    store = MemoryStore()
    seed_categories(store)
    admin = store.insert("profiles", dict(id="00000000-0000-0000-0000-00000000ad01", email="demo-admin@example.test",
                                          display_name="Demo Admin", role="admin"))
    actor = AuthUser(id=admin["id"], email=admin["email"], role="admin")
    svc = build_services(settings, store, MemoryFileStorage(), build_embedding_provider(settings), NullLLMProvider())
    print(f"embedding model: {svc.embedder.model_id}")

    # 1) real official webpage
    src = svc.sources.create(dict(
        title="Study in Korea - Visa and Stay", original_url=URL, organization="Study in Korea (NIIED)",
        source_type="website", authority_type="official_government", scope="national", category="visa-immigration",
        language="ko", sync_frequency="manual", is_active=True), actor.id)
    job = svc.ingestion.create_job(src, "manual", actor.id)
    t0 = time.time()
    job = svc.ingestion.run_job(job["id"])
    print(f"\n[1] website job: status={job['status']} outcome={job.get('outcome')} "
          f"error={job.get('error_code')} stats={json.dumps(job['statistics'], ensure_ascii=False)} ({time.time() - t0:.1f}s)")
    if job["status"] == "succeeded":
        svc.review.approve(job["version_id"], actor, "demo approval")
        print("    approved version", job["version_id"])
    again = svc.ingestion.run_job(svc.ingestion.create_job(src, "manual", actor.id)["id"])
    print(f"    re-fetch (no change expected): outcome={again.get('outcome')}")

    # 2) manually submitted SCH notice -- TEST DATA, not a real announcement
    ann = svc.announcements.create(dict(
        title="[TEST DATA] 외국인 유학생 안내 공지 예시", category="university-announcements",
        body=("[테스트 데이터] 이 공지는 파이프라인 시연용 예시이며 실제 순천향대학교 공지가 아닙니다.\n\n"
              "## 대상\n외국인 유학생\n\n## 안내\n외국인등록증 신청 및 체류기간 연장 관련 안내 예시 문장입니다."),
        target_audience="International students (test)", source_type="manual_text", original_language="ko",
        evidence_note="TEST DATA - not an official notice", submit=True), actor)
    svc.announcements.approve(ann["id"], actor, "demo approval")
    print(f"\n[2] manual SCH notice (TEST DATA) published: {ann['title']}")

    # 3) multilingual retrieval over the same approved corpus
    print("\n[3] retrieval")
    for q in ["D-2 visa extension", "TOPIK registration", "외국인등록증 신청", "izin kerja paruh waktu mahasiswa",
              "student visa application documents", "how to apply for alien registration card"]:
        res = svc.retrieval.search(q, top_k=2)
        print(f"  Q: {q}  [mode={res['retrieval']['mode']}]")
        if not res["results"]:
            print("     (no approved evidence)")
        for r in res["results"]:
            sim = f"{r['similarity']:.3f}" if r["similarity"] is not None else "n/a"
            print(f"     - {r['document_title'][:50]} | sim={sim} kw={r['keyword_rank']} | {r['source_url']}")
            print(f"       {' '.join(r['passage'].split())[:110]}")


if __name__ == "__main__":
    main()

"""Local development backend: FastAPI + local Ollama + in-memory store with SYNTHETIC data. Never touches Supabase.

    cd backend && .venv/bin/python ../scripts/dev_ollama_backend.py                 # translation drafts + RAG answers
    cd backend && .venv/bin/python ../scripts/dev_ollama_backend.py --translation-only
    cd backend && .venv/bin/python ../scripts/dev_ollama_backend.py --embedding hash   # no model download

Safety: .env files are NOT read; the script refuses to start when any Supabase variable is set in the environment;
it listens on 127.0.0.1 only; scheduled agents, automatic translation on publication and public machine translations
stay off; website fetching is disabled. Data is lost when the process stops.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
for _k in list(os.environ):      # a stray shell variable must not change what this script runs
    if _k.upper().startswith(("SUPABASE", "NEXT_PUBLIC_SUPABASE")) and os.environ[_k]:
        sys.exit(f"Refusing to start: {_k} is set. This launcher never connects to Supabase.")
    if _k.upper() in ("AGENT_SCHEDULES_ENABLED", "CRON_SECRET", "LLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        del os.environ[_k]

import app.core.config as config  # noqa: E402

config.Settings.model_config["env_file"] = None      # app.main builds a default app on import: never from a .env file

DOCS = [
    ("en", "academic-life", "[SYNTHETIC] Certificate of enrollment",
     "Students can print a certificate of enrollment at the kiosk in the Example Hall lobby. The fee is 1,500 won per "
     "copy. The kiosk is open from 09:00 to 18:00 on weekdays. Bring your student ID card."),
    ("ko", "visa-immigration", "[가상] 체류기간 연장 안내",
     "D-2 체류기간 연장은 만료일 4개월 전부터 신청할 수 있습니다. 준비 서류는 여권, 외국인등록증, 재학증명서, "
     "체류지 입증서류입니다. 수수료는 60,000원입니다. 이 문서는 개발용 가상 자료입니다."),
    ("ko", "academic-life", "[가상] 기숙사 입사 안내",
     "2027학년도 1학기 생활관 입사일은 2027-02-24이며 10:00부터 17:00까지 입사할 수 있습니다. 결핵 검사 결과서를 "
     "제출해야 합니다. 이 문서는 개발용 가상 자료입니다."),
]
ANNOUNCEMENT = dict(
    title="[가상] 국제학생 장학금 신청 안내",
    body="신청 기간은 2026년 12월 1일부터 12월 15일까지입니다.\n\n신청서는 https://example.ac.kr/apply 에서 제출하세요.\n\n"
         "문의: intl@example.ac.kr")


def build(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    from app.core.config import Settings
    from app.main import create_app
    from app.repositories.memory_store import MemoryFileStorage, MemoryStore, seed_categories

    secret = secrets.token_urlsafe(48)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, environment="development", supabase_url="", supabase_service_role_key="",
        supabase_jwt_secret=secret, llm_provider="none" if args.translation_only else "ollama",
        background_llm_provider="ollama", embedding_provider=args.embedding, job_execution="inline",
        translation_chunk_chars=3000, agent_schedules_enabled=False, auto_translate_announcements=False,
        auto_translate_documents=False, public_machine_translations=False, allowed_source_domains="", cron_secret="")
    store = MemoryStore()
    seed_categories(store)
    users = {}
    for role in ("super_admin", "admin", "supporter", "student"):
        users[role] = str(uuid.uuid4())
        store.insert("profiles", dict(id=users[role], email=f"{role}@example.test", display_name=role.title(), role=role))
    app = create_app(settings, store=store, storage=MemoryFileStorage())
    return app, settings, users, secret


def seed(app, users) -> str:  # type: ignore[no-untyped-def]
    from app.repositories.base import Query

    svc = app.state.services
    for lang, category, title, text in DOCS:
        src = svc.store.insert("knowledge_sources", dict(
            title=title, organization="SYNTHETIC TEST DATA", source_type="manual_text", is_test_data=True,
            authority_type="official_university", scope="university", category=category, language=lang))
        job = svc.ingestion.ingest_text(src, title=title, text=text, requested_by=users["admin"])
        v = svc.store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]
        if v["verification_status"] == "draft":
            svc.store.update("document_versions", {"verification_status": "pending_review"}, {"id": v["id"]})
            v["verification_status"] = "pending_review"
        svc.ingestion.run_job(svc.ingestion.request_activation(v, users["admin"], "synthetic seed")["id"])
    from fastapi.testclient import TestClient

    c = TestClient(app)             # in-process: no network, no server
    h = {"Authorization": f"Bearer {app.state.dev_tokens['admin']}"}
    r = c.post("/api/v1/admin/announcements", headers=h, json=dict(
        ANNOUNCEMENT, category="scholarships", original_language="ko", submit=True, source_type="manual_text",
        target_audience="All international students", evidence_note="SYNTHETIC development data",
        event_date=None, deadline=None))
    if r.status_code != 201:
        sys.exit(f"seeding the announcement failed: {r.status_code} {r.text[:300]}")
    aid = r.json()["id"]
    r = c.post(f"/api/v1/admin/announcements/{aid}/approve", headers=h, json={})
    if r.status_code != 200:
        sys.exit(f"approving the announcement failed: {r.status_code} {r.text[:300]}")
    return aid


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--embedding", choices=["e5_onnx", "hash"], default="e5_onnx",
                   help="e5_onnx: multilingual search (downloads a public ~124 MB model once); hash: offline, keyword-like")
    p.add_argument("--translation-only", action="store_true", help="Qwen drafts only; the assistant shows passages")
    args = p.parse_args()

    import jwt
    import uvicorn

    app, settings, users, secret = build(args)
    app.state.dev_tokens = {
        role: jwt.encode({"sub": uid, "aud": "authenticated", "exp": int(time.time()) + 12 * 3600,
                          "email": f"{role}@example.test"}, secret, algorithm="HS256") for role, uid in users.items()}
    aid = seed(app, users)
    print(f"\nModel: {settings.ollama_model} at {settings.ollama_base_url}  (assistant: {settings.llm_provider}, "
          f"background: ollama)\n\nSynthetic announcement and development tokens (this process only, 12 h):\nexport ANNOUNCEMENT_ID={aid}")
    for role, token in app.state.dev_tokens.items():
        print(f"export {role.upper()}_TOKEN={token}")
    print(flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()

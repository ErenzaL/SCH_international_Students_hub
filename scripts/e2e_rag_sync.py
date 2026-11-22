"""End-to-end check of automatic RAG synchronization (scenarios A–H) on a LOCAL Supabase-compatible stack.

Real: official sources over the network (robots.txt respected), SCH notice board, PyMuPDF, the production
embedding model (e5_onnx, int8 multilingual-e5-small), supabase-py -> PostgREST -> PostgreSQL + pgvector with
all migrations, and the persistent worker (JOB_EXECUTION=worker, claim RPC, retries).
Simulated (and labelled as such in the output): the "updated webpage" in D is the real Study in Korea page with
one appended sentence, because the live page cannot be changed; the embedding failure in F is injected.
Not real: file storage is in-memory; users are local test accounts.

    E2E_REST_URL=http://127.0.0.1:54331 E2E_PSQL="psql -h /tmp/schpg -p 54329 -U postgres -d hub -q -t -A" \\
    E2E_JWT_SECRET=... E2E_HF_CACHE=<dir> backend/.venv/bin/python scripts/e2e_rag_sync.py
"""
from __future__ import annotations

import io
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories.memory_store import MemoryFileStorage  # noqa: E402
from app.repositories.supabase_store import SupabaseStore  # noqa: E402
from app.services.embeddings.base import EmbeddingError  # noqa: E402

REST, PSQL, SECRET = os.environ["E2E_REST_URL"], os.environ["E2E_PSQL"], os.environ["E2E_JWT_SECRET"]
STUDY = "https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do"
BOARD = "https://sgee.sch.ac.kr/notice/notice01.php?page=1&make=&search=&type=&table_name=noti_fore&loc_mnu=3"
OUT = Path(os.environ.get("E2E_OUT", "e2e_rag_sync.json"))
report: dict = {"steps": [], "searches": []}


def log(step: str, ok: bool | None = None, **kw) -> None:  # type: ignore[no-untyped-def]
    mark = "" if ok is None else ("PASS " if ok else "FAIL ")
    print(f"- {mark}{step}: " + json.dumps(kw, ensure_ascii=False, default=str)[:500], flush=True)
    report["steps"].append({"step": step, "ok": ok, **kw})


def sql(q: str) -> str:
    out = subprocess.run(shlex.split(PSQL) + ["-v", "ON_ERROR_STOP=1", "-c", q], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    return out.stdout.strip()


def main() -> None:  # noqa: PLR0915
    key = jwt.encode({"role": "service_role", "exp": int(time.time()) + 7200}, SECRET, algorithm="HS256")
    settings = Settings(_env_file=None, supabase_url=REST, supabase_service_role_key=key, supabase_jwt_secret=SECRET,
                        embedding_provider="e5_onnx", embedding_cache_dir=os.environ.get("E2E_HF_CACHE", ""),
                        retrieval_min_similarity=0.80, job_execution="worker", job_poll_seconds=1.0,
                        job_retry_base_seconds=2, rate_limit_search_per_minute=1000, rate_limit_ingest_per_minute=1000,
                        rate_limit_public_per_minute=1000, board_max_items=5)
    app = create_app(settings, store=SupabaseStore(settings), storage=MemoryFileStorage())
    tag = uuid.uuid4().hex[:6]
    users = {}
    for role in ("admin", "supporter"):
        uid = str(uuid.uuid4())
        sql(f"insert into auth.users (id, email) values ('{uid}', 'rag-{role}-{tag}@example.test')")
        sql(f"update public.profiles set role = '{role}', display_name = 'E2E {role}' where id = '{uid}'")
        users[role] = uid

    def auth(role: str) -> dict[str, str]:
        t = jwt.encode({"sub": users[role], "aud": "authenticated", "exp": int(time.time()) + 7200}, SECRET, algorithm="HS256")
        return {"Authorization": f"Bearer {t}"}

    with TestClient(app) as c:  # lifespan -> persistent worker thread
        svc = app.state.services

        def wait_job(job_id: str, timeout: float = 600) -> dict:  # type: ignore[type-arg]
            t0 = time.time()
            while time.time() - t0 < timeout:
                j = c.get(f"/api/v1/admin/ingestion-jobs/{job_id}", headers=auth("admin")).json()
                if j["status"] in ("succeeded", "failed"):
                    return j
                time.sleep(1)
            raise TimeoutError(job_id)

        def approve_and_wait(vid: str, timeout: float = 600) -> tuple[int, dict, float]:  # type: ignore[type-arg]
            t0 = time.time()
            r = c.post(f"/api/v1/admin/versions/{vid}/approve", headers=auth("admin"), json={"note": "E2E review"})
            while time.time() - t0 < timeout:
                v = c.get(f"/api/v1/admin/versions/{vid}", headers=auth("admin")).json()
                if (v["verification_status"] == "approved" and v["is_current"]) or v["indexing_status"] == "failed":
                    return r.status_code, v, round(time.time() - t0, 1)
                time.sleep(1)
            raise TimeoutError(vid)

        def search(q: str, k: int = 5) -> list[dict]:  # type: ignore[type-arg]
            return c.post("/api/v1/knowledge/search", json={"query": q, "top_k": k}).json()["results"]

        def source(body: dict) -> dict:  # type: ignore[type-arg]
            r = c.post("/api/v1/admin/sources", headers=auth("admin"), json=body)
            if r.status_code == 201:
                return r.json()
            items = c.get("/api/v1/admin/sources", headers=auth("admin"), params={"q": body["original_url"][:150],
                                                                                 "source_type": body["source_type"]}).json()
            return next(x for x in items["items"] if x["original_url"] == body["original_url"])

        log("environment", model=svc.embedder.model_id, job_execution=settings.job_execution)

        # ------------------------------------------------ C: official webpage -> fetch -> approve -> searchable
        study = source(dict(title="Study in Korea – Visa and Stay", original_url=STUDY, organization="Study in Korea (NIIED)",
                            source_type="website", authority_type="official_government", scope="national",
                            category="visa-immigration", language="ko", sync_frequency="weekly"))
        j = wait_job(c.post(f"/api/v1/admin/sources/{study['id']}/ingest", headers=auth("admin")).json()["job_id"])
        pre = [h for h in search("D-2 visa required documents") if h["version_id"] == j["version_id"]]
        log("C.fetch", ok=j["outcome"] == "new_version" and not pre, chunks=j["statistics"].get("chunk_count"),
            embedded_before_approval=j["statistics"].get("embedded_chunks"), searchable_before_approval=bool(pre))
        code, v, secs = approve_and_wait(j["version_id"])
        hits = search("What documents do I need for a D-2 student visa?")
        log("C.approve_index_activate", ok=code == 202 and v["is_current"] and hits and hits[0]["version_id"] == v["id"],
            http=code, seconds_to_active=secs, chunks=v["chunk_count"], embedded=v["embedded_chunk_count"],
            top=hits[0]["heading"] if hits else None)
        study_v1 = v["id"]

        # ------------------------------------------------ board (provides real PDFs and a real staff notice)
        board = source(dict(title="SCH 유학생 공지사항", original_url=BOARD, organization="순천향대학교 국제교육교류처",
                            source_type="sch_board", authority_type="official_university", scope="university",
                            category="university-announcements", language="ko", sync_frequency="daily",
                            config={"max_items": 5, "max_pages": 1}))
        bj = wait_job(c.post(f"/api/v1/admin/sources/{board['id']}/ingest", headers=auth("admin")).json()["job_id"])
        log("board.sync", ok=bj["status"] == "succeeded", new=bj["statistics"].get("items_new"),
            unchanged=bj["statistics"].get("items_unchanged"))
        notices = bj["statistics"].get("notices", [])
        for n in notices:
            if n["outcome"] == "new_version":
                approve_and_wait(n["version_id"])
        pdfs: list[tuple[str, bytes]] = []
        for d in c.get(f"/api/v1/admin/sources/{board['id']}", headers=auth("admin")).json()["documents"]:
            for a in (c.get(f"/api/v1/admin/documents/{d['id']}", headers=auth("admin")).json().get("metadata") or {}).get(
                    "attachments") or []:
                if a["name"].lower().endswith(".pdf") and len(pdfs) < 2:
                    try:
                        res = svc.ingestion.fetcher.fetch(a["url"], "ko")
                        if res.content.startswith(b"%PDF-"):
                            pdfs.append((a["name"], res.content))
                    except Exception as exc:  # noqa: BLE001
                        log("attachment_fetch_failed", name=a["name"], error=str(exc)[:120])

        # ------------------------------------------------ A: PDF upload -> approve -> searchable
        meta = dict(title="SCH dormitory notice (official PDF)", organization="순천향대학교 국제교육교류처",
                    category="dormitory-housing", scope="university", authority_type="official_university", language="ko")
        r = c.post("/api/v1/admin/intake/document", headers=auth("admin"), data={"metadata": json.dumps(meta)},
                   files={"file": ("dorm.pdf", io.BytesIO(pdfs[0][1]), "application/pdf")})
        pj = wait_job(r.json()["job_id"])
        code, va, secs = approve_and_wait(pj["version_id"])
        hits = search("동계방학 생활관 입사 신청 방법")
        log("A.pdf_upload_approve", ok=va["is_current"] and any(h["version_id"] == va["id"] for h in hits),
            file=pdfs[0][0], chunks=va["chunk_count"], embedded=va["embedded_chunk_count"], seconds_to_active=secs)

        # ------------------------------------------------ B: replace the PDF -> new version -> old superseded
        pdf_source = r.json()["source"]["id"]
        r2 = c.post("/api/v1/admin/intake/document", headers=auth("admin"), data={"source_id": pdf_source},
                    files={"file": ("dorm-v2.pdf", io.BytesIO(pdfs[1][1]), "application/pdf")})
        pj2 = wait_job(r2.json()["job_id"])
        before = {h["version_id"] for h in search("생활관 짐 보관", 10) if h["document_id"] == va["document_id"]}
        code, vb, secs = approve_and_wait(pj2["version_id"])
        old = c.get(f"/api/v1/admin/versions/{va['id']}", headers=auth("admin")).json()
        after = {h["version_id"] for h in search("생활관 짐 보관", 10) if h["document_id"] == va["document_id"]}
        log("B.replace_pdf", ok=vb["is_current"] and old["verification_status"] == "superseded" and va["id"] not in after,
            replaced_with=pdfs[1][0], new_chunks=vb["chunk_count"], old_status=old["verification_status"],
            old_chunks_kept=old["chunk_count"], versions_in_results_before=len(before), after_only_new=after <= {vb["id"]})

        # ------------------------------------------------ D: updated webpage (SIMULATED change) -> pending only
        real_fetch = svc.ingestion.fetcher.fetch

        def changed_fetch(url, language=None):  # type: ignore[no-untyped-def]
            res = real_fetch(url, language)
            if url == STUDY:
                marker = "발급받아야 합니다".encode()
                assert marker in res.content, "simulation marker not found in the live page"
                res.content = res.content.replace(marker, marker + " [E2E simulated update] 유학(D-2) 비자 연장 신청은 체류기간 "
                                                  "만료 4개월 전부터 가능합니다.".encode(), 1)
            return res

        svc.ingestion.fetcher.fetch = changed_fetch
        jd = wait_job(c.post(f"/api/v1/admin/sources/{study['id']}/ingest", headers=auth("admin")).json()["job_id"])
        svc.ingestion.fetcher.fetch = real_fetch
        live = search("D-2 비자 연장 신청", 10)
        notes = c.get("/api/v1/admin/notifications", headers=auth("admin")).json()
        log("D.update_detected_pending", ok=jd["outcome"] == "new_version"
            and all(h["version_id"] != jd["version_id"] for h in live) and any(h["version_id"] == study_v1 for h in live),
            simulated=True, pending_version=jd["version_id"], public_answers_from=sorted({h["version_id"][:8] for h in live
                                                                                          if h["document_id"] == v["document_id"]}),
            review_notification=any(n["kind"] == "review_needed" for n in notes["items"]))

        # ------------------------------------------------ F: embedding failure on approval -> old version stays
        emb = svc.embedder
        real_embed = emb.embed_passages

        def broken(texts):  # type: ignore[no-untyped-def]
            raise EmbeddingError("injected failure: model unavailable")

        emb.embed_passages = broken
        rf = c.post(f"/api/v1/admin/versions/{jd['version_id']}/approve", headers=auth("admin"), json={})
        assert rf.status_code == 202, rf.text
        job_id = rf.json()["indexing_job_id"]
        t0 = time.time()
        while time.time() - t0 < 60:
            jj = c.get(f"/api/v1/admin/ingestion-jobs/{job_id}", headers=auth("admin")).json()
            if jj["status"] == "failed":
                break
            time.sleep(1)
        emb.embed_passages = real_embed
        live = search("D-2 비자 연장 신청", 10)
        vf = c.get(f"/api/v1/admin/versions/{jd['version_id']}", headers=auth("admin")).json()
        log("F.embedding_failure", ok=jj["status"] == "failed" and vf["indexing_status"] == "failed"
            and any(h["version_id"] == study_v1 for h in live), simulated=True, job_status=jj["status"],
            attempts=jj["attempts"], error=jj["error_code"], previous_version_still_answers=any(
                h["version_id"] == study_v1 for h in live))

        # ------------------------------------------------ G: retry -> activated, no duplicate chunks
        rr = c.post(f"/api/v1/admin/ingestion-jobs/{job_id}/retry", headers=auth("admin"))
        wait_job(rr.json()["job_id"])
        vg = c.get(f"/api/v1/admin/versions/{jd['version_id']}", headers=auth("admin")).json()
        dup = sql(f"select count(*) - count(distinct chunk_index) from document_chunks where version_id = '{jd['version_id']}'")
        live = search("D-2 비자 연장 신청 4개월 전", 10)
        log("G.retry", ok=vg["is_current"] and dup == "0" and any(h["version_id"] == vg["id"] for h in live),
            chunks=vg["chunk_count"], duplicate_chunks=int(dup), study_v1_status=c.get(
                f"/api/v1/admin/versions/{study_v1}", headers=auth("admin")).json()["verification_status"])

        # ------------------------------------------------ E: pasted verified staff announcement -> approve -> searchable
        staff = next((n for n in notices if "입사생" in n["title"]), notices[0])
        staff_doc = c.get(f"/api/v1/admin/documents/{staff['document_id']}", headers=auth("admin")).json()
        body = (staff_doc.get("current_version") or {}).get("extracted_text", "")
        paste = c.post("/api/v1/admin/intake/announcement", headers=auth("supporter"), json=dict(
            original_text=body[:3000], title=f"[KakaoTalk relay] {staff['title'][:80]}", organization="국제교육교류처",
            category="dormitory-housing", authorized_by_supporter=True, submit=True)).json()
        code, ve, secs = approve_and_wait(paste["version_id"])
        hits = search("동계방학 생활관 입사생 모집", 10)
        log("E.staff_announcement", ok=ve["is_current"] and any(h["version_id"] == ve["id"] for h in hits),
            submitted_by="supporter", authority=next((h["authority_type"] for h in hits if h["version_id"] == ve["id"]), None),
            seconds_to_active=secs)

        # ------------------------------------------------ H: withdraw -> disappears immediately
        w = c.post(f"/api/v1/admin/documents/{ve['document_id']}/cancel", headers=auth("admin"),
                   json={"reason": "E2E: withdrawn incorrect relay"})
        hits = search("동계방학 생활관 입사생 모집", 10)
        log("H.withdraw", ok=w.status_code == 200 and all(h["document_id"] != ve["document_id"] for h in hits),
            still_found=any(h["document_id"] == ve["document_id"] for h in hits),
            public_detail=c.get(f"/api/v1/knowledge/documents/{ve['document_id']}").status_code)

        # ------------------------------------------------ multilingual retrieval
        for q in ("What is a D-2 visa?", "D-2 비자는 무엇인가요?", "Apa itu visa D-2?", "Visa D-2 là gì?", "D-2签证是什么？",
                  "Can I store my luggage in the dormitory during vacation?", "방학 중 짐 보관", "Bisakah saya menyimpan barang di asrama saat liburan?",
                  "Tôi có thể gửi hành lý ở ký túc xá trong kỳ nghỉ không?", "放假期间可以在宿舍存放行李吗？"):
            res = c.post("/api/v1/knowledge/search", json={"query": q, "top_k": 3}).json()
            top = [dict(title=h["document_title"][:50], heading=(h.get("heading") or "")[:40],
                        similarity=round(h["similarity"], 3) if h.get("similarity") is not None else None,
                        exact=h["exact_match"], url=h["source_url"]) for h in res["results"]]
            report["searches"].append(dict(query=q, mode=res["retrieval"]["mode"], top=top))
            print(f"Q {q} [{res['retrieval']['mode']}]")
            for t in top:
                print(f"   {t['similarity']} {t['title']} | {t['heading']}")

        st = c.get("/api/v1/admin/rag/status", headers=auth("admin")).json()
        log("rag_status", counts=st["counts"], embedding=st["embedding"])
        report["sql_counts"] = sql(
            "select json_build_object('chunks', (select count(*) from document_chunks), "
            "'embedded', (select count(*) from document_chunks where embedding is not null), "
            "'embedded_by_model', (select json_object_agg(m, n) from (select coalesce(embedding_model, '(none)') m, count(*) n "
            "from document_chunks group by 1) x), 'searchable', (select count(*) from searchable_chunks), "
            "'versions', (select json_object_agg(s, n) from (select verification_status s, count(*) n from document_versions group by 1) y), "
            "'index_jobs', (select json_object_agg(s, n) from (select status s, count(*) n from ingestion_jobs where job_type = 'index_version' group by 1) z))")
        print("SQL:", report["sql_counts"])
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    passed = sum(1 for s in report["steps"] if s["ok"] is True)
    failed = [s["step"] for s in report["steps"] if s["ok"] is False]
    print(f"\n{passed} scenario checks passed, {len(failed)} failed {failed}")


if __name__ == "__main__":
    main()

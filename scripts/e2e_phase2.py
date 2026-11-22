"""Phase 2 end-to-end run against a LOCAL Supabase-compatible stack with REAL sources.

Real: network fetching of official pages (robots.txt respected), SCH notice-board connector, PyMuPDF,
Tesseract OCR (if installed), multilingual-e5-small embeddings, supabase-py -> PostgREST -> PostgreSQL
+ pgvector with the real migrations, the persistent job worker (claim RPC).
Not real: file storage is in-memory (no local Supabase Storage server); users are local test accounts.
Nothing is approved automatically except by this script acting as the local test admin.

    E2E_REST_URL=http://127.0.0.1:54331 E2E_PSQL="psql -h /tmp/schpg -p 54329 -U postgres -d hub -q -t -A" \\
    E2E_JWT_SECRET=... backend/.venv/bin/python scripts/e2e_phase2.py
"""
from __future__ import annotations

import io
import json
import os
import shlex
import shutil
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

REST = os.environ["E2E_REST_URL"]
PSQL = os.environ["E2E_PSQL"]
SECRET = os.environ["E2E_JWT_SECRET"]
OUT = Path(os.environ.get("E2E_OUT", "e2e_phase2_results.json"))
STUDY = "https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do"
BOARD = "https://sgee.sch.ac.kr/notice/notice01.php?page=1&make=&search=&type=&table_name=noti_fore&loc_mnu=3"
report: dict = {"steps": [], "searches": []}


def log(step: str, **kw) -> None:  # type: ignore[no-untyped-def]
    print(f"- {step}: " + json.dumps(kw, ensure_ascii=False, default=str)[:600], flush=True)
    report["steps"].append({"step": step, **kw})


def sql(q: str) -> str:
    out = subprocess.run(shlex.split(PSQL) + ["-v", "ON_ERROR_STOP=1", "-c", q], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    return out.stdout.strip()


def main() -> None:  # noqa: PLR0915
    service_key = jwt.encode({"role": "service_role", "exp": int(time.time()) + 7200}, SECRET, algorithm="HS256")
    ocr = "tesseract" if shutil.which("tesseract") else "none"
    settings = Settings(_env_file=None, supabase_url=REST, supabase_service_role_key=service_key, supabase_jwt_secret=SECRET,
                        embedding_provider="e5", retrieval_min_similarity=0.80, ocr_provider=ocr,
                        ocr_languages="kor+eng", job_execution="worker", job_poll_seconds=1.0,
                        rate_limit_search_per_minute=1000, rate_limit_ingest_per_minute=1000,
                        rate_limit_public_per_minute=1000, board_max_items=5)
    app = create_app(settings, store=SupabaseStore(settings), storage=MemoryFileStorage())
    tag = uuid.uuid4().hex[:6]
    users = {}
    for role in ("admin", "supporter"):
        uid = str(uuid.uuid4())
        sql(f"insert into auth.users (id, email) values ('{uid}', 'e2e-{role}-{tag}@example.test')")
        sql(f"update public.profiles set role = '{role}', display_name = 'E2E {role}' where id = '{uid}'")
        users[role] = uid

    def auth(role: str) -> dict[str, str]:
        tok = jwt.encode({"sub": users[role], "aud": "authenticated", "exp": int(time.time()) + 7200}, SECRET, algorithm="HS256")
        return {"Authorization": f"Bearer {tok}"}

    with TestClient(app) as c:  # runs the lifespan -> starts the persistent job worker
        svc = app.state.services
        log("environment", embedding=svc.embedder.model_id, ocr=svc.intake.ocr_status(), job_execution=settings.job_execution)

        def wait(job_id: str, timeout: float = 600) -> dict:  # type: ignore[type-arg]
            t0 = time.time()
            while time.time() - t0 < timeout:
                j = c.get(f"/api/v1/admin/ingestion-jobs/{job_id}", headers=auth("admin")).json()
                if j["status"] in ("succeeded", "failed"):
                    return j
                time.sleep(1.5)
            raise TimeoutError(job_id)

        def get_or_create(body: dict) -> dict:  # type: ignore[type-arg]
            r = c.post("/api/v1/admin/sources", headers=auth("admin"), json=body)
            if r.status_code == 201:
                return r.json()
            assert r.status_code == 409, r.text  # already registered (e.g. by the seed): reuse it
            items = c.get("/api/v1/admin/sources", headers=auth("admin"), params={"q": body["original_url"][:150],
                                                                                 "source_type": body["source_type"]}).json()
            src = next(x for x in items["items"] if x["original_url"] == body["original_url"])
            log("reuse_registered_source", id=src["id"], title=src["title"])
            return src

        def approve(vid: str) -> int:
            return c.post(f"/api/v1/admin/versions/{vid}/approve", headers=auth("admin"), json={"note": "E2E review"}).status_code

        # ---------------------------------------------------------------- Test 1: government website
        v = c.post("/api/v1/admin/sources/validate-url", headers=auth("admin"), json={"url": STUDY}).json()
        log("t1.validate_url", ok=v["ok"], checks=[(x["name"], x["ok"]) for x in v["checks"]])
        pv = c.post("/api/v1/admin/sources/preview", headers=auth("admin"), json={"url": STUDY, "language": "ko"}).json()
        log("t1.preview", title=pv.get("title"), chars=pv.get("content_chars"), chunks=pv.get("estimated_chunks"),
            stored_sources=c.get("/api/v1/admin/sources", headers=auth("admin")).json()["total"])
        src = get_or_create(dict(
            title="Study in Korea – Visa and Stay", original_url=STUDY, organization="Study in Korea (NIIED)",
            source_type="website", authority_type="official_government", scope="national", category="visa-immigration",
            language="ko", sync_frequency="weekly"))
        job = wait(c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=auth("admin")).json()["job_id"])
        log("t1.ingest", status=job["status"], outcome=job["outcome"], attempts=job["attempts"],
            stats={k: job["statistics"].get(k) for k in ("content_chars", "chunk_count", "embedded_chunks", "embedding_ms")})
        pending_hits = c.post("/api/v1/knowledge/search", json={"query": "D-2 visa documents", "top_k": 20}).json()["results"]
        log("t1.pending_not_public", pending_version_in_results=any(h["version_id"] == job["version_id"] for h in pending_hits),
            other_results=len(pending_hits))
        log("t1.approve", http=approve(job["version_id"]))
        job2 = wait(c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=auth("admin")).json()["job_id"])
        log("t1.reingest", outcome=job2["outcome"])

        # ---------------------------------------------------------------- Test 2: SCH notice board
        bsrc = get_or_create(dict(
            title="SCH 유학생 공지사항 (International student notices)", original_url=BOARD, organization="순천향대학교 국제교육교류처",
            source_type="sch_board", authority_type="official_university", scope="university",
            category="university-announcements", language="ko", sync_frequency="daily",
            config={"max_items": 5, "max_pages": 1}))
        bjob = wait(c.post(f"/api/v1/admin/sources/{bsrc['id']}/ingest", headers=auth("admin")).json()["job_id"])
        st = bjob["statistics"]
        log("t2.board_sync", status=bjob["status"], outcome=bjob["outcome"], found=st.get("items_found"),
            new=st.get("items_new"), failed=st.get("items_failed"),
            notices=[(n["notice_no"], n["title"][:40]) for n in st.get("notices", [])])
        for n in st.get("notices", []):
            if n["outcome"] == "new_version":
                approve(n["version_id"])
        bjob2 = wait(c.post(f"/api/v1/admin/sources/{bsrc['id']}/ingest", headers=auth("admin")).json()["job_id"])
        log("t2.board_resync", outcome=bjob2["outcome"], unchanged=bjob2["statistics"].get("items_unchanged"))
        events = c.get(f"/api/v1/admin/ingestion-jobs/{bjob['id']}/events", headers=auth("admin")).json()["items"]
        log("t2.events", count=len(events), steps=sorted({e["step"] for e in events}))

        # ---------------------------------------------------------------- Test 3: official PDF upload
        docs = c.get(f"/api/v1/admin/sources/{bsrc['id']}", headers=auth("admin")).json()["documents"]
        pdf_bytes, pdf_name = None, None
        for d in docs:
            detail = c.get(f"/api/v1/admin/documents/{d['id']}", headers=auth("admin")).json()
            for a in (detail.get("metadata") or {}).get("attachments") or []:
                if a["name"].lower().endswith(".pdf"):
                    try:
                        res = svc.ingestion.fetcher.fetch(a["url"], "ko")  # guarded fetch (allowlist, robots, SSRF)
                    except Exception as exc:  # noqa: BLE001
                        log("t3.attachment_fetch_failed", name=a["name"], error=str(exc)[:200])
                        continue
                    if res.content.startswith(b"%PDF-"):
                        pdf_bytes, pdf_name = res.content, a["name"]
                        break
            if pdf_bytes:
                break
        if pdf_bytes:
            meta = dict(title=pdf_name.rsplit(".", 1)[0], organization="순천향대학교 국제교육교류처", category="dormitory-housing",
                        scope="university", authority_type="official_university", language="ko")
            r = c.post("/api/v1/admin/intake/document", headers=auth("admin"),
                       files={"file": ("attachment.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
                       data={"metadata": json.dumps(meta)})
            log("t3.upload", http=r.status_code, size=len(pdf_bytes), name=pdf_name)
            if r.status_code == 202:
                pj = wait(r.json()["job_id"])
                log("t3.extract", status=pj["status"], outcome=pj.get("outcome"), error=pj.get("error_code"),
                    stats={k: pj["statistics"].get(k) for k in ("content_chars", "chunk_count", "embedded_chunks")})
                if pj["status"] == "succeeded":
                    ver = c.get(f"/api/v1/admin/versions/{pj['version_id']}", headers=auth("admin")).json()
                    log("t3.version", pages=ver["extraction_meta"].get("pages"), extractor=ver["extraction_meta"].get("extractor"),
                        page_markers=ver["extracted_text"].count("[Page "), needs_confirm=ver["requires_field_confirmation"],
                        preview=ver["extracted_text"][:300])
                    if ver["requires_field_confirmation"]:
                        c.patch(f"/api/v1/admin/versions/{pj['version_id']}", headers=auth("admin"), json={"fields_confirmed": True})
                    log("t3.approve", http=approve(pj["version_id"]))
                    orig = c.get(f"/api/v1/admin/versions/{pj['version_id']}/original", headers=auth("admin"))
                    log("t3.original_stored", identical=orig.content == pdf_bytes)
                dup = c.post("/api/v1/admin/intake/document", headers=auth("admin"),
                             files={"file": ("again.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
                             data={"metadata": json.dumps(meta)})
                log("t3.duplicate_upload", http=dup.status_code)
        else:
            log("t3.no_pdf_attachment_found")

        # ---------------------------------------------------------------- Test 4: screenshot of an official notice
        notice_text = None
        for d in docs:
            detail = c.get(f"/api/v1/admin/documents/{d['id']}", headers=auth("admin")).json()
            cur = detail.get("current_version") or detail.get("pending_version")
            if cur and len(cur["extracted_text"]) > 200:
                lines = [ln for ln in cur["extracted_text"].splitlines() if ln.strip() and "http" not in ln]
                notice_text = "\n".join(lines[:12])
                notice_title = detail["title"]
                break
        if notice_text:
            import pymupdf

            font = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
            page_doc = pymupdf.open()
            page = page_doc.new_page(width=900, height=1300)
            rc = page.insert_textbox(pymupdf.Rect(40, 40, 860, 1260), notice_text.replace("# ", ""), fontsize=18,
                                     fontfile=font, fontname="sdgothic")
            assert rc >= 0, f"rendered text did not fit ({rc})"  # otherwise PyMuPDF draws nothing
            png = page.get_pixmap(dpi=110).tobytes("png")
            sm = dict(title=f"[screenshot] {notice_title[:60]}", organization="순천향대학교 국제교육교류처",
                      category="university-announcements", scope="university", authority_type="staff_communication", language="ko")
            r = c.post("/api/v1/admin/intake/screenshot", headers=auth("supporter"),
                       files={"file": ("notice.png", io.BytesIO(png), "image/png")},
                       data={"metadata": json.dumps(sm), "authorized_for_distribution": "true"})
            body = r.json()
            ocr_text = body.get("ocr", {}).get("text", "")
            import difflib

            ratio = difflib.SequenceMatcher(None, ocr_text.replace(" ", ""), notice_text.replace("# ", "").replace(" ", "")).ratio()
            log("t4.ocr", http=r.status_code, provider=body.get("ocr", {}).get("provider"),
                available=body.get("ocr", {}).get("available"), chars=len(ocr_text),
                mean_confidence=body.get("ocr", {}).get("mean_confidence"), similarity_to_source=round(ratio, 3),
                uncertain_lines=len(body.get("ocr", {}).get("uncertain_lines", [])), ocr_preview=ocr_text[:250])
            corrected = notice_text.replace("# ", "")  # the supporter corrects OCR errors against the image
            sub = c.post(f"/api/v1/admin/intake/screenshot/{body['job']['id']}/submit", headers=auth("supporter"),
                         json=dict(title=sm["title"], text=corrected, submit=True)).json()
            vid = sub["version_id"]
            log("t4.submitted", status=sub["status"], outcome=sub["outcome"])
            hits = c.post("/api/v1/knowledge/search", json={"query": notice_title[:30]}).json()["results"]
            log("t4.unapproved_excluded", screenshot_in_results=any(h["version_id"] == vid for h in hits))
            log("t4.approve_without_confirmation", http=approve(vid))
            c.patch(f"/api/v1/admin/versions/{vid}", headers=auth("admin"), json={"fields_confirmed": True})
            log("t4.approve_after_confirmation", http=approve(vid))
            ver = c.get(f"/api/v1/admin/versions/{vid}", headers=auth("admin")).json()
            log("t4.evidence", raw_ocr_kept=ver["raw_text"] == (ocr_text or None), corrected_differs=ver["raw_text"] != ver["extracted_text"])

        # ---------------------------------------------------------------- Test 5: multilingual retrieval
        for q in ("What documents do I need for a D-2 student visa?", "What is a D-2 visa?", "D-2 비자는 무엇인가요?",
                  "Apa itu visa D-2?", "Visa D-2 là gì?", "D-2签证是什么？", "방학 중 짐 보관", "dormitory luggage storage during vacation"):
            res = c.post("/api/v1/knowledge/search", json={"query": q, "top_k": 3}).json()
            top = [dict(title=r["document_title"][:60], heading=(r.get("heading") or "")[:50], similarity=round(r["similarity"], 3)
                        if r.get("similarity") is not None else None, exact=r["exact_match"], url=r["source_url"],
                        passage=r["passage"][:160].replace("\n", " ")) for r in res["results"]]
            report["searches"].append(dict(query=q, mode=res["retrieval"]["mode"], exact_terms=res["retrieval"]["exact_terms"],
                                           top=top))
            print(f"\nQ: {q}  [{res['retrieval']['mode']}, exact={res['retrieval']['exact_terms']}]")
            for t in top:
                print(f"   {t['similarity']}  {t['title']} | {t['heading']}\n      {t['passage'][:120]}")

        stats = c.get("/api/v1/admin/knowledge/stats", headers=auth("admin")).json()
        log("final.stats", **{k: stats[k] for k in ("sources_total", "sources_active", "sources_failed", "versions_pending",
                                                     "versions_draft", "documents_approved", "jobs_failed", "searchable_chunks")})
        report["counts_sql"] = sql(
            "select json_build_object('chunks', (select count(*) from document_chunks), 'embedded', "
            "(select count(*) from document_chunks where embedding is not null), 'versions', (select count(*) from document_versions), "
            "'approved', (select count(*) from document_versions where verification_status='approved'), "
            "'jobs', (select count(*) from ingestion_jobs), 'jobs_failed', (select count(*) from ingestion_jobs where status='failed'))")
        print("\nSQL counts:", report["counts_sql"])
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

from app.repositories.base import Query
from tests.conftest import ARTICLE_HTML, ARTICLE_URL

ADMIN_NAME = "admin"


def website_source(env, url=ARTICLE_URL, **kw):
    r = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Study in Korea - Visa", original_url=url, organization="Study in Korea", source_type="website",
        authority_type="official_government", scope="national", category="visa-immigration", language="en", **kw))
    assert r.status_code == 201, r.text
    return r.json()


def ingest(env, source_id):
    r = env.client.post(f"/api/v1/admin/sources/{source_id}/ingest", headers=env.auth("admin"))
    assert r.status_code == 202, r.text
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    return job


def versions(env):
    rows, _ = env.store.select("document_versions", Query(order=[("version_number", False)]))
    return rows


def test_first_ingestion_creates_pending_version_with_chunks_and_embeddings(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    job = ingest(env, src["id"])
    assert job["status"] == "succeeded" and job["outcome"] == "new_version", job
    assert job["statistics"]["chunk_count"] >= 1 and job["statistics"]["embedded_chunks"] == job["statistics"]["chunk_count"]
    (v,) = versions(env)
    assert v["verification_status"] == "pending_review" and v["version_number"] == 1
    assert v["extracted_text"].startswith("#") and "Alien registration" in v["extracted_text"]
    chunks, _ = env.store.select("document_chunks")
    assert all(c["embedding"] is not None and c["embedding_model"] == "hash-dev-384" and len(c["embedding"]) == 384
               for c in chunks)
    refreshed = env.client.get(f"/api/v1/admin/sources/{src['id']}", headers=env.auth("admin")).json()
    assert refreshed["status"] == "pending_review" and refreshed["last_checked_at"]
    assert refreshed["last_ingestion_result"]["outcome"] == "new_version"
    # nothing is public yet
    assert env.client.get("/api/v1/knowledge/documents").json()["total"] == 0


def test_same_content_does_not_create_a_new_version(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    ingest(env, src["id"])
    job2 = ingest(env, src["id"])
    assert job2["outcome"] == "unchanged"
    assert len(versions(env)) == 1
    docs, _ = env.store.select("source_documents")
    assert len(docs) == 1  # dedup: same canonical URL => same document


def test_whitespace_only_change_is_not_a_new_version(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    ingest(env, src["id"])
    env.page(ARTICLE_URL, ARTICLE_HTML.replace("<p>", "<p>   ").replace("</p>", "  \n\n\n</p>"))
    assert ingest(env, src["id"])["outcome"] == "unchanged"


def approve(env, version_id, role="admin"):
    return env.client.post(f"/api/v1/admin/versions/{version_id}/approve", headers=env.auth(role), json={})


def test_changed_content_creates_new_pending_version_and_keeps_approved_one(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    ingest(env, src["id"])
    v1 = versions(env)[0]
    assert approve(env, v1["id"]).status_code == 200

    env.page(ARTICLE_URL, ARTICLE_HTML.replace("Passport", "Passport and ARC fee receipt"))
    job = ingest(env, src["id"])
    assert job["outcome"] == "new_version"
    vs = versions(env)
    assert [(v["version_number"], v["verification_status"]) for v in vs] == [(1, "approved"), (2, "pending_review")]
    # the approved text is untouched and still the current version
    assert vs[0]["extracted_text"] == v1["extracted_text"]
    doc, _ = env.store.select("source_documents")
    assert doc[0]["current_version_id"] == v1["id"]
    detail = env.client.get(f"/api/v1/admin/documents/{doc[0]['id']}", headers=env.auth("admin")).json()
    assert detail["current_version"]["id"] == v1["id"] and detail["pending_version"]["id"] == vs[1]["id"]
    assert detail["diff"]["added_count"] >= 1 and "ARC fee receipt" in "\n".join(detail["diff"]["added_lines"])
    # public readers still get the OLD approved content
    pub = env.client.get(f"/api/v1/knowledge/documents/{doc[0]['id']}").json()
    assert pub["version_number"] == 1 and "ARC fee receipt" not in pub["content"]


def test_newer_extraction_supersedes_unreviewed_pending_version(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    ingest(env, src["id"])
    env.page(ARTICLE_URL, ARTICLE_HTML.replace("Photo", "Two photos"))
    ingest(env, src["id"])
    assert [(v["version_number"], v["verification_status"]) for v in versions(env)] == [(1, "superseded"), (2, "pending_review")]


def test_failed_refetch_keeps_last_approved_version_and_records_error(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    ingest(env, src["id"])
    approve(env, versions(env)[0]["id"])
    env.page(ARTICLE_URL, "blocked", status=403)
    job = ingest(env, src["id"])
    assert job["status"] == "failed" and job["error_code"] == "http_403" and "bypass" in job["error_message"]
    assert [v["verification_status"] for v in versions(env)] == ["approved"]
    s = env.client.get(f"/api/v1/admin/sources/{src['id']}", headers=env.auth("admin")).json()
    assert s["status"] == "blocked" and s["last_ingestion_result"]["status"] == "failed"  # 403 = site refuses access
    docs = env.client.get("/api/v1/knowledge/documents").json()
    assert docs["total"] == 1  # still served


def test_empty_page_fails_instead_of_creating_empty_content(env):
    env.page(ARTICLE_URL, "<html><body><nav>menu</nav></body></html>")
    src = website_source(env)
    job = ingest(env, src["id"])
    assert job["status"] == "failed" and job["error_code"] == "empty_extraction"
    assert versions(env) == []


def test_ingestion_is_blocked_for_disabled_sources_and_non_website_sources(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    assert env.client.post(f"/api/v1/admin/sources/{src['id']}/disable", headers=env.auth("admin")).json()["status"] == "inactive"
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin"))
    assert r.status_code == 409
    manual = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Manual", organization="Org", source_type="manual_text", authority_type="other", scope="national",
        category="daily-living")).json()
    r = env.client.post(f"/api/v1/admin/sources/{manual['id']}/ingest", headers=env.auth("admin"))
    assert r.status_code == 409 and "submit" in r.json()["error"]["message"].lower()


def test_register_rejects_non_allowlisted_and_duplicate_urls(env):
    r = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Evil", original_url="http://169.254.169.254/", organization="x", source_type="website",
        authority_type="other", scope="national", category="daily-living"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "url_not_allowed"
    r = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Evil", original_url="https://evil.example.com/x", organization="x", source_type="website",
        authority_type="other", scope="national", category="daily-living"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "url_not_allowed"
    website_source(env)
    r = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Dup", original_url=ARTICLE_URL, organization="x", source_type="website",
        authority_type="official_government", scope="national", category="visa-immigration"))
    assert r.status_code == 409


def test_source_validation_rules(env):
    base = dict(title="t", organization="o", authority_type="other", scope="national", category="daily-living")
    cases = [
        dict(source_type="website"),  # no url
        dict(source_type="pdf", sync_frequency="daily"),
        dict(source_type="manual_text", category="not-a-category"),
        dict(source_type="kakao_message", authority_type="official_government"),
    ]
    for extra in cases:
        r = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json={**base, **extra})
        assert r.status_code == 422, extra


def test_manual_text_submission_and_dedup_by_title(env):
    src = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="SCH test notices (TEST DATA)", organization="SCH", source_type="manual_text", authority_type="official_university",
        scope="university", category="university-announcements", language="ko", )).json()
    body = dict(title="테스트 공지", text="이것은 테스트 공지 본문입니다. 실제 공지가 아닙니다.")
    r1 = env.client.post(f"/api/v1/admin/sources/{src['id']}/submit-text", headers=env.auth("admin"), json=body)
    assert r1.status_code == 201 and r1.json()["outcome"] == "new_version"
    r2 = env.client.post(f"/api/v1/admin/sources/{src['id']}/submit-text", headers=env.auth("admin"), json=body)
    assert r2.json()["outcome"] == "unchanged"
    r3 = env.client.post(f"/api/v1/admin/sources/{src['id']}/submit-text", headers=env.auth("admin"),
                         json={**body, "text": body["text"] + " 수정됨."})
    assert r3.json()["outcome"] == "new_version"
    docs, _ = env.store.select("source_documents")
    assert len(docs) == 1 and len(versions(env)) == 2


def test_kakao_requires_authorization_and_redacts(env):
    src = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Kakao", organization="SCH Global Supporters", source_type="kakao_message",
        authority_type="supporter_submitted", scope="university", category="university-announcements")).json()
    body = dict(title="공지", text="[홍길동] [오후 3:21] 신청 안내 문의 010-1234-5678 로 연락 주세요 감사합니다")
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/submit-text", headers=env.auth("admin"), json=body)
    assert r.status_code == 422
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/submit-text", headers=env.auth("admin"),
                        json={**body, "authorized_by_supporter": True})
    assert r.status_code == 201 and r.json()["statistics"]["redactions"]["phones"] == 1
    text = versions(env)[0]["extracted_text"]
    assert "홍길동" not in text and "010-1234-5678" not in text


def test_pdf_upload_flow_stores_private_file_and_creates_version(env):
    import pymupdf as fitz

    d = fitz.open()
    d.new_page().insert_text((72, 100), "Scholarship application guide with readable text content.")
    pdf = d.tobytes()
    src = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Guide PDF", organization="Org", source_type="pdf", authority_type="official_university",
        scope="university", category="scholarships", language="en")).json()
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/upload", headers=env.auth("admin"),
                        files={"file": ("guide.pdf", pdf, "application/pdf")})
    assert r.status_code == 202, r.text
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['job_id']}", headers=env.auth("admin")).json()
    assert job["status"] == "succeeded" and job["outcome"] == "new_version"
    assert len(env.storage.files) == 1 and next(iter(env.storage.files)).startswith(f"sources/{src['id']}/")
    # bad type / spoofed file
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/upload", headers=env.auth("admin"),
                        files={"file": ("guide.pdf", b"<html>nope</html>", "application/pdf")})
    assert r.status_code == 415
    r = env.client.post(f"/api/v1/admin/sources/{src['id']}/upload", headers=env.auth("admin"),
                        files={"file": ("guide.exe", pdf, "application/pdf")})
    assert r.status_code == 415
    assert len(env.storage.files) == 1  # rejected files are never stored


def test_embedding_failure_is_reported_and_blocks_approval_until_reprocess(env):
    from app.services.embeddings.base import EmbeddingError

    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    original = env.embedder.embed_passages

    def boom(texts):
        raise EmbeddingError("model download failed")

    env.embedder.embed_passages = boom  # type: ignore[method-assign]
    job = ingest(env, src["id"])
    assert job["status"] == "succeeded" and job["error_code"] == "embedding_unavailable"
    v = versions(env)[0]
    r = approve(env, v["id"])
    assert r.status_code == 503 and r.json()["error"]["code"] == "embedding_unavailable"
    env.embedder.embed_passages = original  # type: ignore[method-assign]
    assert env.client.post(f"/api/v1/admin/versions/{v['id']}/reprocess", headers=env.auth("admin")).status_code == 200
    assert approve(env, v["id"]).status_code == 200


def test_reprocess_reuses_unchanged_embeddings(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    ingest(env, src["id"])
    v = versions(env)[0]
    calls = []
    original = env.embedder.embed_passages
    env.embedder.embed_passages = lambda texts: calls.append(len(texts)) or original(texts)  # type: ignore[method-assign]
    assert env.client.post(f"/api/v1/admin/versions/{v['id']}/reprocess", headers=env.auth("admin")).status_code == 200
    assert calls == []  # nothing needed re-embedding


def test_rollback_and_cancel(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    ingest(env, src["id"])
    v1 = versions(env)[0]
    approve(env, v1["id"])
    env.page(ARTICLE_URL, ARTICLE_HTML.replace("Photo", "Photograph"))
    ingest(env, src["id"])
    v2 = versions(env)[1]
    assert approve(env, v2["id"]).status_code == 200
    doc_id = v1["document_id"]
    assert env.client.get(f"/api/v1/knowledge/documents/{doc_id}").json()["version_number"] == 2
    r = env.client.post(f"/api/v1/admin/documents/{doc_id}/rollback", headers=env.auth("admin"), json={"version_id": v1["id"]})
    assert r.status_code == 200 and r.json()["current_version"]["id"] == v1["id"]
    assert env.client.get(f"/api/v1/knowledge/documents/{doc_id}").json()["version_number"] == 1
    # cannot "roll back" to a version that was never approved
    ingest(env, src["id"])  # same as v2 content => unchanged, no new version
    r = env.client.post(f"/api/v1/admin/documents/{doc_id}/cancel", headers=env.auth("admin"), json={"reason": "withdrawn"})
    assert r.status_code == 200 and r.json()["is_canceled"] is True
    assert env.client.get(f"/api/v1/knowledge/documents/{doc_id}").status_code == 404


def test_reject_requires_reason_and_keeps_history(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env)
    ingest(env, src["id"])
    v = versions(env)[0]
    assert env.client.post(f"/api/v1/admin/versions/{v['id']}/reject", headers=env.auth("admin"), json={}).status_code == 422
    r = env.client.post(f"/api/v1/admin/versions/{v['id']}/reject", headers=env.auth("admin"), json={"reason": "wrong page"})
    assert r.status_code == 200 and r.json()["verification_status"] == "rejected"
    # re-fetching identical content does not resurrect a rejected version
    assert ingest(env, src["id"])["outcome"] == "unchanged"
    audit = env.client.get("/api/v1/admin/audit-log", headers=env.auth("admin")).json()
    assert any(a["action"] == "version.reject" for a in audit["items"])


def test_interrupted_jobs_are_marked_failed_on_recovery(env):
    src = website_source(env)
    job = env.store.insert("ingestion_jobs", dict(source_id=src["id"], status="running"))
    assert env.app.state.services.ingestion.recover_interrupted_jobs() == 1
    j = env.client.get(f"/api/v1/admin/ingestion-jobs/{job['id']}", headers=env.auth("admin")).json()
    assert j["status"] == "failed" and j["error_code"] == "interrupted"
    r = env.client.post(f"/api/v1/admin/ingestion-jobs/{job['id']}/retry", headers=env.auth("admin"))
    assert r.status_code == 202


def test_due_sources_for_scheduled_sync(env):
    from datetime import UTC, datetime, timedelta

    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = website_source(env, sync_frequency="daily")
    svc = env.app.state.services.ingestion
    assert [s["id"] for s in svc.due_sources()] == [src["id"]]  # never checked
    env.store.update("knowledge_sources", {"last_checked_at": datetime.now(UTC).isoformat()}, {"id": src["id"]})
    assert svc.due_sources() == []
    assert len(svc.due_sources(datetime.now(UTC) + timedelta(days=1, minutes=1))) == 1

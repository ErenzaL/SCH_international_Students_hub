from app.repositories.base import Query
from app.services.retrieval.service import query_tokens
from tests.conftest import ARTICLE_HTML, ARTICLE_URL, make_settings


def make_doc(env, title, text, *, category="visa-immigration", scope="national", approve=True, org="Org",
             url=None, language="en", source_type="manual_text", authority="official_government"):
    src = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title=f"src {title}", organization=org, source_type=source_type, authority_type=authority, scope=scope,
        category=category, language=language, original_url=url)).json()
    job = env.client.post(f"/api/v1/admin/sources/{src['id']}/submit-text", headers=env.auth("admin"),
                          json=dict(title=title, text=text, authorized_by_supporter=True)).json()
    assert job["status"] == "succeeded", job
    if approve:
        r = env.client.post(f"/api/v1/admin/versions/{job['version_id']}/approve", headers=env.auth("admin"), json={})
        assert r.status_code == 200, r.text
    return job


def search(env, query, **kw):
    r = env.client.post("/api/v1/knowledge/search", json=dict(query=query, **kw))
    assert r.status_code == 200, r.text
    return r.json()


def test_query_tokenization_handles_korean_particles_and_stopwords():
    assert "외국인등록증" in query_tokens("외국인등록증을 신청")
    assert query_tokens("how do I extend a D-2 visa") == ["extend", "visa"]  # 'D'/'2' too short
    assert "izin" in query_tokens("izin kerja paruh waktu mahasiswa")


def test_only_approved_content_is_returned(env):
    make_doc(env, "Approved doc", "TOPIK registration opens online each exam cycle. Register on the official site.",
             category="topik-korean")
    make_doc(env, "Pending doc", "TOPIK registration secret pending text should never appear.", category="topik-korean",
             approve=False)
    res = search(env, "TOPIK registration")
    assert [r["document_title"] for r in res["results"]] == ["Approved doc"]
    assert "pending" not in res["results"][0]["passage"]


def test_results_carry_accurate_citations(env):
    env.page(ARTICLE_URL, ARTICLE_HTML)
    src = env.client.post("/api/v1/admin/sources", headers=env.auth("admin"), json=dict(
        title="Study in Korea - Visa", original_url=ARTICLE_URL, organization="Study in Korea (NIIED)",
        source_type="website", authority_type="official_government", scope="national", category="visa-immigration",
        language="en")).json()
    jid = env.client.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=env.auth("admin")).json()["job_id"]
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{jid}", headers=env.auth("admin")).json()
    assert env.client.post(f"/api/v1/admin/versions/{job['version_id']}/approve", headers=env.auth("admin"),
                           json={}).status_code == 200
    res = search(env, "alien registration immigration office")
    top = res["results"][0]
    assert top["source_url"] == ARTICLE_URL  # exact registered URL preserved
    assert top["organization"] == "Study in Korea (NIIED)" and top["scope"] == "national"
    assert top["document_id"] == job["document_id"] and top["version_id"] == job["version_id"]
    assert top["verified_at"] and top["category"] == "visa-immigration" and top["score"] > 0
    assert res["retrieval"]["mode"] == "hybrid" and res["retrieval"]["embedding_model"] == "hash-dev-384"


def test_multilingual_queries_against_one_corpus(env):
    make_doc(env, "D-2 visa extension", "To extend a D-2 visa, apply for extension of stay at the immigration office.",
             category="visa-immigration")
    make_doc(env, "외국인등록증 신청", "외국인등록증 신청은 입국 후 90일 이내에 출입국 사무소에서 해야 합니다.",
             category="visa-immigration", language="ko")
    make_doc(env, "Izin kerja paruh waktu", "Mahasiswa asing perlu izin kerja paruh waktu sebelum bekerja.",
             category="part-time-employment", language="id")
    make_doc(env, "TOPIK registration", "TOPIK registration is done online during the application period.",
             category="topik-korean")
    assert search(env, "D-2 visa extension")["results"][0]["document_title"] == "D-2 visa extension"
    assert search(env, "외국인등록증 신청")["results"][0]["document_title"] == "외국인등록증 신청"
    assert search(env, "외국인등록증을 어떻게 신청하나요")["results"][0]["document_title"] == "외국인등록증 신청"
    assert search(env, "izin kerja paruh waktu mahasiswa")["results"][0]["document_title"] == "Izin kerja paruh waktu"
    assert search(env, "TOPIK registration")["results"][0]["document_title"] == "TOPIK registration"


def test_no_evidence_returns_empty_results(env):
    make_doc(env, "Doc", "Completely unrelated content about libraries and books.", category="academic-life")
    assert search(env, "quantum chromodynamics lattice", mode="keyword")["results"] == []
    assert search(env, "anything")["retrieval"]["total"] >= 0
    empty = TestClientless(env)
    assert empty["results"] == []


def TestClientless(env):  # empty corpus
    from tests.conftest import Env

    fresh = Env()
    return search(fresh, "visa")


def test_category_filter_and_top_k_limits(env):
    for i in range(6):
        make_doc(env, f"Visa doc {i}", f"Visa information page number {i} with distinct words item{i}.",
                 category="visa-immigration")
    make_doc(env, "Health doc", "Visa related health insurance note.", category="health-insurance")
    assert {r["category"] for r in search(env, "visa", category="health-insurance")["results"]} == {"health-insurance"}
    assert len(search(env, "visa", top_k=3)["results"]) == 3
    assert env.client.post("/api/v1/knowledge/search", json=dict(query="visa", top_k=21)).status_code == 422
    assert env.client.post("/api/v1/knowledge/search", json=dict(query="visa", top_k=0)).status_code == 422
    assert env.client.post("/api/v1/knowledge/search", json=dict(query="")).status_code == 422
    assert env.client.post("/api/v1/knowledge/search", json=dict(query="x" * 501)).status_code == 422
    assert env.client.post("/api/v1/knowledge/search", json=dict(query="visa", category="nope")).status_code == 422


def test_canceled_expired_and_inactive_sources_are_not_searchable(env):
    j1 = make_doc(env, "Canceled doc", "Canceled content mentioning scholarship", category="scholarships")
    j2 = make_doc(env, "Expired doc", "Expired content mentioning scholarship", category="scholarships")
    j3 = make_doc(env, "Inactive doc", "Inactive source content mentioning scholarship", category="scholarships")
    make_doc(env, "Live doc", "Live content mentioning scholarship", category="scholarships")
    env.client.post(f"/api/v1/admin/documents/{j1['document_id']}/cancel", headers=env.auth("admin"), json={"reason": "withdrawn"})
    env.store.update("document_versions", {"valid_from": "2020-01-01T00:00:00+00:00", "valid_until": "2020-02-01T00:00:00+00:00"},
                     {"id": j2["version_id"]})
    env.client.post(f"/api/v1/admin/sources/{j3['source_id']}/disable", headers=env.auth("admin"))
    titles = [r["document_title"] for r in search(env, "scholarship")["results"]]
    assert titles == ["Live doc"]


def test_embedding_failure_falls_back_to_keyword_with_honest_warning(env):
    from app.services.embeddings.base import EmbeddingError

    make_doc(env, "Doc", "Insurance enrollment information for students.", category="health-insurance")

    def boom(text):
        raise EmbeddingError("model missing")

    env.embedder.embed_query = boom  # type: ignore[method-assign]
    res = search(env, "insurance enrollment")
    assert res["retrieval"]["mode"] == "keyword" and "unavailable" in res["retrieval"]["warning"]
    assert res["results"] and res["results"][0]["similarity"] is None
    r = env.client.post("/api/v1/knowledge/search", json=dict(query="insurance", mode="vector"))
    assert r.status_code == 503 and r.json()["error"]["code"] == "embedding_unavailable"


def test_vectors_from_a_different_model_are_ignored(env):
    make_doc(env, "Doc", "Banking information for opening an account.", category="banking-taxes")
    env.store.update("document_chunks", {"embedding_model": "some-other-model"}, {})
    res = search(env, "banking account", mode="vector")
    assert res["results"] == []


def test_min_similarity_threshold_drops_semantic_only_noise(env):
    make_doc(env, "Doc", "Dormitory application guide for new students.", category="dormitory-housing")
    env.app.state.services.retrieval.settings = make_settings(retrieval_min_similarity=0.99)
    res = search(env, "zebra", mode="vector")
    assert res["results"] == []


def test_search_is_rate_limited():
    from app.core.rate_limit import limiter
    from tests.conftest import Env

    limiter.reset()
    e = Env()
    e.app.dependency_overrides.clear()
    from app.core.config import get_settings

    e.app.dependency_overrides[get_settings] = lambda: make_settings(rate_limit_search_per_minute=2)
    codes = [e.client.post("/api/v1/knowledge/search", json=dict(query="visa")).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and codes[2:] == [429, 429]
    body = e.client.post("/api/v1/knowledge/search", json=dict(query="visa")).json()
    assert body["error"]["code"] == "rate_limited"
    limiter.reset()


_ = Query

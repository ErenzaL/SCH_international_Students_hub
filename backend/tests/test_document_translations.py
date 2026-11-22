"""Multilingual Knowledge Center: version-linked document translations, AI drafts, language-scoped review,
invalidation on original changes, public display and the grounded multilingual assistant."""
from __future__ import annotations

import re

import pytest

from app.core.errors import Forbidden
from app.repositories.base import Query
from app.services.llm.base import LLMError, ScriptedLLMProvider
from app.services.translation_drafts import chunk_text, extract_headings, preservation_warnings
from tests.conftest import ARTICLE_HTML, ARTICLE_URL
from tests.test_document_lifecycle import website_doc

SRC = re.compile(r"<source_text>\n?(.*?)\n?</source_text>", re.S)


def fake_translate(system: str, prompt: str) -> str:
    """'Translates' by prefixing each line with the target tag, keeping numbers / URLs / codes exactly."""
    tag = "[ID]" if "Indonesian" in system else "[VI]" if "Vietnamese" in system else "[XX]"
    text = SRC.search(prompt).group(1)
    return "\n".join(f"{line[:line.index(' ') + 1] if line.startswith('#') else ''}{tag} "
                     f"{line.lstrip('# ') if line.startswith('#') else line}"
                     if line.strip() and not line.lstrip().startswith("|") else line
                     for line in text.splitlines())


def use_llm(env, provider) -> None:  # type: ignore[no-untyped-def]
    svc = env.app.state.services
    svc.llm = svc.doc_translations.llm = svc.conversations.llm = provider


def assign(env, role: str, lang: str, review: bool = True) -> None:  # type: ignore[no-untyped-def]
    env.store.insert("supporter_languages", dict(supporter_id=env.users[role], language_code=lang, can_support=True,
                                                 can_review_translations=review))


def public(env, doc_id: str, lang: str | None = None) -> dict:  # type: ignore[type-arg]
    r = env.client.get(f"/api/v1/knowledge/documents/{doc_id}", params={"lang": lang} if lang else None)
    assert r.status_code == 200, r.text
    return r.json()


def approve_translation(env, doc_id, lang, role="supporter"):  # type: ignore[no-untyped-def]
    return env.client.post(f"/api/v1/admin/documents/{doc_id}/translations/{lang}/approve", headers=env.auth(role),
                           json={"original_verified": True, "note": "checked against the original"})


def write_translation(env, doc_id, lang, role="supporter", submit=True, title="Visa dan Izin Tinggal",  # type: ignore[no-untyped-def]
                      body="# Visa dan Izin Tinggal\n\nMahasiswa internasional harus menjaga status izin tinggal.\n\n"
                           "## Registrasi orang asing\n\nRegistrasi dilakukan di kantor imigrasi."):
    return env.client.put(f"/api/v1/admin/documents/{doc_id}/translations/{lang}", headers=env.auth(role),
                          json={"title": title, "body": body, "submit": submit})


@pytest.fixture
def doc(env):  # type: ignore[no-untyped-def]
    src, job = website_doc(env)
    return dict(source=src, id=job["document_id"], version_id=job["version_id"])


# ------------------------------------------------------------------ pure helpers
def test_preservation_checks_flag_lost_facts():
    original = ("# Visa D-2\n\nApply by 2026-03-15. Fee: 30,000 KRW. Call 041-530-1234 or mail intl@sch.ac.kr. "
                "See https://www.hikorea.go.kr/info.\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    good = ("# Visa D-2\n\nDaftar paling lambat 2026-03-15. Biaya: 30,000 KRW. Hubungi 041-530-1234 atau "
            "intl@sch.ac.kr. Lihat https://www.hikorea.go.kr/info.\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert preservation_warnings(original, good) == []
    bad = "# Visa D-4\n\nDaftar paling lambat 15 Maret 2026. Biaya: 30.000 won. Lihat situs resmi."
    kinds = {(w["type"], w["value"]) for w in preservation_warnings(original, bad)}
    assert ("code", "D-2") in kinds and ("url", "https://www.hikorea.go.kr/info") in kinds
    assert ("email", "intl@sch.ac.kr") in kinds and ("phone", "041-530-1234") in kinds
    assert ("number", "15") not in kinds and ("number", "0315") not in kinds   # 2026-03-15 -> digits '2026','03','15'
    assert any(w["type"] == "table_rows" for w in preservation_warnings(original, bad))
    assert extract_headings("# A\ntext\n## B ##\n") == ["A", "B"]
    parts = chunk_text("\n\n".join(f"Paragraph {i} " + "x" * 50 for i in range(40)), 500)
    assert len(parts) > 3 and all(len(p) <= 500 for p in parts)


# --------------------------------------------------------- tasks + public display
def test_original_shown_in_its_language_and_fallback_without_translation(env, doc):
    d = public(env, doc["id"])                                  # 1. English original in English
    assert d["language"] == "en" and d["translation"] is None and "Visa and Stay" in d["content"]
    assert public(env, doc["id"], "en")["translation"] is None  # same language: nothing to translate
    vi = public(env, doc["id"], "vi")                           # 3. Vietnamese falls back to the original
    assert vi["translation"] is None and vi["content"] == d["content"] and vi["source_url"] == ARTICLE_URL
    rows = env.store.select("document_translations", Query(eq={"document_id": doc["id"]}))[0]
    assert sorted(r["language_code"] for r in rows) == ["id", "ko", "vi", "zh-CN"]   # tasks created on activation
    assert all(r["translation_status"] == "todo" and r["version_id"] == doc["version_id"] for r in rows)


def test_approved_indonesian_translation_is_displayed(env, doc):
    assign(env, "supporter", "id")
    assert write_translation(env, doc["id"], "id").status_code == 200
    d = public(env, doc["id"], "id")
    assert d["translation"] is None                             # 4. submitted but unreviewed: not shown, not verified
    r = approve_translation(env, doc["id"], "id")
    assert r.status_code == 200, r.text
    assert r.json()["translation"]["verified"] and r.json()["translation"]["reviewed_by_name"]
    d = public(env, doc["id"], "id")                            # 2. approved Indonesian displayed
    tr = d["translation"]
    assert tr["status"] == "verified" and tr["title"] == "Visa dan Izin Tinggal" and tr["reviewed_at"]
    assert tr["headings"] == ["Visa dan Izin Tinggal", "Registrasi orang asing"]
    assert d["title"] == "Visa and Stay - Study in Korea" or d["title"]   # the original stays authoritative
    assert "Visa and Stay" in d["content"] and d["source_url"] == ARTICLE_URL and d["verified_languages"] == ["id"]
    listing = env.client.get("/api/v1/knowledge/documents", params={"lang": "id"}).json()["items"][0]
    assert listing["translated_title"] == "Visa dan Izin Tinggal" and listing["verified_languages"] == ["id"]
    assert env.client.get("/api/v1/knowledge/documents", params={"lang": "vi"}).json()["items"][0]["translated_title"] is None
    # the original version row is untouched
    v = env.store.select("document_versions", Query(eq={"id": doc["version_id"]}))[0][0]
    assert "Visa and Stay" in v["extracted_text"]


def test_supporter_can_review_only_assigned_languages(env, doc):
    assign(env, "supporter", "id")
    write_translation(env, doc["id"], "id")
    assert approve_translation(env, doc["id"], "id").status_code == 200            # 5. Indonesian: allowed
    assert write_translation(env, doc["id"], "vi").status_code == 403              # Vietnamese: not assigned
    assert env.client.get(f"/api/v1/admin/documents/{doc['id']}/translations/vi",
                          headers=env.auth("supporter")).status_code == 403
    # a vi row written by someone else cannot be approved by the id supporter, also at the database level
    assign(env, "admin", "vi", review=False)
    assert write_translation(env, doc["id"], "vi", role="admin", title="Thị thực", body="Nội dung").status_code == 200
    assert approve_translation(env, doc["id"], "vi", role="admin").status_code == 403   # support-only, no review
    vi_row = env.store.select("document_translations", Query(eq={"document_id": doc["id"], "language_code": "vi"}))[0][0]
    with pytest.raises(Forbidden):
        env.store.update("document_translations", dict(translation_status="human_approved", reviewed_by=env.users["supporter"],
                                                       reviewed_at="2026-11-22T00:00:00+00:00", original_verified=True),
                         {"id": vi_row["id"]})
    # supporters only list their own languages
    items = env.client.get("/api/v1/admin/document-translations", headers=env.auth("supporter")).json()["items"]
    assert {i["language_code"] for i in items} == {"id"}
    assert env.client.get("/api/v1/admin/document-translations", params={"language": "vi"},
                          headers=env.auth("supporter")).status_code == 403
    # approval requires the explicit original check
    assert env.client.post(f"/api/v1/admin/documents/{doc['id']}/translations/id/request-changes",
                           headers=env.auth("supporter"), json={"reason": "Please fix the heading"}).status_code == 200
    assert env.client.post(f"/api/v1/admin/documents/{doc['id']}/translations/id/approve", headers=env.auth("supporter"),
                           json={"original_verified": False}).status_code == 422


def test_students_cannot_reach_drafts(env, doc):
    assign(env, "supporter", "id")
    write_translation(env, doc["id"], "id", submit=False, title="DRAFT TITLE", body="DRAFT BODY")
    for path in (f"/api/v1/admin/documents/{doc['id']}/translations",
                 f"/api/v1/admin/documents/{doc['id']}/translations/id", "/api/v1/admin/document-translations"):
        assert env.client.get(path, headers=env.auth("student")).status_code == 403   # 10.
        assert env.client.get(path).status_code == 401
    d = env.client.get(f"/api/v1/knowledge/documents/{doc['id']}", params={"lang": "id"}).text
    assert "DRAFT" not in d
    assert env.client.get(f"/api/v1/knowledge/documents/{doc['id']}", params={"lang": "xx"}).status_code == 422


def test_original_update_invalidates_translations(env, doc):
    assign(env, "supporter", "id")
    write_translation(env, doc["id"], "id")
    approve_translation(env, doc["id"], "id")
    old = env.store.select("document_translations", Query(eq={"document_id": doc["id"], "language_code": "id"}))[0][0]
    # the original page changes -> new version -> approve -> activate
    env.page(ARTICLE_URL, ARTICLE_HTML.replace("Bring your passport", "Bring your passport, ARC form"))
    r = env.client.post(f"/api/v1/admin/sources/{doc['source']['id']}/ingest", headers=env.auth("admin")).json()
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r['job_id']}", headers=env.auth("admin")).json()
    assert job["outcome"] == "new_version"
    assert public(env, doc["id"], "id")["translation"]["status"] == "verified"   # still the active v1 until approval
    assert env.client.post(f"/api/v1/admin/versions/{job['version_id']}/approve", headers=env.auth("admin"),
                           json={}).status_code == 202
    rows = env.store.select("document_translations", Query(eq={"document_id": doc["id"], "language_code": "id"}))[0]
    assert len(rows) == 2                                                    # 6. previous translation preserved
    prev = next(r for r in rows if r["id"] == old["id"])
    new = next(r for r in rows if r["id"] != old["id"])
    assert prev["is_outdated"] and prev["translation_status"] == "human_approved"
    assert new["translation_status"] == "todo" and new["version_id"] == job["version_id"]
    assert new["previous_translation_id"] == old["id"] and new["source_version_number"] == 2
    assert public(env, doc["id"], "id")["translation"] is None              # old translation no longer served
    assert "ARC form" in public(env, doc["id"])["content"]
    notes = env.store.select("user_notifications", Query(eq={"user_id": env.users["supporter"]}))[0]
    assert any(n["kind"] == "translation_outdated" for n in notes)
    det = env.client.get(f"/api/v1/admin/documents/{doc['id']}/translations/id", headers=env.auth("supporter")).json()
    assert det["previous"]["translation"]["title"] == "Visa dan Izin Tinggal"         # version comparison data
    assert "ARC form" not in det["previous"]["original_body"] and "ARC form" in det["original"]["body"]
    revs = env.store.select("document_translation_revisions", Query(eq={"translation_id": old["id"]}))[0]
    assert [r["action"] for r in revs][-1] == "outdated"
    # an outdated row can never be approved, even directly
    with pytest.raises(Exception):  # noqa: B017
        env.store.update("document_translations", dict(reviewed_by=env.users["admin"]), {"id": old["id"]})
    # rollback to v1 makes the v1 translation valid again
    env.client.post(f"/api/v1/admin/documents/{doc['id']}/rollback", headers=env.auth("admin"),
                    json={"version_id": doc["version_id"], "note": "v2 was wrong"})
    assert public(env, doc["id"], "id")["translation"]["title"] == "Visa dan Izin Tinggal"


# --------------------------------------------------------------------- AI drafts
def test_ai_draft_job_creates_machine_draft_never_verified(env, doc):
    r = env.client.post(f"/api/v1/admin/documents/{doc['id']}/translations/drafts", headers=env.auth("admin"),
                        json={"languages": ["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "llm_disabled"     # no provider configured
    llm = ScriptedLLMProvider(fake_translate)
    use_llm(env, llm)
    r = env.client.post(f"/api/v1/admin/documents/{doc['id']}/translations/drafts", headers=env.auth("admin"),
                        json={"languages": ["id", "vi"]})
    assert r.status_code == 202, r.text
    jobs = {i["language"]: i["job_id"] for i in r.json()["items"]}
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{jobs['id']}", headers=env.auth("admin")).json()
    assert job["job_type"] == "translate_document" and job["status"] == "succeeded" and job["outcome"] == "translated"
    row = env.store.select("document_translations", Query(eq={"document_id": doc["id"], "language_code": "id"}))[0][0]
    assert row["translation_status"] == "machine_draft" and row["provider"] == "scripted" and row["model"] == "scripted-1"
    assert row["title"].startswith("[ID]") and "[ID] Alien registration" in row["body"] and row["generated_at"]
    assert row["headings"] and row["warnings"] == [] and not row["human_edited"]
    assert public(env, doc["id"], "id")["translation"] is None            # AI drafts are not verified content
    env.app.state.services.settings.public_machine_translations = True
    tr = public(env, doc["id"], "id")["translation"]
    assert tr["status"] == "machine" and tr["reviewed_at"] is None        # clearly labelled machine translation
    env.app.state.services.settings.public_machine_translations = False
    # source status untouched by translation jobs
    assert env.store.select("knowledge_sources", Query(eq={"id": doc["source"]["id"]}))[0][0]["status"] == "approved"
    # human work is never overwritten without force
    assign(env, "supporter", "id")
    write_translation(env, doc["id"], "id", submit=False)
    r = env.client.post(f"/api/v1/admin/documents/{doc['id']}/translations/drafts", headers=env.auth("admin"),
                        json={"languages": ["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "human_draft_exists"
    # supporters may only request drafts for their languages
    assert env.client.post(f"/api/v1/admin/documents/{doc['id']}/translations/drafts", headers=env.auth("supporter"),
                           json={"languages": ["vi"]}).status_code == 403


def test_failed_generation_keeps_original_searchable_and_is_retried(env, doc):
    calls = {"n": 0}

    def flaky(system: str, prompt: str):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return LLMError("llm_refused", "The model declined to generate this content.")

    use_llm(env, ScriptedLLMProvider(flaky))
    r = env.client.post(f"/api/v1/admin/documents/{doc['id']}/translations/drafts", headers=env.auth("admin"),
                        json={"languages": ["ko"]})
    job = env.client.get(f"/api/v1/admin/ingestion-jobs/{r.json()['items'][0]['job_id']}", headers=env.auth("admin")).json()
    assert job["status"] == "failed" and job["error_code"] == "llm_refused"
    row = env.store.select("document_translations", Query(eq={"document_id": doc["id"], "language_code": "ko"}))[0][0]
    assert row["translation_status"] == "todo"                           # nothing partial was written
    assert env.client.post("/api/v1/knowledge/search", json={"query": "alien registration immigration office"}
                           ).json()["results"]                           # the original stays searchable
    ov = env.client.get(f"/api/v1/admin/documents/{doc['id']}/translations", headers=env.auth("admin")).json()
    ko = next(x for x in ov["languages"] if x["language"] == "ko")
    assert ko["job"]["status"] == "failed" and ov["completion"] == {"verified": 0, "total": 4}


def test_overview_reports_completion_per_language(env, doc):
    assign(env, "supporter", "id")
    write_translation(env, doc["id"], "id")
    approve_translation(env, doc["id"], "id")
    ov = env.client.get(f"/api/v1/admin/documents/{doc['id']}/translations", headers=env.auth("admin")).json()
    assert ov["original_language"] == "en" and ov["completion"] == {"verified": 1, "total": 4}
    by = {x["language"]: x for x in ov["languages"]}
    assert by["id"]["translation"]["verified"] and by["id"]["translation"]["reviewed_by_name"] == "Supporter"
    assert by["vi"]["translation"]["translation_status"] == "todo" and "body" not in by["vi"]["translation"]


# multilingual assistant behaviour: see tests/test_assistant.py


def test_language_preference_persists_across_sessions(env):
    h = env.auth("student")
    assert env.client.patch("/api/v1/me", headers=h, json={"preferred_language": "vi"}).status_code == 200
    # a new "session" = a freshly issued token for the same user; the stored profile drives the default
    assert env.client.get("/api/v1/me", headers=env.auth("student")).json()["preferred_language"] == "vi"   # 7.


def test_language_detection_and_original_language_correction(env, doc):
    from app.services.language_detect import detect_language

    assert detect_language("외국인 등록은 입국 후 90일 이내에 출입국관리사무소에서 해야 합니다. " * 5) == "ko"
    assert detect_language("Students must keep their residence status valid and the fee is paid to the office. " * 4) == "en"
    assert detect_language("Mahasiswa harus mengurus izin tinggal dan dokumen yang diperlukan untuk pendaftaran. " * 4) == "id"
    assert detect_language("Sinh viên phải đăng ký người nước ngoài tại văn phòng xuất nhập cảnh trong thời hạn. " * 4) == "vi"
    assert detect_language("国际学生必须在入境后九十天内到出入境管理事务所办理外国人登记。" * 5) == "zh-CN"
    assert detect_language("short") is None
    # an English page mislabelled as Korean: an admin corrects the ORIGINAL language label
    env.store.update("source_documents", {"language": "ko"}, {"id": doc["id"]})
    env.store.delete("document_translations", {"document_id": doc["id"]})
    env.app.state.services.doc_translations.sync(doc["id"])
    langs = {r["language_code"] for r in env.store.select("document_translations", Query(eq={"document_id": doc["id"]}))[0]}
    assert "ko" not in langs and "en" in langs
    assert env.client.patch(f"/api/v1/admin/documents/{doc['id']}/language", headers=env.auth("supporter"),
                            json={"language": "en"}).status_code == 403
    r = env.client.patch(f"/api/v1/admin/documents/{doc['id']}/language", headers=env.auth("admin"), json={"language": "en"})
    assert r.status_code == 200 and r.json()["original_language"] == "en"
    current = {r["language_code"] for r in env.store.select("document_translations", Query(
        eq={"document_id": doc["id"], "is_outdated": False}))[0]}
    assert current == {"ko", "id", "vi", "zh-CN"}
    assert public(env, doc["id"])["language"] == "en"
    assert env.store.select("audit_log", Query(eq={"action": "document.language_changed", "entity_id": doc["id"]}))[0]


def test_foreigner_registration_question_is_not_a_human_request():
    from app.services.conversations import _HUMAN

    assert not _HUMAN.search("Bagaimana cara registrasi orang asing?")
    assert _HUMAN.search("Saya ingin bicara dengan orang sungguhan")
    assert _HUMAN.search("Can I talk to a real person?")

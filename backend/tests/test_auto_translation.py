"""Automatic Korean <-> English machine translation of announcements and Knowledge Center documents: durable jobs,
idempotency and caching, quota / budget deferral, restart recovery, quality checks (needs_review), risk labelling,
long-document summaries, human correction and approval, public display, and the controlled backfill."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.repositories.base import Query
from app.services.llm.base import LLMError, ScriptedLLMProvider
from app.services.translation import backfill
from app.services.translation.quality import is_high_risk, validate_summary, validate_translation
from tests.test_announcements import create
from tests.test_document_translations import assign
from tests.test_retrieval import make_doc

KO_TITLE = "장학금 신청 안내"
KO_BODY = ("장학금 신청 기간은 2026년 12월 1일부터 12월 15일까지입니다.\n\n"
           "신청서는 https://sch.ac.kr/apply 에서 제출하세요. 문의: intl@sch.ac.kr, 041-530-1234")
EN_TITLE = "Dormitory move-in guide"
EN_BODY = ("Move-in for the spring semester starts on 2027-02-24 at 10:00.\n\n"
           "Bring your passport and the dormitory contract. Questions: dorm@sch.ac.kr")


class FakeTranslator:
    """Deterministic 'model': Korean words -> 'notice', English words -> '안내'; numbers, URLs, e-mail addresses and
    structure are copied. Hooks simulate mistakes and failures."""

    def __init__(self, mutate: Any = None, fail: Exception | None = None):
        self.mutate, self.fail, self.calls = mutate, fail, 0

    def __call__(self, system: str, prompt: str) -> str:
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        src = re.search(r"<source_text>\n(.*?)\n</source_text>", prompt, re.S).group(1)  # type: ignore[union-attr]
        if system.startswith("You write short, faithful summaries"):
            return "This document is a guide for international students.\n\n- Section overview for new students"
        to_en = "into English" in prompt
        protected = re.split(r"(https?://\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+)", src)
        out = "".join(p if i % 2 else (re.sub(r"[가-힣]+", "notice", p) if to_en else re.sub(r"[A-Za-z]+", "안내", p))
                      for i, p in enumerate(protected))
        return self.mutate(out) if self.mutate else out


def use_translator(env, fake: FakeTranslator) -> ScriptedLLMProvider:  # type: ignore[no-untyped-def]
    svc = env.app.state.services
    p = ScriptedLLMProvider(fake, model="translate-1")
    svc.doc_translations.llm = svc.announcement_translator.llm = p
    env.settings.translation_fallback_to_gemini = True    # the server's own model (the path Gemini uses): opt-in
    return p


@pytest.fixture
def auto(env):  # type: ignore[no-untyped-def]
    s = env.settings
    s.auto_translate_announcements = s.auto_translate_documents = s.public_machine_translations = True
    s.auto_translate_languages = "ko,en"
    return use_translator(env, FakeTranslator())


def publish(env, **kw):  # type: ignore[no-untyped-def]
    a = create(env, submit=True, **kw)
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    assert r.status_code == 200, r.text
    return a


def ann_row(env, aid: str, lang: str) -> dict:  # type: ignore[type-arg]
    return env.store.select("announcement_translations", Query(eq={"announcement_id": aid, "language_code": lang}))[0][0]


def jobs(env, kind: str = "translate_announcement") -> list[dict]:  # type: ignore[type-arg]
    return env.store.select("ingestion_jobs", Query(eq={"job_type": kind}))[0]


def public_ann(env, aid: str, lang: str) -> dict:  # type: ignore[type-arg]
    r = env.client.get(f"/api/v1/announcements/{aid}", params={"lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------------------------- announcements
def test_korean_announcement_is_machine_translated_into_english_on_publication(env, auto):
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    en = ann_row(env, a["id"], "en")
    assert en["translation_status"] == "machine_draft" and en["provider"] == "scripted" and en["warnings"] == []
    assert "2026" in en["body"] and "https://sch.ac.kr/apply" in en["body"] and "041-530-1234" in en["body"]
    assert [j["payload"]["language"] for j in jobs(env)] == ["en"]           # only the missing language (not ko)
    # Release 1: an unreviewed machine draft of an announcement is never public, even with
    # PUBLIC_MACHINE_TRANSLATIONS on (the fixture turns it on)
    assert env.settings.public_machine_translations is True
    assert public_ann(env, a["id"], "en")["translation"] is None
    assert public_ann(env, a["id"], "ko")["translation"] is None              # the original language
    assert public_ann(env, a["id"], "en")["body"].startswith("장학금")          # the original is unchanged


def test_english_announcement_is_machine_translated_into_korean(env, auto):
    a = publish(env, title=EN_TITLE, body=EN_BODY, original_language="en")
    ko = ann_row(env, a["id"], "ko")
    assert ko["translation_status"] == "machine_draft" and "2027-02-24" in ko["body"] and "dorm@sch.ac.kr" in ko["body"]
    assert public_ann(env, a["id"], "ko")["translation"] is None              # a draft, not reviewed: not public
    listing = env.client.get("/api/v1/announcements", params={"display_language": "ko"}).json()["items"]
    assert listing[0]["display_title"] is None and listing[0]["display_title_status"] is None   # original title


def test_machine_translations_are_hidden_unless_enabled_and_never_block_publication(env, auto):
    env.settings.public_machine_translations = False
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    assert ann_row(env, a["id"], "en")["translation_status"] == "machine_draft"
    assert public_ann(env, a["id"], "en")["translation"] is None              # original shown instead
    # the LLM failing does not affect the publication either
    use_translator(env, FakeTranslator(fail=LLMError("llm_unavailable", "down", transient=True)))
    b = publish(env, title="기숙사 입사 안내", body="기숙사 입사는 3월 2일입니다.")
    assert env.client.get(f"/api/v1/announcements/{b['id']}").status_code == 200


def test_changed_original_outdates_and_regenerates_the_machine_translation(env, auto):
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    first = ann_row(env, a["id"], "en")
    env.store.update("announcements", {"title": "장학금 신청 안내 (기간 연장)"}, {"id": a["id"]})
    env.app.state.services.translations.on_original_published(a["id"], None)
    again = ann_row(env, a["id"], "en")
    assert again["source_content_hash"] != first["source_content_hash"] and not again["is_outdated"]
    assert again["translation_status"] == "machine_draft" and len(jobs(env)) == 2


def test_identical_content_is_not_translated_again(env, auto):
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    calls = auto.responder.calls
    svc = env.app.state.services
    svc.translations.on_original_published(a["id"], None)              # unchanged: nothing queued
    assert auto.responder.calls == calls and len(jobs(env)) == 1
    job = svc.announcement_translator.queue(a["id"], "en", None, enqueue=False)  # explicit request: no model call
    done = svc.ingestion.run_job(job["id"])
    assert done["status"] == "succeeded" and auto.responder.calls == calls
    # a second announcement with exactly the same text reuses the translation (cache by content hash)
    publish(env, title=KO_TITLE, body=KO_BODY, deadline=None, event_date=None)
    assert auto.responder.calls == calls


def test_failed_translation_is_retried_later_and_students_see_the_original(env, auto):
    use_translator(env, FakeTranslator(fail=LLMError("llm_unavailable", "Gemini is temporarily unavailable.",
                                                     transient=True)))
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    j = jobs(env)[0]
    assert j["status"] == "queued" and j["error_code"] == "llm_unavailable"       # retry with backoff
    assert ann_row(env, a["id"], "en")["translation_status"] == "todo"
    assert public_ann(env, a["id"], "en")["translation"] is None


def test_exhausted_quota_defers_the_job_without_using_an_attempt(env, auto):
    use_translator(env, FakeTranslator(fail=LLMError("llm_quota", "The Gemini API quota is exhausted.", transient=True)))
    publish(env, title=KO_TITLE, body=KO_BODY)
    j = jobs(env)[0]
    assert j["status"] == "queued" and j["attempts"] == 0 and j["statistics"]["deferrals"] == 1
    wait = datetime.fromisoformat(j["run_after"]) - datetime.now(UTC)
    assert timedelta(minutes=55) < wait <= timedelta(hours=1)
    ev = env.store.select("ingestion_events", Query(eq={"job_id": j["id"], "step": "deferred"}))[0]
    assert ev and "quota" in ev[0]["message"]


def test_daily_translation_budget_defers_until_tomorrow(env, auto):
    env.settings.translation_daily_job_limit = 0
    publish(env, title=KO_TITLE, body=KO_BODY)
    j = jobs(env)[0]
    assert j["status"] == "queued" and j["error_code"] == "translation_daily_limit" and auto.responder.calls == 0
    assert datetime.fromisoformat(j["run_after"]) > datetime.now(UTC) + timedelta(minutes=4)


def test_a_restart_during_translation_resumes_the_same_job(env, auto):
    env.settings.auto_translate_announcements = False
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    svc = env.app.state.services
    job = svc.announcement_translator.queue(a["id"], "en", None, enqueue=False)
    old = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    env.store.update("ingestion_jobs", dict(status="running", attempts=1, heartbeat_at=old, started_at=old),
                     {"id": job["id"]})                                  # the worker died mid-job
    claimed = svc.jobs.claim(stale_seconds=60)                           # next worker: re-queued and claimed
    assert claimed and claimed["id"] == job["id"] and claimed["attempts"] == 2
    done = svc.ingestion.execute(claimed)
    assert done["status"] == "succeeded" and ann_row(env, a["id"], "en")["translation_status"] == "machine_draft"
    assert len(jobs(env)) == 1 and len(env.store.select("announcement_translations", Query(
        eq={"announcement_id": a["id"], "language_code": "en"}))[0]) == 1


def test_a_changed_number_sends_the_translation_to_review_instead_of_students(env, auto):
    assign(env, "supporter", "en")
    use_translator(env, FakeTranslator(mutate=lambda t: t.replace("15", "25")))
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    en = ann_row(env, a["id"], "en")
    assert en["translation_status"] == "needs_review"
    assert {"type": "number", "value": "15"} in en["warnings"] and {"type": "number_added", "value": "25"} in en["warnings"]
    assert public_ann(env, a["id"], "en")["translation"] is None
    notes = env.store.select("user_notifications", Query(eq={"user_id": env.users["supporter"]}))[0]
    assert any("needs review" in n["title"] for n in notes)


def test_a_person_corrects_and_approves_a_machine_translation(env, auto):
    assign(env, "supporter", "en")
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    url = f"/api/v1/admin/announcements/{a['id']}/translations/en"
    detail = env.client.get(url, headers=env.auth("supporter")).json()
    assert detail["machine"]["state"] == "completed" and detail["machine"]["model"] == "translate-1"
    body = ("The scholarship application period is 2026-12-1 to 12-15 (2026년 12월 1일부터 12월 15일까지).\n\n"
            "Apply at https://sch.ac.kr/apply. Contact: intl@sch.ac.kr, 041-530-1234")
    r = env.client.put(url, headers=env.auth("supporter"), json={"title": "Scholarship application", "body": body,
                                                                  "submit": True})
    assert r.status_code == 200, r.text
    r = env.client.post(f"{url}/approve", headers=env.auth("supporter"), json={"original_verified": True})
    assert r.status_code == 200, r.text
    tr = public_ann(env, a["id"], "en")["translation"]
    assert tr["status"] == "verified" and tr["title"] == "Scholarship application"
    # the machine never overwrites a person's work, even when asked again
    svc = env.app.state.services
    with pytest.raises(Exception, match="approved by a reviewer"):      # protected, even with force
        svc.announcement_translator.queue(a["id"], "en", None, force=True)


def test_machine_translate_endpoint_permissions(env, auto):
    env.settings.auto_translate_announcements = False
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    url = f"/api/v1/admin/announcements/{a['id']}/translations/en/machine-translate"
    assert env.client.post(url, headers=env.auth("supporter")).status_code == 403        # not assigned to English
    assert env.client.post(url, headers=env.auth("student")).status_code == 403
    r = env.client.post(url, headers=env.auth("admin"))
    assert r.status_code == 202 and ann_row(env, a["id"], "en")["translation_status"] == "machine_draft"


def test_high_risk_policy_review_holds_unverified_machine_translations(env, auto):
    env.settings.machine_translation_high_risk = "review"
    a = publish(env, title="비자 연장 안내", body="체류기간 연장은 만료 4개월 전부터 신청할 수 있습니다.")
    assert ann_row(env, a["id"], "en")["translation_status"] == "machine_draft"
    assert public_ann(env, a["id"], "en")["translation"] is None
    b = publish(env, title="도서관 휴관 안내", body="도서관은 리모델링으로 다음 주 월요일 하루 휴관합니다.")
    assert ann_row(env, b["id"], "en")["translation_status"] == "machine_draft"
    assert public_ann(env, b["id"], "en")["translation"] is None   # low risk too: unreviewed drafts stay private


# ------------------------------------------------------------------------------------- documents
def drain(env) -> int:  # type: ignore[no-untyped-def]
    """Run queued translation jobs the way the production worker claims them."""
    n = 0
    for j in jobs(env, "translate_document"):
        if j["status"] == "queued":
            env.app.state.services.ingestion.run_job(j["id"])
            n += 1
    return n


def doc_row(env, doc_id: str, lang: str) -> dict:  # type: ignore[type-arg]
    d = env.store.select("source_documents", Query(eq={"id": doc_id}))[0][0]
    return env.store.select("document_translations", Query(eq={"version_id": d["current_version_id"],
                                                                "language_code": lang}))[0][0]


def public_doc(env, doc_id: str, lang: str) -> dict:  # type: ignore[type-arg]
    return env.client.get(f"/api/v1/knowledge/documents/{doc_id}", params={"lang": lang}).json()


def test_korean_document_is_translated_into_english_only(env, auto):
    job = make_doc(env, KO_TITLE, KO_BODY, language="ko", category="scholarships")
    assert drain(env) == 1                                    # queued at activation, run by the worker
    assert doc_row(env, job["document_id"], "en")["translation_status"] == "machine_draft"
    assert doc_row(env, job["document_id"], "vi")["translation_status"] == "todo"      # later languages: on request
    tr = public_doc(env, job["document_id"], "en")["translation"]
    assert tr["status"] == "machine" and tr["scope"] == "full"
    assert public_doc(env, job["document_id"], "en")["content"] == KO_BODY or "장학금" in public_doc(env, job["document_id"], "en")["content"]
    assert len(jobs(env, "translate_document")) == 1


def test_english_document_is_translated_into_korean(env, auto):
    job = make_doc(env, EN_TITLE, EN_BODY, language="en", category="daily-living")
    drain(env)
    ko = doc_row(env, job["document_id"], "ko")
    assert ko["translation_status"] == "machine_draft" and "2027-02-24" in ko["body"]
    listing = env.client.get("/api/v1/knowledge/documents", params={"lang": "ko"}).json()["items"]
    item = next(i for i in listing if i["id"] == job["document_id"])
    assert item["translated_title"] == ko["title"] and item["translated_title_status"] == "machine"


def test_long_document_gets_a_labelled_summary_not_a_full_translation(env, auto):
    env.settings.translation_full_max_chars = 200
    body = "\n\n".join(f"## 제{i}장 체류 안내\n\n외국인 유학생은 체류 규정을 지켜야 합니다. 신고 기한은 {i}0일입니다." for i in range(1, 12))
    job = make_doc(env, "유학생 생활 가이드북", body, language="ko")
    drain(env)
    en = doc_row(env, job["document_id"], "en")
    assert en["scope"] == "summary" and en["translation_status"] == "machine_draft" and auto.responder.calls == 2
    tr = public_doc(env, job["document_id"], "en")["translation"]
    assert tr["scope"] == "summary" and tr["high_risk"] is True


def test_new_document_version_outdates_the_old_translation_and_translates_the_new_one(env, auto):
    job = make_doc(env, KO_TITLE, KO_BODY, language="ko", category="scholarships")
    drain(env)
    old = doc_row(env, job["document_id"], "en")
    src = env.store.select("source_documents", Query(eq={"id": job["document_id"]}))[0][0]["source_id"]
    r = env.client.post(f"/api/v1/admin/sources/{src}/submit-text", headers=env.auth("admin"),
                        json=dict(title=KO_TITLE, text=KO_BODY + "\n\n추가 안내: 서류는 원본으로 제출합니다.",
                                  authorized_by_supporter=True)).json()
    env.client.post(f"/api/v1/admin/versions/{r['version_id']}/approve", headers=env.auth("admin"), json={})
    drain(env)
    assert env.store.select("document_translations", Query(eq={"id": old["id"]}))[0][0]["is_outdated"] is True
    new = doc_row(env, job["document_id"], "en")
    assert new["id"] != old["id"] and new["translation_status"] == "machine_draft"


def test_original_document_and_search_index_are_untouched(env, auto):
    job = make_doc(env, KO_TITLE, KO_BODY, language="ko", category="scholarships")
    drain(env)
    v = env.store.select("document_versions", Query(eq={"id": job["version_id"]}))[0][0]
    chunks = env.store.select("document_chunks", Query(eq={"version_id": job["version_id"]}))[0]
    assert v["extracted_text"] == KO_BODY
    assert all("notice" not in c["content"] for c in chunks)                 # no translated text in the RAG index
    assert len(env.store.select("document_chunks", Query())[0]) == len(chunks)


# ------------------------------------------------------------------------------------- checks + backfill
def test_quality_checks():
    o = "기한: 2026년 12월 15일. 비자 D-2. https://hikorea.go.kr"
    assert validate_translation(o, "Deadline: 2026-12-15. Visa D-2. https://hikorea.go.kr", "ko", "en") == []
    w = validate_translation(o, "기한: 2026년 12월 15일. 비자 D-2. https://hikorea.go.kr", "ko", "en")
    assert w == [] or all(x["type"] != "language" for x in w)               # too short to judge the language
    long_ko = "외국인 유학생은 체류 기간 연장을 반드시 미리 신청해야 하며 필요한 서류를 준비해야 합니다. " * 3
    assert any(x["type"] == "language" for x in validate_translation(long_ko, long_ko, "ko", "en"))
    assert any(x["type"] == "placeholder" for x in validate_translation("가나다", "[TODO] <source_text>", "ko", "en"))
    assert any(x["type"] == "truncated" for x in validate_translation("가" * 400, "Short.", "ko", "en"))
    assert any(x["type"] == "number_added" for x in validate_summary("수수료 3만원", "The fee is 50,000 won for everyone.", "en"))
    assert is_high_risk("외국인등록증 재발급") and not is_high_risk("도서관 휴관 안내")


def test_backfill_dry_run_estimates_and_apply_queues_in_batches(env, auto):
    env.settings.auto_translate_announcements = env.settings.auto_translate_documents = False
    publish(env, title=KO_TITLE, body=KO_BODY)
    publish(env, title=EN_TITLE, body=EN_BODY, original_language="en")
    make_doc(env, "기숙사 안내", "기숙사 입사는 3월 2일입니다.", language="ko", category="daily-living")
    svc = env.app.state.services
    p = backfill.plan(svc)
    assert p["pairs"] == 3 and p["announcements"] == 2 and p["documents"] == 1 and p["requests"] == 6
    assert p["input_tokens"] > 0 and p["output_tokens"] > 0 and auto.responder.calls == 0     # dry run: no model
    queued = backfill.apply(svc, limit=2)
    assert len(queued) == 2 and all(j["status"] == "queued" for j in env.store.select("ingestion_jobs", Query(
        in_={"job_type": ["translate_announcement", "translate_document"]}))[0])          # queued, not run here
    assert auto.responder.calls == 0
    again = backfill.plan(svc)
    assert again["already_queued"] == 2
    assert len(backfill.apply(svc, limit=10)) == 1                                        # resumes; no duplicates


def test_concurrent_requests_never_create_two_open_jobs_for_one_translation(env, auto, monkeypatch):
    env.settings.auto_translate_announcements = False
    a = publish(env, title=KO_TITLE, body=KO_BODY)
    tr = env.app.state.services.announcement_translator
    first = tr.queue(a["id"], "en", None, enqueue=False)
    # a second request that did not see the first job yet (race): the unique index rejects the insert and the
    # existing job is returned instead of a duplicate
    real_open = tr.open_job
    calls = {"n": 0}

    def stale_then_real(tid):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return None if calls["n"] == 1 else real_open(tid)
    monkeypatch.setattr(tr, "open_job", stale_then_real)
    second = tr.queue(a["id"], "en", None, enqueue=False)
    assert second["id"] == first["id"] and len(jobs(env)) == 1

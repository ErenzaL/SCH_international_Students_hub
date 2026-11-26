"""Release 1 announcement translation scope: machine drafts only between Korean, English and Indonesian, never into
the original language, never public before a reviewer approves them; earlier approved translations in other
languages stay visible. The chatbot, the website and the office keep all five languages (not touched here)."""
from __future__ import annotations

import pytest

from app.repositories.base import Query
from tests.test_auto_translation import FakeTranslator, ann_row, jobs, public_ann, publish, use_translator

TEXT = {
    "ko": ("기숙사 입사 안내", "입사일은 2027년 2월 24일 10:00입니다. 문의: dorm@sch.ac.kr"),
    "en": ("Dormitory move-in guide", "Move-in starts on 2027-02-24 at 10:00. Questions: dorm@sch.ac.kr"),
    "id": ("Panduan masuk asrama", "Masuk asrama dimulai pada 2027-02-24 pukul 10:00. Pertanyaan: dorm@sch.ac.kr"),
}


@pytest.fixture
def auto(env):  # type: ignore[no-untyped-def]
    s = env.settings
    s.auto_translate_announcements = True
    s.public_machine_translations = True          # must not matter for announcements
    use_translator(env, FakeTranslator())
    return env


@pytest.mark.parametrize("original,targets", [("ko", {"en", "id"}), ("en", {"ko", "id"}), ("id", {"ko", "en"})])
def test_each_original_gets_drafts_in_the_other_two_languages_only(auto, original, targets):
    title, body = TEXT[original]
    a = publish(auto, title=title, body=body, original_language=original)
    assert {j["payload"]["language"] for j in jobs(auto)} == targets             # never the original, never vi / zh
    for lang in targets:
        assert ann_row(auto, a["id"], lang)["translation_status"] in ("machine_draft", "needs_review")
        assert public_ann(auto, a["id"], lang)["translation"] is None          # private until reviewed


def test_configured_vietnamese_is_still_not_generated(auto):
    auto.settings.auto_translate_languages = "ko,en,id,vi,zh-CN"
    a = publish(auto, title=TEXT["ko"][0], body=TEXT["ko"][1])
    assert {j["payload"]["language"] for j in jobs(auto)} == {"en", "id"}
    for lang in ("vi", "zh-CN"):
        r = auto.client.post(f"/api/v1/admin/announcements/{a['id']}/translations/{lang}/machine-translate",
                             headers=auto.auth("super_admin"))
        assert r.status_code == 409 and r.json()["error"]["code"] == "language_out_of_scope"
    # the review workflow keeps an empty slot for a person; no model ever filled it
    for row in auto.store.select("announcement_translations", Query(
            eq={"announcement_id": a["id"], "language_code": "vi"}))[0]:
        assert row["translation_status"] == "todo" and row["body"] == "" and not row.get("provider")


def test_the_original_language_is_refused(auto):
    a = publish(auto, title=TEXT["ko"][0], body=TEXT["ko"][1])
    r = auto.client.post(f"/api/v1/admin/announcements/{a['id']}/translations/ko/machine-translate",
                         headers=auto.auth("super_admin"))
    assert r.status_code == 409


def test_an_existing_approved_vietnamese_translation_stays_visible(auto):
    auto.settings.auto_translate_announcements = False
    a = publish(auto, title=TEXT["ko"][0], body=TEXT["ko"][1])
    svc = auto.app.state.services
    h = svc.translations.original(a["id"])["content_hash"]
    row = dict(title="Hướng dẫn nhập ký túc xá", body="Ngày 2027-02-24 lúc 10:00.", translation_status="human_approved",
               source_content_hash=h, is_outdated=False, reviewed_by=auto.users["supporter"],
               reviewed_at="2026-11-01T00:00:00+00:00")
    if not auto.store.update("announcement_translations", row, {"announcement_id": a["id"], "language_code": "vi"}):
        auto.store.insert("announcement_translations", dict(announcement_id=a["id"], language_code="vi") | row)
    tr = public_ann(auto, a["id"], "vi")["translation"]
    assert tr["status"] == "verified" and tr["title"] == "Hướng dẫn nhập ký túc xá"
    listing = auto.client.get("/api/v1/announcements", params={"display_language": "vi"}).json()["items"]
    assert listing[0]["display_title"] == "Hướng dẫn nhập ký túc xá" and listing[0]["display_title_status"] == "verified"


def test_language_switching_never_exposes_a_pending_draft(auto):
    a = publish(auto, title=TEXT["ko"][0], body=TEXT["ko"][1])
    for lang in ("en", "id", "vi", "zh-CN", "ko"):
        d = public_ann(auto, a["id"], lang)
        assert d["translation"] is None and d["body"] == TEXT["ko"][1]            # the approved original
        assert all(t["translation_status"] == "human_approved" for t in d["translations"])
        items = auto.client.get("/api/v1/announcements", params={"display_language": lang}).json()["items"]
        assert items[0]["display_title"] is None


def test_the_supporter_queue_says_where_machine_drafts_exist(auto):
    from tests.test_agent_operations import tool
    from tests.test_document_translations import assign

    auto.settings.auto_translate_announcements = False
    publish(auto, title=TEXT["ko"][0], body=TEXT["ko"][1])
    for lang, expected in (("id", True), ("vi", False)):
        assign(auto, "supporter", lang)
        r = tool(auto, f"supporter-{lang}", "translation_review_queue", {}, "supporter")
        items = [i for i in r.json()["result"]["items"] if i["content_kind"] == "announcement"]
        assert items and all(i["machine_draft"] is expected for i in items), (lang, r.text)

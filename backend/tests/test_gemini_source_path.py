"""Every route that sends Hub content to the model, through the REAL Gemini provider class (recording client, no network):
the request never contains a pending text, title or attachment. Fails if a new route is added without being listed here."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.repositories.base import get_one
from app.services.llm.gemini import GeminiProvider
from tests.test_approved_source import pending_edit
from tests.test_approved_source import publish as publish_announcement
from tests.test_document_attachments import A, B, setup, sync
from tests.test_ingestion_versioning import approve
from tests.test_phase2 import ingest, make_board_source

APP = Path(__file__).resolve().parents[1] / "app"
MARKS = ("SECRET-EDIT", "PENDING-TITLE", B)


def response(text: str) -> NS:
    return NS(candidates=[NS(content=NS(parts=[NS(text=text, thought=None)]), finish_reason=NS(name="STOP"))], prompt_feedback=None,
              model_version="gemini-test", usage_metadata=NS(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0, total_token_count=2))


class Recorder:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def _answer(self, config, contents) -> str:  # type: ignore[no-untyped-def]
        self.sent.append(f"{config.system_instruction}\n{contents}")
        if "search queries" in str(config.system_instruction):
            return '{"standalone": "짐 보관 안내", "en": "storage", "ko": "짐 보관", "topic": "new"}'
        return 'Storage notice [1].\n<<<META>>>\n{"evidence": "sufficient", "needs_human": "none", "in_scope": true}'

    def generate_content(self, *, model, contents, config):  # type: ignore[no-untyped-def]
        return response(self._answer(config, contents))

    def generate_content_stream(self, *, model, contents, config):  # type: ignore[no-untyped-def]
        yield response(self._answer(config, contents))


@pytest.fixture
def live(env):  # type: ignore[no-untyped-def]
    """A published announcement and a published board notice, both with a pending edit, and Gemini everywhere."""
    rec = Recorder()
    p = GeminiProvider("test-key-not-real", primary="gemini-test", client_factory=lambda: NS(models=rec))
    svc = env.app.state.services
    svc.llm = svc.conversations.llm = svc.conversations.engine.llm = p
    svc.doc_translations.llm = svc.announcement_translator.llm = svc.discovery.llm = p
    env.ann = publish_announcement(env)
    pending_edit(env, env.ann)
    long = "방학 중 교내에 개인 짐을 보관할 수 없습니다. 첨부 안내문을 참고하세요. "
    setup(env, A, body=f"<p>{long}</p>")
    env.src = make_board_source(env)
    job = ingest(env, env.src["id"])
    assert approve(env, job["version_id"]).status_code == 202
    env.doc_id = job["document_id"]
    sync(env, B, title="PENDING-TITLE", body=f"<p>{long} SECRET-EDIT</p>")
    assert get_one(env.store, "document_versions", document_id=env.doc_id, verification_status="pending_review")
    env.rec = rec
    rec.sent.clear()
    return env


def clean(env) -> None:  # type: ignore[no-untyped-def]
    assert env.rec.sent, "nothing was sent: the test proves nothing"
    for text in env.rec.sent:
        for mark in MARKS:
            assert mark not in text
    env.rec.sent.clear()


@pytest.mark.parametrize("lang", ["en", "id", "vi", "zh-CN"])
def test_requested_translations(live, lang):
    h = live.auth("super_admin")
    assert live.client.post(f"/api/v1/admin/announcements/{live.ann['id']}/translations/{lang}/machine-translate", headers=h).status_code == 202
    clean(live)
    assert live.client.post(f"/api/v1/admin/documents/{live.doc_id}/translations/drafts", headers=h, json=dict(languages=[lang])).status_code == 202
    clean(live)


def test_automatic_translations_and_backfill(live):
    from app.services.translation import backfill

    s, svc = live.settings, live.app.state.services
    s.auto_translate_announcements = s.auto_translate_documents = True
    s.auto_translate_languages = "ko,en,vi"
    svc.translations.on_original_published(live.ann["id"], None)
    clean(live)
    for q in backfill.apply(svc, 20, ["id", "zh-CN"]):
        svc.ingestion.run_job(q["job_id"])
    clean(live)


def test_summary_of_a_long_document(live):
    live.settings.translation_full_max_chars = 10
    live.client.post(f"/api/v1/admin/documents/{live.doc_id}/translations/drafts", headers=live.auth("super_admin"), json=dict(languages=["en"]))
    clean(live)


def test_agent_summaries(live):
    from tests.test_agents import get_task, task

    t = task(live, "announcement", "summarize_announcement", {"ref": live.ann["id"], "language": "en"})
    assert t.status_code == 201 and get_task(live, t.json()["id"]).json()["status"] == "completed"
    clean(live)


@pytest.mark.parametrize("lang", ["ko", "en", "id", "vi", "zh-CN"])
def test_chat(live, lang):
    live.client.post("/api/v1/assistant/chat", json=dict(message="짐 보관 안내 첨부파일", language=lang))
    clean(live)
    live.client.post("/api/v1/assistant/chat/stream", json=dict(message="장학금 신청 기간", language=lang))
    clean(live)


def test_after_approval_the_new_text_is_used(live):
    v = get_one(live.store, "document_versions", document_id=live.doc_id, verification_status="pending_review")
    approve(live, v["id"])
    live.rec.sent.clear()
    live.client.post(f"/api/v1/admin/documents/{live.doc_id}/translations/drafts", headers=live.auth("super_admin"), json=dict(languages=["en"]))
    sent = "\n".join(live.rec.sent)
    assert all(m in sent for m in MARKS) and A not in sent.replace(B, "")


def test_every_call_to_the_model_is_known():
    found = {}
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).as_posix()
        if rel.startswith("services/llm/") or rel.startswith("gpu_worker/"):
            continue
        n = len(re.findall(r"\bllm\.(?:complete|stream)\(|(?<!def )\b(?:translate|summarize)_document\(", p.read_text()))
        if n:
            found[rel] = n
    assert found == {
        "services/translation_drafts.py": 4,       # the prompts themselves (callers below)
        "services/translation/auto.py": 1,         # announcements: approved public text only
        "services/document_translations.py": 2,    # documents: approved public version only
        "services/agents/tools.py": 2,             # public announcement / document; text the student typed
        "services/assistant/engine.py": 2,         # question rewrite; answer from searchable (approved) chunks
        "services/assistant/handoff.py": 1,        # the student's own conversation
        "services/discovery/service.py": 1,        # external official pages for administrators, not Hub content
    }

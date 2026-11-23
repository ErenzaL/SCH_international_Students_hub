"""Citation targets: announcements open their announcement page, Knowledge Center documents their document page
(PDFs at the cited page), web sources their verified original URL."""
from __future__ import annotations

from app.services.assistant.engine import citation_link
from app.services.llm.base import ScriptedLLMProvider
from tests.test_announcements import create
from tests.test_assistant import use_llm
from tests.test_assistant_m2 import Bot


def cite(**kw):  # type: ignore[no-untyped-def]
    return dict(document_id="d1", source_url=None, source_type="manual_text", page=None) | kw


def test_document_citation_opens_the_knowledge_center_page():
    assert citation_link(cite()) == dict(kind="document", href="/knowledge/d1", page=None)


def test_pdf_citation_opens_the_cited_page():
    assert citation_link(cite(source_type="pdf", page=40)) == dict(kind="document", href="/knowledge/d1?page=40", page=40)
    # a page number on a non-PDF passage is not a viewer page
    assert citation_link(cite(source_type="text_file", page=3))["href"] == "/knowledge/d1"


def test_web_source_citation_opens_the_verified_original_url():
    c = cite(source_type="website", source_url="https://www.hikorea.go.kr/info/d2")
    assert citation_link(c) == dict(kind="external", href="https://www.hikorea.go.kr/info/d2")
    board = cite(source_type="sch_board", source_url="https://home.sch.ac.kr/notice/123")
    assert citation_link(board)["kind"] == "external"
    # a non-http URL is never used as a link target
    assert citation_link(cite(source_type="website", source_url="javascript:alert(1)"))["kind"] == "document"


def test_announcement_citation_opens_the_announcement_page():
    assert citation_link(cite(source_url="https://x.test"), "a-1") == dict(kind="announcement", href="/announcements/a-1")


def test_cited_announcement_in_an_answer_links_to_its_announcement_page(env):
    a = create(env, submit=True)          # 장학금 신청 안내 (scholarship application notice)
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    assert r.status_code == 200, r.text
    use_llm(env, ScriptedLLMProvider(Bot("장학금 신청서를 기간 안에 제출하세요 [1].")))
    out = env.client.post("/api/v1/assistant/chat", json={"message": "장학금 신청 기간", "language": "ko"}).json()
    cited = [c for c in out["citations"] if c["document_id"] == a["document_id"]]
    assert cited and cited[0]["link"] == dict(kind="announcement", href=f"/announcements/{a['id']}")
    # the announcement page it links to is public; the knowledge document route is not (announcements are hidden there)
    assert env.client.get(f"/api/v1/announcements/{a['id']}").status_code == 200
    assert env.client.get(f"/api/v1/knowledge/documents/{a['document_id']}").status_code == 404

"""LIVE check of the official-source connectors against the real sites (opt-in: SCH_LIVE_SOURCES=1). Few requests,
1 s apart, robots.txt respected, in-memory store only - nothing is written to any database. It verifies that the
real page structures still match the connectors; it does not assert on notice contents, which change daily."""
from __future__ import annotations

import os

import pytest

from app.core.config import Settings
from app.repositories.memory_store import MemoryStore, seed_categories
from app.services.discovery.service import DiscoveryService
from app.services.domains import DomainPolicy
from app.services.ingestion.fetcher import GuardedFetcher

pytestmark = pytest.mark.skipif(os.environ.get("SCH_LIVE_SOURCES") != "1", reason="set SCH_LIVE_SOURCES=1 to run")
ADMIN = "00000000-0000-0000-0000-00000000a0a0"


@pytest.fixture(scope="module")
def disc() -> DiscoveryService:
    s = Settings(_env_file=None, board_request_delay_seconds=1.0)
    store = MemoryStore()
    seed_categories(store)
    store.insert("profiles", dict(id=ADMIN, email="admin@example.test", role="admin"))
    return DiscoveryService(store, s, GuardedFetcher(s), DomainPolicy(store, s))


def test_sch_international_board(disc: DiscoveryService):
    src = disc.create_source(ADMIN, dict(agent_id="announcement", name="SCH 유학생 공지사항", kind="sch_board",
                                         url="https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore&loc_mnu=3",
                                         config={"max_items": 3}))
    r = disc.check_source(src)
    assert r["status"] in ("ok", "partial") and r["found"] >= 1, r
    items = disc.items_by_id(r["item_ids"], admin=True)
    assert all(i["href"].startswith("https://sgee.sch.ac.kr/") and i["published_on"] for i in items)


def test_study_in_korea_scholarship_list(disc: DiscoveryService):
    src = disc.create_source(ADMIN, dict(
        agent_id="scholarship", name="Study in Korea 장학금 공지", kind="listing",
        url="https://www.studyinkorea.go.kr/ko/notice/scholarshipsList.do?boardSort=3",
        config={"item_selector": "a.board-text-item", "title_selector": "p.title", "date_selector": "span.date",
                "max_items": 3}))
    r = disc.check_source(src)
    assert r["status"] == "ok" and r["found"] >= 1, r
    items = disc.items_by_id(r["item_ids"], admin=True)
    assert all("no_detail_page" in i["flags"] and i["open_status"] in ("unknown", "closed") for i in items)


def test_gks_page_is_only_open_when_the_page_says_so(disc: DiscoveryService):
    src = disc.create_source(ADMIN, dict(agent_id="scholarship", name="GKS 장학금 안내", kind="page",
                                         url="https://www.studyinkorea.go.kr/ko/plan/scholarship.do"))
    r = disc.check_source(src)
    assert r["status"] == "ok", r
    item = disc.items_by_id(r["item_ids"], admin=True)[0]
    assert item["open_status"] in ("open", "closed", "unknown") and item["eligibility"]

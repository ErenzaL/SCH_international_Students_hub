"""Journey I: an approved opportunity stops being shown as open the day after its deadline (Korea time) without a new
weekly check; a notice that only says it is recruiting, without a date, is never "open"."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.discovery import service as discovery_service
from app.services.discovery.extract import effective_open_status
from tests.test_discovery import D, run_task
from tests.test_job_apis import PUBLIC, answer, source


def f(deadline: str | None, reason: str = "deadline_in_future", flags: list[str] | None = None) -> dict:  # type: ignore[type-arg]
    return dict(next_deadline=deadline, deadlines=[{"date": deadline}] if deadline else [], open_reason=reason,
                flags=flags or [])


@pytest.mark.parametrize("stored,extracted,today,expected", [
    ("open", f("2026-12-15"), date(2026, 12, 15), "open"),            # open through the whole deadline day (KST)
    ("open", f("2026-12-15"), date(2026, 12, 16), "closed"),          # the next day: closed, no crawl needed
    ("open", f(None, "source_says_open"), date(2026, 12, 1), "unknown"),  # "recruiting" without a date
    ("unknown", f(None, "no_deadline"), date(2026, 12, 1), "unknown"),
    ("closed", f("2027-01-01", "source_says_closed"), date(2026, 12, 1), "closed"),   # the source says closed
    ("open", f("2026-12-15", flags=["deadline_before_published"]), date(2026, 12, 1), "unknown"),
])
def test_status_is_computed_for_today(stored, extracted, today, expected):
    assert effective_open_status(stored, extracted, today)[0] == expected


def test_an_approved_posting_disappears_after_its_deadline_without_a_new_check(env, monkeypatch):
    source(env, "data_go_kr_jobs")
    seen = answer(env, PUBLIC)                                        # deadline: D(6)
    run_task(env, "career", "opportunity_discovery")
    item = env.client.get("/api/v1/admin/discovery/items?agent_id=career", headers=env.auth("admin")).json()["items"][0]
    env.client.post(f"/api/v1/admin/discovery/items/{item['id']}/send-to-review", headers=env.auth("admin"))
    v = env.store.select("document_versions")[0][0]
    assert env.client.post(f"/api/v1/admin/versions/{v['id']}/approve", headers=env.auth("admin"), json={}).status_code == 202
    search = lambda **p: env.client.post("/api/v1/agents/career/tools", headers=env.auth("student"), json=dict(  # noqa: E731
        tool="opportunity_search", params={"kind": "job"} | p)).json()["result"]
    shown = search()["items"]
    assert len(shown) == 1 and shown[0]["open_status"] == "open" and shown[0]["next_deadline"] == D(6)
    calls = len(seen)
    deadline = date.fromisoformat(D(6))
    monkeypatch.setattr(discovery_service, "today_kst", lambda: deadline)          # the deadline day itself
    assert [i["open_status"] for i in search()["items"]] == ["open"]
    monkeypatch.setattr(discovery_service, "today_kst", lambda: deadline + timedelta(days=1))
    out = search()
    assert out["items"] == [] and "reviewed_closed_hidden" in out["notes"]       # gone, and the reason is precise
    assert [i["open_status"] for i in search(include_closed=True)["items"]] == ["closed"]   # history kept
    assert len(seen) == calls                                                     # no source was asked again
    admin = env.app.state.services.discovery.items_by_id([item["id"]], admin=True)[0]
    assert admin["open_status"] == "closed" and admin["open_status_when_checked"] == "open"

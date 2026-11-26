"""The pilot helper: read-only checks, exactly one queued job, refuses risky or unclear situations."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from tests.test_gpu_worker import add_pending_edit, claim, done, gpu, publish, set_worker

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from gpu_pilot import Pilot, Stop  # noqa: E402

_ = gpu
LIBRARY = ("도서관 TOPIK 강좌 안내", "도서관에서 TOPIK 동영상 강좌를 볼 수 있습니다. 많은 이용 바랍니다.")


@pytest.fixture
def pilot(gpu):  # type: ignore[no-untyped-def]
    sent = []

    def bridge(req: httpx.Request) -> httpx.Response:
        sent.append(req.method)
        r = gpu.client.request(req.method, req.url.raw_path.decode(), content=req.content,
                               headers={"Authorization": req.headers["Authorization"]})
        return httpx.Response(r.status_code, content=r.content)

    p = Pilot("https://hub.example.test", gpu.auth("super_admin")["Authorization"].removeprefix("Bearer "), httpx.MockTransport(bridge))
    p.sent = sent  # type: ignore[attr-defined]
    return p


def test_one_translation_end_to_end(gpu, pilot):
    a = publish(gpu, *LIBRARY)["id"]
    assert pilot.preflight(a, "vi") == [] and set(pilot.sent) == {"GET"}
    jid = pilot.queue(a, "vi")
    assert pilot.sent.count("POST") == 1
    with pytest.raises(Stop, match="other GPU jobs"):
        pilot.queue(a, "en")
    assert any("expected needs_review" in b for b in pilot.verify(a, "vi"))
    job = claim(gpu)
    assert job["id"] == jid
    done(gpu, job, title="Khóa học TOPIK", body="Bạn có thể xem khóa học TOPIK tại thư viện.")
    assert pilot.verify(a, "vi") == []
    assert any("already a translation" in b for b in pilot.preflight(a, "vi"))


@pytest.mark.parametrize("case", ["high_risk", "long", "pending", "paused", "same_language", "unpublished"])
def test_unsuitable_pilots_are_refused(gpu, pilot, case):
    text = ("장학금 안내", "장학금 마감은 12월 1일입니다.") if case == "high_risk" else \
        ("안내", "도서관 안내입니다. " * 300) if case == "long" else LIBRARY
    a = publish(gpu, *text)["id"]
    if case == "pending":
        add_pending_edit(gpu, a)
    elif case == "paused":
        set_worker(gpu, "paused")
    elif case == "unpublished":
        gpu.client.post(f"/api/v1/admin/announcements/{a}/cancel", headers=gpu.auth("admin"), json=dict(reason="withdrawn"))
    before = len(gpu.store.t["ingestion_jobs"])
    if case == "pending":       # the approved text is what would be sent: allowed, and the waiting edit stays untouched
        assert pilot.preflight(a, "vi") == []
        return
    with pytest.raises(Stop):
        pilot.queue(a, "ko" if case == "same_language" else "vi")
    assert "POST" not in pilot.sent and len(gpu.store.t["ingestion_jobs"]) == before


def test_only_https():
    with pytest.raises(Stop):
        Pilot("http://hub.example.test", "t")

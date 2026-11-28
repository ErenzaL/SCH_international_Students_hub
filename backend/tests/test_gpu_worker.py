"""GPU worker endpoints: credentials, routing, leases, drafts that are never public, cancellation, idempotency."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.repositories.base import Query, get_one
from tests.test_announcements import create
from tests.test_document_translations import assign
from tests.test_retrieval import make_doc

KO = ("장학금 신청 안내", "신청 기간은 2026-12-01부터입니다. 문의: intl@example.ac.kr")
GOOD = dict(title="Scholarship application guide", model="translategemma:12b",
            body="Applications open on 2026-12-01. Contact: intl@example.ac.kr")


@pytest.fixture
def gpu(env):  # type: ignore[no-untyped-def]
    env.settings.gpu_worker_enabled = True
    env.settings.public_machine_translations = True        # the strictest case: clean machine drafts would be public
    w = new_worker(env)
    env.worker = w
    return env


def new_worker(env, name="school-gpu"):  # type: ignore[no-untyped-def]
    r = env.client.post("/api/v1/admin/gpu/workers", headers=env.auth("super_admin"), json=dict(name=name))
    assert r.status_code == 201, r.text
    seen(env, r.json()["id"])
    return r.json()


def seen(env, worker_id, when=None):  # type: ignore[no-untyped-def]
    env.store.update("gpu_workers", {"last_seen_at": (when or datetime.now(UTC)).isoformat()}, {"id": worker_id})


def call(env, path, token=None, **body):  # type: ignore[no-untyped-def]
    t = token or env.worker["token"]
    return env.client.post(f"/api/v1/gpu{path}", json=body, headers={"Authorization": f"Bearer {t}"})


def claim(env, lease=None, **kw):  # type: ignore[no-untyped-def]
    r = call(env, "/claim", lease_token=lease or str(uuid.uuid4()), **kw)
    assert r.status_code == 200, r.text
    return r.json()["job"]


def publish(env, title=KO[0], body=KO[1]):  # type: ignore[no-untyped-def]
    a = create(env, submit=True, title=title, body=body)
    assert env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={}).status_code == 200
    return a


def request(env, aid, lang="en", role="super_admin", **params):  # type: ignore[no-untyped-def]
    r = env.client.post(f"/api/v1/admin/announcements/{aid}/translations/{lang}/machine-translate",
                        headers=env.auth(role), params=params)
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def row(env, aid, lang="en"):  # type: ignore[no-untyped-def]
    return get_one(env.store, "announcement_translations", announcement_id=aid, language_code=lang)


def job_row(env, jid):  # type: ignore[no-untyped-def]
    return get_one(env.store, "ingestion_jobs", id=jid)


def done(env, job, **kw):  # type: ignore[no-untyped-def]
    return call(env, f"/jobs/{job['id']}/complete", lease_token=job["lease_token"], **(GOOD | kw))


def public(env, aid, lang="en"):  # type: ignore[no-untyped-def]
    return env.client.get(f"/api/v1/announcements/{aid}", params={"lang": lang}).json()["translation"]


def expire(env, jid):  # type: ignore[no-untyped-def]
    env.store.update("ingestion_jobs", {"lease_expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}, {"id": jid})


# ------------------------------------------------------------------------ off by default
def test_everything_is_404_and_unchanged_when_disabled(env):
    assert env.client.post("/api/v1/gpu/claim", json=dict(lease_token=str(uuid.uuid4()))).status_code == 404
    for path in ("workers", "jobs/queue-missing"):
        r = env.client.post(f"/api/v1/admin/gpu/{path}", headers=env.auth("super_admin"), json=dict(name="x-1"))
        assert r.status_code == 404
    inserted = env.store.insert
    rows = []
    env.store.insert = lambda t, r: (rows.append((t, r)), inserted(t, r))[1]
    from app.services.llm.base import ScriptedLLMProvider
    env.app.state.services.announcement_translator.llm = ScriptedLLMProvider(lambda s, p: "Guide")
    a = publish(env)
    # default: announcements are translated by the GPU worker only - switched off, nothing is queued or charged
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/translations/en/machine-translate",
                        headers=env.auth("super_admin"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "translation_worker_disabled"
    env.settings.translation_fallback_to_gemini = True                # opt-in: the server's own model
    request(env, a["id"])
    jobs = [r for t, r in rows if t == "ingestion_jobs" and r["job_type"] == "translate_announcement"]
    assert jobs and all("executor" not in r for r in jobs)          # works without migration 0016


# ------------------------------------------------------------------------ credentials
def test_token_is_shown_once_and_stored_hashed(gpu):
    stored = gpu.store.t["gpu_workers"][0]
    assert gpu.worker["token"] not in json.dumps(stored) and len(stored["token_hash"]) == 64
    r = gpu.client.get("/api/v1/admin/gpu/status", headers=gpu.auth("admin"))
    assert r.status_code == 200 and "schgw_" not in r.text and stored["token_hash"] not in r.text and r.json()["workers"][0]["name"] == "school-gpu"
    assert gpu.worker["token"] not in json.dumps(gpu.store.t["audit_log"])


def test_only_super_admins_manage_credentials(gpu):
    for role in ("admin", "supporter", "student"):
        h = gpu.auth(role)
        assert gpu.client.post("/api/v1/admin/gpu/workers", headers=h, json=dict(name="other")).status_code == 403
        assert gpu.client.patch(f"/api/v1/admin/gpu/workers/{gpu.worker['id']}", headers=h,
                                json=dict(status="revoked")).status_code == 403
    for role in ("supporter", "student"):
        assert gpu.client.get("/api/v1/admin/gpu/status", headers=gpu.auth(role)).status_code == 403
    assert gpu.client.post("/api/v1/admin/gpu/workers", headers=gpu.auth("super_admin"),
                           json=dict(name="school-gpu")).status_code == 409


def test_worker_token_opens_nothing_else_and_user_tokens_do_not_open_the_worker_api(gpu):
    h = {"Authorization": f"Bearer {gpu.worker['token']}"}
    a = publish(gpu)
    for method, path in (("get", "/api/v1/admin/overview"), ("get", "/api/v1/admin/gpu/status"),
                         ("get", "/api/v1/agent-tasks"), ("get", "/api/v1/support/tickets"),
                         ("post", f"/api/v1/admin/announcements/{a['id']}/approve"),
                         ("post", f"/api/v1/admin/announcements/{a['id']}/translations/en/approve"),
                         ("post", "/api/v1/admin/gpu/workers")):
        assert getattr(gpu.client, method)(path, headers=h).status_code in (401, 403), path
    for role in ("super_admin", "admin", "student"):
        r = gpu.client.post("/api/v1/gpu/claim", headers=gpu.auth(role), json=dict(lease_token=str(uuid.uuid4())))
        assert r.status_code == 401
    for bad in ("", "x", f"schgw_{uuid.uuid4().hex}_{'a' * 43}", gpu.worker["token"][:-1] + "!"):
        r = gpu.client.post("/api/v1/gpu/claim", headers={"Authorization": f"Bearer {bad}"},
                            json=dict(lease_token=str(uuid.uuid4())))
        assert r.status_code == 401, bad


def test_rotation_with_and_without_overlap(gpu):
    old = gpu.worker["token"]
    url = f"/api/v1/admin/gpu/workers/{gpu.worker['id']}/rotate"
    new = gpu.client.post(url, headers=gpu.auth("super_admin"), json=dict(grace_minutes=10)).json()["token"]
    lease = str(uuid.uuid4())
    assert call(gpu, "/claim", old, lease_token=lease).status_code == 200
    assert call(gpu, "/claim", new, lease_token=lease).status_code == 200
    gpu.store.update("gpu_workers", {"previous_valid_until": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
                     {"id": gpu.worker["id"]})
    assert call(gpu, "/claim", old, lease_token=lease).status_code == 401
    newest = gpu.client.post(url, headers=gpu.auth("super_admin"), json={}).json()["token"]
    assert call(gpu, "/claim", new, lease_token=lease).status_code == 401
    assert call(gpu, "/claim", newest, lease_token=lease).status_code == 200


def test_expired_and_revoked_credentials_stop_at_once_and_free_the_job(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    job = claim(gpu)
    r = gpu.client.patch(f"/api/v1/admin/gpu/workers/{gpu.worker['id']}", headers=gpu.auth("super_admin"),
                         json=dict(status="revoked"))
    assert r.status_code == 200 and job_row(gpu, jid)["status"] == "queued"
    assert done(gpu, job).status_code == 401 and row(gpu, a["id"])["translation_status"] == "todo"
    for status in ("active", "paused"):           # revocation is final
        assert gpu.client.patch(f"/api/v1/admin/gpu/workers/{gpu.worker['id']}", headers=gpu.auth("super_admin"),
                                json=dict(status=status)).status_code == 409
    gpu.worker = new_worker(gpu, "second")
    gpu.store.update("gpu_workers", {"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
                     {"id": gpu.worker["id"]})
    assert call(gpu, "/claim", lease_token=str(uuid.uuid4())).status_code == 401


def test_failed_logins_are_rate_limited_without_blocking_the_real_worker(gpu):
    codes = [call(gpu, "/claim", "nope", lease_token=str(uuid.uuid4())).status_code for _ in range(25)]
    assert codes[0] == 401 and codes[-1] == 429
    assert call(gpu, "/claim", lease_token=str(uuid.uuid4())).status_code == 200


# -------------------------------------------------------------------- routing and content
def test_translation_jobs_wait_for_the_worker_and_the_local_worker_leaves_them_alone(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    assert job_row(gpu, jid)["status"] == "queued" and job_row(gpu, jid)["executor"] == "gpu"
    svc = gpu.app.state.services
    assert svc.ingestion.run_job(jid)["status"] == "queued" and svc.jobs.claim() is None
    claim(gpu)
    svc.ingestion.recover_interrupted_jobs()
    gpu.store.update("ingestion_jobs", {"heartbeat_at": "2020-01-01T00:00:00+00:00"}, {"id": jid})
    assert svc.jobs.claim() is None and job_row(gpu, jid)["status"] == "running"
    assert request(gpu, a["id"], "id") != jid


def test_a_job_contains_only_public_content(gpu):
    a = publish(gpu)
    request(gpu, a["id"])
    job = claim(gpu)
    assert set(job) == {"id", "lease_token", "lease_seconds", "max_seconds", "kind", "mode", "source_language",
                        "target_language", "title", "body", "input_sha256", "chunk_chars", "max_source_chars"}
    assert (job["title"], job["body"]) == KO and job["source_language"] == "ko" and job["target_language"] == "en"
    assert not any(uid in json.dumps(job) for uid in gpu.users.values())


def test_only_the_approved_text_leaves_the_server(gpu):
    a = publish(gpu)
    request(gpu, a["id"])
    add_pending_edit(gpu, a["id"])
    assert claim(gpu)["body"] == KO[1]                 # the approved text, never the waiting edit
    b = publish(gpu, "기숙사 안내", "입사일은 2027-02-24입니다.")
    done(gpu, dict(id=gpu.store.t["ingestion_jobs"][-1]["id"], lease_token=gpu.store.t["ingestion_jobs"][-1]["lease_token"]))
    jid = request(gpu, b["id"])
    gpu.client.post(f"/api/v1/admin/announcements/{b['id']}/cancel", headers=gpu.auth("admin"), json=dict(reason="withdrawn"))
    assert claim(gpu) is None and job_row(gpu, jid)["status"] == "failed"


def add_pending_edit(env, aid, text="SECRET DRAFT EDIT"):  # type: ignore[no-untyped-def]
    doc = get_one(env.store, "announcements", id=aid)["document_id"]
    env.store.insert("document_versions", dict(document_id=doc, version_number=2, extracted_text=text,
                                               content_hash="e" * 64, verification_status="pending_review"))


# the rules themselves: tests/test_approved_source.py (the same for every provider)
def gemini_like(env):  # type: ignore[no-untyped-def]
    """The API's own model (the path Gemini uses), recording every prompt."""
    from app.services.llm.base import ScriptedLLMProvider

    p = ScriptedLLMProvider(lambda s, x: "Scholarship guide 2026-12-01 intl@example.ac.kr")
    svc = env.app.state.services
    svc.announcement_translator.llm = svc.doc_translations.llm = p
    env.settings.translation_fallback_to_gemini = True    # the server's own model is used for announcements: opt-in
    return p


# ------------------------------------------------------------------- nothing waits forever
def old(env, jid, hours=49):  # type: ignore[no-untyped-def]
    env.store.update("ingestion_jobs", {"created_at": (datetime.now(UTC) - timedelta(hours=hours)).isoformat()}, {"id": jid})


def sweep(env):  # type: ignore[no-untyped-def]
    return env.app.state.services.gpu.sweep()


def alerts(env):  # type: ignore[no-untyped-def]
    return [n["title"] for n in env.store.t["admin_notifications"] if n["kind"] == "translation_failed"]


def set_worker(env, status):  # type: ignore[no-untyped-def]
    return env.client.patch(f"/api/v1/admin/gpu/workers/{env.worker['id']}", headers=env.auth("super_admin"), json=dict(status=status))


@pytest.mark.parametrize("state", ["never_seen", "offline", "paused", "revoked", "expired", "type_off"])
def test_without_a_usable_worker_requests_use_the_own_model(gpu, state):
    gemini_like(gpu)
    if state == "never_seen":
        gpu.store.update("gpu_workers", {"last_seen_at": None}, {"id": gpu.worker["id"]})
    elif state == "offline":
        seen(gpu, gpu.worker["id"], datetime.now(UTC) - timedelta(hours=25))
    elif state == "expired":
        gpu.store.update("gpu_workers", {"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}, {"id": gpu.worker["id"]})
    elif state == "type_off":
        gpu.settings.gpu_worker_job_types = "translate_document"
    else:
        set_worker(gpu, state)
    a = publish(gpu)
    jid = request(gpu, a["id"])
    assert job_row(gpu, jid)["executor"] == "local" and job_row(gpu, jid)["status"] == "succeeded"
    if state != "type_off":
        r = gpu.client.post("/api/v1/admin/gpu/jobs/queue-missing", headers=gpu.auth("admin"), json=dict(dry_run=False))
        assert r.json()["error"]["code"] == "gpu_worker_unavailable"


def test_without_a_usable_worker_an_announcement_request_waits_for_it(gpu):
    """TRANSLATION_FALLBACK_TO_GEMINI=false (default): no worker online -> the job waits, nothing paid is used."""
    gemini_like(gpu)                                   # a server model exists ...
    gpu.settings.translation_fallback_to_gemini = False  # ... but is not allowed for announcements
    set_worker(gpu, "revoked")
    a = publish(gpu)
    jid = request(gpu, a["id"])
    assert job_row(gpu, jid)["executor"] == "gpu" and job_row(gpu, jid)["status"] == "queued"
    d = gpu.client.get(f"/api/v1/admin/announcements/{a['id']}/translations/en", headers=gpu.auth("super_admin")).json()
    assert d["machine"]["state"] == "waiting_worker" and d["machine"]["configured"]["model"] == "translategemma:12b"
    assert gpu.app.state.services.announcement_translator.llm.calls == []          # type: ignore[attr-defined]


def test_jobs_nobody_fetches_fail_visibly_and_can_be_requested_again(gpu):
    gpu.settings.translation_fallback_to_gemini = True    # the old expiry rule applies to announcements only with it
    a = publish(gpu)
    young, aged = request(gpu, a["id"], "en"), request(gpu, a["id"], "id")
    old(gpu, aged)
    set_worker(gpu, "revoked")
    assert sweep(gpu) == dict(expired_leases=0, failed=1, rerouted=0)
    assert job_row(gpu, aged)["error_code"] == "gpu_worker_unavailable" and job_row(gpu, young)["status"] == "queued"
    assert "Translations were not fetched by the GPU worker" in alerts(gpu) and "No GPU worker is available" in alerts(gpu)
    n = len(alerts(gpu))
    sweep(gpu)
    assert len(alerts(gpu)) == n                                     # no alert storm
    gemini_like(gpu)
    assert job_row(gpu, request(gpu, a["id"], "id"))["status"] == "succeeded"     # not blocked by the old job


def test_expired_jobs_can_go_to_the_own_model_if_configured(gpu):
    gpu.settings.translation_fallback_to_gemini = True
    a = publish(gpu)
    jid = request(gpu, a["id"])
    old(gpu, jid)
    gpu.settings.gpu_worker_on_expiry = "local"
    assert sweep(gpu)["failed"] == 1                                 # no own model configured: fails instead of waiting
    jid = request(gpu, a["id"])
    old(gpu, jid)
    gemini_like(gpu)
    assert sweep(gpu)["rerouted"] == 1 and job_row(gpu, jid)["executor"] == "local"
    assert gpu.app.state.services.ingestion.run_job(jid)["status"] == "succeeded"
    assert row(gpu, a["id"])["provider"] == "scripted"


def test_disabling_the_feature_releases_every_open_job(gpu):
    a = publish(gpu)
    running = request(gpu, a["id"], "en")
    queued = request(gpu, a["id"], "id")
    job = claim(gpu)
    gpu.settings.gpu_worker_enabled = False
    assert sweep(gpu)["failed"] == 2
    assert {job_row(gpu, j)["error_code"] for j in (running, queued)} == {"gpu_worker_unavailable"}
    gemini_like(gpu)
    assert job_row(gpu, request(gpu, a["id"], "en"))["status"] == "succeeded"
    gpu.settings.gpu_worker_enabled = True               # switched on again: the old lease is worthless
    assert done(gpu, job).json()["error"]["code"] == "lease_lost"


def test_a_dead_workers_lease_ends_without_any_other_worker(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    claim(gpu)
    expire(gpu, jid)
    assert sweep(gpu)["expired_leases"] == 1 and job_row(gpu, jid)["status"] == "queued"


def test_a_job_stuck_while_its_result_was_stored_is_released(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    claim(gpu)
    gpu.store.update("ingestion_jobs", {"locked_by": f"gpu-submit:{gpu.worker['id']}"}, {"id": jid})     # API crashed here
    expire(gpu, jid)
    sweep(gpu)
    assert job_row(gpu, jid)["status"] == "queued" and claim(gpu)["id"] == jid


def test_sweep_without_the_migration_is_silent_and_stops(env):
    svc, calls = env.app.state.services, []

    def broken(table, *a, **k):  # type: ignore[no-untyped-def]
        calls.append(table)
        raise RuntimeError("column ingestion_jobs.executor does not exist")

    real, env.store.select = env.store.select, broken
    svc.gpu.sweep()
    svc.gpu.sweep()
    env.store.select = real
    assert calls == ["ingestion_jobs"]


def test_the_job_worker_loop_sweeps_and_survives_errors(gpu):
    jobs = gpu.app.state.services.jobs
    calls = []
    jobs.gpu = type("G", (), {"sweep": lambda self: calls.append(1)})()
    jobs._sweep_gpu()
    jobs._sweep_gpu()
    assert calls == [1]


def test_waiting_gpu_jobs_do_not_hold_back_scheduled_agents(gpu):
    a = publish(gpu)
    request(gpu, a["id"])
    agents = gpu.app.state.services.agents
    assert agents._content_work_pending() is False
    claim(gpu)
    assert agents._content_work_pending() is False
    gpu.store.insert("ingestion_jobs", dict(source_id=gpu.store.t["knowledge_sources"][0]["id"], job_type="ingest"))
    assert agents._content_work_pending() is True


def test_failed_announcement_translation_has_its_own_alert(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    job = claim(gpu)
    call(gpu, f"/jobs/{jid}/fail", lease_token=job["lease_token"], code="llm_context")
    assert any(t.startswith("Translation draft failed (en)") for t in alerts(gpu))
    assert not any(n["title"].startswith("Sync failed") for n in gpu.store.t["admin_notifications"])


# ------------------------------------------------------------------------------ results
def test_result_is_always_needs_review_and_never_public(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    job = claim(gpu)
    r = done(gpu, job, metrics=dict(duration_ms=1500, input_tokens=10, output_tokens=20, model_calls=2))
    assert r.json() == dict(status="succeeded", duplicate=False)
    t = row(gpu, a["id"])
    assert (t["translation_status"], t["provider"], t["model"]) == ("needs_review", "ollama", "translategemma:12b")
    assert t["warnings"] == [] and public(gpu, a["id"]) is None        # every check passed: still not public
    assert t["reviewed_by"] is None and job_row(gpu, jid)["status"] == "succeeded"
    listing = gpu.client.get("/api/v1/announcements", params={"display_language": "en"}).json()["items"][0]
    assert listing.get("display_title") in (None, KO[0])
    stats = gpu.client.get("/api/v1/admin/gpu/status", headers=gpu.auth("admin")).json()
    assert stats["last_24h"]["succeeded"] == 1 and stats["last_24h"]["average_seconds"] == 1.5


def test_a_reviewer_can_approve_the_draft_and_then_it_is_public(gpu):
    a = publish(gpu)
    request(gpu, a["id"])
    done(gpu, claim(gpu))
    r = gpu.client.post(f"/api/v1/admin/announcements/{a['id']}/translations/en/approve", headers=gpu.auth("super_admin"),
                        json=dict(original_verified=True))
    assert r.status_code == 200, r.text
    assert public(gpu, a["id"])["status"] == "verified"


def test_server_checks_run_on_worker_text(gpu):
    a = publish(gpu)
    request(gpu, a["id"])
    done(gpu, claim(gpu), body="Applications open soon at https://evil.example/pay 奖学金")
    types = {w["type"] for w in row(gpu, a["id"])["warnings"]}
    assert {"number", "email", "url_added", "language"} <= types


@pytest.mark.parametrize("bad", [dict(body=""), dict(body="a\x00b"), dict(title="x" * 501), dict(body="x" * 80_001),
                                 dict(model="bad model"), dict(translation_status="human_approved"),
                                 dict(metrics=dict(note="text")), dict(metrics=dict(duration_ms=-1))])
def test_malformed_results_are_rejected(gpu, bad):
    a = publish(gpu)
    request(gpu, a["id"])
    assert done(gpu, claim(gpu), **bad).status_code == 422
    assert row(gpu, a["id"])["translation_status"] == "todo"


def test_other_models_and_other_workers_are_refused(gpu):
    a = publish(gpu)
    request(gpu, a["id"])
    job = claim(gpu)
    assert done(gpu, job, model="other:1b").json()["error"]["code"] == "model_not_allowed"
    second = new_worker(gpu, "second")["token"]
    body = dict(lease_token=job["lease_token"], **GOOD)
    for path in ("heartbeat", "fail", "complete"):
        b = dict(lease_token=job["lease_token"]) if path == "heartbeat" else \
            dict(lease_token=job["lease_token"], code="llm_error") if path == "fail" else body
        assert call(gpu, f"/jobs/{job['id']}/{path}", second, **b).json()["error"]["code"] == "lease_lost"
    assert done(gpu, job | {"lease_token": str(uuid.uuid4())}).status_code == 409
    assert done(gpu, job).status_code == 200


# ---------------------------------------------------------------- durability, idempotency
def test_one_job_at_a_time_across_workers_and_repeated_claims(gpu):
    a = publish(gpu)
    request(gpu, a["id"], "en")
    request(gpu, a["id"], "id")
    lease = str(uuid.uuid4())
    first = claim(gpu, lease)
    again = claim(gpu, lease)                                   # the response was lost: same job, no extra attempt
    assert again["id"] == first["id"] and job_row(gpu, first["id"])["attempts"] == 1
    assert claim(gpu) is None and claim(gpu, token=new_worker(gpu, "second")["token"]) is None
    done(gpu, first)
    assert claim(gpu)["target_language"] == "id"


def test_completing_twice_stores_once(gpu):
    a = publish(gpu)
    request(gpu, a["id"])
    job = claim(gpu)
    assert done(gpu, job).json()["duplicate"] is False
    assert done(gpu, job, body="Something else 2026-12-01").json() == dict(status="succeeded", duplicate=True)
    assert row(gpu, a["id"])["body"] == GOOD["body"]
    revs = [r for r in gpu.store.t["translation_revisions"] if r["action"] == "generate"]
    assert len(revs) == 1


def test_lost_lease_requeues_and_the_late_result_is_discarded(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    job = claim(gpu)
    expire(gpu, jid)
    second = claim(gpu)
    assert second["id"] == jid and job_row(gpu, jid)["attempts"] == 2
    assert done(gpu, job, body="late").json()["error"]["code"] == "lease_lost"
    assert row(gpu, a["id"])["translation_status"] == "todo" and done(gpu, second).status_code == 200


def test_offline_worker_jobs_fail_visibly_after_the_attempt_limit(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    for _ in range(3):
        assert claim(gpu)["id"] == jid
        expire(gpu, jid)
    assert claim(gpu) is None
    assert (job_row(gpu, jid)["status"], job_row(gpu, jid)["error_code"]) == ("failed", "interrupted")


def test_heartbeat_renews_but_not_forever(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    job = claim(gpu)
    before = job_row(gpu, jid)["lease_expires_at"]
    r = call(gpu, f"/jobs/{jid}/heartbeat", lease_token=job["lease_token"]).json()
    assert r == dict(cancel=False, lease_seconds=180) and job_row(gpu, jid)["lease_expires_at"] > before
    gpu.store.update("ingestion_jobs", {"started_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}, {"id": jid})
    assert call(gpu, f"/jobs/{jid}/heartbeat", lease_token=job["lease_token"]).json()["cancel"] is True


def test_failures_are_retried_with_backoff_then_final(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    for attempt in range(1, 4):
        job = claim(gpu)
        r = call(gpu, f"/jobs/{jid}/fail", lease_token=job["lease_token"], code="llm_timeout")
        assert r.json()["status"] == ("queued" if attempt < 3 else "failed")
        again = call(gpu, f"/jobs/{jid}/fail", lease_token=job["lease_token"], code="llm_timeout")
        assert again.status_code == (409 if attempt < 3 else 200)            # counted once
        if attempt < 3:
            assert claim(gpu) is None                                         # backoff
            gpu.store.update("ingestion_jobs", {"run_after": "2020-01-01T00:00:00+00:00"}, {"id": jid})
    jid = request(gpu, a["id"])
    job = claim(gpu)
    assert call(gpu, f"/jobs/{jid}/fail", lease_token=job["lease_token"], code="llm_context").json()["status"] == "failed"
    assert call(gpu, f"/jobs/{jid}/fail", lease_token=job["lease_token"], code="anything I like").status_code == 422


def test_a_worker_that_shuts_down_gives_the_job_back_without_using_an_attempt(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    job = claim(gpu)
    call(gpu, f"/jobs/{jid}/fail", lease_token=job["lease_token"], code="worker_shutdown")
    assert (job_row(gpu, jid)["status"], job_row(gpu, jid)["attempts"]) == ("queued", 0)
    gpu.store.update("ingestion_jobs", {"statistics": {"releases": 20}}, {"id": jid})
    job = claim(gpu)
    call(gpu, f"/jobs/{jid}/fail", lease_token=job["lease_token"], code="worker_shutdown")
    assert job_row(gpu, jid)["attempts"] == 1                                  # not for free forever


def test_a_storage_failure_gives_the_lease_back(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    job = claim(gpu)
    tr = gpu.app.state.services.announcement_translator
    real, tr.store_result = tr.store_result, lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("db down"))
    with pytest.raises(RuntimeError):
        done(gpu, job)
    tr.store_result = real
    assert job_row(gpu, jid)["status"] == "running" and done(gpu, job).json()["status"] == "succeeded"


def test_a_result_that_is_being_stored_is_not_stored_again(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    job = claim(gpu)
    gpu.store.update("ingestion_jobs", {"locked_by": f"gpu-submit:{gpu.worker['id']}"}, {"id": jid})
    assert done(gpu, job).json()["error"]["code"] == "submission_in_progress"


def test_changed_original_discards_the_result_and_queues_the_new_text(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    job = claim(gpu)
    gpu.store.update("announcements", {"title": "장학금 신청 안내 (연장)"}, {"id": a["id"]})
    assert done(gpu, job).json()["status"] == "requeued" and row(gpu, a["id"])["translation_status"] == "todo"
    assert job_row(gpu, jid)["attempts"] == 0
    second = claim(gpu)
    assert second["title"].endswith("(연장)") and done(gpu, second).json()["status"] == "succeeded"


def test_human_work_is_never_replaced(gpu):
    a = publish(gpu)
    assign(gpu, "supporter", "en")
    jid = request(gpu, a["id"])
    job = claim(gpu)
    r = gpu.client.put(f"/api/v1/admin/announcements/{a['id']}/translations/en", headers=gpu.auth("supporter"),
                       json=dict(title="Human", body="Human text 2026-12-01", translation_status="machine_draft"))
    assert r.status_code == 200, r.text
    assert done(gpu, job).json()["error"] == "human_draft_exists" and row(gpu, a["id"])["title"] == "Human"
    # force was requested before another edit: the later edit wins
    jid = request(gpu, a["id"], force=True)
    gpu.store.update("announcement_translations", {"last_edited_at": datetime.now(UTC).isoformat()}, {"id": row(gpu, a["id"])["id"]})
    assert claim(gpu) is None and job_row(gpu, jid)["error_code"] == "human_draft_exists"


# ------------------------------------------------------------- pause, cancel, backfill, documents
def test_pause_and_resume(gpu):
    a = publish(gpu)
    request(gpu, a["id"])
    url = f"/api/v1/admin/gpu/workers/{gpu.worker['id']}"
    gpu.client.patch(url, headers=gpu.auth("super_admin"), json=dict(status="paused"))
    assert call(gpu, "/claim", lease_token=str(uuid.uuid4())).json() == dict(state="paused", job=None)
    gpu.client.patch(url, headers=gpu.auth("super_admin"), json=dict(status="active"))
    assert claim(gpu) is not None


def test_cancel_queued_and_running(gpu):
    a = publish(gpu)
    jid = request(gpu, a["id"])
    url = f"/api/v1/admin/gpu/jobs/{jid}/cancel"
    assert gpu.client.post(url, headers=gpu.auth("supporter")).status_code == 403
    assert gpu.client.post(url, headers=gpu.auth("admin")).json()["status"] == "cancelled" and claim(gpu) is None
    jid = request(gpu, a["id"])                                     # can be requested again
    job = claim(gpu)
    assert gpu.client.post(url.replace(url.split("/")[-2], jid), headers=gpu.auth("admin")).json()["status"] == "cancelling"
    assert call(gpu, f"/jobs/{jid}/heartbeat", lease_token=job["lease_token"]).json()["cancel"] is True
    assert done(gpu, job).json()["status"] == "cancelled" and row(gpu, a["id"])["translation_status"] == "todo"
    assert job_row(gpu, jid)["error_code"] == "cancelled"
    assert gpu.client.post(url, headers=gpu.auth("admin")).status_code == 409


def test_queue_missing_languages(gpu):
    publish(gpu)
    url, h = "/api/v1/admin/gpu/jobs/queue-missing", gpu.auth("admin")
    plan = gpu.client.post(url, headers=h, json={}).json()
    # Release 1: a Korean announcement gets machine drafts in English and Indonesian only (not vi / zh-CN)
    assert plan["dry_run"] is True and plan["missing"] == 2 and not gpu.store.select(
        "ingestion_jobs", Query(eq={"executor": "gpu"}))[0]
    assert {i["language"] for i in plan["next"]} == {"en", "id"}
    r = gpu.client.post(url, headers=h, json=dict(dry_run=False, limit=1)).json()
    assert len(r["queued"]) == 1 and gpu.client.post(url, headers=h, json={}).json()["missing"] == 1
    assert gpu.client.post(url, headers=gpu.auth("supporter"), json={}).status_code == 403


def test_document_translations_stay_on_the_server_unless_enabled_for_the_gpu(gpu):
    """GPU_WORKER_JOB_TYPES defaults to announcements only: documents are never routed by accident."""
    assert gpu.settings.gpu_worker_job_types == "translate_announcement"
    doc = make_doc(gpu, title="Visa", text="D-2 extension: apply 4 months before. Fee 30,000 KRW.", language="ko")
    gemini_like(gpu)
    r = gpu.client.post(f"/api/v1/admin/documents/{doc['document_id']}/translations/drafts", headers=gpu.auth("super_admin"),
                        json=dict(languages=["en"]))
    assert r.status_code == 202, r.text
    jobs = gpu.store.select("ingestion_jobs", Query(eq={"job_type": "translate_document"}))[0]
    assert jobs and all(j.get("executor") != "gpu" for j in jobs)


def test_document_translation_and_summary_drafts(gpu):
    gpu.settings.gpu_worker_job_types = "translate_announcement,translate_document"   # explicitly enabled

    def ask(doc_id):  # type: ignore[no-untyped-def]
        r = gpu.client.post(f"/api/v1/admin/documents/{doc_id}/translations/drafts", headers=gpu.auth("super_admin"),
                            json=dict(languages=["en"]))
        assert r.status_code == 202, r.text

    short = make_doc(gpu, "기숙사 안내", "입사일은 2027-02-24입니다. 학생증을 가져오세요.", language="ko")
    ask(short["document_id"])
    job = claim(gpu)
    assert (job["kind"], job["mode"]) == ("document", "translate")
    assert done(gpu, job, title="Dormitory", body="Move-in is on 2027-02-24. Bring your student ID.").json()["status"] == "succeeded"
    long = make_doc(gpu, "긴 안내", "\n\n".join(f"{i}번째 문단입니다. 외국인 유학생을 위한 생활 안내 내용입니다." * 4 for i in range(120)),
                    language="ko")
    ask(long["document_id"])
    job = claim(gpu)
    assert job["mode"] == "summarize" and job["max_source_chars"] == 12000
    assert done(gpu, job, title="Long guide", body="This document is a guide for international students.").json()["status"] == "succeeded"
    rows = {t["title"]: t for t in gpu.store.t["document_translations"] if t["translation_status"] != "todo"}
    assert rows["Dormitory"]["scope"] == "full" and rows["Long guide"]["scope"] == "summary"
    assert all(t["translation_status"] == "needs_review" for t in rows.values())
    for d in (short, long):
        out = gpu.client.get(f"/api/v1/knowledge/documents/{d['document_id']}", params={"lang": "en"}).json()
        assert "Long guide" not in json.dumps(out) and "Move-in is on" not in json.dumps(out)


def test_logs_contain_no_token_and_no_content(gpu, caplog):
    with caplog.at_level(logging.DEBUG):
        a = publish(gpu)
        request(gpu, a["id"])
        done(gpu, claim(gpu))
        call(gpu, "/claim", "schgw_bad_token_value", lease_token=str(uuid.uuid4()))
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "gpu complete worker=school-gpu" in logs
    for secret in (gpu.worker["token"], "schgw_bad_token_value", GOOD["body"], KO[1]):
        assert secret not in logs


def test_the_evaluated_translation_model_is_accepted_by_default(gpu):
    """TranslateGemma 12B was selected by the benchmark; a server with default settings must accept its drafts (found by the browser
    journey: without it every draft was refused as model_not_allowed)."""
    a = publish(gpu)
    request(gpu, a["id"])
    r = done(gpu, claim(gpu), model="translategemma:12b")
    assert r.status_code == 200, r.text
    assert row(gpu, a["id"])["model"] == "translategemma:12b" and row(gpu, a["id"])["translation_status"] == "needs_review"

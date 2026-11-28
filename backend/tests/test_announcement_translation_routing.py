"""Announcement translation, final routing: TranslateGemma 12B on the university GPU worker translates announcements
(ko, en, id only), Gemini is never used for them unless TRANSLATION_FALLBACK_TO_GEMINI, people approve every draft.

The letters refer to the test list of the request (A-T). The worker is driven through its real API endpoints; the
real worker client against a mocked Ollama is covered by tests/integration/test_gpu_worker_integration.py.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.repositories.base import Query, get_one
from app.services.llm.base import LLMError, ScriptedLLMProvider
from tests.test_announcements import create
from tests.test_document_translations import assign
from tests.test_gpu_worker import call, claim, expire, gpu, job_row, new_worker, row, seen, sweep

_ = gpu      # fixture: GPU_WORKER_ENABLED, one worker that contacted the server just now
MODEL = "translategemma:12b"
KO = ("기숙사 입사 안내", "2027년 2월 24일 10:00부터 입사합니다.\n\n신청: https://sch.ac.kr/dorm  문의: dorm@sch.ac.kr")
ID = ("Panduan masuk asrama", "Masuk asrama mulai 24 Februari 2027 pukul 10:00.\n\n"
                              "Pendaftaran: https://sch.ac.kr/dorm  Pertanyaan: dorm@sch.ac.kr")
EN = ("Dormitory move-in guide", "Move-in starts on 24 February 2027 at 10:00.\n\n"
                                 "Apply: https://sch.ac.kr/dorm  Questions: dorm@sch.ac.kr")


@pytest.fixture
def server_model(gpu):  # type: ignore[no-untyped-def]
    """A Gemini-like server model that records every call: it must stay unused for announcements by default."""
    p = ScriptedLLMProvider(lambda s, x: "SHOULD NOT BE USED", model="gemini-3.5-flash-lite")
    svc = gpu.app.state.services
    svc.announcement_translator.llm = p
    assert gpu.settings.translation_fallback_to_gemini is False        # the default
    return p


def publish(env, targets=None, title=KO[0], body=KO[1], language="ko"):  # type: ignore[no-untyped-def]
    kw = {} if targets is None else {"translation_targets": targets}
    a = create(env, submit=True, title=title, body=body, original_language=language, **kw)
    r = env.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=env.auth("admin"), json={})
    assert r.status_code == 200, r.text
    return a


def ann_jobs(env, aid=None):  # type: ignore[no-untyped-def]
    rows = env.store.select("ingestion_jobs", Query(eq={"job_type": "translate_announcement"}))[0]
    return [j for j in rows if aid is None or (j.get("payload") or {}).get("announcement_id") == aid]


def ask(env, aid, lang, role="admin", **params):  # type: ignore[no-untyped-def]
    return env.client.post(f"/api/v1/admin/announcements/{aid}/translations/{lang}/machine-translate",
                           headers=env.auth(role), params=params)


def detail(env, aid, lang, role="super_admin"):  # type: ignore[no-untyped-def]
    r = env.client.get(f"/api/v1/admin/announcements/{aid}/translations/{lang}", headers=env.auth(role))
    assert r.status_code == 200, r.text
    return r.json()


def student_view(env, aid, lang):  # type: ignore[no-untyped-def]
    r = env.client.get(f"/api/v1/announcements/{aid}", params={"lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


def work(env, title=ID[0], body=ID[1], model=MODEL):  # type: ignore[no-untyped-def]
    """The GPU worker: claims the next job with its model and hands in TranslateGemma's draft."""
    job = claim(env, model=model)
    assert job is not None
    r = call(env, f"/jobs/{job['id']}/complete", lease_token=job["lease_token"], title=title, body=body, model=model,
             metrics=dict(duration_ms=8800, input_tokens=420, output_tokens=180, model_calls=2, parts=1))
    assert r.status_code == 200, r.text
    return job


# ------------------------------------------------------------------ the production failure (reproduced, then fixed)
def test_a_task_without_a_job_is_ready_not_queued(env):
    """Production: 'To do' + 'Queued' + a disabled button and no job at all. A task without a job is 'ready', and the
    panel says why a request cannot be made instead of showing a disabled button without a reason."""
    assign(env, "admin", "en")
    a = publish(env)                                     # AUTO_TRANSLATE_ANNOUNCEMENTS off, no languages chosen
    d = detail(env, a["id"], "en", role="admin")
    assert d["translation"]["translation_status"] == "todo" and d["machine"]["job"] is None
    assert d["machine"]["state"] == "ready"              # was "pending" -> "Queued" and a disabled button
    assert d["machine"]["blocked"]["code"] == "translation_worker_disabled"     # the reason, shown next to the button
    assert ann_jobs(env) == []


# ------------------------------------------------------------------ A-F manual request -> worker -> review -> students
def test_manual_request_goes_to_the_translategemma_worker_and_becomes_a_private_draft(server_model, gpu):
    a = publish(gpu)
    r = ask(gpu, a["id"], "id")                                                          # A
    assert r.status_code == 202, r.text
    j = job_row(gpu, r.json()["job_id"])
    assert (j["executor"], j["status"]) == ("gpu", "queued")
    d = detail(gpu, a["id"], "id")
    assert d["machine"]["state"] == "pending" and d["machine"]["configured"] == dict(
        route="gpu_worker", provider="ollama", model=MODEL, fallback_to_gemini=False)
    job = claim(gpu, model=MODEL)                                                        # B: only public text leaves
    assert set(job) >= {"title", "body", "source_language", "target_language"} and "dorm@sch.ac.kr" in job["body"]
    assert not {"requested_by", "actor", "email", "conversation", "ticket"} & set(job)
    assert detail(gpu, a["id"], "id")["machine"]["state"] == "processing"
    r = call(gpu, f"/jobs/{job['id']}/complete", lease_token=job["lease_token"], title=ID[0], body=ID[1], model=MODEL,
             metrics=dict(duration_ms=9000, input_tokens=400, output_tokens=170, model_calls=2, parts=1))
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    t = row(gpu, a["id"], "id")                                                          # C: private machine draft
    assert (t["translation_status"], t["provider"], t["model"], t["title"]) == ("needs_review", "ollama", MODEL, ID[0])
    assert student_view(gpu, a["id"], "id")["translation"] is None                       # F: never public unreviewed
    assert server_model.calls == []                                                      # no Gemini call at all


def test_reviewer_edits_and_approves_then_students_see_it(gpu):
    assign(gpu, "supporter", "id")                                    # the Indonesian reviewer
    a = publish(gpu)
    assert ask(gpu, a["id"], "id").status_code == 202
    work(gpu)
    url = f"/api/v1/admin/announcements/{a['id']}/translations/id"
    h = gpu.auth("supporter")
    note = [n for n in gpu.store.t["user_notifications"] if n["kind"] == "translation_review"]
    assert note and note[0]["user_id"] == gpu.users["supporter"]                         # the reviewer is told
    edited = ID[1].replace("Pertanyaan", "Informasi")
    assert gpu.client.put(url, headers=h, json=dict(title=ID[0], body=edited, submit=True)).status_code == 200   # D
    assert student_view(gpu, a["id"], "id")["translation"] is None
    r = gpu.client.post(f"{url}/approve", headers=h, json=dict(original_verified=True))
    assert r.status_code == 200, r.text
    tr = student_view(gpu, a["id"], "id")["translation"]                                 # E
    assert tr["status"] == "verified" and tr["body"] == edited
    assert student_view(gpu, a["id"], "en")["translation"] is None                       # other languages: original


def test_a_reviewer_of_one_language_cannot_approve_another(gpu):                         # Q
    assign(gpu, "supporter", "id")
    a = publish(gpu, targets=["en", "id"])
    while (job := claim(gpu, model=MODEL)) is not None:
        lang = job["target_language"]
        title, body = (EN if lang == "en" else ID)
        call(gpu, f"/jobs/{job['id']}/complete", lease_token=job["lease_token"], title=title, body=body, model=MODEL,
             metrics={})
    r = gpu.client.post(f"/api/v1/admin/announcements/{a['id']}/translations/en/approve", headers=gpu.auth("supporter"),
                        json=dict(original_verified=True))
    assert r.status_code == 403
    assert row(gpu, a["id"], "en")["translation_status"] == "needs_review"


# ------------------------------------------------------------------ G-J languages chosen at publication
def test_languages_chosen_when_writing_are_queued_once_after_approval(server_model, gpu):     # G, H
    a = create(gpu, submit=False, title=KO[0], body=KO[1], translation_targets=["en", "id"])
    assert a["translation_targets"] == ["en", "id"]
    assert gpu.client.post(f"/api/v1/admin/announcements/{a['id']}/submit", headers=gpu.auth("admin")).status_code == 200
    assert ann_jobs(gpu, a["id"]) == []                                  # nothing before the original is approved
    r = gpu.client.post(f"/api/v1/admin/announcements/{a['id']}/reject", headers=gpu.auth("admin"), json=dict(reason="date?"))
    assert r.status_code == 200
    assert gpu.client.patch(f"/api/v1/admin/announcements/{a['id']}", headers=gpu.auth("admin"),
                            json=dict(body=KO[1] + "\n\n기숙사 사무실 운영 시간: 09:00-18:00")).status_code == 200
    assert gpu.client.post(f"/api/v1/admin/announcements/{a['id']}/submit", headers=gpu.auth("admin")).status_code == 200
    assert gpu.client.get(f"/api/v1/admin/announcements/{a['id']}", headers=gpu.auth("admin")).json()[
        "translation_targets"] == ["en", "id"]                            # survived reject -> edit -> resubmit
    assert gpu.client.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=gpu.auth("admin"), json={}).status_code == 200
    jobs = ann_jobs(gpu, a["id"])
    assert sorted(j["payload"]["language"] for j in jobs) == ["en", "id"] and {j["executor"] for j in jobs} == {"gpu"}
    # repeated publication events / the same choice saved again: still exactly these two jobs     # J
    svc = gpu.app.state.services
    svc.translations.on_original_published(a["id"], None)
    svc.announcement_translator.on_published(a["id"], None)
    r = gpu.client.put(f"/api/v1/admin/announcements/{a['id']}/translation-targets", headers=gpu.auth("admin"),
                       json=dict(languages=["en", "id"]))
    assert r.status_code == 200 and r.json()["queued"] == [] or {x["job_id"] for x in r.json()["queued"]} <= {j["id"] for j in jobs}
    assert len(ann_jobs(gpu, a["id"])) == 2 and server_model.calls == []


@pytest.mark.parametrize("original,chosen,expected", [
    ("ko", ["ko", "en", "id"], ["en", "id"]), ("en", ["en", "ko"], ["ko"]), ("id", ["id", "ko", "en"], ["ko", "en"]),
    ("ko", [], [])])
def test_the_original_language_is_never_a_target(gpu, original, chosen, expected):                  # I
    title, body = {"ko": KO, "en": EN, "id": ID}[original]
    a = publish(gpu, targets=chosen, title=title, body=body, language=original)
    assert sorted(j["payload"]["language"] for j in ann_jobs(gpu, a["id"])) == sorted(expected)
    r = ask(gpu, a["id"], original)
    assert r.status_code == 409


def test_vietnamese_and_chinese_are_never_machine_translated(gpu):
    a = publish(gpu)
    for lang in ("vi", "zh-CN"):
        assert ask(gpu, a["id"], lang).json()["error"]["code"] == "language_out_of_scope"
    r = gpu.client.put(f"/api/v1/admin/announcements/{a['id']}/translation-targets", headers=gpu.auth("admin"),
                       json=dict(languages=["vi"]))
    assert r.status_code == 422


def test_only_admins_change_the_languages_once_submitted(gpu):
    a = create(gpu, role="supporter", submit=True, title=KO[0], body=KO[1], translation_targets=["en"])
    r = gpu.client.put(f"/api/v1/admin/announcements/{a['id']}/translation-targets", headers=gpu.auth("supporter"),
                       json=dict(languages=["en", "id"]))
    assert r.status_code == 403
    r = gpu.client.put(f"/api/v1/admin/announcements/{a['id']}/translation-targets", headers=gpu.auth("admin"),
                       json=dict(languages=["en", "id"]))
    assert r.status_code == 200 and r.json()["translation_targets"] == ["en", "id"] and r.json()["queued"] == []


# ------------------------------------------------------------------ K, L, S: no Gemini, no GPU, budgets
def test_gemini_down_or_out_of_budget_does_not_matter_for_announcements(server_model, gpu):            # K, L
    def broken(system, prompt):  # type: ignore[no-untyped-def]
        raise LLMError("llm_quota", "quota exhausted")
    server_model.fn = broken
    gpu.settings.llm_background_daily_attempts = 0
    gpu.settings.translation_daily_job_limit = 0
    a = publish(gpu, targets=["en"])
    work(gpu, *EN)
    assert row(gpu, a["id"], "en")["translation_status"] == "needs_review"


def test_without_the_gpu_worker_the_site_works_and_nothing_is_charged(server_model, env):              # S
    env.settings.gpu_worker_enabled = False                                # GPU_WORKER_ENABLED=false (production now)
    a = publish(env, targets=["en", "id"])                                 # publication is never blocked
    assert student_view(env, a["id"], "ko")["title"] == KO[0]
    assert ann_jobs(env) == [] and server_model.calls == []
    r = ask(env, a["id"], "en")
    assert r.status_code == 409 and r.json()["error"]["code"] == "translation_worker_disabled"
    assert "GPU" in r.json()["error"]["message"]


def test_a_server_job_left_from_before_never_reaches_gemini(server_model, gpu):
    """Real enforcement of TRANSLATION_FALLBACK_TO_GEMINI=false: even a job of the API's own worker (queued before
    the setting changed, or rerouted) fails without a model call."""
    gpu.settings.translation_fallback_to_gemini = True
    seen(gpu, gpu.worker["id"], datetime.now(UTC) - timedelta(hours=30))  # worker offline -> server route
    a = publish(gpu)
    svc = gpu.app.state.services
    svc.announcement_translator.jobs = None                                # do not run it yet
    jid = ask(gpu, a["id"], "en").json()["job_id"]
    assert job_row(gpu, jid)["executor"] == "local"
    gpu.settings.translation_fallback_to_gemini = False
    out = svc.ingestion.run_job(jid)
    assert out["status"] == "failed" and out["error_code"] == "translation_fallback_disabled"
    assert server_model.calls == []


def test_explicit_fallback_uses_only_the_translation_model_never_the_chat_fallback(gpu):
    from app.services.translation.auto import translation_llm

    s = gpu.settings.model_copy(update=dict(llm_provider="gemini", llm_api_key="test-key", translation_model="",
                                            gemini_primary_model="gemini-3.6-flash",
                                            gemini_fallback_model="gemini-3.5-flash-lite"))
    from app.services.llm.base import build_llm_from_settings

    bg = translation_llm(s, build_llm_from_settings(s))
    assert getattr(bg, "primary", None) == "gemini-3.6-flash" and not getattr(bg, "fallback", "")


# ------------------------------------------------------------------ M, N: crash and restart of the worker
def test_a_worker_that_dies_during_translation_gives_the_job_back(server_model, gpu):                  # M
    a = publish(gpu, targets=["id"])
    first = claim(gpu, model=MODEL)
    expire(gpu, first["id"])                                                 # no heartbeat any more
    assert detail(gpu, a["id"], "id")["machine"]["job"]["stalled"] is True
    sweep(gpu)
    assert job_row(gpu, first["id"])["status"] == "queued"
    again = claim(gpu, model=MODEL)
    assert again["id"] == first["id"]
    call(gpu, f"/jobs/{again['id']}/complete", lease_token=again["lease_token"], title=ID[0], body=ID[1], model=MODEL,
         metrics={})
    late = call(gpu, f"/jobs/{first['id']}/complete", lease_token=first["lease_token"], title="late", body="late text",
                model=MODEL, metrics={})
    assert late.status_code == 409                                           # the dead attempt cannot write
    assert row(gpu, a["id"], "id")["title"] == ID[0] and len(ann_jobs(gpu, a["id"])) == 1


def test_an_offline_worker_leaves_jobs_waiting_and_they_run_when_it_is_back(server_model, gpu):       # N
    seen(gpu, gpu.worker["id"], datetime.now(UTC) - timedelta(hours=30))
    a = publish(gpu, targets=["en"])
    j = ann_jobs(gpu, a["id"])[0]
    assert (j["executor"], j["status"]) == ("gpu", "queued")
    d = detail(gpu, a["id"], "en")
    assert d["machine"]["state"] == "waiting_worker" and d["machine"]["worker"]["online"] is False
    gpu.store.update("ingestion_jobs", {"created_at": (datetime.now(UTC) - timedelta(hours=72)).isoformat()}, {"id": j["id"]})
    sweep(gpu)                                                               # days later: still waiting, never failed
    assert job_row(gpu, j["id"])["status"] == "queued" and server_model.calls == []
    assert any("keep waiting" in (n["message"] or "") for n in gpu.store.t["admin_notifications"])
    assert ask(gpu, a["id"], "en").json()["job_id"] == j["id"]               # asking again: the same job, no duplicate
    work(gpu, *EN)                                                           # the worker is back
    assert row(gpu, a["id"], "en")["translation_status"] == "needs_review"


# ------------------------------------------------------------------ O, P: changed / cancelled originals, approved work
def test_a_cancelled_original_is_not_translated(gpu):                                                  # O
    a = publish(gpu, targets=["en"])
    assert gpu.client.post(f"/api/v1/admin/announcements/{a['id']}/cancel", headers=gpu.auth("admin"),
                           json=dict(reason="withdrawn")).status_code == 200
    assert claim(gpu, model=MODEL) is None                                   # finished on the server, nothing sent
    assert job_row(gpu, ann_jobs(gpu, a["id"])[0]["id"])["status"] == "failed"


def test_approved_translations_are_protected(gpu):                                                    # P
    assign(gpu, "supporter", "en")
    a = publish(gpu, targets=["en"])
    work(gpu, *EN)
    assert gpu.client.post(f"/api/v1/admin/announcements/{a['id']}/translations/en/approve",
                           headers=gpu.auth("supporter"), json=dict(original_verified=True)).status_code == 200
    r = ask(gpu, a["id"], "en", role="super_admin", force=True)
    assert r.status_code == 409 and r.json()["error"]["code"] == "translation_approved"
    assert detail(gpu, a["id"], "en")["machine"]["blocked"]["code"] == "translation_approved"
    r = gpu.client.post("/api/v1/admin/translations/backfill", headers=gpu.auth("admin"),
                        json=dict(languages=["en"], dry_run=True))
    assert r.json()["missing"] == 0
    assert student_view(gpu, a["id"], "en")["translation"]["body"] == EN[1]


def test_only_translategemma_drafts_are_accepted_for_announcements(gpu):
    a = publish(gpu, targets=["en"])
    assert claim(gpu, model="qwen2.5:7b-instruct") is None                   # a Qwen worker gets no announcement job
    job = claim(gpu)                                                         # an older worker that does not say
    r = call(gpu, f"/jobs/{job['id']}/complete", lease_token=job["lease_token"], title=EN[0], body=EN[1],
             model="qwen2.5:7b-instruct", metrics={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "model_not_allowed"
    assert row(gpu, a["id"], "en")["translation_status"] == "todo"


# ------------------------------------------------------------------ existing announcements: bounded backfill
def test_backfill_of_existing_announcements_is_bounded_and_idempotent(server_model, gpu):
    ids = [publish(gpu, title=f"{KO[0]} {i}", body=f"{KO[1]}\n\n안내 번호 {i}")["id"] for i in range(3)]
    url, h = "/api/v1/admin/translations/backfill", gpu.auth("admin")
    plan = gpu.client.post(url, headers=h, json=dict(languages=["en", "id"], dry_run=True)).json()
    assert plan["missing"] == 6 and plan["queued"] == [] and ann_jobs(gpu) == []
    out = gpu.client.post(url, headers=h, json=dict(languages=["en", "id"], limit=4, dry_run=False)).json()
    assert len(out["queued"]) == 4 and len(ann_jobs(gpu)) == 4
    out = gpu.client.post(url, headers=h, json=dict(languages=["en", "id"], limit=50, dry_run=False)).json()
    assert len(out["queued"]) == 2 and len(ann_jobs(gpu)) == 6
    again = gpu.client.post(url, headers=h, json=dict(languages=["en", "id"], limit=50, dry_run=False)).json()
    assert again["queued"] == [] and len(ann_jobs(gpu)) == 6                # nothing twice
    assert {j["executor"] for j in ann_jobs(gpu)} == {"gpu"} and server_model.calls == []
    assert gpu.client.post(url, headers=gpu.auth("supporter"), json=dict(dry_run=True)).status_code == 403
    r = gpu.client.post(url, headers=h, json=dict(languages=["vi"], dry_run=False))     # never falls back to others
    assert r.status_code == 422 and len(ann_jobs(gpu)) == 6
    assert len(ids) == 3


def test_a_job_with_unreadable_times_is_not_reported_stalled(gpu):
    from app.services.translation.auto import job_stalled

    assert job_stalled(dict(status="queued", run_after="?", created_at="?"), gpu.settings) is False


def test_the_translation_list_shows_machine_state_model_and_last_attempt(gpu):
    a = publish(gpu, targets=["en", "id"])
    work(gpu, *EN)
    items = gpu.client.get("/api/v1/admin/translations", headers=gpu.auth("super_admin")).json()["items"]
    by = {i["language_code"]: i for i in items if i["announcement_id"] == a["id"]}
    assert by["en"]["machine"]["state"] == "needs_review" and by["en"]["machine"]["model"] == MODEL
    assert by["id"]["machine"]["state"] == "pending" and by["id"]["machine"]["executor"] == "gpu"
    assert by["vi"]["machine"]["state"] == "manual"                          # Release 1: no machine drafts in Vietnamese


# ------------------------------------------------------------------ the explicit fallback (opt-in) still works
def test_with_the_fallback_a_stalled_server_job_is_resumed_not_duplicated(env):
    env.settings.translation_fallback_to_gemini = True
    svc = env.app.state.services
    p = ScriptedLLMProvider(lambda s, x: x.split("<source_text>\n")[-1].split("\n</source_text>")[0], model="gemini-x")
    svc.announcement_translator.llm = p
    a = publish(env)
    jobs_runner = svc.announcement_translator.jobs
    svc.announcement_translator.jobs = None                                  # the worker 'sleeps'
    jid = ask(env, a["id"], "en").json()["job_id"]
    env.store.update("ingestion_jobs", {"created_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
                                        "run_after": (datetime.now(UTC) - timedelta(minutes=10)).isoformat()}, {"id": jid})
    assert detail(env, a["id"], "en")["machine"]["state"] == "stalled"
    svc.announcement_translator.jobs = jobs_runner
    assert ask(env, a["id"], "en").json()["job_id"] == jid                   # resumed, not a second job
    assert job_row(env, jid)["status"] == "succeeded" and len(ann_jobs(env)) == 1
    assert job_row(env, jid)["statistics"]["usage"]["model"] == "gemini-x"
    assert uuid.UUID(jid) and get_one(env.store, "announcement_translations", announcement_id=a["id"],
                                      language_code="en")["translation_status"] in ("machine_draft", "needs_review")


def test_the_gpu_worker_is_never_given_a_second_job_at_once(gpu):
    publish(gpu, targets=["en", "id"])
    first = claim(gpu, model=MODEL)
    other = new_worker(gpu, name="second-gpu")
    assert claim(gpu, model=MODEL) is None and first is not None             # GPU_WORKER_MAX_RUNNING=1
    r = call(gpu, "/claim", token=other["token"], lease_token=str(uuid.uuid4()), model=MODEL)
    assert r.json()["job"] is None


def test_waiting_announcement_jobs_have_an_explicit_expiry_and_never_reach_gemini(server_model, gpu):
    seen(gpu, gpu.worker["id"], datetime.now(UTC) - timedelta(hours=30))        # worker offline
    a = publish(gpu, targets=["en", "id"])
    en, id_ = sorted(ann_jobs(gpu, a["id"]), key=lambda j: j["payload"]["language"])
    assert gpu.settings.gpu_worker_announcement_max_wait_hours == 168           # 7 days by default
    gpu.store.update("ingestion_jobs", {"created_at": (datetime.now(UTC) - timedelta(hours=169)).isoformat()}, {"id": en["id"]})
    gpu.store.update("ingestion_jobs", {"created_at": (datetime.now(UTC) - timedelta(hours=100)).isoformat()}, {"id": id_["id"]})
    sweep(gpu)
    assert (job_row(gpu, en["id"])["status"], job_row(gpu, en["id"])["error_code"]) == ("failed", "gpu_worker_unavailable")
    assert job_row(gpu, id_["id"])["status"] == "queued"                         # still within the limit
    assert detail(gpu, a["id"], "en")["machine"]["state"] == "failed"            # visible, "Translate again"
    assert server_model.calls == []                                              # never handed to Gemini
    r = ask(gpu, a["id"], "en")                                                  # requested again: a new GPU job
    assert r.status_code == 202 and job_row(gpu, r.json()["job_id"])["executor"] == "gpu"


def test_an_expiry_of_zero_waits_however_long_it_takes(gpu):
    gpu.settings.gpu_worker_announcement_max_wait_hours = 0
    seen(gpu, gpu.worker["id"], datetime.now(UTC) - timedelta(hours=30))
    a = publish(gpu, targets=["en"])
    j = ann_jobs(gpu, a["id"])[0]
    gpu.store.update("ingestion_jobs", {"created_at": (datetime.now(UTC) - timedelta(days=60)).isoformat()}, {"id": j["id"]})
    sweep(gpu)
    assert job_row(gpu, j["id"])["status"] == "queued"


def test_staged_activation_credential_without_routing(server_model, gpu):
    """Activation step B: GPU_WORKER_ENABLED=true with GPU_WORKER_JOB_TYPES empty - the credential can be created and the
    worker's HTTPS + authentication tested against production, while no translation is routed to it or charged."""
    gpu.settings.gpu_worker_job_types = ""
    a = publish(gpu, targets=["en"])
    assert ann_jobs(gpu, a["id"]) == []                                         # nothing routed
    r = ask(gpu, a["id"], "en")
    assert r.status_code == 409 and r.json()["error"]["code"] == "translation_worker_disabled"
    other = new_worker(gpu, name="school-gpu-2")                                # the admin page works
    r = call(gpu, "/claim", token=other["token"], lease_token=str(uuid.uuid4()), model=MODEL)
    assert r.status_code == 200 and r.json() == {"state": "idle", "job": None}  # authenticated, nothing to do
    assert server_model.calls == []

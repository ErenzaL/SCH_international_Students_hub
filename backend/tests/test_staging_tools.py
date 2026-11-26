"""Staging tools refuse production and anything that is not synthetic; the hosted memory check judges its samples correctly. No network."""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


boot = load("staging_bootstrap")
check = load("staging_memory_check")
STAGING, PROD = "stagingrefaaaaaaaaaa", "prodrefbbbbbbbbbbbbb"


def jwt(**claims) -> str:  # type: ignore[no-untyped-def]
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'HS256'})}.{enc(claims)}.signature"


class FakeHttp:
    def __init__(self, status: int = 200):
        self.status, self.urls = status, []

    def get(self, url, headers=None, timeout=None):  # type: ignore[no-untyped-def]
        self.urls.append(url)
        return SimpleNamespace(status_code=self.status)


@pytest.fixture
def staging_env(monkeypatch):
    for k, v in dict(STAGING_REF=STAGING, PRODUCTION_REF=PROD, STAGING_SUPABASE_URL=f"https://{STAGING}.supabase.co",
                     STAGING_DB_URL=f"postgresql://postgres.{STAGING}:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres",
                     STAGING_SERVICE_KEY=jwt(ref=STAGING, role="service_role"), STAGING_ANON_KEY=jwt(ref=STAGING, role="anon"),
                     STAGING_API="https://sch-hub-api-staging.onrender.com", STAGING_WEB="https://sch-hub-web-staging.onrender.com").items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("STAGING_PSQL", raising=False)
    return monkeypatch


def guard(step: str = "all", domain: str = "sch-staging.example.com", http=None):  # type: ignore[no-untyped-def]
    st = boot.Staging(argparse.Namespace(step=step, email_domain=domain, local=False, info=Path("/nonexistent")), http=http or FakeHttp())
    st.guard()
    return st


def refused(match: str, **kw) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SystemExit, match=match):
        guard(**kw)


def test_staging_keys_and_addresses_pass(staging_env):
    st = guard()
    assert STAGING in st.db and st.service_key and st.anon_key


def test_production_key_is_refused(staging_env):
    staging_env.setenv("STAGING_SERVICE_KEY", jwt(ref=PROD, role="service_role"))
    refused("PRODUCTION key")


def test_key_of_another_project_or_wrong_role_is_refused(staging_env):
    staging_env.setenv("STAGING_SERVICE_KEY", jwt(ref="someotherprojectccc", role="service_role"))
    refused("another project")
    staging_env.setenv("STAGING_SERVICE_KEY", jwt(ref=STAGING, role="anon"))
    refused("role 'anon'")


def test_new_style_keys_must_be_accepted_by_the_staging_project(staging_env):
    staging_env.setenv("STAGING_SERVICE_KEY", "sb_secret_abc")
    staging_env.setenv("STAGING_ANON_KEY", "sb_publishable_abc")
    http = FakeHttp(401)
    refused("does not accept", http=http)
    assert all(u.startswith(f"https://{STAGING}.supabase.co/") for u in http.urls)       # only ever asks staging
    ok = FakeHttp(200)
    guard(http=ok)
    assert len(ok.urls) == 2


def test_secret_and_publishable_keys_cannot_be_swapped(staging_env):
    staging_env.setenv("STAGING_SERVICE_KEY", "sb_publishable_abc")
    refused("not a secret key")


def test_production_addresses_connection_and_refs_are_refused(staging_env):
    staging_env.setenv("STAGING_API", "https://sch-hub-api.onrender.com")
    refused("not production")
    staging_env.setenv("STAGING_API", "https://sch-hub-api-staging.onrender.com")
    staging_env.setenv("STAGING_DB_URL", f"postgresql://postgres.{PROD}:pw@db.{PROD}.supabase.co:5432/postgres")
    refused("does not belong to the staging project")
    staging_env.setenv("PRODUCTION_REF", STAGING)
    refused("two different projects")


def test_only_reserved_example_domains_for_made_up_accounts(staging_env):
    refused("reserved example domain", domain="gmail.com")
    refused("reserved example domain", domain="sch.ac.kr")
    for ok in ("sch-staging.example.com", "example.org", "hub.test", "x.invalid"):
        assert boot.reserved_domain(ok)


# --------------------------------------------------------------------------- hosted memory check
def test_check_targets_loopback_or_marked_staging_only():
    assert check.target(dict(api="http://127.0.0.1:8051")) == "http://127.0.0.1:8051"
    assert check.target(dict(api="https://sch-hub-api-staging.onrender.com", staging=True)).startswith("https://")
    for info in (dict(api="https://sch-hub-api.onrender.com", staging=True), dict(api="https://sch-hub-api-staging.onrender.com"),
                 dict(api=f"https://{PROD}.supabase.co", staging=True, production_ref=PROD), dict(api="https://other.example.com", staging=True)):
        with pytest.raises(SystemExit, match="REFUSED"):
            check.target(info)


def test_password_only_goes_to_loopback_or_the_staging_project():
    assert check.auth_ok(dict(auth="http://127.0.0.1:8052"))
    assert check.auth_ok(dict(auth=f"https://{STAGING}.supabase.co", staging=True, staging_ref=STAGING, production_ref=PROD))
    assert not check.auth_ok(dict(auth=f"https://{PROD}.supabase.co", staging=True, staging_ref=PROD, production_ref=PROD))
    assert not check.auth_ok(dict(auth="https://evil.example.com", staging=True, staging_ref=STAGING))


def test_without_the_runtime_endpoint_memory_checks_are_skipped():
    rows = [{k: v for k, v in sample(i, 300).items() if k in ("t", "label", "health_ok", "health_s", "search_ok", "search_s")} for i in range(4)]
    res = judge(rows)
    assert res["peak memory"] == res["no restart"] == "SKIP" and res["all jobs succeeded"] == "PASS"


ARGS = SimpleNamespace(max_submit_seconds=30, max_health_seconds=5, max_search_seconds=20, warn_mb=470, limit_mb=512, recovered_mb=420, idle=180)


def sample(t, mem, **kw):  # type: ignore[no-untyped-def]
    row = dict(t=t, label="working", health_ok=True, health_s=0.2, search_ok=True, search_s=1.0, instance="a", rss_mb=mem, peak_rss_mb=mem,
               container_mb=None, container_peak_mb=None, oom_kill=None, slots_active=1, slots_limit=1, jobs_running=1, stale=0, stuck=False,
               arena="2", worker_alive=True)
    row.update(kw)
    return row


def judge(samples, jobs=None):  # type: ignore[no-untyped-def]
    items = [dict(kind="pdf", name="a.pdf", accepted=True, seconds=0.3, http=202)]
    jobs = jobs if jobs is not None else {"j": dict(kind="pdf", name="a.pdf", status="succeeded")}
    return {c["check"]: c["status"] for c in check.evaluate(samples, items, jobs, samples[0], samples[1], samples[-1], ARGS)}


def test_healthy_run_passes():
    res = judge([sample(0, 300), sample(1, 300), sample(2, 450), sample(3, 320)])
    assert {k: v for k, v in res.items() if v != "PASS"} == {"no out-of-memory kill (container)": "SKIP"}


def test_restart_oom_concurrency_and_stuck_work_fail():
    res = judge([sample(0, 300, container_mb=300, oom_kill=0), sample(1, 300, container_mb=300, oom_kill=0),
                 sample(2, 500, instance="b", container_mb=500, oom_kill=1, jobs_running=2, stale=1), sample(3, 480, container_mb=480, oom_kill=1, stale=1)],
                jobs={"j": dict(kind="pdf", name="a.pdf", status="running", error="timeout")})
    for name in ("no restart", "no out-of-memory kill (container)", "ingestion concurrency within the limit", "nothing stuck", "all jobs succeeded"):
        assert res[name] == "FAIL", name
    assert res["peak memory"] == "WARN" and res["memory recovers after the work"] == "WARN"


def test_unresponsive_api_fails():
    res = judge([sample(0, 300), sample(1, 300), sample(2, 300, health_ok=False, health_s=None, search_ok=False), sample(3, 300)])
    assert res["API stays responsive (/health)"] == "FAIL" and res["search stays usable during processing"] == "FAIL"


# --------------------------------------------------------------------------- --supabase-local (the CLI stack on this computer)
DEMO_SERVICE = jwt(iss="supabase-demo", role="service_role")
DEMO_ANON = jwt(iss="supabase-demo", role="anon")


@pytest.fixture
def local_env(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("STAGING_"):
            monkeypatch.delenv(k)
    for k, v in dict(STAGING_DB_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres", STAGING_SERVICE_KEY=DEMO_SERVICE,
                     STAGING_ANON_KEY=DEMO_ANON, STAGING_API="http://127.0.0.1:8051", STAGING_WEB="http://127.0.0.1:3000",
                     PRODUCTION_REF=PROD).items():
        monkeypatch.setenv(k, v)
    return monkeypatch


def local_guard(http=None):  # type: ignore[no-untyped-def]
    st = boot.Staging(argparse.Namespace(step="all", email_domain="sch-staging.example.com", local=False, supabase_local=True,
                                         info=Path("/nonexistent")), http=http or FakeHttp())
    st.guard()
    return st


def test_local_stack_with_demo_keys_passes(local_env):
    st = local_guard()
    assert st.url == "http://127.0.0.1:54321" and "127.0.0.1:54322" in st.db


@pytest.mark.parametrize("name,value,match", [
    ("STAGING_DB_URL", f"postgresql://postgres.{PROD}:pw@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres", "hosted Supabase"),
    ("STAGING_DB_URL", "postgresql://postgres:pw@10.0.0.5:5432/postgres", "not the database on this computer"),
    ("STAGING_SUPABASE_URL", f"https://{PROD}.supabase.co", "hosted Supabase"),
    ("STAGING_API", "https://sch-hub-api.onrender.com", "production"),
    ("STAGING_WEB", "http://192.168.0.10:3000", "on this computer"),
    ("STAGING_SERVICE_KEY", jwt(ref=PROD, role="service_role"), "PRODUCTION"),
    ("STAGING_SERVICE_KEY", jwt(ref="otherhostedprojectxx", role="service_role"), "hosted project"),
    ("STAGING_SERVICE_KEY", DEMO_ANON, "role 'anon'"),
])
def test_local_stack_refuses_anything_hosted_or_remote(local_env, name, value, match):
    local_env.setenv(name, value)
    with pytest.raises(SystemExit, match=match):
        local_guard()


def test_local_stack_new_keys_are_checked_against_the_local_stack_only(local_env):
    local_env.setenv("STAGING_SERVICE_KEY", "sb_secret_local")
    local_env.setenv("STAGING_ANON_KEY", "sb_publishable_local")
    http = FakeHttp(200)
    local_guard(http)
    assert http.urls and all(u.startswith("http://127.0.0.1:54321/") for u in http.urls)


def test_local_api_runs_only_against_the_stack_on_this_computer():
    local_api = load("local_api")
    local_api.check({"SUPABASE_URL": "http://127.0.0.1:54321", "SUPABASE_SERVICE_ROLE_KEY": DEMO_SERVICE})
    for env, match in (({"SUPABASE_URL": f"https://{PROD}.supabase.co"}, "on this computer"),
                       ({"SUPABASE_URL": "http://127.0.0.1:54321", "CORS_ORIGINS": "https://sch-international-students-hub.onrender.com"}, "production"),
                       ({"SUPABASE_URL": "http://127.0.0.1:54321", "LLM_API_KEY": "x"}, "LLM_API_KEY")):
        with pytest.raises(SystemExit, match=match):
            local_api.check(env)


def test_synthetic_web_serves_only_invented_pages():
    import httpx

    web = load("synthetic_web")
    c = httpx.Client(transport=web.transport())
    board = c.get("https://sgee.sch.ac.kr/notice/notice01.php?table_name=noti_fore&loc_mnu=3")
    assert board.status_code == 200 and "(합성)" in board.text
    notice = c.get("https://sgee.sch.ac.kr/notice/notice01.php?admin_mode=read&no=9101&table_name=noti_fore")
    assert web.MARK in notice.text
    assert c.get("https://www.google.com/").status_code == 404 and c.get("https://sgee.sch.ac.kr/robots.txt").status_code == 404

"""End-to-end check of language-based support (scenarios A–L) on a LOCAL Supabase-compatible stack.

Real: the signup trigger (auth.users insert with user metadata), supabase-py -> PostgREST -> PostgreSQL with all
migrations and RLS, the routing/assignment SQL functions, and DIRECT PostgREST reads with each user's own JWT
(what a browser holding the public anon key could attempt). Not real: Supabase Auth itself (users are inserted
into the local auth.users shim) and Realtime delivery (notification rows are checked instead).

    E2E_REST_URL=http://127.0.0.1:54331 E2E_POSTGREST=http://127.0.0.1:54330 \\
    E2E_PSQL="psql -h /tmp/schpg -p 54329 -U postgres -d hub -q -t -A" E2E_JWT_SECRET=... \\
    backend/.venv/bin/python scripts/e2e_support.py
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx  # noqa: E402
import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.repositories.memory_store import MemoryFileStorage  # noqa: E402
from app.repositories.supabase_store import SupabaseStore  # noqa: E402

REST, PGRST, PSQL, SECRET = (os.environ["E2E_REST_URL"], os.environ["E2E_POSTGREST"], os.environ["E2E_PSQL"],
                             os.environ["E2E_JWT_SECRET"])
results: list[tuple[str, bool, dict]] = []


def check(name: str, ok: bool, **info) -> None:  # type: ignore[no-untyped-def]
    results.append((name, ok, info))
    print(f"- {'PASS' if ok else 'FAIL'} {name}: {json.dumps(info, ensure_ascii=False, default=str)[:300]}", flush=True)


def sql(q: str) -> str:
    out = subprocess.run(shlex.split(PSQL) + ["-v", "ON_ERROR_STOP=1", "-c", q], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    return out.stdout.strip()


def token(uid: str) -> str:
    return jwt.encode({"sub": uid, "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 3600},
                      SECRET, algorithm="HS256")


def rest(uid: str, path: str) -> list:  # type: ignore[type-arg]
    """Direct PostgREST read as that user (RLS decides)."""
    r = httpx.get(f"{PGRST}/{path}", headers={"Authorization": f"Bearer {token(uid)}"}, timeout=20)
    return r.json() if r.status_code == 200 else [{"http": r.status_code}]


def main() -> None:  # noqa: PLR0915
    key = jwt.encode({"role": "service_role", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    s = Settings(_env_file=None, supabase_url=REST, supabase_service_role_key=key, supabase_jwt_secret=SECRET,
                 embedding_provider="hash", job_execution="inline", rate_limit_search_per_minute=1000,
                 rate_limit_ingest_per_minute=1000, rate_limit_public_per_minute=1000)
    app = create_app(s, store=SupabaseStore(s), storage=MemoryFileStorage())
    tag = uuid.uuid4().hex[:6]
    U: dict[str, str] = {}

    def signup(name: str, meta: dict) -> str:  # type: ignore[type-arg]
        uid = str(uuid.uuid4())
        sql(f"insert into auth.users (id, email, raw_user_meta_data) values ('{uid}', '{name}-{tag}@example.test', "
            f"'{json.dumps(meta)}'::jsonb)")
        U[name] = uid
        return uid

    # A, B: signup with a chosen language through the real trigger (a role in metadata is ignored)
    signup("ayu", {"preferred_language": "id", "display_name": "Ayu"})
    signup("minh", {"preferred_language": "vi", "role": "super_admin"})
    for n in ("sup_id", "sup_id2", "sup_vi", "lead_id", "boss"):
        signup(n, {})
    prof = {r.split("|")[0]: r.split("|")[1:] for r in sql(
        f"select id || '|' || preferred_language || '|' || role from profiles where id in ('{U['ayu']}','{U['minh']}')").splitlines()}
    check("A.signup_indonesian", prof[U["ayu"]] == ["id", "student"], profile=prof[U["ayu"]])
    check("B.signup_vietnamese_role_ignored", prof[U["minh"]] == ["vi", "student"], profile=prof[U["minh"]])
    sql(f"update profiles set role='supporter', display_name=initcap(split_part(email,'-',1)) where id in "
        f"('{U['sup_id']}','{U['sup_id2']}','{U['sup_vi']}','{U['lead_id']}')")
    sql(f"update profiles set role='super_admin' where id = '{U['boss']}'")

    H = lambda n: {"Authorization": f"Bearer {token(U[n])}"}  # noqa: E731
    with TestClient(app) as c:
        def team(n: str, *a: tuple) -> None:  # type: ignore[type-arg]
            r = c.put(f"/api/v1/admin/users/{U[n]}/team", headers=H("boss"), json={"assignments": [
                dict(language=x[0], can_support=True, can_review_translations="review" in x, is_team_lead="lead" in x)
                for x in a]})
            assert r.status_code == 200, r.text

        team("sup_id", ("id",)), team("sup_id2", ("id",)), team("sup_vi", ("vi",)), team("lead_id", ("id", "lead"))
        c.put("/api/v1/support/me/availability", headers=H("lead_id"), json={"is_available": False})

        # C: conversation persists across sessions (new token = new sign-in)
        conv = c.post("/api/v1/conversations", headers=H("ayu"), json={}).json()
        ans = c.post(f"/api/v1/conversations/{conv['id']}/messages", headers=H("ayu"),
                     json={"content": "Bagaimana cara memperpanjang visa D-2 saya?"}).json()
        again = c.get("/api/v1/conversations", headers={"Authorization": f"Bearer {token(U['ayu'])}"}).json()
        check("C.history_after_relogin", again["total"] == 1 and again["items"][0]["message_count"] == 2,
              assistant_language=ans["assistant_message"]["language"],
              offer_handoff=ans["assistant_message"]["metadata"]["offer_handoff"])
        check("C.rest_rls_own_conversations_only", len(rest(U["ayu"], "ai_conversations")) == 1
              and rest(U["sup_id"], "ai_conversations") == [] and rest(U["boss"], "ai_messages") == [])

        # D: consented handoff of selected messages
        t = c.post("/api/v1/support/tickets", headers=H("ayu"), json=dict(
            subject="Perpanjangan visa D-2", summary="Butuh bantuan memperpanjang visa.", conversation_id=conv["id"],
            message_ids=[ans["user_message"]["id"]], consent=True)).json()
        tid = t["id"]
        assignee = c.get(f"/api/v1/support/tickets/{tid}", headers=H("lead_id")).json()["assigned_to"]
        name = {v: k for k, v in U.items()}[assignee]
        other = "sup_id2" if name == "sup_id" else "sup_id"
        check("D.handoff_routed_to_indonesian_team", t["language"] == "id" and t["status"] == "assigned"
              and len(t["shared_context"]) == 1 and name in ("sup_id", "sup_id2"), assignee=name)

        # E/F: isolation via API and via direct PostgREST
        api_codes = {n: c.get(f"/api/v1/support/tickets/{tid}", headers=H(n)).status_code
                     for n in (name, other, "sup_vi", "minh")}
        rest_rows = {n: len(rest(U[n], f"support_tickets?id=eq.{tid}")) for n in (name, other, "sup_vi", "minh", "ayu")}
        check("E.only_assignee_reads_content", api_codes[name] == 200 and api_codes[other] == 404
              and rest_rows[name] == 1 and rest_rows[other] == 0, api=api_codes, rest=rest_rows)
        check("F.vietnamese_supporter_guessing_id", api_codes["sup_vi"] == 404 and rest_rows["sup_vi"] == 0
              and rest(U["sup_vi"], f"support_ticket_messages?ticket_id=eq.{tid}") == [])

        # G: reply -> student notification (row visible to the student only)
        c.post(f"/api/v1/support/tickets/{tid}/accept", headers=H(name))
        c.post(f"/api/v1/support/tickets/{tid}/messages", headers=H(name), json={"body": "Siapkan paspor dan ARC."})
        mine = rest(U["ayu"], "user_notifications?kind=eq.supporter_reply")
        check("G.reply_notifies_student", len(mine) == 1 and rest(U["minh"], "user_notifications?kind=eq.supporter_reply") == []
              and "paspor" not in json.dumps(mine), notification=mine[0]["title"] if mine else None)

        # H: preference change routes new tickets to the new team only
        c.patch("/api/v1/me", headers=H("ayu"), json={"preferred_language": "vi"})
        t2 = c.post("/api/v1/support/tickets", headers=H("ayu"), json=dict(subject="Ký túc xá", summary="Hỏi về KTX.",
                                                                           consent=True)).json()
        old_lang = c.get(f"/api/v1/support/tickets/{tid}", headers=H("ayu")).json()["language"]
        check("H.new_team_for_new_ticket_only", t2["language"] == "vi" and old_lang == "id",
              new_ticket_status=t2["status"])

        # I: nobody available for Chinese
        signup("chen", {"preferred_language": "zh-CN"})
        t3 = c.post("/api/v1/support/tickets", headers=H("chen"), json=dict(subject="宿舍问题", summary="宿舍。",
                                                                            consent=True)).json()
        check("I.no_supporter_waits", t3["status"] == "waiting" and t3["assigned_supporter"] is None,
              message=t3["status_message"][:60])

        # J: reassignment revokes old access (API + RLS)
        r = c.post(f"/api/v1/support/tickets/{tid}/transfer", headers=H("lead_id"),
                   json={"to_supporter_id": U[other], "reason": "workload"})
        check("J.reassign_revokes", r.status_code == 200 and rest(U[name], f"support_tickets?id=eq.{tid}") == []
              and len(rest(U[other], f"support_tickets?id=eq.{tid}")) == 1
              and c.get(f"/api/v1/support/tickets/{tid}", headers=H(name)).status_code == 404)

        # K: resolve + feedback, still available after re-login
        c.post(f"/api/v1/support/tickets/{tid}/accept", headers=H(other))
        c.post(f"/api/v1/support/tickets/{tid}/resolve", headers=H(other))
        fb = c.post(f"/api/v1/support/tickets/{tid}/feedback", headers=H("ayu"), json={"rating": 5}).json()
        check("K.resolved_kept", fb["status"] == "resolved" and fb["satisfaction"] == 5
              and c.get("/api/v1/support/tickets", headers={"Authorization": f"Bearer {token(U['ayu'])}"}).json()["total"] == 2)

        # L: super admin manages teams; a language-scoped admin cannot widen access
        lead = c.get("/api/v1/admin/language-teams", headers=H("lead_id")).json()
        check("L.scoped_admin", [x["language"] for x in lead["items"]] == ["id"]
              and c.put(f"/api/v1/admin/users/{U['lead_id']}/team", headers=H("lead_id"),
                        json={"assignments": [{"language": "vi", "is_team_lead": True}]}).status_code == 403
              and rest(U["lead_id"], "supporter_languages?language_code=eq.vi") == []
              and httpx.post(f"{PGRST}/supporter_languages", headers={"Authorization": f"Bearer {token(U['lead_id'])}"},
                             json={"supporter_id": U["lead_id"], "language_code": "vi"}).status_code in (401, 403))

        # translation review: Indonesian supporter cannot approve Vietnamese
        team("sup_id", ("id", "review"))
        team("sup_vi", ("vi",))
        from tests.test_announcements import create  # reuse the helper's payload shape

        class E:  # minimal adapter for the helper
            client = c

            @staticmethod
            def auth(_role):  # noqa: ANN001
                return H("boss")

        a = create(E, submit=True)
        c.post(f"/api/v1/admin/announcements/{a['id']}/approve", headers=H("boss"), json={})
        c.put(f"/api/v1/admin/announcements/{a['id']}/translations/vi", headers=H("sup_vi"),
              json={"title": "Thông báo", "body": "Nội dung.", "translation_status": "in_review"})
        denied = c.post(f"/api/v1/admin/announcements/{a['id']}/translations/vi/approve", headers=H("sup_id"),
                        json={"original_verified": True}).status_code
        team("sup_id", ("id", "review"), ("vi", "review"))
        allowed = c.post(f"/api/v1/admin/announcements/{a['id']}/translations/vi/approve", headers=H("sup_id"),
                         json={"original_verified": True}).status_code
        anon_rows = httpx.get(f"{PGRST}/announcement_translations?announcement_id=eq.{a['id']}").json()
        check("T.indonesian_cannot_approve_vietnamese", denied == 403 and allowed == 200
              and [x["language_code"] for x in anon_rows] == ["vi"], denied=denied, allowed_after_assignment=allowed)

        # document lifecycle: archive -> restore -> withdraw -> guarded delete (real DB triggers + RPCs)
        src = c.post("/api/v1/admin/sources", headers=H("boss"), json=dict(
            title=f"Lifecycle {tag}", organization="SCH", source_type="manual_text", authority_type="official_university",
            scope="university", category="academic-life")).json()
        j = c.post(f"/api/v1/admin/sources/{src['id']}/submit-text", headers=H("boss"), json=dict(
            title=f"Lifecycle doc {tag}", text="Course registration closes on the published date for all students.")).json()
        c.post(f"/api/v1/admin/versions/{j['version_id']}/approve", headers=H("boss"), json={})
        doc = j["document_id"]

        def found() -> bool:
            res = c.post("/api/v1/knowledge/search", json={"query": "course registration closes", "top_k": 20}).json()
            return any(r["document_id"] == doc for r in res["results"])

        a1 = found()
        c.post(f"/api/v1/admin/documents/{doc}/archive", headers=H("boss"), json={"reason": "E2E archive"})
        a2 = found()
        c.post(f"/api/v1/admin/documents/{doc}/restore", headers=H("boss"), json={})
        a3 = found()
        check("X.archive_restore_rag", a1 and not a2 and a3)
        blocked = c.post(f"/api/v1/admin/documents/{doc}/delete", headers=H("boss"),
                         json={"reason": "E2E delete", "confirm_title": f"Lifecycle doc {tag}"}).status_code
        c.post(f"/api/v1/admin/documents/{doc}/cancel", headers=H("boss"), json={"reason": "E2E withdraw"})
        not_super = c.post(f"/api/v1/admin/documents/{doc}/delete", headers=H("lead_id"),
                           json={"reason": "E2E delete", "confirm_title": f"Lifecycle doc {tag}"}).status_code
        direct = httpx.delete(f"{PGRST}/source_documents?id=eq.{doc}", headers={"Authorization": f"Bearer {token(U['boss'])}"})
        still = sql(f"select count(*) from source_documents where id = '{doc}'")
        ok = c.post(f"/api/v1/admin/documents/{doc}/delete", headers=H("boss"),
                    json={"reason": "E2E delete", "confirm_title": f"Lifecycle doc {tag}"})
        tomb = sql(f"select count(*) from audit_log where action = 'document.delete' and entity_id = '{doc}'")
        gone = sql(f"select count(*) from source_documents where id = '{doc}'")
        check("X.guarded_delete", blocked == 409 and not_super == 403 and still == "1" and ok.status_code == 200
              and tomb == "1" and gone == "0", published_delete=blocked, non_super=not_super,
              direct_rest_delete=direct.status_code, result=ok.json())

    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")


if __name__ == "__main__":
    main()

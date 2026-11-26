"""Release A smoke test on a SEPARATE staging project (hosted Supabase), SYNTHETIC data only. Plan: docs/release/release-a-staging.md

It WRITES (sources, documents, approvals) and cleans nothing up except archiving. Guards, all before the first write:
the API must run on this computer; the Supabase project must be the one named with --ref and not the one named with
--production-ref; the project may hold no public document that this script did not make.

    STAGING_API=http://127.0.0.1:8000 STAGING_SUPABASE_URL=https://REF.supabase.co STAGING_ANON_KEY=... \\
    STAGING_ADMIN_EMAIL=... backend/.venv/bin/python scripts/staging_smoke.py --ref REF --production-ref PRODREF [--board URL]

The password of the staging administrator is asked for (or STAGING_TOKEN is used). SQL that changes the staging database is
printed for the SQL editor of the STAGING project, or run with STAGING_PSQL when that is set.
"""
from __future__ import annotations

import argparse
import getpass
import os
import shlex
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--ref", required=True)
ap.add_argument("--production-ref", required=True)
ap.add_argument("--board", help="official notice board; a few public notices are imported into STAGING")
args = ap.parse_args()
API, SUPA, ANON = (os.environ[k].rstrip("/") for k in ("STAGING_API", "STAGING_SUPABASE_URL", "STAGING_ANON_KEY"))
LOCAL = {"127.0.0.1", "localhost"}


def stop(why: str) -> None:
    sys.exit(f"REFUSED, nothing was written: {why}")


if urlsplit(API).hostname not in LOCAL:
    stop("STAGING_API must run on this computer (127.0.0.1)")
host = urlsplit(SUPA).hostname or ""
if args.ref == args.production_ref or host.startswith(args.production_ref):
    stop("this is the production project")
if host != f"{args.ref}.supabase.co" and not (args.ref == "local" and host in LOCAL):
    stop("STAGING_SUPABASE_URL is not the project named with --ref")
http = httpx.Client(timeout=120, trust_env=False)
failed = passed = 0


def check(name: str, ok: bool, detail: object = "") -> None:
    global failed, passed
    passed, failed = passed + bool(ok), failed + (not ok)
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"   {detail}"), flush=True)


token = os.environ.get("STAGING_TOKEN")
if not token:
    r = http.post(f"{SUPA}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON},
                  json=dict(email=os.environ["STAGING_ADMIN_EMAIL"], password=getpass.getpass("Staging password: ")))
    if r.status_code != 200:
        stop(f"staging login failed ({r.status_code})")
    token = r.json()["access_token"]


def call(method: str, path: str, body: object = None, ok: tuple[int, ...] = (200, 201, 202)) -> dict:  # type: ignore[type-arg]
    r = http.request(method, f"{API}/api/v1{path}", json=body, headers={"authorization": f"Bearer {token}"})
    if r.status_code not in ok:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
    return r.json() if r.content else {}


def anon_row(doc: str) -> dict:  # type: ignore[type-arg]
    """The row as a browser with the public key reads it."""
    r = http.get(f"{SUPA}/rest/v1/source_documents", params={"id": f"eq.{doc}", "select": "title,metadata"}, headers={"apikey": ANON})
    return (r.json() or [{}])[0] if r.status_code == 200 else {"http": r.status_code}


def wait(what, seconds: int = 90):  # type: ignore[no-untyped-def]
    for _ in range(seconds * 2):
        if what():
            return True
        time.sleep(0.5)
    return False


def detail(doc: str) -> dict:  # type: ignore[type-arg]
    return call("GET", f"/admin/documents/{doc}")


def approve(doc: str, vid: str) -> bool:
    call("POST", f"/admin/versions/{vid}/approve", {})
    return wait(lambda: (detail(doc).get("current_version") or {}).get("id") == vid)


def staging_sql(statement: str) -> None:
    psql = os.environ.get("STAGING_PSQL")
    if psql:
        subprocess.run(shlex.split(psql) + ["-v", "ON_ERROR_STOP=1", "-c", statement], check=True, capture_output=True)
    else:
        input(f"\nRun in the SQL editor of the STAGING project {args.ref}, then press Enter:\n\n{statement};\n\n")


others = [d["title"] for d in call("GET", "/knowledge/documents?page_size=50")["items"] if "STAGING" not in d["title"]]
if others:
    stop(f"{len(others)} public documents were not made by this script; is this really the staging project?")
if call("GET", "/me")["role"] not in ("admin", "super_admin"):
    stop("the staging user is not an administrator")
tag = uuid.uuid4().hex[:8]

# 1. title, text and search
src = call("POST", "/admin/sources", dict(title=f"STAGING {tag}", organization="Staging test", source_type="manual_text",
           authority_type="official_university", scope="university", category="academic-life", language="en"))
send = lambda title, text: call("POST", f"/admin/sources/{src['id']}/submit-text",  # noqa: E731
                                dict(title=title, text=text, external_id=f"staging-{tag}"))
T1, T2 = f"STAGING library hours {tag}", f"STAGING unapproved title {tag}"
one = send(T1, f"The staging library opens at nine in the morning. {tag}")
doc = one["document_id"]
check("1 first version approved", approve(doc, one["version_id"]))
two = send(T2, f"The staging library opens at ten from now on. SECRET-EDIT {tag}")
check("2 the second submission is a waiting version of the same document", two["document_id"] == doc)


def state() -> tuple[bool, bool, bool]:
    """(title, row of the public key, SECRET-EDIT visible)"""
    p = call("GET", f"/knowledge/documents/{doc}")
    found = http.post(f"{API}/api/v1/knowledge/search", json=dict(query=f"staging library opens {tag}", top_k=5)).text
    return p["title"], anon_row(doc).get("title"), "SECRET-EDIT" in str(p) + found or T2 in found  # type: ignore[return-value]


check("3 waiting title and text are not public (page, search, public key)", state() == (T1, T1, False), state())
check("4 the reviewer sees the proposed title", detail(doc).get("proposed_title") == T2)
call("POST", f"/admin/versions/{two['version_id']}/reject", dict(reason="staging test"))
send(T2, f"The staging library opens at ten from now on. SECRET-EDIT {tag}")
check("5 rejected, and the same submission again: still not public", state() == (T1, T1, False), state())
three = send(T2, f"The staging library opens at eleven. {tag}")
check("6 approval changes title and public row together", approve(doc, three["version_id"]) and wait(lambda: state() == (T2, T2, True), 30), state())
call("POST", f"/admin/documents/{doc}/rollback", dict(version_id=one["version_id"]))
check("7 rollback restores the old title", state() == (T1, T1, False), state())

# 2. announcement: translators see the approved text (no model is called)
ann = call("POST", "/admin/announcements", dict(title=f"STAGING {tag}", body=f"승인된 공지입니다. 2026-12-01 {tag}", category="scholarships",
           source_type="manual_text", submit=True, evidence_note="staging test"))
call("POST", f"/admin/announcements/{ann['id']}/approve", {})
check("8 the announcement is public", tag in str(call("GET", f"/announcements/{ann['id']}")))

# 3. attachments
docs = [doc]
if args.board:
    b = call("POST", "/admin/sources", dict(title=f"STAGING board {tag}", original_url=args.board, organization="Staging test",
             source_type="sch_board", authority_type="official_university", scope="university",
             category="university-announcements", language="ko", config=dict(max_items=5, max_pages=1)))

    def ingest() -> dict:  # type: ignore[type-arg]
        job = call("POST", f"/admin/sources/{b['id']}/ingest")["job_id"]
        get = lambda: call("GET", f"/admin/ingestion-jobs/{job}")  # noqa: E731
        wait(lambda: get()["status"] not in ("queued", "running"), 300)
        return get()

    job = ingest()
    rows = call("GET", f"/admin/documents?source_id={b['id']}&page_size=20")["items"]
    pick = next((r["id"] for r in rows if ((detail(r["id"]).get("pending_version") or {}).get("extraction_meta") or {}).get("attachments")), None)
    if pick is None:
        check("9 an imported notice has attachments", False, f"{job['status']}, {len(rows)} notices; try another board")
    else:
        v1 = detail(pick)["pending_version"]
        call("PATCH", f"/admin/versions/{v1['id']}", dict(extracted_text=v1["extracted_text"] + "\n\nSTAGING"))
        staging_sql("update public.document_versions set extraction_meta = jsonb_set(extraction_meta, '{attachments}', "
                    "'[{\"name\": \"STAGING-approved.pdf\", \"url\": \"https://sgee.sch.ac.kr/staging.pdf\"}]') "
                    f"where id = '{v1['id']}' and verification_status = 'pending_review'")
        docs.append(pick)
        page = lambda: [x["name"] for x in call("GET", f"/knowledge/documents/{pick}")["attachments"]]  # noqa: E731
        row = lambda: [x["name"] for x in (anon_row(pick).get("metadata") or {}).get("attachments") or []]  # noqa: E731
        want = ["STAGING-approved.pdf"]
        ok = approve(pick, v1["id"]) and wait(lambda: row() == want, 30)
        check("9 the approved list is public (page, public key)", ok and page() == want, (page(), row()))
        ingest()
        d = detail(pick)
        check("10 the next import waits with its own list", bool(d.get("pending_version")))
        check("11 the waiting list is not public (page, public key)", page() == row() == want, (page(), row()))
        codes = {w["code"] for w in d.get("review_warnings") or []}
        check("12 the reviewer is warned", {"attachments_added", "attachments_removed"} <= codes, codes)
        call("POST", f"/admin/versions/{d['pending_version']['id']}/reject", dict(reason="staging test"))
        ingest()
        check("13 rejected and imported again: unchanged", page() == row() == want, (page(), row()))
        staging_sql("update public.source_documents set metadata = jsonb_set(metadata, '{attachments}', "
                    "'[{\"name\": \"STAGING-wrong.pdf\", \"url\": \"https://sgee.sch.ac.kr/wrong.pdf\"}]') " + f"where id = '{pick}'")
        check("14 a wrong stored row (damage from before): the page shows the approved list", page() == want, page())
        print(f"      known limitation, must be a row of attachments_to_review.sql: {pick}; stored row: {row()}")
for d_id in docs:
    call("POST", f"/admin/documents/{d_id}/archive", dict(reason="staging test finished"))
print(f"{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)

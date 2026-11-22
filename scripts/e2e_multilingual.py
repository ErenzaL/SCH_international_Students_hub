"""End-to-end check of the multilingual Knowledge Center on a LOCAL Supabase-compatible stack.

Real: PostgreSQL with all migrations + RLS + triggers, PostgREST (direct reads with each user's own JWT), the signup
trigger, supabase-py SupabaseStore, the durable job tables, and real multilingual-E5 (int8 ONNX) embeddings.
Simulated: the website (MockTransport) and the LLM provider (ScriptedLLMProvider - no API key in this environment;
the Anthropic provider itself is exercised only by unit tests). Supabase Auth is the local auth.users shim.

    E2E_REST_URL=http://127.0.0.1:54331 E2E_POSTGREST=http://127.0.0.1:54330 \\
    E2E_PSQL="psql -h /tmp/schpg -p 54329 -U postgres -d hub -q -t -A" E2E_JWT_SECRET=... \\
    backend/.venv/bin/python scripts/e2e_multilingual.py [--json out.json]
"""
from __future__ import annotations

import json
import os
import re
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
from app.services.ingestion.fetcher import GuardedFetcher  # noqa: E402
from app.services.llm.base import ScriptedLLMProvider  # noqa: E402

REST, PGRST, PSQL, SECRET = (os.environ["E2E_REST_URL"], os.environ["E2E_POSTGREST"], os.environ["E2E_PSQL"],
                             os.environ["E2E_JWT_SECRET"])
results: list[tuple[str, bool, dict]] = []   # type: ignore[type-arg]

PAGE = """<html lang="ko"><head><title>Student Visa and Stay - Study in Korea</title></head><body><div id="content">
<h1>Student Visa and Stay</h1>
<p>International students must keep their D-2 status valid while studying in Korea. Apply for an extension of the
period of stay before it expires through HiKorea (https://www.hikorea.go.kr) or at the immigration office.</p>
<h2>Alien registration</h2>
<p>Students staying longer than 90 days must complete alien registration within 90 days of entry. The fee is
30,000 KRW. Bring your passport, a photo and the certificate of enrollment.</p>
<h2>Part-time work</h2>
<p>Part-time work requires permission from the immigration office before you start working.</p>
</div></body></html>"""
PAGE_V2 = PAGE.replace("The fee is\n30,000 KRW", "The fee is\n35,000 KRW")

QUESTIONS = {
    "ko": "학생 비자 체류 기간 연장과 외국인 등록은 어떻게 하나요?",
    "en": "How do I extend my student visa and do alien registration?",
    "id": "Bagaimana cara memperpanjang visa pelajar dan registrasi orang asing?",
    "vi": "Làm thế nào để gia hạn visa du học và đăng ký người nước ngoài?",
    "zh-CN": "如何延长学生签证并办理外国人登记？",
}
ANSWERS = {
    "ko": "체류 기간이 만료되기 전에 HiKorea 또는 출입국관리사무소에서 연장을 신청해야 합니다 [1].",
    "en": "Apply for an extension before your period of stay expires, through HiKorea or the immigration office [1].",
    "id": "Ajukan perpanjangan sebelum masa tinggal berakhir melalui HiKorea atau kantor imigrasi [1].",
    "vi": "Hãy xin gia hạn trước khi thời gian lưu trú hết hạn qua HiKorea hoặc văn phòng xuất nhập cảnh [1].",
    "zh-CN": "请在居留期限到期前通过 HiKorea 或出入境管理事务所申请延期 [1]。",
}
LANG_OF = {"Korean": "ko", "English": "en", "Indonesian": "id", "Vietnamese": "vi", "Simplified Chinese": "zh-CN"}


def check(name: str, ok: bool, **info) -> None:  # type: ignore[no-untyped-def]
    results.append((name, ok, info))
    print(f"- {'PASS' if ok else 'FAIL'} {name}: {json.dumps(info, ensure_ascii=False, default=str)[:300]}", flush=True)


def sql(q: str, allow_error: bool = False) -> str:
    out = subprocess.run(shlex.split(PSQL) + ["-v", "ON_ERROR_STOP=1", "-c", q], capture_output=True, text=True)
    if out.returncode != 0:
        if allow_error:
            return "ERROR: " + out.stderr.strip()
        raise RuntimeError(out.stderr)
    return out.stdout.strip()


def token(uid: str) -> str:
    return jwt.encode({"sub": uid, "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 3600},
                      SECRET, algorithm="HS256")


def rest(uid: str | None, path: str) -> list:  # type: ignore[type-arg]
    """Direct PostgREST read as that user (or anonymously) - RLS decides."""
    headers = {"Authorization": f"Bearer {token(uid)}"} if uid else {}
    r = httpx.get(f"{PGRST}/{path}", headers=headers, timeout=20)
    return r.json() if r.status_code == 200 else [{"http": r.status_code, "body": r.text[:200]}]


def responder(system: str, prompt: str) -> str:
    """Scripted LLM: answers cite passage [1]; translations keep codes/numbers/URLs and tag the language."""
    target = next((code for name, code in LANG_OF.items() if f"into {name}" in system or f"in {name}" in system), "en")
    if system.startswith("You turn a student's latest message"):      # follow-up rewrite: keep the question
        q = re.search(r"<latest_message>\n(.*?)\n</latest_message>", prompt, re.S).group(1)  # type: ignore[union-attr]
        return json.dumps({"standalone": q, "en": q, "ko": q})
    if system.startswith("You are the SCH International Student Hub assistant"):
        lang = next((code for name, code in LANG_OF.items() if f"Write in {name}" in system), "en")
        return ANSWERS[lang] + "\n<<<META>>>\n" + json.dumps({"evidence": "sufficient", "individual": False,
                                                              "wants_human": False, "follow_ups": []})
    text = re.search(r"<source_text>\n?(.*?)\n?</source_text>", prompt, re.S).group(1)  # type: ignore[union-attr]
    return "\n".join(f"{line} [{target}]" if line.strip() and not line.startswith("|") else line
                     for line in text.splitlines())


def main() -> None:  # noqa: PLR0915
    out_json = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else None
    key = jwt.encode({"role": "service_role", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    s = Settings(_env_file=None, supabase_url=REST, supabase_service_role_key=key, supabase_jwt_secret=SECRET,
                 embedding_provider=os.environ.get("E2E_EMBEDDINGS", "e5_onnx"), job_execution="inline",
                 rate_limit_search_per_minute=1000, rate_limit_ingest_per_minute=1000, rate_limit_public_per_minute=1000,
                 retrieval_min_similarity=0.70)
    tag = uuid.uuid4().hex[:6]
    url = f"https://www.studyinkorea.go.kr/en_US/plan/visaAndStay.do?e2e={tag}"
    pages = {url: PAGE}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        body = pages.get(str(req.url))
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"}) if body \
            else httpx.Response(404)

    fetcher = GuardedFetcher(s, transport=httpx.MockTransport(handler), resolver=lambda h: ["93.184.216.34"])
    llm = ScriptedLLMProvider(responder, model="scripted-e2e")
    app = create_app(s, store=SupabaseStore(s), storage=MemoryFileStorage(), fetcher=fetcher, llm=llm)
    U: dict[str, str] = {}

    def signup(name: str, meta: dict) -> str:  # type: ignore[type-arg]
        uid = str(uuid.uuid4())
        sql(f"insert into auth.users (id, email, raw_user_meta_data) values ('{uid}', '{name}-{tag}@example.test', "
            f"'{json.dumps(meta)}'::jsonb)")
        U[name] = uid
        return uid

    signup("ayu", {"preferred_language": "id", "display_name": "Ayu"})
    for n in ("sup_id", "sup_vi", "boss"):
        signup(n, {})
    sql(f"update profiles set role='supporter', display_name=initcap(split_part(email,'-',1)) "
        f"where id in ('{U['sup_id']}','{U['sup_vi']}')")
    sql(f"update profiles set role='super_admin' where id = '{U['boss']}'")
    H = lambda n: {"Authorization": f"Bearer {token(U[n])}"}  # noqa: E731

    with TestClient(app) as c:
        # 7. preference stored at signup and kept across sessions (fresh token = new sign-in)
        me = c.get("/api/v1/me", headers=H("ayu")).json()
        check("07.preference_from_signup", me["preferred_language"] == "id" and me["preferred_language_confirmed"],
              me={k: me[k] for k in ("preferred_language", "preferred_language_confirmed")})
        c.patch("/api/v1/me", headers=H("ayu"), json={"preferred_language": "vi"})
        again = c.get("/api/v1/me", headers={"Authorization": f"Bearer {token(U['ayu'])}"}).json()
        check("07.preference_persists_across_sessions", again["preferred_language"] == "vi", now=again["preferred_language"])
        c.patch("/api/v1/me", headers=H("ayu"), json={"preferred_language": "id"})

        # leftovers of earlier runs (same text) are archived first, so the index has exactly one copy
        old_runs = c.get("/api/v1/admin/sources", headers=H("boss"), params={"q": "Study in Korea E2E", "page_size": 100}
                         ).json()["items"]
        for o in old_runs:
            if not o.get("archived_at"):
                c.post(f"/api/v1/admin/sources/{o['id']}/archive", headers=H("boss"), json={"reason": "previous e2e run"})

        for n, lang, review in (("sup_id", "id", True), ("sup_vi", "vi", False)):
            r = c.put(f"/api/v1/admin/users/{U[n]}/team", headers=H("boss"), json={"assignments": [
                dict(language=lang, can_support=True, can_review_translations=review, is_team_lead=False)]})
            assert r.status_code == 200, r.text

        # original document: English page of a Korean site (HTML lang="ko") -> detected as English
        src = c.post("/api/v1/admin/sources", headers=H("boss"), json=dict(
            title=f"Study in Korea E2E {tag}", original_url=url, organization="NIIED", source_type="website",
            authority_type="official_government", scope="national", category="visa-immigration", language="ko")).json()
        jid = c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=H("boss")).json()["job_id"]
        job = c.get(f"/api/v1/admin/ingestion-jobs/{jid}", headers=H("boss")).json()
        doc = job["document_id"]
        lang_label = sql(f"select language from source_documents where id = '{doc}'")
        check("00.original_language_detected", lang_label == "en", stored=lang_label, html_lang="ko")
        r = c.post(f"/api/v1/admin/versions/{job['version_id']}/approve", headers=H("boss"), json={})
        rows = sql(f"select string_agg(language_code || ':' || translation_status, ',' order by language_code) "
                   f"from document_translations where document_id = '{doc}'")
        check("06a.tasks_created_on_activation", r.status_code == 202 and rows == "id:todo,ko:todo,vi:todo,zh-CN:todo",
              rows=rows)
        notes = sql(f"select count(*) from user_notifications where user_id = '{U['sup_id']}' and kind = 'translation_task'")
        check("06b.language_team_notified", int(notes) >= 1, notifications=notes)

        # 1 / 3: original in English; Vietnamese falls back to the original
        en = c.get(f"/api/v1/knowledge/documents/{doc}", params={"lang": "en"}).json()
        vi = c.get(f"/api/v1/knowledge/documents/{doc}", params={"lang": "vi"}).json()
        check("01.english_original_in_english", en["language"] == "en" and en["translation"] is None
              and "Student Visa and Stay" in en["content"])
        check("03.vietnamese_falls_back_to_original", vi["translation"] is None and vi["content"] == en["content"])

        # AI draft through the durable job tables (scripted provider)
        r = c.post(f"/api/v1/admin/documents/{doc}/translations/drafts", headers=H("boss"), json={"languages": ["id", "vi"]})
        tj = c.get(f"/api/v1/admin/ingestion-jobs/{r.json()['items'][0]['job_id']}", headers=H("boss")).json()
        draft = sql(f"select translation_status || '|' || provider || '|' || model || '|' || jsonb_array_length(warnings) "
                    f"from document_translations where document_id = '{doc}' and language_code = 'id' and not is_outdated")
        check("AI.draft_job_durable", r.status_code == 202 and tj["status"] == "succeeded" and tj["job_type"] == "translate_document",
              job=tj["status"], row=draft)
        check("04.machine_draft_not_verified", draft.startswith("machine_draft|scripted|")
              and c.get(f"/api/v1/knowledge/documents/{doc}", params={"lang": "id"}).json()["translation"] is None)

        # 10. RLS: drafts are invisible to anonymous visitors and students, staff only see their language
        anon = rest(None, f"document_translations?document_id=eq.{doc}&select=language_code,translation_status")
        student = rest(U["ayu"], f"document_translations?document_id=eq.{doc}&select=language_code")
        vi_staff = rest(U["sup_vi"], f"document_translations?document_id=eq.{doc}&select=language_code,translation_status")
        check("10.rls_no_drafts_for_anon_or_students", anon == [] and student == [], anon=anon, student=student)
        check("10.rls_staff_only_own_language", sorted(x["language_code"] for x in vi_staff) == ["vi"], vi_staff=vi_staff)
        api_try = c.get(f"/api/v1/admin/documents/{doc}/translations/id", headers=H("ayu"))
        check("10.api_drafts_forbidden_for_students", api_try.status_code == 403, status=api_try.status_code)

        # 5. Indonesian supporter edits + approves; Vietnamese supporter (no review right) cannot approve
        body = ("# Visa Pelajar dan Izin Tinggal\n\nMahasiswa internasional harus menjaga status D-2 tetap berlaku. Ajukan "
                "perpanjangan masa tinggal sebelum berakhir melalui HiKorea (https://www.hikorea.go.kr) atau kantor "
                "imigrasi.\n\n## Registrasi orang asing\n\nMahasiswa yang tinggal lebih dari 90 hari harus melakukan "
                "registrasi orang asing dalam 90 hari setelah masuk. Biayanya 30,000 KRW.\n\n## Kerja paruh waktu\n\n"
                "Kerja paruh waktu memerlukan izin dari kantor imigrasi.")
        sv = c.put(f"/api/v1/admin/documents/{doc}/translations/id", headers=H("sup_id"),
                   json={"title": "Visa Pelajar dan Izin Tinggal", "body": body, "submit": True})
        ap = c.post(f"/api/v1/admin/documents/{doc}/translations/id/approve", headers=H("sup_id"),
                    json={"original_verified": True, "note": "checked against the English original"})
        bad = c.post(f"/api/v1/admin/documents/{doc}/translations/vi/approve", headers=H("sup_vi"),
                     json={"original_verified": True})
        check("05.id_supporter_approves_id", sv.status_code == 200 and ap.status_code == 200,
              warnings=sv.json()["translation"]["warnings"] if sv.status_code == 200 else sv.text[:200])
        check("05.vi_supporter_cannot_approve", bad.status_code == 403, status=bad.status_code)
        trig = sql(f"update document_translations set translation_status='human_approved', original_verified=true, "
                   f"reviewed_by='{U['sup_vi']}', reviewed_at=now() where document_id='{doc}' and language_code='vi' "
                   f"and not is_outdated", allow_error=True)
        check("05.database_trigger_blocks_unassigned_reviewer", "not assigned to review" in trig, db=trig[:160])

        # 2 / 9: verified Indonesian displayed; citation is the original source
        idd = c.get(f"/api/v1/knowledge/documents/{doc}", params={"lang": "id"}).json()
        tr = idd["translation"] or {}
        check("02.approved_indonesian_displayed", tr.get("status") == "verified"
              and tr.get("title") == "Visa Pelajar dan Izin Tinggal" and idd["source_url"] == url,
              headings=tr.get("headings"))
        anon_after = rest(None, f"document_translations?document_id=eq.{doc}&select=language_code,translation_status")
        check("10.rls_anon_sees_only_approved", anon_after == [{"language_code": "id", "translation_status": "human_approved"}],
              anon=anon_after)
        listing = c.get("/api/v1/knowledge/documents", params={"lang": "id", "q": "Student Visa and Stay",
                                                                "page_size": 100}).json()["items"]
        mine = [i for i in listing if i["id"] == doc]
        check("02.list_shows_verified_title", bool(mine) and mine[0]["translated_title"] == "Visa Pelajar dan Izin Tinggal",
              found=bool(mine), translated_title=mine[0]["translated_title"] if mine else None)

        # 8 / 9: RAG retrieves the ORIGINAL across all five languages; assistant answers in the language, cites it
        rag: dict[str, object] = {}
        for lang, q in QUESTIONS.items():
            res = c.post("/api/v1/knowledge/search", json={"query": q, "language": lang, "top_k": 5}).json()
            ids = [x["document_id"] for x in res["results"]]
            rank = ids.index(doc) + 1 if doc in ids else None
            conv = c.post("/api/v1/conversations", headers=H("ayu"), json={"language": lang}).json()
            msg = c.post(f"/api/v1/conversations/{conv['id']}/messages", headers=H("ayu"),
                         json={"content": q, "language": lang}).json()["assistant_message"]
            cited = [x for x in msg["citations"] if x.get("cited")]
            rag[lang] = dict(rank=rank, mode=res["retrieval"]["mode"], generation=msg["metadata"]["answer_generation"],
                             answer_lang=msg["language"], cited_doc=cited[0]["document_id"] == doc if cited else False,
                             cited_url=cited[0]["source_url"] if cited else None)
            check(f"08.rag_{lang}_retrieves_original", rank is not None and rank <= 3, rank=rank, mode=res["retrieval"]["mode"])
            check(f"09.assistant_{lang}_answers_in_language_and_cites_original",
                  msg["language"] == lang and msg["content"].startswith(ANSWERS[lang]) and bool(cited)
                  and not msg["metadata"]["offer_handoff"]
                  and cited[0]["source_url"] == url, generation=msg["metadata"]["answer_generation"],
                  language=msg["language"], content=msg["content"][:80], cited=len(cited))

        # 6. the original changes -> previous translation outdated (kept), new tasks, team notified, not served
        pages[url] = PAGE_V2
        jid = c.post(f"/api/v1/admin/sources/{src['id']}/ingest", headers=H("boss")).json()["job_id"]
        j2 = c.get(f"/api/v1/admin/ingestion-jobs/{jid}", headers=H("boss")).json()
        c.post(f"/api/v1/admin/versions/{j2['version_id']}/approve", headers=H("boss"), json={})
        old = sql(f"select is_outdated || '|' || translation_status from document_translations where document_id = '{doc}' "
                  f"and language_code = 'id' and source_version_number = 1")
        new = sql(f"select translation_status || '|' || (previous_translation_id is not null) from document_translations "
                  f"where document_id = '{doc}' and language_code = 'id' and source_version_number = 2")
        outdated_note = sql(f"select count(*) from user_notifications where user_id = '{U['sup_id']}' "
                            f"and kind = 'translation_outdated'")
        served = c.get(f"/api/v1/knowledge/documents/{doc}", params={"lang": "id"}).json()
        check("06c.previous_translation_preserved_and_outdated", old == "true|human_approved", old=old)
        check("06d.new_review_task_linked_to_previous", new == "todo|true", new=new)
        check("06e.team_notified_of_change", int(outdated_note) >= 1, notifications=outdated_note)
        check("06f.old_translation_not_served", served["translation"] is None and "35,000 KRW" in served["content"])

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    if out_json:
        Path(out_json).write_text(json.dumps(dict(passed=passed, total=len(results), rag=rag,
                                                  checks=[dict(name=n, ok=o, info=i) for n, o, i in results]),
                                             ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()

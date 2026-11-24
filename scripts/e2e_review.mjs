// Browser test of the review workflow with pending edits (Release A), against the real web build and the real API.
// Needs: scripts/e2e_review_server.py running, the web app built with NEXT_PUBLIC_API_URL=http://127.0.0.1:8031,
// NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:8032, NEXT_PUBLIC_SUPABASE_ANON_KEY=any and started on 127.0.0.1:3031, playwright.
//   node scripts/e2e_review.mjs /tmp/e2e.json [screenshot directory]
import fs from "node:fs";
import { createRequire } from "node:module";
const { chromium } = createRequire(process.cwd() + "/")("playwright");
const info = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const shots = process.argv[3];
const WEB = "http://127.0.0.1:3031", API = "http://127.0.0.1:8031/api/v1", AUTH = "http://127.0.0.1:8032";
let failed = 0, passed = 0;
const check = (name, ok, detail = "") => { ok ? passed++ : failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${name} ${detail}`); };
const api = async (method, path, body) => {
  const r = await fetch(API + path, { method, headers: { "content-type": "application/json", authorization: `Bearer ${info.token}` }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text();
  if (!r.ok) throw new Error(`${method} ${path} ${r.status} ${t.slice(0, 200)}`);
  return t ? JSON.parse(t) : {};
};
const control = async (what, body) => (await fetch(`${AUTH}/control/${what}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...body, password: info.password }) })).json();
const BODY = "방학 중 교내에 개인 짐을 보관할 수 없습니다. 첨부 안내문을 참고하세요.";
const importBoard = async (title, files, body = BODY) => {
  await control("board", { title, files, body });
  const { job_id } = await api("POST", `/admin/sources/${info.source}/ingest`);
  for (let i = 0; i < 100; i++) {
    const j = await api("GET", `/admin/ingestion-jobs/${job_id}`);
    if (!["queued", "running"].includes(j.status)) return j;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("import did not finish");
};
const T1 = "승인된 제목", T2 = "미승인 새 제목", A = "alpha-form.pdf", B = "beta-form.pdf", C = "gamma-form.pdf";

const job = await importBoard(T1, [A]);
if (!job.version_id) throw new Error(JSON.stringify(job).slice(0, 600));
await api("POST", `/admin/versions/${job.version_id}/approve`, {});
const doc = job.document_id;

const browser = await chromium.launch();
const ctx = await browser.newContext({ locale: "en-US", extraHTTPHeaders: { "accept-language": "en" }, viewport: { width: 1280, height: 1600 } });
const errors = [];
const admin = await ctx.newPage();
admin.on("pageerror", (e) => errors.push(String(e)));
const studentCtx = await browser.newContext({ locale: "en-US" });
const student = await studentCtx.newPage();
student.on("pageerror", (e) => errors.push(String(e)));
const shot = async (p, n) => { if (shots) await p.screenshot({ path: `${shots}/${n}.png`, fullPage: true }); };
const studentSees = async () => {
  await student.goto(`${WEB}/knowledge/${doc}`);
  await student.getByRole("heading", { level: 1 }).first().waitFor();
  await student.getByText("#" + info.notice).first().waitFor();
  const raw = JSON.stringify(await (await fetch(`${API}/knowledge/documents/${doc}`)).json());
  const text = (await student.locator("main").evaluate((m) => m.textContent)) + (await student.content()) + raw;
  return { title: await student.getByRole("heading", { level: 1 }).first().innerText(), files: [A, B, C].filter((f) => text.includes(f)), text };
};
const open = async () => { await admin.goto(`${WEB}/admin/documents/${doc}`); await admin.getByRole("heading", { name: "Version history" }).waitFor(); };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

let s = await studentSees();
check("student sees the approved notice", s.title.includes(T1) && same(s.files, [A]));
await admin.goto(`${WEB}/admin/documents/${doc}`);
await admin.waitForURL(/login/);
check("admin page asks for a login", true);
await admin.getByTestId("login-staff").click();
await admin.locator("#email").fill("super_admin@example.test");
await admin.locator("#password").fill(info.password);
await admin.locator("form button[type=submit]").click();
await admin.waitForURL((u) => !u.pathname.startsWith("/login"));

// 1. a pending edit: title, text and attachment
await importBoard(T2, [B], BODY + " 변경된 본문 SECRET-EDIT");
s = await studentSees();
check("student: pending title, text and attachment are not visible", s.title.includes(T1) && same(s.files, [A]) && !s.text.includes("SECRET-EDIT"));
await shot(student, "1-student-while-pending");
await open();
let text = await admin.locator("main").innerText();
check("admin: heading is the published title", (await admin.getByRole("heading", { level: 1 }).first().innerText()).includes(T1));
check("admin: warning shows the new title", text.includes(`The title changes from '${T1}' to '${T2}'`));
check("admin: warnings show the attachments", text.includes(`New attachment when this version is approved: ${B}`) && text.includes(`Attachment removed when this version is approved: ${A}`));
check("admin: current and proposed version", text.includes("Current approved version") && text.includes("Proposed new version"));
check("admin: differences show the pending text", text.includes("SECRET-EDIT") && text.includes("Changes since the approved version"));
await shot(admin, "2-admin-pending");
// 2. the review queue lists it
await admin.goto(`${WEB}/admin/review`);
await admin.getByText(T1).first().waitFor();
check("review queue lists the document", true);
// 3. edit the text
await open();
const editor = admin.locator("#rv-text");
await editor.fill((await editor.inputValue()) + "\n\nReviewer correction.");
await admin.getByRole("button", { name: "Save text" }).click();
await admin.getByText("Text saved and re-indexed.").waitFor();
s = await studentSees();
check("edit saved, nothing public", !s.text.includes("Reviewer correction") && same(s.files, [A]));
// 4. send back
await admin.locator("#rv-reason").fill("Please check the new form");
await admin.getByRole("button", { name: "Request changes" }).click();
await admin.getByText("Sent back to the submitter for changes.").waitFor();
await admin.getByText("This is a draft.").waitFor();
check("sent back: approval is blocked for a draft", await admin.getByRole("button", { name: "Approve and index" }).isDisabled());
s = await studentSees();
check("sent back: nothing public", s.title.includes(T1) && same(s.files, [A]));
// 5. resubmitted (the submitter's page), approve in the review page
let d = await api("GET", `/admin/documents/${doc}`);
await api("POST", `/admin/versions/${d.pending_version.id}/submit`);
await open();
await admin.getByRole("button", { name: "Approve and index" }).click();
await admin.getByText("Active – searchable.").waitFor();
s = await studentSees();
check("approved: title, text and attachment change together", s.title.includes(T2) && same(s.files, [B]) && s.text.includes("Reviewer correction"), JSON.stringify({ t: s.title, f: s.files, c: s.text.includes("Reviewer correction") }));
await admin.getByText("Nothing is awaiting review for this document.").waitFor();
check("admin: heading follows", (await admin.getByRole("heading", { level: 1 }).first().innerText()).includes(T2));
await shot(admin, "3-admin-approved");
// 6. reject in the browser
await importBoard("가짜 제목", [C], BODY + " REJECT-ME");
await open();
await admin.getByRole("button", { name: "Reject", exact: true }).click();
check("reject needs a reason", await admin.getByText("A reason is required.").isVisible());
await admin.locator("#rv-reason").fill("Not an official form");
await admin.getByRole("button", { name: "Reject", exact: true }).click();
await admin.getByText("Version rejected.").waitFor();
s = await studentSees();
check("rejected: nothing public", s.title.includes(T2) && same(s.files, [B]) && !s.text.includes("REJECT-ME"), JSON.stringify({ t: s.title, f: s.files }));
// 7. roll back in the browser
await open();
await admin.getByRole("row", { name: /^v1 / }).getByRole("button", { name: "Roll back to this" }).click();
await admin.getByText("Rolled back to the selected version.").waitFor();
s = await studentSees();
check("rollback restores title, text and attachment", s.title.includes(T1) && same(s.files, [A]) && !s.text.includes("SECRET-EDIT"));
// 8. announcement: translators and the model get the approved text while an edit waits
const ann = await api("POST", "/admin/announcements", { title: "장학금 안내", body: "승인된 공지 본문입니다. 2026-12-01", category: "scholarships", source_type: "manual_text", submit: true, evidence_note: "synthetic" });
await api("POST", `/admin/announcements/${ann.id}/approve`, {});
const { document_id } = await control("announcement-edit", { id: ann.id, text: "SECRET-ANNOUNCEMENT 수정 대기 본문입니다. 2026-12-20" });
await control("prompts", {});
await admin.goto(`${WEB}/admin/translations/${ann.id}/en`);
await admin.getByText("승인된 공지 본문입니다").first().waitFor();
text = await admin.locator("main").innerText();
check("translation page shows the approved original only", !text.includes("SECRET-ANNOUNCEMENT"));
await api("POST", `/admin/announcements/${ann.id}/translations/en/machine-translate`);
const { prompts } = await control("prompts", {});
check("the model got the approved text only", prompts.length > 0 && prompts.every((p) => !p.includes("SECRET-ANNOUNCEMENT")), `${prompts.length} prompts`);
await admin.goto(`${WEB}/admin/documents/${document_id}`);
await admin.getByText("SECRET-ANNOUNCEMENT").first().waitFor();
check("the reviewer sees the waiting edit of the announcement", true);
await admin.getByRole("button", { name: "Approve and index" }).click();
await admin.getByText("Active – searchable.").waitFor();
await student.goto(`${WEB}/announcements/${ann.id}`);
await student.getByText("SECRET-ANNOUNCEMENT").first().waitFor();
check("approved announcement edit is public", true);
await admin.goto(`${WEB}/admin/translations/${ann.id}/en`);
await admin.getByText("SECRET-ANNOUNCEMENT").first().waitFor();
check("translation page now shows the new original", true);
await shot(admin, "4-translation-after-approval");
check("no page errors", errors.length === 0, errors.slice(0, 2).join(" | "));
await browser.close();
console.log(`${passed}/${passed + failed} passed`);
process.exit(failed ? 1 : 0);

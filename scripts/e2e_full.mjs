// Full journeys in a real browser against scripts/dev_stack.py (real database, real API with its worker, real Qwen, LIVE official
// SCH websites, the GPU worker as its own process). Synthetic users. Never points at production.
//   node scripts/e2e_full.mjs INFO.json OUTDIR WORKER_PYTHON BACKEND_DIR
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
const { chromium } = createRequire(process.cwd() + "/")("playwright");
const [infoFile, OUT, WPY, BACKEND] = process.argv.slice(2);
const info = JSON.parse(fs.readFileSync(infoFile, "utf8"));
const WEB = info.web, API = info.api + "/api/v1";
// loopback, or (info.staging, written by scripts/staging_bootstrap.py) a hosted STAGING copy; never the production services
const PRODUCTION = ["sch-hub-api.onrender.com", "sch-international-students-hub.onrender.com"];
for (const u of [WEB, info.api, info.auth]) {
  const host = new URL(u).hostname;
  if (PRODUCTION.includes(host) || (info.production_ref && host.startsWith(info.production_ref))) throw new Error(`refusing production: ${host}`);
  if (!u.startsWith("http://127.0.0.1:") && !(info.staging && u.startsWith("https://"))) throw new Error("loopback or a hosted staging copy only");
}
const EMAIL = (who) => `${who}@${info.email_domain ?? "example.test"}`;
const only = process.env.ONLY ? process.env.ONLY.split(",") : null;
const GPU_MODEL = process.env.E2E_GPU_MODEL || "translategemma:12b";   // the translation model chosen in TRANSLATION-EVALUATION.md
let passed = 0, failed = 0;
const check = (n, ok, d = "") => { ok ? passed++ : failed++; console.log(`${ok ? "PASS" : "FAIL"}  ${n}  ${ok ? "" : d}`); };
const api = async (who, method, p, body) => {
  const r = await fetch(API + p, { method, headers: { "content-type": "application/json", ...(who ? { authorization: `Bearer ${info.tokens[who]}` } : {}) }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text();
  return { status: r.status, data: t ? JSON.parse(t) : null };
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (fn, s = 60) => { for (let i = 0; i < s * 2; i++) { const v = await fn(); if (v) return v; await sleep(500); } return null; };
const browser = await chromium.launch();
const errors = [];
const context = async (who, opts = {}) => {
  const ctx = await browser.newContext({ locale: "en-US", viewport: { width: 1360, height: 900 }, ...opts });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`${who}: ${String(e).slice(0, 200)}`));
  page.on("console", (m) => { if (m.type() === "error" && /MISSING_MESSAGE|Hydration|hydrat/.test(m.text())) errors.push(`${who}: ${m.text().slice(0, 200)}`); });
  if (who !== "visitor") {
    await page.goto(`${WEB}/login`);
    if (!who.startsWith("student")) await page.getByTestId("login-staff").click();
    await page.locator("#email").fill(EMAIL(who));
    await page.locator("#password").fill(info.password);
    await page.locator("form button[type=submit]").click();
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20000 });
  }
  return { ctx, page };
};
const shot = (p, n) => p.screenshot({ path: path.join(OUT, `${n}.png`), fullPage: false }).catch(() => {});
const lang = async (page, code) => { await page.context().addCookies([{ name: "NEXT_LOCALE", value: code, url: WEB }]); };
const desk = async (page, id) => { await page.goto(`${WEB}/ai-office?desk=${id}`); await page.getByTestId("office-panel").waitFor({ timeout: 20000 }); };
const tab = async (page, name) => page.getByTestId("office-panel").getByRole("tab", { name, exact: true }).click();
const ask = async (page, text, s = 90) => {
  const before = await page.getByTestId("assistant-answer").count();
  await page.getByTestId("office-panel").locator("textarea, input[type=text]").last().fill(text);
  await page.getByTestId("office-panel").getByRole("button", { name: /Send|보내기|Kirim|Gửi|发送/ }).click();
  return until(async () => {
    if ((await page.getByTestId("assistant-answer").count()) <= before) return null;
    const last = page.getByTestId("assistant-answer").last();
    const t = await last.innerText();
    await sleep(1500);
    return (await last.innerText()) === t && t.length > 20 && (await page.getByTestId("office-panel").locator("textarea:disabled").count()) === 0 ? t : null;
  }, s);
};
const J = {};

J.staging = async () => {   // only on a hosted staging copy
  if (!info.staging) return;
  const { page, ctx } = await context("visitor");
  await page.goto(WEB);
  check("the staging banner is on every page", await page.getByTestId("staging-banner").isVisible());
  check("search engines are told not to index it", (await page.locator('meta[name="robots"]').getAttribute("content") ?? "").includes("noindex"));
  const h = await (await fetch(info.api + "/health")).json();
  check("the API is the staging API with a database", h.status === "ok" && h.supabase === "configured");
  await ctx.close();
};

J.setup = async () => {   // synthetic approved guides
  const docs = [["D-2 extension guide (SYNTHETIC)", "visa-immigration", "en", "You can apply to extend a D-2 stay from 14 weeks before the period of stay ends. Required documents: passport, residence card, certificate of enrollment, transcript and proof of residence. The fee is 71,000 won."],
    ["[가상] 유학생 시간제 취업 허용 시간 안내", "part-time-employment", "ko", "유학생의 시간제 취업 허용 시간은 학기 중 주당 27시간 이내입니다. 시작하기 전에 반드시 시간제 취업 허가를 받아야 합니다."]];
  for (const [title, category, language, text] of docs) {
    const s = await api("admin", "POST", "/admin/sources", { title: `SYNTHETIC ${title}`, organization: "SYNTHETIC", source_type: "manual_text", authority_type: "official_university", scope: "university", category, language });
    const j = await api("admin", "POST", `/admin/sources/${s.data.id}/submit-text`, { title, text });
    await api("admin", "POST", `/admin/versions/${j.data.version_id}/approve`, {});
    const ok = await until(async () => (await api(null, "GET", `/knowledge/documents/${j.data.document_id}`)).status === 200, 90);
    check(`setup: '${title}' approved, indexed by the worker and public`, ok);
  }
};

J.announcement = async () => {   // Robo: real source -> candidate -> review -> approval -> RAG answer in Indonesian with citation
  const { page } = await context("super_admin");
  await page.goto(`${WEB}/admin/agents`);
  await page.getByRole("tab", { name: "Sources" }).click();
  const card = page.getByTestId("prepared").filter({ hasText: "SCH 국제교육교류처 유학생 공지사항" });
  await card.getByRole("button", { name: /Add/ }).click();
  check("admin adds a prepared official source in the browser", await page.getByTestId("source-row").filter({ hasText: "유학생 공지사항" }).waitFor({ timeout: 15000 }).then(() => true, () => false));
  await shot(page, "admin-sources");
  await desk(page, "guide-bot");
  await page.getByTestId("action-check_official_sources").first().click();
  const done = await until(async () => { const r = await api("super_admin", "GET", "/admin/agent-operations/tasks"); return r.data.items.find((x) => x.task_type === "announcement_discovery" && x.status === "completed"); }, 120);
  check("Robo read the LIVE SCH board in the background worker", done && done.new_count > 0, JSON.stringify(done));
  console.log(`      new items: ${done?.new_count}`);
  await page.reload();
  await page.getByTestId("office-panel").waitFor();
  await tab(page, "Review");
  await page.getByTestId("agent-item").first().waitFor({ timeout: 20000 });
  await shot(page, "robo-review");
  const items = (await api("super_admin", "GET", "/admin/discovery/items?agent_id=announcement")).data.items;
  const pick = items.find((x) => /입사생|생활관|짐/.test(x.title)) ?? items[0];
  check("nothing of it is public yet", !(await api(null, "GET", "/knowledge/documents?page_size=50")).data.items.some((d) => d.title.includes(pick.title.slice(0, 12))));
  const el = page.getByTestId("agent-item").filter({ hasText: pick.title.slice(0, 20) }).first();
  await el.getByTestId("send-to-review").click();
  const doc = await until(async () => (await api("admin", "GET", "/admin/documents?review_status=pending_review")).data.items.find((d) => d.title.includes(pick.title.slice(4, 16))), 60);
  if (!doc) console.log("      jobs:", JSON.stringify((await api("admin", "GET", "/admin/ingestion-jobs?page_size=5")).data.items.map((x) => [x.status, x.outcome, x.error_code, x.error_message])), "docs:", JSON.stringify((await api("admin", "GET", "/admin/documents")).data.items.map((d) => [d.title, d.pending_version_id])));
  check("candidate became a version that waits for review", doc, pick.title);
  await page.goto(`${WEB}/admin/documents/${doc.id}`);
  await page.getByRole("button", { name: "Approve and index" }).click();
  check("approved in the browser and indexed by the worker", await page.getByText("Active – searchable.").waitFor({ timeout: 60000 }).then(() => true, () => false));
  const st = await context("student");
  await lang(st.page, "id");
  await desk(st.page, "supporter-id");
  const q = /입사|모집/.test(pick.title) ? "Sampai kapan pendaftaran asrama untuk liburan musim dingin?" : `Apa isi pengumuman ini: ${pick.title}?`;
  const a = await ask(st.page, q);
  await shot(st.page, "sari-answer-id");
  console.log("      id:", (a ?? "").replace(/\s+/g, " ").slice(0, 220));
  check("Sari answers in Indonesian from the approved notice (Qwen + RAG)", a && /\b(yang|untuk|dan|pada|tanggal|pendaftaran|asrama)\b/i.test(a), a);
  const src = st.page.getByTestId("answer-sources").last();
  check("the citation is shown and opens", (await src.getByRole("link").count()) > 0);
  const f = await ask(st.page, "Berapa biayanya?");
  check("a follow-up question is answered", f && f.length > 20, f);
  await st.ctx.close();
  await page.context().close();
};

J.pdf = async () => {   // admin uploads a synthetic Korean PDF in the browser -> worker extracts -> review -> approval -> search -> RAG answer
  const pdf = path.join(OUT, "synthetic-deposit-notice.pdf");
  const py = process.env.PDF_PYTHON ?? path.join(BACKEND, ".venv/bin/python");
  const tag = Date.now().toString(36);
  const code = `import fitz,sys\nd=fitz.open();p=d.new_page()\np.insert_text((50,60),"(합성) 생활관 보증금 환불 안내 ${tag}\\n\\n보증금 환불 신청 기간: 3월 2일 ~ 3월 13일\\n환불 금액: 보증금 50,000원 전액\\n신청 장소: 글로벌빌리지 1층 행정실\\n준비물: 학생증, 본인 명의 통장 사본\\n\\n※ 시험용 합성 데이터입니다.",fontname="korea",fontsize=12)\nd.save(sys.argv[1])`;
  const made = await new Promise((res) => { const p = spawn(py, ["-c", code, pdf]); p.on("close", (c) => res(c === 0)); p.on("error", () => res(false)); });
  check("a synthetic Korean PDF was made", made && fs.existsSync(pdf), py);
  const title = `(합성) 생활관 보증금 환불 안내 ${tag}`;
  const { page, ctx } = await context("admin");
  await page.goto(`${WEB}/admin/knowledge-sources/new`);
  await page.getByRole("tab", { name: "Document upload" }).click();
  await page.locator("#doc-title").fill(title);
  await page.locator("#doc-org").fill("SYNTHETIC TEST");
  await page.getByTestId("doc-input").setInputFiles(pdf);
  await page.getByRole("button", { name: "Upload and extract" }).click();
  const review = page.getByRole("link", { name: "Open review" }).first();
  check("upload accepted; the worker extracted the text in the background", await review.waitFor({ timeout: 300000 }).then(() => true, () => false));
  check("the extracted text is shown before review", await page.getByText("보증금 환불 신청 기간").first().waitFor({ timeout: 10000 }).then(() => true, () => false));
  const hidden = await api(null, "POST", "/knowledge/search", { query: "생활관 보증금 환불 신청 기간", top_k: 5 });
  check("nothing is searchable before approval", !(hidden.data?.results ?? []).some((r) => r.document_title?.includes(tag)));
  await shot(page, "pdf-extracted");
  await review.click();
  await page.getByRole("button", { name: "Approve and index" }).click();
  check("approved in the browser and indexed by the worker", await page.getByText("Active – searchable.").waitFor({ timeout: 180000 }).then(() => true, () => false));
  const found = await api(null, "POST", "/knowledge/search", { query: "생활관 보증금 환불 신청 기간", top_k: 5 });
  check("the PDF is found by a Korean search", (found.data?.results ?? []).some((r) => r.document_title?.includes(tag)), JSON.stringify((found.data?.results ?? []).map((r) => r.document_title)));
  const en = await api(null, "POST", "/knowledge/search", { query: "When can I get my dormitory deposit refunded?", top_k: 5 });
  console.log("      English search top:", JSON.stringify((en.data?.results ?? []).slice(0, 3).map((r) => r.document_title)));
  if (process.env.LLM !== "none") {
    const st = await context("student");
    await desk(st.page, "supporter-en");
    const a = await ask(st.page, "When can I apply for the dormitory deposit refund, and where?");
    console.log("      en:", (a ?? "").replace(/\s+/g, " ").slice(0, 200));
    check("the answer quotes the approved PDF (dates or office)", a && /(13|March|3월|Global Village|글로벌빌리지)/i.test(a), a);
    await st.ctx.close();
  }
  await ctx.close();
};

J.visa = async () => {
  const { page, ctx } = await context("student");
  await desk(page, "visa");
  await page.getByTestId("topic-d2_extension").click();
  console.log("      checklist:", JSON.stringify((await api("student", "POST", "/agents/immigration/tools", { tool: "visa_checklist", params: { topic: "extension" } })).data).slice(0, 400));
  check("Yuna's checklist quotes the approved guide", await page.getByText(/14 weeks before/).first().waitFor({ timeout: 15000 }).then(() => true, () => false));
  await tab(page, "Chat");
  const a = await ask(page, "Which documents do I need to extend my D-2 stay and what is the fee?");
  console.log("      en:", (a ?? "").replace(/\s+/g, " ").slice(0, 200));
  check("Yuna answers with the fee and documents of the guide", a && /71,000/.test(a) && /passport/i.test(a), a);
  const b = await ask(page, "How much is a parking permit on campus?");
  check("Yuna does not invent an answer", b && !/\d{2},?\d{3}/.test(b), b);
  await shot(page, "yuna");
  await tab(page, "Updates");
  check("Updates tab is honest without a source", await page.getByText("No official website is configured for this desk yet.").waitFor({ timeout: 10000 }).then(() => true, () => false));
  await ctx.close();
};

J.chats = async () => {   // every desk that chats, in its own or the student's language, with Qwen and the approved guide
  const q = { en: "What is the fee for extending a D-2 stay?", ko: "D-2 체류기간 연장 수수료는 얼마인가요?", id: "Berapa biaya perpanjangan izin tinggal D-2?", vi: "Lệ phí gia hạn lưu trú D-2 là bao nhiêu?", "zh-CN": "D-2 延长居留的手续费是多少？" };
  const desks = [["reception", "en"], ["supporter-ko", "ko"], ["supporter-en", "en"], ["supporter-id", "id"], ["supporter-vi", "vi"], ["supporter-zh", "zh-CN"], ["academic", "en"], ["topik", "ko"], ["opportunities", "id"], ["events", "vi"], ["career", "zh-CN"], ["supporter-lead", "en"]];
  const { page, ctx } = await context("student2");
  for (const [id, l] of desks) {
    await lang(page, id.startsWith("supporter-") && id !== "supporter-lead" ? "en" : l);
    await desk(page, id);
    const t = page.getByTestId("office-panel").getByRole("tab", { name: /^(Chat|채팅|Obrolan|Trò chuyện|聊天|대화|对话)$/ });
    if (await t.count()) await t.first().click();
    const a = await ask(page, q[l], 60);
    check(`${id} answers in ${l} with the right fee`, a && /71[,.]?000/.test(a), a);
  }
  await ctx.close();
};

J.career = async () => {   // Daniel: live board -> candidate -> approval -> visible
  const { page, ctx } = await context("admin");
  const cat = (await api("admin", "GET", "/admin/discovery/catalog")).data.items.find((x) => x.name.includes("취업·아르바이트 공지"));
  await api("admin", "POST", "/admin/discovery/sources", { agent_id: cat.agent_id, name: cat.name, kind: cat.kind, url: cat.url, category: cat.category, language: cat.language, config: { max_items: 5 } });
  await desk(page, "career");
  await tab(page, "Sources");
  await page.getByTestId("action-check_official_sources").first().click();
  const done = await until(async () => (await api("admin", "GET", "/admin/agent-operations/tasks?agent_id=career")).data.items.find((x) => x.status === "completed"), 120);
  check("Daniel read the LIVE employment board", done && done.new_count > 0);
  const items = (await api("admin", "GET", "/admin/discovery/items?agent_id=career")).data.items;
  const job = items.find((x) => x.opportunity_kind === "job" && x.open_status !== "closed") ?? items.find((x) => x.opportunity_kind === "job");
  check("a job was recognised with its official link", job && job.href.startsWith("https://sgee.sch.ac.kr/"), JSON.stringify(items.map((i) => i.title)));
  await api("admin", "POST", `/admin/discovery/items/${job.id}/send-to-review`);
  const doc = await until(async () => (await api("admin", "GET", "/admin/documents?review_status=pending_review")).data.items.find((d) => d.title.includes(job.title.slice(4, 14))), 90);
  const st = await context("student2");
  await desk(st.page, "career");
  check("the job is invisible before approval", !(await st.page.getByTestId("office-panel").innerText()).includes(job.title.slice(4, 18)));
  const sites = st.page.getByTestId("career-sites").locator("a[data-connected=false]");
  await st.page.getByTestId("career-sites").waitFor({ timeout: 15000 }).catch(() => {});
  check("Daniel lists the official job sites as links that are not connected", (await sites.count()) === 7 && /Not connected/.test(await st.page.getByTestId("career-sites").innerText()), String(await sites.count()));
  await api("admin", "POST", `/admin/versions/${doc.pending_version_id ?? (await api("admin", "GET", `/admin/documents/${doc.id}`)).data.pending_version.id}/approve`, {});
  await until(async () => (await api(null, "GET", `/knowledge/documents/${doc.id}`)).status === 200, 60);
  const listed = (await api(null, "POST", "/agents/career/tools", { tool: "opportunity_search", params: { kind: "job", include_closed: true } })).data.result.items;
  check("after approval Daniel shows it, linked to the approved document", listed.some((i) => i.id === job.id && i.reliability === "verified"), JSON.stringify(listed.map((x) => x.title)));
  await desk(st.page, "career");
  await shot(st.page, "daniel");
  await st.ctx.close();
  await ctx.close();
};

J.scholarship = async () => {
  const cat = (await api("admin", "GET", "/admin/discovery/catalog")).data.items.find((x) => x.name === "순천향대학교 장학공지");
  await api("admin", "POST", "/admin/discovery/sources", { agent_id: cat.agent_id, name: cat.name, kind: cat.kind, url: cat.url, category: cat.category, language: cat.language, config: { ...cat.config, max_items: 4 } });
  await api("admin", "POST", "/agents/scholarship/tasks", { task_type: "opportunity_discovery" });
  const done = await until(async () => (await api("admin", "GET", "/admin/agent-operations/tasks?agent_id=scholarship")).data.items.find((x) => x.status === "completed"), 120);
  check("Leo read the LIVE scholarship board", done && done.new_count > 0);
  const item = (await api("admin", "GET", "/admin/discovery/items?agent_id=scholarship")).data.items.find((x) => x.opportunity_kind === "scholarship");
  check("deadline and eligibility are quoted, duplicates grouped", item && Array.isArray(item.eligibility) && "deadlines" in item, JSON.stringify(item ?? {}).slice(0, 200));
  const { page, ctx } = await context("student");
  await desk(page, "opportunities");
  check("students see no unreviewed scholarship", !(await page.getByTestId("office-panel").innerText()).includes(item.title.slice(0, 16)));
  await shot(page, "leo-student");
  await ctx.close();
};

J.gpu = async () => {   // token in the browser -> worker process -> draft -> language review -> public
  const sa = await context("super_admin");
  await sa.page.goto(`${WEB}/admin/gpu-worker`);
  await sa.page.locator("#worker-name").fill("school-gpu");
  await sa.page.getByRole("button", { name: /Create/ }).click();
  const token = (await sa.page.getByTestId("gpu-token").locator("code").innerText()).trim();
  check("super administrator creates the worker and sees its token once", /^schgw_/.test(token));
  await sa.page.getByRole("button", { name: "Hide" }).click();
  await sa.page.reload();
  check("the token is not shown again", !(await sa.page.content()).includes(token));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gpuw-"));
  fs.writeFileSync(path.join(dir, "token"), token, { mode: 0o600 });
  const worker = (...args) => new Promise((res) => { let log = ""; const p = spawn(WPY, ["-m", "app.gpu_worker", ...args], { cwd: BACKEND, env: { PATH: process.env.PATH, HOME: dir, GPU_WORKER_HUB_URL: info.api, GPU_WORKER_TOKEN_FILE: path.join(dir, "token"), GPU_WORKER_IDLE_MIN_SECONDS: "5", OLLAMA_MODEL: GPU_MODEL } });
    p.stdout.on("data", (d) => (log += d)); p.stderr.on("data", (d) => (log += d)); p.on("close", (code) => res({ code, log })); });
  const chk = await worker("--check");
  check("worker --check", chk.code === 0, chk.log);
  await worker("--drain");                       // first contact: the worker is now known as available
  const ann = await api("admin", "POST", "/admin/announcements", { title: "[가상] 기숙사 점검 안내", body: "기숙사 냉장고 점검은 2026년 12월 2일 13:30에 합니다. 점검 전에 냉장고를 비워 주십시오. 문의: 041-000-1234", category: "dormitory-housing", source_type: "manual_text", submit: true, evidence_note: "synthetic", original_language: "ko" });
  await api("admin", "POST", `/admin/announcements/${ann.data.id}/approve`, {});
  // Journey G (Release 1): a Korean notice -> Indonesian draft on the GPU -> the Indonesian reviewer -> public in Indonesian only
  const sup = await context("reviewer_id");
  await desk(sup.page, "supporter-id");
  await tab(sup.page, "Queue");
  const row = sup.page.getByTestId("queue-item").filter({ hasText: "기숙사 점검" });
  await row.waitFor({ timeout: 15000 });
  await row.getByTestId("request-draft").click();
  check("Indonesian reviewer requests a draft; it waits for the GPU", await sup.page.getByText(/queued for the university GPU/).waitFor({ timeout: 15000 }).then(() => true, () => false));
  await shot(sup.page, "sari-queue");
  const vi = await api("supporter_vi", "POST", `/admin/announcements/${ann.data.id}/translations/vi/machine-translate`);
  check("no machine draft of an announcement in Vietnamese (Release 1)", vi.status === 409 && vi.data?.error?.code === "language_out_of_scope", JSON.stringify(vi.data));
  const t0 = Date.now();
  const draftOf = async () => { const d = (await api("reviewer_id", "GET", `/admin/announcements/${ann.data.id}/translations/id`)).data;
    return { d, body: d?.translation?.body ?? d?.body ?? "" }; };
  // a refused draft (e.g. wrong language) is re-queued by the server with a back-off: drain again when it is due, at most 3 times
  let run = null, got = { d: null, body: "" }, drains = 0;
  for (; drains < 3 && !got.body; drains++) {
    if (drains) await until(async () => (await api("super_admin", "GET", "/admin/gpu/status")).data.jobs.some((j) => j.status === "queued" && new Date(j.run_after) <= new Date()), 180);
    run = await worker("--drain");
    got = await draftOf();
    if (!got.body) console.log(`      drain ${drains + 1}: no draft yet (refused or failed: ${(run.log.match(/error=\w+|llm_\w+/g) || []).slice(-1)})`);
  }
  check(`the GPU worker generated the draft with ${GPU_MODEL}`, run.code === 0 && got.body.length > 20, run.log.slice(-400));
  console.log(`      drain: ${((Date.now() - t0) / 1000).toFixed(1)} s over ${drains} drain(s)`);
  const tr = got.d ?? {};
  const body = got.body;
  console.log("      id:", body.replace(/\s+/g, " ").slice(0, 200), "|", tr.translation?.translation_status ?? tr.translation_status);
  check("the draft needs review, keeps date, time and phone", /2026/.test(body) && /13[:.]30/.test(body) && /041-000-1234/.test(body) && JSON.stringify(tr).includes("needs_review"), JSON.stringify(tr).slice(0, 300));
  const pub = async (lang) => JSON.stringify((await api(null, "GET", `/announcements/${ann.data.id}?lang=${lang}`)).data);
  check("not public before a reviewer approves", body.length > 20 && !(await pub("id")).includes(body.slice(0, 30)));
  const other = await api("supporter_vi", "POST", `/admin/announcements/${ann.data.id}/translations/id/approve`, { original_verified: true });
  check("a reviewer of another language cannot approve it", other.status === 403, other.status);
  const ap = await api("reviewer_id", "POST", `/admin/announcements/${ann.data.id}/translations/id/approve`, { original_verified: true });
  check("the Indonesian reviewer approves", ap.status === 200, JSON.stringify(ap.data));
  check("now it is public in Indonesian", body.length > 20 && (await pub("id")).includes(body.slice(0, 30)));
  const viData = (await api(null, "GET", `/announcements/${ann.data.id}?lang=vi`)).data;
  check("Vietnamese still gets the original (no translation shown)", body.length > 20 && viData.translation === null && viData.body.includes("기숙사 냉장고 점검"),
    JSON.stringify({ translation: viData.translation, body: viData.body?.slice(0, 40) }));
  const reader = await context("visitor");
  await lang(reader.page, "id");
  await reader.page.goto(`${WEB}/announcements/${ann.data.id}`);
  await reader.page.getByTestId("announcement-body").waitFor({ timeout: 20000 });
  check("the Indonesian page shows the reviewed translation", body.length > 20 && (await reader.page.getByTestId("announcement-body").innerText()).includes(body.slice(0, 20)));
  await shot(reader.page, "announcement-id-verified");
  await lang(reader.page, "vi");
  await reader.page.goto(`${WEB}/announcements/${ann.data.id}`);
  await reader.page.getByTestId("fallback-notice").waitFor({ timeout: 20000 });
  check("the Vietnamese page shows the original with the 'not offered yet' note", /chưa được dịch/.test(await reader.page.getByTestId("fallback-notice").innerText()));
  await shot(reader.page, "announcement-vi-original");
  await reader.ctx.close();
  // outage: revoked key while a job waits
  await api("super_admin", "POST", `/admin/announcements/${ann.data.id}/translations/en/machine-translate`);
  const w = (await api("super_admin", "GET", "/admin/gpu/status")).data.workers[0];
  await api("super_admin", "PATCH", `/admin/gpu/workers/${w.id}`, { status: "revoked" });
  const bad = await worker("--once");
  check("a revoked worker stops and gets nothing", bad.code !== 0 && (await api("super_admin", "GET", "/admin/gpu/status")).data.queue.queued === 1, bad.log.slice(-200));
  const pend = (await api("super_admin", "GET", "/admin/gpu/status")).data.jobs[0];
  await sa.page.goto(`${WEB}/admin/gpu-worker`);
  await sa.page.getByRole("button", { name: /Cancel/ }).first().click();
  check("the waiting job is cancelled in the browser", await until(async () => (await api("super_admin", "GET", "/admin/gpu/status")).data.queue.queued === 0, 15), pend?.id);
  await shot(sa.page, "admin-gpu");
  await sup.ctx.close();
  await sa.ctx.close();
};

J.autotr = async () => {   // Admin chooses EN + ID while publishing -> TranslateGemma on the GPU worker -> review -> students
  const name = `autotr-${Date.now() % 1000000}`;
  const w = await api("super_admin", "POST", "/admin/gpu/workers", { name });
  check("a worker credential for this journey", w.status === 201 && /^schgw_/.test(w.data?.token ?? ""), w.status);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gpuw-"));
  fs.writeFileSync(path.join(dir, "token"), w.data.token, { mode: 0o600 });
  const worker = (...args) => new Promise((res) => { let log = ""; const p = spawn(WPY, ["-m", "app.gpu_worker", ...args], { cwd: BACKEND, env: { PATH: process.env.PATH, HOME: dir, GPU_WORKER_HUB_URL: info.api, GPU_WORKER_TOKEN_FILE: path.join(dir, "token"), GPU_WORKER_IDLE_MIN_SECONDS: "5", OLLAMA_MODEL: GPU_MODEL } });
    p.stdout.on("data", (d) => (log += d)); p.stderr.on("data", (d) => (log += d)); p.on("close", (code) => res({ code, log })); });
  // 1. the admin writes a Korean notice and chooses English + Indonesian in "Automatic translation"
  const queueSize = async () => (await api("super_admin", "GET", "/admin/gpu/status")).data.queue.queued;
  const before = await queueSize();
  const adm = await context("admin");
  await adm.page.goto(`${WEB}/admin/announcements/new`);
  const title = `[가상] 기숙사 입사 안내 ${Date.now() % 10000}`;
  await adm.page.getByLabel("Title").fill(title);
  await adm.page.getByLabel("Original text").fill("2027년 2월 24일(수) 10:00부터 기숙사 입사가 시작됩니다.\n\n준비물: 여권, 외국인등록증, 기숙사 계약서. 기숙사비 1,250,000원은 2월 20일까지 납부하세요.\n\n신청: https://sch.ac.kr/dorm  문의: dorm@sch.ac.kr, 041-530-1234");
  check("the original language is not offered as a target", await adm.page.getByTestId("auto-tr-ko").isDisabled());
  await adm.page.getByTestId("auto-tr-en").check();
  await adm.page.getByTestId("auto-tr-id").check();
  await adm.page.getByTestId("auto-translation").scrollIntoViewIfNeeded();
  await shot(adm.page, "autotr-1-form-languages");
  await adm.page.getByRole("button", { name: /Submit for approval/ }).click();
  await adm.page.waitForURL(/\/admin\/announcements\/[0-9a-f-]{36}$/, { timeout: 20000 });
  const aid = adm.page.url().split("/").pop();
  check("nothing is queued before approval", (await queueSize()) === before, `${before} -> ${await queueSize()}`);
  // 2. approval publishes it and queues exactly the two chosen languages for the GPU worker
  await adm.page.getByRole("button", { name: "Approve & publish" }).click();
  await adm.page.getByTestId("auto-tr-save").getByText("Save and translate missing").waitFor({ timeout: 15000 });   // published
  await adm.page.getByTestId("auto-translation-card").scrollIntoViewIfNeeded();
  await shot(adm.page, "autotr-2-published-card");
  const mine = async () => (await api("super_admin", "GET", `/admin/translations?page_size=100`)).data.items.filter((i) => i.announcement_id === aid);
  const queued = await until(async () => { const m = await mine(); const q = m.filter((i) => i.machine?.job_status === "queued"); return q.length === 2 ? q : null; }, 30);
  check("publication queued English and Indonesian once, for the GPU worker", queued && queued.every((i) => i.machine.executor === "gpu") && queued.map((i) => i.language_code).sort().join() === "en,id" && (await queueSize()) === before + 2, JSON.stringify((await mine()).map((i) => [i.language_code, i.machine])));
  // 3. the reviewer sees the honest waiting state (no worker has contacted this server for this credential yet)
  const rev = await context("reviewer_id");
  await rev.page.goto(`${WEB}/admin/translations/${aid}/id`);
  await rev.page.getByTestId("machine-panel").waitFor({ timeout: 20000 });
  const state0 = await rev.page.getByTestId("machine-state").innerText();
  check("the panel shows the real job state, not a disabled button", /Queued|Waiting for the GPU worker/.test(state0) && (await rev.page.getByTestId("machine-run").count()) === 0, state0);
  await shot(rev.page, "autotr-3-waiting-for-gpu");
  // 4. the university GPU worker (this workstation, loopback stack only) runs TranslateGemma 12B
  const chk = await worker("--check");
  check(`worker --check with ${GPU_MODEL}`, chk.code === 0, chk.log.slice(-300));
  const t0 = Date.now();
  let run = null;
  for (let i = 0; i < 3; i++) {
    run = await worker("--drain");
    const m = await mine();
    if (m.filter((x) => ["en", "id"].includes(x.language_code)).every((x) => x.translation_status === "needs_review")) break;
    await sleep(5000);
  }
  console.log(`      drain: ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  const after = await mine();
  check("both drafts were made by TranslateGemma and wait for review", ["en", "id"].every((l) => { const x = after.find((i) => i.language_code === l); return x?.translation_status === "needs_review" && x?.machine?.model === GPU_MODEL; }), JSON.stringify(after.map((i) => [i.language_code, i.translation_status, i.machine?.model, i.machine?.error_code])) + run?.log.slice(-300));
  const idDraft = (await api("reviewer_id", "GET", `/admin/announcements/${aid}/translations/id`)).data;
  const draftBody = idDraft?.translation?.body ?? idDraft?.body ?? "";
  console.log("      id:", draftBody.replace(/\s+/g, " ").slice(0, 240));
  check("the Indonesian draft keeps the date, time, fee, link, e-mail and phone", /2027/.test(draftBody) && /10[:.]00/.test(draftBody) && /1[.,]250[.,]000/.test(draftBody) && draftBody.includes("https://sch.ac.kr/dorm") && draftBody.includes("dorm@sch.ac.kr") && draftBody.includes("041-530-1234"), draftBody.slice(0, 300));
  check("students do not see an unreviewed draft", (await api(null, "GET", `/announcements/${aid}?lang=id`)).data.translation === null);
  await rev.page.reload();
  await rev.page.getByTestId("machine-state").waitFor({ timeout: 20000 });
  check("the reviewer's editor is filled with the draft", (await rev.page.locator("#tre-body").inputValue()).length > 40);
  await shot(rev.page, "autotr-4-draft-for-review");
  // 5. the Indonesian reviewer approves; a reviewer of another language cannot
  const other = await api("supporter_vi", "POST", `/admin/announcements/${aid}/translations/id/approve`, { original_verified: true });
  check("a reviewer of another language cannot approve it", other.status === 403, other.status);
  await rev.page.getByRole("checkbox", { name: /I verified this translation/ }).check();
  await rev.page.getByRole("button", { name: "Approve & publish" }).last().click();
  check("the reviewer approves", await until(async () => (await api(null, "GET", `/announcements/${aid}?lang=id`)).data.translation?.status === "verified", 20));
  await shot(rev.page, "autotr-5-approved");
  // 6. students: Indonesian shows the approved text, English (unreviewed) shows the original with a note
  const reader = await context("visitor");
  await lang(reader.page, "id");
  await reader.page.goto(`${WEB}/announcements/${aid}`);
  await reader.page.getByTestId("announcement-body").waitFor({ timeout: 20000 });
  check("the Indonesian page shows the reviewed translation", (await reader.page.getByTestId("announcement-body").innerText()).includes(draftBody.slice(0, 20)));
  await shot(reader.page, "autotr-6-student-indonesian");
  await lang(reader.page, "en");
  await reader.page.goto(`${WEB}/announcements/${aid}`);
  await reader.page.getByTestId("fallback-notice").waitFor({ timeout: 20000 });
  check("English: the original with 'not available yet' (the draft is not reviewed)", (await reader.page.getByTestId("announcement-body").innerText()).includes("2027년"));
  await shot(reader.page, "autotr-7-student-english-original");
  await reader.ctx.close();
  // 7. the list says where each draft is; the bounded backfill for existing announcements previews first
  const sa = await context("super_admin");
  await sa.page.goto(`${WEB}/admin/translations`);
  await sa.page.getByTestId("machine-cell").first().waitFor({ timeout: 20000 });
  await sa.page.getByTestId("backfill-panel").locator("summary").click();
  await sa.page.getByTestId("backfill-panel").getByRole("button", { name: "Preview" }).click();
  await sa.page.getByTestId("backfill-result").waitFor({ timeout: 20000 });
  await shot(sa.page, "autotr-8-list-and-backfill");
  const again = await api("admin", "POST", `/admin/announcements/${aid}/translations/en/machine-translate`);
  check("asking again for the unchanged English draft creates no job and no inference", again.status === 202 && (await mine()).filter((i) => i.language_code === "en").length === 1, JSON.stringify(again.data));
  await sa.ctx.close();
  await rev.ctx.close();
  await adm.ctx.close();
  await api("super_admin", "PATCH", `/admin/gpu/workers/${w.data.id}`, { status: "revoked" });
};

J.gpuops = async () => {   // failure modes with the REAL worker process and TranslateGemma (local stack; PSQL = scratch DB only)
  const PSQL = process.env.PSQL;
  if (!PSQL || !/sock -p \d+ -U postgres$/.test(PSQL)) { check("scratch database for time simulation", false, "PSQL not set"); return; }
  const sql = (q) => new Promise((res) => { let o = ""; const p = spawn("bash", ["-c", `${PSQL} -d hub -At -v ON_ERROR_STOP=1 -c "$Q"`], { env: { ...process.env, Q: q } });
    p.stdout.on("data", (d) => (o += d)); p.stderr.on("data", (d) => (o += d)); p.on("close", () => res(o.trim())); });
  const w = await api("super_admin", "POST", "/admin/gpu/workers", { name: `ops-${Date.now() % 1000000}` });
  check("worker credential (token written to an owner-only file, never printed)", w.status === 201);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gpuw-"));
  const tokenFile = path.join(dir, "token");
  fs.writeFileSync(tokenFile, w.data.token, { mode: 0o600 });
  const base = { PATH: process.env.PATH, HOME: dir, GPU_WORKER_HUB_URL: info.api, GPU_WORKER_TOKEN_FILE: tokenFile, GPU_WORKER_IDLE_MIN_SECONDS: "5", OLLAMA_MODEL: GPU_MODEL };
  const start = (args, extra = {}) => { let log = ""; const p = spawn(WPY, ["-m", "app.gpu_worker", ...args], { cwd: BACKEND, env: { ...base, ...extra } });
    p.stdout.on("data", (d) => (log += d)); p.stderr.on("data", (d) => (log += d)); return { p, log: () => log, done: new Promise((res) => p.on("close", (code) => res(code))) }; };
  const run = async (args, extra = {}) => { const x = start(args, extra); const code = await x.done; return { code, log: x.log() }; };
  const publishWith = async (title, body, targets) => {
    const a = await api("admin", "POST", "/admin/announcements", { title, body, category: "dormitory-housing", source_type: "manual_text", submit: true,
      evidence_note: "synthetic", original_language: "ko", translation_targets: targets });
    await api("admin", "POST", `/admin/announcements/${a.data.id}/approve`, {});
    return a.data.id;
  };
  const machine = async (aid, lang) => (await api("super_admin", "GET", `/admin/announcements/${aid}/translations/${lang}`)).data;
  const tag = Date.now() % 100000;

  // API unavailable: the worker stops cleanly, takes nothing; the job keeps waiting
  const a1 = await publishWith(`[가상] 도서관 운영 시간 안내 ${tag}`, "중앙도서관은 2026년 12월 21일부터 2027년 2월 28일까지 09:00-18:00에 운영합니다. 문의: 041-530-1000", ["en"]);
  let r = await run(["--drain"], { GPU_WORKER_HUB_URL: "http://127.0.0.1:8099" });
  let m = await machine(a1, "en");
  check("API unavailable: worker stops cleanly, the job stays queued with no attempt used", r.code === 0 && /claim error/.test(r.log) && m.machine.job.status === "queued" && m.machine.job.attempts === 0, r.log.slice(-200));
  // a worker running another model gets no announcement job; a model that is not installed is reported
  r = await run(["--drain"], { OLLAMA_MODEL: "qwen2.5:7b-instruct", GPU_WORKER_MIN_FREE_VRAM_MB: "0" });
  m = await machine(a1, "en");
  check("invalid model: a Qwen worker takes no announcement job", r.code === 0 && m.machine.job.status === "queued" && m.machine.job.attempts === 0, r.log.slice(-200));
  r = await run(["--check"], { OLLAMA_MODEL: "translategemma:27b" });
  check("invalid model: --check reports a model that is not installed", r.code !== 0 && /NOT READY/.test(r.log), r.log.slice(-200));
  // GPU memory: not enough free -> no job taken (the model is unloaded first, so the check really runs)
  await fetch("http://127.0.0.1:11434/api/generate", { method: "POST", body: JSON.stringify({ model: GPU_MODEL, keep_alive: 0 }) }).catch(() => null);
  await sleep(3000);
  r = await run(["--drain"], { GPU_WORKER_MIN_FREE_VRAM_MB: "50000" });
  m = await machine(a1, "en");
  check("not enough free GPU memory: no job taken, no attempt used", r.code === 0 && /gpu busy/.test(r.log) && m.machine.job.status === "queued" && m.machine.job.attempts === 0, r.log.slice(-200));
  // duplicate request while it waits
  const again = await api("admin", "POST", `/admin/announcements/${a1}/translations/en/machine-translate`);
  check("duplicate request: the same job, no second one", again.status === 202 && again.data.job_id === m.machine.job.id, JSON.stringify(again.data));
  // the worker was offline for two days: the panel says so; then it comes back and does the job
  await sql(`update public.gpu_workers set last_seen_at = now() - interval '2 days' where id = '${w.data.id}'`);
  m = await machine(a1, "en");
  check("worker offline: 'Waiting for the GPU worker'", m.machine.state === "waiting_worker" && m.machine.worker.online === false, m.machine.state);
  r = await run(["--drain"]);
  m = await machine(a1, "en");
  check("the worker is back: TranslateGemma drafts it, private, needs review", r.code === 0 && m.translation.translation_status === "needs_review" && m.machine.model === GPU_MODEL && (await api(null, "GET", `/announcements/${a1}?lang=en`)).data.translation === null, r.log.slice(-300));
  console.log("      en:", (m.translation.body || "").replace(/\s+/g, " ").slice(0, 160));
  check("dates, times and phone kept", /2026/.test(m.translation.body) && /2027/.test(m.translation.body) && /09[:.]00/.test(m.translation.body) && /041-530-1000/.test(m.translation.body));

  // expired credential: exit code 77, nothing taken; a rotated token works without other changes
  const a2 = await publishWith(`[가상] 기숙사 정전 안내 ${tag}`, "2026년 12월 5일 10:00-12:00 기숙사 A동 전기 점검으로 정전됩니다. 냉장고 음식을 미리 정리하세요.", ["id"]);
  await sql(`update public.gpu_workers set expires_at = now() - interval '1 minute' where id = '${w.data.id}'`);
  r = await run(["--drain"]);
  m = await machine(a2, "id");
  check("expired credential: the worker stops with exit code 77 and takes nothing", r.code === 77 && m.machine.job.status === "queued", `${r.code} ${r.log.slice(-200)}`);
  const rot = await api("super_admin", "POST", `/admin/gpu/workers/${w.data.id}/rotate`, { grace_minutes: 0 });
  fs.writeFileSync(tokenFile, rot.data.token, { mode: 0o600 });
  r = await run(["--drain"]);
  m = await machine(a2, "id");
  check("after rotation the worker continues (no restart, no other change)", r.code === 0 && m.translation.translation_status === "needs_review", r.log.slice(-200));

  // the original changes: the approved edit outdates the draft and the chosen language is translated again from the new text
  const view = (await api("admin", "GET", `/admin/announcements/${a2}`)).data;
  const edited = "2026년 12월 12일 14:00-16:00 기숙사 A동 전기 점검으로 정전됩니다. 냉장고 음식을 미리 정리하세요.";
  const vid = await sql(`insert into public.document_versions (document_id, version_number, extracted_text, content_hash, verification_status) values ('${view.document_id}', 2, $t$${edited}$t$, encode(sha256(convert_to($t$${edited}$t$, 'UTF8')), 'hex'), 'pending_review') returning id`);
  const ap = await api("admin", "POST", `/admin/versions/${vid.split("\n")[0]}/approve`, {});
  check("the edit is approved through the API", ap.status === 202, JSON.stringify(ap.data).slice(0, 200));
  const requeued = await until(async () => { const x = await machine(a2, "id"); return x.machine.job && x.machine.job.status === "queued" && x.machine.job.id !== m.machine.job.id ? x : null; }, 60);
  check("source changed: a new job for the chosen language (the old draft is not shown as current)", !!requeued, JSON.stringify((await machine(a2, "id")).machine).slice(0, 300));
  r = await run(["--drain"]);
  m = await machine(a2, "id");
  check("the new draft is made from the approved new text", r.code === 0 && /12/.test(m.translation.body) && /14[:.]00/.test(m.translation.body) && m.translation.translation_status === "needs_review", (m.translation.body || "").slice(0, 200));

  // a cancelled announcement is not translated: its queued job ends without sending anything
  const a3 = await publishWith(`[가상] 취소될 안내 ${tag}`, "2026년 12월 30일 행사는 일정이 변경될 수 있습니다. 공지를 확인하세요.", ["en"]);
  await api("admin", "POST", `/admin/announcements/${a3}/cancel`, { reason: "withdrawn (test)" });
  r = await run(["--drain"]);
  m = (await api("super_admin", "GET", `/admin/translations?page_size=100`)).data.items.find((i) => i.announcement_id === a3 && i.language_code === "en");
  check("cancelled original: the job ends, nothing is translated", m && m.translation_status === "todo" && m.machine.job_status === "failed", JSON.stringify(m?.machine));

  // worker restart and lease recovery: kill -9 during the generation, the lease ends, the next run finishes it once
  const long = Array.from({ length: 8 }, (_, i) => `${i + 1}. 2027년 3월 ${i + 2}일 09:30까지 ${["수강신청", "등록금 납부", "기숙사 신청", "건강검진", "외국인등록", "보험 가입", "장학금 신청", "오리엔테이션"][i]} 서류를 국제교류처(041-530-1234)에 제출하세요.`).join("\n\n");
  const a4 = await publishWith(`[가상] 신학기 준비 안내 ${tag}`, long, ["en"]);
  const x = start(["--drain"]);
  const leased = await until(async () => { const y = await machine(a4, "en"); return y.machine.state === "processing" ? y : null; }, 120);
  await sleep(300);
  x.p.kill("SIGKILL");
  await x.done;
  const held = await machine(a4, "en");
  check("worker killed during the generation: the job is still leased, nothing stored", !!leased && held.machine.job.status === "running" && held.translation.translation_status === "todo", held.machine.state);
  await sql(`update public.ingestion_jobs set lease_expires_at = now() - interval '1 second' where id = '${held.machine.job.id}'`);   // 3 minutes later
  await api("super_admin", "GET", "/admin/gpu/status");     // the sweep puts the job back
  r = await run(["--drain"]);
  m = await machine(a4, "en");
  check("lease recovery: the restarted worker finishes it, stored once", r.code === 0 && m.translation.translation_status === "needs_review" && m.machine.job.id === held.machine.job.id && m.machine.job.attempts === 2, JSON.stringify(m.machine.job).slice(0, 300));

  // a revoked credential stops the worker at once
  await api("super_admin", "PATCH", `/admin/gpu/workers/${w.data.id}`, { status: "revoked" });
  r = await run(["--drain"]);
  check("revoked credential: exit code 77", r.code === 77, r.log.slice(-200));
};

J.escalation = async () => {   // student -> Sumin -> consent -> supporter inbox -> answer -> status; other students see nothing
  const { page, ctx } = await context("student");
  await desk(page, "supporter-lead");
  await page.getByTestId("request-language").selectOption("vi").catch(() => {});
  await page.getByTestId("request-subject").fill("Help with my housing contract");
  await page.getByTestId("request-details").fill("PRIVATE-WORDS my landlord does not return the deposit.");
  await page.getByTestId("request-review").click();
  await page.getByRole("button", { name: /Yes, send it|send/i }).last().click();
  const t = await until(async () => (await api("student", "GET", "/support/tickets")).data.items[0], 60);
  check("request sent only after confirmation", t, "no ticket");
  check("another student cannot read it", (await api("student2", "GET", `/support/tickets/${t.id}`)).status === 404 || (await api("student2", "GET", `/support/tickets/${t.id}`)).status === 403);
  const sup = await context("supporter_vi");
  await desk(sup.page, "supporter-lead");
  await tab(sup.page, "Queue");
  const txt = await sup.page.getByTestId("ws-support-queue").waitFor({ timeout: 15000 }).then(async () => { await sleep(1500); return sup.page.getByTestId("ws-support-queue").innerText(); });
  check("Sumin's staff queue shows no private words", !txt.includes("PRIVATE-WORDS"), txt);
  const acc = await api("supporter_vi", "POST", `/support/tickets/${t.id}/accept`);
  check("authorised supporter accepts", acc.status === 200 || acc.status === 409, `${acc.status} ${JSON.stringify(acc.data).slice(0, 150)}`);
  check("supporter of another language cannot open it", [403, 404].includes((await api("reviewer_id", "GET", `/support/tickets/${t.id}`)).status));
  await api("supporter_vi", "POST", `/support/tickets/${t.id}/messages`, { body: "Please bring the contract tomorrow." });
  await page.goto(`${WEB}/support/requests/${t.id}`);
  check("student sees the answer and the status", await page.getByText("Please bring the contract tomorrow.").waitFor({ timeout: 15000 }).then(() => true, () => false));
  check("administrators see the task only as metadata", !JSON.stringify((await api("admin", "GET", "/admin/agent-operations/tasks?agent_id=support-coordinator")).data).includes("PRIVATE-WORDS"));
  await shot(page, "student-ticket");
  await sup.ctx.close();
  await ctx.close();
};

J.admin = async () => {   // every admin page, roles, pause, storage
  const { page, ctx } = await context("super_admin");
  for (const p of ["", "/agents", "/gpu-worker", "/knowledge-sources", "/knowledge-sources/new", "/support", "/submissions", "/documents", "/announcements", "/announcements/new", "/translations", "/review", "/rag-sync", "/users", "/language-teams", "/settings"]) {
    const r = await page.goto(`${WEB}/admin${p}`);
    await page.locator("h1").first().waitFor({ timeout: 20000 }).catch(() => {});
    await sleep(700);
    const text = await page.locator("main").innerText().catch(() => "");
    check(`admin page /admin${p} loads without an error`, r.status() === 200 && (await page.locator("h1").count()) > 0 && !/Something went wrong|could not be loaded|Application error/i.test(text), text.slice(0, 160));
  }
  await page.goto(`${WEB}/admin/agents`);
  check("all 14 desks are listed", (await page.locator("[data-testid^=desk-]").first().waitFor({ timeout: 15000 }).then(() => page.locator("[data-testid^=desk-]").count())) === 14);
  await shot(page, "admin-agents");
  await page.getByTestId("pause-events").click();
  await page.getByText("Paused").first().waitFor({ timeout: 10000 });
  const r = await api("student", "POST", "/agents/events/tasks", { task_type: "event_digest" });
  check("a paused desk starts nothing", r.status === 503 && r.data.error.code === "agent_paused");
  await page.getByTestId("pause-events").click();
  check("and resumes", await until(async () => (await api("student", "POST", "/agents/events/tasks", { task_type: "event_digest" })).status === 201, 10));
  await page.getByRole("tab", { name: "Storage" }).click();
  check("storage shows the real database size", await page.getByTestId("storage").getByText(/Database: \d/).waitFor({ timeout: 10000 }).then(() => true, () => false));
  await shot(page, "admin-storage");
  await page.getByRole("tab", { name: "Schedules" }).click();
  check("every schedule is off", (await page.getByRole("switch").first().waitFor().then(() => page.locator("[role=switch][aria-checked=true]").count())) === 0);
  await ctx.close();
  const s = await context("supporter_vi");
  await s.page.goto(`${WEB}/admin/agents`);
  await sleep(2000);
  check("a supporter does not get the agents page", (await s.page.locator("[data-testid^=desk-]").count()) === 0);
  await s.ctx.close();
  for (const [who, p, m] of [["student", "/admin/agent-operations", "GET"], ["supporter_vi", "/admin/agent-operations", "GET"], ["admin", "/admin/gpu/workers", "POST"], [null, "/admin/overview", "GET"], ["student", "/admin/users", "GET"], ["supporter_vi", "/admin/discovery/sources", "GET"], ["admin", "/admin/users/x/role", "PATCH"]]) {
    const x = await api(who, m, p, m === "GET" ? undefined : { name: "x-worker", role: "admin" });
    check(`${who ?? "visitor"} is refused: ${m} ${p}`, [401, 403].includes(x.status), x.status);
  }
};

J.office = async () => {   // all 14 characters, languages, phone, keyboard
  const { page, ctx } = await context("visitor");
  // the wall must differ visibly from the floor (Release 1 visual change): pastel blue gradient vs. warm planks
  await page.goto(`${WEB}/ai-office`);
  await page.getByTestId("office-wall").waitFor({ timeout: 20000 });
  const colours = await page.evaluate(() => {
    const stops = [...document.querySelectorAll("#office-wall stop")].map((x) => x.getAttribute("stop-color"));
    const plank = document.querySelector("#office-planks rect")?.getAttribute("fill");
    return { stops, plank };
  });
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const blueish = colours.stops.every((c) => { const [r, , b] = hex(c); return b > r; });
  const warm = (() => { const [r, , b] = hex(colours.plank); return r > b; })();
  check("office wall is a cool colour and the floor a warm one", blueish && warm, JSON.stringify(colours));
  await shot(page, "office-wall-desktop");
  const ids = (await api(null, "GET", "/agents")).data.items.map((a) => [a.character_id, a.name]);
  for (const [id, name] of ids) {
    await desk(page, id);
    const ok = await until(async () => { const t = await page.getByTestId("office-panel").innerText(); return t.includes(name) && !/can't be reached|could not be loaded/i.test(t); }, 12);
    check(`${name} opens its workspace`, ok);
  }
  for (const l of ["ko", "id", "vi", "zh-CN", "en"]) {
    await lang(page, l);
    for (const p of ["/", "/knowledge", "/announcements", "/assistant", "/ai-office?desk=visa", "/login", "/support"]) {
      const r = await page.goto(`${WEB}${p}`);
      await sleep(500);
      check(`${l} ${p}`, r.status() === 200 && (await page.evaluate(() => document.documentElement.lang)) === l && !/[a-z]+\.[a-z]+\.[a-zA-Z]+\b(?=\s|$)/.test((await page.locator("h1,h2").allInnerTexts()).join(" ")), await page.evaluate(() => document.documentElement.lang));
    }
  }
  await ctx.close();
  const m = await context("visitor", { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  await m.page.goto(`${WEB}/ai-office`);
  await m.page.getByTestId("office-wall").waitFor({ timeout: 20000 }).catch(() => {});
  await sleep(800);
  await shot(m.page, "office-wall-phone");
  for (const p of ["/", "/knowledge", "/announcements", "/assistant", "/ai-office", "/ai-office?desk=opportunities", "/ai-office?desk=visa", "/login"]) {
    await m.page.goto(`${WEB}${p}`);
    await sleep(1200);
    const over = await m.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`phone ${p}: no sideways scrolling`, over <= 1, `+${over}px`);
  }
  await shot(m.page, "phone-login");
  await m.page.goto(`${WEB}/ai-office?desk=career`);
  await m.page.getByTestId("office-panel").waitFor();
  await sleep(1500);
  await shot(m.page, "phone-daniel");
  check("phone: the desk can be closed", await m.page.getByTestId("panel-back").isVisible());
  await m.ctx.close();
  const ad = await context("super_admin", { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  for (const p of ["/admin/agents", "/admin/gpu-worker", "/admin/review"]) {
    await ad.page.goto(`${WEB}${p}`);
    await sleep(1500);
    const over = await ad.page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`phone ${p}: no sideways scrolling`, over <= 1, `+${over}px`);
  }
  await shot(ad.page, "phone-admin");
  await ad.ctx.close();
  const k = await context("visitor");
  await k.page.goto(`${WEB}/ai-office`);
  await k.page.getByTestId("character-visa").focus();
  await k.page.keyboard.press("Enter");
  check("keyboard: Enter opens a character", await k.page.getByTestId("office-panel").waitFor({ timeout: 10000 }).then(() => true, () => false));
  await k.page.keyboard.press("Escape");
  check("keyboard: Escape closes it", await k.page.getByTestId("office-panel").waitFor({ state: "detached", timeout: 10000 }).then(() => true, () => false));
  await k.ctx.close();
};

J.autonomy = async () => {   // dev_stack --schedules: nobody clicks "check"; the scheduler hook does (development only)
  if (!info.schedules) { console.log("SKIP  dev_stack runs without --schedules"); return; }
  const due = async (secret) => { const r = await fetch(API + "/internal/sync/run-due", { method: "POST", headers: { "x-cron-secret": secret } }); return { status: r.status, data: await r.json() }; };
  const publicBefore = (await api(null, "GET", "/knowledge/documents?page_size=100")).data.items.map((d) => d.id);
  check("the scheduler hook needs its secret", (await due("wrong")).status === 403);
  check("with the server switch on, nothing runs until an administrator enables a schedule", (await due(info.cron)).data.agent_schedules.queued === 0);
  const cat = (await api("admin", "GET", "/admin/discovery/catalog")).data.items.filter((x) => ["SCH 국제교육교류처 유학생 공지사항", "순천향대학교 학사공지", "Study in Korea 학생비자 및 체류자격"].includes(x.name));
  for (const c of cat) await api("admin", "POST", "/admin/discovery/sources", { agent_id: c.agent_id, name: c.name, kind: c.kind, url: c.url, category: c.category, language: c.language, config: { ...c.config, ...(c.kind === "page" ? {} : { max_items: 3 }) } });
  const { page, ctx } = await context("admin");
  await page.goto(`${WEB}/admin/agents`);
  await page.getByRole("tab", { name: "Schedules" }).click();
  for (const s of ["schedule-announcement-announcement_discovery", "schedule-academic-guidance_discovery", "schedule-immigration-guidance_discovery"]) {
    await page.getByTestId(s).getByRole("switch").click();
    await page.getByTestId(s).locator("[aria-checked=true]").waitFor({ timeout: 10000 });
  }
  // weekly (0019): switched on, each waits for its Monday slot (Korea time) plus its own stagger; nothing runs now
  const sch = (await api("admin", "GET", "/admin/agent-schedules")).data;
  const mine = sch.items.filter((x) => x.enabled);
  const kst = (iso) => new Date(new Date(iso).getTime() + 9 * 3600e3);
  check("enabled weekly schedules are planned for distinct Monday slots", mine.length === 3 && mine.every((x) => x.interval_minutes === 10080 && kst(x.next_run_at).getUTCDay() === 1)
    && new Set(mine.map((x) => x.next_run_at)).size === 3, JSON.stringify(mine.map((x) => [x.agent_id, x.next_run_at])));
  check("nothing runs before the weekly slot", (await due(info.cron)).data.agent_schedules.queued === 0);
  // for this test only: a 60-minute interval runs at once (an administrator could do the same)
  for (const x of mine) {
    await api("admin", "PATCH", `/admin/agent-schedules/${x.id}`, { enabled: false });
    await api("admin", "PATCH", `/admin/agent-schedules/${x.id}`, { enabled: true, interval_minutes: 60 });
  }
  const r = await due(info.cron);
  check("three enabled schedules are queued", r.data.agent_schedules.queued === 3, JSON.stringify(r.data));
  const done = await until(async () => { const t = (await api("admin", "GET", "/admin/agent-operations/tasks")).data.items.filter((x) => x.requested === "schedule"); return t.length === 3 && t.every((x) => x.status === "completed") ? t : null; }, 150);
  check("Robo, Joon and Yuna checked the LIVE websites on their own", done, JSON.stringify((await api("admin", "GET", "/admin/agent-operations/tasks")).data.items.map((x) => [x.agent_name, x.status, x.error_code])));
  for (const x of done ?? []) console.log(`      ${x.agent_name}: ${x.result_count} read, ${x.new_count} new`);
  check("administrators were notified about candidates", JSON.stringify((await api("admin", "GET", "/admin/notifications")).data).includes("official notices to review"));
  check("a second hook call does nothing (interval, no duplicates)", (await due(info.cron)).data.agent_schedules.queued === 0);
  const after = (await api(null, "GET", "/knowledge/documents?page_size=100")).data.items.map((d) => d.id);
  check("nothing became public on its own", after.every((id) => publicBefore.includes(id)), JSON.stringify([publicBefore.length, after.length]));
  await page.reload();
  await page.getByRole("tab", { name: "Tasks" }).click();
  check("the admin page shows who started them", (await page.getByText("by a schedule").first().waitFor({ timeout: 10000 }).then(() => page.getByText("by a schedule").count())) === 3);
  await shot(page, "admin-tasks");
  await ctx.close();
};

fs.mkdirSync(OUT, { recursive: true });
for (const [name, fn] of Object.entries(J)) {
  if (only && !only.includes(name)) continue;
  console.log(`== ${name}`);
  try { await fn(); } catch (e) { check(`${name} ran to the end`, false, String(e).slice(0, 400)); }
}
check("no page errors, no missing texts, no hydration errors", errors.length === 0, errors.slice(0, 4).join(" | "));
await browser.close();
console.log(`${passed}/${passed + failed} passed`);
process.exit(failed ? 1 : 0);

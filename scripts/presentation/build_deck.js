// SCH 국제학생 허브 — final presentation deck (Korean). Structured: theme + layouts + sections, native charts.
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.APPLY_THEME || "./apply_theme.js");
const path = require("path");
const OUT = process.argv[2] || "SCH-Hub-final-presentation-ko.pptx";
const SHOTS = path.join(__dirname, "..", "..", "docs", "presentation", "screenshots");
const BROWSER = process.env.BROWSER_RESULT || "114 / 115";        // filled after the re-run

const THEME = {
  name: "SCH Hub", headFontFace: "Malgun Gothic", bodyFontFace: "Malgun Gothic",
  colors: { dk1: "1B2333", lt1: "FFFFFF", dk2: "1F3A8A", lt2: "EEF2FB", accent1: "1F3A8A", accent2: "E9A23B",
            accent3: "2E7D5B", accent4: "B4532A", accent5: "6B7FD7", accent6: "6B7385", hlink: "1F3A8A", folHlink: "6B7FD7" },
};
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";                       // 13.333 x 7.5 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "SCH 국제학생 허브 — 최종 발표"; pres.author = "Lin Erenza"; pres.subject = "SCH International Student Hub";
const C = pres.SchemeColor;
const HEX = THEME.colors;

// ---------- layouts ----------
pres.defineSlideMaster({ title: "TITLE_DARK", background: { color: HEX.dk2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.2, w: 11.7, h: 1.4, fontSize: 44, bold: true, color: C.background1, valign: "bottom", align: "left" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.75, w: 11.7, h: 2.4, fontSize: 20, color: C.background2, valign: "top", align: "left" }, text: "" } },
  ] });
pres.defineSlideMaster({ title: "SECTION", background: { color: HEX.lt2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.6, w: 11.7, h: 1.2, fontSize: 40, bold: true, color: C.accent1, valign: "bottom", align: "left" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.9, w: 11.7, h: 1.2, fontSize: 18, color: C.text1, valign: "top", align: "left" }, text: "" } },
  ],
  slideNumber: { x: 12.3, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent6 } });
pres.defineSlideMaster({ title: "CONTENT", background: { color: HEX.lt1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 30, bold: true, color: C.accent1, valign: "middle", align: "left" }, text: "" } },
    { text: { text: "SCH 국제학생 허브 · 최종 발표 2026-11-30", options: { x: 0.6, y: 6.95, w: 8, h: 0.3, fontSize: 10, color: C.accent6 } } },
  ],
  slideNumber: { x: 12.3, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent6 } });

// ---------- helpers ----------
let n = 0;
const id = (s) => `${s}-${++n}`;
function card(slide, x, y, w, h, fill = C.background2) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { type: "none" }, rectRadius: 0.12, objectName: id("card") });
}
function badge(slide, x, y, label, d = 0.55, fill = C.accent1, size = 16) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" }, objectName: id("badge") });
  slide.addText(label, { x, y, w: d, h: d, align: "center", valign: "middle", fontSize: size, bold: true, color: C.background1, margin: 0, isTextBox: true, objectName: id("badge-text") });
}
function text(slide, t, o) { slide.addText(t, Object.assign({ isTextBox: true, margin: 0, valign: "top", fontSize: 15, color: C.text1 }, o)); }
function stat(slide, x, y, w, big, label, color = C.accent1) {
  text(slide, big, { x, y, w, h: 0.95, fontSize: 44, bold: true, color, valign: "bottom", objectName: id("stat") });
  text(slide, label, { x, y: y + 1.0, w, h: 0.7, fontSize: 14, color: C.text1, objectName: id("stat-label") });
}
function content(section, title, notes) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  if (notes) s.addNotes(notes);
  return s;
}
const chartText = { catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt", legendFontFace: "+mn-lt",
  titleFontFace: "+mn-lt", catAxisLabelColor: "1B2333", valAxisLabelColor: "6B7385", dataLabelColor: "1B2333", legendColor: "1B2333",
  catAxisLabelFontSize: 14, valAxisLabelFontSize: 12, dataLabelFontSize: 13, legendFontSize: 13 };

// ================= 1. 개요 =================
pres.addSection({ title: "개요" });
let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "개요" });
s.addText("SCH 국제학생 허브", { placeholder: "title" });
s.addText("승인된 공식 자료로 답하는 다국어 AI 지원 서비스\n최종 발표 · 2026년 11월 30일", { placeholder: "body" });
s.addNotes("인사 후 한 문장으로 소개: 순천향대 외국인 유학생이 승인된 공식 자료를 근거로 5개 언어로 답을 받는 서비스입니다.");

s = content("개요", "유학생이 겪는 문제",
  "정보가 흩어져 있고 대부분 한국어이며, 틀리면 불이익이 큰 정보가 많다는 점을 강조합니다. 일반 챗봇은 출처 없이 숫자를 지어냅니다.");
const problems = [
  ["흩어진 정보", "비자·수강·기숙사·아르바이트 정보가 대학, 하이코리아, 정부 사이트에 나뉘어 있음"],
  ["한국어 위주 공지", "중요한 공지가 한국어로만 올라와 놓치기 쉬움"],
  ["틀리면 큰 불이익", "마감일, 수수료, 근무 시간처럼 숫자 하나가 체류에 영향"],
  ["일반 챗봇의 한계", "그럴듯한 숫자를 지어내고 출처를 보여 주지 않음"],
];
problems.forEach(([h, b], i) => {
  const x = 0.6 + (i % 2) * 6.15, y = 1.55 + Math.floor(i / 2) * 2.55;
  card(s, x, y, 5.95, 2.3);
  badge(s, x + 0.35, y + 0.35, String(i + 1));
  text(s, h, { x: x + 1.15, y: y + 0.35, w: 4.5, h: 0.55, fontSize: 20, bold: true, color: C.accent1, valign: "middle" });
  text(s, b, { x: x + 1.15, y: y + 1.0, w: 4.5, h: 1.1, fontSize: 15 });
});

s = content("개요", "목표와 설계 원칙",
  "모든 설계 결정은 다섯 가지 원칙에서 나옵니다. 특히 '사람이 검토하기 전에는 공개하지 않는다'는 원칙이 번역과 외부 정보 수집 전체에 적용됩니다.");
const goals = [
  ["승인된 자료만", "검토를 통과한 최신 문서만 검색되도록 데이터베이스에서 강제"],
  ["출처 표시", "모든 답변에 번호 인용, 누르면 원문으로 이동"],
  ["5개 언어", "한국어·영어·인도네시아어·베트남어·중국어로 질문하고 답변"],
  ["사람이 최종 결정", "번역 초안과 외부에서 찾은 정보는 검토자 승인 후에만 공개"],
  ["저비용 운영", "무료 호스팅, 일일 AI 한도, 학교 컴퓨터에 의존하지 않음"],
];
goals.forEach(([h, b], i) => {
  const y = 1.45 + i * 1.03;
  badge(s, 0.7, y + 0.12, String(i + 1), 0.6);
  text(s, h, { x: 1.55, y, w: 3.4, h: 0.85, fontSize: 20, bold: true, color: C.accent1, valign: "middle" });
  text(s, b, { x: 5.0, y, w: 7.7, h: 0.85, fontSize: 16, valign: "middle" });
});

// ================= 2. 시스템 =================
pres.addSection({ title: "시스템" });
s = pres.addSlide({ masterName: "SECTION", sectionTitle: "시스템" });
s.addText("시스템", { placeholder: "title" });
s.addText("구성 · RAG 파이프라인 · 화면 · AI 오피스 · 검토와 번역 · 관리와 비용", { placeholder: "body" });

s = content("시스템", "시스템 구성",
  "웹과 API는 Render 무료 요금제, 데이터는 Supabase입니다. 검색은 승인된 최신 문서만 보는 데이터베이스 뷰를 거칩니다. Gemini는 답변과 질문 재작성에 쓰이고, 학교 GPU는 운영에서 꺼져 있습니다.");
const box = (x, y, w, h, title, sub, fill = C.background2, tColor = C.accent1) => {
  card(s, x, y, w, h, fill);
  text(s, title, { x: x + 0.2, y: y + 0.12, w: w - 0.4, h: 0.45, fontSize: 16, bold: true, color: tColor, valign: "middle" });
  if (sub) text(s, sub, { x: x + 0.2, y: y + 0.58, w: w - 0.4, h: h - 0.68, fontSize: 13, color: tColor === C.background1 ? C.background1 : C.text1 });
};
box(0.6, 1.4, 4.2, 1.05, "학생·직원 브라우저", "5개 언어, 휴대전화 지원");
box(0.6, 2.85, 4.2, 1.05, "Next.js 웹 (Render)", "Supabase Auth 로그인");
box(0.6, 4.3, 4.2, 2.3, "FastAPI API (Render, 512 MB)", "공개 API · RAG 도우미 · AI 오피스 14개 창구 · 검토 · 관리자 · 백그라운드 작업자", C.accent1, C.background1);
box(5.4, 4.95, 3.6, 1.65, "Supabase PostgreSQL", "pgvector + 전문 검색 + 저장소. 검색은 승인·최신·유효 문서만 보는 뷰를 통해서만");
box(9.6, 1.4, 3.1, 1.6, "Gemini API", "3.6 Flash 답변, 3.5 Flash-Lite 재작성·대체, 일일 한도");
box(9.6, 3.3, 3.1, 1.25, "공식 웹사이트", "허용 목록, robots.txt 준수");
s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 9.6, y: 4.85, w: 3.1, h: 1.75, fill: { color: C.background1 }, line: { color: C.accent6, width: 1.25, dashType: "dash" }, rectRadius: 0.12, objectName: "gpu-box" });
text(s, "학교 GPU 작업자", { x: 9.8, y: 4.97, w: 2.7, h: 0.45, fontSize: 16, bold: true, color: C.accent6, valign: "middle" });
text(s, "TranslateGemma 12B 번역 초안. 운영에서는 꺼져 있음", { x: 9.8, y: 5.45, w: 2.7, h: 1.05, fontSize: 13, color: C.accent6 });
const arrow = (x1, y1, x2, y2) => s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001, flipH: x2 < x1, flipV: y2 < y1, line: { color: C.accent6, width: 1.5, endArrowType: "triangle" }, objectName: id("arrow") });
arrow(2.7, 2.45, 2.7, 2.85);
arrow(2.7, 3.9, 2.7, 4.3);
arrow(4.8, 5.75, 5.4, 5.75);
arrow(4.8, 4.45, 9.6, 2.2);
arrow(4.8, 4.6, 9.6, 3.95);

s = content("시스템", "RAG 파이프라인: 질문 하나가 답이 되기까지",
  "7단계입니다. 3단계까지는 근거를 찾는 과정, 4~6단계는 안전장치입니다. 모델이 쓸 수 없는 상황에서는 지어낸 답 대신 승인된 출처를 보여 줍니다.");
const steps = [
  ["질문 재작성", "독립 질문 + 영어·한국어 변형"], ["검색", "벡터 + 전문 검색, 승인 문서만"], ["근거 선택", "문서 4개 × 문단 3개"],
  ["안전 검사", "AI에게 내린 지시 문장 제거"], ["답변 생성", "Gemini, 번호 인용"], ["사후 검사", "출처 없는 숫자 제거, 인용 재지정"], ["대체 경로", "모델 장애 시 출처만 안내"],
];
steps.forEach(([h, b], i) => {
  const x = 0.6 + i * 1.77;
  card(s, x, 2.0, 1.62, 3.4);
  badge(s, x + 0.5, 2.25, String(i + 1), 0.62);
  text(s, h, { x: x + 0.1, y: 3.1, w: 1.42, h: 0.75, fontSize: 16, bold: true, color: C.accent1, align: "center", valign: "middle" });
  text(s, b, { x: x + 0.12, y: 3.95, w: 1.38, h: 1.3, fontSize: 13, align: "center" });
});
text(s, "검색은 데이터베이스 뷰가 강제: 승인 ∧ 최신 판 ∧ 취소·보관 아님 ∧ 출처 활성 ∧ 유효 기간 내", { x: 0.6, y: 5.8, w: 12.1, h: 0.5, fontSize: 15, color: C.accent1, bold: true });

s = content("시스템", "서비스 화면 (현재 운영 배포본)",
  "운영 사이트에서 2026년 11월 28일에 찍은 화면입니다. 지식 센터에는 승인된 문서만 보이며, 화면 위에 그 사실이 적혀 있습니다.");
s.addImage({ path: path.join(SHOTS, "home.png"), x: 0.6, y: 1.45, w: 5.95, h: 3.72, altText: "홈 화면: 질문 입력창과 지식 카테고리", objectName: "shot-home" });
s.addImage({ path: path.join(SHOTS, "knowledge.png"), x: 6.75, y: 1.45, w: 5.95, h: 3.72, altText: "지식 센터: 승인된 문서 목록", objectName: "shot-knowledge" });
text(s, "홈: 5개 언어 선택, 질문 입력, 주제별 지식 카테고리", { x: 0.6, y: 5.35, w: 5.95, h: 0.5, fontSize: 14 });
text(s, "지식 센터: 승인된 문서만, 출처·확인 날짜 표시", { x: 6.75, y: 5.35, w: 5.95, h: 0.5, fontSize: 14 });

s = content("시스템", "AI 오피스: 14개 전문 창구",
  "각 창구의 도구와 금지 행동은 서버가 정합니다. 창구는 사람이 요청할 때 일하며, 주간 자동 일정은 구현되어 있지만 운영에서는 꺼져 있다고 정직하게 말합니다.");
s.addImage({ path: path.join(SHOTS, "office.png"), x: 0.6, y: 1.4, w: 7.2, h: 4.5, altText: "AI 오피스: 14명의 캐릭터가 창구별로 배치된 화면", objectName: "shot-office" });
const desks = [["안내", "하나"], ["언어 지원", "민지·알렉스·사리·민·메이"], ["비자·출입국", "유나"], ["학사·TOPIK", "준·서"], ["장학·행사·취업", "레오·미아·다니엘"], ["모니터링·상담 연결", "로보·수민"]];
desks.forEach(([h, b], i) => {
  const y = 1.4 + i * 0.62;
  text(s, h, { x: 8.15, y, w: 2.3, h: 0.5, fontSize: 15, bold: true, color: C.accent1, valign: "middle" });
  text(s, b, { x: 10.45, y, w: 2.3, h: 0.5, fontSize: 14, valign: "middle" });
});
card(s, 8.15, 5.2, 4.55, 1.3, C.background2);
text(s, "운영: 요청이 있을 때 동작 · 주간 일정 꺼짐 · 찾은 정보는 사람이 승인해야 공개", { x: 8.35, y: 5.3, w: 4.15, h: 1.1, fontSize: 13, valign: "middle" });

s = content("시스템", "사람 검토와 공지 번역",
  "공지 번역은 Release 1에서 한국어·영어·인도네시아어만 초안을 만듭니다. 초안은 검토자가 승인하기 전까지 비공개입니다. 학교 GPU의 TranslateGemma 12B 평가 결과는 자동 검사 기준이며 사람 평가는 아직 없습니다.");
const flow = ["승인된 원문", "번역 초안", "자동 검사", "검토자 승인", "해당 언어로 공개"];
flow.forEach((t, i) => {
  const x = 0.6 + i * 2.48;
  card(s, x, 1.6, 2.2, 1.1, i === 3 ? C.accent2 : C.background2);
  text(s, t, { x: x + 0.1, y: 1.6, w: 2.0, h: 1.1, fontSize: 16, bold: true, color: C.text1, align: "center", valign: "middle" });
  if (i < flow.length - 1) s.addShape(pres.shapes.LINE, { x: x + 2.22, y: 2.15, w: 0.24, h: 0.001, line: { color: C.accent6, width: 1.5, endArrowType: "triangle" }, objectName: id("flow-arrow") });
});
stat(s, 0.6, 3.25, 3.8, "ko · en · id", "Release 1 공지 번역 언어\n(베트남어·중국어는 원문 또는 기존 승인 번역)");
stat(s, 4.75, 3.25, 3.8, "72건", "실제 공지 번역 평가(TranslateGemma 12B)\n날짜·금액·링크 모두 보존");
stat(s, 8.9, 3.25, 3.8, "1건", "자동 검사로 찾은 사실 오류\n(사람 품질 평가는 아직 없음)", C.accent4);
text(s, "학교 GPU 번역 작업자는 운영에서 꺼져 있으며, 운영은 학교 컴퓨터에 의존하지 않습니다.", { x: 0.6, y: 5.75, w: 12.1, h: 0.5, fontSize: 15, color: C.accent1, bold: true });

s = content("시스템", "관리자 기능과 비용 안전",
  "답변 하나에 표준 가격 기준 약 0.012달러가 듭니다. 기존 기본값 하루 1,500회는 예산에 비해 너무 높아서 최종 릴리스에서 하루 60회로 낮췄습니다. 일일 한도는 금액 한도가 아니므로 Google 예산 알림도 함께 설정해야 합니다.");
const admin = [["검토 대기열", "문서·공지·번역·발견 항목 승인 또는 반려"], ["출처 관리", "공식 출처 카탈로그, 실패 시 자동 보류와 알림"], ["에이전트 작업", "작업 기록, 일시정지, 재실행 (학생 글은 비공개)"], ["AI 사용량", "일일 한도, 토큰 사용량, 긴급 정지 (마이그레이션 0018)"]];
admin.forEach(([h, b], i) => {
  const y = 1.45 + i * 1.25;
  badge(s, 0.7, y + 0.15, String(i + 1));
  text(s, h, { x: 1.45, y, w: 5.2, h: 0.5, fontSize: 18, bold: true, color: C.accent1, valign: "middle" });
  text(s, b, { x: 1.45, y: y + 0.5, w: 5.2, h: 0.6, fontSize: 14 });
});
card(s, 7.2, 1.45, 5.5, 4.85);
stat(s, 7.55, 1.6, 4.9, "$0.012", "답변 1회 예상 비용\n(Gemini 3.6 Flash 표준 가격, 입력 약 5,000 토큰)");
stat(s, 7.55, 3.75, 4.9, "1,500 → 60", "하루 생성 답변 기본 한도\n(학생 1명 20회, 비로그인 10회)", C.accent2);

// ================= 3. 평가 =================
pres.addSection({ title: "평가" });
s = pres.addSlide({ masterName: "SECTION", sectionTitle: "평가" });
s.addText("평가", { placeholder: "title" });
s.addText("검색 · 질문 재작성 · 답변 · 안전성 · 테스트", { placeholder: "body" });

s = content("평가", "평가 방법",
  "평가용 TEST 세트는 실험을 시작하기 전에 고정했고 마지막에 한 번만 사용했습니다. 같은 질문의 다섯 언어 버전은 독립적이지 않아서 정보 요구 단위로 신뢰구간을 계산했습니다. 라벨은 AI가 작성했고 사람이 검토하지 않았다는 점을 반드시 밝힙니다.");
const sets = [["100문항", "개발·검증 세트\n20개 상황 × 5개 언어"], ["210문항", "TEST 세트(실험 전 고정)\n42개 정보 요구 × 5개 언어"], ["35문항", "답이 없는 질문 세트\n(근거 판단 조정용)"]];
sets.forEach(([b, l], i) => stat(s, 0.6 + i * 4.15, 1.4, 3.8, b, l));
const method = [
  "정답 근거 문장(57개)을 코퍼스 원문과 자동 대조, 관련 문서 0 / 1 / 2 등급",
  "실제 PostgreSQL + pgvector로 재현 (첫 정답 순위 일치 208 / 210)",
  "정보 요구 단위 부트스트랩 95 % 신뢰구간 (5개 언어 버전은 독립 아님)",
  "개발 세트에서 조정 → 검증 세트에서 미리 정한 규칙으로 선택 → TEST 한 번",
  "주의: 라벨은 AI 작성·사람 미검증, 답변은 Gemini가 아닌 로컬 대리 모델(Qwen 2.5 7B)",
];
s.addText(method.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < method.length - 1, color: i === method.length - 1 ? C.accent4 : C.text1, bold: i === method.length - 1 } })),
  { x: 0.6, y: 3.45, w: 12.1, h: 3.2, fontSize: 16, paraSpaceAfter: 6, valign: "top", isTextBox: true, objectName: "method-list" });

s = content("평가", "검색 성능: 하이브리드 검색이 벡터 검색보다 정확",
  "검증 세트 100문항 결과입니다. 하이브리드는 정답 문서를 10위 안에 94 % 찾습니다. 이것은 검색 지표이고 최종 답의 정확도와는 다릅니다.");
s.addChart(pres.charts.BAR, [
  { name: "벡터 검색만", labels: ["Recall@1", "Recall@10", "MRR"], values: [0.50, 0.83, 0.631] },
  { name: "하이브리드 (운영 방식)", labels: ["Recall@1", "Recall@10", "MRR"], values: [0.63, 0.94, 0.736] },
], Object.assign({ x: 0.6, y: 1.4, w: 7.6, h: 5.2, barDir: "col", barGapWidthPct: 60, chartColors: ["9AA3B5", "1F3A8A"],
  showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00", valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelFormatCode: "0.0",
  valGridLine: { color: "E3E7EF", size: 1 }, catGridLine: { style: "none" }, showLegend: true, legendPos: "b", showTitle: false, objectName: "chart-retrieval" }, chartText));
card(s, 8.6, 1.4, 4.1, 5.2);
stat(s, 8.9, 1.6, 3.6, "0.94", "정답 문서가 10위 안에 있는 비율\n(벡터 검색만 0.83)");
stat(s, 8.9, 3.6, 3.6, "+0.096", "MRR 향상(실제 PostgreSQL), 95 % 구간\n+0.026 ~ +0.172 (정보 요구 단위)", C.accent3);

s = content("평가", "질문 재작성이 다국어 검색의 핵심",
  "TEST 세트 210문항, 고정 후 한 번만 실행한 결과입니다. 질문을 영어·한국어로 다시 써서 함께 검색하면 정답 근거 문단이 답변 모델에 전달되는 비율이 64 %에서 86 %로 오릅니다. 다른 언어로 된 근거에서 효과가 가장 큽니다.");
s.addChart(pres.charts.BAR, [
  { name: "재작성 없음", labels: ["전체 질문", "다른 언어 근거", "같은 언어 근거"], values: [64.2, 57.9, 89.5] },
  { name: "재작성 사용", labels: ["전체 질문", "다른 언어 근거", "같은 언어 근거"], values: [85.8, 84.2, 92.1] },
], Object.assign({ x: 0.6, y: 1.4, w: 7.6, h: 5.2, barDir: "col", barGapWidthPct: 60, chartColors: ["9AA3B5", "1F3A8A"],
  showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", valAxisMinVal: 0, valAxisMaxVal: 100, valAxisLabelFormatCode: "0",
  valAxisTitle: "정답 근거 문단이 전달된 비율 (%)", showValAxisTitle: true, valAxisTitleFontFace: "+mn-lt", valAxisTitleFontSize: 12, valAxisTitleColor: "6B7385",
  valGridLine: { color: "E3E7EF", size: 1 }, catGridLine: { style: "none" }, showLegend: true, legendPos: "b", objectName: "chart-rewrite" }, chartText));
card(s, 8.6, 1.4, 4.1, 5.2);
stat(s, 8.9, 1.6, 3.6, "+21.6 %p", "전체 효과, 95 % 구간\n+14.7 ~ +28.4 %p", C.accent3);
stat(s, 8.9, 3.6, 3.6, "58 → 84 %", "다른 언어 근거 질문\n(예: 영어 질문 → 한국어 공지)");
text(s, "운영은 이미 Gemini로 재작성 → 재작성 실패 시 품질 저하를 감시", { x: 8.9, y: 5.55, w: 3.6, h: 0.9, fontSize: 13, bold: true, color: C.accent4 });

s = content("평가", "답변 평가: 검색이 숫자를 맞게 만든다",
  "로컬 대리 모델 Qwen 2.5 7B로 측정한 값이며 Gemini 정확도가 아닙니다. 같은 모델에 출처 없이 물으면 정답 수치는 2 %뿐이고, 출처에 없는 수수료를 지어냅니다. 검색을 쓰면 출처에 없는 질문에서 지어낸 금액이 없었습니다.");
const ans = [["59 %", "정답 수치 포함 (검색 사용)", C.accent1], ["2 %", "정답 수치 포함 (출처 없이)", C.accent4], ["0 / 20", "출처에 없는 질문에 지어낸 금액\n(출처 없이: 5개 중 2개)", C.accent3], ["73 %", "인용한 문단에 정답 근거 포함", C.accent1]];
ans.forEach(([b, l, c], i) => { const x = 0.6 + (i % 2) * 6.15, y = 1.45 + Math.floor(i / 2) * 2.35; card(s, x, y, 5.95, 2.1); stat(s, x + 0.35, y + 0.05, 5.3, b, l, c); });
text(s, "로컬 대리 모델(Qwen 2.5 7B) 결과 · Gemini 정확도는 아직 측정하지 않음 · 라벨은 AI 작성", { x: 0.6, y: 6.25, w: 12.1, h: 0.45, fontSize: 14, bold: true, color: C.accent4 });

s = content("평가", "발견하고 고친 것, 채택하지 않은 것",
  "연구에서 가장 중요한 결과 중 하나는 채택하지 않은 두 가지입니다. 개발 세트에서는 좋아 보였지만 고정된 TEST 세트에서 나빠졌기 때문에 운영에 넣지 않았습니다.");
const cols = [
  ["발견하고 고친 것", C.accent3, ["청크 분할 버그: 승인 문서 본문 13 % 검색 불가(가이드북 58 %) → v2 수정, 스테이징 재색인 후 적용", "프롬프트 인젝션: 차단 전 7 / 11 → 후 11 / 11", "다른 출처에 붙은 숫자 7 / 112 → 올바른 출처로 재지정"]],
  ["채택하지 않은 것", C.accent4, ["긴 가이드북 감점: 개발·검증 세트에서 향상, TEST에서 가이드북이 정답인 질문 MRR −0.112", "근거 부족 시 자동 거절: 답할 수 있는 질문의 18 %까지 거절 → 기록 모드로만 사용"]],
  ["이유", C.accent1, ["개발 세트 라벨이 가이드북 정답을 충분히 인정하지 않았음", "실험 전에 고정한 TEST 세트가 이것을 드러냄", "따라서 운영에는 검증된 변경만 넣음"]],
];
cols.forEach(([h, c, items], i) => {
  const x = 0.6 + i * 4.1;
  card(s, x, 1.45, 3.9, 5.15);
  text(s, h, { x: x + 0.3, y: 1.6, w: 3.3, h: 0.55, fontSize: 19, bold: true, color: c, valign: "middle" });
  s.addText(items.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < items.length - 1 } })), { x: x + 0.3, y: 2.3, w: 3.35, h: 4.1, fontSize: 16, paraSpaceAfter: 10, valign: "top", color: C.text1, isTextBox: true, objectName: id("col-list") });
});

s = content("평가", "안전성과 테스트",
  "승인되지 않은 문서가 답변에 쓰이지 않는지 실제 PostgreSQL에서 8가지 상태로 확인했습니다. 테스트 수치는 모두 학교 워크스테이션의 로컬 결과이며, 운영 환경에서는 읽기 전용 확인만 했습니다.");
const tests = [["1,072", "백엔드 단위 테스트 통과"], ["100", "PostgreSQL 통합 테스트 통과"], ["261", "웹 단위 테스트 통과"], ["15 / 15", "SQL 동작 검사"], [BROWSER, "브라우저 여정 검사(로컬)\n시간 초과 1건 → 재실행 15 / 15"], ["8 / 8", "미승인·이전 판·만료 등 차단 상태"]];
tests.forEach(([b, l], i) => { const x = 0.6 + (i % 3) * 4.1, y = 1.45 + Math.floor(i / 3) * 2.35; card(s, x, y, 3.9, 2.1); stat(s, x + 0.3, y + 0.05, 3.3, b, l); });
text(s, "모두 로컬 검증 · 운영 사이트는 공개 화면과 질문 1건만 읽기 전용으로 확인", { x: 0.6, y: 6.25, w: 12.1, h: 0.45, fontSize: 14, bold: true, color: C.accent6 });

// ================= 4. 한계와 계획 =================
pres.addSection({ title: "한계와 계획" });
s = pres.addSlide({ masterName: "SECTION", sectionTitle: "한계와 계획" });
s.addText("한계와 향후 과제", { placeholder: "title" });
s.addText("측정하지 못한 것과 다음에 할 일을 정직하게", { placeholder: "body" });

s = content("한계와 계획", "현재 한계",
  "가장 큰 한계는 사람이 검증한 평가가 없다는 점과 Gemini 답변 정확도를 아직 측정하지 못했다는 점입니다. 측정 방법과 비용은 준비되어 있습니다.");
const lim = [
  ["평가", "라벨은 AI 작성, 사람 검증 없음 · Gemini 정확도 미측정(키·유료 실행 승인 필요)", "높음"],
  ["다국어", "질문 재작성이 실패하면 다른 언어 질문의 근거 전달 58 %", "중간"],
  ["답변", "숫자는 맞지만 대상이 틀린 답 · 출처끼리 다를 때 알리지 않음", "중간"],
  ["검색", "긴 문서 속 규정·각주 문단을 놓침 · 청크 수정(v2) 운영 미적용", "중간"],
  ["번역", "공지 번역은 한·영·인니만 · 원어민 품질 평가 없음", "중간"],
  ["에이전트", "주간 자동 일정 꺼짐 · 외부 채용 API 키·권한 없음", "낮음"],
  ["인프라", "512 MB 메모리 여유 적음 · 첫 접속 약 45초 · 무료 DB는 자동 백업 없음", "중간"],
];
const rows = [[{ text: "분야", options: { bold: true, color: C.background1, fill: { color: C.accent1 } } }, { text: "한계", options: { bold: true, color: C.background1, fill: { color: C.accent1 } } }, { text: "중요도", options: { bold: true, color: C.background1, fill: { color: C.accent1 }, align: "center" } }]]
  .concat(lim.map(([a, b, c]) => [{ text: a, options: { bold: true, color: C.accent1 } }, { text: b }, { text: c, options: { align: "center", bold: true, color: c === "높음" ? C.accent4 : C.text1 } }]));
s.addTable(rows, { x: 0.6, y: 1.4, w: 12.1, colW: [1.8, 8.8, 1.5], fontSize: 14, color: C.text1, border: { type: "solid", pt: 0.75, color: "D7DCE6" }, valign: "middle", rowH: 0.62, objectName: "limits-table" });

s = content("한계와 계획", "향후 과제",
  "발표 직후에는 운영 안정화, 다음 학기에는 사람이 검증한 평가와 Gemini 품질 측정, 장기적으로는 번역 언어 확대와 지속적인 평가 체계입니다.");
const stages = [
  ["A", "발표 직후", ["운영 모니터링과 버그 수정", "Gemini 비용 확인, 예산 알림", "주간 DB 백업", "실패 로그 검토"]],
  ["B", "다음 학기", ["사람이 검증한 평가 세트", "Gemini 답변 품질 측정", "청크 v2 스테이징 재색인", "출처 충돌 안내, 주간 일정 하나씩"]],
  ["C", "장기", ["공지 번역 언어 확대", "상시 번역 서버", "학생 피드백", "지속적 RAG 평가(CI)"]],
];
stages.forEach(([k, h, items], i) => {
  const x = 0.6 + i * 4.1;
  card(s, x, 1.45, 3.9, 4.0);
  badge(s, x + 0.3, 1.7, k, 0.65, i === 0 ? C.accent2 : C.accent1, 20);
  text(s, h, { x: x + 1.15, y: 1.7, w: 2.5, h: 0.65, fontSize: 20, bold: true, color: C.accent1, valign: "middle" });
  s.addText(items.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < items.length - 1 } })), { x: x + 0.3, y: 2.65, w: 3.35, h: 2.6, fontSize: 16, paraSpaceAfter: 10, valign: "top", color: C.text1, isTextBox: true, objectName: id("stage-list") });
});

text(s, "우선순위·의존성·수용 기준: docs/final-release/FUTURE-IMPROVEMENTS.md", { x: 0.6, y: 5.75, w: 12.1, h: 0.5, fontSize: 14, color: C.accent6 });

s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "한계와 계획" });
s.addText("정리", { placeholder: "title" });
s.addText("승인된 자료만, 출처와 함께, 5개 언어로\n질문 재작성으로 다국어 근거 전달 64 % → 86 %\n측정하지 못한 것은 측정하지 못했다고 말하기\n감사합니다", { placeholder: "body" });
s.addNotes("세 가지를 다시 말하고 마칩니다. 질문을 받을 때 Gemini 정확도와 사람 검증은 아직 측정하지 않았다고 정확히 답합니다.");

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();

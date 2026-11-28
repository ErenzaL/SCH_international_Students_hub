# Monthly operating cost

Prices: Google's official Gemini API pricing page, read 2026-11-27 (paid tier, USD per 1 M tokens, output **includes thinking tokens**):

| Model | Input | Output | Note |
|---|---|---|---|
| `gemini-3.6-flash` (current primary) | 0.75 until 2026-12-31, **1.50 from 2027-01-01** | 3.75 until 2026-12-31, **7.50 from 2027-01-01** | free tier also exists |
| `gemini-3.5-flash-lite` (current fallback, query rewriting) | 0.30 | 2.50 | free tier also exists |

These are list prices, not your invoice. Check Google AI Studio / Cloud Billing for the real charges; prices change.

## 1. Measured request sizes (this branch, `rag_lab.py`, 95 answers, local tokenizer)

| Call per answer | Model in production | Input tokens | Output tokens |
|---|---|---|---|
| query rewrite (fast) | Flash-Lite | 340 | 72 |
| answer (stream) | Flash (primary) | 3,127 | 74 |
| second look (verify) | local model only — **not** sent to Gemini | 191 | 23 |

The synthetic answers are short. Real answers are longer, and Gemini adds thinking tokens at `GEMINI_THINKING_LEVEL=low` (not measured
here). Gemini counts tokens differently from the local tokenizer (estimate ±30 %, more for Korean).

## 2. Cost per chatbot answer

| Scenario | Flash answer | 2026 price | 2027 price |
|---|---|---|---|
| A: measured sizes, no thinking | 3,127 in / 74 out | **US$0.0029** | **US$0.0055** |
| B: conservative, 300 visible + 500 thinking tokens | 3,127 in / 800 out | **US$0.0056** | **US$0.0110** |
| B with Flash-Lite as primary | 3,127 in / 800 out | US$0.0032 | US$0.0032 |

(each includes the Flash-Lite rewrite: about US$0.0003)

The owner's capped comparison run (FINAL-SETUP-CHECKLIST 1.4: 95 answers once) ≈ 0.33 M input + 0.014 M output tokens + thinking ≈
**US$0.28–0.46** at the 2026 price.

## 3. Monthly scenarios (chat)

| Use | Answers / month | A, 2027 | B, 2027 | B, Flash-Lite primary |
|---|---|---|---|---|
| low (pilot) | 300 | US$1.7 | US$3.3 | US$1.0 |
| moderate | 3,000 | US$17 | US$33 | US$10 |
| high | 15,000 | US$83 | US$165 | US$48 |
| **ceiling of today's default cap** (`AI_DAILY_LIMIT_GLOBAL=1500` × 30) | 45,000 | US$250 | **US$495** | US$144 |

**Finding:** the code bounds spending, but the default global cap is far above a student project budget. Set the cap from your budget:

    AI_DAILY_LIMIT_GLOBAL ≈ monthly budget in USD / (30 × cost per answer)
    e.g. US$5 / (30 × 0.011) ≈ 15 answers a day;  US$20 → ≈ 60 a day (scenario B, 2027 price)

Beyond the cap students still get the cited sources (no model call). Per-user (150) and per-client (40) daily caps stay as they are.

## 4. Background AI

| Work | Model | Size | Cost |
|---|---|---|---|
| Announcement drafts on the school GPU (TranslateGemma 12B) | local | ~1,600 in / ~600 out per draft | US$0 (university electricity, ≈ 200 W while running; minutes per week) |
| The same drafts by Gemini when the GPU worker is off (`TRANSLATION_MODEL` empty = the chat models) | Flash | ~1,600 / ~600 per draft | ≈ US$0.007 per draft (2027); 2 drafts × 40 notices ≈ **US$0.55 / month** |
| … with `TRANSLATION_MODEL=gemini-3.5-flash-lite` | Flash-Lite | same | ≈ US$0.002 per draft ≈ US$0.16 / month |
| Weekly discovery (7 desks) | none by default (`summarize_new=false`) | parsing, dedup, deadlines are code | US$0 |
| Optional AI summaries of discoveries | Flash | per new item | off; bounded by `LLM_BACKGROUND_DAILY_ATTEMPTS` (150/day) and optional `LLM_BACKGROUND_DAILY_USD_LIMIT` |

## 5. Hosting and other services

| Service | Plan | Cost |
|---|---|---|
| Render web + API | free (750 instance hours / month per workspace, sleeps after 15 min) | US$0 |
| Supabase | free (500 MB database; ~35 KB per 1,000 indexed characters) | US$0 |
| Embeddings | local ONNX model inside the API | US$0 |
| Work24, data.go.kr, Saramin APIs | free registrations (limits per provider) | US$0 |
| Google Search API | not used (closed to new customers, ends 2027-01-01) | – |

## 6. Safeguards to set before activation

1. Google Cloud budget alert on the key's project (the only real cap).
2. `AI_DAILY_LIMIT_GLOBAL` from §3; review weekly in Admin → Settings → AI usage.
3. `LLM_PRICES` so the admin page shows estimated cost; optionally `LLM_BACKGROUND_DAILY_USD_LIMIT`.
4. Migration 0018 so budgets survive the free plan's sleep/restart cycle.
5. `TRANSLATION_MODEL=gemini-3.5-flash-lite` if Gemini ever translates.
6. Emergency stop: Admin → Settings → AI usage → Stop background AI (or `AI_BACKGROUND_STOP=true`).

The earlier KRW 8,000 payment is not a spending limit: Google bills usage; only a budget alert or a removed key stops charges.

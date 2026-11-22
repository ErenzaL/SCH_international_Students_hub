# Multilingual system (ko · en · id · vi · zh-CN)

The interface, the Knowledge Center articles, the assistant and notifications follow the student's language. The
**original document stays authoritative**: translations are separate, version-linked rows that are shown to
students only after a Global Supporter assigned to that language approved them.

## Language preference

* Sign-up requires a preferred language (`profiles.preferred_language`, `preferred_language_confirmed`); it can be
  changed in Account settings (`PATCH /api/v1/me`).
* After sign-in the site language is set from the profile on that device (cookie `NEXT_LOCALE`), so the profile
  language is the default everywhere.
* The header language switcher and the article "Read in" selector change only what is shown — never the profile.
  Assistant conversations can switch language per message (`language` on the message) without changing the profile.

## Interface localization

All student **and** admin screens use next-intl catalogs in `apps/web/src/messages/{en,ko,id,vi,zh-CN}.json`
(1,465 keys each, English is the merge base). Dates and numbers are formatted with the active locale
(`formatDate`, `formatDateTime`, `Intl.RelativeTimeFormat`). `messages.test.ts` fails if any locale misses a key or a
key is used in code but missing in English.

## Knowledge document translations (migration 0011)

| Table | Purpose |
|---|---|
| `document_translations` | one row per (original **version**, language): title, headings, body, status, provider/model, warnings, reviewer, approval time, `source_content_hash`, `source_version_number`, `is_outdated`, `previous_translation_id` |
| `document_translation_revisions` | append-only history: generate / save / submit / approve / reject / request_changes / outdated / restored |

Statuses: `todo` → `machine_draft` (AI, unreviewed) / `draft` (human) → `in_review` → `human_approved`
(or `changes_requested`, `rejected`). Only `human_approved`, not outdated, made from the document's **current**
approved version is public.

### Workflow

1. An original version is approved → indexed → activated (existing RAG sync). Activation calls
   `DocumentTranslationService.sync()`: rows of older versions are marked **outdated** (kept for audit), new `todo`
   rows are created for every other language, linked to the previous translation, and the language team is notified.
2. **AI draft** (optional): Admin → Documents → Translations, or the editor, queues a durable `translate_document`
   job per language on the existing job queue (worker claims with `SKIP LOCKED`, retries transient provider errors).
   The draft is stored as `machine_draft` with provider/model and automated preservation checks (URLs, e-mails,
   phone numbers, visa codes, numbers/dates/fees, heading and table-row counts). A failed draft never affects the
   original, which stays searchable.
3. A Global Supporter with the language edits / saves / submits; a reviewer for the language approves (must
   confirm "checked against the original"), requests a correction or rejects. Version comparison shows what changed
   in the original and the previous translation vs. the draft.
4. A rollback to an older original makes the translations made from exactly that version valid again.

### Permissions (FastAPI + database)

* Editing: `support` or `review` permission for the language (`supporter_languages`). Approve / reject / request
  changes: `review` (or team lead / super admin). Plain admins need an assignment, but may queue AI drafts.
* The trigger `guard_document_translation` re-checks approval in the database: reviewer must hold `review` for the
  language, the row must not be outdated and must belong to the document's current approved version.
* RLS: anon/students can read only approved, current translations of public documents; staff read drafts only of
  languages they are assigned to; no client writes.

### Original-language correction

Content-based detection (`app/services/language_detect.py`) sets the original language of new documents (HTML
`lang` attributes on Korean government sites are often `ko` on English pages). Admins can correct a label in the
Translations tab (`PATCH /admin/documents/{id}/language`); only the label changes. Migration 0011 relabels
originals tagged `ko` whose approved text contains no Hangul and is clearly English (audited as
`document.language_changed`).

## Assistant (multilingual RAG)

* The vector index contains **originals only** (multilingual-E5 embeddings). Translations are not embedded, so
  citations always point to the authoritative original and there are no duplicate versions.
* With `LLM_PROVIDER=anthropic` the assistant answers in the conversation language from the retrieved approved
  passages only, with `[n]` citations; it copies dates/fees/codes exactly, flags possibly outdated passages, keeps
  general explanations separate from official rules, and never decides individual cases. If the model reports
  insufficient evidence, cites nothing valid, or the provider fails, the assistant falls back to showing the
  approved passages with a localized framing sentence and offers a Global Supporter.
* Without a provider (`LLM_PROVIDER=none`) the evidence-only replies continue to work.

## Provider configuration (backend environment)

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `none` | `anthropic` enables answer generation and AI translation drafts |
| `LLM_API_KEY` | – | Anthropic API key (or set `ANTHROPIC_API_KEY`) — Render secret, never in the frontend |
| `LLM_MODEL` | `claude-opus-5-5` | |
| `LLM_EFFORT` | `medium` | `low`–`max` |
| `TRANSLATION_CHUNK_CHARS` | `6000` | documents are translated in chunks |
| `AUTO_TRANSLATE_DOCUMENTS` | `false` | queue AI drafts automatically when a new original version is activated |
| `PUBLIC_MACHINE_TRANSLATIONS` | `false` | show unreviewed AI drafts to students, clearly labelled as machine translation |

## Retrieval evaluation per language

`scripts/eval_multilingual_retrieval.py` indexes 8 evaluation-fixture documents (4 English originals, 4 Korean
originals) with the production code path and the real `multilingual-e5-small` int8 ONNX
model, and asks each topic in all five languages (40 queries). Results (2026-11-22):

| lang | vector R@1 | vector R@3 | vector MRR | hybrid R@1 | hybrid R@3 | hybrid MRR |
|---|---|---|---|---|---|---|
| ko | 0.625 | 0.750 | 0.738 | 0.500 | 0.500 | 0.600 |
| en | 0.625 | 0.875 | 0.754 | 0.625 | 0.750 | 0.723 |
| id | 0.875 | 0.875 | 0.875 | 0.875 | 0.875 | 0.875 |
| vi | 1.000 | 1.000 | 1.000 | 0.750 | 1.000 | 0.854 |
| zh-CN | 0.875 | 0.875 | 0.875 | 0.750 | 0.875 | 0.812 |

Misses are mostly cross-language (Korean query → English original, English/Indonesian query → Korean original);
the keyword half of hybrid search lowers Korean results. Against production (`--api`) the Study in Korea article
is the top result for the query in every language (only one public document exists, so that run is a smoke test).
Improvement options, not yet enabled: LLM query translation into the corpus languages before retrieval, a
vector-weighted fusion for cross-language queries, a larger E5 model (memory-bound on the 512 MB instance).

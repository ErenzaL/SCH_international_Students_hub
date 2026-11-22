# Language-based student support, AI history and translation review

## Data and privacy model
| Data | Table | Who can read (API + RLS) |
|---|---|---|
| AI conversations / messages | `ai_conversations`, `ai_messages` | the student only (not supporters, not admins, not super admins) |
| Support request (summary, shared excerpt, thread) | `support_tickets`, `support_ticket_messages` | the student; the **current** assignee; team leads of the ticket's language; super admins |
| Queue entry (number, subject, priority, time) | `support_tickets` via `/support/inbox?view=queue` | supporters of that language (metadata only, no content) |
| Assignment history | `support_ticket_assignments` | the assignee, team leads of the language |
| Notifications | `user_notifications` | the owner only (also for Realtime) |
| Team permissions | `supporter_languages` (+ `can_support`, `can_review_translations`, `is_team_lead`) | managed by super admins only |

* Private student data never enters the RAG tables (`document_*`) and is never embedded.
* A handoff copies **only** the messages the student selected, after explicit consent (`consent_at`). The student can
  withdraw the excerpt later (`withdraw-context`). Private conversations cannot be shared.
* Plain `admin` accounts have no support or translation access without a language assignment; `super_admin` is global.
* Permissions require a staff role at request time, so a demotion revokes access immediately; their open tickets
  return to the queue. Reassignment revokes the previous assignee at once (`assigned_to` is the only grant).
* Probing: wrong-language or unrelated users get the same 404 as for a missing ticket. RLS helpers that take a user
  id are server-only; clients only get caller-scoped wrappers (`my_language_permission`, `can_i_view_ticket`).
* Audit (`audit_log`): ticket create/assign/transfer/accept/reply/resolve/reopen/escalate/feedback/context-withdrawn,
  every staff read of ticket content (`ticket.view`), team changes (`team.update`, with before/after), role changes,
  profile language changes, all translation actions. Message bodies are never written to logs or audit details.
* Retention: AI conversations inactive for `CONVERSATION_RETENTION_DAYS` (365) and resolved tickets older than
  `SUPPORT_RETENTION_DAYS` (365) are deleted by the daily scheduler call (`/internal/sync/run-due`) or
  `python -m app.cli purge-expired`. Students can delete conversations at any time (hard delete).

## Routing
`route_support_ticket()` (SQL, row lock + per-language advisory lock) assigns a `waiting` ticket to the available
supporter of **that language** with the fewest active tickets (below `max_active_tickets`), then the one assigned
longest ago. Nobody available → the ticket stays `waiting`, the student is told, the language's supporters see it in
their queue, and team leads (or super admins when a language has no lead) are notified. Tickets are never moved to
another language automatically; transfers to a supporter without that language are refused by the database.
Changing the preferred language affects only new tickets. Claiming from the queue uses `assign_support_ticket(...,
p_expect_waiting=true)`, so two supporters can never both get the same ticket (the second gets 409).

Statuses: `waiting → assigned → open ⇄ waiting_for_student → resolved` (reopen → `open`, or `waiting` if unassigned).

## AI assistant
Answer generation (LLM) is not enabled. Replies contain approved passages with citations and a short framing
sentence in the conversation language, distinguish general guidance from individual decisions, and offer a Global
Supporter when there is no evidence, the student asks for a person, the question depends on their personal case, or
they dispute an answer. Nothing claims a human joined until a supporter accepts the ticket (a system message
"A Global Supporter joined the conversation" is posted on accept). Remaining LLM work: generate grounded answers in
the conversation language behind `LLMProvider`, with citations restricted to retrieved passages.

## Translation review
Per language: `todo` (created when the original is published) → draft (`machine_draft`) → `in_review` →
`human_approved` (published for that language only) or `changes_requested` / `rejected`. Approving requires the
`review` permission for the language, a published original, `original_verified=true`, and a translation made from the
current original (`source_content_hash`). When the original changes, translations become `is_outdated`, disappear
from the public page and must be updated and re-approved. Every action is a row in `translation_revisions`.
"Copy for KakaoTalk" returns plain text for approved, current translations only; nothing is sent automatically.

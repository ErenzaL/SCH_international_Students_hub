# AI Office: character-specific workspaces

Each staff member in the AI Office opens a workspace that matches their job. Only Hana and the five
language supporters open a chat first. The others open a service desk, a discovery list, a monitoring
desk or a request form.

This is a presentation layer on top of the existing agent system. It adds no new tables, chatbot
backend, LLM provider or crawling.

## Character-to-interface mapping

The backend registry defines the mapping (`AgentDefinition.interface` in
`backend/app/services/agents/registry.py`). `GET /api/v1/agents` returns it for each viewer, with the
admin tabs and actions removed for everyone else.

| Character | Agent | Interface | Default view | Tabs (admins also get Review and Sources) |
|---|---|---|---|---|
| Hana | `reception` | CHAT | chat | chat, tasks, desks, about |
| Minji, Alex, Sari, Minh, Mei | `supporter-*` | CHAT | chat | chat, tasks, about |
| Yuna | `immigration` | SERVICE (hybrid) | checklists | checklists, chat, guides, tasks, about |
| Joon | `academic` | SERVICE | procedures | procedures, notices, guides, chat, tasks, about |
| Seo | `topik` | SERVICE | topik | topik, guides, chat, tasks, about |
| Leo | `scholarship` | DISCOVERY | opportunities | opportunities, tasks, chat, about, **review, sources** |
| Mia | `events` | DISCOVERY | events | events, tasks, chat, about |
| Daniel | `career` | DISCOVERY | careers | careers, guides, tasks, chat, about |
| Robo | `announcement` | MONITORING | monitoring | monitoring, notices, tasks, about, **review, sources** |
| Sumin | `support-coordinator` | TASK_WORKSPACE | request | request, requests, chat, about |

Each interface also lists:
- `capabilities`, shown in "What I can do";
- `data_sources`, where the shown data comes from;
- `task_actions`, the agent's backend actions shown as buttons;
- `allowed_user_roles`.

The frontend (`apps/web/src/features/ai-office/workspace/index.tsx`) only maps a view id to a
component. It never grants anything. Until the directory loads, or if it can't, the panel falls back
to the earlier chat-first layout.

## What each workspace shows (all real data)

### Leo: scholarships and opportunities

Leo combines two sources:
- `scholarship_search`: published Hub notices and approved Knowledge Center guides;
- `opportunity_search`: official-site notices that an admin sent to review and the Knowledge Center
  approved.

The list has type filters, search and an "include closed" option, and is sorted by soonest deadline.
Each card shows:
- the verification label;
- deadlines and eligibility quoted from the source;
- the approved Hub document and the official page;
- application links;
- the last check time.

"Open" appears only when the backend derived it from the source. Students can also see their own
background checks.

### Robo: announcement monitoring

- **Status:** the watched official websites with OK, "Needs attention" or "Not checked yet";
  whether a check is running now; the last check and last success; and whether automatic checks are
  on, off, or switched on here but off on the server.
- **Digest:** the student's own "what changed" digest.
- **Recently published:** the latest published announcements.
- **Activity timeline:** built from stored timestamps only.

### Mia: events

Published announcements that have an event date or deadline, filtered by upcoming or past and by
category. Each opens an inline detail view (reviewed or labelled machine translation, both dates, and
links to the Hub notice and the official notice). Registration is never called "open".

### Daniel: careers

- Published career notices and guides.
- Job postings from official sites, reviewed and approved only.
- A clear statement that external job search is not connected (the `official_web_search` tool is
  unavailable).
- The work-permission reminder.
- The student's own career results.

### Yuna, Joon and Seo: service desks

- **Yuna and Joon:** procedure topics are the agent's backend checklist actions (Joon gained leave of
  absence and graduation, both on the existing `academic_checklist` tool). Each result is quoted from
  approved guides.
- **Yuna** also keeps the chat one tab away.
- **Joon** also shows the latest university notices.
- **Seo** shows TOPIK dates and registration deadlines quoted from published notices, plus
  Knowledge Center resources.

### Sumin: support requests

1. The student fills in a topic, the reply language, a subject and details.
2. **Review request** stores the request as a task waiting for approval. No ticket exists yet.
3. The preview shows exactly what the server stored.
4. **Confirm and send** is the only way the human-support request is created (the existing approval
   endpoint). **Edit** declines the stored draft and keeps the text.

The topic is written into the subject as `[Topic]`, because tickets have no category column. The
"My requests" tab lists the student's own requests.

## Permissions (all enforced on the server)

- **Admin tabs (review, sources) and admin actions:** only in admins' directory entries. Every call
  behind them goes to admin-only endpoints or admin-only tools.
- **Official discoveries:** non-admins only receive items that an admin sent to review and whose
  Knowledge Center version is approved (`DiscoveryService.opportunities`). Unreviewed candidates,
  review status and admin fields never reach them. Admins see approved items as verified and the
  rest as unverified, and Leo's list never mixes unreviewed candidates in.
- **`GET /api/v1/agents/{id}/monitoring`:** public, but sanitised. Everyone gets source names, public
  URLs, times and OK or attention. Only admins get errors, failure counts, disabled sources, schedule
  settings and the number of candidates waiting.
- **Tasks and requests:** private to the signed-in student, as before. Students still cannot start
  official-source checks.

## Agent status in the office

Character states come only from the backend directory (the viewer's own tasks), with no frontend
timers:

| State | What the office shows |
|---|---|
| Idle | Breathing animation |
| Working | Quick "typing" animation and a spinning dot |
| Waiting for approval | "!" dot |
| Finished | Check dot |
| Problem | Cross dot |

A running official-source check (scheduled, or started by an admin) shows the monitoring agent as
working to everyone. Characters stay clickable while they work, greeting bubbles no longer block clicks
on a neighbour, and tasks continue after the panel closes.

## Shared components

They live in `workspace/parts.tsx`:
- **Panel and header:** `AgentWorkspaceShell`, `AgentHeader`, `AgentStatus`.
- **Tasks and activity:** `AgentActivityTimeline`, `AgentTaskList`, which reuses the task cards and the
  `useAgentTasks` polling hook shared with the Tasks tab.
- **Cards:** `AgentResultCard`, `SourceCitation`, `OpportunityCard`, `AnnouncementCard`,
  `DeadlineDisplay`, which uses Korean dates.
- **Actions and gates:** `AgentActionBar`, `AgentPermissionGate`, `AdminStrip`.

## Empty states and admin tabs

- **Empty states.** Every empty workspace list says why it is empty and offers next steps, for example:
  - clear the filters or include closed items;
  - show past events;
  - open guides or ask this desk in chat;
  - ask a person through Sumin;
  - open the official TOPIK site.
- **Admin tabs.** Admins see Review and Sources in a separate, always-visible "Admin" row.
- **Review queue.** A card that was just sent to review or dismissed stays in place and shows its new status;
  Refresh reloads the queue.

## Mobile and desktop

- **Desktop:** the existing right-hand panel, with the office visible and clickable.
- **Phones:** a full-screen workspace with a back button. Lists scroll, and controls are at least
  36 px high.

## Production assessment

See [production-assessment.md](production-assessment.md): usefulness by character, end-to-end results, cost and
performance, limitations and readiness.

## Screenshots

Real Chrome, production build, scratch database with synthetic users. The Robo images come from a
live admin check of the configured SCH pages. See [`screenshots-workspaces/`](screenshots-workspaces/).

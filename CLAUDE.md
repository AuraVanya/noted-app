# CLAUDE.md — Noted

Standing instructions for Claude Code. Read this every session before acting.

## What we're building
Noted turns a team's meeting minutes into shared knowledge. Meeting **summaries** and **transcripts** are produced by Fireflies and dropped into Google Drive as PDFs; Noted reads them, presents them, links them to Confluence/Jira, and hands meeting/ticket context to the team's claude.ai Projects by filing Google Docs into mapped Drive folders.

**Sources of truth (read these before building a feature):**
- `docs/noted-build-spec.md` — the full build spec. If this file and the spec disagree, the spec wins; tell me about the conflict.
- `docs/noted-mockup.html` — the interactive design/interaction reference. Match its look and flows.

## Stack
- **Frontend:** React + TypeScript (Vite), client-side routing, React Query for server state. **Styling: Tailwind CSS + shadcn/ui** (components copied into the repo; Radix under the hood). No browser storage (`localStorage`/`sessionStorage`).
- **Backend:** Python, FastAPI (async), Pydantic schemas for all I/O, SQLAlchemy + Alembic.
- **DB:** PostgreSQL (SQLite acceptable for first local runs).
- **LLM:** Use the **Gemini API (Google AI Studio)** for small reformatting tasks only — Confluence page generation, and *optionally* reformatting a Jira ticket into its handoff Doc. **No Anthropic API anywhere.** Target a **Flash** model (free tier covers Flash/Flash-Lite only; Pro needs billing) — don't hardcode the model string from memory; confirm the current one + rate limits at https://ai.google.dev and keep it in config. Key in env as `GEMINI_API_KEY`. The meeting-summary→Doc handoff and Doc filing stay **non-LLM**. **Privacy:** Gemini *free-tier* prompts may be used by Google for training — for sensitive meeting content use the paid tier or Vertex AI (no training), or keep it off the LLM path. (Enabling billing on a Cloud project removes that project's free tier; use a separate project if you want both.) The handoff *destination* is still claude.ai Projects (the user's subscription) — distinct from the Gemini API.

## Repo layout
```
frontend/   # Vite React TS app
backend/    # FastAPI app, app/ package, alembic/, tests/
docs/       # noted-build-spec.md, noted-mockup.html
.env        # never committed; see .env.example
```

## Commands (establish these and keep them working)
- Backend: `cd backend && uvicorn app.main:app --reload` · migrations `alembic upgrade head` · tests `pytest`
- Frontend: `cd frontend && npm run dev` · build `npm run build` · lint `npm run lint`
- Keep a `.env.example` documenting every required variable.

## Domain rules that are easy to get wrong — get these right
1. **Filename parsing is the foundation.** Drive files are `[Title]-[summary|transcript]-[ISO timestamp].pdf`, e.g. `TSD Daily Sync-transcript-2026-06-12T06-15-00.000Z.pdf`. Titles may contain hyphens, so **parse from the right** anchored on the timestamp + `summary|transcript` token — never split left-to-right on `-`. Timestamps are **UTC**; store UTC, display in the user's local timezone. Regex on the stem:
   `^(?P<title>.+)-(?P<kind>summary|transcript)-(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z)$`
2. **Series vs occurrence.** An *occurrence* = `(normalized_title, timestamp)`; a *series* = all occurrences sharing the normalized title. Normalize (trim/collapse-space/lowercase) for matching only; keep the original title for display.
3. **Projects are a Drive handoff to claude.ai — Noted runs NO chat and makes NO Anthropic API calls for chat.** A Noted "Claude Project" is a **registry entry mapping a label to one Google Drive folder**. To get meeting/ticket context into Claude, Noted converts the summary/ticket into a **Google Doc** and files it in the mapped folder(s); the user then adds that Doc to their claude.ai Project once (it auto-syncs thereafter). There is **no programmatic write into claude.ai Projects** — the one-time "admit the Doc" click in claude.ai is unavoidable and stays manual. A series may feed **multiple** Claude Projects (many-to-many). Filing a Doc is reachable from three entry points that all call one handoff service: the minute detail, the ticket detail, and the **Project Context tab** (selecting a context → "Add context to project" modal to multi-select minutes/tickets). Dedupe per project.
4. **Doc conversion, not chat context.** To hand off, extract the summary text (via `extraction.py`) and create a **Google Doc** (text-extraction only; Google Docs are what claude.ai Projects auto-sync — not PDFs). No LLM is needed to file a Doc. The upload/Doc-creation path needs the Drive **write** scope `drive.file` (least privilege). Idempotent: one Doc per occurrence per target project; re-runs don't duplicate.
5. **Transcripts/summaries display as their original PDFs**, streamed from Drive. The file proxy needs **signed-URL** (or cookie) auth because "open in new tab" won't carry an Authorization header.
6. **Confluence page generation uses Gemini, filling a per-series template.** One page service — called by both the manual button and the auto sync job — sends **both the meeting transcript and summary** (transcript for verbatim accuracy, summary for structure) to **Gemini (Flash)** to fill a **page template** stored per series (`confluence_series_config.template_name` + `template_body`; a preset or a custom body with `{{title}}`/`{{date}}`/headings). Gemini returns Markdown mapped into that structure. Extract `transcript_text` lazily (only when generating). New page per occurrence (never overwrite). Confluence `parentId` may be a **folder or a page**. Send Markdown, not hand-built storage XHTML. Log every attempt to `confluence_generation_log`. Needs `GEMINI_API_KEY`. **Transcripts are large and go to Gemini here** — mind free-tier TPM cost and the privacy caveat (verbatim transcripts on the free tier may be used for training; prefer paid/Vertex for sensitive series).
7. **`project_context` is one polymorphic table** (`item_type` = meeting | ticket | file). The meeting-detail, ticket-detail, and in-project picker all insert here. Unique on `(project_id, item_type, item_ref)`.
8. **Sync job is idempotent.** Safe to re-run; rely on unique constraints and the generation log. Failures log and don't abort the run.
9. **Tickets tab is a read-only Kanban** (status columns), Jira **read** scope. A ticket's always-available action is **Add to Claude Project** — files it as a Doc into a Project Context folder, the **same handoff as a minute** (ticket Doc = description + comments). That ticket Doc may *optionally* be reformatted by **Gemini** ("if necessary"); without it, file the raw ticket text. A separate "draft a new Jira ticket from a summary" feature is **not in scope** (not requested) and would need Jira write scope — don't build it. Drag-to-transition is a later enhancement.

## Security
- Never commit secrets. OAuth tokens encrypted at rest. Never send Drive/Atlassian tokens to the client. Scope every query to the authenticated user. Signed file URLs expire quickly.

## How to work with me
- **Plan first.** For each task, propose a short plan and wait for approval before large changes.
- **Small commits.** After each working slice, stop so I can review the diff and commit in GitHub Desktop.
- **Don't invent product facts** (model names, API shapes). Check official docs; if unsure, say so.
- Follow the build order in the spec (§15). Don't jump ahead phases.
- Keep the visual direction from the mockup: cool neutrals + restrained indigo (`#4B45C6`), monospace for timestamps/keys, left-sidebar shell. **Theme shadcn/ui to these tokens — never ship shadcn's default theme.** `docs/noted-mockup.html` is a plain-HTML/CSS reference; replicate its look via the shadcn theme, don't copy its raw CSS. The calendar week grid and the Tickets Kanban are custom Tailwind layouts, not shadcn primitives.

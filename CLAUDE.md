# CLAUDE.md — Noted

Standing instructions for Claude Code. Read this every session before acting.

## What we're building
Noted turns a team's meeting minutes into shared knowledge and Claude-powered context. Meeting **summaries** and **transcripts** are produced by Fireflies and dropped into Google Drive as PDFs; Noted reads them, presents them, links them to Confluence/Jira, and lets the team chat with Claude over project-scoped context.

**Sources of truth (read these before building a feature):**
- `docs/noted-build-spec.md` — the full build spec. If this file and the spec disagree, the spec wins; tell me about the conflict.
- `docs/noted-mockup.html` — the interactive design/interaction reference. Match its look and flows.

## Stack
- **Frontend:** React + TypeScript (Vite), client-side routing, React Query for server state. No browser storage (`localStorage`/`sessionStorage`).
- **Backend:** Python, FastAPI (async), Pydantic schemas for all I/O, SQLAlchemy + Alembic.
- **DB:** PostgreSQL (SQLite acceptable for first local runs).
- **LLM:** Anthropic Messages API. Default `claude-sonnet-4-6` for chat/generation, `claude-haiku-4-5` for cheap extraction. **Do not hardcode model strings from memory — confirm current ones at https://docs.claude.com/en/docs/about-claude/models and keep them in config.**

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
3. **No claude.ai Projects embedding.** "Projects" are an app-side concept. Chat is our own UI on the Anthropic Messages API; the API is stateless, so persist history ourselves.
4. **Context payload = summaries, not transcripts.** Feed meeting *summaries* (and ticket text, and context files) to chat. Only parse transcript *text* for flagged-series auto-Confluence and manual Confluence generation — this is the cost control. Use **prompt caching** for the stable context block in chat.
5. **Transcripts/summaries display as their original PDFs**, streamed from Drive. The file proxy needs **signed-URL** (or cookie) auth because "open in new tab" won't carry an Authorization header.
6. **One Confluence generation service**, called by both the manual button and the auto sync job. New page per occurrence (never overwrite). Confluence `parentId` is a single reference that may be a **folder or a page**. Send Claude's **Markdown**, not hand-built storage XHTML. Log every attempt to `confluence_generation_log`.
7. **`project_context` is one polymorphic table** (`item_type` = meeting | ticket | file). The meeting-detail, ticket-detail, and in-project picker all insert here. Unique on `(project_id, item_type, item_ref)`.
8. **Sync job is idempotent.** Safe to re-run; rely on unique constraints and the generation log. Failures log and don't abort the run.
9. **Tickets tab is a read-only Kanban** (status columns). Drag-to-transition is a later enhancement (needs Jira write scope).

## Security
- Never commit secrets. OAuth tokens encrypted at rest. Never send Drive/Atlassian tokens to the client. Scope every query to the authenticated user. Signed file URLs expire quickly.

## How to work with me
- **Plan first.** For each task, propose a short plan and wait for approval before large changes.
- **Small commits.** After each working slice, stop so I can review the diff and commit in GitHub Desktop.
- **Don't invent product facts** (model names, API shapes). Check official docs; if unsure, say so.
- Follow the build order in the spec (§15). Don't jump ahead phases.
- Keep the visual direction from the mockup: cool neutrals + restrained indigo (`#4B45C6`), monospace for timestamps/keys, left-sidebar shell.

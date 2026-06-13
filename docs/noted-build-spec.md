# Noted — MVP Build Spec

**Purpose.** Noted turns a team's meeting minutes into shared knowledge and LLM context. Meeting transcripts and summaries are already produced by Fireflies and dropped into Google Drive as PDFs; Noted reads them, presents them, connects them to Confluence and Jira, and lets the team chat with Claude over project-scoped context.

This document is written to be handed to Claude Code as the build brief. It assumes the interactive prototype (`noted-mockup.html`) as the visual and interaction reference. Where the prototype and this spec differ, this spec wins.

---

## 1. Scope of the MVP

**In scope:** Google sign-in; reading meeting summaries/transcripts from Drive; a Google-Calendar-style week view; a Minutes list and summary detail; a Tickets tab over Jira presented as a **status-column Kanban board**; app-side Projects with Claude chat over context; **adding files as context (direct upload to Drive, or pick an existing Drive file)**; manual + automatic Confluence page generation; drafting Jira tickets from summaries; a shared "add to project context" model spanning meetings, tickets, and files.

**Explicitly out of scope for MVP:** writing back to Google Calendar; editing summaries/transcripts; full enterprise SAML SSO (Google sign-in only); a vector database (context is fed directly — see §9); mobile-native apps (responsive web only); multi-org tenancy beyond a single Workspace.

**Key constraint that shapes everything:** there is **no Fireflies API access** and **no way to embed claude.ai Projects**. All meeting data comes from Drive PDFs; all chat is built on the Anthropic Messages API with context assembled by Noted.

---

## 2. Tech stack

- **Frontend:** React + TypeScript (Vite). Client-side routing. State via React Query (server cache) + light local state. No browser storage beyond auth session handling.
- **Backend:** Python, **FastAPI** (async; supports streaming chat responses). Pydantic models for all request/response schemas.
- **Database:** PostgreSQL (SQLite acceptable for first local runs). SQLAlchemy + Alembic migrations.
- **Background work:** a scheduled **sync job** (APScheduler or a cron-invoked worker for MVP; Celery/RQ if it grows). Idempotent.
- **LLM:** Anthropic Messages API (`https://api.anthropic.com/v1/messages`). Default model: `claude-sonnet-4-6` for chat and generation; `claude-haiku-4-5` acceptable for cheap extraction. Verify current model strings at https://docs.claude.com/en/docs/about-claude/models before pinning. Use streaming for chat and **prompt caching** for the project-context portion of chat requests to cut repeat-token cost.
- **Integrations:** Google (Drive, Calendar, OAuth/OIDC), Atlassian (Confluence + Jira Cloud REST v2/v3).

---

## 3. Data sources & file convention

Two Drive folders already exist and are populated automatically after each meeting:

- `Fireflies Meeting → Summaries`
- `Fireflies Meeting → Transcript`

**Filename convention (confirmed, stable):**

```
[Meeting Title]-summary-[ISO8601 timestamp].pdf
[Meeting Title]-transcript-[ISO8601 timestamp].pdf
```

Example: `TSD Daily Sync-transcript-2026-06-12T06-15-00.000Z.pdf`

Rules the parser must follow:
- The `.pdf` extension is always present. The title is **never altered** (it equals the calendar event title), and **may itself contain hyphens** (e.g. `Q2 Planning - Phase 1`).
- The timestamp is **UTC** (`Z`). Colons in the time are written as hyphens (`06-15-00` → `06:15:00`); only the dashes **after the `T`** convert back to colons — the date's dashes stay.
- **Parse from the right**, anchoring on the rigid timestamp pattern and the closed `summary|transcript` token. Do **not** split on `-` left-to-right. Suggested regex (apply to the stem):

  ```
  ^(?P<title>.+)-(?P<kind>summary|transcript)-(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z)$
  ```
- Store the timestamp as UTC; **convert to the user's local timezone for all display**.

**Identity model derived from filenames:**
- A **meeting occurrence** = `(normalized_title, timestamp)`. Its summary and transcript are the two files sharing that pair.
- A **meeting series** = all occurrences sharing `normalized_title`. Normalize with: trim, collapse internal whitespace, lowercase, for matching only (preserve the original title for display).

---

## 4. Authentication

**Google sign-in is the only login path for the MVP**, and it doubles as the data-access grant. One OAuth 2.0 / OIDC consent flow requests:
- `openid email profile` (identity / SSO)
- `https://www.googleapis.com/auth/drive.readonly` (read the two folders + stream PDFs)
- `https://www.googleapis.com/auth/calendar.readonly` (week view + today's meetings)

Store the **refresh token** per user (encrypted at rest). Implement token refresh; surface re-auth when refresh fails.

**Atlassian** uses a separate OAuth 2.0 (3LO) consent, triggered on demand the first time the user hits a Confluence/Jira feature. Scopes: read/write Confluence content + space read; read Jira issues, read user, write issues (for Jira drafting). Store tokens per user; the auto-Confluence job (§8) runs under the flag-setter's stored token.

> Note for production: Google may require app verification for the Drive/Calendar sensitive scopes. This is far simpler if Noted is configured as an **internal** app within the org's Google Workspace.

Sessions: issue an HttpOnly session cookie after Google sign-in. (See §7 on why the file proxy needs cookie/signed-URL auth rather than a bearer header.)

---

## 5. Data model

Tables (PostgreSQL). Names indicative.

**`users`** — `id`, `google_sub`, `email`, `display_name`, `avatar_initials`, `timezone`, `created_at`.

**`oauth_credentials`** — `id`, `user_id`, `provider` (`google`|`atlassian`), `access_token` (enc), `refresh_token` (enc), `expires_at`, `scopes`, `atlassian_cloud_id` (nullable). One row per user per provider.

**`meeting_series`** — `id`, `normalized_title`, `display_title`, `created_at`. One per recurring/standalone meeting name.

**`meetings`** (occurrences) — `id`, `series_id`, `title`, `occurred_at` (UTC), `summary_file_id` (Drive), `transcript_file_id` (Drive), `summary_text` (nullable; extracted lazily — see §8), `attendees` (from calendar match, nullable), `calendar_event_id` (nullable), `created_at`. Unique on `(series_id, occurred_at)`.

**`confluence_series_config`** — `id`, `series_id` (unique), `enabled` (bool), `space_key`, `parent_id` (Confluence content id — a page **or** folder; see §10), `format_template` (text), `created_by_user_id`, `updated_at`. Drives "Always add to Confluence."

**`confluence_generation_log`** — `id`, `meeting_id`, `series_id`, `trigger` (`auto`|`manual`), `status` (`success`|`failed`), `confluence_page_id` (nullable), `error` (nullable), `created_at`. One row per generation attempt; powers the "last page created / failed" indicator and idempotency.

**`projects`** — `id`, `name`, `description`, `instructions` (system-prompt preamble for chat), `created_at`, `last_accessed_at`.

**`project_context`** — `id`, `project_id`, `item_type` (`meeting`|`ticket`|`file`), `item_ref` (meeting_id, Jira issue key, or Drive file id), `added_by_user_id`, `added_at`. **Polymorphic association table** — the single source of truth for what's in a project's context. The entry points (meeting detail, ticket detail, in-project picker's Minutes/Tickets/Files tabs) all insert here. Unique on `(project_id, item_type, item_ref)` to prevent duplicates.

**`context_files`** — `id`, `drive_file_id` (unique), `name`, `mime_type`, `source` (`upload`|`drive`), `extracted_text` (nullable, lazily filled), `added_by_user_id`, `created_at`. Metadata for files referenced as context. Files always live in Drive: uploads are pushed to a dedicated Noted folder; "browse" files are referenced in place. `project_context.item_ref` for files points at `drive_file_id`.

**`chat_messages`** — `id`, `project_id`, `role` (`user`|`assistant`), `content`, `sources` (json, optional citations), `created_at`. The Messages API is stateless; this is where conversation persistence lives.

**Jira tickets are not persisted** for the MVP beyond what `project_context` references — they're fetched live from Jira (§11), optionally short-TTL cached. (If live latency is poor, add a `tickets_cache` table later.)

---

## 6. The sync job

Runs on a schedule (e.g. every 5–15 min) per connected user, idempotently.

1. **Enumerate** both Drive folders (Drive API `files.list`, paginated). Collect `{file_id, name, createdTime}`.
2. **Parse** each filename (§3). Skip non-conforming names (log them).
3. **Group** into occurrences by `(normalized_title, timestamp)`; pair summary + transcript file ids.
4. **Upsert** `meeting_series` and `meetings`. Do **not** extract text yet (cost control).
5. **Calendar match** (best-effort): for each occurrence, find the Google Calendar event whose normalized title matches and whose start is within a tolerance window (e.g. ±10 min) of the occurrence timestamp; store `calendar_event_id` and `attendees`.
6. **Auto-Confluence trigger:** for any **new** occurrence whose series has `confluence_series_config.enabled = true`, enqueue a generation job (§8). Use `confluence_generation_log` to guarantee **at most one successful page per occurrence** (decision: a *new page is created per occurrence*; never overwrite).

Failures in any step are logged and do not abort the run.

---

## 7. File serving (transcripts & summaries as PDFs)

Summaries and transcripts are shown as their **original PDFs**, streamed from Drive — they are display artifacts, not parsed for display.

- Endpoint: `GET /api/files/{drive_file_id}` → backend fetches bytes from Drive using the user's token and streams back with `Content-Type: application/pdf`, `Content-Disposition: inline`.
- **Auth gotcha:** "View full transcript" opens a new tab via a plain link, which won't carry an `Authorization` header. Solve with **either** a short-lived **signed URL** (`?token=<signed,exp>`) the backend issues per request, **or** session-cookie auth on this endpoint. Pick one and apply consistently. Signed URL is recommended (works regardless of cookie settings).

Text is extracted from PDFs (pypdf/pdfplumber) **only** when needed: the summary for chat/Confluence/Jira, and the transcript **only for flagged-series auto-generation and manual Confluence generation**. Cache extracted text (`meetings.summary_text`, and a transient transcript cache) to avoid re-extraction.

---

## 8. Confluence generation service (shared by manual + auto)

One service, two triggers. Signature roughly:

```
generate_confluence_page(meeting, space_key, parent_id, format_template, trigger) -> page_id
```

Steps:
1. Ensure `meeting.summary_text` (extract from summary PDF if missing).
2. Extract transcript text (the format template typically references transcript detail/quotes).
3. Call Claude: system prompt instructs it to render the meeting into the given **format_template**, output **Markdown**, no preamble. Provide summary first as the backbone, transcript for detail. (Markdown → Confluence is far safer than asking for storage-format XHTML.)
4. **Validate** the output (non-empty, parses) before posting.
5. Create the page via Confluence REST (§10) in `space_key` under `parent_id`. Add a backlink to the meeting in Noted.
6. Write a `confluence_generation_log` row (`success` + `page_id`, or `failed` + `error`).

- **Manual** ("Create Confluence page" button): opens the modal pre-filled from `confluence_series_config` if the series has one, else defaults; user can edit space/location/format, then calls this service with `trigger='manual'`. One-off transcript parsing here is fine cost-wise.
- **Auto** ("Always add to Confluence"): the sync job calls this service with `trigger='auto'` using the stored series config. Only flagged series ever parse transcripts on a recurring basis — this is the cost control.

---

## 9. Project chat (Claude over context)

Projects are an **app-side concept**, not claude.ai Projects. Each project's context = the items in `project_context` (meeting summaries + Jira tickets).

Chat request flow (`POST /api/projects/{id}/messages`, streamed):
1. Load the project's `instructions` and assemble context: each linked meeting's `summary_text` (extract on first use) and each linked ticket's description + comments (fetched from Jira).
2. Build the Messages API call: system = instructions + assembled context block; messages = persisted `chat_messages` history + the new user turn.
3. **Prompt-cache** the large, stable context block so repeated turns don't re-pay for it.
4. Stream the response to the client; persist the user turn and assistant turn to `chat_messages`. Optionally attach `sources` (which summaries/tickets informed the answer).

For MVP, feed context **directly** (no vector store). Claude's context window comfortably handles a handful of summaries per project. Add retrieval only if a single project's corpus outgrows the window — keep summaries (not full transcripts) as the default context payload to stay well within limits.

### 9a. Files as context

The in-project "Add context" picker has three tabs: Minutes, Tickets, and **Files**. Files give two intake paths, both ending in a Drive-resident file referenced via `context_files` + `project_context`:

- **Upload** (`POST /api/projects/{id}/context/upload`, multipart): backend receives the file, uploads it to a dedicated **Noted** Drive folder (Drive API `files.create`), records `context_files` with `source='upload'`, and links it to the project. This satisfies "the file is saved in Google Drive."
- **Browse Drive:** use the **Google Picker API** on the frontend (API key + the user's OAuth token + app id) so users select from their existing Drive with the access already granted. The selected `drive_file_id` is sent to the backend, recorded with `source='drive'` (referenced in place, not copied), and linked. A backend `files.list` search is an acceptable fallback if the Picker is not wired up.

When a file enters a project's context, its text is extracted on first use (PDF via pypdf/pdfplumber; `.docx`, `.txt`, `.md`, and Google Docs export-to-text) and cached in `context_files.extracted_text`, then fed to chat like a summary. Cap per-file size and total context size; skip/flag unsupported binary types.

---

## 10. Confluence integration (REST v2)

- Resolve `cloud_id` from the Atlassian OAuth grant.
- **Create page:** `POST /wiki/api/v2/pages` with `spaceId`, `title`, `body` (Markdown representation), and optional **`parentId`**. The `parentId` is a single content reference and **may point at a folder or a page** — that is how "Folder/Parent" from the UI maps. There is no separate folder field.
- **Destination pickers:** populate Space from `GET .../spaces`; populate the location picker from the space's content tree (pages + folders) so users choose a real `parentId` rather than typing it.
- Body: send Claude's Markdown via the API's Markdown representation (avoid hand-built storage XHTML).

---

## 11. Jira integration (REST)

- **Tickets tab:** fetch issues assigned to the current user — JQL `assignee = currentUser() ORDER BY updated DESC`. From each issue read: key, summary (title), issue type, status, priority, project, and the board it belongs to. Present as a **Kanban board**: one vertical column per status (To Do / In Progress / In Review / Done), tickets as cards within their status column. A project filter narrows which tickets appear; each card shows type, key, priority, its board, and assignee. Cards click through to the ticket detail. Read-only for the MVP — **drag-to-transition is a deliberate enhancement** (it requires Jira write scope and the transitions API: `GET .../issue/{key}/transitions` then `POST .../transitions`), worth adding once the read board is solid. Map your instance's real workflow statuses to the columns rather than hardcoding four.
- **Ticket detail:** fetch description + comments for the selected issue.
- **Add to project:** inserts a `project_context` row with `item_type='ticket'`, `item_ref=<issue key>`.
- **Draft Jira ticket** (from a meeting summary): Claude extracts action items from the summary into `{summary, description, type}`, maps assignees from attendees where possible; the modal lets the user edit, then `POST` creates the issue. Review-before-create.

---

## 12. API surface (indicative)

```
# Auth
GET  /api/auth/google/login            -> redirect to Google consent
GET  /api/auth/google/callback         -> create session
GET  /api/auth/atlassian/login         -> redirect to Atlassian consent
GET  /api/auth/atlassian/callback
POST /api/auth/logout
GET  /api/me                           -> profile + connection status

# Home / Calendar
GET  /api/calendar/week?start=         -> events for the week (+matched meeting_id, past/upcoming)
GET  /api/calendar/today               -> today's meetings

# Minutes
GET  /api/meetings                      -> past occurrences (list), newest first
GET  /api/meetings/{id}                 -> summary detail (overview/points/decisions/actions)
GET  /api/files/{drive_file_id}         -> stream PDF (signed-URL auth)

# Confluence
GET  /api/confluence/spaces
GET  /api/confluence/spaces/{key}/tree  -> pages + folders for the location picker
POST /api/meetings/{id}/confluence      -> manual generate {space,parent,format}
GET  /api/series/{id}/confluence-config
PUT  /api/series/{id}/confluence-config -> enable/disable + space/parent/format

# Jira
GET  /api/tickets                       -> assigned issues (for the Kanban board)
GET  /api/tickets/{key}                 -> description + comments
POST /api/meetings/{id}/jira-draft      -> Claude draft -> create issue

# Projects + context
GET  /api/projects                      -> list (+context counts, last_accessed)
GET  /api/projects/{id}                 -> project + context items
POST /api/projects/{id}/context         -> add {item_type,item_ref}[]  (meeting | ticket | file)
POST /api/projects/{id}/context/upload  -> multipart upload -> save to Drive -> link as file context
GET  /api/drive/files?q=                -> Drive search (fallback if not using Google Picker)
DELETE /api/projects/{id}/context/{cid}
GET  /api/projects/{id}/messages        -> chat history
POST /api/projects/{id}/messages        -> send turn (streamed response)
```

---

## 13. Screens (map to the prototype)

| Route | Screen | Notes |
|---|---|---|
| `/login` | Login | Google sign-in only; SSO via Workspace |
| `/` | Home | Greeting (time-of-day), Today's Meetings (left), Recent Projects (right) |
| `/calendar` | Calendar | Week grid; past meeting → summary dialog w/ "Full view" → `/minutes/:id`; upcoming → "Upcoming" dialog |
| `/minutes` | Minutes list | Past occurrences; series flagged for auto-Confluence show an indicator |
| `/minutes/:id` | Summary detail | Overview/points/decisions/actions; "View full transcript" (new tab); **Always add to Confluence** panel (series-level); action bar: Create Confluence page, Draft Jira ticket, Add to project |
| `/tickets` | Tickets board | **Kanban**: status columns (To Do / In Progress / In Review / Done), cards by status; project filter chips; read-only (drag-to-transition is a later add) |
| `/tickets/:key` | Ticket detail | Description + comments; Add to project |
| `/projects` | Projects list | Cards with context counts (summaries · tickets · files) |
| `/projects/:id` | Project chat | Claude over context; **Add context** picker with Minutes / Tickets / **Files** tabs (upload or browse Drive), multi-select, in header |
| `/profile` | Profile | Connected accounts (Google, Atlassian), sign out |

Visual direction: cool neutrals + one restrained indigo accent (`#4B45C6`), monospace for timestamps/keys/metadata, left sidebar shell. See `noted-mockup.html`.

---

## 14. Non-functional requirements

- **Security:** encrypt OAuth tokens at rest; HttpOnly session cookies; never expose Drive/Atlassian tokens to the client; scope every query to the authenticated user; signed URLs for file streaming expire quickly.
- **Token refresh:** implement for both providers; on refresh failure, prompt re-auth and (for auto-Confluence) mark the generation `failed` with a clear reason.
- **Idempotency:** sync job and auto-generation must be safe to re-run; rely on `confluence_generation_log` and unique constraints.
- **Cost control:** summaries (not transcripts) are the default LLM payload; transcripts parsed only for flagged-series auto-gen and manual Confluence; prompt-cache chat context.
- **Observability:** structured logs for sync runs, generation attempts, and Claude calls (latency, tokens). Surface auto-gen status in the UI.
- **Resilience:** all third-party calls wrapped with timeouts + retries; partial failures degrade gracefully (e.g. a meeting with no calendar match still lists in Minutes).
- **Quality floor:** responsive to mobile, keyboard focus visible, reduced-motion respected.

---

## 15. Suggested build order

1. **Foundation:** repo scaffold (Vite + FastAPI), DB + migrations, Google OAuth + session, `/api/me`, app shell + sidebar.
2. **Ingestion:** sync job (enumerate → parse → upsert series/meetings), file proxy with signed URLs.
3. **Read tabs:** Minutes (list + detail + transcript link), Calendar (week view + dialogs, calendar matching), Home widgets.
4. **Projects + chat:** projects CRUD, `project_context` table, chat over context (streamed, prompt-cached), persistence.
5. **Atlassian:** OAuth; Tickets tab (list/detail/add-to-project); manual "Create Confluence page" + "Draft Jira ticket"; the three add-to-context entry points unified.
6. **Confluence automation:** series config UI + storage, generation service, sync-job auto-trigger, generation log + status indicators.

Phases 1–4 deliver the core value loop (meetings → shared context → Claude). Phases 5–6 add the integrations and the automation.

---

## 16. Open assumptions to confirm

- "Space" in the Tickets UI is treated as Jira **Project** (Jira has no Spaces). Relabel if the team insists on "Space."
- Calendar↔meeting matching uses title + timestamp proximity; acceptable tolerance window TBD against real data.
- Single Google Workspace / single Atlassian site for the MVP (no multi-org).
- Auto-Confluence runs under the token of whoever enabled the series flag.

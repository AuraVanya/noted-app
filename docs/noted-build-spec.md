# Noted — MVP Build Spec

**Purpose.** Noted turns a team's meeting minutes into shared knowledge and LLM context. Meeting transcripts and summaries are already produced by Fireflies and dropped into Google Drive as PDFs; Noted reads them, presents them, connects them to Confluence and Jira, and lets the team chat with Claude over project-scoped context.

This document is written to be handed to Claude Code as the build brief. It assumes the interactive prototype (`noted-mockup.html`) as the visual and interaction reference. Where the prototype and this spec differ, this spec wins.

---

## 1. Scope of the MVP

**In scope:** Google sign-in; reading meeting summaries/transcripts from Drive; a Google-Calendar-style week view; a Minutes list and summary detail; a Tickets tab over Jira presented as a **status-column Kanban board**; **a "Claude Project" registry that hands meeting/ticket context to claude.ai by filing Google Docs into a mapped Drive folder** (manual one-time admit in claude.ai; a series may feed multiple projects, manually or via an "Always add to Claude Project" flag); manual + automatic Confluence page creation (Gemini reformats the summary into the page); Jira tickets read-only (Tickets tab) and fileable to a Project Context.

**Explicitly NOT in scope (changed):** Noted does **not** run in-app Claude chat and does **not** call the Anthropic API for chat — there is no per-token cost on the chat path. Context reaches Claude through the Drive→claude.ai Project handoff (claude.ai Projects auto-sync Google Docs). There is no programmatic write into claude.ai Projects, so admitting a new Doc to a Project is a one-time manual click in claude.ai. The earlier "in-app chat over context / files-as-context / project_context" design is superseded by this handoff model.

**Explicitly out of scope for MVP:** writing back to Google Calendar; editing summaries/transcripts; full enterprise SAML SSO (Google sign-in only); a vector database (context is fed directly — see §9); mobile-native apps (responsive web only); multi-org tenancy beyond a single Workspace.

**Key constraint that shapes everything:** there is **no Fireflies API access** and **no way to embed claude.ai Projects**. All meeting data comes from Drive PDFs; there is no in-app chat — meeting context reaches Claude via the Drive→claude.ai handoff, and the only LLM Noted calls is Gemini for small Confluence/Jira reformatting.

---

## 2. Tech stack

- **Frontend:** React + TypeScript (Vite). Client-side routing. State via React Query + light local state. **Styling: Tailwind CSS + shadcn/ui** — accessible primitives (dialog, select, dropdown, tabs, toast, avatar, badge, button, card) for the modals/pickers; the calendar week grid and Tickets Kanban are custom Tailwind. **Theme shadcn to the mockup tokens; not its default theme.** No browser storage beyond auth session handling.
- **Backend:** Python, **FastAPI** (async). Pydantic schemas for all I/O.
- **Database:** PostgreSQL (SQLite for first local runs). SQLAlchemy + Alembic.
- **Background work:** a scheduled **sync job** (APScheduler for MVP). Idempotent.
- **LLM:** **Gemini API (Google AI Studio)** for small reformatting tasks only — Confluence page generation (§8/§10) and _optionally_ the Jira-ticket→Doc handoff (§9/§11). **No Anthropic API.** Use a **Flash** model (free tier covers Flash/Flash-Lite; Pro needs billing); confirm the current model string + rate limits at https://ai.google.dev, keep in config, key as `GEMINI_API_KEY`. The meeting-summary→Doc handoff and Doc filing are **non-LLM**. **Privacy caveat (now stronger):** Confluence generation sends **both the summary and the full transcript** to Gemini. Free-tier prompts may be used by Google for training — meaning the verbatim meeting transcript could be. For any sensitive meetings, use the **paid tier or Vertex AI** (neither trains on your data), or don't enable Confluence generation for those series. The handoff _destination_ remains claude.ai Projects (the user's subscription), separate from the Gemini API.
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

**Atlassian** uses a separate OAuth 2.0 (3LO) consent, triggered on demand the first time the user hits a Confluence/Jira feature. Scopes: read/write Confluence content + space read (to create pages); **read** Jira issues + read user. **No Jira write scope** — Noted doesn't create or transition issues in the MVP. Store tokens per user; the auto-Confluence job (§8) runs under the flag-setter's stored token.

> Note for production: Google may require app verification for the Drive/Calendar sensitive scopes. This is far simpler if Noted is configured as an **internal** app within the org's Google Workspace.

Sessions: issue an HttpOnly session cookie after Google sign-in. (See §7 on why the file proxy needs cookie/signed-URL auth rather than a bearer header.)

---

## 5. Data model

Tables (PostgreSQL). Names indicative.

**`users`** — `id`, `google_sub`, `email`, `display_name`, `avatar_initials`, `timezone`, `created_at`.

**`oauth_credentials`** — `id`, `user_id`, `provider` (`google`|`atlassian`), `access_token` (enc), `refresh_token` (enc), `expires_at`, `scopes`, `atlassian_cloud_id` (nullable). One row per user per provider.

**`meeting_series`** — `id`, `normalized_title`, `display_title`, `created_at`. One per recurring/standalone meeting name.

**`meetings`** (occurrences) — `id`, `series_id`, `title`, `occurred_at` (UTC), `summary_file_id` (Drive), `transcript_file_id` (Drive), `summary_text` (nullable; extracted lazily — see §8), `transcript_text` (nullable; extracted lazily, only when a Confluence page is generated — §8), `attendees` (from calendar match, nullable), `calendar_event_id` (nullable), `created_at`. Unique on `(series_id, occurred_at)`.

**`confluence_series_config`** — `id`, `series_id` (unique), `enabled` (bool), `space_key`, `parent_id` (Confluence content id — a page **or** folder; see §10), `template_name`, `template_body` (the page template Gemini fills — preset name + body with `{{title}}`/`{{date}}`/headings), `created_by_user_id`, `updated_at`. Drives "Always add to Confluence."

**`confluence_generation_log`** — `id`, `meeting_id`, `series_id`, `trigger` (`auto`|`manual`), `status` (`success`|`failed`), `confluence_page_id` (nullable), `error` (nullable), `created_at`. One row per generation attempt; powers the "last page created / failed" indicator and idempotency.

**`claude_projects`** (registry) — `id`, `label` (the claude.ai Project's name, user-entered), `drive_folder_id` (the one Drive folder this maps to), `created_at`. Noted never talks to claude.ai; this is a user-maintained mapping of "Claude Project name → Drive folder."

**`series_project_links`** (many-to-many) — `id`, `series_id`, `claude_project_id`, `enabled` (the "Always add to Claude Project" flag). A series may link to **multiple** Claude Projects.

**`claude_project_docs`** (handoff log + idempotency) — `id`, `item_type` (`meeting`|`ticket`), `item_ref`, `claude_project_id`, `drive_doc_id` (the created Google Doc), `trigger` (`manual`|`auto`), `status` (`success`|`failed`), `error`, `created_at`. Unique on `(item_type, item_ref, claude_project_id)` — one Doc per item per project. Powers the flag's last-run status and prevents duplicates.

> Superseded: the earlier `projects`, `project_context`, `context_files`, and `chat_messages` tables are **not** built — they belonged to the in-app-chat design, which is replaced by the Drive handoff.

**Jira tickets are not persisted** beyond what `claude_project_docs` references — fetched live from Jira (§11).

---

## 6. The sync job

Runs on a schedule (e.g. every 5–15 min) per connected user, idempotently.

1. **Enumerate** both Drive folders (Drive API `files.list`, paginated). Collect `{file_id, name, createdTime}`.
2. **Parse** each filename (§3). Skip non-conforming names (log them).
3. **Group** into occurrences by `(normalized_title, timestamp)`; pair summary + transcript file ids.
4. **Upsert** `meeting_series` and `meetings`. Do **not** extract text yet (cost control).
5. **Calendar match** (best-effort): for each occurrence, find the Google Calendar event whose normalized title matches and whose start is within a tolerance window (e.g. ±10 min) of the occurrence timestamp; store `calendar_event_id` and `attendees`.
6. **Auto-Confluence trigger:** for any **new** occurrence whose series has `confluence_series_config.enabled = true`, enqueue a generation job (§8). Use `confluence_generation_log` to guarantee **at most one successful page per occurrence** (decision: a _new page is created per occurrence_; never overwrite).

Failures in any step are logged and do not abort the run.

---

## 7. File serving (transcripts & summaries as PDFs)

Summaries and transcripts are shown as their **original PDFs**, streamed from Drive — they are display artifacts, not parsed for display.

- Endpoint: `GET /api/files/{drive_file_id}` → backend fetches bytes from Drive using the user's token and streams back with `Content-Type: application/pdf`, `Content-Disposition: inline`.
- **Auth gotcha:** "View full transcript" opens a new tab via a plain link, which won't carry an `Authorization` header. Solve with **either** a short-lived **signed URL** (`?token=<signed,exp>`) the backend issues per request, **or** session-cookie auth on this endpoint. Pick one and apply consistently. Signed URL is recommended (works regardless of cookie settings).

Text is extracted from PDFs (pypdf/pdfplumber) when needed: the **summary** text for the Claude Project handoff Doc (§9), and **both the summary and the transcript** to feed Gemini for the Confluence page (§8) — sending both gives the model the verbatim detail for accuracy. Transcripts remain **display-only in the UI** (embedded PDF; never shown as parsed text), but their text _is_ extracted for Confluence generation. Cache extracted text (`meetings.summary_text`, `meetings.transcript_text`) to avoid re-extraction; transcript extraction can be lazy (only when a Confluence page is generated for that occurrence).

---

## 8. Confluence page service (shared by manual + auto)

One service, two triggers — **Gemini-reformatted**. Signature roughly:

```
create_confluence_page(meeting, space_key, parent_id, trigger) -> page_id
```

Steps:

1. Ensure `meeting.summary_text` and `meeting.transcript_text` (extract from the summary/transcript PDFs if missing; cache both).
2. Call **Gemini** (Flash) to fill a **page template** using **both the transcript and the summary** — the summary for structure/decisions, the transcript for verbatim accuracy and detail the summary omits. The template is chosen per series (a preset — standard notes / decisions & actions / exec summary — or a custom body with `{{title}}`, `{{date}}`, and the user's own headings), stored in `confluence_series_config` (`template_name`, `template_body`). Gemini maps the content into that structure and returns Markdown. **Cost/limits:** transcripts are large — this is the main token driver, especially for the per-occurrence auto flow; mind the free-tier TPM cap and prefer paid/Vertex for sensitive transcripts (see §16).
3. Create the page via Confluence REST (§10) in `space_key` under `parent_id`. Add a backlink to the meeting in Noted.
4. Write a `confluence_generation_log` row (`success` + `page_id`, or `failed` + `error`).

- **Manual** ("Create Confluence page" button): opens the modal pre-filled from `confluence_series_config` if the series has one, else defaults; user edits space/location only, then calls this service with `trigger='manual'`.
- **Auto** ("Always add to Confluence"): the sync job calls this service with `trigger='auto'` using the stored series config. A new page per occurrence.

> **Gemini reformats** the meeting summary into a structured Confluence page (Flash model, low volume). An optional page-format template can steer the structure. Privacy caveat applies (free-tier training); see §2/§16.

---

## 9. Claude Project handoff (via Google Drive)

Noted does **not** chat with Claude or call the Anthropic API. Instead it gets meeting/ticket context _into the user's claude.ai Project_ by filing **Google Docs** into a Drive folder that the user has linked to that Project. claude.ai Projects auto-sync linked Google Docs, so once a Doc is admitted it stays current.

**Why Docs, why this shape:** claude.ai Projects ingest Google Docs (text), not PDFs, and ingest **per file** (no folder-watch). So a _new_ Doc must be admitted once in claude.ai; thereafter edits sync automatically. There is no API to write into a Project's knowledge — the one-time admit click is unavoidable.

**The registry.** A Noted "Project Context" = `{label, drive_folder_id}` (`claude_projects`). The label is the claude.ai Project's name; the folder is where Noted files that project's Docs. **"Create new Project Context"** provisions a new Drive folder to represent the context (`files.create` folder). Noted never contacts claude.ai.

**Manual handoff** (`POST /api/claude-projects/{id}/docs` from a minute or ticket): extract the summary text (`extraction.py`) or gather the ticket's description + comments, create a **Google Doc** in the project's folder (`files.create`), log to `claude_project_docs`. Return the Doc link + an "open in Claude" helper so the user can admit it in claude.ai quickly. A minute/ticket may be sent to **multiple** projects at once (multi-select).

**Three entry points, one action.** Filing a Doc is reachable from (a) the **minute detail** "Add to Claude Project", (b) the **ticket detail** "Add to Claude Project", and (c) the **Project Context tab** — selecting a registered context opens an **"Add context to project"** modal to multi-select meeting minutes and/or tickets to file into that context's folder (with Open-folder / Open-in-Claude buttons in the modal). All three call the same handoff service and write `claude_project_docs`; items already filed to that project show a "Filed" badge (dedupe).

**Automatic handoff — "Always add to Claude Project."** A **series-level** flag (mirrors "Always add to Confluence"), many-to-many via `series_project_links`: when a new occurrence of a flagged series is ingested, the **sync job** converts its summary → Google Doc → files it into each linked project's folder, logged and idempotent (one Doc per occurrence per project). No LLM. The new Doc still needs the one-time admit in claude.ai (a batched "pending admit" queue is a deferred enhancement).

**Scope/cost:** filing Docs needs the Drive **write** scope `drive.file` (least privilege). Meeting-summary Docs are filed **non-LLM**; a ticket Doc may _optionally_ be reformatted by **Gemini** (§11, "if necessary"). The handoff itself adds no Anthropic cost.

---

## 10. Confluence integration (REST v2)

- Resolve `cloud_id` from the Atlassian OAuth grant.
- **Create page:** `POST /wiki/api/v2/pages` with `spaceId`, `title`, `body` (Markdown representation), and optional **`parentId`**. The `parentId` is a single content reference and **may point at a folder or a page** — that is how "Folder/Parent" from the UI maps. There is no separate folder field.
- **Destination pickers:** populate Space from `GET .../spaces`; populate the location picker from the space's content tree (pages + folders) so users choose a real `parentId` rather than typing it.
- Body: send Gemini's reformatted Markdown (§8) and send via the API's Markdown representation (avoid hand-built storage XHTML).

---

## 11. Jira integration (REST)

- **Tickets tab:** fetch issues assigned to the current user — JQL `assignee = currentUser() ORDER BY updated DESC`. From each issue read: key, summary (title), issue type, status, priority, project, and the board it belongs to. Present as a **Kanban board**: one vertical column per status (To Do / In Progress / In Review / Done), tickets as cards within their status column. A project filter narrows which tickets appear; each card shows type, key, priority, its board, and assignee. Cards click through to the ticket detail. Read-only for the MVP — **drag-to-transition is a deliberate enhancement** (it requires Jira write scope and the transitions API: `GET .../issue/{key}/transitions` then `POST .../transitions`), worth adding once the read board is solid. Map your instance's real workflow statuses to the columns rather than hardcoding four.
- **Ticket detail:** fetch description + comments for the selected issue.
- **Add to Claude Project:** files the ticket (description + comments) as a Google Doc into the selected Claude Project's folder(s) and logs to `claude_project_docs` (§9). Same handoff as a minute.

> **Jira role = read (Tickets tab) + file-to-Project-Context.** Filing a ticket as a handoff Doc (§9) can _optionally_ use **Gemini** to reformat the ticket's description + comments into a cleaner Doc ("if necessary"); without it, the Doc is the raw ticket text — no LLM required. Jira needs **read-only** scope for the MVP (no Jira write). A separate "Draft a new Jira ticket from a summary" feature is **not** in scope right now (not requested); if reintroduced it would be a small Gemini extraction task plus a Jira write scope.

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

# Claude Projects (registry + Drive handoff)
GET    /api/claude-projects                 -> list registry (label, folder, recent)
POST   /api/claude-projects                 -> register {label, drive_folder_id | create new folder}
DELETE /api/claude-projects/{id}
POST   /api/claude-projects/{id}/docs        -> file a {item_type,item_ref}[] as Google Docs in the folder (from minute, ticket, or the Project Context add-items modal); returns doc links
GET    /api/claude-projects/{id}/filed        -> items already filed to this project (for "Filed" badges)
POST   /api/meetings/{id}/claude-projects    -> add this minute to one or more projects (multi-select)
POST   /api/tickets/{key}/claude-projects    -> add this ticket to one or more projects
GET    /api/series/{id}/claude-projects      -> the series' "Always add" links + status
PUT    /api/series/{id}/claude-projects      -> set the flag + which projects (many-to-many)
```

---

## 13. Screens (map to the prototype)

| Route                  | Screen                       | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ---------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/login`               | Login                        | Google sign-in only; SSO via Workspace                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `/`                    | Home                         | Greeting (time-of-day), Today's Meetings (left), Recent Projects (right)                                                                                                                                                                                                                                                                                                                                                                                             |
| `/calendar`            | Calendar                     | Week grid; past meeting → summary dialog w/ "Full view" → `/minutes/:id`; upcoming → "Upcoming" dialog                                                                                                                                                                                                                                                                                                                                                               |
| `/minutes`             | Minutes list                 | Past occurrences; series flagged for auto-Confluence show an indicator                                                                                                                                                                                                                                                                                                                                                                                               |
| `/minutes/:id`         | Summary detail               | Overview/points/decisions/actions; "View full transcript" (new tab); **Always add to Confluence** + **Always add to Claude Project** panels (series-level); action bar: Create Confluence page (Gemini), Add to Claude Project                                                                                                                                                                                                                                       |
| `/tickets`             | Tickets board                | **Kanban**: status columns (To Do / In Progress / In Review / Done), cards by status; project filter chips; read-only (drag-to-transition is a later add)                                                                                                                                                                                                                                                                                                            |
| `/tickets/:key`        | Ticket detail                | Description + comments; **Add to Claude Project** (files a Doc into the folder)                                                                                                                                                                                                                                                                                                                                                                                      |
| `/projects`            | Project Context              | Registry of **Project Contexts** (each = a Claude Project label → a Google Drive folder), with docs-filed count. **"Create new Project Context"** creates a new Drive folder to represent a context. Selecting a context opens **"Add context to project"** — multi-select minutes/tickets to file as Docs (already-filed show "Filed"), plus **Open folder** / **Open in Claude** buttons in that modal. Confirm reads **"Add to Claude Project."** No in-app chat. |
| `/minutes/:id` (panel) | Always add to Claude Project | Series-level flag + multi-select of target Claude Projects, mirroring the Confluence panel; last-run status; "Add to Claude Project" action with Doc link + open-in-Claude helper                                                                                                                                                                                                                                                                                    |
| `/profile`             | Profile                      | Connected accounts (Google, Atlassian), sign out                                                                                                                                                                                                                                                                                                                                                                                                                     |

Visual direction: cool neutrals + one restrained indigo accent (`#4B45C6`), monospace for timestamps/keys/metadata, left sidebar shell. Built with Tailwind + shadcn/ui themed to these tokens (not shadcn defaults). `noted-mockup.html` is a plain-HTML/CSS reference for look and flows — replicate its appearance via the shadcn theme rather than porting its CSS verbatim.

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
4. **Claude Project handoff:** the `claude_projects` registry + Projects tab; `drive.file` scope; "Add to Claude Project" on minute/ticket (summary/ticket → Google Doc in folder, with open-in-Claude helper); the series-level "Always add to Claude Project" flag (many-to-many) wired into the sync job; the handoff log. No Anthropic API.
5. **Atlassian:** OAuth (Confluence + Jira); **Tickets tab** live data (list/detail); Jira ticket → **Add to Claude Project** (file as a Doc — same handoff as minutes; built in Phase 4), optionally Gemini-reformatted. Jira read-only scope.
6. **LLM-assisted Confluence (Gemini):** "Create Confluence page" + the "Always add to Confluence" automation reformat the summary into a page via the **Gemini API** (Flash model, low volume). Needs `GEMINI_API_KEY` (Google AI Studio, free tier). Mind the privacy caveat (§16).

Phases 1–4 deliver the core value loop (meetings → shared context → Claude). Phases 5–6 add the integrations and the automation.

---

## 16. Open assumptions to confirm

- "Space" in the Tickets UI is treated as Jira **Project** (Jira has no Spaces). Relabel if the team insists on "Space."
- Calendar↔meeting matching uses title + timestamp proximity; acceptable tolerance window TBD against real data.
- Single Google Workspace / single Atlassian site for the MVP (no multi-org).
- Auto-Confluence runs under the token of whoever enabled the series flag.
- **Claude Project handoff is Drive-based, not API-based.** Noted files Google Docs into a mapped folder; the user admits new Docs to their claude.ai Project manually (one click per new Doc; auto-syncs after). A batched "pending admit" queue is a planned later enhancement.
- **LLM for Confluence/Jira — RESOLVED: Gemini API (Google AI Studio), Flash model.** Small reformatting (Confluence page generation; optional Jira-ticket→Doc reformatting) runs on Gemini, not Anthropic. Needs `GEMINI_API_KEY` (free, no card; free tier = Flash/Flash-Lite only). **Confluence generation sends both the summary and the full transcript** for accuracy. **Privacy:** free-tier prompts may be used by Google for training — and that now includes verbatim transcripts; for sensitive meetings use the **paid tier or Vertex AI** (no training) or don't enable Confluence for those series. **Cost/limits:** transcripts are the dominant token cost, especially in the per-occurrence auto flow (a daily standup = a full transcript to Gemini daily) — watch the free-tier TPM/RPD caps. **Ops:** enabling billing on a Cloud project deletes that project's free tier — use a separate project for free vs paid. Model strings/limits change; confirm at https://ai.google.dev. The meeting-summary→Doc handoff and the claude.ai destination are unaffected (no LLM / the user's own subscription).
- **External-member access** (sign-in with personal email while keeping company data private) remains a future design: decouple data ingestion (service account) from login (allow-list). Not in MVP.

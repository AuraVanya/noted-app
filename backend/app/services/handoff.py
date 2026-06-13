"""
Drive handoff service.

`file_meeting_to_context` is the one shared service called by every UI
entry point that adds a meeting to a Project Context — the minute
detail's "Add to Project Context" button, the Project Context detail
page's "Add context to project" picker, and (Slice C) the auto-add
sync job. Ticket handoff lands in Phase 5 along with Jira read.

Idempotency lives at the DB level: `project_context_docs` has a unique
`(project_context_id, item_type, item_ref)`. If a successful row already
exists, we return it and skip the Drive write.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Meeting,
    MeetingSeries,
    OAuthCredential,
    ProjectContext,
    ProjectContextDoc,
)
from .atlassian import AtlassianAuthError, get_issue, get_valid_atlassian_token
from .extraction import SummaryUnavailable, extract_summary_text
from .google import (
    DriveAccessError,
    GoogleAuthError,
    create_drive_doc,
    get_valid_google_token,
)


log = logging.getLogger(__name__)

Trigger = Literal["manual", "auto"]


@dataclass
class FilingResult:
    item_type: str
    item_ref: str
    status: str  # 'success' | 'failed' | 'skipped'
    drive_doc_id: str | None = None
    drive_doc_url: str | None = None
    error: str | None = None


def _doc_name(meeting: Meeting, project_context_label: str) -> str:
    """Filename format: `[Project Context Label] Meeting Title - YYYY-MM-DD`.
    The date is UTC — we don't know the user's TZ at filing time, and a
    deterministic UTC stamp keeps Drive listings sortable."""
    date_str = meeting.occurred_at.strftime("%Y-%m-%d")
    return f"[{project_context_label}] {meeting.title} - {date_str}"


def _doc_body(meeting: Meeting, series_title: str, summary_text: str) -> str:
    """Body the Doc starts with: a small metadata header, then the
    extracted summary. The header makes the Doc self-contained when
    claude.ai picks it up (Claude can see which meeting it came from)."""
    attendee_names = []
    if isinstance(meeting.attendees, list):
        for a in meeting.attendees:
            if not isinstance(a, dict):
                continue
            name = a.get("displayName") or a.get("email") or ""
            if name:
                attendee_names.append(name)
    attendees_line = ", ".join(attendee_names) if attendee_names else "—"

    return (
        f"Meeting: {meeting.title}\n"
        f"Series: {series_title}\n"
        f"Occurred (UTC): {meeting.occurred_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"Attendees: {attendees_line}\n"
        f"\n"
        f"———\n"
        f"\n"
        f"{summary_text}\n"
    )


async def file_meeting_to_context(
    session: AsyncSession,
    *,
    meeting_id: int,
    project_context_id: int,
    user_id: int,
    trigger: Trigger = "manual",
) -> FilingResult:
    """File a meeting's summary as a Google Doc into the Project Context's
    Drive folder. Idempotent by `(project_context_id, 'meeting', meeting_id)`."""
    # Load meeting + series + context
    meeting_row = await session.execute(
        select(Meeting, MeetingSeries.display_title)
        .join(MeetingSeries, MeetingSeries.id == Meeting.series_id)
        .where(Meeting.id == meeting_id)
    )
    pair = meeting_row.first()
    if pair is None:
        return FilingResult(
            item_type="meeting",
            item_ref=str(meeting_id),
            status="failed",
            error=f"meeting {meeting_id} not found",
        )
    meeting, series_title = pair

    ctx = await session.get(ProjectContext, project_context_id)
    if ctx is None:
        return FilingResult(
            item_type="meeting",
            item_ref=str(meeting_id),
            status="failed",
            error=f"Project Context {project_context_id} not found",
        )

    if not meeting.summary_file_id:
        return FilingResult(
            item_type="meeting",
            item_ref=str(meeting_id),
            status="failed",
            error="meeting has no summary file yet",
        )

    # Dedupe: if a successful row already exists, return it as 'skipped'
    existing_row = await session.execute(
        select(ProjectContextDoc).where(
            ProjectContextDoc.project_context_id == ctx.id,
            ProjectContextDoc.item_type == "meeting",
            ProjectContextDoc.item_ref == str(meeting.id),
        )
    )
    existing = existing_row.scalar_one_or_none()
    if existing is not None and existing.status == "success":
        return FilingResult(
            item_type="meeting",
            item_ref=str(meeting.id),
            status="skipped",
            drive_doc_id=existing.drive_doc_id,
            drive_doc_url=existing.drive_doc_url,
        )

    # Need the user's token both for extraction (download summary PDF)
    # and the Doc upload.
    try:
        token = await get_valid_google_token(session, user_id)
    except GoogleAuthError as exc:
        return await _record_failure(
            session, existing, ctx, meeting, trigger, f"auth: {exc}"
        )

    # Extract summary text (cached on meeting.summary_text after first hit)
    try:
        summary_text = await extract_summary_text(session, meeting, token)
    except SummaryUnavailable as exc:
        return await _record_failure(
            session, existing, ctx, meeting, trigger, f"extraction: {exc}"
        )

    # Create the Doc
    try:
        created = await create_drive_doc(
            token,
            _doc_name(meeting, ctx.label),
            ctx.drive_folder_id,
            _doc_body(meeting, series_title, summary_text),
        )
    except DriveAccessError as exc:
        return await _record_failure(
            session, existing, ctx, meeting, trigger, f"drive: {exc}"
        )

    # Upsert success row
    if existing is None:
        row = ProjectContextDoc(
            project_context_id=ctx.id,
            item_type="meeting",
            item_ref=str(meeting.id),
            drive_doc_id=created["id"],
            drive_doc_url=created.get("webViewLink"),
            status="success",
            error=None,
            trigger=trigger,
        )
        session.add(row)
    else:
        existing.drive_doc_id = created["id"]
        existing.drive_doc_url = created.get("webViewLink")
        existing.status = "success"
        existing.error = None
        existing.trigger = trigger

    await session.commit()
    return FilingResult(
        item_type="meeting",
        item_ref=str(meeting.id),
        status="success",
        drive_doc_id=created["id"],
        drive_doc_url=created.get("webViewLink"),
    )


async def _record_failure(
    session: AsyncSession,
    existing: ProjectContextDoc | None,
    ctx: ProjectContext,
    meeting: Meeting,
    trigger: Trigger,
    error: str,
) -> FilingResult:
    """Persist a 'failed' row so the UI can show + retry, and roll up the
    error into the FilingResult."""
    if existing is None:
        row = ProjectContextDoc(
            project_context_id=ctx.id,
            item_type="meeting",
            item_ref=str(meeting.id),
            status="failed",
            error=error,
            trigger=trigger,
        )
        session.add(row)
    else:
        existing.status = "failed"
        existing.error = error
        existing.trigger = trigger
    await session.commit()
    log.warning(
        "handoff failed meeting_id=%s context_id=%s: %s", meeting.id, ctx.id, error
    )
    return FilingResult(
        item_type="meeting",
        item_ref=str(meeting.id),
        status="failed",
        error=error,
    )


# --- Ticket variant ---------------------------------------------------------


def _ticket_doc_name(ticket: dict, label: str) -> str:
    """`[Project Context Label] KEY - summary` (summary truncated to 80)."""
    summary = ticket.get("summary") or ""
    if len(summary) > 80:
        summary = summary[:77].rstrip() + "…"
    return f"[{label}] {ticket['key']} - {summary}"


def _ticket_doc_body(ticket: dict) -> str:
    """Self-contained body so claude.ai can identify the source from the Doc
    alone. Header with ticket meta + description + threaded comments."""
    lines: list[str] = [
        f"Ticket: {ticket.get('key', '')}",
        f"Summary: {ticket.get('summary', '')}",
    ]
    project = ticket.get("project") or {}
    if project.get("name"):
        lines.append(
            f"Project: {project.get('name', '')} ({project.get('key', '')})"
        )
    if ticket.get("type"):
        lines.append(f"Type: {ticket['type']}")
    if ticket.get("priority"):
        lines.append(f"Priority: {ticket['priority']}")
    if ticket.get("status"):
        lines.append(f"Status: {ticket['status']}")
    assignee = ticket.get("assignee") or {}
    if assignee.get("displayName"):
        email = assignee.get("email") or ""
        suffix = f" <{email}>" if email else ""
        lines.append(f"Assignee: {assignee['displayName']}{suffix}")
    if ticket.get("updatedAt"):
        lines.append(f"Updated: {ticket['updatedAt']}")

    out = "\n".join(lines) + "\n\n———\n\nDescription:\n\n"
    out += (ticket.get("description") or "(no description)").strip() + "\n"

    comments = ticket.get("comments") or []
    if comments:
        out += f"\n———\n\nComments ({len(comments)}):\n"
        for c in comments:
            author = (c.get("author") or {}).get("displayName") or "(unknown)"
            created = c.get("createdAt") or ""
            out += f"\n[{author} · {created}]\n"
            out += (c.get("body") or "").rstrip() + "\n"

    return out


async def file_ticket_to_context(
    session: AsyncSession,
    *,
    jira_key: str,
    project_context_id: int,
    user_id: int,
    trigger: Trigger = "manual",
) -> FilingResult:
    """File a Jira ticket as a Google Doc into the Project Context's folder.

    Idempotent by `(project_context_id, 'ticket', jira_key)`. Two upstream
    APIs are required: Atlassian to fetch the ticket text, Google to write
    the Doc. Both failures are persisted as `status='failed'` rows so the
    UI can show + retry.
    """
    ctx = await session.get(ProjectContext, project_context_id)
    if ctx is None:
        return FilingResult(
            item_type="ticket",
            item_ref=jira_key,
            status="failed",
            error=f"Project Context {project_context_id} not found",
        )

    # Dedupe — fast path
    existing_q = await session.execute(
        select(ProjectContextDoc).where(
            ProjectContextDoc.project_context_id == ctx.id,
            ProjectContextDoc.item_type == "ticket",
            ProjectContextDoc.item_ref == jira_key,
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing is not None and existing.status == "success":
        return FilingResult(
            item_type="ticket",
            item_ref=jira_key,
            status="skipped",
            drive_doc_id=existing.drive_doc_id,
            drive_doc_url=existing.drive_doc_url,
        )

    # Resolve the user's Atlassian cloud_id
    cred_q = await session.execute(
        select(OAuthCredential).where(
            OAuthCredential.user_id == user_id,
            OAuthCredential.provider == "atlassian",
        )
    )
    cred = cred_q.scalar_one_or_none()
    if cred is None or not cred.atlassian_cloud_id:
        return await _record_ticket_failure(
            session, existing, ctx, jira_key, trigger, "atlassian: not connected"
        )

    # Atlassian token + ticket fetch
    try:
        atlassian_token = await get_valid_atlassian_token(session, user_id)
    except AtlassianAuthError as exc:
        return await _record_ticket_failure(
            session, existing, ctx, jira_key, trigger, f"atlassian: {exc}"
        )

    try:
        ticket = await get_issue(atlassian_token, cred.atlassian_cloud_id, jira_key)
    except AtlassianAuthError as exc:
        return await _record_ticket_failure(
            session, existing, ctx, jira_key, trigger, f"jira: {exc}"
        )

    # Google token + Doc upload
    try:
        google_token = await get_valid_google_token(session, user_id)
    except GoogleAuthError as exc:
        return await _record_ticket_failure(
            session, existing, ctx, jira_key, trigger, f"google: {exc}"
        )

    try:
        created = await create_drive_doc(
            google_token,
            _ticket_doc_name(ticket, ctx.label),
            ctx.drive_folder_id,
            _ticket_doc_body(ticket),
        )
    except DriveAccessError as exc:
        return await _record_ticket_failure(
            session, existing, ctx, jira_key, trigger, f"drive: {exc}"
        )

    # Upsert success row
    if existing is None:
        row = ProjectContextDoc(
            project_context_id=ctx.id,
            item_type="ticket",
            item_ref=jira_key,
            drive_doc_id=created["id"],
            drive_doc_url=created.get("webViewLink"),
            status="success",
            error=None,
            trigger=trigger,
        )
        session.add(row)
    else:
        existing.drive_doc_id = created["id"]
        existing.drive_doc_url = created.get("webViewLink")
        existing.status = "success"
        existing.error = None
        existing.trigger = trigger

    await session.commit()
    return FilingResult(
        item_type="ticket",
        item_ref=jira_key,
        status="success",
        drive_doc_id=created["id"],
        drive_doc_url=created.get("webViewLink"),
    )


async def _record_ticket_failure(
    session: AsyncSession,
    existing: ProjectContextDoc | None,
    ctx: ProjectContext,
    jira_key: str,
    trigger: Trigger,
    error: str,
) -> FilingResult:
    if existing is None:
        row = ProjectContextDoc(
            project_context_id=ctx.id,
            item_type="ticket",
            item_ref=jira_key,
            status="failed",
            error=error,
            trigger=trigger,
        )
        session.add(row)
    else:
        existing.status = "failed"
        existing.error = error
        existing.trigger = trigger
    await session.commit()
    log.warning(
        "handoff failed ticket=%s context_id=%s: %s", jira_key, ctx.id, error
    )
    return FilingResult(
        item_type="ticket",
        item_ref=jira_key,
        status="failed",
        error=error,
    )

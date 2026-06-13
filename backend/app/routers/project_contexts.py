"""
Project Context registry endpoints.

A "Project Context" is a registry row: label + one Drive folder. Noted
files Google Docs into that folder; the user adds the Doc to their
claude.ai Project once (auto-syncs thereafter).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import ProjectContext, ProjectContextDoc, User
from ..services.google import (
    DriveAccessError,
    GoogleAuthError,
    create_drive_folder,
    get_drive_folder,
    get_valid_google_token,
    search_drive_folders,
    trash_drive_file,
)
from ..services.handoff import file_meeting_to_context, file_ticket_to_context


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/project-contexts", tags=["project-contexts"])


# --- request/response models --------------------------------------------------


class CreateProjectContextBody(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    mode: Literal["create", "existing"]
    folder_id: str | None = Field(default=None, max_length=128, alias="folderId")

    model_config = {"populate_by_name": True}


def _serialize(ctx: ProjectContext, doc_count: int) -> dict[str, Any]:
    return {
        "id": ctx.id,
        "label": ctx.label,
        "driveFolderId": ctx.drive_folder_id,
        "driveFolderUrl": ctx.drive_folder_url,
        "docCount": doc_count,
        "createdAt": ctx.created_at.isoformat(),
    }


# --- routes -------------------------------------------------------------------


@router.get("")
async def list_project_contexts(
    _user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    # Aggregate successful doc count per Project Context in one query.
    doc_count_subq = (
        select(
            ProjectContextDoc.project_context_id,
            func.count(ProjectContextDoc.id).label("n"),
        )
        .where(ProjectContextDoc.status == "success")
        .group_by(ProjectContextDoc.project_context_id)
        .subquery()
    )
    result = await session.execute(
        select(ProjectContext, doc_count_subq.c.n)
        .outerjoin(
            doc_count_subq,
            doc_count_subq.c.project_context_id == ProjectContext.id,
        )
        .order_by(ProjectContext.created_at.desc())
    )
    return [_serialize(ctx, n or 0) for (ctx, n) in result.all()]


@router.post("", status_code=201)
async def create_project_context(
    body: CreateProjectContextBody,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        token = await get_valid_google_token(session, user.id)
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    # Label uniqueness check (DB has a unique constraint as a safety net,
    # but a friendly 409 beats a generic 500)
    existing = await session.execute(
        select(ProjectContext).where(ProjectContext.label == body.label)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A Project Context with label {body.label!r} already exists.",
        )

    if body.mode == "create":
        try:
            folder = await create_drive_folder(token, body.label)
        except DriveAccessError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        folder_id = folder["id"]
        folder_url = folder.get("webViewLink")
    else:
        # mode == "existing"
        if not body.folder_id:
            raise HTTPException(
                status_code=400, detail="folderId is required when mode='existing'"
            )
        try:
            folder = await get_drive_folder(token, body.folder_id)
        except DriveAccessError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        folder_id = folder["id"]
        folder_url = folder.get("webViewLink")

        # Don't double-register the same folder
        dup = await session.execute(
            select(ProjectContext).where(ProjectContext.drive_folder_id == folder_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A Project Context is already mapped to that folder.",
            )

    ctx = ProjectContext(
        label=body.label,
        drive_folder_id=folder_id,
        drive_folder_url=folder_url,
        created_by_user_id=user.id,
    )
    session.add(ctx)
    await session.commit()
    await session.refresh(ctx)
    return _serialize(ctx, 0)


@router.delete("/{project_context_id}")
async def delete_project_context(
    project_context_id: int = Path(..., ge=1),
    delete_drive_folder: bool = Query(
        True,
        alias="deleteDriveFolder",
        description="If true (default), also move the mapped Drive folder to trash.",
    ),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    ctx = await session.get(ProjectContext, project_context_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Project Context not found")

    folder_id = ctx.drive_folder_id
    drive_trashed = False
    drive_error: str | None = None

    if delete_drive_folder:
        try:
            token = await get_valid_google_token(session, user.id)
            await trash_drive_file(token, folder_id)
            drive_trashed = True
        except GoogleAuthError as exc:
            drive_error = str(exc)
        except DriveAccessError as exc:
            # Most common cause: the folder was a "use existing" pick that
            # Noted doesn't have write access to delete. Tell the caller;
            # still remove the registry row.
            drive_error = str(exc)

    # Registry row goes regardless — that's the user's stated intent. If the
    # Drive folder couldn't be trashed, the response carries the error so the
    # UI can tell the user to clean up manually.
    await session.delete(ctx)
    await session.commit()

    return {
        "id": project_context_id,
        "driveFolderTrashed": drive_trashed,
        "driveFolderId": folder_id,
        "driveFolderError": drive_error,
    }


# --- filing (handoff entry point) --------------------------------------------


class FileItem(BaseModel):
    type: Literal["meeting", "ticket"]
    ref: str = Field(..., min_length=1, max_length=128)


class FileBody(BaseModel):
    items: list[FileItem] = Field(..., min_length=1, max_length=50)


@router.post("/{project_context_id}/file")
async def file_into_context(
    body: FileBody,
    project_context_id: int = Path(..., ge=1),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """File a batch of items into one Project Context. Each item is filed
    independently — a failure on one doesn't abort the others; the per-item
    status comes back in the response."""
    # Verify the context exists upfront so the caller gets a 404 rather than
    # per-item failures.
    ctx = await session.get(ProjectContext, project_context_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Project Context not found")

    results: list[dict[str, Any]] = []
    for item in body.items:
        if item.type == "ticket":
            result = await file_ticket_to_context(
                session,
                jira_key=item.ref,
                project_context_id=project_context_id,
                user_id=user.id,
                trigger="manual",
            )
        else:
            try:
                meeting_id = int(item.ref)
            except ValueError:
                results.append(
                    {
                        "type": item.type,
                        "ref": item.ref,
                        "status": "failed",
                        "error": "meeting ref must be a numeric id",
                    }
                )
                continue
            result = await file_meeting_to_context(
                session,
                meeting_id=meeting_id,
                project_context_id=project_context_id,
                user_id=user.id,
                trigger="manual",
            )
        results.append(
            {
                "type": result.item_type,
                "ref": result.item_ref,
                "status": result.status,
                "driveDocId": result.drive_doc_id,
                "driveDocUrl": result.drive_doc_url,
                "error": result.error,
            }
        )

    return {"projectContextId": project_context_id, "results": results}


@router.delete("/{project_context_id}/docs/{doc_id}")
async def delete_filed_doc(
    project_context_id: int = Path(..., ge=1),
    doc_id: int = Path(..., ge=1),
    delete_drive_file: bool = Query(
        True,
        alias="deleteDriveFile",
        description="If true (default), also move the filed Google Doc to Drive trash.",
    ),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Remove one filed Doc: drops the project_context_docs row, and (by
    default) trashes the Google Doc in Drive too. Removing the row also
    clears the dedupe guard, so the user can re-file the same meeting into
    this context later if they change their mind."""
    doc = await session.get(ProjectContextDoc, doc_id)
    if doc is None or doc.project_context_id != project_context_id:
        raise HTTPException(status_code=404, detail="Filed Doc not found")

    drive_file_id = doc.drive_doc_id
    drive_trashed = False
    drive_error: str | None = None

    if delete_drive_file and drive_file_id:
        try:
            token = await get_valid_google_token(session, user.id)
            await trash_drive_file(token, drive_file_id)
            drive_trashed = True
        except GoogleAuthError as exc:
            drive_error = str(exc)
        except DriveAccessError as exc:
            # Mirrors the context-delete behaviour: row goes regardless,
            # error is surfaced so the user can clean up Drive manually.
            drive_error = str(exc)

    await session.delete(doc)
    await session.commit()
    return {
        "id": doc_id,
        "driveTrashed": drive_trashed,
        "driveDocId": drive_file_id,
        "driveError": drive_error,
    }


@router.get("/{project_context_id}/docs")
async def list_filed_docs(
    project_context_id: int = Path(..., ge=1),
    _user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Filed-doc records for one Project Context (used by 'Filed' badges + the
    context detail page)."""
    ctx = await session.get(ProjectContext, project_context_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Project Context not found")

    result = await session.execute(
        select(ProjectContextDoc)
        .where(ProjectContextDoc.project_context_id == project_context_id)
        .order_by(ProjectContextDoc.created_at.desc())
    )
    out: list[dict[str, Any]] = []
    for row in result.scalars().all():
        out.append(
            {
                "id": row.id,
                "itemType": row.item_type,
                "itemRef": row.item_ref,
                "driveDocId": row.drive_doc_id,
                "driveDocUrl": row.drive_doc_url,
                "status": row.status,
                "error": row.error,
                "trigger": row.trigger,
                "createdAt": row.created_at.isoformat(),
                "updatedAt": row.updated_at.isoformat(),
            }
        )
    return out


# --- drive folder search ------------------------------------------------------


drive_router = APIRouter(prefix="/api/drive", tags=["drive"])


@drive_router.get("/folders")
async def search_folders(
    q: str = Query(..., min_length=1, max_length=128),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Search the user's Drive for folders whose name contains `q`. Used by
    the 'Use existing folder' picker in the Create-Project-Context dialog."""
    try:
        token = await get_valid_google_token(session, user.id)
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    try:
        results = await search_drive_folders(token, q)
    except DriveAccessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return [
        {"id": f["id"], "name": f["name"], "url": f.get("webViewLink")}
        for f in results
    ]

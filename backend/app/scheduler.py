"""
Periodic + one-shot ingestion scheduler.

We use APScheduler's AsyncIOScheduler since it shares FastAPI's event loop
cleanly. The scheduler runs `run_sync_for_all_users` on an interval (every
SYNC_INTERVAL_MINUTES) and, when SYNC_RUN_ON_STARTUP is set, also fires
that same job once shortly after boot so a fresh dev server doesn't sit
idle until the first tick.

Each user is synced in its own AsyncSession so a per-user failure can't
poison the rest of the pass.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .models import OAuthCredential
from .services.sync import sync_user


log = logging.getLogger(__name__)


async def run_sync_for_all_users() -> None:
    """List every user with a Google credential and sync them, one by one."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(OAuthCredential.user_id).where(OAuthCredential.provider == "google")
        )
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        log.info("scheduler: no Google-connected users; nothing to do")
        return

    log.info("scheduler: starting sync for %d user(s)", len(user_ids))
    for user_id in user_ids:
        async with SessionLocal() as session:
            try:
                summary = await sync_user(session, user_id)
                log.info(
                    "scheduler: user_id=%s series=%s meetings=%s skipped=%s matched=%s errors=%d",
                    user_id,
                    summary.series_upserted,
                    summary.meetings_upserted,
                    summary.meetings_skipped,
                    summary.calendar_matched,
                    len(summary.errors),
                )
                if summary.errors:
                    for err in summary.errors:
                        log.warning("scheduler: user_id=%s err=%s", user_id, err)
            except Exception:  # noqa: BLE001 — top-level safety net
                log.exception("scheduler: unhandled error for user_id=%s", user_id)


def build_scheduler() -> AsyncIOScheduler | None:
    """Create and configure (but do not start) the scheduler. Returns None
    if sync is disabled via env."""
    settings = get_settings()
    if not settings.sync_enabled:
        log.info("scheduler: SYNC_ENABLED=false, scheduler disabled")
        return None

    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        run_sync_for_all_users,
        trigger=IntervalTrigger(minutes=settings.sync_interval_minutes),
        id="periodic-sync",
        coalesce=True,         # if we missed several ticks, run once not N times
        max_instances=1,       # never overlap a slow run with the next tick
        misfire_grace_time=60,
        replace_existing=True,
    )

    if settings.sync_run_on_startup:
        # Slight delay so the app finishes booting (and the user can hit the
        # logs) before the first job fires.
        scheduler.add_job(
            run_sync_for_all_users,
            trigger=DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=5)),
            id="startup-sync",
            replace_existing=True,
        )

    return scheduler

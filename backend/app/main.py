import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .routers import auth_atlassian, auth_google, files, me, sync
from .scheduler import build_scheduler


log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = build_scheduler()
    if scheduler is not None:
        scheduler.start()
        log.info(
            "scheduler started: periodic every %d min, startup-once=%s",
            get_settings().sync_interval_minutes,
            get_settings().sync_run_on_startup,
        )
    try:
        yield
    finally:
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Noted API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="noted_session",
        same_site="lax",
        https_only=not settings.is_local,
        max_age=60 * 60 * 24 * 14,  # 14 days
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_google.router)
    app.include_router(auth_atlassian.router)
    app.include_router(me.router)
    app.include_router(sync.router)
    app.include_router(files.router)

    @app.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

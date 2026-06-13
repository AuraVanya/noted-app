from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .routers import auth_atlassian, auth_google, me


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Noted API", version="0.1.0")

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

    @app.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

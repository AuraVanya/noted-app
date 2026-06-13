import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="session", autouse=True)
def _env():
    """Use an isolated SQLite file + dummy secrets for the test session."""
    tmpdir = tempfile.mkdtemp(prefix="noted-test-")
    db_path = Path(tmpdir) / "test.db"
    os.environ.setdefault("APP_ENV", "local")
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    os.environ.setdefault("SESSION_SECRET", "test-session-secret-test-session-secret")
    # Generated once: a valid Fernet key for tests
    os.environ.setdefault("TOKEN_ENC_KEY", "zmWl5eR8tQ3OTbq4nQO1V7pX8h_VqzN1d2J3sV0kZ9I=")
    os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
    os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
    yield


@pytest_asyncio.fixture()
async def client():
    # Import here so env is set first
    from app.db import Base, engine
    from app.main import app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

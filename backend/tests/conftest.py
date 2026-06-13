"""
Test isolation hinges on env vars being set *before* any `from app.…`
import — `app/db.py` builds the engine at import time, and pytest imports
test files (which import app modules) during collection, before fixtures
run. So we do the env setup at conftest module top, not inside a fixture.

The `.env` file at `backend/.env` is ignored: pydantic-settings reads env
vars first, dotenv file second, so our values win.
"""

import os
import tempfile
from pathlib import Path


# --- Env isolation (must run before any `from app...` import) ----------------

_TMPDIR = Path(tempfile.mkdtemp(prefix="noted-test-"))
_TEST_DB_PATH = _TMPDIR / "test.db"

# Unconditional assignment — refuse to inherit a real DATABASE_URL from the
# developer's shell or .env file. A test run must never touch noted.db.
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ["APP_ENV"] = "local"
os.environ["SESSION_SECRET"] = "test-session-secret-test-session-secret"
# Pre-generated valid Fernet key, used only by tests
os.environ["TOKEN_ENC_KEY"] = "zmWl5eR8tQ3OTbq4nQO1V7pX8h_VqzN1d2J3sV0kZ9I="
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["FILE_URL_SECRET"] = "test-file-url-secret-test-file-url-secret"
# Scheduler off by default for tests — the few tests that exercise it set
# this back to true via monkeypatch.
os.environ["SYNC_ENABLED"] = "false"
os.environ["SYNC_RUN_ON_STARTUP"] = "false"

# Defensive: clear settings cache in case anything imported app.config
# before conftest was loaded (shouldn't happen, but cheap insurance).
from app.config import get_settings  # noqa: E402 — must follow env setup
get_settings.cache_clear()


# --- Fixtures ----------------------------------------------------------------

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _confirm_isolation():
    """
    Hard guard: assert at session start that the engine isn't pointing at
    the dev DB. If a future refactor breaks the env-set ordering above,
    this fails fast instead of corrupting state.
    """
    from app.db import engine

    url = str(engine.url)
    assert "noted.db" not in url, (
        f"Test engine resolved to {url!r}; refusing to run tests "
        "that could write to the dev database."
    )
    assert str(_TEST_DB_PATH) in url, (
        f"Test engine should point at {_TEST_DB_PATH}, got {url!r}"
    )
    yield


@pytest_asyncio.fixture()
async def client():
    # Import here so env is set first (and the assertion fixture has run)
    from app.db import Base, engine
    from app.main import app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

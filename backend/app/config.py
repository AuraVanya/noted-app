from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    frontend_url: str = "http://localhost:5173"

    database_url: str = "sqlite+aiosqlite:///./noted.db"

    session_secret: str = Field(..., min_length=16)
    token_enc_key: str = Field(..., min_length=16)

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    google_scopes: tuple[str, ...] = (
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
        # Phase 4: write Docs into project context folders. Least-privilege
        # write scope — only grants access to files Noted itself creates.
        # Existing user sessions lack this scope; they re-consent on next
        # sign-in.
        "https://www.googleapis.com/auth/drive.file",
    )

    # --- Atlassian (Phase 5 Jira read + Phase 6 Confluence read/write) ---
    atlassian_client_id: str = ""
    atlassian_client_secret: str = ""
    atlassian_redirect_uri: str = "http://localhost:8000/api/auth/atlassian/callback"
    atlassian_scopes: tuple[str, ...] = (
        # Jira read (Phase 5)
        "read:jira-work",
        "read:jira-user",
        # Confluence read/write (Phase 6 — bundled now to avoid a re-consent)
        "read:confluence-content.all",
        "write:confluence-content",
        "read:confluence-space.summary",
        # Refresh tokens
        "offline_access",
    )

    # Phase 2 — Drive folder IDs for ingestion
    drive_summaries_folder_id: str = ""
    drive_transcripts_folder_id: str = ""

    # Phase 2 — signed file proxy URLs (separate from session secret so they
    # can be rotated independently)
    file_url_secret: str = ""
    file_url_ttl_seconds: int = 600  # 10 minutes

    # Phase 2 — scheduler
    sync_enabled: bool = True
    sync_interval_minutes: int = 10
    sync_run_on_startup: bool = True

    # --- Demo mode (read-time allowlists) ---
    # Comma-separated. Empty = no filter (default). Case-insensitive.
    # The sync job still ingests everything; these filters apply at API
    # read time so filtered data never reaches the client.
    demo_meeting_title_prefixes: str = ""
    demo_jira_project_names: str = ""

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"

    @property
    def demo_meeting_prefixes_list(self) -> list[str]:
        return [
            p.strip().upper()
            for p in self.demo_meeting_title_prefixes.split(",")
            if p.strip()
        ]

    @property
    def demo_jira_projects_list(self) -> list[str]:
        return [
            p.strip().lower()
            for p in self.demo_jira_project_names.split(",")
            if p.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

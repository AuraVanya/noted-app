"""
Demo-mode read-time allowlists.

These are intentionally lightweight: env-var-driven, case-insensitive
prefix/exact matches, all-or-nothing. Set the env vars in `backend/.env`
when demoing; leave them blank in normal operation.
"""

from __future__ import annotations

from ..config import get_settings


def meeting_title_visible(title: str) -> bool:
    """True if `title` passes the demo prefix allowlist (or if the
    allowlist is empty / disabled)."""
    prefixes = get_settings().demo_meeting_prefixes_list
    if not prefixes:
        return True
    upper = (title or "").upper()
    return any(upper.startswith(p) for p in prefixes)


def jira_project_visible(project_name: str) -> bool:
    """True if `project_name` matches one of the allowed names exactly
    (case-insensitive), or if the allowlist is empty / disabled."""
    allow = get_settings().demo_jira_projects_list
    if not allow:
        return True
    return (project_name or "").lower() in allow

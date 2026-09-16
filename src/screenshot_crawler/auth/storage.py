"""Locate and validate Playwright authentication state files.

The state file contains credentials such as cookies and local storage. This
module deliberately never reads or logs its contents; it only handles the
path and existence checks needed by Playwright.
"""

from __future__ import annotations

from pathlib import Path

from screenshot_crawler.core.errors import AuthenticationStateNotFoundError

DEFAULT_AUTH_DIR = Path(".auth")
AUTH_STATE_NOT_FOUND_MESSAGE = (
    "Authentication state not found.\n"
    "Run save_auth first."
)


def _validate_site_name(site_name: str) -> str:
    if not site_name or site_name in {".", ".."}:
        raise ValueError("site_name must be a non-empty filename stem")

    # Authentication state paths are intentionally restricted to one file
    # below the auth directory. This prevents a site name from escaping it.
    if Path(site_name).name != site_name or any(char in site_name for char in "\\/"):
        raise ValueError("site_name must not contain path separators")
    return site_name


def auth_state_path(
    site_name: str,
    *,
    auth_dir: str | Path = DEFAULT_AUTH_DIR,
) -> Path:
    """Return the state path for ``site_name`` without reading the file."""

    return Path(auth_dir) / f"{_validate_site_name(site_name)}.json"


def require_auth_state(
    site_name: str,
    *,
    auth_dir: str | Path = DEFAULT_AUTH_DIR,
) -> Path:
    """Return an existing state path or raise the user-facing auth error."""

    path = auth_state_path(site_name, auth_dir=auth_dir)
    if not path.is_file():
        raise AuthenticationStateNotFoundError(AUTH_STATE_NOT_FOUND_MESSAGE)
    return path

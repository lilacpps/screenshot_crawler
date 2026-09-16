"""Small, dependency-free .env reader for local command configuration."""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def read_env_file(path: str | Path) -> dict[str, str]:
    """Read simple ``KEY=VALUE`` entries without logging their values."""

    env_path = Path(path)
    if not env_path.is_file():
        raise FileNotFoundError(f"Environment file not found: {env_path}")

    values: dict[str, str] = {}
    for line_number, line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            raise ValueError(f"Invalid environment entry at {env_path}:{line_number}")
        name, raw_value = stripped.split("=", 1)
        name = name.strip()
        if not _ENV_NAME.fullmatch(name):
            raise ValueError(f"Invalid environment variable name at {env_path}:{line_number}")
        values[name] = _parse_value(raw_value)
    return values


def env_value(name: str, values: dict[str, str], *, default: str | None = None) -> str | None:
    """Return a process environment value, falling back to the .env value."""

    return os.environ.get(name) or values.get(name) or default


def require_env_value(name: str, values: dict[str, str]) -> str:
    value = env_value(name, values)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def site_env_name(site: str, suffix: str) -> str:
    """Build a site-scoped environment variable name safely."""

    site_key = site.strip().upper()
    suffix_key = suffix.strip().upper()
    if not _ENV_NAME.fullmatch(site_key) or not _ENV_NAME.fullmatch(suffix_key):
        raise ValueError("site and environment suffix must contain letters, digits, or underscores")
    return f"{site_key}_{suffix_key}"


def require_site_env_value(site: str, suffix: str, values: dict[str, str]) -> str:
    """Return a required value such as ``BOOKWALKER_EMAIL``."""

    return require_env_value(site_env_name(site, suffix), values)

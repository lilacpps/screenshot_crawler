"""Runtime settings loaded outside the crawler Core."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PAGE_TURN_DELAY_MS = 1000
DEFAULT_INTER_CANDIDATE_DELAY_MS = 3000


@dataclass(frozen=True, slots=True)
class SiteRuntimeSettings:
    """Resolved settings for one site without any site-specific behavior."""

    page_turn_delay_ms: int = DEFAULT_PAGE_TURN_DELAY_MS
    inter_candidate_delay_ms: int = DEFAULT_INTER_CANDIDATE_DELAY_MS
    stop_on_http_403: bool = True
    stop_on_http_429: bool = True
    stop_on_challenge: bool = True
    stop_on_captcha: bool = True
    work_ticket_cooldown_hours: int | None = None


@dataclass(frozen=True, slots=True)
class CrawlerRuntimeSettings:
    """Parsed crawler.yaml settings and the default resolution policy."""

    sites: dict[str, SiteRuntimeSettings]

    def for_site(self, site: str) -> SiteRuntimeSettings:
        """Return configured settings, falling back to safe code defaults."""

        return self.sites.get(site, SiteRuntimeSettings())


def load_runtime_settings(path: str | Path = "crawler.yaml") -> CrawlerRuntimeSettings:
    """Load and validate a root crawler.yaml file.

    A missing file is intentionally equivalent to an empty configuration. YAML
    that exists but has an invalid shape or value fails explicitly instead of
    silently disabling pacing.
    """

    config_path = Path(path)
    if not config_path.is_file():
        return CrawlerRuntimeSettings(sites={})
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeSettingsError(f"Could not read runtime settings: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise RuntimeSettingsError(f"Invalid YAML in runtime settings: {config_path}") from exc

    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise RuntimeSettingsError("crawler.yaml root must be a mapping")
    sites = payload.get("sites", {})
    if not isinstance(sites, dict):
        raise RuntimeSettingsError("crawler.yaml 'sites' must be a mapping")

    resolved: dict[str, SiteRuntimeSettings] = {}
    for site, raw_settings in sites.items():
        if not isinstance(site, str) or not site.strip():
            raise RuntimeSettingsError("crawler.yaml site names must be non-empty strings")
        if raw_settings is None:
            raw_settings = {}
        if not isinstance(raw_settings, dict):
            raise RuntimeSettingsError(f"crawler.yaml site entry {site!r} must be a mapping")
        resolved[site] = _resolve_site_settings(site, raw_settings)
    return CrawlerRuntimeSettings(sites=resolved)


class RuntimeSettingsError(ValueError):
    """Raised when crawler.yaml contains an invalid runtime setting."""


def _resolve_site_settings(site: str, raw: dict[Any, Any]) -> SiteRuntimeSettings:
    values: dict[str, Any] = {}
    for field_name in SiteRuntimeSettings.__dataclass_fields__:
        if field_name not in raw:
            continue
        value = raw[field_name]
        if field_name.endswith("_delay_ms") or field_name == "work_ticket_cooldown_hours":
            values[field_name] = _non_negative_int(value, f"sites.{site}.{field_name}")
        else:
            if not isinstance(value, bool):
                raise RuntimeSettingsError(
                    f"sites.{site}.{field_name} must be a boolean"
                )
            values[field_name] = value
    return SiteRuntimeSettings(**values)


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeSettingsError(f"{field_name} must be a non-negative integer")
    if value < 0:
        raise RuntimeSettingsError(f"{field_name} must be a non-negative integer")
    return value


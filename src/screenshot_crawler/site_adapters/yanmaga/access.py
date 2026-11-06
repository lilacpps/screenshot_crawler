"""Yanmaga-owned host classification for the shared access guard."""

from __future__ import annotations

from urllib.parse import urlsplit

from screenshot_crawler.core.access_guard import AccessProfile

YANMAGA_RELEVANT_HOSTS = frozenset({"yanmaga.jp"})


def is_yanmaga_relevant_host(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower() in YANMAGA_RELEVANT_HOSTS
    except ValueError:
        return False


def yanmaga_access_profile() -> AccessProfile:
    """Keep the observed first-party viewer under shared access guards."""

    return AccessProfile(relevant_host=is_yanmaga_relevant_host)

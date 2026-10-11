"""Hanayume host classification for the shared access guard."""

from __future__ import annotations

from urllib.parse import urlsplit

from screenshot_crawler.core.access_guard import AccessProfile

HANAYUME_RELEVANT_HOSTS = frozenset(
    {"hanayume.com", "www.hanayume.com", "viewer.hanayume.com"}
)


def is_hanayume_relevant_host(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower() in HANAYUME_RELEVANT_HOSTS
    except ValueError:
        return False


def hanayume_access_profile() -> AccessProfile:
    return AccessProfile(relevant_host=is_hanayume_relevant_host)

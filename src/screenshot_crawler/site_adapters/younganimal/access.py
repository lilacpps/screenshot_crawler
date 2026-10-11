"""Younganimal host and challenge signals for the shared AccessGuard."""

from __future__ import annotations

from urllib.parse import urlsplit

from screenshot_crawler.core.access_guard import AccessProfile

YOUNGANIMAL_RELEVANT_HOSTS = frozenset(
    {
        "younganimal.com",
        "viewer.younganimal.com",
        "cdn-public.comici.jp",
    }
)


def is_younganimal_relevant_host(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower() in YOUNGANIMAL_RELEVANT_HOSTS
    except ValueError:
        return False


def younganimal_access_profile() -> AccessProfile:
    return AccessProfile(relevant_host=is_younganimal_relevant_host)


__all__ = [
    "YOUNGANIMAL_RELEVANT_HOSTS",
    "is_younganimal_relevant_host",
    "younganimal_access_profile",
]

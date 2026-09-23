"""Manga ONE-owned access host classification."""

from __future__ import annotations

from urllib.parse import urlparse

from screenshot_crawler.core.access_guard import AccessProfile

MANGAONE_RELEVANT_HOSTS = frozenset(
    {
        "manga-one.com",
        "www.manga-one.com",
        "app.manga-one.com",
    }
)


def is_mangaone_relevant_host(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in MANGAONE_RELEVANT_HOSTS


def mangaone_access_profile() -> AccessProfile:
    """Known viewer and content hosts; no unverified DOM hook."""

    return AccessProfile(relevant_host=is_mangaone_relevant_host)

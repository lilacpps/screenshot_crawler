"""Piccoma-owned host classification for shared access guards."""

from __future__ import annotations

from urllib.parse import urlsplit

from screenshot_crawler.core.access_guard import AccessProfile

PICCOMA_RELEVANT_HOSTS = frozenset(
    {"piccoma.com", "www.piccoma.com", "pcm.kakaocdn.net"}
)


def is_piccoma_relevant_host(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower() in PICCOMA_RELEVANT_HOSTS
    except ValueError:
        return False


def piccoma_access_profile() -> AccessProfile:
    """Keep Piccoma and its observed body-image host under shared guards."""

    return AccessProfile(relevant_host=is_piccoma_relevant_host)

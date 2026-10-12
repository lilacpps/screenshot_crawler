"""AccessGuard host scope for the observed Kadocomi WEB surface."""

from __future__ import annotations

from urllib.parse import urlsplit

from screenshot_crawler.core.access_guard import AccessProfile


def is_kadocomi_relevant_host(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower() == "comic-walker.com"
    except ValueError:
        return False


def kadocomi_access_profile() -> AccessProfile:
    return AccessProfile(relevant_host=is_kadocomi_relevant_host)


__all__ = ["is_kadocomi_relevant_host", "kadocomi_access_profile"]

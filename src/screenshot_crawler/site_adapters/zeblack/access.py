"""Zeblack-owned access host classification."""

from __future__ import annotations

from urllib.parse import urlsplit

from screenshot_crawler.core.access_guard import AccessProfile

ZEBLACK_RELEVANT_HOSTS = frozenset(
    {
        "zebrack-comic.shueisha.co.jp",
        "asset.zebrack-comic.com",
    }
)


def _url_host(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme == "blob":
        parsed = urlsplit(parsed.path)
    return (parsed.hostname or "").lower() or None


def is_zeblack_relevant_host(url: str) -> bool:
    """Return whether an observed response belongs to a known Zeblack host."""

    return _url_host(url) in ZEBLACK_RELEVANT_HOSTS


def zeblack_access_profile() -> AccessProfile:
    """Expose only the verified viewer/content hosts.

    Z3 intentionally has no Zeblack-specific challenge or login detector.
    """

    return AccessProfile(relevant_host=is_zeblack_relevant_host)

"""Magapoke-owned access host classification."""

from __future__ import annotations

from urllib.parse import urlparse

from screenshot_crawler.core.access_guard import AccessProfile

MAGAPOKE_RELEVANT_HOSTS = frozenset(
    {
        "pocket.shonenmagazine.com",
        "mgpk-cdn.magazinepocket.com",
    }
)


def is_magapoke_relevant_host(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in MAGAPOKE_RELEVANT_HOSTS


def magapoke_access_profile() -> AccessProfile:
    """Known first-party viewer/API/image hosts; no unverified DOM hook."""

    return AccessProfile(relevant_host=is_magapoke_relevant_host)

"""BookWalker-owned access host classification."""

from __future__ import annotations

from urllib.parse import urlparse

from screenshot_crawler.core.access_guard import AccessProfile

BOOKWALKER_RELEVANT_HOSTS = frozenset(
    {
        "bookwalker.jp",
        "www.bookwalker.jp",
        "viewer.bookwalker.jp",
        "trial.bookwalker.jp",
        "bw-bv-epubs.bookwalker.jp",
    }
)


def is_bookwalker_relevant_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in BOOKWALKER_RELEVANT_HOSTS or (
        host.startswith("viewer-epubs") and host.endswith(".bookwalker.jp")
    )


def bookwalker_access_profile() -> AccessProfile:
    """Known product/viewer/content hosts; no unverified DOM hook."""

    return AccessProfile(relevant_host=is_bookwalker_relevant_host)

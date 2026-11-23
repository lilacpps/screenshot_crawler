"""HERO'S WEB host matching for the shared fail-safe AccessGuard."""

from __future__ import annotations

from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.core.access_guard import AccessProfile

HEROSWEB_RELEVANT_HOSTS = frozenset(
    {
        "heros-web.com",
        "comicsviewer.heros-web.com",
        "cdn-public.comici.jp",
    }
)


def is_herosweb_relevant_host(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower() in HEROSWEB_RELEVANT_HOSTS
    except ValueError:
        return False


async def herosweb_challenge_signal(page: Page) -> str | None:
    """Recognize only explicit Cloudflare challenge document markers."""

    for selector in ("#challenge-running", "#challenge-stage", "form#challenge-form"):
        try:
            locator = page.locator(selector)
            if await locator.count() and await locator.first.is_visible():
                return f"cloudflare:{selector}"
        except PlaywrightError:
            continue
    return None


def herosweb_access_profile() -> AccessProfile:
    return AccessProfile(
        relevant_host=is_herosweb_relevant_host,
        challenge_detector=herosweb_challenge_signal,
    )


__all__ = [
    "HEROSWEB_RELEVANT_HOSTS",
    "herosweb_access_profile",
    "herosweb_challenge_signal",
    "is_herosweb_relevant_host",
]

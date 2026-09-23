"""Jump+ access classification owned by the site adapter."""

from urllib.parse import urlparse

from screenshot_crawler.core.access_guard import AccessProfile

JUMPPLUS_RELEVANT_HOSTS = frozenset(
    {
        "shonenjumpplus.com",
        "www.shonenjumpplus.com",
        "cdn-ak-img.shonenjumpplus.com",
        "cdn-ak.shonenjumpplus.com",
    }
)


def is_jumpplus_relevant_host(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "").lower() in JUMPPLUS_RELEVANT_HOSTS
    except ValueError:
        return False


def jumpplus_access_profile() -> AccessProfile:
    # Generic 403/429/challenge/captcha handling remains in AccessGuard.  No
    # Jump+-specific challenge signal has been observed in the PoC runs.
    return AccessProfile(relevant_host=is_jumpplus_relevant_host)

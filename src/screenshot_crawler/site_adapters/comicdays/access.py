"""Comic DAYS access classification."""

from urllib.parse import urlparse

from screenshot_crawler.core.access_guard import AccessProfile

COMICDAYS_RELEVANT_HOSTS = frozenset(
    {"comic-days.com", "www.comic-days.com", "cdn.comic-days.com", "cdn-img.comic-days.com"}
)


def is_comicdays_relevant_host(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "").lower() in COMICDAYS_RELEVANT_HOSTS
    except ValueError:
        return False


def comicdays_access_profile() -> AccessProfile:
    return AccessProfile(relevant_host=is_comicdays_relevant_host)

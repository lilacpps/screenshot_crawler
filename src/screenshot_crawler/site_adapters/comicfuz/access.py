"""ComicFUZ access-profile helpers for anonymous public reading."""

from __future__ import annotations

from urllib.parse import urlparse

from screenshot_crawler.core.access_guard import AccessProfile


def comicfuz_access_profile() -> AccessProfile:
    """Watch only the public site and the observed image host."""

    def relevant_host(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        return parsed.scheme.lower() == "https" and parsed.hostname in {
            "comic-fuz.com",
            "img.comic-fuz.com",
            "api.comic-fuz.com",
        }

    return AccessProfile(relevant_host=relevant_host)

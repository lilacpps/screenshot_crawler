"""Bounded, site-neutral URL checks. No network, Catalog or Watchlist access."""

import re
from dataclasses import replace
from urllib.parse import urlsplit

from screenshot_crawler.discovery.registry import DiscoveryAdapterRegistry
from screenshot_crawler.registration.models import UrlResolution

MAX_URLS = 100
MAX_URL_LENGTH = 4096
MAX_INPUT_BYTES = 256 * 1024


def safe_url(url: str) -> str:
    if (not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH
            or re.search(r"[\s\\\x00-\x20\x7f]", url) or "%" in url or ";" in url):
        raise ValueError("URLに空白・制御文字・曖昧なエスケープがあります")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment or "#" in url
            or parsed.netloc not in (parsed.hostname, parsed.hostname + ":443")
            or url.endswith("?")):
        raise ValueError("HTTPSの公式URLのみ対応しています（認証情報・fragment・任意port不可）")
    return parsed.hostname


class UrlResolver:
    def __init__(self, registry: DiscoveryAdapterRegistry):
        self.registry = registry

    def resolve(self, url: str) -> UrlResolution:
        try:
            host = safe_url(url)
            matches = [(site, self.registry.create(site)) for site in self.registry.sites()]
            matches = [(site, adapter) for site, adapter in matches
                       if host in adapter.registration_hosts]
            if len(matches) != 1:
                raise ValueError("未対応の公式hostです。対応サイトのDiscovery起点URLを指定してください")
            site, adapter = matches[0]
            result = replace(adapter.resolve_registration_url(url), site=site)
            if result.status != "blocked" and (not result.discovery_url
                    or safe_url(result.discovery_url) not in adapter.registration_hosts):
                raise ValueError("変換先URLが確定できません")
            return result
        except (ValueError, TypeError) as exc:
            return UrlResolution(input_url=url, blockers=(str(exc),))

    async def observe(self, page, resolution: UrlResolution) -> UrlResolution:
        """Page lifecycle belongs to the caller; default hooks never navigate."""
        fresh = self.resolve(resolution.input_url)
        if fresh.status == "blocked" or fresh != resolution:
            return fresh.blocked("URL解析結果が一致しません")
        return await self.registry.create(fresh.site).observe_registration_metadata(page, fresh)


def split_inputs(text: str) -> tuple[tuple[int, str], ...]:
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("貼付内容は256KiBまでです")
    rows = tuple((line, raw.strip()) for line, raw in enumerate(text.splitlines(), 1) if raw.strip())
    seen = set()
    unique = []
    for line, url in rows:
        if url not in seen:
            seen.add(url)
            unique.append((line, url))
    if len(rows) > MAX_URLS or any(len(url) > MAX_URL_LENGTH for _, url in rows):
        raise ValueError("1回100行、1URL 4096文字までです。分割して入力してください")
    return tuple(unique)

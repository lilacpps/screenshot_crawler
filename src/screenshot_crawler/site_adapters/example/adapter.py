"""Example only — not a real-site implementation.

Copy this package when starting a new adapter, then replace every placeholder
based on probe output and docs/SITE_ADAPTER_GUIDE.md.
"""

from screenshot_crawler.core.models import ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter


class ExampleAdapter(SiteAdapter):
    async def initialize(self, page):
        raise NotImplementedError("Example adapter is documentation only")

    async def detect_state(self, page) -> PageState:
        raise NotImplementedError("Implement from site observations")

    async def get_capture_target(self, page):
        raise NotImplementedError("Implement from site observations")

    async def get_content_identity(self, page) -> ContentIdentity:
        raise NotImplementedError("Implement from site observations")

    async def get_content_context(self, page) -> ContentContext:
        raise NotImplementedError("Implement from site observations")

    async def go_next(self, page) -> None:
        raise NotImplementedError("Implement from site observations")

    async def wait_for_change(self, page, previous_identity: ContentIdentity | None) -> None:
        raise NotImplementedError("Implement from site observations")

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from screenshot_crawler.core.models import ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


class SiteAdapter(ABC):
    """Contract implemented by each supported site.

    Site-specific selectors and behavior belong here, not in core.
    """

    async def prepare_page(self, page: Page) -> None:
        """Optionally install page hooks before the first navigation."""

        return

    @abstractmethod
    async def initialize(self, page: Page) -> None:
        """Prepare the viewer after navigation.

        Examples: dismiss cookie UI, switch to single-page mode, hide viewer chrome.
        """

    @abstractmethod
    async def detect_state(self, page: Page) -> PageState:
        """Classify the currently visible screen."""

    @abstractmethod
    async def get_capture_target(self, page: Page) -> Locator:
        """Return the locator whose rendered pixels should be saved for CONTENT."""

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        """Return one or more capture locators for the current screen.

        Most viewers expose one page and use the original target. A viewer
        that renders a spread may return multiple temporary, page-sized
        targets while keeping the decision inside the site adapter.
        """

        return (await self.get_capture_target(page),)

    async def cleanup_capture_targets(self, page: Page) -> None:
        """Remove temporary targets created by :meth:`get_capture_targets`."""

        return

    @abstractmethod
    async def get_content_identity(self, page: Page) -> ContentIdentity:
        """Return the strongest available identity for the current page."""

    @abstractmethod
    async def get_content_context(self, page: Page) -> ContentContext:
        """Return identity of the current work/episode/chapter."""

    @abstractmethod
    async def go_next(self, page: Page) -> None:
        """Perform one site-appropriate next-page action."""

    @abstractmethod
    async def wait_for_change(
        self,
        page: Page,
        previous_identity: ContentIdentity | None,
    ) -> None:
        """Wait until the previous screen has changed and rendering is stable enough."""

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        """Optional site-specific data appended to generic diagnostics."""
        return {}

    def get_output_metadata(self) -> dict[str, str | None]:
        """Return optional metadata used by the generic output organizer."""
        return {}

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import UnsupportedAccessStrategyError
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


@dataclass(frozen=True, slots=True)
class AccessConsumption:
    consumed: bool = False
    resource: str | None = None
    consumed_at: datetime | None = None


class SiteAdapter(ABC):
    """Contract implemented by each supported site.

    Site-specific selectors and behavior belong here, not in core.
    """

    async def prepare_page(self, page: Page) -> None:
        """Optionally install page hooks before the first navigation."""

        return

    async def configure_run(
        self, page: Page, access_strategy: AccessStrategy
    ) -> None:
        """Validate the requested strategy before navigation.

        Adapters opt into ``direct`` or ``quota`` by overriding this hook.
        The base implementation deliberately supports only the legacy ``auto``
        flow so unsupported strategies cannot silently fall back.
        """

        del page
        if access_strategy != "auto":
            raise UnsupportedAccessStrategyError(
                f"{type(self).__name__} does not support "
                f"access_strategy={access_strategy!r}"
            )

    async def configure_quota_resource(
        self, page: Page, quota_resource: str | None
    ) -> None:
        """Validate optional quota resource metadata before navigation."""

        del page
        if quota_resource is not None:
            raise UnsupportedAccessStrategyError(
                f"{type(self).__name__} does not support "
                f"quota_resource={quota_resource!r}"
            )

    def get_access_consumption(self) -> AccessConsumption:
        """Report any resource use observed by this adapter during the run."""

        return AccessConsumption()

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

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        """Optionally capture CONTENT directly; ``None`` selects Locator fallback."""

        del page
        return None

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

    def get_page_change_timeout_ms(self, default_ms: int) -> int:
        """Return the adapter's bounded page-change wait budget."""

        return int(getattr(self, "page_change_timeout_ms", default_ms))

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        """Optional site-specific data appended to generic diagnostics."""
        return {}

    def get_output_metadata(self) -> dict[str, str | None]:
        """Return optional metadata used by the generic output organizer."""
        return {}

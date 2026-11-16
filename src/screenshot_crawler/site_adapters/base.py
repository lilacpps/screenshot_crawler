from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import UnsupportedAccessStrategyError
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page


@dataclass(frozen=True, slots=True)
class ConfirmedAccessGrant:
    """Site evidence for one finite, exact-source access grant."""

    site: str
    external_id: str
    observed_at: datetime
    access_granted_until: datetime
    expiry_evidence: Literal["site_absolute_expiry", "site_countdown_lower_bound"]

    def __post_init__(self) -> None:
        if not isinstance(self.site, str) or not self.site.strip():
            raise ValueError("confirmed grant site must be non-empty")
        if not isinstance(self.external_id, str) or not self.external_id.strip():
            raise ValueError("confirmed grant external_id must be non-empty")
        for name, value in (
            ("observed_at", self.observed_at),
            ("access_granted_until", self.access_granted_until),
        ):
            if not isinstance(value, datetime):
                raise TypeError(f"confirmed grant {name} must be a datetime")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"confirmed grant {name} must be timezone-aware")
        if self.access_granted_until <= self.observed_at:
            raise ValueError("confirmed grant expiry must follow its observation")
        if self.expiry_evidence not in {
            "site_absolute_expiry",
            "site_countdown_lower_bound",
        }:
            raise ValueError("confirmed grant expiry evidence is unsupported")


@dataclass(frozen=True, slots=True)
class AccessConsumption:
    consumed: bool = False
    resource: str | None = None
    consumed_at: datetime | None = None
    access_granted_until: datetime | None = None
    # Finish the current successful capture/grant before ending this resource pass.
    stop_resource_pass: bool = False


@dataclass(frozen=True, slots=True)
class AccessResourceResolution:
    """Selection result for one site-owned resource resolver."""

    selected_source_ids: tuple[int, ...] = ()
    skipped_source_reasons: tuple[tuple[int, str], ...] = ()


class SiteAdapter(ABC):
    """Contract implemented by each supported site.

    Site-specific selectors and behavior belong here, not in core.
    """

    async def prepare_page(self, page: Page) -> None:
        """Optionally install page hooks before the first navigation."""

        return

    async def prepare_entry_only_page(self, page: Page) -> None:
        """Prepare an entry-only page, defaulting to the normal setup."""

        await self.prepare_page(page)

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        """Return the adapter-selected URL used for the first navigation.

        ``source_url`` remains the canonical crawl target and is persisted as
        such.  Adapters may select a safer site-local entry point while
        keeping that target identity separate from the browser entry URL.
        """

        return source_url

    def get_access_profile(self) -> AccessProfile:
        """Return site-owned host and access-signal classification metadata."""

        return AccessProfile()

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

    async def configure_target_identity(
        self, external_id: str, work_key: str
    ) -> None:
        """Supply Catalog identity expected by a Batch navigation."""

        del external_id, work_key

    def configure_existing_access_grant(
        self, access_granted_until: datetime | None
    ) -> None:
        """Supply a previously trusted finite grant for the selected source."""

        del access_granted_until

    def set_confirmed_access_grant_observer(
        self, observer: Callable[[ConfirmedAccessGrant], None] | None
    ) -> None:
        """Configure a synchronous, site-neutral persistence observer."""

        if observer is not None and not callable(observer):
            raise TypeError("confirmed grant observer must be callable or None")
        self._confirmed_access_grant_observer = observer

    def report_confirmed_access_grant(self, grant: ConfirmedAccessGrant) -> None:
        """Persist site evidence before execution can proceed to capture."""

        if not isinstance(grant, ConfirmedAccessGrant):
            raise TypeError("reported value must be a ConfirmedAccessGrant")
        observer = getattr(self, "_confirmed_access_grant_observer", None)
        if observer is None:
            raise RuntimeError("confirmed access grant observer is not configured")
        observer(grant)

    async def configure_quota_resource(
        self, page: Page, quota_resource: str | None
    ) -> None:
        """Validate the selected access resource before navigation.

        ``quota_resource`` is retained as the persisted/API field name while
        representing the generic access-resource contract.
        """

        del page
        if quota_resource is not None:
            raise UnsupportedAccessStrategyError(
                f"{type(self).__name__} does not support "
                f"quota_resource={quota_resource!r}"
            )

    def configure_access_resource_resolution(
        self, *, timeout_ms: int, page_turn_delay_ms: int,
        blocked_external_ids: frozenset[str] = frozenset(),
    ) -> int:
        """Configure bounded non-consuming preparation and return its total budget.

        The observation timeout remains separate. Default resolvers retain their
        original budget and perform no prerequisite reading.
        """
        return timeout_ms

    async def resolve_access_resource_candidates(
        self,
        page: Page,
        candidates: tuple[object, ...],
        quota_resource: str,
        *,
        timeout_ms: int = 15_000,
    ) -> AccessResourceResolution | None:
        """Optionally select candidates from a site-native access snapshot.

        The default keeps existing sites on the generic candidate path. A site
        integration may override this small hook when one live observation can
        resolve several Catalog candidates without trying them one by one.
        """

        del page, candidates, quota_resource, timeout_ms
        return None

    def get_access_consumption(self) -> AccessConsumption:
        """Report any resource use observed by this adapter during the run."""

        return AccessConsumption()

    async def adopt_prepared_access_entry(self, page: Page, source_url: str) -> bool:
        """Validate a same-page resolver handoff; unsupported adapters fail closed."""

        del page, source_url
        return False

    @abstractmethod
    async def initialize(self, page: Page) -> None:
        """Prepare the viewer after navigation.

        Examples: dismiss cookie UI, switch to single-page mode, hide viewer chrome.
        """

    async def initialize_entry_only(self, page: Page) -> None:
        """Prepare only the access entry path for grant-only runs.

        Adapters that need to avoid full crawl readiness/capture setup may
        override this hook. The default preserves the existing lifecycle.
        """

        await self.initialize(page)

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

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        """Return the bounded overall initialization budget."""

        return default_ms

    async def collect_debug_metadata(self, page: Page) -> dict[str, Any]:
        """Optional site-specific data appended to generic diagnostics."""
        return {}

    def get_output_metadata(self) -> dict[str, str | None]:
        """Return optional metadata used by the generic output organizer."""
        return {}

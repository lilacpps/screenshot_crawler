"""Piccoma episode-list Discovery adapter.

The public product episode page renders the complete episode list as one
oldest-first DOM list. This adapter validates that full listing before it
yields any site-neutral records.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget

ALLOWED_HOSTS = frozenset({"piccoma.com", "www.piccoma.com"})
VIEWER_PATH = re.compile(
    r"^/web/viewer/(?P<product_id>[0-9]+)/(?P<episode_id>[0-9]+)/?$"
)
LISTING_PATH = re.compile(r"^/web/product/(?P<product_id>[0-9]+)/episodes/?$")
TOTAL_EPISODES = re.compile(r"全\s*(?P<count>[0-9]+)\s*話")

LISTING_SELECTOR = "#js_episodeList"
ROW_SELECTOR = "#js_episodeList a[data-product_id][data-episode_id]"
TITLE_SELECTOR = "#js_contentBody .PCM-headTitle_name"
STATUS_SELECTOR = ".PCM-epList_status"

FREE_MARKER = "PCM-epList_status_free"
WAIT_FREE_MARKER = "PCM-epList_status_waitfree"
BINGE_FREE_MARKER = "PCM-epList_status_bingefree"
POINT_MARKER = "PCM-epList_status_point"
GRANTED_MARKER = "PCM-epList_status_waitfreeRead"
_GRANTED_HOURS = re.compile(r"閲覧期限 残り([1-9][0-9]{0,2})時間")
WAIT_MARKERS = frozenset({WAIT_FREE_MARKER, BINGE_FREE_MARKER})

WAIT_TIMEOUT_MS = 15_000
MAX_EPISODE_ROWS = 10_000


@dataclass(frozen=True, slots=True)
class PiccomaEpisodeIdentity:
    """Product-scoped Piccoma episode identity."""

    product_id: str
    episode_id: str

    @property
    def external_id(self) -> str:
        return f"{self.product_id}:{self.episode_id}"


@dataclass(frozen=True, slots=True)
class PiccomaListingRow:
    identity: PiccomaEpisodeIdentity
    title: str
    access_mode: str
    dom_index: int
    access_granted_until: datetime | None = None


def parse_piccoma_viewer_url(url: str) -> PiccomaEpisodeIdentity | None:
    """Parse the supported absolute viewer URL without accepting lookalikes."""

    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        return None
    match = VIEWER_PATH.fullmatch(parsed.path)
    if match is None:
        return None
    return PiccomaEpisodeIdentity(
        product_id=match.group("product_id"),
        episode_id=match.group("episode_id"),
    )


def canonical_piccoma_viewer_url(url: str) -> str:
    identity = parse_piccoma_viewer_url(url)
    if identity is None:
        raise ValueError("Not a supported Piccoma viewer URL")
    return (
        "https://piccoma.com/web/viewer/"
        f"{identity.product_id}/{identity.episode_id}"
    )


def parse_piccoma_listing_url(url: str) -> str | None:
    """Return the product ID for a strict canonical episode-list URL."""

    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        return None
    match = LISTING_PATH.fullmatch(parsed.path)
    return match.group("product_id") if match is not None else None


def classify_piccoma_access(markers: Iterable[str], status_label: str) -> str:
    """Map only observed, unambiguous listing badges to Catalog access modes."""

    observed = {marker for marker in markers if marker.startswith("PCM-epList_status_")}
    label = " ".join(status_label.split())

    if _manual_grant_hours(observed, label) is not None:
        return "quota"
    if observed == {FREE_MARKER} and label == "¥0":
        return "free"
    if FREE_MARKER in observed:
        return "unknown"
    if observed and observed.issubset(WAIT_MARKERS) and WAIT_FREE_MARKER in observed:
        return "quota"
    if observed == {POINT_MARKER} and re.fullmatch(r"[1-9][0-9]*", label):
        return "paid"
    return "unknown"


def _manual_grant_hours(markers: set[str], label: str) -> int | None:
    """Require the observed personal rental badge, never just countdown text."""

    if markers != {GRANTED_MARKER}:
        return None
    match = _GRANTED_HOURS.fullmatch(label)
    return int(match[1]) if match is not None else None


def piccoma_manual_grant_until(
    markers: Iterable[str], status_label: str, observed_at: datetime
) -> datetime | None:
    """Bound the observed whole-hour rental countdown conservatively."""

    hours = _manual_grant_hours(
        {marker for marker in markers if marker.startswith("PCM-epList_status_")},
        " ".join(status_label.split()),
    )
    # Rounding is not established. Reserve one hour rather than overstate
    # the grant; a one-hour display does not establish a future lower bound.
    return observed_at + timedelta(hours=hours - 1) if hours is not None else None


def _parse_listing_rows(
    *,
    rows: Sequence[dict[str, object]],
    product_id: str,
    canonical_title: str,
    declared_count: int,
    scope: DiscoveryScope | None,
    observed_at: datetime | None = None,
) -> list[DiscoveredRecord]:
    """Validate and buffer a complete DOM snapshot before any record is yielded."""

    if not canonical_title.strip():
        raise DiscoveryIncompleteError("Piccoma product title was missing")
    if declared_count < 1 or declared_count > MAX_EPISODE_ROWS:
        raise DiscoveryIncompleteError("Piccoma episode count was missing or exceeded the row cap")
    if len(rows) != declared_count:
        raise DiscoveryIncompleteError("Piccoma episode listing count did not match its header")

    observed_at = observed_at or datetime.now(UTC)
    parsed_rows: list[PiccomaListingRow] = []
    seen_ids: set[str] = set()
    for dom_index, raw in enumerate(rows):
        row_product_id = raw.get("product_id")
        episode_id = raw.get("episode_id")
        title = raw.get("title")
        status_count = raw.get("status_count")
        status_markers = raw.get("status_markers")
        status_label = raw.get("status_label")
        if (
            row_product_id != product_id
            or not isinstance(episode_id, str)
            or not episode_id.isdigit()
            or not isinstance(title, str)
            or not title.strip()
            or status_count != 1
            or not isinstance(status_markers, list)
            or not all(isinstance(marker, str) for marker in status_markers)
            or not isinstance(status_label, str)
        ):
            raise DiscoveryIncompleteError(
                "Piccoma episode listing contains an incomplete or foreign row"
            )

        identity = PiccomaEpisodeIdentity(product_id, episode_id)
        if identity.external_id in seen_ids:
            raise DiscoveryIncompleteError("Piccoma episode listing contains duplicate identities")
        seen_ids.add(identity.external_id)
        parsed_rows.append(
            PiccomaListingRow(
                identity=identity,
                title=" ".join(title.split()),
                access_mode=classify_piccoma_access(status_markers, status_label),
                dom_index=dom_index,
                access_granted_until=piccoma_manual_grant_until(
                    status_markers, status_label, observed_at
                ),
            )
        )

    canonical_rows = list(reversed(parsed_rows))
    if scope is not None:
        canonical_rows = _apply_scope(canonical_rows, product_id, scope)

    return [
        DiscoveredRecord(
            item=DiscoveredItem(
                canonical_title=canonical_title.strip(),
                kind="episode",
                order_label=row.title,
            ),
            source=DiscoveredSource(
                external_id=row.identity.external_id,
                url=(
                    "https://piccoma.com/web/viewer/"
                    f"{row.identity.product_id}/{row.identity.episode_id}"
                ),
                access_mode=row.access_mode,
                available=True,
                global_display_position=row.dom_index + 1,
                access_granted_until=row.access_granted_until,
                access_granted_until_observed=True,
                access_checked_at=observed_at,
            ),
        )
        for row in canonical_rows
    ]


def _apply_scope(
    rows: list[PiccomaListingRow], product_id: str, scope: DiscoveryScope
) -> list[PiccomaListingRow]:
    """Select inclusive site-native boundaries in latest-to-oldest order."""

    if scope.from_url is None and scope.through_url is None:
        raise DiscoveryIncompleteError("Piccoma bounded scope has no boundary")

    indices = {row.identity.external_id: index for index, row in enumerate(rows)}
    boundaries: dict[str, int] = {}
    for name, value in (("from", scope.from_url), ("through", scope.through_url)):
        if value is None:
            continue
        identity = parse_piccoma_viewer_url(value)
        if identity is None:
            raise DiscoveryIncompleteError(f"Piccoma bounded {name} URL is invalid")
        if identity.product_id != product_id:
            raise DiscoveryIncompleteError(
                f"Piccoma bounded {name} boundary belongs to a different product"
            )
        index = indices.get(identity.external_id)
        if index is None:
            raise DiscoveryIncompleteError(
                f"Piccoma bounded {name} boundary was not present in the complete listing"
            )
        boundaries[name] = index

    start = boundaries.get("from", 0)
    end = boundaries.get("through", len(rows) - 1)
    if start > end:
        raise DiscoveryIncompleteError("Piccoma bounded boundaries are reversed")
    return rows[start : end + 1]


class PiccomaDiscoveryAdapter(DiscoveryAdapter):
    """Enumerate a Piccoma product's full native episode list."""

    supports_bounded_discovery = True

    def incremental_stop_decision(
        self,
        record: DiscoveredRecord,
        previous: DiscoverySourceSnapshot | None,
        target: WatchlistTarget,
    ) -> IncrementalStopDecision:
        # Manual grants can change on any old episode. The entire validated
        # listing is already buffered; a known newest streak is not a safe boundary.
        return IncrementalStopDecision.CONTINUE

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode  # Both modes use the same validated latest-first listing stream.
        target_identity = parse_piccoma_viewer_url(target.url)
        if target_identity is None:
            raise DiscoveryIncompleteError(
                "Piccoma Watchlist target must be an absolute viewer URL"
            )

        listing_url = (
            "https://piccoma.com/web/product/"
            f"{target_identity.product_id}/episodes"
        )
        observed_at = datetime.now(UTC)
        try:
            response = await page.goto(
                listing_url,
                wait_until="domcontentloaded",
                timeout=WAIT_TIMEOUT_MS,
            )
            if response is None or response.status != 200:
                raise DiscoveryIncompleteError("Piccoma episode listing did not return HTTP 200")
            if parse_piccoma_listing_url(page.url) != target_identity.product_id:
                raise DiscoveryIncompleteError(
                    "Piccoma episode listing redirected outside the target product"
                )
            await page.locator("#js_contentBody").wait_for(
                state="visible", timeout=WAIT_TIMEOUT_MS
            )
            await page.locator(LISTING_SELECTOR).wait_for(
                state="visible", timeout=WAIT_TIMEOUT_MS
            )
            await page.wait_for_function(
                "document.querySelectorAll("
                "'#js_episodeList a[data-product_id][data-episode_id]'"
                ").length > 0",
                timeout=WAIT_TIMEOUT_MS,
            )
            list_count = await page.locator(LISTING_SELECTOR).count()
            title_count = await page.locator(TITLE_SELECTOR).count()
            if list_count != 1 or title_count != 1:
                raise DiscoveryIncompleteError(
                    "Piccoma episode listing identity was missing or ambiguous"
                )
            list_classes = set(
                (await page.locator(LISTING_SELECTOR).get_attribute("class") or "").split()
            )
            if "PCM-list_asc" not in list_classes or "PCM-list_desc" in list_classes:
                raise DiscoveryIncompleteError(
                    "Piccoma episode list order was not the observed oldest-first order"
                )

            canonical_title = (await page.locator(TITLE_SELECTOR).inner_text()).strip()
            body_text = await page.locator("#js_contentBody").inner_text()
            total_matches = [int(match.group("count")) for match in TOTAL_EPISODES.finditer(body_text)]
            if len(total_matches) != 1:
                raise DiscoveryIncompleteError(
                    "Piccoma episode listing declared count was missing or ambiguous"
                )
            declared_count = total_matches[0]
            if declared_count < 1 or declared_count > MAX_EPISODE_ROWS:
                raise DiscoveryIncompleteError(
                    "Piccoma episode count was missing or exceeded the row cap"
                )
            if await page.locator(ROW_SELECTOR).count() != declared_count:
                raise DiscoveryIncompleteError(
                    "Piccoma episode listing count did not match its header"
                )
            rows = await page.locator(ROW_SELECTOR).evaluate_all(
                """anchors => anchors.map(anchor => {
                  const cards = anchor.querySelectorAll('.PCM-epList_ep');
                  const card = cards.length === 1 ? cards[0] : null;
                  const title = card?.querySelector('.PCM-epList_title');
                  const statuses = card ? [...card.querySelectorAll('.PCM-epList_status')] : [];
                  const status = statuses.length === 1 ? statuses[0] : null;
                  const markers = status
                    ? [status, ...status.querySelectorAll('[class]')]
                        .flatMap(node => [...node.classList])
                        .filter(name => name.startsWith('PCM-epList_status_'))
                    : [];
                  return {
                    product_id: anchor.getAttribute('data-product_id'),
                    episode_id: anchor.getAttribute('data-episode_id'),
                    title: title?.innerText?.trim() || null,
                    status_count: statuses.length,
                    status_markers: [...new Set(markers)],
                    status_label: status?.innerText?.trim() || '',
                  };
                })"""
            )
        except DiscoveryIncompleteError:
            raise
        except (PlaywrightError, TimeoutError) as exc:
            raise DiscoveryIncompleteError("Piccoma episode listing did not become ready") from exc

        if declared_count > MAX_EPISODE_ROWS:
            raise DiscoveryIncompleteError("Piccoma episode listing exceeded the row cap")
        if not any(
            row.get("product_id") == target_identity.product_id
            and row.get("episode_id") == target_identity.episode_id
            for row in rows
        ):
            raise DiscoveryIncompleteError(
                "Piccoma Watchlist episode was not present in the product listing"
            )

        records = _parse_listing_rows(
            rows=rows,
            product_id=target_identity.product_id,
            canonical_title=canonical_title,
            declared_count=declared_count,
            scope=target.discovery_scope,
            observed_at=observed_at,
        )
        for record in records:
            yield record


__all__ = [
    "PiccomaDiscoveryAdapter",
    "PiccomaEpisodeIdentity",
    "canonical_piccoma_viewer_url",
    "classify_piccoma_access",
    "parse_piccoma_listing_url",
    "parse_piccoma_viewer_url",
]

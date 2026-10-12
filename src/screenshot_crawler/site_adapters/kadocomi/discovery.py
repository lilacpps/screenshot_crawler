"""Strict, work-scoped Discovery for the observed Kadocomi WEB episode list."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.catalog.service import JST, now_jst
from screenshot_crawler.core.access_guard import AccessGuard
from screenshot_crawler.core.errors import AccessStopError
from screenshot_crawler.discovery.base import DiscoveryAdapter
from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryMode,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.kadocomi.access import kadocomi_access_profile
from screenshot_crawler.watchlist.models import WatchlistTarget

SITE_HOST = "comic-walker.com"
EPISODE_ID_PATTERN = re.compile(r"^KC_[0-9]{16}_E$")
WORK_PATH_PATTERN = re.compile(r"^/detail/(?P<work_id>KC_[0-9]{6}_S)$")
EPISODE_PATH_PATTERN = re.compile(
    r"^/detail/(?P<work_id>KC_[0-9]{6}_S)/episodes/(?P<episode_id>KC_[0-9]{16}_E)$"
)

DOM_TIMEOUT_MS = 12_000
NAVIGATION_TIMEOUT_MS = 20_000
SETTLEMENT_TIMEOUT_SECONDS = 12.0
SETTLEMENT_INTERVAL_MS = 500
MAX_DECLARED_EPISODES = 1_000
NO_DEADLINE_VERIFIED_WORK_ID = "KC_004915_S"

_ALLOWED_WORK_QUERIES = frozenset({"", "episodeType=first"})
_ALLOWED_EPISODE_QUERIES = frozenset(
    {
        "",
        "co=true",
        "episodeType=first",
        "co=true&episodeType=first",
        "episodeType=first&co=true",
    }
)
_EXPAND_LABEL = re.compile(r"^\u5168(?P<count>[1-9][0-9]*)\u8A71\u3092\u8868\u793A$")
_DEADLINE_MARKER = "\u914D\u4FE1\u671F\u9650"
_OG_TITLE_SUFFIX = "\uFF5C\u30AB\u30C9\u30B3\u30DF (\u30B3\u30DF\u30C3\u30AF\u30A6\u30A9\u30FC\u30AB\u30FC)"
_ENDED_EPISODES_PLACEHOLDER = "\u305D\u306E\u4ED6\u306E\u8A71\u306F\u516C\u958B\u7D42\u4E86\u3057\u307E\u3057\u305F"
_DEADLINE_LABEL = re.compile(
    r"\u914D\u4FE1\u671F\u9650\s*[:\uFF1A]\s*(?P<date>[0-9]{4}/[0-9]{1,2}/[0-9]{1,2})"
    r"[ \t\u3000]+(?P<time>[0-9]{1,2}:[0-9]{2})"
)
_GATE_TEXT = re.compile(
    r"(?:\u30ED\u30B0\u30A4\u30F3|\u8CFC\u5165|\u30C1\u30B1\u30C3\u30C8|"
    r"\u30B3\u30A4\u30F3|\u30DD\u30A4\u30F3\u30C8|\u30EC\u30F3\u30BF\u30EB|"
    r"\u30A2\u30D7\u30EA|\u6709\u6599\u4F1A\u54E1)"
)

_LIST_SNAPSHOT_SCRIPT = r"""() => {
  const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
  const visible = node => !!node && node.getClientRects().length > 0 &&
    getComputedStyle(node).visibility !== 'hidden' &&
    getComputedStyle(node).display !== 'none';
  const parents = [...document.querySelectorAll(
    'div[class*="EpisodesTabContents_root__"]')];
  const parent = parents.length === 1 ? parents[0] : null;
  const lists = parent ? [...parent.querySelectorAll(
    'ul[class*="EpisodesTabContents_episodeList__"]')] : [];
  const list = lists.length === 1 ? lists[0] : null;
  const headingNodes = [...document.querySelectorAll('h1')].filter(node =>
    visible(node) && normalize(node.innerText));
  const heading = headingNodes.length === 1 ? normalize(headingNodes[0].innerText) : null;
  const metaTitles = [...document.querySelectorAll('meta[property="og:title"]')];
  const workTitle = metaTitles.length === 1
    ? normalize(metaTitles[0].content || '') : null;
  if (!list) return {ready: false, parentCount: parents.length,
    listCount: lists.length, heading, workTitle};
  const directChildren = [...list.children];
  const rows = [];
  const placeholders = [];
  let malformedListItemCount = 0;
  let malformedChildCount = 0;
  for (const [index, child] of directChildren.entries()) {
    if (child.tagName !== 'LI') {
      malformedChildCount += 1;
      continue;
    }
    const links = [...child.querySelectorAll('a[href]')];
    const titleNodes = [...child.querySelectorAll(
      '[class*="EpisodeThumbnail_title__"]')];
    if (links.length === 1 && titleNodes.length === 1 &&
        links[0].contains(titleNodes[0]) &&
        links[0].closest('li') === child) {
      rows.push({
        href: links[0].getAttribute('href'),
        label: normalize(titleNodes[0].innerText || titleNodes[0].textContent),
        rowText: normalize(child.innerText || child.textContent),
        rowLinkCount: links.length,
        listIndex: index,
      });
      continue;
    }
    const directElements = [...child.children];
    const paragraphs = directElements.filter(node => node.tagName === 'P');
    const paragraphText = paragraphs.length === 1
      ? normalize(paragraphs[0].innerText || paragraphs[0].textContent) : '';
    if (child.attributes.length === 0 && directElements.length === 1 &&
        paragraphs.length === 1 && links.length === 0 && titleNodes.length === 0 &&
        paragraphText === '\u305D\u306E\u4ED6\u306E\u8A71\u306F\u516C\u958B\u7D42\u4E86\u3057\u307E\u3057\u305F' &&
        normalize(child.innerText || child.textContent) === paragraphText) {
      placeholders.push({index, text: paragraphText});
      continue;
    }
    malformedListItemCount += 1;
  }
  for (const placeholder of placeholders) {
    for (let index = placeholder.index - 1; index >= 0; index -= 1) {
      const previous = rows.find(row => row.listIndex === index);
      if (previous) {
        placeholder.previousEpisodeLabel = previous.label;
        break;
      }
    }
    for (let index = placeholder.index + 1; index < directChildren.length; index += 1) {
      const next = rows.find(row => row.listIndex === index);
      if (next) {
        placeholder.nextEpisodeLabel = next.label;
        break;
      }
    }
  }
  return {ready: true, parentCount: parents.length, listCount: lists.length,
    directChildCount: directChildren.length,
    listItemCount: directChildren.filter(item => item.tagName === 'LI').length,
    episodeRowCount: rows.length, placeholderCount: placeholders.length,
    placeholders, malformedListItemCount, malformedChildCount,
    heading, workTitle, rows};
}"""


@dataclass(frozen=True, slots=True)
class KadocomiWorkUrl:
    work_id: str


@dataclass(frozen=True, slots=True)
class KadocomiEpisodeUrl:
    work_id: str
    episode_id: str


@dataclass(frozen=True, slots=True)
class KadocomiListingRow:
    identity: KadocomiEpisodeUrl
    label: str
    deadline: datetime | None
    access_mode: str

    @property
    def external_id(self) -> str:
        return f"{self.identity.work_id}:{self.identity.episode_id}"


def _strict_site_parts(url: str, allowed_queries: frozenset[str]):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != SITE_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or parsed.query not in allowed_queries
    ):
        return None
    return parsed


def parse_kadocomi_work_url(url: str) -> KadocomiWorkUrl | None:
    parsed = _strict_site_parts(url, _ALLOWED_WORK_QUERIES)
    match = WORK_PATH_PATTERN.fullmatch(parsed.path) if parsed is not None else None
    return KadocomiWorkUrl(match.group("work_id")) if match is not None else None


def canonical_kadocomi_work_url(url: str) -> str:
    identity = parse_kadocomi_work_url(url)
    if identity is None:
        raise ValueError("Not a supported Kadocomi work URL")
    return f"https://{SITE_HOST}/detail/{identity.work_id}"


def parse_kadocomi_episode_url(url: str) -> KadocomiEpisodeUrl | None:
    parsed = _strict_site_parts(url, _ALLOWED_EPISODE_QUERIES)
    match = EPISODE_PATH_PATTERN.fullmatch(parsed.path) if parsed is not None else None
    if match is None:
        return None
    work_id = match.group("work_id")
    episode_id = match.group("episode_id")
    if not EPISODE_ID_PATTERN.fullmatch(episode_id) or not episode_id.startswith(work_id[:-2]):
        return None
    return KadocomiEpisodeUrl(work_id=work_id, episode_id=episode_id)


def canonical_kadocomi_episode_url(url: str) -> str:
    identity = parse_kadocomi_episode_url(url)
    if identity is None:
        raise ValueError("Not a supported Kadocomi episode URL")
    return (
        f"https://{SITE_HOST}/detail/{identity.work_id}/episodes/"
        f"{identity.episode_id}"
    )


def parse_kadocomi_deadline(row_text: str) -> datetime | None:
    """Parse only the observed explicit `配信期限：YYYY/M/D HH:MM` row label."""

    markers = row_text.count("配信期限")
    if markers == 0:
        return None
    if markers != 1:
        raise ValueError("Kadocomi row has multiple delivery-deadline labels")
    match = _DEADLINE_LABEL.search(row_text)
    if match is None:
        raise ValueError("Kadocomi delivery deadline has an unknown format")
    try:
        parsed = datetime.strptime(
            f"{match.group('date')} {match.group('time')}", "%Y/%m/%d %H:%M"
        ).replace(tzinfo=JST)
    except ValueError as exc:
        raise ValueError("Kadocomi delivery deadline is invalid") from exc
    return parsed


def classify_kadocomi_access(
    row_text: str,
    *,
    observed_at: datetime,
    work_id: str | None = None,
) -> tuple[str, datetime | None]:
    """Classify only rows in the exact observed public WEB episode list."""

    if _GATE_TEXT.search(row_text):
        raise ValueError("Kadocomi public row contains an access gate")
    deadline = parse_kadocomi_deadline(row_text)
    if deadline is not None and deadline > observed_at:
        return "free", deadline
    if deadline is None and work_id == NO_DEADLINE_VERIFIED_WORK_ID:
        # Anonymous readability was verified for a no-deadline row only in
        # this exact work's public list. Do not generalize that proof.
        return "free", None
    if deadline is None:
        return "unknown", None
    return "unknown", deadline


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_listing_rows(
    raw_rows: Sequence[object],
    *,
    work_id: str,
    base_url: str,
    observed_at: datetime,
) -> list[KadocomiListingRow]:
    if not raw_rows or len(raw_rows) > MAX_DECLARED_EPISODES:
        raise DiscoveryIncompleteError("Kadocomi episode list is empty or exceeds its safety limit")
    rows: list[KadocomiListingRow] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise DiscoveryIncompleteError("Kadocomi episode row is malformed")
        href = raw.get("href")
        label = raw.get("label")
        row_text = raw.get("rowText")
        row_link_count = raw.get("rowLinkCount")
        if (
            not isinstance(href, str)
            or not href.strip()
            or not isinstance(label, str)
            or not isinstance(row_text, str)
            or not row_text.strip()
            or row_link_count != 1
        ):
            raise DiscoveryIncompleteError("Kadocomi episode row identity is incomplete or ambiguous")
        absolute_url = urljoin(base_url, href)
        identity = parse_kadocomi_episode_url(absolute_url)
        if identity is None or identity.work_id != work_id:
            raise DiscoveryIncompleteError("Kadocomi episode row belongs to another or unknown work")
        if identity.episode_id in seen:
            raise DiscoveryIncompleteError("Kadocomi episode list contains a duplicate episode ID")
        seen.add(identity.episode_id)
        try:
            access_mode, deadline = classify_kadocomi_access(
                row_text,
                observed_at=observed_at,
                work_id=work_id,
            )
        except ValueError as exc:
            raise DiscoveryIncompleteError("Kadocomi episode row has ambiguous access evidence") from exc
        visible_label = _normalize_text(label)
        if not visible_label:
            raise DiscoveryIncompleteError("Kadocomi episode display label is missing")
        rows.append(
            KadocomiListingRow(
                identity=identity,
                label=visible_label,
                deadline=deadline,
                access_mode=access_mode,
            )
        )
    return rows


async def _evaluate_snapshot(page: Page) -> dict[str, object]:
    try:
        value = await asyncio.wait_for(
            page.evaluate(_LIST_SNAPSHOT_SCRIPT),
            timeout=5,
        )
    except (TimeoutError, PlaywrightError) as exc:
        raise DiscoveryIncompleteError("Kadocomi scoped episode list could not be read") from exc
    if not isinstance(value, dict):
        raise DiscoveryIncompleteError("Kadocomi scoped episode snapshot is malformed")
    return value


async def _wait_for_settled_rows(
    page: Page,
    *,
    guard: AccessGuard,
    declared_count: int,
    work_title: str,
) -> list[dict[str, object]]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SETTLEMENT_TIMEOUT_SECONDS
    previous_key: tuple[object, ...] | None = None
    while loop.time() < deadline:
        await guard.check_page(page)
        snapshot = await _evaluate_snapshot(page)
        placeholder_count = snapshot.get("placeholderCount")
        valid_placeholder_count = (
            isinstance(placeholder_count, int)
            and not isinstance(placeholder_count, bool)
            and placeholder_count in (0, 1)
        )
        ready = (
            snapshot.get("ready") is True
            and snapshot.get("parentCount") == 1
            and snapshot.get("listCount") == 1
            and snapshot.get("episodeRowCount") == declared_count
            and valid_placeholder_count
            and snapshot.get("directChildCount") == declared_count + placeholder_count
            and snapshot.get("malformedListItemCount") == 0
            and snapshot.get("malformedChildCount") == 0
            and snapshot.get("heading")
            and snapshot.get("workTitle") == f"{work_title}{_OG_TITLE_SUFFIX}"
        )
        raw_rows = snapshot.get("rows")
        placeholders = snapshot.get("placeholders")
        if ready and isinstance(raw_rows, list) and len(raw_rows) == declared_count:
            key_values: list[tuple[int, str, str, str]] = []
            valid_key = True
            for raw in raw_rows:
                if not isinstance(raw, dict):
                    valid_key = False
                    break
                list_index, href, label, row_text = (
                    raw.get("listIndex"),
                    raw.get("href"),
                    raw.get("label"),
                    raw.get("rowText"),
                )
                if (
                    isinstance(list_index, bool)
                    or not isinstance(list_index, int)
                    or not all(isinstance(value, str) for value in (href, label, row_text))
                ):
                    valid_key = False
                    break
                key_values.append((list_index, href, label, row_text))
            placeholder_key: list[tuple[int, str, str, str]] = []
            if not isinstance(placeholders, list) or len(placeholders) != placeholder_count:
                valid_key = False
            else:
                for placeholder in placeholders:
                    if not isinstance(placeholder, dict):
                        valid_key = False
                        break
                    index, text, previous, following = (
                        placeholder.get("index"),
                        placeholder.get("text"),
                        placeholder.get("previousEpisodeLabel"),
                        placeholder.get("nextEpisodeLabel"),
                    )
                    if (
                        isinstance(index, bool)
                        or not isinstance(index, int)
                        or text != _ENDED_EPISODES_PLACEHOLDER
                        or not isinstance(previous, str)
                        or not previous
                        or not isinstance(following, str)
                        or not following
                    ):
                        valid_key = False
                        break
                    placeholder_key.append((index, text, previous, following))
            if valid_key:
                key = (
                    snapshot.get("heading"),
                    snapshot.get("workTitle"),
                    tuple(key_values),
                    tuple(placeholder_key),
                )
                if key == previous_key:
                    return raw_rows
                previous_key = key
            else:
                previous_key = None
        else:
            previous_key = None
        await page.wait_for_timeout(SETTLEMENT_INTERVAL_MS)
    raise DiscoveryIncompleteError(
        "Kadocomi episode list did not settle to its declared complete count"
    )


def _read_expand_button(value: object) -> tuple[str, int]:
    if not isinstance(value, list):
        raise DiscoveryIncompleteError("Kadocomi episode expansion controls could not be read")
    matches: list[tuple[str, int]] = []
    for label in value:
        if not isinstance(label, str):
            continue
        normalized = _normalize_text(label)
        match = _EXPAND_LABEL.fullmatch(normalized)
        if match is not None:
            matches.append((normalized, int(match.group("count"))))
    if len(matches) != 1:
        raise DiscoveryIncompleteError("Kadocomi episode expansion control is missing or ambiguous")
    label, declared_count = matches[0]
    if declared_count > MAX_DECLARED_EPISODES:
        raise DiscoveryIncompleteError("Kadocomi declared episode count exceeds its safety limit")
    return label, declared_count


def _canonical_work_title(raw_title: object) -> str:
    if not isinstance(raw_title, str) or not raw_title.endswith(_OG_TITLE_SUFFIX):
        raise DiscoveryIncompleteError("Kadocomi canonical work title is missing or unknown")
    title = raw_title[: -len(_OG_TITLE_SUFFIX)].strip()
    if not title:
        raise DiscoveryIncompleteError("Kadocomi canonical work title is empty")
    return title


class KadocomiDiscoveryAdapter(DiscoveryAdapter):
    """Read and validate the exact currently public episode list before yielding."""

    allow_inferred_display_positions = False

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        del mode  # Both modes buffer and validate the same exact current public list.
        if target.site != "kadocomi":
            raise DiscoveryIncompleteError("Kadocomi adapter received a different site target")
        if target.discovery_scope is not None:
            raise DiscoveryIncompleteError("Kadocomi bounded from/through Discovery is unsupported")
        work = parse_kadocomi_work_url(target.url)
        if work is None:
            raise DiscoveryIncompleteError("Kadocomi Watchlist target is not a supported work URL")

        guard = AccessGuard.from_profile(
            site="kadocomi",
            profile=kadocomi_access_profile(),
            stop_on_http_403=True,
            stop_on_http_429=True,
            stop_on_challenge=True,
            stop_on_captcha=True,
        )
        guard.start(page)
        try:
            response: Response | None
            try:
                response = await page.goto(
                    target.url,
                    wait_until="domcontentloaded",
                    timeout=NAVIGATION_TIMEOUT_MS,
                )
            except (PlaywrightError, PlaywrightTimeoutError) as exc:
                await guard.check_page(page)
                raise DiscoveryIncompleteError("Kadocomi work page navigation did not complete") from exc
            await guard.check_page(page)
            if response is None or response.status != 200:
                raise DiscoveryIncompleteError("Kadocomi work page did not return HTTP 200")
            actual_work = parse_kadocomi_work_url(page.url)
            if actual_work is None or actual_work.work_id != work.work_id:
                raise DiscoveryIncompleteError("Kadocomi navigation changed the exact work identity")

            title_values = await asyncio.wait_for(
                page.locator('meta[property="og:title"]').evaluate_all(
                    "nodes => nodes.map(node => node.content || '')"
                ),
                timeout=5,
            )
            if not isinstance(title_values, list) or len(title_values) != 1:
                raise DiscoveryIncompleteError("Kadocomi og:title is missing or ambiguous")
            work_title = _canonical_work_title(title_values[0])

            button_labels = await asyncio.wait_for(
                page.locator("button").evaluate_all(
                    "nodes => nodes.filter(node => node.getClientRects().length > 0 && "
                    "getComputedStyle(node).visibility !== 'hidden').map(node => "
                    "(node.innerText || '').replace(/\\s+/g, ' ').trim())"
                ),
                timeout=5,
            )
            button_label, declared_count = _read_expand_button(button_labels)
            await guard.check_page(page)
            expand_button = page.get_by_role("button", name=button_label, exact=True)
            if await expand_button.count() != 1 or not await expand_button.is_visible():
                raise DiscoveryIncompleteError(
                    "Kadocomi episode expansion button changed or is ambiguous"
                )
            if _normalize_text(await expand_button.inner_text()) != button_label:
                raise DiscoveryIncompleteError("Kadocomi episode expansion button changed")
            await expand_button.click(timeout=DOM_TIMEOUT_MS)
            raw_rows = await _wait_for_settled_rows(
                page,
                guard=guard,
                declared_count=declared_count,
                work_title=work_title,
            )
            observed_at = now_jst()
            rows = _parse_listing_rows(
                raw_rows,
                work_id=work.work_id,
                base_url=page.url,
                observed_at=observed_at,
            )
            if len(rows) != declared_count:
                raise DiscoveryIncompleteError("Kadocomi episode rows do not match the declared total")
            records = [
                DiscoveredRecord(
                    item=DiscoveredItem(
                        canonical_title=work_title,
                        kind="episode",
                        order_label=row.label,
                    ),
                    source=DiscoveredSource(
                        external_id=row.external_id,
                        url=canonical_kadocomi_episode_url(
                            f"https://{SITE_HOST}/detail/{row.identity.work_id}/episodes/"
                            f"{row.identity.episode_id}"
                        ),
                        access_mode=row.access_mode,
                        free_until=row.deadline,
                        available=True,
                        access_checked_at=observed_at,
                        last_seen_at=observed_at,
                    ),
                )
                for row in reversed(rows)
            ]
        except DiscoveryIncompleteError:
            raise
        except AccessStopError as exc:
            raise DiscoveryIncompleteError(
                f"Kadocomi Discovery stopped by the access guard: {exc.reason}"
            ) from exc
        except (TimeoutError, PlaywrightError, PlaywrightTimeoutError) as exc:
            await guard.check_page(page)
            raise DiscoveryIncompleteError("Kadocomi episode listing did not complete") from exc
        except (ValueError, TypeError) as exc:
            raise DiscoveryIncompleteError("Kadocomi work or episode identity is invalid") from exc
        finally:
            await guard.close()

        for record in records:
            yield record


__all__ = [
    "NO_DEADLINE_VERIFIED_WORK_ID",
    "KadocomiDiscoveryAdapter",
    "KadocomiEpisodeUrl",
    "KadocomiListingRow",
    "KadocomiWorkUrl",
    "canonical_kadocomi_episode_url",
    "canonical_kadocomi_work_url",
    "classify_kadocomi_access",
    "parse_kadocomi_deadline",
    "parse_kadocomi_episode_url",
    "parse_kadocomi_work_url",
]

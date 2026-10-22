"""Strict, work-scoped Discovery for the observed Kadocomi WEB episode list."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from urllib.parse import urljoin, urlsplit
from uuid import UUID

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
MAX_NATIVE_JSON_BYTES = 2_000_000

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
    r"\u30A2\u30D7\u30EA|\u6709\u6599)"
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


@dataclass(frozen=True, slots=True)
class KadocomiNativeEpisode:
    """One first-party lifetime listing row with an explicit native ordinal."""

    work_id: str
    episode_id: str
    episode_uuid: str
    title: str
    episode_no: int
    episode_type: str
    is_active: bool
    page_count: int

    @property
    def external_id(self) -> str:
        return f"{self.work_id}:{self.episode_id}"


@dataclass(frozen=True, slots=True)
class KadocomiNativeListing:
    work_id: str
    work_uuid: str
    work_title: str
    episodes: tuple[KadocomiNativeEpisode, ...]


def _canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return None
    canonical = str(parsed)
    return canonical if value == canonical else None


def _native_episode_projection(raw: object, *, work_id: str) -> KadocomiNativeEpisode:
    if not isinstance(raw, dict):
        raise DiscoveryIncompleteError("Kadocomi native history contains a malformed episode")
    code = raw.get("code")
    episode_uuid = _canonical_uuid(raw.get("id"))
    title = raw.get("title")
    service_id = raw.get("serviceId")
    episode_type = raw.get("type")
    is_active = raw.get("isActive")
    internal = raw.get("internal")
    if (
        not isinstance(code, str)
        or EPISODE_ID_PATTERN.fullmatch(code) is None
        or not code.startswith(work_id[:-2])
        or episode_uuid is None
        or not isinstance(title, str)
        or not _normalize_text(title)
        or service_id != "web"
        or not isinstance(episode_type, str)
        or episode_type not in {"normal", "extra"}
        or not isinstance(is_active, bool)
        or not isinstance(internal, dict)
    ):
        raise DiscoveryIncompleteError("Kadocomi native history identity is incomplete")
    episode_no = internal.get("episodeNo")
    internal_type = internal.get("episodetype")
    page_count = internal.get("pageCount")
    if (
        isinstance(episode_no, bool)
        or not isinstance(episode_no, int)
        or episode_no < 1
        or internal_type != episode_type
        or isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count < 0
    ):
        raise DiscoveryIncompleteError("Kadocomi native history order or type is invalid")
    return KadocomiNativeEpisode(
        work_id=work_id,
        episode_id=code,
        episode_uuid=episode_uuid,
        title=_normalize_text(title),
        episode_no=episode_no,
        episode_type=episode_type,
        is_active=is_active,
        page_count=page_count,
    )


def _parse_native_work_listing(value: object, *, work_id: str) -> KadocomiNativeListing:
    """Validate only the observed work query and its complete first/latest arrays."""

    if not isinstance(value, dict):
        raise DiscoveryIncompleteError("Kadocomi first-party work data is malformed")
    props = value.get("props")
    page_props = props.get("pageProps") if isinstance(props, dict) else None
    dehydrated = page_props.get("dehydratedState") if isinstance(page_props, dict) else None
    queries = dehydrated.get("queries") if isinstance(dehydrated, dict) else None
    if not isinstance(queries, list):
        raise DiscoveryIncompleteError("Kadocomi native work query is unavailable")
    matches = [
        query
        for query in queries
        if isinstance(query, dict)
        and query.get("queryKey") == ["/api/contents/details/work", {"workCode": work_id}]
    ]
    if len(matches) != 1:
        raise DiscoveryIncompleteError("Kadocomi native work query is missing or ambiguous")
    query_state = matches[0].get("state")
    data = query_state.get("data") if isinstance(query_state, dict) else None
    work = data.get("work") if isinstance(data, dict) else None
    if not isinstance(work, dict) or work.get("code") != work_id:
        raise DiscoveryIncompleteError("Kadocomi native history belongs to another work")
    work_uuid = _canonical_uuid(work.get("id"))
    work_title = work.get("title")
    if (
        work_uuid is None
        or not isinstance(work_title, str)
        or not _normalize_text(work_title)
    ):
        raise DiscoveryIncompleteError("Kadocomi native work identity is incomplete")

    first = data.get("firstEpisodes")
    latest = data.get("latestEpisodes")
    if not isinstance(first, dict) or not isinstance(latest, dict):
        raise DiscoveryIncompleteError("Kadocomi complete native episode arrays are unavailable")
    first_total, first_raw = first.get("total"), first.get("result")
    latest_total, latest_raw = latest.get("total"), latest.get("result")
    if (
        isinstance(first_total, bool)
        or not isinstance(first_total, int)
        or first_total < 1
        or first_total > MAX_DECLARED_EPISODES
        or isinstance(latest_total, bool)
        or not isinstance(latest_total, int)
        or first_total != latest_total
        or not isinstance(first_raw, list)
        or not isinstance(latest_raw, list)
        or len(first_raw) != first_total
        or len(latest_raw) != first_total
    ):
        raise DiscoveryIncompleteError("Kadocomi native episode totals are incomplete")

    episodes = tuple(_native_episode_projection(row, work_id=work_id) for row in first_raw)
    if (
        len({episode.episode_id for episode in episodes}) != len(episodes)
        or len({episode.episode_uuid for episode in episodes}) != len(episodes)
        or any(
            current.episode_no <= previous.episode_no
            for previous, current in pairwise(episodes)
        )
    ):
        raise DiscoveryIncompleteError("Kadocomi native episode order is duplicated or unstable")
    latest_episodes = tuple(
        _native_episode_projection(row, work_id=work_id) for row in latest_raw
    )
    if latest_episodes != tuple(reversed(episodes)):
        raise DiscoveryIncompleteError("Kadocomi latest episode array is not the reverse listing")
    if not any(episode.is_active for episode in episodes):
        raise DiscoveryIncompleteError("Kadocomi native history has no observed public rows")
    inactive_runs = _native_inactive_runs(episodes)
    if any(previous is None for previous, _run, _following in inactive_runs):
        raise DiscoveryIncompleteError("Kadocomi leading ended history is not represented safely")
    return KadocomiNativeListing(
        work_id=work_id,
        work_uuid=work_uuid,
        work_title=_normalize_text(work_title),
        episodes=episodes,
    )


def _native_inactive_runs(
    episodes: Sequence[KadocomiNativeEpisode],
) -> list[
    tuple[
        KadocomiNativeEpisode | None,
        tuple[KadocomiNativeEpisode, ...],
        KadocomiNativeEpisode | None,
    ]
]:
    """Return each inactive run with its nearest active rows in native order."""

    runs: list[
        tuple[
            KadocomiNativeEpisode | None,
            tuple[KadocomiNativeEpisode, ...],
            KadocomiNativeEpisode | None,
        ]
    ] = []
    index = 0
    while index < len(episodes):
        if episodes[index].is_active:
            index += 1
            continue
        start = index
        while index < len(episodes) and not episodes[index].is_active:
            index += 1
        previous = episodes[start - 1] if start > 0 else None
        following = episodes[index] if index < len(episodes) else None
        runs.append((previous, tuple(episodes[start:index]), following))
    return runs


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
    """Classify validated public WEB rows; unflagged rows are free for any work."""

    if _GATE_TEXT.search(row_text):
        raise ValueError("Kadocomi public row contains an access gate")
    deadline = parse_kadocomi_deadline(row_text)
    if deadline is not None and deadline > observed_at:
        return "free", deadline
    if deadline is None:
        return "free", None
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
            # Each accepted marker separates two episode rows, so at most
            # declared_count - 1 distinct ended-publication gaps can exist.
            and 0 <= placeholder_count < declared_count
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
            episode_labels = {index: label for index, _href, label, _text in key_values}
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
                        or episode_labels.get(index - 1) != previous
                        or episode_labels.get(index + 1) != following
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


def _read_optional_expand_button(value: object) -> tuple[str, int] | None:
    if not isinstance(value, list):
        raise DiscoveryIncompleteError("Kadocomi episode controls could not be read")
    matches = [
        (normalized, int(match.group("count")))
        for label in value
        if isinstance(label, str)
        for normalized in [_normalize_text(label)]
        if (match := _EXPAND_LABEL.fullmatch(normalized)) is not None
    ]
    if len(matches) > 1:
        raise DiscoveryIncompleteError("Kadocomi episode expansion control is ambiguous")
    if not matches:
        return None
    label, count = matches[0]
    if count > MAX_DECLARED_EPISODES:
        raise DiscoveryIncompleteError("Kadocomi declared episode count exceeds its safety limit")
    return label, count


def _canonical_work_title(raw_title: object) -> str:
    if not isinstance(raw_title, str) or not raw_title.endswith(_OG_TITLE_SUFFIX):
        raise DiscoveryIncompleteError("Kadocomi canonical work title is missing or unknown")
    title = raw_title[: -len(_OG_TITLE_SUFFIX)].strip()
    if not title:
        raise DiscoveryIncompleteError("Kadocomi canonical work title is empty")
    return title


class KadocomiDiscoveryAdapter(DiscoveryAdapter):
    """Read and validate the exact currently public episode list before yielding."""

    supports_bounded_discovery = True
    allow_inferred_display_positions = False

    async def iter_records(
        self,
        page: Page,
        target: WatchlistTarget,
        mode: DiscoveryMode,
    ) -> AsyncIterator[DiscoveredRecord]:
        self.reset_complete_listing_inventory()
        if target.site != "kadocomi":
            raise DiscoveryIncompleteError("Kadocomi adapter received a different site target")
        work = parse_kadocomi_work_url(target.url)
        if work is None:
            raise DiscoveryIncompleteError("Kadocomi Watchlist target is not a supported work URL")

        native_opt_in = target.discovery_scope is not None or target.archive_order is not None
        if native_opt_in:
            all_records, records, listing_identity = await self._discover_native_listing(
                page,
                target,
                work.work_id,
            )
        else:
            if target.discovery_scope is not None:
                raise DiscoveryIncompleteError("Kadocomi bounded from/through Discovery is unsupported")
            records = await self._discover_legacy_public_listing(page, target, work.work_id)
            all_records = records
            listing_identity = None

        for record in records:
            yield record
        if native_opt_in and mode == "full":
            self.capture_complete_listing_inventory(
                target=target,
                all_records=all_records,
                selected_records=records,
                listing_identity=listing_identity,
            )

    async def _discover_legacy_public_listing(
        self,
        page: Page,
        target: WatchlistTarget,
        work_id: str,
    ) -> list[DiscoveredRecord]:
        """Keep the established unordered, current-public-only contract unchanged."""

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
            if actual_work is None or actual_work.work_id != work_id:
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
                work_id=work_id,
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

        return records

    async def _read_native_listing(
        self,
        page: Page,
        *,
        work_id: str,
    ) -> KadocomiNativeListing:
        script = page.locator("#__NEXT_DATA__")
        try:
            await script.wait_for(state="attached", timeout=DOM_TIMEOUT_MS)
            if await script.count() != 1:
                raise DiscoveryIncompleteError("Kadocomi native work data is ambiguous")
            raw = await script.text_content()
            title_values = await page.locator('meta[property="og:title"]').evaluate_all(
                "nodes => nodes.map(node => node.content || '')"
            )
        except (PlaywrightError, PlaywrightTimeoutError, TimeoutError) as exc:
            raise DiscoveryIncompleteError("Kadocomi native work data could not be read") from exc
        if not isinstance(raw, str) or not raw:
            raise DiscoveryIncompleteError("Kadocomi native work data is empty")
        if len(raw.encode("utf-8")) > MAX_NATIVE_JSON_BYTES:
            raise DiscoveryIncompleteError("Kadocomi native work data exceeds its safety limit")
        if not isinstance(title_values, list) or len(title_values) != 1:
            raise DiscoveryIncompleteError("Kadocomi canonical work title is missing or ambiguous")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DiscoveryIncompleteError("Kadocomi native work data is invalid JSON") from exc
        listing = _parse_native_work_listing(parsed, work_id=work_id)
        if _canonical_work_title(title_values[0]) != listing.work_title:
            raise DiscoveryIncompleteError("Kadocomi native work title does not match the page")
        return listing

    async def _wait_for_native_settled_snapshot(
        self,
        page: Page,
        *,
        guard: AccessGuard,
        listing: KadocomiNativeListing,
    ) -> dict[str, object]:
        expected_active = [episode for episode in listing.episodes if episode.is_active]
        inactive_runs = _native_inactive_runs(listing.episodes)
        if not expected_active or any(previous is None for previous, _run, _next in inactive_runs):
            raise DiscoveryIncompleteError("Kadocomi native history cannot be mapped to public rows")

        loop = asyncio.get_running_loop()
        deadline = loop.time() + SETTLEMENT_TIMEOUT_SECONDS
        previous_key: str | None = None
        while loop.time() < deadline:
            await guard.check_page(page)
            snapshot = await _evaluate_snapshot(page)
            raw_rows = snapshot.get("rows")
            raw_placeholders = snapshot.get("placeholders")
            ready = (
                snapshot.get("ready") is True
                and type(snapshot.get("parentCount")) is int
                and snapshot.get("parentCount") == 1
                and type(snapshot.get("listCount")) is int
                and snapshot.get("listCount") == 1
                and type(snapshot.get("episodeRowCount")) is int
                and snapshot.get("episodeRowCount") == len(expected_active)
                and type(snapshot.get("placeholderCount")) is int
                and snapshot.get("placeholderCount") == len(inactive_runs)
                and type(snapshot.get("directChildCount")) is int
                and snapshot.get("directChildCount") == len(expected_active) + len(inactive_runs)
                and type(snapshot.get("malformedListItemCount")) is int
                and snapshot.get("malformedListItemCount") == 0
                and type(snapshot.get("malformedChildCount")) is int
                and snapshot.get("malformedChildCount") == 0
                and isinstance(snapshot.get("heading"), str)
                and bool(snapshot.get("heading"))
                and snapshot.get("workTitle") == f"{listing.work_title}{_OG_TITLE_SUFFIX}"
                and isinstance(raw_rows, list)
                and len(raw_rows) == len(expected_active)
                and isinstance(raw_placeholders, list)
                and len(raw_placeholders) == len(inactive_runs)
            )
            if ready:
                rows_by_index: dict[int, tuple[str, str]] = {}
                row_index_by_episode: dict[str, int] = {}
                valid_rows = True
                row_indices: list[int] = []
                for raw, episode in zip(raw_rows, expected_active, strict=True):
                    if not isinstance(raw, dict):
                        valid_rows = False
                        break
                    index = raw.get("listIndex")
                    href = raw.get("href")
                    label = raw.get("label")
                    row_text = raw.get("rowText")
                    if (
                        isinstance(index, bool)
                        or not isinstance(index, int)
                        or not isinstance(href, str)
                        or not isinstance(label, str)
                        or not isinstance(row_text, str)
                        or isinstance(raw.get("rowLinkCount"), bool)
                        or raw.get("rowLinkCount") != 1
                        or _normalize_text(label) != episode.title
                    ):
                        valid_rows = False
                        break
                    identity = parse_kadocomi_episode_url(urljoin(page.url, href))
                    if identity is None or identity.work_id != listing.work_id or identity.episode_id != episode.episode_id:
                        valid_rows = False
                        break
                    rows_by_index[index] = (_normalize_text(label), episode.episode_id)
                    row_index_by_episode[episode.episode_id] = index
                    row_indices.append(index)
                if row_indices != sorted(set(row_indices)):
                    valid_rows = False

                valid_placeholders = valid_rows
                if valid_placeholders:
                    placeholder_indices: list[int] = []
                    for raw, (previous, run, following) in zip(
                        raw_placeholders,
                        inactive_runs,
                        strict=True,
                    ):
                        if not isinstance(raw, dict) or previous is None:
                            valid_placeholders = False
                            break
                        index = raw.get("index")
                        previous_label = raw.get("previousEpisodeLabel")
                        next_label = raw.get("nextEpisodeLabel")
                        if (
                            isinstance(index, bool)
                            or not isinstance(index, int)
                            or raw.get("text") != _ENDED_EPISODES_PLACEHOLDER
                            or previous_label != previous.title
                            or rows_by_index.get(index - 1, (None, None))[0] != previous.title
                        ):
                            valid_placeholders = False
                            break
                        placeholder_indices.append(index)
                        if following is None:
                            if next_label not in (None, "") or index != row_indices[-1] + 1:
                                valid_placeholders = False
                                break
                        elif (
                            next_label != following.title
                            or rows_by_index.get(index + 1, (None, None))[0] != following.title
                            or index != row_index_by_episode[following.episode_id] - 1
                        ):
                            valid_placeholders = False
                            break
                    if sorted(row_indices + placeholder_indices) != list(
                        range(len(expected_active) + len(inactive_runs))
                    ):
                        valid_placeholders = False

                if valid_rows and valid_placeholders:
                    key = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
                    if key == previous_key:
                        return snapshot
                    previous_key = key
                else:
                    previous_key = None
            else:
                previous_key = None
            await page.wait_for_timeout(SETTLEMENT_INTERVAL_MS)
        raise DiscoveryIncompleteError("Kadocomi native public rows did not settle exactly")

    async def _discover_native_listing(
        self,
        page: Page,
        target: WatchlistTarget,
        work_id: str,
    ) -> tuple[list[DiscoveredRecord], list[DiscoveredRecord], str]:
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
            if actual_work is None or actual_work.work_id != work_id:
                raise DiscoveryIncompleteError("Kadocomi navigation changed the exact work identity")
            listing = await self._read_native_listing(page, work_id=work_id)

            button_labels = await asyncio.wait_for(
                page.locator("button").evaluate_all(
                    "nodes => nodes.filter(node => node.getClientRects().length > 0 && "
                    "getComputedStyle(node).visibility !== 'hidden').map(node => "
                    "(node.innerText || '').replace(/\\s+/g, ' ').trim())"
                ),
                timeout=5,
            )
            expand = _read_optional_expand_button(button_labels)
            active_count = sum(episode.is_active for episode in listing.episodes)
            if expand is not None:
                button_label, declared_count = expand
                if declared_count != active_count:
                    raise DiscoveryIncompleteError(
                        "Kadocomi expansion count does not match native public rows"
                    )
                await guard.check_page(page)
                button = page.get_by_role("button", name=button_label, exact=True)
                if await button.count() != 1 or not await button.is_visible():
                    raise DiscoveryIncompleteError("Kadocomi expansion control changed or is ambiguous")
                if _normalize_text(await button.inner_text()) != button_label:
                    raise DiscoveryIncompleteError("Kadocomi expansion control changed")
                await button.click(timeout=DOM_TIMEOUT_MS)

            settled_snapshot = await self._wait_for_native_settled_snapshot(
                page,
                guard=guard,
                listing=listing,
            )
            raw_rows = settled_snapshot.get("rows")
            rows = _parse_listing_rows(
                raw_rows if isinstance(raw_rows, list) else [],
                work_id=work_id,
                base_url=page.url,
                observed_at=now_jst(),
            )
            active_native = [episode for episode in listing.episodes if episode.is_active]
            if len(rows) != len(active_native) or any(
                row.external_id != episode.external_id or row.label != episode.title
                for row, episode in zip(rows, active_native, strict=True)
            ):
                raise DiscoveryIncompleteError("Kadocomi public rows disagree with native history")
            await guard.check_page(page)
            final_listing = await self._read_native_listing(page, work_id=work_id)
            final_snapshot = await _evaluate_snapshot(page)
            if final_listing != listing or final_snapshot != settled_snapshot:
                raise DiscoveryIncompleteError("Kadocomi native history changed before emission")
            await guard.check_page(page)
            final_work = parse_kadocomi_work_url(page.url)
            if final_work is None or final_work.work_id != work_id:
                raise DiscoveryIncompleteError("Kadocomi page identity changed before emission")

            active_rows = {
                row.external_id: row
                for row in rows
            }
            observed_at = now_jst()
            all_records: list[DiscoveredRecord] = []
            for episode in reversed(listing.episodes):
                row = active_rows.get(episode.external_id)
                if episode.is_active and row is None:
                    raise DiscoveryIncompleteError("Kadocomi active native episode has no public row")
                all_records.append(
                    DiscoveredRecord(
                        item=DiscoveredItem(
                            canonical_title=listing.work_title,
                            kind="episode",
                            order_label=episode.title,
                        ),
                        source=DiscoveredSource(
                            external_id=episode.external_id,
                            url=canonical_kadocomi_episode_url(
                                f"https://{SITE_HOST}/detail/{work_id}/episodes/{episode.episode_id}"
                            ),
                            access_mode=row.access_mode if row is not None else "unknown",
                            free_until=row.deadline if row is not None else None,
                            available=row is not None,
                            access_granted_until_observed=False,
                            access_checked_at=observed_at,
                            last_seen_at=observed_at,
                            global_display_position=episode.episode_no,
                        ),
                    )
                )
            selected = self._select_native_scope(all_records, target, work_id)
            return all_records, selected, f"kadocomi-native-work:{work_id}"
        except DiscoveryIncompleteError:
            raise
        except AccessStopError as exc:
            raise DiscoveryIncompleteError(
                f"Kadocomi Discovery stopped by the access guard: {exc.reason}"
            ) from exc
        except (TimeoutError, PlaywrightError, PlaywrightTimeoutError, ValueError, TypeError) as exc:
            await guard.check_page(page)
            raise DiscoveryIncompleteError("Kadocomi native episode listing did not complete") from exc
        finally:
            await guard.close()

    @staticmethod
    def _select_native_scope(
        records: list[DiscoveredRecord],
        target: WatchlistTarget,
        work_id: str,
    ) -> list[DiscoveredRecord]:
        scope = target.discovery_scope
        if scope is None:
            return records
        if scope.from_url is None and scope.through_url is None:
            raise DiscoveryIncompleteError("Kadocomi scope has no boundaries")
        indices: dict[str, int] = {}
        by_external_id = {record.source.external_id: index for index, record in enumerate(records)}
        for name, url in (("from", scope.from_url), ("through", scope.through_url)):
            if url is None:
                continue
            identity = parse_kadocomi_episode_url(url)
            if identity is None or identity.work_id != work_id:
                raise DiscoveryIncompleteError(f"Kadocomi {name} boundary is not a canonical episode")
            external_id = f"{work_id}:{identity.episode_id}"
            if external_id not in by_external_id:
                raise DiscoveryIncompleteError(f"Kadocomi {name} boundary is not in native history")
            indices[name] = by_external_id[external_id]
        start = indices.get("from", 0)
        end = indices.get("through", len(records) - 1)
        if start > end:
            raise DiscoveryIncompleteError("Kadocomi scope boundaries are reversed")
        return records[start : end + 1]


__all__ = [
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

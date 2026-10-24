"""Bounded same-Page access evidence and route protection for Batch entry."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Request, Response, Route

BASE_URL = "https://younganimal.com"
MAX_EVENTS = 128
MAX_JSON_BYTES = 1_048_576
MAX_REQUEST_JSON_BYTES = 65_536
MAX_JSON_NODES = 50_000
MAX_JSON_DEPTH = 64
OBSERVATION_TIMEOUT_SECONDS = 8.0
MAX_RECORDED_ROUTE_PREFETCHES = 16
ID_PATTERN = re.compile(r"^[0-9a-f]{13}$")
STATIC_RESOURCE_TYPES = frozenset({"font", "image", "media", "script", "stylesheet"})
_ACCESS_TYPE = "waitAndFree"
_AUTH_PATH = "/api/auth/session"
_SERIES_PATH = "/api/series/access"
_CHECKOUT_PATH = "/api/checkout/rental"


@dataclass(frozen=True, slots=True)
class NativeAccessState:
    episode_id: str
    work_id: str | None
    has_access: bool
    access_type: str
    remaining_seconds: int | None
    remaining_state: Literal["missing", "null", "valid", "malformed"]


@dataclass(frozen=True, slots=True)
class ConsumptionProof:
    consumed_at: datetime
    access_granted_until: datetime | None


@dataclass(slots=True)
class _RequestEvidence:
    request: Request
    kind: Literal["auth", "episode", "series", "checkout"]
    path: str
    started_at: datetime
    started_monotonic: float
    query_work_ids: tuple[str, ...] = ()
    target_bound: bool = False
    response_seen: bool = False
    status: int | None = None
    response_at: datetime | None = None
    response_monotonic: float | None = None
    parsed: bool = False
    user_id: int | None = None
    state: NativeAccessState | None = None
    series_work_id: str | None = None
    series_target_count: int = 0
    series_state: NativeAccessState | None = None
    error: str | None = None


def _site_url(url: str) -> tuple[str | None, str, str, bool]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None, "", "", False
    host = (parsed.hostname or "").lower()
    valid = (
        parsed.scheme.lower() == "https"
        and host == "younganimal.com"
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
    )
    return host or None, parsed.path, parsed.query, valid


def _known_external_subframe_reason(
    *,
    url: str,
    method: str,
    resource_type: str,
    is_navigation: bool,
    is_main_frame: bool,
) -> str | None:
    """Match only the two observed third-party subframe route families."""

    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold()
        path = parsed.path
        try:
            port = parsed.port
            valid_port = port in (None, 443)
        except ValueError:
            valid_port = False
    except ValueError:
        return None

    stripe_path = re.fullmatch(
        r"/v3/(?:controller-with-preconnect|m-outer)-[0-9a-f]{32}\.html",
        path,
    )
    facebook_path = host == "www.facebook.com" and path == "/tr/"
    if host == "js.stripe.com" and stripe_path is not None:
        exact_route = (
            parsed.scheme.casefold() == "https"
            and parsed.username is None
            and parsed.password is None
            and valid_port
            and parsed.query == ""
            and method == "GET"
            and resource_type == "document"
            and is_navigation
            and not is_main_frame
        )
        # The live request summary did not retain fragment state. Stripe's
        # observed route family deliberately ignores fragments and never stores
        # or logs them.
        return "stripe_known_subframe_navigation" if exact_route else "unexpected_stripe_subframe_route"
    if facebook_path:
        exact_route = (
            parsed.scheme.casefold() == "https"
            and parsed.username is None
            and parsed.password is None
            and valid_port
            and parsed.query == ""
            and parsed.fragment == ""
            and method == "POST"
            and resource_type == "document"
            and is_navigation
            and not is_main_frame
        )
        return (
            "facebook_known_subframe_navigation"
            if exact_route
            else "unexpected_facebook_subframe_route"
        )
    return None


def _query_work_ids(query: str) -> tuple[str, ...]:
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=128)
    except ValueError:
        return ("<invalid>",)
    keys = {"seriesid", "workid", "series_id", "work_id"}
    return tuple(value for key, value in pairs if key.casefold() in keys)


def _target_id_in_json(raw: str | None, *, target_id: str) -> bool:
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw.encode("utf-8", errors="ignore")) > MAX_REQUEST_JSON_BYTES
    ):
        return False
    try:
        root = json.loads(raw)
    except (TypeError, ValueError):
        return False
    stack: list[tuple[object, int]] = [(root, 0)]
    visited = 0
    target_found = False
    while stack:
        if visited >= MAX_JSON_NODES:
            return False
        value, depth = stack.pop()
        visited += 1
        if depth > MAX_JSON_DEPTH:
            return False
        if isinstance(value, str) and value == target_id:
            target_found = True
        elif isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)
    return target_found


def _native_access(
    access: object,
    *,
    work_id: str | None,
    episode_id: str,
) -> NativeAccessState | None:
    if not isinstance(access, dict):
        return None
    observed_episode = access.get("episodeId")
    has_access = access.get("hasAccess")
    access_type = access.get("accessType")
    if (
        observed_episode != episode_id
        or type(has_access) is not bool
        or not isinstance(access_type, str)
        or not access_type
        or len(access_type) > 64
    ):
        return None
    if "timeRemainingInSeconds" not in access:
        remaining_state: Literal["missing", "null", "valid", "malformed"] = "missing"
        remaining = None
    else:
        raw_remaining = access.get("timeRemainingInSeconds")
        if raw_remaining is None:
            remaining_state, remaining = "null", None
        elif type(raw_remaining) is int and 0 <= raw_remaining <= 9_007_199_254_740_991:
            remaining_state, remaining = "valid", raw_remaining
        else:
            remaining_state, remaining = "malformed", None
    return NativeAccessState(
        episode_id=episode_id,
        work_id=work_id,
        has_access=has_access,
        access_type=access_type,
        remaining_seconds=remaining,
        remaining_state=remaining_state,
    )


def _scan_exact_episode_access(
    payload: object,
    *,
    episode_id: str,
    expected_access_path: str,
) -> tuple[int, str | None, NativeAccessState | None]:
    stack: list[tuple[object, str, int]] = [(payload, "$", 0)]
    count = 0
    visited = 0
    exact_path_state: NativeAccessState | None = None
    while stack:
        if visited >= MAX_JSON_NODES:
            return -1, None, None
        value, path, depth = stack.pop()
        visited += 1
        if depth > MAX_JSON_DEPTH:
            return -1, None, None
        if isinstance(value, dict):
            if value.get("episodeId") == episode_id:
                count += 1
                if path == expected_access_path:
                    episode = payload.get("episode") if isinstance(payload, dict) else None
                    series = episode.get("series") if isinstance(episode, dict) else None
                    work_id = series.get("id") if isinstance(series, dict) else None
                    if not isinstance(work_id, str) or ID_PATTERN.fullmatch(work_id) is None:
                        work_id = None
                    exact_path_state = _native_access(value, work_id=work_id, episode_id=episode_id)
            stack.extend(
                (child, f"{path}.{key}" if isinstance(key, str) else f"{path}.[key]", depth + 1)
                for key, child in value.items()
            )
        elif isinstance(value, list):
            stack.extend(
                (child, f"{path}[{index}]", depth + 1) for index, child in enumerate(value)
            )
    return count, None, exact_path_state


def _parse_episode_payload(payload: object, *, episode_id: str) -> NativeAccessState | None:
    count, _unused, state = _scan_exact_episode_access(
        payload,
        episode_id=episode_id,
        expected_access_path="$.episode.access",
    )
    if count != 1:
        return None
    return state


def _parse_series_payload(
    payload: object,
    *,
    episode_id: str,
) -> tuple[str | None, int, NativeAccessState | None] | None:
    if not isinstance(payload, dict):
        return None
    series_access = payload.get("seriesAccess")
    if not isinstance(series_access, dict):
        return None
    work_id = series_access.get("seriesId")
    rows = series_access.get("episodeAccesses")
    if (
        not isinstance(work_id, str)
        or ID_PATTERN.fullmatch(work_id) is None
        or not isinstance(rows, list)
        or len(rows) > 3_000
    ):
        return None
    matching = [row for row in rows if isinstance(row, dict) and row.get("episodeId") == episode_id]
    if len(matching) != 1:
        return work_id, len(matching), None
    return (
        work_id,
        1,
        _native_access(matching[0], work_id=work_id, episode_id=episode_id),
    )


def guarded_route_reason(
    *,
    url: str,
    expected_episode_url: str,
    expected_work_id: str,
    resource_type: str,
    method: str,
    is_navigation: bool,
    is_main_frame: bool,
    has_rsc_header: bool = False,
) -> str | None:
    """Classify target routes, including harmless same-work RSC prefetches."""

    external_subframe_reason = _known_external_subframe_reason(
        url=url,
        method=method,
        resource_type=resource_type,
        is_navigation=is_navigation,
        is_main_frame=is_main_frame,
    )
    if external_subframe_reason is not None:
        return external_subframe_reason
    _host, path, query, valid = _site_url(url)
    try:
        has_rsc_query = any(
            key == "_rsc"
            for key, _ in parse_qsl(query, keep_blank_values=True, max_num_fields=128)
        )
    except ValueError:
        has_rsc_query = False
    if is_navigation:
        if not valid:
            return "non_target_navigation"
        if is_main_frame and url != expected_episode_url:
            return "non_target_main_document"
        if not is_main_frame:
            return "unexpected_subframe_navigation"
    # These category paths are exact natural prefetches observed on Items 33403/36914;
    # other category routes remain unknown. Recognition only authorizes abort.
    known_page_rsc_path = path in {
        "/", "/category/manga/day/2/1", "/category/manga/day/1/1",
    } or re.fullmatch(
        r"/store_items/(?:[1-9][0-9]*|series/[1-9][0-9]*/[1-9][0-9]*)", path
    ) is not None
    if not valid:
        if has_rsc_query and known_page_rsc_path:
            return "unknown_rsc_page_route"
        return None
    if path.startswith("/api/"):
        episode = re.fullmatch(r"/api/episodes/([0-9a-f]{13})(?:/.*)?", path)
        if episode is not None and episode.group(1) != expected_episode_url.rsplit("/", 1)[-1]:
            return "other_episode_api_route"
        series = re.fullmatch(r"/api/series/([0-9a-f]{13})(?:/.*)?", path)
        if series is not None and series.group(1) != expected_work_id:
            return "other_work_api_route"
        return None
    expected_path = urlsplit(expected_episode_url).path
    episode_route = re.fullmatch(r"/episodes/([0-9a-f]{13})/?", path)
    if (
        episode_route is not None
        and episode_route.group(1) != expected_episode_url.rsplit("/", 1)[-1]
    ):
        if (
            not is_navigation
            and is_main_frame
            and resource_type == "fetch"
            and method == "GET"
            and path == f"/episodes/{episode_route.group(1)}"
            and has_rsc_query
            and has_rsc_header
        ):
            # A narrowly observed Next.js RSC prefetch for another episode is
            # aborted before it reaches the network. It is not a page visit and
            # does not invalidate the selected episode's current-page operation.
            return "other_episode_rsc_prefetch"
        return "other_episode_page_route"
    if known_page_rsc_path:
        if (
            not is_navigation
            and is_main_frame
            and resource_type == "fetch"
            and method == "GET"
            and has_rsc_query
            and has_rsc_header
        ):
            # These exact same-site RSC prefetch routes were observed during
            # the bounded guard trace. They are aborted before the network and
            # are not treated as page navigations.
            return "known_page_rsc_prefetch"
        return "unknown_rsc_page_route"
    if resource_type in STATIC_RESOURCE_TYPES:
        return None
    if path == expected_path:
        return None
    if (
        not is_navigation
        and resource_type == "fetch"
        and re.fullmatch(re.escape(expected_path) + r"/(?:[1-9][0-9]*|old)", path)
    ):
        # Observed reader RSC requests for the selected episode only. These are
        # not document navigations and never authorize another episode/work.
        return None
    expected_work_path = f"/series/{expected_work_id}"
    series_path = re.fullmatch(
        re.escape(expected_work_path) + r"(?:/(?:1|new|old))?/?", path
    )
    if (
        not is_navigation
        and resource_type == "fetch"
        and method == "GET"
        and series_path is not None
        and has_rsc_query
    ):
        # Next.js can emit this read-only same-work prefetch while rendering an
        # episode. The route guard records and aborts it without treating it as
        # a work-page visit or failing the selected episode operation.
        return "same_work_rsc_prefetch"
    if path == "/episodes" or path.startswith("/episodes/"):
        return "other_episode_page_route"
    series_route = re.fullmatch(r"/series/([0-9a-f]{13})(?:/.*)?/?", path)
    if series_route is not None:
        return "series_page_or_rsc_route"
    if path == "/series" or path.startswith("/series/"):
        return "series_page_or_rsc_route"
    if has_rsc_query:
        return "unknown_rsc_page_route"
    if resource_type == "document":
        return "unknown_document_route"
    return None


class YounganimalLiveAccessObserver:
    """Observe only the exact auth/current/work/checkout signals needed by entry."""

    def __init__(self, *, work_id: str, episode_id: str) -> None:
        self.work_id = work_id
        self.episode_id = episode_id
        self._page: Page | None = None
        self._requests: list[_RequestEvidence] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._click_started_monotonic: float | None = None
        self._overflow = False
        self._incomplete = False
        self._request_listener = self._on_request
        self._response_listener = self._on_response

    @property
    def overflow(self) -> bool:
        return self._overflow

    @property
    def incomplete(self) -> bool:
        return self._incomplete or self._overflow

    def attach(self, page: Page) -> None:
        self._page = page
        page.on("request", self._request_listener)
        page.on("response", self._response_listener)

    def _on_request(self, request: Request) -> None:
        try:
            _host, path, query, valid = _site_url(request.url)
            method = request.method.upper()
        except (AttributeError, PlaywrightError):
            return
        if not valid:
            return
        if method == "GET" and path == _AUTH_PATH:
            kind: Literal["auth", "episode", "series", "checkout"] = "auth"
        elif method == "GET" and path == f"/api/episodes/{self.episode_id}":
            kind = "episode"
        elif method == "GET" and path == _SERIES_PATH:
            kind = "series"
        elif method == "POST" and path == _CHECKOUT_PATH:
            kind = "checkout"
        else:
            return
        if len(self._requests) >= MAX_EVENTS:
            self._overflow = True
            self._incomplete = True
            return
        try:
            page = self._page
            frame = request.frame
            frame_matches = page is not None and frame is page.main_frame
        except (AttributeError, PlaywrightError):
            frame_matches = False
        if not frame_matches or getattr(request, "redirected_from", None) is not None:
            self._incomplete = True
        query_work_ids = _query_work_ids(query) if kind == "series" else ()
        target_bound = False
        if kind == "checkout":
            try:
                target_bound = _target_id_in_json(request.post_data, target_id=self.episode_id)
            except (AttributeError, PlaywrightError):
                target_bound = False
        try:
            started_at = datetime.now(UTC)
            started_monotonic = time.monotonic()
        except (OverflowError, OSError):
            self._incomplete = True
            return
        self._requests.append(
            _RequestEvidence(
                request=request,
                kind=kind,
                path=path,
                started_at=started_at,
                started_monotonic=started_monotonic,
                query_work_ids=query_work_ids,
                target_bound=target_bound,
            )
        )

    def _on_response(self, response: Response) -> None:
        try:
            request = response.request
            _host, path, _query, valid = _site_url(response.url)
            method = request.method.upper()
            if not valid:
                return
        except (AttributeError, PlaywrightError):
            return
        record = next(
            (
                item
                for item in reversed(self._requests)
                if item.request is request and not item.response_seen
            ),
            None,
        )
        if record is None:
            if (
                path in {_AUTH_PATH, _SERIES_PATH, _CHECKOUT_PATH}
                or path == f"/api/episodes/{self.episode_id}"
            ):
                self._incomplete = True
            return
        if record.path != path or method != ("POST" if record.kind == "checkout" else "GET"):
            self._incomplete = True
            record.error = "response_identity_mismatch"
            return
        record.response_seen = True
        record.status = response.status
        record.response_at = datetime.now(UTC)
        record.response_monotonic = time.monotonic()
        if record.kind == "checkout":
            record.parsed = True
            return
        if len(self._tasks) >= MAX_EVENTS:
            self._overflow = True
            self._incomplete = True
            record.error = "response_task_overflow"
            return
        self._tasks.append(asyncio.create_task(self._read_response(record, response)))

    async def _read_response(self, record: _RequestEvidence, response: Response) -> None:
        try:
            if record.status != 200:
                record.error = "non_200"
                return
            headers = response.headers
            content_length = headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_JSON_BYTES:
                        record.error = "response_too_large"
                        return
                except ValueError:
                    record.error = "invalid_content_length"
                    return
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if "json" not in content_type:
                record.error = "unexpected_content_type"
                return
            body = await asyncio.wait_for(response.body(), timeout=OBSERVATION_TIMEOUT_SECONDS)
            if len(body) > MAX_JSON_BYTES:
                record.error = "response_too_large"
                return
            payload = json.loads(body)
        except asyncio.CancelledError:
            raise
        except (PlaywrightError, TimeoutError, TypeError, ValueError, UnicodeDecodeError):
            record.error = "response_parse_failed"
            return
        if record.kind == "auth":
            user = payload.get("user") if isinstance(payload, dict) else None
            record.user_id = user if type(user) is int and user > 0 else None
            record.parsed = record.user_id is not None
            if not record.parsed:
                record.error = "authentication_not_positive"
            return
        if record.kind == "episode":
            count, _unused, state = _scan_exact_episode_access(
                payload,
                episode_id=self.episode_id,
                expected_access_path="$.episode.access",
            )
            record.state = state if count == 1 else None
            record.parsed = count == 1 and state is not None
            if not record.parsed:
                record.error = "current_episode_access_ambiguous_or_invalid"
            return
        parsed_series = _parse_series_payload(payload, episode_id=self.episode_id)
        if parsed_series is None:
            record.error = "series_access_invalid"
            return
        work_id, target_count, state = parsed_series
        record.series_work_id = work_id
        record.series_target_count = target_count
        record.series_state = state
        query_mismatch = any(value != self.work_id for value in record.query_work_ids)
        if work_id != self.work_id or query_mismatch:
            record.error = "series_work_binding_mismatch"
            return
        if target_count > 1:
            record.error = "series_target_duplicate"
            return
        record.parsed = True
        if target_count == 1 and state is None:
            record.error = "series_target_access_invalid"

    async def wait_until_current_observed(self, *, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await self._drain_finished_tasks()
            auth = self.latest_auth(post_click=False)
            episode = self.latest_episode(post_click=False)
            if (
                auth is not None
                and auth.status == 200
                and auth.parsed
                and episode is not None
                and episode.status == 200
                and episode.parsed
            ):
                return True
            if self.incomplete:
                return False
            await asyncio.sleep(min(0.05, max(0.0, deadline - asyncio.get_running_loop().time())))
        await self._drain_finished_tasks()
        return (
            self.latest_auth(post_click=False) is not None
            and self.latest_auth(post_click=False).parsed is True
            and self.latest_episode(post_click=False) is not None
            and self.latest_episode(post_click=False).parsed is True
        )

    async def request_fresh_readonly_state(self, page: Page, *, timeout: float) -> bool:
        """Refresh only the observed read-only auth/current endpoints on this Page."""

        if page.url != f"{BASE_URL}/episodes/{self.episode_id}":
            return False
        endpoints = (
            f"{BASE_URL}{_AUTH_PATH}",
            f"{BASE_URL}/api/episodes/{self.episode_id}",
        )
        try:
            result = await asyncio.wait_for(
                page.evaluate(
                    """async endpoints => {
                      const results = [];
                      for (const url of endpoints) {
                        try {
                          const response = await fetch(url, {
                            method: 'GET', credentials: 'same-origin', cache: 'no-store',
                            redirect: 'error'
                          });
                          await response.arrayBuffer();
                          results.push({status: response.status, url: response.url,
                            redirected: response.redirected});
                        } catch (_) {
                          results.push({status: null, url: null, redirected: null});
                        }
                      }
                      return results;
                    }""",
                    endpoints,
                ),
                timeout=timeout,
            )
        except (PlaywrightError, TimeoutError):
            self._incomplete = True
            return False
        if (
            page.url != f"{BASE_URL}/episodes/{self.episode_id}"
            or not isinstance(result, list)
            or len(result) != 2
            or any(
                not isinstance(row, dict)
                or row.get("status") != 200
                or row.get("url") != endpoint
                or row.get("redirected") is not False
                for row, endpoint in zip(result, endpoints, strict=True)
            )
        ):
            self._incomplete = True
            return False
        return await self.wait_until_current_observed(timeout=timeout)

    async def settle(self, *, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await self._drain_finished_tasks()
            pending_requests = any(not item.response_seen for item in self._requests)
            pending_tasks = any(not task.done() for task in self._tasks)
            if not pending_requests and not pending_tasks:
                return not self.incomplete
            await asyncio.sleep(min(0.05, max(0.0, deadline - asyncio.get_running_loop().time())))
        await self._drain_finished_tasks()
        return (
            not self.incomplete
            and not any(not item.response_seen for item in self._requests)
            and not any(not task.done() for task in self._tasks)
        )

    async def wait_for_series_observations(self, *, post_click: bool, timeout: float) -> bool:
        """Drain any observed same-work aggregate before accepting a state."""

        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await self._drain_finished_tasks()
            if self.incomplete:
                return False
            click_at = self._click_started_monotonic
            records = [
                item
                for item in self._requests
                if item.kind == "series"
                and (
                    (click_at is None or item.started_monotonic < click_at)
                    if not post_click
                    else (click_at is not None and item.started_monotonic > click_at)
                )
            ]
            if all(
                item.response_seen and (item.parsed or item.error is not None) for item in records
            ):
                return all(item.error is None for item in records)
            await asyncio.sleep(min(0.05, max(0.0, deadline - asyncio.get_running_loop().time())))
        await self._drain_finished_tasks()
        return False

    async def _drain_finished_tasks(self) -> None:
        for task in self._tasks:
            if task.done() and (task.cancelled() or task.exception() is not None):
                self._incomplete = True
        self._tasks = [task for task in self._tasks if not task.done()]

    def mark_click_started(self) -> tuple[datetime, float]:
        if self._click_started_monotonic is not None:
            raise RuntimeError("Younganimal work-ticket action was already latched")
        click_at = datetime.now(UTC)
        click_monotonic = time.monotonic()
        self._click_started_monotonic = click_monotonic
        return click_at, click_monotonic

    def latest_auth(self, *, post_click: bool) -> _RequestEvidence | None:
        return self._latest("auth", post_click=post_click)

    def latest_episode(self, *, post_click: bool) -> _RequestEvidence | None:
        return self._latest("episode", post_click=post_click)

    def _latest(self, kind: str, *, post_click: bool) -> _RequestEvidence | None:
        click_at = self._click_started_monotonic
        candidates = [
            item
            for item in self._requests
            if item.kind == kind
            and (
                (click_at is None or item.started_monotonic < click_at)
                if not post_click
                else (click_at is not None and item.started_monotonic > click_at)
            )
        ]
        return max(candidates, key=lambda item: item.started_monotonic) if candidates else None

    def pre_click_state(self) -> NativeAccessState | None:
        auth = self.latest_auth(post_click=False)
        episode = self.latest_episode(post_click=False)
        if (
            self.incomplete
            or auth is None
            or auth.status != 200
            or not auth.parsed
            or auth.user_id is None
            or episode is None
            or episode.status != 200
            or not episode.parsed
            or episode.state is None
            or episode.state.work_id != self.work_id
        ):
            return None
        if self._has_series_conflict(post_click=False, current=episode):
            return None
        return episode.state

    def _has_series_conflict(
        self,
        *,
        post_click: bool,
        current: _RequestEvidence,
    ) -> bool:
        click_at = self._click_started_monotonic
        current_at = current.started_monotonic
        for item in self._requests:
            if item.kind != "series" or not item.response_seen:
                continue
            is_post = click_at is not None and item.started_monotonic > click_at
            if is_post != post_click:
                continue
            if item.error in {
                "series_work_binding_mismatch",
                "series_target_duplicate",
                "series_target_access_invalid",
            }:
                return True
            if item.series_target_count == 1:
                state = item.series_state
                if state is None or state.work_id != self.work_id:
                    return True
                if item.started_monotonic >= current_at and (
                    state.access_type != _ACCESS_TYPE
                    or state.has_access != current.state.has_access
                ):
                    return True
        return False

    async def reconcile_consumption(
        self,
        *,
        before: NativeAccessState,
        timeout: float,
    ) -> ConsumptionProof | None:
        click_at = self._click_started_monotonic
        if (
            click_at is None
            or before.episode_id != self.episode_id
            or before.work_id != self.work_id
            or before.access_type != _ACCESS_TYPE
            or before.has_access is not False
        ):
            return None
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            await self._drain_finished_tasks()
            if self.incomplete:
                return None
            checkout = [
                item
                for item in self._requests
                if item.kind == "checkout" and item.started_monotonic > click_at
            ]
            current = self.latest_episode(post_click=True)
            if len(checkout) > 1:
                return None
            if (
                len(checkout) == 1
                and checkout[0].response_seen
                and checkout[0].status == 200
                and checkout[0].target_bound
                and current is not None
                and current.response_seen
                and current.status == 200
                and current.parsed
                and current.state is not None
                and current.state.work_id == self.work_id
                and current.state.access_type == _ACCESS_TYPE
                and current.state.has_access is True
                and not self._has_series_conflict(post_click=True, current=current)
            ):
                remaining_timeout = max(0.0, deadline - asyncio.get_running_loop().time())
                if not await self.wait_for_series_observations(
                    post_click=True, timeout=remaining_timeout
                ):
                    return None
                current = self.latest_episode(post_click=True)
                checkout = [
                    item
                    for item in self._requests
                    if item.kind == "checkout" and item.started_monotonic > click_at
                ]
                if (
                    len(checkout) != 1
                    or current is None
                    or current.status != 200
                    or not current.parsed
                    or current.state is None
                    or current.state.work_id != self.work_id
                    or current.state.access_type != _ACCESS_TYPE
                    or current.state.has_access is not True
                    or self._has_series_conflict(post_click=True, current=current)
                ):
                    return None
                expiry: datetime | None = None
                seconds = current.state.remaining_seconds
                if (
                    current.state.remaining_state == "valid"
                    and type(seconds) is int
                    and seconds > 0
                ):
                    try:
                        candidate_expiry = current.started_at + timedelta(seconds=seconds - 1)
                        if candidate_expiry > datetime.now(UTC):
                            expiry = candidate_expiry
                    except (OverflowError, ValueError):
                        expiry = None
                assert checkout[0].response_at is not None
                return ConsumptionProof(
                    consumed_at=checkout[0].response_at,
                    access_granted_until=expiry,
                )
            await asyncio.sleep(min(0.05, max(0.0, deadline - asyncio.get_running_loop().time())))
        await self._drain_finished_tasks()
        return None

    async def close(self) -> None:
        page, self._page = self._page, None
        if page is not None:
            try:
                page.remove_listener("request", self._request_listener)
                page.remove_listener("response", self._response_listener)
            except PlaywrightError:
                pass
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            done, remaining = await asyncio.wait(pending, timeout=1.0)
            for task in done:
                if not task.cancelled() and task.exception() is not None:
                    self._incomplete = True
            for task in remaining:
                task.add_done_callback(_consume_task)


class YounganimalEpisodeRouteGuard:
    """Abort off-target page routes while leaving APIs and static assets available."""

    def __init__(self, *, work_id: str, episode_id: str) -> None:
        self.work_id = work_id
        self.episode_id = episode_id
        self.expected_episode_url = f"{BASE_URL}/episodes/{episode_id}"
        self._page: Page | None = None
        self._handler = self._handle_route
        self.failure_reason: str | None = None
        self.failure_request: dict[str, object] | None = None
        self.blocked_count = 0
        self.same_work_prefetch_count = 0
        self.same_work_prefetch_paths: list[str] = []
        self.other_episode_prefetch_count = 0
        self.other_episode_prefetch_paths: list[str] = []
        self.known_page_rsc_prefetch_count = 0
        self.known_page_rsc_prefetch_paths: list[str] = []
        self.stripe_subframe_count = 0
        self.stripe_subframe_paths: list[str] = []
        self.facebook_subframe_count = 0
        self.facebook_subframe_paths: list[str] = []

    async def attach(self, page: Page) -> None:
        self._page = page
        await page.route("**/*", self._handler)

    async def _handle_route(self, route: Route) -> None:
        request = route.request
        try:
            frame = request.frame
            page = self._page
            is_main_frame = page is not None and frame is page.main_frame
            reason = guarded_route_reason(
                url=request.url,
                expected_episode_url=self.expected_episode_url,
                expected_work_id=self.work_id,
                resource_type=request.resource_type,
                method=request.method,
                is_navigation=request.is_navigation_request(),
                is_main_frame=is_main_frame,
                has_rsc_header=any(
                    name.casefold() == "rsc" for name in request.headers
                ),
            )
            if reason in {
                "same_work_rsc_prefetch",
                "other_episode_rsc_prefetch",
                "known_page_rsc_prefetch",
                "stripe_known_subframe_navigation",
                "facebook_known_subframe_navigation",
            }:
                self.blocked_count += 1
                if reason == "same_work_rsc_prefetch":
                    self.same_work_prefetch_count += 1
                    if len(self.same_work_prefetch_paths) < MAX_RECORDED_ROUTE_PREFETCHES:
                        self.same_work_prefetch_paths.append(urlsplit(request.url).path)
                elif reason == "other_episode_rsc_prefetch":
                    self.other_episode_prefetch_count = min(
                        self.other_episode_prefetch_count + 1,
                        MAX_RECORDED_ROUTE_PREFETCHES,
                    )
                    if len(self.other_episode_prefetch_paths) < MAX_RECORDED_ROUTE_PREFETCHES:
                        self.other_episode_prefetch_paths.append(urlsplit(request.url).path)
                else:
                    path = urlsplit(request.url).path
                    if reason == "known_page_rsc_prefetch":
                        self.known_page_rsc_prefetch_count = min(
                            self.known_page_rsc_prefetch_count + 1,
                            MAX_RECORDED_ROUTE_PREFETCHES,
                        )
                        if (
                            len(self.known_page_rsc_prefetch_paths)
                            < MAX_RECORDED_ROUTE_PREFETCHES
                        ):
                            self.known_page_rsc_prefetch_paths.append(path)
                    elif reason == "stripe_known_subframe_navigation":
                        self.stripe_subframe_count = min(
                            self.stripe_subframe_count + 1,
                            MAX_RECORDED_ROUTE_PREFETCHES,
                        )
                        if len(self.stripe_subframe_paths) < MAX_RECORDED_ROUTE_PREFETCHES:
                            self.stripe_subframe_paths.append(path)
                    else:
                        self.facebook_subframe_count = min(
                            self.facebook_subframe_count + 1,
                            MAX_RECORDED_ROUTE_PREFETCHES,
                        )
                        if len(self.facebook_subframe_paths) < MAX_RECORDED_ROUTE_PREFETCHES:
                            self.facebook_subframe_paths.append(path)
                await route.abort()
                return
            if reason is not None:
                self.blocked_count += 1
                if self.failure_reason is None:
                    self.failure_reason = reason
                    parsed = urlsplit(request.url)
                    # Retain only bounded structural evidence, never raw URLs,
                    # query/header values, credentials, fragments, or bodies.
                    self.failure_request = {
                        "host": (parsed.hostname or "")[:253],
                        "path": parsed.path[:512],
                        "method": request.method[:16],
                        "resource_type": request.resource_type[:32],
                        "is_navigation": request.is_navigation_request(),
                        "is_main_frame": is_main_frame,
                    }
                await route.abort()
                return
            await route.fallback()
        except asyncio.CancelledError:
            raise
        except (PlaywrightError, AttributeError, ValueError):
            self.failure_reason = self.failure_reason or "route_guard_error"
            try:
                await route.abort()
            except PlaywrightError:
                pass

    def raise_if_failed(self) -> None:
        if self.failure_reason is not None:
            raise RuntimeError(
                f"Younganimal episode route guard blocked access: {self.failure_reason}"
            )

    def collect_debug_metadata(self) -> dict[str, object]:
        return {
            "failure_reason": self.failure_reason,
            "failure_request": (
                dict(self.failure_request) if self.failure_request is not None else None
            ),
            "blocked_count": self.blocked_count,
            "known_page_rsc_prefetch_count": self.known_page_rsc_prefetch_count,
            "known_page_rsc_prefetch_paths": list(self.known_page_rsc_prefetch_paths),
        }

    async def close(self) -> None:
        page, self._page = self._page, None
        if page is not None:
            try:
                await page.unroute("**/*", self._handler)
            except PlaywrightError:
                pass


def _consume_task(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    task.exception()


__all__ = [
    "ConsumptionProof",
    "NativeAccessState",
    "YounganimalEpisodeRouteGuard",
    "YounganimalLiveAccessObserver",
    "guarded_route_reason",
]

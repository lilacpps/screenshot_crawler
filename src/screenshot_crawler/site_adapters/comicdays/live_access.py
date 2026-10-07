"""Bounded, read-only Comic DAYS access observations.

This module owns the small amount of site-native state needed by the adapter
and resolver.  It deliberately contains no mutation request and never clicks
an access control.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicdays.discovery import (
    comicdays_access_observation,
    fetch_comicdays_atom,
    fetch_comicdays_listing_total,
    fetch_comicdays_readable_products,
    parse_comicdays_episode_url,
)

COMICDAYS_LIVE_ACCESS_TIMEOUT_MS = 15_000
COMICDAYS_TARGET_ACCESS_STABILIZATION_MS = 2_000
COMICDAYS_TARGET_ACCESS_POLL_MS = 50
MAX_GRAPHQL_BODY = 100_000
TraceSink = Callable[[str, dict[str, object]], None]
TICKET_QUERY = """
query Viewer_SeriesTicketQuery($id: String!) {
  userAccount { eventTicketCount }
  series(databaseId: $id) { ticket { isCharged chargedAt } }
}
"""


class ComicDaysLiveAccessError(RuntimeError):
    """Raised when a bounded live access observation is not authoritative."""


class ComicDaysTargetIdentityMismatch(ComicDaysLiveAccessError):
    """Raised when the selected page positively identifies another target."""


@dataclass(frozen=True, slots=True)
class ComicDaysTicketState:
    series_id: str
    is_charged: bool | None
    charged_at: datetime | None
    event_ticket_count: int | None = None
    graphql_status: int | None = None
    graphql_elapsed_ms: int | None = None
    ticket_present: bool = True


@dataclass(frozen=True, slots=True)
class ComicDaysLiveAccessState:
    series_id: str
    episode_id: str
    row: dict[str, object]
    access_mode: str
    grant_until: datetime | None
    grant_observed: bool
    ticket: ComicDaysTicketState
    viewer_unlocked: bool = False
    rental_term_hours: int | None = None
    rental_term_seconds: int | None = None
    canonical_url: str | None = None
    private_viewer_count: int = 0
    normal_viewer_count: int = 0
    normal_viewer_visible: bool = False
    normal_viewer_json: str | None = None
    ticket_control_count: int = 0
    dom_snapshot: dict[str, object] | None = None


def _safe_diagnostic_url(value: object) -> str:
    """Keep only a credential-free, query-free URL shape for diagnostics."""

    raw = str(value or "")
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        try:
            port = parts.port
        except ValueError:
            port = None
        netloc = host + (f":{port}" if port is not None else "")
        return urlunsplit((parts.scheme, netloc, parts.path, "", ""))[:500]
    except (TypeError, ValueError):
        return raw.split("?", 1)[0].split("#", 1)[0][:500]


def _emit_trace(
    trace_sink: TraceSink | None,
    phase: str,
    fields: dict[str, object],
) -> None:
    if trace_sink is None:
        return
    try:
        trace_sink(phase, fields)
    except Exception:  # noqa: BLE001 - diagnostics must never change access behavior
        return


def _dom_trace_metadata(
    dom: dict[str, object], *, expected_episode_id: str
) -> dict[str, object]:
    """Reduce the live DOM snapshot to bounded, body-free metadata."""

    private_rows = dom.get("private")
    normal_rows = dom.get("normal")
    aggregate_rows = dom.get("aggregate")
    contract_rows = dom.get("contract")
    ticket_rows = dom.get("ticket")
    purchase_rows = dom.get("purchase")
    private = private_rows if isinstance(private_rows, list) else []
    normal = normal_rows if isinstance(normal_rows, list) else []
    aggregates = aggregate_rows if isinstance(aggregate_rows, list) else []
    contracts = contract_rows if isinstance(contract_rows, list) else []
    tickets = ticket_rows if isinstance(ticket_rows, list) else []
    purchases = purchase_rows if isinstance(purchase_rows, list) else []
    expected_json = f"https://comic-days.com/episode/{expected_episode_id}.json"

    def ids(rows: list[object]) -> list[str]:
        values: list[str] = []
        for row in rows[:32]:
            if isinstance(row, dict) and row.get("aggregate_id") is not None:
                values.append(str(row["aggregate_id"]))
        return values

    ticket = tickets[0] if len(tickets) == 1 and isinstance(tickets[0], dict) else {}
    contract = contracts[0] if len(contracts) == 1 and isinstance(contracts[0], dict) else {}
    rental_term = contract.get("rental_term")
    rental_term_value = (
        int(rental_term) if isinstance(rental_term, str) and rental_term.isdigit() else None
    )
    return {
        "url": _safe_diagnostic_url(dom.get("url")),
        "private_viewer_count": len(private),
        "normal_viewer_count": len(normal),
        "normal_viewer_visible": bool(normal[0].get("visible"))
        if len(normal) == 1 and isinstance(normal[0], dict)
        else False,
        "private_json_matches_expected": len(private) == 1
        and isinstance(private[0], dict)
        and private[0].get("json") == expected_json,
        "normal_json_matches_expected": len(normal) == 1
        and isinstance(normal[0], dict)
        and normal[0].get("json") == expected_json,
        "aggregate_count": len(aggregates),
        "aggregate_ids": ids(aggregates),
        "contract_count": len(contracts),
        "contract_aggregate_ids": ids(contracts),
        "rental_term": rental_term_value,
        "ticket_control_count": len(tickets),
        "ticket_visible": ticket.get("visible") if ticket else None,
        "ticket_enabled": ticket.get("enabled") if ticket else None,
        "ticket_label": str(ticket.get("label", ""))[:200] if ticket else None,
        "purchase_control_count": len(purchases),
    }


@dataclass(frozen=True, slots=True)
class ComicDaysListingState:
    """One complete Atom/readable-product observation for a series."""

    series_id: str
    rows: tuple[dict[str, object], ...]
    free_ids: frozenset[str]
    ticket: ComicDaysTicketState


async def observe_comicdays_ticket(
    page: Page,
    series_id: str,
    *,
    timeout_ms: int = COMICDAYS_LIVE_ACCESS_TIMEOUT_MS,
    trace_sink: TraceSink | None = None,
) -> ComicDaysTicketState:
    if not str(series_id).isdigit():
        raise ComicDaysLiveAccessError("Comic DAYS series identity is not numeric")
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    query_timeout = min(timeout_ms, 15_000)
    deadline = asyncio.get_running_loop().time() + query_timeout / 1000
    query_started = time.monotonic()
    graphql_status: int | None = None
    is_charged: bool | None = None
    charged_at: datetime | None = None
    count: int | None = None
    ticket_present = True
    try:
        try:
            remaining = _remaining_ms(deadline)
            if remaining <= 0:
                raise ComicDaysLiveAccessError("Comic DAYS ticket query timed out")
            response = await page.request.post(
                "https://comic-days.com/graphql?opname=Viewer_SeriesTicketQuery",
                data={"query": TICKET_QUERY, "variables": {"id": str(series_id)}},
                headers={"Content-Type": "application/json"},
                timeout=remaining,
                fail_on_status_code=False,
            )
            raw_status = getattr(response, "status", None)
            if isinstance(raw_status, int) and not isinstance(raw_status, bool):
                graphql_status = raw_status
            if graphql_status != 200:
                raise ComicDaysLiveAccessError("Comic DAYS ticket query returned a non-200 status")
            remaining = _remaining_ms(deadline)
            if remaining <= 0:
                raise ComicDaysLiveAccessError("Comic DAYS ticket query timed out")
            body = await asyncio.wait_for(response.body(), timeout=remaining / 1000)
        except (PlaywrightTimeoutError, TimeoutError) as exc:
            raise ComicDaysLiveAccessError("Comic DAYS ticket query timed out") from exc
        if len(body) > MAX_GRAPHQL_BODY:
            raise ComicDaysLiveAccessError("Comic DAYS ticket query exceeded the body limit")
        try:
            payload = json.loads(body.decode("utf-8"))
            data = payload["data"]
            series = data["series"]
            ticket = series["ticket"]
            account = data["userAccount"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ComicDaysLiveAccessError("Comic DAYS ticket query had an invalid shape") from exc
        if not isinstance(account, dict):
            raise ComicDaysLiveAccessError("Comic DAYS ticket query omitted ticket state")
        if ticket is not None and not isinstance(ticket, dict):
            raise ComicDaysLiveAccessError("Comic DAYS ticket query had an invalid shape")
        ticket_present = ticket is not None
        if ticket_present:
            is_charged = ticket.get("isCharged")
            if not isinstance(is_charged, bool):
                raise ComicDaysLiveAccessError("Comic DAYS ticket readiness was malformed")
            raw_charged_at = ticket.get("chargedAt")
            if raw_charged_at is not None:
                if not isinstance(raw_charged_at, str):
                    raise ComicDaysLiveAccessError("Comic DAYS ticket chargedAt was malformed")
                try:
                    charged_at = datetime.fromisoformat(raw_charged_at)
                except ValueError as exc:
                    raise ComicDaysLiveAccessError("Comic DAYS ticket chargedAt was invalid") from exc
                if charged_at.tzinfo is None or charged_at.utcoffset() is None:
                    raise ComicDaysLiveAccessError("Comic DAYS ticket chargedAt was timezone-naive")
                charged_at = charged_at.astimezone(UTC)
        count = account.get("eventTicketCount")
        if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
            raise ComicDaysLiveAccessError("Comic DAYS event ticket count was malformed")
        return ComicDaysTicketState(
            str(series_id),
            is_charged,
            charged_at,
            count,
            graphql_status,
            int((time.monotonic() - query_started) * 1000),
            ticket_present,
        )
    finally:
        _emit_trace(
            trace_sink,
            "ticket_query_result",
            {
                "series_id": str(series_id),
                "is_charged": is_charged,
                "ticket_present": ticket_present,
                "charged_at": charged_at.isoformat() if charged_at is not None else None,
                "event_ticket_count": count,
                "graphql_status": graphql_status,
                "elapsed_ms": int((time.monotonic() - query_started) * 1000),
            },
        )


async def observe_comicdays_live_access(
    page: Page,
    *,
    series_id: str,
    episode_id: str,
    timeout_ms: int = COMICDAYS_LIVE_ACCESS_TIMEOUT_MS,
) -> ComicDaysLiveAccessState:
    """Validate one complete listing and return the target's current state."""

    if not str(series_id).isdigit() or not str(episode_id).isdigit():
        raise ComicDaysLiveAccessError("Comic DAYS access identity is not numeric")
    current = parse_comicdays_episode_url(str(page.url))
    if current != str(episode_id):
        raise ComicDaysLiveAccessError("Comic DAYS page URL did not match the target episode")
    listing = await observe_comicdays_listing(page, series_id=series_id, episode_id=episode_id, timeout_ms=timeout_ms)
    try:
        row = next(row for row in listing.rows if str(row.get("readable_product_id")) == str(episode_id))
        mode, expiry, observed = comicdays_access_observation(
            row, free=str(episode_id) in listing.free_ids, now=datetime.now(UTC)
        )
    except (DiscoveryIncompleteError, StopIteration) as exc:
        raise ComicDaysLiveAccessError(str(exc)) from exc
    if not listing.ticket.ticket_present and mode != "free":
        raise ComicDaysLiveAccessError(
            "Comic DAYS ticket-free series did not identify a free target"
        )
    return ComicDaysLiveAccessState(str(series_id), str(episode_id), row, mode, expiry, observed, listing.ticket)


async def _observe_target_dom_snapshot(page: Page, *, timeout_ms: int) -> dict[str, object]:
    """Read target identity/access DOM atomically after the ticket query.

    Playwright Locator calls are intentionally avoided here.  Comic DAYS can
    replace the private viewer with the unlocked viewer while the GraphQL
    request is in flight; querying the current document in one evaluate avoids
    reusing a detached scope and keeps the operation bounded.
    """

    if timeout_ms <= 0:
        raise ComicDaysLiveAccessError("Comic DAYS target access observation timed out")
    script = """
    () => {
      const visible = (node) => {
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          rect.width > 0 && rect.height > 0;
      };
      const viewer = (node) => ({
        json: node.getAttribute('data-json-url'), visible: visible(node),
      });
      const control = (node) => ({
        visible: visible(node), enabled: !node.disabled,
        label: (node.innerText || '').trim(),
        rental_id: node.getAttribute('data-ticket-rental-id'),
        behaviour: node.getAttribute('data-behaviour'),
        title: node.getAttribute('title'),
        buy_price: node.getAttribute('data-buy-price'),
        onclick: node.getAttribute('onclick'),
      });
      const aggregate = Array.from(document.querySelectorAll('[data-aggregate-id][data-type="episode"]'))
        .map((node) => ({aggregate_id: node.getAttribute('data-aggregate-id')}));
      const contract = Array.from(document.querySelectorAll('.js-readable-products-pagination[data-type="episode"][data-aggregate-id]'))
        .map((node) => ({
          aggregate_id: node.getAttribute('data-aggregate-id'),
          rental_term: node.getAttribute('data-rental-term'),
        }));
      return {
        url: location.href,
        private: Array.from(document.querySelectorAll('section.private-viewer.js-viewer[data-json-url]')).map(viewer),
        normal: Array.from(document.querySelectorAll('section.viewer.js-viewer[data-json-url]')).map(viewer),
        aggregate, contract,
        ticket: Array.from(document.querySelectorAll('section.private-viewer.js-viewer[data-json-url] button[data-test-id="use-series-ticket-button"][data-ticket-type="series"], section.viewer.js-viewer[data-json-url] button[data-test-id="use-series-ticket-button"][data-ticket-type="series"]')).map(control),
        purchase: Array.from(document.querySelectorAll('section.private-viewer.js-viewer[data-json-url] [data-test-id="purchase-button"]')).map(control),
      };
    }
    """
    try:
        value = await asyncio.wait_for(page.evaluate(script), timeout=timeout_ms / 1000)
    except (PlaywrightTimeoutError, TimeoutError) as exc:
        raise ComicDaysLiveAccessError("Comic DAYS target DOM snapshot timed out") from exc
    if not isinstance(value, dict):
        raise ComicDaysLiveAccessError("Comic DAYS target DOM snapshot was malformed")
    return value


def _is_transient_hidden_ticket_state(
    dom: dict[str, object],
    *,
    ticket_state: ComicDaysTicketState,
    episode_id: str,
) -> bool:
    """Return whether a narrowly defined viewer-hydration race may be retried.

    The page can briefly retain the locked viewer and its exact Work Ticket
    control while the control is still hidden.  This is the only ambiguous
    state that gets a short read-only re-observation window.  Duplicate,
    malformed, identity-mismatched, or paid-only controls remain fail-closed.
    """

    if not ticket_state.ticket_present or ticket_state.is_charged is not True:
        return False
    private_rows = dom.get("private")
    normal_rows = dom.get("normal")
    ticket_rows = dom.get("ticket")
    purchase_rows = dom.get("purchase")
    if (
        not isinstance(private_rows, list)
        or len(private_rows) != 1
        or not isinstance(normal_rows, list)
        or len(normal_rows) != 0
        or not isinstance(ticket_rows, list)
        or len(ticket_rows) != 1
        or not isinstance(purchase_rows, list)
        or len(purchase_rows) > 1
        or not isinstance(ticket_rows[0], dict)
    ):
        return False
    control = ticket_rows[0]
    return (
        control.get("visible") is False
        and control.get("enabled") is True
        and control.get("rental_id") == str(episode_id)
        and control.get("behaviour") == "button"
        and control.get("buy_price") is None
        and control.get("onclick") is None
    )


def _classify_comicdays_target_dom(
    dom: dict[str, object],
    *,
    dom_trace: dict[str, object],
    ticket_state: ComicDaysTicketState,
    series_id: str,
    episode_id: str,
) -> ComicDaysLiveAccessState:
    """Validate and classify one atomic target DOM snapshot."""

    current = parse_comicdays_episode_url(str(dom.get("url", "")))
    if current != str(episode_id):
        raise ComicDaysTargetIdentityMismatch(
            "Comic DAYS target page identity did not match"
        )
    aggregate = dom.get("aggregate")
    if (
        not isinstance(aggregate, list)
        or len(aggregate) != 1
        or not isinstance(aggregate[0], dict)
    ):
        raise ComicDaysLiveAccessError("Comic DAYS target work identity was missing or ambiguous")
    aggregate_id = aggregate[0].get("aggregate_id")
    if aggregate_id != str(series_id):
        raise ComicDaysTargetIdentityMismatch(
            "Comic DAYS target work identity did not match"
        )
    contract = dom.get("contract")
    if (
        not isinstance(contract, list)
        or len(contract) != 1
        or not isinstance(contract[0], dict)
    ):
        raise ComicDaysLiveAccessError("Comic DAYS target ticket contract was missing")
    contract_id = contract[0].get("aggregate_id")
    raw_term = contract[0].get("rental_term")
    if contract_id != str(series_id) or not isinstance(raw_term, str) or not raw_term.isdigit():
        raise ComicDaysLiveAccessError("Comic DAYS target ticket contract was unknown")
    seconds = int(raw_term)
    rental_term_hours = seconds // 3600
    private_rows = dom.get("private")
    viewer_rows = dom.get("normal")
    private_count = len(private_rows) if isinstance(private_rows, list) else 0
    viewer_count = len(viewer_rows) if isinstance(viewer_rows, list) else 0
    if private_count == 1 and viewer_count == 1:
        raise ComicDaysLiveAccessError("Comic DAYS viewer scopes were ambiguous")
    if private_count > 1 or viewer_count > 1:
        raise ComicDaysLiveAccessError("Comic DAYS viewer scope was ambiguous")
    expected_json = f"https://comic-days.com/episode/{episode_id}.json"
    viewer_unlocked = False
    mode = "unknown"
    row: dict[str, object] = {
        "status": {"rental_term": rental_term_hours},
        "purchase_info": {
            "can_read": False,
            "is_free": False,
            "has_rented_via_ticket": False,
        },
    }
    ticket_rows = dom.get("ticket")
    purchase_rows = dom.get("purchase")
    ticket_count = len(ticket_rows) if isinstance(ticket_rows, list) else 0
    purchase_count = len(purchase_rows) if isinstance(purchase_rows, list) else 0
    if private_count == 1:
        private_json = private_rows[0].get("json") if isinstance(private_rows[0], dict) else None
        if private_json != expected_json:
            raise ComicDaysTargetIdentityMismatch(
                "Comic DAYS locked viewer identity did not match"
            )
        # A positive work-level debit state is authoritative for cooldown.
        # Evaluate it before interpreting stale/hidden controls or a paid
        # control on the locked page.
        if ticket_state.is_charged is False or (
            ticket_count == 1
            and isinstance(ticket_rows[0], dict)
            and bool(ticket_rows[0].get("visible"))
        ):
            mode = "quota"
        elif ticket_count != 0:
            # A hidden or duplicate Work Ticket control is still a positive
            # access-control surface. Never reinterpret it as a
            # purchase-only page while hydration or routing is ambiguous.
            mode = "unknown"
        elif (
            purchase_count == 1
            and isinstance(purchase_rows[0], dict)
            and bool(purchase_rows[0].get("visible"))
        ):
            mode = "paid"
        else:
            mode = "unknown"
    elif viewer_count == 1:
        normal = viewer_rows[0] if isinstance(viewer_rows[0], dict) else {}
        if normal.get("json") != expected_json:
            raise ComicDaysTargetIdentityMismatch(
                "Comic DAYS viewer identity did not match"
            )
        mode = "free"
        # Access mode is still free when the identity is correct, but the
        # post-click success contract additionally requires a visible normal
        # viewer. Keep that readiness bit explicit so a hidden viewer cannot
        # be mistaken for positive consumption.
        viewer_unlocked = bool(normal.get("visible"))
        row["purchase_info"] = {
            "can_read": True,
            "is_free": True,
            "has_rented_via_ticket": False,
        }
    else:
        raise ComicDaysLiveAccessError("Comic DAYS viewer scope was missing or ambiguous")
    return ComicDaysLiveAccessState(
        str(series_id), str(episode_id), row, mode, None, mode == "quota",
        ticket_state, viewer_unlocked, rental_term_hours, seconds,
        str(dom.get("url")), private_count, viewer_count,
        bool(viewer_rows[0].get("visible"))
        if viewer_count == 1 and isinstance(viewer_rows[0], dict)
        else False,
        viewer_rows[0].get("json")
        if viewer_count == 1 and isinstance(viewer_rows[0], dict)
        else None,
        ticket_count,
        dom_trace,
    )


async def observe_comicdays_target_access(
    page: Page,
    *,
    series_id: str,
    episode_id: str,
    timeout_ms: int = COMICDAYS_LIVE_ACCESS_TIMEOUT_MS,
    trace_sink: TraceSink | None = None,
) -> ComicDaysLiveAccessState:
    """Observe only the selected episode and work-level ticket state.

    Discovery owns the complete listing.  Batch entry intentionally reads the
    target page's identity, contract metadata, access controls, and the small
    work-ticket GraphQL state without refreshing the whole episode listing.
    """

    if not str(series_id).isdigit() or not str(episode_id).isdigit():
        raise ComicDaysLiveAccessError("Comic DAYS target identity is not numeric")
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    current = parse_comicdays_episode_url(str(page.url))
    if current != str(episode_id):
        raise ComicDaysTargetIdentityMismatch(
            "Comic DAYS page URL did not match the target episode"
        )
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    try:
        # The ticket GraphQL call can trigger a first-party route/viewer swap.
        # Never retain counts or Locators across that await.  The atomic DOM
        # snapshot below is evaluated after GraphQL and has its own bounded
        # timeout, so a removed scope cannot consume Playwright's default
        # 30-second Locator wait.
        ticket_state = await observe_comicdays_ticket(
            page, str(series_id), timeout_ms=timeout_ms, trace_sink=trace_sink
        )
        if not ticket_state.ticket_present:
            raise ComicDaysLiveAccessError(
                "Comic DAYS target access requires ticket state"
            )
        loop = asyncio.get_running_loop()
        stabilization_deadline = min(
            deadline,
            loop.time() + COMICDAYS_TARGET_ACCESS_STABILIZATION_MS / 1000,
        )
        stabilization_attempt = 0
        last_state: ComicDaysLiveAccessState | None = None
        while True:
            remaining = _remaining_ms(deadline)
            if remaining <= 0:
                if last_state is not None:
                    _emit_trace(
                        trace_sink,
                        "access_stabilization",
                        {
                            "attempt": stabilization_attempt,
                            "status": "timeout",
                            "reason": "hidden_ticket_control",
                        },
                    )
                    return last_state
                raise ComicDaysLiveAccessError("Comic DAYS target access observation timed out")
            dom = await _observe_target_dom_snapshot(page, timeout_ms=remaining)
            dom_trace = _dom_trace_metadata(dom, expected_episode_id=str(episode_id))
            dom_trace["stabilization_attempt"] = stabilization_attempt
            _emit_trace(trace_sink, "dom_snapshot", dom_trace)
            state = _classify_comicdays_target_dom(
                dom,
                dom_trace=dom_trace,
                ticket_state=ticket_state,
                series_id=str(series_id),
                episode_id=str(episode_id),
            )
            last_state = state
            if state.access_mode != "unknown" or not _is_transient_hidden_ticket_state(
                dom,
                ticket_state=ticket_state,
                episode_id=str(episode_id),
            ):
                if stabilization_attempt:
                    _emit_trace(
                        trace_sink,
                        "access_stabilization",
                        {
                            "attempt": stabilization_attempt,
                            "status": "resolved",
                        },
                    )
                return state
            remaining_stabilization = max(
                0, int((stabilization_deadline - loop.time()) * 1000)
            )
            if remaining_stabilization <= 0:
                _emit_trace(
                    trace_sink,
                    "access_stabilization",
                    {
                        "attempt": stabilization_attempt,
                        "status": "timeout",
                        "reason": "hidden_ticket_control",
                    },
                )
                return state
            stabilization_attempt += 1
            _emit_trace(
                trace_sink,
                "access_stabilization",
                {
                    "attempt": stabilization_attempt,
                    "status": "retry",
                    "reason": "hidden_ticket_control",
                    "remaining_ms": remaining_stabilization,
                },
            )
            await asyncio.sleep(
                min(COMICDAYS_TARGET_ACCESS_POLL_MS, remaining_stabilization) / 1000
            )
    except (PlaywrightTimeoutError, TimeoutError) as exc:
        raise ComicDaysLiveAccessError("Comic DAYS target access observation timed out") from exc


async def observe_comicdays_listing(
    page: Page,
    *,
    series_id: str,
    episode_id: str,
    timeout_ms: int = COMICDAYS_LIVE_ACCESS_TIMEOUT_MS,
) -> ComicDaysListingState:
    """Validate one complete listing and one work-level ticket query."""

    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    current = parse_comicdays_episode_url(str(page.url))
    if current != str(episode_id):
        raise ComicDaysLiveAccessError("Comic DAYS page URL did not match the target episode")
    try:
        full = await _bounded_call(
            fetch_comicdays_atom(page, str(series_id), free_only=False), deadline
        )
        free = await _bounded_call(
            fetch_comicdays_atom(page, str(series_id), free_only=True), deadline
        )
        total = await _bounded_call(
            fetch_comicdays_listing_total(page, str(series_id), str(episode_id)), deadline
        )
        rows = await _bounded_call(
            fetch_comicdays_readable_products(page, str(series_id), expected_total=total), deadline
        )
        full_ids = [str(item["episode_id"]) for item in full]
        if len(full_ids) != total or len(set(full_ids)) != total:
            raise DiscoveryIncompleteError("Comic DAYS listing identity/count mismatch")
        row_ids = [str(item.get("readable_product_id")) for item in rows]
        if row_ids != full_ids:
            raise DiscoveryIncompleteError("Comic DAYS listing order disagreed with Atom")
        if str(episode_id) not in full_ids:
            raise DiscoveryIncompleteError("Comic DAYS target was absent from the complete listing")
        free_ids = {str(item["episode_id"]) for item in free}
        if not free_ids.issubset(set(full_ids)):
            raise DiscoveryIncompleteError("Comic DAYS free listing contained an unknown episode")
        if [item_id for item_id in full_ids if item_id in free_ids] != [str(item["episode_id"]) for item in free]:
            raise DiscoveryIncompleteError("Comic DAYS free listing order disagreed with Atom")
    except (DiscoveryIncompleteError, StopIteration) as exc:
        raise ComicDaysLiveAccessError(str(exc)) from exc
    remaining = _remaining_ms(deadline)
    if remaining <= 0:
        raise ComicDaysLiveAccessError("Comic DAYS listing observation exceeded its time bound")
    ticket = await _bounded_call(
        observe_comicdays_ticket(page, str(series_id), timeout_ms=remaining), deadline
    )
    return ComicDaysListingState(str(series_id), tuple(rows), frozenset(free_ids), ticket)


def _remaining_ms(deadline: float) -> int:
    return max(0, int((deadline - asyncio.get_running_loop().time()) * 1000))


async def _bounded_call(awaitable: Awaitable[Any], deadline: float) -> Any:
    remaining = _remaining_ms(deadline)
    if remaining <= 0:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise ComicDaysLiveAccessError("Comic DAYS listing observation exceeded its time bound")
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining / 1000)
    except TimeoutError as exc:
        raise ComicDaysLiveAccessError("Comic DAYS listing observation exceeded its time bound") from exc


__all__ = [
    "COMICDAYS_LIVE_ACCESS_TIMEOUT_MS",
    "ComicDaysListingState",
    "ComicDaysLiveAccessError",
    "ComicDaysLiveAccessState",
    "ComicDaysTargetIdentityMismatch",
    "ComicDaysTicketState",
    "observe_comicdays_listing",
    "observe_comicdays_live_access",
    "observe_comicdays_target_access",
    "observe_comicdays_ticket",
]

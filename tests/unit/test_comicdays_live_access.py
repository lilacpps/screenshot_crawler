from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicdays.discovery import fetch_comicdays_readable_products
from screenshot_crawler.site_adapters.comicdays.live_access import (
    ComicDaysLiveAccessError,
    observe_comicdays_listing,
    observe_comicdays_live_access,
    observe_comicdays_ticket,
)


def _atom(episode_id: str) -> bytes:
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><id>comicdays:episode:' + episode_id + '</id>'
        '<title>第1話</title><link href="https://comic-days.com/episode/' + episode_id + '"/>'
        '</entry></feed>'
    ).encode()


def _atom_entries(*episode_ids: str) -> bytes:
    entries = "".join(
        f'<entry><id>comicdays:episode:{episode_id}</id>'
        f'<title>episode</title><link href="https://comic-days.com/episode/{episode_id}"/>'
        '</entry>'
        for episode_id in episode_ids
    )
    return ('<feed xmlns="http://www.w3.org/2005/Atom">' + entries + '</feed>').encode()


def _row(episode_id: str) -> dict[str, object]:
    return {
        "readable_product_id": episode_id,
        "viewer_uri": f"https://comic-days.com/episode/{episode_id}",
        "purchase_info": {
            "can_read": False,
            "is_free": False,
            "has_rented_via_ticket": False,
            "rentable_via_ticket": True,
            "unavailable": False,
            "has_purchased": False,
            "has_rented_via_point": False,
        },
        "status": {
            "is_support_ticket": True,
            "rental_price": 0,
            "rental_end_at": None,
            "buy_price": None,
            "rental_term": 72,
        },
    }


def _free_row(episode_id: str) -> dict[str, object]:
    return {
        "readable_product_id": episode_id,
        "viewer_uri": f"https://comic-days.com/episode/{episode_id}",
        "purchase_info": {
            "can_read": True,
            "is_free": True,
            "has_rented_via_ticket": False,
            "rentable_via_ticket": False,
            "unavailable": False,
            "has_purchased": False,
            "has_rented_via_point": False,
        },
        "status": {
            "is_support_ticket": False,
            "rental_price": None,
            "rental_end_at": None,
            "buy_price": None,
            "rental_term": None,
        },
    }


class _Response:
    def __init__(self, body: bytes | object, status: int = 200) -> None:
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    async def body(self) -> bytes:
        return self._body


class _StalledResponse(_Response):
    async def body(self) -> bytes:
        await asyncio.sleep(10)
        return self._body


class _Request:
    def __init__(self, gets: list[_Response], post: _Response) -> None:
        self._gets = iter(gets)
        self._post = post
        self.get_urls: list[str] = []

    async def get(self, url: str, **_kwargs: object) -> _Response:
        self.get_urls.append(url)
        return next(self._gets)

    async def post(self, *_args: object, **_kwargs: object) -> _Response:
        return self._post


class _Page:
    url = "https://comic-days.com/episode/1"

    def __init__(self, gets: list[_Response], post: _Response) -> None:
        self.request = _Request(gets, post)


def _page(row: dict[str, object] | None = None) -> _Page:
    row = row or _row("1")
    graphql = {"data": {"userAccount": {"eventTicketCount": 0}, "series": {"ticket": {"isCharged": True, "chargedAt": "1999-01-01T00:00:00Z"}}}}
    return _Page(
        [
            _Response(_atom("1")),
            _Response(_atom("1")),
            _Response({"readable_products_count": 1}),
            _Response([row]),
        ],
        _Response(graphql),
    )


@pytest.mark.asyncio
async def test_live_listing_uses_readable_product_id_and_real_request_shapes() -> None:
    observed = await observe_comicdays_listing(_page(), series_id="9", episode_id="1")
    assert observed.series_id == "9"
    assert observed.rows[0]["readable_product_id"] == "1"
    assert observed.ticket.is_charged is True
    assert observed.ticket.ticket_present is True


@pytest.mark.asyncio
async def test_live_listing_preserves_explicitly_absent_ticket_state() -> None:
    page = _page()
    page.request._post = _Response(  # type: ignore[attr-defined]
        {"data": {"userAccount": {"eventTicketCount": 0}, "series": {"ticket": None}}}
    )

    observed = await observe_comicdays_listing(page, series_id="9", episode_id="1")

    assert observed.ticket.ticket_present is False
    assert observed.ticket.is_charged is None
    assert observed.ticket.charged_at is None


@pytest.mark.asyncio
async def test_absent_ticket_trace_marks_ticket_as_not_present() -> None:
    page = _page()
    page.request._post = _Response(  # type: ignore[attr-defined]
        {"data": {"userAccount": {"eventTicketCount": 0}, "series": {"ticket": None}}}
    )
    trace: list[tuple[str, dict[str, object]]] = []

    await observe_comicdays_ticket(
        page,
        series_id="9",
        trace_sink=lambda phase, fields: trace.append((phase, dict(fields))),
    )

    assert trace[-1][0] == "ticket_query_result"
    assert trace[-1][1]["ticket_present"] is False
    assert trace[-1][1]["is_charged"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("total,index", [(1, 0), (1767, 3), (1767, 50), (1767, 1766)])
async def test_live_access_allows_absent_ticket_only_for_free_feed_target(
    total: int, index: int,
) -> None:
    page = _page(_free_row("1"))
    ids = [str(i + 1) for i in range(total)]
    episode_id = ids[index]
    page.url = f"https://comic-days.com/episode/{episode_id}"
    offset = index // 50 * 50
    page.request._gets = iter([
        _Response(_atom_entries(*ids)),
        _Response(_atom(episode_id)),
        _Response({"readable_products_count": total}),
        _Response([_free_row(key) for key in ids[offset:offset + 50]]),
    ])
    page.request._post = _Response(  # type: ignore[attr-defined]
        {"data": {"userAccount": {"eventTicketCount": 0}, "series": {"ticket": None}}}
    )

    observed = await observe_comicdays_live_access(page, series_id="9", episode_id=episode_id)

    assert observed.access_mode == "free"
    assert observed.ticket.ticket_present is False
    assert observed.ticket.is_charged is None
    assert observed.episode_id == episode_id
    assert observed.row["readable_product_id"] == episode_id
    assert len(page.request.get_urls) == 4
    query = parse_qs(urlsplit(page.request.get_urls[-1]).query)
    assert query == {
        "type": ["episode"], "aggregate_id": ["9"], "offset": [str(offset)],
        "limit": ["50"], "sort_order": ["desc"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [
    "count", "missing_target", "unknown_free", "free_order", "page_order",
    "short_page", "duplicate", "foreign_url", "paid", "owned", "expiry", "oversized",
])
async def test_ticket_free_target_rejects_incoherent_listing(fault: str) -> None:
    ids = [str(i + 1) for i in range(51)]
    free = ["1", "2"]
    total = len(ids)
    rows = [_free_row(key) for key in ids[:50]]
    if fault == "count":
        total += 1
    elif fault == "missing_target":
        ids[0] = "99"
    elif fault == "unknown_free":
        free.append("99")
    elif fault == "free_order":
        free.reverse()
    elif fault == "page_order":
        rows.reverse()
    elif fault == "short_page":
        rows.pop()
    elif fault == "duplicate":
        rows[-1] = rows[0]
    elif fault == "foreign_url":
        rows[0]["viewer_uri"] = "https://comic-days.com/episode/99"
    elif fault == "paid":
        rows[0]["purchase_info"].update(can_read=False, is_free=False)
        rows[0]["status"]["buy_price"] = 100
    elif fault == "owned":
        rows[0]["purchase_info"]["has_purchased"] = True
    elif fault == "expiry":
        rows[0]["status"]["rental_end_at"] = "2099-01-01T00:00:00Z"
    page = _Page([
        _Response(_atom_entries(*ids)), _Response(_atom_entries(*free)),
        _Response({"readable_products_count": total}),
        _Response(b"x" * 500_001 if fault == "oversized" else rows),
    ], _Response({"data": {"userAccount": {"eventTicketCount": 0}, "series": {"ticket": None}}}))
    with pytest.raises(ComicDaysLiveAccessError):
        await observe_comicdays_live_access(page, series_id="9", episode_id="1")
    assert len(page.request.get_urls) <= 4


@pytest.mark.asyncio
async def test_ticket_free_target_cancels_stalled_page_at_shared_deadline() -> None:
    page = _Page([
        _Response(_atom("1")), _Response(_atom("1")),
        _Response({"readable_products_count": 1}), _StalledResponse(b"[]"),
    ], _Response({"data": {"userAccount": {"eventTicketCount": 0}, "series": {"ticket": None}}}))
    with pytest.raises(ComicDaysLiveAccessError, match="time bound"):
        await observe_comicdays_live_access(page, series_id="9", episode_id="1", timeout_ms=50)


@pytest.mark.asyncio
async def test_live_access_uses_target_contract_when_ticket_is_present() -> None:
    class TargetRequest:
        async def get(self, *_args: object, **_kwargs: object) -> _Response:
            raise AssertionError("target access must not refresh the whole listing")

        async def post(self, *_args: object, **_kwargs: object) -> _Response:
            return _Response(
                {
                    "data": {
                        "userAccount": {"eventTicketCount": 0},
                        "series": {
                            "ticket": {
                                "isCharged": True,
                                "chargedAt": "1999-01-01T00:00:00Z",
                            }
                        },
                    }
                }
            )

    class TargetPage:
        url = "https://comic-days.com/episode/1"
        request = TargetRequest()

        async def evaluate(self, _script: str) -> dict[str, object]:
            return {
                "url": self.url,
                "private": [],
                "normal": [
                    {
                        "json": "https://comic-days.com/episode/1.json",
                        "visible": True,
                    }
                ],
                "aggregate": [{"aggregate_id": "9"}],
                "contract": [{"aggregate_id": "9", "rental_term": "259200"}],
                "ticket": [],
                "purchase": [],
            }

    observed = await observe_comicdays_live_access(
        TargetPage(), series_id="9", episode_id="1"
    )

    assert observed.access_mode == "free"
    assert observed.normal_viewer_count == 1
    assert observed.ticket.ticket_present is True


@pytest.mark.asyncio
async def test_live_access_rejects_absent_ticket_for_nonfree_target() -> None:
    page = _page()
    page.request._gets = iter(  # type: ignore[attr-defined]
        [
            _Response(_atom_entries("1", "2")),
            _Response(_atom("2")),
            _Response({"readable_products_count": 2}),
            _Response([_row("1"), _free_row("2")]),
        ]
    )
    page.request._post = _Response(  # type: ignore[attr-defined]
        {"data": {"userAccount": {"eventTicketCount": 0}, "series": {"ticket": None}}}
    )

    with pytest.raises(ComicDaysLiveAccessError, match="did not identify a free target"):
        await observe_comicdays_live_access(page, series_id="9", episode_id="1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "graphql",
    [
        {"data": {"userAccount": {"eventTicketCount": 0}, "series": {}}},
        {"data": {"userAccount": {"eventTicketCount": 0}, "series": None}},
        {"data": {"userAccount": None, "series": {"ticket": None}}},
        {"data": {"userAccount": {"eventTicketCount": 0}, "series": {"ticket": "bad"}}},
    ],
)
async def test_live_listing_rejects_missing_or_malformed_ticket_state(
    graphql: dict[str, object],
) -> None:
    page = _page()
    page.request._post = _Response(graphql)  # type: ignore[attr-defined]

    with pytest.raises(ComicDaysLiveAccessError):
        await observe_comicdays_listing(page, series_id="9", episode_id="1")


@pytest.mark.asyncio
async def test_live_listing_late_oversized_body_fails_closed() -> None:
    page = _page()
    page.request._gets = iter([  # type: ignore[attr-defined]
        _Response(_atom("1")),
        _Response(_atom("1")),
        _Response({"readable_products_count": 1}),
        _Response(b"x" * 500_001),
    ])
    with pytest.raises(ComicDaysLiveAccessError):
        await observe_comicdays_listing(page, series_id="9", episode_id="1")


@pytest.mark.asyncio
async def test_readable_product_fetch_rejects_missing_id_before_yield() -> None:
    class Page:
        class Request:
            async def get(self, *_args: object, **_kwargs: object) -> _Response:
                return _Response([{"viewer_uri": "https://comic-days.com/episode/1"}])

        request = Request()

    with pytest.raises(DiscoveryIncompleteError):
        await fetch_comicdays_readable_products(Page(), "9", expected_total=1)


@pytest.mark.asyncio
async def test_live_listing_cancels_stalled_final_graphql_body_at_total_deadline() -> None:
    page = _page()
    page.request._post = _StalledResponse(b"{}")  # type: ignore[attr-defined]
    with pytest.raises(ComicDaysLiveAccessError, match="timed out|time bound"):
        await observe_comicdays_listing(page, series_id="9", episode_id="1", timeout_ms=50)

import json
import textwrap
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicdays import discovery as discovery_module
from screenshot_crawler.site_adapters.comicdays.discovery import (
    canonical_comicdays_episode_url,
    comicdays_access_observation,
    fetch_comicdays_readable_products,
    parse_atom_entries,
    parse_comicdays_episode_url,
)
from screenshot_crawler.watchlist.models import WatchlistTarget


def _feed(link: str = "https://comic-days.com/episode/2", *, feed_id: str | None = None) -> bytes:
    identity = f"<id>{feed_id}</id>" if feed_id else ""
    return textwrap.dedent(f"""\
      <feed xmlns="http://www.w3.org/2005/Atom">{identity}<entry>
        <id>comicdays:episode:2</id><title>第2話</title><updated>2026-01-01T00:00:00Z</updated>
        <link rel="enclosure" href="https://cdn.comic-days.com/thumb/2.jpg"/><link href="{link}"/>
      </entry></feed>
    """).encode()


def test_comicdays_url_parser_is_canonical_and_strict() -> None:
    assert parse_comicdays_episode_url("https://comic-days.com/episode/12") == "12"
    assert parse_comicdays_episode_url("https://www.comic-days.com/episode/12") == "12"
    assert parse_comicdays_episode_url("https://comic-days.com/episode/12?free_only=1") is None
    assert parse_comicdays_episode_url("https://example.test/episode/12") is None
    assert canonical_comicdays_episode_url("https://www.comic-days.com/episode/12") == "https://comic-days.com/episode/12"


def test_atom_uses_matching_episode_link_and_ignores_thumbnail() -> None:
    entries = parse_atom_entries(_feed(), expected_series_id="42")
    assert entries == [{"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "第2話", "updated": "2026-01-01T00:00:00Z"}]


def test_atom_rejects_conflicting_episode_identity() -> None:
    with pytest.raises(DiscoveryIncompleteError):
        parse_atom_entries(_feed("https://comic-days.com/episode/9"), expected_series_id="42")


def test_atom_requires_exact_series_identity_when_feed_provides_one() -> None:
    with pytest.raises(DiscoveryIncompleteError):
        parse_atom_entries(_feed(feed_id="https://comic-days.com/atom/series/420"), expected_series_id="42")


def _row(episode_id: str, *, free: bool = False, ticket: bool = False, grant: bool = False, paid: bool = False, end: str | None = None) -> dict:
    return {
        "readable_product_id": episode_id,
        "viewer_uri": f"https://comic-days.com/episode/{episode_id}",
        "purchase_info": {
            "can_read": free or grant,
            "has_purchased": False,
            "has_rented_via_point": False,
            "is_free": free,
            "has_rented_via_ticket": grant,
            "rentable_via_ticket": ticket,
            "unavailable": False,
        },
        "status": {
            "is_support_ticket": ticket or grant,
            "rental_price": 0 if ticket or grant else None,
            "rental_end_at": end,
            "rental_term": 72 if ticket or grant else None,
            "buy_price": 100 if paid else None,
        },
    }


def test_access_observation_classifies_free_ticket_grant_paid_and_unknown() -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    assert comicdays_access_observation(_row("1", free=True), free=True, now=now) == ("free", None, True)
    assert comicdays_access_observation(_row("2", ticket=True), free=False, now=now) == ("quota", None, True)
    expiry = "2026-10-06T00:00:00Z"
    mode, until, observed = comicdays_access_observation(_row("3", grant=True, end=expiry), free=False, now=now)
    assert mode == "quota" and until == datetime.fromisoformat(expiry) and observed
    assert comicdays_access_observation(_row("4", paid=True), free=False, now=now)[0] == "paid"
    unsupported = _row("5")
    unsupported["purchase_info"]["can_read"] = True
    assert comicdays_access_observation(unsupported, free=False, now=now) == ("unknown", None, False)


@pytest.mark.parametrize("term", [None, True, "72", 71, 73])
def test_access_observation_excludes_unsupported_locked_ticket_contract(term: object) -> None:
    row = _row("5", ticket=True)
    row["status"]["rental_term"] = term
    assert comicdays_access_observation(
        row, free=False, now=datetime(2026, 10, 3, tzinfo=UTC)
    ) == ("unknown", None, False)


def test_access_observation_accepts_free_feed_ticket_support_metadata_without_quota() -> None:
    row = _row("6", free=True)
    row["status"].update(is_support_ticket=True, rental_price=0, rental_term=72)
    assert comicdays_access_observation(
        row, free=True, now=datetime(2026, 10, 3, tzinfo=UTC)
    ) == ("free", None, True)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row["status"].update(rental_price=1),
        lambda row: row["status"].update(rental_price=True),
        lambda row: row["status"].update(rental_term=None),
        lambda row: row["status"].update(rental_term="72"),
        lambda row: row["status"].update(rental_term=72.0),
        lambda row: row["status"].update(rental_term=True),
        lambda row: row["status"].update(rental_term=71),
        lambda row: row["status"].update(buy_price=80),
        lambda row: row["status"].update(is_support_ticket=False),
    ],
)
def test_access_observation_rejects_malformed_free_ticket_support_metadata(mutate) -> None:
    row = _row("6", free=True)
    row["status"].update(is_support_ticket=True, rental_price=0, rental_term=72)
    mutate(row)
    with pytest.raises(DiscoveryIncompleteError):
        comicdays_access_observation(
            row, free=True, now=datetime(2026, 10, 3, tzinfo=UTC)
        )


def test_access_observation_rejects_malformed_active_grant() -> None:
    with pytest.raises(DiscoveryIncompleteError):
        comicdays_access_observation(_row("1", grant=True, end="bad"), free=False, now=datetime.now(UTC))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row["status"].update(rental_price=0.0, rental_end_at="2026-10-06T00:00:00Z"),
        lambda row: row["purchase_info"].update(can_read=True, has_rented_via_ticket=True, rentable_via_ticket=True),
        lambda row: row["purchase_info"].update(unavailable=True),
        lambda row: row["purchase_info"].update(has_purchased=True),
        lambda row: row["purchase_info"].update(has_rented_via_point=True),
        lambda row: row["status"].update(rental_price=True),
    ],
)
def test_access_observation_rejects_conflicting_or_unavailable_rows(mutate) -> None:
    row = _row("1", ticket=True)
    mutate(row)
    with pytest.raises(DiscoveryIncompleteError):
        comicdays_access_observation(row, free=False, now=datetime(2026, 10, 3, tzinfo=UTC))


def test_access_observation_expired_or_naive_grant_is_fail_closed() -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    assert comicdays_access_observation(_row("1", grant=True, end="2026-10-02T00:00:00Z"), free=False, now=now) == ("unknown", None, False)
    with pytest.raises(DiscoveryIncompleteError):
        comicdays_access_observation(_row("1", grant=True, end="2026-10-06T00:00:00"), free=False, now=now)


class _FakeLocator:
    async def count(self) -> int:
        return 1

    async def inner_text(self, **_kwargs: object) -> str:
        return "Synthetic Work"


class _FakePage:
    url = "https://comic-days.com/episode/1"
    request = SimpleNamespace()

    async def goto(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def evaluate(self, _script: str) -> list[str]:
        return ["42"]

    def locator(self, _selector: str) -> _FakeLocator:
        return _FakeLocator()


class _Response:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.status = status
        self.payload = payload

    async def body(self) -> bytes:
        return json.dumps(self.payload).encode()


class _Request:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)

    async def get(self, *_args: object, **_kwargs: object) -> _Response:
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


class _BulkPage:
    def __init__(self, responses: list[object]) -> None:
        self.request = _Request(responses)


def _bulk_row(episode_id: int, viewer_uri: str | None = None) -> dict:
    return {"readable_product_id": str(episode_id), "viewer_uri": viewer_uri or f"https://comic-days.com/episode/{episode_id}"}


@pytest.mark.asyncio
async def test_readable_product_fetch_accepts_array_and_multiple_pages() -> None:
    first = [_bulk_row(i) for i in range(50, 0, -1)]
    second = [_bulk_row(0)]
    rows = await fetch_comicdays_readable_products(
        _BulkPage([_Response(first), _Response(second)]), "42", expected_total=51
    )
    assert len(rows) == 51 and rows[0]["readable_product_id"] == "50"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected,total",
    [
        ([[_bulk_row(1)][0], _bulk_row(1)], "duplicate", 2),
        ([_bulk_row(2), _bulk_row(1)], "incomplete", 1),
        ([_bulk_row(1)], "incomplete", 2),
        ({"wrapper": [_bulk_row(1)]}, "invalid", 1),
        ([_bulk_row(1, "https://comic-days.com/episode/9")], "viewer URI", 1),
    ],
)
async def test_readable_product_fetch_rejects_duplicate_missing_wrapper_and_conflicting_rows(payload: object, expected: str, total: int) -> None:
    with pytest.raises(DiscoveryIncompleteError, match=expected):
        await fetch_comicdays_readable_products(_BulkPage([_Response(payload)]), "42", expected_total=total)


@pytest.mark.asyncio
async def test_readable_product_fetch_rejects_status_body_and_late_page_failures() -> None:
    with pytest.raises(DiscoveryIncompleteError):
        await fetch_comicdays_readable_products(_BulkPage([_Response([], status=500)]), "42", expected_total=1)
    with pytest.raises(DiscoveryIncompleteError):
        await fetch_comicdays_readable_products(_BulkPage([TimeoutError("late")]), "42", expected_total=1)
    first = [_bulk_row(i) for i in range(50, 0, -1)]
    with pytest.raises(DiscoveryIncompleteError):
        await fetch_comicdays_readable_products(
            _BulkPage([_Response(first), TimeoutError("late page")]), "42", expected_total=51
        )


@pytest.mark.asyncio
async def test_discovery_buffers_until_full_free_and_total_contracts_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    full = [
        {"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "第2話"},
        {"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第1話"},
    ]
    free = [full[1]]
    async def atom(_page: object, _series: str, *, free_only: bool) -> list[dict[str, str | None]]:
        return free if free_only else full
    async def total(_page: object, _series: str, _episode: str) -> int:
        return 2
    async def bulk(_page: object, _series: str, *, expected_total: int) -> list[dict]:
        assert expected_total == 2
        free_row = _row("1", free=True)
        free_row["status"].update(is_support_ticket=True, rental_price=0, rental_term=72)
        return [_row("2", paid=True), free_row]
    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_readable_products", bulk)
    target = WatchlistTarget("k", "w", "comicdays", "https://comic-days.com/episode/1", "x")
    rows = [row async for row in discovery_module.ComicDaysDiscoveryAdapter().iter_records(_FakePage(), target, "full")]
    assert [row.source.external_id for row in rows] == ["2", "1"]
    assert [row.source.access_mode for row in rows] == ["paid", "free"]


@pytest.mark.asyncio
async def test_discovery_total_mismatch_yields_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def atom(_page: object, _series: str, *, free_only: bool) -> list[dict[str, str | None]]:
        return [{"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第1話"}]
    async def total(_page: object, _series: str, _episode: str) -> int:
        return 2
    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    target = WatchlistTarget("k", "w", "comicdays", "https://comic-days.com/episode/1", "x")
    iterator = discovery_module.ComicDaysDiscoveryAdapter().iter_records(_FakePage(), target, "full")
    with pytest.raises(DiscoveryIncompleteError):
        await anext(iterator)


@pytest.mark.asyncio
async def test_discovery_validates_every_access_row_before_first_yield(monkeypatch: pytest.MonkeyPatch) -> None:
    full = [
        {"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "第2話"},
        {"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第1話"},
    ]
    async def atom(_page: object, _series: str, *, free_only: bool) -> list[dict[str, str | None]]:
        return [full[1]] if free_only else full
    async def total(_page: object, _series: str, _episode: str) -> int:
        return 2
    async def malformed(_page: object, _series: str, *, expected_total: int) -> list[dict]:
        assert expected_total == 2
        return [_row("2", paid=True), {"readable_product_id": "1", "purchase_info": None, "status": {}}]
    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_readable_products", malformed)
    target = WatchlistTarget("k", "w", "comicdays", "https://comic-days.com/episode/1", "x")
    with pytest.raises(DiscoveryIncompleteError):
        await anext(discovery_module.ComicDaysDiscoveryAdapter().iter_records(_FakePage(), target, "full"))


@pytest.mark.asyncio
async def test_discovery_rejects_late_access_contradiction_before_yield(monkeypatch: pytest.MonkeyPatch) -> None:
    full = [
        {"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "第2話"},
        {"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第1話"},
    ]
    async def atom(_page: object, _series: str, *, free_only: bool) -> list[dict[str, str | None]]:
        return [full[1]] if free_only else full
    async def total(_page: object, _series: str, _episode: str) -> int:
        return 2
    contradictory = _row("1", ticket=True)
    contradictory["status"]["rental_end_at"] = "2026-10-06T00:00:00Z"
    async def bulk(_page: object, _series: str, *, expected_total: int) -> list[dict]:
        assert expected_total == 2
        return [_row("2", paid=True), contradictory]
    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_readable_products", bulk)
    target = WatchlistTarget("k", "w", "comicdays", "https://comic-days.com/episode/1", "x")
    with pytest.raises(DiscoveryIncompleteError):
        await anext(discovery_module.ComicDaysDiscoveryAdapter().iter_records(_FakePage(), target, "full"))


def test_comicdays_fresh_sync_records_native_grant_and_clears_stale_grant(tmp_path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="comicdays-work", title="Work"))
    item = service.create_item(ItemInput(status="pending"), work_id=work.id)
    created = service.create_source(
        SourceInput(
            site="comicdays", external_id="episode-1", discovery_key="comicdays",
            access_mode="quota", access_checked_at="2026-10-03T10:00:00+00:00",
            access_granted_until="2026-10-06T01:22:56+00:00",
        ), item_id=item.id,
    )
    target = service.create_source_target(
        SourceTargetInput(backend="web", locator="https://comic-days.com/episode/1"),
        source_id=created.id,
    )
    refreshed = service.refresh_discovered_source(
        work_id=work.id, source_id=created.id,
        item_input=ItemInput(),
        source_input=SourceInput(
            site="comicdays", external_id="episode-1", discovery_key="comicdays",
            access_mode="paid", access_checked_at="2026-10-03T11:00:00+00:00",
        ),
        web_target_input=SourceTargetInput(backend="web", locator=target.locator),
        access_granted_until_observed=True,
    )
    assert refreshed.source.access_mode == "paid"
    assert refreshed.source.access_granted_until is None
    assert refreshed.source.access_checked_at == "2026-10-03T20:00:00+09:00"
    assert service.get_item(item.id).status == "pending"

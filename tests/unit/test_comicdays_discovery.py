import json
import textwrap
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import (
    CatalogService,
    DiscoveryInventoryPosition,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.discovery import DiscoveryAdapterRegistry, DiscoveryService
from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicdays import discovery as discovery_module
from screenshot_crawler.site_adapters.comicdays.discovery import (
    canonical_comicdays_episode_url,
    comicdays_access_observation,
    fetch_comicdays_readable_products,
    parse_atom_entries,
    parse_comicdays_episode_url,
)
from screenshot_crawler.site_policies import (
    BookWalkerSitePolicy,
    ComicDaysSitePolicy,
    SitePolicyRegistry,
)
from screenshot_crawler.watchlist.fingerprints import target_scope_fingerprint
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.reconcile import ScopeReconciler
from screenshot_crawler.watchlist.service import WatchlistService


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
    target = WatchlistTarget(
        "k", "w", "comicdays", "https://comic-days.com/episode/1", "x", archive_order=10
    )
    adapter = discovery_module.ComicDaysDiscoveryAdapter()
    partial = adapter.iter_records(_FakePage(), target, "full")
    assert (await anext(partial)).source.external_id == "2"
    assert adapter.complete_listing_inventory is None
    await partial.aclose()
    assert adapter.complete_listing_inventory is None

    rows = [row async for row in adapter.iter_records(_FakePage(), target, "full")]
    assert [row.source.external_id for row in rows] == ["2", "1"]
    assert [row.source.access_mode for row in rows] == ["paid", "free"]
    inventory = adapter.complete_listing_inventory
    assert inventory is not None
    assert inventory.listing_identity == "comicdays-series:42"
    assert [
        (entry.external_id, entry.display_position, entry.in_scope)
        for entry in inventory.positions
    ] == [("2", 2, True), ("1", 1, True)]

    incremental = [
        row async for row in adapter.iter_records(_FakePage(), target, "incremental")
    ]
    assert [row.source.external_id for row in incremental] == ["2", "1"]
    assert adapter.complete_listing_inventory is None


@pytest.mark.asyncio
async def test_discovery_total_mismatch_yields_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def atom(_page: object, _series: str, *, free_only: bool) -> list[dict[str, str | None]]:
        return [{"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第1話"}]
    async def total(_page: object, _series: str, _episode: str) -> int:
        return 2
    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    target = WatchlistTarget("k", "w", "comicdays", "https://comic-days.com/episode/1", "x")
    adapter = discovery_module.ComicDaysDiscoveryAdapter()
    iterator = adapter.iter_records(_FakePage(), target, "full")
    with pytest.raises(DiscoveryIncompleteError):
        await anext(iterator)
    assert adapter.complete_listing_inventory is None


@pytest.mark.asyncio
async def test_discovery_rejects_readable_listing_order_disagreement_before_yield(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full = [
        {"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "第2話"},
        {"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第1話"},
    ]

    async def atom(_page: object, _series: str, *, free_only: bool):
        return [full[1]] if free_only else full

    async def total(_page: object, _series: str, _episode: str) -> int:
        return 2

    async def wrong_order(_page: object, _series: str, *, expected_total: int):
        assert expected_total == 2
        return [_row("1", free=True), _row("2", paid=True)]

    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_readable_products", wrong_order)
    target = WatchlistTarget(
        "k", "w", "comicdays", "https://comic-days.com/episode/1", "x", archive_order=10
    )
    adapter = discovery_module.ComicDaysDiscoveryAdapter()
    with pytest.raises(DiscoveryIncompleteError, match="order disagreed"):
        await anext(adapter.iter_records(_FakePage(), target, "full"))
    assert adapter.complete_listing_inventory is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("from_url", "through_url", "expected_ids"),
    [
        (
            "https://comic-days.com/episode/2",
            "https://comic-days.com/episode/1",
            ["2", "1"],
        ),
        ("https://comic-days.com:443/episode/2", None, ["2", "1"]),
        (None, "https://www.comic-days.com/episode/2", ["3", "2"]),
        (
            "https://comic-days.com/episode/2",
            "https://comic-days.com/episode/2",
            ["2"],
        ),
    ],
)
async def test_bounded_discovery_keeps_full_positions_and_inventory_membership(
    monkeypatch: pytest.MonkeyPatch,
    from_url: str | None,
    through_url: str | None,
    expected_ids: list[str],
) -> None:
    full = [
        {"episode_id": "3", "url": "https://comic-days.com/episode/3", "title": "Chapter 3"},
        {"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "Chapter 2"},
        {"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "Chapter 1"},
    ]

    async def atom(_page: object, _series: str, *, free_only: bool):
        return full[1:] if free_only else full

    async def total(_page: object, _series: str, _episode: str) -> int:
        return len(full)

    async def readable(_page: object, _series: str, *, expected_total: int):
        assert expected_total == len(full)
        return [_row("3", paid=True), _row("2", free=True), _row("1", free=True)]

    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_readable_products", readable)
    target = WatchlistTarget(
        "k",
        "w",
        "comicdays",
        "https://comic-days.com/episode/1",
        "x",
        discovery_scope=DiscoveryScope(from_url=from_url, through_url=through_url),
        archive_order=10,
    )
    adapter = discovery_module.ComicDaysDiscoveryAdapter()
    assert adapter.supports_bounded_discovery is True
    rows = [row async for row in adapter.iter_records(_FakePage(), target, "full")]
    assert [row.source.external_id for row in rows] == expected_ids
    assert [row.source.global_display_position for row in rows] == [
        int(external_id) for external_id in expected_ids
    ]
    inventory = adapter.complete_listing_inventory
    assert inventory is not None
    assert inventory.listing_identity == "comicdays-series:42"
    assert [
        (position.external_id, position.display_position, position.in_scope)
        for position in inventory.positions
    ] == [
        (external_id, int(external_id), external_id in expected_ids)
        for external_id in ("3", "2", "1")
    ]


@pytest.mark.parametrize(
    ("from_url", "through_url", "message"),
    [
        (None, None, "no episode boundary"),
        ("https://comic-days.com/episode/1", "https://comic-days.com/episode/3", "reversed"),
        ("https://comic-days.com/episode/4", None, "not in the listing"),
        ("https://example.test/episode/2", None, "URL is invalid"),
        ("http://comic-days.com/episode/2", None, "URL is invalid"),
        ("ftp://comic-days.com/episode/2", None, "URL is invalid"),
        ("https://user@comic-days.com/episode/2", None, "URL is invalid"),
        ("https://comic-days.com:9999/episode/2", None, "URL is invalid"),
        ("https://comic-days.com/episode/2;ignored", None, "URL is invalid"),
    ],
)
@pytest.mark.asyncio
async def test_bounded_discovery_rejects_unresolved_boundaries_before_yield(
    from_url: str | None,
    through_url: str | None,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full = [
        {"episode_id": "3", "url": "https://comic-days.com/episode/3", "title": "Chapter 3"},
        {"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "Chapter 2"},
        {"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "Chapter 1"},
    ]

    async def atom(_page: object, _series: str, *, free_only: bool):
        return full[1:] if free_only else full

    async def total(_page: object, _series: str, _episode: str) -> int:
        return len(full)

    async def readable(_page: object, _series: str, *, expected_total: int):
        return [_row("3", paid=True), _row("2", free=True), _row("1", free=True)]

    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_readable_products", readable)
    target = WatchlistTarget(
        "k",
        "w",
        "comicdays",
        "https://comic-days.com/episode/1",
        "x",
        discovery_scope=DiscoveryScope(from_url=from_url, through_url=through_url),
        archive_order=10,
    )
    adapter = discovery_module.ComicDaysDiscoveryAdapter()
    iterator = adapter.iter_records(_FakePage(), target, "full")
    with pytest.raises(DiscoveryIncompleteError, match=message):
        await anext(iterator)
    assert adapter.complete_listing_inventory is None


@pytest.mark.asyncio
async def test_comicdays_full_inventory_syncs_into_cross_site_archive_order(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = [
        {"episode_id": "103", "url": "https://comic-days.com/episode/103", "title": "第3話"},
        {"episode_id": "102", "url": "https://comic-days.com/episode/102", "title": "第2話"},
        {"episode_id": "101", "url": "https://comic-days.com/episode/101", "title": "第1話"},
    ]
    free = full[1:]
    listing_total = [3]

    async def atom(_page: object, series_id: str, *, free_only: bool):
        assert series_id == "42"
        return free if free_only else full

    async def total(_page: object, series_id: str, _episode_id: str) -> int:
        assert series_id == "42"
        return listing_total[0]

    async def readable(_page: object, series_id: str, *, expected_total: int):
        assert series_id == "42"
        assert expected_total == listing_total[0]
        return [_row("103", paid=True), _row("102", free=True), _row("101", free=True)]

    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_readable_products", readable)

    catalog = CatalogService(tmp_path / "catalog.sqlite")
    watchlist = WatchlistService(tmp_path / "watchlist.yaml")
    watchlist.path.write_text(
        "targets:\n"
        "  - key: comic-days\n"
        "    work_key: shared-work\n"
        "    site: comicdays\n"
        "    url: https://comic-days.com/episode/101\n"
        "    label: Comic DAYS\n"
        "    enabled: true\n"
        "    archive_order: 10\n"
        "    discovery_scope:\n"
        "      from_url: https://comic-days.com/episode/102\n"
        "      through_url: https://comic-days.com/episode/101\n",
        encoding="utf-8",
    )
    comic_target = watchlist.get("comic-days")
    bookwalker_target = watchlist.add(
        key="bookwalker",
        work_key="shared-work",
        site="bookwalker",
        url="https://example.invalid/bookwalker/list",
        label="BookWalker",
        archive_order=20,
    )

    work = catalog.create_work(WorkInput(work_key="shared-work", title="Synthetic Work"))
    out_of_scope_item = catalog.create_item(
        ItemInput(kind="episode", order_label="Chapter 3", status="completed"),
        work_id=work.id,
    )
    out_of_scope_source = catalog.create_source(
        SourceInput(
            site="comicdays",
            external_id="103",
            discovery_key=comic_target.key,
            access_mode="paid",
            available=False,
            display_position=99,
        ),
        item_id=out_of_scope_item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://comic-days.com/episode/103"),
        source_id=out_of_scope_source.id,
    )

    discovery_registry = DiscoveryAdapterRegistry()
    discovery_registry.register("comicdays", discovery_module.ComicDaysDiscoveryAdapter)
    discovery = DiscoveryService(catalog, discovery_registry)
    page = _FakePage()
    page.url = comic_target.url
    result = await discovery.discover(page, comic_target, "full")
    assert result.complete is True
    assert result.observed_count == 2

    comic_inventory = catalog.get_discovery_inventory_evidence(comic_target.key)
    assert comic_inventory is not None
    assert comic_inventory.listing_identity == "comicdays-series:42"
    assert [
        (position.external_id, position.display_position, position.in_scope)
        for position in comic_inventory.positions
    ] == [("101", 1, True), ("102", 2, True), ("103", 3, False)]

    sources_by_external_id = {
        source.external_id: source
        for source in catalog.list_sources(site="comicdays", discovery_key=comic_target.key)
    }
    assert {
        external_id: source.display_position
        for external_id, source in sources_by_external_id.items()
    } == {"101": 1, "102": 2, "103": 3}
    refreshed_out_of_scope = sources_by_external_id["103"]
    assert refreshed_out_of_scope.id == out_of_scope_source.id
    assert refreshed_out_of_scope.access_mode == "paid"
    assert refreshed_out_of_scope.available is False
    assert refreshed_out_of_scope.acquisition_enabled is True
    assert refreshed_out_of_scope.quota_started_at is None
    assert catalog.get_item(out_of_scope_item.id).status == "completed"
    catalog.mark_item_completed(sources_by_external_id["102"].item_id)
    assert catalog.get_item(sources_by_external_id["102"].item_id).status == "completed"

    book_item = catalog.create_item(
        ItemInput(kind="book", order_label="Volume 1"), work_id=work.id
    )
    book_source = catalog.create_source(
        SourceInput(
            site="bookwalker",
            external_id="volume-1",
            discovery_key=bookwalker_target.key,
            access_mode="owned",
            available=True,
            display_position=1,
        ),
        item_id=book_item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(
            backend="web", locator="https://example.invalid/bookwalker/volume-1"
        ),
        source_id=book_source.id,
    )
    catalog.record_discovery_inventory_evidence(
        work_key=work.work_key,
        discovery_key=bookwalker_target.key,
        site=bookwalker_target.site,
        target_url=bookwalker_target.url,
        scope_fingerprint=target_scope_fingerprint(bookwalker_target),
        listing_identity="bookwalker-series:synthetic",
        positions=[DiscoveryInventoryPosition("volume-1", 1)],
    )

    reconciler = ScopeReconciler(watchlist, catalog)
    preview = reconciler.preview(work.work_key)
    assert preview.ready
    reconciler.apply(preview)
    assert catalog.get_source(out_of_scope_source.id).acquisition_enabled is False

    policies = SitePolicyRegistry()
    policies.register("comicdays", ComicDaysSitePolicy)
    policies.register("bookwalker", BookWalkerSitePolicy)
    planner = BatchPlanner(
        catalog,
        policies,
        watchlist=watchlist,
        library_dir=tmp_path / "Books",
    )
    comic_plan = planner.plan(site="comicdays", now=datetime(2026, 10, 3, tzinfo=UTC))
    bookwalker_plan = planner.plan(
        site="bookwalker", now=datetime(2026, 10, 3, tzinfo=UTC)
    )
    assert [candidate.source_id for candidate in comic_plan.candidates] == [
        sources_by_external_id["101"].id
    ]
    assert [candidate.artifact_prefix for candidate in comic_plan.candidates] == ["001"]
    assert [candidate.source_id for candidate in bookwalker_plan.candidates] == [
        book_source.id
    ]
    assert [candidate.artifact_prefix for candidate in bookwalker_plan.candidates] == [
        "003"
    ]
    assert catalog.get_item(sources_by_external_id["102"].item_id).status == "completed"
    assert catalog.get_source(sources_by_external_id["103"].id).access_mode == "paid"
    assert catalog.get_source(sources_by_external_id["103"].id).quota_started_at is None

    sync = catalog.get_acquisition_scope_sync(work.work_key)
    assert sync is not None and sync.status == "synced"
    listing_total[0] = 4
    page.url = comic_target.url
    incomplete = await discovery.discover(page, comic_target, "full")
    assert incomplete.complete is False
    assert catalog.get_discovery_inventory_evidence(comic_target.key) is None
    assert catalog.get_acquisition_scope_sync(work.work_key).status == "stale"

    listing_total[0] = 3
    page.url = comic_target.url
    incremental = await discovery.discover(page, comic_target, "incremental")
    assert incremental.complete is None
    assert catalog.get_discovery_inventory_evidence(comic_target.key) is None
    assert not reconciler.preview(work.work_key).ready


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

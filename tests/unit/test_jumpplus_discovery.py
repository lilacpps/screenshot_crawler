from datetime import datetime, timedelta, timezone

import pytest

from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.jumpplus.discovery import (
    JumpPlusDiscoveryAdapter,
    JumpPlusRange,
    canonical_jumpplus_episode_url,
    map_jumpplus_access,
    parse_jumpplus_dom_expiry,
    parse_jumpplus_episode_url,
    parse_jumpplus_order_label,
    parse_jumpplus_published_at,
    parse_jumpplus_range_label,
    parse_jumpplus_structured_expiry,
)
from screenshot_crawler.watchlist import DiscoveryScope, WatchlistTarget


def row(*, text: list[str], classes: list[str] | None = None, title: str | None = None):
    return {"access_text": text, "access_class": classes or [], "access_title": title}


def test_jumpplus_episode_identity_is_canonical_and_host_restricted() -> None:
    assert parse_jumpplus_episode_url(
        "https://www.shonenjumpplus.com/episode/123?from=listing#top"
    ) == "123"
    assert canonical_jumpplus_episode_url("https://shonenjumpplus.com/episode/123?x=1") == (
        "https://shonenjumpplus.com/episode/123"
    )
    assert parse_jumpplus_episode_url("https://example.test/episode/123") is None
    with pytest.raises(ValueError):
        canonical_jumpplus_episode_url("https://shonenjumpplus.com/series/123")


def test_jumpplus_dates_and_order_labels_are_conservative() -> None:
    assert parse_jumpplus_published_at("2026/09/24") == datetime(
        2026, 9, 24, tzinfo=timezone(timedelta(hours=9))
    )
    assert parse_jumpplus_order_label("第10話 タイトル") == ("10", "第10話 タイトル")
    assert parse_jumpplus_order_label("イラスト3") == (None, "イラスト3")
    assert parse_jumpplus_order_label("特別収録作品1 麦わら劇場 海の音楽会")[0] is None
    assert parse_jumpplus_order_label("2026/09/24") == (None, "2026/09/24")


def test_jumpplus_range_label_has_no_fixed_values() -> None:
    assert parse_jumpplus_range_label("1180 - 1081") == (1180, 1081)
    assert parse_jumpplus_range_label("86 - 1") == (86, 1)
    assert parse_jumpplus_range_label("1") == (1, 1)
    assert parse_jumpplus_range_label("42") == (42, 42)
    assert parse_jumpplus_range_label("1話から") is None


def test_jumpplus_access_mapping_covers_free_paid_rental_and_schedule() -> None:
    assert map_jumpplus_access(row(text=["無料"], classes=["series-episode-list-is-free"]), None) == (
        "free",
        None,
    )
    assert map_jumpplus_access(row(text=["40pt", "レンタル・48時間"], classes=["price"]), None) == (
        "paid",
        None,
    )
    assert map_jumpplus_access(
        row(text=["レンタル中 2026/09/26 11:41まで"], classes=["rental"]), None
    ) == ("paid", parse_jumpplus_dom_expiry("2026/09/26 11:41まで"))
    assert map_jumpplus_access(
        row(text=["40pt", "2026年09月29日に無料公開予定"], classes=["price"]), None
    )[0] == "paid"


def test_jumpplus_structured_rental_wins_when_dom_is_uninformative() -> None:
    state = {
        "purchase_info": {"can_read": True, "has_rented_via_point": True},
        "status": {"label": "has_rented", "rental_end_at": "2026-09-26T02:41:39Z"},
    }
    mode, expiry = map_jumpplus_access(row(text=[], classes=[]), state)
    assert mode == "paid"
    assert expiry == parse_jumpplus_structured_expiry("2026-09-26T02:41:39Z")


def test_jumpplus_conflicting_access_evidence_is_unknown() -> None:
    state = {"purchase_info": {"can_read": False}, "status": {"label": "is_rentable"}}
    assert map_jumpplus_access(row(text=["レンタル中"], classes=["rental"]), state) == (
        "unknown",
        None,
    )


def test_jumpplus_active_dom_evidence_does_not_require_structured_state() -> None:
    mode, expiry = map_jumpplus_access(
        row(text=["レンタル中"], classes=["series-episode-list-rental"]), None
    )
    assert mode == "paid"
    assert expiry is None


def test_jumpplus_range_order_validation_is_latest_first() -> None:
    adapter = JumpPlusDiscoveryAdapter()
    ranges = adapter._ranges(
        {
            "range_controls": [
                {"text": "286 - 187"},
                {"text": "186 - 87"},
                {"text": "86 - 2"},
                {"text": "1"},
            ]
        }
    )
    assert [(item.first, item.last) for item in ranges] == [
        (286, 187),
        (186, 87),
        (86, 2),
        (1, 1),
    ]
    adapter._validate_range_order(ranges)
    with pytest.raises(DiscoveryIncompleteError):
        adapter._validate_range_order(list(reversed(ranges)))


def test_jumpplus_scope_validation_covers_both_dom_variants() -> None:
    base = {
        "series_ids": ["series-1"],
        "listing_count": 1,
        "episodes": [{"episode_id": "123", "href": "/episode/123"}],
    }
    for variant in ("role-tabpanel", "direct-pagination"):
        snapshot = {**base, "scope": {"variant": variant}}
        assert JumpPlusDiscoveryAdapter._validate_scope(snapshot, "123", None) == "series-1"


class _FakeLocator:
    def __init__(self, page):
        self.page = page

    async def count(self):
        return 1

    async def scroll_into_view_if_needed(self):
        return None

    async def click(self, **_kwargs):
        self.page.clicks += 1


class _FakePage:
    url = "https://shonenjumpplus.com/episode/123"

    def __init__(self):
        self.clicks = 0
        self.range_index = 0

    def on(self, _event, _listener):
        return None

    def remove_listener(self, _event, _listener):
        return None

    def locator(self, _selector):
        return _FakeLocator(self)

    async def goto(self, *_args, **_kwargs):
        return None

    async def wait_for_timeout(self, _milliseconds):
        return None


@pytest.mark.asyncio
async def test_jumpplus_more_requires_identity_growth(monkeypatch) -> None:
    adapter = JumpPlusDiscoveryAdapter()
    page = _FakePage()
    snapshots = iter(
        [
            {"scope": {"variant": "direct-pagination"}, "series_ids": ["s"], "listing_count": 1, "episodes": [{"episode_id": "1"}], "more_controls": [{"visible": True, "disabled": False, "text": "もっと見る", "selector": "#more"}]},
            {"scope": {"variant": "direct-pagination"}, "series_ids": ["s"], "listing_count": 1, "episodes": [{"episode_id": "1"}, {"episode_id": "2"}], "more_controls": []},
            {"scope": {"variant": "direct-pagination"}, "series_ids": ["s"], "listing_count": 1, "episodes": [{"episode_id": "1"}, {"episode_id": "2"}], "more_controls": []},
        ]
    )
    async def next_snapshot(*_args):
        return next(snapshots)

    monkeypatch.setattr(adapter, "_snapshot", next_snapshot)
    result = await adapter._expand_range(page, "123", "s")
    assert [row["episode_id"] for row in result] == ["1", "2"]
    assert page.clicks == 1


@pytest.mark.asyncio
async def test_jumpplus_multiple_or_disabled_more_fails_closed(monkeypatch) -> None:
    adapter = JumpPlusDiscoveryAdapter()
    page = _FakePage()
    for controls in (
        [
            {"visible": True, "disabled": False, "text": "もっと見る", "selector": "#a"},
            {"visible": True, "disabled": False, "text": "もっと見る", "selector": "#b"},
        ],
        [{"visible": True, "disabled": True, "text": "もっと見る", "selector": "#a"}],
    ):
        async def snapshot(*_args, controls=controls):
            return {
                "scope": {"variant": "direct-pagination"},
                "series_ids": ["s"],
                "listing_count": 1,
                "episodes": [{"episode_id": "1"}],
                "more_controls": controls,
            }
        monkeypatch.setattr(adapter, "_snapshot", snapshot)
        with pytest.raises(DiscoveryIncompleteError):
            await adapter._expand_range(page, "123", "s")


def _jump_record(episode_id: str):
    from screenshot_crawler.discovery import (
        DiscoveredItem,
        DiscoveredRecord,
        DiscoveredSource,
    )

    return DiscoveredRecord(
        item=DiscoveredItem(canonical_title="Work", kind="episode"),
        source=DiscoveredSource(
            external_id=episode_id,
            url=f"https://shonenjumpplus.com/episode/{episode_id}",
            access_mode="free",
            available=True,
        ),
    )


def _jump_snapshot(episode_ids: list[str]) -> dict:
    return {
        "scope": {"variant": "direct-pagination"},
        "series_ids": ["series-1"],
        "listing_count": 1,
        "episodes": [
            {
                "episode_id": episode_id,
                "href": f"/episode/{episode_id}",
                "title_text": "Special",
                "access_text": [],
                "access_class": [],
                "access_title": None,
            }
            for episode_id in episode_ids
        ],
        "work": {"title": "Work", "author": None},
    }


def _configure_jumpplus_traversal(
    monkeypatch,
    adapter: JumpPlusDiscoveryAdapter,
    page: _FakePage,
    snapshots: list[dict],
    ranges,
    *,
    failing_range: int | None = None,
) -> None:
    async def load_initial(*_args):
        return snapshots[0]

    async def switch_range(_page, _target_episode_id, desired, _series_id):
        page.range_index = desired.dom_index

    async def wait_for_listing(*_args):
        return snapshots[page.range_index]

    async def expand_range(*_args):
        if page.range_index == failing_range:
            raise DiscoveryIncompleteError("later range failed")
        return snapshots[page.range_index]["episodes"]

    monkeypatch.setattr(adapter, "_load_initial_listing", load_initial)
    monkeypatch.setattr(adapter, "_switch_range", switch_range)
    monkeypatch.setattr(adapter, "_wait_for_listing", wait_for_listing)
    monkeypatch.setattr(adapter, "_expand_range", expand_range)
    monkeypatch.setattr(adapter, "_ranges", lambda _snapshot: ranges)


def _jump_target(scope: DiscoveryScope | None) -> WatchlistTarget:
    return WatchlistTarget(
        key="jumpplus-scope",
        work_key="jumpplus-work",
        site="jumpplus",
        url="https://shonenjumpplus.com/episode/123",
        label="Work",
        discovery_scope=scope,
    )


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (
            DiscoveryScope(
                from_url="https://shonenjumpplus.com/episode/300",
                through_url="https://shonenjumpplus.com/episode/100",
            ),
            ["300", "200", "100"],
        ),
        (
            DiscoveryScope(from_url="https://shonenjumpplus.com/episode/200"),
            ["200", "100"],
        ),
        (
            DiscoveryScope(through_url="https://shonenjumpplus.com/episode/200"),
            ["400", "300", "200"],
        ),
        (
            DiscoveryScope(
                from_url="https://shonenjumpplus.com/episode/300",
                through_url="https://shonenjumpplus.com/episode/300",
            ),
            ["300"],
        ),
    ],
)
def test_jumpplus_bounded_scope_selects_by_episode_identity(scope, expected) -> None:
    records = [_jump_record(episode_id) for episode_id in ["400", "300", "200", "100"]]
    selected = JumpPlusDiscoveryAdapter._apply_discovery_scope(records, scope)
    assert [item.source.external_id for item in selected] == expected


@pytest.mark.parametrize(
    "scope",
    [
        DiscoveryScope(from_url="https://example.test/episode/300"),
        DiscoveryScope(from_url="https://shonenjumpplus.com/not-episode/300"),
        DiscoveryScope(from_url="https://shonenjumpplus.com/episode/999"),
        DiscoveryScope(through_url="https://shonenjumpplus.com/episode/999"),
        DiscoveryScope(
            from_url="https://shonenjumpplus.com/episode/200",
            through_url="https://shonenjumpplus.com/episode/400",
        ),
    ],
)
def test_jumpplus_bounded_scope_rejects_invalid_or_missing_boundaries(scope) -> None:
    records = [_jump_record(episode_id) for episode_id in ["400", "300", "200", "100"]]
    with pytest.raises(DiscoveryIncompleteError):
        JumpPlusDiscoveryAdapter._apply_discovery_scope(records, scope)


def test_jumpplus_bounded_capability_is_explicit() -> None:
    assert JumpPlusDiscoveryAdapter.supports_bounded_discovery is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "incremental"])
async def test_jumpplus_bounded_buffers_all_ranges_before_yielding(monkeypatch, mode) -> None:
    adapter = JumpPlusDiscoveryAdapter()
    page = _FakePage()
    snapshots = [_jump_snapshot(["4", "3"]), _jump_snapshot(["2", "1"])]
    ranges = [
        adapter._ranges({"range_controls": [{"text": "4 - 3"}, {"text": "2 - 1"}]})[0],
        adapter._ranges({"range_controls": [{"text": "4 - 3"}, {"text": "2 - 1"}]})[1],
    ]
    _configure_jumpplus_traversal(monkeypatch, adapter, page, snapshots, ranges)

    observed = [
        record
        async for record in adapter.iter_records(
            page,
            _jump_target(
                DiscoveryScope(
                    from_url="https://shonenjumpplus.com/episode/3",
                    through_url="https://shonenjumpplus.com/episode/2",
                )
            ),
            mode,
        )
    ]

    assert [item.source.external_id for item in observed] == ["3", "2"]


@pytest.mark.asyncio
async def test_jumpplus_bounded_preserves_global_positions_from_complete_identity_order(
    monkeypatch,
) -> None:
    adapter = JumpPlusDiscoveryAdapter()
    page = _FakePage()
    snapshot = _jump_snapshot([str(value) for value in range(140, 0, -1)])
    ranges = [JumpPlusRange("140 - 1", 0, 140, 1)]
    _configure_jumpplus_traversal(monkeypatch, adapter, page, [snapshot], ranges)

    observed = [
        record
        async for record in adapter.iter_records(
            page,
            _jump_target(
                DiscoveryScope(
                    from_url="https://shonenjumpplus.com/episode/140",
                    through_url="https://shonenjumpplus.com/episode/138",
                )
            ),
            "full",
        )
    ]

    assert [record.source.external_id for record in observed] == ["140", "139", "138"]
    assert [record.source.global_display_position for record in observed] == [140, 139, 138]
    assert all(record.item.order_label == "Special" for record in observed)


@pytest.mark.asyncio
async def test_jumpplus_special_chapter_keeps_global_position_without_label_inference(
    monkeypatch,
) -> None:
    adapter = JumpPlusDiscoveryAdapter()
    page = _FakePage()
    snapshot = _jump_snapshot(["5004", "5003", "5000", "5002", "5001"])
    labels = ["第4話", "第3話", "番外編", "第2話", "第1話"]
    for row, label in zip(snapshot["episodes"], labels, strict=True):
        row["title_text"] = label
    ranges = [JumpPlusRange("5 - 1", 0, 5, 1)]
    _configure_jumpplus_traversal(monkeypatch, adapter, page, [snapshot], ranges)

    observed = [
        record
        async for record in adapter.iter_records(
            page,
            _jump_target(
                DiscoveryScope(
                    from_url="https://shonenjumpplus.com/episode/5003",
                    through_url="https://shonenjumpplus.com/episode/5002",
                )
            ),
            "full",
        )
    ]

    assert [record.item.order_label for record in observed] == ["第3話", "番外編", "第2話"]
    assert [record.source.global_display_position for record in observed] == [4, 3, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "incremental"])
async def test_jumpplus_bounded_later_range_failure_yields_no_records(
    monkeypatch, mode
) -> None:
    adapter = JumpPlusDiscoveryAdapter()
    page = _FakePage()
    snapshots = [_jump_snapshot(["2", "1"]), _jump_snapshot(["0"])]
    ranges = [
        adapter._ranges({"range_controls": [{"text": "2 - 1"}, {"text": "1"}]})[0],
        adapter._ranges({"range_controls": [{"text": "2 - 1"}, {"text": "1"}]})[1],
    ]
    _configure_jumpplus_traversal(
        monkeypatch,
        adapter,
        page,
        snapshots,
        ranges,
        failing_range=1,
    )

    observed = []
    with pytest.raises(DiscoveryIncompleteError):
        async for record in adapter.iter_records(
            page,
            _jump_target(
                DiscoveryScope(
                    from_url="https://shonenjumpplus.com/episode/2",
                    through_url="https://shonenjumpplus.com/episode/1",
                )
            ),
            mode,
        ):
            observed.append(record)
    assert observed == []


@pytest.mark.asyncio
async def test_jumpplus_unbounded_incremental_keeps_prior_yields_on_later_failure(
    monkeypatch,
) -> None:
    adapter = JumpPlusDiscoveryAdapter()
    page = _FakePage()
    snapshots = [_jump_snapshot(["2", "1"]), _jump_snapshot(["0"])]
    ranges = [
        adapter._ranges({"range_controls": [{"text": "2 - 1"}, {"text": "1"}]})[0],
        adapter._ranges({"range_controls": [{"text": "2 - 1"}, {"text": "1"}]})[1],
    ]
    _configure_jumpplus_traversal(
        monkeypatch,
        adapter,
        page,
        snapshots,
        ranges,
        failing_range=1,
    )

    observed = []
    with pytest.raises(DiscoveryIncompleteError):
        async for record in adapter.iter_records(page, _jump_target(None), "incremental"):
            observed.append(record)
    assert [item.source.external_id for item in observed] == ["2", "1"]

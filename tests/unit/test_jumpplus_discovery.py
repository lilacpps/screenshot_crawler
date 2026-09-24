from datetime import datetime, timedelta, timezone

import pytest

from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.jumpplus.discovery import (
    JumpPlusDiscoveryAdapter,
    canonical_jumpplus_episode_url,
    map_jumpplus_access,
    parse_jumpplus_dom_expiry,
    parse_jumpplus_episode_url,
    parse_jumpplus_order_label,
    parse_jumpplus_published_at,
    parse_jumpplus_range_label,
    parse_jumpplus_structured_expiry,
)


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
        {"range_controls": [{"text": "286 - 187"}, {"text": "186 - 87"}]}
    )
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

    def locator(self, _selector):
        return _FakeLocator(self)

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

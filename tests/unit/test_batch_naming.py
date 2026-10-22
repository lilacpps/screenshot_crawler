import pytest

from screenshot_crawler.batch.naming import (
    ArchiveOrderPlanningError,
    archive_position_prefix,
    build_work_archive_position_plan,
)
from screenshot_crawler.catalog.models import Item, Source, Work
from screenshot_crawler.watchlist.models import WatchlistTarget


@pytest.mark.parametrize(
    ("display_position", "expected"),
    [(1, "001"), (3, "003"), (999, "999"), (1000, "1000"), (None, None)],
)
def test_archive_position_prefix_does_not_infer_from_missing_position(
    display_position: int | None,
    expected: str | None,
) -> None:
    assert archive_position_prefix(display_position) == expected


def _work() -> Work:
    return Work(1, "series", "Series", None, None, "", "")


def _target(key: str, site: str, order: int | None) -> WatchlistTarget:
    return WatchlistTarget(
        key=key,
        work_key="series",
        site=site,
        url=f"https://example.invalid/{key}/list",
        label=key,
        archive_order=order,
    )


def _item(item_id: int, *, status: str = "pending") -> Item:
    return Item(item_id, 1, None, None, None, None, status, None, "", "")


def _source(
    source_id: int,
    item_id: int,
    key: str,
    site: str,
    position: int | None,
    *,
    enabled: bool = True,
) -> Source:
    return Source(
        id=source_id,
        item_id=item_id,
        site=site,
        external_id=f"external-{source_id}",
        discovery_key=key,
        access_mode="paid",
        free_until=None,
        available=False,
        access_checked_at=None,
        last_seen_at=None,
        quota_started_at=None,
        access_granted_until=None,
        published_at=None,
        created_at="",
        updated_at="",
        display_position=position,
        acquisition_enabled=enabled,
    )


def test_work_archive_positions_order_keys_then_global_display_position() -> None:
    plan = build_work_archive_position_plan(
        _work(),
        [_target("book", "bookwalker", 2), _target("zeblack", "zeblack", 1)],
        [_item(1, status="completed"), _item(2, status="skipped"), _item(3)],
        [
            _source(1, 1, "zeblack", "zeblack", 1),
            _source(2, 2, "zeblack", "zeblack", 2, enabled=False),
            _source(3, 3, "book", "bookwalker", 1),
            _source(4, 3, "book", "bookwalker", 2),
        ],
    )

    assert plan is not None
    assert plan.ordered_source_ids == (1, 3, 4)
    assert dict(plan.positions_by_source_id) == {1: 1, 3: 2, 4: 3}


def test_work_archive_positions_keeps_disabled_paid_rows_out_without_status_filter() -> None:
    targets = [_target("a", "zeblack", 1), _target("b", "bookwalker", 2)]
    items = [_item(1, status="external"), _item(2, status="completed")]
    sources = [
        _source(1, 1, "a", "zeblack", 100),
        _source(2, 1, "a", "zeblack", 101, enabled=False),
        _source(3, 2, "b", "bookwalker", 1),
    ]
    plan = build_work_archive_position_plan(_work(), targets, items, sources)
    assert plan is not None
    assert dict(plan.positions_by_source_id) == {1: 1, 3: 2}


@pytest.mark.parametrize(
    "sources",
    [
        [_source(1, 1, "a", "zeblack", None)],
        [_source(1, 1, "a", "zeblack", 1), _source(2, 1, "a", "zeblack", 1)],
        [_source(1, 1, "unknown", "zeblack", 1)],
        [_source(1, 1, "a", "bookwalker", 1)],
    ],
    ids=["null-position", "duplicate-position", "unknown-owner", "wrong-site"],
)
def test_work_archive_positions_rejects_unresolved_ownership_or_positions(
    sources: list[Source],
) -> None:
    with pytest.raises(ArchiveOrderPlanningError):
        build_work_archive_position_plan(
            _work(), [_target("a", "zeblack", 1)], [_item(1)], sources
        )


def test_work_archive_positions_preserves_unordered_legacy_mode() -> None:
    assert build_work_archive_position_plan(
        _work(),
        [_target("a", "zeblack", None)],
        [_item(1)],
        [_source(1, 1, "a", "zeblack", None)],
    ) is None

from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import CatalogService, ItemInput, SourceInput
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import (
    BookWalkerSitePolicy,
    SitePolicyError,
    SitePolicyRegistry,
)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=JST)


def make_registry() -> SitePolicyRegistry:
    registry = SitePolicyRegistry()
    registry.register("bookwalker", BookWalkerSitePolicy)
    return registry


def add_source(
    service: CatalogService,
    *,
    order: str,
    access_mode: str = "quota",
    status: str = "pending",
    quota_started_at: str | None = None,
    access_granted_until: str | None = None,
    available: bool = True,
):
    item = service.create_item(ItemInput(canonical_title=f"Volume {order}", order_key=order, status=status))
    source = service.create_source(
        SourceInput(
            site="bookwalker",
            external_id=f"book-{order}-{item.id}",
            url=f"https://bookwalker.example/de{order}/",
            access_mode=access_mode,
            available=available,
            quota_started_at=quota_started_at,
            access_granted_until=access_granted_until,
        ),
        item_id=item.id,
    )
    return item, source


def test_quota_window_is_05_00_jst_half_open_and_normalizes_timezone() -> None:
    policy = BookWalkerSitePolicy()

    start, end = policy.quota_window(datetime(2026, 9, 19, 5, 0, tzinfo=JST))
    assert start == datetime(2026, 9, 19, 5, 0, tzinfo=JST)
    assert end == datetime(2026, 9, 20, 5, 0, tzinfo=JST)

    before_start, before_end = policy.quota_window(
        datetime(2026, 9, 18, 19, 59, tzinfo=JST)
    )
    assert before_start == datetime(2026, 9, 18, 5, 0, tzinfo=JST)
    assert before_end == datetime(2026, 9, 19, 5, 0, tzinfo=JST)

    # Use a deterministic non-JST offset: 2026-09-19 05:00 JST.
    utc_now = datetime.fromisoformat("2026-09-18T20:00:00+00:00")
    assert policy.quota_window(utc_now) == (start, end)

    with pytest.raises(SitePolicyError, match="timezone-aware"):
        policy.quota_window(datetime.fromisoformat("2026-09-19T05:00:00"))


def test_available_quota_is_site_wide_and_ignores_old_window(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    add_source(
        service,
        order="old",
        status="completed",
        quota_started_at="2026-09-18T04:59:59+09:00",
    )
    add_source(
        service,
        order="current",
        status="completed",
        quota_started_at="2026-09-19T06:00:00+09:00",
    )
    _, sources = service.read_items_and_sources(site="bookwalker")

    policy = BookWalkerSitePolicy()
    assert policy.available_quota(sources, NOW) == 0
    assert policy.available_quota(sources, datetime(2026, 9, 20, 5, 0, tzinfo=JST)) == 1


@pytest.mark.parametrize(
    ("access_mode", "available", "expected"),
    [
        ("owned", True, (True, "direct", "owned", False)),
        ("quota", True, (True, "quota", "quota_available", True)),
        ("quota", False, (False, None, "unavailable", False)),
        ("paid", True, (False, None, "paid", False)),
        ("unknown", True, (False, None, "unknown", False)),
        ("free", True, (False, None, "unsupported_access_mode", False)),
    ],
)
def test_policy_decision_mapping(
    tmp_path: Path,
    access_mode: str,
    available: bool,
    expected: tuple[bool, str | None, str, bool],
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    _, source = add_source(
        service,
        order=access_mode,
        access_mode=access_mode,
        available=available,
    )

    decision = BookWalkerSitePolicy().evaluate(
        source,
        now=NOW,
        quota_available=1,
    )
    assert (
        decision.eligible,
        decision.access_strategy,
        decision.reason,
        decision.consumes_quota,
    ) == expected


def test_active_grant_does_not_turn_bookwalker_quota_into_direct(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    future = "2026-09-20T12:00:00+09:00"
    item, source = add_source(
        service,
        order="active",
        access_granted_until=future,
    )

    assert source.quota_started_at is None
    assert source.access_granted_until == future

    decision = BookWalkerSitePolicy().evaluate(source, now=NOW, quota_available=1)
    assert decision.access_strategy == "quota"
    assert decision.consumes_quota is True
    assert service.get_item(item.id).status == "pending"
    assert BookWalkerSitePolicy().access_grant_until(NOW) is None


def test_record_quota_access_accepts_and_clears_grantless_state(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    _, source = add_source(service, order="grantless")
    service.record_quota_access(
        source.id,
        quota_started_at=NOW,
        access_granted_until="2026-09-20T12:00:00+09:00",
    )
    updated = service.record_quota_access(
        source.id,
        quota_started_at=NOW,
        access_granted_until=None,
    )

    assert updated.quota_started_at == NOW.isoformat()
    assert updated.access_granted_until is None

    with pytest.raises(ValueError, match="quota_started_at is required"):
        service.record_quota_access(
            source.id,
            quota_started_at=None,  # type: ignore[arg-type]
            access_granted_until=None,
        )


def test_planner_allocates_one_site_wide_quota_in_natural_order(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    add_source(service, order="03")
    add_source(service, order="01", access_mode="owned")
    add_source(service, order="02")
    add_source(service, order="04")

    plan = BatchPlanner(service, make_registry()).plan(site="bookwalker", now=NOW)

    assert [service.get_item(candidate.item_id).order_key for candidate in plan.candidates] == [
        "01",
        "02",
    ]
    assert [candidate.access_strategy for candidate in plan.candidates] == ["direct", "quota"]
    assert plan.quota_available == 1
    assert plan.quota_remaining == 0
    assert Counter(skipped.reason for skipped in plan.skipped) == Counter({"quota_exhausted": 2})


def test_planner_reopens_quota_in_next_window(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    add_source(
        service,
        order="used",
        status="completed",
        quota_started_at="2026-09-19T04:59:59+09:00",
    )
    add_source(service, order="pending")

    plan = BatchPlanner(service, make_registry()).plan(
        site="bookwalker",
        now=datetime(2026, 9, 19, 5, 0, tzinfo=JST),
    )

    assert plan.quota_available == 1
    assert plan.quota_count == 1

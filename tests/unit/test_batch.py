from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from screenshot_crawler.batch import BatchPlanner, BatchPlanningError
from screenshot_crawler.catalog import CatalogService, ItemInput, SourceInput
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import MangaOneSitePolicy, SitePolicyRegistry

NOW = datetime(2026, 9, 17, 15, 0, tzinfo=JST)


def make_registry() -> SitePolicyRegistry:
    registry = SitePolicyRegistry()
    registry.register("mangaone", MangaOneSitePolicy)
    return registry


def add_source(
    service: CatalogService,
    *,
    item: ItemInput,
    external_id: str,
    access_mode: str = "quota",
    free_until: str | None = None,
    available: bool = True,
    quota_started_at: str | None = None,
    access_granted_until: str | None = None,
):
    catalog_item = service.create_item(item)
    source = service.create_source(
        SourceInput(
            site="mangaone",
            external_id=external_id,
            url=f"https://manga-one.example/chapter/{external_id}",
            access_mode=access_mode,
            free_until=free_until,
            available=available,
            quota_started_at=quota_started_at,
            access_granted_until=access_granted_until,
        ),
        item_id=catalog_item.id,
    )
    return catalog_item, source


def plan_for(service: CatalogService, *, now: datetime = NOW):
    return BatchPlanner(service, make_registry()).plan(site="mangaone", now=now)


def test_pending_only_and_basic_access_modes(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    add_source(service, item=ItemInput(canonical_title="free"), external_id="free", access_mode="free")
    completed, _ = add_source(
        service,
        item=ItemInput(canonical_title="completed", status="completed"),
        external_id="completed",
        access_mode="free",
    )
    add_source(
        service,
        item=ItemInput(canonical_title="unavailable"),
        external_id="unavailable",
        access_mode="owned",
        available=False,
    )
    add_source(service, item=ItemInput(canonical_title="paid"), external_id="paid", access_mode="paid")
    add_source(
        service,
        item=ItemInput(canonical_title="unknown"),
        external_id="unknown",
        access_mode="unknown",
    )

    plan = plan_for(service)

    assert [(candidate.item_id, candidate.access_strategy) for candidate in plan.candidates] == [
        (1, "direct")
    ]
    reasons = Counter(skipped.reason for skipped in plan.skipped)
    assert reasons == Counter(
        {"completed": 1, "unavailable": 1, "paid": 1, "unknown": 1}
    )
    assert completed.id == 2


def test_source_priority_and_metadata_mapping(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    item = service.create_item(
        ItemInput(
            canonical_title="作品A",
            author="作者A",
            order_key="80",
            order_label="第80話-後編",
            genre="漫画",
        )
    )
    service.create_source(
        SourceInput(
            site="mangaone",
            external_id="quota",
            url="https://example.invalid/quota",
            access_mode="quota",
        ),
        item_id=item.id,
    )
    owned = service.create_source(
        SourceInput(
            site="mangaone",
            external_id="owned",
            url="https://example.invalid/owned",
            access_mode="owned",
        ),
        item_id=item.id,
    )
    service.create_source(
        SourceInput(
            site="mangaone",
            external_id="free-late",
            url="https://example.invalid/free-late",
            access_mode="free",
            free_until="2026-09-17T20:00:00+09:00",
        ),
        item_id=item.id,
    )
    nearest = service.create_source(
        SourceInput(
            site="mangaone",
            external_id="free-nearest",
            url="https://example.invalid/free-nearest",
            access_mode="free",
            free_until="2026-09-17T16:00:00+09:00",
        ),
        item_id=item.id,
    )

    plan = plan_for(service)

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.source_id == nearest.id
    assert candidate.source_id != owned.id
    assert candidate.access_mode == "free"
    assert candidate.access_strategy == "direct"
    assert candidate.metadata == {
        "title": "作品A",
        "author": "作者A",
        "order": "第80話-後編",
        "genre": "漫画",
    }


def test_quota_is_reserved_in_memory_only(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for index in range(5):
        add_source(
            service,
            item=ItemInput(canonical_title=f"quota-{index}"),
            external_id=f"quota-{index}",
        )

    before = service.read_items_and_sources(site="mangaone")
    before_bytes = service.path.read_bytes()
    plan = plan_for(service)
    after = service.read_items_and_sources(site="mangaone")

    assert len(plan.candidates) == 4
    assert plan.quota_count == 4
    assert plan.quota_remaining == 0
    assert sum(item.consumes_quota for item in plan.candidates) == 4
    assert [skipped.reason for skipped in plan.skipped] == ["quota_exhausted"]
    assert before == after
    assert service.path.read_bytes() == before_bytes


def test_quota_window_counts_only_current_window(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for index, started_at in enumerate(
        ("2026-09-17T10:00:00+09:00", "2026-09-17T14:59:00+09:00")
    ):
        add_source(
            service,
            item=ItemInput(canonical_title=f"used-{index}", status="completed"),
            external_id=f"used-{index}",
            quota_started_at=started_at,
        )
    add_source(
        service,
        item=ItemInput(canonical_title="previous-window", status="completed"),
        external_id="previous-window",
        quota_started_at="2026-09-17T08:59:00+09:00",
    )
    for index in range(3):
        add_source(
            service,
            item=ItemInput(canonical_title=f"candidate-{index}"),
            external_id=f"candidate-{index}",
        )

    plan = plan_for(service)

    assert len(plan.candidates) == 2
    assert plan.quota_available == 2
    assert plan.quota_remaining == 0
    assert Counter(skipped.reason for skipped in plan.skipped)["quota_exhausted"] == 1


def test_reset_boundaries_and_active_or_expired_grant(tmp_path: Path) -> None:
    policy = MangaOneSitePolicy()
    morning_start, morning_end = policy.quota_window(
        datetime(2026, 9, 17, 9, 0, tzinfo=JST)
    )
    evening_start, evening_end = policy.quota_window(
        datetime(2026, 9, 17, 21, 0, tzinfo=JST)
    )
    assert (morning_start.hour, morning_end.hour) == (9, 21)
    assert (evening_start.hour, evening_end.hour) == (21, 9)
    assert evening_end.date() == datetime(2026, 9, 18, tzinfo=JST).date()

    service = CatalogService(tmp_path / "catalog.sqlite")
    active, _ = add_source(
        service,
        item=ItemInput(canonical_title="active"),
        external_id="active",
        access_granted_until="2026-09-17T16:00:00+09:00",
    )
    expired, _ = add_source(
        service,
        item=ItemInput(canonical_title="expired"),
        external_id="expired",
        access_granted_until="2026-09-17T15:00:00+09:00",
    )

    plan = plan_for(service)

    by_item = {candidate.item_id: candidate for candidate in plan.candidates}
    assert by_item[active.id].access_strategy == "direct"
    assert by_item[active.id].consumes_quota is False
    assert by_item[expired.id].access_strategy == "quota"
    assert by_item[expired.id].consumes_quota is True


def test_quota_window_before_morning_uses_previous_evening(tmp_path: Path) -> None:
    policy = MangaOneSitePolicy()
    now = datetime(2026, 9, 17, 8, 0, tzinfo=JST)

    start, end = policy.quota_window(now)

    assert start == datetime(2026, 9, 16, 21, 0, tzinfo=JST)
    assert end == datetime(2026, 9, 17, 9, 0, tzinfo=JST)

    service = CatalogService(tmp_path / "catalog.sqlite")
    for index, started_at in enumerate(
        (
            "2026-09-16T20:59:00+09:00",
            "2026-09-16T21:00:00+09:00",
            "2026-09-17T07:59:00+09:00",
            "2026-09-17T09:00:00+09:00",
        )
    ):
        add_source(
            service,
            item=ItemInput(canonical_title=f"usage-{index}", status="completed"),
            external_id=f"usage-{index}",
            quota_started_at=started_at,
        )

    _, sources = service.read_items_and_sources(site="mangaone")

    assert policy.available_quota(sources, now) == 2


def test_quota_usage_uses_reset_boundaries(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for index in range(4):
        add_source(
            service,
            item=ItemInput(canonical_title=f"morning-{index}", status="completed"),
            external_id=f"morning-{index}",
            quota_started_at="2026-09-17T09:00:00+09:00",
        )
    _, sources = service.read_items_and_sources(site="mangaone")
    policy = MangaOneSitePolicy()

    assert policy.available_quota(sources, datetime(2026, 9, 17, 9, 0, tzinfo=JST)) == 0
    assert policy.available_quota(sources, datetime(2026, 9, 17, 21, 0, tzinfo=JST)) == 4


def test_naive_now_and_unknown_policy_fail_safely(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    add_source(service, item=ItemInput(canonical_title="A"), external_id="a")

    with pytest.raises(BatchPlanningError, match="timezone-aware"):
        plan_for(service, now=datetime.fromisoformat("2026-09-17T15:00:00"))
    with pytest.raises(BatchPlanningError, match="No Site Policy"):
        BatchPlanner(service, make_registry()).plan(site="bookwalker", now=NOW)


def test_missing_catalog_is_not_created_by_planning(tmp_path: Path) -> None:
    catalog_path = tmp_path / "missing.sqlite"

    with pytest.raises(BatchPlanningError, match="not found"):
        BatchPlanner(CatalogService(catalog_path), make_registry()).plan(
            site="mangaone", now=NOW
        )

    assert not catalog_path.exists()

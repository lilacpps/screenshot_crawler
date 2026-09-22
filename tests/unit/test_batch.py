from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from screenshot_crawler.batch import BatchPlanner, BatchPlanningError
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import (
    BookWalkerSitePolicy,
    MangaOneSitePolicy,
    SitePolicyRegistry,
)

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
    discovery_key: str | None = None,
    quota_started_at: str | None = None,
    access_granted_until: str | None = None,
    work: WorkInput | None = None,
):
    catalog_item = add_item(
        service,
        item,
        work=work or WorkInput(
            work_key=f"work-{external_id}",
            title=item.item_title or external_id,
        ),
    )
    source = service.create_source(
        SourceInput(
            site="mangaone",
            external_id=external_id,
            discovery_key=discovery_key,
            access_mode=access_mode,
            free_until=free_until,
            available=available,
            quota_started_at=quota_started_at,
            access_granted_until=access_granted_until,
        ),
        item_id=catalog_item.id,
    )
    service.create_source_target(
        SourceTargetInput(
            backend="web",
            locator=f"https://manga-one.example/chapter/{external_id}",
        ),
        source_id=source.id,
    )
    return catalog_item, source


def add_item(
    service: CatalogService,
    item: ItemInput,
    *,
    work: WorkInput | None = None,
):
    work = work or WorkInput(
        work_key=f"work-item-{item.item_title or 'default'}",
        title=item.item_title or "Test work",
    )
    catalog_work = service.create_work(work)
    return service.create_item(item, work_id=catalog_work.id)


def plan_for(service: CatalogService, *, now: datetime = NOW):
    return BatchPlanner(service, make_registry()).plan(site="mangaone", now=now)


def test_pending_only_and_basic_access_modes(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    add_source(service, item=ItemInput(item_title="free"), external_id="free", access_mode="free")
    completed, _ = add_source(
        service,
        item=ItemInput(item_title="completed", status="completed"),
        external_id="completed",
        access_mode="free",
    )
    add_source(
        service,
        item=ItemInput(item_title="unavailable"),
        external_id="unavailable",
        access_mode="owned",
        available=False,
    )
    add_source(service, item=ItemInput(item_title="paid"), external_id="paid", access_mode="paid")
    add_source(
        service,
        item=ItemInput(item_title="unknown"),
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


def test_site_scoped_plan_ignores_other_site_and_orphan_items(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    mangaone_item, _ = add_source(
        service,
        item=ItemInput(item_title="mangaone"),
        external_id="mangaone",
        access_mode="free",
    )
    bookwalker_item = add_item(service, ItemInput(item_title="bookwalker"))
    service.create_source(
        SourceInput(site="bookwalker", external_id="bookwalker"),
        item_id=bookwalker_item.id,
    )
    orphan_item = add_item(service, ItemInput(item_title="orphan"))

    plan = plan_for(service)

    planned_item_ids = {candidate.item_id for candidate in plan.candidates}
    skipped_item_ids = {skipped.item_id for skipped in plan.skipped}
    assert planned_item_ids == {mangaone_item.id}
    assert bookwalker_item.id not in planned_item_ids | skipped_item_ids
    assert orphan_item.id not in planned_item_ids | skipped_item_ids
    assert all(skipped.reason != "no_source" for skipped in plan.skipped)


def test_source_priority_and_metadata_mapping(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    item = add_item(
        service,
        ItemInput(
            order_key="80",
            order_label="第80話-後編",
        ),
        work=WorkInput(
            work_key="work-a",
            title="作品A",
            author="作者A",
            genre="漫画",
        ),
    )
    quota = service.create_source(
        SourceInput(
            site="mangaone",
            external_id="quota",
            access_mode="quota",
        ),
        item_id=item.id,
    )
    service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/quota"),
        source_id=quota.id,
    )
    owned = service.create_source(
        SourceInput(
            site="mangaone",
            external_id="owned",
            access_mode="owned",
        ),
        item_id=item.id,
    )
    service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/owned"),
        source_id=owned.id,
    )
    free_late = service.create_source(
        SourceInput(
            site="mangaone",
            external_id="free-late",
            access_mode="free",
            free_until="2026-09-17T20:00:00+09:00",
        ),
        item_id=item.id,
    )
    service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/free-late"),
        source_id=free_late.id,
    )
    nearest = service.create_source(
        SourceInput(
            site="mangaone",
            external_id="free-nearest",
            access_mode="free",
            free_until="2026-09-17T16:00:00+09:00",
        ),
        item_id=item.id,
    )
    service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/free-nearest"),
        source_id=nearest.id,
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


def test_mangaone_non_numeric_order_gets_stable_artifact_disambiguator(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    first_item, first_source = add_source(
        service,
        item=ItemInput(item_title="おまけ", order_label="おまけ"),
        external_id="214131",
        access_mode="free",
    )
    second_item, second_source = add_source(
        service,
        item=ItemInput(item_title="おまけ", order_label="おまけ"),
        external_id="214987",
        access_mode="free",
    )

    plan = plan_for(service)
    candidates = {candidate.source_id: candidate for candidate in plan.candidates}

    assert candidates[first_source.id].artifact_disambiguator == "mangaone-214131"
    assert candidates[second_source.id].artifact_disambiguator == "mangaone-214987"
    assert candidates[first_source.id].metadata["order"] == "おまけ"
    assert candidates[second_source.id].metadata["order"] == "おまけ"
    assert candidates[first_source.id].item_id == first_item.id
    assert candidates[second_source.id].item_id == second_item.id


def test_mangaone_numeric_order_has_no_artifact_disambiguator(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    _, source = add_source(
        service,
        item=ItemInput(item_title="第80話", order_key="80", order_label="第80話"),
        external_id="214131",
        access_mode="free",
    )

    candidate = plan_for(service).candidates[0]

    assert candidate.source_id == source.id
    assert candidate.artifact_disambiguator is None


def test_non_mangaone_candidate_has_no_artifact_disambiguator(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    work = service.create_work(WorkInput(work_key="book", title="作品"))
    item = service.create_item(ItemInput(item_title="第01巻", order_key="01"), work_id=work.id)
    source = service.create_source(
        SourceInput(site="bookwalker", external_id="book-1", access_mode="owned"),
        item_id=item.id,
    )
    service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/book-1"),
        source_id=source.id,
    )

    registry = SitePolicyRegistry()
    registry.register("bookwalker", BookWalkerSitePolicy)
    plan = BatchPlanner(service, registry).plan(site="bookwalker", now=NOW)

    assert plan.candidates[0].artifact_disambiguator is None


def test_planner_selects_enabled_web_target_and_skips_other_backends(
    tmp_path: Path,
) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")

    no_target_item = add_item(service, ItemInput(item_title="no target"))
    no_target_source = service.create_source(
        SourceInput(site="mangaone", external_id="no-target", access_mode="free"),
        item_id=no_target_item.id,
    )
    disabled_item = add_item(service, ItemInput(item_title="disabled"))
    disabled_source = service.create_source(
        SourceInput(site="mangaone", external_id="disabled", access_mode="free"),
        item_id=disabled_item.id,
    )
    service.create_source_target(
        SourceTargetInput(backend="web", locator="https://example.invalid/disabled", enabled=False),
        source_id=disabled_source.id,
    )
    android_item = add_item(service, ItemInput(item_title="android only"))
    android_source = service.create_source(
        SourceInput(site="mangaone", external_id="android", access_mode="free"),
        item_id=android_item.id,
    )
    service.create_source_target(
        SourceTargetInput(backend="android", locator="episode_android"),
        source_id=android_source.id,
    )
    selected_item, selected_source = add_source(
        service,
        item=ItemInput(item_title="selected"),
        external_id="selected",
        access_mode="free",
    )
    selected_target = service.find_source_target(selected_source.id, "web")
    assert selected_target is not None
    direct_target = service.create_source_target(
        SourceTargetInput(
            backend="web",
            target_key="direct",
            locator="https://example.invalid/direct",
            priority=50,
        ),
        source_id=selected_source.id,
    )

    plan = plan_for(service)

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert (candidate.item_id, candidate.source_id) == (selected_item.id, selected_source.id)
    assert candidate.target_id == direct_target.id
    assert candidate.backend == "web"
    assert candidate.target_key == "direct"
    assert candidate.locator.endswith("/direct")
    assert Counter(skipped.reason for skipped in plan.skipped) == Counter(
        {"no enabled web target": 3}
    )
    assert {skipped.source_id for skipped in plan.skipped} == {
        no_target_source.id,
        disabled_source.id,
        android_source.id,
    }


def test_quota_is_reserved_in_memory_only(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for index in range(5):
        add_source(
            service,
            item=ItemInput(item_title=f"quota-{index}"),
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
    assert all(item.quota_resource is None for item in plan.candidates)
    assert all(item.quota_commit_mode == "before_run" for item in plan.candidates)
    assert [skipped.reason for skipped in plan.skipped] == ["quota_exhausted"]
    assert before == after
    assert service.path.read_bytes() == before_bytes


def test_new_quota_is_allocated_to_oldest_episode_first(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for index in range(2):
        add_source(
            service,
            item=ItemInput(item_title=f"used-{index}", status="completed"),
            external_id=f"used-{index}",
            quota_started_at="2026-09-17T14:00:00+09:00",
        )
    inserted_order = ["05", "04", "03", "02", "01"]
    items = {
        order: add_source(
            service,
            item=ItemInput(item_title=f"第{order}話", order_key=order),
            external_id=f"episode-{order}",
        )[0]
        for order in inserted_order
    }

    plan = plan_for(service)

    assert plan.quota_available == 2
    assert [plan_item.order_key for plan_item in (service.get_item(c.item_id) for c in plan.candidates)] == [
        "01",
        "02",
    ]
    assert Counter(skipped.reason for skipped in plan.skipped) == Counter(
        {"completed": 2, "quota_exhausted": 3}
    )
    assert all(items[order].id not in {c.item_id for c in plan.candidates} for order in ["05", "04", "03"])


def test_new_quota_is_allocated_by_discovery_group_then_item_order(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for index in range(2):
        add_source(
            service,
            item=ItemInput(item_title=f"used-{index}", status="completed"),
            external_id=f"used-{index}",
            quota_started_at="2026-09-17T14:00:00+09:00",
        )

    for group, order in [("A", "03"), ("B", "01"), ("A", "01"), ("B", "02")]:
        add_source(
            service,
            item=ItemInput(item_title=f"{group}-{order}", order_key=order),
            external_id=f"{group}-{order}",
            discovery_key=group,
        )

    plan = plan_for(service)

    assert [
        service.get_item(candidate.item_id).item_title
        for candidate in plan.candidates
    ] == ["A-01", "A-03"]
    assert sum(skipped.reason == "quota_exhausted" for skipped in plan.skipped) == 2


def test_new_item_is_kept_in_its_existing_discovery_group(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    add_source(
        service,
        item=ItemInput(item_title="used", status="completed"),
        external_id="used",
        quota_started_at="2026-09-17T14:00:00+09:00",
    )
    for group, order in [("A", "01"), ("A", "02"), ("B", "01"), ("B", "02"), ("A", "03")]:
        add_source(
            service,
            item=ItemInput(item_title=f"{group}-{order}", order_key=order),
            external_id=f"{group}-{order}",
            discovery_key=group,
        )

    plan = plan_for(service)

    assert [
        service.get_item(candidate.item_id).item_title
        for candidate in plan.candidates
    ] == ["A-01", "A-02", "A-03"]


def test_null_discovery_key_is_after_explicit_groups(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    add_source(
        service,
        item=ItemInput(item_title="used", status="completed"),
        external_id="used",
        quota_started_at="2026-09-17T14:00:00+09:00",
    )
    add_source(
        service,
        item=ItemInput(item_title="null-old", order_key="01"),
        external_id="null-old",
    )
    add_source(
        service,
        item=ItemInput(item_title="explicit", order_key="99"),
        external_id="explicit",
        discovery_key="A",
    )

    plan = plan_for(service)

    assert [
        service.get_item(candidate.item_id).item_title
        for candidate in plan.candidates
    ] == ["explicit", "null-old"]


def test_numeric_episode_order_is_not_lexicographic(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for order in ["11", "1", "10", "9", "2"]:
        add_source(
            service,
            item=ItemInput(item_title=f"第{order}話", order_key=order),
            external_id=f"episode-{order}",
        )

    plan = plan_for(service)

    assert [service.get_item(candidate.item_id).order_key for candidate in plan.candidates] == [
        "1",
        "2",
        "9",
        "10",
    ]


def test_episode_parts_are_ordered_before_next_episode(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for order in ["13", "12-後編", "12-前編", "11"]:
        add_source(
            service,
            item=ItemInput(item_title=order, order_key=order),
            external_id=f"episode-{order}",
        )

    plan = plan_for(service)

    assert [service.get_item(candidate.item_id).order_key for candidate in plan.candidates] == [
        "11",
        "12-前編",
        "12-後編",
        "13",
    ]


def test_quota_window_counts_only_current_window(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for index, started_at in enumerate(
        ("2026-09-17T10:00:00+09:00", "2026-09-17T14:59:00+09:00")
    ):
        add_source(
            service,
            item=ItemInput(item_title=f"used-{index}", status="completed"),
            external_id=f"used-{index}",
            quota_started_at=started_at,
        )
    add_source(
        service,
        item=ItemInput(item_title="previous-window", status="completed"),
        external_id="previous-window",
        quota_started_at="2026-09-17T08:59:00+09:00",
    )
    for index in range(3):
        add_source(
            service,
            item=ItemInput(item_title=f"candidate-{index}"),
            external_id=f"candidate-{index}",
        )

    plan = plan_for(service)

    assert len(plan.candidates) == 2
    assert plan.quota_available == 2
    assert plan.quota_remaining == 0
    assert Counter(skipped.reason for skipped in plan.skipped)["quota_exhausted"] == 1


def test_reset_boundaries_and_active_or_expired_grant(tmp_path: Path) -> None:
    policy = MangaOneSitePolicy()
    assert policy.access_grant_until(NOW) == datetime(2026, 9, 18, 15, 0, tzinfo=JST)
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
        item=ItemInput(item_title="active"),
        external_id="active",
        access_granted_until="2026-09-17T16:00:00+09:00",
    )
    expired, _ = add_source(
        service,
        item=ItemInput(item_title="expired"),
        external_id="expired",
        access_granted_until="2026-09-17T15:00:00+09:00",
    )

    plan = plan_for(service)

    by_item = {candidate.item_id: candidate for candidate in plan.candidates}
    assert by_item[active.id].access_strategy == "direct"
    assert by_item[active.id].consumes_quota is False
    assert by_item[expired.id].access_strategy == "quota"
    assert by_item[expired.id].consumes_quota is True


def test_active_grant_does_not_consume_slot_before_older_quota(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for index in range(3):
        add_source(
            service,
            item=ItemInput(item_title=f"used-{index}", status="completed"),
            external_id=f"used-{index}",
            quota_started_at="2026-09-17T14:00:00+09:00",
        )
    active, _ = add_source(
        service,
        item=ItemInput(item_title="第01話", order_key="01"),
        external_id="active-old",
        access_granted_until="2026-09-17T16:00:00+09:00",
    )
    next_item, _ = add_source(
        service,
        item=ItemInput(item_title="第02話", order_key="02"),
        external_id="next-old",
    )
    exhausted, _ = add_source(
        service,
        item=ItemInput(item_title="第03話", order_key="03"),
        external_id="later",
    )

    plan = plan_for(service)
    by_item = {candidate.item_id: candidate for candidate in plan.candidates}

    assert by_item[active.id].access_strategy == "direct"
    assert by_item[active.id].consumes_quota is False
    assert by_item[next_item.id].access_strategy == "quota"
    assert by_item[next_item.id].consumes_quota is True
    assert exhausted.id not in by_item
    assert plan.quota_available == 1
    assert plan.quota_remaining == 0
    assert sum(skipped.reason == "quota_exhausted" for skipped in plan.skipped) == 1


def test_mixed_access_keeps_direct_behavior_and_allocates_old_quota(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    records = {}
    for order, access_mode in [
        ("05", "quota"),
        ("04", "owned"),
        ("03", "quota"),
        ("02", "free"),
        ("01", "quota"),
    ]:
        records[order] = add_source(
            service,
            item=ItemInput(item_title=f"第{order}話", order_key=order),
            external_id=f"mixed-{order}",
            access_mode=access_mode,
        )[0]
    for index in range(2):
        add_source(
            service,
            item=ItemInput(item_title=f"used-{index}", status="completed"),
            external_id=f"mixed-used-{index}",
            quota_started_at="2026-09-17T14:00:00+09:00",
        )

    plan = plan_for(service)
    by_item = {candidate.item_id: candidate for candidate in plan.candidates}

    assert by_item[records["02"].id].access_strategy == "direct"
    assert by_item[records["04"].id].access_strategy == "direct"
    assert [
        service.get_item(candidate.item_id).order_key
        for candidate in plan.candidates
        if candidate.consumes_quota
    ] == ["01", "03"]
    assert records["05"].id not in by_item


def test_unknown_order_formats_have_stable_fallback(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    for key, label in [(None, "第?話"), ("mystery", "特別編"), ("02", "第02話")]:
        add_source(
            service,
            item=ItemInput(item_title=label, order_key=key, order_label=label),
            external_id=f"unknown-{key or 'none'}",
        )

    first = plan_for(service)
    second = plan_for(service)

    assert [(candidate.item_id, candidate.source_id) for candidate in first.candidates] == [
        (candidate.item_id, candidate.source_id) for candidate in second.candidates
    ]
    assert first.quota_count == 3
    assert first.quota_remaining == 1




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
            item=ItemInput(item_title=f"usage-{index}", status="completed"),
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
            item=ItemInput(item_title=f"morning-{index}", status="completed"),
            external_id=f"morning-{index}",
            quota_started_at="2026-09-17T09:00:00+09:00",
        )
    _, sources = service.read_items_and_sources(site="mangaone")
    policy = MangaOneSitePolicy()

    assert policy.available_quota(sources, datetime(2026, 9, 17, 9, 0, tzinfo=JST)) == 0
    assert policy.available_quota(sources, datetime(2026, 9, 17, 21, 0, tzinfo=JST)) == 4


def test_naive_now_and_unknown_policy_fail_safely(tmp_path: Path) -> None:
    service = CatalogService(tmp_path / "catalog.sqlite")
    add_source(service, item=ItemInput(item_title="A"), external_id="a")

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

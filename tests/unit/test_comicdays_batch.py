from datetime import datetime, timedelta
from pathlib import Path

from screenshot_crawler.batch import BatchPlanner
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.catalog.service import JST
from screenshot_crawler.site_policies import SitePolicyRegistry
from screenshot_crawler.site_policies.comicdays import ComicDaysSitePolicy

NOW = datetime(2026, 10, 4, 12, tzinfo=JST)


def _registry() -> SitePolicyRegistry:
    registry = SitePolicyRegistry()
    registry.register("comicdays", ComicDaysSitePolicy)
    return registry


def _episode(
    catalog: CatalogService,
    *,
    work,
    external_id: str,
    order: str,
    access_mode: str,
    access_granted_until: str | None = None,
):
    item = catalog.create_item(
        ItemInput(item_title=f"Episode {order}", order_key=order), work_id=work.id
    )
    source = catalog.create_source(
        SourceInput(
            site="comicdays",
            external_id=external_id,
            access_mode=access_mode,
            access_granted_until=access_granted_until,
        ),
        item_id=item.id,
    )
    catalog.create_source_target(
        SourceTargetInput(
            backend="web",
            locator=f"https://comic-days.com/episode/{external_id}",
        ),
        source_id=source.id,
    )
    return item, source


def test_comicdays_planner_keeps_one_quota_candidate_per_work_in_catalog_order(
    tmp_path: Path,
) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    first_work = catalog.create_work(
        WorkInput(work_key="comicdays:series:100", title="First")
    )
    second_work = catalog.create_work(
        WorkInput(work_key="comicdays:series:200", title="Second")
    )
    _episode(catalog, work=first_work, external_id="1003", order="03", access_mode="quota")
    _episode(catalog, work=first_work, external_id="1001", order="01", access_mode="quota")
    _episode(catalog, work=first_work, external_id="1002", order="02", access_mode="quota")
    _episode(catalog, work=second_work, external_id="2002", order="02", access_mode="quota")
    _episode(catalog, work=second_work, external_id="2001", order="01", access_mode="quota")

    plan = BatchPlanner(catalog, _registry()).plan(site="comicdays", now=NOW)

    assert [candidate.external_id for candidate in plan.candidates] == ["1001", "2001"]
    assert all(candidate.quota_scope == "work" for candidate in plan.candidates)
    assert all(candidate.quota_limit == 1 for candidate in plan.candidates)


def test_comicdays_planner_direct_and_skip_classifications(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="comicdays:series:300", title="States"))
    _episode(catalog, work=work, external_id="free", order="01", access_mode="free")
    _episode(
        catalog,
        work=work,
        external_id="active",
        order="02",
        access_mode="quota",
        access_granted_until=(NOW + timedelta(hours=1)).isoformat(),
    )
    _episode(catalog, work=work, external_id="paid", order="03", access_mode="paid")
    _episode(catalog, work=work, external_id="unknown", order="04", access_mode="unknown")

    plan = BatchPlanner(catalog, _registry()).plan(site="comicdays", now=NOW)

    assert [(candidate.external_id, candidate.access_strategy) for candidate in plan.candidates] == [
        ("free", "direct"),
        ("active", "direct"),
    ]
    assert {skipped.reason for skipped in plan.skipped} >= {"paid", "unknown"}

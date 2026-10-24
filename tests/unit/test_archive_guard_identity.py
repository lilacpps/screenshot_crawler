from pathlib import Path

from screenshot_crawler.batch.archive_guard import _run_matches_source
from screenshot_crawler.catalog import (
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.maintenance.source_identity import SourceIdentityMaintenance


def test_historical_run_snapshot_stays_owned_by_stable_source(tmp_path: Path) -> None:
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="ng-life", title="NG LIFE"))
    item = catalog.create_item(ItemInput(item_title="scene 1"), work_id=work.id)
    source = catalog.create_source(
        SourceInput(site="hanayume", external_id="old", discovery_key="ng-life"),
        item_id=item.id,
    )
    target = catalog.create_source_target(
        SourceTargetInput(backend="web", locator="https://hanayume.com/episodes/old"),
        source_id=source.id,
    )
    run = catalog.create_crawl_run(
        item_id=item.id, source_id=source.id, target_id=target.id, access_strategy="direct"
    )
    run = catalog.mark_crawl_run_succeeded(run.id, page_count=1)
    plan = SourceIdentityMaintenance(catalog).plan(
        site="hanayume", work_key="ng-life", old_external_id="old",
        new_external_id="new", new_locator="https://hanayume.com/episodes/new",
        reason="native identity proof",
    )
    SourceIdentityMaintenance(catalog).apply(plan)
    current = catalog.get_source(source.id)
    assert run.external_id_snapshot == "old"
    assert current.external_id == "new"
    assert _run_matches_source(run, item=item, source=current)

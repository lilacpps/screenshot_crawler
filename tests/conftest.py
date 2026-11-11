"""Shared synthetic inputs for Hanayume repair; no real-site content."""

import hashlib
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
import yaml

from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)


@pytest.fixture
def hanayume_repair_inputs(tmp_path):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="repair-test", title="架空作品"))
    native_work = "aaaaaaaaaaaaa"

    def add(number, label, *, available, status="pending", key="repair-test", item=None,
            native=native_work, parent=work):
        item = item or catalog.create_item(
            ItemInput(order_label=label, note=None if available else "手動note", status=status), work_id=parent.id)
        eid = f"{number:013x}"
        source = catalog.create_source(SourceInput(site="hanayume", external_id=f"{native}:{eid}",
            discovery_key=key, access_mode="free", available=available, display_position=number),
            item_id=item.id)
        target = catalog.create_source_target(SourceTargetInput(backend="web",
            locator=f"https://hanayume.com/episodes/{eid}"), source_id=source.id)
        return source, item, target

    old, old_item, old_target = add(1, "第1話", available=False, status="completed")
    new, new_item, new_target = add(101, "第1話", available=True)
    catalog.update_item_metadata(old_item.id, item_title="手動タイトル")
    archive = tmp_path / "old.zip"
    with ZipFile(archive, "w") as stream:
        stream.writestr("synthetic.txt", "synthetic fixture, no copyrighted material")

    def history(source, target):
        for _ in range(2):
            run = catalog.create_crawl_run(item_id=source.item_id, source_id=source.id,
                target_id=target.id, access_strategy="direct")
            catalog.mark_crawl_run_succeeded(run.id, page_count=1)
            catalog.create_artifact(ArtifactInput(kind="archive", format="zip",
                sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), byte_size=archive.stat().st_size,
                storage_backend="filesystem", locator=str(archive), state="present"),
                item_id=source.item_id, crawl_run_id=run.id)

    history(old, old_target)
    catalog.record_quota_access_with_resource_state(old.id, work_id=work.id, site="hanayume",
        resource="work_ticket", consumed_at="2026-11-01T10:00:00+09:00",
        access_granted_until="2026-11-02T10:00:00+09:00")
    watchlist = tmp_path / "watchlist.yaml"
    target = {"key": "repair-test", "work_key": "repair-test", "site": "hanayume",
              "url": f"https://hanayume.com/episodes/{101:013x}", "label": "架空作品"}
    watchlist.write_text(yaml.safe_dump({"targets": [target]}, allow_unicode=True), "utf-8")
    return SimpleNamespace(catalog=catalog, work=work, old=old, old_item=old_item, new=new,
        new_item=new_item, new_target=new_target, archive=archive, watchlist=watchlist,
        add=add, history=history, native_work=native_work, target=target)

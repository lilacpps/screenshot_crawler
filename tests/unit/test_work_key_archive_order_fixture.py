"""Validate synthetic, isolated data used by the work-key ordering phases."""

from __future__ import annotations

from pathlib import Path

import yaml

from screenshot_crawler.catalog import (
    ArtifactInput,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)
from screenshot_crawler.watchlist import WatchlistService

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "work_key_archive_order"


def test_synthetic_work_key_fixture_is_isolated_and_preserves_current_catalog_contract(
    tmp_path: Path,
) -> None:
    expanded_path = FIXTURE_DIR / "expanded.yaml"
    reduced_path = FIXTURE_DIR / "reduced.yaml"
    expanded = yaml.safe_load(expanded_path.read_text(encoding="utf-8"))
    reduced = yaml.safe_load(reduced_path.read_text(encoding="utf-8"))

    catalog_path = tmp_path / "catalog.sqlite"
    output_dir = tmp_path / "output" / "Books"
    expanded_copy = tmp_path / "watchlist-expanded.yaml"
    reduced_copy = tmp_path / "watchlist-reduced.yaml"
    expanded_copy.write_text(expanded_path.read_text(encoding="utf-8"), encoding="utf-8")
    reduced_copy.write_text(reduced_path.read_text(encoding="utf-8"), encoding="utf-8")

    expanded_targets = WatchlistService(expanded_copy).list_targets()
    reduced_targets = WatchlistService(reduced_copy).list_targets()
    assert [target.key for target in expanded_targets] == [
        "archive-demo-zeblack",
        "archive-demo-bookwalker",
        "archive-demo-magapoke",
    ]
    assert expanded_targets[2].enabled is False
    assert expanded_targets[0].discovery_scope is not None
    assert expanded_targets[0].discovery_scope.from_url.endswith("chapter/140")
    assert reduced_targets[0].discovery_scope is not None
    assert reduced_targets[0].discovery_scope.from_url.endswith("chapter/100")
    assert expanded["targets"][0]["archive_order"] == 10
    assert reduced["targets"][0]["archive_order"] == 10

    catalog = CatalogService(catalog_path)
    catalog.initialize()
    work = catalog.create_work(
        WorkInput(work_key="archive-demo", title="Synthetic series", genre="漫画")
    )
    sources_by_key = {target.key: [] for target in expanded_targets}
    completed_graph = None

    for site, config in expanded["catalog_fixture"].items():
        first, last = config["positions"]
        statuses = {int(position): status for position, status in config.get("item_statuses", {}).items()}
        paid_positions = set(config.get("paid_positions", []))
        unavailable_positions = set(config.get("unavailable_positions", []))
        for position in range(first, last + 1):
            label = f"第{position}話" if site != "bookwalker" else f"第{position + 13}巻"
            item = catalog.create_item(
                ItemInput(
                    item_title=label,
                    order_key=f"{position:04d}",
                    order_label=label,
                    status=statuses.get(position, "pending"),
                ),
                work_id=work.id,
            )
            access_mode = (
                "paid" if position in paid_positions else config.get("access_mode", "free")
            )
            source = catalog.create_source(
                SourceInput(
                    site=site,
                    external_id=(
                        f"chapter-{position}" if site != "bookwalker" else f"volume-{position + 13}"
                    ),
                    discovery_key=config["discovery_key"],
                    access_mode=access_mode,
                    available=(
                        False if site == "magapoke" else position not in unavailable_positions
                    ),
                    display_position=position,
                ),
                item_id=item.id,
            )
            target = catalog.create_source_target(
                SourceTargetInput(
                    backend="web",
                    locator=f"https://example.invalid/{site}/{source.external_id}",
                ),
                source_id=source.id,
            )
            sources_by_key[config["discovery_key"]].append(source)
            if site == "zeblack" and position == 10:
                completed_graph = (item, source, target)

    assert catalog_path.is_file()
    assert len(sources_by_key["archive-demo-zeblack"]) == 140
    assert len(sources_by_key["archive-demo-bookwalker"]) == 2
    assert len(sources_by_key["archive-demo-magapoke"]) == 2
    assert sources_by_key["archive-demo-zeblack"][74].access_mode == "paid"
    assert sources_by_key["archive-demo-zeblack"][119].access_mode == "paid"
    assert sources_by_key["archive-demo-magapoke"][0].available is False
    assert catalog.list_items(work_id=work.id)[9].status == "completed"
    assert catalog.list_items(work_id=work.id)[10].status == "skipped"
    assert catalog.list_items(work_id=work.id)[11].status == "external"

    assert completed_graph is not None
    completed_item, completed_source, completed_target = completed_graph
    archive_path = output_dir / "archive-demo" / "010-synthetic.zip"
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(b"synthetic zip payload")
    run = catalog.create_crawl_run(
        item_id=completed_item.id,
        source_id=completed_source.id,
        target_id=completed_target.id,
        access_strategy="direct",
        started_at="2026-10-01T00:00:00+09:00",
    )
    catalog.mark_crawl_run_succeeded(run.id, page_count=1)
    catalog.create_artifact(
        ArtifactInput(
            kind="archive",
            format="zip",
            sha256="A" * 64,
            byte_size=archive_path.stat().st_size,
            storage_backend="filesystem",
            locator=archive_path.as_posix(),
            state="present",
        ),
        item_id=completed_item.id,
        crawl_run_id=run.id,
    )
    assert archive_path.is_file()
    assert archive_path.is_relative_to(tmp_path)

    identity_conflict = expanded["same_site_identity_conflict"]
    assert identity_conflict["site"] == "zeblack"
    assert identity_conflict["existing_key"] != identity_conflict["attempted_key"]
    assert identity_conflict["expected"] == "reject_without_reparenting"


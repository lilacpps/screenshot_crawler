"""One consistent SQLite read-only snapshot; no CatalogService construction."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from pathlib import Path

from screenshot_crawler.catalog.models import (
    AcquisitionScopeSync,
    Artifact,
    CrawlRun,
    DiscoveryInventoryEvidence,
    DiscoveryInventoryPosition,
    Item,
    QuotaResourceState,
    Source,
    SourceTarget,
    Work,
)
from screenshot_crawler.catalog.schema import SchemaError, validate_existing_schema


class InventoryLoadError(RuntimeError):
    """An existing input cannot be safely read; never create a replacement."""


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    works: tuple[Work, ...]
    items: tuple[Item, ...]
    sources: tuple[Source, ...]
    targets: tuple[SourceTarget, ...]
    syncs: tuple[AcquisitionScopeSync, ...]
    evidence: tuple[DiscoveryInventoryEvidence, ...]
    resource_states: tuple[QuotaResourceState, ...]
    latest_runs: tuple[CrawlRun, ...]
    artifacts: tuple[Artifact, ...]


class CatalogInventoryReader:
    """Reads only existing v7 files, including history in the same transaction."""

    def read(self, path: str | Path) -> CatalogSnapshot:
        path = Path(path).resolve()
        if not path.is_file():
            raise InventoryLoadError(f"Catalogが見つかりません（新規作成しません）: {path}")
        try:
            # SQLite mode=ro still updates WAL shared-memory read marks. Reject
            # that journal before opening SQLite; immutable=1 would silently
            # ignore committed WAL pages and is not a safe alternative.
            with path.open("rb") as stream:
                header = stream.read(20)
            if header.startswith(b"SQLite format 3\x00") and 2 in header[18:20]:
                raise InventoryLoadError(
                    "WAL形式のCatalogはP1では読み込めません。read-only接続でも"
                    "SQLite共有メモリが更新されるためです。運用側で明示的に作成した"
                    "通常journal形式の一貫したバックアップを指定してください。"
                    "GUIはjournal設定を変更しません。"
                )
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
            try:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
                validate_existing_schema(connection)
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise InventoryLoadError("Catalogの参照整合性が不正です")

                def rows(table, model, *, sql=None):
                    names = {field.name for field in fields(model)}
                    result = []
                    for row in connection.execute(sql or f"SELECT * FROM {table} ORDER BY id"):
                        value = {key: row[key] for key in names}
                        for key in ("available", "acquisition_enabled", "enabled"):
                            if key in value:
                                value[key] = bool(value[key])
                        result.append(model(**value))
                    return tuple(result)

                works = rows("works", Work)
                work_keys = {work.id: work.work_key for work in works}
                syncs = []
                for row in connection.execute("SELECT * FROM acquisition_scope_sync"):
                    value = dict(row)
                    value["work_key"] = work_keys[value.pop("work_id")]
                    syncs.append(AcquisitionScopeSync(**value))
                positions = {}
                for row in connection.execute(
                    "SELECT * FROM discovery_inventory_positions ORDER BY display_position"
                ):
                    positions.setdefault(row["discovery_key"], []).append(
                        DiscoveryInventoryPosition(
                            row["external_id"], row["display_position"], bool(row["in_scope"])
                        )
                    )
                evidence = []
                for row in connection.execute("SELECT * FROM discovery_inventory_evidence"):
                    value = dict(row)
                    value["work_key"] = work_keys[value.pop("work_id")]
                    value["positions"] = tuple(positions.get(value["discovery_key"], ()))
                    evidence.append(DiscoveryInventoryEvidence(**value))
                return CatalogSnapshot(
                    works=works,
                    items=rows("items", Item),
                    sources=rows("sources", Source),
                    targets=rows("source_targets", SourceTarget),
                    syncs=tuple(syncs),
                    evidence=tuple(evidence),
                    resource_states=rows("quota_resource_states", QuotaResourceState),
                    latest_runs=rows("crawl_runs", CrawlRun, sql=(
                        "SELECT * FROM crawl_runs WHERE id IN "
                        "(SELECT MAX(id) FROM crawl_runs GROUP BY item_id)"
                    )),
                    artifacts=rows("artifacts", Artifact, sql=(
                        "SELECT * FROM artifacts WHERE id IN (SELECT MAX(id) FROM artifacts "
                        "GROUP BY item_id, kind, format, storage_backend)"
                    )),
                )
            finally:
                connection.close()
        except (sqlite3.Error, SchemaError, OSError, KeyError, TypeError, ValueError) as exc:
            raise InventoryLoadError(
                f"Catalogを読み込めません。既存v7・権限・破損を確認してください: {exc}"
            ) from exc

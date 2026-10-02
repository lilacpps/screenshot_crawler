"""Comic DAYS C3 live Discovery -> Catalog -> Batch -> packaging audit.

This is an operator-run verification harness.  It deliberately supplies every
path explicitly and refuses to fall back to the normal Catalog or watchlist.
The browser is the shared Crawler Chrome connected over CDP.
"""

from __future__ import annotations

import asyncio
import binascii
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from screenshot_crawler.batch.executor import BatchExecutor
from screenshot_crawler.batch.planner import BatchPlanner
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.cli import (
    _batch_adapter_registry,
    _batch_policy_registry,
    _discovery_registry,
)
from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.core.runner import CrawlerRunner, RunResult
from screenshot_crawler.discovery.service import DiscoveryService
from screenshot_crawler.runtime_settings import SiteRuntimeSettings
from screenshot_crawler.watchlist.service import WatchlistService

ROOT = Path(__file__).resolve().parents[1]
DB = (ROOT / "catalog_comicdays.sqlite").resolve()
TARGET = "https://comic-days.com/episode/2550689798754939004"
WORK_KEY = "comicdays:series:2550689798737278979"
TARGET_EXTERNAL_ID = "2550689798754939004"
# Deliberately distinct from the page title to verify Catalog metadata
# precedence; the verified page title remains in manifest content_context.
WORK_TITLE = "Comic DAYS target free episode"
OUTPUT_ROOT = (ROOT / "output/comicdays_c3_batch11").resolve()
LIBRARY = (ROOT / "output/comicdays_c3_library11").resolve()
EVIDENCE = (ROOT / "output/comicdays_c3_evidence11").resolve()
WATCHLIST = (ROOT / "output/comicdays_c3_e2e11/watchlist.yaml").resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_summary(result: RunResult) -> dict[str, Any]:
    return {
        "stop_state": result.stop_state.value,
        "stop_reason": result.stop_reason,
        "page_count": len(result.pages),
        "pages": [
            {
                "sequence": page.sequence,
                "file": page.file.as_posix(),
                "page_id": page.identity.page_id,
                "page_number": page.identity.page_number,
                "source_id": page.identity.source_id,
                "width": page.width,
                "height": page.height,
                "native": page.metadata.get("native"),
                "parts": page.metadata.get("parts", 1),
            }
            for page in result.pages
        ],
    }


class EvidenceRunner(CrawlerRunner):
    """Copy pre-package evidence while preserving the normal Runner path."""

    def __init__(self, config, evidence: Path) -> None:
        super().__init__(config)
        self._evidence = evidence

    async def run(self, page, adapter):  # type: ignore[no-untyped-def]
        result = await super().run(page, adapter)
        self._evidence.mkdir(parents=True, exist_ok=True)
        output = self.config.output_dir
        for name in ("manifest.json", "progress.json"):
            source = output / name
            if source.is_file():
                shutil.copy2(source, self._evidence / f"before_package_{name}")
        for sequence in (1, 16, 32):
            source = output / f"page-{sequence:04d}.png"
            if source.is_file():
                shutil.copy2(source, self._evidence / source.name)
        (self._evidence / "run_result.json").write_text(
            json.dumps(_run_summary(result), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result


def _audit_archive(manifest: dict[str, Any], archive: Path) -> dict[str, Any]:
    declared = {entry["file"]: entry for entry in manifest.get("pages", [])}
    entries: list[dict[str, Any]] = []
    bad_crc: list[str] = []
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            payload = handle.read(info.filename)
            if info.CRC != binascii.crc32(payload):
                bad_crc.append(info.filename)
            from io import BytesIO

            with Image.open(BytesIO(payload)) as image:
                entries.append(
                    {
                        "file": info.filename,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "width": image.width,
                        "height": image.height,
                    }
                )
    mismatches = []
    for entry in entries:
        expected = declared.get(entry["file"])
        if expected is None or entry["sha256"] != expected.get("fingerprint") or (
            entry["width"], entry["height"]
        ) != (expected.get("width"), expected.get("height")):
            mismatches.append(entry["file"])
    return {
        "entry_count": len(entries),
        "bad_crc": bad_crc,
        "manifest_mismatches": mismatches,
        "entries": entries,
        "archive_sha256": _sha256(archive),
        "archive_bytes": archive.stat().st_size,
    }


def _assert_isolated() -> None:
    if DB.name != "catalog_comicdays.sqlite" or DB == (ROOT / "catalog.sqlite").resolve():
        raise RuntimeError(f"unsafe Catalog path: {DB}")
    if DB.exists() or Path(f"{DB}-wal").exists() or Path(f"{DB}-shm").exists():
        raise RuntimeError(f"experiment Catalog must be fresh: {DB}")
    if WATCHLIST == (ROOT / "watchlist.yaml").resolve():
        raise RuntimeError("unsafe watchlist path")
    for path in (OUTPUT_ROOT, LIBRARY, EVIDENCE, WATCHLIST.parent):
        if path.exists():
            raise FileExistsError(f"C3 path already exists: {path}")


async def run() -> None:
    _assert_isolated()
    WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
    WatchlistService(WATCHLIST).add(
        key="comicdays-target",
        work_key=WORK_KEY,
        site="comicdays",
        url=TARGET,
        label=WORK_TITLE,
    )
    target = WatchlistService(WATCHLIST).get("comicdays-target")

    catalog = CatalogService(DB)
    catalog.initialize()
    discovery_registry = _discovery_registry()
    policies = _batch_policy_registry()
    adapter_registry = _batch_adapter_registry({})
    report: dict[str, Any] = {
        "catalog": str(DB),
        "watchlist": str(WATCHLIST),
        "target": TARGET,
        "work_key": WORK_KEY,
        "registry_sites": {
            "discovery": discovery_registry.sites(),
            "policy": policies.sites(),
            "adapter": adapter_registry.sites(),
        },
    }

    session = await BrowserSession.connect(resolve_cdp_endpoint())
    try:
        discovery_page = await session.new_page()
        try:
            discovery_result = await DiscoveryService(catalog, discovery_registry).discover(
                discovery_page, target, "full"
            )
            report["discovery"] = {
                "observed": discovery_result.observed_count,
                "new": discovery_result.new_count,
                "complete": discovery_result.complete,
                "stopped_reason": discovery_result.stopped_reason,
            }
        finally:
            await session.close_page(discovery_page)

        sources = catalog.list_sources(site="comicdays", discovery_key=target.key)
        modes: dict[str, int] = {}
        for source in sources:
            modes[source.access_mode] = modes.get(source.access_mode, 0) + 1
        target_source = catalog.get_source_by_external_id("comicdays", TARGET_EXTERNAL_ID)
        work = catalog.get_work(catalog.get_item(target_source.item_id).work_id)
        if len(sources) != 79 or modes != {"free": 4, "unknown": 75}:
            raise RuntimeError(f"unexpected Discovery Catalog shape: {len(sources)} / {modes}")
        if target_source.access_mode != "free" or target_source.discovery_key != target.key:
            raise RuntimeError("target source was not positively free in the experiment Catalog")
        report["catalog_snapshot"] = {
            "work_id": work.id,
            "work_key": work.work_key,
            "work_title": work.title,
            "source_count": len(sources),
            "access_modes": modes,
            "target_source_id": target_source.id,
            "target_external_id": target_source.external_id,
            "target_url": catalog.list_source_targets(source_id=target_source.id)[0].locator,
            "quota_started_at": target_source.quota_started_at,
            "access_granted_until": target_source.access_granted_until,
        }

        plan = BatchPlanner(catalog, policies).plan(site="comicdays")
        candidate = next(
            (value for value in plan.candidates if value.external_id == TARGET_EXTERNAL_ID),
            None,
        )
        if candidate is None:
            raise RuntimeError("target was absent from the normal Batch plan")
        if candidate.access_strategy != "direct" or candidate.consumes_quota or candidate.quota_resource:
            raise RuntimeError(f"target Batch candidate was not free direct: {candidate}")
        report["batch_plan"] = {
            "candidate_count": len(plan.candidates),
            "skipped_count": len(plan.skipped),
            "selected": {
                "item_id": candidate.item_id,
                "source_id": candidate.source_id,
                "target_id": candidate.target_id,
                "external_id": candidate.external_id,
                "access_strategy": candidate.access_strategy,
                "access_mode": candidate.access_mode,
                "consumes_quota": candidate.consumes_quota,
                "quota_resource": candidate.quota_resource,
                "locator": candidate.locator,
            },
        }

        EVIDENCE.mkdir(parents=True, exist_ok=True)

        def runner_factory(config):  # type: ignore[no-untyped-def]
            return EvidenceRunner(config, EVIDENCE)

        executor = BatchExecutor(
            catalog,
            policies,
            adapter_registry,
            runner_factory=runner_factory,
            runtime_settings=SiteRuntimeSettings(page_turn_delay_ms=0, inter_candidate_delay_ms=0),
        )
        batch_page = await session.new_page()
        try:
            result = await executor.execute_candidate(
                batch_page,
                candidate,
                output_root=OUTPUT_ROOT,
                library_dir=LIBRARY,
                max_pages=40,
                max_same_content=3,
            )
        finally:
            await session.close_page(batch_page)

        run = catalog.get_crawl_run(result.crawl_run_id)
        artifact = catalog.get_artifact(result.artifact_id)
        item = catalog.get_item(candidate.item_id)
        archive = result.archive_path
        manifest = json.loads((EVIDENCE / "before_package_manifest.json").read_text(encoding="utf-8"))
        audit = _audit_archive(manifest, archive)
        if run.status != "succeeded" or run.stop_reason != "end" or item.status != "completed":
            raise RuntimeError(f"unexpected persisted success state: {run} / {item}")
        if artifact.state != "present" or artifact.sha256 != audit["archive_sha256"]:
            raise RuntimeError(f"unexpected artifact state: {artifact}")
        run_summary = json.loads((EVIDENCE / "run_result.json").read_text(encoding="utf-8"))
        pages = run_summary["pages"]
        if run_summary["stop_state"] != "end" or run_summary["page_count"] != 32:
            raise RuntimeError("Batch Runner did not complete the expected 32-page END run")
        if any(page["width"] != 1125 or page["height"] != 1600 or page["native"] is not True for page in pages):
            raise RuntimeError("Batch output violated native 1125x1600 contract")
        area_ids: list[int] = []
        for page in pages:
            for raw in str(page["page_id"] or "").split(","):
                value = int(raw)
                if value not in area_ids:
                    area_ids.append(value)
        if area_ids != list(range(1, 33)):
            raise RuntimeError(f"Batch output area order mismatch: {area_ids}")
        if audit["entry_count"] != 32 or audit["bad_crc"] or audit["manifest_mismatches"]:
            raise RuntimeError(f"archive audit failed: {audit}")

        remaining_files = [
            str(path)
            for path in OUTPUT_ROOT.rglob("*")
            if path.is_file()
        ] if OUTPUT_ROOT.exists() else []
        report["batch_execution"] = {
            "result": {
                "crawl_run_id": result.crawl_run_id,
                "artifact_id": result.artifact_id,
                "archive": str(archive),
                "page_count": run_summary["page_count"],
                "stop_state": run_summary["stop_state"],
                "stop_reason": run_summary["stop_reason"],
                "area_ids": area_ids,
            },
            "crawl_run": run.__dict__ if hasattr(run, "__dict__") else {
                "id": run.id, "status": run.status, "page_count": run.page_count,
                "stop_reason": run.stop_reason, "access_strategy": run.access_strategy,
                "external_id_snapshot": run.external_id_snapshot,
            },
            "item": {"id": item.id, "status": item.status, "completed_at": item.completed_at},
            "artifact": {
                "id": artifact.id, "state": artifact.state, "sha256": artifact.sha256,
                "byte_size": artifact.byte_size, "locator": artifact.locator,
            },
            "archive_audit": audit,
            "metadata_precedence": {
                "catalog_work_title": work.title,
                "crawl_context_title": manifest.get("content_context", {}).get("title"),
            },
            "output_files_remaining_after_package": remaining_files,
            "output_removed_after_package": not remaining_files,
        }
        report["status"] = "ok"
    finally:
        await session.close()
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "c3_e2e_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    asyncio.run(run())

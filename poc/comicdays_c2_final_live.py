"""Final current-code Comic DAYS live crawl and packaging audit.

The harness uses only the shared Crawler Chrome/CDP session.  All retained
evidence is redacted to manifest identities, dimensions, fingerprints, and
native-capture flags; page PNGs remain under ignored output paths.
"""

from __future__ import annotations

import argparse
import asyncio
import binascii
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.runner import CrawlerRunner, RunResult
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter

TARGET = "https://comic-days.com/episode/2550689798754939004"
OUTPUT = Path("output/comicdays_c2_final_live11")
LIBRARY = Path("output/comicdays_c2_final_library11")
EVIDENCE = Path("output/comicdays_c2_final_evidence11")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def result_summary(result: RunResult) -> dict[str, Any]:
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
                "fingerprint": page.metadata.get("fingerprint"),
                "width": page.width,
                "height": page.height,
                "native": page.metadata.get("native"),
                "parts": page.metadata.get("parts", 1),
            }
            for page in result.pages
        ],
    }


def audit_manifest_and_zip(manifest: dict[str, Any], archive_path: Path) -> dict[str, Any]:
    pages = manifest.get("pages", [])
    by_file = {page["file"]: page for page in pages}
    with zipfile.ZipFile(archive_path) as archive:
        bad_crc = [info.filename for info in archive.infolist() if info.CRC != binascii.crc32(archive.read(info.filename))]
        names = archive.namelist()
        entries = []
        for name in names:
            data = archive.read(name)
            from io import BytesIO

            with Image.open(BytesIO(data)) as image:
                entries.append({
                    "file": name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "width": image.width,
                    "height": image.height,
                })
    mismatches = []
    for entry in entries:
        declared = by_file.get(entry["file"])
        if declared is None or entry["sha256"] != declared.get("fingerprint") or [entry["width"], entry["height"]] != [declared.get("width"), declared.get("height")]:
            mismatches.append(entry["file"])
    return {
        "zip_entry_count": len(entries),
        "zip_names": names,
        "bad_crc": bad_crc,
        "manifest_zip_mismatches": mismatches,
        "zip_dimensions": entries,
    }


async def run(endpoint: str | None) -> None:
    for path in (OUTPUT, LIBRARY, EVIDENCE):
        if path.exists():
            raise FileExistsError(f"final live path already exists: {path}")
    EVIDENCE.mkdir(parents=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=endpoint))
    page = await session.new_page()
    adapter = ComicDaysAdapter()
    result: RunResult | None = None
    report: dict[str, Any] = {"target": TARGET, "output": str(OUTPUT), "library": str(LIBRARY)}
    try:
        config = RunConfig(
            site="comicdays",
            source_url=TARGET,
            output_dir=OUTPUT,
            diagnostics_dir=OUTPUT / "diagnostics",
            max_pages=40,
            max_same_content=3,
            navigation_timeout_ms=30_000,
            page_change_timeout_ms=15_000,
            adapter_timeout_grace_ms=2_000,
            page_turn_delay_ms=0,
            access_strategy="direct",
        )
        result = await CrawlerRunner(config).run(page, adapter)
        report["run_result"] = result_summary(result)
        if result.stop_state is not PageState.END or len(result.pages) != 32:
            raise RuntimeError("final live crawl did not produce exactly 32 pages with END")
        ordered_area_ids: list[int] = []
        for captured_page in result.pages:
            for value in str(captured_page.identity.page_id or "").split(","):
                area_id = int(value)
                if area_id not in ordered_area_ids:
                    ordered_area_ids.append(area_id)
        if ordered_area_ids != list(range(1, 33)):
            raise RuntimeError("final live spread identities do not cover ordered area IDs 1..32")
        report["ordered_area_ids"] = ordered_area_ids
        if any(page.width != 1125 or page.height != 1600 for page in result.pages):
            raise RuntimeError("final live page dimensions are not 1125x1600")
        if any(page.metadata.get("native") is not True for page in result.pages):
            raise RuntimeError("final live used a non-native capture path")
        if result.pages[0].identity.page_id != "1" or result.pages[-1].identity.page_id != "32":
            raise RuntimeError("final live first/last identity mismatch")

        manifest_path = OUTPUT / "manifest.json"
        progress_path = OUTPUT / "progress.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        report["manifest_before_package"] = manifest
        report["progress_before_package"] = progress
        report["manifest_sha256_before_package"] = sha256(manifest_path)
        report["progress_sha256_before_package"] = sha256(progress_path)
        for sequence in (1, 16, 32):
            source = OUTPUT / f"page-{sequence:04d}.png"
            shutil.copy2(source, EVIDENCE / source.name)
        (EVIDENCE / "manifest_before_package.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (EVIDENCE / "progress_before_package.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        package = package_crawl_output(OUTPUT, adapter.get_output_metadata(), library_dir=LIBRARY)
        report["package"] = {"archive_path": str(package.archive_path), "status_path": str(package.status_path)}
        report["archive_audit"] = audit_manifest_and_zip(manifest, package.archive_path)
        if report["archive_audit"]["zip_entry_count"] != 32 or report["archive_audit"]["bad_crc"] or report["archive_audit"]["manifest_zip_mismatches"]:
            raise RuntimeError("packaged ZIP failed manifest/CRC/dimension audit")
        report["status"] = "ok"
    except BaseException as exc:
        report["status"] = "error"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        raise
    finally:
        (EVIDENCE / "final_live_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        await session.close_page(page)
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp-endpoint")
    args = parser.parse_args()
    asyncio.run(run(args.cdp_endpoint))


if __name__ == "__main__":
    main()

"""Final current-code Comic DAYS live crawl and packaging audit.

The harness uses only the shared Crawler Chrome/CDP session. All retained
evidence is redacted to manifest identities, dimensions, fingerprints, capture
modes, and native-capture flags; page files remain under ignored output paths.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
from screenshot_crawler.core.models import RunConfig
from screenshot_crawler.core.packaging import package_crawl_output
from screenshot_crawler.core.runner import CrawlerRunner, RunResult
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.comicdays.adapter import ComicDaysAdapter
from screenshot_crawler.site_adapters.comicdays.native_capture import (
    _jpeg_header,
    reconstruct_jpeg,
    source_id_for_row,
    strict_canvas_sequence,
)

TARGET = "https://comic-days.com/episode/2550689798754939004"
OUTPUT = Path("output/comicdays_c2_final_live11")
LIBRARY = Path("output/comicdays_c2_final_library11")
EVIDENCE = Path("output/comicdays_c2_final_evidence11")


INDEPENDENT_CENSUS_JS = r"""
() => {
  const visible = element => {
    if (!element) return false;
    const own = getComputedStyle(element);
    if (own.display === 'none' || own.visibility === 'hidden' || own.opacity === '0') return false;
    const rect = element.getBoundingClientRect();
    if (!(rect.width > 0 && rect.height > 0)) return false;
    let left = Math.max(rect.left, 0), right = Math.min(rect.right, innerWidth);
    let top = Math.max(rect.top, 0), bottom = Math.min(rect.bottom, innerHeight);
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
      if (['hidden', 'clip', 'scroll', 'auto'].includes(style.overflowX)) {
        const clip = parent.getBoundingClientRect(); left = Math.max(left, clip.left); right = Math.min(right, clip.right);
      }
      if (['hidden', 'clip', 'scroll', 'auto'].includes(style.overflowY)) {
        const clip = parent.getBoundingClientRect(); top = Math.max(top, clip.top); bottom = Math.min(bottom, clip.bottom);
      }
    }
    const area = Math.max(0, right - left) * Math.max(0, bottom - top);
    return area / (rect.width * rect.height) >= 0.5;
  };
  const root = document.querySelector('section.viewer.js-viewer .image-container.js-viewer-content');
  const areas = root ? [...root.querySelectorAll('.page-area.js-page-area')] : [];
  const isBack = area => [...area.children].some(page => page.classList.contains('page') &&
    page.classList.contains('js-page') && page.classList.contains('back-link-page') &&
    page.classList.contains('js-link-page') && page.classList.contains('js-back-link-page'));
  const isAd = area => [...area.children].some(page => page.classList.contains('page') &&
    page.classList.contains('js-page') && page.classList.contains('js-page-ad'));
  const body = areas.map((area, areaIndex) => ({area, areaIndex})).filter(({area}) =>
    area.id !== 'viewer-colophon' && !isBack(area) && !isAd(area) &&
    area.querySelectorAll('canvas.page-image.js-page-image').length > 0);
  const describe = ({area, areaIndex}) => ({
    areaIndex,
    id: area.id || null,
    dataIndex: area.getAttribute('data-area-index') || area.getAttribute('data-page-index'),
    visible: visible(area),
    canvases: [...area.querySelectorAll('canvas.page-image.js-page-image')].map((canvas, canvasIndex) => {
      const rect = canvas.getBoundingClientRect();
      return {canvasIndex, visible: visible(canvas), x: rect.x, y: rect.y, width: rect.width,
        height: rect.height, canvasWidth: canvas.width, canvasHeight: canvas.height};
    }),
  });
  return {
    sliderNow: Number(document.querySelector('.js-viewer-slider-pagenum-now')?.textContent?.trim()),
    sliderLast: Number(document.querySelector('.js-viewer-slider-pagenum-last')?.textContent?.trim()),
    viewerCount: document.querySelectorAll('section.viewer.js-viewer').length,
    body: body.map(describe),
    visibleBody: body.filter(({area}) => visible(area)).map(describe),
  };
}
"""


class AuditedComicDaysAdapter(ComicDaysAdapter):
    """Record an independent DOM census beside the production hook results."""

    def __init__(self) -> None:
        super().__init__()
        self.position_audit: list[dict[str, Any]] = []

    async def get_content_identity(self, page):
        active = await self._active(page)
        census = await page.evaluate(INDEPENDENT_CENSUS_JS)
        identity = await super().get_content_identity(page)
        self.position_audit.append({
            "sliderNow": active.get("sliderNow"),
            "sliderLast": active.get("sliderLast"),
            "independent": census,
            "active": active,
            "identity": {
                "page_id": identity.page_id,
                "page_number": identity.page_number,
                "source_id": identity.source_id,
                "fingerprint": identity.fingerprint,
            },
            "capture_count": None,
            "capture_page_ids": [],
        })
        return identity

    async def capture_page(self, page):
        source_proof: list[dict[str, Any]] = []
        state = await self._active(page)
        rows = state.get("rows", [])
        plans = [strict_canvas_sequence(row) for row in rows]
        ids = [source_id_for_row(row) for row in rows]
        if rows and all(plan is not None for plan in plans) and all(item is not None for item in ids):
            try:
                payload = await page.evaluate(
                    "ids => window.__comicDaysProductionCapture.snapshot(ids)", ids
                )
                by_id = {
                    item.get("id"): item for item in payload if isinstance(item, dict)
                } if isinstance(payload, list) else {}
                for row, plan in zip(rows, plans, strict=True):
                    item = by_id.get(source_id_for_row(row))
                    raw = base64.b64decode(item["bytes"], validate=True) if isinstance(item, dict) else b""
                    header = _jpeg_header(raw)
                    sof = header["sof"] if header else None
                    generated = reconstruct_jpeg(raw, plan) if header and plan else None
                    source_proof.append({
                        "areaIndex": row.get("areaIndex"),
                        "source_id": source_id_for_row(row),
                        "source_url": row.get("base", {}).get("sourceUrl") if isinstance(row.get("base"), dict) else None,
                        "generation": row.get("base", {}).get("sequence") if isinstance(row.get("base"), dict) else None,
                        "source_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
                        "sof_marker": sof.get("marker") if sof else None,
                        "precision": sof.get("precision") if sof else None,
                        "dimensions": [sof["width"], sof["height"]] if sof else None,
                        "components": [
                            {"id": component["id"], "h": component["h"], "v": component["v"], "qt": component["qt"]}
                            for component in sof["components"]
                        ] if sof else [],
                        "mcu_dimensions": [
                            8 * max(component["h"] for component in sof["components"]),
                            8 * max(component["v"] for component in sof["components"]),
                        ] if sof else None,
                        "tile_dct_blocks": [35, 50],
                        "untiled_right_edge": int(sof["width"] - 1120) if sof else None,
                        "coefficient_validation": generated is not None,
                        "output_sha256": hashlib.sha256(generated.data).hexdigest() if generated else None,
                    })
            except Exception:  # noqa: BLE001 - audit data must not alter crawl behavior
                source_proof = []
        captures = await super().capture_page(page)
        if self.position_audit:
            current = self.position_audit[-1]
            current["capture_count"] = len(captures or ())
            current["capture_debug"] = dict(self._capture_debug)
            current["source_proof"] = source_proof
            current["capture_page_ids"] = [
                {"width": capture.width, "height": capture.height, "extension": capture.file_extension}
                for capture in (captures or ())
            ]
        return captures


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


async def run(
    endpoint: str | None,
    *,
    target: str = TARGET,
    output: Path = OUTPUT,
    library: Path = LIBRARY,
    evidence: Path = EVIDENCE,
    expected_body: int = 32,
) -> None:
    for path in (output, library, evidence):
        if path.exists():
            raise FileExistsError(f"final live path already exists: {path}")
    evidence.mkdir(parents=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=endpoint))
    page = await session.new_page()
    adapter = AuditedComicDaysAdapter()
    result: RunResult | None = None
    report: dict[str, Any] = {"target": target, "output": str(output), "library": str(library)}
    try:
        config = RunConfig(
            site="comicdays",
            source_url=target,
            output_dir=output,
            diagnostics_dir=output / "diagnostics",
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
        if result.stop_state is not PageState.END or len(result.pages) != expected_body:
            raise RuntimeError(f"live crawl did not produce exactly {expected_body} pages with END")
        ordered_area_ids: list[int] = []
        saved_part_area_ids: list[int] = []
        for captured_page in result.pages:
            values = [int(value) for value in str(captured_page.identity.page_id or "").split(",") if value]
            ordered_area_ids.extend(values)
            part = captured_page.metadata.get("part")
            if isinstance(part, int) and 1 <= part <= len(values):
                saved_part_area_ids.append(values[part - 1])
            elif len(values) == 1:
                saved_part_area_ids.append(values[0])
            else:
                raise RuntimeError(f"multi-part page lacks a valid manifest part index: {captured_page.identity.page_id!r}")
        if saved_part_area_ids != list(range(1, expected_body + 1)):
            raise RuntimeError(f"saved manifest part order is not 1..{expected_body}: {saved_part_area_ids}")
        report["ordered_area_ids"] = ordered_area_ids
        report["saved_part_area_ids"] = saved_part_area_ids
        report["identity_area_id_duplicates"] = sum(
            count - 1 for count in Counter(ordered_area_ids).values() if count > 1
        )
        report["position_audit"] = adapter.position_audit
        captured_positions = [position for position in adapter.position_audit if position.get("capture_count") is not None]
        if sum(int(position.get("capture_count") or 0) for position in captured_positions) != len(result.pages):
            raise RuntimeError("position audit capture counts do not match saved pages")
        for position in captured_positions:
            independent_visible = [item["areaIndex"] for item in position["independent"].get("visibleBody", [])]
            active_expected = position["active"].get("expectedAreaIndices", [])
            active_rows = [row.get("areaIndex") for row in position["active"].get("rows", [])]
            if independent_visible != active_expected or sorted(active_rows) != sorted(active_expected):
                raise RuntimeError(f"independent DOM census disagrees with active rows: {position}")
            if position.get("capture_count") != len(active_expected):
                raise RuntimeError(f"capture count disagrees with active rows: {position}")
            if position.get("capture_debug", {}).get("capture_mode") == "jpeg":
                proof = position.get("source_proof", [])
                if len(proof) != int(position["capture_count"]) or any(
                    item.get("coefficient_validation") is not True for item in proof
                ):
                    raise RuntimeError(f"JPEG coefficient proof is incomplete: {position}")
        final_census = await page.evaluate(INDEPENDENT_CENSUS_JS)
        report["independent_body_census_final"] = final_census
        observed_body_area_ids = [
            item["areaIndex"]
            for position in captured_positions
            for item in position["independent"].get("body", [])
        ]
        observed_visible_body_area_ids = [
            item["areaIndex"]
            for position in captured_positions
            for item in position["independent"].get("visibleBody", [])
        ]
        body_area_ids = observed_visible_body_area_ids
        report["independent_body_area_ids_all_observed_sequence"] = observed_body_area_ids
        report["independent_body_area_ids_observed_sequence"] = observed_visible_body_area_ids
        report["independent_body_area_ids"] = body_area_ids
        if body_area_ids != list(range(1, expected_body + 1)):
            raise RuntimeError(f"independent DOM body census does not cover 1..{expected_body}: {body_area_ids}")
        mode_counts = Counter(
            str(position.get("capture_debug", {}).get("capture_mode", "unknown"))
            for position in captured_positions
        )
        report["capture_mode_counts"] = dict(sorted(mode_counts.items()))
        report["page_capture_mode_counts"] = dict(
            sorted(Counter(str(page.metadata.get("capture_mode", "unknown")) for page in result.pages).items())
        )
        report["dimensions"] = sorted({(page.width, page.height) for page in result.pages})
        if any(page.metadata.get("native") is not True for page in result.pages):
            raise RuntimeError("final live used a non-native capture path")
        if result.pages[0].identity.page_id != "1" or result.pages[-1].identity.page_id != str(expected_body):
            raise RuntimeError("final live first/last identity mismatch")

        manifest_path = output / "manifest.json"
        progress_path = output / "progress.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        manifest_pages = manifest.get("pages", [])
        captured_positions = [position for position in adapter.position_audit if position.get("capture_count") is not None]
        cursor = 0
        for position in captured_positions:
            count = int(position["capture_count"])
            chunk = list(result.pages[cursor : cursor + count])
            if len(chunk) != count:
                raise RuntimeError("position audit chunk does not match saved result pages")
            identity = position["identity"]
            expected_ids = [row.get("areaIndex") for row in position["active"].get("rows", [])]
            saved_parts = []
            for part_index, captured_page in enumerate(chunk, start=1):
                values = [int(value) for value in str(captured_page.identity.page_id or "").split(",") if value]
                declared_part = captured_page.metadata.get("part", 1)
                area_id = values[declared_part - 1] if len(values) > 1 else values[0]
                manifest_page = manifest_pages[captured_page.sequence - 1]
                manifest_metadata = manifest_page.get("metadata", {}) if isinstance(manifest_page, dict) else {}
                saved_parts.append({
                    "sequence": captured_page.sequence,
                    "file": captured_page.file.as_posix(),
                    "areaIndex": area_id,
                    "part": declared_part,
                    "parts": captured_page.metadata.get("parts", 1),
                    "manifest_file": manifest_page.get("file"),
                    "manifest_part": manifest_metadata.get("part", 1),
                    "manifest_parts": manifest_metadata.get("parts", 1),
                    "page_id": captured_page.identity.page_id,
                    "page_number": captured_page.identity.page_number,
                })
            if identity["page_id"] != chunk[0].identity.page_id or identity["page_number"] != chunk[0].identity.page_number:
                raise RuntimeError("position identity changed before packaging")
            if [part["areaIndex"] for part in saved_parts] != expected_ids:
                raise RuntimeError(f"position saved parts do not match RTL active order: {saved_parts}")
            if any(part["manifest_file"] != part["file"] for part in saved_parts):
                raise RuntimeError("manifest file does not match captured file")
            if any(part["manifest_part"] != part["part"] or part["manifest_parts"] != count for part in saved_parts):
                raise RuntimeError("manifest metadata part mapping does not match captured spread")
            position["saved_parts"] = saved_parts
            cursor += count
        if cursor != len(result.pages) or len(manifest_pages) != len(result.pages):
            raise RuntimeError("manifest/result page count mismatch")
        report["manifest_before_package"] = manifest
        report["progress_before_package"] = progress
        report["manifest_sha256_before_package"] = sha256(manifest_path)
        report["progress_sha256_before_package"] = sha256(progress_path)
        for sequence in (1, max(1, expected_body // 2), expected_body):
            manifest_file = str(manifest_pages[sequence - 1]["file"])
            source = output / manifest_file
            destination = evidence / Path(manifest_file).name
            shutil.copy2(source, destination)
        (evidence / "manifest_before_package.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (evidence / "progress_before_package.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        package = package_crawl_output(output, adapter.get_output_metadata(), library_dir=library)
        report["package"] = {"archive_path": str(package.archive_path), "status_path": str(package.status_path)}
        report["archive_audit"] = audit_manifest_and_zip(manifest, package.archive_path)
        if report["archive_audit"]["zip_entry_count"] != expected_body or report["archive_audit"]["bad_crc"] or report["archive_audit"]["manifest_zip_mismatches"]:
            raise RuntimeError("packaged ZIP failed manifest/CRC/dimension audit")
        spread_pages = [page for page in result.pages if page.metadata.get("parts", 1) > 1]
        if len(spread_pages) < 2 or spread_pages[0].identity.page_id != spread_pages[1].identity.page_id:
            raise RuntimeError("no complete representative spread was retained")
        spread_dir = evidence / "spread_visuals"
        spread_dir.mkdir(parents=True, exist_ok=True)
        representative = []
        with zipfile.ZipFile(package.archive_path) as archive:
            for captured_spread_page in spread_pages[:2]:
                manifest_page = manifest_pages[captured_spread_page.sequence - 1]
                entry_name = manifest_page["file"]
                destination = spread_dir / f"part-{captured_spread_page.metadata['part']:02d}-{entry_name}"
                destination.write_bytes(archive.read(entry_name))
                representative.append({
                    "page_id": captured_spread_page.identity.page_id,
                    "areaIndex": saved_part_area_ids[captured_spread_page.sequence - 1],
                    "manifest_file": entry_name,
                    "path": str(destination),
                    "sha256": sha256(destination),
                })
        (spread_dir / "README.json").write_text(json.dumps({"files": representative}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["representative_spread"] = representative
        report["status"] = "ok"
    except BaseException as exc:
        report["status"] = "error"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        raise
    finally:
        (evidence / "final_live_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        await session.close_page(page)
        await session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp-endpoint")
    parser.add_argument("--target", default=TARGET)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--library", type=Path, default=LIBRARY)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--expected-body", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.cdp_endpoint, target=args.target, output=args.output, library=args.library, evidence=args.evidence, expected_body=args.expected_body))


if __name__ == "__main__":
    main()

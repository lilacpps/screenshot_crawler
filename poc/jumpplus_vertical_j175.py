"""Read-only J1.75 validation of the production Jump+ native primitive.

The probe performs one fresh initial load, builds production-shaped draw rows
from the observed vertical mappings, and calls ``JumpPlusAdapter._native_attempt``
without changing production code.  The adapter method therefore owns candidate
selection, strict mapping validation, JPEG-DCT reconstruction, and PNG
fallback priority for each region.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path
from types import MethodType
from typing import Any

from PIL import Image, ImageChops, ImageStat

try:
    from poc.jumpplus_probe import (
        _now_iso,
        _write_json,
        _write_text,
        canvas_mutations_for_canvas,
        draw_calls_for_canvas,
        extract_episode_id,
    )
    from poc.jumpplus_vertical_j1 import (
        VerticalJ1Probe,
        _is_full_frame,
        _is_ignored_spacer_draw,
        _vertical_j1_draw_hook,
    )
    from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
    from screenshot_crawler.site_adapters.jumpplus.adapter import JumpPlusAdapter
    from screenshot_crawler.site_adapters.jumpplus.native_capture import (
        _dct_signature,
        _records,
        dct_lossless_feasibility,
        decoded_pixel_sha256,
        reconstruct_jpeg_lossless,
        reconstruct_jpeg_png,
        select_transport_candidate,
    )
except ModuleNotFoundError:  # direct ``python poc/<probe>.py`` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from poc.jumpplus_probe import (
        _now_iso,
        _write_json,
        _write_text,
        canvas_mutations_for_canvas,
        draw_calls_for_canvas,
        extract_episode_id,
    )
    from poc.jumpplus_vertical_j1 import (
        VerticalJ1Probe,
        _is_full_frame,
        _is_ignored_spacer_draw,
        _vertical_j1_draw_hook,
    )
    from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
    from screenshot_crawler.site_adapters.jumpplus.adapter import JumpPlusAdapter
    from screenshot_crawler.site_adapters.jumpplus.native_capture import (
        _dct_signature,
        _records,
        dct_lossless_feasibility,
        decoded_pixel_sha256,
        reconstruct_jpeg_lossless,
        reconstruct_jpeg_png,
        select_transport_candidate,
    )


DEFAULT_URL = "https://shonenjumpplus.com/episode/10834108156642491399"
DEFAULT_OUTPUT_DIR = Path("output/jumpplus_vertical_j175")
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_MUTATING_OPERATIONS = {"clearRect", "fillRect", "putImageData", "strokeRect", "fillText", "strokeText", "fill", "stroke"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative_file(output_dir: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = output_dir / str(value)
    return path if path.exists() else None


def _source_record_for_region(
    region: dict[str, Any],
    source_records: dict[tuple[Any, str], dict[str, Any]],
) -> dict[str, Any] | None:
    identities = [
        source_records.get((source_id, str(source_url or "")))
        for source_id, source_url in zip(region.get("source_ids") or [], region.get("source_urls") or [])
    ]
    meaningful = [
        item for item in identities
        if item and not str(item.get("url") or "").endswith("/images/spacer.png")
    ]
    return meaningful[0] if len(meaningful) == 1 else None


def _production_mapping(draw: dict[str, Any], canvas_size: tuple[int, int]) -> dict[str, Any]:
    source = draw.get("source") or {}
    source_rect = draw.get("sourceRect") or {}
    destination = draw.get("destinationRect") or {}
    transform = draw.get("transform") or {}
    return {
        "sourcePath": source.get("url"),
        "sourceUrl": source.get("url"),
        "sourceWidth": source.get("naturalWidth"),
        "sourceHeight": source.get("naturalHeight"),
        "canvasWidth": canvas_size[0],
        "canvasHeight": canvas_size[1],
        "sx": source_rect.get("sx"),
        "sy": source_rect.get("sy"),
        "sw": source_rect.get("sw"),
        "sh": source_rect.get("sh"),
        "dx": destination.get("dx"),
        "dy": destination.get("dy"),
        "dw": destination.get("dw"),
        "dh": destination.get("dh"),
        "transform": transform,
        "globalCompositeOperation": draw.get("globalCompositeOperation"),
        "filter": draw.get("filter"),
        "globalAlpha": draw.get("globalAlpha"),
        "sourceId": source.get("sourceId"),
        "sequence": draw.get("sequence", 0),
    }


def build_production_row(
    region: dict[str, Any],
    draw_calls: list[dict[str, Any]],
    canvas_mutations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Translate observed J1 evidence into the adapter's native row contract."""

    width, height = (region.get("canvas_dimensions") or [0, 0])[:2]
    canvas_size = (int(width or 0), int(height or 0))
    canvas_id = region.get("canvas_id")
    observed = draw_calls_for_canvas(draw_calls, canvas_id)
    effective = [
        draw for draw in observed
        if not _is_ignored_spacer_draw(draw, canvas_size[0], canvas_size[1])
    ]
    full_frames = [draw for draw in effective if _is_full_frame(draw, canvas_size[0], canvas_size[1])]
    base_draw = max(full_frames, key=lambda item: item.get("sequence", 0)) if full_frames else None
    base = _production_mapping(base_draw, canvas_size) if base_draw else None
    mapping = []
    if base_draw is not None:
        base_sequence = int(base_draw.get("sequence", 0))
        mapping = [
            _production_mapping(draw, canvas_size)
            for draw in effective
            if int(draw.get("sequence", 0)) >= base_sequence and draw is not base_draw
        ]
    source = None
    if base_draw:
        source_info = base_draw.get("source") or {}
        source = {
            "sourceId": source_info.get("sourceId"),
            "sourceUrl": source_info.get("url"),
            "type": source_info.get("type", "HTMLImageElement"),
        }
    return {
        "index": region.get("index"),
        "canvasId": canvas_id,
        "canvasWidth": canvas_size[0],
        "canvasHeight": canvas_size[1],
        "source": source,
        "base": base,
        "mapping": mapping,
        "visibleDraw": dict(base) if base else None,
        "mutations": canvas_mutations_for_canvas(canvas_mutations, canvas_id),
    }


def _mapping_values(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item for item in [row.get("base"), row.get("visibleDraw"), *(row.get("mapping") or [])]
        if isinstance(item, dict)
    ]


def _transform_tuple(raw: Any) -> tuple[float, ...]:
    if isinstance(raw, dict):
        raw = tuple(raw.get(key) for key in ("a", "b", "c", "d", "e", "f"))
    try:
        return tuple(float(value) for value in (raw or ()))
    except (TypeError, ValueError):
        return ()


def production_validation(
    row: dict[str, Any],
    candidate_data: bytes | None,
    source_path: str | None,
) -> dict[str, Any]:
    """Report strict production validation inputs; reconstruction remains authoritative."""

    values = _mapping_values(row)
    source_paths = {str(item.get("sourcePath") or "") for item in values}
    transforms = [_transform_tuple(item.get("transform")) for item in values]
    source_over = all(item.get("globalCompositeOperation") == "source-over" for item in values)
    filter_none = all(item.get("filter") == "none" for item in values)
    alpha_one = all(item.get("globalAlpha") == 1 for item in values)
    mutations = row.get("mutations") or []
    mutations_valid = not any(item.get("operation") in _MUTATING_OPERATIONS for item in mutations if isinstance(item, dict))
    conditions = {
        "base_draw_exists": isinstance(row.get("base"), dict),
        "visible_draw_exists": isinstance(row.get("visibleDraw"), dict),
        "tile_mappings_exist": bool(row.get("mapping")),
        "source_identity_consistent": bool(source_path) and source_paths == {str(source_path)},
        "transform_identity": bool(values) and all(transform == _IDENTITY for transform in transforms),
        "global_composite_source_over": bool(values) and source_over,
        "filter_none": bool(values) and filter_none,
        "global_alpha_one": bool(values) and alpha_one,
        "unsupported_canvas_mutation_absent": mutations_valid,
    }
    records_valid = False
    feasibility: dict[str, Any] | None = None
    if candidate_data is not None and source_path:
        records = _records(
            candidate_data,
            base=row.get("base"),
            mappings=row.get("mapping") or [],
            visible_draw=row.get("visibleDraw"),
            source_path=source_path,
            canvas_size=(int(row.get("canvasWidth", 0)), int(row.get("canvasHeight", 0))),
        )
        records_valid = records is not None
        if records is not None:
            _, tiles, _ = records
            feasibility = dct_lossless_feasibility(
                jpeg_bytes=candidate_data,
                source_rectangles=[(item.sx, item.sy, item.sw, item.sh) for item in tiles],
                destination_rectangles=[(item.dx, item.dy, item.dw, item.dh) for item in tiles],
                canvas_size=(int(row.get("canvasWidth", 0)), int(row.get("canvasHeight", 0))),
            )
    conditions["production_records_valid"] = records_valid
    conditions["mapping_geometry_valid"] = bool(feasibility and feasibility.get("feasible"))
    failure_reasons: list[str] = []
    if not conditions["base_draw_exists"]:
        failure_reasons.append("base_draw_unavailable")
    if not conditions["visible_draw_exists"]:
        failure_reasons.append("visible_draw_unavailable")
    if not conditions["source_identity_consistent"]:
        failure_reasons.append("source_identity_inconsistent")
    if not conditions["transform_identity"]:
        failure_reasons.append("invalid_transform")
    if not conditions["global_composite_source_over"]:
        failure_reasons.append("invalid_composite")
    if not conditions["filter_none"]:
        failure_reasons.append("invalid_filter")
    if not conditions["global_alpha_one"]:
        failure_reasons.append("invalid_alpha")
    if not conditions["unsupported_canvas_mutation_absent"]:
        failure_reasons.append("unsupported_mutation")
    if not conditions["tile_mappings_exist"]:
        failure_reasons.append("tile_mapping_unavailable")
    if candidate_data is not None and not records_valid:
        failure_reasons.append("production_mapping_validation_failed")
    if records_valid and not conditions["mapping_geometry_valid"]:
        failure_reasons.append(str((feasibility or {}).get("reason") or "invalid_tile_geometry"))
    return {
        "conditions": conditions,
        "failure_reasons": failure_reasons,
        "dct_lossless_feasibility": feasibility,
    }


def _candidate_summary(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    return {
        key: candidate.get(key)
        for key in ("url", "file", "dimensions", "raw_sha256", "pixel_sha256", "image_format")
    }


def _reference_path(index: int) -> Path | None:
    candidates = (
        Path("output/jumpplus_vertical_j1_20260928_final/references") / f"region_{index:03d}.png",
        Path("output/jumpplus_vertical_j1_20260928/references") / f"region_{index:03d}.png",
    )
    return next((path for path in candidates if path.exists()), None)


def _visual_reference(result_data: bytes, expected_dimensions: tuple[int, int], index: int) -> dict[str, Any]:
    reference = _reference_path(index)
    result: dict[str, Any] = {
        "file": str(reference) if reference else None,
        "dimensions_match": None,
        "generated_dimensions_match": None,
        "reference_dimensions_match": None,
        "reference_device_scale": None,
        "assessment": "unavailable",
    }
    if reference is None:
        return result
    try:
        with Image.open(io.BytesIO(result_data)) as generated_image, Image.open(reference) as reference_image:
            generated = generated_image.convert("RGB")
            rendered = reference_image.convert("RGB")
            result["generated_dimensions"] = list(generated.size)
            result["reference_dimensions"] = list(rendered.size)
            result["generated_dimensions_match"] = generated.size == expected_dimensions
            result["reference_dimensions_match"] = rendered.size == expected_dimensions
            if expected_dimensions[0] and expected_dimensions[1]:
                result["reference_device_scale"] = [
                    rendered.width / expected_dimensions[0],
                    rendered.height / expected_dimensions[1],
                ]
            result["dimensions_match"] = result["generated_dimensions_match"]
            scale_x = rendered.width / generated.width if generated.width else 0
            scale_y = rendered.height / generated.height if generated.height else 0
            if generated.size != rendered.size and abs(scale_x - scale_y) <= 0.02 and 1.0 < scale_x < 3.0:
                rendered = rendered.resize(generated.size, Image.Resampling.LANCZOS)
                result["reference_resampled_for_device_scale"] = True
            elif generated.size != rendered.size:
                result["assessment"] = "dimension_mismatch"
                return result
            diff = ImageChops.difference(generated, rendered)
            mean = sum(ImageStat.Stat(diff).mean) / 3
            result["mean_absolute_difference"] = mean
            result["max_channel_difference"] = max(diff.getchannel(channel).getextrema()[1] for channel in range(3))
            result["assessment"] = "close" if mean <= 12 else "visual_mismatch"
    except (OSError, ValueError) as exc:
        result["assessment"] = "comparison_error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _candidate_data(output_dir: Path, saved_images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in saved_images:
        path = _relative_file(output_dir, item.get("file"))
        if path is None:
            continue
        candidate = dict(item)
        candidate["data"] = path.read_bytes()
        result.append(candidate)
    return result


def _make_summary(report: dict[str, Any]) -> str:
    counts = report.get("counts") or {}
    lines = [
        "# Jump+ Vertical J1.75: production primitive validation",
        "",
        f"- target: `{report.get('target_url')}`",
        f"- content regions: `{report.get('content_region_count')}`",
        f"- candidate association success: `{report.get('candidate_association_success')}`",
        f"- lossless JPEG success: `{counts.get('lossless_jpeg_success', 0)}`",
        f"- PNG fallback success: `{counts.get('png_reconstruction_success', 0)}`",
        f"- failed: `{counts.get('failed', 0)}`",
        f"- all regions captured: `{report.get('all_regions_captured')}`",
        f"- conclusion: `{report.get('conclusion')}`",
        "",
        "## Primitive and candidate set",
        "",
        "- Candidate selection and reconstruction were executed through the production `JumpPlusAdapter._native_attempt()` path.",
        "- The candidate pool was the complete retained `/public/page/` JPEG set for this fresh load; no PoC dimension prefilter was applied.",
        "- The adapter's order was preserved: `reconstruct_jpeg_lossless()` first, then `reconstruct_jpeg_png()` only when the lossless path returned `None`.",
        "",
        "## Per-region results",
        "",
        "| index | selection | method | dimensions | validation | reference |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for row in report.get("regions", []):
        validation = row.get("validation") or {}
        lines.append(
            f"| {row.get('index')} | `{row.get('selection_reason')}` | `{row.get('capture_method')}` | "
            f"`{row.get('width')}x{row.get('height')}` | `{validation.get('failure_reasons') or 'valid'}` | "
            f"`{(row.get('rendered_reference') or {}).get('assessment', 'unavailable')}` |"
        )
    lines.extend([
        "",
        "## Scope and interpretation",
        "",
        "- One fresh initial load only; no timeline wait, scroll, keyboard, or viewer navigation was performed.",
        f"- Scroll required for this capture: `{report.get('scroll_required_for_capture')}`.",
        f"- Production implementation changed: `{report.get('production_code_changed')}`.",
        f"- Residual: `{report.get('residual')}`.",
        "",
        "Artifacts: `report.json`, `regions.json`, `association.json`, `validation.json`, `reconstructed/`, and `diagnostics/`.",
    ])
    return "\n".join(lines) + "\n"


async def run_probe(url: str, output_dir: Path, cdp_endpoint: str | None) -> dict[str, Any]:
    expected_episode_id = extract_episode_id(url)
    if expected_episode_id is None:
        raise ValueError("--url must be a Jump+ URL of the form /episode/<numeric-id>")
    endpoint = resolve_cdp_endpoint(cli_endpoint=cdp_endpoint)
    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    probe = VerticalJ1Probe(page=page, output_dir=output_dir, expected_episode_id=expected_episode_id)
    probe.target_url = url
    output_dir.mkdir(parents=True, exist_ok=True)
    probe.install_listeners()
    await page.add_init_script(script=_vertical_j1_draw_hook())
    adapter = JumpPlusAdapter()
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except BaseException as exc:  # noqa: BLE001
            probe.errors.append(f"goto failed: {type(exc).__name__}: {exc}")
        await probe.wait_for_stability(timeout=12.0)
        await probe.wait_for_scroll_stability(timeout=5.0)
        initial = await probe.record_stage("initial")
        await probe._take_renderer_events()
        for record in probe.source_records.values():
            record["source_raw_sha256"] = None
            record["source_raw_sha256_note"] = "fresh research snapshot is PNG; original source raw bytes were not available"
        candidates = _candidate_data(output_dir, probe.saved_images)
        all_rows = [
            build_production_row(
                region,
                probe.all_draw_calls,
                probe.all_canvas_mutations,
            )
            for region in initial["regions"]
        ]
        _write_json(output_dir / "sources.json", list(probe.source_records.values()))
        _write_json(output_dir / "candidates.json", [
            {key: value for key, value in candidate.items() if key != "data"}
            for candidate in candidates
        ])
        _write_json(output_dir / "network.json", {"events": probe.network_events, "saved_images": probe.saved_images})
        _write_json(output_dir / "draw_calls.json", {
            "draw_calls": probe.all_draw_calls,
            "canvas_mutations": probe.all_canvas_mutations,
        })
        associations: list[dict[str, Any]] = []
        validations: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        reconstructed_dir = output_dir / "reconstructed"
        reconstructed_dir.mkdir(parents=True, exist_ok=True)
        diagnostics_dir = output_dir / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        for region, row in zip(initial["regions"], all_rows, strict=True):
            index = int(region["index"])
            source_record = _source_record_for_region(region, probe.source_records)
            source_path = str((row.get("source") or {}).get("sourceUrl") or "")
            source_file = _relative_file(output_dir, source_record.get("file") if source_record else None)
            source_data = source_file.read_bytes() if source_file else None
            source_pixel_sha = decoded_pixel_sha256(source_data) if source_data else None
            source_raw_sha = source_record.get("source_raw_sha256") if source_record else None
            selection = select_transport_candidate(
                source_pixel_sha,
                candidates,
                source_raw_sha256=source_raw_sha if isinstance(source_raw_sha, str) else None,
                source_data=source_data,
                load_bytes=lambda item: item["data"],
                analyze_candidate=_dct_signature,
            )
            selected = selection.get("selected_candidate") or selection.get("pixel_fallback_candidate")
            selected_data = selected.get("data") if isinstance(selected, dict) else None
            validation = production_validation(row, selected_data if isinstance(selected_data, bytes) else None, source_path)
            source_map = {}
            if source_record and source_data is not None:
                source_map[(source_record.get("sourceId"), str(source_record.get("url") or ""))] = {
                    "data": source_data,
                    "raw_sha256": source_raw_sha,
                }

            async def snapshot_override(
                self: JumpPlusAdapter,
                _page: Any,
                _wanted: list[dict[str, Any]],
                _source_map: dict[tuple[Any, str], dict[str, Any]] = source_map,
            ) -> dict[tuple[Any, str], dict[str, Any]]:
                return _source_map

            adapter._snapshot_sources = MethodType(snapshot_override, adapter)  # type: ignore[method-assign]
            captures = None
            native_reason = None
            native_selections: list[str] = []
            try:
                captures, native_reason, native_selections, _used_urls = await adapter._native_attempt(page, [row], candidates)
            except BaseException as exc:  # noqa: BLE001 - report production primitive failure per region
                native_reason = f"native_capture_error:{type(exc).__name__}:{exc}"
            lossless_result = None
            png_result = None
            if isinstance(selected_data, bytes):
                try:
                    lossless_result = reconstruct_jpeg_lossless(
                        selected_data,
                        base=row.get("base"),
                        mappings=row.get("mapping") or [],
                        visible_draw=row.get("visibleDraw"),
                        source_path=source_path,
                        canvas_size=(int(row.get("canvasWidth", 0)), int(row.get("canvasHeight", 0))),
                    )
                except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                    lossless_result = None
                if lossless_result is None:
                    try:
                        png_result = reconstruct_jpeg_png(
                            selected_data,
                            base=row.get("base"),
                            mappings=row.get("mapping") or [],
                            visible_draw=row.get("visibleDraw"),
                            source_path=source_path,
                            canvas_size=(int(row.get("canvasWidth", 0)), int(row.get("canvasHeight", 0))),
                        )
                    except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                        png_result = None
            capture = captures[0] if captures else None
            capture_method = "failed"
            output_file = None
            rendered_reference = {"assessment": "unavailable", "file": None, "dimensions_match": None}
            if capture is not None:
                capture_method = "jpeg_dct" if capture.mime_type == "image/jpeg" else "png_reconstruction"
                output_path = reconstructed_dir / f"{index + 1:03d}{capture.file_extension}"
                output_path.write_bytes(capture.data)
                output_file = str(output_path.relative_to(output_dir))
                rendered_reference = _visual_reference(
                    capture.data,
                    (int(row.get("canvasWidth", 0)), int(row.get("canvasHeight", 0))),
                    index,
                )
            association = {
                "index": index,
                "canvas_id": row.get("canvasId"),
                "source_id": (row.get("source") or {}).get("sourceId"),
                "source_url": source_path,
                "selection_status": selection.get("selection_status"),
                "selection_reason": selection.get("selection_reason"),
                "selected_candidate": _candidate_summary(selected if isinstance(selected, dict) else None),
                "candidate_pool_count": len(candidates),
                "candidate_count": selection.get("candidate_count"),
                "equivalent_candidate_count": selection.get("equivalent_candidate_count"),
                "metadata_equivalent": selection.get("metadata_equivalent"),
                "source_pixel_sha256": source_pixel_sha,
                "source_raw_sha256": source_raw_sha,
            }
            result_record = {
                **association,
                "width": capture.width if capture else row.get("canvasWidth"),
                "height": capture.height if capture else row.get("canvasHeight"),
                "mime_type": capture.mime_type if capture else None,
                "extension": capture.file_extension if capture else None,
                "output_size": len(capture.data) if capture else 0,
                "output_file": output_file,
                "capture_method": capture_method,
                "lossless_jpeg_success": lossless_result is not None,
                "png_reconstruction_success": png_result is not None,
                "native_reason": native_reason,
                "native_selection_statuses": native_selections,
                "validation": validation,
                "rendered_reference": rendered_reference,
            }
            associations.append(association)
            validations.append({"index": index, **validation})
            results.append(result_record)
            _write_json(diagnostics_dir / f"region_{index:03d}.json", {
                "production_row": row,
                "association": association,
                "native_reason": native_reason,
                "native_selection_statuses": native_selections,
                "validation": validation,
                "lossless_jpeg_result": lossless_result is not None,
                "png_reconstruction_result": png_result is not None,
            })
        _write_json(output_dir / "association.json", associations)
        _write_json(output_dir / "validation.json", validations)
        _write_json(output_dir / "regions.json", results)
        association_success = sum(
            row.get("selection_status") in {"unique", "equivalent_multiple"}
            for row in associations
        )
        lossless_count = sum(row.get("lossless_jpeg_success") for row in results)
        png_count = sum(
            row.get("capture_method") == "png_reconstruction"
            for row in results
        )
        failed_count = sum(row.get("capture_method") == "failed" for row in results)
        validation_failures = sum(bool((row.get("validation") or {}).get("failure_reasons")) for row in results)
        report = {
            "target_url": url,
            "target_episode_id": expected_episode_id,
            "final_url": page.url,
            "captured_at": _now_iso(),
            "content_region_count": len(initial["regions"]),
            "candidate_pool_count": len(candidates),
            "candidate_association_success": association_success,
            "lossless_jpeg_success": lossless_count,
            "png_reconstruction_success": png_count,
            "failed": failed_count,
            "all_regions_captured": failed_count == 0 and len(results) == len(initial["regions"]),
            "counts": {
                "candidate_association_success": association_success,
                "lossless_jpeg_success": lossless_count,
                "png_reconstruction_success": png_count,
                "failed": failed_count,
                "validation_failure_regions": validation_failures,
            },
            "candidate_filter": "none; complete retained /public/page/ JPEG candidate pool passed to production selector",
            "production_primitive": "JumpPlusAdapter._native_attempt",
            "production_code_changed": False,
            "scroll_performed": False,
            "scroll_required_for_capture": "not indicated by J0/J1/J1.5 and not re-investigated in J1.75",
            "conclusion": (
                "A" if failed_count == 0 and association_success == len(results) and lossless_count == len(results)
                else "B" if failed_count == 0 and association_success == len(results)
                else "C"
            ),
            "production_implementation_ready": failed_count == 0 and association_success == len(results),
            "residual": "production vertical branch is not implemented; validate other vertical episodes and source/runtime variants before changing production",
            "errors": probe.errors,
        }
        _write_json(output_dir / "report.json", report)
        _write_text(output_dir / "summary.md", _make_summary({**report, "regions": results}))
        return {**report, "regions": results}
    finally:
        await session.close_page(page)
        await session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Jump+ vertical J1.75 production primitive probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    report = asyncio.run(run_probe(args.url, args.output_dir, args.cdp_endpoint))
    print(json.dumps({
        "content_region_count": report.get("content_region_count"),
        "candidate_association_success": report.get("candidate_association_success"),
        "lossless_jpeg_success": report.get("lossless_jpeg_success"),
        "png_reconstruction_success": report.get("png_reconstruction_success"),
        "failed": report.get("failed"),
        "conclusion": report.get("conclusion"),
        "output_dir": str(args.output_dir),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

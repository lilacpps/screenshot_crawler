"""Read-only J1.5 probe for Jump+ vertical transport association.

This research probe observes one fresh initial load only.  It reuses the J1
source/network/draw collection and the production Jump+ transport selector;
the production adapter itself is not changed.  It deliberately does not
scroll, wait on a timeline, or perform any viewer navigation.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

try:
    from poc.jumpplus_probe import (
        _now_iso,
        _write_json,
        _write_text,
        draw_calls_for_canvas,
        extract_episode_id,
    )
    from poc.jumpplus_reconstruct import reconstruct_jpeg_dct, run_reconstruction
    from poc.jumpplus_vertical_j1 import (
        VerticalJ1Probe,
        _is_full_frame,
        _is_ignored_spacer_draw,
        _vertical_j1_draw_hook,
        classify_reconstruction,
    )
    from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
    from screenshot_crawler.site_adapters.jumpplus.native_capture import (
        _dct_signature,
        max_decoded_pixel_difference,
        select_transport_candidate,
    )
except ModuleNotFoundError:  # direct ``python poc/<probe>.py`` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from poc.jumpplus_probe import (
        _now_iso,
        _write_json,
        _write_text,
        draw_calls_for_canvas,
        extract_episode_id,
    )
    from poc.jumpplus_reconstruct import reconstruct_jpeg_dct, run_reconstruction
    from poc.jumpplus_vertical_j1 import (
        VerticalJ1Probe,
        _is_full_frame,
        _is_ignored_spacer_draw,
        _vertical_j1_draw_hook,
        classify_reconstruction,
    )
    from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint
    from screenshot_crawler.site_adapters.jumpplus.native_capture import (
        _dct_signature,
        max_decoded_pixel_difference,
        select_transport_candidate,
    )


DEFAULT_URL = "https://shonenjumpplus.com/episode/10834108156642491399"
DEFAULT_OUTPUT_DIR = Path("output/jumpplus_vertical_j15")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_is_content(source: dict[str, Any] | None) -> bool:
    return bool(source and not str(source.get("url") or "").endswith("/images/spacer.png"))


def _candidate_dimensions(candidate: dict[str, Any]) -> tuple[int, int] | None:
    dimensions = candidate.get("dimensions")
    if not isinstance(dimensions, list | tuple) or len(dimensions) != 2:
        return None
    try:
        return int(dimensions[0]), int(dimensions[1])
    except (TypeError, ValueError):
        return None


def dimension_compatible_candidates(
    source_dimensions: list[int] | tuple[int, int] | None,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply only the existing association precondition: equal dimensions."""

    if not source_dimensions or len(source_dimensions) != 2:
        return list(candidates)
    wanted = (int(source_dimensions[0]), int(source_dimensions[1]))
    return [candidate for candidate in candidates if _candidate_dimensions(candidate) == wanted]


def selection_bucket(selection: dict[str, Any]) -> str:
    """Classify production selector output without changing its decision."""

    reason = str(selection.get("selection_reason") or "")
    status = str(selection.get("selection_status") or "unmatched")
    if reason == "single_raw_sha256":
        return "raw_sha256"
    if reason == "single_pixel_match":
        return "exact_pixel_sha256"
    if reason == "single_decoder_tolerant_pixel_match":
        return "tolerant_pixel"
    if reason == "identical_dct_image_content":
        return "dct_equivalence"
    if status == "ambiguous":
        return "ambiguous"
    if status == "unmatched":
        return "unmatched"
    return "other"


def _pixel_diff_metrics(source_data: bytes, candidate_data: bytes) -> dict[str, Any]:
    try:
        with Image.open(io.BytesIO(source_data)) as source_image, Image.open(io.BytesIO(candidate_data)) as candidate_image:
            source = source_image.convert("RGB")
            candidate = candidate_image.convert("RGB")
            if source.size != candidate.size:
                return {"max_channel_difference": None, "mean_absolute_difference": None, "different_pixel_ratio": None}
            difference = ImageChops.difference(source, candidate)
            stats = ImageStat.Stat(difference)
            histogram = difference.convert("L").histogram()
            different = source.width * source.height - histogram[0]
            return {
                "max_channel_difference": max(
                    difference.getchannel(channel).getextrema()[1] for channel in range(3)
                ),
                "mean_absolute_difference": sum(stats.mean) / 3,
                "different_pixel_ratio": different / (source.width * source.height)
                if source.width and source.height else 0.0,
            }
    except (OSError, ValueError, TypeError) as exc:
        return {"max_channel_difference": None, "mean_absolute_difference": None, "error": f"{type(exc).__name__}: {exc}"}


def _relative_file(output_dir: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = output_dir / str(value)
    return path if path.exists() else None


def _candidate_summary(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    return {
        "url": candidate.get("url"),
        "file": candidate.get("file"),
        "dimensions": candidate.get("dimensions"),
        "raw_sha256": candidate.get("raw_sha256"),
        "pixel_sha256": candidate.get("pixel_sha256"),
        "image_format": candidate.get("image_format"),
    }


def associate_regions(
    *,
    output_dir: Path,
    regions: list[dict[str, Any]],
    source_records: dict[tuple[Any, str], dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run the production selector once per content region and save diagnostics."""

    diagnostics_dir = output_dir / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for region in regions:
        index = int(region["index"])
        source_ids = list(region.get("source_ids") or [])
        source_urls = list(region.get("source_urls") or [])
        identities = [
            source_records.get((source_id, str(source_url or "")))
            for source_id, source_url in zip(source_ids, source_urls)
        ]
        identities = [item for item in identities if _source_is_content(item)]
        source = identities[0] if len(identities) == 1 else None
        source_file = _relative_file(output_dir, source.get("file") if source else None)
        source_data = source_file.read_bytes() if source_file else None
        source_dimensions = source.get("decoded_dimensions") if source else None
        dimension_candidates = dimension_compatible_candidates(source_dimensions, candidates)
        exact_matches = [
            candidate for candidate in dimension_candidates
            if source and source.get("pixel_sha256") and candidate.get("pixel_sha256") == source.get("pixel_sha256")
        ]
        source_raw_sha256 = source.get("source_raw_sha256") if source else None
        raw_matches = [
            candidate for candidate in dimension_candidates
            if source_raw_sha256 and candidate.get("raw_sha256") == source_raw_sha256
        ]

        candidate_diffs: list[dict[str, Any]] = []
        min_max_difference: int | None = None
        min_mean_difference: float | None = None
        if source_data:
            for candidate in dimension_candidates:
                candidate_file = _relative_file(output_dir, candidate.get("file"))
                if candidate_file is None:
                    candidate_diffs.append({"candidate": _candidate_summary(candidate), "error": "candidate_file_missing"})
                    continue
                candidate_data = candidate_file.read_bytes()
                max_difference = max_decoded_pixel_difference(source_data, candidate_data)
                metrics = _pixel_diff_metrics(source_data, candidate_data)
                if max_difference is not None:
                    min_max_difference = max_difference if min_max_difference is None else min(min_max_difference, max_difference)
                mean_difference = metrics.get("mean_absolute_difference")
                if isinstance(mean_difference, (int, float)):
                    min_mean_difference = mean_difference if min_mean_difference is None else min(min_mean_difference, float(mean_difference))
                candidate_diffs.append({
                    "candidate": _candidate_summary(candidate),
                    "max_decoded_pixel_difference": max_difference,
                    **metrics,
                })

        if source and source_data:
            selection = select_transport_candidate(
                str(source.get("pixel_sha256") or "") or None,
                dimension_candidates,
                source_raw_sha256=source_raw_sha256,
                source_data=source_data,
                load_bytes=lambda candidate: (output_dir / str(candidate["file"])).read_bytes(),
                analyze_candidate=_dct_signature,
            )
        elif source:
            selection = select_transport_candidate(
                str(source.get("pixel_sha256") or "") or None,
                dimension_candidates,
                source_raw_sha256=source_raw_sha256,
            )
        else:
            selection = {
                "selection_status": "unmatched",
                "selection_reason": "source_identity_missing_or_ambiguous",
                "candidate_count": 0,
                "equivalent_candidate_count": 0,
                "metadata_equivalent": None,
                "selected_candidate": None,
            }
        selected = selection.get("selected_candidate") or selection.get("pixel_fallback_candidate")
        selection_reason = str(selection.get("selection_reason") or "")
        source_snapshot_raw_sha256 = _sha256(source_data) if source_data else None
        diagnostics_file = diagnostics_dir / f"region_{index:03d}_candidate_diffs.json"
        _write_json(diagnostics_file, {
            "index": index,
            "source_dimensions": source_dimensions,
            "source_snapshot_raw_sha256": source_snapshot_raw_sha256,
            "candidate_diffs": candidate_diffs,
            "min_max_decoded_pixel_difference": min_max_difference,
            "min_mean_absolute_difference": min_mean_difference,
        })
        rows.append({
            **region,
            "source_count": len(identities),
            "source_id": source.get("sourceId") if source else None,
            "source_url": source.get("url") if source else None,
            "source_dimensions": source_dimensions,
            "source_snapshot_file": source.get("file") if source else None,
            "source_raw_sha256": source_raw_sha256,
            "source_snapshot_raw_sha256": source_snapshot_raw_sha256,
            "source_pixel_sha256": source.get("pixel_sha256") if source else None,
            "candidate_count_total": len(candidates),
            "dimension_compatible_candidate_count": len(dimension_candidates),
            "pixel_sha_exact_match_count": len(exact_matches),
            "raw_sha_match_count": len(raw_matches),
            "tolerant_pixel_match_count": sum(
                bool(item.get("max_decoded_pixel_difference") is not None and item.get("max_decoded_pixel_difference") <= 2)
                for item in candidate_diffs
            ),
            "min_max_decoded_pixel_difference": min_max_difference,
            "min_mean_absolute_difference": min_mean_difference,
            "selection_status": selection.get("selection_status", "unmatched"),
            "selection_reason": selection_reason,
            "selection_bucket": selection_bucket(selection),
            "selector_candidate_count": selection.get("candidate_count", 0),
            "equivalent_candidate_count": selection.get("equivalent_candidate_count", 0),
            "metadata_equivalent": selection.get("metadata_equivalent"),
            "selected_candidate": _candidate_summary(selected),
            "selected_candidate_url": selected.get("url") if selected else None,
            "selected_candidate_raw_sha256": selected.get("raw_sha256") if selected else None,
            "selected_candidate_pixel_sha256": selected.get("pixel_sha256") if selected else None,
            "candidate_diagnostics_file": str(diagnostics_file.relative_to(output_dir)),
            "transport_ready_production_selector": selection.get("selection_status") in {"unique", "equivalent_multiple"},
            "association_evidence": {
                "exact_pixel_sha_match": bool(exact_matches),
                "raw_sha_match": bool(raw_matches),
                "tolerant_pixel_match": selection_reason == "single_decoder_tolerant_pixel_match",
                "dct_equivalence": selection_reason == "identical_dct_image_content",
            },
        })
    return rows


def _augment_source_records(output_dir: Path, records: dict[tuple[Any, str], dict[str, Any]]) -> None:
    for record in records.values():
        path = _relative_file(output_dir, record.get("file"))
        record["source_raw_sha256"] = None
        record["source_snapshot_raw_sha256"] = _sha256(path.read_bytes()) if path else None
        record["source_raw_sha256_note"] = "browser source snapshot is PNG; original source raw bytes are unavailable"


def _write_reconstruction_input(probe: VerticalJ1Probe, stage: dict[str, Any]) -> None:
    """Reuse J1's input shape so the existing J2 reconstruction stays unchanged."""

    probe._write_reconstruction_input(stage)


def _reconstruction_rows(
    regions: list[dict[str, Any]],
    reconstruction: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_canvas = {
        int(item["canvas_id"]): item
        for item in reconstruction.get("states", [])
        if item.get("canvas_id") is not None
    }
    result: list[dict[str, Any]] = []
    for row in regions:
        actual = by_canvas.get(int(row["canvas_id"])) if row.get("canvas_id") is not None else None
        mapping = (actual or {}).get("mapping")
        evidence = {
            "reconstructable": bool(row.get("transport_ready_production_selector") and row.get("draw_ready")),
        }
        classification = classify_reconstruction(mapping, evidence)
        if row.get("selection_status") not in {"unique", "equivalent_multiple"}:
            classification = "inconclusive"
        enriched = {
            **row,
            "reconstruction": {
                "status": (actual or {}).get("status", "inconclusive"),
                "classification": classification,
                "mapping_status": (mapping or {}).get("mapping_status"),
                "pixel_reconstruction": (mapping or {}).get("pixel_reconstruction"),
                "jpeg_dct_feasibility": (mapping or {}).get("jpeg_dct_feasibility"),
                "jpeg_dct_reconstruction": (mapping or {}).get("jpeg_dct_reconstruction"),
                "visual_reference": (mapping or {}).get("visual_reference"),
                "mapping_file": (mapping or {}).get("reconstructed_file"),
            },
            "classification": classification,
        }
        result.append(enriched)
    counts = {
        "confirmed": sum(item["classification"] == "confirmed" for item in result),
        "inconclusive": sum(item["classification"] == "inconclusive" for item in result),
        "failed": sum(item["classification"] == "failed" for item in result),
    }
    return result, counts


def _run_production_selected_dct(
    *,
    output_dir: Path,
    regions: list[dict[str, Any]],
    all_draw_calls: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Run the existing DCT reconstruction with the production-selected JPEG.

    The existing J2 runner predates the production selector and intentionally
    retains its exact-pixel-only selection.  For J1.5, only the selected
    candidate is supplied here; tile mapping and DCT reconstruction are still
    the existing PoC implementations.
    """

    result_dir = output_dir / "reconstructed" / "production_selector"
    result_dir.mkdir(parents=True, exist_ok=True)
    results: dict[int, dict[str, Any]] = {}
    for row in regions:
        index = int(row["index"])
        selected = row.get("selected_candidate")
        canvas_id = row.get("canvas_id")
        width, height = (row.get("canvas_dimensions") or [None, None])[:2]
        if not selected or canvas_id is None or not isinstance(width, int) or not isinstance(height, int):
            results[index] = {"jpeg_dct_reconstruction": "not_attempted", "reason": "missing_selected_candidate_source_or_geometry"}
            continue
        candidate_file = _relative_file(output_dir, selected.get("file"))
        if candidate_file is None:
            results[index] = {"jpeg_dct_reconstruction": "not_attempted", "reason": "selected_candidate_file_missing"}
            continue
        draws = draw_calls_for_canvas(all_draw_calls, canvas_id)
        effective_draws = [
            draw for draw in draws
            if not _is_ignored_spacer_draw(draw, width, height)
        ]
        try:
            with Image.open(candidate_file) as candidate_image:
                pixel_replay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                source_image = candidate_image.convert("RGBA")
                for draw in effective_draws:
                    source_rect = draw.get("sourceRect") or {}
                    destination_rect = draw.get("destinationRect") or {}
                    if not source_rect or not destination_rect:
                        continue
                    sx, sy = int(source_rect["sx"]), int(source_rect["sy"])
                    sw, sh = int(source_rect["sw"]), int(source_rect["sh"])
                    dx, dy = int(destination_rect["dx"]), int(destination_rect["dy"])
                    dw, dh = int(destination_rect["dw"]), int(destination_rect["dh"])
                    if (sw, sh) != (dw, dh):
                        raise ValueError("scaled_draw_observed")
                    pixel_replay.alpha_composite(source_image.crop((sx, sy, sx + sw, sy + sh)), (dx, dy))
                pixel_replay_path = result_dir / f"region_{index:03d}_pixel_replay.png"
                pixel_replay.save(pixel_replay_path)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            results[index] = {
                "jpeg_dct_reconstruction": "not_attempted",
                "reason": f"pixel_replay_reference_failed: {type(exc).__name__}: {exc}",
            }
            continue
        tile_draws = [
            draw for draw in effective_draws
            if not _is_full_frame(draw, width, height)
        ]
        if not tile_draws:
            results[index] = {"jpeg_dct_reconstruction": "not_attempted", "reason": "no_partial_tile_mapping"}
            continue
        output_path = result_dir / f"region_{index:03d}_reconstructed_lossless.jpg"
        try:
            dct_result = reconstruct_jpeg_dct(
                jpeg_bytes=candidate_file.read_bytes(),
                tile_draws=tile_draws,
                canvas_size=(width, height),
                output_path=output_path,
                png_path=pixel_replay_path,
            )
        except (OSError, ValueError) as exc:
            dct_result = {
                "jpeg_dct_reconstruction": "failed",
                "reason": f"dct_probe_error: {type(exc).__name__}: {exc}",
            }
        results[index] = dct_result
    _write_json(output_dir / "reconstructed" / "production_selector_dct.json", results)
    return results


def _probe_draw_diagnostic(
    output_dir: Path,
    post_capture_renderer: dict[str, Any],
    content_canvas_ids: set[int],
) -> dict[str, Any]:
    (output_dir / "diagnostics").mkdir(parents=True, exist_ok=True)
    all_draws = list(post_capture_renderer.get("drawCalls", []))
    generated = [
        draw for draw in all_draws
        if (draw.get("canvas") or {}).get("id") not in content_canvas_ids
    ]
    content = [
        draw for draw in all_draws
        if (draw.get("canvas") or {}).get("id") in content_canvas_ids
    ]
    result = {
        "captured_after_source_snapshot": True,
        "total_draw_calls": len(all_draws),
        "content_canvas_ids": sorted(content_canvas_ids),
        "viewer_content_draw_calls_after_snapshot": len(content),
        "probe_generated_or_non_content_draw_calls": len(generated),
        "probe_generated_canvas_ids": sorted({(draw.get("canvas") or {}).get("id") for draw in generated}),
        "interpretation": "post-capture draw calls are attributed to probe-generated temporary canvases unless their canvas ID belongs to an observed content canvas",
    }
    _write_json(output_dir / "diagnostics" / "probe_source_snapshot_draws.json", {
        **result,
        "content_draw_calls": content,
        "probe_generated_draw_calls": generated,
    })
    return result


def _make_summary(report: dict[str, Any]) -> str:
    association = report.get("association_counts") or {}
    reconstruction = report.get("reconstruction_counts") or {}
    lines = [
        "# Jump+ Vertical J1.5: transport candidate association",
        "",
        "## Target",
        "",
        f"- URL: `{report.get('target_url')}`",
        f"- content regions: `{report.get('content_region_count')}`",
        f"- source snapshots: `{report.get('source_count')}`",
        f"- transport candidates: `{report.get('transport_candidate_count')}`",
        f"- conclusion: `{report.get('conclusion')}`",
        "",
        "## Production selector association",
        "",
        f"- exact pixel SHA regions: `{association.get('exact_pixel_sha256', 0)}`",
        f"- raw SHA regions: `{association.get('raw_sha256', 0)}`",
        f"- tolerant pixel regions: `{association.get('tolerant_pixel', 0)}`",
        f"- DCT-equivalence regions: `{association.get('dct_equivalence', 0)}`",
        f"- unmatched regions: `{association.get('unmatched', 0)}`",
        f"- ambiguous regions: `{association.get('ambiguous', 0)}`",
        "",
        "## Reconstruction",
        "",
        f"- confirmed: `{reconstruction.get('confirmed', 0)}`",
        f"- inconclusive: `{reconstruction.get('inconclusive', 0)}`",
        f"- failed: `{reconstruction.get('failed', 0)}`",
        "- Existing J2 reconstruction is used after production-selector association; rendered references are visual evidence, not byte identity.",
        "",
        "## Draw-hook pollution check",
        "",
        f"- `{json.dumps(report.get('probe_draw_diagnostic', {}), ensure_ascii=False)}`",
        "",
        "## Interpretation",
        "",
        f"- scroll performed by J1.5: `{report.get('scroll_performed')}`",
        f"- scroll required by current evidence: `{report.get('scroll_required_for_capture')}`",
        f"- residual: `{report.get('residual')}`",
        "",
        "## Artifacts",
        "",
        "- `initial/` contains the fresh initial DOM, network, draw, and screenshot snapshot.",
        "- `sources.json`, `candidates.json`, `association.json`, and `regions.json` retain region-level evidence.",
        "- `diagnostics/region_*_candidate_diffs.json` contains minimum decoded-difference analysis.",
        "- `reconstructed/` is produced by the existing J2 reconstruction PoC.",
        "",
        "## Scope",
        "",
        "- No production adapter, Discovery, Batch, DB, ZIP, purchase, point, rental, next-episode, or scrolling behavior was changed or invoked.",
    ]
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
    reconstruction: dict[str, Any] = {"states": []}
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except BaseException as exc:  # noqa: BLE001
            probe.errors.append(f"goto failed: {type(exc).__name__}: {exc}")
        await probe.wait_for_stability(timeout=12.0)
        await probe.wait_for_scroll_stability(timeout=5.0)
        initial = await probe.record_stage("initial")
        post_capture_renderer = await probe._take_renderer_events()
        _augment_source_records(output_dir, probe.source_records)
        content_canvas_ids = {
            int(row["canvas_id"])
            for row in initial["regions"]
            if row.get("canvas_id") is not None
        }
        probe_diagnostic = _probe_draw_diagnostic(output_dir, post_capture_renderer, content_canvas_ids)
        _write_json(output_dir / "sources.json", list(probe.source_records.values()))
        _write_json(output_dir / "candidates.json", probe.saved_images)
        _write_json(output_dir / "network.json", {
            "events": probe.network_events,
            "saved_images": probe.saved_images,
        })
        _write_json(output_dir / "draw_calls.json", {
            "viewer_content_draw_calls": probe.all_draw_calls,
            "viewer_content_canvas_mutations": probe.all_canvas_mutations,
            "post_source_snapshot_renderer": post_capture_renderer,
        })

        associations = associate_regions(
            output_dir=output_dir,
            regions=initial["regions"],
            source_records=probe.source_records,
            candidates=probe.saved_images,
        )
        _write_json(output_dir / "association.json", associations)

        _write_reconstruction_input(probe, initial)
        try:
            reconstruction = run_reconstruction(
                input_dir=output_dir,
                output_dir=output_dir / "reconstructed",
            )
        except BaseException as exc:  # noqa: BLE001
            probe.errors.append(f"existing J2 reconstruction failed: {type(exc).__name__}: {exc}")
            reconstruction = {"states": [], "error": f"{type(exc).__name__}: {exc}"}
        final_regions, reconstruction_counts = _reconstruction_rows(associations, reconstruction)
        production_dct = _run_production_selected_dct(
            output_dir=output_dir,
            regions=associations,
            all_draw_calls=probe.all_draw_calls,
        )
        for row in final_regions:
            dct_result = production_dct.get(int(row["index"]), {})
            row["reconstruction"]["production_selector_dct"] = dct_result
            if (
                row.get("transport_ready_production_selector")
                and row.get("draw_ready")
                and dct_result.get("jpeg_dct_reconstruction") == "successful"
            ):
                row["reconstruction"]["classification"] = "confirmed"
                row["classification"] = "confirmed"
        reconstruction_counts = {
            "confirmed": sum(item["classification"] == "confirmed" for item in final_regions),
            "inconclusive": sum(item["classification"] == "inconclusive" for item in final_regions),
            "failed": sum(item["classification"] == "failed" for item in final_regions),
        }
        _write_json(output_dir / "regions.json", {
            "initial": initial,
            "association": final_regions,
        })
        association_counts = {
            "exact_pixel_sha256": sum(bool(row.get("association_evidence", {}).get("exact_pixel_sha_match")) for row in associations),
            "raw_sha256": sum(bool(row.get("association_evidence", {}).get("raw_sha_match")) for row in associations),
            "tolerant_pixel": sum(row.get("selection_bucket") == "tolerant_pixel" for row in associations),
            "dct_equivalence": sum(row.get("selection_bucket") == "dct_equivalence" for row in associations),
            "unmatched": sum(row.get("selection_status") == "unmatched" for row in associations),
            "ambiguous": sum(row.get("selection_status") == "ambiguous" for row in associations),
        }
        report = {
            "target_url": url,
            "target_episode_id": expected_episode_id,
            "final_url": page.url,
            "captured_at": _now_iso(),
            "content_region_count": len(initial["regions"]),
            "source_count": sum(_source_is_content(record) for record in probe.source_records.values()),
            "transport_candidate_count": len(probe.saved_images),
            "old_j1_exact_association_count": association_counts["exact_pixel_sha256"],
            "production_selector": "screenshot_crawler.site_adapters.jumpplus.native_capture.select_transport_candidate",
            "association_counts": association_counts,
            "selection_status_counts": {
                status: sum(row.get("selection_status") == status for row in associations)
                for status in {str(row.get("selection_status")) for row in associations}
            },
            "reconstruction_counts": reconstruction_counts,
            "production_selector_dct_reconstruction_count": sum(
                row.get("reconstruction", {}).get("production_selector_dct", {}).get("jpeg_dct_reconstruction") == "successful"
                for row in final_regions
            ),
            "24_of_24_reconstruction": reconstruction_counts["confirmed"] == len(initial["regions"]),
            "scroll_performed": False,
            "scroll_required_for_capture": "not indicated; J1 already observed all 24 source identities/draw mappings without scroll, and J1.5 does not repeat lazy-load probing",
            "lazy_load_reinvestigated": False,
            "probe_draw_diagnostic": probe_diagnostic,
            "conclusion": (
                "A" if reconstruction_counts["confirmed"] == len(initial["regions"])
                else "B" if association_counts["unmatched"] == 0 and association_counts["ambiguous"] == 0
                else "C"
            ),
            "production_candidate": (
                "initial load -> enumerate all content canvases -> capture source snapshots -> "
                "associate with production selector -> existing Jump+ reconstruction; no scrolling indicated for capture"
            ),
            "residual": (
                "none"
                if reconstruction_counts["inconclusive"] == 0
                else "candidate association or evidence remains unresolved for the inconclusive regions; no failed claim is made"
            ),
            "reconstruction_report": "reconstructed/reconstruction_report.json",
            "errors": probe.errors,
        }
        _write_json(output_dir / "report.json", report)
        _write_text(output_dir / "summary.md", _make_summary(report))
        return report
    finally:
        await session.close_page(page)
        await session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Jump+ vertical J1.5 transport association probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    report = asyncio.run(run_probe(args.url, args.output_dir, args.cdp_endpoint))
    print(json.dumps({
        "content_region_count": report.get("content_region_count"),
        "source_count": report.get("source_count"),
        "transport_candidate_count": report.get("transport_candidate_count"),
        "association_counts": report.get("association_counts"),
        "reconstruction_counts": report.get("reconstruction_counts"),
        "conclusion": report.get("conclusion"),
        "output_dir": str(args.output_dir),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

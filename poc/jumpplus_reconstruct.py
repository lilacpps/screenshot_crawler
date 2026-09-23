"""J2 PoC: reconstruct Jump+ canvas output from transport JPEG draw mappings.

This is diagnostic code only.  It consumes a completed J1 output directory and
does not connect to a browser or change production capture behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

DEFAULT_INPUT_DIR = Path("output/jumpplus_probe")
DEFAULT_OUTPUT_DIR = Path("output/jumpplus_probe/j2")
IDENTITY = {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def decoded_pixel_sha256(image: Image.Image) -> str:
    """Hash RGB pixels, independent of PNG/JPEG encoding."""

    return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


def _is_identity_transform(transform: dict[str, Any] | None) -> bool:
    return bool(transform) and all(transform.get(key) == value for key, value in IDENTITY.items())


def _integer_value(value: Any) -> int | None:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    integer = round(value)
    return integer if abs(value - integer) < 1e-6 else None


def _rect_values(rect: dict[str, Any] | None, keys: tuple[str, ...]) -> tuple[int, ...] | None:
    if not rect:
        return None
    values = tuple(_integer_value(rect.get(key)) for key in keys)
    return values if all(value is not None for value in values) else None


def classify_draw_stage(draws: list[dict[str, Any]]) -> str:
    """Describe full-frame and tile calls without assuming one is disposable."""

    full = 0
    partial = 0
    for draw in draws:
        source = draw.get("source") or {}
        source_rect = draw.get("sourceRect") or {}
        destination = draw.get("destinationRect") or {}
        if (
            source_rect.get("sx") == 0
            and source_rect.get("sy") == 0
            and source_rect.get("sw") == source.get("naturalWidth")
            and source_rect.get("sh") == source.get("naturalHeight")
            and destination.get("dx") == 0
            and destination.get("dy") == 0
            and destination.get("dw") == (draw.get("canvas") or {}).get("width")
            and destination.get("dh") == (draw.get("canvas") or {}).get("height")
        ):
            full += 1
        else:
            partial += 1
    if full and partial:
        return "full_frame_plus_tiles"
    if full:
        return "full_frame_only"
    if partial:
        return "tiles_only"
    return "unknown"


def _visual_comparison(reconstructed: Image.Image, reference_path: Path, difference_path: Path) -> dict[str, Any]:
    """Compare only as a visual reference; this is not canvas pixel ground truth."""

    with Image.open(reference_path) as reference_source:
        reference = reference_source.convert("RGB")
        rendered = reconstructed.convert("RGB")
        resized_for_comparison = rendered.size != reference.size
        if rendered.size != reference.size:
            rendered = rendered.resize(reference.size, Image.Resampling.LANCZOS)
        difference = ImageChops.difference(rendered, reference)
        means = ImageStat.Stat(difference).mean
        pixels = reference.width * reference.height
        max_channel = max(channel.getextrema()[1] for channel in (
            difference.getchannel(0), difference.getchannel(1), difference.getchannel(2)
        ))
        nonzero = sum(value != 0 for value in difference.convert("L").tobytes())
        difference_path.parent.mkdir(parents=True, exist_ok=True)
        difference.save(difference_path)
        return {
            "reference_file": str(reference_path),
            "reference_dimensions": [reference.width, reference.height],
            "resized_for_comparison": resized_for_comparison,
            "mean_absolute_difference": sum(means) / 3,
            "max_channel_difference": max_channel,
            "different_pixel_count": nonzero,
            "different_pixel_ratio": nonzero / pixels if pixels else 0.0,
            "difference_file": str(difference_path),
            "assessment": "close" if sum(means) / 3 <= 12 else "visual_mismatch",
        }


def _candidate_index(candidate_images: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidate_images:
        pixel_sha = candidate.get("pixel_sha256")
        if pixel_sha:
            result.setdefault(str(pixel_sha), []).append(candidate)
    return result


def _state_paths(input_dir: Path, report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for state in report.get("states", []):
        name = str(state.get("state"))
        pixels_path = input_dir / "j1" / name / "pixels.json"
        if pixels_path.exists():
            result[name] = json.loads(pixels_path.read_text(encoding="utf-8"))
    return result


def _source_artifacts_by_id(pixels: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(item["sourceId"]): item
        for item in pixels.get("source_artifacts", [])
        if item.get("sourceId") is not None
    }


def _canvas_artifacts_by_id(pixels: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(item["canvasId"]): item
        for item in pixels.get("canvas_artifacts", [])
        if item.get("canvasId") is not None
    }


def _relative_path(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def reconstruct_canvas(
    *,
    input_dir: Path,
    output_dir: Path,
    state: dict[str, Any],
    pixels: dict[str, Any],
    candidates_by_pixel: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    canvas_id = state.get("canvas_id")
    canvas_id = int(canvas_id) if canvas_id is not None else None
    canvas_artifact = _canvas_artifacts_by_id(pixels).get(canvas_id) if canvas_id is not None else None
    width, height = (state.get("canvas_dimensions") or [None, None])[:2]
    state_name = str(state.get("state"))
    mapping_dir = output_dir / state_name
    mapping_path = mapping_dir / f"canvas_{canvas_id if canvas_id is not None else 'unknown':02}_mapping.json"
    reconstructed_path = mapping_dir / f"canvas_{canvas_id if canvas_id is not None else 'unknown':02}_reconstructed.png"
    difference_path = mapping_dir / f"canvas_{canvas_id if canvas_id is not None else 'unknown':02}_difference.png"
    source_by_id = _source_artifacts_by_id(pixels)
    draws = sorted(state.get("draw_calls", []), key=lambda item: item.get("sequence", 0))
    mapping: dict[str, Any] = {
        "state": state_name,
        "canvas_id": canvas_id,
        "width": width,
        "height": height,
        "draw_count": len(draws),
        "draw_stage": classify_draw_stage(draws),
        "sources": [],
        "draws": [],
        "unsupported": [],
        "unmatched_sources": [],
        "ignored_draws": [],
        "background_mode": "unknown",
    }
    if canvas_id is None or not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        mapping["unsupported"].append("missing_canvas_id_or_dimensions")
        _write_json(mapping_path, mapping)
        return {"mapping": mapping, "status": "inconclusive"}
    if not draws:
        mapping["unsupported"].append("no_draw_calls_observed")
        mapping["status"] = "inconclusive"
        _write_json(mapping_path, mapping)
        return {"mapping": mapping, "status": mapping["status"]}

    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    loaded_sources: dict[int, tuple[Image.Image, dict[str, Any], list[dict[str, Any]]]] = {}
    for sequence, draw in enumerate(draws):
        source = draw.get("source") or {}
        destination = _rect_values(draw.get("destinationRect"), ("dx", "dy", "dw", "dh"))
        source_url = str(source.get("url") or "")
        if source_url.endswith("/images/spacer.png") and destination:
            dx, dy, dw, dh = destination
            if dx + dw <= 0 or dy + dh <= 0 or dx >= width or dy >= height:
                mapping["ignored_draws"].append({
                    "sequence": draw.get("sequence", sequence),
                    "source_id": source.get("sourceId"),
                    "reason": "out_of_bounds_spacer_noop",
                    "destinationRect": draw.get("destinationRect"),
                })
                mapping["draws"].append({
                    "sequence": draw.get("sequence", sequence),
                    "source_id": source.get("sourceId"),
                    "status": "ignored_non_content_noop",
                    "reason": "out_of_bounds_spacer_noop",
                })
                continue
        source_id = source.get("sourceId")
        source_id = int(source_id) if source_id is not None else None
        source_artifact = source_by_id.get(source_id) if source_id is not None else None
        source_pixel_sha = source_artifact.get("pixel_sha256") if source_artifact else None
        candidates = candidates_by_pixel.get(str(source_pixel_sha), []) if source_pixel_sha else []
        if source_id is None or source_artifact is None or not candidates:
            mapping["unmatched_sources"].append({
                "sequence": draw.get("sequence", sequence),
                "source_id": source_id,
                "source_url": source.get("url"),
                "reason": "unmatched_source",
                "source_pixel_sha256": source_pixel_sha,
            })
            mapping["draws"].append({
                "sequence": draw.get("sequence", sequence),
                "source_id": source_id,
                "sourceRect": draw.get("sourceRect"),
                "destinationRect": draw.get("destinationRect"),
                "status": "unmatched_source",
            })
            continue
        candidate = candidates[0]
        if source_id not in loaded_sources:
            source_path = input_dir / str(candidate["file"])
            try:
                loaded_sources[source_id] = (
                    Image.open(source_path).convert("RGBA"),
                    source_artifact,
                    candidates,
                )
            except (OSError, ValueError) as exc:
                mapping["unmatched_sources"].append({
                    "sequence": draw.get("sequence", sequence),
                    "source_id": source_id,
                    "reason": "network_image_unreadable",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                mapping["draws"].append({
                    "sequence": draw.get("sequence", sequence),
                    "source_id": source_id,
                    "status": "unmatched_source",
                })
                continue
            mapping["sources"].append({
                "source_id": source_id,
                "source_url": source.get("url"),
                "network_file": candidate["file"],
                "network_candidates": [item["file"] for item in candidates],
                "pixel_sha256": source_pixel_sha,
                "matched_by": "decoded_pixel_sha256",
                "same_pixel_candidate_count": len(candidates),
            })
        source_image, source_artifact, candidates = loaded_sources[source_id]
        source_rect = _rect_values(draw.get("sourceRect"), ("sx", "sy", "sw", "sh"))
        issues: list[str] = []
        if source.get("type") != "HTMLImageElement":
            issues.append("unsupported_source_type")
        if draw.get("argumentForm") != "9-argument" or source_rect is None or destination is None:
            issues.append("unsupported_draw_argument_form")
        if not _is_identity_transform(draw.get("transform")):
            issues.append("unsupported_transform")
        if draw.get("globalCompositeOperation") != "source-over":
            issues.append("unsupported_composite")
        if draw.get("filter") not in (None, "none"):
            issues.append("unsupported_filter")
        if draw.get("globalAlpha") != 1:
            issues.append("unsupported_alpha")
        if source_rect and destination:
            sx, sy, sw, sh = source_rect
            dx, dy, dw, dh = destination
            if sw != dw or sh != dh:
                issues.append("scaled_draw_observed")
            if sx < 0 or sy < 0 or sw <= 0 or sh <= 0 or sx + sw > source_image.width or sy + sh > source_image.height:
                issues.append("source_rect_out_of_bounds")
            if dx < 0 or dy < 0 or dw <= 0 or dh <= 0 or dx + dw > width or dy + dh > height:
                issues.append("destination_rect_out_of_bounds")
        draw_record = {
            "sequence": draw.get("sequence", sequence),
            "source_id": source_id,
            "network_file": candidate["file"],
            "pixel_sha256": source_pixel_sha,
            "matched_by": "decoded_pixel_sha256",
            "sourceRect": draw.get("sourceRect"),
            "destinationRect": draw.get("destinationRect"),
            "status": "unsupported" if issues else "applied",
        }
        if issues:
            draw_record["issues"] = issues
            mapping["unsupported"].extend({"sequence": draw_record["sequence"], "reason": issue} for issue in issues)
        else:
            sx, sy, sw, sh = source_rect
            dx, dy, dw, dh = destination
            tile = source_image.crop((sx, sy, sx + sw, sy + sh))
            output.alpha_composite(tile, (dx, dy))
        mapping["draws"].append(draw_record)

    alpha_min, alpha_max = output.getchannel("A").getextrema()
    mapping["background_mode"] = "fully_opaque" if alpha_min == 255 and alpha_max == 255 else "rgba_transparent_uncovered"
    reconstructed_path.parent.mkdir(parents=True, exist_ok=True)
    if alpha_min == 255:
        output.convert("RGB").save(reconstructed_path)
    else:
        output.save(reconstructed_path)
    mapping["reconstructed_file"] = _relative_path(reconstructed_path, output_dir.parent)
    mapping["reconstructed_dimensions"] = [output.width, output.height]
    mapping["reconstructed_pixel_sha256"] = decoded_pixel_sha256(output)
    mapping["draw_count_applied"] = sum(item.get("status") == "applied" for item in mapping["draws"])
    mapping["draw_count_ignored"] = sum(
        item.get("status") == "ignored_non_content_noop" for item in mapping["draws"]
    )
    mapping["draw_count_unsupported"] = sum(item.get("status") == "unsupported" for item in mapping["draws"])
    if canvas_artifact and canvas_artifact.get("file"):
        reference_path = input_dir / str(canvas_artifact["file"])
        if reference_path.exists():
            mapping["visual_comparison"] = _visual_comparison(output, reference_path, difference_path)
    all_supported = not mapping["unsupported"] and not mapping["unmatched_sources"]
    visual_close = mapping.get("visual_comparison", {}).get("assessment") == "close"
    mapping["status"] = "confirmed" if all_supported and visual_close else (
        "likely" if all_supported else "inconclusive"
    )
    _write_json(mapping_path, mapping)
    return {"mapping": mapping, "status": mapping["status"]}


def _mapping_pattern(report: dict[str, Any]) -> tuple[Any, ...]:
    pattern = []
    for draw in report.get("draws", []):
        pattern.append((
            draw.get("sourceRect", {}).get("sx"),
            draw.get("sourceRect", {}).get("sy"),
            draw.get("sourceRect", {}).get("sw"),
            draw.get("sourceRect", {}).get("sh"),
            draw.get("destinationRect", {}).get("dx"),
            draw.get("destinationRect", {}).get("dy"),
            draw.get("destinationRect", {}).get("dw"),
            draw.get("destinationRect", {}).get("dh"),
        ))
    return tuple(pattern)


def make_summary(report: dict[str, Any]) -> str:
    states = report.get("states", [])
    status_counts = Counter(state.get("status") for state in states)
    active_states = [
        state for state in states if state.get("mapping", {}).get("draw_count", 0) > 0
    ]
    patterns = {_mapping_pattern(state.get("mapping", {})) for state in active_states}
    tile_sizes = Counter(
        (draw.get("sourceRect", {}).get("sw"), draw.get("sourceRect", {}).get("sh"))
        for state in active_states
        for draw in state.get("mapping", {}).get("draws", [])
        if draw.get("sourceRect") and draw.get("status") == "applied"
    )
    all_confirmed = bool(active_states) and all(state.get("status") == "confirmed" for state in active_states)
    lines = [
        "# Jump+ J2 lossless reconstruction PoC summary",
        "",
        f"- input: `{report.get('input_dir')}`",
        f"- target episode ID: `{report.get('target_episode_id')}`",
        f"- states/canvas reconstructions: `{len(states)}`",
        f"- status counts: `{json.dumps(dict(status_counts), ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Reconstruction method",
        "",
        "- Candidate transport images were selected by decoded RGB pixel SHA-256 equality between J1 blob source and network JPEG.",
        "- Draw calls were filtered by `canvas.id == captured canvasId` and replayed in recorded `sequence` order.",
        "- Supported path was restricted to HTMLImageElement, 9-argument drawImage, identity transform, source-over, filter none, alpha 1, and integer crop/paste with no scaling.",
        "- locator screenshots were used only as visual references; they were not treated as raw canvas pixel ground truth.",
        "",
        "## Mapping observations",
        "",
        f"- applied tile source-rect sizes: `{json.dumps(tile_sizes.most_common(), ensure_ascii=False)}`",
        f"- mapping geometry pattern: `{'fixed across observed canvases' if len(patterns) == 1 else 'variable / page-dependent'}`",
        f"- draw stage classifications: `{json.dumps(dict(Counter(state.get('mapping', {}).get('draw_stage') for state in active_states)), ensure_ascii=False, sort_keys=True)}`",
        "- Full-frame and partial tile calls were retained and replayed in sequence; no call was discarded solely because it was a staging-looking full-frame draw.",
        "",
        "## Per-canvas results",
        "",
    ]
    for state in states:
        mapping = state.get("mapping", {})
        visual = mapping.get("visual_comparison", {})
        lines.append(
            f"- `{state.get('state')}` canvas `{state.get('canvas_id')}`: `{state.get('status')}`, draws `{mapping.get('draw_count_applied', 0)}/{mapping.get('draw_count', 0)}` applied, ignored `{mapping.get('draw_count_ignored', 0)}`, unmatched `{len(mapping.get('unmatched_sources', []))}`, unsupported `{len(mapping.get('unsupported', []))}`, visual `{visual.get('assessment', 'not_observed')}`"
        )
    lines.extend([
        "",
        "## Capture recommendation",
        "",
        f"- J2 reconstruction: `{'confirmed' if all_confirmed else 'inconclusive / requires further investigation'}`.",
        "- Option A (runtime draw mapping reuse) remains the preferred candidate because mappings are taken from the actual page draw sequence.",
        "- Option B (static permutation) is not adopted; it is only safe if the observed geometry is proven fixed across more pages.",
        "- Production Site Adapter implementation is not included in this PoC.",
        "",
        "## Unknowns",
        "",
        "- Locator screenshot comparison is visual evidence only because raw canvas export is tainted.",
        "- Any unmatched source, scaled draw, unsupported operation, or missing stage keeps the result from being confirmed.",
    ])
    return "\n".join(lines) + "\n"


def run_reconstruction(input_dir: Path, output_dir: Path, max_states: int | None = None) -> dict[str, Any]:
    report_path = input_dir / "j1" / "comparison_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidate_images = report.get("candidate_images", [])
    candidates_by_pixel = _candidate_index(candidate_images)
    pixels_by_state = _state_paths(input_dir, report)
    states: list[dict[str, Any]] = []
    for state in report.get("states", [])[:max_states]:
        state_name = str(state.get("state"))
        pixels = pixels_by_state.get(state_name, {})
        for canvas in state.get("canvas_comparisons", []):
            result = reconstruct_canvas(
                input_dir=input_dir,
                output_dir=output_dir,
                state=canvas,
                pixels=pixels,
                candidates_by_pixel=candidates_by_pixel,
            )
            states.append({
                "state": state_name,
                "canvas_id": canvas.get("canvas_id"),
                "status": result["status"],
                "mapping": result["mapping"],
            })
    output = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "target_episode_id": report.get("target_episode_id"),
        "states": states,
    }
    _write_json(output_dir / "reconstruction_report.json", output)
    _write_text(output_dir / "summary.md", make_summary(output))
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconstruct Jump+ pages from J1 drawImage mappings")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-states", type=int, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_reconstruction(args.input_dir, args.output_dir, args.max_states)
    print(json.dumps({"states": len(result["states"]), "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

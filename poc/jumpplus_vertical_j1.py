"""Read-only J1 probe for initial-load and lazy-load behavior of Jump+ vertical pages.

This probe intentionally stays outside production capture.  It reuses the
existing vertical DOM probe, canvas draw hook, transport response collector,
and J2 reconstruction implementation.  A single fresh page is observed at
T0/T2/T5/T10/T20 without scrolling; only when the initial state is incomplete
are five bounded ``scrollIntoView`` probes performed.

Example::

    .\\.venv\\Scripts\\python.exe poc\\jumpplus_vertical_j1.py `
        --url https://shonenjumpplus.com/episode/10834108156642491399 `
        --output-dir output\\jumpplus_vertical_j1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

try:
    from poc.jumpplus_probe import (
        _DRAW_HOOK,
        _decoded_pixel_sha256,
        _now_iso,
        _write_json,
        _write_text,
        canvas_mutations_for_canvas,
        draw_calls_for_canvas,
        extract_episode_id,
        is_target_episode_url,
    )
    from poc.jumpplus_reconstruct import run_reconstruction
    from poc.jumpplus_vertical_probe import (
        _VERTICAL_SCROLL_ACTION_SCRIPT,
        STABILITY_TIMEOUT_SECONDS,
        VerticalProbe,
        scroll_position,
    )
except ModuleNotFoundError:  # direct ``python poc/<probe>.py`` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from poc.jumpplus_probe import (
        _DRAW_HOOK,
        _decoded_pixel_sha256,
        _now_iso,
        _write_json,
        _write_text,
        canvas_mutations_for_canvas,
        draw_calls_for_canvas,
        extract_episode_id,
        is_target_episode_url,
    )
    from poc.jumpplus_reconstruct import run_reconstruction
    from poc.jumpplus_vertical_probe import (
        _VERTICAL_SCROLL_ACTION_SCRIPT,
        STABILITY_TIMEOUT_SECONDS,
        VerticalProbe,
        scroll_position,
    )


DEFAULT_URL = "https://shonenjumpplus.com/episode/10834108156642491399"
DEFAULT_OUTPUT_DIR = Path("output/jumpplus_vertical_j1")
TIMELINE_POINTS = (("t00", 0.0), ("t02", 2.0), ("t05", 5.0), ("t10", 10.0), ("t20", 20.0))
SCROLL_TARGETS = (0, 5, 12, 18, 23)
MAX_IMAGE_RESPONSES_J1 = 64
MAX_SOURCE_SNAPSHOTS_J1 = 64
MAX_SCROLL_PROBES = 5

_SOURCE_CAPTURE_SCRIPT = r"""
() => window.__jumpplusProbe?.captureImageSources?.({}) || []
"""


def _vertical_j1_draw_hook() -> str:
    """Keep the existing hook but raise only its diagnostic source cap."""

    return _DRAW_HOOK.replace(
        "if (items.length >= 20) break;",
        f"if (items.length >= {MAX_SOURCE_SNAPSHOTS_J1}) break;",
    )


def _content_regions(dom: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in dom.get("regions", []) if item.get("isContentPage")]


def _identity_key(source_id: Any, url: Any) -> tuple[Any, str]:
    return (source_id, str(url or ""))


def _region_distance(region: dict[str, Any], viewport_height: float | None) -> dict[str, Any]:
    rect = region.get("renderedRect") or {}
    top = float(rect.get("top") or 0)
    bottom = float(rect.get("bottom") or 0)
    height = float(viewport_height or 0)
    if bottom < 0:
        return {"pixels": round(-bottom, 3), "direction": "above"}
    if top > height:
        return {"pixels": round(top - height, 3), "direction": "below"}
    return {"pixels": 0.0, "direction": "in_viewport"}


def _is_full_frame(draw: dict[str, Any], canvas_width: int | None, canvas_height: int | None) -> bool:
    source = draw.get("source") or {}
    source_rect = draw.get("sourceRect") or {}
    destination = draw.get("destinationRect") or {}
    return bool(
        canvas_width
        and canvas_height
        and source_rect.get("sx") == 0
        and source_rect.get("sy") == 0
        and source_rect.get("sw") == source.get("naturalWidth")
        and source_rect.get("sh") == source.get("naturalHeight")
        and destination.get("dx") == 0
        and destination.get("dy") == 0
        and destination.get("dw") == canvas_width
        and destination.get("dh") == canvas_height
    )


def _is_ignored_spacer_draw(draw: dict[str, Any], canvas_width: int | None, canvas_height: int | None) -> bool:
    source_url = str((draw.get("source") or {}).get("url") or "")
    destination = draw.get("destinationRect") or {}
    if not source_url.endswith("/images/spacer.png"):
        return False
    dx = float(destination.get("dx") or 0)
    dy = float(destination.get("dy") or 0)
    dw = float(destination.get("dw") or 0)
    dh = float(destination.get("dh") or 0)
    width = float(canvas_width or 0)
    height = float(canvas_height or 0)
    return dx + dw <= 0 or dy + dh <= 0 or dx >= width or dy >= height


def _source_records_for_draws(
    draws: list[dict[str, Any]], source_records: dict[tuple[Any, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, str]] = set()
    for draw in draws:
        source = draw.get("source") or {}
        key = _identity_key(source.get("sourceId"), source.get("url"))
        if key in seen or (key[0] is None and not key[1]) or key[1].endswith("/images/spacer.png"):
            continue
        seen.add(key)
        result.append(source_records.get(key, {"sourceId": key[0], "url": key[1], "file": None}))
    return result


def build_region_states(
    dom: dict[str, Any],
    draw_calls: list[dict[str, Any]],
    source_records: dict[tuple[Any, str], dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build stage-separated region state from observed evidence only."""

    candidates_by_pixel: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        pixel_sha = candidate.get("pixel_sha256")
        if pixel_sha:
            candidates_by_pixel.setdefault(str(pixel_sha), []).append(candidate)
    viewport_height = (dom.get("viewport") or {}).get("height")
    rows: list[dict[str, Any]] = []
    for region in _content_regions(dom):
        image = region.get("image") or {}
        canvas_id = image.get("canvasId")
        width = image.get("width")
        height = image.get("height")
        mounted = bool(canvas_id is not None and width and height)
        region_draws = draw_calls_for_canvas(draw_calls, canvas_id)
        effective_draws = [
            item for item in region_draws
            if not _is_ignored_spacer_draw(item, width, height)
        ]
        identities = _source_records_for_draws(region_draws, source_records)
        source_available = bool(identities)
        source_snapshot_available = bool(identities) and all(item.get("file") for item in identities)
        full_frame = any(_is_full_frame(item, width, height) for item in effective_draws)
        partial_draws = [item for item in effective_draws if not _is_full_frame(item, width, height)]
        partial_mapping_count = sum(bool(item.get("sourceRect")) for item in partial_draws)
        draw_ready = bool(region_draws and full_frame and (partial_mapping_count or len(region_draws) == 1))
        matching_candidates: list[dict[str, Any]] = []
        candidate_counts: list[int] = []
        candidate_association = "unavailable"
        for identity in identities:
            matches = candidates_by_pixel.get(str(identity.get("pixel_sha256")), []) if identity.get("pixel_sha256") else []
            matching_candidates.extend(matches)
            candidate_counts.append(len(matches))
        if identities and source_snapshot_available:
            if all(count > 0 for count in candidate_counts):
                candidate_association = "matched"
            elif candidates:
                candidate_association = "candidate_association_failed"
            else:
                candidate_association = "network_response_unavailable"
        transport_ready = bool(identities and source_snapshot_available and candidate_association == "matched")
        reconstructable = bool(mounted and source_available and draw_ready and transport_ready)
        if not mounted:
            reason = "canvas_not_mounted"
        elif not region_draws:
            reason = "drawImage_not_observed"
        elif not source_available:
            reason = "source_identity_missing"
        elif not draw_ready:
            reason = "mapping_incomplete"
        elif not source_snapshot_available:
            reason = "source_snapshot_unavailable"
        elif candidate_association == "network_response_unavailable":
            reason = "network_response_unavailable"
        elif candidate_association == "candidate_association_failed":
            reason = "candidate_association_failed"
        else:
            reason = None
        rows.append(
            {
                "index": region.get("index"),
                "canvas_id": canvas_id,
                "canvas_dimensions": [width, height],
                "mounted": mounted,
                "distance_from_viewport": _region_distance(region, viewport_height),
                "in_viewport": bool(region.get("inViewport")),
                "intersection_ratio": region.get("intersectionRatio"),
                "draw_image_call_count": len(region_draws),
                "effective_draw_image_call_count": len(effective_draws),
                "ignored_non_content_draw_count": len(region_draws) - len(effective_draws),
                "full_frame_draw": full_frame,
                "partial_mapping_count": partial_mapping_count,
                "draw_ready": draw_ready,
                "source_ids": [item.get("sourceId") for item in identities],
                "source_urls": [item.get("url") for item in identities],
                "source_available": source_available,
                "source_snapshot_available": source_snapshot_available,
                "source_snapshot_files": [item.get("file") for item in identities if item.get("file")],
                "transport_ready": transport_ready,
                "transport_candidate_count": len(matching_candidates),
                "transport_candidate_urls": [item.get("url") for item in matching_candidates],
                "candidate_association": candidate_association,
                "reconstructable": reconstructable,
                "unavailable_reason": reason,
                "classification": "inconclusive",
            }
        )
    return rows


def classify_reconstruction(mapping: dict[str, Any] | None, evidence: dict[str, Any]) -> str:
    """Classify actual J2 output; missing evidence remains inconclusive."""

    if not mapping:
        return "inconclusive"
    if mapping.get("jpeg_dct_reconstruction") == "successful":
        return "confirmed"
    if mapping.get("pixel_reconstruction") == "successful":
        return "confirmed"
    if mapping.get("pixel_reconstruction") == "failed" or mapping.get("status") == "failed":
        return "failed"
    if evidence.get("reconstructable") and mapping.get("mapping_status") == "unsupported":
        return "failed"
    return "inconclusive"


def prefetch_bucket(distances: list[float], viewport_height: float | None) -> str:
    if not distances:
        return "not_observed"
    height = float(viewport_height or 0)
    if height <= 0:
        return "unknown"
    ratio = max(distances) / height
    if ratio <= 1:
        return "viewport_or_within_one_screen"
    if ratio <= 3:
        return "a_few_screens"
    return "far_prefetch"


def _count(rows: list[dict[str, Any]], field: str) -> int:
    return sum(bool(row.get(field)) for row in rows)


def _meaningful_source_count(source_records: dict[tuple[Any, str], dict[str, Any]]) -> int:
    return sum(
        not str(record.get("url") or "").endswith("/images/spacer.png")
        for record in source_records.values()
    )


class VerticalJ1Probe(VerticalProbe):
    """VerticalProbe with a larger research-only response/source bound."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_image_responses", MAX_IMAGE_RESPONSES_J1)
        super().__init__(*args, **kwargs)
        self.all_draw_calls: list[dict[str, Any]] = []
        self.all_canvas_mutations: list[dict[str, Any]] = []
        self.source_records: dict[tuple[Any, str], dict[str, Any]] = {}
        self.stage_records: list[dict[str, Any]] = []
        self.references: dict[int, str] = {}

    async def capture_source_snapshots(self) -> None:
        try:
            items = await self.page.evaluate(_SOURCE_CAPTURE_SCRIPT)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"J1 source snapshot failed: {type(exc).__name__}: {exc}")
            return
        source_dir = self.output_dir / "sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            key = _identity_key(item.get("sourceId"), item.get("url"))
            if key in self.source_records:
                continue
            record = {key_name: value for key_name, value in item.items() if key_name != "dataUrl"}
            file_path = self._save_data_url(
                item.get("dataUrl"),
                source_dir / f"source_{item.get('sourceId', len(self.source_records)):03d}.png",
            )
            record["file"] = file_path
            if file_path:
                try:
                    record["decoded_dimensions"], record["pixel_sha256"] = _decoded_pixel_sha256(
                        self.output_dir / file_path
                    )
                    record["pixel_color_space"] = "RGB"
                except BaseException as exc:  # noqa: BLE001
                    record["pixel_error"] = f"{type(exc).__name__}: {exc}"
            if item.get("error"):
                record["error"] = item["error"]
            self.source_records[key] = record
        _write_json(self.output_dir / "sources.json", list(self.source_records.values()))

    async def record_stage(self, name: str, wait_seconds: float | None = None) -> dict[str, Any]:
        observation = await self.collect_vertical_snapshot(name, include_html=name == "timeline/t00")
        draw = observation.get("draw") or {}
        self.all_draw_calls.extend(draw.get("drawCalls", []))
        self.all_canvas_mutations.extend(draw.get("canvasMutations", []))
        await self.capture_source_snapshots()
        rows = build_region_states(
            observation.get("dom", {}),
            self.all_draw_calls,
            self.source_records,
            self.saved_images,
        )
        record = {
            "name": name,
            "wait_seconds": wait_seconds,
            "captured_at": _now_iso(),
            "directory": str(Path(observation["directory"]).relative_to(self.output_dir)),
            "scroll": scroll_position(observation.get("dom", {})),
            "content_region_count": len(rows),
            "mounted_count": _count(rows, "mounted"),
            "source_available_count": _count(rows, "source_available"),
            "draw_ready_count": _count(rows, "draw_ready"),
            "transport_ready_count": _count(rows, "transport_ready"),
            "reconstructable_count": _count(rows, "reconstructable"),
            "draw_call_count": len(self.all_draw_calls),
            "source_count": _meaningful_source_count(self.source_records),
            "transport_candidate_count": len(self.saved_images),
            "regions": rows,
        }
        _write_json(self.output_dir / name / "regions.json", record)
        self.stage_records.append(record)
        return record

    async def capture_reference(self, index: int, stage_name: str) -> str | None:
        if index in self.references:
            return self.references[index]
        before = await self.page.evaluate(
            """() => ({windowY: Number(scrollY) || 0, contentTop: Number(document.querySelector('#content')?.scrollTop) || 0})"""
        )
        try:
            areas = self.page.locator(".image-container.js-viewer-content .page-area.js-page-area")
            area = areas.nth(index)
            canvas = area.locator("canvas.page-image.js-page-image, canvas").first
            if await canvas.count() != 1:
                return None
            path = self.output_dir / "references" / f"region_{index:03d}.png"
            await canvas.screenshot(path=str(path), animations="disabled", scale="device")
            relative = str(path.relative_to(self.output_dir))
            try:
                dimensions, pixel_sha = _decoded_pixel_sha256(path)
            except BaseException as exc:  # noqa: BLE001
                dimensions, pixel_sha = None, None
                self.errors.append(f"reference hash failed for region {index}: {type(exc).__name__}: {exc}")
            self.references[index] = relative
            _write_json(
                self.output_dir / "references" / f"region_{index:03d}.json",
                {"index": index, "stage": stage_name, "file": relative, "dimensions": dimensions, "pixel_sha256": pixel_sha},
            )
            return relative
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"reference screenshot failed for region {index}: {type(exc).__name__}: {exc}")
            return None
        finally:
            try:
                await self.page.evaluate(
                    """({windowY, contentTop}) => { window.scrollTo(0, windowY); const content = document.querySelector('#content'); if (content) content.scrollTop = contentTop; }""",
                    before,
                )
                await self.wait_for_scroll_stability(timeout=4.0)
            except BaseException as exc:  # noqa: BLE001
                self.errors.append(f"reference scroll restore failed: {type(exc).__name__}: {exc}")

    async def run_scroll_probe(self, target_index: int, probe_index: int) -> dict[str, Any]:
        prefix = f"scroll_probes/probe_{probe_index:02d}_region_{target_index:02d}"
        before = await self.record_stage(f"{prefix}/before")
        event_start = len(self.network_events)
        candidate_start = len(self.saved_images)
        await self.page.evaluate(
            _VERTICAL_SCROLL_ACTION_SCRIPT,
            {"operation": "scrollIntoView", "amount": 0, "targetIndex": target_index},
        )
        stable = await self.wait_for_scroll_stability(timeout=STABILITY_TIMEOUT_SECONDS)
        await self.wait_for_stability(timeout=5.0)
        after = await self.record_stage(f"{prefix}/after")
        before_by_index = {int(row["index"]): row for row in before["regions"]}
        after_by_index = {int(row["index"]): row for row in after["regions"]}
        newly_source = [
            index for index, row in after_by_index.items()
            if row.get("source_available") and not before_by_index.get(index, {}).get("source_available")
        ]
        newly_draw = [
            index for index, row in after_by_index.items()
            if row.get("draw_ready") and not before_by_index.get(index, {}).get("draw_ready")
        ]
        newly_transport = [
            index for index, row in after_by_index.items()
            if row.get("transport_ready") and not before_by_index.get(index, {}).get("transport_ready")
        ]
        newly_reconstructable = [
            index for index, row in after_by_index.items()
            if row.get("reconstructable") and not before_by_index.get(index, {}).get("reconstructable")
        ]
        before_dom = json.loads(
            (self.output_dir / before["directory"] / "dom.json").read_text(encoding="utf-8")
        )
        height = (before_dom.get("viewport") or {}).get("height")
        distances = [
            float(before_by_index[index].get("distance_from_viewport", {}).get("pixels") or 0)
            for index in newly_source
        ]
        record = {
            "probe_index": probe_index,
            "target_index": target_index,
            "stable": bool(stable),
            "before_stage": before["name"],
            "after_stage": after["name"],
            "before_scroll": before["scroll"],
            "after_scroll": after["scroll"],
            "source_count_before": before["source_count"],
            "source_count_after": after["source_count"],
            "draw_call_count_before": before["draw_call_count"],
            "draw_call_count_after": after["draw_call_count"],
            "transport_candidate_count_before": before["transport_candidate_count"],
            "transport_candidate_count_after": after["transport_candidate_count"],
            "new_network_image_responses": [
                event.get("url") for event in self.network_events[event_start:]
                if event.get("event") == "response" and event.get("classification") == "image"
            ],
            "new_saved_image_count": len(self.saved_images) - candidate_start,
            "new_source_available_indices": newly_source,
            "new_draw_ready_indices": newly_draw,
            "new_transport_ready_indices": newly_transport,
            "new_reconstructable_indices": newly_reconstructable,
            "newly_loaded_distance_from_viewport_before": distances,
            "prefetch_bucket": prefetch_bucket(distances, height),
        }
        _write_json(self.output_dir / prefix / "probe.json", record)
        if target_index in after_by_index and after_by_index[target_index].get("reconstructable"):
            await self.capture_reference(target_index, after["name"])
        return record

    def _copy_initial_artifacts(self) -> None:
        source = self.output_dir / "timeline" / "t00"
        target = self.output_dir / "initial"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("dom.json", "network.json", "draw_calls.json", "scripts.json", "links.json", "page.html", "screenshot.png"):
            source_file = source / name
            if not source_file.exists():
                continue
            target_file = target / name
            if source_file.suffix in {".json", ".html"}:
                target_file.write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                shutil.copyfile(source_file, target_file)

    def _write_reconstruction_input(self, final_stage: dict[str, Any]) -> list[dict[str, Any]]:
        state_name = "final"
        state_dir = self.output_dir / "j1" / state_name
        state_dir.mkdir(parents=True, exist_ok=True)
        canvas_comparisons: list[dict[str, Any]] = []
        for row in final_stage["regions"]:
            canvas_id = row.get("canvas_id")
            canvas_comparisons.append(
                {
                    "state": state_name,
                    "canvas_index": row.get("index"),
                    "canvas_id": canvas_id,
                    "canvas_dimensions": row.get("canvas_dimensions"),
                    "draw_calls": draw_calls_for_canvas(self.all_draw_calls, canvas_id),
                    "canvas_mutations": canvas_mutations_for_canvas(self.all_canvas_mutations, canvas_id),
                    "content_mutations": [
                        item for item in canvas_mutations_for_canvas(self.all_canvas_mutations, canvas_id)
                        if item.get("operation") in {"clearRect", "fillRect", "putImageData"}
                    ],
                }
            )
        canvas_artifacts = [
            {
                "index": row.get("index"),
                "canvasId": row.get("canvas_id"),
                "width": (row.get("canvas_dimensions") or [None, None])[0],
                "height": (row.get("canvas_dimensions") or [None, None])[1],
                "file": self.references.get(int(row["index"])) if row.get("index") is not None else None,
            }
            for row in final_stage["regions"]
        ]
        pixels = {
            "state": state_name,
            "url": self.target_url,
            "canvas_artifacts": canvas_artifacts,
            "source_artifacts": list(self.source_records.values()),
            "draw_calls": self.all_draw_calls,
            "canvas_mutations": self.all_canvas_mutations,
            "content_mutations": [
                item for item in self.all_canvas_mutations
                if item.get("operation") in {"clearRect", "fillRect", "putImageData"}
            ],
            "renderer_events": [],
        }
        _write_json(state_dir / "pixels.json", pixels)
        report = {
            "target_episode_id": self.expected_episode_id,
            "candidate_images": self.saved_images,
            "states": [{"state": state_name, "canvas_comparisons": canvas_comparisons}],
        }
        _write_json(self.output_dir / "j1" / "candidate_images.json", self.saved_images)
        _write_json(self.output_dir / "j1" / "comparison_report.json", report)
        return canvas_comparisons

    def _apply_reconstruction_results(
        self,
        final_stage: dict[str, Any],
        reconstruction: dict[str, Any],
    ) -> dict[str, Any]:
        by_canvas = {int(item["canvas_id"]): item for item in reconstruction.get("states", []) if item.get("canvas_id") is not None}
        final_rows: list[dict[str, Any]] = []
        for row in final_stage["regions"]:
            enriched = dict(row)
            actual = by_canvas.get(int(row["canvas_id"])) if row.get("canvas_id") is not None else None
            mapping = (actual or {}).get("mapping")
            enriched["reconstruction"] = {
                "status": (actual or {}).get("status", "inconclusive"),
                "classification": classify_reconstruction(mapping, row),
                "mapping_status": (mapping or {}).get("mapping_status"),
                "pixel_reconstruction": (mapping or {}).get("pixel_reconstruction"),
                "jpeg_dct_feasibility": (mapping or {}).get("jpeg_dct_feasibility"),
                "jpeg_dct_reconstruction": (mapping or {}).get("jpeg_dct_reconstruction"),
                "visual_reference": (mapping or {}).get("visual_reference"),
                "mapping_file": (mapping or {}).get("reconstructed_file"),
            }
            enriched["classification"] = enriched["reconstruction"]["classification"]
            final_rows.append(enriched)
        return {
            "regions": final_rows,
            "confirmed_count": sum(row.get("classification") == "confirmed" for row in final_rows),
            "inconclusive_count": sum(row.get("classification") == "inconclusive" for row in final_rows),
            "failed_count": sum(row.get("classification") == "failed" for row in final_rows),
        }

    async def run(self, url: str) -> dict[str, Any]:
        self.target_url = url
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.install_listeners()
        await self.page.add_init_script(script=_vertical_j1_draw_hook())
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"goto failed: {type(exc).__name__}: {exc}")
        await self.wait_for_stability(timeout=12.0)
        await self.wait_for_scroll_stability(timeout=5.0)
        timeline_start = time.monotonic()
        for label, target_seconds in TIMELINE_POINTS:
            remaining = target_seconds - (time.monotonic() - timeline_start)
            if remaining > 0:
                await asyncio.sleep(remaining)
            stage = await self.record_stage(f"timeline/{label}", wait_seconds=target_seconds)
            if label == "t00":
                self._copy_initial_artifacts()
                await self.capture_reference(0, stage["name"])
        initial = self.stage_records[0]
        wait20 = self.stage_records[-1]
        scroll_records: list[dict[str, Any]] = []
        if initial["reconstructable_count"] < initial["content_region_count"]:
            targets = [
                index for index in SCROLL_TARGETS
                if index < initial["content_region_count"]
            ][:MAX_SCROLL_PROBES]
            for probe_index, target_index in enumerate(targets, start=1):
                if not is_target_episode_url(self.page.url, self.expected_episode_id):
                    self.stopped_reason = "target episode URL changed during J1 scroll probe"
                    break
                scroll_records.append(await self.run_scroll_probe(target_index, probe_index))
        await self.drain_image_tasks()
        final_stage = self.stage_records[-1]
        for row in final_stage["regions"]:
            if row.get("reconstructable") and row.get("index") is not None:
                await self.capture_reference(int(row["index"]), final_stage["name"])
        reconstruction: dict[str, Any]
        try:
            self._write_reconstruction_input(final_stage)
            reconstruction = run_reconstruction(
                input_dir=self.output_dir,
                output_dir=self.output_dir / "reconstructed",
            )
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"J2 reconstruction run failed: {type(exc).__name__}: {exc}")
            reconstruction = {"states": [], "error": f"{type(exc).__name__}: {exc}"}
        final_result = self._apply_reconstruction_results(final_stage, reconstruction)
        _write_json(self.output_dir / "draw_calls.json", {"draw_calls": self.all_draw_calls, "canvas_mutations": self.all_canvas_mutations})
        _write_json(self.output_dir / "network.json", {"events": self.network_events, "saved_images": self.saved_images})
        _write_json(self.output_dir / "candidate_images.json", self.saved_images)
        _write_json(
            self.output_dir / "timeline.json",
            {"points": self.stage_records, "scroll_probes": scroll_records},
        )
        _write_json(
            self.output_dir / "regions.json",
            {"timeline": self.stage_records, "scroll_probes": scroll_records, "final": final_result},
        )
        initial_rows = initial["regions"]
        wait_rows = wait20["regions"]
        final_rows = final_result["regions"]
        initial_reconstructable = _count(initial_rows, "reconstructable")
        wait20_reconstructable = _count(wait_rows, "reconstructable")
        final_reconstructable = _count(final_rows, "reconstructable")
        scroll_added = any(record.get("new_reconstructable_indices") for record in scroll_records)
        wait_added = wait20_reconstructable > initial_reconstructable
        if initial_reconstructable == initial["content_region_count"]:
            conclusion = "A"
            production = "initial load -> enumerate content regions -> reconstruct all; navigation is not required for this episode/state"
        elif final_reconstructable == initial["content_region_count"]:
            conclusion = "B"
            production = "initial load -> save reconstructable regions -> scrollIntoView next unready region -> bounded settle -> reconstruct"
        else:
            conclusion = "C"
            production = "initial load capture is sufficient for observed regions; scroll did not add missing evidence, so resolve candidate association before deciding whether scroll is needed"
        lazy_load = bool(wait_added or scroll_added or any(record.get("new_source_available_indices") for record in scroll_records))
        report = {
            "target_url": url,
            "target_episode_id": self.expected_episode_id,
            "final_url": self.page.url,
            "content_region_count": initial["content_region_count"],
            "timeline_points": [
                {
                    "name": record["name"],
                    "wait_seconds": record["wait_seconds"],
                    "mounted_count": record["mounted_count"],
                    "source_available_count": record["source_available_count"],
                    "draw_ready_count": record["draw_ready_count"],
                    "transport_ready_count": record["transport_ready_count"],
                    "reconstructable_count": record["reconstructable_count"],
                    "draw_call_count": record["draw_call_count"],
                    "source_count": record["source_count"],
                    "transport_candidate_count": record["transport_candidate_count"],
                }
                for record in self.stage_records[: len(TIMELINE_POINTS)]
            ],
            "scroll_probes": scroll_records,
            "initial_reconstructable_count": initial_reconstructable,
            "wait_20s_reconstructable_count": wait20_reconstructable,
            "scroll_final_reconstructable_count": final_reconstructable,
            "final_reconstruction": final_result,
            "lazy_load_observed": lazy_load,
            "wait_only_increased_load": wait_added,
            "scroll_increased_load": scroll_added,
            "prefetch_buckets": sorted({record.get("prefetch_bucket") for record in scroll_records}),
            "conclusion": conclusion,
            "production_candidate": production,
            "saved_network_images": self.saved_images,
            "source_count_final": _meaningful_source_count(self.source_records),
            "draw_call_count_final": len(self.all_draw_calls),
            "references": self.references,
            "reconstruction_report": "reconstructed/reconstruction_report.json",
            "stopped_reason": self.stopped_reason,
            "errors": self.errors,
        }
        _write_json(self.output_dir / "report.json", report)
        _write_text(self.output_dir / "summary.md", make_summary(report))
        return report


def make_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Jump+ Vertical J1: initial load / lazy load / reconstruction",
        "",
        "## Target",
        "",
        f"- URL: `{report.get('target_url')}`",
        f"- content regions: `{report.get('content_region_count')}`",
        f"- conclusion: `{report.get('conclusion')}`",
        "",
        "## Unscrolled timeline",
        "",
        "| point | mounted | source | draw ready | transport | reconstructable | draws | sources | candidates |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for point in report.get("timeline_points", []):
        lines.append(
            f"| `{point['name']}` | {point['mounted_count']} | {point['source_available_count']} | "
            f"{point['draw_ready_count']} | {point['transport_ready_count']} | {point['reconstructable_count']} | "
            f"{point['draw_call_count']} | {point['source_count']} | {point['transport_candidate_count']} |"
        )
    lines.extend(
        [
            "",
            "## Required answers",
            "",
            f"- initial reconstructable: `{report.get('initial_reconstructable_count')}/{report.get('content_region_count')}`",
            f"- after waiting 20s: `{report.get('wait_20s_reconstructable_count')}/{report.get('content_region_count')}`",
            f"- after bounded scroll probes: `{report.get('scroll_final_reconstructable_count')}/{report.get('content_region_count')}`",
            f"- wait alone increased load: `{report.get('wait_only_increased_load')}`",
            f"- scroll increased load: `{report.get('scroll_increased_load')}`",
            f"- lazy load observed: `{report.get('lazy_load_observed')}`",
            f"- approximate prefetch buckets: `{report.get('prefetch_buckets')}`",
            f"- production candidate: `{report.get('production_candidate')}`",
            "",
            "## Final reconstruction classification",
            "",
            f"- confirmed: `{(report.get('final_reconstruction') or {}).get('confirmed_count', 0)}`",
            f"- inconclusive: `{(report.get('final_reconstruction') or {}).get('inconclusive_count', 0)}`",
            f"- failed: `{(report.get('final_reconstruction') or {}).get('failed_count', 0)}`",
            "- `confirmed` is based on the existing J2 pixel/DCT reconstruction result; a rendered locator screenshot is a visual reference, not byte identity.",
            "",
            "## Artifacts",
            "",
            "- `report.json`, `regions.json`, `timeline.json`, `network.json`, `draw_calls.json`, `sources.json`",
            "- `timeline/t00`, `timeline/t02`, `timeline/t05`, `timeline/t10`, `timeline/t20` contain unscrolled snapshots.",
            "- `scroll_probes/` contains only bounded representative target before/after snapshots.",
            "- `j1/` is the input shape for the existing reconstruction PoC; `reconstructed/` contains its output.",
            "",
            "## Safety and limitations",
            "",
            "- No production adapter, Discovery, Batch, DB, ZIP, purchase, point, rental, login, or next-episode behavior was changed or invoked.",
            "- No full bottom traversal was performed; scroll probes run only when the initial state is incomplete and are capped at five representative regions.",
            f"- errors: `{json.dumps(report.get('errors', []), ensure_ascii=False)}`",
        ]
    )
    return "\n".join(lines) + "\n"


async def run_probe(url: str, output_dir: Path, cdp_endpoint: str | None) -> dict[str, Any]:
    expected_episode_id = extract_episode_id(url)
    if expected_episode_id is None:
        raise ValueError("--url must be a Jump+ URL of the form /episode/<numeric-id>")
    endpoint = resolve_cdp_endpoint(cli_endpoint=cdp_endpoint)
    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    probe = VerticalJ1Probe(page=page, output_dir=output_dir, expected_episode_id=expected_episode_id)
    try:
        return await probe.run(url)
    finally:
        await session.close_page(page)
        await session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Shonen Jump+ vertical J1 lazy-load probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    report = asyncio.run(run_probe(args.url, args.output_dir, args.cdp_endpoint))
    print(json.dumps({
        "content_region_count": report.get("content_region_count"),
        "initial_reconstructable_count": report.get("initial_reconstructable_count"),
        "wait_20s_reconstructable_count": report.get("wait_20s_reconstructable_count"),
        "scroll_final_reconstructable_count": report.get("scroll_final_reconstructable_count"),
        "conclusion": report.get("conclusion"),
        "output_dir": str(args.output_dir),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

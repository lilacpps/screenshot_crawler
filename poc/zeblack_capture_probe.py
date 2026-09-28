"""Zebrack Z1 blob-JPEG capture proof-of-concept.

This module is intentionally a probe, not a production Site Adapter.  It reuses
the bounded, read-only navigation from :mod:`zeblack_probe` and adds only the
current-state ``page_N`` blob retrieval and pixel-equivalence checks.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import itertools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

try:  # Works both when imported as ``poc.*`` and when the probe is run directly.
    from .zeblack_probe import (
        DEFAULT_OUTPUT_DIR,
        DEFAULT_URL,
        MAX_STEPS,
        ZebrackProbe,
        _now_iso,
        _write_json,
        extract_viewer_identity,
        resolve_cdp_endpoint,
    )
except ImportError:  # pragma: no cover - exercised by direct script execution.
    from zeblack_probe import (  # type: ignore[no-redef]
        DEFAULT_OUTPUT_DIR,
        DEFAULT_URL,
        MAX_STEPS,
        ZebrackProbe,
        _now_iso,
        _write_json,
        extract_viewer_identity,
        resolve_cdp_endpoint,
    )


Z1_OUTPUT_NAME = "z1"
MAX_BLOB_BYTES = 25 * 1024 * 1024
MAX_LIFETIME_CHECKS = 2
PAGE_ALT_RE = re.compile(r"^page_(?P<index>[0-9]+)$")
PAGE_COUNTER_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")


def parse_page_index(alt: Any) -> int | None:
    """Parse only the exact ``page_<non-negative integer>`` alt convention."""

    if not isinstance(alt, str):
        return None
    match = PAGE_ALT_RE.fullmatch(alt)
    if match is None:
        return None
    return int(match.group("index"))


def order_page_metadata(metadata: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a numeric ``page_N`` order, rejecting malformed/duplicate input."""

    normalized: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []
    for item in metadata:
        page_index = item.get("page_index")
        if not isinstance(page_index, int) or page_index < 0:
            page_index = parse_page_index(item.get("page_alt"))
        if page_index is None:
            malformed.append(item)
            continue
        normalized.append({**item, "page_index": page_index})

    indices = [int(item["page_index"]) for item in normalized]
    duplicates = sorted({index for index in indices if indices.count(index) > 1})
    if malformed or duplicates:
        return {
            "status": "ambiguous",
            "ordered": [],
            "indices": indices,
            "malformed_count": len(malformed),
            "duplicate_indices": duplicates,
        }
    ordered = sorted(normalized, key=lambda item: int(item["page_index"]))
    return {
        "status": "stable",
        "ordered": ordered,
        "indices": [int(item["page_index"]) for item in ordered],
        "malformed_count": 0,
        "duplicate_indices": [],
    }


def is_exact_pixel_match(
    decoded_pixel_sha256: str | None,
    img_pixel_sha256: str | None,
    decoded_dimensions: list[int] | tuple[int, int] | None,
    natural_dimensions: list[int] | tuple[int, int] | None,
    img_pixel_dimensions: list[int] | tuple[int, int] | None,
) -> bool:
    """Return true only when all native dimensions and RGB hashes agree."""

    dimensions = (decoded_dimensions, natural_dimensions, img_pixel_dimensions)
    return bool(
        decoded_pixel_sha256
        and img_pixel_sha256
        and all(_valid_dimensions(value) for value in dimensions)
        and len({tuple(value) for value in dimensions if value is not None}) == 1
        and decoded_pixel_sha256 == img_pixel_sha256
    )


def _valid_dimensions(value: list[int] | tuple[int, int] | None) -> bool:
    return bool(
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in value)
    )


def classify_z1_comparison(
    *,
    fetch_error: str | None,
    decoded_format: str | None,
    decoded_dimensions: list[int] | tuple[int, int] | None,
    natural_dimensions: list[int] | tuple[int, int] | None,
    img_pixel_dimensions: list[int] | tuple[int, int] | None,
    decoded_pixel_sha256: str | None,
    img_pixel_sha256: str | None,
    canvas_error: str | None,
) -> str:
    """Classify one page without treating a partial result as a match."""

    if fetch_error or not decoded_format:
        return "unavailable"
    if decoded_format.upper() != "JPEG":
        return "unavailable"
    required_dimensions = (decoded_dimensions, natural_dimensions, img_pixel_dimensions)
    if not all(_valid_dimensions(value) for value in required_dimensions):
        return "inconclusive"
    if len({tuple(value) for value in required_dimensions if value is not None}) != 1:
        return "mismatch"
    if canvas_error:
        return "inconclusive"
    if not decoded_pixel_sha256 or not img_pixel_sha256:
        return "inconclusive"
    return (
        "exact_pixel_match"
        if is_exact_pixel_match(
            decoded_pixel_sha256,
            img_pixel_sha256,
            decoded_dimensions,
            natural_dimensions,
            img_pixel_dimensions,
        )
        else "mismatch"
    )


def classify_z1_verdict(
    pages: list[dict[str, Any]],
    ordering: dict[str, Any],
    *,
    minimum_pages: int = 2,
) -> str:
    """Aggregate page results using a fail-closed capture decision."""

    if not pages:
        return "inconclusive"
    if any(page.get("equivalence") == "mismatch" for page in pages):
        return "rejected"
    if any(page.get("equivalence") != "exact_pixel_match" for page in pages):
        return "inconclusive"
    page_indices = [page.get("page_index") for page in pages]
    if (
        len(pages) >= minimum_pages
        and all(isinstance(index, int) and not isinstance(index, bool) and index >= 0 for index in page_indices)
        and len(set(page_indices)) == len(page_indices)
        and ordering.get("status") == "stable"
        and ordering.get("spread_observed") is True
        and not ordering.get("gaps")
    ):
        return "confirmed"
    return "inconclusive"


_Z1_PAGE_METADATA_SCRIPT = r"""
() => {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      style.opacity !== "0" && rect.width > 0 && rect.height > 0;
  };
  const inViewport = (element) => {
    const rect = element.getBoundingClientRect();
    return rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight;
  };
  const rect = (element) => {
    const value = element.getBoundingClientRect();
    return {x: value.x, y: value.y, width: value.width, height: value.height};
  };
  const closestViewer = (element) => {
    const ancestor = element.closest("[id], [class]");
    if (!ancestor) return null;
    const label = `${ancestor.id || ""} ${String(ancestor.className || "")}`;
    return /viewer|reader|comic|manga|spread|page/i.test(label) ? label.slice(0, 500) : null;
  };
  const all = Array.from(document.images);
  const pageImages = all.map((element, domOrder) => {
    const alt = element.getAttribute("alt") || "";
    if (!/^page_[0-9]+$/.test(alt)) return null;
    const source = element.currentSrc || element.src || "";
    return {
      page_alt: alt,
      src: element.getAttribute("src"),
      current_src: element.currentSrc || null,
      blob_url: source.startsWith("blob:") ? source : null,
      natural_dimensions: [element.naturalWidth || 0, element.naturalHeight || 0],
      rendered: rect(element),
      visible: visible(element),
      in_viewport: inViewport(element),
      dom_order: domOrder,
      viewer_ancestor_hint: closestViewer(element),
      selected: visible(element) && inViewport(element) && element.naturalWidth > 0 && element.naturalHeight > 0,
    };
  }).filter(Boolean);
  return {
    captured_at: new Date().toISOString(),
    url: location.href,
    viewport: {width: innerWidth, height: innerHeight},
    page_images: pageImages,
    candidates: pageImages.filter((item) => item.selected),
  };
}
"""


_Z1_FETCH_AND_COMPARE_SCRIPT = r"""
async ({domOrder, expectedAlt, maxBytes}) => {
  const image = Array.from(document.images)[domOrder];
  if (!image || (image.getAttribute("alt") || "") !== expectedAlt) {
    return {ok: false, error: "image_identity_changed"};
  }
  const blobUrl = image.currentSrc || image.src || "";
  if (!blobUrl.startsWith("blob:")) {
    return {ok: false, error: "current_source_is_not_blob", blob_url: blobUrl || null};
  }
  let response;
  let buffer;
  let fetchError = null;
  try {
    response = await fetch(blobUrl);
    if (!response.ok) fetchError = `fetch_status_${response.status}`;
    else buffer = await response.arrayBuffer();
  } catch (error) {
    fetchError = `${error?.name || "Error"}: ${error?.message || error}`;
  }
  let encodedBase64 = null;
  let byteLength = null;
  if (buffer && buffer.byteLength <= maxBytes) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunkSize = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
    }
    encodedBase64 = btoa(binary);
    byteLength = bytes.length;
  } else if (buffer) {
    fetchError = "blob_too_large";
  }
  const result = {
    ok: Boolean(encodedBase64),
    blob_url: blobUrl,
    byte_length: byteLength,
    encoded_base64: encodedBase64,
    fetched_content_type: response?.headers?.get("content-type") || null,
    fetch_error: fetchError,
    img_pixel_sha256: null,
    img_pixel_dimensions: [image.naturalWidth || 0, image.naturalHeight || 0],
    canvas_error: null,
  };
  try {
    const width = image.naturalWidth;
    const height = image.naturalHeight;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", {willReadFrequently: true});
    if (!context) throw new Error("2d_context_unavailable");
    context.drawImage(image, 0, 0, width, height);
    const rgba = context.getImageData(0, 0, width, height).data;
    const rgb = new Uint8Array(width * height * 3);
    for (let source = 0, target = 0; source < rgba.length; source += 4) {
      rgb[target++] = rgba[source];
      rgb[target++] = rgba[source + 1];
      rgb[target++] = rgba[source + 2];
    }
    const digest = await crypto.subtle.digest("SHA-256", rgb);
    result.img_pixel_sha256 = Array.from(new Uint8Array(digest),
      (value) => value.toString(16).padStart(2, "0")).join("");
  } catch (error) {
    result.canvas_error = `${error?.name || "Error"}: ${error?.message || error}`;
  }
  return result;
}
"""


_Z1_LIFETIME_SCRIPT = r"""
async (urls) => {
  const results = [];
  for (const url of urls || []) {
    try {
      const response = await fetch(url);
      if (!response.ok) {
        results.push({blob_url: url, fetchable: false, error: `fetch_status_${response.status}`});
        continue;
      }
      const body = await response.arrayBuffer();
      results.push({blob_url: url, fetchable: true, byte_length: body.byteLength});
    } catch (error) {
      results.push({blob_url: url, fetchable: false, error: `${error?.name || "Error"}: ${error?.message || error}`});
    }
  }
  return results;
}
"""


def _rgb_sha256(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


def _decode_blob_body(body: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "byte_length": len(body),
        "encoded_sha256": hashlib.sha256(body).hexdigest(),
        "detected_format": None,
        "decoded_dimensions": None,
        "decoded_pixel_sha256": None,
        "jpeg_decode_success": False,
        "decode_error": None,
    }
    try:
        with Image.open(io.BytesIO(body)) as image:
            result["detected_format"] = image.format
            result["decoded_dimensions"] = [image.width, image.height]
            result["decoded_pixel_sha256"] = _rgb_sha256(image)
            result["jpeg_decode_success"] = image.format == "JPEG"
    except BaseException as exc:  # noqa: BLE001
        result["decode_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _asset_candidates(observation: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for event in observation.network.get("events", []):
        if event.get("event") != "response" or event.get("host") != "asset.zebrack-comic.com":
            continue
        if event.get("classification") != "image":
            continue
        candidates.append(
            {
                "timestamp": event.get("timestamp"),
                "url": event.get("url"),
                "content_type": event.get("content_type"),
                "content_length": event.get("content_length"),
                "body": event.get("body", {}),
            }
        )
    return candidates


@dataclass
class ZebrackZ1Probe(ZebrackProbe):
    """Z0 probe with opt-in current-state blob capture diagnostics."""

    z1_states: list[dict[str, Any]] = field(default_factory=list)
    z1_pages: list[dict[str, Any]] = field(default_factory=list)
    lifetime_checks: list[dict[str, Any]] = field(default_factory=list)
    _previous_blobs: list[dict[str, Any]] = field(default_factory=list)

    async def capture_initial(self) -> None:
        await super().capture_initial()
        if self.observations:
            await self.capture_z1_state(self.observations[-1])

    async def collect_snapshot(self, directory_name: str, *, include_html: bool) -> Any:
        observation = await super().collect_snapshot(directory_name, include_html=include_html)
        # ``ZebrackProbe.capture_initial`` first collects ``initial`` and then
        # copies that same stable observation to ``state_000``.  Capture only
        # the canonical state to avoid manufacturing a duplicate page index.
        if directory_name != "initial":
            await self.capture_z1_state(observation)
        return observation

    async def _probe_lifetime(self, state: str) -> None:
        if not self._previous_blobs or len(self.lifetime_checks) >= MAX_LIFETIME_CHECKS:
            return
        remaining = MAX_LIFETIME_CHECKS - len(self.lifetime_checks)
        selected = self._previous_blobs[:remaining]
        try:
            results = await self.page.evaluate(_Z1_LIFETIME_SCRIPT, [item["blob_url"] for item in selected])
        except BaseException as exc:  # noqa: BLE001
            results = [{"fetchable": False, "error": f"{type(exc).__name__}: {exc}"} for _ in selected]
        for previous, result in zip(selected, results, strict=False):
            self.lifetime_checks.append(
                {
                    "checked_after_state": state,
                    "previous_state": previous.get("state"),
                    "page_alt": previous.get("page_alt"),
                    "page_index": previous.get("page_index"),
                    "blob_url": previous.get("blob_url"),
                    "checked_at": _now_iso(),
                    **result,
                }
            )

    async def _capture_page(self, state: str, metadata: dict[str, Any]) -> dict[str, Any]:
        page_alt = str(metadata.get("page_alt") or "")
        page_index = parse_page_index(page_alt)
        record: dict[str, Any] = {
            "state": state,
            "page_alt": page_alt,
            "page_index": page_index,
            "src": metadata.get("src"),
            "current_src": metadata.get("current_src"),
            "blob_url": metadata.get("blob_url"),
            "natural_dimensions": metadata.get("natural_dimensions"),
            "rendered": metadata.get("rendered"),
            "visible": metadata.get("visible"),
            "in_viewport": metadata.get("in_viewport"),
            "dom_order": metadata.get("dom_order"),
            "viewer_ancestor_hint": metadata.get("viewer_ancestor_hint"),
            "retrieved_at": _now_iso(),
            "fetch_error": None,
            "fetched_content_type": None,
            "canvas_error": None,
            "file": None,
        }
        if page_index is None or not metadata.get("blob_url"):
            record["fetch_error"] = "malformed_page_alt_or_missing_blob_source"
            record["equivalence"] = "unavailable"
            return record
        try:
            fetched = await self.page.evaluate(
                _Z1_FETCH_AND_COMPARE_SCRIPT,
                {"domOrder": metadata["dom_order"], "expectedAlt": page_alt, "maxBytes": MAX_BLOB_BYTES},
            )
        except BaseException as exc:  # noqa: BLE001
            record["fetch_error"] = f"{type(exc).__name__}: {exc}"
            record["equivalence"] = "unavailable"
            return record
        record["blob_url"] = fetched.get("blob_url") or record["blob_url"]
        record["blob_fetch_error"] = fetched.get("fetch_error") or fetched.get("error")
        body = None
        if fetched.get("encoded_base64"):
            try:
                body = base64.b64decode(fetched["encoded_base64"], validate=True)
                record["bytes_source"] = "page_fetch_blob_url"
            except (KeyError, ValueError, TypeError, base64.binascii.Error) as exc:
                record["blob_fetch_error"] = f"invalid_browser_bytes: {type(exc).__name__}: {exc}"
        if body is None:
            # A revoked object URL can still be the current decoded image while
            # a later fetch(blob:) fails.  Reuse only the exact blob response
            # body already captured by the same Playwright browser context.
            response_candidates = [
                item for item in self.saved_images if item.get("url") == record["blob_url"]
            ]
            if response_candidates:
                response_item = response_candidates[-1]
                response_path = self.output_dir / str(response_item.get("file") or "")
                try:
                    if response_path.is_file():
                        body = response_path.read_bytes()
                        record["bytes_source"] = "playwright_blob_response_body"
                        record["blob_response_timestamp"] = response_item.get("network_timestamp")
                except BaseException as exc:  # noqa: BLE001
                    record["blob_response_read_error"] = f"{type(exc).__name__}: {exc}"
        if body is None:
            record["fetch_error"] = record.get("blob_fetch_error") or "blob_bytes_unavailable"
            record["byte_length"] = fetched.get("byte_length")
            record["equivalence"] = "unavailable"
            return record
        record.update(_decode_blob_body(body))
        record.update(
            {
                "blob_url": fetched.get("blob_url") or record["blob_url"],
                "fetched_content_type": fetched.get("fetched_content_type"),
                "img_pixel_sha256": fetched.get("img_pixel_sha256"),
                "img_pixel_dimensions": fetched.get("img_pixel_dimensions"),
                "canvas_error": fetched.get("canvas_error"),
            }
        )
        record["equivalence"] = classify_z1_comparison(
            fetch_error=record.get("fetch_error"),
            decoded_format=record.get("detected_format"),
            decoded_dimensions=record.get("decoded_dimensions"),
            natural_dimensions=record.get("natural_dimensions"),
            img_pixel_dimensions=record.get("img_pixel_dimensions"),
            decoded_pixel_sha256=record.get("decoded_pixel_sha256"),
            img_pixel_sha256=record.get("img_pixel_sha256"),
            canvas_error=record.get("canvas_error"),
        )
        if record.get("detected_format") == "JPEG":
            pages_dir = self.output_dir / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)
            path = pages_dir / f"page_{page_index:03d}.jpg"
            try:
                if path.exists():
                    # Never silently overwrite an already observed page index.
                    existing = path.read_bytes()
                    if existing != body:
                        record["file_error"] = "duplicate_page_index_with_different_bytes"
                    else:
                        record["file"] = str(path.relative_to(self.output_dir))
                else:
                    path.write_bytes(body)
                    record["file"] = str(path.relative_to(self.output_dir))
            except BaseException as exc:  # noqa: BLE001
                record["file_error"] = f"{type(exc).__name__}: {exc}"
        return record

    async def capture_z1_state(self, observation: Any) -> None:
        state = observation.state
        await self._probe_lifetime(state)
        try:
            collected = await self.page.evaluate(_Z1_PAGE_METADATA_SCRIPT)
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(f"Z1 page metadata collection failed: {type(exc).__name__}: {exc}")
            collected = {"captured_at": _now_iso(), "url": self.page.url, "page_images": [], "candidates": [], "error": str(exc)}
        candidates = list(collected.get("candidates", []))
        candidate_indices = [parse_page_index(item.get("page_alt")) for item in candidates]
        present_indices = [index for index in candidate_indices if index is not None]
        has_duplicate = len(present_indices) != len({index for index in present_indices})
        records: list[dict[str, Any]] = []
        if not has_duplicate:
            for metadata in candidates:
                records.append(await self._capture_page(state, metadata))
        else:
            for metadata in candidates:
                record = {
                    **metadata,
                    "state": state,
                    "page_index": parse_page_index(metadata.get("page_alt")),
                    "equivalence": "inconclusive",
                    "fetch_error": "duplicate_page_index_in_same_state",
                    "file": None,
                }
                records.append(record)
        self.z1_pages.extend(records)
        self.z1_states.append(
            {
                "state": state,
                "url": collected.get("url") or observation.url,
                "captured_at": collected.get("captured_at") or _now_iso(),
                "page_counter_candidates": [
                    candidate.get("text")
                    for candidate in observation.dom.get("pageInfoCandidates", [])
                    if PAGE_COUNTER_RE.fullmatch(str(candidate.get("text") or ""))
                ],
                "page_images": collected.get("page_images", []),
                "candidates": candidates,
                "candidate_page_indices": candidate_indices,
                "duplicate_page_index": has_duplicate,
                "asset_response_candidates": _asset_candidates(observation),
                "page_records": records,
            }
        )
        self._previous_blobs = [
            {
                "state": state,
                "page_alt": record.get("page_alt"),
                "page_index": record.get("page_index"),
                "blob_url": record.get("blob_url"),
            }
            for record in records
            if record.get("blob_url")
        ][:2]
        _write_json(self.output_dir / state / "z1.json", self.z1_states[-1])

    def _ordering(self) -> dict[str, Any]:
        metadata = [page for page in self.z1_pages if page.get("page_index") is not None]
        order = order_page_metadata(metadata)
        state_indices = [
            [int(index) for index in state.get("candidate_page_indices", []) if index is not None]
            for state in self.z1_states
        ]
        unique_indices = sorted(set(order.get("indices", [])))
        gaps = [index for index in range(unique_indices[-1] + 1) if index not in unique_indices] if unique_indices else []
        spread_observed = any(len(indices) >= 2 for indices in state_indices)
        transitions_monotonic = all(
            not previous or not current or min(current) > max(previous)
            for previous, current in itertools.pairwise(state_indices)
        )
        status = "stable" if order["status"] == "stable" and transitions_monotonic else "ambiguous"
        return {
            "status": status,
            "observed_page_indices": unique_indices,
            "state_page_indices": state_indices,
            "gaps": gaps,
            "duplicate_indices": order.get("duplicate_indices", []),
            "malformed_count": order.get("malformed_count", 0),
            "spread_observed": spread_observed,
            "transitions_monotonic": transitions_monotonic,
            "logical_order": "page_N numeric ascending" if status == "stable" else "ambiguous",
        }

    def as_report(self, target_url: str, steps: int) -> dict[str, Any]:
        report = super().as_report(target_url, steps)
        ordering = self._ordering()
        verdict = classify_z1_verdict(self.z1_pages, ordering)
        report["z1"] = {
            "capture_verdict": verdict,
            "pages": self.z1_pages,
            "states": self.z1_states,
            "comparison": self.z1_pages,
            "reading_order": ordering,
            "blob_lifetime": self.lifetime_checks,
            "asset_response_relationship": {
                "same_state_candidates": sum(len(state.get("asset_response_candidates", [])) for state in self.z1_states),
                "one_to_one_mapping": "not established",
                "note": "asset response and blob retrieval are recorded in the same-state artifacts; no transport decoding or inferred mapping is used",
            },
        }
        report["capture_verdict"] = verdict
        return report

    def write_report(self, report: dict[str, Any]) -> None:
        _write_json(self.output_dir / "report.json", report)
        _write_json(
            self.output_dir / "comparison.json",
            {
                "target_url": report.get("target_url"),
                "target_title_id": report.get("target_title_id"),
                "target_chapter_id": report.get("target_chapter_id"),
                "capture_verdict": report.get("capture_verdict"),
                "pages": report.get("z1", {}).get("pages", []),
                "reading_order": report.get("z1", {}).get("reading_order", {}),
                "blob_lifetime": report.get("z1", {}).get("blob_lifetime", []),
                "asset_response_relationship": report.get("z1", {}).get("asset_response_relationship", {}),
            },
        )
        (self.output_dir / "summary.md").write_text(self.make_z1_summary(report), encoding="utf-8")

    @staticmethod
    def make_z1_summary(report: dict[str, Any]) -> str:
        z1 = report.get("z1", {})
        pages = z1.get("pages", [])
        counts = {name: sum(page.get("equivalence") == name for page in pages) for name in (
            "exact_pixel_match", "mismatch", "unavailable", "inconclusive"
        )}
        dimensions = sorted({tuple(page.get("decoded_dimensions", [])) for page in pages if page.get("decoded_dimensions")})
        lifetime = z1.get("blob_lifetime", [])
        return "\n".join(
            [
                "# Zebrack Z1 blob-JPEG capture probe summary",
                "",
                "## Target",
                "",
                f"- URL: `{report.get('target_url')}`",
                f"- title_id: `{report.get('target_title_id')}`; chapter_id: `{report.get('target_chapter_id')}`",
                f"- capture verdict: `{report.get('capture_verdict')}`",
                f"- states observed: `{report.get('states_observed')}`; final URL relation: `{report.get('final_url_change_kind')}`",
                "",
                "## Page results",
                "",
                f"- pages inspected: `{len(pages)}`; exact: `{counts['exact_pixel_match']}`; mismatch: `{counts['mismatch']}`; unavailable: `{counts['unavailable']}`; inconclusive: `{counts['inconclusive']}`",
                f"- decoded dimensions: `{', '.join(f'{width}x{height}' for width, height in dimensions) or 'not observed'}`",
                "- JPEG files are saved from the fetched blob bytes without re-encoding.",
                "- The visible-image comparison uses a temporary canvas at HTMLImageElement natural dimensions; CSS display scaling is excluded.",
                "",
                "## Reading order",
                "",
                f"- result: `{z1.get('reading_order', {}).get('status')}`",
                f"- page indices: `{z1.get('reading_order', {}).get('observed_page_indices', [])}`",
                f"- state page indices: `{z1.get('reading_order', {}).get('state_page_indices', [])}`",
                f"- page counters: `{[state.get('page_counter_candidates', []) for state in z1.get('states', [])]}`",
                f"- logical order: `{z1.get('reading_order', {}).get('logical_order')}`",
                "- DOM order and screen x/y are retained as metadata; x/y is not used as the logical-page authority.",
                "",
                "## Blob lifetime",
                "",
                f"- checks: `{len(lifetime)}`",
                *[f"- `{item.get('page_alt')}` after `{item.get('checked_after_state')}`: `{item.get('fetchable')}`" for item in lifetime],
                "- Production guidance remains immediate retrieval in the current stable state; later blob availability is not assumed.",
                "",
                "## Asset response relationship",
                "",
                "- Same-state asset.zebrack-comic.com image responses are recorded as diagnostic candidates only.",
                "- A one-to-one asset-response-to-visible-page mapping was not inferred; transport bytes were not reverse engineered.",
                "",
                "## Capture strategy conclusion",
                "",
                "- If the verdict is `confirmed`, the Zeblack-specific top candidate is `visible HTMLImageElement -> blob URL -> original encoded JPEG bytes`.",
                "- This PoC does not change the shared capture hierarchy or implement a production Site Adapter.",
                "",
                "## Safety / remaining unknowns",
                "",
                "- Navigation is bounded and target-title/chapter guarded. No access, ticket, purchase, advertisement, login, or next-chapter control is clicked.",
                "- Cross-chapter behavior, final-page behavior, other chapters, and production Adapter integration remain out of scope.",
                f"- probe errors: `{json.dumps(report.get('errors', []), ensure_ascii=False)}`",
                "",
            ]
        )


async def run_z1_probe(
    url: str = DEFAULT_URL,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    steps: int = MAX_STEPS,
    cdp_endpoint: str | None = None,
) -> dict[str, Any]:
    identity = extract_viewer_identity(url)
    if identity is None:
        raise ValueError(
            "--url must be a Zebrack URL of the form "
            "https://zebrack-comic.shueisha.co.jp/title/<id>/chapter/<id>/viewer"
        )
    endpoint = resolve_cdp_endpoint(cli_endpoint=cdp_endpoint)
    from screenshot_crawler.core.browser import BrowserSession

    session = await BrowserSession.connect(endpoint)
    page = await session.new_page()
    z1_output_dir = output_dir / Z1_OUTPUT_NAME
    probe = ZebrackZ1Probe(
        page=page,
        output_dir=z1_output_dir,
        expected_title_id=identity["title_id"],
        expected_chapter_id=identity["chapter_id"],
    )
    try:
        report = await probe.run(url, max(0, min(MAX_STEPS, steps)))
        probe.write_report(report)
        return report
    finally:
        await session.close_page(page)
        await session.close()


def main() -> None:  # pragma: no cover - CLI exercised by live verification.
    import argparse

    parser = argparse.ArgumentParser(description="Read-only Zebrack Z1 blob-JPEG capture probe")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--cdp-endpoint", default=None)
    args = parser.parse_args()
    report = asyncio.run(run_z1_probe(args.url, args.output_dir, args.steps, args.cdp_endpoint))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

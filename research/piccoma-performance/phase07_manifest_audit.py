"""Opt-in, URL-free audit of a crawl manifest immediately before packaging.

This research-only hook reads the final manifest once after Runner returns and
before the ordinary packager can remove its temporary output directory. It
records a small allowlist of page identity/format/provenance fields and never
persists the manifest, titles, URLs, or image data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_OUTPUT_ROOT = (REPO_ROOT / "output" / "piccoma_performance").resolve()


def _phase_root(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate == ALLOWED_OUTPUT_ROOT:
            break
        if candidate.parent == ALLOWED_OUTPUT_ROOT and candidate.name.startswith("phase07_"):
            return candidate
    raise ValueError("Phase 07 audit paths must remain under an isolated phase root")


def _failure_report(
    code: str, expected_pages: int, *, manifest_read_count: int = 0
) -> dict[str, Any]:
    return {
        "audit_version": 1,
        "audit_passed": False,
        "failure_code": code,
        "expected_page_count": expected_pages,
        "manifest_read_count": manifest_read_count,
        "raw_manifest_persisted": False,
        "urls_persisted": False,
    }


def _allowlisted_report(manifest: object, expected_pages: int) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(manifest, Mapping):
        manifest = {}
        errors.append("manifest_not_mapping")
    pages = manifest.get("pages")
    if not isinstance(pages, list):
        pages = []
        errors.append("pages_not_list")
    if len(pages) != expected_pages:
        errors.append("page_count_mismatch")

    page_rows: list[dict[str, Any]] = []
    source_ids: list[str] = []
    for index, raw_page in enumerate(pages, start=1):
        if not isinstance(raw_page, Mapping):
            errors.append("page_not_mapping")
            continue
        identity = raw_page.get("identity")
        capture = raw_page.get("metadata", {})
        piccoma = capture.get("piccoma_capture", {}) if isinstance(capture, Mapping) else {}
        if not isinstance(identity, Mapping):
            identity = {}
            errors.append("identity_not_mapping")
        if not isinstance(piccoma, Mapping):
            piccoma = {}
            errors.append("capture_metadata_not_mapping")

        sequence = raw_page.get("sequence")
        raw_page_id = identity.get("page_id")
        page_id = (
            raw_page_id
            if isinstance(raw_page_id, str) and re.fullmatch(r"p[0-9]{1,4}", raw_page_id)
            else None
        )
        source_id = identity.get("source_id")
        if isinstance(source_id, str) and source_id:
            source_ids.append(source_id)
        expected_id = f"p{index}"
        native = piccoma.get("source_native") is True
        source_mime = piccoma.get("source_mime") == "image/jpeg"
        backdrop = piccoma.get("source_backdrop") == "verified_solid_white"
        method = piccoma.get("method") == "native_tile_replay_lossless_webp"
        lossless = piccoma.get("output_lossless") is True
        webp = (
            raw_page.get("mime_type") == "image/webp"
            and raw_page.get("file_extension") == ".webp"
            and piccoma.get("output_format") == "image/webp"
        )
        no_fallback = (
            piccoma.get("fallback_reason") is None
            and piccoma.get("encoding_fallback_reason") is None
        )
        complete_count = piccoma.get("page_count") == expected_pages
        if (
            type(sequence) is not int
            or sequence != index
            or page_id != expected_id
            or not all((native, source_mime, backdrop, method, lossless, webp,
                        no_fallback, complete_count))
        ):
            errors.append("page_contract_mismatch")
        page_rows.append({
            "sequence": sequence if type(sequence) is int else None,
            "page_id": page_id,
            "source_native": native,
            "source_mime": "image/jpeg" if source_mime else None,
            "verified_white_backdrop": backdrop,
            "native_tile_replay_lossless_webp": method,
            "output_lossless": lossless,
            "mime_type": "image/webp" if webp else None,
            "file_extension": ".webp" if webp else None,
            "no_fallback": no_fallback,
            "manifest_page_count_matches": complete_count,
        })

    source_id_consistent = (
        len(source_ids) == expected_pages and len(set(source_ids)) == 1
    )
    if not source_id_consistent:
        errors.append("source_identity_not_consistent")
    return {
        "audit_version": 1,
        "audit_passed": not errors,
        "failure_codes": sorted(set(errors)),
        "expected_page_count": expected_pages,
        "manifest_read_count": 1,
        "page_count": len(pages),
        "sequence": [row["sequence"] for row in page_rows],
        "page_ids": [row["page_id"] for row in page_rows],
        "source_identity_consistent": source_id_consistent,
        "pages": page_rows,
        "raw_manifest_persisted": False,
        "urls_persisted": False,
    }


def audit_manifest_file(
    output_dir: Path,
    report_path: Path,
    *,
    expected_pages: int,
) -> dict[str, Any]:
    """Write a sanitized prepackage manifest verdict without retaining input."""

    if type(expected_pages) is not int or not 1 <= expected_pages <= 1000:
        raise ValueError("expected_pages must be an integer from 1 through 1000")
    output_dir = output_dir.resolve()
    report_path = report_path.resolve()
    phase = _phase_root(report_path)
    if (
        phase != _phase_root(output_dir)
        or report_path == output_dir
        or output_dir in report_path.parents
        or report_path == output_dir / "manifest.json"
    ):
        raise ValueError("audit report and crawl output must share one Phase 07 root")
    if report_path.exists():
        raise FileExistsError("refusing to overwrite a Phase 07 manifest audit")

    manifest_path = output_dir / "manifest.json"
    try:
        with manifest_path.open("r", encoding="utf-8") as source:
            manifest = json.load(source)
    except FileNotFoundError:
        report = _failure_report("manifest_missing", expected_pages)
    except (OSError, UnicodeError, json.JSONDecodeError):
        report = _failure_report(
            "manifest_unreadable", expected_pages, manifest_read_count=1
        )
    else:
        report = _allowlisted_report(manifest, expected_pages)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def install_runner_manifest_audit(
    runner_class: type,
    report_path: Path,
    *,
    expected_pages: int,
) -> None:
    """Audit once after Runner returns END, before CLI/Batch packaging starts."""

    report_path = report_path.resolve()
    _phase_root(report_path)
    if report_path.exists():
        raise FileExistsError("refusing to overwrite a Phase 07 manifest audit")
    original_run = runner_class.run

    async def audited_run(self: Any, page: Any, adapter: Any) -> Any:
        result = await original_run(self, page, adapter)
        stop_state = getattr(result, "stop_state", None)
        if getattr(stop_state, "value", stop_state) != "end":
            report = _failure_report("runner_did_not_reach_end", expected_pages)
            if report_path.exists():
                raise FileExistsError("refusing to overwrite a Phase 07 manifest audit")
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            raise RuntimeError("phase07_prepackage_manifest_audit_failed")
        output_dir = Path(self.config.output_dir)
        report = audit_manifest_file(
            output_dir, report_path, expected_pages=expected_pages
        )
        if report.get("audit_passed") is not True:
            raise RuntimeError("phase07_prepackage_manifest_audit_failed")
        return result

    runner_class.run = audited_run


__all__ = ["audit_manifest_file", "install_runner_manifest_audit"]

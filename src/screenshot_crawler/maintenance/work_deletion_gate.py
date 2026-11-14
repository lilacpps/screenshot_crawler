"""Read-only runtime gate shared by Catalog writers during Work recovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from screenshot_crawler.catalog.job_lock import CatalogJobLock


class WorkDeletionGateError(RuntimeError):
    """A Catalog has an unfinished Work-deletion operation."""


def work_deletion_gate_path(catalog_path: str | Path) -> Path:
    catalog = Path(catalog_path).resolve(strict=False)
    digest = hashlib.sha256(str(catalog).casefold().encode("utf-8")).hexdigest()[:24]
    return catalog.parent / ".work-deletion" / f"catalog-{digest}"


def check_work_deletion_gate(catalog_path: str | Path) -> tuple[str, ...]:
    """Return blockers without creating markers or opening a Catalog DB."""

    gate = work_deletion_gate_path(catalog_path)
    if not gate.is_dir():
        return ()
    blockers: list[str] = []
    try:
        entries = sorted(
            path for path in gate.iterdir()
            if path.is_file() and path.name not in {"management-bindings.json", "operations.json"}
            and not path.name.endswith(".job.lock")
        )
    except OSError:
        return ("deletion_gate_unreadable",)
    operations = gate / "operations.json"
    if operations.is_file():
        try:
            value = json.loads(operations.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or any(
                not isinstance(key, str) or not isinstance(ref, dict) or not isinstance(ref.get("manifest"), str)
                for key, ref in value.items()
            ):
                raise ValueError("invalid operation index")
        except (OSError, UnicodeDecodeError, ValueError, TypeError):
            blockers.append("deletion_gate_malformed")
    for entry in entries:
        try:
            value = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, TypeError):
            blockers.append("deletion_gate_malformed")
            continue
        if not isinstance(value, dict):
            blockers.append("deletion_gate_malformed")
            continue
        phase = str(value.get("phase", "")).casefold()
        if entry.name in {"active.json", "pending.json"} or entry.name == "manifest.json" or phase not in {"", "none", "done", "rolled_back"}:
            blockers.append("deletion_recovery_required" if phase in {"recovery", "recovering", "failed", "interrupted"} else "deletion_in_progress")
    return tuple(dict.fromkeys(blockers))


def assert_work_deletion_gate_clear(catalog_path: str | Path) -> None:
    blockers = check_work_deletion_gate(catalog_path)
    if blockers:
        raise WorkDeletionGateError(", ".join(blockers))


def work_deletion_admission_lock(catalog_path: str | Path) -> CatalogJobLock:
    """Return the short admission lock; callers must not hold it for jobs."""

    return CatalogJobLock(work_deletion_gate_path(catalog_path) / "admission")


def register_management_store(catalog_path: str | Path, management_path: str | Path):
    """Lazily delegate durable enqueue binding without an import cycle."""

    from screenshot_crawler.maintenance.work_deletion import register_management_store as _register

    return _register(catalog_path, management_path)


__all__ = [
    "WorkDeletionGateError",
    "assert_work_deletion_gate_clear",
    "check_work_deletion_gate",
    "register_management_store",
    "work_deletion_admission_lock",
    "work_deletion_gate_path",
]

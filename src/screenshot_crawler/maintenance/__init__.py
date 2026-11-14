"""Safety-first maintenance operations for existing crawler output.

Exports are loaded lazily so low-level gate modules can be imported by
Watchlist/Catalog services without eagerly importing maintenance modules that
depend back on those services.
"""

from importlib import import_module

_EXPORTS = {
    "ArchiveAuditReport": ("archive_audit", "ArchiveAuditReport"),
    "ArchiveAuditUsageError": ("archive_audit", "ArchiveAuditUsageError"),
    "ArchiveNameGuardError": ("archive_audit", "ArchiveNameGuardError"),
    "audit_existing_archives": ("archive_audit", "audit_existing_archives"),
    "inspect_existing_archive_names": ("archive_audit", "inspect_existing_archive_names"),
    "ArchiveRenumberPlan": ("archive_renumber", "ArchiveRenumberPlan"),
    "ArchiveRenumberResult": ("archive_renumber", "ArchiveRenumberResult"),
    "RenumberEntry": ("archive_renumber", "RenumberEntry"),
    "apply_archive_renumber_plan": ("archive_renumber", "apply_archive_renumber_plan"),
    "build_archive_renumber_plan": ("archive_renumber", "build_archive_renumber_plan"),
    "SourceIdentityError": ("source_identity", "SourceIdentityError"),
    "SourceIdentityMaintenance": ("source_identity", "SourceIdentityMaintenance"),
    "SourceIdentityPlan": ("source_identity", "SourceIdentityPlan"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute)
    globals()[name] = value
    return value

__all__ = [
    "ArchiveAuditReport",
    "ArchiveAuditUsageError",
    "ArchiveNameGuardError",
    "ArchiveRenumberPlan",
    "ArchiveRenumberResult",
    "RenumberEntry",
    "SourceIdentityError",
    "SourceIdentityMaintenance",
    "SourceIdentityPlan",
    "apply_archive_renumber_plan",
    "audit_existing_archives",
    "build_archive_renumber_plan",
    "inspect_existing_archive_names",
]

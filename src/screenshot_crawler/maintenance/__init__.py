"""Safety-first maintenance operations for existing crawler output."""

from screenshot_crawler.maintenance.archive_audit import (
    ArchiveAuditReport,
    ArchiveAuditUsageError,
    ArchiveNameGuardError,
    audit_existing_archives,
    inspect_existing_archive_names,
)
from screenshot_crawler.maintenance.archive_renumber import (
    ArchiveRenumberPlan,
    ArchiveRenumberResult,
    RenumberEntry,
    apply_archive_renumber_plan,
    build_archive_renumber_plan,
)
from screenshot_crawler.maintenance.source_identity import (
    SourceIdentityError,
    SourceIdentityMaintenance,
    SourceIdentityPlan,
)

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

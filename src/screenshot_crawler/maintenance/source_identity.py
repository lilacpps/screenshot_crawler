"""Safe, explicit maintenance for a Source identity change.

Discovery deliberately does not infer episode equivalence from title or order.
This module is the human-confirmed escape hatch: it produces a read-only plan,
then applies the exact plan under the Catalog job lock after rechecking a
precondition token.  The existing Source/Item is retained whenever possible;
an already-created, pristine donor Source is removed only after its complete
graph is validated.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from screenshot_crawler.catalog import (
    CatalogService,
    CatalogValidationError,
    format_timestamp,
    now_jst,
)


class SourceIdentityError(CatalogValidationError):
    """Raised when an explicit identity change is unsafe or stale."""


@dataclass(frozen=True, slots=True)
class SourceIdentityPlan:
    site: str
    work_key: str
    old_external_id: str
    new_external_id: str
    new_locator: str
    reason: str
    body_revision_possible: bool
    old_source_id: int
    old_item_id: int
    old_locator: str | None
    old_discovery_key: str | None
    donor_source_id: int | None
    donor_item_id: int | None
    donor_pristine: bool
    source_target_count: int
    token: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SourceIdentityMaintenance:
    """Plan and apply one manually confirmed Source identity change."""

    def __init__(self, catalog: CatalogService | str | Path) -> None:
        self.catalog = catalog if isinstance(catalog, CatalogService) else CatalogService(catalog)

    def plan(
        self,
        *,
        site: str,
        work_key: str,
        old_external_id: str,
        new_external_id: str,
        new_locator: str,
        reason: str,
        body_revision_possible: bool = True,
    ) -> SourceIdentityPlan:
        self._validate_args(site, work_key, old_external_id, new_external_id, new_locator, reason)
        self._reject_wal_snapshot()
        with self.catalog._read_only_connection() as connection:  # type: ignore[attr-defined]
            # A read-only SQLite connection can still advance WAL read marks.
            # The maintenance dry-run promises byte-level immutability, so the
            # plan is only allowed against a stable rollback-journal snapshot.
            connection.execute("BEGIN")
            return self._plan_connection(
                connection,
                site=site,
                work_key=work_key,
                old_external_id=old_external_id,
                new_external_id=new_external_id,
                new_locator=new_locator,
                reason=reason,
                body_revision_possible=body_revision_possible,
            )

    def apply(
        self,
        plan: SourceIdentityPlan,
        *,
        expected_token: str | None = None,
    ) -> SourceIdentityPlan:
        """Apply exactly ``plan`` and return the committed plan.

        ``expected_token`` is required by callers using a prior dry-run.  A
        fresh plan token is also checked inside the transaction so changes made
        between preflight and mutation cannot be silently overwritten.
        """

        expected = expected_token or plan.token
        with self.catalog.job_lock(), self.catalog._connection() as connection:  # type: ignore[attr-defined]
            connection.execute("BEGIN IMMEDIATE")
            current = self._plan_connection(
                connection,
                site=plan.site,
                work_key=plan.work_key,
                old_external_id=plan.old_external_id,
                new_external_id=plan.new_external_id,
                new_locator=plan.new_locator,
                reason=plan.reason,
                body_revision_possible=plan.body_revision_possible,
            )
            if current.token != expected or current.token != plan.token or current != plan:
                raise SourceIdentityError(
                    "Catalog changed since the identity plan was created; rerun dry-run"
                )
            # Use only the transaction-recomputed plan after validation;
            # callers cannot forge row IDs inside an otherwise valid token.
            plan = current
            if current.donor_source_id is not None and not current.donor_pristine:
                raise SourceIdentityError("Existing new Source is not pristine; refusing merge")
            timestamp = format_timestamp(now_jst())
            old = connection.execute(
                "SELECT s.*, i.work_id FROM sources s JOIN items i ON i.id = s.item_id "
                "WHERE s.id = ?",
                (plan.old_source_id,),
            ).fetchone()
            if old is None:
                raise SourceIdentityError("Old Source disappeared during precondition check")
            donor = plan.donor_source_id
            # Remove only a validated, history-free donor before changing
            # the unique (site, external_id) key on the retained Source.
            if donor is not None:
                connection.execute("DELETE FROM source_targets WHERE source_id = ?", (donor,))
                connection.execute("DELETE FROM sources WHERE id = ?", (donor,))
                if plan.donor_item_id is not None:
                    connection.execute("DELETE FROM items WHERE id = ?", (plan.donor_item_id,))
            connection.execute(
                "UPDATE sources SET external_id = ?, updated_at = ? WHERE id = ?",
                (plan.new_external_id, timestamp, plan.old_source_id),
            )
            targets = connection.execute(
                "SELECT * FROM source_targets WHERE source_id = ? ORDER BY id",
                (plan.old_source_id,),
            ).fetchall()
            matching = [
                row for row in targets if row["backend"] == "web" and row["target_key"] == "default"
            ]
            if matching:
                connection.execute(
                    "UPDATE source_targets SET locator = ?, updated_at = ? WHERE id = ?",
                    (plan.new_locator, timestamp, matching[0]["id"]),
                )
            else:
                connection.execute(
                    "INSERT INTO source_targets "
                    "(source_id, backend, target_key, locator, priority, enabled, created_at, updated_at) "
                    "VALUES (?, 'web', 'default', ?, 100, 1, ?, ?)",
                    (plan.old_source_id, plan.new_locator, timestamp, timestamp),
                )
            # Identity changes invalidate every listing proof for this Work
            # and site.  A later complete Full Discovery rebuilds evidence for
            # all current discovery keys, including keys other than the one
            # that first observed the old identity.
            connection.execute(
                "DELETE FROM discovery_inventory_evidence WHERE work_id = ? AND site = ?",
                (old["work_id"], plan.site),
            )
            connection.execute(
                "UPDATE acquisition_scope_sync SET status = 'stale' "
                "WHERE work_id = (SELECT work_id FROM items WHERE id = ?)",
                (plan.old_item_id,),
            )
            return current

    @staticmethod
    def _validate_args(*values: str) -> None:
        names = ("site", "work_key", "old_external_id", "new_external_id", "new_locator", "reason")
        for name, value in zip(names, values):
            if not isinstance(value, str) or not value.strip():
                raise SourceIdentityError(f"{name} must be a non-empty string")
        if values[2] == values[3]:
            raise SourceIdentityError("old and new external IDs must differ")

    def _reject_wal_snapshot(self) -> None:
        wal_path = Path(f"{self.catalog.path}-wal")
        try:
            with self.catalog.path.open("rb") as stream:
                header = stream.read(20)
            if header.startswith(b"SQLite format 3\x00") and 2 in header[18:20]:
                raise SourceIdentityError(
                    "Identity dry-run requires a stable rollback-journal Catalog; "
                    "create an explicit non-WAL backup before planning"
                )
            if wal_path.exists() and wal_path.stat().st_size:
                raise SourceIdentityError(
                    "Identity dry-run requires a stable rollback-journal Catalog; "
                    "finish or copy the active WAL before planning"
                )
        except OSError as exc:
            raise SourceIdentityError("Cannot verify Catalog journal state") from exc

    def _plan_connection(self, connection: sqlite3.Connection, **kwargs: Any) -> SourceIdentityPlan:
        site = kwargs["site"]
        old_id = kwargs["old_external_id"]
        new_id = kwargs["new_external_id"]
        work_key = kwargs["work_key"]
        old = connection.execute(
            "SELECT s.*, i.item_title, i.work_id, i.status AS item_status, i.completed_at, i.note, w.work_key "
            "FROM sources s JOIN items i ON i.id = s.item_id JOIN works w ON w.id = i.work_id "
            "WHERE s.site = ? AND s.external_id = ?",
            (site, old_id),
        ).fetchone()
        if old is None:
            raise SourceIdentityError(f"Old Source not found: ({site}, {old_id})")
        if old["work_key"] != work_key:
            raise SourceIdentityError("Old Source does not belong to the requested Work")
        donor = connection.execute(
            "SELECT s.*, i.item_title, i.work_id, i.status AS item_status, i.completed_at, i.note, w.work_key "
            "FROM sources s JOIN items i ON i.id = s.item_id JOIN works w ON w.id = i.work_id "
            "WHERE s.site = ? AND s.external_id = ?",
            (site, new_id),
        ).fetchone()
        if donor is not None and donor["work_key"] != work_key:
            raise SourceIdentityError("New Source belongs to a different Work")
        if donor is not None and donor["discovery_key"] != old["discovery_key"]:
            raise SourceIdentityError("Old and new Sources belong to different Discovery keys")
        if connection.execute(
            "SELECT 1 FROM crawl_runs WHERE (source_id = ? OR item_id = ?) "
            "AND status = 'running' LIMIT 1",
            (old["id"], old["item_id"]),
        ).fetchone():
            raise SourceIdentityError("Old Source has a running CrawlRun; refusing identity change")
        old_target = connection.execute(
            "SELECT locator FROM source_targets WHERE source_id = ? AND backend = 'web' AND target_key = 'default'",
            (old["id"],),
        ).fetchone()
        donor_pristine = donor is None or self._donor_pristine(connection, donor)
        if donor is not None and not donor_pristine:
            raise SourceIdentityError("Existing new Source is not pristine; refusing merge")
        token_payload = {
            "site": site,
            "work_key": work_key,
            "old_external_id": old_id,
            "new_external_id": new_id,
            "old": dict(old),
            "donor": None if donor is None else dict(donor),
            "old_target": None if old_target is None else old_target["locator"],
            "old_targets": [
                dict(row)
                for row in connection.execute(
                    "SELECT backend, target_key, locator, priority, enabled "
                    "FROM source_targets WHERE source_id = ? ORDER BY id",
                    (old["id"],),
                ).fetchall()
            ],
            "donor_targets": []
            if donor is None
            else [
                dict(row)
                for row in connection.execute(
                    "SELECT backend, target_key, locator, priority, enabled "
                    "FROM source_targets WHERE source_id = ? ORDER BY id",
                    (donor["id"],),
                ).fetchall()
            ],
            "new_locator": kwargs["new_locator"],
            "reason": kwargs["reason"],
            "body_revision_possible": bool(kwargs["body_revision_possible"]),
        }
        token = hashlib.sha256(
            json.dumps(token_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        target_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM source_targets WHERE source_id = ?", (old["id"],)
            ).fetchone()[0]
        )
        return SourceIdentityPlan(
            site=site,
            work_key=work_key,
            old_external_id=old_id,
            new_external_id=new_id,
            new_locator=kwargs["new_locator"],
            reason=kwargs["reason"],
            body_revision_possible=bool(kwargs["body_revision_possible"]),
            old_source_id=int(old["id"]),
            old_item_id=int(old["item_id"]),
            old_locator=None if old_target is None else old_target["locator"],
            old_discovery_key=old["discovery_key"],
            donor_source_id=None if donor is None else int(donor["id"]),
            donor_item_id=None if donor is None else int(donor["item_id"]),
            donor_pristine=donor_pristine,
            source_target_count=target_count,
            token=token,
        )

    @staticmethod
    def _donor_pristine(connection: sqlite3.Connection, donor: sqlite3.Row) -> bool:
        if (
            donor["item_title"] is not None
            or
            donor["item_status"] != "pending"
            or donor["completed_at"] is not None
            or donor["note"] is not None
        ):
            return False
        source_id = donor["id"]
        if connection.execute(
            "SELECT 1 FROM crawl_runs WHERE source_id = ? OR item_id = ? LIMIT 1",
            (source_id, donor["item_id"]),
        ).fetchone():
            return False
        if connection.execute(
            "SELECT 1 FROM artifacts WHERE item_id = ? LIMIT 1", (donor["item_id"],)
        ).fetchone():
            return False
        if donor["quota_started_at"] is not None or donor["access_granted_until"] is not None:
            return False
        if connection.execute(
            "SELECT 1 FROM sources WHERE item_id = ? AND id != ? LIMIT 1",
            (donor["item_id"], source_id),
        ).fetchone():
            return False
        # A newly discovered row may have its normal web target.  Other target
        # shapes are operator state and are conservatively treated as a conflict.
        targets = connection.execute(
            "SELECT backend, target_key, priority, enabled FROM source_targets WHERE source_id = ?",
            (source_id,),
        ).fetchall()
        return all(
            row["backend"] == "web"
            and row["target_key"] == "default"
            and row["priority"] == 100
            and row["enabled"] == 1
            for row in targets
        )

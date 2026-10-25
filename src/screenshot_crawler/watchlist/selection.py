"""Pure conversion of a complete listing checkbox set into Watchlist scope."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from screenshot_crawler.discovery.listing import ListingPreview, ListingRow, listing_digest
from screenshot_crawler.watchlist.models import DiscoveryScope


@dataclass(frozen=True, slots=True)
class ScopePreviewRow:
    """A listing row joined with a read-only Catalog snapshot."""

    external_id: str
    site_position: int
    url: str
    source_id: int | None
    owner_key: str | None
    current_acquisition_enabled: bool | None
    proposed_acquisition_enabled: bool | None
    change: str


@dataclass(frozen=True, slots=True)
class ArchiveArtifactFact:
    """Immutable read-only join of a current ZIP Artifact and its Source."""

    source_id: int
    artifact_id: int
    locator: str | None
    state: str
    run_source_id: int | None = None


@dataclass(frozen=True, slots=True)
class ArchiveFactsSnapshot:
    """Bound archive facts used to make a non-speculative numbering preview."""

    snapshot_id: str
    before_positions: tuple[tuple[int, int | None], ...]
    artifacts: tuple[ArchiveArtifactFact, ...] = ()
    collision_source_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ScopeEditPreview:
    """No-write prediction used by GUI before Watchlist or Full changes."""

    proposed_target: Any
    rows: tuple[ScopePreviewRow, ...]
    selected_count: int
    excluded_count: int
    new_count: int
    retained_count: int
    removed_count: int
    unknown_count: int
    owner_conflict_count: int
    listing_identity: str
    listing_digest: str | None
    watchlist_revision: str | None
    watchlist_content_sha: str | None
    catalog_snapshot_id: str | None
    observed_at: datetime
    archive_order_preview: Mapping[str, Any] | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blockers

    @property
    def token(self) -> str:
        payload = {
            "target": {
                "key": self.proposed_target.key,
                "work_key": self.proposed_target.work_key,
                "site": self.proposed_target.site,
                "url": self.proposed_target.url,
                "label": self.proposed_target.label,
                "enabled": self.proposed_target.enabled,
                "archive_order": self.proposed_target.archive_order,
                "discovery_scope": (
                    None
                    if self.proposed_target.discovery_scope is None
                    else {
                        "from_url": self.proposed_target.discovery_scope.from_url,
                        "through_url": self.proposed_target.discovery_scope.through_url,
                        "excluded_external_ids": sorted(
                            self.proposed_target.discovery_scope.excluded_external_ids
                        ),
                    }
                ),
            },
            "listing_identity": self.listing_identity,
            "listing_digest": self.listing_digest,
            "watchlist_revision": self.watchlist_revision,
            "watchlist_content_sha": self.watchlist_content_sha,
            "catalog_snapshot_id": self.catalog_snapshot_id,
            "observed_at": self.observed_at.isoformat(),
            "archive_order_preview": self.archive_order_preview,
            "rows": [
                {
                    "external_id": row.external_id,
                    "site_position": row.site_position,
                    "url": row.url,
                    "source_id": row.source_id,
                    "owner_key": row.owner_key,
                    "current_acquisition_enabled": row.current_acquisition_enabled,
                    "proposed_acquisition_enabled": row.proposed_acquisition_enabled,
                    "change": row.change,
                }
                for row in self.rows
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            .encode("utf-8")
        ).hexdigest()

    def is_fresh(self, *, now: datetime | None = None, max_age_seconds: int = 300) -> bool:
        current = datetime.now(UTC) if now is None else now
        if current.tzinfo is None or self.observed_at.tzinfo is None:
            return False
        age = (current - self.observed_at).total_seconds()
        return (
            0 <= age <= max_age_seconds
            and self.listing_digest is not None
            and self.watchlist_revision is not None
            and self.watchlist_content_sha is not None
            and self.catalog_snapshot_id is not None
        )


@dataclass(frozen=True, slots=True)
class ScopeSelectionPlan:
    site: str
    target_key: str
    listing_identity: str
    selected_external_ids: tuple[str, ...]
    excluded_external_ids: tuple[str, ...]
    discovery_scope: DiscoveryScope | None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blockers

    @property
    def selected_count(self) -> int:
        return len(self.selected_external_ids)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_external_ids)


class SelectionPlanner:
    """Build inclusive range plus hole IDs without accessing Catalog or sites."""

    def plan(
        self,
        listing: ListingPreview,
        checked_external_ids: Iterable[str],
        *,
        existing_scope: DiscoveryScope | None = None,
    ) -> ScopeSelectionPlan:
        blockers: list[str] = []
        warnings: list[str] = []
        rows = tuple(listing.rows)
        self._validate_listing(listing, blockers)
        try:
            raw_checked = tuple(checked_external_ids)
        except TypeError:
            raw_checked = ()
        valid_checked = tuple(value for value in raw_checked if isinstance(value, str) and value)
        checked = tuple(dict.fromkeys(valid_checked))
        valid_rows = tuple(
            row for row in rows if isinstance(row, ListingRow) and row.external_id
        )
        known_ids = tuple(row.external_id for row in valid_rows)
        known_set = set(known_ids)
        if len(valid_checked) != len(raw_checked):
            blockers.append("Checked episode IDs must be non-empty strings")
        unknown = sorted(set(valid_checked) - known_set)
        if unknown:
            blockers.append("Checked episode IDs are absent from the complete listing: " + ", ".join(unknown[:5]))
        if not checked:
            blockers.append("At least one episode must be selected")
        checked_set = set(checked)
        selected = tuple(row.external_id for row in valid_rows if row.external_id in checked_set)
        excluded = tuple(row.external_id for row in valid_rows if row.external_id not in checked_set)
        scope: DiscoveryScope | None
        if not blockers:
            if len(selected) == len(rows):
                scope = None
                excluded = ()
            else:
                selected_set = set(selected)
                first_index = next(
                    index for index, row in enumerate(valid_rows) if row.external_id in selected_set
                )
                last_index = max(
                    index for index, row in enumerate(valid_rows) if row.external_id in selected_set
                )
                first = valid_rows[first_index]
                last = valid_rows[last_index]
                inner_ids = {
                    row.external_id
                    for row in valid_rows[first_index : last_index + 1]
                    if row.external_id not in selected_set
                }
                excluded = tuple(row.external_id for row in valid_rows if row.external_id in inner_ids)
                scope = DiscoveryScope(
                    from_url=first.url,
                    through_url=last.url,
                    excluded_external_ids=tuple(sorted(excluded)),
                )
                if len(selected) == 1:
                    warnings.append("A single selected episode becomes an inclusive one-episode range")
        else:
            scope = None
        if existing_scope != scope and existing_scope is not None:
            warnings.append("The proposed range or exclusions differ from the saved scope")
        return ScopeSelectionPlan(
            site=listing.site,
            target_key=listing.target_key,
            listing_identity=listing.listing_identity or "",
            selected_external_ids=selected,
            excluded_external_ids=excluded,
            discovery_scope=scope,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def preview_edit(
        self,
        listing: ListingPreview,
        checked_external_ids: Iterable[str],
        *,
        current_target,
        catalog_sources: Iterable[Any] = (),
        watchlist_revision: str | None = None,
        watchlist_content_sha: str | None = None,
        catalog_snapshot_id: str | None = None,
        observed_at: datetime | None = None,
        archive_work: Any | None = None,
        archive_items: Iterable[Any] = (),
        archive_targets: Iterable[Any] = (),
        archive_facts: ArchiveFactsSnapshot | None = None,
        sibling_listings: Mapping[str, ListingPreview] | None = None,
        sibling_checked_external_ids: Mapping[str, Iterable[str]] | None = None,
        sibling_targets: Iterable[Any] = (),
    ) -> ScopeEditPreview:
        """Join a pure checkbox proposal with a read-only Catalog snapshot.

        ``catalog_sources`` is deliberately an iterable of immutable Source
        rows. The method never opens Catalog, writes flags, or calls an
        adapter; callers obtain the snapshot and bind its revision token.
        """

        proposed_target = replace(current_target, discovery_scope=None)
        blockers: list[str] = []
        if (
            current_target.site != listing.site
            or current_target.key != listing.target_key
            or current_target.url != listing.target_url
        ):
            blockers.append("Watchlist target does not match the complete listing identity")
        plan = self.plan(
            listing,
            checked_external_ids,
            existing_scope=current_target.discovery_scope,
        )
        blockers.extend(plan.blockers)
        warnings = list(plan.warnings)
        # A complete listing is required to prove that two same-site keys do
        # not claim the same native episode before either key has a Catalog
        # Source.  Existing Source ownership alone cannot provide that proof.
        if sibling_listings is not None:
            checked_by_key = sibling_checked_external_ids or {}
            current_selected = set(plan.selected_external_ids)
            for sibling_key, sibling_listing in sibling_listings.items():
                if sibling_key == current_target.key:
                    continue
                sibling_plan = self.plan(
                    sibling_listing,
                    checked_by_key.get(sibling_key, ()),
                )
                if not sibling_plan.ready:
                    blockers.append(
                        f"Sibling Watchlist key {sibling_key!r} has no complete scope proof"
                    )
                    continue
                if sibling_listing.site != listing.site:
                    continue
                overlap = current_selected.intersection(sibling_plan.selected_external_ids)
                if overlap:
                    blockers.append(
                        "Same-site Watchlist scopes overlap for episode IDs: "
                        + ", ".join(sorted(overlap)[:8])
                    )
        for sibling in sibling_targets:
            if getattr(sibling, "key", None) == current_target.key:
                continue
            if getattr(sibling, "site", None) != listing.site:
                continue
            if (
                sibling_listings is None
                or getattr(sibling, "key", None) not in sibling_listings
            ):
                blockers.append(
                    f"Sibling Watchlist key {sibling.key!r} scope membership is unresolved"
                )
        sources = tuple(catalog_sources)
        same_key = {
            source.external_id: source
            for source in sources
            if source.site == listing.site and source.discovery_key == listing.target_key
        }
        owners: dict[str, list[Any]] = {}
        for source in sources:
            if source.site == listing.site:
                owners.setdefault(source.external_id, []).append(source)
        from screenshot_crawler.watchlist.reconcile import classify_scope_source

        selected = set(plan.selected_external_ids)
        retained_count = 0
        removed_count = 0
        unknown_count = 0
        rows: list[ScopePreviewRow] = []
        owner_conflicts = 0
        new_count = 0
        for row in listing.rows:
            if not isinstance(row, ListingRow):
                continue
            source = same_key.get(row.external_id)
            foreign = [
                candidate
                for candidate in owners.get(row.external_id, ())
                if candidate.discovery_key != listing.target_key
            ]
            is_selected = row.external_id in selected
            source_class = (
                classify_scope_source(
                    source,
                    target_site=listing.site,
                    target_key=listing.target_key,
                    selected_external_ids=selected,
                )
                if source is not None
                else "foreign_owner" if foreign else "unregistered"
            )
            if is_selected and foreign:
                owner_conflicts += 1
                unknown_count += 1
                blockers.append(
                    f"Episode {row.external_id!r} is owned by another Watchlist key"
                )
            if source is None:
                new_count += int(is_selected and not foreign)
                change = "add" if is_selected and not foreign else "excluded_unregistered"
                current_enabled = foreign[0].acquisition_enabled if foreign else None
                proposed_enabled = True if is_selected and not foreign else current_enabled
                owner_key = foreign[0].discovery_key if foreign else None
                if is_selected and foreign:
                    change = "owner_conflict"
                if not is_selected and not foreign:
                    unknown_count += 1
            else:
                current_enabled = source.acquisition_enabled
                proposed_enabled = is_selected
                owner_key = source.discovery_key
                if is_selected == current_enabled:
                    change = "keep"
                else:
                    change = "enable" if is_selected else "exclude"
                if foreign and not is_selected:
                    # A foreign owner remains untouched when this key excludes
                    # the row; it is shown as a warning rather than reparented.
                    change = "excluded_foreign_owner"
                    proposed_enabled = current_enabled
                    warnings.append(
                        f"Excluded row {row.external_id!r} remains owned by another Watchlist key"
                    )
                if foreign or source_class == "foreign_owner":
                    unknown_count += 1
                elif is_selected:
                    retained_count += 1
                else:
                    removed_count += 1
            rows.append(
                ScopePreviewRow(
                    external_id=row.external_id,
                    site_position=row.site_position,
                    url=row.url,
                    source_id=(
                        source.id
                        if source is not None
                        else (foreign[0].id if foreign else None)
                    ),
                    owner_key=owner_key,
                    current_acquisition_enabled=current_enabled,
                    proposed_acquisition_enabled=proposed_enabled,
                    change=change,
                )
            )
        listing_ids = {
            row.external_id for row in listing.rows if isinstance(row, ListingRow)
        }
        for source in same_key.values():
            if source.external_id in listing_ids:
                continue
            rows.append(
                ScopePreviewRow(
                    external_id=source.external_id,
                    site_position=getattr(source, "display_position", None) or 0,
                    url="",
                    source_id=source.id,
                    owner_key=source.discovery_key,
                    current_acquisition_enabled=source.acquisition_enabled,
                    proposed_acquisition_enabled=None,
                    change="catalog_missing_from_listing",
                )
            )
            blockers.append(
                f"Catalog Source {source.id} is absent from the complete listing"
            )
            unknown_count += 1
        proposed_target = replace(current_target, discovery_scope=plan.discovery_scope)
        proposed_archive_targets = tuple(archive_targets)
        if proposed_archive_targets:
            proposed_archive_targets = tuple(
                proposed_target if target.key == proposed_target.key else target
                for target in proposed_archive_targets
            )
        archive_preview = self._archive_preview(
            archive_work,
            tuple(archive_items),
            proposed_archive_targets,
            sources,
            same_key,
            selected,
            blockers,
            archive_facts,
        )
        return ScopeEditPreview(
            proposed_target=proposed_target,
            rows=tuple(rows),
            selected_count=plan.selected_count,
            excluded_count=plan.excluded_count,
            new_count=new_count,
            retained_count=retained_count,
            removed_count=removed_count,
            unknown_count=unknown_count,
            owner_conflict_count=owner_conflicts,
            listing_identity=listing.listing_identity or "",
            listing_digest=listing.digest,
            watchlist_revision=watchlist_revision,
            watchlist_content_sha=watchlist_content_sha,
            catalog_snapshot_id=catalog_snapshot_id,
            observed_at=observed_at or listing.observed_at,
            archive_order_preview=archive_preview,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _archive_preview(
        work,
        items,
        targets,
        sources,
        same_key,
        selected,
        blockers: list[str],
        archive_facts: ArchiveFactsSnapshot | None,
    ) -> Mapping[str, Any] | None:
        if work is None or not targets:
            return None
        # Archive numbering is Work-wide, but unrelated Works must never enter
        # the position planner.  Ownership/conflict classification happens in
        # preview_edit before this helper and still sees every Catalog Source.
        item_ids = {item.id for item in items}
        sources = tuple(source for source in sources if source.item_id in item_ids)
        try:
            from screenshot_crawler.archive_order import (
                ArchiveOrderPlanningError,
                build_work_archive_position_plan,
            )
            from screenshot_crawler.batch.naming import catalog_archive_stem

            same_key_source_ids = {source.id for source in same_key.values()}
            flags = {}
            for source in sources:
                if source.id in same_key_source_ids:
                    flags[source.id] = source.external_id in selected
                else:
                    flags[source.id] = source.acquisition_enabled
            future = build_work_archive_position_plan(
                work, tuple(targets), tuple(items), sources,
                acquisition_flags=flags,
                provisional=True,
            )
        except (ValueError, ArchiveOrderPlanningError) as exc:
            blockers.append(f"Archive-order prediction is unresolved: {exc}")
            return {"ready": False, "number_changes": (), "unknown": True}
        if future is None:
            # A Work whose keys all use the legacy ``None`` archive order has
            # no work-wide ordinal stream to predict.  Scope preview remains
            # valid; Full/maintenance will continue to use the existing
            # legacy naming path until an explicit archive order is assigned.
            return {
                "ready": True,
                "number_changes": (),
                "unknown": False,
                "legacy_archive_order": True,
            }
        selected_unregistered = selected - set(same_key)
        if selected_unregistered:
            blockers.append(
                "Archive-order prediction is unknown for selected Catalog-unregistered rows: "
                + ", ".join(sorted(selected_unregistered)[:5])
            )
            return {
                "ready": False,
                "positions": tuple(sorted(future.positions_by_source_id.items())),
                "number_changes": (),
                "unknown": True,
                "unknown_reason": "Selected rows are not in the Catalog snapshot",
            }
        future_sources = [source for source in sources if source.id in future.positions_by_source_id]
        missing_positions = [
            source.id for source in future_sources if source.display_position is None
        ]
        if missing_positions:
            blockers.append(
                "Archive-order prediction has unknown source positions: "
                + ", ".join(str(source_id) for source_id in missing_positions[:5])
            )
            return {
                "ready": False,
                "positions": tuple(sorted(future.positions_by_source_id.items())),
                "number_changes": (),
                "unknown": True,
                "unknown_reason": "Source positions are incomplete",
            }
        if archive_facts is None:
            blockers.append("Immutable archive facts snapshot was not supplied")
            return {
                "ready": False,
                "positions": tuple(sorted(future.positions_by_source_id.items())),
                "number_changes": (),
                "unknown": True,
                "unknown_reason": "Archive facts are incomplete",
            }
        if not archive_facts.snapshot_id:
            blockers.append("Immutable archive facts snapshot has no identity")
            return {
                "ready": False,
                "positions": tuple(sorted(future.positions_by_source_id.items())),
                "number_changes": (),
                "unknown": True,
                "unknown_reason": "Archive facts snapshot identity is missing",
            }
        archive_blocker_count = len(blockers)
        collision_source_ids = tuple(sorted(set(archive_facts.collision_source_ids)))
        if collision_source_ids:
            blockers.append(
                "Archive facts contain unresolved collision Sources: "
                + ", ".join(str(source_id) for source_id in collision_source_ids[:5])
            )
        before_positions = dict(archive_facts.before_positions)
        if len(before_positions) != len(archive_facts.before_positions):
            blockers.append("Archive facts contain duplicate current positions")
        position_values = tuple(before_positions.values())
        if any(
            position is None
            or isinstance(position, bool)
            or not isinstance(position, int)
            or position < 1
            for position in position_values
        ):
            blockers.append("Archive facts contain missing or invalid current positions")
        if len(position_values) != len(set(position_values)):
            blockers.append("Archive facts contain duplicate current archive positions")
        if any(source_id not in {source.id for source in sources} for source_id in before_positions):
            blockers.append("Archive facts contain an unknown Source")
        artifact_by_source: dict[int, ArchiveArtifactFact] = {}
        for artifact in archive_facts.artifacts:
            if artifact.source_id in artifact_by_source:
                blockers.append(
                    f"Source {artifact.source_id} has ambiguous current ZIP Artifacts"
                )
                continue
            artifact_by_source[artifact.source_id] = artifact
            if artifact.run_source_id not in (None, artifact.source_id):
                blockers.append(
                    f"Artifact {artifact.artifact_id} is joined to the wrong Source"
                )
            if artifact.state == "present" and not artifact.locator:
                blockers.append(
                    f"Present Artifact {artifact.artifact_id} has no locator"
                )
        locators = [
            artifact.locator
            for artifact in artifact_by_source.values()
            if artifact.locator
        ]
        if len(locators) != len(set(locators)):
            blockers.append("Archive facts contain colliding Artifact locators")
        source_ids = {source.id for source in sources}
        if any(source_id not in source_ids for source_id in artifact_by_source):
            blockers.append("Archive facts contain an Artifact for an unknown Source")
        future_source_ids = set(future.positions_by_source_id)
        if any(source_id not in before_positions for source_id in future_source_ids):
            blockers.append("Archive-order before positions are incomplete")
        source_by_id = {source.id: source for source in sources}
        item_by_id = {item.id: item for item in items}
        expected_stems: dict[int, str] = {}
        for source_id in artifact_by_source:
            if source_id not in future_source_ids:
                continue
            source = source_by_id.get(source_id)
            item = item_by_id.get(source.item_id) if source is not None else None
            if source is None or item is None:
                blockers.append(
                    f"Source {source_id} has no Item while previewing its archive"
                )
                continue
            expected_stems[source_id] = catalog_archive_stem(
                work,
                item,
                source,
                archive_position=future.positions_by_source_id[source_id],
                artifact_disambiguator=(
                    f"{source.site}-{source.external_id}"
                    if source_id in collision_source_ids
                    else None
                ),
            )
        artifact_rows = tuple(
            {
                "source_id": source_id,
                "artifact_id": artifact.artifact_id,
                "locator": artifact.locator,
                "state": artifact.state,
                "current_stem": (
                    Path(artifact.locator).stem
                    if artifact.locator
                    else None
                ),
                "expected_stem": expected_stems[source_id],
                "renumber_required": (
                    artifact.locator is not None
                    and Path(artifact.locator).stem != expected_stems[source_id]
                ),
            }
            for source_id, artifact in sorted(artifact_by_source.items())
            if source_id in expected_stems
        )
        changes = tuple(
            {
                "source_id": source_id,
                "from": before_positions.get(source_id),
                "to": after,
            }
            for source_id, after in sorted(future.positions_by_source_id.items())
            if source_id not in before_positions or before_positions.get(source_id) != after
        )
        unknown = (
            any(source_id not in before_positions for source_id in future.positions_by_source_id)
            or len(blockers) > archive_blocker_count
        )
        return {
            "ready": not unknown,
            "snapshot_id": archive_facts.snapshot_id,
            "positions": tuple(sorted(future.positions_by_source_id.items())),
            "number_changes": changes,
            "artifacts": artifact_rows,
            "collision_source_ids": collision_source_ids,
            "renumber_required_source_ids": tuple(
                row["source_id"] for row in artifact_rows if row["renumber_required"]
            ),
            "unknown": unknown,
        }

    @staticmethod
    def _validate_listing(listing: ListingPreview, blockers: list[str]) -> None:
        if not listing.complete or listing.digest is None or listing.blockers:
            blockers.extend(listing.blockers or ("Complete listing proof is unavailable",))
        if not listing.listing_identity:
            blockers.append("Complete listing identity is missing")
        ids: list[str] = []
        positions: list[int] = []
        urls: list[str] = []
        for row in listing.rows:
            if not isinstance(row, ListingRow) or not row.external_id or not row.url:
                blockers.append("Complete listing contains an invalid row")
                continue
            if listing.listing_identity and row.listing_identity != listing.listing_identity:
                blockers.append("Complete listing row identity does not match listing identity")
            ids.append(row.external_id)
            positions.append(row.site_position)
            urls.append(row.url)
        if len(ids) != len(set(ids)):
            blockers.append("Complete listing contains duplicate episode IDs")
        if len(positions) != len(set(positions)) or any(position < 1 for position in positions):
            blockers.append("Complete listing positions are missing or ambiguous")
        if len(urls) != len(set(urls)):
            blockers.append("Complete listing URLs are duplicated")
        if positions and (
            positions != sorted(positions, reverse=True)
            or any(left - right != 1 for left, right in pairwise(positions))
        ):
            blockers.append(
                "Complete listing order is not a contiguous site-native newest-first sequence"
            )
        if (
            listing.listing_identity
            and all(isinstance(row, ListingRow) for row in listing.rows)
            and listing.digest != listing_digest(listing.listing_identity, tuple(listing.rows))
        ):
            blockers.append("Complete listing digest does not match its rows")

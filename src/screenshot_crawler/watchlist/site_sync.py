"""Bulk scope-sync orchestration for all Watchlist works on one site."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.watchlist.fingerprints import work_scope_fingerprint
from screenshot_crawler.watchlist.reconcile import (
    ScopeReconciler,
    ScopeSyncPreview,
)
from screenshot_crawler.watchlist.service import WatchlistService


@dataclass(frozen=True, slots=True)
class ScopeSiteSyncPreview:
    """Read-only previews for the distinct works selected by one site."""

    site: str
    target_keys: tuple[str, ...]
    work_keys: tuple[str, ...]
    selection_fingerprint: str
    works: tuple[ScopeSyncPreview, ...]
    blockers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.work_keys) and not self.blockers and all(
            preview.ready for preview in self.works
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "site": self.site,
            "target_keys": list(self.target_keys),
            "work_keys": list(self.work_keys),
            "selection_fingerprint": self.selection_fingerprint,
            "ready": self.ready,
            "target_count": len(self.target_keys),
            "work_count": len(self.work_keys),
            "ready_work_count": sum(preview.ready for preview in self.works),
            "blocked_work_count": sum(not preview.ready for preview in self.works),
            "blockers": list(self.blockers),
            "works": [preview.to_dict() for preview in self.works],
        }


@dataclass(frozen=True, slots=True)
class ScopeSiteSyncApplyResult:
    """Outcome of applying a site preview, including safe partial progress."""

    site: str
    selection_fingerprint: str
    selected_work_keys: tuple[str, ...]
    applied_work_keys: tuple[str, ...]
    not_applied_work_keys: tuple[str, ...]
    failed_work_key: str | None
    failure_stage: str | None
    selection_changed: bool
    complete: bool
    error: str | None
    preview: ScopeSiteSyncPreview

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["selected_work_keys"] = list(self.selected_work_keys)
        result["applied_work_keys"] = list(self.applied_work_keys)
        result["not_applied_work_keys"] = list(self.not_applied_work_keys)
        result["preview"] = self.preview.to_dict()
        return result


class ScopeSiteSyncService:
    """Select, preview, and apply all Watchlist works that include a site.

    Preview performs no lock or write. Apply holds the shared Catalog job lock,
    validates every work before changing any, then uses the existing atomic
    per-work reconciliation. The service deliberately reports partial progress
    rather than claiming site-wide transactional atomicity.
    """

    def __init__(self, watchlist: WatchlistService, catalog: CatalogService) -> None:
        self.watchlist = watchlist
        self.catalog = catalog
        self.reconciler = ScopeReconciler(watchlist, catalog)

    def preview_site(self, site: str) -> ScopeSiteSyncPreview:
        """Return all distinct site-selected Work previews, including disabled keys."""

        targets = self._site_targets(site)
        target_keys = tuple(sorted(target.key for target in targets))
        work_keys = tuple(sorted({target.work_key for target in targets}))
        fingerprint = self._selection_fingerprint(site, targets)
        works = tuple(self.reconciler.preview(work_key) for work_key in work_keys)
        blockers: list[str] = []
        if not targets:
            blockers.append(f"No Watchlist targets found for site {site!r}")
        for preview in works:
            blockers.extend(
                f"{preview.work_key}: {blocker}" for blocker in preview.blockers
            )
        return ScopeSiteSyncPreview(
            site=site,
            target_keys=target_keys,
            work_keys=work_keys,
            selection_fingerprint=fingerprint,
            works=works,
            blockers=tuple(blockers),
        )

    def apply_site(self, preview: ScopeSiteSyncPreview) -> ScopeSiteSyncApplyResult:
        """Apply all work previews only after site-wide preflight succeeds.

        Each Work retains the Catalog's existing transaction and CAS check.
        A later unexpected failure stops the sequence and returns the committed
        and remaining work keys; successfully applied Works are not rolled back.
        """

        if not preview.ready:
            return self._failure(
                preview,
                error="Site scope preview is blocked; no work was applied",
                failed_work_key=self._first_blocked_work(preview),
                not_applied_work_keys=preview.work_keys,
                failure_stage="preflight",
            )

        applied: list[str] = []
        active_work_key: str | None = None
        stage = "preflight"
        try:
            with self.catalog.job_lock():
                current = self.preview_site(preview.site)
                stale_reason = self._preflight_error(preview, current)
                if stale_reason is not None:
                    return self._failure(
                        current,
                        error=stale_reason,
                        failed_work_key=self._first_blocked_work(current),
                        not_applied_work_keys=self._remaining_keys(preview, current, applied),
                        failure_stage="preflight",
                        requested_preview=preview,
                        selection_changed=(
                            current.selection_fingerprint != preview.selection_fingerprint
                        ),
                    )

                current_by_key = {value.work_key: value for value in current.works}
                for work_key in preview.work_keys:
                    selection_error, observed_keys = self._check_selection(preview)
                    if selection_error is not None:
                        try:
                            changed = self.preview_site(preview.site)
                        except Exception:  # noqa: BLE001 - preserve selection-change outcome
                            changed = current
                        return self._failure(
                            changed,
                            error=selection_error,
                            failed_work_key=None,
                            not_applied_work_keys=self._remaining_keys(
                                preview, changed, applied, observed_keys
                            ),
                            failure_stage="selection",
                            requested_preview=preview,
                            selection_changed=True,
                            applied_work_keys=applied,
                        )
                    active_work_key = work_key
                    stage = "apply"
                    try:
                        self.reconciler.apply(current_by_key[work_key])
                    except Exception as exc:  # noqa: BLE001 - commit may precede the error
                        try:
                            changed = self.preview_site(preview.site)
                        except Exception:  # noqa: BLE001 - keep the primary apply failure
                            # Preserve the primary failure and known progress if
                            # a second Watchlist read also fails.
                            changed = current
                        return self._failure(
                            changed,
                            error=f"Apply failed for work_key {work_key!r}: {exc}",
                            failed_work_key=work_key,
                            not_applied_work_keys=self._remaining_keys(
                                preview,
                                changed,
                                applied,
                                observed_keys,
                                attempted_failure_key=work_key,
                            ),
                            failure_stage="apply",
                            requested_preview=preview,
                            selection_changed=(
                                changed.selection_fingerprint
                                != preview.selection_fingerprint
                            ),
                            applied_work_keys=applied,
                        )
                    applied.append(work_key)
                    active_work_key = None
                    stage = "preflight"

                # Re-read the entire selection after the last work transaction;
                # checking only the old target list immediately before this
                # read would leave a race that could silently omit new works.
                stage = "final_validation"
                final_preview = self.preview_site(preview.site)
                selection_error = self._selection_difference(preview, final_preview)
                if selection_error is not None:
                    return self._failure(
                        final_preview,
                        error=selection_error,
                        failed_work_key=None,
                        not_applied_work_keys=self._remaining_keys(
                            preview, final_preview, applied
                        ),
                        failure_stage="selection",
                        requested_preview=preview,
                        selection_changed=True,
                        applied_work_keys=applied,
                    )
                if not final_preview.ready:
                    return self._failure(
                        final_preview,
                        error="Final site scope preview is blocked after applying work scopes",
                        failed_work_key=self._first_blocked_work(final_preview),
                        not_applied_work_keys=(),
                        failure_stage="final_validation",
                        requested_preview=preview,
                        applied_work_keys=applied,
                    )
                for work_key in final_preview.work_keys:
                    try:
                        self.reconciler.require_synchronized(work_key)
                    except Exception as exc:  # noqa: BLE001 - report any final gate failure
                        return self._failure(
                            final_preview,
                            error=f"Final scope validation failed for {work_key!r}: {exc}",
                            failed_work_key=work_key,
                            not_applied_work_keys=(),
                            failure_stage="final_validation",
                            requested_preview=preview,
                            applied_work_keys=applied,
                        )
                # The per-Work synchronization checks reread the Watchlist.
                # Use one final snapshot to check both site membership and the
                # full configuration of every selected Work. This catches a
                # cross-site key/scope/order edit during the validation pass.
                final_targets = tuple(self.watchlist.list_targets())
                selection_error, observed_keys = self._final_configuration_error(
                    preview, final_targets
                )
                if selection_error is not None:
                    return self._failure(
                        final_preview,
                        error=selection_error,
                        failed_work_key=None,
                        not_applied_work_keys=self._remaining_keys(
                            preview, final_preview, applied, observed_keys
                        ),
                        failure_stage="selection",
                        requested_preview=preview,
                        selection_changed=True,
                        applied_work_keys=applied,
                    )
        except Exception as exc:  # noqa: BLE001 - return known partial progress on any failure
            return self._failure(
                preview,
                error=f"Site scope apply stopped: {exc}",
                failed_work_key=active_work_key,
                not_applied_work_keys=self._remaining_keys(
                    preview,
                    preview,
                    applied,
                    attempted_failure_key=active_work_key if stage == "apply" else None,
                ),
                failure_stage=stage,
                applied_work_keys=applied,
            )

        return ScopeSiteSyncApplyResult(
            site=preview.site,
            selection_fingerprint=preview.selection_fingerprint,
            selected_work_keys=preview.work_keys,
            applied_work_keys=tuple(applied),
            not_applied_work_keys=(),
            failed_work_key=None,
            failure_stage=None,
            selection_changed=False,
            complete=True,
            error=None,
            preview=final_preview,
        )

    def _site_targets(self, site: str):
        # Site selection is Watchlist-authoritative. Unknown site strings simply
        # produce no targets; Catalog contents are never used as a fallback.
        return tuple(
            target for target in self.watchlist.list_targets() if target.site == site
        )

    @staticmethod
    def _selection_fingerprint(site: str, targets: tuple) -> str:
        selection = sorted((target.key, target.work_key, target.site) for target in targets)
        payload = json.dumps([site, selection], ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _check_selection(
        self, preview: ScopeSiteSyncPreview
    ) -> tuple[str | None, tuple[str, ...]]:
        targets = self._site_targets(preview.site)
        observed_keys = tuple(sorted({target.work_key for target in targets}))
        observed_fingerprint = self._selection_fingerprint(preview.site, targets)
        if self._selection_difference(
            preview,
            site=preview.site,
            fingerprint=observed_fingerprint,
            work_keys=observed_keys,
            target_keys=tuple(sorted(target.key for target in targets)),
        ) is not None:
            return (
                "Site Watchlist selection changed during apply; review a new site preview",
                observed_keys,
            )
        return None, observed_keys

    @classmethod
    def _final_configuration_error(
        cls,
        expected: ScopeSiteSyncPreview,
        targets: tuple,
    ) -> tuple[str | None, tuple[str, ...]]:
        selected_targets = tuple(
            target for target in targets if target.site == expected.site
        )
        observed_keys = tuple(sorted({target.work_key for target in selected_targets}))
        observed_target_keys = tuple(sorted(target.key for target in selected_targets))
        if cls._selection_difference(
            expected,
            site=expected.site,
            fingerprint=cls._selection_fingerprint(expected.site, selected_targets),
            work_keys=observed_keys,
            target_keys=observed_target_keys,
        ) is not None:
            return (
                "Site Watchlist selection changed during apply; review a new site preview",
                observed_keys,
            )

        expected_work_fingerprints = {
            preview.work_key: preview.fingerprint for preview in expected.works
        }
        targets_by_work: dict[str, list] = {}
        for target in targets:
            if target.work_key in expected_work_fingerprints:
                targets_by_work.setdefault(target.work_key, []).append(target)
        for work_key, fingerprint in expected_work_fingerprints.items():
            if work_scope_fingerprint(targets_by_work.get(work_key, ())) != fingerprint:
                return (
                    "Watchlist work configuration changed during apply; review a new site preview",
                    observed_keys,
                )
        return None, observed_keys

    @staticmethod
    def _selection_difference(
        expected: ScopeSiteSyncPreview,
        current: ScopeSiteSyncPreview | None = None,
        *,
        site: str | None = None,
        fingerprint: str | None = None,
        work_keys: tuple[str, ...] | None = None,
        target_keys: tuple[str, ...] | None = None,
    ) -> str | None:
        actual_site = current.site if current is not None else site
        actual_fingerprint = (
            current.selection_fingerprint if current is not None else fingerprint
        )
        actual_work_keys = current.work_keys if current is not None else work_keys
        actual_target_keys = current.target_keys if current is not None else target_keys
        if (
            actual_site != expected.site
            or actual_fingerprint != expected.selection_fingerprint
            or actual_work_keys != expected.work_keys
            or actual_target_keys != expected.target_keys
        ):
            return "Site Watchlist selection changed during apply; review a new site preview"
        return None

    @staticmethod
    def _preflight_error(
        original: ScopeSiteSyncPreview, current: ScopeSiteSyncPreview
    ) -> str | None:
        if (
            current.selection_fingerprint != original.selection_fingerprint
            or current.target_keys != original.target_keys
            or current.work_keys != original.work_keys
        ):
            return "Site Watchlist selection changed after preview; create a new preview"
        if not current.ready:
            return "Site scope preflight is blocked; no work was applied"
        if current.works != original.works:
            return "Watchlist or Catalog changed after preview; create a new site preview"
        return None

    @staticmethod
    def _first_blocked_work(preview: ScopeSiteSyncPreview) -> str | None:
        return next((item.work_key for item in preview.works if not item.ready), None)

    @staticmethod
    def _remaining_keys(
        original: ScopeSiteSyncPreview,
        current: ScopeSiteSyncPreview,
        applied: list[str],
        observed_keys: tuple[str, ...] = (),
        *,
        attempted_failure_key: str | None = None,
    ) -> tuple[str, ...]:
        applied_set = set(applied)
        if attempted_failure_key is not None:
            applied_set.add(attempted_failure_key)
        return tuple(
            sorted(
                (set(original.work_keys) | set(current.work_keys) | set(observed_keys))
                - applied_set
            )
        )

    @staticmethod
    def _failure(
        preview: ScopeSiteSyncPreview,
        *,
        error: str,
        failed_work_key: str | None = None,
        not_applied_work_keys: tuple[str, ...] = (),
        failure_stage: str | None = None,
        requested_preview: ScopeSiteSyncPreview | None = None,
        selection_changed: bool = False,
        applied_work_keys: list[str] | tuple[str, ...] = (),
    ) -> ScopeSiteSyncApplyResult:
        requested = requested_preview or preview
        return ScopeSiteSyncApplyResult(
            site=requested.site,
            selection_fingerprint=requested.selection_fingerprint,
            selected_work_keys=requested.work_keys,
            applied_work_keys=tuple(applied_work_keys),
            not_applied_work_keys=not_applied_work_keys,
            failed_work_key=failed_work_key,
            failure_stage=failure_stage,
            selection_changed=selection_changed,
            complete=False,
            error=error,
            preview=preview,
        )

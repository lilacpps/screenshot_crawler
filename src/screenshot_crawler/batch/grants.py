"""Work-level grant reporting without changing execution or output metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from screenshot_crawler.batch.metrics import BatchMetricsWriter
from screenshot_crawler.batch.models import BatchCandidate, BatchPlanningError
from screenshot_crawler.catalog import CatalogService
from screenshot_crawler.watchlist.service import WatchlistService


def group_grant_candidates(candidates: list[BatchCandidate]) -> list[list[BatchCandidate]]:
    """Keep planned work order and give the live resolver one work at a time."""

    groups: dict[int, list[BatchCandidate]] = {}
    for candidate in candidates:
        if candidate.work_id is None:
            raise BatchPlanningError("Deferred grant-only candidates require a work_id")
        groups.setdefault(candidate.work_id, []).append(candidate)
    return list(groups.values())


@dataclass
class _WorkGrant:
    work_id: int
    resource: str
    label: str
    candidate: BatchCandidate
    status: str = "未実行"
    reason: str = "not_started"
    resource_consumed: bool | None = None
    selected: bool = False

    def line(self) -> str:
        order = f"  {self.candidate.metadata.get('order', '-')}" if self.selected else ""
        return (
            f"  {self.status}  {self.label}{order} "
            f"resource={self.resource} reason={self.reason}"
        )


class GrantOnlyReport:
    """Report deferred grants in normal Batch and explicit grant-only runs."""

    def __init__(
        self, catalog: CatalogService, watchlist: Path, metrics: BatchMetricsWriter,
        *, heading: str = "Grant-only results:",
    ) -> None:
        self.catalog = catalog
        self.metrics = metrics
        self.heading = heading
        self.targets = {target.key: target for target in WatchlistService(watchlist).list_targets()}
        self.rows: dict[tuple[int, str], _WorkGrant] = {}
        self._finalized = False

    def prepare(self, candidates: list[BatchCandidate], resource: str) -> None:
        for group in group_grant_candidates(candidates):
            candidate = group[0]
            assert candidate.work_id is not None
            key = (candidate.work_id, resource)
            if key in self.rows:
                continue
            work = self.catalog.get_work(candidate.work_id)
            labels: list[str] = []
            for item in group:
                source = self.catalog.get_source(item.source_id)
                target = self.targets.get(source.discovery_key)
                if (
                    target is not None
                    and target.site == item.site
                    and target.work_key == work.work_key
                    and target.label not in labels
                ):
                    labels.append(target.label)
            label = " / ".join(labels) if labels else f"{work.title} [Catalog名]"
            self.rows[key] = _WorkGrant(candidate.work_id, resource, label, candidate)

    def record(
        self,
        candidate: BatchCandidate,
        *,
        status: str,
        reason: str,
        resource_consumed: bool | None = None,
        selected: bool = True,
    ) -> None:
        row = self.rows[(candidate.work_id, candidate.quota_resource)]
        row.candidate = candidate
        row.status = status
        row.reason = reason
        row.resource_consumed = resource_consumed
        row.selected = selected
        print(row.line(), flush=True)
        self._write(row)

    def failure(
        self, candidate: BatchCandidate, error: BaseException, *, selected: bool = True
    ) -> None:
        row = self.rows[(candidate.work_id, candidate.quota_resource)]
        consumed = (
            getattr(error, "resource_consumed", None) is True or row.resource_consumed is True
        )
        root = error.__cause__ if error.__cause__ is not None else error
        reason = (
            getattr(getattr(error, "access_stop", None), "reason", None)
            or getattr(root, "reason", None)
            or type(root).__name__
        )
        self.record(
            candidate,
            status="OK" if consumed is True else "NG",
            reason=(
                f"チケット使用確認済み／後処理失敗: {reason}"
                if consumed is True
                else f"消費未確認: {reason}"
            ),
            resource_consumed=True if consumed is True else None,
            selected=selected,
        )

    def has_result(self, candidate: BatchCandidate) -> bool:
        return self.rows[(candidate.work_id, candidate.quota_resource)].status != "未実行"

    def finish(self, *, reason: str) -> None:
        if self._finalized:
            return
        self._finalized = True
        print(self.heading, flush=True)
        for row in self.rows.values():
            if row.status == "未実行":
                row.reason = reason
                self._write(row)
            print(row.line(), flush=True)

    def _write(self, row: _WorkGrant) -> None:
        self.metrics.record_grant_result(
            work_id=row.work_id,
            label=row.label,
            resource=row.resource,
            source_id=row.candidate.source_id if row.selected else None,
            status=row.status,
            reason=row.reason,
            resource_consumed=row.resource_consumed,
        )

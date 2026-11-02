"""One-Work immutable patches; child editors cannot replace another Work."""

from dataclasses import dataclass

from screenshot_crawler.discovery.listing import ListingPreview
from screenshot_crawler.management.catalog_reader import catalog_snapshot_identity
from screenshot_crawler.registration.draft import PREVIEW_SITES, BatchRegistrationDraft
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.work_edit import (
    WorkDraft,
    WorkEditPreview,
    validate_work_snapshot,
)


@dataclass(frozen=True)
class DetailRequest:
    group_id: str
    version: int
    revision: str
    catalog_identity: str
    members: tuple[WatchlistTarget, ...]


@dataclass(frozen=True)
class WorkDetailProof:
    request: DetailRequest
    members: tuple[WatchlistTarget, ...]
    listings: tuple[ListingPreview, ...]
    configured_keys: frozenset[str]
    summary: str


def member_patch(base, work_key: str, members) -> tuple[WatchlistTarget, ...]:
    """Only replace members of this Work; preserve every unrelated target."""
    proposed = {target.key: target for target in members}
    if len(proposed) != len(members) or any(target.work_key != work_key for target in members):
        raise ValueError("Work patchが別作品/重複keyを含みます")
    if any((target.work_key != work_key and target.key in proposed)
           or (target.work_key == work_key and target.key not in proposed) for target in base):
        raise ValueError("既存keyの削除/別Workの変更はできません")
    result = tuple(proposed.pop(target.key, target) for target in base)
    return result + tuple(proposed.values())


def detail_draft(batch: BatchRegistrationDraft, group_id: str) -> tuple[DetailRequest, WorkDraft]:
    group = batch.works[group_id]
    state = batch.readiness(group_id)
    if state.status not in ("ready", "needs_scope"):
        raise ValueError(" / ".join(state.reasons))
    rows = batch.members(group_id)
    if any(not row.confirmed or row.resolution.status == "blocked" for row in rows):
        raise ValueError("先にURL・作品名・所属・IDを明示確認してください")
    members = batch.targets_for(group_id)
    unsupported = {target.site for target in members} - PREVIEW_SITES
    if unsupported:
        raise ValueError("完全一覧preview未対応: " + ", ".join(sorted(unsupported)))
    if batch.catalog_snapshot is None:
        raise ValueError("Catalogの基準snapshotがありません")
    request = DetailRequest(group_id, group.version, batch.revision,
        catalog_snapshot_identity(batch.catalog_snapshot), members)
    existing_keys = {target.key for target in batch.base}
    draft = WorkDraft(batch.base, group.work_key)
    for target in members:
        if target.key not in existing_keys:
            draft.add(target)
    if group.detail is not None:
        proof = group.detail
        draft.targets = member_patch(batch.base, group.work_key, proof.members)
        draft.listings = {listing.target_key: listing for listing in proof.listings}
        draft.configured_keys = set(proof.configured_keys)
    return request, draft


def accept_detail(batch: BatchRegistrationDraft, request: DetailRequest, result: WorkEditPreview,
                  configured_keys) -> WorkDetailProof:
    group = batch.works.get(request.group_id)
    if (group is None or group.version != request.version or batch.revision != request.revision
            or batch.targets_for(group.id) != request.members):
        raise ValueError("このWorkの下書き版が変わりました。再編集してください")
    if (result.work_key != group.work_key or result.revision != request.revision
            or result.catalog_identity != request.catalog_identity):
        raise ValueError("詳細設定の基準Watchlist/Catalogが一致しません")
    members = tuple(target for target in result.targets if target.work_key == group.work_key)
    expected = {target.key: target for target in request.members}
    if {target.key for target in members} != set(expected) or len(members) != len(expected):
        raise ValueError("詳細設定が別Work/別keyを含んでいます")
    for target in members:
        old = expected[target.key]
        if (target.work_key, target.site, target.url, target.label, target.enabled) != (
                old.work_key, old.site, old.url, old.label, old.enabled):
            raise ValueError("詳細設定で安定identity/基本設定は変更できません")
    if set(configured_keys) != set(expected):
        raise ValueError("全keyの範囲・担当の明示確認が必要です")
    proof = WorkDetailProof(request, members, tuple(result.listings), frozenset(configured_keys), result.summary)
    validate_detail(batch, proof, batch.catalog_snapshot)
    group.detail = proof
    batch.generation += 1
    return proof


def validate_detail(batch: BatchRegistrationDraft, proof: WorkDetailProof, data, *, targets=None):
    request = proof.request
    group = batch.works.get(request.group_id)
    if (group is None or group.version != request.version or batch.revision != request.revision
            or batch.targets_for(group.id) != request.members
            or catalog_snapshot_identity(data) != request.catalog_identity):
        raise ValueError("詳細設定の版/Watchlist/Catalogが古いため再編集してください")
    draft = WorkDraft(targets if targets is not None else member_patch(batch.base, group.work_key, proof.members),
        group.work_key)
    if draft.members != proof.members:
        raise ValueError("詳細設定と保存対象のWorkが一致しません")
    draft.listings = {listing.target_key: listing for listing in proof.listings}
    if (len(proof.listings) != len(draft.members)
            or proof.configured_keys != {target.key for target in draft.members}):
        raise ValueError("全keyの完全一覧/確認証拠が必要です")
    return validate_work_snapshot(draft, data, batch.revision)

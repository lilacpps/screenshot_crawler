"""Selected-Work preview and one atomic Watchlist save. No Catalog mutation."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from screenshot_crawler.catalog.job_lock import CatalogJobLock
from screenshot_crawler.management.catalog_reader import (
    CatalogInventoryReader,
    catalog_snapshot_identity,
)
from screenshot_crawler.registration.detail import member_patch, validate_detail
from screenshot_crawler.registration.draft import BatchRegistrationDraft
from screenshot_crawler.watchlist.models import WatchlistTarget
from screenshot_crawler.watchlist.service import WatchlistService
from screenshot_crawler.watchlist.work_edit import full_changed_keys, selected_rows


def draft_identity(batch: BatchRegistrationDraft) -> str:
    payload = (batch.base, batch.revision, tuple(batch.candidates.values()), tuple(batch.works.values()))
    def encode(value):
        if isinstance(value, (set, frozenset)):
            return sorted(value)
        if hasattr(value, "__dataclass_fields__"):
            return asdict(value)
        return str(value)
    return hashlib.sha256(json.dumps(payload, default=encode, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class RegistrationPreview:
    targets: tuple[WatchlistTarget, ...]
    revision: str
    catalog_identity: str
    draft_identity: str
    selected_groups: tuple[str, ...]
    changed_keys: frozenset[str]
    summary: str


@dataclass(frozen=True)
class RegistrationSaveResult:
    targets: tuple[WatchlistTarget, ...]
    revision: str | None
    selected_groups: tuple[str, ...]
    changed_keys: frozenset[str]
    verified: bool
    message: str


class RegistrationService:
    def __init__(self, watchlist_path, catalog_path):
        self.watchlist = WatchlistService(watchlist_path)
        self.catalog = Path(catalog_path)

    def preview(self, batch: BatchRegistrationDraft, *, data=None) -> RegistrationPreview:
        base, revision = self.watchlist.read_snapshot()
        if (base, revision) != (batch.base, batch.revision):
            raise ValueError("Watchlistが変更されました。下書きを保持したまま保存を停止します")
        data = data if data is not None else CatalogInventoryReader().read(self.catalog)
        selected = tuple(group.id for group in batch.works.values() if group.selected)
        if not selected:
            raise ValueError("登録対象のWorkを選択してください")
        targets = base
        summary = ["選択したWorkを一度にWatchlistへ保存します。まだ保存していません。"]
        selected_sources, selected_urls = {}, {}
        for group_id in selected:
            group = batch.works[group_id]
            state = batch.readiness(group_id)
            if state.status != "ready":
                raise ValueError(f"{group.work_key or group_id}: {state.status}: " + " / ".join(state.reasons))
            if not group.existing and group.work_key in {work.work_key for work in data.works}:
                raise ValueError("Catalogに既存work_keyがあります。既存Work所属を明示選択してください")
            errors = batch.ownership_blockers(group_id, data)
            if errors:
                raise ValueError(" / ".join(errors))
            for row in batch.members(group_id):
                fresh = batch.resolver.resolve(row.resolution.input_url)
                if (fresh.status == "blocked" or fresh.site != row.resolution.site
                        or fresh.discovery_url != row.resolution.discovery_url
                        or fresh.site_work_identity != row.resolution.site_work_identity):
                    raise ValueError("安全な正規URLの証拠が一致しません。再解析してください")
            members = group.detail.members if group.detail is not None else batch.targets_for(group_id)
            targets = member_patch(targets, group.work_key, members)
            summary.append(f"\nWork: {group.work_key} ({'既存Workへ追加' if group.existing else '新規'})")
            for target in members:
                old = next((row for row in base if row.key == target.key), None)
                if old and (old.work_key, old.site, old.url, old.label, old.enabled) != (
                        target.work_key, target.site, target.url, target.label, target.enabled):
                    raise ValueError("既存keyのidentity/基本設定は変更できません")
                action = "追加" if old is None else "更新" if old != target else "変更なし"
                summary.append(f"  {action}: {target.label} / {target.site} / {target.key}")
            for row in batch.members(group_id):
                summary.append(f"  入力: {row.resolution.input_url}\n    → {row.resolution.discovery_url}\n"
                    f"    identity={row.resolution.identity_status}; title={row.resolution.title_status}; 人の確認済み")
            if group.detail is None:
                summary.append("  Catalog影響: UNKNOWN（完全一覧未取得）。新規単一key・scopeなし。所有確認は既知URL/identityのみ。")
                for target in members:
                    self._claim(selected_urls, (target.site, target.url), group_id)
            else:
                checked = validate_detail(batch, group.detail, data)
                summary.append(checked.summary)
                listings = {listing.target_key: listing for listing in group.detail.listings}
                for target in members:
                    for row in selected_rows(target, listings[target.key]):
                        self._claim(selected_sources, (target.site, row.external_id), group_id)
                        resolution = batch.resolver.resolve(row.url)
                        url = resolution.discovery_url if resolution.status != "blocked" else row.url
                        self._claim(selected_urls, (target.site, url), group_id)
        preview = self.watchlist.preview_edit(targets, expected_revision=revision)
        if not preview.ready:
            raise ValueError(" / ".join(preview.blockers))
        # Validate every proof against the final composed proposal too.
        for group_id in selected:
            proof = batch.works[group_id].detail
            if proof is not None:
                validate_detail(batch, proof, data, targets=targets)
        changed = full_changed_keys(base, targets)
        summary.append("\n保存後にFull Discoveryを確認します: " + ", ".join(sorted(changed)))
        summary.append("Fullは独立ジョブです。No/取消は保存のみ・Catalog未同期。失敗しても設定は保存済みです。"
            "\nScope sync・既存ZIPのaudit/renumber・Batchは必要に応じて別途明示実行してください。ここでは起動しません。")
        return RegistrationPreview(targets, revision, catalog_snapshot_identity(data), draft_identity(batch),
            selected, changed, self._yaml_changes(base, targets) + "\n\n" + "\n".join(summary))

    def _yaml_changes(self, base, targets):
        previous = {target.key: target for target in base}
        added = tuple(target for target in targets if target.key not in previous)
        updated = tuple(target for target in targets if target.key in previous and target != previous[target.key])
        sections = [(f"watchlist.yaml への変更: 追加 {len(added)}件 / 更新 {len(updated)}件 / "
                     f"既存のまま {len(base) - len(updated)}件"),
                    ("追加・更新する項目をYAMLで表示します（targetsの抜粋）。まだ保存していません。\n"
                     "既存コメント・空白・変更しない項目は表示を省略し、保存時は従来どおり保持します。")]
        for title, rows in (("追加する項目", added),
                            ("既存項目の変更前", tuple(previous[target.key] for target in updated)),
                            ("既存項目の変更後", updated)):
            sections.append(f"\n【{title}】\n" + (self.watchlist.format_targets_yaml(rows) if rows else "（なし）\n"))
        return "\n".join(sections)

    @staticmethod
    def _claim(owners, identity, group_id):
        if identity in owners and owners[identity] != group_id:
            raise ValueError("選択した異なるWork間で同一サイトSourceが重複しています")
        owners[identity] = group_id

    def save(self, batch: BatchRegistrationDraft, preview: RegistrationPreview) -> RegistrationSaveResult:
        if draft_identity(batch) != preview.draft_identity:
            raise ValueError("プレビュー後に下書き/選択が変わりました")
        with CatalogJobLock(self.catalog):
            # No browser/network or Catalog write occurs inside either lock.
            fresh = self.preview(batch, data=CatalogInventoryReader().read(self.catalog))
            if fresh != preview:
                raise ValueError("Catalog/下書き/一覧証拠が変更されました。再プレビューしてください")
            saved = self.watchlist.apply_edit(preview.targets, expected_revision=preview.revision)
            try:
                actual, revision = self.watchlist.read_snapshot()
                if actual != saved:
                    raise ValueError("保存直後に別のWatchlist変更を検出しました")
            except Exception as exc:  # noqa: BLE001 - atomic commit already succeeded
                return RegistrationSaveResult(saved, None, preview.selected_groups, preview.changed_keys, False,
                    f"Watchlist保存済み・読戻し確認不能: {exc}。自動再保存/Fullは行いません。")
            return RegistrationSaveResult(saved, revision, preview.selected_groups, preview.changed_keys, True,
                "Watchlist保存済み。Catalogは未同期です。Full Discoveryは別途確認します。")


def retain_unsaved(batch: BatchRegistrationDraft, result: RegistrationSaveResult) -> None:
    """Rebase only after verified commit; keep every unselected candidate edit."""
    if not result.verified or result.revision is None:
        raise ValueError("保存確認不能の状態では下書きを自動更新できません")
    batch.candidates = {key: row for key, row in batch.candidates.items()
                        if row.group_id not in result.selected_groups}
    batch.works = {key: group for key, group in batch.works.items() if key not in result.selected_groups}
    batch.base, batch.revision = result.targets, result.revision
    for group in batch.works.values():
        group.detail = None
        group.version += 1
    batch.generation += 1

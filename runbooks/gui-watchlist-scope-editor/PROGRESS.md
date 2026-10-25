# GUI Watchlist Scope Editor — Progress

> **2026-10-25: PLANNED / DOCUMENTATION ONLY. 実装未着手。**
>
> Main runbook: [README.md](README.md)

## Phase gates

| Stage | Status | Evidence / next action |
|---|---|---|
| 00 現行契約監査 | PLANNED | 現行main/作業枝、Adapter・Discovery・scope-sync・GUI・コメント付きYAML更新契約を検証 |
| 01 Watchlistモデル/編集API | PLANNED | 除外ID、fingerprint、lossless YAML/CAS、Unit |
| 02 Read-only listing | PLANNED | Magapoke完全一覧、Catalog非書込、synthetic integration |
| 03 Scope selection/Sync | PLANNED | 飛び飛び選択、proof、Batch/Grant-only遮断、renumber影響 |
| 04 GUI統合/E2E | PLANNED | 別管理画面、編集・プレビュー・段階適用、Windows/Qt検証 |

## Admitted risks / explicit decisions

- 現行`ScopeReconciler.preview`は永続化されたWatchlist/Full証拠を確認するもので、仮設定の事前プレビューとは同一APIではない。pure planning/helper抽出が必要。
- 現行通常FullはCatalogを書き込む。previewに流用せずread-only listing capabilityが必要。
- `excluded_external_ids` が現行schemaに存在しないため、YAML/Adapter/Core/証拠mask/正式同期の全経路を更新する。
- 同site他keyのSource ownershipを変えない。除外済の未登録話は作成必須とせず、既存除外話の履歴を保持。
- 空選択は初期版で適用不可。除外のみ・飛び飛び選択はサポート。
- `archive_order`変更時の自動renameは禁止。保存とFullとscope-syncとrenumberは別操作。
- 既存GUI Live Monitor workstreamと同一ファイルの変更競合を調整。
- 2026-10-25のドキュメント作成では実サイト接続、Catalog/Watchlist/ZIP書込、production実装、テスト実行は行っていない。

## Implementation record template

- Baseline HEAD/branch:
- Writer/reviewer:
- Files + notes updated:
- Contract changes / migration:
- Targeted tests + results:
- Affected tests + results:
- Integration/GUI/Windows + results:
- Live verification or explicit not-run reason:
- Full suite/ruff + results or not-run reason:
- Blockers / next gate:

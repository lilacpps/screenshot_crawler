# Work deletion — Progress

> **PLANNED / NOT IMPLEMENTED — 2026-11-14**
>
> [Runbook](README.md)。このファイルはCodex実装の各Stage完了時に更新する。進捗やテストの成功を推測で記載しない。

| Stage | Status | Evidence / 次のゲート |
|---|---|---|
| 00 現行契約監査 | NOT STARTED | DB FK / Catalog・Watchlist所有/Job・ファイル所有境界、rollback/forwardのfailure matrix |
| 01 Read-onlyプレビュー | NOT STARTED | no-write、Work全依存、危険path/alias、stale tokenのtargeted tests |
| 02 退避・削除 | NOT STARTED | isolated fixture成功/通常例外、transaction/FK、原子的YAML更新（非公開） |
| 03 強制中断復旧 | NOT STARTED | restart/fault-injection、未完了gate、roll-forward/rollback |
| 04 CLI / GUI / E2E | NOT STARTED | 明示確認、Windows GUI、削除→同key登録→Full→Batch、docs/note同期 |

## Stage記録テンプレート

- 基準HEAD / branch / 未commit差分:
- 変更ファイル（コード・テスト・文書）:
- 開始証拠と設計判断:
- Targeted / affected / integration / full / ruff の実行コマンドと実測結果:
- Skipped / 未実行カテゴリと理由:
- 故意の中断・回復試験の結果:
- 独立ReviewerのBLOCKING / non-blocking所見と再レビュー:
- 未解決事項・次Stageへの条件:

## 初期メモ

- 実装・試験・本番データ削除は一切行っていない。
- 既存アーカイブ機能は表示だけの変更。新しい完全削除は別機能。
- Catalog v7、SQLite online backup、Watchlist lossless patch、GUI context menu、job lockを再利用する方針。

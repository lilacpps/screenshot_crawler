# Stage 00 — 現行契約・安全境界の監査

**状態:** PLANNED / NOT STARTED。前提: [親Runbook](../README.md)。このStageはread-only、production改変なし。

## 開始時に確認する証拠

- HEAD、作業branch、未commit変更。AGENTS.mdと上位docs、note/00_core.md、Catalog v7スキーマ・migration、Watchlist構造パッチ、managementジョブ管理。
- 主要コード: catalog/{schema,service,backup,job_lock}.py、watchlist/service.py、gui/{main_window,work_archive}.py、management/{jobs,job_controller}.py、batch/archive_guard.py、core/packaging.py、maintenance/archive_renumber.py。
- 対象実体: works、items、sources、source_targets、crawl_runs、artifacts（ZIP以外も）、quota_resource_states、acquisition_scope_sync、discovery_inventory_evidence/positions。管理DBのjobテーブルとジョブ開始時のlock取得箇所。
- 実出力の所有: Artifact locator、ZIPとstatus JSONのpath関係、複数履歴Artifact、失敗run/raw、外部library-dir、同名作品、alias/symlink/hardlink。
- GUIとCLIの実行・起動契約: GUI内job pending / running / orphaned、別processのCatalog lock、Watchlist CAS、状態再読込とstale preview。

## 目的と作業

1. DBテーブルごとの正確な外部キー方向、子→親DELETE順、必要なWork-ownership queryを監査し、`PRAGMA foreign_key_check`を保証する単一transaction境界を決める。Schema v7互換・schema変更不要を検証。
2. `WatchlistService`の `_write` / `_patch_existing_yaml` / `set_work_archived` を追い、全key削除と `archived_work_keys` の同時原子更新に必要な**最小API**を定義。コメント、空targets、未知root key、CRLFを維持。構文上安全にpatch不能なら拒否。
3. 任意のWorkが Catalog-only / Watchlist-only / 両方あり / どちらにもなし の場合の扱いを確定。Work所属が曖昧なSource、複数Workの同一パス参照、歴史的Artifact、非ZIP、missing、status不一致を一覧化する。
4. Job管理の実際のnonterminal statusとpathを確認し、**queued/running/終了未確認**があるときのblockingと、CLIからのrace防止条件を記録。GUI内の状態チェックだけでは不十分。
5. 退避先同一volumeの判定、path traversal/reparse point/hardlink、Windows rename衝突とcase-insensitive path扱いを検証する。
6. 「DB commit後はroll forward、以前はrollback」の状態遷移をfailure matrixに落とす。録画ではなく人工SQLite/ZIP fixtureとfault injectionを使用。
7. runbookとコードに矛盾があれば、勝手に削除機能を実装しない。上位仕様に必要な最小追記・未決問題を [PROGRESS.md](../PROGRESS.md) に記録する。

## 必要なfixture / baseline

- 対象Work: 2サイト/複数key・completed/pending/failed・historical ZIP・quota・scope evidence・archived work設定。
- 非対象Work: 同じタイトル、別work_key、同じgenre/title directoryの別ZIP。
- 管理境界: target-only、Catalog-only、Watchlist-only、外部artifact/欠損/重複/別Work alias。
- Baseline targeted test: tests/unit/test_catalog.py、test_catalog_backup.py、test_watchlist.py、test_archive_renumber.py、test_archive_guard_identity.py、test_management_jobs.py。実際の変更/影響でテスト選択を調整。

## Exit / 独立レビュー

- [ ] IDとFK依存関係の削除順・全Artifact query契約が明文化されている。
- [ ] 正規化済み所有ファイルと未管理/孤立ファイルの判定を説明できる。
- [ ] in-flight job、Watchlist/Catalog lock順、plan revision再検証、復旧gateを確定。
- [ ] rollback / roll-forward のcommit境界と全失敗点の期待状態を確認。
- [ ] 同じwork_key再登録を妨げる可能性のある残存ファイルの検出方針を確定。
- [ ] 実測baseline・レビュー結果・Stage01への前提をPROGRESSへ記録。BLOCKING 0。

**禁止:** 実作品を使ったDelete試行、production codeの削除関数追加、live site操作。

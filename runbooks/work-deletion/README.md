# Work単位の完全削除（退避付き）Runbook

> **PLANNED / NOT IMPLEMENTED — 2026-11-14**
>
> 対象: lilacpps/screenshot_crawler の Catalog v7、Watchlist、ZIP/status、Windows GUI、CLI。
> 目的は既存の作品を完全に登録し直せるようにすること。実際の作品・実データの削除はこのRunbookの作成では行わない。
> 各Stageの実装状況とレビューは [PROGRESS.md](PROGRESS.md) を更新する。計画を実装済みと記載しない。

## 0. Authority / 実装ルール

- 上位authority: AGENTS.md → docs/SPEC.md → docs/ARCHITECTURE.md → docs/DISCOVERY_AND_BATCH.md → docs/DECISIONS.md → docs/TEST_STRATEGY.md → docs/CODEX_IMPLEMENTATION_GUIDE.md → コード・テスト。
- 運用参照: docs/GUI_README.md、docs/BOOK_NAMING_RULES.md、note/00_core.md、runbooks/gui-watchlist-scope-editor/README.md、runbooks/work-key-archive-order/README.md。
- Runbookは作業契約。採用された仕様変更は関連する docs/ と note/00_core.md に**同じ実装変更で**同期する。既存のsite adapter、capture、quota/accessの意味は変更しない。
- feature branch / 単一production writer / 独立reviewer。未commitのユーザー変更を保持し、他の作業ブランチと混ぜない。段階ごとにtargeted testsと独立レビューを行い、BLOCKINGを解消して次へ進む。
- 実サイト・ユーザー本番Catalog・実ZIPは試験に使わず、完全隔離された一時ファイルと人工ZIPで検証する。

## 1. 目的・受け入れ条件

**要求:** 明示したひとつの `work_key` に属する登録を、複数site/keyにまたがって完全削除する。対応するZIPおよびstatus JSONは削除せず保全領域に退避する。削除完了後、同一`work_key`で新規登録→Full Discovery→Batch取得を、新規作品として実行できる。

**成功条件（すべて必須）:**
1. 対象Workの全Watchlist targetと `archived_work_keys` エントリが消える。
2. Catalog内の対象Work、およびそのItem/Source/SourceTarget/CrawlRun/Artifact、quota、scope同期、Discovery証拠が消える。`PRAGMA foreign_key_check` が成功。
3. 退避対象の既存ZIPと対応status JSONは、内容を保持して一意の退避ディレクトリへ移動済み。管理対象ライブラリの同名ZIPとの衝突が残らない。
4. 他WorkのDB行、Watchlistエントリ、ファイル内容・パスが変わらない。同一タイトルの別Workも影響を受けない。
5. 中断・失敗は「未変更」「復旧待ち」「削除完了」を明確に区別し、復旧待ちに取得/新規削除/同名登録を許さない。静かな部分成功は不可。
6. 復旧完了後、同じ`work_key`を再利用しても旧Itemのcompleted、quota、採番、Artifact参照を継承しない。

**対象外:** サイト間の話数対応、部分/1話削除、サイト別削除、ZIPの自動比較・改名、既存ZIPの永久削除、退避データのGUI上からのワンクリック復元、自動期限切れGC、既存の管理ジョブ履歴削除、Catalogスキーマ移行。対象Workに属さない古い手動crawl出力等は勝手に消さない。

## 2. 現行コードで確認できる前提（2026-11-14 / main）

- `catalog/schema.py`: Catalog v7。`works→items→sources→source_targets`、`crawl_runs`、`artifacts`、quota、scope同期、Discovery evidence/positions。外部キーが多く、Workを単純DELETEしても完結しない。Discovery positions→evidenceのみON DELETE CASCADE。
- `catalog/service.py`: `CatalogService`、`job_lock()`、read-only接続/atomic connection、`read_work_archive_references()` と `read_all_archive_references()`。後者はZIP参照に限定されるため、削除前の**全種類のArtifact**を調べる追加queryが必要。
- `catalog/backup.py`: `backup_catalog()` はSQLite Online Backup・quick_check検証済みのバックアップを作る。WALファイルの単純コピーは禁止。
- `watchlist/service.py`: `apply_edit()` / `remove()` / `set_work_archived()` と改行・コメントを極力維持する構造パッチ/CASがある。しかし「全key削除とarchived_work_keys削除を同じ原子的書込みで完了する」専用APIはない。
- `gui/main_window.py`: Work行の右クリックは現状「アーカイブ/通常に戻す」。`_discovery_block_reason()`、busy state、ジョブ管理を利用可能。
- `management/jobs.py`: management DBはCatalogと別。ジョブ履歴は変更しないが、実行/待機/終了未確認のジョブが削除と衝突し得る。GUI内だけのチェックではCLIや別プロセスを防ぎ切れない。
- `batch/archive_guard.py`、`core/packaging.py`: ZIPへの上書きは禁止。単にWatchlistを削除するだけ、またはZIPだけ手動移動するだけでは新規登録時の衝突・参照不整合が残る。
- `maintenance/archive_renumber.py`: ZIP/status/Artifact locatorの整合性検証は参考にできるが、担当外ZIPを残すことが前提のため、削除サービスとして流用はしない。

## 3. 操作・対象データ契約

| 対象 | 動作 |
|---|---|
| Watchlist `targets` | 対象`work_key`の全keyを除去。siteやenabledに依存しない |
| Watchlist `archived_work_keys` | 対象keyを除去。未登録ならそのまま |
| Catalog `works` | 正確なwork_idを1件削除 |
| `items` / `sources` / `source_targets` | work_idを辿った関連IDだけ削除 |
| `crawl_runs` / `artifacts` | 失敗・成功・過去run、全Artifactを含む関連履歴を削除 |
| `quota_resource_states` / `acquisition_scope_sync` | 対象work_idに紐付く行を削除 |
| `discovery_inventory_evidence` / `discovery_inventory_positions` | 対象work_idに紐付く証拠/子行を削除 |
| Catalog以外のmanagement DB | 操作履歴を保持。実行可能なqueued/running jobは削除前にブロック |
| ZIP・対応status JSON | Catalogで所有が証明できたものだけ保全領域へ移動。削除しない |
| その他のファイル | 自動変更しない。不明な関連出力・所有衝突はプレビューに表示し、危険ならブロック |

「対象作品」は作品名・ZIP名・URLではなく正確な `work_key → work_id → 関連ID` で決定する。Catalogが未作成でWatchlistのみ登録済みの場合は**Watchlist-only**の削除ケースとして明示的に対応する（ZIP等の孤立ファイルについての自動所有推定は禁止）。WatchlistにはなくCatalogだけにあるWorkは**Catalog-only**として明示表示し、同じ安全検査を満たす場合のみ削除可。どちらにもない場合はNot Foundで終了。

## 4. 保全領域とファイル所有

例（実パスは設定値から解決）:

~~~text
output/trash/work-deletion/<unique-id>/
  manifest.json
  catalog-before.sqlite          # Catalogが存在するとき
  watchlist-before.yaml          # 原本のバイト列
  files/
    Books/<genre>/<title>/<archive>.zip
    crawl-status/<genre>/<title>/<archive>.json
~~~

- この例は相対的な概念図。`trash` はLibraryやstatus配下に置かず、ユーザー指定の安全な退避ルートへ。ZIP/statusと退避先は同じvolume（rename可能）を初期必須条件とし、cross-volume copy/moveは初期版で拒否。
- pathはCatalogの`filesystem Artifact.locator`と、該当ZIPのstemに対応する**内容照合済みstatus JSON**から確定する。Libraryディレクトリ全体や作品名一致によるglob削除は禁止。historical Artifactも列挙し、重複パスは明示的に検証して一度だけ移動。
- 他WorkのArtifactが同一パスを参照、symlink/reparse point・hardlinkによる曖昧な所有、ルート外/`..`/path traversal、衝突、Zip不在なのにpresent、既存ファイルのchecksum不一致、status JSONの不一致等はfail-closed。対象Artifactの種類/保存先が不明なら推測しない。
- 欠損・既にdeleted/missingと記録済みのArtifactは退避対象にしない。ただし`present`の実ファイル不在を成功扱いしない。status JSONが存在しない場合はZIPに対して許容できるかStage 00で明示し、推測で作成しない。
- 未追跡ファイル、失敗runの一時出力、他rootのファイルは検出可能な範囲で「手動確認対象」として報告。所有が証明できないファイルを勝手に移動しない。新規Batch衝突の恐れがある場合は完了保証に含めずブロックする。
- 退避ファイルは自動削除しない。ユーザーが明示的に別途整理する。初期版ではGUI復元や自動purgeを追加しない。

## 5. 安全な実行と復旧契約

### 5.1 Read-only preview

`WorkDeletionPlan`はWork ID・全依存ID・全退避ファイルのsource/destination・size/hash・Watchlist revision・Catalog snapshot identity・job store identity・blockers/warnings・一意のplan tokenを持つ。previewではCatalog / Watchlist / ZIP / job state / backupを**一切変更しない**。移動・バックアップ用ディレクトリも作らない。

### 5.2 排他・再検証

Apply前に既存のCatalog Job LockとWatchlist edit lockを**常に同じ順序**で取得し、すべての削除・復旧エントリがその順序を守る。GUI worker以外のCLI/workerも対象。関連Catalogの実行中・待機中・orphaned/supervision errorを検査し、安全性を証明できなければ止める（Stage00でmanagement DB位置と判定箇所を確定）。ロック保持中に状態・plan token・パスとhash・Watchlist CASを再検証。プレビュー中にジョブが開始していたらapplyしない。

### 5.3 Durability/commit boundary

推奨順序: **(A)** manifestの予約と永続化 → **(B)** 検証済みCatalog online backup + Watchlist原本保存 → **(C)** 個々のZIP/statusをwrite-ahead journal付きでrenameして検証 → **(D)** 対象Work依存行のCatalog単一transaction DELETE + foreign_key_check → **(E)** Watchlist target/archived entryを同じatomic YAML replaceで除去 → **(F)** 最終照合後にmanifestをDONE。

- **DのDB COMMITをcutoverとする。** それより前の障害は、移動済みファイルを検証して元位置へ戻し「未変更」にする。DB commit済み（またはcommitした可能性がある）場合は、確定状態を観測して**roll forward**でE/Fを完了する。外部変更を失う恐れがある「Catalogバックアップ丸ごと無条件復元」は禁止。
- 各ファイルは移動前に`intent`をfsyncし、移動後にsource/destinationとhashを観測、結果をdurableに記録。停電・killのように記録更新の途中で止まっても両パスの実在とhashで判定。両方に存在/どちらにも存在しない/サイズ不一致は復旧を中止して手動確認へ。
- `manifest.json`は一意の削除ID、対象Work/ID、revision/fingerprint、移動リストとbefore/after hash、phase、失敗理由を持ち、更新はtemp + fsync + atomic replace。既存manifestを上書きしない。削除後も保持。
- 起動/実行前に未完了manifestを検出するgatingを設ける。少なくともそのCatalogに対するDiscovery/Batch/削除/同名再登録をブロックし、専用`recover`でlock取得・再検証して再開。自動で無言の復旧/再試行を行わない。復旧不能なら明確に理由と手動手順を出す。
- 他Workのデータはすべて保存。不明な状態で「成功」を返さない。途中で中断したmanifestの処置を後回しにしたまま、次の削除/取得へ進ませない。
- Stage 02の実装途中では破壊的ApplyをGUI/CLIから有効化しない。Stage 03の中断復旧gate・テストが通ってから公開する。

## 6. GUI / CLIでの操作契約

- GUI: 既存Work行右クリック「作品をアーカイブする」の下に「作品を削除…」を追加。read-only previewでwork_key、サイト/key、Item、Run、ZIP数・容量、退避先、blockersを表示。明示チェック・確認操作なしにapplyしない。実行中は別ジョブ開始や編集を禁止し、結果をDONE / BLOCKED / RECOVERY_REQUIREDとして区別。
- CLI案: `python -m screenshot_crawler.cli work delete --work-key KEY --dry-run --json`、`... --apply`、`... work delete recover --operation-id ID --dry-run/--apply`。命名はStage00で既存CLI parserと競合しないことを確認し、README/GUI_READMEへ確定記載。
- Work削除はネットワークアクセスやCDP起動を必要としない。preview操作で購入・quota消費・viewer操作は起こらない。
- main GUIのアーカイブ挙動・上部UI・ジョブ監視、Watchlist管理、siteごとのFull/Batchは変更しない。

## 7. ステージゲート

| Stage | 内容 | Exit |
|---|---|---|
| [00 現行契約監査](00-contract/README.md) | DB所有・ファイル/ジョブの境界と復旧可否を証明 | unknown/未決事項の解消、fixture設計、review |
| [01 無変更プレビュー](01-preview/README.md) | 正確なWork/DB/ファイル列挙、重複所有・危険パス検知 | no-write、blocker、race検出をテスト |
| [02 退避・DB/YAML削除](02-apply/README.md) | backup/manifest、正確なtransaction削除、atomic YAML更新 | 限定fixtureで成功と通常例外rollback。公開はまだ不可 |
| [03 強制中断復旧](03-recovery/README.md) | journalとroll-back/forward、起動gate、障害注入 | kill/crash境界を通し、公開可とreview |
| [04 GUI・CLI統合](04-gui-cli/README.md) | 右クリック確認と共通サービス、実行系回帰 | Windows/Qt・CLI・削除→再登録E2E、docs/note同期 |

各Stage終了時、担当・変更ファイル・受け入れテストと実測結果・レビュー結果・リスク・次Stage前提を [PROGRESS.md](PROGRESS.md) に記録。部分完了を完了扱いしない。

## 8. 共通禁止事項

- Work名・ZIP stemによる一括rm/rmtree、外部キー無視、SQLite DBの単純ファイルコピー、成功扱いの部分削除。
- 全データを削除する前提で`DROP TABLE`やCatalog migrationを導入すること。
- 既存の全ファイルバックアップを黙って本番へ戻し、削除後に発生した別Workの更新を潰すこと。
- 新規Capture/Discovery/Batchの挙動・site adapter・quota/resolver/AccessGuardへ副作用を入れること。
- 本番データで試験すること。特に実データ削除を自動化テストで実行しないこと。

## 9. 最終ゲート

- 完了報告には、各Stageの差分・動作例・対象外・復旧手順・テスト実績（skips/未実行理由を含む）・独立レビュー結果を明記。
- docs/GUI_README.md、docs/ARCHITECTURE.md、必要なdocs/SPEC.md/DECISIONS.md、note/00_core.mdを実装と一致させる。
- 新しいSite Adapter実装は不要。ユーザーが明示的に選ぶまで、本番作品の削除操作はしない。

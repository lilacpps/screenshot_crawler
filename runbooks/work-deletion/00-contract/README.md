# Stage 00 — 現行契約・安全境界の監査

**状態:** COMPLETE (audit only, independent review approved 2026-11-14)。前提: [親Runbook](../README.md)。このStageはread-onlyで、production code / Catalog / Watchlist / ZIPを変更しない。

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

- [x] IDとFK依存関係の削除順・全Artifact query契約が明文化されている。
- [x] 正規化済み所有ファイルと未管理/孤立ファイルの判定を説明できる。
- [x] in-flight job、Watchlist/Catalog lock順、plan revision再検証、復旧gateを確定。
- [x] rollback / roll-forward のcommit境界と全失敗点の期待状態を確認。
- [x] 同じwork_key再登録を妨げる可能性のある残存ファイルの検出方針を確定。
- [x] 実測baseline・レビュー結果・Stage01への前提をPROGRESSへ記録。独立ReviewerのBLOCKING 0確認待ち。

**禁止:** 実作品を使ったDelete試行、production codeの削除関数追加、live site操作。

## 監査結果（2026-11-14）

### Catalog v7の所有境界と削除順

`works.work_key` の完全一致で1行を解決し、`work_id`から次の閉じた集合を作る。Work名、URL、ZIP stem、表示タイトルは所有判定に使わない。

```text
works(id = W)
  └─ items(work_id = W)
       └─ sources(item_id = I)
            └─ source_targets(source_id = S)
       └─ crawl_runs(item_id = I, source_id = S, target_id = T)
            └─ artifacts(item_id = I, crawl_run_id = R または NULL)
  ├─ quota_resource_states(work_id = W)
  ├─ acquisition_scope_sync(work_id = W)
  └─ discovery_inventory_evidence(work_id = W)
       └─ discovery_inventory_positions(discovery_key = E.discovery_key)
```

Schema v7は`discovery_inventory_positions → discovery_inventory_evidence`だけが`ON DELETE CASCADE`で、その他は`NO ACTION`である。したがってApplyの単一Catalog transactionは、positions（明示削除）、evidence、artifacts、crawl_runs、source_targets、sources、items、quota_resource_states、acquisition_scope_sync、worksの順で子から親へ削除し、最後に`PRAGMA foreign_key_check`を実行する。Artifactは`kind/format/state`を問わず全件を列挙する。`crawl_run_id IS NULL`のmanual Artifactも漏らさない。

Run/ArtifactにはWorkを直接持たない冗長FKがあるため、次を計画時とtransaction直前に検証する。

- 各CrawlRunの`item_id`が対象Item、`source_id`がそのItemのSource、`target_id`がそのSourceのTargetであること。
- 各Artifactの`item_id`が対象Itemであること。`crawl_run_id`がある場合は、そのRunの`item_id`も同じであること。
- 不一致、対象外Workを跨ぐ参照、存在しない親、未知のtable/columnはfail-closedする。

これにより、同じ`work_id`だけを条件にしたDELETEで別Workの履歴を巻き込むことを防ぐ。Catalog schema migrationは不要である。

### WatchlistとWorkの4ケース

- Catalog + Watchlist: 対象`work_key`の全target（site/key/enabledを問わない）と`archived_work_keys`を、同一YAML atomic replaceで除去する。
- Catalog-only: Catalog依存を全削除し、Watchlistに同keyがあれば`archived_work_keys`だけを除去する。
- Watchlist-only: 全targetとarchive entryを除去する。Catalog未作成なのでファイル所有を推測せず、孤立ZIP/statusは移動しない。
- どちらにもない: `Not Found`で終了し、manifest、backup、lock以外の書込みをしない。

Watchlistは既存の`edit_lock()`（CAS/atomic replace）を使い、コメント、CRLF、未知root key、空targetsを保持する。構文上安全にtarget spanを除去できない、重複root/anchor/commentを安全に扱えない、expected revisionが変化した場合は書き込まずblockする。Lock orderは常に`CatalogJobLock → Watchlist edit_lock`とする。

### Artifact / ZIP / status所有

退避対象は、対象Workの全Artifactのうち`storage_backend == filesystem`、`state == present`、`format == zip`、非空locatorを満たし、locatorを正規化して設定済みLibrary root内に収められるものだけである。`missing/deleted`は移動対象外としてmanifestに記録し、`present`なのに実体がない場合は成功扱いにしない。

全Workの全Artifact（ZIP以外を含む）で、正規化後locatorのcase-insensitive aliasを照合する。同一pathを他Workが参照、同一Work内でも所有者が不一致、symlink/reparse point、`st_nlink != 1`のhardlink、root外、`..`、既存destination衝突、size/SHA不一致があればfail-closedする。対象Work内の履歴Artifactが同一pathを参照する場合は1回だけ移動し、全Artifact IDをmanifestに列挙する。

status JSONは全走査せず、`status_root / archive.relative_to(library_root).with_suffix('.json')`の規定位置だけを候補とする（2026-11-15ユーザー指示による変更）。移動するのは候補本文の`archive_path`がCWD基準で正規化したZIP locatorと一致する場合だけ。候補の本文/size/SHA/strong identity不一致、permission/reparse/hardlink/非regular fileはblockする。別配置・別名の過去JSONは探索も移動もせず、全status aliasの検出保証は廃止する。個別候補の欠落は`status_missing` warning付きZIP-only退避を許可し、status root未作成時は従来どおりstatusなし扱い。rootが非directoryまたは読取不能ならblockする。JSONを推測生成しない。missing/deleted Artifactにもこの候補規則とLibrary root境界を適用し、statusだけが残る場合は従来どおり停止する。

退避先はユーザー指定trash root配下の一意 operation directoryだが、未完了gateはCatalog隣接の固定 `.work-deletion/` registry に置く。source/destinationの`st_dev`が異なる場合はcross-volume moveを拒否する。Windowsでは`resolve(strict=True)`、`normcase`、reparse属性、hardlink数を確認し、case-insensitive衝突を同一pathとして扱う。

### Management job境界とrace対策

Management DBはCatalogと別SQLite（GUI既定 `output/management/management.sqlite`、CLI/GUIで明示pathを受ける）であり、操作履歴は削除しない。Delete requestはこのmanagement pathを必須入力としてplan tokenへ含め、未指定時だけ既存GUI既定値を使う。標準pathだけを見てcustom storeを見逃してはならないため、実装時はcanonical Catalog pathのSHA-256を含むCatalog固有namespace（例: `.work-deletion/catalog-<path-hash>/`）へ`management-bindings.json`を置き、Catalogを使うJobStoreのcanonical management pathをadmission lock内でdurable登録する。registryが欠落・壊れている、`sealed`でない、登録pathが読めない、または明示pathがregistryに未登録の場合は`management_store_unbound`でpreview/applyをblockする（未知storeを推測走査しない）。

初回導入や既存custom storeには、専用の明示bootstrap（CLI案: `work delete bind-management --catalog C --management M [--management M2 ...] [--seal] --apply`）を設ける。bindはユーザーが列挙した複数pathだけを対象に、各DBのcanonical path・management schema・queued/planning/running行・worker identity/supervision markerをread-only確認し、Catalog固有admission lock取得後にregistryをCAS再読込してatomic replace（temp + fsync）する。active jobがあってもpath登録はできるが、削除plan/applyはactiveが消えるまでblockする。`--seal`は「この明示リストが運用上の全storeである」というoperator declarationを記録するだけで、未知pathが存在しないことを自動証明するものではない。全既知pathを列挙できない場合、registryをsealedにせず削除を有効化しない。sealed後に新しいJobStore pathが必要になったら、admission lock内でunsealedへ戻して再bindし、再度明示sealする。bind時にregistry CASが変化した、DBが読めない、または列挙path間でCatalog bindingが一致しない場合は書き込まず停止する。

`jobs.state`の`planning`、`running`、起動情報がある`queued`と終了未確認workerを削除前block対象とする。queuedでworker_pid/worker_start_token/started_atの全列が存在し全NULLなら未開始予約として除外する（ageによらず、DB行は保持）。通常terminal（succeeded/partial/failed/cancelled、互換completed/aborted）も除外し、過去summary/log/supervision-error.jsonを読まずfingerprintにも含めない。queuedにworker.identityは不要。`interrupted`はDB tokenとworker.identityのtoken/child・launcher PIDを照合し、OS生存/start identityで終了またはPID再利用を証明できれば除外する。生存・identity欠落・読取不能・終了確認不能の間はblockする。過去supervision marker単独では停止しない。管理DBを推測で全ディレクトリ走査せず、sealed registryと実行設定に束縛されたpathだけを読む。

Catalog lock取得後の再確認だけでは、別プロセスの`JobController.queue()`が管理DBへqueued rowを後付けできるraceが残る。一方、既存worker実行中の後続queue登録は許容されているため、queueへCatalogJobLockを長時間要求して既存挙動を変えてはならない。Stage 02以降ではCatalog隣接の短時間admission lock（既存Catalog job lockとは別ファイル）を使い、次を同じ契約として実装する。

1. Catalog固有namespace（canonical Catalog pathのSHA-256で識別）内の`active.json`をmanifest予約時にfsync + atomic replaceし、Catalog identity、operation id、phase、absolute manifest path、management DB identityを記録する。同じ親に別Catalogがあってもmarkerは衝突しない。trash rootがcustomでも、このmarkerとcatalog pathから未完了状態を発見できる。
2. `JobStore.create_job`（queue）とworkerの実行開始は、このadmission lockを短時間取得してactive markerを検査する。markerが未完了ならenqueue/startを拒否する。通常workerがCatalogJobLockを保持していても、後続queue登録の既存挙動は変えない。
3. Delete Applyはadmission lockを先に取得し、`CatalogJobLock → Watchlist edit_lock`を同じ順序で保持したまま、DB COMMIT、YAML replace、最終照合、manifest DONEまで進める。起動情報のあるqueuedはApply前にblockする。全NULLの未開始予約は残したまま許可し、claim raceはworker冒頭のadmission/start gateとCatalog lock後の再確認で遮断する。
4. markerが残る限りDiscovery/Batch/削除/同名registrationは開始しない。marker消去はDONEまたは明示的に検証済みROLLBACKの後だけ許可する。

### Commit境界とfailure matrix

DB COMMITをcutoverとする。各段階の期待状態は次のとおりである。

| 故障点 | 期待状態 | 復旧方針 |
|---|---|---|
| marker/manifest予約前後、backup前 | Catalog/Watchlist/files unchanged | markerを検査し、未移動なら明示ROLLBACK記録後に終了 |
| backupまたはWatchlist原本保存失敗 | Catalog/Watchlist/files unchanged | backup/manifest一時物を残さず、未完了markerを解除できることを確認 |
| file rename途中（DB COMMIT前） | DB/Watchlist unchanged、移動済み分はwrite-ahead journalに記録 | source/destinationの存在・hashが一意なら元へ戻す。両方/どちらも無い/不一致はRECOVERY_REQUIRED |
| file移動完了後にDB transaction失敗/rollback | DB/Watchlist unchanged、files原位置 | 全fileをhash検証してrollback。失敗時はmarkerを残しRECOVERY_REQUIRED |
| DB COMMIT成功後にYAML replace失敗 | Catalog削除済み、Watchlist旧状態の可能性 | DBをbackup復元せず、lock保持でroll-forwardしてtarget/archive除去。観測不能ならRECOVERY_REQUIRED |
| YAML成功後に最終照合/manifest更新失敗 | Catalog/Watchlist削除済み、files退避済み | 観測結果をmanifestへ追記しDONEへroll-forward。曖昧ならRECOVERY_REQUIRED |
| process kill/停電 | phaseと各path/hashがdurable | 起動gateで全操作を停止し、専用recoverだけがlock・再検証後にrollback/roll-forward |

部分成功を`DONE`として返さない。RECOVERY_REQUIRED中は同じCatalogに対する取得、再登録、別delete、同名Work作成を許可しない。

### Management bootstrapのStage 01/02受け入れテスト

人工management DBをA/B/Cの3隔離pathに作り、Aだけbindした状態、A+Bをbindしてunsealedの状態、A+Bを明示sealした状態を検証する。Aだけでは`management_store_unbound`、unsealedでは同じblock、A+B sealedではA/B双方のqueued/planning/runningと終了未確認workerが検査される。通常終了履歴のsupervision markerだけではblockしない。Cは暗黙走査・暗黙登録されず、operatorがCを列挙しない限り「全storeの不存在」を成功扱いしない。bind中のCAS競合、schema不正、active worker、atomic replace/fsync失敗はregistryを部分更新せず、再bindを要求する。既存custom storeを含む複数pathの明示bootstrapが完了するまで、削除preview/applyは有効化しない。

### Stage 01 fixture契約とbaseline

隔離fixtureは人工SQLite/人工ZIP/人工statusだけを使い、次を含める。

- 対象Work（2 site/key、completed/pending/failed、複数Run、成功/失敗/手動Artifact、quota、scope、evidence/positions、archived work）。
- 非対象Work（同じtitle、別work_key、同genre/title directory、別status/ZIP）。
- Catalog-only、Watchlist-only、両方、Not Found。
- 冗長FK不一致、別Work同一locator、case-only alias、symlink/reparse、hardlink、root外、missing/present不整合、status欠落/不一致。
- queued/planning/running、worker identity不明、supervision errorを持つ隔離management DB。

Stage 01はplan token、Catalog snapshot identity、Watchlist revision、全依存ID、退避source/destination/size/SHA、blocker/warningを返し、previewでCatalog/Watchlist/ZIP/backup/manifest directoryを変更しないことを確認する。既存baselineとして、隔離pytest環境（`--basetemp .tmp/stage00-basetemp`）でCatalog/backup/Watchlist/archive/managementの関連230 testsがPASSした。通常のpytest一時rootは実行環境の権限制約で作成できなかったため使用していない。

## Stage 01への前提

- Work ownership query、冗長FK整合性、削除順、status欠落ポリシー、path alias/hardlink/reparse判定は確定した。
- queued raceはCatalog隣接durable markerとqueue/start側の短時間admission lock内gate検査を必須とする。markerを任意trash配下だけに置く設計は採用しない。
- Stage 01はread-only plannerと人工fixtureを追加する。Stage 02で初めてbackup、journal、退避、Catalog/YAML applyを実装する。

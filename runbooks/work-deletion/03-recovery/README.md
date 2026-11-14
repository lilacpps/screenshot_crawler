# Stage 03 — 強制中断・再開・安全な公開ゲート

**状態:** IMPLEMENTED / INDEPENDENT REVIEW APPROVED (BLOCKING-0, 2026-11-14)。前提: Stage02のApplyとbackup/manifestの状態契約。通常の削除CLI/GUI公開はStage04の独立review完了まで保留。

## 目的

process kill、PC停止、disk errorなど、通常のPython例外処理を通らない失敗後にも、ユーザーの他WorkやZIPを失わず「復旧完了」か「明確な復旧待ち」を判定できるようにする。

## Durable state machine（例）

~~~text
PREPARED
   ↓ verified backups
BACKED_UP
   ↓ per-file INTENT → rename → VERIFIED
FILES_STAGED
   ↓ Catalog commit
DB_COMMITTED
   ↓ Watchlist CAS atomic replace
WATCHLIST_COMMITTED
   ↓ final validation
DONE

DB commit前の失敗 → ROLLING_BACK → ROLLED_BACK
DB commit後の失敗 → RECOVERY_REQUIRED → verified roll-forward → DONE
不明/衝突/改ざん → RECOVERY_REQUIRED（手動対応）
~~~

**重要:** manifestのphase更新とSQLite COMMITは同一transactionでない。`DB_COMMITTED`記録がなくても実際にWorkが消えている可能性がある。復旧判定はmanifestの文字列だけでなく、DB行・全関連ID・source/dest hash・Watchlist revisionの観測で行う。

## 実装契約

1. 各file moveの書込み前intentをdurable記録。sourceのみ / destのみ / 両方 / どちらもなしを区別し、hashと所有を確認。安全に一意の状態へ復帰できない場合は停止して詳細表示。
2. 退避manifestは必ずバックアップ/Work ID/DB fingerprint・Watchlist原本・全move mapと紐づく。再実行時にoperation ID以外からWork名だけで復旧先を推測しない。
3. DBが「before」「対象Work削除済」「その他」のどれかを再検証。Beforeならステージ済ファイルをrollback、対象削除済ならWatchlistをroll-forward。`その他`は復旧待ち。DB backup全体の無条件restore禁止。
4. Watchlistが元revision/削除後想定revisionのどちらかを判断。外部変更が混ざったら自動上書きしない。更新済みなら重複書込せず終了できる（idempotent）。
5. RecoveryはCatalog Job Lock・Watchlist edit lockを取得し、通常の削除と同様のactive/queued job状態確認を行う。初期実装では**明示的なrecover apply**だけが状態変更可能。単に起動しただけで勝手に復旧しない。
6. GUI/CLIの通常ジョブ入口に、同じCatalogに結び付く未完了operationの検査を組み込む。少なくともDiscovery・Batch・新規Work登録・削除をブロックする。対象の管理DBの所在不明・別process状態未確認ならfail-closed。
7. トラッシュ配下の`DONE`データは安全に保管し、自動消去しない。`ROLLING_BACK`などの中断状態を手動でmanifestを書き換えて成功扱いにしない。

## Fault injection / テスト

- [x] ファイル移動前intent直後、rename後状態記録直前、複数ファイル中間、バックアップ完了直後でprocess kill相当を再現（fault matrix）。
- [x] DB commit前/中/直後（manifestは前phase）、Watchlist atomic replace前/直後、DONE記録前にkill相当を再現。hot-journalの実DB中断も隔離fixtureで確認。
- [x] 2回recoverしても追加の削除・上書きが起きず、同一最終結果（idempotency）。
- [x] 同じpathに他WorkのZIPが作られた場合や元/退避両方にファイルがある場合は自動復旧禁止。
- [x] 管理対象ジョブがある/終了未確認、Lock競合、Catalog/Watchlist外部変更があると安全停止。
- [x] Pending operationが残るCatalogで通常Batch/Full/再登録/削除が止まる。復旧後には解除。
- [x] すべて隔離したSQLite・ZIPで実施し、本番実作品には触れない。work-deletion targeted **60 passed, 2 warnings**、GUI Watchlist editorとの合同実行 **95 passed, 2 warnings**、affected **202 passed, 434 warnings**、ruff PASS。
- [ ] 独立レビューBLOCKING 0。承認後にのみStage04へ進む。

## Exit

- 未完了manifestの診断と復旧CLIが動作。
- in-process例外だけでなくprocess restart境界のテストが成立。
- **初めて**ユーザー向けApplyを有効にしてよい（GUI統合自体はStage04）。
-
## Stage 03 implementation status (2026-11-14)

Independent review follow-up remains in progress. Recovery is implemented but
Stage 03 independent review is approved (BLOCKING-0). Stage 04 CLI/GUI exposure
is implemented in the companion runbook and remains subject to its independent
review and final acceptance evidence.
The read-only recovery path rejects SQLite WAL/header/sidecar and hot-journal
ambiguity without writing; explicit apply may let SQLite perform native
hot-journal rollback under the Catalog lock. Manifests require canonical
Catalog/Watchlist/namespace bindings and verified backup facts. Catalog
deletion also compares the complete non-target logical fingerprint inside the
same transaction before commit, so an injected mutation of another Work
rolls back rather than becoming a post-commit recovery case. Unknown Catalog
tables/columns fail closed.

The explicit service/CLI recovery path is implemented: `work delete recover`
supports dry-run diagnosis and verified rollback/roll-forward, while
`work delete bind` performs an operator-declared, read-only management-store
bootstrap with CAS and sealed complete-set semantics. Recovery re-reads and
validates the manifest under admission→Catalog→Watchlist locks, checks all
bound management stores, verifies Catalog logical before/after rows, exact
Watchlist bytes, and every file's size/SHA/strong identity. Mixed per-file
states may be rolled back only when every individual side is verified;
ambiguous/tampered state remains `RECOVERY_REQUIRED`.

The runtime gate is connected to Discovery, registration, Batch execution, and
JobStore enqueue when the request carries its effective Catalog path. The gate
is checked again after the Catalog lock to close the TOCTOU window; normal
queue registration during an active worker remains permitted. True subprocess
`os._exit` recovery, manifestless active reservation diagnosis, idempotent
recovery, and isolated binding/gate tests are covered. Physical power-loss
durability remains unverified; normal destructive CLI/GUI Apply is still
deferred to Stage 04.

Preview also fails closed for a Catalog Artifact marked `missing` or `deleted`
when its recorded ZIP locator, or the recorded status stem, still exists on
disk. The implementation never infers a replacement filename; a genuine
absence remains eligible for the existing manual/missing-artifact contract.

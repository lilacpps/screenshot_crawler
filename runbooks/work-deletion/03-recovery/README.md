# Stage 03 — 強制中断・再開・安全な公開ゲート

**状態:** PLANNED / NOT STARTED。前提: Stage02のApplyとbackup/manifestの状態契約。CLI/GUI公開は本Stage完了後。

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

- [ ] ファイル移動前intent直後、rename後状態記録直前、複数ファイル中間、バックアップ完了直後でprocess kill相当を再現。
- [ ] DB commit前/中/直後（manifestは前phase）、Watchlist atomic replace前/直後、DONE記録前にkill相当を再現。
- [ ] 2回recoverしても追加の削除・上書きが起きず、同一最終結果（idempotency）。
- [ ] 同じpathに他WorkのZIPが作られた場合や元/退避両方にファイルがある場合は自動復旧禁止。
- [ ] 管理対象ジョブがある/終了未確認、Lock競合、Catalog/Watchlist外部変更があると安全停止。
- [ ] Pending operationが残るCatalogで通常Batch/Full/再登録/削除が止まる。復旧後には解除。
- [ ] すべて隔離したSQLite・ZIPで実施し、本番実作品には触れない。
- [ ] 適切なテスト結果・未回収問題をPROGRESSへ記録。独立レビューBLOCKING 0でStage04へ。

## Exit

- 未完了manifestの診断と復旧CLIが動作。
- in-process例外だけでなくprocess restart境界のテストが成立。
- **初めて**ユーザー向けApplyを有効にしてよい（GUI統合自体はStage04）。

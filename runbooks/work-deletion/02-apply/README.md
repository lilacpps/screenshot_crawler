# Stage 02 — 退避・DB/YAML削除（CLI/GUI非公開）

**状態:** IMPLEMENTED / INDEPENDENT REVIEW APPROVED。前提: Stage01のread-only Planと所有証拠が独立レビュー承認済み。通常のユーザー向けApplyはStage04まで非公開。

## 目的

隔離fixture上で、退避とCatalog/Watchlist削除を単一Workに限って実行する。通常例外はrollback、DB commit後はroll-forward可能な中間状態を残す。**Stage03が通るまでユーザー向けApplyは公開しない。**

## 設計と変更範囲

- `maintenance/work_deletion.py`に`apply(plan_token, ...)`、manifestとfile moveの局所的処理。Qtなし。
- `catalog/service.py`に `delete_work_records(work_id, expected_snapshot)` を追加。**単一SQLite transaction**で子から消し、期待行数/全FKを検証。既存Catalog schema v7のまま。
- `watchlist/service.py`に `delete_work_targets_and_archive_state(work_key, expected_revision)` を追加。**全targetsとarchived_work_keysを同じ1回のatomic replace**で更新。既存 `apply_edit` と `set_work_archived` を2回呼ぶ実装は不可。
- `catalog/backup.py` のonline backupを再利用。`work deletion`専用のraw-SQL接続乱用や`PRAGMA foreign_keys=OFF`は不可。

## Apply順序

1. Catalog job lock → Watchlist edit lockをStage00で定めた統一順に取得。非終端jobの不存在を確認。plan token/Work ID/全DB参照/Watchlist原本/全path/hashを再検証。既存の未完了manifestがあれば新規削除を拒否。
2. 一意の退避operation IDとフォルダを`exclusive create`し、manifestの準備段階を書込・fsync。Catalogがある場合はonline backupして整合性をチェックし、Watchlist原本はbytesのまま保存。保存失敗なら削除しない。
3. 移動元・移動先をmanifestに先行記録してfsync → 同一volume上でファイルを一つずつatomic rename → hash/存在確認して状態を記録。ZIPとstatusは論理的に一組、両方をmanifestに列挙する。collision時は上書きせず停止。
4. 退避全件の整合性が確認できたら`CatalogService`でWork関連行を子→親の順でDELETE。`PRAGMA foreign_key_check`、削除件数、他Work不変性を検証し、COMMIT。
5. DB COMMITがcutover。以降は別Workへの影響を防ぐため**rollback目的のCatalog全体restore禁止**。Watchlist専用APIで対象keyとarchived entryを原子的に削除。CAS衝突はRECOVERY_REQUIREDとし、後で安全にroll-forward。
6. WorkがCatalog/Watchlistから消え、保全ファイルが存在し元ファイルが不在、非対象Workが保全されていることを検証してDONE。退避データは保持する。

## 異常系

- **DB commit前:** 原則ファイルを元位置へ戻す。戻し操作自体もsource/destination/hashを確認し、衝突を上書きしない。戻せなければRECOVERY_REQUIRED。
- **DB commit後（またはcommit有無不明）:** DB状態を再照合し、削除済みならWatchlist更新をroll-forward。DB状態が事前と一致なら安全なrollback、どちらでもなければ復旧待ち停止。
- **Watchlist atomic replace成功→manifest更新前:** 再照合してDONEに進める。Watchlistが外部変更された場合は書き戻さない。
- **WorkがWatchlist-only:** Catalogが不在の場合はCatalog作成/バックアップをしない。ファイル退避0件と明示し、原子的YAML更新で完了。曖昧な既存ZIPは自動回収しない。

## 受け入れ条件とテスト

- [ ] 複数site、全status、historical artifactを含むWorkの削除後にWork関連行0・FK check OK。
- [ ] 非対象Workの全DB行/ZIP/status/YAMLが変更されない。対象ZIP/statusのhashが退避前後で一致。
- [ ] トップレベルYAML未知key、コメント/CRLF/空targets、archived_work_keysを維持または対象のみ削除。
- [ ] 退避作成/backup/途中rename/DB DELETE/Watchlist更新で故意に例外を発生させ、正しい未変更またはRECOVERY_REQUIREDとなる。
- [ ] 同一volume/許可root、path衝突、別Work alias、権限不備、予想外の変更に対し書込前に拒否。
- [ ] Stage02の機能をGUI・CLIの破壊的コマンドで公開しない。独立レビューとPROGRESS記録を完了。

**注意:** このStageのテストだけではSIGKILL/電源断の回復を保証しない。Stage03必須。
- Stage 02 implementation record (2026-11-14): `WorkDeletionPreviewService.apply(plan_or_token)` is implemented and is now used by the Stage 04 CLI/GUI surfaces. It acquires the separate admission lock, then Catalog and Watchlist locks, re-previews and adopts the fresh locked plan, creates an exclusive fsync manifest and verified Catalog backup, moves primary artifact/status files with no-clobber same-volume rename, deletes the exact Work graph in one FK-checked CAS transaction, and atomically patches all Watchlist targets plus archived state. Pre-commit exceptions restore files and mark `ROLLED_BACK`; uncertain/post-commit failures preserve evidence and mark `RECOVERY_REQUIRED`. Isolated Stage 02 tests cover normal, Catalog-only, Watchlist-only, stale/forged plan, comments/CRLF, full dependent rows, backup/move/DB/YAML failure injection, and non-target protection.
- BLOCKING7 follow-up (2026-11-14): canonical same-instance DTO cache is mandatory, paths/namespace are token-bound, Watchlist original/after bytes are durably snapshotted, each file has fsync INTENT/VERIFIED checkpoints, and `active.json` reserves the Catalog namespace before destructive work. Source/destination strong identity is recorded and checked through move/restore/final verification; rollback observes every intent and escalates ambiguity to `RECOVERY_REQUIRED`. DONE performs final target/non-target invariants. Final isolated suite: 32 passed; affected suite: 262 passed; ruff/diff-check pass. Stage 02 independent review is approved; public entry points are covered by Stage 04.
-
## Stage 02 implementation status (2026-11-14)

The shared Apply path is implemented and exposed through the Stage 04 CLI/GUI
surfaces after the Stage 03 recovery gate. The destructive sequence is admission lock, Catalog
lock, Watchlist lock; a canonical fresh preview is the sole authority. The
namespace `active.json` reservation is durably written before the operation
manifest, so a crash in that interval is still gated. Watchlist disappearance
after replacement is treated as unknown/recovery-required when the original
Watchlist or target/archive state was present; it can never be reported DONE.

Snapshots, manifest replacements, active-marker removal, and file renames use
best-effort file and directory `fsync` barriers. Directory fsync is unavailable
on some Windows/filesystem combinations, and this is not a proof against
physical power loss. True process-kill and restart recovery remain Stage 03
acceptance work. The latest isolated Stage 02 suite is 34 passed (2 warnings);
the affected suite and independent review are still required before Stage 03.

Relative Artifact locators and status `archive_path` values retain the
existing process-CWD resolution semantics used by archive maintenance and
Batch. A custom Catalog parent is never used as an implicit new base; raw
traversal and reparse checks remain fail-closed before resolution.

The trash operation directory is reserved with exclusive creation before any
Watchlist snapshot or manifest write. A name race with an unrelated existing
directory stops Apply without touching that directory or creating an active
marker.

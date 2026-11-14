# Stage 04 — CLI / Windows GUI / E2E / ドキュメント

**状態:** IMPLEMENTED / INDEPENDENT REVIEW BLOCKING-0 APPROVED (2026-11-14)。Stage04のCLI/GUI surfaceは共通Serviceへ接続済み。実データ操作は行わず、破壊的操作の検証は隔離fixtureに限定した。Full suiteはWindows `pytest_asyncio`/IOCP teardown timeoutで完走せず、最終検証制限として記録する。

## 目的

read-onlyプレビューと明示的削除を同じServiceでGUI/CLIに接続し、同一`work_key`の再登録と別サイトFull/Batchが旧履歴に妨げられないことを隔離E2Eで確認する。

## CLI（提案。Stage00で既存パーサとの互換性を確定）

~~~powershell
python -m screenshot_crawler.cli work delete --work-key sample --dry-run --json
python -m screenshot_crawler.cli work delete --work-key sample --apply
python -m screenshot_crawler.cli work delete recover --operation-id <id> --dry-run
python -m screenshot_crawler.cli work delete recover --operation-id <id> --apply
~~~

- `--dry-run`は画面・DB・ZIP・保全フォルダを変更しない。`--apply`は最終プレビューのtokenと環境/ジョブ再検証を必須にする。CLI上も明示的に危険性を表示し、対象Work ID/Work keyを誤認しない。
- JSONには成功/blocked/recovery-required、対象件数、退避先、blockers、operation idを機械可読で返す。異常な部分成功をexit 0で返さない。

## GUI契約

- `gui/main_window.py`のWork行右クリックに「作品を削除…」を追加。既存アーカイブ/復帰は維持。キー/サイト行には追加しない。
- GUI Dialogは対象Work key・タイトル・全サイト/key・Item/Run/Artifact数、ZIP数・容量・退避先、検証済みか・blockersを表示。非空の確認チェックと削除ボタンを設け、表示と操作は二段階で誤操作防止。
- 変更中のWatchlist editor、保存中/読込中、実行/待機/監督状態不明のジョブ、stale snapshot、未完了削除時は操作禁止。GUIだけでなくbackendで同条件を再検証。
- Qt main threadでSQLite backup/hash/renameをしない。既存QRunnable/Signalを参照し、操作中のreload/別ジョブ開始/終了を安全に制御。処理中にUIを閉じた場合の結果は実manifestで追跡し、成功推定しない。
- 終了状態をDONE / BLOCKED（未変更）/ RECOVERY_REQUIRED（手動復旧要）として表示。DONE後はInventoryを更新し、Work行が消える。error時は最新版読み直しと復旧導線を表示。
- Workのアーカイブ/非表示と削除は別操作。トラッシュの自動削除、GUI復元は設けない。
- Previewは完全Catalog snapshotのfingerprintを維持したままID辞書join、library/status一回索引、同一preview内のstable file fact再利用を行う。候補走査とSHA chunk読取はQt非依存cancel tokenを確認し、Plan/token公開前のキャンセルはno-writeで終わる。GUI progressはqueued/throttledで段階・処理単位・経過秒を表示し、Apply中のキャンセル/closeは受け付けない。

## E2E fixtureシナリオ（外部サイト・実作品不要）

1. 2サイト3key・一部completed、複数historical Artifact、failed/pending、quota/scope-sync/discovery証拠、archived設定ありの作品A、同タイトル別work_keyの作品Bを作る。
2. Aをプレビュー。Aだけの全依存とZIP/statusが列挙され、Bのレコード/ファイルが除外されることを確認。
3. GUI/CLIの明示ApplyでAを削除。全FKとmanifest/退避hash、Watchlistのコメント/改行保持を検証。
4. 同じ`work_key`に別サイトのWatchlistを登録し、人工Discovery AdapterによるFull、`scope-sync`（必要な場合）、Batch Planner/Executorを隔離出力で実行。新規`pending`から`completed`へ進む。旧ZIP/statusは衝突せず、旧quota・歴史Artifactも引き継がない。
5. 重複locator/他Work alias、status不一致、変更済みYAML、queued/running job、途中kill復旧をGUIとCLI双方から検証。
6. Windows Qt GUI smoke（コンテキストメニューWork行、キャンセル/no-write、実行中disabled、処理結果表示、終了時再読込）、headless CLI JSON・exit codeも確認。

## 変更ファイル候補

- `src/screenshot_crawler/cli.py`
- `src/screenshot_crawler/gui/main_window.py`、`src/screenshot_crawler/gui/work_deletion.py`
- `tests/unit/test_work_deletion.py`、`tests/unit/test_cli.py`、`tests/unit/test_gui_model.py`、`tests/integration/test_gui_smoke.py`、必要に応じE2Eを1本
- `docs/GUI_README.md`、`docs/ARCHITECTURE.md`、必要に応じ`docs/SPEC.md` / `docs/DECISIONS.md`、`note/00_core.md`

## Exit / 最終レビュー

- [x] Isolated affected CLI/maintenance/GUI suite: **313 passed, 442 warnings**; GUI subset: **46 passed, 1 warning**; Discovery→delete→same-key Full→package/Batch exact-path E2E: **1 passed, 10 warnings**. Root namespace and user config hashes were unchanged before/after.
- [x] Full suite was attempted in an isolated CWD with a 120-second per-test timeout. Full2 was interrupted at approximately 5% after no output at `test_comicfuz_native_nonblank_1`; Full3 reached approximately 5% and emitted a Windows IOCP/`pytest_asyncio` teardown timeout stack without a suite summary. Both are recorded as incomplete, not PASS. The unchanged ComicFuz parameterized fixture separately passed `[False]` and `[True]` (**2 passed, 5 warnings, 11.37s**); this does not prove a causal baseline. `ruff check src tests` passes.
- [x] 実サイト/live verificationは不要。不要な外部アクセスや権利消費がない。
- [x] 独立 Stage 04 review BLOCKING 0. The isolated deletion→same-key registration→Full→Batch E2E itself passes; full-suite incompletion remains a documented limitation.
- [x] docs/GUI_README.mdの操作・復旧手順、note/00_core.mdの現行実装スナップショット、PROGRESSを実装と同期。
- [x] 変更したコード、テスト件数/skips/未実行カテゴリ、退避/復旧契約、未対応ケースを `PROGRESS.md` と `note/00_core.md` に記録。

# Stage 00 / 01 / 02 / 03A 実装・検証結果

2026-11-11 / feature branch: `feature/hanayume-catalog-repair`。
Stage 02は実装・隔離コピー検証済み。追加のStage 03A履歴ZIP分離を実装・合成apply検証済み。
Stage 03の採番/不要ZIP削除は **PLANNED / NOT YET IMPLEMENTED**。
ユーザーがStage 02を適用した後の実Catalogをread-only確認済み。履歴先ZIP locator15件も確認した。
assistantによる運用Catalog apply、Watchlist編集、Batch/Grant-only、ZIPのrename/delete/overwriteは実施していない。
作業開始時から存在したwatchlist.yamlの未commit変更、`.worktrees/`、既存pytest出力は保持した。

## Batch Runが無反応に見える問題（2026-11-11）

確認用の旧GUIとユーザーの新GUIが同時に存在し、旧GUIが同management DBのcontroller leaseを保持していた。
新GUIのボタンは有効だが、押すと排他例外がコンソールだけに出ていた。スクロールcache修正とは直接無関係。
旧GUIはmonitorがsucceeded/緊急停止disabledでジョブ終了済みと確認し、その旧windowだけを閉じた。
選択12 keyの新GUIは保持。排他byte lockの一時取得/解放で空きを確認し、lockファイル内容は変更していない。
本番Batchボタンは押さず、Catalog/ZIP/チケット操作やユーザーの別CLI取得停止は行っていない。

変更: management/job_controller.py（RuntimeError互換のControllerOwnershipError）、gui/main_window.py
（実行/Jobs入口の画面内例外表示、queue済みjob ID表示、成功誤表示防止、初期化の公開/lease解放）、
tests/integration/test_gui_smoke.py。docs/GUI_INVENTORY/GUI_README/ARCHITECTUREとnote/00_core.mdを同期。
正常な排他制約、最新Catalogからのworker計画、queued jobの再開規則は維持。自動再実行は追加しない。

targetedは4 passed / 0 failed / 0 skipped / 28 deselected、1 warning、1.61秒。
Qt smoke/実行inputs、管理jobs、Work/Watchlist editorの5ファイルを `--basetemp output/gui-start-affected` で
**125 passed / 0 failed / 0 skipped**、1 warning、76.78秒。
二重GUI競合中はjobを作らずエラー表示、競合解消後に同選択で再操作可能、登録後spawn失敗でjob ID表示、
reconcile失敗でlease解放、既存の合成worker/monitor/queue/rerun回帰を確認した。
`ruff check src tests` と対象diff-checkはPASS。full suite/Research/LiveはGUI開始エラー処理のみのため未実行。
実環境の競合は旧GUI終了で解消。画面内エラー表示のコード改善は次のGUI起動から反映される。

## 作品ビューのスクロール性能（2026-11-11）

ユーザー申告の「作品ビューを下へスクロールすると重い」を実Catalogの隔離offscreen GUIで再現。
原因はQt index()等がvisible_children()経由で毎回全兄弟を走査する既存処理だった。
271作品/292 key/47,646 Sourceで、30回のscroll描画中に約169万回の表示判定が発生した。
表示子一覧をprojection/filter状態ごとにcacheし、検索/状態/Archive filter/snapshotで失効、sortで順序cache失効、
projection切替で新nodeを構築する。非表示nodeのFalseもcacheする。選択/実行/Discoveryの意味は変えない。

新規の履歴分類は再読込時だけでscroll時には走らない。これも候補Item/Work/bindingだけをindexするようにし、
約36〜46ms（5回中1回132ms）→約5.2msに削減。29件の履歴/旧ID分類と未管理の区別は維持する。
通常GUIにZIP読取/hash/実サイト通信は追加していない。

計測証拠: `output/gui-performance/{before,after,work-before,work-after,scroll-comparison}.json`。
cProfile付きの30 scroll比較は2.217秒→0.340秒（最遅frame86.5ms→20.8ms）。
計測器なしの同process A/B（隔離windowに旧メソッドを再現）は3.056秒→0.630秒、約4.85倍。
これは実データ・同一snapshotのoffscreen比較であり、他process負荷やOS描画がある実desktop FPSの保証ではない。
全計測でCatalog/Watchlist SHA-256が前後不変。ユーザーの開いているGUIは変更していない。

変更ファイル: gui/model.py、maintenance/hanayume_repair.py、tests/unit/test_gui_model.py、
docs/GUI_INVENTORY.md、GUI_README.md、ARCHITECTURE.md、note/00_core.md、note/10_hanayume.md、本PROGRESS。
300作品×1000回のindex参照で全件再走査が増えないことと、検索/filter/並べ替え/アーカイブ/snapshot/
projection切替のcache失効を回帰テストにした。
targeted: Qt model/Inventory/修復解析Unitの3ファイル **96 passed / 0 failed / 0 skipped**、82 warnings、24.07秒。
affected: Qt model/Inventory/Work editor/Watchlist editor、GUI archive/Discovery toggle/smoke/execution inputsの
8ファイルを `--basetemp output/gp-aff` で実行し **188 passed / 0 failed / 0 skipped**、1 warning、110.56秒。
`ruff check src tests` と対象trackedファイルのdiff-checkはPASS。
full suite/Research/実サイト通信/本番データ操作はGUI描画と分類indexの最適化だけのため未実行。
GUIは起動し直すと反映する。実desktopでの操作感の最終確認は再起動後に必要。

## 適用後の通常GUI — 履歴と旧ID参照の表示

通常Inventoryが修復の非現行keyを未管理へまとめていた表示上の不足を修正した。
「履歴保管（旧話）」「移行済み旧ID（参照用）」へ分け、真正の所属不明は従来表示を維持する。
判定には修復監査marker/保存binding/Work/site/担当OFF/unavailableを要求。prefixだけでは認定しない。
親の進捗・同期/review status・重複Item警告では正常な履歴を中立にし、現行の担当数を維持する。
履歴/旧ID行は実行/Discovery切替不可、進捗は対象外、候補列は—、詳細にSource数/Item取得状態を表示する。

変更: maintenance/hanayume_repair.py（site-local判定）、management/inventory.pyとmodels.py、gui/model.pyとdetails.py、
tests/unit/test_inventory.pyとtest_gui_model.py。仕様/操作説明はSPEC/ARCHITECTURE/GUI_INVENTORY/GUI_README、
現行noteは00_core.mdと10_hanayume.md、Runbook README/02-migration/本PROGRESSを同期した。
実Catalogのread-only証拠は `output/hanayume-repair-inventory-labels/verification.json`。
NGライフ現行154（completed21/pending133）、旧話履歴16、旧ID参照13。親statusはsynced、履歴由来の診断なし。
Catalog/WatchlistのSHA-256/mtimeは表示検証の前後で不変。通常GUIはZIPをstat/hashせずCatalogの記録だけを表示する。
Stage 02/03A節の「運用apply待ち/本番未適用」は実装当時の記録であり、現在はユーザー適用後の表示確認段階。
targeted: InventoryとQt modelを `--basetemp output/hr-label-targeted` で **63 passed / 0 failed / 0 skipped**。
affected: Inventory、Qt model、GUI smoke/execution inputs、修復解析/移行/ZIP Unitの7ファイルを
`--basetemp output/hr-label-affected` で **210 passed / 0 failed / 0 skipped**、136既存warnings、113.44秒。
履歴候補列を—/担当外数を確定値にした最終表示調整後、Qt model全体を
`--basetemp output/hr-label-final-model` で **18 passed / 0 failed / 0 skipped**、1 warning、2.57秒。
有効な旧話/旧IDの分離、prefixだけ/担当ON/receipt欠落/他siteを誤認しないこと、真正の未管理との共存、
親集計・同期状態・要確認/担当外filter、実行選択禁止、詳細/Membership表示、DB/Watchlist/ZIP不変を検証。
`ruff check src tests` と変更対象のdiff-checkはPASS。
full suite/Research/追加実サイト通信は表示projectionだけの変更のため未実行。browser-backed追加検証は不要。
Qt/offscreenと実desktopの両方で確認した。通常GUIを新しく起動しNGライフを検索/展開、
「履歴保管（旧話）」16 Source（取得済み15/未取得1）と「移行済み旧ID（参照用）」13 Sourceを詳細欄でも確認。
現行進捗21/154、履歴側の対象外表示・候補—、実行選択0件を維持し、旧ID参照行を選択して開いたまま引き渡した。
古いGUIの未保存編集は閉じていない。表示のコード変更はGUIの起動し直しで反映される。

## Stage 03A — 履歴専用ZIPの分離

ユーザー追加依頼により、Stage 02の別ボタンから履歴ZIPの分離preview/applyを提供する。
現役として使う旧ZIPは保持し、履歴専用ItemのZIPだけをBooks-historyへ移動して全Artifact locatorを更新する。
移行前はStage 02のplanに基づく投影予定を表示するがapply不能。移行後の実Catalogから再検証する。
DBの履歴keyは内部bindingでWatchlistへ追加しない。普通のkeyはWatchlist.keyと対応する。
無範囲Fullがmissing/unavailableを含め同key全Sourceを担当ONにする現行実装を変えず、履歴行をその対象から外す。

変更ファイル: `maintenance/hanayume_history.py`、`gui/repair_history.py`、既存 `gui/repair_migration.py`、
`tests/unit/test_hanayume_history.py`、`tests/integration/test_gui_repair_history.py`。
仕様/操作説明/責務/判断: docs/SPEC.md、ARCHITECTURE.md、DISCOVERY_AND_BATCH.md、GUI_README.md、DECISIONS.md。
Runbook: README.md、本PROGRESS.md、03-history.md。
同期note: note/00_core.md、note/10_hanayume.md、note/07_catalog_position_archive_plan.md。
既存renumberのpreflight/CAS/復旧設計を確認したが、通常採番の対象選択を変更せず、独立した移動処理とした。

参照/存在/size/SHA/ZIP形式、path境界/リンク/既存hardlink/衝突を検証。現役Item、external coverage、共有pathを保護。
job lock/verified backup/BEGIN IMMEDIATE内再検証とpersistent journalを先行し、排他的hardlink作成＋元path解除で移動。
全Artifact locatorをCAS更新。通常例外はDBとfileの復元を検証し、不明/失敗はRECOVERY_REQUIREDとして再apply拒否。
Item/Source/Target/Run/quota、ZIP bytes/名前、Watchlist、過去status/manifest snapshotは維持する。
強制終了からの自動復旧helperは未実装。journalによる明示復旧、残るsidecar衝突、採番/削除は別作業。

検証: 修復ZIP Unit/Qt、既存移行Unit/Qt、SourceIdentity、renumber、Catalog backup、Batch scopeの8ファイルを
`--basetemp output/hh-affected` で実行し **160 passed / 0 failed / 0 skipped**、91既存warnings、116.22秒。
その後、network pathを解決前に拒否するguardを追加し、履歴ZIP Unitを
`--basetemp output/hh-network` で **18 passed / 0 failed / 0 skipped**、1 warning、9.16秒。
最終Unit18件＋Qt2件を含む。現役/coverage/共有path保護、投影apply禁止、全参照更新、成功/no-op、
破損/欠落/衝突/外部path/link/network/古いtoken/改変、link後例外、DB失敗、複数fileの途中失敗、
復旧失敗journalによる再apply拒否、GUIのpreview/新規JSON保存/明示applyを合成データで確認。
`ruff check src tests` と対象tracked文書のdiff-checkはPASS。
full suite/Research/追加実サイト通信は未実行。専用maintenance/Qtだけの変更で、通常Discovery/Batch/schema/Coreに変更なし。

実データはread-only previewのみ。証拠: `output/hanayume-repair-stage03-history/verification.json`。
NGライフは**履歴へ移動15 ZIP / 現役として維持21 ZIP**、blockerなし。
本番の移行前投影と移行済み隔離copyからのpreviewが全path/Artifact ID/判定で一致。
本番Catalog/Watchlist/元報告/copyのSHA-256不変。実ZIPは移動していない。
実desktopでStage 02の新ボタンからStage 03Aを開き、15/21件の集計、移動前/履歴先path、
未移行の投影予定でapply disabledであることを確認。最初の移動行を選択したままGUIを開いて引き渡した。
既存GUIと未保存メモは閉じていない。本番apply/ZIP移動はユーザーによる別の明示操作待ち。

## Stage 02 — 現行結果

ユーザー保存 `output/hanayume-repair.json` を現在のNGライフgraphと照合し、
13組の旧completed再利用と141グループの新側採用をプレビューできる。
新旧pendingでは履歴/権利/手動編集/別Source/個別Targetのない旧132件を削除し、新pending133件を残す。
scene15③の旧pending #32061はCrawlRun1件があるため保管。取得済み履歴・ZIPは引き続き保持する。
人間が対応と利用方針を採用することと、技術的な本文同一性の証明を区別する。
詳細契約: [02-migration.md](02-migration.md)。運用applyは別の明示承認待ち。

新規: `maintenance/hanayume_migration.py`、`gui/repair_migration.py`、
`tests/unit/test_hanayume_migration.py`、`tests/integration/test_gui_repair_migration.py`、
`02-migration.md`。更新: 既存identity maintenanceのtransaction内private境界、
Stage 01の履歴保管メモ/Stage 02入口、main GUIの更新通知と起動option、fixture、仕様/Runbook/両note。

- reportの型/version/重複key、Work/Source/Item/Target/全履歴snapshot、site/key/側/重複を検証。
  当該Work変更は拒否し、無関係なWorkだけの更新は読込時に許容。preview tokenは現全Catalogに結び付く。
- GUIに方針選択、全新側採用、対応再編集、新規preview保存、backup付きapplyを追加。
  デフォルトは人間の採用checkbox未チェック、apply不能。方針/入力変更はpreviewを無効にする。
  適用前と適用後の現行Item/Source ID・取得状態、残す/物理削除するDB行を分離表示。
  選択行の説明でItem/Source/Target ID、新URL、旧ID保管alias、採用ZIPを明示する。
  新規preview JSONにもoutcomes/after_summaryを含め、方針変更/失敗時は古い表示を消す。
- 最新ZIP/成功Run/存在/size/SHA-256/形式を検証。旧利用はpristine 1対1だけidentity継承。
  donor履歴/編集は無理にmergeせず、新側か明示的なexternal coverageで旧Artifactを参照。
- 非現行履歴binding＋担当OFF＋scope configuration history登録で、Full/Scope Syncの再有効化を防ぐ。
  旧identityはquotaなしaliasで予約し、再掲時は既存key所有権guardでfail-closed停止。
- Catalog/Watchlist lock、backup成功、BEGIN IMMEDIATE内再検証、全件単一transaction、
  最終ZIP/報告/Watchlist/FK検証、監査markerの冪等性を実装。ZIP/Watchlist/履歴は書き込まない。

### Stage 02の検証

旧pending整理の現行検証: `output/hanayume-repair-stage02-pending/{operational-preview,copy-verification}.json`。
新しい隔離copyだけにapplyし、previewどおりの旧pending132件＋新donor13件のItem/Source/Target削除、
現行154 Sourceのstatus/ID/external_id一致、全Run/Artifact/resource table hash不変、再apply no-op、
Scope Sync成功、通常Batch候補1件/重複なしを確認した。元Catalog/Watchlist/報告SHA不変。
保管は元旧Source16件＋旧ID予約alias13件＝29件。新側completed21/pending133は維持。
今回変更したproductionはmaintenance/hanayume_migration.pyとgui/repair_migration.pyのみ。
対応Unit/Qt、仕様・操作説明・Runbook、note/00_core.mdとnote/10_hanayume.mdを同期した。
旧pendingの削除は対応採用後のbackup付きapplyに限定し、本番applyは未実施。
最終targeted/affectedは修復Unit/Qt、SourceIdentity、Scope Reconciler/Sync、Batch scopeの6ファイルを
`--basetemp output/hm-pending-final2` で実行し **122 passed / 0 failed / 0 skipped**、
91既存warnings、99.14秒。空旧pendingの1対1/分割/統合、自動/新採用/再取得、失敗Run/Artifact/
quota/grant/title/note/兄弟Source/個別Targetの保護、preview後のnote/Run追加の拒否、
削除後の監査失敗rollback、backup失敗/競合/再apply、連続2回Full→Scope Sync→Batchを確認した。
Qtでは予定どおりの旧削除/新保持表示と、合成Catalogへの明示applyを検証した。
`ruff check src tests` と対象tracked文書のdiff-checkはPASS。
追加のfull suite / Research / 実サイト通信は、変更がHanayume専用maintenance/Qtに限定され、
通常Discovery/Batch/schema/Coreに変更がないため未実行。実desktop GUIと隔離copyは検証した。
更新版GUI「Stage 02 未取得旧側の削除プレビュー」を起動し、scene4①の旧 #32096削除・新 #40581維持を
右側の説明で確認。旧pending132/新donor13削除の全体集計も確認し、当該行を選択して引き渡した。
採用checkbox未チェック、apply disabledのまま、以前のGUIと未保存メモも閉じていない。

再Discoveryへの確認を強化: 既存Full後の回帰テストを連続2回のFullに拡張し、各回で新external_idの
Sourceが1件だけ、旧Item/Source IDとcompletedを維持、新側の空DB行は再生成されないこと、
全Run/Artifact/resource履歴不変を直接検証した。通常/archive_order/archive_segmentsの3構成。
`tests/unit/test_hanayume_migration.py -k full_discovery_after_apply`
（`--basetemp output/hm-rediscovery-tests`）: **3 passed / 0 failed / 0 skipped / 35 deselected**、
28既存warnings、2.07秒。production処理の変更なし、note/00_core.mdとnote/10_hanayume.mdへ照合keyを明記。
実サイト/full suite/GUIの追加検証は、production変更のない既存テスト強化のため未実行。本番applyなし。

適用後表示の改善: 修復Unit/Qtと既存SourceIdentityの3ファイルを
`--basetemp output/hm-after-state-tests` で実行し **56 passed / 0 failed / 0 skipped**、
28既存warnings、51.25秒。1対1の維持/削除予定を実apply結果と照合し、両側completed・分割/統合の
表示、方針変更で古い結果を消すこと、新規JSONのoutcomes/after_summary、read-only不変を確認した。
`ruff check src tests` / 対象docのdiff-checkもPASS。
今回の追加は表示のみでtransaction変更なし。full suite / Research / 実サイト通信は追加実行していない。

旧pending整理前の広いaffected: **427 passed / 0 failed / 0 skipped**、271既存deprecation warnings、183.47秒。
19ファイルを `--basetemp output/hm-affected` で実行した。新旧修復Unit/Qt/合成Chromium、
SourceIdentity/CLI、Hanayume identity、Inventory、Scope Sync、Batch/scope/naming、renumber、
Catalog/backup、GUI model/smoke/execution inputsを含む。
新Stage 02はUnit38＋Qt4の42件。Full→Scope Sync→Batchの再実行をunbounded/archive_order/
archive_segmentsで検証、ZIP変化後のtransaction rollback、backup失敗、競合、冪等性、
donor履歴/手動title/note、最新ZIPの不正、複数旧Source/分割/統合、未対応の明示保管を確認。
`ruff check src tests` と変更対象の `git diff --check` はPASS。

旧pendingも保管していた方針での隔離コピー検証: `output/hanayume-repair-stage02/copy-verification.json`。
copyだけにapplyし、同じplanの再applyがno-opであること、全CrawlRun/Artifact/resource tableの
hash不変、Scope preview成功、通常Batch plan候補の重複なしを確認した。
現行154 Sourceはcompleted21/pending133。元の旧Sourceは13件を現行へ継承、148件を履歴保管。
旧ID保管aliasを13件追加（履歴Source合計161）、新側の空Item/Source/Targetを各13件削除する。
旧Item/Sourceを一律削除する処理ではない。計画時点でBatch候補は1件、
他はcompleted21/paid17/quota_work_limit115でskip（これはpytest skipではなく通常のBatch判断）。
取得やチケット消費は実行していない。
CLIと同じ実library root `output/Books` での追加plan確認も候補1件/unique Item1件。
証拠は `actual-library-plan-check.json`。最終コードの運用plan tokenは検証済みpreviewと一致した。

旧方針のread-only計画（現行applyには再previewが必要）: `output/hanayume-repair-stage02/operational-preview.json`。
適用後graphを含む追加preview: `operational-preview-after-state.json`（同じディレクトリ）。
scene10③では旧Item/Source/Target #32076を現行completedとして残し、新側の空Item/Source/Target
#40561だけを削除、旧episode ID保管aliasを追加する予定。ZIP/Run/Artifactは保持する。
更新版の実デスクトップGUIで当該行と右側の説明を確認し、行を選択したまま引き渡した。
既存GUIは閉じず、採用checkboxは未チェック、適用ボタンはdisabledのまま。運用applyは行っていない。
`catalog-copy.sqlite` は検証後のcopyであり運用へ丸ごと戻す用途ではない。
copy apply前のverified backupは `copy-backups/` に保持。運用apply時は運用Catalogから
改めて現在tokenを検証し、`output/hanayume-repair-backups` へ新規backupを作る。
運用Catalog/Watchlist/元報告のSHA-256はcopy検証の前後で一致している。
Stage 02 GUIを実デスクトップで起動し、保存報告、141グループ新側採用/13組旧継承のsummary、
各行の方針・実施内容、backup先、未承認でapplyがdisabledであることを確認した。
採用checkboxを未チェックのまま、適用ボタンを押さずに引き渡す。既存Stage 01画面も閉じていない。

未実行: repository full suite（schema/Core/通常Discovery/Batch/Browserは変更せず、
private transaction境界と保守GUIに対して427件のaffectedを実行）、既存Research helper（変更なし）、
実サイトFull/Batch（今回のStage 02に通信は不要、未承認の取得/消費をしない）。
本番applyとStage 03の採番/ZIP操作は未実施。

## 現行の照合方式 — ユーザー確認後の修正

話数ラベル全体（丸数字のpart含む）・話数番号が一致し、旧新両側で対応が一意なら、
他の弱い候補を除いて1対1推測を優先する。重複した完全ラベルは任意選択せず、残りだけを
従来の複数候補グループにする。手動titleや表示位置の変更は完全ラベル一致を妨げない。
GUIは「ラベル一致で1対1推測」と表示し、件数とJSONのmatch_ruleにも区別を記録する。
Stage 01のAPI/手動メモの優先度、本文未証明、候補だけではcompletedを引き継がない条件を維持する。

実CatalogのNGライフをローカルで再解析: ラベル優先1対1推測145組、複数グループ50→2。
残るのはscene2①〜⑤→scene2（5対1）、scene3①〜④→scene3（4対1）。
APIの追加アクセスなし。Catalog/Watchlist SHA-256前後一致。
証拠: `output/hanayume-repair-verification/label-priority-result.json`。
未保存の確認メモを破棄しないため、既存GUIは閉じず、更新版GUIを別ウィンドウで起動した。
実デスクトップの「話数ラベル優先・読み取り専用」画面で推測145組/複数2グループ、
1対1の各行と「ラベル一致で1対1推測」表示を確認した。旧ウィンドウも保持されている。

変更: maintenance/hanayume_repair.py、gui/catalog_repair.py、対応するUnit/Qt test、
README、docs/GUI_README.md、note/00_core.md、note/10_hanayume.md、本PROGRESS。
修復機能のUnit/Qt/合成Chromium: **39 passed / 0 failed / 0 skipped**、109 warnings、19.25秒。
コマンドは `--basetemp output/repair-label-tests` で修復Unit/Integrationの2ファイルを実行。
3対3→3つの1対1、part違いの分割/統合、完全ラベル重複（8件超も含む）、並びの入れ替え、
APIがラベル推測に優先・手動メモが両方に優先、Batch/既存データ不変を検証。
最終タイトル変更後も、partの1対1表示と手動split/API結果のQt2件を再実行しPASS
（5件は意図的にdeselected、skip0）。`ruff check src tests`、変更対象のdiff-checkもPASS。
この修正では通常Discovery/Batch/共通reader/probeを変更していないため、過去の広いaffected、
full suite、Research helper、実サイト通信は再実行しない。後述の33件/広いaffected結果は初回時点。

## 完了した機能

- Stage 00: Catalog v7、Full reconciliation、16件制限、identity maintenance、
  scope/flags/order/segments、Batch、renumber、GUIを調査しREADMEに設計・各Stage契約を記載。
- Stage 01a: 全Run/Artifactを含むread-only snapshot、作品選択、旧unavailableと
  新availableのpending/completed、同一Itemの複数Sourceを含む比較。
- 話数ラベル/手動title/番号/前後ラベル/位置/ZIP記録から候補生成。
  API identity、人間のメモ、metadata推測を区別し、本文同一性の証明済み数は常に0。
  1対多/多対1/多対多の候補群を扱い、複数候補を分割・統合の確定としない。
- Stage 01b: 独立したmetadata GET解析、offset/件数/GET数/deadline/間隔/cancel、
  strict two-endpoint identity、異なる作品/key/URL/矛盾index拒否、部分結果。
- Stage 01c: Qt workerによる左右表・検索・全履歴/設定/根拠表示、任意複数行の手動対応、
  保留、再取得、解除、一部候補の切り出しと残りの保持。片側だけの保留/再取得も可能。
  新規JSON保存（上書き拒否）。main GUI toolbarとstandalone起動を追加。
- Stage 01d: 実デスクトップでNGライフの左右一覧と集計を確認し、GUIを開いた状態で引き渡す。

## 変更ファイル

| ファイル | 責務 |
|---|---|
| `src/screenshot_crawler/maintenance/hanayume_repair.py` | read-only解析・候補・手動メモ・新規JSON |
| `src/screenshot_crawler/site_adapters/hanayume/repair_probe.py` | bounded exact metadata GET / strict native proof |
| `src/screenshot_crawler/gui/catalog_repair.py` | worker / shared CDP lifecycle / 比較GUI |
| `src/screenshot_crawler/gui/main_window.py` | toolbar、既存guard、standalone CLI |
| `src/screenshot_crawler/management/catalog_reader.py` | 明示include_history、通常latest projectionは維持 |
| `tests/conftest.py` | 架空作品のv7 DB/ZIP/履歴fixture |
| `tests/unit/test_hanayume_catalog_repair.py` | ローカル解析・予算・不変性・Batch不変 |
| `tests/integration/test_gui_catalog_repair.py` | Qt操作/workerと実Chromiumの合成通信 |
| `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/DISCOVERY_AND_BATCH.md`, `docs/GUI_README.md` | 実装契約・責務・操作手順 |
| `note/00_core.md`, `note/10_hanayume.md` | 現行挙動・設定/出力/制約/実確認 |
| `runbooks/hanayume-catalog-repair/{README,PROGRESS}.md` | 設計と結果、後続Stage判断 |

schema/通常Discovery/Batch Planner・Executor/source identity apply/renumber/他サイトは変更なし。

## テスト結果

### 新規機能（最終実装）

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv/Scripts/python.exe -m pytest -q --disable-warnings -p no:cacheprovider --basetemp output/repair-final2 tests/unit/test_hanayume_catalog_repair.py tests/integration/test_gui_catalog_repair.py
```

**33 passed / 0 failed / 0 skipped**, 109既存pytest-asyncio deprecation warnings、19.74秒。
Unit 27件、Qt 3件、実Chromiumでsynthetic transportを使う3件。
DB/Watchlist/既存ZIPのbyte/mtime不変、通常latestと全履歴の差分、手動title/note、
scope/order/segments、他Work/key/native identity/URL/site拒否、完成済み新側、複数旧、
片側指定、丸数字part、候補一部編集、Batch plan/重複候補不変を確認。
API正常・foreign/index矛盾/redirect/URL不一致/型不整合/403/429、16超、
GET/time/count/offset/cancel、POST/viewer拒否、worker failure回復、新規保存/上書き拒否を検証。

### 既存の影響範囲

既存Catalog/Inventory/identity/GUI/Hanayume Discovery/Batch/scope/naming/renumberを含む
22ファイルのaffected実行: **687 passed / 5 failed / 0 skipped**、284 warnings、557.65秒。
使用base temp: `output/repair-tests-affected`。失敗は次の既存browser tests:

- `test_hanayume_now_free_discovery_uses_only_fresh_series_auth_markers[delayed-32]`:
  expected freeがunknown。production変更なしで再実行PASS。遅延ケースの原因は確定していない。
- `test_hanayume_ticket_read_preview_without_account_icons_uses_existing_grant_directly`
  のalready-granted / already-granted-start: WinError 206（Windows path length）で出力dir作成失敗。
- `test_hanayume_duplicate_newer_series_target_blocks_native_current_latch`の2variant:
  synthetic click観測に到達せずNone。短い出力先で再実行PASS。

```powershell
.venv/Scripts/python.exe -m pytest -q --disable-warnings -p no:cacheprovider --basetemp C:/Users/kensu/AppData/Local/Temp/hr11 tests/integration/test_hanayume_discovery_browser.py -k 'fresh_series_auth_markers or ticket_read_preview_without_account_icons or duplicate_newer_series_target_blocks_native_current_latch'
```

**8 passed / 0 failed / 0 skipped / 135 deselected**, 5 warnings、32.75秒。
deselectedは意図的な対象選択でありskipではない。失敗5件はすべてこの再実行に含む。
affected全体を再実行したall-green結果ではない。元の失敗を消して成功扱いにはしない。

`ruff check src tests`: PASS。変更対象への `git diff --check`: PASS。
ユーザー既存watchlist.yamlの末尾空白は変更せず、全体diff-checkではその既存警告が残る。

### 実Catalog / live / GUI

実Catalogはread-onlyでv7を検証。NGライフは旧161 / 現行候補154 / 現行pending146。
候補にはscene2①〜⑤→scene2、scene3①〜④→scene3等があるが、本文や統合確定の証明ではない。
ローカル解析は約2.7秒（環境測定値、workerで実行）。

bounded liveは旧3 ID、上限6 GET/30秒/2秒間隔を指定。実際は4 metadata GET。
旧Source32106→新Source40584のepisode/summary/access/series/index一致(index619450)を確認。
残り2旧Sourceは対応未証明で、推測だけを維持。これは本文同一性の証明ではない。
証拠: `output/hanayume-repair-verification/live-result.json` と隣接するmetadata確認script。
前後のCatalog/Watchlist SHA-256一致。viewer/capture/checkout/Batch/Grant-only/ZIP操作なし。
実デスクトップでPySide6のNGライフ左右表・status/ZIP履歴・候補・詳細・集計の表示を確認。
最新コードのGUI API操作も旧3件/GET6上限/30秒/2秒間隔で実施し、
画面上でAPI対応1件、実GET4回、次offset3/161、部分結果表示を確認した。
GUI確認後もCatalog/Watchlist SHA-256はlive開始前と一致し、GUIを開いたまま引き渡した。

### 未実行カテゴリ

- repository full suite: 未実行。変更は独立したread-only機能とdefault互換の明示reader option、
  toolbar routingに限定。広いaffectedと関連browser/Qtを実行済み。
- Research helper suite: 既存PoCは変更しないため未実行。新規probeはUnit/実Chromium/liveで検証。
- Stage 02 apply失敗/競合transaction/再実行/後続Fullでの再発防止: 適用機能が未実装のため未検証。
  既存SourceIdentityMaintenanceのrollback/token/Full等はaffectedに含めた。
- 実サイト全161件/全28作品のAPI照合、本文/ZIPハッシュ照合: 未実行。人間による確認が必要。

## 未対応と次Stageの判断

- JSONはStage 02から読み込んで対応を再編集できる。Stage 01の未保存メモ/API証拠は同snapshot内だけで累積し、再解析/終了でリセット。
- ZIPファイルの存在・CRC/hash/本文は未検証。全Artifact記録を表示するだけで、同じItemの別Sourceの
  ZIPも含む。再利用可能数の断定を行わず検討候補として数える。画像previewは後続Stage。
- 同名/番号/順序の誤対応を意味的には検出できない。機械で証明できるのはnative identityまで。
  手動対応も本文証明へ昇格させない。旧1対新複数/旧複数対新1の実ファイル切断/統合は行わない。
- 各旧Source上位8辺の候補連結成分を表示するため、番号一致だけで広い候補群になることがある。
  候補がない場合も、真の対応が存在しないことを証明しない。
- unavailable/availableの分割はCatalog上の状態で、旧世代/最新サイトmembershipを証明しない。
  外部更新はsnapshotへ自動反映されない。別CLI/別GUIの実ブラウザ操作と同時に実行しない。
- Stage 02では本文証明とは別に人間の旧取得採用を明示し、非現行履歴bindingで退役を永続化する。
  Watchlist anchor/segmentsは変更せず旧anchorを含む計画をblockする。Stage 03で採番とZIP衝突を
  整理する必要がある。external coverageは新ItemのArtifactを作らず、旧参照をnote/planに残す。

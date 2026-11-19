# BookWalker quota resume — Progress

> **P1–P4 COMPLETE / OWNED READER + SYNTHETIC QUOTA VERIFIED — 2026-11-20**
>
> 実行契約は [README.md](README.md)。利用者の実装開始指示に従い、購入済み位置調査から開始。

## 現在地

| Phase | 状態 | 根拠・次の条件 |
|---|---|---|
| P0 計画・契約 | 完了 | 合意済み仕様と購入済み限定の検証契約を文書化し、production変更前に上位仕様の限定例外を計画同期 |
| P1 購入済み位置調査 | 確認済み | 指定作品で3/291・4/291への再入場復元と前後操作を確認。frame/出力の限界は下記 |
| P2 永続化 | 実装・targeted確認済み | Catalog namespace、取得UUID、画像hash/group検証、参照削除、revision再検証、継続不能の無効化 |
| P3 再開・590秒 | 実装・targeted/owned確認済み | 保存済み境界への有界補正と描き直し、単一期限、専用Page close。local browser 6 casesとowned実機 |
| P4 Batch/GUI・完成 | 完了（下記検証範囲） | 途中優先、GUI fingerprint/表示、local完了再試行、owned canvas全巻E2Eを確認。全9052 nodeを網羅し9051 PASS／既知設定不一致1 FAIL、skip 0。docs/note同期済み |

## 採用済みの判断

- 通常BookWalker quota実行で再開情報を解決する。専用コマンド・run-id入力は設けない。
- 途中巻を、選択／除外／取得可否の条件を守ったうえでquota仮割り当て前に優先する。
- 再開ファイル削除はその巻の途中取得の不採用。次回は別directoryで先頭から取得する。
  quota履歴、過去の途中出力、completed Itemの扱いは変えない。
- 最終保存済み表示と次の未保存表示のどちらへの復元も考慮する。
  具体的な位置照合・補正と描画安定の根拠はP1で得る。
- 時間はまる読みボタン押下直前から専用readerタブを閉じるまで。
  590秒で終了させ、580秒等の別段階は追加しない。ZIP化・Catalog更新はclose後に行う。
- 毎表示単位のcheckpointを正本にし、例外的に継続不能な取得は理由を残して不採用にする。
  次の通常実行で取り直し、同じ実行内のquota再入場はしない。
- 新しい利用者向け「ZIP化待ち」statusは追加しない。
  終端確認済みを内部に記録し、ローカル完了処理はreaderなしで再試行できるようにする。
- 本番の対象はquotaだけ。owned/directの短縮timer検証はtest-only driverから
  同じproduction部品を使い、権利分類や本番strict entryを偽装しない。

## 証拠の現在地と未解決事項

- 開始時のcode/docsはresume未実装だった。現在はBookWalker通常quota Batchだけ限定対応し、
  一般の非空出力拒否とfresh/normal Home巻き戻しは維持する。
- 計画前の2026-11-18の確認は商品ページまで。購入済み入口の条件が成立せず、
  reader起動・ページ移動・quota利用は実施していない。位置復元成功の証拠ではない。
  P0文書作成時はChrome/CDPへ接続していない。その後のP1/P3/P4のowned検証は下記の通り。
- 過去のBookWalker noteのowned capture／Home検証も、本件のresume実機確認の代用にしない。
- 指定作品のlive購入済み入口、再入場位置、前後操作はP1で確認済み。
  counter先行・遅延paintとcounterが2ずつ進むspreadは人工browserで検証する。
  他作品・異なるviewer設定・8操作を超える復元・single-position readerの一般化はしない。
- P2/P3の更新境界と障害分類は下記。新Catalog schemaや新公開Item statusは追加していない。
- 上位仕様との同期先: SPEC §17–19、ARCHITECTUREのRunner/Output/Safety、
  DISCOVERY_AND_BATCH §10.4とPlanner/Executor契約、DECISIONS D-009/D-031に関係する判断。
  shared deadline / metrics契約を変更する場合はaccess-control仕様も同期する。
- 実quotaのclick、実残時間、サーバー失効時の挙動は本計画ではlive未検証のままとする。
  購入済みreaderとsynthetic quotaテストの結果を、実quota E2E成功と一般化しない。

## P1の観測と設計判断

- 購入済み候補は利用者指定CID `2532de3b-1769-4210-ab6e-2952e4ecbe08`。
  strict directが成立した後だけreaderへ入り、初期1/291を記録した。
- 2回の通常advanceで3/291→close→商品から再入場でも3/291。
  ArrowRightで2/291、ArrowLeftで3/291、次の4/291でclose後も4/291。
  Homeなしで復元した。最後に1/291へ戻し、専用タブを閉じた。
- `.tmp/bookwalker-resume-position-20261119/report.json` がcounter/geometry/hashの証拠。
  同じcounterでも全canvas hashは一致しなかった。追加probeでもcaptureの分割・解像度・codecが変化した。
  artifactのbyte/decoded一致によるcross-session照合案は採用しない。
- 採用した位置契約: CID/総数/layoutを照合し、保存済みcounterまで最大8操作で戻す。
  既にその位置でも隣接表示を経て戻し、counterだけでなくpaintの変化と安定frame joinを確認する。
  保存画像は置換せず、次の通常go_nextから追記する。capture/source provenanceの既存proofは変更しない。
- 初期追加probeには再入場直後のcounter不一致で停止した試行もあり、成功データと混同しない。
  一時タブ集合が外部変化した試行を「全既存タブ保存成功」と一般化しない。
  最終のowned E2Eでは元のタブ数・オブジェクトを保持し、1/291へ復元した。

## 永続化・障害分類（P2/P3/P4）

- 再開参照は `catalog.sqlite.resume/bookwalker/<CID>.json`、データは `data/<取得UUID>/`。
  取得名はWindowsのpath長を抑えるため短いUUIDとし、ownershipは検証済みbindingで判断する。
- manifestは全画像SHA-256、連番、全part、capture_groupsの表示単位を持つ。
  checkpoint観測後、全画像保存とmanifestのgroup確定をawaitなしで行う。
  参照はページ一覧を持たず、progressは再構築可能。
- 各attemptのCrawlRun IDをmanifest内に関連付け、失敗履歴を成功へ書き換えない。
  正常終端を記録し、readerをcloseしてからpackage intent→ZIP/status→Catalog commit→参照解除。
  Catalog commit前は `capture-session.keep` で元画像・manifestを保持する。
- package前に画像/manifestを再検証し、package後もZIP entries/hashを照合する。
  ZIPだけ作成済みの失敗は同じ取得のintentと全画像の一致を確認して再利用する。
- Preview/planはread-only。manifest revisionも実行時とGUI fingerprintへ入れ、更新後はreplanを要求。
  途中巻はquota仮割当前に優先し、scope/selection/available等の条件は維持する。
- Coreにはsite固有の590秒上限・quota ruleを置かず、BookWalker integrationが590秒を渡す。
  所有権確認とmonotonic startはstrict control click直前。owned testの短縮値はdriver内だけで注入する。

| 状態 | 処置 |
|---|---|
| reader前の破損参照／別binding／画像欠落・hash不一致 | パスと理由を表示して停止。参照や旧データを黙って消さない |
| cleanな期限到達、保存済みgroupは整合 | Page close、`quota_time_budget`、pending維持。次のeligible attemptでresume |
| capture失敗でも確定済みgroupと出力が整合し、Pageをcloseできた | 過去groupを保全。次回は有界に境界へ合わせてから継続 |
| 既知の実行中sessionの未確定artifact／close・cancel失敗 | 理由付きで無効化し参照を解除。次の通常実行は新規取得。旧出力・quotaは保持 |
| 復元位置／CID／総数／layoutの不整合や補正上限超過 | 推測で飛ばさず停止。利用者が参照削除を選べる |
| ZIP/status作成後に失敗、またはCatalog commit失敗 | terminal記録とpackage intentを保全し、次回はChrome/reader/quotaなしでローカル完了処理 |
| Catalog成功後の参照解除失敗 | 成功runをfailedへ変更せずwarning。次回はArtifact/hashとattempt履歴を確認してcleanup |
| 同名の他者ZIP／不一致ZIP／別status | 上書き・自動採用せず停止 |

## 検証checkpoint — 2026-11-20最終同期

- 追加契約tests: `tests/unit/test_capture_resume.py` **32 passed**。
  破損/path/binding、参照削除、累計max_pages、子task cancel、click直前のclock start、
  再開優先／無効source除外、stale preview、ZIP/Catalog境界、completed後cleanup、offline CLI等。
- 最新の同file＋BookWalker Policy/Batch選択: **50 passed**。
- Core/Batch/Packaging等のaffected選択: **305 passed / 1 failed**。
  失敗は既存の長いタイトルpackaging testのWindows path長。下記の短いtempで再検証した。
- 同じaffected選択を短い専用tempで再実行し、**306 passed**。
  最終のCore/BookWalker契約選択も **93 passed**。追加test case数は32件のまま、既存caseを拡張した。
- CLI/GUI入力/workerの選択: **177 passed**。
- local browserのresume位置・counter先行paint・spread遷移: **6 passed / 62 deselected / 0 skipped**。
- 最初のfull pytest: **1179 passed / 3 failed / 0 skipped**、1264.85秒。
  GUI repairのbusy-close testとHanayumeの既存grant test2件で停止。
  Hanayumeは長いworktree配下tempで生成した既存出力名がWindows path長に達した。
- 短い専用temp `C:/Users/kensu/AppData/Local/Temp/bwr-mocm4gn_/a` で
  GUI repair module、失敗したHanayume function、Packaging moduleを再実行し **33 passed**。
  GUI repair failureの根本原因を本変更で修正したとは扱わない。
- full coverage追補完了: `.tmp/resume_coverage.py` がcollect順の境界1182件をassertし、
  既存1179 PASSと再検証対象3件、それ以降7870件を分離した。
  残りの実行結果は **7869 passed / 1 failed / 1182 deselected / 0 skipped**、3599.99秒。
  `.tmp/resume-coverage-selection.json` と結果JSONLのunionをnode IDで照合し、
  **全9052件を網羅、9051 PASS／1 FAIL、未実行0、skip 0**。
  集計証拠は `.tmp/resume-coverage-summary.json`。単一のfull実行が全件PASSしたという意味ではない。
- 残るFAILは既存 `test_distributed_crawler_yaml_resolves_piccoma_settings_without_changing_other_sites`。
  HEADと現行の `crawler.yaml` はBookWalker delay=0ms、HEADと現行testの期待は200ms。
  この不一致はCore noteにも以前から記録されている。今回の変更では設定・testとも変更しない。
- 最終 `ruff check src tests`、`git diff --check`、文書の相対リンク52件はPASS。
  独立agent reviewは実施していない。

## main取り込みcheckpoint — 2026-11-20

- 利用者のmainマージ指示に従い、実装を `8e303ef` にコミットしてから、
  分岐後のmain `da5c74c` の26コミットを取り込んだ。
- 競合は `batch/executor.py`、`batch/planner.py`、`cli.py`、`core/runner.py`、
  `site_adapters/base.py`。main側の権利・attempt observer、未確定quota保護、
  speculative grant撤回、Piccomaの候補順序維持、grant-onlyのmanifest非作成を保持した。
  resumeの位置照合・優先・timer・offline完了を併存させ、local完了ではobserverを設定しない。
- マージ後のCore/Batch/Policy/CLI/deferred-grant選択は **515 passed / 0 skipped**（128.52秒）。
  BookWalker Adapter/native capture/source/reader controls/terminal＋実browser Integrationは
  **290 passed / 0 skipped**（60.75秒）。合計 **805 passed**。
- `ruff check src tests` と `git diff --check` はPASS。別worktreeの未commit変更は変更しない。
- 上の全9052 nodeの分割検証はmain取り込み前の実装時点の記録。
  今回は競合を解消した契約とその影響範囲を再検証し、full suiteと実サイトprobeは再実行していない。
  前回の購入済み検証記録は保持し、実quotaは引き続き消費していない。

## 購入済みlive検証

- すべて上記購入済み商品へのstrict direct。通常Catalog/Watchlist/ZIPを更新しない。
  test-only driverは `owned_test` と短縮期限だけを渡し、access_mode/strategyをquotaへ偽装しない。
- **canvas E2E PASS:** `.tmp/bw-resume-live-canvas-20261119/report.json`。
  20秒で10枚を確定して `quota_time_budget` →再開して全291枚・END→Page close後にZIP化し、
  隔離Catalogでcompletedを記録。参照解除、sourceはowned、quota_started_atはNULLのまま。
  既存タブは1→1で保持し、cleanup後の読書位置は1/291。
- **native bounded resume PASS（全巻未実施）:**
  `.tmp/bw-resume-live-native-r2-20261119/report.json`。
  20秒で5枚→30秒のresumeで17枚→再び `quota_time_budget`。
  前の画像を上書きせず、両attemptで専用readerをclose。source owned／quota NULL、位置は1/291へ復元。
- 最終コードでのnative短縮再検証は `.tmp/bw-resume-live-native-r4-20261119/report.json`。
  20秒で4枚→再開して8枚、closeイベント実測は押下直前のmonotonic startから20.041秒／20.052秒。
  追加r3は計測driverのclose callback引数の誤りで中断した試行で、成功証拠には使わない。
- canvas E2Eの停止境界10/291は2-partの見開きで、再開後は12/291の次表示へ継続した。
  全291画像は152表示group。実測に1/291→2→3→4→5→7、8→10→12などの遷移があり、
  単純なcounter `+1` や画像連番だけでは再開しない設計を裏付ける。
  最終verifierでも全291 ZIP entries/hashとmanifestを照合済み:
  `.tmp/bw-resume-live-canvas-20261119/post-verification.json`。
- 初回native試行 `.tmp/bw-resume-live-20261119/report.json` は表紙の既存
  `retained capture final renderer join failed` で停止した。
  no-sessionの通常native対照 `.tmp/bw-native-baseline-20261119/report.json` は表紙1枚を保存して
  max_pages=1で予定どおり停止した。guardの緩和やrace解決は行わず、上記の再試行結果と区別する。
- 実quota live、実サーバー失効、native全巻E2E、本番590秒の実待機は未実施。
  購入済み短縮timerとsynthetic契約が本runbookの受け入れ範囲である。

## 変更ファイルとレビュー範囲

- Core: `core/resume.py`（新規）、`core/progress.py`、`core/runner.py`、`core/models.py`。
- Batch: `batch/planner.py`、`batch/executor.py`、`batch/models.py`。
- Site integration: `site_policies/base.py`、`site_policies/bookwalker.py`、
  `site_adapters/base.py`、`site_adapters/bookwalker/adapter.py`、
  `site_adapters/bookwalker/resume.py`（新規）、同README。
- CLI/GUI: `cli.py`、`management/execution.py`。GUIの専用resume操作や新Item statusは追加しない。
- Tests: `tests/unit/test_capture_resume.py`（新規32 cases）、
  `tests/integration/test_bookwalker_adapter_browser.py`（既存fileへ6 cases追加）。
  既知の設定不一致を持つ `test_runtime_settings.py`／`crawler.yaml` は変更していない。
- Authority: `docs/SPEC.md`、`ARCHITECTURE.md`、`DISCOVERY_AND_BATCH.md`、
  `DECISIONS.md`、`CODEX_IMPLEMENTATION_GUIDE.md`。
- 運用: root `README.md`、`.gitignore`、`runbooks/README.md`、本README/PROGRESS、
  `note/00_core.md`、`note/01_bookwalker.md`。
- self-reviewで、Coreへのsite名／590秒rule混入がないこと、通常経路の非空拒否とpacing、
  cumulative guards、子task cancel、正常終端→close→ZIP、ZIP全entry/hash検証、
  Catalog成功をcleanup失敗でfailedへ戻さないこと、scope/identity/revision再検証を確認した。
- BookWalker targetとSource CIDのcanonical product一致も、参照作成／再読込時に検証する。
  同名CatalogやID再利用・異なるtargetを引き継がない。
- 独立agent reviewは未実施。source-native/JPEG判定・proof gate・実quota取得操作は変更していない。

## P0 文書checkpoint — 2026-11-19

- Branch: `feat/bookwalker-resume`。
- 変更: このREADME／PROGRESS、runbooks index、Core／BookWalker noteへの未実装計画参照。
- production / test code、Catalog、Watchlist、runtime設定は変更しない。
- 検証: 相対リンク16件（runbook内とindex／noteからの参照）はすべて解決。
  UTF-8読取り、code fenceの対応、未実装表示、合意済み契約の照合、`git diff --check` はPASS。
- 未実行: pytest / browser-backed Integration / Research probe / Live / full suite / Ruff。
  文書のみの変更であり、実装とprobeは未着手のため。pytestのskip件数は実行自体がないため集計対象外。

## Phase終了時の記録項目

### P1 bounded probe contract — 2026-11-19

- 候補: 利用者指定の `https://bookwalker.jp/de2532de3b-1769-4210-ab6e-2952e4ecbe08/`。
- strict directの購入済みcontrolが一意に成立した場合のみreaderを開く。
- 専用Page最大3回の再入場、通常移動とcleanup合計最大16操作、各待機は既存上限内。
  最初のactual位置を記録し、調査後に同じ位置へ有界に戻して専用タブを閉じる。
- 保存相当の安定位置、advance後のclose、前後1回の移動、再入場時のCID/counter/frameを観測。
  このprobeでは画像・ZIPは保存せず、数値・hashのみ隔離 `.tmp/` に記録する。
- reader起動失敗でも作成Pageを閉じ、既存tabとremote Chromeを維持する。

- Phase、日付、branch/commit、変更範囲。
- 既知事実／仮説／未確認と、sanitized evidenceの場所。
- 変更ファイル、上位仕様／note同期、設計上の判断。
- 実機はowned確認、開始／終了／復元位置、専用タブcleanup、隔離Catalog／出力、driverの注入範囲。
- テスト分類ごとの結果、skip件数と理由、未実行カテゴリと理由。
- レビューの有無・指摘・対応、残課題、次Phaseのexit前提。

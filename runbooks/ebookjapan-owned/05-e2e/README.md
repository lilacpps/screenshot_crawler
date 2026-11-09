# 05 — Live E2E / 独立Tester・Reviewer / 引渡し

Status: **USER-APPROVED REPRESENTATIVE ANGEL 10 SCOPE COMPLETE / REVIEWER B0 ACCEPTED / FULL 17 CAPTURE NOT CLAIMED**. The final isolated Catalog has 1 completed Item and 16 pending. Angel 10 passed strict END and the independent 13-check C/D ZIP audit with 287/287 RAM witnesses. The other 15 Muda Items were intentionally not captured; Muda 1 remains incomplete.

## Full/Plan preflight checkpoint (2026-11-08)

In a fresh isolated environment, Full 17 and Plan 17 passed. Evidence: `output/ebookjapan_experiment/e2e/r/full-discovery-stage05-check.json` (SHA-256 `7b8ffde11bee85b21514e412eff97e8ecdf8272bf303f3408103ea66b6c2836b`). The inventory contained 26 records and 17 distinct owned Source/Items; all Items remained pending and 0 CrawlRun rows and 0 Artifact rows were created. After the ordering fix, a normal read-only CLI Plan returned 17 candidates with Angel 10 followed by Muda positions 1 through 16. Catalog SHA remained `4d839d7f34b4a695d31b68b5ba1b79afc7978e7bb656a0d74d1441682262e752`; evidence is `stage05-plan-order-20261108-implemented.json` (SHA-256 `787492261ea2adae7922360b8ea9aab10c177e8aff8b682d901f12cbc36c2cf4`). The prior `stage05-plan-order-check-20261108.json` recorded the pre-fix reverse order and is superseded. At this preflight checkpoint no page capture had yet run; the first Batch result is recorded next.

## First normal Stage 05 capture (2026-11-09)

The first ordinary owned/direct Batch for Angel 10 reached strict END at 287/287 pages. All 287 outputs were conditional C/WebP (144 frame groups: one cover plus 143 spreads), with D/A/B counts 0 and no fallback. It produced Run 1, Artifact 1 and completed the selected Item; 16 Stage 05 Items remain pending. The Reader Page closed at 1/1 and disconnected with source pins unchanged.

The 121,973,766-byte archive SHA-256 is `8dcf82d9043b7ffbc6f548ef93dbf43f8649472d506705c7b7ae6ae1fd3f3160`; its retained prepackage manifest SHA-256 is `fdd10a5f4ec2ab0a1a17445490922660da1b805cd0af3e0b3b25a643dd837815`. Strict C/D audit `output/ebookjapan_experiment/e2e/r/angel-actual-c-d-audit-v1.json` (SHA-256 `d8217da113bf14936c5402a8ba8a3456e282fa9a278ff570647672c5100a3082`) passed 13 checks, including independent 287/287 in-RAM pixel witnesses. Run evidence SHA-256: `f88d31fb76b1293f5a8a2ae4e36726238bc6e0bba9d520b51deac1e6c0912cde`. The audit establishes source ROI proof and pixel equivalence for each captured page, not original response bytes as page files or complete source paint history. Whole-source provenance remains NOT ESTABLISHED. Independent Reviewer B0 accepted the 13-check audit for this one-work run. This accepted result completes the current user-approved one-work capture scope only; the broader Full 17 capture is not claimed.

## Final scope and Muda 1 run history (2026-11-09)

The approved capture scope is one representative owned book, Angel 10. The final summary is `output/ebookjapan_experiment/e2e-validation/representative-final-audit-cfea49a7a71740b5a02a8c4ee2b33727/final-summary-v3.json` (SHA-256 `B874293BCCD05F12F9969FAB7AF6F8C4E765C0C710818795A4898EE4ABD50632`); v2 is superseded. Both series Full listings and the 17-item Plan passed. The Muda Plan contains DP1 through DP16 with exact IDs; DP1 has no official volume label, so no volume number is inferred. Final isolated Catalog SHA-256 `AD456ADA4A1BA9576C1B9B0E214A3933235AEAA8F2C48DDC03D1BF419A1D3487`: 1 completed Item, 16 pending, 1 successful Run, 3 failed Runs, 1 Artifact. The Angel zero-eligible Batch skipped the completed Item and made 0 HTTP requests, Pages, new Runs, Artifacts, or ZIPs. The accepted ZIP SHA-256 is `8dcf82d9043b7ffbc6f548ef93dbf43f8649472d506705c7b7ae6ae1fd3f3160` (121,973,766 bytes); retained prepackage manifest SHA-256 is `fdd10a5f4ec2ab0a1a17445490922660da1b805cd0af3e0b3b25a643dd837815`. Independent Reviewer B0 accepted strict END, 287/287 C/WebP pages, 144 groups, D/A/B zero, no fallback, and 287/287 in-RAM witnesses. The immediate-before prepackage manifest baseline was not recorded, so no immediate before/after equality claim is made.

Muda 1 Run 2 saved 191 C pages, then failed on an unsafe intersecting DIV. No Artifact was produced; cause remains unknown and is not linked to the earlier 320 x 49 metadata candidate or notification. Run 3 was outside approved scope due to a Reviewer stub error and entered public capture/C2 but stopped before the first saved page at unverified viewport 1904 x 985: SQL `page_count` was NULL, manifest body-image count was 0, no new ZIP/Artifact was created, and a separate 910,670-byte diagnostic screenshot exists. Its body-attempt count is unknown; do not describe it as zero body/pixel reads. It recorded 1,032 requests and 0 403/429; owned Page closed 1/1. Controlled Run 4 used an isolated Muda 1 quality wrapper and stopped before override, Core entry, navigation, source/body access, or capture because initial DPR did not match the wrapper's expected 1.5; actual DPR was not saved. It made 0 site requests, created no new output, and closed its owned Page 1/1. DPR was measured with Page.evaluate. The approved own-Page Raw CDP `Emulation.setDeviceMetricsOverride` would have preserved known DPR 1.5 at 1906 x 986, but Run 4 stopped before that override. The live override and quality path remain unverified; only local self-checks targeting native 1088 x 1600 output from a 1280 x 1792 source were exercised. These wrapper checks are not global production restrictions. Ordinary production geometry remains the observed 1906 x 986 entry viewport and three supported backing/rectangle profiles; arbitrary window geometry remains unsupported.

The other 15 Muda Items were intentionally not captured under the approved one-book scope; Muda 1 is incomplete. The accepted C result is limited source-ROI-derived output paired with exact D references, per-channel RGB delta <= 2, exact alpha/dimensions and exact lossless roundtrip. It does not prove A original-page bytes, B encoded-domain lossless reconstruction, complete paint history, or whole-source provenance. The seven prior C3 cases remain `NOT_VERIFIED` / `UNASSIGNED`; full 17-item capture is future scope and is not reported as passed.


Stage 04 context: run 4 reached END after 287 ordered D pages and produced an isolated 209,716,162-byte ZIP (SHA-256 `364623441ab91a0aa5638bf7d4260822d8534e4b3c5a9f2219eae2fd698e71ae`) with manifest SHA-256 `e8a1c37e9f709089f733f1ee8e4a44f105bffa8a41b94681e5d714b73b372c80`. Strict ZIP audit passed 11 checks; independent current-ZIP audit and Reviewer B0 were accepted. Full details are in `../PROGRESS.md`.


## 運用・安全なテスト準備

- 稼働 `catalog.sqlite`、本番 `watchlist.yaml`、既存`Books`へ書き込まない。テスト専用 `output/ebookjapan_experiment/e2e/` を新設し、独立Catalog/Watchlist/ZIP library/診断を使用。
- 権利はユーザー申告のみを根拠に保存成功としない。E2E実行時の同一ログイン済みアカウント/同一巻の公式Owned証拠が必要。
- AccessGuard、ユーザーの通常のログイン操作とMFA・challengeを尊重。403/429に回避リトライしない。ユーザーの認証情報・個人履歴・本文画像をrepositoryへコミットしない。
- 干渉しないShared Chromeで**実Browser操作は一人のoperator**。独立Testerを使う時は先行操作を完了/引き継いでから行う。

## Test A — エンジェル伝説（10巻のみ所有）

1. 新しいWatchlistで`books/all/134336/`登録。`full`で正しい全件リストとowned集合を確認。Catalogの当該`work_key`に新たに登録されるSourceは**10巻の1件のみ**。
2. Batch Planは10巻だけを候補として返す（これまで実行したstatusがcompletedならskippedとして明示）。`quota_available=None`、resource debit=0。
3. Batch `--limit 1`で、巻/ページID一致、先頭→END、現ページの保存形式・dimensions・欠落/重複・左右順、Manifest→ZIP→Artifact→completedを監査。
4. 直後の再Fullはcompleted/Archive identityを維持、再Batchでは0件の新しい実行となる。発見対象外の巻を新規Catalog登録しない。

## Test B — ムダヅモ無き改革（全16巻所有）

1. `books/all/115888/`を登録しFull。**16件がowned**、1～16巻の公式順に`display_position` / 巻metadataが正しい。
2. Batch Plan 16件を`display_position` 1～16の順で確認する。`Source.id`が逆順でも巻順の根拠にしない。まず`--limit 1`の本番経路でposition 1を確認し、次に順次16巻へ広げる。異なる読書レイアウトがあればclass単位のViewer・source-native gateを再評価。
3. すべての巻で`END`、正しいZIP件数、Manifest imagesの実ファイル/format/hash、ページ順・欠損/重複/本文の混入、Catalog completedとArtifact locatorを照合。
4. 失敗・権利・表示構造変更時は当該itemが未完了/診断保持になり、勝手に次巻購入や危険な改変をしない。**16完了でないなら「全巻E2E PASS」と報告しない**。

## Test C — 再Discoveryと安全性

- 1回目full→2回目fullでSource id、completedと既存ZIPを維持。
- 追加購入を模したoffline fixtureで未購入→ownedに変わった新しい巻のみpending追加、以前のSource順序/IDを破壊しない。
- 逆にowned表示が消えたfixtureでは既存Sourceの`available=False`、新規Batch対象外、既存ZIP/Artifact/履歴を温存。
- ログアウト・Viewer entitlement切れ・別巻redirect・不完全一覧・バッジ遅延・unknownは、0件成功や全巻unavailableの誤確定にならない。負例の実サイト操作が危険な場合はbrowser fixtureで検証し、live未実施と明示。
- 無料・試読・レンタル・未購入が対象に混入しない。Quota/grant-only/決済関連操作=0を確認。

## Test D — archive_order / 最終renumber

1. offlineの同一`work_key`に他サイトkeyとebookjapan keyを登録し、双方に`archive_order=1/2`を設定。
2. 取得担当Sourceだけで通し採番され、巻番号・表示順・ZIP prefixの違いが意図通りであることを検証。
3. 追加購入によるZIP名のdrift warningと、`scripts/renumber_archives.py`の`--dry-run`（実引数再確認）で新旧名/衝突/sidecar/Artifactを比較。**実アーカイブへのapplyは行わない**。実リネームはユーザーの後工程。

## Test E — 原画像の最終監査（重要）

各巻の `capture_class`、native候補数、fallback理由をrun manifestまたはsanitized diagnosticsで取得し、独立Testerが代表ページ（最初・中間・最後、表紙/見開き、異なる作品/レイアウト）を確認。成功は作品・レイアウト・ページ単位の証明範囲までとする。

| 問い | 検査 |
| --- | --- |
| A 元bytesを保存できたか | sourceと同一バイトhash・元format/size、対象巻/pageとのprovenance |
| B lossless再構成は真か | 実tile geometry、符号化の無劣化条件、デコードpixelと再描画照合 |
| C source pixels保存か | capture前元画素、transform replay、lossless roundtrip、表示画面との一致 |
| D renderedのみか | 出力元、元解像度と実出力解像度の違い、A/B/Cを採用できなかった理由 |
| 未証明の限界 | 使ったProbeの実際の範囲、未試行経路、今後の再Probe条件 |

**高品質画像については、原画像byte保存率、source-derived保存率、rendered fallback率を可能な限り巻ごとに出す。** 何枚かでA成功しただけで全巻A成功としない。A/B/Cがいずれも無理なら、その実測理由とDの品質/制限を別節で明示する。

## Gate / 完了・報告基準

- 対象の2作品で完全なDiscoveryと実際のCrawl/ZIP/Library/CatalogのE2Eが終了したこと。
- Browser E2E、必要なunit/integration、`ruff`と`git diff --check`の結果を記録。shared変更が大きければ`docs/TEST_STRATEGY.md`に従ってfull suiteも実施。未実行理由・skipped件数を明記。
- **Reviewer `BLOCKING 0` + 独立Tester PASS**。fail-closed状態や未検証はPASSとして扱わない。
- site README、`note/15_ebookjapan.md`（番号確認）、Runbook PROGRESSを現行実装と一致させる。
- 最終報告は、画像に関して「原画像採用方法／採用できなかった具体理由／fallbackページ数」を独立項目とする。既存ZIPのrenameは実行せず、ユーザーが後で行える手順を記載。

## 失敗した場合

`PARTIAL / BLOCKED`で保存し、どの巻・ページ・権利/画像経路/END/利用環境が障害だったか、再現に必要な最小sanitized証拠を残す。未完成なのに`completed`やE2E成功と報告しない。外部ログイン等がないならそのblockerをユーザーへ具体的に報告する。

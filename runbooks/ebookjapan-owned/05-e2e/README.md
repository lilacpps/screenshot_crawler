# 05 — Live E2E / 独立Tester・Reviewer / 引渡し

Status: **NOT STARTED**。開始条件: Stages 00〜04が各Acceptance/Reviewを満たし、現在の実装と`note`が同期している。

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
2. Batch Plan 16件。まず`--limit 1`の本番経路で1巻を確認し、次に順次16巻へ広げる。異なる読書レイアウトがあればclass単位のViewer・source-native gateを再評価。
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

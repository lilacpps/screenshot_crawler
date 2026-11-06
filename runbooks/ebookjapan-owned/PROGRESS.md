# ebookjapan 購入済み限定 Site Adapter — Progress

最終更新: 2026-11-06
Status: **PLANNED / NO IMPLEMENTATION / NO LIVE E2E**

## 確定した要求（ユーザー指定）

- Watchlist作品URL `/books/all/<series-id>/` から`full`で購入済み巻だけを登録。quota/free/incremental/discovery_scopeは不要。
- 作品内の巻は左から右、上から下へ2冊ずつ並ぶ現在の表示を観測。実装ではsort方向・DOM/視覚順と全件位置をサイト実測で検証する。
- エンジェル伝説 `134336`: 10巻のみ購入済み想定。
- ムダヅモ無き改革 `115888`: 全16巻購入済み想定。
- 他サイトとの`archive_order`は維持。ZIP名は後工程で手動renumberする方針。
- **原画像をできるだけ取る。簡単に描画PNGへ諦めず、A→B→Cを実証し、不成立の具体的理由を後で報告する**。

## 現時点で確かめたこと

**Repository code inspected (2026-11-06)**

- `src/screenshot_crawler/discovery/models.py` の`DiscoveredSource.access_mode` はownedを格納でき、`global_display_position` と`CompleteListingInventory`がある。
- `src/screenshot_crawler/site_policies/base.py` のPolicyは`direct`とquota無しを表現できる。`site_policies/bookwalker.py`にもowned→direct実装例がある。
- `src/screenshot_crawler/discovery/service.py` のFullは前回Sourceを`mark_sources_unavailable_except`で更新する。中途半端な列挙の誤成功が最大リスク。
- `src/screenshot_crawler/archive_order.py`、`scripts/renumber_archives.py` は今回のユーザー方針でそのまま使う対象。
- `src/screenshot_crawler/cli.py` に登録すべきAdapter/Discovery/Policy Registryがある。
- 公式説明 `https://ebookjapan.yahoo.co.jp/info/viewer-instruction/` はPC見開き/頁数表示/スライダー/画面端操作、`https://ebookjapan.yahoo.co.jp/info/bookshelf-instruction/` は本棚の巻順切替を説明。ただし認証済み`/books/all/`のownership DOMの根拠にはならない。

**未検証 / UNKNOWN**

- 購入済みHTML/カード内セレクタ、冊数、全巻総数、正規Source巻ID/URL、表示順、ログイン証拠。
- 実際のowned Viewer画像形式・元画像response・canvas draw・暗号化/タイル処理・source-native可能性。
- 先頭復帰、見開きの頁単位対応、END、Batch実行・画像完全性。
- 実サイトのサインイン済みBrowser Session、2作品の所持冊数を機械的に実確認した事実は**ない**。
- ソースコード・Unit Tests・実サイトの変更は**まだ行っていない**。

## Stage checkpoints

| Stage | 状態 | 証拠 / blocker | Next |
| --- | --- | --- | --- |
| [00 Site Probe](00-site-probe/README.md) | NOT STARTED | 所有DOM/Reader/画像source未確認 | ログイン済み共有Chromeで2作品に対する有界Probe |
| [01 Full Discovery](01-discovery/README.md) | NOT STARTED | card ID/owned証拠が必要 | 全カードをbufferしownedのみyield |
| [02 Viewer baseline](02-viewer-baseline/README.md) | NOT STARTED | 同一巻のowned Viewerを確認する必要あり | ページ/見開き/先頭復帰/END |
| [03 Source-native](03-source-native-capture/README.md) | NOT STARTED | A/B/Cの実描画証拠なし | 元bytes→無劣化再構成→source pixelを独立検証 |
| [04 Batch/GUI](04-batch-integration/README.md) | NOT STARTED | P01–P03結果を待つ | owned-only direct policy/registry |
| [05 E2E](05-e2e/README.md) | NOT STARTED | 実コード未実装 | 1冊/16冊＋再Full・rename別工程 |

## このファイルの更新方法（Codex）

各Stageで以下を追記し、先頭の`Status`とStage表を**現在の真実**へ更新する。

1. 実行日時/commit/環境/対象作品・巻、実サイトなら匿名化した採用ID。
2. `OBSERVED`、`INFERRED`、`UNKNOWN`、不成立/ブロックを分け、口頭の仮説を実観測へ昇格させない。
3. 出力/診断のignoredパス、実際に呼んだ最小再現手順、権利・AccessGuardの状況（秘密/署名付きURL/画像内容を含めない）。
4. 取得画像のClass A/B/C/D・テストした候補・実測寸法・pixel/byte一致・採用しない理由。**「試していない」は“不可能”と書かない**。
5. Unit/Integration/Live/E2E/Reviewer/Testerの実行数と結果、skip理由、BLOCKING対応、残る変更。
6. 次Stageを始められる根拠、User確認や外部認証が必要な場合のblocker。

原画像の検討に重要な否定的証拠が現れたら`03-source-native-capture/README.md`のA/B/C観測項目を具体化する。ただし、上位authorityを無断変更しない。研究ログは`PROGRESS.md`の要点＋ignored evidenceに残し、Runbookを成功済み仕様に書き換えない。

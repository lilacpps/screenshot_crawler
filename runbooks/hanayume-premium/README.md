# はなゆめ＋ すぐ無料チケット

2026-11-21。既存AdapterのPremium拡張。上位authorityと
`note/10_hanayume.md` を現行契約とする。実装ブランチ:
`feat/hanayume-premium-ticket`。元からある未commit変更は保持する。

## 実行契約と手順

1. 読み取り調査: Watchlist/Catalogの作品・話ID、共有CDPの実UI、
   ガチャ入口/結果、アカウント残数、確認ダイアログ、native grantを確認。
2. 有界Probe: ガチャは最大1回。チケットは合計5枚以内、まず1枚だけ。
   不明なクリックは再実行しない。コイン、購入、シェア、Work Ticketを使わない。
3. 実装: Premiumだけを作品単位resolverへ接続し、最初の残数Nで候補を絞る。
   残数0でpass全体終了。不明な残数のために別のquota話を探し回らない。
   各候補のexact identity、1枚/15日間、二段階UI、コイン0の単発checkout、
   残数1減少とnative grantを確認。同じPageからcapture/END/ZIPを継続。
4. 検証: Unit → 人工ブラウザ → 隔離Catalog/Watchlistでgrant-only 1話と
   normal 1話 → ZIP監査 → 回帰テスト。0枚/最後の1枚は人工fixtureで検証し、
   実チケットを使い切って試さない。

## 実測結果

- ガチャ: UIクリック1回、native `gachaTimes 0→1`、1枚当選の結果表示。
  シェア/再挑戦なし。残数増加の独立帰属までは証明していない。
- 最初の「すぐ無料」は消費せず、`1枚 / 15日間 / レンタルする` を表示する。
  確認ボタンが実際のcheckout。正確なPOSTは対象話1件、`amount=0,ticketCount=1`。
- Probe `9d5e222206beb`: 確認クリック1回、15日間のnative `purchased` grantとViewer。
- 本番resolver: 高嶺と花の286 quota候補を、残数13件に絞った。候補の総当たりなし。
- 本番grant-only `6e0cbd2f259d4`: 1枚消費、native期限保存、Item pending、Artifact 0。
- 本番normal `39315af210304`: 再計画285候補を残数12件に絞り1話だけ実行。
  1枚消費、native期限保存、END、Item completed、Artifact 1。
- ZIPは6個の異なる960×1508 WebP。全ファイルをdecodeし、先頭/中間/末尾を目視。
- 既存Work Ticket時刻は不変、Premium resource-state行なし。
- **消費3枚、残数14→13→12→11。上限5枚に対して追加消費は停止。**

隔離した証拠/DB/Watchlist/output: `.tmp/hy-premium/`。
通常のCatalogとWatchlistへの書き込みは行っていない。Cookie/storage state、
認証情報、作品画像、実サイト全文を永続fixture/このrunbookへ保存しない。

## 変更範囲

- `site_adapters/hanayume/premium_access.py`、`adapter.py`、README。
- `site_policies/hanayume.py`。
- `site_policies/base.py` のresource別expiry hook、`batch/executor.py` の2呼出箇所。
  defaultは既存hookへ委譲。Premiumはnative expiryのみ、Work Ticketは72時間。
- `tests/integration/test_hanayume_premium_browser.py`。
- 既存Unit: `test_hanayume_policy.py`、`test_comicdays_batch.py`、
  `test_batch_executor.py`、`test_cli.py`。
- `docs/ARCHITECTURE.md`、`DISCOVERY_AND_BATCH.md`、
  `ACCESS_CONTROL_AND_PACING.md`、`ACCESS_CONTROL_AND_PACING_PLAN.md`。
- `note/00_core.md`、`note/10_hanayume.md`。

## 検証状況

- 変更直結/影響Unit: **417 passed**、0 skipped。
- 新Premium＋既存Hanayume Adapter＋Comic DAYS Work/Premium Integration:
  **246 passed**、0 skipped（最後のガード補強前のスナップショット）。
- 残数確認にも既存誤遷移ガードを適用した後の対象確認: **142 passed**。
- checkoutのboolean/wrong-episode/透明control拒否とPremium診断を含む最終対象確認:
  **168 passed**、0 skipped。
- `ruff check src tests`、変更対象の`git diff --check`: PASS。
- フルpytest: **10,011件実行、初回10,003 passed / 8 failed / 0 skipped**。
  ファイル単位の4分割、専用basetemp/cache/JUnit出力で実行した。
  長いWindowsテスト出力パスで失敗した5件（既存Hanayume Work Ticket 4件、
  長い題名のpackaging 1件）は、OS一時領域の短い専用パスで全件PASS。
  修復GUIのworker待機タイムアウト1件は、単独再実行でPASS。変更前HEADと
  現行コードの隔離実行もPASSしたが、最初のタイムアウト原因は未確定。
  **再実行後の未解決は既存ユーザー設定差異2件**。変更前からの `crawler.yaml`
  はHanayume Discovery 10000ms、Magapoke page-turn 1500ms / candidate 6000ms。
  配布値5000ms / 1000ms / 3000msを期待する2テストと一致しない。
  `git show HEAD:crawler.yaml` を隔離して読み込んだ同じ2チェックはPASS。
  今回の作業ではユーザー設定や該当テストを変更していない。
  分割計画・JUnit・集計は `.tmp/hy-premium/full-plan.json`、`full-final-*`、
  `validation-summary.json`。先行した単一processの途中結果は合計に含めない。
  最後の診断/透明control補強と追加1ケースは別途最終対象168件で確認した。

FullにはIntegration 3696 / Unit 6144 / Research 171件を含む。最後に追加した
透明controlケースは上記Fullの収集後であり、対象再実行で検証している。
既存stockテストの4件だけを選ぶ確認は4 passed / 30 deselected / 0 skipped
（意図したnode選択）。Real-siteは上記の有界範囲のみで、CI依存を追加していない。

未確認: Production未使用ガチャ/作品紹介closeの独立live、実残数0と最後の1枚、
全Watchlist作品へのlive適用。ガチャは1日1回、残数を使い切る検証は消費上限を
超えるため、対応する人工ブラウザテストを使用する。独立agent reviewは実施していない。

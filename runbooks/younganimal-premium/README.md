# Younganimal Premium extension

2026-11-21。既存Younganimal Adapterへはなゆめ型Premium処理を追加する。
上位authorityを優先する。ブランチ: `feat/younganimal-premium-ticket`。
既存の未commit変更を保持し、共通Batch/Coreと既存はなゆめの実装は変更しない。

## Phase contract

1. Read-only: Watchlist対象・残数・認証・entry/gacha UIと自然なAPI応答を照合。
2. Implementation/fixtures: サイト内Policy/stock/gacha/entryのみ追加。
   Work Ticketの認証・誤遷移防止・消費確定とViewer/captureを維持する。
3. Evidence gate: 未確認のpost-consumption native shapeは有界Probeで確認し、
   違えば本番の受け入れ条件を推測せず修正する。ガチャは一度だけ。
4. Synthetic/affected tests → dedicated Catalog/Watchlistでgrant-only/normal
   → END/ZIP・source/Item/resource-state監査 → note/README/spec同期。

実チケットは**最大3枚**。まずgrant-only/normal各1枚を目標とし、消費後shapeの
追加Probeが必要なら1枚のみ。消費不明時にクリックを繰り返さない。コイン、
有料購入、Work Ticketへのfallback、公開シェア、ガチャ再挑戦を行わない。
実残数0/最後の1枚は人工fixtureで検証し、在庫を使い切らない。
実験ファイル/DB/Watchlist/outputは `.tmp/ya-premium/` に隔離する。

## Observed before any consumption

Younganimalの実表示はユーザーの呼称「どこでもチケット」に対し、現在の画面では
**すぐ無料チケット** / **すぐ無料ガチャ**。内部resourceは `premium_ticket`。
`/api/userPoint` は `paidCoin=0,bonusValue=18`。
あそびあそばせ `61580be25d2c1` のquota話 `d561e8b80803b` は正のWork Ticket
回復残時間、exact `waitAndFree/hasAccess=false/isDisableBonus=false`、timer省略。
`ifRead` は「『すぐ無料』で読む1枚」、walletはcoin 0/ticket 18。
非表示の確認dialogには `rentConf`、1枚、15日間が存在する。
Gacha GETは `canRollGacha=true,gachaTimes=0`、`gachaExecBtn.mode-user` を確認。
ここまでは全mutating requestを拒否し、ガチャ/チケット操作はゼロ。

## Implementation boundary

Younganimal専用 `premium_access.py` をはなゆめの検証済み経路から移植する。
ホスト・認証・aggregate conflict・既存route guardとの接続をサイト内で保持。
正の認証、exact currentの3 IDs、bounded body/request/time、live残数とコインを検証。
既存Work Ticketの `waitAndFree` 専用の消費確認をPremiumへ緩めない。
Premiumの `purchased` と15-day timerは下記の実消費で確認済み。
残数NでCatalog先頭N件のみ選び、0でpass終了、不明なら停止。quota話の総当たりなし。
準備のhome/gachaとselected-episode route guardの適用区間を分ける。

## Completed verification

Status: IMPLEMENTED / TARGETED VERIFIED / BOUNDED LIVE VERIFIED.

実装ファイル:

- `src/screenshot_crawler/site_adapters/younganimal/premium_access.py` (new)
- `src/screenshot_crawler/site_adapters/younganimal/adapter.py`
- `src/screenshot_crawler/site_policies/younganimal.py`
- `tests/integration/test_younganimal_premium_browser.py` (new)
- `tests/unit/test_younganimal_policy.py`, `test_cli.py`,
  `test_comicdays_batch.py`, `test_batch_executor.py` の既存contract拡張
- `note/11_younganimal.md`, site README、shared docsと `note/00_core.md` の仕様同期

shared production codeの追加変更はない。既存の未commit変更は保持する。
トップ宣伝の実selectorは `dialog.mode-campaign[open]` 内の `popClose`。
アカウントhydrationより遅れて出る場合もscoped locator handlerで一度閉じる。
ガチャ使用後もhomeリンクは残る実例があり、native used stateならクリックせず続行。
初回の導線調査で停止した試行はcheckout/gacha POSTともゼロ。

2026-11-21 あそびあそばせ:

- ガチャPOST **1回だけ**、native result0 / UIはずれ。取得0枚、再抽選・シェアなし。
  数字0のみを想定していた結果確認は初回にfail-closedで停止した。観測した
  はずれ表示へ修正し、fixtureで通過確認。修正後に2回目の実spinは行わない。
- Source34829 / `2daff889b6c82`: grant-only、18 ->17枚、約15日間、Item pending、Artifact0。
- Source34828 / `8cf938c20849d`: normal、17 ->16枚、約15日間、14ページEND/ZIP、Artifact1。
- 全14 WebPをdecode、960x1364・各hash unique。先頭/中間/最終の目視確認済み。
- Work Ticket resource stateは通常Catalogのread-only snapshotと同一。
  Premium resource stateの追加なし。**消費は合計2枚、残数16枚で検証終了**。
- Full/Incremental各154既知行、error/warningなし。両grantはpaid rentalとしてactive。
  既存の表示時間parserがexpiryを約2時間保守的に短縮し、quota_started_atは保持。

証拠（git対象外、認証情報を記録しない）:

- `.tmp/ya-premium/live/gacha-attempt.json`, `ticket-attempts.json`
- `.tmp/ya-premium/live/grant_popup_fix.json` (一度だけのspin/native result)
- `.tmp/ya-premium/gacha-result-dom.json` (はずれのread-only DOM確認)
- `.tmp/ya-premium/live/grant_verified.json`, `normal.json`, `output-audit.json`
- `.tmp/ya-premium/live/Books/` と `sample-{1,7,14}.webp`

選択した検証は **537件pass / 0 skipped**:

- affected Unit418: policy, batch, live_access parser, CLI, BatchExecutor。
- Younganimal Premium browser48: stock9000件/zero/no-episode、二段階entry、
  auth/ID/aggregate矛盾、cost/term、debit後失敗、最後の1枚、
  popup有無/遅延、ガチャabsent/used/0/1/uncertain/no-share。
- 既存Younganimal entry/Work/direct/capture browser35。
- Hanayume Premium browser35。
- Younganimal rental-history Discovery browser1。
- `ruff check src tests`、変更対象の `git diff --check` pass。
  全workspaceでは既存の `watchlist.yaml` に末尾空白1件を検出（今回の変更外）。

最終ログ: `.tmp/ya-premium/final-unit.log`, `stock-final.log` と `stock-final-fixed.log`,
`affected-browser2.log`, `both-premium.log` (Hanayume35を含む), `discovery-tests.log`。
一部初回test実行はOS temp権限でsetup errorとなり、workspace内の専用basetempで
再実行してpass。stock fixture補強時の二重cleanup4件はtest内のcleanupを修正して再実行。
pytest cache書込warning / Python3.14 asyncio deprecationは既存環境由来。
full suiteはsite-local変更のため再実行不要と判断。Research/Probe suiteは対象helperを
変更していないため未実行。実winnerガチャ・zero/最後の残数・他作品は未検証で、
必要な境界は人工fixtureで確認。追加の実チケットは使わない。

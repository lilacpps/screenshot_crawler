# Stage 01 — Read-only URL Resolverとpilot site

> Status: COMPLETE。実装・検証記録は ../PROGRESS.md のStage 01 checkpoint。

## Objective

- GUIや既存Discoveryの副作用なしに、1入力URLから「受理」「安全変換」「ブロック」を返す小さな共通resolverを追加。
- 最初は11 siteの現在のDiscovery起点URLを既存parse helperで検証・canonicalize。別形状への確実な変換はStage 00で選んだpilot 1サイトだけ先行。
- DTO: input_url, site, discovery_url, site_work_identity（verifiedまたはNone）、title（observedまたはNone）、URL status（valid/converted/blocked）、identity/titleの独立した証拠状態、warnings/blockers、provenance/evidence。正規URLが確認できたが作品ID/titleが不明ならunknownを維持して後続の手動確認候補にする。**URLのvalidと登録readyを混同しない**。
- URL文字列のみで完結する処理と、CDP経由でサイトをread-only観測する処理を分離。共通層にsite特有のselector/routeを入れない。既存site adapterのparser/観測ロジックを再利用。新たな深い抽象化は作らない。

## Security/safety

- 公式site allowlistの厳格なhost/scheme/path/parser。恣意的な外部HTTP URLは開かない。userinfo、localhost/private、任意redirect、曖昧な工作用queryは拒否。
- 順序ある、boundedなnavigation/timeout/件数で停止。login誘導、viewer開始、ticket/grant/point/購入/特別アクセスはしない。remote Chromeは閉じない。
- **正規Discovery URLが確定できない場合**（未対応、曖昧変換、不安全URL等）はblockedで、手動確認によるbypass不可。正規URLが確定済みでもwork identityが曖昧ならnative identityをverifiedとせずunknownで返す。URL-only identityから別Workへの変換を推測しない。

## Tests / exit

- 各siteの現行起点URL: valid/invalid parser tests。pilot: input-variant→canonical target, mismatched work, redirect, unknown path, query/fragment, auth failure, timeout, cross-host and no-write。
- Browserが必要なpilotはlocal synthetic DOM/route fixtureでIntegration、Liveは限定Probeのみ。CIにreal-site依存を入れない。
- Watchlist/Catalog/ZIPへの書き込みがないことを検証。Stage 00で宣言した契約を満たしてからStage 02へ。

## Stage 00後の決定・追加受入条件（2026-11-02）

- [採用判断](../DECISIONS.md)に従う。Stage 01の実装対象は11サイトの現行Discovery起点URLの厳格な受理・正規化と、Kadocomi episode→work pilot（既存parserと確認済みsame-work ID）。可能なら読み取り専用detail metadataを取得し、readerへ移動しない。
- **作品名/IDを自動観測できない正規URL**もURL statusはvalid/converted、identity/titleはunknownとして返し、手動入力・確認が必要な状態を示す。URL未対応・危険・変換先不明はblockedのまま。native work IDと作品タイトルを捏造しない。
- identity/titleの証拠状態とURL statusは独立。Stage 01で手動確認UI、ユーザー確認の永続化、Work grouping、Watchlist/Catalogアクセス・保存機能は実装しない（Stage 02–05）。
- Tests: 全11サイトで正規URL valid とunknown identity/titleの併存、危険URL/unsupportedの手動bypass不可、Kadocomiの既存prefix・許可query・same work検証・read-only metadata、安全なredirectとno-writeを確認する。
- 終了時の報告では「起点URL受理」「別形式変換」「native work ID確定」「title取得」「完全一覧preview」を混同せずサイト別に表示する。Full listing preview対応は現行4サイトに限り、Stage 07へ拡張を後送りする。

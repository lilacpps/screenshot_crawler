# Stage 01 — Read-only URL Resolverとpilot site

> Status: NOT STARTED。Stage 00のmatrix/契約とCheckpoint承認を開始条件とする。

## Objective

- GUIや既存Discoveryの副作用なしに、1入力URLから「受理」「安全変換」「ブロック」を返す小さな共通resolverを追加。
- 最初は11 siteの現在のDiscovery起点URLを既存parse helperで検証・canonicalize。別形状への確実な変換はStage 00で選んだpilot 1サイトだけ先行。
- DTO: input_url, site, discovery_url, site_work_identity, title (known/unknown), status, warnings/blockers, provenance/evidence。site_work_identityが未確認なら同一作品確定や保存不可。入力URLと正式Discovery URLを別フィールドで保持。
- URL文字列のみで完結する処理と、CDP経由でサイトをread-only観測する処理を分離。共通層にsite特有のselector/routeを入れない。既存site adapterのparser/観測ロジックを再利用。新たな深い抽象化は作らない。

## Security/safety

- 公式site allowlistの厳格なhost/scheme/path/parser。恣意的な外部HTTP URLは開かない。userinfo、localhost/private、任意redirect、曖昧な工作用queryは拒否。
- 順序ある、boundedなnavigation/timeout/件数で停止。login誘導、viewer開始、ticket/grant/point/購入/特別アクセスはしない。remote Chromeは閉じない。
- URLが解釈可能でもwork identityが曖昧なら変換成功扱いしない。site-native identityの証拠を要求。未対応を「修正すべきURL形式」の警告で返す。

## Tests / exit

- 各siteの現行起点URL: valid/invalid parser tests。pilot: input-variant→canonical target, mismatched work, redirect, unknown path, query/fragment, auth failure, timeout, cross-host and no-write。
- Browserが必要なpilotはlocal synthetic DOM/route fixtureでIntegration、Liveは限定Probeのみ。CIにreal-site依存を入れない。
- Watchlist/Catalog/ZIPへの書き込みがないことを検証。Stage 00で宣言した契約を満たしてからStage 02へ。

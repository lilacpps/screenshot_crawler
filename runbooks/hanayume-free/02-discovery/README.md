# Phase 02 — Discovery / Catalog

Status: NOT STARTED。前提: [Phase 01](../01-site-probe/README.md)の一覧・ラベル・identity証拠。
次段階: [Viewer/Capture](../03-viewer-capture/README.md)。

## 目的
Watchlistに与えた花とゆめ＋の任意の正規1話URLから対象作品の**全話**を発見し、
complete snapshotを検証してCatalogへ反映する。
「無料」「今なら無料」をpositiveに区別して判定し、両方とも安全なfreeへ正規化する。
それ以外のアクセス種別はsite観測に基づいてquota/paid/unknown等へ保守的に分類。

## 実装範囲
- src/screenshot_crawler/site_adapters/hanayume/ のDiscovery、URL/ID parser、
  最小限のsite registration、対応Unit/Playwright browser Integration test。
- Watchlistはsite=hanayume（仮site key、既存site registry namingと整合を取って確定）。
  work_keyはuser指定のopaque value。source external_idはサイトの確実なstable identity。
- 作品タイトル/著者/ジャンル/話タイトル/公開日/全体話順はサイトから観測できるものだけ採用。
  第N話の表示番号が欠けたり重複したりしても、完全集合の**native順序**で整序する。
- full / incremental / site-native boundedが既存framework契約を満たす。
  範囲内で1から振り直さず、作品全体の表示番号を保持する。

## 契約
- Phase 01で選んだ一つのexpand方式を、boundedクリック/タイムアウト/termination checksで実装。
- 宣言話数があれば一致を検証し、行IDの欠損/重複、別作品混入、折り畳み残り、
  未完了paginate、DOM変更はDiscoveryIncompleteError相当で失敗。
- **全件のrowを一旦収集し検証した後**にrecordsをyield。途中失敗でfull既存sourceを
  unavailableにしない。incrementalでも対象外の過去rowを誤って消さない。
- 対象rowで厳密な「無料」もしくは「今なら無料」の単独positive signalが確認でき、
  相反する paid/consume/unknown マーカーがなければ access_mode=free。
  他のラベル、readable-only、既存unlock、矛盾表示をfree推定しない。
- 生ラベルと正規化結果が診断可能な形でテスト/サイトドキュメントに残る。
  既存Catalog schemaで未対応の追加フィールドが必要な場合は、schema変更前にLeadへ相談。
- completed itemや既存ArtifactをDiscoveryだけで変更しない。再Discoverでfree→nonfreeとなる
  正当な変化を反映し、Batchの対象選定に伝える。

## テストとレビュー
- Unit: canonical host/URL/ID、作品scope、label分類（両exact free / 相反 / nonfree / unknown）、
  duplicate/missing/reordered row、分割話、全体順序、bounded scope境界。
- Browser Integration: 「もっと見る」または範囲展開の増分DOM、実際の完全終了signal、
  transient loader、途中失敗は全体失敗、full/incremental、既知item状態を保全。
- Live: seedの対象作品全件数/最古/最新、両無料ラベルが存在すれば各1件の正しいCatalog分類、
  full→incremental、boundedの全体順序、サイト変更時の扱いを検証。
- Reviewerはラベルの誤判定・不完全Discovery・範囲内番号誤り・item欠落を最優先で確認。
  BLOCKING 0になるまで先へ進めない。

## Exit
実装diff、actual test selection/results/skips、live観測/未確認、Review、現在のCatalog出力を
PROGRESS.mdへ記録。site README / noteは**実装済み契約のみ**を同期。


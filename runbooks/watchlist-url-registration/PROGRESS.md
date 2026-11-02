# Watchlist URL Registration — Progress

> Status: Stage 01 COMPLETE（2026-11-02）/ Stage 02 next。
> Stage 01–05は連続実装を承認済み。Stage 06–07は対象外。
> Runbook: [README.md](README.md)

| Stage | Status | Exit evidence / next action |
|---|---|---|
| 00 Current contract audit | COMPLETE (static audit) | [設計・証拠](00-contract/RESEARCH.md): 11site URL/title/変換matrix、Resolver hook、Work draft/atomic save/Full境界、Kadocomi pilotとStage 01ファイル/testを確定。Liveは全site未検証 |
| 01 URL resolver + pilot | COMPLETE | 168 new + 653 affected passed; independent review PASS |
| 02 Registration draft + naming | NOT STARTED | ローマ字候補、同一性・重複、Work/grouping、pure tests |
| 03 Batch registration GUI | NOT STARTED | URL貼付、解析進捗、修正、draft保持、GUI tests |
| 04 Scope editor draft integration | NOT STARTED | work-scoped 編集結果を未保存で返す、stale/overlap tests |
| 05 Atomic save and E2E | NOT STARTED | CAS/lock、selected-set atomic、Full confirmation、E2E |
| 06 Site URL/metadata coverage | NOT STARTED | サイト別URL変換と非消費metadata拡張 |
| 07 Listing preview coverage | NOT STARTED | 既存4サイト先行、残り7サイトを別Stageで段階拡張 |

## Stage 00 checkpoint — 2026-11-02 JST

- Branch `main`; HEAD `faa4677a3f20e0f0b818c81857e33866a5ab1af5`。
- 開始時差分: `crawler.yaml`, `watchlist.yaml` modified、`.None.job.lock`, `.catalog.sqlite.job.lock`, `.watchlist.yaml.job.lock`, `debug.log` untracked。既存差分を保持し、運用データ/lock/profileへ操作なし。
- 成果物: `00-contract/RESEARCH.md`、`00-contract/README.md`、本ファイルのみ変更。current-state noteは現行仕様/動作変更がない監査のため更新不要。実装Stageで共通/site noteを同期する。
- 照合: AGENTS.md順のauthority、GUI_README、関連notes、11site Discovery parser/metadata/preview実装と既存Unit/Integration期待値、WatchlistService/WorkDraft/WorkEditor/MainWindowの保存→Full signal。
- 設計: 共通Resolverにsite URL/selector分岐を置かずDiscoveryAdapterの任意hookから既存parserを再利用。URL-only判定とPage metadata/完全一覧取得を分離。pilotはKadocomi episode→work（既存prefix/query検証、readerを開かない）。命名は人の確定、異site groupingも明示操作。複数Workのmember patchを1proposalへ合成し、CAS/Catalog snapshot/TTL検証後に1回のapply_edit。
- 発見: PiccomaのWatchlist起点はviewer URLで一覧URLではない。一部parserの入力検証は新入口の安全基準より緩い。Full inventoryとGUI完全一覧previewは別で、後者はMagapoke/Jump+/Zeblack/Comic DAYSのみ。ほか7siteの複数key詳細設定はblockedを継続。Zeblackの現titleはlabel由来で新登録の一次根拠に使えない。
- 検証: 静的読取と文書差分/リンク確認のみ。pytest/ruff/Integration/Research/full suite未実行（code/test変更なし）。実行0・skip 0（runなし）。漫画サイトのLive/CDP未実施。辞書候補の公式公開ドキュメントだけ参照し依存は追加していない。
- 次Stage: Stage 01の設計上の開始条件は成立、阻害BLOCKERなし。ただし今回は開始しない。実装時はfeature branch/差分を再確認し、11site入口検証とKadocomi限定pilotのtargeted/affected/local browser testsを実行する。実サイト未確認を成功扱いせず、7site preview・metadata非消費経路・辞書採用の未解決境界を後続へ引き継ぐ。

## Change discipline

- 各Stage開始時に現在のHEAD、作業branch、未commit変更、他作業とのmain_window.py競合を確認。
- Stage 00はread-only監査を原則とし、成果物は本RunbookとPROGRESSの証拠更新のみ。production codeを書かず次Stageへ自動進行しない。
- 各Stage終了時に、証拠（読み取った関数/関連テスト/fixture/現行site挙動）、判定した仮定、未解決・BLOCKER、次Stageに進んでよい根拠を追記。
- 旧Stageの結果を未検証で COMPLETE にしない。サイト実観測なしなら「未検証」と記す。
- 通常運用のwatchlist.yaml、catalog.sqlite、Books/ZIP、Cookie、quotaデータは変更しない。検証は隔離された一時データのみ。

## 2026-11-02 Stage 00後の確定判断

- [DECISIONS.md](DECISIONS.md): 現行Discovery用の安全な正規URLが確定するなら、作品ID/title未取得でもunknownのままlabel/Work/keyを手動確認して登録可能。URL不正・起点不明は手動確認でもブロック。保存直前の所有競合・Catalog/Watchlist照合は必須。
- 初期のread-only完全一覧preview対応はmagapoke/jumpplus/zeblack/comicdaysの4サイトだけ。7サイトの詳細設定が必要なWorkは理由付きblockedとし、後続Stage 07でサイト単位に拡張。
- Stage 01の対象は11サイトの厳格な正規URL判定、Kadocomi episode→work pilot、identity/title unknown状態の表現。手動確認と一括保存はStage 02–05。Stage 06はサイト別URL変換/metadata、Stage 07は完全一覧preview拡張。
- Stage 00の監査時点記録を改変しない。今回の更新はRunbook文書のみで、コード・テスト・運用Watchlist/Catalog/ZIP/Chromeは変更していない。

## Stage 01 checkpoint — 2026-11-02 JST

- Base: latest fetched origin/main `82e9f92`; feature/watchlist-url-registration.
  User config/Watchlist/locks/log changes preserved, not used as test data.
- Implemented immutable URL evidence, bounded pure resolver, all 11 site-owned
  canonical entry hooks, Kadocomi same-work episode-to-detail conversion and
  optional detail-only og:title observation. Native work identity stays unknown
  for episode-only Comic DAYS/Jump+/Hanayume; title unknown unless observed.
- All unsafe/unsupported URL forms stay blocked. Percent escapes are conservatively
  unsupported. Kadocomi natural document response uses Playwright route.fetch
  with max_redirects=0 to reject Location before Chromium follows it; all other
  requests are blocked. No general HTTP client, reader or acquisition action.
- Tests: 168 new Unit/artificial-browser passed; 653 affected Discovery/listing/
  Kadocomi browser passed; zero skips. Ruff src/tests and diff check passed.
  Independent Reviewer: PASS, zero blockers. Full/Research not run at this stage
  (bounded change); Live resolver not verified. HTTP-200 authentication/content
  ambiguity remains a metadata expansion concern for Stage 06, never save proof.
- Docs and core/all 11 site notes synchronized. No CLI/GUI/schema or data mutation.
  Next Stage 02 permitted by tests and review.

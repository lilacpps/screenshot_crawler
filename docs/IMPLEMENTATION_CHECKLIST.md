# Implementation Checklist

現在の実装状況を記録する。単にファイルが存在するだけでなく、テストまたは実サイト確認済みかを基準にする。

## Core contracts / I/O

- [x] 共通models / PageState / errors
- [x] SiteAdapter contract / registry
- [x] Browser lifecycle
- [x] CDP接続
- [x] Locator / canvas capture
- [x] PNG保存
- [x] SHA-256 fingerprint
- [x] unit tests

## Browser Session architecture

Browser Session migrationとshared-profile live verificationまで完了。

- [x] 共通Crawler Chrome/profile方針をdocsで確定
- [x] CDP=接続 / Playwright=操作 の責務分離をdocsで確定
- [x] Adapterがbrowser接続方式を知らない方針をdocsで確定
- [x] global endpoint + site-specific override方針をdocsで確定
- [x] `scripts/start_crawler_chrome.ps1`
- [x] 共通profile `.chrome-crawler/`
- [x] `CRAWLER_CDP_ENDPOINT`
- [x] endpoint precedence実装: CLI > site override > global > default
- [x] login / crawlを共通Browser Session helperへ統一
- [x] site-specific launcherを削除し、共通launcherを標準化
- [x] 既存CDP listenerのshared profile確認と不一致時の安全停止
- [x] BookWalker共通profile smoke test
- [x] Manga ONE共通profile smoke test

## Persistence / safety

- [x] manifest JSON
- [x] progress JSON
- [x] atomic write
- [x] basic diagnostics screenshot / HTML / metadata / error
- [x] 非空output directory拒否
- [x] 既存manifest/progressの暗黙上書き防止
- [x] manifest基準packaging
- [x] manifest外PNG混入防止
- [x] cleanup時の無関係ファイル保護
- [ ] 自動resume
- [ ] Adapter固有debug metadataのdiagnostics統合

## Runner

- [x] CONTENT
- [x] AD
- [x] LOADING
- [x] END
- [x] NEXT_CONTENT
- [x] UNKNOWN
- [x] max_pages
- [x] max_pages == actual pages の正常終了
- [x] fingerprint duplicate guard
- [x] same-content guard
- [x] bounded retry / timeout
- [x] context change detection
- [x] multiple capture targets / spread
- [x] unit tests
- [x] Playwright local integration tests

## Probe

- [x] screenshot
- [x] HTML
- [x] img metadata
- [x] canvas metadata
- [x] button candidates
- [x] background-image candidates
- [x] CLI

## BookWalker

- [x] product URL / viewer URL entry
- [x] canvas capture
- [x] spread capture
- [x] page change wait / bounded retry
- [x] final page / END確認
- [x] NEXT_CONTENT判定
- [x] output metadata / ZIP naming
- [x] CDP workflow
- [x] login handler
- [x] site README / note
- [x] live verification記録
- [x] shared `.chrome-crawler/` でlogin/crawl/session共存を確認

## Manga ONE

- [x] chapter URL parsing
- [x] image capture
- [x] right-to-left spread order
- [x] page change wait / bounded retry
- [x] final image disappearance heuristic
- [x] chapter change -> NEXT_CONTENT
- [x] output metadata / ZIP naming
- [x] CDP workflow
- [x] login handler
- [x] site README / note
- [x] live working implementation maintained
- [x] shared `.chrome-crawler/` でlogin/crawl/session共存を確認

## Maintenance

- [x] local artificial integration fixture
- [x] packaging regression tests
- [x] note同期ルール
- [ ] GitHub CI workflow
- [ ] identity優先dedupeの再検討（実サイト遷移データが揃ってから）

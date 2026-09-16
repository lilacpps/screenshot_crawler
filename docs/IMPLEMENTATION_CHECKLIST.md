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
- [ ] 自動resume（v1.1非対象）
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
- [x] CDP profile workflow
- [x] site README
- [x] live verification記録

## Manga ONE

- [x] chapter URL parsing
- [x] image capture
- [x] right-to-left spread order
- [x] page change wait / bounded retry
- [x] final image disappearance heuristic
- [x] chapter change -> NEXT_CONTENT
- [x] output metadata / ZIP naming
- [x] CDP profile workflow
- [x] site README
- [x] live working implementation maintained

## Maintenance

- [x] local artificial integration fixture
- [x] packaging regression tests
- [ ] GitHub CI workflow（必要になってから）
- [ ] identity優先dedupeの再検討（実サイト遷移データが揃ってから）

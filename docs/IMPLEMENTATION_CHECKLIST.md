# Implementation Checklist

Codexで段階実装するときの進捗管理用。

## Phase 1 — Contracts / Models
- [ ] 共通models確定
- [ ] PageState確定
- [ ] SiteAdapter ABC確定
- [ ] errors確定
- [ ] unit tests

## Phase 2 — Browser / Capture / Fingerprint
- [ ] Browser lifecycle
- [ ] Context / viewport
- [ ] Locator screenshot
- [ ] PNG保存
- [ ] SHA-256
- [ ] unit tests

## Phase 3 — Progress / Manifest / Diagnostics
- [ ] manifest JSON
- [ ] progress JSON
- [ ] atomic write
- [ ] diagnostics screenshot
- [ ] diagnostics HTML
- [ ] diagnostics metadata
- [ ] tests

## Phase 4 — Runner
- [ ] CONTENT
- [ ] AD
- [ ] LOADING
- [ ] END
- [ ] NEXT_CONTENT
- [ ] UNKNOWN
- [ ] max_pages
- [ ] same-content guard
- [ ] retry
- [ ] tests

## Phase 5 — Probe
- [ ] screenshot
- [ ] HTML
- [ ] img metadata
- [ ] canvas metadata
- [ ] button candidates
- [ ] background-image candidates
- [ ] CLI

## Phase 6 — Example Adapter / Fixture
- [ ] artificial viewer fixture
- [ ] example adapter
- [ ] normal pages
- [ ] ad transition
- [ ] end transition
- [ ] next-content transition
- [ ] integration test

## Phase 7 — First real site
- [ ] probe実行
- [ ] adapter実装
- [ ] config
- [ ] site README
- [ ] normal page確認
- [ ] 広告前後確認
- [ ] 最終ページ確認
- [ ] 次話停止確認

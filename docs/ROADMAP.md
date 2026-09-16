# Roadmap

## Completed

- Core contracts / PageState / Adapter registry
- Browser lifecycle / CDP connection
- Capture / PNG / SHA-256 fingerprint
- Manifest / progress / basic diagnostics
- Runner state machine
- max_pages / same-content / bounded retry guards
- Probe
- local Playwright integration fixtures
- BookWalker Adapter
- Manga ONE Adapter
- spread capture
- output metadata / ZIP packaging
- manifest-based packaging safety
- non-empty output directory protection
- Browser Session共通化の設計確定

## Current priority — Browser Session unification

採用済み仕様:

```text
shared Crawler Chrome/profile (.chrome-crawler/)
    ↑ CDP
Playwright Browser/Context/Page
    ↓
Core Runner
    ↓
Site Adapter
```

次の実装作業:

- `start_crawler_chrome.ps1` を追加
- 共通profile `.chrome-crawler/` を標準化
- `CRAWLER_CDP_ENDPOINT` をglobal defaultとして追加
- endpoint precedenceを `CLI > site override > global > default` に整理
- login / crawlを同じBrowser Session modelへ揃える
- site-specific launcherをdeprecated後に削除
- BookWalker/Manga ONEを共通profileでlive smoke test

Browser Session整理のために既存Adapterのcapture/navigation/END logicを変更しない。

## Current maintenance priorities

- 実サイトで動いているBookWalker / Manga ONEの挙動を回帰させない
- Adapter変更時はsite READMEとsite noteのlive observationsを確認する
- Core変更はlocal integration testsとsite-specific unit testsで固定する
- docs / noteを現在実装と同期する

## Next when needed

- diagnosticsへのAdapter固有debug metadata統合
- explicit resume機能 (`--resume`)
- CIでのunit/integration実行
- config.yamlの扱い整理
- identity/fingerprint dedupe方式の再評価

## Later

- URL batch入力
- OCR
- PDF化
- perceptual hash
- 自動Pattern候補提示
- GUI
- 複数サイト並列実行

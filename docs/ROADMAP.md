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

## Current maintenance priorities

- 実サイトで動いているBookWalker / Manga ONEの挙動を回帰させない
- Adapter変更時はsite READMEのlive observationsを確認する
- Core変更はlocal integration testsとsite-specific unit testsで固定する
- docsを現在実装と同期する

## Next when needed

- diagnosticsへのAdapter固有debug metadata統合
- explicit resume機能 (`--resume`) の設計・実装
- CIでのunit/integration実行
- config.yamlの扱い整理（実際に使うか削除するか）
- identity/fingerprint dedupe方式の再評価

## Later

必要になってから検討する。

- URL batch入力
- OCR
- PDF化
- perceptual hash
- 自動Pattern候補提示
- GUI
- 複数サイト並列実行

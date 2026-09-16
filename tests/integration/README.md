# Integration tests

Playwright + 人工ローカルviewerでCoreと一部Adapter挙動を検証します。

現在 `test_local_viewer_flows.py` で主に以下を確認します。

- CONTENT / AD / LOADING / END / NEXT_CONTENT / UNKNOWN
- spread capture
- same-content guard
- max_pages境界
- Manga ONEのimage-disappearance END heuristic
- Manga ONE chapter change

外部サイトへ依存する恒久CI fixtureは置きません。

Chromiumが利用できない環境ではintegration testがskipされるため、実行結果ではpassed / skipped件数を確認してください。

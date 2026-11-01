# Watchlist URL Registration — Progress

> Status: PLANNED（2026-11-02）。このファイルの各行は現時点で未着手。実装済みという意味ではない。
> Runbook: [README.md](README.md)

| Stage | Status | Exit evidence / next action |
|---|---|---|
| 00 Current contract audit | NOT STARTED | 現行11site parser/起点URL matrix、保存/WorkEditor/GUI境界、Stage 01仕様決定 |
| 01 URL resolver + pilot | NOT STARTED | 厳格なnormalization/parser + 1site converter + tests |
| 02 Registration draft + naming | NOT STARTED | ローマ字候補、同一性・重複、Work/grouping、pure tests |
| 03 Batch registration GUI | NOT STARTED | URL貼付、解析進捗、修正、draft保持、GUI tests |
| 04 Scope editor draft integration | NOT STARTED | work-scoped 編集結果を未保存で返す、stale/overlap tests |
| 05 Atomic save and E2E | NOT STARTED | CAS/lock、selected-set atomic、Full confirmation、E2E |
| 06 Site URL conversion coverage | NOT STARTED | サイト単位に検証・拡張、未対応明示、tests |

## Change discipline

- 各Stage開始時に現在のHEAD、作業branch、未commit変更、他作業とのmain_window.py競合を確認。
- Stage 00はread-only監査を原則とし、成果物は本RunbookとPROGRESSの証拠更新のみ。production codeを書かず次Stageへ自動進行しない。
- 各Stage終了時に、証拠（読み取った関数/関連テスト/fixture/現行site挙動）、判定した仮定、未解決・BLOCKER、次Stageに進んでよい根拠を追記。
- 旧Stageの結果を未検証で COMPLETE にしない。サイト実観測なしなら「未検証」と記す。
- 通常運用のwatchlist.yaml、catalog.sqlite、Books/ZIP、Cookie、quotaデータは変更しない。検証は隔離された一時データのみ。

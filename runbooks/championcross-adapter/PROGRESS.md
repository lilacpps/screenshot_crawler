# Champion Cross Adapter — PROGRESS

**Status:** PLANNED（2026-10-20）
**Authority:** [README.md](README.md)
**Runbook creation only:** 実装・実サイトread-only操作・チケット消費はこの時点では実行していない。

## Execution baseline

- Repository: `lilacpps/screenshot_crawler`
- Default branch: `main`
- Planned implementation branch: `feat/championcross-adapter`（着手時に最新mainから作成）
- Site key: `championcross`
- Allowed access: 無料 / 「待つと無料」`work_ticket`
- **Excluded:** 「すぐ無料チケット」、有料コイン、課金/購入/レンタル。
- **Highest-priority invariant:** quota/grant-only時はCatalogに保存された選定済みepisode URLへ直接アクセス。他話の状態探索、seriesページ訪問、候補fallbackをしない。
- **Real ticket consumption approval:** **NOT GIVEN**。対象episode URL・枚数の明示的承認があるまでは実消費禁止。

## Phase status

| Phase | Status | Evidence / Next checkpoint |
| --- | --- | --- |
| 01 Repo/live read-only差分調査 | NOT STARTED | Work/episode identity、2種チケットの分離、Viewer・ボタン構造 |
| 02 Discovery / Policy / Catalog | NOT STARTED | full/incremental、手動Grant、23h・72h境界、1work1candidate |
| 03 Viewer / Free direct E2E | NOT STARTED | 画像・END・ZIP・Catalog・独立画質監査 |
| 04 Work Ticket Entry / grant-only | NOT STARTED | 対象episode直接入場、他話状態探索0、消費確認・後続失敗記録 |
| 05 Reviewer / Tester / live E2E | NOT STARTED | 非消費E2E、実消費は別途ユーザー許可後 |

## Evidence log

着手後、日付、branch/commit SHA、対象URL（秘密を含まないもの）、観測事実、仮説、失敗の原因、Reviewer判定、Tester検証範囲、実行コマンドと結果を追記する。

## Work Ticket consumption ledger

| When (JST) | Work ID | Episode ID | Authorized? | Attempt / confirmed result | Grant expiry | Viewer/ZIP |
| --- | --- | --- | --- | --- | --- | --- |
| — | — | — | **No consumption authorized** | 0 attempted / 0 confirmed | — | — |

**注記:** 72h閲覧期限と23h作品回復は別の値。手動消費時刻を閲覧期限から逆算しない。ボタンを押したが結果不明な場合は「消費未確認・再試行禁止」を記録し、成功に数えない。

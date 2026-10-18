# Young Animal `work_ticket` — PROGRESS

**Date:** 2026-10-18
**Status:** PLANNED / NOT IMPLEMENTED。`README.md` に実装計画を記載したのみ。
**Baseline:** 実装開始時に `main` のcommit SHAを記録する。
**Execution branch:** `feat/younganimal-work-ticket`（作成前）。
**Live ticket usage in this work-ticket implementation:** **0枚**（本Runbook作成時点。この機能の新規試験での消費数）。
**Authority:** [README.md](README.md)。既存 `runbooks/younganimal-adapter/PROGRESS.md` は無料・レンタルdirect実装の履歴。

## 実装ステータス

| Phase | Status | Gate |
| --- | --- | --- |
| 01 — Repo / live probe | NOT STARTED | DOM・API・クリック前後・回復時間と閲覧期間・positive evidence |
| 02 — Discovery / SitePolicy | NOT STARTED | work quota、23h cooldown、候補安全判定、手動grant |
| 03 — Adapter entry / grant-only | NOT STARTED | one-click、same-page capture、未確認時fail-closed |
| 04 — Tests / live E2E | NOT STARTED | grant-onlyと通常Batch、SKIP・回帰・Reviewer/Tester |

## 未確定事項（推測で補完しない）

- Young Animalの「待つと無料で読む」の正確なcontrol、paidとの差、hydration・認証証拠。
- Discovery一覧だけでのwork-ticket対象episode分類の正確な根拠。従来925話の多くはunknown。
- サイト生成の消費成功/失敗を示すexact work/episode-boundの通信・DOM証拠。
- Young Animalの**話単位閲覧可能期間**。花とゆめの72時間をそのまま使わない。
- 使用済み・手動使用済みepisodeのDiscovery label/API、正確なexpires/cooldown証拠。
- 押下後のURL・Viewer1ページ目の状態・native captureへの安全な接続。

## Phase 01 実測記録（着手後に追記）

- Baseline SHA / Branch / dirty working tree保護:
- 選択した試験episode URL / work ID / account positive evidence:
- Read-only DOM/UI・API観測（秘密・signed URL除外）:
- Selectorとpaid/control区別、重複・disabled・loginの判定:
- クリック1回の前提とReviewer判断:
- 実際の消費日時 / work / episode / 観測したPOSTまたは状態遷移:
- 対象話の有効期限・手動消費表示・work回復時刻:
- 1ページ目・route・Viewer現行実装との整合:
- 追加確認が必要な未知:

## Phase 02/03 実装・検証記録

- 変更ファイル / 理由:
- SitePolicyのwork resource・work選定順・23h local SKIP:
- Discovery分類・手動grant同期・誤クリア対策:
- Adapterの1回クリック・AccessConsumptionラッチ・entry-only:
- CLI / Batch共通コード変更（ある場合は最小性と回帰）:
- Fixture/Unit/Integrationテストと失敗分析:
- Reviewer findings（BLOCKING / NON-BLOCKING）と解消:

## Phase 04 実サイトE2E・独立監査

- 隔離Catalog/Watchlist/output使用、共有CDP排他:
- Grant-only: confirmed consumption / work cooldown / source grant / Item pending / 画像0 ZIP0:
- 再実行local SKIP: site requests 0 / 次回確認時刻:
- 通常Batch: episode one-click / 同一Page first→END / ZIP CRC / Catalog complete:
- 手動消費→Discovery full・incremental→再消費なしdirect:
- Negative branches: paid/login/duplicate/mismatch/click timeout/interrupt:
- 作品一覧(main-frame `/series/`)のBatch中navigation: 0件の監査:
- 利用したticket合計・正確なwork/episode一覧（重複排除）:
- Independent Reviewer / Tester結果:
- 未完了項目・運用上の注意:

## 終了判断

本ファイルが `PLANNED` の間、機能完成・実チケット試験成功を主張しない。Phase別に実装と検証を記録し、最終受け入れ条件が全て成立した場合にのみ `COMPLETE` とする。

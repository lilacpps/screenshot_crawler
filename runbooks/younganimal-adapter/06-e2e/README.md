# Phase 06 — independent E2E, regression and handoff

Status: LOCAL TEST/ARTIFACT AUDIT PASS; LIVE E2E INCOMPLETE. Latest independent Tester: 42 passed, 0 skipped, 140 existing asyncio deprecation warnings in 9.00s; four isolated Catalogs were opened read-only and each contained one pre-created Work row with all other tables empty. No live capture, ZIP, entitlement state, or complete Catalog flow was verified.

## Current result (2026-10-11)
- Earlier independent local Tester audit: PASS; 27 passed, 0 skipped, 23 existing deprecation warnings, 4.31s across the two Younganimal test files. Latest independent audit: PASS; 42 passed, 0 skipped, 140 existing asyncio deprecation warnings, 9.00s.
- Four isolated Catalogs were opened read-only; each had one Work row created before adapter invocation and zero items, episode sources, targets, runs, artifacts, or quota states. JSON sanitation passed. The 03A retry report records one listing main-frame navigation, then a page-originated Younganimal fetch HTTP 429 (`Retry-After: 1`) and zero episode main-frame navigations/seek positions. No manual navigation or retry was issued after the stop; in-flight automatic requests are not ruled out.
- This local audit does not establish live Viewer capture, END, ZIP, entitlement, or complete Catalog synchronization. Live E2E remains incomplete because full Discovery stopped at `/6` without a response status and the later 03A attempt stopped on HTTP 429.

Tester audit report: ignored `output/younganimal_experiment/tester/final_post429_local_audit.md`.

## Objective
「無料」「待つと無料」それぞれの**実際にサポートするstate**で、
標準Discovery→Catalog→Batch Plan→Batch Run→Crawl→END→Manifest/ZIP
の完全性を独立検証。保存品質・サイト利用権・他Adapter回帰を確認する。

## Isolated execution
Shared Crawler Chrome + Playwright/CDPを使うが、通常DB/profileの未許可な変更をしない。
例:
```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m screenshot_crawler.cli watch add --watchlist output\younganimal_experiment\watchlist.yaml --key younganimal-sample --work-key younganimal-sample-work --site younganimal --url "https://younganimal.com/series/aee4fa742b0fe" --label "Younganimal sample"
.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover --key younganimal-sample --mode full --watchlist output\younganimal_experiment\watchlist.yaml --catalog output\younganimal_experiment\catalog.sqlite
.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover --key younganimal-sample --mode incremental --watchlist output\younganimal_experiment\watchlist.yaml --catalog output\younganimal_experiment\catalog.sqlite
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch plan --site younganimal --catalog output\younganimal_experiment\catalog.sqlite
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run --site younganimal --catalog output\younganimal_experiment\catalog.sqlite --output-root output\younganimal_experiment\batch --library-dir output\younganimal_experiment\library --limit 1
```

CLI引数・登録の最終形は実装者が確認。仮のURLで実行しない。
`--limit 1`はfree smoke。wait-freeの新たな状態操作はPhase 05で
実証された安全な狭い経路のみ検証し、実際の待機時間を飛ばさない。

## Independent Tester audit
- 全件Discoveryの作品ID、話ID、global position、対象範囲、重複/欠損/false free判定。
- Free/Wait candidateごとの現在の正規権利とアクセス経路、操作履歴、
  resource状態の前後差分、付随CTAクリック有無。
- Freeの代表2〜3話、可能なら別作品/初期空白/通常の2種類を確認。
  Waitがsupportedでreadyにある場合はその話を追加。
- 画像全page、first/middle/last/左右spread、元解像度、Manifest由来capture method、
  JPEG無変換かnative pixelか、WebP VP8L lossless/PNG fallback、
  source pixel照合と見た目を別々に検証。
- 完全本文のEND、広告/次話混入なし、同一ページ重複・途中脱落・誤ったENDなし。
- ZIP member/Manifest/CRC/各hashとsize、Catalog item/run/artifact、
  successful package時のみcompleted、失敗時pending。
- 403/429/challenge、retry数/AccessGuard停止、既存Hanayume/Piccoma等の関連回帰。
  shared変更があれば該当両siteのbrowser regression、広範囲ならfull suite。
- 不足した実例・実サイト未検証、消費系の未承認は**NOT VERIFIED**として記録する。

## Final gate
独立Reviewerの変更差分BLOCKING 0、Testerのlive/画像監査、
site READMEと`note/<nn>_younganimal.md`の同期。
最終報告は**無料の完成度と待つと無料の完成度を別々に**示す。
未完のfeatureを完成扱いしない。ブランチへcommitし、mainへ自動mergeしない。

# Phase 06 — independent E2E, regression and handoff

Status: NOT STARTED。Prereq: Phases 01〜05で支持された実装とReview。

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
.\.venv\Scripts\python.exe -m screenshot_crawler.cli watch add --watchlist output\younganimal_experiment\watchlist.yaml --key younganimal-sample --work-key younganimal-sample-work --site younganimal --url "<currently verified episode URL>" --label "Younganimal sample"
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

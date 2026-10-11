# Phase 06 — independent E2E, regression and handoff

Status: Attempt 9 passed final-code free Batch E2E for both live profiles. The standard target captured 16/16 native VP8L pages across 9 spreads; the top-empty target captured 44/44 across 22 spreads. Both reached END, passed ZIP/CRC and isolated Catalog checks, and preserved source fingerprints. Independent audit: `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/independent-final-audit.json`. Discovery (925 positions), Phase 03 review, and Phase 04 direct-only Batch are complete. Phase 05 wait/resource semantics remain UNKNOWN and unimplemented; the overall request to support wait-free episodes is not complete.

The historical D-only attempt remains `PASS_WITH_STATUS_PROVENANCE_LIMIT`: its completion status was restored from a measured snapshot after a later experiment overwrote the attempt status. Attempt 3 completed 16 ordered pages through a mixed capture path and passed independent artifact audit with one exact native VP8L page and 15 rendered PNG pages. These older results remain historical and are not used as the final all-native standard-target claim.

## Current result (2026-10-11)

- Final affected capture-unit plus Younganimal browser suite: `84 passed, 0 skipped`, 5 existing pytest-asyncio deprecation warnings, 133.19s. Full `ruff check src tests` passed. Full `pytest -q` was not run because changes are site-local.
- The independent attempt-9 audit confirms 16 standard-target and 44 top-empty native VP8L outputs, decoded-RGBA/byte and ZIP/CRC checks, END, isolated Catalog completion, and unchanged source fingerprints. The separate artifacts are `attempt-9/provided-free/audit.json` and `attempt-9/topempty-free/audit.json` beneath `output/younganimal_experiment/phase04_batch_e2e_20261011/`; the combined independent report is linked above.
- Attempts 7 and 8 remain historical: attempt 7 timed out before top-empty capture; attempt 8 failed closed during native verification before page save. Attempt 9 supersedes those incomplete attempts on the final code. The older attempt-6 top-empty pass used a preceding geometry rule.
- Phase 05's latest public probe measured both blank-row SVG icons visible at 24x24 with visible parents, but did not identify active icon/access semantics, authentication state, or a safe wait operation. No episode navigation, CTA, wait, or resource action occurred.

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

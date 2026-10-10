# Phase 05 — Independent live E2E / Final gate

Status: PASS / BLOCKING 0 for the logged-out exact-`無料` scope. Independent Tester completed three standard Batch runs with END, generated three verified ZIPs, pixel-checked all 122 pages and visually passed 9 first/middle/last samples. Final independent Reviewer passed with 42 fresh tests, 0 skipped, Ruff/diff, and independent SQLite/ZIP/PNG audits passing. The earlier HTTP 429 and one-page timeout attempts are historical and superseded. Authenticated non-consuming `今なら無料` remains outside scope and unverified.

## 目的
**2〜3話**を実際の標準CLIで Watchlist → Discovery → Catalog → Batch Plan →
Batch Run → Crawl → Manifest/ZIP → completed と通し、画像と状態の整合性を独立検証する。
このrunではログアウト状態で直接閲覧を確認した「無料」話から2〜3話を含める。
「今なら無料」は登録/ログインを要する表示を観測し、認証済みの非消費閲覧を確認していないためE2E対象外。
シード: https://hanayume.com/episodes/8c6f15923caa0。

## Live手順（実装後のCLI、隔離パス）
共通Crawler Chromeを既存手順で起動し、1 operatorで実施。
以下は既存のCLI形式に沿う**例**であり、site登録/作品IDがPhase 02で確定した後に使用。
PowerShellで記号を扱うためUTF-8環境を設定する。

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
New-Item -ItemType Directory -Force output\hanayume_experiment | Out-Null
.\.venv\Scripts\python.exe -m screenshot_crawler.cli watch add --watchlist output\hanayume_experiment\watchlist.yaml --key hanayume-sample --work-key hanayume-sample-work --site hanayume --url "https://hanayume.com/episodes/8c6f15923caa0" --label "Hanayume sample"
.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover --key hanayume-sample --mode full --watchlist output\hanayume_experiment\watchlist.yaml --catalog output\hanayume_experiment\catalog.sqlite
.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover --key hanayume-sample --mode incremental --watchlist output\hanayume_experiment\watchlist.yaml --catalog output\hanayume_experiment\catalog.sqlite
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch plan --site hanayume --catalog output\hanayume_experiment\catalog.sqlite
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run --site hanayume --catalog output\hanayume_experiment\catalog.sqlite --output-root output\hanayume_experiment\batch --library-dir output\hanayume_experiment\library --limit 1
```

**注意**: --limit 1 は最初の候補に対するE2E smoke。残り2〜3話はplanが示した
現在の無料候補に合わせた隔離Catalogと追加Batchで実施する。--limitを増やす前に対象候補を確認し、
本番Catalogや手作業で取得済みの保存先を流用しない。

## Tester独立監査
1. Discoveryの全件数、作品/話ID重複なし、最古/最新、全体position、
   ラベル別件数・特定例、full/incremental/bounded、非freeの除外を確認。
2. Batchの直前に正しい作品/話と現在freeの表示を再確認。課金/チケット/購入/自動ログイン操作ゼロ。
3. 各話の最初・中間・最後の画像を実Viewerと視認照合。全画像の順序、dimensions、
   page fingerprint、異常重複、欠落、黒/白化、見開き半分欠損、広告/UI/次話混入を検査。
4. Nativeならresponse/source identity、jpeg DCT復元証拠またはsource-derived RGB proof、
   WebPならlossless VP8Lとdecode round-trip、fallback理由を検証。
5. Runnerの最終本文後のENDを確認し、途中のmax_pages停止を成功扱いしない。
6. ZIP member全体・Manifestの1:1対応、CRC/hash/size、Artifact、
   completed/succeeded Run、失敗候補のpending/no Artifactを確認。
7. 既存の他サイトAdapter/Catalog/共通部の対象回帰試験、skips/未実行理由を報告。

## Final gate
- Tester結果はPASS/FAIL/NOT VERIFIEDを各観点で報告。通常のUnit成功だけではlive PASSとしない。
- 最終Reviewerが実装差分・Checker evidence・失敗修正を再確認し、BLOCKING 0。
- 「無料」と「今なら無料」の分類を独立にUnit/Integrationで検証し、後者は `unknown` のままにする。
  今なら無料の認証済み非消費Viewer確認はユーザーのno-login指示で未実施であり、Live accessはNOT VERIFIEDと報告する。
- PROGRESS.md、site README、対応noteを**実際の実装結果**に同期。
  ブランチはレビュー可能な状態で残す。mainへ自動mergeしない。

## Final Tester result (2026-10-11)

- The independent Tester reused the previously audited 296-source Discovery Catalog through a coherent SQLite backup; it did not rerun Discovery during the final Batch E2E. The harness invoked the standard `batch run --site hanayume --limit 3` CLI with transparent in-process evidence wrappers under isolated paths.
- Exactly the three logged-out exact-`無料` entries completed with `stop_reason=end`: `8c6f15923caa0` (32 pages), `9202b052ad237` (40), and `2ec9c6b024ee0` (50). Before each advance, an independent visible-canvas read in the same run was decoded as RGBA and exactly matched the adapter PNG. Three ZIPs matched Manifest member count/order/CRC/hash; the corresponding three Catalog Items completed, while the 293 `unknown` Items remained pending. The earlier failed run record was retained.
- Tester independently viewed first, middle, and last page samples for every episode (9 total); each showed only the comic body with no UI/ad, blank frame, or half-page crop. Quota resources remained unused and grant/entitlement state unchanged. Metrics: 1,189 requests; zero 403/429/5xx, challenge, CAPTCHA, or retries.
- Command: `.venv/Scripts/python.exe output/hanayume_experiment/tester/hanayume_e2e.py --live --reuse-catalog output/hanayume_experiment/tester/runs/20261010T152230Z-2794388b/catalog.sqlite`. Reports: `output/hanayume_experiment/tester/runs/20261010T153649Z-ac385393/final_report.json` and `tester_assessment.json`; ZIPs and sampled images are isolated under the same ignored run directory.
- Capture method is rendered body-canvas PNG at observed 828×1329 dimensions. It retains the rendered canvas pixels but not the original 960×1540 source resolution. The bounded 240×385 tiles reject only the tested MCU-8 DCT permutation approach. Authenticated non-consuming access for `今なら無料` remains NOT VERIFIED per the user's no-login instruction.


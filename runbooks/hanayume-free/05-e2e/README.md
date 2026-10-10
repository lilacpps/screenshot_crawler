# Phase 05 — Independent live E2E / Final gate

Status: NOT STARTED。前提: Phase 02〜04の実装Review BLOCKING 0、siteの現在の無料候補があること。

## 目的
**2〜3話**を実際の標準CLIで Watchlist → Discovery → Catalog → Batch Plan →
Batch Run → Crawl → Manifest/ZIP → completed と通し、画像と状態の整合性を独立検証する。
「無料」「今なら無料」が両方現存するときは**各ラベルから1話以上**を含める。
シード: https://hanayume.com/episodes/8c6f15923caa0 （この話の無料権利は未確認）。
不足すれば同一作品の現存無料話または別の花とゆめ＋作品に切り替え、対象と根拠を記録する。

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
- 「無料」「今なら無料」各分類を独立にUnit/Integrationで検証。
  Live候補が存在しなかったラベルはNOT VERIFIEDと残し、仮定で実サイト成功を主張しない。
- PROGRESS.md、site README、対応noteを**実際の実装結果**に同期。
  ブランチはレビュー可能な状態で残す。mainへ自動mergeしない。


# Phase 05 — Independent live E2E / Final gate

Status: PASS / BLOCKING 0 for the final logged-in standard Batch E2E within the verified scope. Four inclusive-scope candidates completed at END, producing 134/134 independently RGBA-verified original-canvas lossless-WebP pages and four verified ZIPs. Final independent review PASS / BLOCKING 0.

## 目的
**2〜3話**を実際の標準CLIで Watchlist → Discovery → Catalog → Batch Plan →
Batch Run → Crawl → Manifest/ZIP → completed と通し、画像と状態の整合性を独立検証する。
このrunでは「無料」対象に加え、現在の共有プロファイルで同作品の認証markerを確認できる場合は「今なら無料」対象を少なくとも1話含める。Viewer/Batchのfresh preflightで認証と正確な対象rowを再確認し、未確認ならunknownのまま停止する。
Do not perform login, registration, purchase, ticket, quota, or entitlement actions. If fresh authentication or the exact target row cannot be verified, keep the candidate unknown and stop before entry.
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

- Final report: `output/hanayume_experiment/tester/runs/20261010T231618Z-a02345e9/final_report.json`; audit files in the same directory include `batch_access_metrics.json`, `independent_capture_fingerprints.json`, and `independent_draw_trace.json`. Final run 20261010T231618Z-a02345e9 performed fresh standard Discovery, validated all 296 rows, applied the standard inclusive Watchlist scope, synchronized four records into a new isolated Catalog, and ran standard Batch for these four candidates. No Catalog backup was reused.
- Full-list observation contained 296 unique IDs/positions 1-296: 3 exact `無料` and 293 exact `今なら無料`. The attempt verified account markers on the canonical same-work series route; all rows were classified free for this attempt, while the standard inclusive scope selected four candidates.
- Selected episodes in execution order: `90868f4de278f` (12 body pages), `2ec9c6b024ee0` (50), `9202b052ad237` (40), and `8c6f15923caa0` (32). All four runs reached END, all four Catalog items completed, and all four ZIP artifacts are present.
- All 134 output pages are 960x1540 `source_canvas_lossless_webp` artifacts. Independent draw-time copies of the selected original canvas and deferred decoded RGBA readback matched each output exactly (134/134); every WebP is single-chunk VP8L. Rendered fallback was zero. The observed resized display canvas was 828x1329 (CSS 552x886 at DPR 1.5); the native path avoids that display resize.
- All four ZIPs passed CRC, manifest order, member count, and SHA-256 checks. Tester visual review passed 12 first/middle/final samples. Access metrics recorded 2,426 requests and zero 403/429/challenge/CAPTCHA events; CLI-reported retry count was 0. No quota resource or grant/entitlement state changed.
- Earlier 122-page rendered-PNG E2E, R5 auth/counter probes, and initial failed attempts remain historical checkpoints. The bounded auth poll follows a live probe where positive markers appeared at 150 ms; the counter transition itself was not directly measured. An ignored audit-harness slot-attribution failure was corrected and the final independent audit passed.
- Limits: this verifies decoded source-canvas pixels, not original JPEG bytes. The measured 385px tile height did not support the tested MCU-8 DCT coefficient permutation. Other native dimensions/layouts may use whole-spread rendered PNG; universal detection of a ready Viewer overlapping an entry gate remains unverified.
## Historical logged-out rendered-PNG baseline (superseded by the final logged-in E2E above)

- The independent Tester reused the previously audited 296-source Discovery Catalog through a coherent SQLite backup; it did not rerun Discovery during the final Batch E2E. The harness invoked the standard `batch run --site hanayume --limit 3` CLI with transparent in-process evidence wrappers under isolated paths.
- Exactly the three logged-out exact-`無料` entries completed with `stop_reason=end`: `8c6f15923caa0` (32 pages), `9202b052ad237` (40), and `2ec9c6b024ee0` (50). Before each advance, an independent visible-canvas read in the same run was decoded as RGBA and exactly matched the adapter PNG. Three ZIPs matched Manifest member count/order/CRC/hash; the corresponding three Catalog Items completed, while the 293 `unknown` Items remained pending. The earlier failed run record was retained.
- Tester independently viewed first, middle, and last page samples for every episode (9 total); each showed only the comic body with no UI/ad, blank frame, or half-page crop. Quota resources remained unused and grant/entitlement state unchanged. Metrics: 1,189 requests; zero 403/429/5xx, challenge, CAPTCHA, or retries.
- Command: `.venv/Scripts/python.exe output/hanayume_experiment/tester/hanayume_e2e.py --live --reuse-catalog output/hanayume_experiment/tester/runs/20261010T152230Z-2794388b/catalog.sqlite`. Reports: `output/hanayume_experiment/tester/runs/20261010T153649Z-ac385393/final_report.json` and `tester_assessment.json`; ZIPs and sampled images are isolated under the same ignored run directory.
- This historical baseline used rendered body-canvas PNG at observed 828x1329 dimensions and verified only the logged-out `無料` path. It does not establish original-canvas or authenticated `今なら無料` behavior; those were verified separately in the final E2E above.

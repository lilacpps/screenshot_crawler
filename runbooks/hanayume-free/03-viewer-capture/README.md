# Phase 03 — Free Viewer / Rendered PNG Capture

Status: Phase 03 PASS / BLOCKING 0. The final Phase 05 live Batch E2E completed all 32/40/50 body slots across the three confirmed `無料` samples with END, same-run RGBA proof for all 122 pages, and clean first/middle/last visual samples. Independent review of the center-in-viewport correction passed (163 affected tests, 0 skipped; Ruff and diff checks passed). The HTTP 429 and one-page timeout below are historical failed attempts superseded by the final E2E.
Next: no additional live Viewer run is needed for this logged-out scope. Other layouts/works and authenticated `今なら無料` access remain unverified. Stop if future access encounters 403/429/challenge; do not log in, pay, exclude the content host, weaken AccessGuard, or add retry behavior.

## 目的
現在ログアウト状態で閲覧確認済みの「無料」対象話を正規Viewerで開き、
**元画像を可能な限り無変換で保存**して本文すべてを正しい順序で終了まで取得する。
サイト側の表示方式をまだ観測していないため、Capture MethodはProbe後に決定する。

## Viewer/アクセス契約
- 実行時のcanonical URL/target external_idと対象作品・話IDを厳密に比較。
- 直接入場前に同一一覧等で対象行の現在の正確な「無料」badgeをfresh check。
  `今なら無料` はCatalog上unknownであり、このrunでは入場しない。古いCatalogのfreeやログイン状態だけでは許可しない。
- 課金/チケット/待機/解放/login操作、別話への遷移はしない。
  必要な未対応CTAが出たらfail closed。auto/direct限定、quotaを拒否。
- サイトで観測された単画面/見開き、上部Viewer、再開/巻き戻しを正しく扱う。
  body index、page-change readiness、loading、広告、END/NEXT_CONTENTを
  明示的なbounded state/signalsで判定。固定sleepだけでcaptureしない。
- 最終本文を落とさず、最終本文後は次話の有料Viewerに入る前にEND。
  spreadは片側欠損不可、読書順を守る。same-content/max_pages/timeoutを残す。

## 画像取得の決定ゲート
優先順位は docs/CAPTURE_STRATEGY.md のauthorityどおり。

A. **Original image bytes**:
  Network response等から現在表示中のページと1対1で一致する元JPEG/WebP/PNGを
  Provenanceで証明できれば、そのバイト列をそのまま保存（再エンコード禁止）。
B. **JPEGの無劣化スクランブル復元**:
  画像responseがスクランブルJPEGなら、実際のdraw map・sourceID・全tile coverage・
  orientationとMCU境界を検証。Jump+/BookWalkerのjpeglib DCT係数入替方式が
  **実geometryで適合すると証明できる場合だけ**復元JPEGを保存。
  係数/量子化table・見た目・画像内容を厳密に比較する。
C. **Source-derived pixels**:
  Bが成立しなければ、正確なdraw trace/source pixel/mutation/transform/背景を
  再現し、既知良品のrendered RGBと同一であると証明する。
  証明済みpixelをlossless WebPで保存し、encode/decode pixel round-tripを検証。
  エンコード失敗時は同じ検証済みpixelをPNGで保持。
D. **Rendered fallback**:
  Source provenance/replayが一般化できない場合は、現在のbody slotに直接対応し、
  loaded/rendered状態とreadbackを確認できるclean Canvas PNGを使う。
  Hanayumeではspread、広告、viewer chromeが混入するためUI screenshotへfallbackしない。
  Readback不可や状態不明はfail closedとする。

**Stop condition**: DCT不適合などの否定的証拠が出たら無制限に探索せず、
失敗理由を記録してC/Dで実装へ進んでよい。Dが唯一の実装可能な方式なら
品質制約（実測解像度、同一ページ照合）を文書化し、見込みのないJPEG復元を作り込まない。
ただしA/B/Cを観測・検証せず最初からDを恒久の標準にしない。

## Phase 03-B implementation checkpoint (2026-10-10; historical pre-live checkpoint, local review PASS)

- Manual Viewer registration is site-local and uses the shared CDP/Page lifecycle. Before entry it verifies the exact episode URL and unique scoped work header, then checks the exact bare same-work URL and a finite valid range set. It proceeds only if that listing contains one exact target row with `無料`; otherwise it follows observed numbered routes with exact current-range, unchanged-range-set, declared row-count, and page-local ID checks, stopping at the first target. Duplicate, conflicting, or nonfree target rows fail immediately, and the adapter exhausts ranges only when the target is absent. After opening the exact episode it checks the work and label again. Discovery remains responsible for full-work coverage/global uniqueness. `今なら無料`, a missing/duplicate/conflicting label, target/work drift, or unsupported viewer state fails closed.
- The observed desktop `mode-spread` viewer is treated as an ordered set of body candidates between known promo/info/good/last wrappers. A candidate placeholder is not content. Current body capture requires the selected wrapper to be active and `mode-loaded mode-rendered`, contain exactly one visible canvas under `.-cv-page-canvas`, and have valid PNG readback at that canvas's actual dimensions. The observed offscreen `mode-loading` state, alone or with `mode-req-render`, remains not-ready; other unobserved classes remain UNKNOWN.
- The adapter rewinds using the observed public seek input, advances one verified spread at a time, requires stable counter/active/ready metadata, captures spread sides in order, and checks contiguous body slot identity. It recognizes terminal UI only after every body slot has been captured. It never follows the next-episode card. Direct PNG errors/timeouts cannot reach generic locator/screenshot fallback.
- Selected capture is the clean rendered body-canvas PNG. A one-page source-derived replay had pixel equality but did not establish reusable mapping for every page/source generation; the tested 240×385 tile geometry rejects the measured MCU-8 DCT permutation method. The fallback retains the visible canvas pixels/dimensions, with reduced fidelity relative to the 960×1540 source.
- Focused local unit and synthetic-browser tests: 14 passed, 0 skipped (5 pytest-asyncio deprecation warnings). A Runner-level test injects direct PNG timeout and proves generic locator capture is rejected before `capture_locator` runs.
- Historical failures: an initial Viewer attempt exposed an offscreen body wrapper with `mode-loading mode-req-render`; a bounded diagnostic later observed `mode-loading` alone with no canvas. Those exact non-ready states received unit coverage. A subsequent run stopped on AccessGuard HTTP 429 with `Retry-After: 1` and captured no pages. A later third-episode Batch attempt saved one page then timed out at 3/55; a metadata-only probe showed the previous wrapper intersecting the viewport by 15.33 px while its canvas was offscreen. The center-in-viewport correction removed that stale slot. These failures were superseded by the final successful three-sample E2E recorded below; no retry or AccessGuard relaxation was used.
- Ignored local probe/output paths: `output/hanayume_experiment/phase03b_dom_diagnostic.py`, `phase03b_live_check.py`, and `phase03b-live-20261010/` plus `phase03b-live-20261010-r2/`. Initial failure diagnostics may include local screenshot/page HTML under ignored output; none are committed. Live scripts store only sanitized counts, slot IDs, dimensions and decoded-pixel hashes when a full run succeeds.
- The final three-sample Phase 05 run resolved the Phase 03 live gate for the logged-out exact-`無料` scope. This does not verify authenticated `今なら無料`, other reader layouts, other works, or broad source-native image fidelity.

## Bounded live failure and correction follow-up (2026-10-11; later superseded by the successful E2E below)

- The authorized third-episode Batch attempt (`2ec9c6b024ee0`) completed fresh exact-free preflight, rewound to 1/55, saved body slot 1, and reached 3/55. It then timed out waiting for the next state; no ZIP Artifact was created and the Catalog Item stayed pending.
- A single metadata-only follow-up observed `active=[1,2,3]`, `ready=[2,3]` at 3/55. In the 1906×986 viewport, wrapper 1 overlapped the left edge by 15.33 px, but its 828×1329 canvas was wholly offscreen; wrappers/canvases 2 and 3 were the visible spread. This showed that any-intersection activity retained the stale previous wrapper.
- Site-local parsing now defines active wrappers by their center being inside the viewport. Selected canvases still require the exact expected slot set/order, loaded/rendered markers, full canvas visibility, and atomic PNG readback; an active loading side remains blocking. The new unit and synthetic-browser regression covers both the clipped previous wrapper and active loading side.
- Metadata probe: `output/hanayume_experiment/phase03c-advance-metadata.py`; sanitized result: `output/hanayume_experiment/phase03c-advance-metadata.json`; command: `.venv/Scripts/python.exe output/hanayume_experiment/phase03c-advance-metadata.py`. It recorded metadata only, no image bytes or page body. No 403/429/challenge was observed in this bounded follow-up.
- Post-fix focused tests: **27 passed, 0 skipped**; scoped Ruff passed. Independent re-review then passed BLOCKING 0 with 163 affected tests, 0 skipped, and Ruff/diff checks passing. The earlier full suite (2037 passed, 0 skipped) predates this site-only fix. The subsequent successful Tester run is recorded below.

## Final live capture verification (Phase 05; Tester PASS)

- The Tester reused the previously verified isolated Discovery Catalog (296 sources: 3 `free`, 293 `unknown`) by SQLite backup, then invoked the normal Batch CLI for the three exact-free candidates. Discovery was not rerun during this Batch iteration.
- All three episode runs reached `END` with complete body coverage: 32, 40, and 50 slots (122 total). The same-run selected visible canvas RGBA payload exactly matched every adapter PNG. Three ZIPs matched Manifest member count/order/CRC/hash; exactly three Catalog Items completed and the 293 `unknown` Items remained pending.
- Independent visual review sampled each episode's first, middle, and last body page (9 images); all showed clean comic body canvases without UI, ads, blank frames, or half-page crops. Metrics were 1,189 requests and zero 403/429/5xx, challenge, CAPTCHA, or retry events; quota remained unused and entitlement/grant state unchanged.
- The harness command and final reports are in `output/hanayume_experiment/tester/runs/20261010T153649Z-ac385393/`; details are summarized in `runbooks/hanayume-free/PROGRESS.md` and `note/10_hanayume.md`. The run used rendered body-canvas PNG at 828×1329; original 960×1540 source mapping is not proven generally. The authenticated, non-consuming `今なら無料` case remains unverified under the user's no-login instruction.

## Phase 03-A probe result (2026-10-10; production contract still gated)

- The three logged-out `無料` samples were preflighted from the observed same-work listing and then opened at their exact episode paths. For the third sample, the observed range link `/series/1f9f5b0d4cd52/1` labeled `1-30` was followed; selected range, row label, episode ID, and scoped work link were validated. No access-stop response occurred.
- In these samples, counters were 37/45/55, while `#xCVPages` had 38/46/56 slots. Slot 0 was promotion; slots 1 through N−5 were structural body candidate wrappers, many of which were unloaded placeholders without a canvas. Slot N−4 was a book-information panel, the next two slots were promotion, and the last two slots were good/last terminal UI. At counter N−4 the final body canvas was visible; terminal N/N contained no body canvas. This is sample evidence, not a site-wide invariant. The observed mode was `mode-spread`; no single-page control was established.
- One first-page source replay is positively proven: 16 tiles fully covered a 960×1540 scratch generation from a JPEG response; replay through the observed 828×1329 scale matched both scratch and visible body pixels exactly. 828×1329 is the selected canvas size observed on these samples, not a universal accepted dimension. A different-canvas relationship on the third sample remains unproven, so this cannot be generalized to all pages. The measured 240×385 tiles reject only the tested MCU-8 DCT permutation path.
- Proposed Phase 03-B gate: use source-derived pixels only when current page/source/generation, full tile coverage and source rectangle, exact final scale and pixel equality are proven for that page. If using a mutable scratch canvas, snapshot at its proven draw event before reuse and encode afterward. Otherwise use the clean body canvas PNG; fail closed on readback failure and never substitute a UI screenshot silently. Page readiness, complete ordering, last-body/END logic and per-page binding still need implementation evidence.
- The probe was `output/hanayume_experiment/phase03a_probe.py`, with sanitized metadata in `output/hanayume_experiment/phase03a-viewer-binding.json` (ignored). It saved no page/image bodies, screenshots, or signed URL queries. No tests were run because this was a probe-only checkpoint. Lead adjudication and independent review are required before production changes.

## 実装・テスト範囲
- site固有adapter / capture補助、正当化された小さいpure helper、
  対応Unit/Browser integration、site README/note。Core/Packagerの
  出力形式仕様を無断で改変しない。
- Unit: canonical target mismatch、free→nonfree、forbidden control、同一ページ、
  検証不可能なsource、MCU不整合、WebP lossless証明失敗とPNG fallback。
- Integration: CONTENT→CONTENT→END、LOADING→CONTENT、UNKNOWN、
  spread/片側不完全、最終本文、巻き戻し、別話遷移防止、fallback正しい状態。
- Live: 同一作品の代表2〜3話で先頭/中間/最終、画像のサイズ・順序・品質・元body照合、
  終端、数ページ連続のnavigation安定性を確認。保存画像と基準表示を視覚・pixel両面で監査。
- 独立Reviewerは原画像帰属根拠、誤ったjpeg係数変換、ページ脱落/重複、
  UI混入、最終ページEND、再開処理と他Adapter回帰を確認。高リスクCaptureはTesterにも渡す。

## Exit
本番で採用するCaptureレベル、証明手段、観測した解像度/ページ数、fallback頻度、
テストPASS/FAIL/NOT VERIFIED、差分とReview BLOCKING 0をPROGRESS.mdへ記録。
未対応layoutやDCT不適合を「完全復元済」と表現しない。


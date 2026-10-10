# Tester計測結果

このファイルはTesterが作成した測定と再現性の記録。数値JSON/CSVと計測スクリプトは同じディレクトリ配下にある。画像、JPEGレスポンス、HTML、認証情報、署名付きURLは研究成果物に複製していない。

## 実サイト確認

**NOT VERIFIED: source-native capture 0 pages.** 指定URLでfresh-free preflightを実施した後、既存shared contextとCDP接続の新規・未認証context（viewport 1904×1200、requested device scale factor 1）を試した。いずれもcapture前に既存のcanvas geometry guardで停止した。隔離contextの数値snapshotではorigin/viewer page p1、innerWidth/innerHeight `[1904,1200]`、canvas pixels `[844,1200]`、canvas rect `[529.6667,0,844,1200]`、frame rect `[530,0,844,1200]`。唯一の不一致は `window.devicePixelRatio=1.0000000298023224` で、コードが要求するviewport tuple `[1904,1200,1]` との厳密比較を通らなかった。0.99999997から1.000000005まで9個のrequested DSFでも実値は0.9999999403953552または1.0000000298023224となり、厳密な1は得られなかった。

検証を通すためにproduction guard、shared Chrome設定、Cookie、サイト権利を変更していない。JPEGレスポンス取得・通常ページ遷移は行われず、liveの9工程分解、ページwall time、遷移固定待機、Chrome CPU/RSSは未計測。失敗試行の初期化・待機時間は通常成功ページの性能値として扱わない。max-pages/END、Catalog、Batch、通常出力への操作もない。

## ローカル画像処理ベンチ

入力は既存のPhase 06-D source-native lossless WebP archive/manifestを読み取り専用で使用した。manifest上の `source_native=true`、`native_tile_replay_lossless_webp`、`output_lossless=true` と、archive memberの単一VP8L / RGB mode / 1 frameを確認した。12ページを2回処理。出力は数字とタイミングだけで、元画像や中間画像はファイルに書き出さない。

既存成果物には元の透明度を含むreplay PNGが保存されていない。そのため本計測のPNG入力は、同じ既存composited RGBから作ったopaque RGBA PNG surrogateである。white composite後のRGB byte equalityは確認したが、透明タイルの実際の白合成コストを測った値ではない。

### 現行helper対experimental direct-RGB

`local-pipeline-final/local_pipeline_pages.csv` はpage×stageのwall/CPU/bytesを、`local_pipeline_summary.json` はrunごと/first-vs-normalの統計とheartbeat lagを記録する。表のnormalは22件（11ページ×2 run）、firstは2件。p90はnearest-rank `ceil(0.9*n)-1`。

| 同期処理（Python内） | normal median | mean | p90 | max |
|---|---:|---:|---:|---:|
| production PNG白背景合成（PNG再encodeを含む） | 0.0844 s | 0.0894 s | 0.1136 s | 0.1191 s |
| production WebP method 6 helper（fallback PNG検証とexact decodeを含む） | 0.3966 s | 0.6597 s | 1.2954 s | 1.4593 s |
| production adapter最終形式再検証 | 0.0150 s | 0.0183 s | 0.0276 s | 0.0345 s |
| experimental white composite→RGB bytes | 0.0267 s | 0.0274 s | 0.0335 s | 0.0373 s |
| experimental WebP method 6 + VP8L/RGB exact検証 | 0.3492 s | 0.6012 s | 1.1546 s | 1.2881 s |
| experimental adapter最終形式再検証（productionと共通） | 0.0151 s | 0.0184 s | 0.0288 s | 0.0303 s |

direct-RGB案は中間PNG save/reopenを避け、fallback PNG branchの成功時検証を経由しない。最終形式検証は現行と同じ関数で両案に1回ずつ実行した。したがってcomposite差はPNG serialize/decodeを避けた効果に近いが、WebP helper差はPNGの往復とfallback PNG検証をまとめた比較である。2案のmethod 6 encodeを別々に実行したため、この差を厳密なpaired estimateとは見なさない。測定値の合計から実ページ全体の短縮率を推定しない。

CPU時間はWindows process `time.process_time()`。同期helperのwall時間はイベントループを止めている時間にほぼ等しい。50ms周期heartbeatでは最大lag 1.425sを観測したが、処理順の中で最大サイズの初回画像と重なった粗いサンプルなので、それだけでブロック区間を特定しない。プロセスRSSのpeakはlocal pipeline CSVに含めていない。計測スクリプト内の `asyncio.sleep(0.06)` はheartbeatに同期停止を検知させるためだけで、stage wallから除外される。

### WebP method比較

同一の再構成済みRGBを持つ4サンプルについて各methodを3回、合計12 encode/method実行。画像byteはメモリ内に留めた。すべての出力が単一VP8Lであり、decode後の全RGB bytesが入力と完全一致した。

| Pillow method | encode median | p90 | 平均出力サイズ |
|---|---:|---:|---:|
| 0 | 0.2078 s | 0.2384 s | 936,699 bytes |
| 3 | 0.4567 s | 0.5701 s | 824,211 bytes |
| 6 | 0.9713 s | 1.1871 s | 819,327 bytes |

元の数字は `local-webp-methods/webp_methods.json` / `.csv`。4画像に対するローカル結果であり、ネットワークやbrowser waitを含まない。method 3はこの測定でmethod 6より約53%短いencode時間、平均ファイルサイズは約0.6%増。method 0は約79%短いが約14.3%増。

## 計測harness検証・テスト

- `profile_sitecustomize.py` をResearch専用importし、synthetic browser fixtureの `tests/integration/test_piccoma_adapter_browser.py::test_piccoma_native_tile_replay_matches_clean_rendered_canvas` を実行: **1 passed, 5 deprecation warnings, 6.64s**。clean rendered canvasとのpixel比較が通り、`paintSnapshot` DOM walk / snapshot evaluate 各6回、native trace snapshot 2回、JPEG decode / 408 draws / PNG encode clocks、source-native-lossless WebP gateが記録された。計測scriptの配線・tile replayのpixel equalityを確認するfixture試験であり、実サイト証拠ではない。
- `ruff check research/piccoma-performance`: **PASS**。
- Leadが実行した `pytest -q tests/unit/test_piccoma_native_capture.py`: **45 passed, 0 skipped, 0.55s**。Testerは重複実行していない。
- Python base `Image.load` monkeypatchのspanはcodecの実decode時間の根拠にしない。Pillow codec subclassのdecodeはbase method hookの外で起こりうる。実際のlocal final-validation時間は `capture_result_format_is_valid` を呼び出し全体で囲ったwall/CPU timerを根拠にする。

## Evidence files

- `profile_sitecustomize.py`: runner/adapter/Pillow/Playwright instrumentation。実装ファイルを変更しない。
- `profile_run_driver.py`, `run_profile.ps1`, `probe_context_scale.py`: bounded live attempt / geometry probe用。`run_profile.ps1` はrun pathが `output/piccoma_performance/` 配下であることを境界込みで検査し、既存pathを拒否する。
- `webp_method_bench.py`, `local_pipeline_bench.py`: local-only benchmark scripts。
- `measurements/`: sanitized timing JSON/CSV、fixture instrumentation JSON。画像バイト列なし。

## Live snapshot shadow probe (追加計測)

`live_snapshot_shadow.py` は共有CDP `127.0.0.1:9222` に接続し、free listing preflight後に通常Runnerを1ページだけ試す。2回とも既存の厳密なgeometry guardが `UnknownPageStateError` で停止したため、通常captureは成功していない。両runで保存ページ0、`Response.body()` 呼び出し0、native tile replay呼び出し0。Catalog・通常成果物・共有Chrome設定を変更していない。p1の読取専用metadata観測ではcanvas 844×1200、tile trace validation `valid`、drawImage 408件、white paint valid、唯一のsource JPEG responseがstatus 200 / image/jpeg / 1,951,370 byte declared lengthだった。応答bodyは読んでいない。この結果はcapture provenanceの証明ではなく、capture成功として扱わない。

追加したA/B/Cは同じページ状態・同じLocator.evaluate APIで、native full snapshot() と paint処理を実行する。各variant前後のp1 reader projectionとfull target/source/paint signatureをRAM上で確認し、安定した12組だけを集計する。全raw traceとURLはRAM内のみ。B(compact)は全計算後に数値要約だけ返す。Cは全traceを`JSON.stringify`で文字列化して返し、Python `json.loads`を別計測した。Cの返却オブジェクトは同じ組のA(full object)と全フィールドdeep-equalで、2 run各12/12成立した。trace numeric projectionも2 run各12/12一致、unstable pairは0。各variantでfull JSON serialization lengthは約390,600 byte、compact JSONは513 byte。これらはブラウザ内UTF-8 JSON長でありCDP wire byte数ではない。

| Run | Variant | evaluate wall median (p90) | Python loads median | evaluate + loads paired median (p90) |
|---|---|---:|---:|---:|
| A | full object | 200.9 ms (221.2 ms) | — | — |
| A | compact numeric | 11.9 ms (13.0 ms) | — | — |
| A | full JSON string | 22.7 ms (26.5 ms) | 3.34 ms | 26.3 ms (30.9 ms) |
| B | full object | 157.3 ms (189.3 ms) | — | — |
| B | compact numeric | 11.9 ms (14.9 ms) | — | — |
| B | full JSON string | 21.0 ms (23.0 ms) | 2.86 ms | 24.1 ms (25.6 ms) |

呼出順は各組で固定のfull→compact→json-stringで、ランダム化した因果比較ではない。p1一状態のbounded観測で、通常capture後のfinal traceや成功ページ全体へそのまま一般化できない。full objectよりJSON文字列が速かった差は大きいが、CDP transport / Playwrightの戻り値変換が含まれる。compact方式は証明に必要な408イベントを返さないため、この時間をそのまま安全な短縮とみなせない。Cは観測データの全フィールドを保持したまま戻り値表現を変える候補だが、production導入時はtrace値がJSON-safeである契約、undefined/NaN/Infinity/-0などの型差、全validatorの通過、full objectと同じsource/provenance proofを維持するテストが必要。今回の一状態比較だけを根拠に実装採用はしない。

旧 `live-shadow-a.json` / `live-shadow-b.json` はJS/Python projection schema差によりprojection matchが0だったため、match根拠としては無効。修正後の `live-shadow-final-a.json` / `live-shadow-final-b.json` と `live-shadow-final-summary.{json,csv}` を使用する。aggregatorは `aggregate_live_snapshot_shadow.py`。raw trace/画像/response body/署名URLはmeasurementに保存していない。

検証: harness Python compile PASS、研究スクリプト Ruff PASS。2回のlive metadata probeは前述のとおりcapture未到達。通常の成功ページE2E・p2以降・10〜20ページwall-time profileは未検証。

## WebP method 4 follow-up (same-RGB balanced comparison)

既存の同一無料話source-native RGB WebP p1/p13/p24を読み取り専用で使い、0/3/4/6全methodを各sample×4回、各sample/methodの未集計warmup 1回後にbalanced orderで計測した（各method n=12）。出力byteは保存せずメモリ内検証し、48件すべてsingle VP8Lかつ全RGB byte完全一致。

| method | encode median | p90 | median bytes |
|---:|---:|---:|---:|
| 0 | 0.2063 s | 0.3204 s | 843,804 |
| 3 | 0.5858 s | 0.6481 s | 681,864 |
| 4 | 0.5146 s | 0.5891 s | 681,864 |
| 6 | 1.1620 s | 1.3226 s | 682,062 |

3 sample全体のmean sizeはmethod0 1,052,250 byte、method3/4 940,149 byte、method6 937,396 byte。method4はこの小標本でmethod6よりmedian encodeが約0.647 s短く、median size差は0 byte、mean sizeは約0.294%増。method0比ではmethod4は約10.65%小さい（以前の誤った逆方向の記述は訂正済み）。これは既存3画像のローカルcodec比較であり、capture全体または異なる画像集合へ一般化しない。結果: `measurements/local-webp-method4/webp_methods.json` / `.csv`。再実行用は`webp_method_bench.py`。


## Final full-profile instrumentation fixture validation

After both live runs completed, the revised research profiler was imported before running the existing synthetic browser-backed pixel-equality fixture:

- Command target: `tests/integration/test_piccoma_adapter_browser.py::test_piccoma_native_tile_replay_matches_clean_rendered_canvas`
- Result: **1 passed, 5 warnings, 5.02s**. All five warnings are `pytest-asyncio` deprecations for event-loop policy APIs; no test failures.
- `PERF_TRACE_FILE` output was written only under ignored `output/piccoma_performance/20261010_full_profile_fixture/` (42,507-byte numeric/timing trace).
- This confirms the instrumented synthetic replay still matches the clean rendered canvas pixel-for-pixel. It does not add live capture evidence or imply that a Piccoma live capture succeeded.
- Final research checks: `ruff check research/piccoma-performance` **PASS**; `python -m compileall -q research/piccoma-performance` **PASS**.


## Full current-pipeline live profile handoff (two runs)

This section reports the completed 2026-10-10 baseline runs. Raw timing traces and image outputs are isolated under `output/piccoma_performance/20261010_full_profile_01/run-1/` and `output/piccoma_performance/20261010_full_profile_02/run-1/`; sanitized aggregation is `measurements/full-profile-current/full-profile.json` and `.csv`. The baseline retained source-native capture, JSON-object trace return, method-6 lossless WebP, strict geometry/provenance/page-generation/fallback gates, and the existing 1000 ms pacing. Both runs used the shared CDP endpoint with a fresh uncredentialed owned context, the fresh-free viewer URL from the task, and no paid resource.

Each run saved pages 1?12 in order: 12 `native_tile_replay_lossless_webp`, zero fallback pages, and no gap or duplicate sequence. The bounded stop after reaching the page limit is `max_pages_exceeded_bounded_probe_not_end`: page 13 was not captured and this is not an END verification. The driver used an isolated output directory; it did not use Catalog/Batch or modify normal output. The measured final manifest was checked.

The primary steady-page measure is **capture start for page n to capture start for page n+1**, not `capture_page()` alone. There were 11 complete cycles per run (p1 through p11); the last capture-to-run-end interval was partial and excluded. This gives 20 normal complete cycles across both runs, while the inclusive raw `capture_page()` event table has 22 normal observations because it also contains p12 captures; keep those denominators separate. Across the 20 normal cycles, median was **4.151 s**, mean **4.538 s**, nearest-rank p90 **5.627 s**, max **5.772 s**. The two p1 cycles were **5.571 s** and **5.398 s** (mean/median **5.485 s**). Normal `capture_page()` itself has 22 observations because it includes p2?p12: median **2.269 s**, mean **2.673 s**, p90 **3.670 s**, max **3.926 s**. The p1 capture spans were 3.706 s and 3.515 s (median 3.610 s).

| Pipeline stage / observed span | p1 median (n=2) | normal median (n=22) | normal p90 / max | Interpretation |
|---|---:|---:|---:|---|
| Fixed pacing (`runner.pacing`) | 1.010 s | 1.007 s | 1.013 / 1.015 s | Deliberate configured wait; not CPU work. |
| Page turn (`go_next` start through `wait_for_change` completion) | 0.727 s | 0.721 s | 0.806 / 0.826 s | Includes click and existing state/stability polling. `wait_for_change` alone: normal median 0.631 s. |
| Reader/state and native trace proof | reader snapshot call median 10.0 ms; full `snapshot_native_trace()` span 165 ms | reader snapshot call median 13.7 ms; `snapshot_native_trace()` span 162 ms; `validate_current` 165 ms | trace helper p90 227 ms, max 351 ms; `validate_current` p90 250 ms, max 261 ms | Per normal capture: 20.7 `reader_snapshot` calls on average, 2 high-level `snapshot_native_trace()` invocations and 1 `validate_current` span. The profiler also records 6 low-level `browser.snapshot_evaluate` calls per capture (72/run, 6/page); these include internal before/after/final/generation snapshots. Parent helper spans overlap low-level evaluates and must not be summed. |
| Source JPEG response body + source-JPEG validation | 191 ms + 223 ms | 75.6 ms + 94.3 ms | body 146 / 154 ms; validation 183 / 191 ms | Browser response transfer/body retrieval and Python source integrity/provenance validation. |
| Tile replay and browser PNG return | replay evaluate 672 ms | replay evaluate 388 ms | 740 / 819 ms | JS subtimings (duration only): JPEG decode 15.9 ms median, drawing 408 tiles 1.0 ms, `toDataURL` PNG 42.6 ms. The remaining evaluate wall includes browser/Playwright serialization, base64/transport, scheduling, and other unclassified work; it is not a pure JS CPU duration. |
| PNG decode, white composite, RGB PNG intermediate | composite helper 117 ms; PNG save 88 ms | composite helper 85.2 ms; PNG save 64.4 ms | helper 118 / 123 ms; save 88 / 94 ms | The PNG save is nested in the composite helper; do not add the two. |
| Lossless WebP encode | method-6 `Image.save` 1.140 s; helper including surrounding work 1.199 s | `Image.save` 333 ms; helper 368 ms | save 1.214 / 1.442 s; helper 1.275 / 1.508 s | Largest variable CPU-heavy step. The helper span includes more than the codec call. |
| WebP decode / RGB and format checks | final format validation 34.1 ms; final codec decode 32.8 ms | final format validation 15.7 ms; final codec decode 14.2 ms; RGB conversion 16.0 ms | final validation 28.8 / 33.2 ms; codec decode 26.8 / 31.1 ms | Decoder, conversion and final validation are separate/nested observations; preserve exact RGB and VP8L gates. |
| Save and manifest/progress update | file save 1.5 ms; manifest update 5.0 ms | file save 1.3 ms; manifest update 3.1 ms | manifest 3.8 / 4.3 ms | Research progress sidecar was written only after p1 commit, outside `capture_page`; its small numeric write is excluded from the primary capture span. |

For both runs, whole-run wall was 59.989 s / 59.413 s; Python process CPU was 22.234 s / 22.063 s; Python RSS peak was 165.2 / 166.7 MiB (final 108.6 / 109.6 MiB). Heartbeat maximum lag was 1.443 s / 1.628 s over 786 / 779 ticks. This shows substantial synchronous CPU activity during capture, but the full-run heartbeat cannot attribute each lag to a specific encoder call. Shared Chrome CPU/RSS was not sampled because other shared-browser activity would contaminate it. Instrumentation overhead was not measured against an otherwise identical uninstrumented run; no instrumentation-overhead correction was applied.

The transition milestone anchor differs by run and must not be pooled as though equivalent. Run 1 used the existing wait wrapper start because the research hook did not obtain an exact click marker; run 2 measured the `Locator.click` start. Run 2 normal click-to-wait-complete median was **665.5 ms** (p90 704.2 ms, max 765.0 ms); first expected-ID/loaded snapshot appeared at median **49.4 ms** (p90 73.9 ms, max 151.0 ms), while the third stable snapshot was reached at median **665.1 ms**. Run 1's wait-start-anchored first expected/loaded snapshot was median **12.5 ms** and third stable snapshot **632.0 ms**. No rect/style/viewport/backing-size change-reason counters were installed, so the reason stability takes the remaining ~0.6 s is **not measured**; these data do not justify relaxing stability conditions.

Instrumentation recorded 247?248 `adapter.reader_snapshot` calls/run, 24 `snapshot_native_trace()` helper calls/run (=2/page), 72 `browser.snapshot_evaluate` calls/run (=6/page), 259?260 `Page.evaluate` calls, 108 `Locator.evaluate` calls and 1,726?1,753 `Locator.count` calls per run. Counts are instrumented Playwright calls, not a complete CDP packet count. The six low-level snapshot evaluations cover repeated source/target-generation checks inside capture; the two named helper calls are only the adapter-level wrapper count. These counters describe different nesting levels, not contradictory totals. The observed JS 408-tile draw itself was about 1 ms, so tile drawing is not the page bottleneck. WebP encoding is both CPU-heavy and variable; the 1-second pacing and ~0.65-second transition stability wait are also direct cycle costs. The residual difference between the cycle and individually timed spans contains polling, other browser calls, serialization/transport/scheduling, and instrumentation gaps; spans overlap, so subtotals must not be summed into a synthetic exact decomposition.

For the separate same-RGB local method comparison in `measurements/local-webp-method4/webp_methods.json/.csv`, method 4 versus method 6 median file size is **681,864 ? 682,062 = ?198 bytes** (method 4 smaller), while mean file size is **940,149.33 versus 937,396 bytes**, so method 4 mean is **0.294% larger**. Method 4 median encode was 0.5146 s versus method 6 1.1620 s in this small three-image sample. All outputs were single VP8L and exact-RGB-equal. This is a local codec comparison, not a live method-4 run or a causal estimate of whole-page savings. This arithmetic corrects the earlier sentence in this file that said the median size difference was 0 bytes.

The profiler's browser-JS durations are milliseconds from `performance.now()` converted to seconds; the initial verbal reading of 0.024 s and 0.0016 s as microseconds was incorrect and has been corrected here. These values mean 24 ms and 1.6 ms for the initial p1 sample. JS event start/end timestamps in older raw records are synthetic return-relative placements, not event intervals, and were not interval-unioned. `pillow.load.*` hooks do not measure the full codec decode; the explicit `pillow.codec_decode.*` spans are the relevant decode observations. Percentiles use nearest-rank `ceil(0.9*n)-1`.

**Unmeasured / limits:** no full 10?20 page END-confirmed free chapter run; no uninstrumented control for measuring profiler overhead; no shared-Chrome CPU/RSS attribution; no exact transition invalidation-reason counters; no live method-4 comparison; no ZIP/Catalog/Batch behavior was exercised because their specifications were explicitly out of scope. These are limits of this performance study, not success claims. The synthetic replay pixel-equality fixture and the 12-page per-run native manifest checks are reported separately above.


## 0 ms page-turn pacing bounded live comparison (research-only override)

Two additional 12-page bounded runs used `RunConfig.page_turn_delay_ms=0` directly in the isolated research driver. The production runner, adapter and `crawler.yaml` were not changed. Fresh-free listing preflight, direct strategy, strict page/geometry/source guards, AccessGuard stop flags for HTTP 403/429/challenge/CAPTCHA, source-native method-6 path, expected page IDs, canvas loaded/renderability checks, and three identical stable samples remained enabled. The primary live outputs are isolated at `output/piccoma_performance/20261010_full_profile_zero_delay/run-1/` and `run-2/`. Sanitized profiles are `measurements/full-profile-zero-delay/full-profile.json`, `.csv`, `cycle-partitions.json`, and `output-equivalence.json` (counts only; no hashes or image bytes).

Both runs saved ordered pages 1?12, all 12 with `native_tile_replay_lossless_webp`, `source_native=true`, `image/webp`, and lossless output; fallback count was zero. Both stopped on the deliberate max-pages bound after the p12?p13 advance path and did not capture p13 or verify END. There was no AccessGuard fatal stop; each timing trace has normal `runner.access_check` calls. SHA-256 comparisons against baseline run-1's p1?p12 WebPs were byte-identical **12/12 for zero run-1 and 12/12 for zero run-2**. Since bytes matched exactly, no separate RGB comparison was needed. No ticket, paid resource, normal Catalog or normal crawl output was touched. Each full profile still has 20 complete normal cycles (p2?p3 through p11?p12) per two-run pair; the separate raw `capture_page()` summary also includes p12 captures (22 normal observations) and is not that cycle population.

| Measure (complete normal cycles unless noted) | 1000 ms baseline, n=20 | 0 ms run, n=20 | Interpretation |
|---|---:|---:|---|
| Capture-start?next-capture-start cycle, mean / median / p90 / max | 4.538 / 4.151 / 5.627 / 5.772 s | 4.068 / 3.742 / 5.143 / 5.301 s | The observed median was 0.409 s lower at 0 ms, not a one-second reduction. Separate time windows and variable processing/transport prevent attributing the difference to pacing alone. |
| Exclusive `runner.pacing` span, median / p90 / max | 1.008 / 1.013 / 1.015 s | 7.3 / 15.5 / 17.5 ms | 0 was passed in `RunConfig`; observed few milliseconds are wrapper/instrument/runtime overhead, not a deliberate one-second sleep. |
| `go_next` span, median / p90 / max | 89 / 116 / 143 ms | 111 / 137 / 167 ms | Observed independently from the configured delay. |
| `wait_for_change` span, median / p90 / max | 631 / 721 / 741 ms | 636 / 751 / 849 ms | The readiness and stability gate remained present; 0 did not bypass the adapter wait. |
| Exclusive `capture_page` span, mean / median / p90 / max | 2.632 / 2.234 / 3.670 / 3.926 s | 3.076 / 2.703 / 4.140 / 4.277 s | Capture processing was slower in the 0 ms time window, offsetting some delay removal. |
| Exclusive native trace snapshot RPC budget, mean / median | 1.034 / 1.037 s | 1.277 / 1.228 s | Six low-level `browser.snapshot_evaluate` operations per page are counted in this partition; this is distinct from 2 high-level `snapshot_native_trace()` calls/page. |
| Exclusive WebP encode, mean / median / p90 | 572 / 318 / 1,198 ms | 649 / 380 / 1,322 ms | Same method and byte-identical output, but encoder wall time varied by run. |
| JS replay subtimings, median decode / 408 draw / PNG encode | 16 / 1 / 43 ms | 17 / 1 / 46 ms | No material draw-time change; values are duration-only browser measurements. |
| Whole-run wall, per run | 59.989 / 59.413 s | 60.088 / 59.323 s | Essentially unchanged in these runs; do not claim a whole-run throughput gain. |
| Python process CPU, per run | 22.234 / 22.063 s | 26.156 / 25.703 s | CPU use was higher in the 0 ms window. Shared Chrome CPU is not attributable/measured. |
| Python RSS peak, per run | 165.2 / 166.7 MiB | 163.8 / 163.3 MiB | Process-local measurement only. |

First-page cycle medians were 5.485 s baseline versus 5.220 s at 0 ms (two observations each; zero-delay runs were 5.648 and 4.792 s). For zero-delay normal transitions using the exact click marker, first expected ID and loaded snapshot appeared at median 59 ms; three stable samples completed at median 686 ms (p90 790 ms, max 895 ms). Baseline normal transition medians were 49 ms to first expected/loaded snapshot and 665 ms to three stable samples. The existing expected ID and stability contract was therefore exercised under 0 ms; output SHA equality verifies that these bounded captures emitted the same source-derived WebPs as baseline. No rect/style/viewport/backing-change reason counter was installed, and this two-run max-pages probe does not prove safety over all page transition variants or a complete END path.

Although the configured delay removed about one second from each intentional advance, whole-run wall did not fall in this measurement. Capture-start p1 initialization was ~3.93 s baseline versus ~4.54 s at 0 ms, while time from p12 capture end to runner end was ~1.83 s baseline versus ~5.88 s at 0 ms; the latter follows p12's final advance/stability/max-pages handling and is outside the 11 complete p1?p11 cycles. These unexplained start/tail differences, plus higher capture, trace-RPC, and encode spans during the 0 ms runs, leave the whole-run comparison inconclusive. Do not extrapolate the per-cycle difference as a causal 0 ms speedup.

The shared authority says a missing pacing setting keeps the safe 1000 ms default, while an explicit nonnegative integer override (including zero) is permitted (`docs/ACCESS_CONTROL_AND_PACING.md` ?4.3, ?5). The live harness supplied zero directly to `RunConfig`, rather than testing the production CLI/crawler.yaml route. While running, I found one indentation error in the research PowerShell template's generated crawler.yaml; both generated files are preserved as raw evidence and were unused by the driver, which directly constructs `RunConfig`. I corrected the research template and verified the corrected YAML text parses; the live facts above are taken from the recorded `RunConfig` value `0` and runner pacing spans. No production configuration was altered.

# Phase 07 Stage C live profile

## Scope and method

This report compares the reviewed Stage A object-return baseline with the reviewed Stage B JSON-string snapshot implementation through the stock CLI and the shared Chrome CDP session. Both arms used the same isolated `crawler.yaml` (SHA-256 `37cff66f637de63c9a7494590e6e5e82ba521e51d114f311b025906019a72003`), Piccoma `page_turn_delay_ms=200`, and all four HTTP/challenge/captcha stop flags set to `true`. WebP method 6, the native JPEG response path, 408-tile replay, white backdrop proof, source/page identity checks, six snapshot checkpoints, and output validation remained enabled.

The immutable object source copy was `output/piccoma_performance/phase07_20261010b_dpr_object_baseline`; the JSON arm used the current checkout. The launcher recorded and matched the selected adapter, native-capture, runtime-settings, and CLI source paths and SHA-256 values for each process. Runs were interleaved: object 1, JSON 1, object 2, JSON 2. Each was a real `crawl --site piccoma --access-strategy direct --max-pages 12` through the actual CLI with fresh output, diagnostics, and library directories under `output/piccoma_performance/phase07_20261010_stagec_live_01/`.

The expected stock CLI `MaxPagesExceededError` and exit code 1 were preserved on all four bounded runs. These are not END runs. The audit of each run found 12 pages in p1..p12 order, 12 native lossless-WebP results, zero fallback, consistent source ID and JPEG provenance, and six native trace evaluations per page (72/run). Source and output image bytes were never copied into the research Markdown.

`cycle_partitions.py --without-replay-js` assigned measured Python intervals exclusively and required exactly six trace calls per cycle. It summarized the complete p1..p11 capture-start cycles from each run: p1 separately (n=2/arm), normal p2..p11 (n=20/arm), and excluded the incomplete p12-to-process-end tail. No synthetic replay-JavaScript intervals were injected. The 50 ms event-loop heartbeat and timing hooks were identical across both arms; the harness added no browser RPC or source response wrapper. It does add local sampling/instrumentation, so absolute times should be read as profiled CLI measurements.

## Main comparison

All figures are seconds unless stated otherwise. `p90` uses the nearest-rank sample in the indicated sample set.

| Measured interval | Object, n=20 normal | JSON, n=20 normal | Difference |
| --- | ---: | ---: | ---: |
| Capture-start to next capture-start: mean / median / p90 / max | 3.601 / 3.361 / 4.450 / 4.943 | 2.743 / 2.410 / 3.693 / 3.709 | -0.857 mean (-23.8%) |
| Capture operation: mean | 2.497 | 1.632 | -0.865 |
| Capture CPU: mean | 1.427 | 1.026 | -0.401 |
| Browser native-trace RPCs (six calls summed): mean | 1.006 | 0.142 | -0.864 |
| Python JSON decode (six calls summed): mean | 0.000 | 0.034 | +0.034 |
| Source response-body read: mean | 0.087 | 0.084 | -0.004 |
| Source JPEG validation: mean | 0.113 | 0.114 | +0.001 |
| Browser tile-replay RPC, including browser PNG: mean | 0.476 | 0.439 | -0.037 |
| PNG decode / white composite: mean | 0.089 | 0.087 | -0.002 |
| Lossless WebP method-6 encode: mean / p90 / max | 0.508 / 1.084 / 1.140 | 0.510 / 1.057 / 1.173 | +0.002 mean |
| WebP decode / exact round-trip: mean | 0.024 | 0.025 | +0.001 |
| Final format and native comparison: mean | 0.022 | 0.022 | ~0 |
| Runner access check: mean | 0.075 | 0.076 | +0.001 |
| Page-turn pacing: mean | 0.208 | 0.209 | +0.001 |
| `go_next`: mean | 0.110 | 0.108 | -0.002 |
| Page-change wait/stability: mean / p90 | 0.628 / 0.641 | 0.637 / 0.654 | +0.009 mean |

The p1 capture-start-to-next-capture-start cycle is separate (n=2 per arm): object mean 4.526 seconds (p90/max 4.651), JSON mean 3.639 seconds (p90/max 3.662). Each run's p12 capture-to-process-end interval is an incomplete max-pages tail and is excluded from the cycle distributions: object 3.634 and 3.891 seconds, JSON 7.890 and 7.804 seconds. The tail varied substantially between arms and is not treated as a normal page-cycle estimate.

JSON reduced the six-call trace RPC group by about 0.864 seconds per normal page. Decoding the returned JSON added about 0.034 seconds; the net capture reduction measured 0.865 seconds/page, with small differences in other capture spans. Each arm retained exactly six browser round trips per page. The JSON string length was 389,800–391,031 characters (mean 390,450) per snapshot, with six snapshots per page; string transport still carries about 2.34 million characters/page. The representation change replaces Playwright's per-field object transport/conversion with JSON string transfer plus Python JSON reconstruction. The RPC span includes browser-side serialization, CDP transport, and driver work, so it is not a pure wire-time measurement. The measured end-to-end RPC span fell; snapshot count and payload size did not.

## Timing and resource notes

| Run | CLI wall | Runner wall | Python Runner CPU | Python process peak RSS | Python process final RSS | Max Python-loop heartbeat lag |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Object 1 | 47.96 | 46.56 | 19.27 | 170.8 MB | 115.1 MB | 1.264 s |
| JSON 1 | 42.88 | 41.77 | 15.72 | 138.5 MB | 83.8 MB | 1.346 s |
| Object 2 | 50.03 | 48.65 | 20.89 | 171.5 MB | 115.2 MB | 1.393 s |
| JSON 2 | 43.00 | 41.83 | 15.20 | 137.6 MB | 85.0 MB | 1.398 s |

Across these two interleaved runs per arm, mean CLI wall time was 48.99 seconds (object) versus 42.94 seconds (JSON), and mean peak RSS was 171.2 versus 138.0 MB. Runner CPU averaged 20.08 versus 15.46 seconds. The whole-process difference includes startup and the distinct incomplete max-pages tail, so the 20 normal-cycle comparison is the better estimate of steady-state page benefit. The sample is one episode on one shared Chrome machine; these are observed results, not a universal speed guarantee.

CPU and RSS figures come from the Python CLI/Runner process. Chrome and Playwright driver CPU/RSS were not measured separately; event-loop heartbeat lag describes the Python event loop only.

The measured policy wait before page-turn actions is about 0.21 seconds. The action plus loaded-page/stability checks take about 0.74 seconds (`go_next` plus wait-for-change). Page movement/stability therefore remains a visible, separate ~0.95-second cost after a capture. This experiment did not set the policy wait to zero; no claim is made that a zero delay is safe.

In every run, the largest measured event-loop lag (1.26–1.40 seconds) overlapped the same page's synchronous `pillow.save.webp` span (1.09–1.27 seconds). This is strong timing evidence that method-6 encoding is the leading source of the longest event-loop stalls. It is not proof that it is the only contributor. The mean method-6 encode interval was about 0.51 seconds and p90 was about 1.06 seconds; JSON snapshots did not shorten it. No WebP method change was made in Stage C.

## Pixel and source equivalence

The 48 manual WebP files were grouped by page number across both arms and repeat runs. All 12 groups had identical dimensions and identical decoded RGB SHA-256 values; all 12 groups also had identical WebP bytes across all four runs. Every manifest page recorded native capture, JPEG source MIME, verified white backdrop, `native_tile_replay_lossless_webp`, lossless output, direct access, and no fallback. All four outputs contain source ID `28600:1910027` and IDs p1..p12 in sequence.

Two separate dedicated Batch runs each completed 24 pages at 844×1200 and ended with a succeeded Catalog Run and `stop_reason=end`. Both produced 24 ordered `.webp` members, passed ZIP CRC testing, matched their Catalog Artifact SHA-256 and byte size, and all 24 members passed the existing VP8L lossless chunk validator. Every uncompressed page file was byte-identical across both Batch ZIPs; p1..p12 were also byte-identical to manual JSON run 1.

Because normal packaging removes the temporary page directory and keeps only page files in the ZIP, a one-use opt-in research hook read the final Batch manifest exactly once after Runner returned END and immediately before the unchanged packager ran. The URL/title-free audit report passed for all 24 ordered IDs and checked source-native status, JPEG MIME, verified white backdrop, tile-replay method, lossless WebP format/extension, no fallback, per-page count, and uniform source identity. The hook did not change package arguments or cleanup: the second Batch still reports `source_removed=true`. It stores no raw manifest, images, title, or URL.

## Measurement boundaries

- Page IDs, sequence, native capture, JPEG MIME, white-backdrop proof, output format, lossless marker, and fallback were audited from each manual manifest before any report was written.
- Browser response bodies were used in memory and were not persisted. Captured image artifacts remain only in the ignored run outputs and are not included in research files.
- Full Batch Catalog/END/ZIP and independent per-page ephemeral-manifest audit passed in the second isolated run. The sanitized audit output is `output/piccoma_performance/phase07_20261010_stagec_live_01/batch_manifest_01/run/manifest_audit.json` (ignored local evidence).
- These Stage C results compare JSON with the current 200 ms configuration. Comparison against earlier 1,000 ms profiles uses a different harness/source snapshot and is descriptive only.

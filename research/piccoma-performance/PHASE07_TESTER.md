# Phase 07 Stage C tester report

## Verdict

**PASS** for the interleaved 12-page object/JSON manual comparison, direct/free access checks, manual source-native output sequence, and dedicated actual Batch execution through END and ZIP/Catalog artifact checks. The independent per-page Batch manifest audit also passed with the reviewed, opt-in research hook in a second fresh isolated Catalog and Batch run. No paid, ticket, quota, waiting-free, point, coin, purchase, or other entitlement flow was invoked; both dedicated Catalogs report zero quota-resource rows.

## Evidence summary

| Gate | Result | Evidence |
| --- | --- | --- |
| Isolated source/config selection | PASS | All four manual and Batch launch results recorded resolved Piccoma, actual loaded source paths/hashes, explicit isolated YAML SHA-256, `page_turn_delay_ms=200`, and all four required stop flags true. |
| Exact current-free target | PASS | A fresh dedicated full Discovery completed with one bounded result; Batch plan returned exactly one eligible direct item, quota=0, skipped=0 for the selected product/episode. |
| Bounded object/JSON runs | PASS | Four stock CLI runs, interleaved object/JSON/object/JSON; each saved 12 p1..p12 images and preserved the stock typed `MaxPagesExceededError`, exit 1, and `end_verified=false`. Bounded max-pages was not represented as END. |
| Source-native capture and sequence | PASS | All 48 manual pages were native, JPEG-source, white-backdrop-proven, lossless WebP, correct source ID and p1..p12 order, with no fallback. Six trace calls per page were observed in both arms. |
| Manual output equality | PASS | All four outputs had identical WebP bytes for each corresponding page (48/48 files); decoded RGB and dimensions matched across each of the 12 page groups. |
| Batch END/Catalog/ZIP | PASS | One isolated Catalog item completed; its Run succeeded at explicit `end` after 24 pages using direct access; source remained free/available; quota-resource table empty. The single registered ZIP Artifact exists and matches Catalog SHA-256 and byte size. ZIP has 24 ordered WebP members, passes CRC testing, all 24 pass VP8L lossless-container validation, and first 12 page bytes match manual JSON run 1. |
| Batch per-page manifest evidence | PASS | The reviewed opt-in prepackage hook read the actual manifest once after Runner END; its URL/title-free report proves all 24 ordered pages have source-native JPEG provenance, verified white backdrop, native tile-replay lossless WebP, no fallback, and consistent identity. The regular packager still removed its temporary output (`source_removed=true`). |
| Repeat Batch artifact equality | PASS | The second run's 24 uncompressed WebP members are byte-identical to the first Batch ZIP; its first 12 pages are also byte-identical to the manual JSON run. Both archives pass CRC, Catalog SHA/size, and VP8L lossless checks. |
| Existing genre fallback behavior | PASS | The Batch used ordinary existing metadata fallback, with no classification override or metadata rewrite. The isolated synthetic watchlist supplied only its own work label. |
| Existing Catalog/Watchlist/output preservation | PASS | Discovery, Catalog, Batch output, diagnostics and library were all under the ignored fresh `output/piccoma_performance/phase07_20261010_stagec_live_01/` tree. Repository Watchlist and ordinary output were not used. |

The isolated direct Discovery plan and bounded CLI outputs include a public canonical viewer URL in ignored local files; the tracked report omits the URL. No credentials or signed URLs were persisted in research evidence.

## Performance observations

For 20 complete normal p2..p11 cycles per arm, mean page-cycle time was 3.601 seconds for object snapshots and 2.743 seconds for JSON snapshots, a measured reduction of 0.857 seconds/page (23.8%) in these runs. The six native trace RPCs fell from 1.006 seconds/page to 0.142 seconds/page; JSON decoding added 0.034 seconds/page. The JSON string remained approximately 390,450 characters per snapshot. Method-6 WebP encoding stayed at about 0.51 seconds/page mean, while the measured 200 ms pacing and ~0.64-second stability wait remained essentially unchanged.

Manual CLI exit status 1 is expected for the bounded probes. Both Batch exit statuses were 0 and were independently cross-checked with the Catalog Runs' explicit `end`, page counts, status records, archives, and CRCs.

## Tests and instrumentation

- `python -m unittest discover -s research/piccoma-performance -p 'test_phase07_*.py' -v` — **13 passed**.
- `ruff check` for the Stage C research launcher, manifest audit, hook and offline tests — **passed**.
- `py_compile` for the Stage C research launcher and hook modules — **passed**.
- Manual live run profiler added no browser snapshot calls; each run had exactly six per page. The JSON arm had one Python JSON decoder timing per snapshot. The replay-JavaScript measurement hook was disabled.
- Existing stock CLI behavior and production source were not changed by the tester. The manifest audit hook is under `research/` only and remains opt-in; only the final dedicated verification Batch used it.

## Remaining gate

No further live run is required. The final research-only manifest hook was reviewed before use, and the fresh bounded Discovery plus Batch run passed the manifest, END, Catalog, ZIP, cleanup, and equality audits. No additional object/JSON benchmarking is needed.

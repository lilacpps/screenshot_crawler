# ebookjapan purchased-only Discovery - current implementation

> **Current status (2026-11-08):** Stage 00/01 are accepted. Stage 02 is VERIFIED / ACCEPTED for the one-work Angel 10 D baseline `core-run-angel10-20261107-215910-399914`: actual native END after 287 ordered pages, retained exact prepackage manifest, isolated ZIP, 20 artifact checks and 9 visual samples. Stage 03 source-research exit is accepted and the scoped D rendered-PNG policy is adopted under revision `ebookjapan-owned-rendered-png-v1-20261108`. The adopted rendered capture class is `D`; source-native A/B/C remain `NOT_VERIFIED`, with source-native class `UNASSIGNED`. The Muda 16 live validation was one cover capture only, not a full-book run. Toolbar hiding remains supported only at the observed 1906x986 viewport with exact backing/rect pairs for Angel 10 (816x1200), Muda 1 (1088x1600), and Muda 16 (1120x1600); other geometry fails closed. Stage 04 CLI registry wiring is implemented locally and awaiting independent review; no live Batch run has started. Stage 05 live E2E is not started.
>
> Five Pillow page-part samples across four profiles differ from stable D outputs: Muda 1 cover 822,567/max delta 2; Muda 1 middle 88,953 and 87,501/max delta 2; Angel 10 cover 510,602/max delta 2; Muda 16 cover 318,401/max delta 2. On Angel 10 cover, RGB atlas copy and default Blob -> `createImageBitmap` -> `VideoFrame` replay matched the Pillow candidate, not D (510,602/max delta 2). The current-realm ImageDecoder I420-to-RGBA candidate differed by 675,038/max delta 44; cause unknown. Literal HTMLImage replay raised `EncodingError` before copy; phase and cause were not recorded. The Pillow fallback differed by 510,602/max delta 2. Exact PNG/VP8L roundtrips establish encoding only.
>
> A separate format-only Blob -> `createImageBitmap` -> `VideoFrame` probe observed BGRX at 1024x1408. A descriptor-only check created ordinary 1x1 HTML and Offscreen scratch contexts, but did not invoke the five undefined pixel/export APIs and read no pixels. Successful Angel/Muda16 hit records had raw title mismatch, NFKC/whitespace equality, and other fixed hit gates true; earlier failures without these fields remain unattributed. These results do not promote A/B/C. No source bytes or raw URLs are retained. The sanitized version 2 ledger is [`source-native-evidence.json`](../output/ebookjapan_experiment/phase03/source-native-evidence.json).
>
> The bounded Muda 16 cover capture was made from a fresh Page that stayed at physical 1906x986 / DPR 1.5 through owned Reader initialization (no pre-Reader viewport write). It began at visible 1/225 with a ready 1120x1600 canvas, then the unchanged production capture path hid the toolbar and fit to 2240x1600 / DPR 1. PNG SHA-256 `2fe49c2b2f67f60f13a9dc0bb595baeb60980119a9f67ede6f8c36461f200f09` was independently decoded and visually QA-passed without UI or clipping. The post-hide top-level native counter was `None`; the cached part counter remained the pinned pre-hide `1`. The exact evidence and audit references are in the current ledger. Catalog before/after hashes matched `7fce06b7e223c0c7abd7d48afdc7ec78dccb95b6e27b60317977971e048b6a1b`; the one owned Page closed successfully. This probe did not test END, create a ZIP, or establish A/B/C.
>
> Two earlier probe-harness attempts produced no PNG and are not production-capture failures or passes. The first wrote the 1906x986 viewport before Reader initialization, observed DPR change from 1.5 to 1.0 and 840x1200 backing, then stopped on a harness check reading layout fields from the wrong frame projection; the quality cause is unknown and no 840x1200 profile was accepted. The second used the natural DPR/backing and production capture returned valid bytes, but the harness incorrectly expected a visible top-level counter after toolbar hide and did not retain the PNG. The corrected run above preserves `None` for the hidden live counter and `1` in the cached pre-hide part metadata.
>
> Stage 04 CLI registry wiring is implemented locally and awaits independent review; no live Batch run has started. Stage 05 has offline audit preparation only; live E2E remains not started.

## Scope

`EbookJapanDiscoveryAdapter` supports authenticated Full Discovery for ebookjapan
series listings and emits only explicitly purchased books. It reuses the
existing Discovery registry, registration resolver, `DiscoveryService`,
Catalog reconciliation, GUI Full registration flow, and shared CDP
BrowserSession/Playwright Page. The adapter never writes Catalog state itself.

The registration URL is exactly
`https://ebookjapan.yahoo.co.jp/books/all/<positive-series-id>/`, with no
query, fragment, alias, foreign host or ambiguous redirect. Registration leaves
title unknown so the existing manual label confirmation supplies a new Work
title. Incremental Discovery and bounded scope are unsupported and fail before
Catalog reconciliation; unsupported incremental is not coerced to Full.

## Full listing and ownership

The adapter requires an exact series path, structural signed-in account shell
with `/mypage/` link, native total, selected `1巻から` order, complete stable
bottom listing IDs/count, matching DOM and layout order, and no list-local
pagination/load-more control. It buffers all card metadata and validates the
whole listing before the first yield. It first parses only the card structure
from the exact HTTP 200, non-redirect main-document response returned by
`page.goto`. The HTML parser accepts up to 32 MiB and retains each card's official path and a static
purchase-bit witness; raw HTML and inline JSON are discarded after parsing.

Each card is classified independently. One visible card-local `購入済み`
without a price, basket action, or conflicting right is owned. One positive
visible price plus one card-local basket action and no owned/conflicting badge
is explicitly not owned. Hidden, missing or conflicting evidence aborts the
whole run as unknown. Static purchase bits are a hydration witness, not a
complete rights classification: an unowned static bit cannot prove
`NOT_OWNED`; only hydrated positive price text and one visible basket action
can do that. Before emission, the entire static ID/order/bit set must match the
authenticated hydrated listing, including each card's tri-state evidence.
Unknown, duplicate, hidden/template/noscript, partial, reordered or mismatched
source structure fails closed. Only owned records are emitted, with official product
A-ID external IDs, exact card product URLs, `access_mode=owned`,
`available=True`, and oldest-first global display positions. Volume labels are
only populated from explicit title text; missing numbering remains unknown.
All cards and positions plus the selected owned subset are attached using the
existing `CompleteListingInventory` hook.

The AccessGuard is site-local to `ebookjapan.yahoo.co.jp`, stops on 403/429,
challenge or CAPTCHA, and is checked after the final snapshot before inventory
or record emission. The adapter does not open a Reader or click purchase, cart,
trial or other rights-changing controls.

## Verified behavior

On 2026-11-07, isolated production CLI Full Discovery completed for:

| Listing | Full inventory | Owned records | Re-run |
| --- | ---: | ---: | --- |
| Angel | 10 cards | 1 at global position 10 | 1 known; IDs/status preserved |
| Mudazumo | 16 cards | 16 at positions 1–16 | 16 known; IDs/status preserved |

The isolated Catalog contains 17 owned/available Sources and 17 pending Items;
no Batch or Crawl has run. The live run used only the phase01 Catalog and
Watchlist under `output/ebookjapan_experiment/phase01/`.

The original server response was also inspected in memory using a regular
shared-CDP GET; only a structural summary was saved. The exact product paths
matched dynamic Full Discovery. Angel positions 1–9 each had one static price
element and no exact purchased span; position 10 had one exact purchased span
and no price element. Position 10 also had one unrelated additional tag span.
Mudazumo's 16 cards each had one exact purchased span and no price element;
position 16 also had one unrelated additional tag span. The complete static
bitsets and product order matched dynamic Full Discovery. Static price elements
did not contain positive price text, so they are not a not-owned authority.
The original responses did not include the account shell or a native total
string; they did include the selected oldest-first sort control. Dynamic
authentication, native total/sort and visible card-right checks remain
mandatory. The bounded `registration_document` diagnostic ended in
`ObservationUnavailable` with a failed document request and no HTTP status; this
did not trigger AccessGuard and is unavailable transport evidence, not a site
rejection or proof that the server response lacks listing content.

## Source-capture boundary

The first-party PNG response observed during Stage 00 is not bound to a current
page. A (original bytes), B (lossless reconstruction) and C (source-derived
pixels) are unproven. Two D compositor cover controls (Angel and Mudazumo) are
retained only in the ignored phase02 research output, along with 287 D page
artifacts from a run that failed before END; these are not an adopted source
capture method. No
DRM/access-control bypass or decryption was attempted. An offline Site Policy
candidate is now prepared: only an available `owned` Catalog source is planned
as `direct`, with no quota consumption. It is not registered in CLI, Batch or
GUI and is not live-verified; Catalog state does not replace current Reader
ownership checks. ZIP creation and end-to-end acquisition remain later stages.
See `runbooks/ebookjapan-owned/PROGRESS.md` for the current gate.

## Stage 03 method ledger and local preparation

`output/ebookjapan_experiment/phase03/source-native-evidence.json` is the current sanitized version 2 evidence ledger. It separates metadata-only runs, exact-response format observations, source-derived pixel candidates, and the accepted Stage 02 D control. It records the adopted production capture class as `D` while keeping `source_native_proof_status=NOT_VERIFIED` and `source_native_capture_class=UNASSIGNED`; historical source-derived candidates remain `UNASSIGNED`.

Current tested source profiles include Muda 1 cover/middle, Angel 10 cover, and Muda 16 cover. Bound responses are WebP VP8 tile/atlas sources; the representative source-to-target ROI maps had 256 operations for Angel and Muda 1, and 240 for Muda 16. Every tested Pillow candidate differs from both stable D samples, despite exact PNG/VP8L roundtrips. The Angel ImageDecoder/VideoFrame RGBA candidate also differs; no mismatch cause has been established. Candidate PNGs and D reference images remain quarantined in ignored phase03 run directories; response bodies and raw source URLs were not retained.

Representative metadata reached Angel 10 middle 116/287, Angel 10 final 287/287 after a normal Home action on the repinned document, Muda 1 middle 96/193 and final 193/193, and Muda 16 cover 1/225. Muda 16's earlier cohort-overflow/unmatched-response run remains UNKNOWN, separate from its later exact-response positive metadata recheck. These metadata results do not prove page pixels. Subsequent Angel 10 cover experiments completed the BGRX-to-RGBA atlas copy and default Blob/createImageBitmap/VideoFrame replay; both matched the Pillow candidate but differed from stable D by 510,602 pixels/max delta 2. Literal HTMLImage replay raised EncodingError before copy (phase and cause unrecorded), while the separate default bitmap-frame replay completed and had the same Pillow/D mismatch. No method is adopted.

The ordinary scratch API descriptor observation created blank 1x1 HTML/Offscreen contexts to inspect descriptors and receivers, invoked none of the five undefined pixel/export APIs, and read no pixels. Successful normalized-title hit records demonstrate `raw=false`, `NFKC/whitespace=true`, with the remaining recorded hit booleans true; this is diagnostic evidence, not a production adapter change. Full per-sample details, JSON hashes, and explicit A/B/C not-done limits are in the version 2 ledger. Stage 03 research exit is accepted and the scoped D rendered-PNG policy is adopted. No A/B/C source method is adopted; A/B/C remain unverified.

## Stage 02 bounded Viewer observations and accepted one-work D baseline

The probe entered Angel position 10 (`A000083590`) and Mudazumo global position
1 (`A000039104`) through the exact live owned card. For each, the Reader title
matched the card title, the route remained a purchased Viewer route, and the
entry counter was 1/N. The observed totals were Angel 287 and Mudazumo 193.
Each Reader had the same count of `.comic-viewer__page-slot` nodes as its
native total. A per-Page WeakMap assigned 287/193 unique ephemeral DOM-node
IDs; their entire order remained stable across three samples, one normal
left-edge step and restoration. These IDs are diagnostic references only and
are not site-native page IDs. No numeric page/slot/index/position attribute was
present on the sampled Angel slots.

Both viewers use the observed horizontal RTL spread layout. From counter 1/N,
one normal left edge followed by a center tap on the visible page canvas showed
counter 2/N. Two part canvases were then visible. Physical right-to-left slot
order was Angel DOM ordinals 285 then 284, and Mudazumo ordinals 191 then 190.
No formula maps these ordinals to page numbers. A normal opposite-edge action
and a guarded center reveal returned both Readers to the original 1/N counter,
visible slot/canvas node identities and geometry. The `role=status`
`.comic-viewer-loading` element remained positioned outside the viewport; its
presence is not treated as current-page loading state.

A temporary passive context/draw observer ran on a fresh probe-owned Mudazumo
position-one Reader. It recorded successful full-size `drawImage` transfers
from 1088×1600 `ImageBitmap` objects into 1088×1600 canvases, plus separate
1088×1600 HTML-canvas transfers into hidden 1088×1 strips. The selected visible
canvas was joined to its ephemeral DOM slot/canvas identities and hook ID.
These observations do not establish complete page paint, clipping, or source
provenance.

Natural `getImageData` through the already observed non-null 2D context on the
selected 1088×1600 canvas returned browser `SecurityError`
(`readback-security-blocked`) on the first attempt. No raw canvas bytes or data
URL were retained. This establishes a readback restriction for this specific
canvas and method; A/B/C remain unknown, not impossible. That probe did not
turn a page and closed its owned Reader at entry 1/193.

A separate fresh entry probe used one previously observed safe content-center
tap after a page-one/nonterminal check to hide the Reader toolbar. On its
probe-owned Page only, the viewport changed from 1906×986 to 2176×1600. The
same anchored canvas element changed from a 300×150 placeholder to a naturally
drawn 1088×1600 canvas rendered at CSS 1088×1600. Two
`Locator.screenshot(scale="css")` samples separated by animation frames
decoded to 1088×1600 with identical RGBA SHA-256; route/document, all 193 slot
element references/order, selected slot/canvas IDs, geometry, scroll and
successful observed transfer generation remained stable. Visual inspection
confirmed the full cover artwork with no toolbar overlay. The isolated file is
`output/ebookjapan_experiment/phase02/d-compositor-mudazumo1-entry-part1-css.png`.
It is a D compositor control for one cover only, not full-book coverage, END,
or A/B/C source proof. The viewport was restored and the owned Reader closed at
its anchored 1/193 entry.

The final Stage 02 runtime/test tree passed 115 affected tests (24 adapter unit + 91 local Chromium Viewer/Runner), 0 skipped. An independent Reviewer passed 37 browser and 4 geometry cases; runtime/test review is VERIFIED / BLOCKING 0. The finite-outline refinement remains a bounded supported Chromium case, not a universal paint proof, and the prior IMG rejection has not been explained. At that Stage 02 checkpoint, the accepted production result was the one-work Angel 10 D baseline recorded below; A/B/C remained unproven and Stage 04 CLI/Batch registration had not started.

The first isolated production-adapter live attempt used the phase01 Catalog read-only
and a new shared-CDP Page. The canonical series listing returned HTTP 200, with
native total 10, oldest-first order, and the exact visible owned position-10 card.
On this Page the account shell was initially absent, then appeared after about
899 ms as one visible `.account__user` with one `/mypage/` link; no account text
was read. The adapter entered the exact purchased Angel Reader and pinned its
visible title and 287-slot inventory, but stopped before capture with
`UnknownPageStateError: ebookjapan canvas did not redraw at its native CSS
viewport`. A bounded follow-up found the same pinned slot/canvas and backing
size, unchanged drawGeneration/successfulDraws at 1/1, no reset or observer
errors, and CSS geometry changing from 670.48x986 to 816x1200. The toolbar was
still visible; no PNG or slot coverage was produced. The local fit gate now has
two reviewed paths: accept the exact unchanged full-draw signature for a CSS-only
fit with all pins/health fields intact and CSS/backing 1:1, or accept a new
complete draw only with increased cumulative successfulDraws, positive current
generation, and reset/observer failures absent. A reset without redraw remains
rejected. A later isolated **hide-before-fit** diagnostic at the measured 1906 by 986 entry viewport hid the toolbar without changing the pinned Angel cover, then fitted the same canvas and produced one decoded 816 by 1200 D PNG (SHA-256 `ab1a2462559bdf6875885de5a520b6ccd38c34d317f6607767b17b7fd0706227`). Root visually QA-passed the upright full cover without UI. Evidence: `output/ebookjapan_experiment/phase02/live-angel10-first-20261107-155246-687880/`. A separate fresh owned-card entry verified native 1/287 afterward. This was a single D diagnostic frame only. A later production CoreRunner run saved 287 ordered D page artifacts but failed closed before verified END at `outset-painted-element:img`; no RunResult completion or ZIP was produced. See the terminal/baseline observations below.

`capture_page()` produces a D compositor PNG; it is not an A/B/C source capture. Captured pages/parts record `capture_class=D`, `fallback_reason_code=SOURCE_NATIVE_PROOF_NOT_ESTABLISHED`, and `ebookjapan_capture_policy_revision=ebookjapan-owned-rendered-png-v1-20261108`; `source_provenance` remains `UNKNOWN` and `native_page_number=None`. It hides the toolbar before fitting only the task-owned Page viewport. The guarded center action is enabled only at the observed 1906 by 986 entry viewport and one of three exact backing/rect pairs: Angel 816x1200 or Muda 1 1088x1600 at the 0.68 CSS shape, and Muda 16 1120x1600 at the 0.70 CSS shape. Other visible-toolbar geometry fails before click. The ordinary shared-CDP new-page viewport is not normalized here, so a nonmatching initial viewport remains unsupported. Fitting before hiding is prohibited because the fitted cover center advanced into the next spread. The fit keeps either the exact unchanged full-draw signature or a fresh complete draw, while rejecting reset without redraw. The pinned frame must remain stable across two animation frames. Before and after each sample the unchanged D surface guards reject clipped/off-viewport canvases, unsafe canvas/ancestor transforms, opacity, filter, mask/blend, generated pseudo-elements, and painted overlaps from a bounded 20,000-node inventory; a 5x5 `elementFromPoint` grid is an additional occlusion check. A narrow local qualifier permits only an unrelated, complete HTML image with a simple solid finite outline when exact client/bounding rectangles agree, the image and all ancestors satisfy the supported HTML/no-effect/translation-only checks, DPR is at least 1, and the outline bounds expanded by width + absolute offset + 2 CSS pixels are strictly disjoint from every target canvas. Contact, target/ancestor outlines, unknown effects, and unsupported geometry still fail closed. This is a bounded supported Chromium case, not a universal CSS paint proof. The image that triggered the earlier live rejection has not been identified or shown to meet this qualifier; the refinement is not live-verified. Two CSS-scale samples must still decode to equal RGBA and preserve route/document/slot/canvas/draw state; all spread parts return atomically. Metadata records run-local slot IDs, physical right-to-left order, `native_page_number=None`, an actually visible native counter only, and `source_provenance=UNKNOWN`. Core generic locator fallback remains blocked.

Normal advance uses the observed non-interactive left-edge page region. Before clicking, the current implementation rechecks committed slot/canvas nodes, backing dimensions, CSS rectangles, draw geometry, route, document, layout, and observer state in the same DOM sample used to bind the x=12 hit. Drift, an unpinned hit, interactive/modal/terminal ancestors, or unknown state fail before click. END requires complete ordered coverage plus one of two observed scoped profiles: Angel's exact terminal message and exhaustive scoped action partition, or Mudazumo's pinned `.book-last` shell/cell and observed module/header action partition. Inactive hidden roots remain LOADING; visible malformed, modal, unknown, or extra actions remain fatal. Other D surface guards and atomic spread capture remain unchanged by the narrow outline exception.

Production CoreRunner history includes several distinct runs. Historical `core-run-angel10-20261107-200001-949259` reached END and created a ZIP but lost its current manifest during packaging; it remains PARTIAL, with an old/new comparison of 285/287 positions exact and 23 differing pixels. Historical `core-run-angel10-20261107-202212-410192` failed closed at page 285 with `outset-painted-element:img`. A later bounded 287/287 qualifier sample found zero candidate IMG nodes and did not identify the prior offender. The accepted current run is `core-run-angel10-20261107-215910-399914`: 287 ordered D pages reached actual END and produced a completed isolated ZIP with the exact prepackage manifest retained. The manifest SHA-256 is `3344d568e48089ec157e148cb20e30345edb71fcf7deae6e42b3c0a5cf2c4237`; the ZIP SHA-256 is `55d3e7298d1c9278f75e19e6540d26f940accd2f9c8c506dc303a5939f1d3933` (209,716,162 bytes). Tester passed 20 artifact checks and 9 visual samples; Reviewer and Lead accepted this one-work D baseline. Catalog before/after SHA matched at `7fce06b7e223c0c7abd7d48afdc7ec78dccb95b6e27b60317977971e048b6a1b`; owned Page close was confirmed 1/1. The run proves neither A/B/C nor a general capture policy, and does not resolve the earlier IMG failure.

A separate one-entry source-lineage probe installed a native-pass-through
main-frame `createImageBitmap` observer and grouped normal Page response
metadata. No main-frame `createImageBitmap` call occurred. No `Response.blob`
conversion call was recorded; whether that wrapper was available is not
captured in this evidence. The same Reader Page saw 10 `image/avif` and
one `image/webp` HTTP 200 responses from the observed ebookjapan Akamai image
host, but none was tied by object identity to the selected canvas's ImageBitmap
source. No response body was read. The listener stopped after 512 response
events and counted 528 additional events; this incomplete inventory does not
prove source absence. Worker processing was not instrumented. A remains
unproven at that Stage 02 checkpoint; A/B/C source work was carried into Stage 03 and is summarized in the current method ledger above. A later bounded OffscreenCanvas
observer identified one `transferToImageBitmap` output whose ephemeral
ImageBitmap identity matched a draw into the selected Mudazumo canvas. The
OffscreenCanvas draw history had exceeded its 64-call cap, so the bitmap's
source drawing and any response-byte origin were not proven. This does not
establish A, B or C. Exact sanitized evidence is in
`stage02-mudazumo1-source-lineage.json` and `PROGRESS.md`.

All Stage 02 artifacts are isolated under `output/ebookjapan_experiment/phase02/`. They include the accepted current manifest/ZIP, historical 287-page failed-closed output, two D cover diagnostics, the 200001 ZIP with lost current manifest, and the 202212 partial output. The current manifest was retained before packaging; no raw canvas readback bytes or source response bodies were retained. The accepted baseline is limited to Angel 10 and D capture. A/B/C provenance and final source-native capture policy remain unverified.

The previous affected selection passed 115 tests (24 adapter unit + 91 local Chromium Viewer/Runner), 0 skipped; its independent review passed 37 browser and 4 geometry cases. The current D-policy affected selection passed 124 tests, 0 skipped; independent review verified 13 cases and the Lead accepted the scoped D policy. The finite-outline matrix tests only the bounded supported shape and keeps contact/reach, unsupported effects/transforms/ancestors, and DPR below 1 fail-closed. Existing scoped END profiles, navigation atomicity, neutral CoreRunner ZIP/failure cases, and artifact invariants remain covered. `ruff check src tests` passed. The task-path `git diff --check` passed; a whole-tree check reports only the user's pre-existing `watchlist.yaml` trailing whitespace. Stage 03 diagnostic history and current C/A results are summarized above; no A/B/C method is verified. The browser-default decoder variant passed 38 local synthetic checks and one live candidate attempt failed before D comparison or artifact output. A/B/C and source-native capture remain unverified.

## Stage 01 verification

- Unit parser/inventory tests: 34 passed.
- Browser-backed listing/history tests: 11 passed, including the 2.6-second
  temporary owned-to-price-to-owned hydration case, a complete zero-owned
  listing and an unresolved ownership mismatch that preserves prior Catalog
  availability.
- Affected shared Discovery, CLI, registration, worker and GUI tests: 393
  passed. Ruff and `git diff --check` passed.
- Broad full-suite validation is incomplete. A 7,533-test run timed out in
  pytest-asyncio teardown for `test_comicfuz_other_episode_route_fails_closed`
  while waiting in Windows IOCP polling. The 7,532-selected run excluded only
  that node and stopped at the first failure: 873 passed, 1 failed, 1
  deselected, 107 warnings; the Hanayume failure was WinError 3 creating a
  260-character path under the long temporary base. That exact node passed
  once under the verified short `.tmp/ej1h` base (230-character candidate
  path). This fits a path-length cause but does not prove it. The isolated
  ComicFuz module passed 69 tests, including the teardown node; ComicDays
  passed 136. No full-suite PASS is claimed. See the phase01 diagnostic JSON
  and log in `output/ebookjapan_experiment/phase01/`.

### 2026-11-07 production baseline and terminal probes

The earlier isolated production CoreRunner run `core-run-angel10-20261107-162050-596703` saved 287 ordered D PNG artifacts and then failed closed with `UnknownPageStateError: ebookjapan D canvas surface is unsafe (outset-painted-element:img)`. The exact failing method was not captured; attributing it to terminal advance is an inference from the completed-page Runner flow. That historical run produced no ZIP, completed RunResult, or Catalog write. Root independently verified decoded format/dimensions, source fingerprints, RGBA hashes, manifest order, and part grouping for all 287 files; this validates artifact integrity only. The later manifest-retained 215910–399914 run is the accepted one-work D baseline described above.

A subsequent isolated full-baseline attempt (`core-run-angel10-20261107-184139-316247`) historically stopped before `CrawlerRunner.run` because Playwright `BrowserType.connect_over_cdp` timed out after 180 seconds while initializing the shared browser. At that time a bounded Node WebSocket did receive a read-only `Browser.getVersion` response; no Page was created. A separate 10-second attach-only check, including `no_defaults=True`, also timed out. On 2026-11-07 at 19:53:57 JST another 10-second check ended in `TimeoutError` after 10.369 seconds and cleanup ended STOPPED. The user later restarted shared Crawler Chrome, after which Playwright attachment recovered and the 200001 and 202212 CoreRunner attempts above were performed. The cause of the earlier attach stall remains unknown.

A separate owned Angel 10 normal-navigation probe reached one exact viewport-visible terminal marker after the final left-edge advance, with 287 frozen slots and zero visible page slots. Twelve visible actions shared the `.book-last-dead-end__inner` root: one review action, one coupon banner action, and ten recommendation-module actions. No recommendation destination was opened. The local implementation has an exact structural partition for this profile. The 200001 run later reached END but remains PARTIAL because its current manifest was lost; the later 215910–399914 run is the accepted manifest-retained one-work D baseline.

A separate owned Mudazumo 1 probe reached 193/193, made one validated normal edge advance, then remained `loading` for its 20-second bound with route stable, zero visible slots, and toolbar visible. A metadata-only snapshot found a distinct `.book-last` root with review, next-item, CTA, banner, and recommendation modules. Twelve visible actions were recorded; no CTA or recommendation was clicked; fresh entry restored 1/193. The local implementation has a separate scoped classifier for this observed profile. This was a terminal research probe, not a full Mudazumo capture/Batch run. No Batch, repeated Full Discovery, or Stage 05 live E2E is claimed.


## Stage 04 CLI registry wiring and Site Policy

`EbookJapanSitePolicy` is registered in the CLI Batch policy registry and remains a Catalog planning filter, not proof of current rights. It plans `direct` with `consumes_quota=False` only for `site=ebookjapan`, `available=True`, and `access_mode=owned`; all other states are ineligible, with no quota/resource or grant-only path. The live adapter still rechecks the exact owned book before Reader entry. The GUI policy inventory already discovers the class through `site_policies.__all__`; no GUI-specific registration change was needed. Manual Crawl and Batch adapter registries now include `EbookJapanAdapter`, while Discovery remains separately registered. The affected local CLI/policy/inventory/worker/presenter/GUI selection passed 207 tests with 0 skips. Stage 04 status is **LOCAL CLI REGISTRY WIRING IMPLEMENTED / INDEPENDENT REVIEW PENDING / NOT LIVE**; no Batch execution has run.

## Stage 05 offline E2E audit preparation

An ignored synthetic audit preparation exists under
`output/ebookjapan_experiment/e2e-validation/`; it is not a live E2E run. After
the aggregate item-status fix, the independent Reviewer passed 19 audit cases
(2 positive, 17 negative); the Tester passed 2 positive and 8 negative cases,
and 4 existing validator-negative cases passed. This verifies only the offline
audit preparation. Page coverage, source proof, repeated Full Discovery,
repeated Batch, production E2E and ZIP remain `NOT_VERIFIED`; the source-proof
schema is `NOT_DEFINED`, and Stage 05 live verification has not started.

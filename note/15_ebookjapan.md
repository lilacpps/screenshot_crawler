# ebookjapan purchased-only Discovery — current implementation

> Current status (2026-11-07): Stage 00 and Stage 01 are accepted. Stage 02 is VERIFIED / ACCEPTED for the single Angel 10 D baseline `core-run-angel10-20261107-215910-399914`: 287 ordered pages reached actual END, with a retained prepackage manifest, completed isolated ZIP, 20 independent artifact checks and 9 visual samples. The current Stage 02 suite passes 115 affected tests (24 adapter unit + 91 local Chromium), 0 skipped; independent review passed 37 browser and 4 geometry cases. This does not establish A/B/C or a general capture policy. Stage 03 has three bounded Muda 1 metadata-only attempts. The latest reached 1/193 and recorded a selected canvas-to-ImageBitmap transfer/Offscreen epoch graph chain with 256 draw operations linked to one same-document HTTP 200 WebP response, but observer health had two additional unidentified context-method descriptor mismatches outside the six critical keys; their drawing relevance is unknown. Evidence is `UNHEALTHY_METADATA_ONLY`, `NOT_VERIFIED`, `UNASSIGNED`; no response body, pixels, or screenshot were read. A/B/C remain unproven. Stage 04 remains offline policy only/not integrated; Stage 05 live E2E and Batch remain unverified.


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

A/B/C remain unproven. Stage 00 observed a first-party PNG response of 364,375 bytes that was not bound to the current page. Stage 02 observed AVIF/WebP response metadata and one OffscreenCanvas `transferToImageBitmap()` object joined to a natural selected-canvas draw, but did not bind the bitmap source to an ordinary response or read response bytes. The earlier observer’s call cap had dropped relevant source history. These observations do not establish A.

B has not been evaluated because no exact encoded source and complete source/tile lineage were bound to a page. Natural `getImageData` on the selected main canvas returned `SecurityError`, which blocks only that exact readback path; no bypass, decryption, or DRM circumvention was attempted. C remains untested. The accepted Stage 02 result is a one-work D compositor baseline, not source-native proof or adoption of D as the final capture policy.

Offline preparation under `output/ebookjapan_experiment/phase03/` includes a new copied observer, `offscreen_epoch_observer_source_lineage_20261107.js`, and `verify_offscreen_epoch_source_lineage_20261107.py`. Their **60 local synthetic checks passed**, and the offline hook review is accepted. They exercise connected current-document lookup IDs separately from natural target-canvas draw IDs (including detached-at-draw state), immutable OffscreenCanvas epoch/bitmap joins, exact private `(objectId,currentSrc)` pairing, same-document response uniqueness negatives, fixed UNKNOWN for present `getContext` options, operation/time/byte bounds, privacy, and native-call semantics. This does not demonstrate the site's actual source chain.

`source-native-evidence.json` remains `proof_status=NOT_VERIFIED` and `capture_class=UNASSIGNED`. The copied health diagnostic verifier passed 64 local checks and the copied metadata harness passed 17 local self-checks; these validate diagnostic handling only. Three bounded Muda 1 metadata-only live attempts were made. The first ended UNKNOWN during page-only reload; the second found the observer not installed after reload; the third reached counter 1/193 and recorded canvas object 13 received ImageBitmap object 12, produced by transfer sequence 5 from HTMLImage source object 11, with 256 successful draw operations linked to one same-document HTTP 200 WebP response (17 image-response records total, no overflow). Observer health remained incomplete: six critical descriptors matched, but two additional unidentified context-method descriptors mismatched outside the six critical keys; their drawing relevance is unknown. The evidence is `UNHEALTHY_METADATA_ONLY`; no response body, source pixels, or screenshot was read, and no codec or capture-method conclusion was made. A/B/C remain unproven. Evidence: `output/ebookjapan_experiment/phase03/metadata-muda1-20261107-234730-600867.json`.

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

The final Stage 02 runtime/test tree passed 115 affected tests (24 adapter unit + 91 local Chromium Viewer/Runner), 0 skipped. An independent Reviewer passed 37 browser and 4 geometry cases; runtime/test review is VERIFIED / BLOCKING 0. The finite-outline refinement remains a bounded supported Chromium case, not a universal paint proof, and the prior IMG rejection has not been explained. The accepted production result is the one-work Angel 10 D baseline recorded below; A/B/C remain unproven and CLI/Batch registration remains incomplete.

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
errors, and CSS geometry changing from 670.48?986 to 816?1200. The toolbar was
still visible; no PNG or slot coverage was produced. The local fit gate now has
two reviewed paths: accept the exact unchanged full-draw signature for a CSS-only
fit with all pins/health fields intact and CSS/backing 1:1, or accept a new
complete draw only with increased cumulative successfulDraws, positive current
generation, and reset/observer failures absent. A reset without redraw remains
rejected. A later isolated **hide-before-fit** diagnostic at the measured 1906 by 986 entry viewport hid the toolbar without changing the pinned Angel cover, then fitted the same canvas and produced one decoded 816 by 1200 D PNG (SHA-256 `ab1a2462559bdf6875885de5a520b6ccd38c34d317f6607767b17b7fd0706227`). Root visually QA-passed the upright full cover without UI. Evidence: `output/ebookjapan_experiment/phase02/live-angel10-first-20261107-155246-687880/`. A separate fresh owned-card entry verified native 1/287 afterward. This was a single D diagnostic frame only. A later production CoreRunner run saved 287 ordered D page artifacts but failed closed before verified END at `outset-painted-element:img`; no RunResult completion or ZIP was produced. See the terminal/baseline observations below.

`capture_page()` produces a D compositor PNG; it is not an A/B/C source capture. It hides the toolbar before fitting only the task-owned Page viewport. The guarded center action is enabled only at the observed 1906 by 986 entry viewport and measured cover rect; other visible-toolbar geometries fail before click. Fitting before hiding is prohibited because the fitted cover center advanced into the next spread. The fit keeps either the exact unchanged full-draw signature or a fresh complete draw, while rejecting reset without redraw. The pinned frame must remain stable across two animation frames. Before and after each sample the unchanged D surface guards reject clipped/off-viewport canvases, unsafe canvas/ancestor transforms, opacity, filter, mask/blend, generated pseudo-elements, and painted overlaps from a bounded 20,000-node inventory; a 5x5 `elementFromPoint` grid is an additional occlusion check. A narrow local qualifier permits only an unrelated, complete HTML image with a simple solid finite outline when exact client/bounding rectangles agree, the image and all ancestors satisfy the supported HTML/no-effect/translation-only checks, DPR is at least 1, and the outline bounds expanded by width + absolute offset + 2 CSS pixels are strictly disjoint from every target canvas. Contact, target/ancestor outlines, unknown effects, and unsupported geometry still fail closed. This is a bounded supported Chromium case, not a universal CSS paint proof. The image that triggered the earlier live rejection has not been identified or shown to meet this qualifier; the refinement is not live-verified. Two CSS-scale samples must still decode to equal RGBA and preserve route/document/slot/canvas/draw state; all spread parts return atomically. Metadata records run-local slot IDs, physical right-to-left order, `native_page_number=None`, an actually visible native counter only, and `source_provenance=UNKNOWN`. Core generic locator fallback remains blocked.

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
unproven; B and C have not yet been evaluated. A later bounded OffscreenCanvas
observer identified one `transferToImageBitmap` output whose ephemeral
ImageBitmap identity matched a draw into the selected Mudazumo canvas. The
OffscreenCanvas draw history had exceeded its 64-call cap, so the bitmap's
source drawing and any response-byte origin were not proven. This does not
establish A, B or C. Exact sanitized evidence is in
`stage02-mudazumo1-source-lineage.json` and `PROGRESS.md`.

All Stage 02 artifacts are isolated under `output/ebookjapan_experiment/phase02/`. They include the accepted current manifest/ZIP, historical 287-page failed-closed output, two D cover diagnostics, the 200001 ZIP with lost current manifest, and the 202212 partial output. The current manifest was retained before packaging; no raw canvas readback bytes or source response bodies were retained. The accepted baseline is limited to Angel 10 and D capture. A/B/C provenance and final source-native capture policy remain unverified.

The final affected selection (`tests/unit/test_ebookjapan_adapter.py` and `tests/integration/test_ebookjapan_viewer_browser.py`) passed 115 tests (24 adapter unit + 91 local Chromium Viewer/Runner), 0 skipped; an independent Reviewer separately passed 37 browser and 4 geometry cases. The finite-outline matrix tests only the bounded supported shape and keeps contact/reach, unsupported effects/transforms/ancestors, and DPR below 1 fail-closed. Existing scoped END profiles, navigation atomicity, neutral CoreRunner ZIP/failure cases, and artifact invariants remain covered. `ruff check src tests` passed. The task-path `git diff --check` passed; a whole-tree check reports only the user's pre-existing `watchlist.yaml` trailing whitespace. Stage 03 copied health verifier (64 checks) and metadata harness (17 self-checks) are diagnostic preparation only. Three bounded Muda 1 metadata-only attempts were made; the latest records an unhealthy observer graph as described above. A/B/C and source-native capture remain unverified.

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


## Stage 04 offline Site Policy preparation

`EbookJapanSitePolicy` and focused policy/planner tests are prepared locally,
but the policy is not registered in CLI, Batch, or GUI and has not been
exercised by a Batch run. It plans `direct` only when the source is for
`ebookjapan`, `available=True`, and `access_mode=owned`; all other states are
ineligible. It declares no quota/resource or grant-only path. This is Catalog
planning eligibility only: the live adapter must recheck current owned rights
before Reader entry. The focused test module passed 12 tests with 0 skips. Stage
04 remains **OFFLINE POLICY PREPARED / NOT INTEGRATED / NOT LIVE** pending Stage
03 source/capture decisions.

## Stage 05 offline E2E audit preparation

An ignored synthetic audit preparation exists under
`output/ebookjapan_experiment/e2e-validation/`; it is not a live E2E run. After
the aggregate item-status fix, the independent Reviewer passed 19 audit cases
(2 positive, 17 negative); the Tester passed 2 positive and 8 negative cases,
and 4 existing validator-negative cases passed. This verifies only the offline
audit preparation. Page coverage, source proof, repeated Full Discovery,
repeated Batch, production E2E and ZIP remain `NOT_VERIFIED`; the source-proof
schema is `NOT_DEFINED`, and Stage 05 live verification has not started.

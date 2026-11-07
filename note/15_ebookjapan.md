# ebookjapan purchased-only Discovery — current implementation

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
pixels) are unproven. One D compositor cover control is retained only in the
ignored phase02 research output; it is not an adopted capture method. No
DRM/access-control bypass or decryption was attempted. An offline Site Policy
candidate is now prepared: only an available `owned` Catalog source is planned
as `direct`, with no quota consumption. It is not registered in CLI, Batch or
GUI and is not live-verified; Catalog state does not replace current Reader
ownership checks. ZIP creation and end-to-end acquisition remain later stages.
See `runbooks/ebookjapan-owned/PROGRESS.md` for the current gate.

## Stage 02 bounded Viewer observations and partial entry implementation

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

The Stage 02 entry, D capture and traversal slice and the scoped END/navigation delta passed local material review. The current local implementation has separate Angel and Mudazumo terminal profiles, same-sample navigation binding to committed paint/geometry, and bounded handling for inactive hidden terminal roots. The affected command covers `tests/unit/test_ebookjapan_adapter.py` and `tests/integration/test_ebookjapan_viewer_browser.py`: 92 passed, 0 skipped, 69 warnings (24 adapter unit + 68 local Chromium). An independent Reviewer selection separately passed 30 tests, 0 skipped. A prior production full-book run saved 287 D artifacts but failed closed before verified END; a new full-book rerun has not reached `CrawlerRunner.run` because Playwright attachment to the shared CDP browser stalls. The adapter is not registered in production CLI or Batch, and successful live full-book completion remains unverified.

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

`capture_page()` is a D compositor PNG implementation, not an A/B/C source capture. It first hides the toolbar, then fits only the task-owned Page viewport. The guarded center action is enabled only at the observed entry viewport 1906 by 986 and measured cover rect (left 282.52, right 953, top 0, bottom 986, width 670.48, height 986; 1 CSS-pixel tolerance); other visible-toolbar geometries fail before click. Immediately before the action, one DOM read revalidates the exact viewport, connected canvas rect and center hit. Fitting before hiding is prohibited because the fitted cover center at fraction 0.25/0.5 advanced into the next spread. The fit accepts either the exact unchanged full-draw signature or a fresh complete draw proven by increased cumulative successfulDraws and positive current generation; backing reset without redraw remains rejected. The same pinned frame signature must remain stable across two animation frames before capture. Before and after each sample it rejects clipped/off-viewport surfaces, canvas/ancestor transforms, outset paint, opacity, filter, mask/blend and intersecting visible painted DOM elements from a bounded 20,000-node inventory (independent of pointer-events). It also rejects generated pseudo-elements and shadow/filter/outline effects that could paint outside their host; a 5x5 elementFromPoint grid is an additional occlusion check. It takes two CSS-scale samples separated by animation frames, checks decoded RGBA equality plus unchanged route/document/slot/canvas/draw state, and returns all spread parts atomically. Cached per-part metadata belongs to that exact capture and records run-local slot IDs, physical right-to-left order, `native_page_number=None`, a visible native counter only when actually visible, and `source_provenance=UNKNOWN`. Core generic locator fallback is blocked.

Normal advance uses the observed non-interactive left-edge page region. Before clicking, the current implementation rechecks the captured slot/canvas nodes, backing dimensions, CSS rectangles, draw geometry and observer state in the same DOM sample used to bind the x=12 hit. Geometry/draw drift, an unpinned hit, interactive/modal/terminal ancestors, or unknown state fail closed. The D capture surface guards are unchanged. END requires complete ordered coverage and one of two observed profiles: Angel's exact terminal message, pinned root and exhaustive review/coupon/recommendation action partition; or Mudazumo's pinned `.book-last` shell/cell, observed modules, scoped native header controls and exhaustive action partition. The author-heading link is admitted only in the observed author section. Hidden/offscreen roots alone remain LOADING during an asynchronous terminal transition; visible malformed, unknown, modal, or extra actions remain fatal. The current affected suite passed 92 tests, 0 skipped (24 adapter unit + 68 local Chromium; 69 warnings); an independent Reviewer selection passed 30 tests separately. Local material review accepted this implementation. The previous CoreRunner baseline saved 287 D artifacts but failed closed at `outset-painted-element:img` before verified END, without ZIP or completed RunResult. A subsequent attempt against the accepted delta could not attach Playwright to the shared browser, so live full-book END remains unverified.

The Angel production CoreRunner baseline was attempted but did not complete: 287 D pages were saved and independently audited, then the run failed closed before verified END and ZIP. Separate normal UI probes observed the Angel end panel and Mudazumo 1 terminal structure. The local implementation contains separate scoped classifiers for these observed structures and navigation uses a same-sample committed paint/geometry check. The current 92-test affected run and independent Reviewer selection pass, and local material review accepted the implementation. A new production CoreRunner attempt has not reached the Runner because Playwright CDP attachment stalls before Page creation. Earlier entry/source probes predate the production adapter, while the later 287-page CoreRunner attempt used the production adapter but failed closed. Production CLI/GUI registration, Batch, a completed ZIP, and E2E remain incomplete.

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

All Stage 02 artifacts are isolated under
`output/ebookjapan_experiment/phase02/`. They contain sanitized structural
metadata, ephemeral canvas/slot IDs, bounded SecurityError details, one D
compositor control PNG, and 287 output D page PNGs from the failed-closed
production run. No raw readback bytes were retained. The page artifacts passed
integrity checks, but CoreRunner completion, END acceptance, A/B/C provenance,
and final capture policy remain unverified and are recorded separately in
`PROGRESS.md`.

The latest affected viewer suite passed 92 tests with 0 skipped (69 warnings): 24 ebookjapan adapter unit tests and 68 local Chromium viewer/Runner tests. It includes scoped Angel/Mudazumo END structures, normal and hidden-root delayed transitions, a tall-viewport author heading, purchase/modal/unknown-action rejection, same-sample paint/geometry race rejection, and navigation hit/ancestor negatives. The independent Reviewer also ran a selected 30-test subset separately with 0 skips. The seven-slot neutral CoreRunner captures a cover plus three continuous spreads through exact END; seven identical fingerprints remain seven manifest/ZIP artifacts. These tests do not verify live full-book END or a successful production ZIP. The earlier 97-test count belongs to a previous frozen tree that included Discovery tests; the 88 count is an intermediate END/navigation tree. Full `ruff check src tests` and task-path `git diff --check` passed on the accepted frozen runtime/test tree. A full live rerun is blocked before Page creation by the current Playwright/CDP attach issue.

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

The isolated production CoreRunner baseline saved 287 ordered D PNG artifacts and then failed closed with `UnknownPageStateError: ebookjapan D canvas surface is unsafe (outset-painted-element:img)`. The exact failing method was not captured; attributing it to terminal advance is an inference from the completed-page Runner flow. No ZIP, completed RunResult, or Catalog write was produced. Root independently verified decoded format/dimensions, source fingerprints, RGBA hashes, manifest order, and part grouping for all 287 files; this validates artifact integrity only.

A subsequent isolated full-baseline attempt stopped before `CrawlerRunner.run`: Playwright `BrowserType.connect_over_cdp` timed out after 180 seconds while initializing the shared browser. `/json/version` returned HTTP 200 (Chrome 156 / CDP 1.3). In a separate bounded diagnostic, the Node built-in WebSocket received a read-only `Browser.getVersion` response and a types-only `Target.getTargets` summary counted 6 page, 2 browser_ui, 15 iframe and 1 worker targets. No target IDs, titles or URLs were retained, and no target operation, activation, Page creation or navigation occurred. A separate 10-second Playwright attach-only attempt, including `no_defaults=True`, also timed out. The observed fact is that WebSocket/RPC succeeds while Playwright attachment initialization stalls; a delayed/discarded existing page is only a hypothesis. No new PNG/output/library run, ZIP or Catalog write occurred. Sanitized evidence: `core-run-angel10-20261107-184139-316247-evidence.json`.

A separate owned Angel 10 normal-navigation probe reached one exact viewport-visible terminal marker after the final left-edge advance, with 287 frozen slots and zero visible page slots. Twelve visible actions shared the `.book-last-dead-end__inner` root: one review action, one coupon banner action, and ten recommendation-module actions. No recommendation destination was opened. The local implementation has an exact structural partition for this profile and passed local material review; no successful live CoreRunner END or ZIP is claimed.

A separate owned Mudazumo 1 probe reached 193/193, made one validated normal edge advance, then remained `loading` for its 20-second bound with route stable, zero visible slots, and toolbar visible. A metadata-only snapshot found a distinct `.book-last` root with review, next-item, CTA, banner, and recommendation modules. Twelve visible actions were recorded; no CTA/recommendation or other control was clicked; fresh entry restored 1/193. The local implementation has a separate scoped classifier for this observed profile; Angel behavior is not generalized to it. Independent selected tests cover inactive hidden-root transitions for both profiles, but no fresh production CoreRunner acceptance is claimed. Sanitized evidence is under the ignored phase02 output. A/B/C remain unproven; live full-book completion remains blocked; Stage 03 is not started and Batch/ZIP/E2E have not run.


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

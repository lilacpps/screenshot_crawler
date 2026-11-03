# BookWalker adapter

## Discovery access for bonus and preorder products

Bonus products retain their special order metadata but no longer force an
unknown access mode. A product's purchased full-reader control is `owned`;
strong maruyomi remains `quota`. A visible `コードを入力` control with
`data-action-label="enter_code"` is `paid` only inside the current product's
main action scope and with an HTTPS member.bookwalker.jp link to
`/app/03/products/<same UUID>/purchase/confirm`. Related, hidden, other-product,
and other-host controls are excluded. A bonus title/badge or trial alone is
insufficient. Code-entry observations use the bounded paid-control settle wait
so a delayed owned/quota control can take precedence.

Code entry is a Discovery-only observation; it is never a reader control and
is not clicked. Run Full Discovery for the registered series to refresh old
unknown bonus records while preserving Item completion state. Incremental
Discovery retains its existing owned/quota stopping boundary. The existing GUI
counts then reflect the refreshed access modes; no GUI-specific suppression is
needed.

Preorders are `paid` when the current product's visible main action has text
`予約する`, `data-action-label="reserve"`, and a matching `data-uuid`.
Series reservations, related/hidden controls, and missing or mismatching UUIDs
are excluded. A preorder keeps its normal volume order. Reservation is a
Discovery-only observation, never a reader entry or an action to execute.
No date-based transition is inferred: a later Discovery observes trial as
`paid`, strong maruyomi as `quota`, or purchased full-reader access as `owned`.
Existing owned/quota priority, paid-control settling, and incremental stopping
boundaries still apply.

## Entry flow

The crawler accepts a direct viewer URL or a BookWalker product URL such as `/de<content-id>/`. For a product URL, `initialize()` locates the product reading control and follows the best reader candidate in the same tab.

Before the first capture of an ordinary `auto`, `direct`, or `quota` run,
`initialize()` verifies the authorized `cid` and the viewer counter. If the
viewer restored a middle or final position, it focuses the viewer and sends
`Home` at most twice within the existing bounded initialization deadline. A
rewind is accepted only after the counter is `1/N`, the same content remains
authorized, the current canvas has positive DOM and backing dimensions, and
the canvas signature changes from the pre-rewind frame before the normal
render-stability checks pass. The pre-ready frame may repaint while that wait
settles; its stable and final observations must join the same CID, `1/N`
counter, canvas identity/content version, dimensions, and non-empty signature.
An already visible `1/N` page does not receive a Home key. Missing identity, a
counter/CID change, ignored Home, or stale pixels fails before the first save.
Normal `go_next()` navigation is unchanged.
Grant-only/entry-only initialization keeps the current reader position and
waits only for render readiness.

For a body-page spread with exactly two selected, integer, non-overlapping
regions, BookWalker can promote source-native JPEGs through the strict
executed-clear path. Both parts must join one pre-selection renderer/CID/counter
anchor and retain their own immutable B snapshots and historical content
versions. After all asynchronous JPEG and coefficient checks, one synchronous
browser task reads both current ROIs from that same renderer frame and compares
them with both immutable snapshots. The result is all-or-none: both JPEGs are
returned only with a complete common proof. A stable JPEG-stage failure, such
as a missing candidate, may return both fresh current native PNGs only when the
same final task proves both ROIs exact and joined to the common frame. A final
ROI mismatch, missing snapshot, identity/geometry change, or an unresolved
redraw race, including a second race after the bounded retry, is `UNKNOWN` and
cannot return an old PNG. Existing single-part and legacy paths remain
unchanged.

The final affected W1/W2 selection is 442 passed, 0 skipped; Ruff and diff
checks pass. The renewed logged-in source-124 focused live check observed a
real End transition from `1/322` (signature `[2732494671,1489]`) to `322/322`
(signature `[3810581606,84]`), then invoked the production Home rewind on that
same page. Normal initialization and the subsequent forced End-to-Home check
completed; two focus attempts were recorded across the adapter lifecycle.
Cleanup restored
the created page to `1/322` with render readiness and closed it; the original
context remained at two pages. No W2 capture, live JPEG, or image artifact was
produced. The safe manifest is recorded in `note/01_bookwalker.md`.
At the W1/W2 checkpoint the new exact-two live JPEG path was unexercised: the separate bounded
page-317 diagnostic had four geometry boxes, no matching destination, and zero
JPEG candidates. The synthetic two-part tests therefore do not constitute a
live JPEG success claim.

## Initial spread-selection redraw retry

A failed initial two-part anchor may retry once when its raw recheck proves
the same authorized book, counter, pinned canvas, dimensions, generations and
complete safety flags, with only geometry/content versions both advancing.
Other changes remain `UNKNOWN`. After 100 ms, both page boxes and native draw
calls are selected again. Layout/source identities must match, versions and
operation indices cannot regress, and the fresh initial anchor must pass.

Every recovered return path, including native PNG and original-JPEG-disabled
capture, freezes both settled current DOM ROIs immediately after fresh selection,
in one synchronous task guarded by the complete before/after renderer stamp
and selected tuples. Private canvas copies are held only for this capture.
Before output, both current ROIs must exactly match these settled copies with
the same stamp and tuples. This frame-stability check includes page-number/title
overlays already present at fresh selection; it does not infer overlay regions,
exclude header pixels, or apply tolerance. Source-native PNG/JPEG validation
still uses the immutable source/draw snapshots. Existing strict executed-clear
reconstruction retains its separate immediate-target/current-ROI pixel gate;
the settled baseline cannot replace that provenance proof.
A second race, missing witness or snapshot/baseline, changed identity/layout,
materialization failure, or any post-baseline differing pixel stops the capture.
Initial recovery consumes the capture's existing one-redraw
budget; it cannot chain another reconstruction retry. The normal successful
path, capture format priority, access/pacing settings and Core fallback policy
are unchanged. No new configuration is required.

The bounded diagnostics retain `batch_initial_anchor_retry` with attempt count
and final proof/output status, including recovered middle-page JPEG successes.
Synthetic tests reproduce the retained `97/350` race and the `315/350` final
comparison failure caused by comparing immediate image snapshots against a
settled renderer with later header drawing. They verify source-native PNG and
legacy JPEG recovery with headers, plus rejection of later pixel changes,
missing/mismatched baselines and strict executed-clear overlay mismatches.
The user Batch recurrence passed reselection but failed the former immediate
ROI check; real-viewer recovery with the settled baseline remains unverified.

## Viewer and capture target

BookWalker uses a canvas renderer. The observed current screen is `#renderer .currentScreen canvas:not(.dummy)`. Core reads the canvas PNG buffer so viewer toolbar/browser UI is not included.

The adapter first traces renderer `drawImage` geometry and source metadata. When one visible page
rectangle maps safely to one source rectangle, it copies that source rectangle synchronously to a
temporary canvas during the intercepted draw and returns the source-native PNG. The native path
requires valid source dimensions, matching PNG dimensions, identity transform, `source-over`, and
`filter: none`; it rejects ambiguous multiple draws, atlas/composition cases, and invalid copies.
Native capture is cleared after every attempt and does not retain `ImageBitmap` references.

If native capture is unavailable or fails any safety check, the adapter uses the existing geometry
crop path with temporary page-sized canvases. This handles centered single pages, landscape pages,
and true spreads. When geometry is unavailable, the bounded center-split fallback remains. Spread
parts stay in right-to-left reading order in both paths.

The first numbered viewer page is treated specially when it is a spread: it is
the visual cover and is saved as one artifact cropped to the draw geometry. If
the cover has multiple visible draw rectangles, they are combined into one
outer content rectangle before capture. Other spreads remain separate
right-to-left page artifacts. This prevents a two-part cover from becoming
`page-0001` / `page-0002` while removing the viewer's outer margins.

Native cover geometry is restricted to the current renderer dimensions and
trace/reset epochs, after the latest proven executed full clear or observed
canvas dimension reset. The existing clear witness requires successful native
execution with identity transform, known unclipped state and complete observer/
canvas/epoch checks. Earlier body-page rectangles remain in the provenance
ledger and are excluded when a later proven boundary exists. Multiple current-frame
cover regions are still combined; artwork with white borders is not trimmed
by pixel colour. An unobserved boundary retains the existing single-rectangle
path only when all records have one identical rectangle and current dimensions/
epochs. Ambiguous or missing current geometry is rechecked once after 50 ms,
then becomes `UNKNOWN`; a counter change during recheck also stops. This applies
before native selection and to rendered fallback, so a failure cannot silently
save an old union. Body geometry, explicit canvas mode and the no-record
pixel-bound fallback keep their existing behavior.

`bookwalker_capture.cover_geometry` diagnostics retain the boundary, record
counts and up to four selected rectangles. Synthetic browser tests reproduce
the old 1086x983 cover with 391 white columns and verify a 695x983 current-frame
crop, native selection, true-cover union, white borders and fail-closed cases.
Known live limitation: the 19:47 Item1880 recrawl retained a body rectangle and
three cover draws after the same initial canvas-reset boundary, so the union
still included 391 white columns. A reset/clear epoch alone does not distinguish
repainting within that epoch. A synthetic white-background `fillRect` reproduces
this shape, but the real renderer's replacement operation is not retained and
has not been attributed. This case remains unresolved; waiting longer does not
remove old ledger entries. Item1874's defective ZIP was skipped as completed in
that Batch and remains an older artifact. Explicit per-Item recrawl preparation
is available through `prepare_recrawl.py --item-id ... --force`; no further
capture-policy change or live recapture was performed during this investigation.

For the next recurrence, native tracing retains the first renderer capture's
execution ledger in `cover_geometry.renderer_operations`: up to four connected
renderer canvases and 64 events each, with eviction/failure counts and a
`truncated` flag. Events include counter, canvas/trace/reset identity, dimensions,
operation order and actual native return, source/destination rectangles, colour,
transform, clip-safety, alpha/composite/filter/shadow and before/after versions.
Text/image contents, signed URLs and credentials are excluded. A missing native
return or truncated ledger cannot establish successful execution or absence.
Collection stops at the first native-success or rendered-fallback cleanup;
source/proof buffers and all capture decisions are unchanged.

The existing `output/diagnostics/bookwalker/run-<UUID>.jsonl` contains these
records automatically (`BOOKWALKER_DIAGNOSTICS_DIR` overrides the directory).
Inspect the latest cover row, including `rendered_fallback_complete`, and any
`kind=cover_renderer_operations` row emitted when unrelated debug exceeded the
per-row cap. Failed-run metadata also carries the ledger. Existing row/run size
limits and best-effort failure isolation remain. No new setting or live-site
probe is required to enable logging; real recurrence verification is pending.

For a purchased product, the product control may expose
`data-action-label="read_purchased"` while displaying `読む`; this is treated as the owned
strict-direct entry. The purchased viewer's page JPEGs are fetched as XHR responses from
`bw-bv-epubs.bookwalker.jp`. Trial/free viewer JPEGs continue to use the
`viewer-epubs*.bookwalker.jp` family. Both are subject to the same conservative matching and
all-parts-or-PNG fallback rules. Lossless reconstruction accepts candidates from the
explicit purchased host `bw-bv-epubs.bookwalker.jp` and maruyomi 10-minute host
`viewer-epubs-ptrial.bookwalker.jp`. Eligibility does not establish provenance: the
same selected mapping, unique full-resolution raw-JPEG match, MCU/DCT and pixel
gates apply to both. Other trial/free hosts retain original-JPEG matching and PNG
fallback until their reconstruction path is verified. The purchased viewer's intermediate
`HTMLCanvasElement` source is accepted only with the existing identity-transform and
composition checks, and its mutable source canvas uses eager per-draw crop capture.
An `HTMLCanvasElement` without an eager crop is rejected before deferred materialization.
When a raw tile cannot be uniquely matched, the verified source-native PNG is returned as-is;
the adapter does not re-encode it as JPEG. A direct completed tile mapping may instead
produce a lossless reconstructed JPEG when the coded source frame `S` and visible
intermediate frame `V` are proven separately. The supported cropped shape is limited
to a right or bottom final-MCU crop of fewer than eight pixels, integer 8-pixel-aligned
geometry, complete source/destination MCU bijection, SOF0 4:4:4 structure, exact
coefficient/qtable/component-selector readback, and one unique full-pixel JPEG match.
The cropped one-hop extension observes native canvas dimension setters as reset boundaries and
retains the clear target, tile draw target, reset generation, and selected
renderer geometry separately. It supports only one origin-zero full-frame
A-to-B canvas draw followed by the recorded right/bottom renderer crop. It
replays the reconstructed A through B and independently compares the eager A
snapshot, eager B snapshot, and selected renderer destination ROI in-browser.
The final replay keeps the renderer's actual backing-canvas dimensions and
destination offset. Every comparison must be available, dimension-equal, and
zero-difference, even when
`BOOKWALKER_FINAL_PIXEL_VERIFY` is disabled. An unavailable or mismatched proof
returns the associated native PNG only while the selected native association
and current page identity remain valid; a stale, missing, or ambiguous proof
remains UNKNOWN and cannot reuse an old buffer. The current source-native
priority is verified original JPEG, verified lossless reconstructed JPEG,
source/native PNG, then rendered-canvas PNG fallback. Unavailable spread-native
capture falls back to the complete Core PNG path only after the normal current
identity checks pass.

## Spread and order

BookWalker can render a spread in a wide Chrome window. The adapter saves the
right page first and the left page second. Split files record
`metadata.part` / `metadata.parts`. The first numbered page is an exception:
when it is a spread, the cover's draw-geometry union is saved as one artifact.
If the viewer exposes no draw geometry, the adapter scans the rendered pixels
for the non-white cover bounds and crops that area. The full-canvas fallback is
kept only when neither geometry nor a usable pixel bound is available.

## Navigation and page change

The adapter advances with the viewer's `ArrowLeft` keyboard handler and falls back to a left-edge `#viewport1` click only when page identity remains unchanged. `#loaderStatusDialog` must disappear and the canvas signature must stabilize before capture. `#pageSliderCounter` is the primary page identity signal, with viewer `cid` as a secondary signal.

Some transitions consume the first action, so `wait_for_change()` performs bounded retry and never waits indefinitely.

## Content context and stopping

The URL `cid` is stored as content/work/source ID.

- `#eobNext` → `NEXT_CONTENT`
- visible `#endOfBook` → `END`
- the adapter first checks a bounded, source-independent complete-canvas image
  matcher for the registered notice/logo roles, before geometry splitting. If
  that complete-canvas read is unavailable or does not match, it may fall
  through to the observed native notice at `N-1/N` and native logo artifact at
  `N/N`. Both paths remain terminal-only; the existing final-navigation/END
  checks remain authoritative
- known ad markers → `AD`
- otherwise ambiguous state → `UNKNOWN`

Do not simplify this to a single END signal without live verification.

Terminal classification is non-consuming. The approximate path first reads the
complete current canvas before any geometry split and uses a white-flattened
foreground union bbox, aspect-preserving 32x32 image normalization, and a
calibrated 256-bit perceptual hash. If that read is unavailable or does not
match, the native path reuses the ordinary selected draw call and source
snapshot shape without arming or clearing capture state. Both paths require a
stable pinned canvas identity and unchanged counter/frame. A missing/unstable
native call, partial crop, changed counter, unknown image, mixed canvas, or role
mismatch remains content. The known-image registry stores compact hashes and
calibration metrics only; the approximate matcher never infers JPEG/source
identity from filename, extension, or visual similarity. Successful and fallback
capture attempts also write bounded, sanitized diagnostics JSONL under
`output/diagnostics/bookwalker/` (override with `BOOKWALKER_DIAGNOSTICS_DIR`).

For `BookWalker strict batch initial anchor changed`, capture diagnostics retain
`batch_initial_anchor_failure`: the first rejected join and the existing
failure recheck, with before/after counter, canvas identity, trace/geometry/
content versions, per-part selected source/snapshot tuples and changed-field
names. Opaque geometry generation values are omitted, but their change is
reported. The first failure remains available even if the recheck is stable.
The same data is in the failed run's `diagnostics/metadata.json` under
`adapter_debug.bookwalker_capture`; the JSONL capture row includes the error
message in `failure_reason`. Logging is enabled automatically with no added
successful-path browser reads and does not change capture, retry or stopping.
It is bounded and sanitized, and logging failures cannot mask the original
capture error. On a future recurrence, use the metrics path/item ID to locate
the failed run's metadata and corresponding diagnostics JSONL.

## Browser Session policy

The adopted target architecture uses one shared Crawler Chrome/profile for all real sites.

```text
shared Crawler Chrome (.chrome-crawler/)
    ↑ CDP
Playwright Page
    ↓
BookWalker adapter
```

The adapter should not own Chrome launch, profile selection, CDP endpoint resolution, or `connect_over_cdp()`.

CDP is the connection transport; normal BookWalker interaction remains Playwright `Page` / `Locator` operations.

Authentication state should normally stay in the shared Chrome profile. A BookWalker-specific endpoint/profile is an exception override, not the default design.

### Current launcher state

The only standard launcher is `scripts/start_crawler_chrome.ps1` with the shared `.chrome-crawler` profile. BookWalker and Manga ONE sessions can coexist there. Site-specific launcher/profile paths are not part of the current operation; site-specific CDP endpoint/profile settings remain exception overrides only.

## Authentication

BookWalker login DOM automation remains site-specific, but it should receive a Playwright Page from the common Browser Session layer.

Target endpoint precedence:

1. `--cdp-endpoint`
2. `BOOKWALKER_CDP_ENDPOINT`
3. `CRAWLER_CDP_ENDPOINT`
4. `http://127.0.0.1:9222`

`CRAWLER_CDP_ENDPOINT` is the standard global endpoint. `BOOKWALKER_CDP_ENDPOINT` remains an exception override.

The login CLI always creates a dedicated new Page, does not reuse another site's tab, closes that Page after login, and leaves the remote Chrome/profile running.

CAPTCHA / MFA / validation errors are not automatically bypassed.

## Live verification

Live headed-CDP checks confirmed:

- single-page PNG capture
- spread capture in right-to-left order
- renderer geometry-based page split
- final `59/59` transition where the BookWalker logo appears in the canvas while `#endOfBook` becomes visible

The prepare-recrawl scanner accepts PNGs only at the last five saved-page
numbers when a JPEG companion exists, under the naming rules in
`docs/BOOKWALKER_RECRAWL.md`. Opening PNGs outside that tail and PNG-only archives
remain `FALLBACK_INCLUDED`. This positional acceptance is independent of the
adapter's terminal-image navigation decision.

These observations remain the basis for the site-specific logic and should not be changed merely as part of Browser Session unification.

Source-native live verification on 2026-09-19 used the four trial samples recorded in
`note/01_bookwalker.md`: 960x1280, 1443x2048 portrait, 2048x1090 landscape, and a two-page
1303x2048 spread. All produced native source crops; unsupported or ambiguous pages remain covered
by the existing Canvas crop fallback.

Shared-profile live verification confirmed BookWalker login and crawl, coexistence with the Manga ONE session, dedicated login Page cleanup, remote Chrome preservation, and no regression in the adapter-specific capture, navigation, or END behavior.

## Output naming and packaging

For product-page entry, the adapter collects title/author/category/series metadata before opening the reader. Campaign tags such as `【期間限定】` are removed and numeric volume suffixes are normalized according to `docs/BOOK_NAMING_RULES.md`.

On normal `END` / `NEXT_CONTENT`, manifest-declared PNGs are archived under:

```text
output/Books/<genre>/<title>/<volume>-<author>.zip
```

This is the short-title form. When the sanitized title is 50 characters or
longer, the ZIP and matching `crawl-status` JSON omit the title from the stem
and use `<volume>-<author>` instead. The title remains the library directory in
both cases.

A completion record is kept under `output/crawl-status/<genre>/<title>/` using the
same stem as the ZIP. The intermediate crawl directory is removed only when its
complete contents are generated run artifacts (manifest, progress, and
manifest-declared PNGs). If unrelated or extra files exist, the directory is
retained rather than deleted.

Direct viewer URLs may lack product metadata and can produce an `unknown-title` archive name.

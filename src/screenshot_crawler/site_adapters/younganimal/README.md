# Younganimal adapter

The Younganimal adapter provides Discovery, a manual free-episode crawl, and a
direct-only free-source Batch path. It uses the shared CDP BrowserSession / Playwright Page,
the shared AccessGuard, and the normal Runner, manifest, and packager.
It does not launch Chrome or select a profile. Batch selects only currently
available Catalog sources with `access_mode=free`; wait-free and resource flows
are not implemented.

## Current live verification (2026-10-11)

Full live Discovery passed all 31 ranges and 925 positions with a 3000 ms
harness override; the production default was changed to 3000 ms after that run.
The isolated Catalog contains 925 Items/Sources/Targets; three rows are exact
free and the remaining 922 are UNKNOWN, not paid.

Attempt 9 passed both final-code live profiles. The standard target captured
16/16 pages as native VP8L across 9 spreads; the top-empty target captured
44/44 pages as native VP8L across 22 spreads. Both reached Runner END, passed
ZIP and isolated Catalog audits, and preserved source fingerprints. The
top-empty audit confirms physical slots 2-45 and 44 CRC-valid archive members;
the standard target confirms physical slots 1-16. Reports are
`output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/provided-free/audit.json`
and `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/topempty-free/audit.json`.
The earlier attempt-7 top-empty navigation timeout and attempt-8 native verification
failure remain historical and are not treated as current failures.

The reviewed capture-epoch exception is limited to observed ordinary class
mutations on one exact nested CI scroll widget. Same-token-set no-ops in the two
known states are accepted; the observed base-to-`mode-scroll-bottom` transition
is accepted only with positive finite geometry proving the widget/CI is offscreen
or disjoint from every active body wrapper/canvas. Missing, ambiguous, or
overlapping geometry fails closed. Global DOM accounting, candidate identity,
selected-page and post-encode proofs, frozen mapping, pixels, atomic spread
handling, and cleanup remain strict. The final code passed the affected local
suite and both live profiles described above.

## Manual crawl entry

Pass a canonical episode URL to the crawl command for site younganimal and set
YOUNGANIMAL_WORK_URL=https://younganimal.com/series/&lt;work-id&gt; in the selected
environment file. The work URL must be canonical and same-work; the episode
source URL remains the manifest source URL. The adapter rejects a missing,
malformed, or mismatched entry before episode navigation.

The adapter starts at the configured work listing, validates its observed range
map and each visited range, and stops once the exact target row is found. It
does not need to enumerate all 925 rows for this manual path. It waits 3 seconds
before every selected numeric range route and before entering the episode. The
selected row must have exactly one row-scoped 無料 label; 今なら無料,
待つと無料, blank, repeated, conflicting, and unknown labels are ineligible.
After entry, the embedded public row must independently prove the exact target
route, same work, unique row, and exact 無料 label before viewer observation
begins. No login, wait, ticket, coin, point, purchase, grant, or next-episode
action is performed.

The manual crawl supports only `access_strategy=auto` and retains its fresh
series-listing preflight. Configured Batch requires `access_strategy=direct`, a
strict `{13-hex-work-id}:{13-hex-episode-id}` external identity, and a nonempty
opaque `work_key`. It navigates once to the canonical Catalog episode URL, then
validates the freshly embedded exact-free row and work header before viewer
initialization. It does not visit the series listing or consume/update quota or
grant state. A mismatch stops before capture and leaves the Batch item pending.

## Viewer and rendered PNG contract

The metadata-only live probe observed the exact target episode, a fresh
same-work public row with exact 無料, and one viewer layout:
#comici-viewer, #xCVSeekBar, #xCVPages, 22 physical wrappers,
seek min=1, max=21, step=2, a top PR lead-in at physical slot 0,
contiguous body slots 1–16, CI slot 17, PR slots 18–19, Good slot 20, and Last
slot 21. This 22-wrapper / 16-body shape is the observed sample, not a fixed
production count. The live report records seek positions 21, 19, …, 1 and the
Last marker at the terminal position. The production parser validates exact
lead and tail roles, then derives the contiguous body interval and checks its
relationship to the physical count and public seek range; it does not copy
Hanayume page counts or total-5 arithmetic. Unknown role markers, interior
gaps, counts inconsistent with the seek range, wrong route, or unexpected
canvas state fail closed. A second exact-free live work exposed a distinct top-empty profile. Its observed sample had 51 wrappers, seek min=1/max=51/step=2, and the exact top-empty root flag. In that sample, slot 0 was the exact lead-in, slot 1 the centered `-cv-page mode-empty` wrapper with no canvas, body slots were 2-45, and CI/PR/Good/Last occupied 46/47-48/49/50. The max-seek root also had first/top-PR flags; one public step from 51 to 49 centered body slots 2 and 3 and cleared those transient flags. The production parser does not allowlist 51: it accepts this dynamic structural profile only with the positive root flag, exact lead/blank/tail roles, contiguous derived body interval, and `min=1`, `step=2`, `max=wrapper_count` relation. Other wrapper totals for the standard profile have not been individually verified live. No generic blank-page skip is inferred.

The top-empty profile's slot 1 is recognized only at max seek with the exact root flag, exact blank classes, no canvas, centered wrapper, and first/top-PR markers. The adapter makes one ordinary public seek step to `max - step` and requires both first body canvases ready before capture; it never skips a page by subtracting a wrapper count. Known initial body-loading classes remain unready and cannot produce a capture. Unknown wrapper variants fail closed.

The adapter rewinds a resumed viewer with the public seek control. Before the
first capture it requires read-only observer metadata to show `mode-nav-open`
absent and zero `.-cv-splash` nodes, then requires the existing first-canvas and
capture-epoch quiet signature to remain stable for 1 second within the same
5-second bound. UI reappearance resets the quiet interval. Missing or malformed
metadata and UI that does not settle fail closed before capture. Global DOM
generation still records every observed mutation; capture stability uses the
separate epoch described above. It then
captures only the next contiguous body slot or spread. It sets the observed
public range value and dispatches ordinary input/change events for subsequent
seeks. It verifies the exact target route, frozen physical body mapping, current
seek, active visible canvases, canvas node references, dimensions, write and
generation counters, layout, viewport, and RGBA fingerprints before and after
capture in one page evaluation. It saves PNGs from the body canvases' own
toDataURL output, decodes and validates each image, and requires the decoded
RGBA fingerprint to match the same synchronous canvas readback. Generic locator
screenshots are disabled for this adapter. Missing halves, mutations, unreadable
pixels, route drift, or unsupported state stop the crawl.

After every derived body slot has been captured, the adapter moves only the
public seek to its minimum and requires the observed Last role to be visible
with no body slot centered in the viewport before reporting END. It never
follows next-episode controls.

Capture prefers verified draw-time source-canvas pixels when every active half
has a supported full-frame candidate. The observer copies the source during the
source-to-body draw into a private immutable canvas, uses runtime dimensions,
and replays the captured transform into a scratch canvas. Native selection
requires exact RGBA equality with the active body and the full strict viewer
parser before selection and after encoding. A single-use post-proof binds route,
seek, role mapping, active physical slots, viewer/wrapper/canvas nodes,
dimensions, generation/write counts, layout, readiness, and pixels. Unsupported
or missing evidence falls back to rendered body-canvas PNG for the entire spread;
mutation after selection raises `UnknownPageStateError`. VP8L WebP is used only
when decoded RGBA is identical to the verified source PNG; otherwise the same
PNG is retained. Candidate/proof state is bounded and released after each try.
The observer does not hard-code Hanayume dimensions or wrapper arithmetic and
does no image encoding in the draw hook.

The D rendered body-canvas PNG path remains the atomic fallback. The historical
D-only Runner audit covered 16 ordered 984?1329 PNG pages through END/ZIP and
passed raw SHA-256, CRC, physical-slot, and PNG-decode checks; its restored
completion status remains `PASS_WITH_STATUS_PROVENANCE_LIMIT`. The later
provided-target direct Batch live run captured all 16 pages as native VP8L,
matched decoded RGBA to traced PNG pixels, reached END, and completed isolated
ZIP/Catalog packaging. The attempt-7 audit is in
`output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-7/offline-final-audit.json`.

Attempts 6 through 8 are historical diagnostics under earlier geometry/code
revisions. Attempt 9 is the current two-profile live verification on the final
code. Earlier failures remain in the isolated Catalog history and were not
deleted or rewritten.

Sampled source attribution reports are ignored under
`output/younganimal_experiment/native_attribution_probe_20261011_retry2.json`
and `native_attribution_validation_20261011.json`. Sampled first/middle source
responses were WebP at 960?1297, tiled by a nonidentity 4?4 map into a
960?1296 intermediate, then scaled to 984?1329. Those sampled bytes cannot be
saved as-is; JPEG DCT does not apply to those WebP samples. Slot 16 response-byte
attribution remains UNKNOWN; this does not generalize to every page.

## Discovery contract

- Episode identity is work-scoped as &lt;work_id&gt;:&lt;episode_id&gt;.
- Discovery accepts only a canonical series listing URL of the form
  https://younganimal.com/series/&lt;13-lowercase-hex-work-id&gt;. Episode seeds
  are rejected before guard startup/navigation because the row's exact free
  status has not been proven.
- Full Discovery buffers every declared range before yielding. It validates
  contiguous ranges, row counts, unique IDs, work title, and exact row URLs.
  Incomplete traversal yields no partial records. Inclusive bounded scopes
  preserve whole-work global positions.
- Nonempty epListUser history is rejected because same-ID title/access
  consistency has not been established. The range selector accepts the exact
  observed 最新話から control at the same-work /new route and an optional
  no-href ... placeholder. Unknown controls and redirects fail closed.
- Only exact row-local 無料 maps to free. Authentication, 今なら無料, waiting,
  tickets, coins, purchases, grants, and resource state remain unknown or
  unimplemented.

The Discovery adapter uses a 3-second delay before every numeric range route,
a finite retry budget that requires matching current-attempt HTTP 200 document
evidence, and bounded AccessGuard cleanup. Its exact retry contract and the
completed 925-row live pass are documented in note/11_younganimal.md and the
runbook progress.

## Verification status

The final affected Younganimal capture unit and browser suite passed 84 tests,
0 skipped, with 5 existing pytest-asyncio deprecation warnings in 133.19s.
`ruff check src tests` passed. A read-only CLI review inspected a SHA-snapshotted
code view but did not run tests. The full `pytest -q` suite was not run for this
site-local change.

Discovery's 925-row live run is complete. The direct-only Policy/Batch path has
passed independent review and synthetic BatchExecutor-to-Runner-to-ZIP tests.
Attempt 9 verifies the final capture code on both live profiles. The 44-page
synthetic Runner also verifies all native outputs against independent
fixture-source RGBA through END/ZIP. Phase 05 remains UNKNOWN-only and
unimplemented: both SVG icons on blank rows were measured
visible at 24x24 with visible parents, but active icon, wait/access/resource
semantics, and positive authentication state remain UNKNOWN. No wait, CTA,
episode, or resource action occurred.

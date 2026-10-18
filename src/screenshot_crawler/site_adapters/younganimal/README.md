# Younganimal adapter

The Younganimal adapter provides Discovery, direct manual episode Crawl, and a
direct Batch path for free sources and active rentals. Discovery also records
authenticated, work-bound wait-free candidates and active manual ticket grants
from natural listing responses. The shared CDP BrowserSession / Playwright Page, AccessGuard, Runner,
manifest, and packager remain in use. Batch supports the existing direct
free/rental path and the explicit `quota + work_ticket` path. Discovery itself
never clicks or consumes a ticket. Synthetic Batch coverage is in place; the
Phase 03 independent review passed; Phase 04 live CLI checks remain pending.

## Current live verification (2026-10-18)

The supplied rental episode `37d94ac0d8242` passed full work Discovery (six
positions, three active rentals) and a production Batch run through END with
28 pages and 28 CRC-valid ZIP members. Crawl made exactly one main-frame
document navigation, to the canonical episode URL, and visited no listing route.
Its additional `top_empty_no_pr` layout requires the positive top-empty root
flag, exact empty/no-canvas slot 0, contiguous body and CI/PR/PR/Good/Last tail,
and `seek.max=wrapper_count-1`. At maximum seek the empty wrapper and first body
are in view with only the first-page flag; no blank-only advance is needed.
The observed sample has 34 wrappers and 28 body pages; these counts are derived,
not fixed. Native/rendered capture proof and frozen mapping remain required.
Report: `output/younganimal_rental/crawl_20261012_065928/report.json`.

Previous exact-free verification (2026-10-11):

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

## Batch `work_ticket` entry

The `work_ticket` resource is attempted only for a planned Younganimal quota
candidate with its exact Catalog work/episode identity. Batch installs a
same-Page route guard and bounded natural-response observer before the initial
navigation, then goes directly to the Catalog episode URL; it does not previsit
a series page or another episode. Before any action it requires the canonical
route, one matching work header, positive session authentication, and an exact
current episode access record bound to that work. Only `accessType=waitAndFree`
with `hasAccess=false` and a missing or exact-zero timer can reach the control.
An already-active exact ticket grant is reused as non-consuming direct access in
normal Batch; grant-only skips an existing grant.

The adapter requires the unique visible, enabled, uncovered
`button[data-e2e=wfRead]` with the exact observed free label and charge scope,
known paid sibling controls, and stable retained-element identity. It performs
one trial click, repeats the same-Page native/auth and UI checks, latches before
one click, and never retries. Consumption is confirmed only by a post-click
successful target-bound `POST /api/checkout/rental` together with the same
work/episode's exact native `waitAndFree` false-to-true transition. The observed
request body is checked with a bounded exact-target-ID scan; its key path was
not retained by the research artifact. The adapter records this proof before
Viewer initialization, so later Viewer/Capture failure or cancellation does not
lose the observed quota use. The observed timer supplies an expiry only when it
is a valid positive integer; there is no fixed-duration fallback.

The route guard aborts and records a recognized same-work read-only RSC GET
prefetch without treating it as a series-page visit or failing the selected
episode run. Phase 04 also observed one off-target episode `GET` fetch with an
`_rsc` query key and an `rsc` header. That exact same-origin canonical route
signature is recorded and aborted before the network handler, while the
selected episode run continues. The guard keeps an internal count capped at 16
and up to 16 sanitized paths; it does not retain or use query/header values or
the response. Exact other-episode page paths are checked before the generic
static-resource pass-through; asset suffix paths retain their existing
handling. Missing either marker, another method/resource/navigation/frame
shape, other series routes, off-target navigations, unexpected subframe
navigations, and unrecognized RSC routes remain fatal. The adapter checks both
this route guard and recorded 403/429 stops again immediately before latching
the single action.

The Phase 04 zero-dispatch guard trace also observed exact same-site RSC `GET`
fetches for `/` and `/store_items/series/<positive-id>/<positive-id>`, plus
Stripe controller/m-outer and Facebook `/tr/` third-party subframe requests.
The adapter recognizes only those observed route families with their reviewed
origin, method, resource, navigation, and query constraints, then aborts them
before any downstream handler. Stripe route matching ignores the fragment;
Facebook requires an empty fragment, but the live request summary did not retain
fragment presence, so whether its observed request meets that condition remains
unverified. These classifications store only a bounded count and sanitized
path in the live guard object.

The latest affected local checks pass: the route-classifier unit file has 57
passing tests, and the browser-backed Younganimal adapter integration file has
82 passing tests, no skips, and five existing pytest-asyncio deprecation
warnings. The route-drift regression waits for a confirmed grant before
attempting the blocked main-frame navigation. Live Phase 04 CLI verification is
still pending.

Normal Batch stays on the same Page and continues through the existing Viewer,
Capture, END, and ZIP checks. `batch run --site younganimal --grant-only
work_ticket` confirms the same entry and consumption without Viewer image
capture or packaging, leaving the Item pending. The local work-scoped policy
skips the same-work resource before Browser/Page setup for at least 23 hours
since recorded consumption; a longer configured cooldown is preserved.

## Manual crawl entry

Pass a canonical episode URL to the crawl command for site younganimal and set
YOUNGANIMAL_WORK_URL=https://younganimal.com/series/&lt;work-id&gt; in the selected
environment file. The work URL must be canonical and same-work; the episode
source URL remains the manifest source URL. Missing/malformed configuration is
rejected before navigation; a mismatched work header is rejected before capture.

The adapter starts directly at the canonical episode URL and verifies its exact
route and same-work header. The configured work URL is an identity check only.
Crawl does not navigate to, traverse, or read episode listing rows. Visible
central charge UI or read/rental controls stop without clicking. The strict
viewer/body parser must positively establish readable content before capture.
No login, ticket, coin, point, purchase, rental activation or next-episode action
is performed.

The manual crawl supports only `access_strategy=auto`. Configured Batch
requires a strict `{13-hex-work-id}:{13-hex-episode-id}` external identity and a
nonempty opaque `work_key`. `access_strategy=direct` retains the existing
free/rental behavior and does not consume a ticket. `access_strategy=quota`
accepts only `quota_resource=work_ticket` and uses the entry contract above.

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
  are rejected before guard startup/navigation; the supported Discovery scope
  is the canonical series listing.
- Full Discovery buffers every declared range before yielding. It validates
  contiguous ranges, row counts, unique IDs, work title, and exact row URLs.
  Incomplete traversal yields no partial records. Inclusive bounded scopes
  preserve whole-work global positions.
- epListUser account rows settle within a bounded 12-second wait. Canonical
  unique IDs and matching normalized public/user titles are required. Account
  rows supplement access only and never create extra positions or Items.
  Duplicate/malformed identities or conflicting titles fail closed.
  The range selector accepts the exact
  observed 最新話から control at the same-work /new route and an optional
  no-href ... placeholder. Unknown controls and redirects fail closed.
- Exact row-local 無料 maps to free. Exact normalized rental countdown
  `レンタル中 閲覧期限 D日+H時間` maps to paid with the conservative grant
  `observation start + D days + H hours - 1 hour` (days 0..14, hours 0..23,
  positive remaining bound). Free takes precedence; malformed/near-expiry or
  unobserved formats stay unknown.
- During the existing listing traversal, the adapter observes only natural
  `GET /api/series/access` and `GET /api/auth/session` responses. It makes no
  additional request. A positive integer session user and an exact
  `seriesAccess.seriesId` matching the canonical work are required before
  joining `episodeAccesses` by canonical episode ID. Only `waitAndFree` is
  interpreted: exact `hasAccess=false` with a missing or zero timer is a
  work-ticket candidate; null, positive, or malformed timers stay unknown.
  Exact `hasAccess=true` with a valid positive timer is a manually active ticket
  grant. Its conservative expiry uses request start plus timer seconds minus one;
  a recognized rental-label lower bound can shorten it. Other access types,
  contradictory timer states, duplicate or absent rows, foreign work, and
  unavailable authentication stay unknown and preserve a stored grant. Native
  observations do not override an exact free label or active rental.
- `YounganimalSitePolicy` exposes one `work_ticket` pass, scoped to a work with
  limit one and a local minimum 23-hour post-consumption cooldown. Free and
  unexpired rental sources remain non-consuming `direct`. The Batch ticket
  click, grant-only executor verification, and same-Page Viewer handoff are a
  later phase and remain unimplemented.

The Discovery adapter uses a 3-second delay before every numeric range route,
a finite retry budget that requires matching current-attempt HTTP 200 document
evidence, and bounded AccessGuard cleanup. After native response draining, it
checks AccessGuard once more before constructing or yielding records so a late
fatal response cannot publish a seemingly complete listing. Its exact retry
contract and the completed 925-row live pass are documented in
note/11_younganimal.md and the runbook progress.

Incremental refreshes every validated row in the requested scope because rental
rights can change on old episodes beyond a newest-known boundary. The listing
is already buffered, so this adds no browser requests. Incremental does not
reconcile unseen sources as unavailable.

## Verification status

The rental/direct-entry iteration passed all six Younganimal unit/browser files:
171 passed, 0 skipped, with existing pytest-asyncio deprecation warnings.
The final incremental refresh change also passed a targeted Discovery rerun:
51 passed, 0 skipped.
`ruff check src tests` and `git diff --check` passed. The global full suite and
Research tests were not run for this site-local change.

Discovery's 925-row live run is complete. The Phase 02 work-ticket Discovery
contract has been observed on the live listing: two natural series-access GETs
returned work-bound `episodeAccesses`, and the auth session returned a positive
integer user. No ticket was used during that listing observation. Its targeted
unit tests and browser-backed fixture tests pass, and Phase 02 independent review
passed. The Phase 03 ticket-entry Policy/Batch path also passed independent review;
synthetic browser verification is complete, with live CLI checks reserved for Phase 04.
The previous free/rental direct path has passed independent review and synthetic
BatchExecutor-to-Runner-to-ZIP tests.
Attempt 9 verifies the final capture code on both live profiles. The 44-page
synthetic Runner also verifies all native outputs against independent
fixture-source RGBA through END/ZIP. A bounded work-ticket research action was
later observed on the authorized episode `856137d88753b`; one resource use is
recorded in the work-ticket Runbook. This evidence does not implement Batch
entry. The remaining adapter work must verify the same safe control and hand
the same Page to the production Viewer/Capture path.

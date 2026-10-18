# 11. Younganimal current implementation

## Current verification snapshot (2026-10-18)

Rental Discovery and direct reader entry are supported. Full live Discovery of
the supplied work enumerated six public positions and selected three current
rentals in an isolated Catalog. Episode `37d94ac0d8242` remained at position 2
with `access_mode=paid` and a conservative rental grant. Final-code Batch
captured all 28 body pages through END and packaged 28 CRC-valid ZIP members.
The only main-frame Crawl document navigation was the exact supplied episode
URL; no listing route was visited during Crawl and no quota consumption was
recorded. The report is
`output/younganimal_rental/crawl_20261012_065928/report.json`.

On 2026-10-18, one authorized research action was observed on episode
`856137d88753b` / work `8246f8b8b2e6c`. The exact wait-free control, same-row
`waitAndFree` false-to-true transition, target-bound successful checkout, and
same-Page ready Viewer were adjudicated as one resource use. Its 23-hour
minimum same-work cooldown ends at `2026-10-19T05:05:50.550591Z`.

A second authorized use occurred through live `--grant-only work_ticket` on
episode `e15e15c6ec11a` / work `128888a1fb162`. The CLI returned
`entry_confirmed` with `resource_consumed=true`, and the isolated Catalog
recorded `quota_started_at=2026-10-18T17:14:10.767250+09:00` and
`access_granted_until=2026-10-21T17:13:58.168443+09:00`. Pre/post native state
changed from authenticated `waitAndFree` without access to authenticated
`waitAndFree` with access and a positive 259187-second timer. One retained free
control click was delegated, and one target-bound checkout returned HTTP 200;
no balance-delta claim is made. The Item stayed pending with zero captured pages
and no artifact/ZIP. The trusted DOM event list was empty, so trusted-event proof
is NOT VERIFIED. The same-Page audit recorded two selected-episode main-document
requests and zero series/off-target main-document requests; source contains no
post-click goto/new-Page call, but the second request's initiator is unknown.
Do not repeat the action to repair telemetry. Its local 23-hour cooldown ends at
`2026-10-19T07:14:10.767250Z`.

One normal Batch work-ticket use occurred on episode `0634e2ac53df6` / work
`145fe0e303563` at `2026-10-18T17:32:39.739556+09:00`. The target-bound
checkout and authenticated native `waitAndFree` transition confirmed the third
resource use; the isolated Source recorded grant expiry
`2026-10-21T17:31:58.911149+09:00`. The CLI then failed Viewer readiness with
`PageChangeTimeoutError`: no stable known layout within 20 seconds, Capture
`not_started`, zero pages, pending Item, and no artifact. The 23-hour minimum
cooldown ends `2026-10-19T16:32:39.739556+09:00`. No quota-consuming retry
occurred. A later direct run used the already-active grant without consuming a
resource; details are recorded below. Evidence:
`output/younganimal_work_ticket_tester/NORMAL_BATCH_0634_REPORT.md` and
`output/yanc-0634/younganimal/`.

A bounded read-only diagnostic on this already-granted exact episode confirmed
the canonical route/work header, positive authentication, and current native
`hasAccess=true`, `accessType=waitAndFree` state with a positive timer. It made
one direct load, blocked 25 non-GET/HEAD requests before dispatch, had zero
checkout mutations and zero click events, and closed its Page. Two existing
`SNAPSHOT_SCRIPT(pixelSlots=[])` observations 5.03 seconds apart were fully
sanitized to structural metadata. The first snapshot had one Viewer root but no
`#xCVPages` or seek control and failed parser root-selector validation. The
second had 21 wrappers and live seek value 21, min 1, max 21, step 2; the unique
Last marker was at slot 20 and the tail roles were CI/PR/PR/Good/Last at
16-20. Slots 1-15 were body-class candidates; only 1-3 had loaded/rendered
925×1329 canvases, 4-5 were loaded without canvases, and 6-15 had only
`-cv-page`. The earlier read-only snapshot was rejected because the standard
parser expected `seek_max=len(slots)-1` (20 for these 21 wrappers). A later
bounded public-seek probe on the exact active grant observed values 21, 19, 7,
5, 3, and 1 mapping to body slot 1; body 2-3; body 14-15; CI/PR 16-17;
PR/Good 18-19; and Last 20. The `standard_odd_body` profile recognizes a
conditional structural family: no top-empty flag; positive
`mode-has-pr`, `mode-has-comic-info`, and `mode-has-good-page`; exact lead,
contiguous odd body B>=3, and CI/PR/PR/Good/Last tail roles; and seek min=1,
max=wrapper_count, step=2. Every accepted member also requires exact marker
sets and selected wrapper centers at maximum, body, CI/PR, PR/Good, and minimum.
Live B=15 metadata (21 wrappers, body 1-15, tail 16-20) establishes the
observed structure. Its separate existing-grant direct Capture through END/ZIP
ran under the earlier count-specific `standard15_body` fix, before the current
parametric generalization. Live B=7 metadata (13 wrappers, body 1-7, tail
8-12) confirms its marker/center mapping but does not establish Viewer readiness
or successful Capture. Synthetic B=9 full Runner coverage passed. Python
parsing, JS capture geometry, and native proof apply the same contract;
unsupported shapes remain fail-closed. A fresh quota-consuming run through
END/ZIP has not yet validated that full path. The public-seek
probe restored value 21, read metadata only, and made no capture, click, or
checkout. Evidence:
`output/younganimal_work_ticket_tester/readonly_viewer_diag_0634.json`,
`public_seek_metadata_0634_attempt3.json`, and
`saved_viewer_structure_0634.json`.

An independent direct Batch capture on the already-active grant for episode
`856137d88753b` / work `8246f8b8b2e6c` completed 28 pages through END and
produced a 28-member CRC-valid ZIP with zero click/checkout and no new ticket
use. It validates the existing-grant direct path only. Evidence:
`output/younganimal_work_ticket_tester/direct-one-shot-856.json` and
`direct-postflight-856.json`.

After the earlier count-specific `standard15_body` fix, direct Batch on the already-granted episode
`0634e2ac53df6` / work `145fe0e303563` also exited 0 and completed a new Run
with 15 pages through END. The Page audit recorded one owned Page, one goto,
and one main-document request, with zero reloads, off-target/series navigation,
commerce clicks, or checkout POSTs. The prior failed Run, Source grant/quota
timestamps, and Work last-consumed time were unchanged. The ZIP contained 15
ordered 925×1329 PNGs; CRC, decode, manifest order, Catalog completion, and
archive SHA validation passed. No per-image hash or source-native format claim
is made. Independent review passed. Evidence:
`output/younganimal_work_ticket_tester/direct-postflight-0634.json` and
`direct-preflight-0634-provenance.json`. This verifies direct capture with an
existing grant; fresh quota consumption through same-Page END/ZIP remains
pending.

A fourth authorized normal Batch work-ticket use occurred on episode
`c7819ded99f66` / work `5d1e949cd0b52` at `2026-10-18T18:33:53.283098+09:00`.
One exact wait-free click, target-bound checkout HTTP 200, and authenticated
native `waitAndFree` false-to-true transition confirmed resource use. The Source
grant expires at `2026-10-21T18:32:56.842671+09:00`; the same-work 23-hour
cooldown ends at `2026-10-19T17:33:53.283098+09:00`. The CLI then failed before
Capture with `PageChangeTimeoutError`; the Item remains pending with no pages,
END, ZIP, or Artifact. A bounded read-only follow-up on the active grant
verified exact work/auth/native state and a 13-wrapper profile. Public seek
values 13, 11, 7, 5, 3, 1 mapped to body slot 1, body 2-3, body 6-7, CI8+PR9,
PR10+Good11, and Last12. Marker flags matched. The current parser recognizes
this as a B=7 member of `standard_odd_body` only when its positive capability
flags, exact wrapper roles, marker phases, and selected centers validate. The
diagnostic observed nav-open and one splash
marker throughout, so it does not establish Viewer readiness. It made no click,
checkout, image read, or Capture call. Evidence: `output/younganimal_work_ticket_tester/normal-postflight-c781.json` and
`output/younganimal_work_ticket_tester/public_seek_metadata_c781_attempt1.json`.
No balance-delta claim is made. Ticket use is now 4/5.

The ticket ledger is 4/5. Stage A full and incremental Discovery on the first
used work retained the manual grant; a disposable stale-grant cache copy then
skipped grant-only as already granted with no click or checkout. The first local
cooldown audit was **INCONCLUSIVE** because its hard sentinel stopped before
CDP. A corrected isolated audit allowed one transparent CDP attach while
blocking Page creation/navigation and site requests. Both normal and grant-only
CLI runs exited 0 with `work_ticket_cooldown`, one skipped candidate, zero Page
or site activity, and no Catalog/artifact mutation. The local same-work cooldown
gate is verified before Page/site access. Evidence:
`output/younganimal_work_ticket_tester/LOCAL_COOLDOWN_E15_REPORT.md`. Phase 02
listing Discovery recognizes authenticated native ticket state, and the
site-local adapter implements `quota + work_ticket` without a shared Core
change. Phases 02-03 passed independent review. The latest complete
seven-file Younganimal regression selection passed 313 tests with 0 skipped:
capture+adapter passed 162 (5 existing warnings), and the remaining
policy/live-access/discovery/batch-unit plus Discovery-browser files passed 151
(203 existing warnings). The full repository suite was not run.

This target proved the additional `top_empty_no_pr` layout: the positive
`mode-has-top-emptypage` root flag, one exact empty/no-canvas leading wrapper at
slot 0, body slots 1–28, and CI/PR/PR/Good/Last slots 29–33. Seek is 1..33 by 2.
At maximum seek, the empty wrapper and first body page are in view with
`mode-first-page` and no `mode-top-pr-page`; there is no initial blank-only step.
First, second, final-body/CI and Last states were observed with the public seek
control, then the complete production Batch run verified capture and END.
The profile derives its body interval from strict tail roles and wrapper count;
28 is the observed sample, not a hard-coded page count. Native and rendered
capture retain the same identity, mutation, geometry and pixel proof gates.

The previous exact-free verification remains valid for its two profiles:

Full live Discovery passed all 31 ranges and 925 positions with a 3000 ms
harness override; the production default was set to 3000 ms after that run.
Its isolated Catalog has 925 Items/Sources/Targets, 0 Runs/Artifacts, and 3
exact-free rows; the other 922 remain UNKNOWN, not paid.

Attempt 9 passed both final-code live free-work runs. The standard target
captured 16/16 pages as native VP8L across 9 spreads; the top-empty target
captured 44/44 pages as native VP8L across 22 spreads. Both reached Runner END,
passed ZIP and isolated Catalog audits, and preserved source fingerprints. The
top-empty audit confirms physical slots 2-45, 44 CRC-valid members, and one
completed isolated Catalog item/artifact; seven earlier failed attempts remain
in the isolated Catalog history. The standard target completed one item. Reports:
`output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/provided-free/audit.json`
and `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/topempty-free/audit.json`.

Earlier attempts 7 and 8 remain historical: attempt 7's top-empty portion timed
out before capture;
attempt 8 reached the exact episode with HTTP 200 and failed closed at native
post-encoding verification before saving a page. Its selected body proof fields
matched, but the exact failed subcondition is not attributed beyond the stored
`native_reader_layout_changed` reason. Attempt 8's audit is
`output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-8/topempty-free/offline-final-audit.json`.

The final capture-epoch rule exempts only observed ordinary `class` mutations
on the exact nested CI scroll widget: same-token-set no-ops in its two known
states, and the observed base-to-`mode-scroll-bottom` transition when finite
raw geometry proves the widget/CI is offscreen or disjoint from every active
body wrapper/canvas. Missing or ambiguous geometry and overlap fail closed.
The raw global DOM epoch still counts every observed mutation. Candidate,
selected-page, post-encode, frozen-mapping, pixel, END, atomic-spread, and
cleanup gates remain unchanged. The current revision passed independent review
and the latest affected local suite; see the current progress checkpoint.

The reviewed initial UI settle waits until the read-only viewer `mode-nav-open`
state is false and the `.-cv-splash` count is zero, then requires the existing
one-second stable canvas/capture-epoch quiet interval within the same five-second
deadline. Reappearing UI resets that interval. Missing or malformed metadata
and non-settling UI fail closed before collection. Native selection,
post-encoding verification, D fallback, and the frozen viewer mapping remain
unchanged. The raw global DOM epoch remains available for diagnostics while
capture stability uses a separate epoch. The final-code top-empty live pass
reached END for all 44 pages after this settle and CI-widget proof rule.

The preceding diagnostics iteration added a bounded YA mutation journal and
typed native failure metadata: expected/observed seek, route, DOM epoch, viewer
node identities, wrapper count, selected canvas identity/generation/write,
dimensions, rectangles, readiness/context, and pixel/replay equality when safe.
Pixel diagnostics run only for the exact selected target, wrapper, holder, and
proof dimensions within the existing per-canvas pixel bound; otherwise those
readbacks are explicitly unavailable. Rectangle predicates use unrounded DOM
coordinates, while serialized coordinates remain rounded. The journal holds at
most 64 safe class/id/child-list records. DOM generation advances by the full
MutationObserver batch before diagnostic summarization; a per-record summary
failure is contained, later records continue, and the report marks coverage
incomplete with an unrecorded count. Overflow also reports incomplete coverage.
URL query/hash values, HTML, arbitrary text, image bytes, and full RGBA buffers
are excluded. The reviewed capture-epoch implementation retains these bounds
and adds the narrow CI rule summarized above. Attempt 9 exercised this final
revision on both live profiles: the 16-page standard target and the 44-page
top-empty target.

## Registration and crawl entry

The CLI registers Younganimal for Discovery, manual Crawl, Batch adapter, and
Batch Site Policy. All paths use the repository's shared CDP BrowserSession and
Playwright Page; the adapter does not launch Chrome or select a profile. The
policy selects available free sources and paid sources with a future observed
rental grant; the
configured Batch adapter requires direct strategy and a strict work/episode
external identity. No shared Core or Catalog schema changes were made.

Manual Crawl requires:
- source URL: the exact canonical episode URL, for example
  https://younganimal.com/episodes/55889b8a851cb
- environment value YOUNGANIMAL_WORK_URL:
  https://younganimal.com/series/&lt;13-lowercase-hex-work-id&gt;

Both manual and Batch Crawl navigate directly to the canonical episode URL.
The configured manual work URL validates the episode header's exact same-work
link; it is never visited by Crawl. The adapter does not traverse or read episode
listing rows during Crawl. Exact route/header identity and the strict body-canvas
viewer parser provide entry proof. A visible `.ep-main-content.mode-charge` /
`.ep-main-content .ep-charge`, or a visible reader control for すぐ無料で読む,
待つと無料で読む or この話をレンタルする, stops entry without clicking.
The check repeats before viewer observations. Missing/unknown reader state
remains fail-closed. No login, ticket, coin, point, purchase, rental activation,
or next-episode action is performed.

## Discovery

Discovery accepts only a canonical first-party series URL matching
https://younganimal.com/series/<13-lowercase-hex-work-id>. Episode seeds are
rejected before AccessGuard startup/navigation because only a series URL defines
the supported Discovery scope. Episode URL parsing remains available for public row identities and
bounded-scope boundaries. This is a Lead-approved safety deviation from the
original episode-seed plan; the work ID from the supplied target is an example,
not an allowlist.

The Discovery adapter validates the canonical work title and buffers the complete
declared range map before yielding. It checks each route against the same range
map, declared row count, unique episode IDs, and first-party canonical URLs.
Output order is latest-first while global display positions remain the
oldest-first whole-work indices. Inclusive bounded scopes retain global positions.
An optional epListUser root is awaited until `mode-loading` clears within 12
seconds. Its canonical unique episode IDs and titles are validated; matching
public/user identities must have identical normalized titles. User rows supplement
public access observations but never add Items or positions. Duplicate IDs,
malformed identities and conflicting titles fail buffered Discovery. User rows
outside the current public range are not yielded.
The observed 最新話から control is accepted
only at the same-work /new path. An optional ... placeholder is ignored only when
the raw anchor has no href; unknown controls and route changes fail closed.

One exact row-local 無料 label maps to free. A matching user's exact normalized
`レンタル中 閲覧期限 D日+H時間` label maps to paid with
`access_granted_until = observation time + D days + H hours - 1 hour`.
This is a conservative lower bound, not exact expiry; days 0..14, hours 0..23
and a positive lower-bound duration are required. Other countdown formats,
near-expiry durations, 今なら無料, 待つと無料, blank, repeated and unrecognized
labels remain unknown. Free takes precedence over rental on the same identity.
Unknown observations preserve a stored grant; a positively observed exact
denial or valid grant refreshes it. Policy selects only a strictly future,
timezone-aware paid grant as non-consuming `direct` / `active_rental`;
unavailable, expired and malformed grants are excluded.

During the existing canonical work-listing traversal, Discovery observes the
site's natural `GET /api/series/access` and `GET /api/auth/session` responses;
it issues no additional request. A positive integer session user and an exact
response `seriesAccess.seriesId` matching the canonical work are required
before joining episode rows by ID. Only `accessType=waitAndFree` is classified:
`hasAccess=false` with a missing or exact zero timer is a `quota` candidate;
null, positive, or malformed timers remain unknown. An exact active row with a
valid positive `timeRemainingInSeconds` is a manually used ticket grant; its
conservative expiry is request-start plus timer seconds minus one, shortened
when the account rental label provides an earlier lower bound. Other access
types, contradictory timer states, foreign/duplicate or missing rows, and
unavailable authentication remain unknown. Native observations do not
override an exact free label or active rental. The live listing
observation confirmed this schema and positive auth; no ticket was used during
Discovery.

The Younganimal Policy exposes one `work_ticket` resource pass scoped to a work,
with quota limit one and a local minimum 23-hour cooldown after observed
consumption. A longer configured cooldown is honored. The adapter supports only
explicit quota/work_ticket entry: it verifies the canonical target, exact work
header, positive auth and current native `waitAndFree` state before considering
one exact free control. Already-active grants are non-consuming direct access
in normal Batch and skip grant-only. A single retained control is clicked once
after a trial and final same-Page checks; repeated attempts are forbidden.
Consumption is exposed immediately after a post-click target-bound successful
checkout plus the exact same-work/episode native false-to-true transition. A
valid positive native timer supplies a conservative expiry; otherwise expiry is
unknown. Normal Batch hands that same Page to the unchanged Viewer/Capture/END/ZIP
flow; grant-only creates no capture/package and leaves the Item pending. The
route guard aborts and records recognized same-work read-only RSC GET prefetches
without failing the episode run. Phase 04 observed one off-target episode `GET`
fetch with the `_rsc` query key and an `rsc` header. The exact same-origin
canonical route signature is now recorded and aborted before reaching the
network handler, without retaining or using query/header values or its
response; the selected episode run may continue. The guard retains an internal count capped
at 16 and up to 16 sanitized paths, not output metadata. Missing either marker,
another method, resource, navigation, or frame shape, other series routes,
off-target navigation, unexpected subframe navigation, and unknown RSC routes
remain fatal. Immediately before the action latch, both route evidence and
recorded 403/429 access stops are checked again. This Phase 04 guard regression
is synthetic; live CLI verification remains pending. Exact other-episode page
paths are classified before the generic static-resource pass-through; asset
suffix paths keep their previous handling.
The later zero-dispatch guard trace also observed same-origin RSC GET fetches
for `/` and `/store_items/series/<positive-id>/<positive-id>`, plus Stripe
controller/m-outer and Facebook `/tr/` third-party subframe navigations. These
route families now have narrow abort-only predicates; requests never reach the
downstream test/application handler, and bounded diagnostics store paths only.
Stripe matching ignores URL fragments. Facebook requires an empty fragment,
but the trace omitted request-fragment presence, so its production match remains
unverified until the next sanitized audit records that Boolean. No ticket was
used during that audit.
The latest complete seven-file Younganimal regression selection passed 313
tests with 0 skipped: capture+adapter passed 162 (5 existing warnings), and the
remaining policy/live-access/discovery/batch-unit plus Discovery-browser files
passed 151 (203 existing warnings). The route-drift fixture triggers the exact
series main-frame navigation only after positive consumption proof and asserts the guard's observed rejection. Phase 04
grant-only and both-mode before-Page/site cooldown verification passed. One
normal Batch ticket grant was confirmed; its first Viewer attempt failed before
Capture. Direct Batch on that episode's already-active grant later completed 15
pages through END and passed ZIP/Catalog validation with no further resource
use. The conditional `standard_odd_body` signature is implemented consistently
in Python parsing, JS geometry, and native proof, and passed independent review
plus focused synthetic checks. Live B=7 metadata is mapped but has not been
through Capture; the B=15 existing-grant direct capture ran under the earlier
count-specific `standard15_body` fix, before the current parametric generalization.
Synthetic B=9 Runner coverage passed. Fresh quota-consuming normal END/ZIP
remains pending. The full repository suite was not run.
Full Discovery buffers before yielding, so an incomplete
traversal cannot mark unseen sources unavailable. Maximums are 100 ranges and
3,000 rows.

Incremental Discovery refreshes the entire validated requested scope rather
than stopping at a newest known streak: old episodes can gain or lose rental
access. The adapter's existing stop hook returns CONTINUE. All ranges were
already buffered before yielding, so this adds no browser requests. Incremental
still does not reconcile unseen sources as unavailable.

Discovery waits 3 seconds before every numeric range route. A Playwright
DOMContentLoaded timeout is retried only when the exact current attempt proves one
matching main-frame document request and its matching response is HTTP 200, and
the current route remains exact after the timeout and again after a 2-second
backoff plus AccessGuard check. There is at most one retry per route and two
retries per work. Unknown response evidence, non-200, redirect/drift, other
Playwright errors, and access stops are not retried. Request/response listeners
are removed on every path, and no response body or retry header is read. The
earlier /3 timeout cause remains unknown; this recovery does not assign a cause.
AccessGuard cleanup is bounded. After the native access observer drains its
bounded response tasks, Discovery checks AccessGuard again before constructing
or yielding any records. A fatal response arriving during the final body drain
therefore leaves the full listing uncommitted.

## Viewer layout and capture

A metadata-only direct target probe, after a fresh exact-free listing proof,
returned HTTP 200 at the supplied episode route. The embedded public row proved
one exact target route, work aee4fa742b0fe, and exact label 無料. The report is
ignored at
output/younganimal_experiment/phase03a_viewer_probe_20261011_direct_target.json;
it contains metadata and in-page pixel digests, not page images, HTML, or response
bodies. The reported prior-listing-age value is invalid because it mixed a
monotonic timestamp with file modification time; age is UNKNOWN.

Observed viewer contract in that probe:
- unique #comici-viewer, #xCVSeekBar, and #xCVPages;
- 22 direct physical wrappers; public seek min=1, max=21, step=2;
- physical slot 0 is the exact mode-empty/mode-pr/mode-top-pr lead-in with no
  canvas; body slots 1–16 are contiguous; tail roles are CI at 17, empty PR at
  18–19, Good at 20, and Last at 21;
- public seek values 21,19,…,1 were observed. A resumed value was rewound to 21
  using the public control. At minimum seek 1, #xCVLastPage was visible in slot 21;
- body canvas bitmaps sampled in the probe were 984×1329, with 656×886 CSS bounds.
  The first-state source trace also saw WebP transport images at 960×1297 and
  960×1296 intermediate tiled draws. It did not link those responses to individual
  body slots or prove original-byte/pixel reconstruction.

The resource summary also lists api-ai.comici.jp image responses. They are
treated as tracking/pixel traffic, not body-source evidence, and that host is
excluded from the Younganimal AccessGuard relevant-host profile. The profile
includes the observed site, viewer-image, and public-content image hosts.

The initial probe's same_candidate_identity field compared slot/canvas IDs and
indices; it did not prove JavaScript object identity, mutation generation, or
write continuity. Its body_continuity_proven and end_semantics_proven flags are
false because that diagnostic did not assert those contracts. Attempt 9 later
verified the production Runner's strict mapping, ordered body capture, native
output, and terminal checks on both final-code profiles.

The live sample has 22 wrappers and 16 body slots, but the adapter does not fix
that count. It validates the exact observed lead/tail role classes and their
positions, then derives the contiguous body interval and requires the public
seek range to match the physical wrapper count. A second exact-free work exposed a distinct top-empty profile. Its observed sample had 51 wrappers and seek 1..51 by 2. The root flag `mode-has-top-emptypage` is required; in that sample, slot 0 was the exact lead-in, slot 1 the centered `-cv-page mode-empty` wrapper with no canvas, body slots were 2..45, and tail roles were CI 46, PR 47-48, Good 49, Last 50. At max seek 51, first/top-PR flags accompanied the centered blank. One public step to 49 centered body slots 2 and 3 and cleared those transient flags. This bounded evidence is in `output/younganimal_experiment/blank_variant_probe/blank_wrapper_probe_20261011.json`. It did not test terminal seek, a full 44-page crawl, native capture, or a challenge detector. The production parser does not allowlist 51: it accepts the dynamic profile only with the positive root flag, exact lead/blank/tail roles, contiguous derived body interval, and `min=1`, `step=2`, `max=wrapper_count` relation. Other wrapper totals for the standard profile have not been individually verified live. No generic blank skip is inferred. Unrecognized wrapper classes, interior gaps,
changed range/route, duplicate canvas candidates, unreadable pixels, and
incomplete spreads fail closed. It rewinds any resumed public seek to the maximum and
requires the first body canvas to stay unchanged for 1 second within a 5-second
bound. Before that interval starts, typed read-only metadata must show the viewer
navigation panel closed and no `.-cv-splash` nodes. Reappearing UI resets the
interval; malformed metadata or UI that remains active through the same deadline
fails closed. Capture stability uses a separate epoch; raw global DOM
generation remains available in diagnostics. Subsequent seeks use the public range value with ordinary
input/change events. After all body slots are captured it seeks to the minimum and reports END
only when the unique Last marker is visible and no body wrapper center is in view.

The top-empty profile's slot 1 is a non-body initial blank and is skipped only after max-seek structural proof and one public seek step to `max - step`; both first body slots must be ready. Known temporary body classes (`-cv-page`, `mode-loading`, `mode-loading mode-req-render`, `mode-loaded`, and `mode-loaded mode-rendered`) remain structural states only. An active blank/loading body cannot be captured. Unknown wrappers fail closed.

The adapter prefers verified C source-native pixels when every active half has a
supported full-frame draw candidate. The observer copies the source canvas into a
private immutable canvas at draw time, then replays the source-to-target draw using
runtime dimensions and captured smoothing/context state. It selects the native
snapshot only when replay RGBA exactly matches the active body canvas and the full
strict Python viewer parser validates the current spread against the frozen
body/tail mapping, layout variant, and seek bounds recorded at initialization.
A single-use post-Python proof binds the route, viewer/wrapper/canvas nodes, physical slot, seek, dimensions,
generation/write counts, layout, readiness and pixels. Unsupported, clipped,
incomplete, over-bound or mismatched candidates fall back for the whole active
spread to D. Any mutation after native selection fails with UnknownPageStateError.
PNG encoding and hashing stay outside the draw hook. Verified native PNG is
converted to VP8L WebP only when the decoded RGBA is identical; otherwise the same
verified PNG is retained. Candidate and proof references are bounded. A failed or
cancelled selection clears the bounded window even when Python did not receive its
token; successful cleanup releases only the selected slots so later draw-time
candidates remain available. Rendered observations and native pre/post proofs all
retain the frozen mapping.

D rendered body-canvas PNG remains the atomic fallback. A document-start observer
records canvas object IDs, dimensions, Canvas 2D writes, dimension resets, viewer
mutations, and RGBA fingerprints. One synchronous capture retains actual DOM
references and checks route, seek, roles, dimensions, generation/write counters,
layout, and pixels. Python decodes every PNG and checks its RGBA fingerprint
against the in-page readback. Generic locator/screenshot fallback is disabled.
Neither path hard-codes Hanayume dimensions or wrapper arithmetic.

Bounded source attribution reports are ignored at
`output/younganimal_experiment/native_attribution_probe_20261011_retry2.json` and
`native_attribution_validation_20261011.json`. Slots 1, 8, 9, and 16 have sampled
draw-time snapshot/replay and selected target node/generation/write/layout/pixel
proof. For sampled first/middle paths, actual response bytes were WebP at
960×1297, tiled as sixteen 240×324 pieces into a 960×1296 intermediate, then
scaled to the 984×1329 body canvas. The nonidentity map and pixel difference rule
out saving those sampled response bytes as-is; JPEG DCT does not apply to those
WebP samples. Slot 16 response-byte attribution remains UNKNOWN. This is not an
all-page original-byte claim; no research image bodies were saved.

## Current verification status and remaining work

The rental/direct-entry change passed all six affected Younganimal unit and
browser test files: 171 passed, 0 skipped, with 207 existing pytest-asyncio
deprecation warnings in 172.75s. This covers free/rental Batch-to-Runner-to-ZIP,
all three viewer profiles, no listing navigation, central access-gate rejection,
HTTP 429 stop, account-row loading/identity conflicts and stale-grant clearing.
The final incremental refresh adjustment was also checked by the targeted
Discovery unit/browser rerun (51 passed, 0 skipped). `ruff check src tests` and `git diff --check`
passed. No global full suite or Research tests were run: shared code and probe
contracts were not changed. The previous independent CLI/capture reviews belong
to the earlier exact-free iteration, not to the current rental change.

Attempt 9 verified the final code on both live exact-free profiles: the standard
target captured all 16 pages as native VP8L over 9 spreads; the top-empty target
captured all 44 pages as native VP8L over 22 spreads. Both reached END, passed
independent ZIP/CRC, raw hash and decoded-RGBA audits, completed one isolated
Catalog item/artifact, and retained unchanged source fingerprints. The separate
reports are `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/provided-free/audit.json`
and `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/topempty-free/audit.json`;
the combined independent audit is `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/independent-final-audit.json`.
Attempts 7 and 8 remain historical incomplete attempts; attempt 6 used the
preceding geometry rule. None is substituted for attempt 9's final-code proof.

The independent 44-page synthetic Runner compares every native output against
fixture-source RGBA and verifies END/ZIP bytes. The current geometry contract
accepts same-state token-set no-ops on the exact nested CI widget, and the
observed base-to-`mode-scroll-bottom` transition only with positive finite proof
that the widget/CI is offscreen or geometrically disjoint from all active body
wrappers/canvases. Ambiguous/missing geometry and overlap fail closed. Attempt
8 does not prove that its slot-46 record satisfies this widget/geometry rule.
Global mutation accounting and all candidate, selected-page, post-encode, mapping,
layout, pixel, cleanup, and whole-spread gates remain intact.

The preceding free-only status was accurate on 2026-10-12. Work-ticket live
evidence and the four-use ledger are summarized in the current verification
snapshot above. The 0634 ticketed attempt failed in Viewer readiness; a direct
run on its existing grant later captured 15 pages through END and passed
ZIP/Catalog validation without another resource use. A fresh normal
quota/capture/END/ZIP run remains pending. Live B=15 metadata describes the structure; its separate existing-grant direct
run passed under the earlier count-specific `standard15_body` fix, before the
current parametric implementation. The current `standard_odd_body` rule passed
synthetic B=9 full Runner tests and independent review. B=7 metadata remains
capture-unverified. No universal odd-count claim is made.
The first cooldown audit was inconclusive; the corrected normal and grant-only
audits passed before Page/site access. The full repository suite was not run.

## Historical native geometry diagnostic (2026-10-11)

A bounded diagnostic observed a same-size pure translation between draw and selection for slot 2: target x moved from -947.333 to 944.667, and the wrapper shared that displacement. Relative offset, actual node identities, dimensions, generation/write counters, paint state, exact replay pixels, readiness, visibility, and centering remained valid. The underlying CSS cause is UNKNOWN. The reviewed C change permits only that equal-size target/wrapper translation with unchanged relative offset at selection; all identity, generation/write, paint, source snapshot, replay, frozen mapping, and visibility gates remain. Post-encode verification still requires exact full rectangles and rejects any later movement. Synthetic browser tests prove two-half VP8L RGBA equality, whole-spread D fallback for size/relative-offset changes, and failure after post-encode movement. Any native coverage gain on other pages remains UNKNOWN until a later standard Runner audit.

## Historical failure-diagnostics iteration (2026-10-11)

The top-empty 44-page live attempt 3 failed at native postproof before any
page save. The exact failed proof subcondition was not retained by its Runner
harness, so it remains UNKNOWN. The local diagnostics-only change preserves the
static failure reason and a bounded expected/observed report for canonical
episode path (never query/hash values), seek, DOM epoch, node-reference
identity, wrapper count, active slots, viewport, selected canvas generation
and write values, dimensions, rectangles, and readiness/context. Pixel and
replay equality are read only for the exact proof target/wrapper/holder and
exact proof dimensions within the existing pixel bound; otherwise the booleans
are null. Rectangle equality uses raw DOM values before the reported
coordinates are rounded. A 64-record journal returns allowlisted target
area/node/slot, safe class flags or changed booleans, and bounded child/tag
summaries. Mutation generations advance for the entire observer batch before
summaries are attempted; a failed summary is contained, later records continue,
and missing coverage is explicit. Overflow also marks coverage incomplete.
Initial quiet metadata is retained through Runner exceptions. This earlier
iteration did not change capture gates and was not live-run.

## Historical capture-epoch implementation checkpoint (2026-10-11)

Top-empty Batch attempt 5 failed closed before saving a page. The isolated
report is `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-5/offline-final-audit.json`.
The provided-target 16-page Batch still passed with all pages native; the
top-empty first spread failed native postproof with global DOM epoch 682 to
684 and capture epoch 677 to 679. Both complete records were class mutations
associated with physical CI slot 46, but `canonicalCiWrapper=false` and
`canonicalCiClassNoop=false`. The prior attempt-4 interpretation that these
were CI-wrapper no-ops is withdrawn.

A separate one-capture bounded probe at
`output/younganimal_experiment/canonical_ci_role_probe_20261011/attempt-3/canonical-ci-role-probe-attempt-3.json`
observed an ordinary class assignment on a nested `DIV.-cv-ci-content`. Its
immediate parent was the sole-child `DIV.-cv-ci.-cv-page-content`, directly
under the canonical `DIV.-cv-page.mode-ci` wrapper; the target and wrapper
were wholly outside the viewport. The target's class changed only from
`{-cv-ci-content}` to `{-cv-ci-content, mode-scroll-bottom}`. The single probe
capture returned successfully, but it was not a Runner crawl or saved page.
Connecting that observed transition to attempt 5's failure is an inference
across separate attempts, not a directly recorded identity match.

The local, not-yet-reviewed change keeps the raw global DOM generation
incrementing for every observed mutation and adds a separate capture-stability
epoch. It exempts only an ordinary class mutation on the exact, offscreen,
sole-child nested CI widget under the canonical CI wrapper. Allowed token sets
are base-to-base, scroll-state-to-the-same-scroll-state, or base-to-scroll-state
using ASCII HTML whitespace tokenization. Reverse transitions, unknown tokens,
namespace or missing values, other ancestors or widgets, IDs, viewer changes,
and structure still advance the capture epoch. Candidate draw-to-selection
eligibility, global generation, native post-encode proof, Python quiet
signatures, rendered-D before/after checks, frozen mapping, node, generation /
write, layout, context, readiness, pixel proofs, and cleanup remain unchanged.

Synthetic browser coverage captures all 44 top-empty pages as native VP8L,
matches every decoded RGBA to independent fixture-source pixels, reaches END,
and verifies ZIP bytes. Twenty-two fixture verifications include the approved
CI serialization and widget transition; negatives cover unknown tokens,
reverse transition, non-CI lookalikes, reparenting/replacement/missing widget,
and namespace changes, with no save, locator fallback, or leaked proof.
Focused browser/unit selection passed 29 tests, 0 skipped, with 5 existing
pytest-asyncio warnings; the complete capture unit file passed 32 tests, 0
skipped, with 1 existing warning. Ruff, compileall, and `git diff --check`
passed. These are synthetic results. At this historical checkpoint, independent
review and another top-empty live run were pending; attempt 9's final-code
independent audits are recorded in the current verification snapshot above.

# Younganimal adapter

The adapter provides Discovery, direct manual episode Crawl, and Batch support
for free sources, active rentals, and explicit `quota + work_ticket` entry. It
reuses the shared CDP BrowserSession / Playwright Page, AccessGuard, Runner,
manifest, and packager. Discovery recognizes authenticated work-bound wait-free
candidates and active manual grants from naturally emitted listing responses;
it does not click or consume tickets.

The current verified fresh-quota path is a normal Batch run on episode
`849948508c8bc` / work `71460b2b6686f`: one exact wait-free click and a bound
checkout were followed on the same Page through the standard Viewer, END, ZIP,
and Catalog completion. Eight ticket uses are recorded: all five original
uses, DD9 and 849 from the separately authorized candidates, and a later
user-triggered use on 8d92. Two of three separately authorized additional
candidates were consumed; `4ba85f4c9e538` remains unopened and unused.

The 849 run recorded consumption at `2026-10-19T00:06:51.538338+09:00`, grant
expiry `2026-10-22T00:05:58.369033+09:00`, and local 23-hour cooldown end
`2026-10-19T23:06:51.538338+09:00`. The same Page produced 12 ordered 934x1329
PNG pages through END. ZIP CRC/decode/order/MIME/dimensions, manifest, Catalog
completion, and Catalog/archive SHA checks passed. Archive SHA-256 was
`cf4a3f5d897f762dc042d770f3ad04ebb192ad2855255d8cb7711dca321de0c1`
(11,388,813 bytes). No source-native format, balance-delta, or per-image hash
claim is made. Sanitized evidence:
`output/younganimal_work_ticket_tester/normal-849-attempt1-postflight.json`.

The run used one owned Page, one Python `Page.goto`, and zero reloads. Two
same-target main-document requests and four same-target navigation/frame events
were recorded; their cause is UNKNOWN. Seven off-target episode RSC GETs were
aborted and no series/off-target main-frame navigation occurred. Natural
mission, read-completion, pixel/analytics, notification, and points traffic was
also observed, so this is not a zero-total-traffic or request-initiator claim.

Existing-grant direct captures on 856 (28 pages), 0634 (15), C781 (7), and 78
(12 WEBP) passed through END/ZIP without another resource use. Normal attempts
using tickets three through six on 0634, C781, 78, and DD9 each confirmed a use
but failed before Capture artifacts. DD9 remains fail-closed for its observed
`mode-v`/`mode-single` no-seek/no-CI layout. The 78 action sentinel is absent,
so click/checkout counts are UNKNOWN. The conditional `standard_odd_body`
profile is strict across Python parsing, JS geometry, and native proof; live B=7
and B=15 evidence and synthetic B=9 coverage do not authorize arbitrary odd
layouts. The narrow CI exception applies only to observed class pairs with the
existing geometry, identity, and active-body proof.

## Earlier live verification (2026-10-18; historical)

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
mutations on one exact nested CI scroll widget. After canonical scope validation,
base-to-base and scroll-bottom-to-scroll-bottom same-token-set no-ops remain
accepted without geometry checks. The base-to-scroll-bottom transition is
accepted only with positive finite geometry proving the widget/CI is offscreen
or disjoint from every active body wrapper/canvas. The later exact
base-to-overflow and overflow-to-overflow pairs require that same strict geometry
proof. Missing, ambiguous, or overlapping geometry fails closed. Global DOM
accounting, candidate identity,
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
The later Item/Source 33083 read-only trace also observed
`/store_items/<positive-id>` RSC GET fetches. These use the same abort-only
known-page predicate: exact same-site origin, main-frame fetch, no navigation,
and both `_rsc` query and `rsc` header markers. The product prefetch is blocked
without failing the selected episode; other signatures remain fatal.
The adapter recognizes only these observed route families with their reviewed
origin, method, resource, navigation, and query constraints, then aborts them
before any downstream handler. Stripe matching ignores URL fragments. The
original zero-dispatch trace omitted request-fragment presence; the later 849
production audit classified an observed subframe as
`facebook_known_subframe_navigation`. The audit records that bounded
classification, not a fragment value.

Fatal route errors include the reason classification in CLI/metrics error text.
Failure `diagnostics/metadata.json` includes
`adapter_debug.ticket_action_attempted` and `adapter_debug.ticket_route_guard`:
first fatal reason/request, blocked count, and bounded known-page prefetch
counts/paths. Request diagnostics contain only host (max 253 characters), path
(512), method (16), resource type (32), and navigation/main-frame flags. They
retain no credentials, query/header values, fragments, or request bodies.
Internal guard errors may have no request details. No new setting is needed.
The updated production guard passed a read-only live check on the exact failed
episode with the product prefetch aborted, no fatal reason, no click events,
and no rental-checkout attempts; no consuming grant-only retry was performed.
Evidence: `output/younganimal-error-33083-fixed-readonly.json`.

At that historical checkpoint, the seven-file regression selection passed 313
tests with 0 skipped. The current final selection and fresh-quota result are
recorded below; the 849 run subsequently completed same-Page Capture -> END ->
ZIP.

Normal Batch stays on the same Page and continues through the existing Viewer,
Capture, END, and ZIP checks. `batch run --site younganimal --grant-only
work_ticket` confirms the same entry and consumption without Viewer image
capture or packaging, leaving the Item pending. The local work-scoped policy
requires at least 23 hours after recorded same-work consumption and preserves
a longer configured cooldown. A corrected isolated test passed both normal and
grant-only modes: each allowed one transparent CDP attach, then skipped before
Page creation, navigation, or site requests. An earlier probe that blocked the
connect call was overstrict and inconclusive.

## Earlier work-ticket live status (2026-10-18; historical)

The standard full and incremental Discovery runs on episode 856137d88753b / work
8246f8b8b2e6c retained its active manual grant. A disposable stale-cache copy
cleared the local grant and `--grant-only work_ticket` skipped as
`work_ticket_already_granted` with zero click or checkout. This did not verify
the local cooldown-before-Page gate or normal capture. Each Discovery run also
observed 34 off-target episode GET/HEAD requests that were not main-document
navigations; their initiators were not established. Evidence:
`output/younganimal_work_ticket_tester/stageA-856137d88753b/STAGEA_REPORT.md`.

One authorized `--grant-only work_ticket` run then succeeded for episode
e15e15c6ec11a / work 128888a1fb162. The CLI exited 0 with
`entry_confirmed`/`resource_consumed=true`, one delegated click, a target-bound
checkout POST returning HTTP 200, and a positive-auth native transition from
ungranted `waitAndFree` to active `waitAndFree`. The isolated Catalog records
the use at 2026-10-18 17:14:10.767250 JST; the minimum same-work cooldown ends
2026-10-19 16:14:10.767250 JST. The Item remains pending with zero pages and no
images or artifacts. No balance delta is claimed. The trusted DOM event list
was empty, so trusted-event proof is not verified; a derived sentinel counter
was stale and must not be repaired by repeating the action. The same Page audit
recorded two selected-episode main-document requests and no series/off-target
main-document request. The adapter source has no post-click goto/new-Page call,
but the cause of the second request is unknown. Evidence:
`output/younganimal_work_ticket_tester/GRANT_ONLY_E15_REPORT.md`.

One normal Batch run on episode `0634e2ac53df6` / work `145fe0e303563`
consumed the third authorized ticket at 2026-10-18 17:32:39.739556 JST. The
target-bound checkout and native state confirmed access, and the isolated
Catalog recorded a grant expiry of 2026-10-21 17:31:58.911149 JST. The CLI
then failed with `PageChangeTimeoutError`: the Viewer did not expose a stable
known layout within 20 seconds, Capture never started, the Item stayed pending,
and no page or archive was produced. No quota-consuming retry was made. Its minimum same-work
cooldown ends at 2026-10-19 16:32:39.739556 JST. Evidence:
`output/younganimal_work_ticket_tester/NORMAL_BATCH_0634_REPORT.md` and
`output/yanc-0634/younganimal/diagnostics/`.

A bounded read-only diagnostic on that already-granted episode verified the
canonical route/work header, positive auth, and exact active `waitAndFree`
native state. Its two Viewer metadata samples were 5.03 seconds apart and used
the production `SNAPSHOT_SCRIPT` with no pixel slots. The first snapshot had a
viewer root but no pages/seek; the second showed 21 wrappers with live seek
range 1..21 by 2, Last at slot 20, and CI/PR/PR/Good/Last at slots 16..20. The
Slots 1-3 were initially loaded/rendered at 925×1329, slots 4-5 were loaded
without canvases, and 6-15 were not loaded. A later bounded public-seek probe
on the exact active grant observed values 21, 19, 7, 5, 3, and 1 mapping to
body slot 1; body 2-3; body 14-15; CI/PR 16-17; PR/Good 18-19; and Last 20.
The live B=15 sample is recognized as one member of the conditional
`standard_odd_body` family: no top-empty flag; positive `mode-has-pr`,
`mode-has-comic-info`, and `mode-has-good-page`; exact lead, contiguous odd body,
and CI/PR/PR/Good/Last tail roles; and `min=1`, `step=2`, `max=wrapper_count`.
Exact marker phases and selected wrapper centers are required at each sampled
state; unsupported structures remain fail-closed. Synthetic B=9 Runner coverage
exercises the same contract. The probe restored
seek 21, read no pixels, performed no capture/click/checkout, and closed its
Page. The focused synthetic Runner reached END and validated ordered ZIP CRC
and decoded RGBA against fixture source pixels; the independent Reviewer passed
the profile and focused regressions. A later direct Batch run on the existing
grant verified the profile through END/ZIP. At that historical checkpoint,
fresh quota-consuming verification remained pending; the 849 result is in the
current checkpoint above. Evidence:
`output/younganimal_work_ticket_tester/readonly_viewer_diag_0634.json`,
`public_seek_metadata_0634_attempt3.json`, and `saved_viewer_structure_0634.json`.

An independent direct Batch run on the already-active grant for episode
`856137d88753b` / work `8246f8b8b2e6c` completed through END with 28 pages and
a 28-member CRC-valid ZIP. It used the exact Catalog URL on one Page with zero
click/checkout events and no new ticket use. This confirms existing-grant direct
capture only, not a fresh quota-consumption run. Evidence:
`output/younganimal_work_ticket_tester/direct-one-shot-856.json` and
`direct-postflight-856.json`.

After the earlier count-specific `standard15_body` fix, direct Batch on the already-granted episode
`0634e2ac53df6` / work `145fe0e303563` exited 0 and completed a new Run with
15 pages through END. It used one Page, one goto, and one main-document request;
there were zero reloads, off-target/series navigation, commerce clicks, or
checkout POSTs. The old failed Run, Source grant/quota timestamps, and Work
last-consumed time were unchanged. Its ZIP contained 15 ordered PNGs at
925×1329; CRC, decoding, manifest order, Catalog completion, and archive SHA
checks passed. No per-image hash or source-native format claim is made.
Independent review passed. Evidence:
`output/younganimal_work_ticket_tester/direct-postflight-0634.json` and
`direct-preflight-0634-provenance.json`. This validates existing-grant direct
capture, not a fresh quota-consuming entry through END/ZIP.

One normal Batch run on episode `c7819ded99f66` / work `5d1e949cd0b52` consumed
the fourth authorized ticket at `2026-10-18T18:33:53.283098+09:00`. A single
retained wait-free click, target-bound checkout HTTP 200, and authenticated
native `waitAndFree` false-to-true transition confirmed resource use. The
isolated Source expiry is `2026-10-21T18:32:56.842671+09:00`; the 23-hour
same-work cooldown ends at `2026-10-19T17:33:53.283098+09:00`. Capture then
failed with `PageChangeTimeoutError` before any page sequence, END, ZIP, or
Artifact; the Item remains pending. No balance delta is claimed. Evidence:
`output/younganimal_work_ticket_tester/NORMAL_C781_OFFLINE_PREP.md` and
`normal-postflight-c781.json`.

A bounded read-only probe on that already-granted episode used the unchanged
public seek setter and sampled values 13, 11, 7, 5, 3, and 1, restoring 13.
It observed 13 wrappers: value 13 showed first+top-PR with body slot 1; 11
showed body 2-3; 7 showed body 6-7; 5 showed CI slot 8 plus PR slot 9; 3
showed PR slot 10 plus Good slot 11; and 1 showed Last slot 12. Native marker
flags matched each observation. The previous exact-profile parser rejected
this layout with `UnknownPageStateError`. The current `standard_odd_body`
implementation recognizes the observed B=7 structural member only when the
positive capability flags, exact wrapper roles, range, marker phases, and
selected centers all validate. This metadata-only probe did not establish
Viewer readiness or a successful live capture; the later direct Batch result
is recorded below.
Viewer navigation remained open and a splash marker remained present, so this
metadata does not establish Viewer readiness. The probe made no click,
checkout, image read, or Capture call. Evidence:
`output/younganimal_work_ticket_tester/public_seek_metadata_c781_attempt1.json`.

On frozen commit `f2d7ad8`, a later direct Batch run on C781's existing grant
exited 0 and completed 7 pages through END. The ZIP contained 7 ordered
925x1329 PNGs; CRC, decode, manifest, Catalog completion, and archive SHA
checks passed. The previous failed Run, Source grant/quota timestamps, and Work
last-consumed time were unchanged. It used one Page, one initial goto, and one
main-document request; two same-target frame events were recorded, with cause
unknown. No commerce click or checkout occurred. No per-image hash or
source-native format claim is made. Evidence:
`output/younganimal_work_ticket_tester/direct-postflight-c781.json` and
`output/ydr-c781/runDB/precli-baseline.json`. This validates existing-grant capture,
not a fresh quota-consuming entry.

The final bounded read-only recheck of episode `77d27c1572ac7` used one exact
canonical goto and observed the expected work header and positive auth, but no
current episode native record, no target row in the natural series-access
responses, and zero free-ticket/charge controls. Its eligibility is UNKNOWN.
No click or checkout occurred. The page naturally generated first-party
read/mission POSTs that were aborted before network, off-target RSC reads that
were also aborted, one other-episode-like GET API path, and same-target reader
subpath GETs. There was one Python goto and one main-document request, while the
observer recorded two same-target frame navigation events with cause unknown.
These were site-generated incidental requests, not explicit probe
API/navigation calls. No retry followed. Evidence:
`output/younganimal_work_ticket_tester/readonly-77-final.json`.

The fifth original ticket was used by a normal Batch attempt on
`78a0c0e1ccfef` / work `423d7471396e9` at
`2026-10-18T20:03:38.150057+09:00`. The Source grant expiry recorded in its
isolated Catalog is `2026-10-21T20:02:57.649998+09:00`; the minimum same-work
cooldown ends at `2026-10-19T19:03:38.150057+09:00`. The CLI failed closed at
native post-encoding verification (`native_reader_layout_changed`) for a
12-body / 18-wrapper Viewer before saving any page or artifact. The action
sentinel was not written, so click and checkout event counts are UNKNOWN, not
zero. The Item remained pending; no quota-consuming retry followed. A later direct
capture on the existing grant is recorded below. Evidence:
`output/younganimal_work_ticket_tester/normal-postflight-failed-78.json` and
`output/ydr-78/runDB/precli-baseline.json`.

A later zero-resource read-only probe on the same active grant observed exact
widget transitions `-cv-ci-content` -> `-cv-ci-content mode-overflow` and an
overflow same-value write. Ten hook events reconciled with ten MutationObserver
transitions; strict widget, parent, CI, and selected-body geometry/identity were
unchanged. The exception is limited to those exact pairs with the existing
geometry and active-body checks; reverse, combined/extra, foreign, namespaced,
overlap, and ambiguous-geometry writes still fail closed. The probe used no
click, seek, scroll, pixel read, capture, or checkout. First-party POST paths
were aborted, but path-only telemetry cannot bind a reported 200 to a method;
server-side effects remain UNKNOWN. Evidence:
`output/younganimal_work_ticket_tester/ci-widget-readonly-78-corrected-summary-20261018.json`.

On frozen implementation commit `0574870`, a later direct Batch run on
episode `78a0c0e1ccfef`'s already-active grant exited 0 and completed 12 pages
through END. The ZIP contained 12 ordered WEBP images at 848x1200; CRC, decode,
manifest order/metadata, Catalog completion, and Catalog/archive SHA checks
passed. The previous failed Run, Source grant/quota timestamps, and Work
`last_consumed_at` were unchanged. No checkout or commerce action occurred and
no per-image hashes were declared. This validates only the existing-grant
direct path. Evidence: `output/younganimal_work_ticket_tester/direct-78-existing-grant/postflight-78.json`.

The corrected local cooldown audit used a fresh copy of the e15 Catalog,
cleared only its source grant, and preserved the actual work timestamp. Normal
and grant-only CLI runs both exited 0 with `work_ticket_cooldown`, one skipped
candidate, one CDP attach, zero Page/goto/reload calls, zero requests/access
events, and no Catalog/artifact change. The initial no-connect attempt remains
inconclusive and is superseded. Evidence:
`output/younganimal_work_ticket_tester/LOCAL_COOLDOWN_E15_REPORT.md`.

The earlier isolated cooldown probe prohibited the CDP connect call and was
inconclusive; the corrected audit above supersedes it and verifies the local
skip before Page creation or site access in both CLI modes.

## Additional-candidate chronology (updated 2026-10-19)

DD9 (`dd9facaba1704` / work `06e1b9373ea6e`) passed isolated one-work
Discovery. Its first normal invocation failed at Core/Playwright CDP attach
before Page creation and used no resource. The second failed closed as
`work_ticket_unavailable` with zero click/checkout/resource use. The third
confirmed use six but failed before Capture because the saved Viewer had an
unsupported `mode-v`/`mode-single` shape without the supported seek/CI layout.
The quota grant and Work timestamp were persisted; the production capture gates
were not weakened.

849 (`849948508c8bc` / work `71460b2b6686f`) passed its own isolated one-work
Discovery and one normal Batch invocation, consuming use seven and completing
same-Page Capture through END/ZIP as described above. Two of the three
separately authorized additional uses were consumed. `4ba85f4c9e538` remains
unopened and unused; it was unnecessary for acceptance. These were sequential
single-work operations, not a multi-work preflight. Evidence for 849 is
`output/younganimal_work_ticket_tester/normal-849-attempt1-postflight.json`.

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

The one-page bonus episode `ccae6b96885d7` (Item/Source 35233) has seven wrappers
and range min=1/max=7/step=2. Its `standard_one_body` map is top PR 0, body 1,
CI 2, PR 3-4, Good 5, Last 6. Unlike the two-body shape below, seeks 5 and 3
are interstitial CI/PR and PR/Good pairs, and seek 1 centers only Last with
Last-only flags. Seek 7 centers top PR/body 1 with first+top-PR; 5 requires
CI+PR and 3 requires PR. Both short shapes require the same exact horizontal/
spread/RTL and PR/CI/Good capabilities, no top-empty/vertical/single modes,
known body classes, exact non-body roles without canvases, and all selected
centers and phases. A unique visible/centered Last marker and full captured
body coverage remain mandatory. Fewer than seven wrappers and unproven short
shapes fail closed.

Python observation, native proof, and CI geometry distinguish the one- and
two-body variants; their shared short-layout helper derives CI/tail positions
from the proven body count. The one-page isolated normal Batch completed a
native 960x1376 WebP, independently equal to source RGBA, through END/ZIP/Catalog
with max_pages=1. No retry, timeout increase, blank skip or weaker source/replay
proof was introduced.

The two-page bonus episode `9f869e61ae122` (Item/Source 35228) has only eight
wrappers, below the old generic minimum of nine. `standard_two_body` supports
this exact shape: top PR 0, body 1-2, CI 3, PR 4-5, Good 6, Last 7; range
min=1/max=7/step=2. It requires horizontal/spread/RTL and PR/CI/Good capabilities,
absent top-empty/vertical/single modes, exact role classes, contiguous known body
states, and zero non-body canvases. Other incomplete or unknown short layouts
remain unsupported.

All selected centers and phase flags must match: seek 7 selects top PR/body 1
with first+top-PR; 5 selects body 2/CI with CI+PR; 3 selects both PRs with PR;
1 selects Good/Last with Last+PR and the unique visible/centered terminal marker.
Both body pages are required before END. Python parsing, native proof and CI
mutation geometry recognize the same narrow profile, retaining source/replay,
identity/write/epoch, final geometry, byte bounds, and coverage checks. The live
isolated normal Batch completed both 960x1376 native WebP pages, independently
equal to source RGBA, through END/ZIP/Catalog; its max_pages was exactly two.
No retry, generic blank skip or timeout increase was introduced.

The no-top-PR layout also has an independently observed odd-body variant on
`fe0edd24d59ae` (Item/Source 35225, 藍より青し / 第一話 縁ーえにしー).
`top_empty_no_pr_odd_body` requires the positive top-empty flag but no extra blank
slot: slot 0 is exactly `-cv-page mode-empty`, body 1..B is contiguous, B=N-6 is
odd and at least three, and the exact five-slot tail is CI/PR/PR/Good/Last without
canvases. Horizontal/spread/RTL and PR/CI/Good capabilities must be present;
vertical/single modes are forbidden. Seek is min=1/max=N/step=2, distinct from
the existing even-body no-top-PR layout's max=N-1.

All selected wrapper centers and phases must match: maximum has first-only;
body pairs have no phase flags; seek 5 is CI/PR with CI+PR flags; seek 3 is PR/Good
with PR; minimum is Last-only with its unique visible, centered marker. No body
is skipped at initialization, and every body must be captured before END. The
live sample has B=29/N=35; these counts and episode IDs are not allowlisted.
Python parsing, capture geometry, and native proof use the same mapping. Only
draw-time observation may precede final CSS translation, under existing node,
dimension, generation/write, source/replay and full pixel checks. Selection and
postproof still require final centers. An isolated normal Batch completed all
29 native 960x1364 WebP pages with independent source RGBA equality, END, ZIP
and Catalog checks. An earlier audit observed a permitted PNG fallback for an
unproven first-page source; native availability is not guaranteed during loading.
No retry, public-seek refresh, timeout increase or proof relaxation was added.

The observed episode `24c5d5dae77b0` additionally has 18 wrappers with max seek 17,
top PR at 0, an exact blank at 1, eleven body slots 2-12, CI 13, PR 14-15, Good 16,
and Last 17. The top-empty profile now accepts this shorter odd-body family only with an
even physical count, `max=wrapper_count-1`, positive horizontal/PR/CI/Good capabilities,
and unchanged exact blank/body/tail roles. Seek 5 selects the last single body with CI and
requires CI+PR flags; seek 3 selects both PR wrappers; seek 1 selects Good+Last with
Last+PR flags and a visible unique Last marker. Exact selected wrapper centers and phase
flags are checked, and all eleven body pages are required before END.

During a seek, this Viewer draws the incoming body pair before its wrappers translate into
the viewport. Only draw-time source observation may precede the final selected centers;
the candidate still binds exact route, seek, slots, nodes, source draw, paint, dimensions,
and write generations. Selection and postproof require the exact final centers plus the
existing same-size wrapper/canvas translation and full replay-pixel proof. No screenshot
fallback, retry, or timeout relaxation was added. The isolated normal Batch verification
completed eleven native 960x1364 WebP pages, all independently equal to draw-time source
RGBA, through END, ZIP, and completed Item; the site note records evidence and limits.

The separately observed episode `1517292f23ad0` (Item/Source 34211) has only one
trailing PR wrapper. Its `standard_single_pr` profile requires horizontal/spread/RTL
and positive PR/CI/Good capabilities, no top-empty/vertical/single flags, an exact
top-PR lead, contiguous even body `B = wrapper_count - 5` of at least four pages,
and the exact four-slot CI/PR/Good/Last tail with no canvases. Its seek range is
`min=1`, `max=wrapper_count`, `step=2`. The live sample has body 1-6, CI 7, PR 8,
Good 9, and Last 10; these counts are derived rather than hard-coded.

Every selected wrapper center and phase must match: maximum seek has first/top-PR;
intermediate body pairs have neither; seek 5 has CI+PR and the final single body;
seek 3 has PR with the PR/Good pair; minimum seek has only Last with its unique
visible, centered marker. END still requires complete body coverage. Python parsing,
native capture, and CI mutation geometry use the same role mapping and existing
source/draw/replay proof. Unknown layouts continue to fail closed. Isolated normal
Batch verification of 34211 completed all six 960x1364 native WebP pages through
END/ZIP/Catalog, with independent source RGBA equality and no checkout attempt,
using its existing grant. The normal Catalog and archives were not changed.

Episode `be702296e543c` (Item/Source 35579) exposes a separate three-PR tail:
top PR 0, body 1-10, CI 11, PR 12-14, Good 15, Last 16; seek min=1/max=17/step=2.
`standard_three_pr` requires the same exact horizontal/spread/RTL, PR/CI/Good,
lead/body/no-tail-canvas and absent top-empty/vertical/single contracts as the
single-PR family, with even derived body B=N-P-4>=4 and exactly P=3 trailing PRs.
The explicit PR-tail proof helper supports P=1 and P=3; it does not infer support
for arbitrary PR counts or unobserved role sequences.

Its final single body/CI is at seek P+4=7 with CI+PR flags. Seeks 5 and 3 select
PR/PR then PR/Good with PR-only flags; seek 1 centers only Last with Last-only
and a unique visible/centered marker. Maximum has first+top-PR, intermediate body
pairs have no phase flags, and every selected center is checked. Python/native/
CI geometry derive the same role positions, preserve source/replay and frozen
body coverage, and require final geometry at selection/postproof. An isolated
normal Batch completed all ten native 960x1364 WebP pages, independently equal
to source RGBA, through END/ZIP/Catalog using its existing grant with no checkout.
No retry, deadline increase, PNG fallback change or access-resource change was made.

Readiness timeouts now retain the bounded parser rejection text (up to 256 characters) in
`adapter_debug.capture.viewer_readiness.last_error_message` and the console/metrics error.
The existing 20-second deadline and fail-closed handling of unknown layouts are unchanged.

A separate horizontal no-CI profile was observed on already-granted episode
`8d92e88ab93ec`. Its metadata had 15 wrappers and seek `min=1`, `max=15`,
`step=2`; the root was horizontal/spread/RTL with top-empty, PR, and Good
capabilities, and without comic-info, vertical, or single-page flags. Slot 0
was the empty lead-in, body slots 1-10 were contiguous, and the four-slot tail
was PR 11-12, Good 13, Last 14. The selected wrappers were 0+1 at seek 15,
2+3 at 13, 4+5 at 11, 6+7 at 9, 8+9 at 7, body 10 plus PR 11 at 5, PR 12
plus Good 13 at 3, and Last 14 at 1. All ten body canvases were observed
ready when selected. Production recognizes the structural `top_empty_no_ci`
family only with an even derived body count `B = wrapper_count - 5` of at least
four, exact roles/range/root flags, and the observed phase markers and centers;
it does not accept a count based on parity alone. Synthetic B=6 and B=10 full
Runner fixtures verify ordered body capture, pixel equality, END, and ZIP. END
also requires the unique `#xCVLastPage` marker itself to be visible and
centered within the unchanged final Last wrapper. Marker identity, parent,
visibility, viewport, role, and fake-CI mutation cases fail closed; this profile
has no CI mutation exception, and the native identity, generation/write,
replay-pixel, frozen-role, readiness, and post-encode proofs remain in force.
An existing-grant direct Batch on 8d later completed 10 pages through END/ZIP
with this profile (`top_empty_no_ci`, B=10, N=15, `ci_slot=None`, seek=1).
The archive contains 10 ordered PNGs at 925x1329; CRC, decode, manifest order
and metadata, Catalog completion, and Catalog/archive SHA checks passed. Its
SHA-256 is `c21eabe0f0c67459bf95fb789c5175b3d865d79d30621f4a177465e532d04772`
(11,643,064 bytes); no source-native format or per-image-hash claim is made.
The earlier quota-use Run still records the failure before Capture; the later
direct run used the active grant without another ticket and preserved the
Source grant/quota and Work consumption timestamps. Audit: one owned Page, one
adapter `goto`, zero reloads, one main-document request, and two frame
navigation events with unknown cause. No commerce click or checkout POST was
recorded. Natural read-completion, mission/reward, and pixel/analytics traffic
also occurred; their site-side effects are not inferred. See the direct-8d
postflight and audit artifacts under
`output/younganimal_work_ticket_tester/direct-8d-fix/`.

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

The destination may retain a fractional width/height truncated by the Viewer bitmap sizing
(observed: 933x1327.5 into a 933x1327 bitmap). Both source and destination origins remain
exactly zero and the source rectangle must cover the complete native canvas. Only finite
destination dimensions whose floors equal the bounded target bitmap dimensions are supported;
underfill, whole-pixel overhang, source crops, and nonzero offsets remain unsupported. Each
candidate retains the exact eight observed draw arguments for selection and postproof replay.
Replay never rounds the rectangle, and native output retains the source dimensions. Every
existing pixel, context, node, generation/write, layout, and all-or-none spread proof still applies.
The 2026-10-19 isolated direct Runner verification reached END for the affected existing-grant
Source 33083 and free control Source 33096 with ten 960x1364 WebP pages each. All twenty
decoded outputs matched independently copied draw-time source RGBA. It used no new ticket
and did not alter the normal Catalog or existing ZIPs; details and limits are in the site note.

The D rendered body-canvas PNG path remains the atomic fallback. The historical
D-only Runner audit covered 16 ordered 984?1329 PNG pages through END/ZIP and
passed raw SHA-256, CRC, physical-slot, and PNG-decode checks; its restored
completion status remains `PASS_WITH_STATUS_PROVENANCE_LIMIT`. The later
provided-target direct Batch live run captured all 16 pages as native VP8L,
matched decoded RGBA to traced PNG pixels, reached END, and completed isolated
ZIP/Catalog packaging. The attempt-7 audit is in
`output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-7/offline-final-audit.json`.

Attempts 6 through 8 are historical diagnostics under earlier geometry/code
revisions. Attempt 9 verified the earlier two-profile implementation; the latest
fractional-destination verification above is separate, bounded evidence. Earlier failures
remain in the isolated Catalog history and were not
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
  click and grant-only entry are implemented and independently reviewed.
  Live grant-only and both-mode local cooldown-before-Page/site verification
  passed. A normal Batch ticket grant was confirmed, but its first Viewer
  attempt failed before Capture. Direct Batch on that already-active grant
  later completed 15 pages through END and passed the ZIP/Catalog audit without
  another resource use. Fresh quota-consuming END/ZIP was later verified on 849; see the current checkpoint above.

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

## Verification status (2026-10-19)

Phase 04 passed independent review. The current seven-file Younganimal
selection covers 379 tests, 0 skipped: 95 capture-unit tests, 133
adapter-browser tests, and 151 tests across the other five files. After the
final no-CI marker and fake-widget test corrections, its 10 affected
adapter-browser cases were rerun as an overlapping subset, not counted twice.
`ruff check src tests` and scoped `git diff --check` passed. The full repository
suite was not run for this site-local change.

The fresh-quota normal Batch acceptance on 849 completed Capture -> END -> ZIP
on the same Page and passed the independent artifact/Catalog audit. Exact
consumption, grant, cooldown, archive, and navigation evidence is in the current
verification section above and `runbooks/younganimal-work-ticket/PROGRESS.md`.
At the 849 acceptance checkpoint, the original five uses plus DD9 and 849
totaled seven; `4ba85f4c9e538` was not inspected or used. A later
user-triggered use on `8d92e88ab93ec` / work `cded52d3dfcd3` is the eighth
recorded use. Its earlier quota-use attempt failed before Capture on the no-CI
layout; a later existing-grant direct run completed the updated profile through
END/ZIP without another ticket. No further ticket was used for this implementation. No
source-native format, balance-delta, or per-image hash claim is made.

Older work-ticket attempts remain distinct from the passing 849 run. Normal
attempts using tickets three through six on 0634, C781, 78, and DD9 persisted
resource use but did not produce Capture artifacts. The 78 action sentinel is
missing, so its click/checkout counts are UNKNOWN, not zero. Existing-grant
direct captures on 856, 0634, C781, and 78 passed through END/ZIP; 849 was the
separate fresh-quota normal run. DD9's unsupported `mode-v`/`mode-single`
Viewer remains fail-closed. The narrow 78 CI-widget exception does not relax
identity, geometry, native source, END, or other Capture proofs.

The final 849 audit recorded one owned Page, one Python `Page.goto`, and zero
reloads. It saw two same-target main-document requests and four same-target
navigation/frame events; their cause is UNKNOWN. Seven off-target episode RSC
GETs were aborted and no series/off-target main-frame navigation occurred.
Natural site-generated traffic was also observed; the audit does not claim zero
total site traffic or known initiators for every request. Full details and
limitations are in `runbooks/younganimal-work-ticket/PROGRESS.md`.

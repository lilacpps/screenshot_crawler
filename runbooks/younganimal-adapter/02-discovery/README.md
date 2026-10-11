# Phase 02 - Younganimal Discovery

Status: full 925-row live Discovery PASS on 2026-10-11. The live pass used a 3000 ms harness override; production pacing was subsequently set to 3000 ms before each numeric range request. The completed pass validated all 31 ranges, 925 unique episode positions, and the target at position 1 with exact free status. Older /6 timeout and HTTP 429 stops remain historical, separate attempts. The completed pass observed no 403, 429, challenge, or CAPTCHA.
Prerequisite: Phase 01 VERIFIED / BLOCKING 0.

## Contract and safety deviation

Discovery currently accepts only the exact canonical first-party series listing URL shape
`https://younganimal.com/series/<13-lowercase-hex-work-id>` with no credentials, query, fragment, or trailing slash. The user-supplied episode URL resolved to work `aee4fa742b0fe`; `https://younganimal.com/series/aee4fa742b0fe` is the current example and future continuation entry, not a work-ID allowlist.

The original proposal used an episode URL as the Watchlist seed. Review rejected that entry because navigating to an episode before reading its row-level free label would enter the viewer without positive free proof. The adapter now rejects episode seeds before AccessGuard startup or any navigation. Episode URLs remain valid for public row identities and optional bounded-scope boundaries. No episode-seed containment is claimed.

## Implemented behavior

- Validate the unique work title and the complete declared numeric range map, then visit each range in oldest-first order. Require the expected row count, stable routes and labels, unique episode IDs, and a consistent work title before yielding any episode record.
- Output source identity as `work_id:episode_id`, latest-first, with `global_display_position` retained from the oldest-first work position. Full and incremental modes both buffer the complete work; bounded slices preserve whole-work positions.
- Emit only canonical public `epList` rows. Reject any nonempty `epListUser` history root because the same-ID identity, title, and access-label relation is unverified. This deliberately limits current support to listings with an empty user/history root.
- Map only one exact row-scoped `無料` label to `free`. `今なら無料`, `待つと無料`, missing, repeated, conflicting, or unknown labels remain `unknown`. No wait, ticket, coin, purchase, grant, or resource action is implemented.
- On any incomplete or changed listing, fail before yielding episode records so the Catalog cannot mark unseen sources unavailable.

## Validation

Unit tests cover strict site/work URLs, episode-seed rejection, range maps, duplicate identities, classification, positions, and bounded cleanup. Synthetic Playwright Integration tests cover full/incremental/bounded Discovery, a conflicting duplicate in `epListUser` with zero records yielded and existing sources preserved, and episode-seed rejection with zero navigation. The CLI registry test confirms Discovery-only registration.

The adapter waits 3 seconds before every numeric range navigation, including
the first range after the canonical listing. Unit tests verify the exact delay
without wall-clock waiting; browser-backed tests verify pacing occurs before
the first and subsequent range requests using a zero-duration test override.

A `DOMContentLoaded` timeout is retried only when the exact current `goto`
attempt captured one main-frame document request for the exact expected URL
and that same Request object has one HTTP 200 response for the exact URL, while
`page.url` still matches. The guard is checked before the retry decision, then
the adapter waits 2 seconds, checks the guard and exact URL again, and retries
once at most. A shared budget allows at most two retries across the work. Unknown
status, non-200, redirect/route drift, other Playwright errors, and access stops
are not retried. This contains the earlier unexplained navigation timeout; it
does not establish its cause.

## Historical live evidence and gate (superseded by the 925-row pass below; 2026-10-11)

- The canonical work page declared 31 numeric ranges, `1-30` through `901-925`. Fresh `/1` returned 30 rows and 30 unique IDs; its selected `1-30` route pointed to the canonical work URL. Bounded samples `/2` and `/3` through `/5` also returned 30 rows. These samples do not establish all 925 rows.
- This historical live attempt used the earlier episode-seed draft, before the current series-only and history-row fixes. It stopped after nine range pages (11 navigations total) in 13.066 seconds when the shared AccessGuard observed HTTP 429 at `/series/aee4fa742b0fe/9`. No episode records were yielded. `Retry-After` was not retained. No further manual navigation or retry was issued in that run; the report does not establish whether any in-flight automatic request completed. Later bounded preflight and partial full passes exercised the corrected series-seed code, but none completed all 925 rows.
- Both isolated DiscoveryService Catalogs contain one Work row created before adapter invocation and zero items, episode sources, targets, runs, artifacts, or quota states. No normal Catalog was used.
- A separate 90-second diagnostic harness stopped at `/28`; it did not complete and does not prove an AccessGuard failure. Earlier timeout causes remain unknown.

The earlier user-authorized resume first probed the canonical listing and first numeric
range: both returned HTTP 200, with no AccessGuard stop. One full Discovery pass
then navigated the root, `/1`, `/2`, and attempted `/3`. The first three
responses were HTTP 200; `/1` and `/2` each yielded 30 metadata rows with
unique IDs. The `/3` navigation did not complete after 24.010 seconds and the
adapter returned `incomplete`; no HTTP status was retained for that request,
and no 403/429/challenge/CAPTCHA was observed by AccessGuard. The underlying
navigation failure cause is UNKNOWN. The pass stopped there with no later
range request and no retry.

A separate bounded diagnostic then navigated directly to `/3`: it received
HTTP 200, `DOMContentLoaded` at 1.191s and `load` at 1.207s. The page reached
`readyState=complete`; the strict `61-90` listing validated with 30 rows and
30 unique IDs at global positions 61-90. A fresh `/2` also returned HTTP 200
and validated `31-60` with 30/30 rows. The controls are ordinary anchors with
no `onclick`; the `/2` `61-90` anchor points at the exact `/3` route. A role
locator did not match that anchor, so no click was performed. These two quick
requests do not explain the earlier delay or establish complete traversal;
the diagnostic did not explain the earlier failure. The separately reviewed
timeout-only recovery rule above was implemented with synthetic tests; it is
not evidence of the earlier timeout's cause.

The captured 60 rows have 60 distinct episode IDs and global positions 1–60.
Their exact observed labels are `無料` (3 rows) and `今なら無料` (57 rows),
classified as 3 `free` and 57 `unknown`. The user-provided episode occurs at
global position 1 with exact row label `無料`. The isolated Catalog contains
one pre-created Work and zero episode items/sources/targets because the adapter
buffers the complete listing before yielding. The 925-row target remains
unverified; do not claim full live Discovery. The Lead later authorized a
bounded 03A metadata probe and, after that probe supplied a target-scoped
layout contract, a separate manual Viewer/Capture implementation. Those steps
do not clear the full Discovery gate or implement Discovery-to-Batch integration.

The earlier HTTP 429 run and the resumed navigation-incomplete run are separate
observations. No further manual navigation or retry was issued after either
stop; reports do not establish that every in-flight automatic request had
finished. No alternate endpoint/profile or guard bypass was used. Phase 03A was later authorized as a
separate safe probe while complete Discovery remained externally incomplete;
it does not accept or imply 925-row completeness. At this historical checkpoint,
Phase 03/04 production work had not been implemented; the current Phase 03A
implementation and its review status are recorded in the parent progress file.
Reviewer gate for the pacing and timeout-recovery changes is PASS / BLOCKING 0;
the complete live Discovery gate remains open.

## Earlier incomplete full traversal (superseded by the completed pass below)

The single authorized full pass used the canonical series seed and isolated
`resume_20261011_retry1` Catalog/Watchlist/output. It completed `/1`–`/5` with
matching main-frame HTTP 200 responses and buffered 150 distinct rows at
positions 1–150. The target remained at position 1 with exact row label
`無料`; observed `今なら無料` rows remained `unknown`. Navigation to `/6`
produced no response status, so the reviewed retry rule refused a retry because
there was no exact-attempt HTTP 200 proof. The pass ended after 48.242 seconds,
7 actual `goto` attempts, 6 range routes, and 0 retries; 0 episode records were
yielded. The isolated Catalog retained one pre-created Work and zero episode
items/sources/targets. No AccessGuard stop was reported for this pass, and no
further range request was made.

Metadata report: ignored
`output/younganimal_experiment/resume_20261011_retry1/phase02_full_discovery_retry_20261011.json`.
This is an incomplete traversal, not an accepted listing or a fix for the
unknown route delay. The later Phase 03A access stop is recorded in the parent
runbook progress and does not authorize another Discovery request.

Prior local gates: Reviewer VERIFIED the partial implementation/tests/docs with BLOCKING 0. Before pacing, targeted tests passed `28 passed`, and the independent Tester run over the two Younganimal files passed `27 passed, 0 skipped` with 23 existing warnings in 4.31s. After the pacing and bounded-retry changes, targeted Younganimal Unit/Integration plus CLI registry passed `42 passed, 0 skipped` with 140 existing asyncio deprecation warnings in 9.20s. `ruff check src tests` passed. Latest Root regression: the Hanayume six-file run initially had 198 passed, 3 failed, 0 skipped, with 90 existing warnings in 140.49s. The three timing-boundary failures (two adapter, one Discovery) passed when rerun alone: 3 passed, 0 skipped, 9 warnings in 7.91s; do not treat the full group as a clean pass. The generic CLI/registry/discovery/catalog/watchlist group passed 214/0 skips; the focused Younganimal registry test is included in that group.
Tester local artifact audit PASS: both read-only isolated Catalogs contained one pre-created Work row and zero other records; JSON sanitation passed. The Tester did not run live E2E. Historical and resumed access stops had no subsequent manual navigation or retry in those runs; in-flight automatic requests are not ruled out.


## Superseding full traversal (2026-10-11)

The later authorized Discovery pass completed all 31 numeric ranges
using a 3000 ms harness override: 32 document navigations (canonical root plus the 31
ranges), 925 unique episode identities at positions 1-925, and the target once
at position 1 with exact free status. The isolated Catalog contains one Work,
925 Items, Sources, and Targets, and zero Runs, Artifacts, or quota states. Its
labels classify 3 rows as free and 922 as unknown; the latter are not claimed to
be paid. The AccessGuard observed 8,701 events with HTTP 200, 204, and 304 only,
and no 403, 429, challenge, CAPTCHA, or timeout. Report:
`output/younganimal_experiment/discovery_3sec/report.json`.

The live run used a temporary module-level 3000 ms override. The production
pacing constant was changed to 3000 ms after that live pass. Its HTTP 429 cooldown/retry path was not exercised; any
separate retry must honor Retry-After and wait at least 60 seconds. The earlier
unexplained /6 timeout and distinct /9 HTTP 429 retain their original UNKNOWN
causes and are not evidence about this successful pass.

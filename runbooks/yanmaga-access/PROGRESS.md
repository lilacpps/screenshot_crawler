# Yanmaga access expansion progress

**Status:** Stage 01 PASS (observed Discovery subset); Stage 02 PASS (independent final review BLOCKING 0); Stage 03 PASS with qualified composite live evidence and independent BLOCKING 0; Stage 04 live runs, affected tests, and independent Tester audits PASS; final Reviewer gate PASS (independent BLOCKING 0). A6 existing-grant work-novel chapter 10 and A7 public-free work-dual chapter 51 completed through END/ZIP/Completed. Pre/post Discovery preserved Catalog state with zero Source/Viewer/rental POST. The affected scope passed 261 tests, 0 skipped, with 305 deselected. The full-suite run was controlled-stopped and is not a clean full-suite pass. No new rights are authorized. First-free budget is exhausted, and manual chapter-26 use is excluded from ticket/quota use.
**Plan authored:** 2026-11-15.
**Implementation branch:** `feat/yanmaga-access`, created from latest `origin/main` (`4407e975`).
**Stage 01 implementation commit:** `26cbae8`.
**Stage 03/04 implementation and verification commit:** `3585535`.
**Authority:** [README.md](README.md), `runbooks/yanmaga-free/README.md`, `AGENTS.md`.
**Workspace boundary:** live artifacts are isolated under `output/yanmaga_access_experiment/stage01/`, `stage02/`, and `stage03/`. No normal Catalog, Watchlist, library, or capture output was used. User-edited `crawler.yaml` and `watchlist.yaml` were preserved.

| Stage | Status | Gate |
| --- | --- | --- |
| 01 Site probe / Discovery | PASS (observed subset); independent BLOCKING 0 | Its original sample kept wait rows unknown; Stage 03 later verified the wait marker/charged state. Paid-only classification, recovery timing, and an absolute grant expiry remain unverified. |
| 02 First-free capture | PASS; independent final review BLOCKING 0 | C1 used one additional first-free attempt on position 31. C2 reused the same grant without a new right. V4 pre-capture full/incremental and plan passed independent Catalog audit. C3 stopped before Source entry under a QA budget guard. C4-C6 failed before complete capture. C7 saved 13 WebP pages and reached 14/14, then failed before END because the nonsemantic `#rental` card matched the broad modal gate. The site-local exemption preserves semantic-dialog, body-ownership, and positive-END checks. C8 completed the same existing-grant target with one Source GET and one Viewer GET, no other episode or non-GET request, and zero new first-free use. Run 8 succeeded with 14 pages and `stop_reason=end`; Item 27 completed and one Artifact was present. The 14-page ZIP and genuine Manifest match exactly and Root's artifact audit passed. Post-capture full Discovery completed with 57 known rows and `complete=true`; incremental returned `known_streak` with five known rows and `complete=null` (not evaluated), and its Source/Viewer request counts are unknown because its observer was not installed. The post-full plan had zero candidates because Item 27 was complete. The independent final review accepted Stage 02 with BLOCKING 0. No new right is authorized. |
| 03 Work ticket | PASS (qualified composite live evidence); focused checks and independent review BLOCKING 0 | Run 10's native POST was verified later from retained exact notice/Viewer/history evidence and applied once using a frozen observation anchor. Novel chapter 10 grant-only succeeded with one POST, `entry_confirmed`, zero pages, pending Item, and no Artifact. Cumulative ticket actions=2. Dual chapter 29 same-grant attempts 3/4 were incomplete; attempt 5 completed 14 pages with positive END, ZIP, and Completed without another POST. Root audited the genuine Manifest/ZIP; the grant and cooldown remained unchanged. Post-capture full/incremental Discovery preserved the target, Items, Sources, flags, grants, and artifacts; Source/Viewer/native rental POST=0. No further ticket action is authorized. |
| 04 E2E / final review | PASS (independent final Reviewer BLOCKING 0) | A6 completed work-novel Source 26 / chapter 10 with its existing grant: 18 WebP pages, positive END, ZIP, Completed, unchanged grant, and no new ticket POST. A7 completed public-free work-dual Source 3 / chapter 51: 16 WebP pages, positive END, ZIP, Completed, unchanged quota/grant state, and Source=1/Viewer=1/other=0/POST and non-GET=0. Pre/post full/incremental Discovery preserved state with zero Source/Viewer/rental POST. Tester independently passed both ZIP/Manifest/SQL and visual audits. Core/local-viewer passed 55 / 0 skip / 8 deselected; Batch/CLI/Catalog passed 61 / 0 skip / 297 deselected; Yanmaga site + five entry-only representatives passed 145 / 0 skip / 0 deselected (129 Yanmaga tests + 16 representative cases). Total affected scope: 261 passed, 0 skipped, 305 deselected. The final Reviewer gate passed with independent BLOCKING 0. The full suite did not complete; do not claim a full pass. No new first-free/ticket/paid rights were used. |

## Stage 04 current checkpoint (2026-11-16)

Stage 04 started after the Stage 03 qualified PASS and independent BLOCKING 0.
A6 completed the first bounded target, work-novel Source 26 / chapter 10, using
its existing grant. Run 2 succeeded with 18 WebP pages and positive END; Item
26 completed and Artifact 1 was present. The ZIP SHA-256 is
`4c2f204c4600b6c9b7360bcc0d4e8203705af7aa1df134bc46837e7dab34ebb1`
(18,706,580 bytes). Root's nine-check artifact audit passed. Source=1,
Viewer=1, other episodes=0, and POST/non-GET=0; the grant and work timestamp
were unchanged. Pre/post Discovery used no Source, Viewer, or native rental
POST. The next bounded target is work-dual Source 3 / chapter 51 using
public-free access. Target-only flags and dedicated Catalog/output remain
required. No new first-free or work-ticket action is authorized; Source 28
(the user-reported manual chapter-26 use) remains excluded.

A7 completed work-dual Source 3 / chapter 51 through the ordinary public-free
path. Run 14 succeeded with 16 native 1125x1600 WebP pages, positive END, Item
3 completed at `2026-11-16T10:21:36.821596+09:00`, and Artifact 3 present. The
ZIP SHA-256 is
`e731f5450a3410e65b8f2f0e4c744ff1b35b937171d2cc40ad6bf94736b24231`
(13,092,610 bytes); Root's nine-check audit passed. Source=1, Viewer=1, other
episodes=0, POST/non-GET=0; Source grant/quota fields and the work anchor were
unchanged. Pre/post full Discovery had 57 known rows and `complete=true`;
incremental had five known rows and stopped at `known_streak` with
`complete=null`. Both metadata refreshes had zero Source, Viewer, or native
rental POST. Selected source flags/IDs and Artifacts 1/2/3 remained unchanged;
normal and grant-only post-capture plans were empty.

### Final validation checkpoint

The accepted affected scope includes Core/local-viewer, Batch/CLI/Catalog/
resource behavior, all Yanmaga adapter browser tests, and five other entry-only
representatives. Core/local-viewer passed 55, skipped 0, deselected 8. The
Batch/Catalog affected run passed 61, skipped 0, deselected 297. The Yanmaga
site plus five entry-only representatives passed 145, skipped 0, deselected
0 (129 Yanmaga cases and 16 representative cases). Total affected scope:
261 passed, 0 skipped, 305 deselected. The independent Tester audit passed both
A6/A7 manifests, ZIPs, SQL state, and first/middle/final visual checks. Root reports
`ruff check src tests` and owned-path `git diff --check` passed.

The full-suite v2 did not complete. The earlier `a086` run stopped after 560
passes at a 120-second ComicFuz browser teardown timeout; an isolated rerun of
that node passed once with no skips. The later v2 run first had four QA
import-path collection errors, corrected in the ignored helper, then recorded
1,013 visible calls before a controlled stop after the agreed affected scope.
Evidence is `output/yanmaga_access_experiment/stage03/resume-suite-controlled-stop.json`.
This is not a clean full-suite pass and does not establish 9,180 passing tests.

## Stage 03 current checkpoint (2026-11-16)

Authenticated metadata-only Discovery verified the image-only
`span.mod-episode-free_browse` marker and exact logo asset: 22 `quota` rows in
the 57-row `work-dual` listing and 29 in the 37-row `work-novel` listing;
`work-dual` retains two unknown rows. The visible exact
`.episode-free-time.charged` / `チャージ完了` state was observed in the same
work. `data-is-free="true"` alone is not classification evidence.

Read-only Source pages for `work-dual` chapter 29 and `work-novel` chapter 10
showed the same active modal with exact work/episode identity, the label
`レンタル期間 / 3日間`, and one enabled `読む` submitter. The observed
same-origin POST is bound to the exact episode's
`/rental/episodes/<episode-id>/by_free_waits` path. Source GET itself did not
consume a ticket. The exact work-ticket success notice observed after the dual
chapter-29 submit was `レンタルが完了しました`; the distinct first-free notice remains
`無料レンタルが完了しました`. Run 10's production postcondition did not
latch or persist the use. Root later verified the exact notice, Viewer, and
active target history from retained evidence, then applied one frozen history
observation to Source 25 and work cooldown state. The observation at
`2026-11-16T00:23:46.090627Z` showed `残り2日`, with the lower bound
`2026-11-17T00:23:41.090627Z`; it is an observation anchor, not the exact POST
time. The applied record is `stage03/dual/late-confirmation-applied.json`; a
reapply is rejected and cannot move the bound.

Dual chapter 29 same-grant direct retry attempt 3 made Source=1, Viewer=1, and
native ticket POST=0. It saved 13 pages and failed before END. Attempt 4 saved
all 14 native WebP body pages and then failed to recognize a terminal boundary;
no Artifact was created and Source/Work grant state stayed unchanged. Attempt 5
then completed all 14 pages and positive END without a new ticket POST. Root
audited the genuine Manifest and ZIP; Source 25/Work grant and cooldown stayed
unchanged. Its ZIP SHA-256 is
`b1ffc5c22c175d22a1bc44af291ceeb141500d20a7a5a934e99c9b8d7afe5cff` (12,548,287
bytes); the genuine Manifest SHA-256 is
`16186b30fa07320821d3847e61299ba220c4277070804d2ba3b394fe60a46c3e`.
The saved
page identified the inline next-chapter point/rental metadata as the false gate
source. The gate now excludes only the observed point, possession,
necessary-point, and short-description nodes inside the unique `#rental` card;
semantic dialogs remain gates. A separate terminal branch accepts the observed
visible native wait countdown only when it matches the exact immediate next
wait-marked row and no next/read or signup CTA is present. Body ownership and
positive-END checks remain strict. The observed terminal countdown variant
matches the immediate next wait-marked listing row when no next/read or signup
CTA exists. Stage 03 capture is verified; no further ticket submit is
authorized.

Novel chapter 10 grant-only run succeeded with `stop_reason=entry_confirmed`,
zero pages, Item 26 pending, and no Artifact. It emitted one native wait-rental
POST; Source=3 and Viewer=2 are request totals with route types unrecorded. No
other rental POST or episode was observed. The updated automatic ticket proof
and Catalog persistence worked on this path. Its Source grant expiry is
`2026-11-17T09:35:11.467066+09:00`; quota start and work last-consumed time are
`2026-11-16T09:35:16.467066+09:00`. The report is
`stage03/novel/grant_only-report.json`. Cumulative Stage 03 ticket actions are
two: dual chapter 29 and novel chapter 10. No further ticket action is
authorized.

Wait/trusted-history parsing accepts the observed exact `残りH時間` or
`残りD日` field only when the explicit 72-hour bound permits it. For D>=2 the
lower bound is observation start plus (D-1) days minus 5 seconds, labeled
`site_day_countdown_lower_bound`; D=1 and H=1 establish active access but no
finite expiry. No fixed 72-hour grant is synthesized. Ordinary first-free
history remains capped at 23 hours and rejects day notation.

Focused synthetic verification: Rental History browser tests **37 passed**;
wait-ticket/rental-form adapter browser selection **18 passed / 106 deselected**;
first-free adapter regression selection **15 passed / 109 deselected**; adapter
and policy unit files **41 passed**. The first-free selection initially failed
six cases because a fixed November 15 grant fixture had expired against the
current clock; it now anchors to test execution and passes. Independent review
of the notice/day/late-record code passed BLOCKING 0. Five focused browser cases
cover the observed terminal countdown branch and the adapter Unit file passed
10 tests. Stage 03 post-capture full/incremental Discovery completed with
Source=0, Viewer=0, and native rental POST=0; Root's audit confirmed the target,
grant, cooldown, and artifacts were preserved. Stage 03 is accepted with
qualified composite evidence and independent BLOCKING 0. Stage 04 A6/A7 live
runs and independent Tester audits passed; final Yanmaga affected-test count
and the final Reviewer gate passed with independent BLOCKING 0. The full-suite run was
controlled-stopped and is not a full pass.

## Stage 01: site probe and Discovery

### Live evidence

- Connected to the existing shared Crawler Chrome through the standard CDP helper; Lead verified process/profile provenance. All site interaction used Playwright pages/locators in a newly created page. No Chrome launcher, profile change, login action, episode navigation, access CTA, or rights-consuming action was used.
- Evidence timestamps are 2026-11-15 JST, based on isolated evidence-file modification times: initial dual sample 09:41-09:44; wife-list continuation 09:46; wait-candidate scan 09:50; post-change verification 10:12-10:13.
- Stable sample IDs map to user-provided samples: `work-dual` is the dual-access sample (`/comics/%E5%8F%8C%E6%98%9F%E3%81%AE%E3%82%A2%E3%83%9D%E3%82%AF%E3%83%AA%E3%83%95%E3%82%A1`); `work-wife` is the wife/child-care sample (`/comics/%E5%A6%BB%E3%81%A8%E5%83%95%E3%81%AE%E5%B0%8F%E8%A6%8F%E6%A8%A1%E3%81%AA%E8%82%B2%E5%85%90`); `work-amateur` and `work-company-stars` are the two inspected wait candidates.
- Authenticated shared-profile `work-dual` returned HTTP 200. The post-change complete listing had 57 rows: 27 exact first-free rows, 8 red public-free rows, and 22 unknown. Snapshot state was authenticated, with no continuation left. Counts match the pre-implementation DOM audit. Before the change, the old adapter classified all 57 rows as unknown.
- Two first-free rows appeared in the initial viewport; 27 appeared in the complete 57-row listing. Positive UI evidence was five visible same-origin `/mypage` links, no visible sign-in/sign-out label, and the current top-level work document. `ep.is_logged_in=true` was consistent supporting evidence, not the authority. A temporary empty-context comparison had no `/mypage` link, two sign-in links, and `ep.is_logged_in=false`. No account/profile values were captured.
- A request-method-only counter during full traversal saw 25 POST requests. A separate short reload recorded 18 POSTs with sanitized host/path; all were third-party analytics endpoints (TikTok, Meta, and Google measurement). No first-party Yanmaga POST was seen in that endpoint sample. This is not a network-wide POST-zero claim. The synthetic browser fixture separately asserts no first-party non-GET or episode-route request and zero access-control button clicks.
- On `work-wife`, the initial listing had no wait marker. One authorized ordinary More click on a dedicated page issued only `GET /episodes?offset=5&sort=older`, without `limit`; it inserted 150 rows at positions 5-154. All 10 original IDs remained in their original relative order, but did not remain a prefix. This shape stays outside the strict pagination contract; no adapter broadening was made.
- On `work-amateur` and `work-company-stars`, the inspected first view had no wait marker. Their episode identities failed the adapter's strict row-URL check, so no records were emitted. These failures remain closed.
- No wait-free row, paid-only/coin-only row, active grant, safe grant expiry, or 23-hour recovery behavior was observed. Numeric point badges coexisted with free states and do not prove paid-only access. These states remain unknown and are not implemented.

### Evidence files

All files below are sanitized and isolated under `output/yanmaga_access_experiment/stage01/`:

- `probe-dual-sample.json` and `probe-visible-dom-summary.json`: initial complete-list and rendered DOM summaries.
- `auth-ui-compare.json`: shared-profile and temporary empty-context UI/telemetry comparison.
- `wife-list-single-continuation.json` and `wife-list-order-summary.json`: the one bounded ordinary list expansion and identity/order summary.
- `wait-sample-scan.json`: first-view observations for the two wait candidates.
- `post-implementation-live-counts.json` and `post-request-endpoints.json`: final classifier counts and sanitized POST endpoint hosts/paths.

### Implementation decisions

- Positive authenticated evidence is a visible exact same-origin `/mypage` UI link without credentials/query/fragment, no visible sign-in link, current work-document identity, and no observer overflow. Analytics true is supporting only; it may be absent, but any observed state must agree.
- First-free classification requires exactly one total free marker and one first-free marker, exact displayed badge text translated as `first-free`, exact class-token set `mod-episode-point--free` + `by_first_time`, authenticated page proof, and no wait/modal/red/conflicting free badge. Public red-free classification retains its exact marker proof and accepts verified anonymous or authenticated page identity.
- Confirmed first-free and public-free rows map to existing `access_mode=free`; no schema or new mode was added. Capture remains anonymous-only in Stage 01, so Discovery recognition does not authorize first-free Viewer entry.
- At this Stage 01 checkpoint, wait-free/paid/quota/grant selectors were unsupported; the later evidence-backed wait marker and `work_ticket` behavior are recorded under Stage 03 below. Missing `data-limit` continuation and invalid episode URL shapes continue to fail closed. No Stage 01 shared Core, Catalog, or Planner policy behavior changed.
- Yanmaga planning remains direct-only and uses Catalog order. `test_yanmaga_planner_keeps_only_free_direct_and_preserves_positions` confirms two free direct candidates retain Catalog insertion order while artifact prefixes preserve `display_position` (`013`, `002`); unknown/quota/paid/owned/unavailable rows are skipped. The shared `test_display_position_order_preserves_direct_quota_slots_and_quota_selection` confirms direct candidates stay before work-quota candidates and `display_position` reorders only within each pool. This is shared planner behavior, not evidence for a future Yanmaga quota policy.
- Every Yanmaga refresh sends `free_until=None` because no expiry was observed; the existing Catalog contract clears stale free expiry. Yanmaga does not observe grants, so `access_granted_until_observed=False` preserves an existing grant. An explicitly observed null remains authoritative and clears it. Lead separately ran both Catalog grant-preservation regression cases; Stage 01 had no live grant evidence.

### Tests and checks

Pre-change baseline run by Lead: `test_yanmaga_policy.py` 24 passed; Discovery and adapter unit tests 27 passed; Discovery browser integration 21 passed; total 72 passed / 0 skipped.

Post-change Stage 01 runs:

- `tests/unit/test_yanmaga_discovery.py`: 29 passed / 0 skipped.
- `tests/integration/test_yanmaga_discovery_browser.py`: 24 passed / 0 skipped; after adding the strict first-party request spy, the focused authenticated/non-consumption case passed 1 / 0 skipped.
- `tests/unit/test_yanmaga_policy.py`: 24 passed / 0 skipped.
- Independent Reviewer reran `tests/unit/test_yanmaga_discovery.py` (29 passed) and two browser-backed Discovery cases (2 passed); 0 skipped, then reported BLOCKING 0.
- `tests/unit/test_batch.py::test_display_position_order_preserves_direct_quota_slots_and_quota_selection`: 1 passed / 0 skipped.
- Lead separately verified existing Catalog grant-preservation contracts: 2 passed / 0 skipped. This verifies the existing shared contract only; Stage 01 did not observe a live grant.
- An initial unit run found one misplaced multi-marker case in the public-free classifier table; it was moved to the first-free classifier table. The focused node then passed 7 cases and the full Discovery unit file passed. No implementation failure remained.
- Pytest reported existing pytest-asyncio / Python 3.14 deprecation warnings. No test was skipped.
- Full `ruff check src tests` passed after import sorting (Lead verification). Independent Reviewer verified the owned-file diff and reported BLOCKING 0. `git diff --check` was clean for owned files; the unrelated user-edited `watchlist.yaml` contains trailing whitespace and was not changed to avoid overwriting user work.

Capture/native/END tests were not rerun because Stage 01 did not change the capture adapter, native capture, END, packaging, or executor path; Lead supplied the existing baseline. Full `pytest -q` was not run for this site-local Discovery change.

### Modified implementation and documentation

- `src/screenshot_crawler/site_adapters/yanmaga/discovery.py`
- `src/screenshot_crawler/site_adapters/yanmaga/__init__.py`
- `tests/unit/test_yanmaga_discovery.py`
- `tests/integration/test_yanmaga_discovery_browser.py`
- `src/screenshot_crawler/site_adapters/yanmaga/README.md`
- `note/14_yanmaga.md`
- `runbooks/yanmaga-access/PROGRESS.md`

No cookies, auth state, personal account data, or full analytics request URLs were recorded.

### Stage 01 gate

**PASS (observed Discovery subset); independent BLOCKING 0.** At the Stage 01 checkpoint, wait-free/quota behavior was still unknown and disabled. Later Stage 03 evidence and implementation are recorded in the current checkpoint above; this historical observation is not the current classifier status. Unknown behavior remains fail-closed.

## Stage 02: first-free capture

### Target and action budget (recorded before any potential release)

At 2026-11-15 11:07 JST, the Lead-approved single target is `work-dual`,
full-list position 32, anonymized as `episode-ff-probe-01`. Its canonical
source path shape is `/comics/<work-dual-slug>/<episode-ff-probe-01>`.
The exact episode ID is retained only in ignored Stage 02 evidence, including
`single-entry-readonly-state.json` and `sort-ui-readonly.json`.
The total live first-free-use budget is one episode and at most one effective
release. The Lead approved one same-Page navigation via the freshly verified normal
episode anchor; it may itself release the episode. After this one transition,
stop for the next Lead checkpoint.
No access CTA may be clicked during that probe. If navigation does not establish
Viewer access and exposes a separate free CTA, stop for another Lead checkpoint.
No retry, second release, other episode, ticket, point, coin, paid, purchase, or
alternate resource action is permitted. The one authorized anchor click has since
completed; the site showed its free-rental completion notice. The observed use is
recorded as one first-free release, with zero separate access-CTA clicks.

### Read-only live preflight

A fresh guarded listing load on 2026-11-15 JST returned HTTP 200 and a complete
57-row Discovery snapshot. During this read-only preflight, no episode route was requested. The current page had positive authenticated UI
(`5` visible `/mypage` links, `0` sign-in, `0` sign-out). The selected target was
one exact first-free row at position 32, with one same-origin anchor to its
canonical episode path, no row button/role-button, and no inline click handler.
Its marker was the exact first-free state; there was no public red-free marker.
No episode route was requested, no access control UI was clicked, and no
first-party non-GET request occurred. The visible numeric point badge is not
permission to use points and remains outside this probe.

One bounded same-document script inspection read two normal-loaded first-party
assets, `1,045,629` bytes total (`application-d08a19d8.js` and
`for_customer_comics_contents-89f33b50.js`), within a six-asset / 4 MiB cap.
It found only generic `expiry`, `point`, `modal`, and `registration` terms in
the general application asset. It found no first-free label/class, first-free
state, grant-until/free-until field, or viewer route identifier; the second
asset and inline scripts had no matching terms. This does not prove the code
has no such logic. No raw bundle, token, personal value, or full URL query was
saved. A modal/confirmation path and finite grant expiry remain unobserved.

The Lead separately checked the official Help article for Wait-and-Free: it
describes a 23-hour ticket charge and availability for displayed Works/episodes,
not the first-free grant lifetime. The official renewal page returned HTTP 403
when opened; its search-index text is only an unverified lead about a first-free
Viewer control and was not used as implementation evidence. No 23-hour or
24-hour expiry is inferred for first-free access.


### Single first-free entry probe (2026-11-15 11:08 JST)

The final same-Page pre-click check passed the exact work/canonical/og URL,
authenticated UI, target row and episode anchor, first-free label/class/count,
no wait/modal/conflicting free badge, and no row button or inline handler. One
normal target anchor click was made; there were no retries or additional clicks.
The exact public episode route returned HTTP 302 and redirected to the matching
`/viewer/comics/.../<episode-id>` route with HTTP 200. The viewer parser matched
the target ID, the opaque `cid` query was present but not recorded, and the
read-only snapshot showed page `1/14`, visible body page 1, and no access gate or
rental/signup overlay. The native capture observer was installed before the
work-page navigation. A first-party visible notice said 'Free rental completed'
(the exact Japanese text is in the isolated JSON); this is positive evidence of
one first-free use, not evidence of its expiry. No deadline/expiry was observed.
There was no first-party non-GET request. This is not a claim that all
third-party/network POSTs were zero.

The Lead accepted the explicit site notice and matching accessible Viewer as
one first-free use. The one-use budget is exhausted; no additional free, ticket,
point, coin, or paid action is authorized. The one entry probe did not rewind,
capture, package, complete an Item, write a Catalog, or use another resource.
Its Page and AccessGuard were held only for the Lead-approved bounded read-only checkpoint, then the owning process received `CLEANUP`; its owned Page and Guard closed and `BrowserSession` disconnected. No shared Chrome close occurred. The separate listing Page was also closed. Further navigation or CTA clicks remain stopped. The isolated probe JSON records the action count and UI evidence. The final
entry record stores `rights_used=1`, based on the first-party completion notice
and accessible same-episode body. No second use occurred.

### Post-entry read-only probes

#### Planned D countdown confirmation (2026-11-15 11:56 JST)

Before execution, the sole remaining metadata probe is bounded to the existing
exact target `work-dual` / episode `episode-ff-probe-01`:
open one new owned metadata Page, observe the visible `/mypage` rental-history
link, then issue one same-origin `fetch` GET to that exact observed href with
`cache=no-store`, `redirect=error`, and `credentials=same-origin`. The detached
DOM inspection is limited to the exact target card and its rental-period label
and remaining-hours text. It will save only safe response headers and whether
the UI countdown matches. Maximum: two document GET navigations (mypage and its
observed history link), one same-origin GET fetch, zero episode/Viewer entry,
zero CTA clicks, zero non-GET requests, zero additional rights use. If the
response, target binding, or countdown is ambiguous, expiry remains unknown.

The first execution completed the two document GETs and one no-store GET, but
its detached-card parser searched ancestors and had an ASI bug in a callback
return. Its countdown_unconfirmed result is invalid parser evidence and did
not establish a site mismatch. A temporary exact-target-anchor aggregate-text
parser was exercised on local synthetic target/decoy cases before the final
probe. Formal review found it could still conflate title text with the native
rental label/value fields; the helper and test were removed from production
sources. The successful GET remains direct evidence, but no reusable expiry
parser or runtime Grant behavior is implemented. One corrected metadata-only no-store GET is
planned at 2026-11-15 12:05 JST, with the same target and zero additional rights.
The UI portion returned one visible exact target anchor with one rental-period
label and H=23. The probe then stopped before fetch because the injected parser
function was missing parentheses; fetch_count=0, so no additional no-store
GET occurred. This is another probe implementation error, not site evidence.
The expression was corrected and the same synthetic target/decoy cases passed
again. The approved no-store request is still pending a Lead checkpoint; no
further site operation has been made. Lead has now authorized one final
no-store GET on the same exact target at 2026-11-15 12:10 JST, using the tested
helper. The maximum remains one GET; if the UI/fetch match is absent or
ambiguous, expiry stays unknown and the probe stops.

The authorized fresh full work-list read on a separate owned Page failed closed
with `DiscoveryIncompleteError: Yanmaga continuation semantics are unsupported`.
It obtained no post-entry row status or expiry. This is an unsupported listing
shape, not an HTTP/challenge stop; the attempt made no episode navigation or CTA
click and its isolated probe records `rights_used=0`. No Catalog was written and
the full read was not retried. The existing strict continuation contract remains
unchanged pending a Lead-defined bounded More-control probe.

A read-only inspection of the single already-loaded exact Viewer found no
robustly visible finite expiry text or expiry-related data attribute. The
observed `rentalPopup` global was undefined; `loadingRentalModalPopup` and
`showRentalModalPopup` were functions, not expiry values. A weak visibility scan
found `#popup-refresh-page-header` with expired-period wording, but an earlier
scan using display, visibility, opacity, and nonzero geometry checks did not
find it visible. It is therefore recorded as a hidden/unverified UI node, not a
granted-access expiry. No API or resource was requested to resolve it. The
Viewer request log had already recorded `/assets/viewer_embed-e72628cb.js`, but
its body was not retrieved; the corrected metadata probe exposed no script body
or finite-expiry field. The grant expiry remains unknown.

Two additional Lead-approved, non-consuming probes were then run with fresh
owned Pages. The first queried the exact work-dual listing and confirmed HTTP
200, positive authenticated UI, and the same canonical work. Before expansion it
had 10 rows and one visible native More button. The button had the observed More label,
same-work `/episodes` `data-path`, `data-limit=47`, `data-offset=5`, no
sort field, and no href or inline handler. One click, bounded by an AccessGuard
and a route guard that aborted non-GET and episode/Viewer/account paths, produced
one first-party `GET /comics/<same-work>/episodes?offset=5&limit=47` with HTTP
200. No episode route, CTA, blocked request, or right use occurred. The rows
expanded from 10 to 57: all 10 previous IDs remained, no duplicates appeared,
and 47 new IDs were inserted after the initial first five and before the prior
last five. The target ID occurred once at post-entry position 26; its
`.mod-episode-point--free` marker was absent, and only the `data-is-free`
attribute name was recorded. This observed position differs from pre-entry
position 32 and is recorded as a live state/time difference. It does not prove a
finite grant expiry or modify the production parser's strict ordering contract.

The second probe issued one same-origin GET to the already-observed static
`/assets/viewer_embed-e72628cb.js`: HTTP 200, `application/javascript`,
115,764 bytes. It saved only bounded names/counts, not source or snippets. No
first-free/free-rental/deadline text, relevant selector, or expiry/deadline key
was found. A coarse substring scan produced generic false positives such as
`parent`, `different`, and `last_accessed_at`; none is an access-grant field.
This asset supplied no finite expiry evidence. Both probes used AccessGuard,
recorded zero rights use, and closed only their owned Pages.

The first metadata script attempt had a JavaScript syntax error caused by raw
Japanese text passed through PowerShell; it made no navigation or access action.
The corrected probe source was saved as ASCII, checked, and compiled before
execution. It performed no navigation or CTA click, and the owning Viewer
Page/Guard were then closed at the bounded hold deadline through the original
BrowserSession cleanup.

Evidence added under `output/yanmaga_access_experiment/stage02/`:
`post-entry-work-listing.json`, `post-entry-viewer-expiry-readonly.json`,
`post-entry-viewer-expiry-corrected.json`, `viewer_metadata_corrected.py`,
`post-entry-more-control.json`, `more_probe.py`,
`viewer-asset-readonly-findings.json`, and `viewer_asset_probe.py`. Those
earlier read-only probes made no production change; the subsequent C sub-gate
change and tests are documented below. Immediate
grant persistence, expiry, rediscovery recovery, capture/END/ZIP, and Completed
remain unverified; Stage 02 is still IN PROGRESS and cannot pass its gate.

### Probe execution notes and evidence

The first listing attempt used a Japanese literal through PowerShell stdin,
which was converted to question marks and led to a not-found path containing
`%3F`. This was an implementer encoding error, not a site failure or challenge.
The malformed Page was the one created by that probe and was closed through
`BrowserSession.close_page`; no episode route or rights action occurred. The
correct retry used the ASCII percent-encoded canonical work path and succeeded.

One raw `Browser.close()` call was inadvertently made during an initial CDP
connectivity check. A later `/json/version` HTTP 200 did not prove which Chrome
instance it represented. Lead's independent CIM check found the current shared
Crawler Chrome PID `33724`, with the expected `.chrome-crawler` profile and
creation time 2026-11-15 10:13:21 JST, before that call. No causal link between
that earlier PID change and the raw close is established. Subsequent probe
sessions used `BrowserSession.connect`, owned Pages, `close_page`, and
`session.close`; the pre-existing `about:blank` Page was left untouched.

Isolated Stage 02 evidence is under `output/yanmaga_access_experiment/stage02/`:
`read-only-listing-preflight.json`, `first-party-script-readonly-summary.json`,
`malformed-work-url-probe.json`, `single-entry-readonly-state.json`,
`sort-ui-readonly.json`, and `rental-history-fetch-confirmation-verified.json`.
One exact episode navigation has occurred, with one first-free use assessed
from the site completion notice; no separate CTA was clicked. Subsequent
read-only probes below were separately bounded and Lead-approved. Stage 02
now has a site-local Discovery sort correction and focused tests; its C
sub-gate was accepted by the independent Reviewer with BLOCKING 0. The
the production countdown helper has since been exercised by the separately
approved metadata-only probe recorded below. First-free runtime persistence,
retry with and without rediscovery, complete capture/END/ZIP, and capture-path
Completed behavior remain unverified on the live production path.

### Stage 02 C sort correction and D countdown observation

The post-entry normal work page for work-dual was default newest-first. A fresh
read-only probe observed two visible same-work sort links; the exact
oldest-first label opened the same work with the sole sort=older query and
became active. One native More click used the observed offset 5, limit 47, and
sort older; its same-work GET returned 200. The 57 resulting IDs exactly
matched the pre-entry oldest-first sequence, with the selected episode at
position 32. Rights use, episode navigation, Viewer navigation, CTA clicks,
and non-GET requests were all zero in these sort probes.

The initial C implementation required base canonical and og:url. The later
production diagnostic found both identity URLs on the exact same-work sort=older
shape after the observed oldest-first navigation. The current implementation
accepts either a matching base pair or that matching sorted pair only when the
same document observation also proves the exact older URL and active oldest UI.
It performs existing strict expansion and ordering on the oldest-first
document. It rejects duplicate,
hidden, foreign, unknown-query, label-conflicting, and active-state-conflicting
sort controls. Canonical input work URLs and public episode Source targets remain
queryless. Legacy fixtures with no sort UI keep their
existing oldest-first pagination contract. C implementation/tests are complete
and accepted with independent BLOCKING 0. The canonical/og follow-up below is
accepted with independent BLOCKING 0. At that C-review checkpoint no Stage 02
live capture had been run; the later C1 result is recorded below.

The earlier Rental History UI read showed H=23. The latest read-only
exact-target Rental History document showed one target anchor/card and one
visible rental-period label with H=22. One
same-origin no-store GET to the exact observed history href returned 200
text/html, 33,971 bytes, and the detached target-A summary matched H=22. The
safe headers included Date 2026-11-15 03:10:51 GMT, no Age, and
Cache-Control max-age=0, private, must-revalidate. At aware UTC fetch start
2026-11-15 03:10:49.892907 UTC (12:10:49.892907 JST), the then-current
diagnostic recorded 2026-11-16 00:10:49.892907 UTC (GET start plus 21 hours)
as its countdown-derived result. This was not an absolute site expiry. The
current runtime rule subtracts an additional 5 seconds: its
site_countdown_lower_bound for H=22 is 2026-11-16 00:10:44.892907 UTC
(09:10:44.892907 JST), computed as GET start plus (H - 1) hours minus 5
seconds. This is also a lower bound, not an absolute expiry. The probe recorded
one fetch, two document GETs, zero rights use, zero episode/Viewer routes, zero
CTA clicks, zero non-GETs, and no AccessGuard stop. At that checkpoint, before
later Lead-authorized metadata-only probes, no further site operation had been
authorized. Those later probes are recorded below and also used zero rights and
made zero Source/Viewer requests.

The earlier aggregate-text countdown helper and test were withdrawn after
Review noted that they did not prove native exact label/value leaf nodes and
same-card binding. A later native-structure helper is now present in the Stage
02 working tree, but the latest complete-listing probe stopped before calling
it. Its compatibility through the production Discovery path and its use before
capture have not passed the Stage 02 gate. The earlier DOM relation was not
recorded in the original probe.

The first full browser invocation could not create pytest temporary directories
under the Windows global temp root (30 setup errors, 2 tests passed). An
isolated-browser rerun then passed 32 tests before review fixes. After removing
the temporary parser test and adding zero-click oldest-active, sort href-drift,
and post-More active-state cases, the final combined run passed 30 Discovery
unit tests and 36 Yanmaga Discovery browser tests: 66 passed, 0 skipped in
46.85 seconds. The independent Reviewer reran the Unit file (30 passed) plus
6 focused browser cases: 36 passed, 0 skipped, then reported BLOCKING 0. The
full browser file used a dedicated Stage 02 basetemp.
Full ruff check src tests passed, and git diff --check was clean for owned
files. Full pytest and capture/END/ZIP integration were not run because no
capture path changed.

Isolated evidence for this checkpoint is in
output/yanmaga_access_experiment/stage02/, including sort-ui-readonly.json,
rental-history-goto.json, rental-history-fetch-confirmation.json,
rental-history-fetch-confirmation-verified.json, and the ASCII-only
rental_history_fetch_confirmation.py. The first no-store parser attempt had
an implementation bug and its countdown_unconfirmed result is invalid; the
next attempt stopped before fetch due a JavaScript composition error. The
successful read-only GET used a temporary target-A diagnostic parser. That
aggregate-text helper/test was removed after Review because it lacked exact
native label/value leaf-node and same-card structure proof.


### Stage 02 C canonical/og identity follow-up

A bounded read-only production Discovery diagnostic reached the authenticated
oldest-sort document and failed before expansion with allowlisted reason
`redirected_to_different_work_or_route`; the cause type was absent. The work
GET and exact sort GET each returned HTTP 200. At failure, the same-page scalar
snapshot showed canonical and og:url both had the exact same-work `?sort=older`
shape, the document was on that exact sort path, and the older control was
active. It also showed one same-work More control (`offset=5`, `limit=47`,
`sort=older`), 10 visible rows, one visible MyPage link, no visible sign-in
link, and one valid `ep.is_logged_in=true` telemetry event. The More control was
not clicked (instrumented click attempts 0); More XHRs and metadata helper calls
were 0. Source/Viewer attempts and first-party non-GET requests were 0. Thirty
foreign non-GET requests were aborted. Additional rights used: 0. Guard had not
stopped at the diagnostic checkpoint. All outputs omit request URLs and raw
query values.

This is the observed reason the initial C code rejected the page: it required
base canonical/og URLs even though the sorted page served the exact older-sort
identity pair. The site-local correction retains queryless public input and
Source URL parsing, allows either an exact base identity pair or an exact older
pair tied to the same sorted document plus unique active older UI, and rejects
mixed/unknown/duplicate identity forms. Unit tests passed 31; the Yanmaga
Discovery browser file passed 48 with 0 skips. Existing pytest-asyncio
deprecation warnings only. The independent C review reported BLOCKING 0 and the
Lead accepted that sub-gate. Stage 02 capture and Catalog grant persistence
remain unverified.

Evidence: ignored `output/yanmaga_access_experiment/stage02/discovery-failure-diagnostic.json`
plus the corrected earlier `production-helper-complete-listing-probe.json`.
At that checkpoint, no follow-up live requests were yet authorized before the C review gate.

### Stage 02 More request query observation

After the C review gate, a separately Lead-approved metadata-only probe used the
already opened `episode-ff-probe-01` target. This probe used 0 rights; the
previously confirmed first-free use remains a separate cumulative count of 1.
It made one base work GET, one oldest-sort GET, and one native More click. It
observed one exact same-work `/episodes` GET/XHR attempt. The query had the
bounded key set `cb`, `limit`, `offset`, and `sort`; there were no duplicate
keys or parse errors, and the three paging values matched the visible native
More control. The opaque `cb` value was not saved. No `_` key was present.

The diagnostic field `more_xhr_get_count=0` is the count accepted under the
then-current strict three-key pagination contract; it does not mean there were
no `/episodes` path attempts. The new observer recorded path attempts 1,
allowed 0, aborted 1. The probe route filter rejected the extra `cb` key before
continuation was accepted. Because the request was intercepted locally, this
does not establish what the site handler would have done with it. The listing
did not change (`continuation_did_not_change_listing`); MyPage/history helper
calls were 0, Source/Viewer attempts were 0, and the AccessGuard did not stop.
The probe output contains no URL or raw query values.

The next probe-only guard revision recognizes either the legacy three paging
keys or this exact four-key shape when `cb` is a single nonempty value of at
most 1024 decoded characters without control characters and all three paging
values match the native control. It forwards the observed `cb` value unchanged
and does not generate or record it. Unknown keys, duplicates, `_`, other
resources, and Source or Viewer routes remain denied. This does not claim that
`cb` is a cache-buster. The revision has only passed local checks so far: 70
existing route cases, 10 `cb` classifier cases, 21 observer cases, Python
compile, and ASCII-only validation. The independent Reviewer reported BLOCKING
0 for this probe-only guard revision; the site adapter/helper SHAs remained
unchanged.

The Lead then approved one metadata-only probe for the same already opened
target. It completed the 57-row listing, with the target present once at
position 32 and authenticated UI true. The visible More control produced one
GET/XHR request with the exact observed key set; the native offset, limit, and
sort values all matched. The `cb` value was single, nonempty, 13 characters,
decimal-shaped, and free of control characters. Its value was not recorded and
its meaning remains unknown. The More response was HTTP 200 JavaScript. This
establishes successful bounded listing expansion under the approved query
shape, not anything about `cb` semantics.

The metadata helper ran once. MyPage metadata GET returned HTTP 200 HTML with
`Cache-Control: max-age=0, private, must-revalidate` and no Age header, but no
history metadata GET was recorded and the helper returned zero proofs. One
`unexpected_first_party_fetch` was aborted; its path and query keys were not
recorded, so its role is unknown and cannot be identified as the history
request. The result is `metadata_unknown`: no H, expiry evidence, or finite
grant bound was observed in this run. The guard did not stop and there were no
page errors.
The work, sort, More, and MyPage responses all returned HTTP 200 and had no
Age header. Each had
`Cache-Control: max-age=0, private, must-revalidate`.
There were two observed recommendation GETs and 44 known analytics POSTs
allowed by the bounded route guard. Source/Viewer attempts and first-party
non-GET requests were 0. This probe used 0 rights; the prior confirmed
first-free use remains a separate cumulative count of 1. No capture, new
entry, or retry was performed. Stage 02 remains unverified.

Evidence: `output/yanmaga_access_experiment/stage02/production-helper-compat-native-traffic-v3.json`.

An offline code review then found that the probe guard, not the production
helper, hardcoded the MyPage history tab value as `rental`. The native link's
tab value had not been retained in prior evidence, and the v3 summary has one
`unexpected_first_party_fetch` abort whose path/query were not recorded. It is
not established that this abort was the history request. A new diagnostic-only
harness version removes the enum assumption: it allows a single nonempty,
bounded, control-free `tab` value only on same-origin `/mypage` GET/fetch, while
still rejecting duplicates, other keys, wrong resource type, auth and other
work. It logs only safe query shape and request outcomes, never the value.

The probe-only harness now has a `--metadata-only` mode. It uses one fresh base
work GET, reads current URL/canonical/og/auth/MyPage evidence in one DOM
observation, then calls the frozen helper at most once for the prior exact
target proof. It does not require that target to appear in the initial ten
rows. The route budget is base GET 1, MyPage GET 1, history GET 1, at most three
main metadata GETs total, sort and More 0, recommendations 1, and known
analytics POSTs 100. Source/Viewer, auth, other-work, and first-party non-GET
requests remain denied. Only safe MyPage query shape and request outcome are
recorded. Local checks pass: 70 route cases, 10 `cb` classifier cases, 21 More
observer cases, 13 MyPage history classifier/observer cases, and 14
metadata-only budget cases. A base-response gate also requires HTTP 200 before
the helper can run; its 12 local cases include a status-500 caller path with
zero helper calls. Python compile and ASCII-only validation pass. Harness
SHA256 is `701aa60791b86e9ca12dc574a525b7470e7165429f3994963512863f035bf6ab`;
production/helper SHAs remain unchanged. This latest harness version has not
been independently reviewed or run live.

This was the planned check at the earlier harness-review checkpoint. A later
Lead-approved execution and its result are recorded in the latest Stage 02
status section below.

## Stages 03-04

Not started. Record the Lead-approved scope, live evidence, tests, independent review, and gate outcome here before advancing each stage. Do not infer missing site behavior to satisfy a stage.

### Latest Stage 02 implementation and verification status (2026-11-15)

The C canonical/og identity correction is accepted with independent BLOCKING 0.
The pre-entry check now uses the same C-approved identity validator: it accepts
a sorted document with the observed oldest-first UI and either matching sorted
or base canonical/og pair, as well as a base document with the positive
oldest-first UI and matching base identity pair. Mixed, unknown, duplicate,
foreign, or unsupported forms remain rejected.

The fixed production helper and Discovery sources were verified by SHA before
the Lead-approved metadata-only probe. The probe used the already released
`episode-ff-probe-01`, made one base work GET, one MyPage GET, and one observed
Rental History GET (three metadata document GETs total), plus one known same-work
recommendation GET. It made zero Source/Viewer requests, zero first-party
non-GET requests, and used zero rights; the cumulative first-free use remains
one. It reported `metadata_verified_finite`, native H=17, and
`observed_at_utc=2026-11-15T08:11:29.019643Z`. The derived
`site_countdown_lower_bound` is `2026-11-16T00:11:24.019643Z`, using GET start
plus (H - 1) hours minus 5 seconds. This is a conservative lower bound, not an
absolute site expiry. MyPage and History responses were HTTP 200 HTML; both had
`Cache-Control: max-age=0, private, must-revalidate` and no Age header. The
probe allowed one recommendation GET and 21 known analytics POSTs; no raw URL,
query value, HTML, or account data was recorded. Evidence:
`output/yanmaga_access_experiment/stage02/production-helper-metadata-only-v1.json`.

### Metadata-only candidate preparation and audit correction (2026-11-15)

A later Lead-approved metadata-only check prepared a separate candidate without
opening a Source or Viewer and without using rights. A fresh canonical full and
incremental snapshot each contained 57 rows; `work-dual` had one authenticated,
exact first-free row at full-list position 31, aliased here as
`episode-ff-capture-01`. It is distinct from the already-used position-32
`episode-ff-probe-01`. In a new isolated Catalog, this run recorded 1 Work,
57 Items, 57 Sources, and 57 SourceTargets; the selected target IDs were Work 1 /
Item 27 / Source 27 / Target 27. It reapplied the acquisition flag to exactly
one Source and produced a one-candidate direct plan. Rights used: 0.
No capture or Source navigation was performed. Exact episode identifiers and
URLs remain only in ignored evidence.

The unchanged report
`output/yanmaga_access_experiment/stage02/metadata-only-v2/metadata-firstfree-work-dual-report.json`
has SHA-256 `65497681fb71324a3c7c1557e1cf5143e4ccdf8dd702164f0d42e90e35aeb94d`;
its companion Catalog audit has SHA-256
`a5ef54089913fa829fe86fa698ae2d9e5e7507b406cf77dda3e870caae1fb7d3`. The
The numeric zero values for `source_viewer_attempt_count` and
`first_party_non_get_attempt_count` were computed from the measured full and
incremental request-monitor guard counters, which recorded zero Source/Viewer
and zero first-party non-GET activity. Only the `*_observed` flags remain
false because the success branch omitted their updates. Those monitor runs
recorded primary GET count 3 and recommendations-GET count 2
each, with no fatal route, consistent with the classifier's all-resource-type
Source/Viewer denial and first-party non-GET denial. The original report
and audit were not edited, and no site rerun was made for this correction.
The production source hashes used for C1 and still held fixed for C2 are
adapter SHA-256
`6B26B256809D5CE177E07D154B6625D48F467C88AF90AFDD7CE100B6AE90353F`, Discovery
SHA-256 `E560CC4084B87716438BDBEA3D16480CA7CE6A206692FFE1159CA786375361AA`, and
rental-history helper SHA-256
`85717DE55E8DCF4873D03E742A465CB1F9966B32640C0DDB2B1402F09C8097E8`. The
failure-injection harness `769` and external QA manifest monitor remain fixed.

### Stage 02 C1 result and C2/final-capture contract

The exact candidate was `work-dual` / `episode-ff-capture-01`, one-based
full-list position 31. The isolated metadata report is authoritative for its
canonical URL and identity; the exact episode ID remains only in ignored
artifacts. The target identifiers in the dedicated Catalog were Work 1 / Item
27 / Source 27 / Target 27; they are identifiers, not Catalog row totals. It is
distinct from the previously used position-32
`episode-ff-probe-01`.

Tester ran C1 as the sole shared-browser operator; this documentation update
made no source change and performed no CDP operation. C1 completed with all
recorded checks passing. This additional first-free attempt used exactly one
Source GET and one Viewer GET, attempted no other episode, made zero first-party
non-GET requests, and invoked the capture hook once. The grant was saved before
pixel-readiness work. After readiness/rewind, the hook raised the intentional QA
`RuntimeError` before the first content page was saved.
Root's independent Catalog audit confirmed the exact Work 1 / Item 27 / Source 27
/ Target 27 identity, `access_mode=free`, and a future-aware stored grant, an
Item still pending, one failed CrawlRun with
`page_count=null` and the injected error marker, zero Artifacts, null
`quota_started_at`, and zero Work resource state. No page file or Manifest page
was created. The report was created at
`2026-11-15T12:12:32.491816+00:00`; that is the report timestamp, not an exact
site release or DB commit time. The stored Catalog bound
`2026-11-16T19:12:23.851271+09:00` comes from the verified native countdown's
conservative lower bound. It is not an observed absolute site expiry and does
not assume a fixed 24-hour lifetime.

Evidence is preserved without raw episode IDs in this note:
`output/yanmaga_access_experiment/stage02/live-c1-failure-report.json` (SHA-256
`7742a32ac4e6b5c2ea22999185332cc87a02b50745ff8ee7a2be66bcf30117f4`) and
`output/yanmaga_access_experiment/stage02/root-c1-catalog-audit.json` (SHA-256
`7ed0d238937cdf6e1b18139c7d0df16fd1ee1f7b4ddf4608017894d3864931f7`). The prior
Research release on position 32 plus C1 on position 31 make two confirmed
first-free uses in total. The additional first-free allowance is now exhausted;
ticket, point, coin, and paid actions remain zero.

Root independently confirmed the C1 persisted grant and authorized one C2
retry without rerunning the external Catalog DiscoveryService. C2 completed
with all checks passing on the same exact Source and future saved grant. The
Adapter did perform its fresh internal listing preflight. It used one Source
GET and one Viewer GET, then an intentional `capture_page` failure after
readiness/rewind but before the first content page was saved, zero new first-free
rights,
zero other-episode attempts, zero first-party non-GET requests, and zero request
observer errors. The Item remains pending; the two exact CrawlRuns are failed
with the injected error and `page_count=null`; there are no Artifacts or Work
resource records, and `quota_started_at` remains null. The saved future-aware
Catalog grant is unchanged at
`2026-11-16T19:12:23.851271+09:00`, the same conservative native-countdown lower
bound recorded after C1. C2 report:
`output/yanmaga_access_experiment/stage02/live-c2-no-rediscovery-report.json`
(SHA-256 `1bc4cb6b3159c277d5b1449374788699006e8915113699d6757408abb4a5b0bd`).
Independent Catalog audit:
`output/yanmaga_access_experiment/stage02/root-c2-catalog-audit.json` (SHA-256
`59c57136b19dcf0deb4958f09f32f8cb9b1a3c9e050458e5827ec3a578afed53`). Across
C1 and C2, the dedicated Catalog totals were 1 Work, 57 Items, 57 Sources, 57
SourceTargets, 2 CrawlRuns, 0 Artifacts, and 0 Work-resource rows. The selected
target identity remained Work 1 / Item 27 / Source 27 / Target 27. These reports
use only the `episode-ff-capture-01` alias.

### Post-C2 metadata QA refresh (2026-11-15)

A metadata-only v3 refresh then ran one full normal CLI Discovery for this
candidate (incremental was not run). It made one work GET, one sort GET, one
More request, three primary metadata GETs, two recommendation GETs, one MyPage
GET, and one Rental History GET; Source/Viewer and first-party non-GET were 0,
fatal routes were 0, and the existing future grant, pending Item, and
zero Artifact/quota state were retained; the acquisition flag was restored to
target-only scope. QA
stopped because its derived `discovery_complete=false` was produced by an
unconditional exception overwrite. The raw result was not saved, so the
underlying result mode, error type/message presence, counts, snapshot, and
record state are unknown; this is not evidence of a production Discovery
failure. The QA assertion requiring a raw `free` mode was found inconsistent
with the B-contract. The v4 QA preserves raw requested/result mode, completion,
type, error-presence, counts, snapshot, and record state before assertions; it
does not overwrite results in exception handling, require raw `free`, or require
an incremental record.

The distinct v4 QA harness (SHA prefix `98db3a1`; helper SHA prefix `1e8835`)
passed its pure CLI-boundary self-test. Root approved and Tester completed one
full and one incremental normal CLI metadata run, each once. The unchanged v4
report is `output/yanmaga_access_experiment/stage02/metadata-only-v4-refresh-report.json`
(SHA-256 `0b62fbb74622ef25e30f4f38d64ebc0c30d112365b894a56cc99dc29b85a100b`);
Root's read-only audit `output/yanmaga_access_experiment/stage02/root-v4-refresh-catalog-audit.json` reports `allpass`.

Both snapshots had 57 rows, current authenticated UI, unique canonical identity,
and matching position-31 target sequence. Full Discovery reported native
`complete=true`, `exhausted`, 57 observed rows, and no error. The target's raw
SourceRecord was UNKNOWN; fresh Rental History plus the trusted future grant
preserved Catalog `access_mode=free`. Incremental reported native
`complete=null`, `known_streak`, five observed rows, and no error; it did not
yield the target (zero records) while its snapshot still contained all 57 rows.
After each run the acquisition flag was reapplied to only the target. Root
confirmed the unchanged future grant, pending Item, target identities Work 1 /
Item 27 / Source 27 / Target 27, 0 Artifacts, 0 quota/resource state, two
existing CrawlRuns, and an exact one-candidate direct non-quota plan. Both runs
used zero rights and recorded Source/Viewer, first-party non-GET, and fatal
route counts of zero. No capture was attempted. The v3 report remains preserved
separately; its raw result and underlying cause remain unknown.

The offline CLI-help preflight ran `.venv` help for the root, `discover`,
`batch`, and `batch run` commands; all four exited 0. Outputs are isolated
under `output/yanmaga_access_experiment/stage02/cli-help-preflight/`. This
checks available syntax only and is not a Stage 04 pass.

### Stage 02 C3 and C4 normal-CLI attempts (2026-11-15)

C3 was attempted once under its separately approved normal-CLI contract, then
stopped before Source entry because the metadata-only one-work-request guard was
reused for the final flow. Its report and the known two-work-navigation
explanation remain above. No C3 retry occurred.

Root separately authorized one C4 attempt after QA helper SHA
`a916408933112f9cadc7f54ec2e3824354ca3ed4b8cdbc516d524f8b9eb20a97` and Rental
History helper SHA
`769d7ec68f6864302a0529ae79304ca0a9e67c49725c1d5138e0bf57f8933da3` passed
Root's independent self-tests and actual-prepare check. C4 used the unchanged
position-31 alias `episode-ff-capture-01` (Work 1 / Item 27 / Source 27 / Target
27), same future grant, pending Item, and direct plan, with isolated
`output/c4`, `library/b4`, CWD `c4cwd`, snapshot `c4`, and a separate report.
The fixed adapter, Discovery, and Rental History sources were unchanged.

C4's normal CLI ran once without capture injection, rediscovery, or retry. The
report is `output/yanmaga_access_experiment/stage02/c4-final-capture-report.json`
(SHA-256 `034c0ef4b8bacb7a8eda10f793e5ab90f463e1dd7d820defb052a03c72c5cafd`).
It exited 2 after a Page handle JavaScript error: no dialog was present and the
Node was closed. Root's read-only Catalog audit
`output/yanmaga_access_experiment/stage02/root-c4-catalog-audit.json` reports
`allpass`: Item pending, C1 grant unchanged and future-aware, Run 4 failed with
an exception and `page_count=null`, and Artifact/quota state zero. Genuine
Manifest, page progress, and ZIP were all zero. Error/metadata diagnostics were
preserved; no C4 rerun occurred.

The safe request-observer counted Source GET=1, Viewer GET=1, other requests=0,
and non-GET=0. The run used the existing grant; new first-free, ticket, point,
and paid actions and other-episode attempts were 0. Route counters separately
recorded primary=4, work-document=2, older-sort=1, More=1, recommendations=3,
MyPage=1, History=1, and analytics=45.
The broad `source_viewer` classifier counted 29: exact Source route=1, exact
Viewer route=0, and 28 parent `/viewer/` matches that were broad-denied. Do not
interpret those 28 as Viewer entries or assets. Raw path and Resource Timing
resourceType were not recorded, so request attribution is UNKNOWN. Root checked
the Playwright route API behavior: the route handler sees only the first URL in
a redirect chain. Therefore routeViewer=0 is not evidence that a Viewer hop was
blocked or never reached; the independent request-observer Viewer GET=1 is
consistent with a redirect hop. No driver-error cause or site failure is
established. No production change is justified by this evidence.

Tester inspected the already existing exact Viewer page read-only. During that
inspection, new Page, goto, click, keypress, refresh, and rights use remained 0;
the other two tabs were preserved. The initial safe-resource JSON was truncated
in tool output and not saved; it is not evidence. A later sanitized capture is
preserved at `output/yanmaga_access_experiment/stage02/c4-existing-resource-shapes-v2.json`
(SHA-256 `f1b9d8672ef747479cb13902f44a95e6c34d508e25a384886e68ce2727dea80d`). It
counts 89 resources, 31 first-party, including 28 on
`viewer-assets.yanmaga.jp` under `/viewer/assets/` (JS, CSS, PNG, nested JS);
none had a query. Timing exposed only `initiatorType`; actual Resource Timing
type remains unknown. The Python and page JavaScript both identified the
expected Viewer, with redirect count 1 and status 200, but
`referrer_source=false`; the Source-to-Viewer chain is not proven. The earlier
`c4-existing-viewer-resource-shapes.json` is retained as historical QA output
but its `/viewer/` root filter and encoded-slug comparison were incomplete; the
v2 result corrects the host/path and comics-shape comparison. Do not attribute
C4's 28 broad parent matches to these assets or to the driver error: C4 raw
paths/resource types were not recorded. This read-only inspection observed no
new Source/Viewer/non-GET/error events.

The initial QA preparation SHA-256 was
`d6dfc77bafedd8dac772db599b903ddce55120ff2360fd89635c156f0448a705`. Independent
pre-live review found two blockers: a caller passed a status string to
`_crawl_run_is_successful(run)`, and `safeSamples` accepted an unbounded query
key including a 1,045-character opaque key. Tester corrected only QA code in
SHA `b70e47e36990f5069ab9513c35692de1cdf5e8df0bc66337e4d8cd3883128960`;
independent C5 pre-live review reported BLOCKING 0, and Root's self-test and
actual-prepare check passed with the same SHA. Query sampling is capped at
4,096 characters and 64 fields; semantic-key matching is capped at 32
characters, opaque values are recorded as `<other>`, and sampled key names are
bounded to 10 characters with overflow tracking. Positive and privacy-negative
checks passed. The normal-CLI run-object check is corrected. These were
QA-harness findings, not production source changes.

The read-only resource inventory above supports a narrow QA exception for exact
HTTPS host `viewer-assets.yanmaga.jp`, `/viewer/assets/` path, GET, non-navigation
static fetch types; credentials, query, fragment, and dot traversal remain
rejected. The technical cap is 64, a safety limit rather than a site quota or an
observed limit. This asset predicate must require a synchronous exact Viewer
HTTP 200; UNKNOWN, 302, and 500 are rejected. Keep that response check separate
from redirect-chain request classification to avoid blocking the Viewer hop.
Metadata-mode limits remain unchanged. For the required source-to-viewer proof,
verify the request/response chain in memory: one source request, its immediate
exact Viewer request, source response 302, and Viewer response 200. Record only a
boolean, two request nodes, and one HTTP redirect. A first-hop-only route Viewer
count of 0 is acceptable only when that positive request/response chain is proven.
Source/Viewer request-observer counts must each be 1, with other episodes,
non-GET, and errors 0; recommendations remain capped at 3.

An independent local Chromium fixture (one run, 3.48 seconds; local dynamic port
and test-owned temporary profile only) exercised this event order: Source request,
source route, source 302 response/finished, exact Viewer request, Viewer 200
response, then static non-navigation asset request/route. It produced no
Viewer-route callback but both requests/responses were observed. Source
`redirected_to` the Viewer and the reverse/frame/main-frame checks were all true;
at asset time the Source 302/Viewer 200 chain was present and JS executed. This
is local synthetic evidence only, not a C4 or live-site redirect proof; external
GET and shared CDP were 0 and the temporary profile was cleaned.

The fixed C5 execution contract used adapter, Discovery, Rental History helper,
and QA hashes
`6B26B256809D5CE177E07D154B6625D48F467C88AF90AFDD7CE100B6AE90353F`,
`E560CC4084B87716438BDBEA3D16480CA7CE6A206692FFE1159CA786375361AA`,
`85717DE55E8DCF4873D03E742A465CB1F9966B32640C0DDB2B1402F09C8097E8`, and
`b70e47e36990f5069ab9513c35692de1cdf5e8df0bc66337e4d8cd3883128960`. It
targeted only `work-dual` / `episode-ff-capture-01` (position 31; Work 1 / Item
27 / Source 27 / Target 27), the existing future grant, and the audited direct
plan, in isolated `c5`/`b5`/`c5cwd`/snapshot/report paths.

C5 ran once and failed before content capture because the body did not
stabilize. Immutable report
`output/yanmaga_access_experiment/stage02/c5-final-capture-report.json` has
SHA-256 `79238a71c34164def7b83b244262cbcd781593b91b40aa24abd575b76c675f9b`.
It records one Source request followed by the exact Viewer request (Source
302, Viewer 200; two request nodes and one redirect), 27 allowed static assets
(22 script, 1 stylesheet, 4 images), zero other episodes/non-GET/errors, and
one fatal source-or-viewer violation. Root's Catalog audit found the Item still
pending, the C1 grant unchanged and future-aware, one failed CrawlRun with
`page_count=null`, and zero Artifacts. No additional right was used. The report
is preserved; this failure does not prove a site-side failure.

The safe C5 sample contains one same-main-frame `xhr` at masked path
`/viewer/<opaque>` with query key names `cid`, `dmytime`, `k`,
`random_identification`, and `type`; it contains no values. Offline inspection
of the saved C5 HTML found the static literal `/viewer/bibGetCntntInfo` once
(HTML SHA-256 `4a9bc205b2d1ef474b19dae5cda0488b77dd768725a026a6d9f5bbf3f56e8787`),
but the exact request-to-literal mapping has not been observed. The isolated
evidence is `stage02/c5-content-endpoint-offline-evidence.json`.

A minimal C6-only QA delta adds one unmodified-request allowance for that exact
`https://yanmaga.jp/viewer/bibGetCntntInfo` request: GET/XHR/non-navigation,
same owned main frame, after the verified Source 302 to Viewer 200 chain, and
one attempt only. It reads only a unique `cid` and requires equality with the
exact Viewer URL's `cid`; other query values are ignored, not logged, and not
changed. Query length and field count keep the existing bounded limits. The
response observer records only the status scalar; final budget requires status
200 and exactly one attempt. The request remains browser-generated and is
continued unchanged. No other API, Source/Viewer entry, or resource allowance
is added. C6 used separate `c6`/`b6`/`c6cwd`/snapshot/report paths and preserved
all C5/C4/C3 artifacts. It made one Source and one Viewer GET, verified the
302-to-200 chain and one content-info XHR, then failed because the body did not
stabilize. The C6 report SHA-256 is
`e285c019e5b3fe7a665de9882055b42d1850425373732e13c35d25ffba1e2039`; it records
run 6 failed with page_count null, unchanged pending Item/grant, zero Artifact,
two broad fatal counts and one unknown-subdomain count. No additional right was
used. The C6 request guard proved too restrictive for the normal page flow, so
C7 uses no network route interception or capture patch; it only counts requests
through the existing sanitized observer while invoking ordinary CLI once.
The ignored wrapper is
`output/yanmaga_access_experiment/qa/c7_normal_cli_observed.py` (SHA-256
`757cb1054399a8f7bf77e4a3804852f7e77b0d5b23f1165fd0f8ed124ef91e76`). Its
offline preflight passed for the same existing-grant direct candidate, with
chapter 26 / Source 28 disabled and no quota. C7 report
`stage02/c7-normal-cli-observed-report.json` has SHA-256
`3226ddc9e3708e0ca47b1fc20a461d62be55d4bb5d152fbcaee51ff058bce374`. It
observed one Source GET, one Viewer GET, the 302-to-200 chain, one content-info
XHR, and no non-GET; the normal CLI saved 13 native WebP pages and reached
counter 14/14. The last rendered page and next-episode rental card were both
present, but the run failed before positive END and created no Artifact. The
existing grant and pending Item were unchanged; no new right was used.

Root traced the stop to `_read_snapshot_js` treating all visible modal-named
elements as gates. The observed nonsemantic inline card is nested under the
unique `#rental` auxiliary and uses the exact static selectors
`.episode-modal-expire`, `.episode-modal-rental-detail`,
`.mod-modal-content-inner.episode-modal`, `.mod-modal-content.wrapper-mod-modal`,
and `#js-modal-content.rental-modal`. The site-local gate now exempts only
those exact shapes inside `#rental`; semantic dialog nodes remain gates, and
existing page ownership, viewport, menu, image, END, and page-count checks are
unchanged. The synthetic browser fixture models the adjacent card and final
body page without site HTML or images. A semantic dialog inside that same card
still fails closed.

Validation after the fix: the targeted batch had 30 pass and five WinError 206
failures because its basetemp path was too long; rerunning those five first-free
gate cases with short `output/yfgr` passed 5/5. Adapter Unit passed 10/10 and
the full Yanmaga adapter browser integration passed 106/106 (0 skipped).
Independent Reviewer confirmed 8 pass / 0 skip and BLOCKING 0. Scoped Ruff and
`git diff --check` passed. The first-free gate remained strict in both the
existing signup/access cases and the new inline semantic-dialog case.

The one normal-CLI retry uses the existing grant only. C8 is copied from the
C7 observer wrapper into separate `c8`/`b8`/`c8cwd` and report/log paths; it
checks the C7 report and fixed metadata/source hashes, then runs the ordinary
CLI with passive sanitized request counts and no network interception or
capture patch. C8's wrapper SHA-256 is
`39201d2419525505659892da698b4c6b55a1f26644fac2b4af534614a8d8ed53`; offline
prepare passed for the same direct existing-grant target, with Source 28
disabled. C8 completed successfully: report
`stage02/c8-normal-cli-observed-report.json` SHA-256
`525c532a18bebd2f99ac95ab924adb56ec5eccc8353be2f87c00e108d6a31b63` records CLI
exit 0, Run 8 succeeded, 14 pages, and `stop_reason=end`. Item 27 completed at
`2026-11-16T05:37:42.303655+09:00`; one Artifact was present. Source GET=1,
Viewer GET=1, other episodes=0, non-GET=0, observer errors=0. The C1 grant
remained unchanged and future-aware; quota start and Work-resource count stayed
zero, with no additional first-free use. The 14-page ZIP SHA-256 is
`c9c33b1aa66583eef70220e823f14f9e93cc0e3d119ecfae361d8bb93e4eb35c` (10,990,866
bytes). The genuine Manifest SHA-256 is
`420ba7b88dd92b57bcfaaf9b47b983f689675664dcaccc0a493d350103d77ba2`; Root
confirmed an exact 14-page Manifest/ZIP match and passed the artifact audit.
The archive contains 13 native WebP pages and one safe PNG fallback for the
last page (`segment_source_not_exactly_bound`). Terminal proof reported counter
14, captured 14, complete sequence, visible final page, owned perimeter, rental
card, title, hidden next button/menu, and same route. Independent extraction and
visual review of pages 1, 8, and 14 confirmed chapter 27 and its ending title (`第27話 完`).
The passive watcher ended without its auxiliary watch-result marker, so its
standard audit command did not run; Root directly audited the genuine Manifest
and ZIP. No marker was fabricated and no retry was made. Post-capture full
Discovery exited 0 with 57 observed/known rows, `complete=true`, and
`stopped_reason=exhausted`; the before/after Catalog comparison passed. The
incremental CLI retry exited 0 without error, observed 5 known rows and 0 new,
and stopped with `known_streak`; `complete=null` means completion was not
evaluated. Its report says the Source/Viewer request observer was not used, so
those request counts are unknown. The Catalog retained Source 27 as the only
enabled source, Source 28 disabled, Item 27 completed, Artifact and grant
unchanged, and quota state zero. The post-full plan had zero candidates because
the Item was already completed. A bounded work-intro popup observation found
`DIV.mod-modal-close.js-modal-close`, but its one click did not confirm the
popup closed; the listing remained at 57 rows with no More control, so there was
no further popup action. The ignored QA popup helper recognizes that observed
DIV shape but has only passed compile checks; it has not been live tested. The C6 QA script has SHA-256
`5EAE5EC75296DF37C43F1DE94CF6CD6FFC2E1C83BAD64D35705417E415D48746`; versus
the accepted C5 QA backup its diff is 158 insertions / 17 deletions, limited to
the endpoint branch, scalar counters, a happy/CID-mismatch self-test, C6 paths,
and preserving the C5 failure record during preflight. `py_compile`, focused
Ruff, `--selftest`, and no-execution prepare passed. Preparation reported the
future-aware existing grant, pending Item, zero Artifacts, direct non-quota
candidate, prior failed runs [3, 4, 5], and `capture_executed=false`. No CDP or
live request was made.

The fixed capture request budget remains one Source and one exact Viewer request,
with the same-frame non-navigation static GET exception on exact HTTPS host
`viewer-assets.yanmaga.jp`, `/viewer/assets/` prefix, only after exact Viewer
HTTP 200, with technical cap 64. The chain must show Source 302 and Viewer 200.
C8 verified capture, positive END, ZIP, and Completed for the selected
existing-grant target. Post-capture full Discovery completed with 57 known
rows, `complete=true`, and `stopped_reason=exhausted`; incremental stopped at
`known_streak` with five known rows and `complete=null` (not evaluated). Its
Source/Viewer request counts are unknown because its observer was not
installed. The final independent Stage 02 review accepted PASS with BLOCKING
0. No other episode, new first-free, ticket, point, or paid action was used.

The selected automated candidate is chapter 27, Source 27 / Item 27 / position
31. The user separately reported manually using first-free on chapter 26;
Root's isolated catalog check identifies that as Source 28 / Item 28 / position
30. Chapter 26 is excluded from this automation target and use count, and is
not represented as ticket/quota usage.

The current adapter implementation keeps the one-use first-free transition
bound to an authenticated fresh `free` classification, exact row and public
source href, and final visible marker check. After the Source GET, a DOM-only
bounded poll requires the exact Viewer episode, one valid counter, the current
visible body wrapper, no known access gate, and the exact first-free completion
notice. The notice latch is cleared when the observed expected Viewer URL no longer matches. Only then does
the production helper obtain the finite target-specific lower bound and the
Batch observer synchronously persist it before any image/pixel readiness,
rewind, or capture work. A failed render, END check, or packaging leaves the
Item pending and preserves any saved grant; it does not consume a second
entry. AccessGuard stop and cancellation do not trigger metadata retry. The
release state distinguishes `not_attempted`, `attempted_unknown`,
`site_confirmed`, and `persisted`.

Existing-grant reuse now requires both a still-future trusted Catalog expiry
and a fresh exact-target active countdown immediately before entry. H=1 is
active but has no new finite lower bound, so the stored Catalog expiry can
authorize direct reuse without creating or extending a grant. H=0, unknown or
future-dated observation time, and expired stored grant fail closed. Discovery
also repeats the full same-work snapshot after its async history lookup and
emits no records if work/auth/sort/row identity or ordering changed.

Focused checks after these changes passed: 32 adapter pre-entry/first-free/
existing-grant cases; 49 Yanmaga Discovery browser cases; 95 Yanmaga adapter,
Discovery, policy, and Rental History cases; and a 9-case first-free gate,
timeout, and no-ready targeted selection after the latest gate-token update.
The earlier full adapter browser run passed 99 cases before that final
role-less gate-token fixture expansion. A later full-suite attempt stopped after
2,952 completed calls while one YoungAnimal test produced no progress; it is an
interrupted run, not a pass. A bounded resume selected the remaining 6,179
collection entries plus four earlier failures for recheck (6,183 selected):
6,182 passed, 1 failed, 0 skipped in 12:42, with no per-test timeout. The four
rechecked nodes were the GUI close regression, two Hanayume already-granted
cases, and Yanmaga lossless-WebP pixel capture; all four passed on the resume.
The sole resume failure was
`test_distributed_crawler_yaml_resolves_piccoma_settings_without_changing_other_sites`:
its Magapoke assertion expected 1,000 ms but read 1,500 ms from the user's
unchanged working `crawler.yaml`. The committed blob for this test at HEAD is identical to base `4407e975`; its
working-tree line endings normalize to that blob and `git diff` shows no test
change. `src/screenshot_crawler/runtime_settings.py` and the committed
`crawler.yaml` are byte-identical between base and HEAD. At the full-suite run,
the working `crawler.yaml` had SHA-256
`C71792897E17C8BB4ABAA0D1BF6F0966DE4833DDFCF2902DC88B20C39FF58631` and set
Magapoke to 1,500 ms, which triggered the first assertion. In an isolated copy
of the committed configuration, that assertion passes but the same test then
fails its BookWalker assertion (expected 200 ms; committed config says 0 ms), a
separate existing test/config mismatch. Neither configuration nor test was
edited by this documentation-only update. A later read after the C1 run found
the working `crawler.yaml` at SHA-256
`A73BE4222B95611AD2ADCB6DAEAB57B916EC5AEDDB634AF05F7F6DD74FD565A6`, with
Magapoke `inter_candidate_delay_ms=100000`; its Git diff still contains only
the Magapoke delay overrides relative to the committed file. This later change
was outside this writer's edits; its provenance is not established here and the
file was not modified or restored. The full suite is therefore NOT CLEAN; this
finding is not evidence of a Yanmaga regression. The preserved node-coverage
audit records all 9,131
collected nodes covered across the interrupted prefix and resumed suffix, with
no missing or unexpected nodes; the latest per-node result is 9,130 passed and
this one failure. This is coverage across separate attempts, not a clean single
full-suite pass.

The full-suite GUI-order failure was independently reproduced: a preceding test
patched `QThreadPool.globalInstance().start` on the process-wide singleton and
left an instance attribute that shadowed a later class-level stub. The two tests
now patch `QThreadPool.start` at class level. Forward and reverse pair runs each
passed 2 cases; Lead's affected run of the two changed GUI files plus
`test_gui_repair_migration.py` passed 34, skipped 0, in 82.33 seconds (one
existing pytest-asyncio deprecation warning). This is a test-only isolation fix;
no GUI production code changed. The initial Yanmaga terminal-boundary failure
also passed on one bounded rerun, but its original cause remains unknown. The
first full-suite run is not reclassified as a pass.

C1 and C2 verified release/grant persistence and preservation through
intentional capture-hook failures after readiness/rewind but before the
first saved content page; neither completed page capture, END, ZIP, or
Completed state. Post-C2 full/incremental metadata Discovery and direct-plan
validation are complete and independently audited. C3 stopped before Source
entry on its QA request budget. C4 failed during normal CLI execution after
one Source and one Viewer request, with no saved page or ZIP. C5 verified its
Source 302 to Viewer 200 chain and allowed 27 static assets, but the body did
not stabilize and no content page was saved; its Item stayed pending and
existing grant unchanged. C6 failed before content stabilized and used no
additional right. C7 saved 13 pages and reached 14/14 but did not establish
END because the inline nonsemantic rental card was misclassified as a gate.
The exact known-card exemption has independent BLOCKING 0 review. C8 then
completed the same existing-grant target through the ordinary CLI, with passive
request observation and no network interception. The run captured 14 pages,
reached positive END, produced an exactly matching genuine Manifest and ZIP,
and completed Item 27; Root's artifact audit passed. Post-capture full Discovery completed; the incremental CLI stopped with
`known_streak` and `complete=null`, which does not establish incremental
completeness. The post-full plan had zero candidates because Item 27 was already
completed. The independent final review accepted Stage 02 with BLOCKING 0. The
later post-A5 full/incremental refresh preserved the target, grant, cooldown,
and Artifacts with zero Source, Viewer, or native rental POST activity. Stage 03
is accepted with qualified composite live evidence and independent BLOCKING 0;
its wait-ticket use, grant-only persistence, same-grant capture, positive END,
ZIP, and Completed state were verified across bounded runs. Stage 04 A6/A7 live
runs and independent Tester audits passed. The final Yanmaga affected-test
count passed and the final Reviewer gate passed with independent BLOCKING 0; the full-suite run was controlled-stopped
and is not a full pass. The
additional first-free budget is exhausted;
C8 used no new right, ticket, point, paid action, retry, or alternate episode. The separate ignored QA watcher now skips identical snapshot
rewrites and retries transient Windows replace-permission failures; its local
selftest passed. This QA-only adjustment does not change production capture.

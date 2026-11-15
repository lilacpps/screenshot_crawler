# Yanmaga access expansion progress

**Status:** Stage 01 PASS (observed Discovery subset); Stage 02 C sort sub-gate accepted with independent BLOCKING 0. Stage 02 as a whole remains incomplete; first-free capture and grant persistence are not implemented.
**Plan authored:** 2026-11-15.
**Implementation branch:** `feat/yanmaga-access`, created from latest `origin/main` (`4407e975`).
**Stage 01 implementation commit:** `26cbae8`.
**Authority:** [README.md](README.md), `runbooks/yanmaga-free/README.md`, `AGENTS.md`.
**Workspace boundary:** live artifacts are isolated under `output/yanmaga_access_experiment/stage01/` and `output/yanmaga_access_experiment/stage02/`. No normal Catalog, Watchlist, library, or capture output was used. User-edited `crawler.yaml` and `watchlist.yaml` were preserved.

| Stage | Status | Gate |
| --- | --- | --- |
| 01 Site probe / Discovery | PASS (observed subset); independent BLOCKING 0 | Wait-free, paid-only, and grant/expiry evidence remains unverified. |
| 02 First-free capture | IN PROGRESS (one entry observed; C sort correction accepted, independent BLOCKING 0; capture/persistence pending) | The C sort sub-gate is accepted. Stage 02 capture, immediate grant persistence, and recovery remain incomplete. No more rights use is authorized for this target. |
| 03 Work ticket | NOT STARTED / NOT VERIFIED | No wait-free signal or ticket/cooldown behavior has been confirmed live. Do not infer or enable quota. |
| 04 E2E / final review | NOT STARTED | Depends on earlier accepted stages and live access evidence. |

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
- Wait-free, paid, quota, grant, expiry, and reset-time selectors remain unsupported. Missing `data-limit` continuation and invalid episode URL shapes continue to fail closed. No shared Core, Catalog, or Planner policy behavior changed.
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

**PASS (observed Discovery subset); independent BLOCKING 0.** Lead accepted the review. Stage 02 is now in progress under its own Lead phase contract. Stage 03 remains not verified and cannot be treated as implemented without a live wait-free signal and a separate bounded quota/ticket contract. Unknown behavior remains fail-closed.

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
detached countdown helper is diagnostic only and is not wired to runtime
access state. Immediate grant persistence, retry with and without rediscovery,
complete capture/END/ZIP, and capture-path Completed behavior remain
unverified.

### Stage 02 C sort correction and D countdown observation

The post-entry normal work page for work-dual was default newest-first. A fresh
read-only probe observed two visible same-work sort links; the exact
oldest-first label opened the same work with the sole sort=older query and
became active. One native More click used the observed offset 5, limit 47, and
sort older; its same-work GET returned 200. The 57 resulting IDs exactly
matched the pre-entry oldest-first sequence, with the selected episode at
position 32. Rights use, episode navigation, Viewer navigation, CTA clicks,
and non-GET requests were all zero in these sort probes.

Discovery now requires that observed sort UI shape when present, revalidates
base canonical and og:url, accepts an already-active oldest link without a
click, and selects the oldest link once only when the observed UI is newest.
It performs existing strict expansion and ordering on the oldest-first
document. It rejects duplicate,
hidden, foreign, unknown-query, label-conflicting, and active-state-conflicting
sort controls. Canonical input URLs, canonical/og identity, and public episode
Source targets remain unqueried. Legacy fixtures with no sort UI keep their
existing oldest-first pagination contract. C implementation/tests are complete
and accepted with independent BLOCKING 0; no Stage 02 capture implementation has begun.

The earlier Rental History UI read showed H=23. The latest read-only
exact-target Rental History document showed one target anchor/card and one
visible rental-period label with H=22. One
same-origin no-store GET to the exact observed history href returned 200
text/html, 33,971 bytes, and the detached target-A summary matched H=22. The
safe headers included Date 2026-11-15 03:10:51 GMT, no Age, and
Cache-Control max-age=0, private, must-revalidate. At aware UTC fetch start
2026-11-15 03:10:49.892907 UTC (12:10:49.892907 JST), H=22 yields only the conservative
site_countdown_lower_bound of 2026-11-16 00:10:49.892907 UTC (GET start plus
21 hours). This is not an absolute expiry. The probe recorded one fetch, two
document GETs, zero rights use, zero episode/Viewer routes, zero CTA clicks,
zero non-GETs, and no AccessGuard stop. No further site operation will be
performed for this target.

No rental-countdown parser remains in production code. The temporary
aggregate-text helper and test were withdrawn after Review noted that native
exact label/value leaf nodes and same-card structural binding were not proven.
That DOM relationship was not recorded during the final probe.

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

## Stages 03-04

Not started. Record the Lead-approved scope, live evidence, tests, independent review, and gate outcome here before advancing each stage. Do not infer missing site behavior to satisfy a stage.

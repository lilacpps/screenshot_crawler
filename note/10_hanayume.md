# Hanayume current implementation

Current capture correction (2026-10-19): finite fractional destination dimensions are supported
only when truncation yields the exact target bitmap size. Source rectangles remain complete,
origins zero, and exact observed-rectangle pixel replay plus post-encoding proof remain required.
The failing Item/Source 27945 now reaches END with nine independently verified native pages;
details and validation are in the fractional-destination section below.

Updated: 2026-10-18. Phases 01-04 are complete at source/test checkpoint `467dc69a1ca093ac07e6024b5bddb6575d6cf24c`; implementation, tests, and live verification passed independent review; the focused Hanayume adapter Unit suite plus explicitly selected adapter-browser cases at this checkpoint passed 103 tests, 0 failed, 0 skipped/deselected (266 pytest-asyncio deprecation warnings; 7.36s). The two-class ungranted account-row correction passed independent review with 0 blockers. This result is a separate current snapshot; earlier 342-, 333-, 147-selected-plus-3, and 92-case results are not additive. The pre-guard full-repository snapshot at `1256d3b` remains 3718 passed and 2 failed (0 skipped/deselected; 4737 warnings; 1581.78s), predating later guard/adapter changes: Kadocomi's test-only redirect fixture repair passed its focused check, while the Younganimal cause remains unknown. No changed-source full-repository pass is claimed. Stage 5ca6372 live serial Batch validation passed on existing-grant `49b7e11049871` and free `8c6`; the route-guard error-code follow-up passed independent review. The 9a grant-only run confirmed a second ticket use. The first 0699 normal attempt confirmed checkout and a native grant but failed to persist it; its original reconciliation branch is unknown. A later native-first correction passed review. Full/incremental Discovery and normal direct Batch on existing-grant 0699 then preserved its future episode expiry, reached END with a 30-page PNG ZIP, and used no new checkout or work cooldown backfill. The prior `1d10701c05629` attempt is independently confirmed pre-click by source order: its exact current API was `waitAndFree/hasAccess=false` with null remaining time, a valid ungranted state; checkout/read POSTs were 0. Offline HTML plus a bounded read-only probe showed the exact target row as `mode-current mode-store-item-start` without rental markers. The narrow two-class recognition change passed the 103-case suite and independent review; exact button-label/actionability checks are unchanged. The fresh normal consuming Batch on 1d107 passed the Tester audit with one checkout, a fresh exact current-episode native grant, source/work persistence, END, and a verified 30-page PNG ZIP. Confirmed live ticket use is four on distinct works; the final independent live Reviewer gate passed with 0 blockers, completing Phase 04. Earlier direct Batch and R9 evidence remains historical below.

## Shared Catalog v7 / acquisition-scope gate (2026-10-22)

The site behavior documented below runs through the shared Catalog v7,
Watchlist, Scope Reconciler, and Batch gate. Run the explicit v6-to-v7
migration on an isolated Catalog copy first; Discovery never migrates a Catalog
implicitly. Watchlist discovery_scope is the acquisition-scope authority, while
target enabled controls whether Discovery runs and is not an ownership flag.
Batch requires a current synchronized Scope Reconciler snapshot and
sources.acquisition_enabled state.

Hanayume now supplies a target-bound complete-listing proof for its validated
full range inventory (`hanayume-work:<work_id>`) and supports native bounded
`discovery_scope`. Its existing oldest-first global positions are retained
before the inclusive scope slice; account user rows do not become public
inventory Sources. Only a normal Full iterator exhaustion publishes proof,
and Full only updates evidence/observed positions, not acquisition flags. After
Full, explicitly preview and apply `watch scope-sync` before Batch. A failed,
partial, or Incremental run does not unlock synchronization. Catalog Sources
absent from the proof still block reconciliation. For a NEVER-MANAGED legacy
work without scope/order, explicit bootstrap remains restricted to matching
Watchlist key/site/work ownership. Newly discovered Sources require a fresh
sync before Batch.

A successful Full after a prior scope sync invalidates the sync marker. After
Full, rerun preview and explicit apply with the same Watchlist before planning
Batch. Scope changes also require review and apply. No Source is moved between
keys or deleted.

Use one isolated Catalog, Watchlist, and library path throughout copy
validation; replace placeholders with paths under the same COPY_ROOT:

    python -m screenshot_crawler.cli catalog migrate --catalog <copy/catalog.sqlite> --backup-dir <copy/backups>
    python -m screenshot_crawler.cli watch scope-sync --watchlist <copy/watchlist.yaml> --catalog <copy/catalog.sqlite> --work-key <work-key> --dry-run --json
    python -m screenshot_crawler.cli watch scope-sync --watchlist <copy/watchlist.yaml> --catalog <copy/catalog.sqlite> --work-key <work-key> --apply --json
    python -m screenshot_crawler.cli batch plan --site <site> --catalog <copy/catalog.sqlite> --watchlist <copy/watchlist.yaml> --library-dir <copy/Books>

The scope-sync apply example can also be used after a successful full scoped
Hanayume Discovery. Batch plan remains read-only; use the same copy paths for
any separately authorized execution.

## Registration and browser use

`HanayumeDiscoveryAdapter` is registered in the CLI Discovery registry. `HanayumeAdapter` is registered in the manual Viewer and Batch adapter registries; `HanayumeSitePolicy` is registered in the Batch policy registry. All paths use the shared Crawler Chrome through the existing CDP `BrowserSession` and Playwright `Page`; none launches Chrome or selects a profile. Discovery writes through the existing `DiscoveryService` and Catalog schema. Batch uses the existing Planner/Executor/Runner/Packager; no site-specific Core branch or Catalog schema was added.

The strict Watchlist episode URL is `https://hanayume.com/episodes/<13-lowercase-hex-id>`. Episode IDs are paired with the work ID from the unique `#xHeader a.ep-h-main-h-series` link. Episode pages use `div.ep-main.series-safe-filter-target[data-e2e="pageEpisode"] > div.series.mode-ep` (the inner `.series` has no `data-e2e`) > `.series-eplist-wrap` > direct `.series-eplist-main`. Canonical series routes use `div.series.mode-series-top.series-safe-filter-target[data-e2e="pageSeries"]` as the wrapper parent. Both require a unique public `epList` direct under main; `eli` rows are descendants within `.series-eplist-default.has-store-item.mode-last`. The header work link is outside the episode-list subtree. Global series links are not used because related works appear on the page.

## Enumeration and ordering

The observed listing declares ten contiguous oldest-first ranges, from `1-30` through `271-296`. Discovery reads the whole declared range set, then navigates each numbered route once with finite navigation, DOM, and observation timeouts plus fixed 2,500 ms inter-range pacing in full, incremental, and bounded Discovery. The wait runs after reading one numbered range and before navigating to the next; no pacing is added before the first numbered range. This site-local constant is independent of shared runtime pacing settings. Every page must return HTTP 200 at the exact requested route, preserve its work identity and full range set, and expose one selected marker whose exact label matches the range. The actual page URL must equal the declared route. Live evidence showed the active selected anchor points to the seed episode path on all ten ranges; only that unique selected anchor may use this exact seed alias. All nonselected range links must retain their exact numbered paths.

The 2026-10-18 pacing correction passed all 43 Discovery Unit cases plus the browser-backed full/incremental/bounded case (44 passed, 0 skipped), and `ruff check src tests`. Unit coverage pins the 2,500 ms production default; the browser test substitutes a short delay and records the wait before the second numbered range in each mode. No wall-clock live-site timing verification was performed for this correction. Research/Probe and the full suite were not rerun because the change is limited to the site-local Discovery delay.

Each range must contain its declared number of unique episode IDs. All ranges are buffered before the adapter yields any record, in both full and incremental modes. Global positions are assigned in oldest-first order before the complete records are reversed to latest-first output or sliced by inclusive bounded scope. Split episode labels remain separate as observed; display numbering is not used to derive identity or position. Missing/duplicate rows, foreign work context, route/range drift, invalid labels, or an AccessGuard stop make Discovery incomplete and prevent Catalog source updates.

## Access classification

Access badges are read only from each exact episode row. One exact `無料` label maps to `access_mode=free` regardless of login state. One exact `今なら無料` label maps to `free` only when the current attempt has verified authentication on the exact canonical `/series/<work-id>` route. That check requires one `#xHeader.h` with the observed `hUserMenu` link, nested `hUserIcon`, `signoutBtn` under `.h-usermenu`, and no login anchor. Missing or ambiguous auth markers mean there is no authentication proof for `今なら無料`; missing, duplicate, conflicting, or unsupported row labels remain `unknown`. If the route and listing structure are already exact, the adapter polls for the complete positive marker set for at most five seconds at 150 ms intervals; route or listing drift still fails immediately. Authentication is not persisted or cached across attempts. Catalog stores `access_mode` only; raw badge labels remain site-local diagnostic/helper values.

The natural first-party `GET /api/series/access` response is reduced to exact `seriesId` / `episodeId` access rows; Discovery does not issue an extra API request. A matching `accessType=waitAndFree` promotes an otherwise unknown row to a nominal `quota` candidate (an exact free badge remains direct free). This status never authorizes Batch entry. Full and incremental Discovery reconcile all already-buffered rows, so old grants are refreshed beyond the generic known-row streak without adding range pages. Each authenticated range waits up to five seconds for the episode-local account root to reach its observed ready state before taking the history snapshot. A positive manual grant requires current authenticated series markers and the exact work/episode native row with `hasAccess=true`, `accessType=waitAndFree`, and strict integer `timeRemainingInSeconds` from 1 through 259200. If the exact episode row is present in the account preview, it must also show `mode-read` and one `eliRentStat` rental-expiry marker; a present row without these markers does not grant access. If the exact episode is absent from the preview, absence is not negative evidence and the exact native active row may prove the grant. Unknown, loading, no-user, malformed, or contradictory account state fails Discovery closed or preserves the prior grant. The overall series-auth hydration deadline means authentication was not established; if one observation times out at that deadline, the exact work route is rechecked and the result is unauthenticated/unknown. An earlier observation timeout and any route drift remain incomplete; this does not affirm authentication or weaken the entry proof. Expiry is conservatively anchored at the natural request start plus `remainingSeconds - 1`; an exact matching wait-and-free row with zero remaining seconds clears stale `access_granted_until`. Missing, malformed, mismatched, unauthenticated, or history-unconfirmed access data leaves the existing grant unchanged. No history label or class by itself creates a grant. A public/history badge mismatch is accepted only for that exact episode when this full authenticated active-grant proof is present; other mismatches make Discovery incomplete.

The saved reports have distinct scope: `output/hanayume_experiment/tester/login-nowfree-metadata-20261010T210447Z-86b4f281.json` includes series row/auth metadata and an `episode_route.reader` pilot at counter 1/17 with one 828x1329 canvas for target `90868f4de278f`. The later `output/hanayume_experiment/tester/r3-auth-marker-20261010T214015Z-6fc6ccb8.json` records series auth/listing markers only; it contains no viewer-entry result. Neither is a logged-in Batch artifact. Logged-out gated samples showed signup/login CTAs with zero canvases; a ready Viewer overlapping an entry dialog has not been observed, so universal overlay detection is not claimed. No account, ticket, coin, purchase, or quota action is performed.

## Access guard and CLI

The local profile marks `hanayume.com`, `www.hanayume.com`, and the observed image host `viewer.hanayume.com` as relevant. The shared AccessGuard stops on relevant HTTP 403/429, an explicit `cf-mitigated: challenge` header, or the shared conservative visible-provider CAPTCHA UI check. No broad page-body text detector or speculative host is configured. Page evaluation and access-state observations have site-local timeouts. The shared guard now propagates cancellation from a pending visible-provider locator check so its monitor can close cleanly.

Use the existing CLI form `python -m screenshot_crawler.cli discover --key <watch-key> --mode full|incremental --watchlist <path> --catalog <path>`. Normal operation uses the caller's explicit Watchlist and Catalog paths; research/live verification used only isolated files under ignored `output/hanayume_experiment/`.

## Viewer capture

Manual Viewer capture accepts the exact supported episode URL, verifies its scoped work link, then opens the exact canonical same-work `/series/<work-id>` route to read the finite range set and fresh auth markers. It stops on one unique target row in the bare listing or first observed numbered range; otherwise it follows the observed numbered routes with current-range, unchanged-range-set, declared row-count, and page-local unique-ID checks, exhausting ranges only when the target is absent. `今なら無料` requires the attempt-local verified series auth result; `無料` does not. After opening the exact episode, the adapter rechecks same-work identity and either the exact target row or, when that target is absent there, an episode preview matching the nonempty, unselected fresh bare-series preview by complete ordered ID/label signature or exact reverse. Login/paid entry dialogs or missing viewer structure fail closed without clicking. Unrelated page-wide purchase/resource copy is not inspected as an access gate.

The reader contract remains the observed desktop `mode-spread` layout. Viewer counters and `#xCVPages` wrappers are checked together, active slots must be structurally valid and fully visible, and capture proceeds in contiguous page order. Verified source-canvas pixels are read at their actual native dimensions; source unavailability stops capture without rendered PNG or generic locator/UI screenshot fallback. Only after every body slot is captured does the observed terminal state produce END; the adapter never follows a next-episode card.

For the R8-probed leading-empty layout, `mode-has-top-emptypage` must be present and physical slot 1 must be exactly `-cv-page mode-empty` with no canvas. That slot is excluded from the body; physical body slots are frozen from 2 up to the exact validated CI slot (exclusive), giving 11 body pages for the original 17-page two-PR episode. The initial counter-1 state must also contain `mode-first-page`; the adapter uses one normal public seek step to counter 3, then captures body slots 2/3 onward. The top-empty flag, exact blank lead-in, and body-slot tuple remain bound through native collection and verification. Unflagged blanks, interior empty slots, changed layout, missing spread sides, or incomplete terminal coverage fail closed. Archive capture order is sequential while identities retain physical slot IDs.

### Supported counter/physical-wrapper variant: episode `e2a7ca7bd6dd7`

Investigation on 2026-10-11 reproduced the normal Batch failure for Item/Source `25142` (`番外編 食の都③`). The failing metrics run `4082ffbbf88447dca0c2032c5562bf51` stopped after 1.946 seconds with `Hanayume viewer page-wrapper count is incomplete`; its summary records no HTTP 403/429/5xx, challenge, or CAPTCHA event. Two bounded fresh-page CDP metadata probes reproduced a stable counter `1/17` with **17 physical wrappers**, rather than the former parser's required `total + 1 = 18`. The first probe retained that shape through 8.671 seconds, excluding a short initialization delay as the explanation for the observed mismatch.

There is no `mode-has-top-emptypage` flag: slot 1 is rendered body, slots 1–11 precede `mode-ci` at 12, PR placeholders at 13/14, `mode-good` at 15, and `mode-last` at 16. Every trailing role is one physical slot earlier than the former `total`-based contract. A normal public seek `Home` produced counter `17/17`, seek value 1, and `mode-last-page` with the same 17 wrappers. The probe rewound to counter 1 and closed only its own page. The metadata probe alone did not establish captured coverage; the subsequent standard Batch verification below did. The viewer's internal rounding/padding algorithm remains unproven and is not used as an implementation assumption.

Current behavior accepts the existing `wrapper_count == total + 1` layout, and additionally the observed `wrapper_count == total` variant only for an odd total, with or without the top-empty flag. The flagged shorter variant was confirmed on episode `7c893d766d5ac` on 2026-10-18 as detailed below. Let `last_slot = wrapper_count - 1`. Both variants require the exact top PR and a validated CI/two-or-three-PR/good/last suffix relative to `last_slot`; unknown/missing tail classes fail closed. Body slots are frozen from 1 (or 2 for the exactly validated flagged leading blank) to immediately before CI. The original two-PR layout ends at `last_slot - 5`; the three-PR correction below ends at `last_slot - 6`. The public counter/seek validation remains unchanged. For the original unflagged target this yields exactly physical slots 1–11, rather than incorrectly treating slot 12 (`mode-ci`) as body; the newly confirmed flagged target uses slots 2–11.

Native collect and post-encode verification independently validate this physical tail and exact body tuple. Proofs also retain the wrapper count; count/tail/flag drift rejects the capture, with no generic screenshot fallback. Leading-empty validation remains exact and now also supports the confirmed shorter odd-counter variant. Synthetic tests cover both flagged and unflagged shorter layouts, complete native capture to END, rejected tail/count/flag changes, missing spread halves, and premature END alongside the prior layouts.

Probe evidence: `output/hanayume-wrapper-investigation-20261011.json`; bounded metadata probe: `output/hanayume_wrapper_probe.py`. Post-fix standard CLI Batch evidence: `output/hanayume-wrapper-live-20261011-bc7bbdb0/verification.json`, prepared/audited by `output/hanayume_wrapper_live_verify.py`. The affected target completed 11 pages, ordinary control `90868f4de278f` completed 12, and leading-empty control `c8904d8e3f912` completed 11; all reached END, completed their isolated Items, and created present ZIP Artifacts. All 34 members decoded as 960x1540 VP8L WebP; ZIP CRC, sequential member names, whole-archive size/SHA-256, SQLite integrity, and crawl-status page counts passed. Packaging removed generated source directories as designed. The initial audit incorrectly expected retained manifests; its correction audited the existing completed target ZIP without repeating that crawl. No independent source-canvas RGBA comparison or visual review was performed for these 34 pages, and those historical 134-page proofs are not extended by this run.

Each live case used a dedicated Catalog/output/library and working directory (including metrics). Exact available/free source, target, work, and item metadata were copied from the explicitly selected normal Catalog through a read-only connection; only the isolated retry Item was set pending. The normal Catalog, including the affected Item's existing skipped status, was not written. Access eligibility, pacing, CLI, and max-pages/same-content safeguards did not change. Adapter/native Unit + viewer browser Integration: 115 passed, 0 skipped; Discovery/policy Unit + Discovery browser Integration: 69 passed, 0 skipped (184 total). Ruff (`src tests`) and diff checks passed. All three live metrics summaries recorded zero HTTP 403/429/5xx and zero retries. Full suite was not run because this is confined to the Hanayume viewer/native layout contract; research-helper tests were not needed for production acceptance.

## Viewer layout failure diagnostics (2026-10-18)

User grant-only metrics run `ac9462d6318f488b9f2d00fd6a69e903` failed on Item/Source
`28587`, episode `3eaecb5b69d55`, after 4.281 seconds, with
`Hanayume viewer page-wrapper count is incomplete`. The candidate records
`resource_consumed=true`; the summary has zero 403/429/5xx/challenge/CAPTCHA events and
zero retries. The saved HTML is
`output/batch/hanayume/item-28587-source-28587-20261018T073900955376+0900-855ce707dce04104917dd1eb791cb88c/diagnostics/page.html`.
Offline inspection found a unique Viewer/pages/seek, counter 1/21, 21 direct page wrappers,
and `mode-has-top-emptypage`: top PR at slot 0, empty slot 1, `mode-ci` at 16, PR at 17/18,
good at 19, and last at 20. The pre-fix parser required 22 wrappers for that flagged
21-counter layout; its shorter odd-counter variant excluded the top-empty flag. The old
metadata did not preserve the exact rejected observation, so that report alone could not
distinguish transient mounting from a stable unsupported layout.

The subsequent user failure on Item/Source `28987`, episode `7c893d766d5ac`, metrics run
`c4c2f18a10c946b99de4b886caed4215`, preserved the exact rejected observation: counter 1/17,
17 wrappers, top-empty flag, exact empty slot 1, `mode-ci` at 12, PR at 13/14, good at 15,
and last at 16. The diagnostic observation 5.754 ms later was identical. Its ticket metadata
records entry-only, click-attempted, and confirmed consumption, with zero fallback reads.
The candidate failed after 3.945 seconds; the batch summary has zero 403/429/5xx/challenge/
CAPTCHA events and retries. A separate bounded same-episode metadata probe using the existing
recorded grant observed that complete layout at 1, 2, 4, and 6 seconds after DOMContentLoaded.
This establishes the flagged shorter layout as the cause for this failure, rather than a
missing wrapper that merely needs more startup time. Evidence:
`output/hanayume-viewer-layout-28987-20261018.json`. The probe used an owned new Page through
shared CDP, blocked mutating requests, made no ticket clicks, and closed only its own Page.

Python parsing and the native observer's shared collect/verify body-layout validation now
accept an odd total with `wrapper_count == total` even with the top-empty flag. Exact empty
slot 1 with zero canvases, physical top PR/five-tail roles, counter/seek agreement, frozen
body slots, proof identity/count/flag stability, and complete body coverage before END remain
required. Even-total shorter layouts and missing/changed structures still fail closed. This
changes no ticket eligibility/confirmation, pacing, retries, or Catalog contracts.

Post-fix direct initialization on the already-granted 28987 target passed at counter 3/17,
17 wrappers, with body slots 2–11. A public metadata-only seek reached terminal UI 17/17 and
rewound to 1/17 before cleanup. There were zero checkout attempts, zero captured body pages,
and no new resource consumption or normal Catalog writes. Evidence:
`output/hanayume-viewer-layout-fix-28987-20261018.json`. This verifies initialization and
terminal metadata only; full real capture/packaging and a new consuming grant-only attempt
were not run. Synthetic tests verify native output through END and the real grant-only
Runner/Executor success/failure paths without spending another live ticket.

The adapter now retains a bounded projection of each latest Viewer observation before parsing,
including the rejected sample if parsing/identity/layout validation fails. The existing Runner
failure writer saves it at `diagnostics/metadata.json` under
`adapter_debug.viewer.failure.observation`, with the original error. The projection includes
counts of Viewer/pages/seek roots, Viewer classes (including top-empty), current/total text,
seek values, viewport, wrapper count, slot indices/classes, canvas count/dimensions/readiness,
and a monotonic observation timestamp. It retains at most 128 slots (first/last 64 on larger
episodes), at most 64 class names per node, and at most 160 characters per scalar string;
`omitted_slots` records truncation. It never copies URLs, PNG/base64, canvas pixels, native/API
payloads, credentials, cookies, or browser storage into these new metadata fields.

After an observation failure, `collect_debug_metadata()` makes one read-only metadata snapshot
with a one-second timeout, saved separately as `viewer.at_diagnostics`. A timeout/evaluation
failure records only its exception type and preserves the original failed sample. This is
diagnostic observation only, not a readiness retry. `adapter_debug.ticket` adds entry-only mode,
click-attempted, confirmed-consumption, and fallback-read count. No CLI/config changes are
required. The diagnostics do not change initialization waits, click/consumption rules, or retry
behavior. The existing generic diagnostic writer still writes HTML/screenshot;
its behavior and the shared Core contract are unchanged, so no Core note update is required.

Unit tests cover rejected missing-wrapper observations, preservation when the later
snapshot has 22 wrappers or evaluation fails, exclusion of URL/pixel/transport details, and
bounded slot retention. Browser-backed grant-only tests exercise success and wrapper-count
failure through the real Runner/Executor diagnostics path, preserving confirmed consumption
and source grant, a pending Item, one ticket click, zero CONTENT captures, and no ZIP.
The final affected run (Hanayume adapter/native Unit, complete adapter-browser Integration,
grant-only success/failure for both layouts, and full/incremental/bounded Discovery) passed
221 cases with zero failures or skips (288 existing deprecation warnings; 86.53 seconds);
`ruff check src tests` passed. Research/Probe helper
tests and the full repository suite are not required for this site-local layout correction;
the live evidence and its verification limits are explicitly described above.

## Post-encoding verification diagnostics (2026-10-11)

The user-reported Item/Source `25190` failure stopped at physical body slot 1 with zero saved pages,
`native_target_changed_after_encoding`, and a candidate duration of about 2.8 seconds. Read-only
inspection found 13 saved diagnostic failures with that reason, all at zero saved pages / slot 1.
This supports an initialization race hypothesis but the old boolean verification result does not
identify its cause. The pre-fix readiness checks stabilized counter/seek/active/ready/layout metadata,
without checking canvas generation, writes, or bitmap dimensions. The additional initial-canvas
quiet wait described below addresses that gap; post-encoding pixel proof remains unchanged.

Native post-encoding verification now returns a structured result while retaining the existing
strict gates and one-shot proof deletion. The legacy observer `verify(token)` still returns a
boolean for probe compatibility; production uses `verifyDetailed(token)`. Failures retain the
first failed gate and a bounded selected-row comparison: wrapper/canvas identity equality,
generation/write counts, bitmap dimensions, wrapper/canvas rectangles, readiness/visibility,
viewport, seek, page counters, body slots, and top-empty flag. Pixel comparison on failure reads
only the same selected canvas with unchanged dimensions and records `equal`, `different`,
`unreadable`, or `not_compared`; no pixels, PNG/base64, credentials, or browser storage are added
to these diagnostics. A same-pixel redraw still fails the original write/generation gate.

The existing failed-run path persists these details at
`output/batch/hanayume/<run>/diagnostics/metadata.json` under
`adapter_debug.capture.verification`; `adapter_debug.capture.encode_elapsed_ms` times Python
encoding, and verification `elapsed_ms` is the browser interval since proof collection, including
transport, Python decoding, and encoding. The terminal error/metrics includes
`(verification=<reason>)`. Missing observer/proof, observer integrity loss, timeout, evaluation
failure, and malformed verification results remain fail-closed with distinct reason codes.
The diagnostics addition alone introduced no CLI/config change, readiness delay, automatic retry,
capture fallback, navigation, or Core change. The current startup wait is described below.
Capture-attempt cleanup releases the same resources and preserves the
diagnostic metadata. Only existing Hanayume source/tests/README and this site note are changed;
the shared Core note needs no update because its existing diagnostics contract is unchanged.

Synthetic browser tests cover changed pixels, same-pixel redraw, bitmap reset, canvas replacement,
visibility/position/counter/layout drift, and persistence through the existing failure diagnostics
writer. Unit tests cover verification timeout/evaluation/malformed-result failures. No real-site
reproduction was performed when adding these diagnostics. The subsequent user-run failure below
provides the first detailed live observation.

User-run diagnostic analysis, Item/Source `25220` (`第38話③`, episode `6ef7cf9906de5`):
metrics run `fe912201adfa42d1922adc51d9fa20cf` failed on 2026-10-11 at the first body slot,
zero saved pages, after 2.925 seconds. The saved evidence is
`output/batch/hanayume/item-25220-source-25220-20261011T112455149880+0900-54c915f4d76c4997b58687d06ac11729/diagnostics/metadata.json`.
The gate was `canvas_generation_changed`: generation 4 -> 6 and writes 8 -> 12 during a
461.6 ms browser proof interval; Python WebP encoding took 336.691 ms. Wrapper and canvas object
identities matched. Before/after selected-row metadata was exactly equal: 828x1329 bitmap,
552x886 displayed canvas, the same wrapper/canvas rectangles, ready/visible flags and classes.
Counter 1/15, seek 15, viewport 1906x986, body slots and wrapper count were unchanged.
Failure-only full RGBA comparison was `equal`. Thus the observed failure is strict invalidation
of the same selected canvas after bitmap reset activity despite identical final pixels; it is
not evidence of a page transition, changed final dimensions, canvas replacement, or a pixel
mismatch. The metric summary recorded zero 403/429/5xx/challenge/CAPTCHA events.

Generation +2 / writes +4 is consistent with width and height being reassigned (including
same-value setters) followed by one drawImage, because each reset adds one generation/write and
drawImage adds two writes. This specific call sequence is a hypothesis, not an observed stack
or operation trace: reset(), dimension-attribute APIs and context lost/restored events can also
increment generation. The reset initiator and transient intermediate pixels remain unknown.
The same Item completed in 11.643 seconds in run `0bd98ee7cb504c3eafd67871edcb7398`, starting
2026-10-11 11:25:28.978 JST, about 34 seconds after the failed candidate started. Neither candidate
used CLI retries. These facts support an initial-render reset/redraw race for this case, without
proving that all older failures have the same cause. This checkpoint changes only the site note;
no implementation, wait/retry policy, tests, or real-site browser operation is changed.

Validation: `tests/unit/test_hanayume_adapter.py` plus
`tests/integration/test_hanayume_adapter_browser.py`: 122 passed, 0 skipped;
`tests/unit/test_hanayume_native_capture.py`: 4 passed, 0 skipped.
`ruff check src tests` and `git diff --check` passed. The pytest runs emitted existing
asyncio event-loop-policy deprecation warnings. Full suite and Research/Live verification were
not run: this change adds site-local failure diagnostics, and synthetic browser tests exercise
the relevant proof gates and actual diagnostics persistence without operating the shared viewer.

## Observed Yona PNG fallback and native dimension limit (2026-10-18)

Read-only inspection of the Hanayume `akatsuki-no-yona` Catalog artifacts found 20 completed
archives containing 595 pages, all PNG at 846x1329. The interrupted next Item/Source `26977`,
episode `b0115b14b2324`, retained 11 pages in its manifest; every page records
`capture_mode=rendered_body_canvas_png`, `reason=native_candidate_missing_or_stale`, and
`source_native=false`. This is the clean rendered-canvas fallback, not a source-sized native
PNG retained after a WebP encoder failure. The output dimensions are the displayed canvas
bitmap dimensions and therefore can change with the Viewer geometry.

A bounded read-only live draw-metadata probe on that same free episode observed full-frame
draws from `HTMLCanvasElement` sources at **960x1508** into **846x1329** target canvases.
Observed draws use the complete source/destination rectangles, identity transform, alpha 1,
`source-over`, and filter `none`. The production observer reports integrity true, no disabled
reason, and zero native candidates. The pre-fix `exactFullFrame` condition required
960x1540 source dimensions, so these 960x1508 draws were excluded before candidate creation.
Later native replay/encoding/dimension checks also assumed 960x1540; changing only the
first condition would not provide support. That fixed dimension contract dates to native
capture commit `202f61a`, preceding the later wrapper-layout correction.

Probe evidence is `output/hanayume-yona-native-draw-26977-20261018.json`. Only metadata was
recorded; no source pixels, native replay equivalence, or alternate-dimension native output
were verified. Mutating requests were blocked; checkout attempts and new resource consumption
were zero. The probe closed only its own shared-CDP Page and did not write the normal Catalog
or existing archives. The new observation explains this episode's absent native candidates;
it is not an all-page source-dimension survey of all 20 archives. The subsequent variable-size
implementation and verification are described below; existing archives remain unchanged.

### Variable native dimensions and strict failure behavior

At the user's request, the source observer now reads actual source dimensions rather than
requiring 960x1540. The source rectangle remains exactly full-frame; destination rectangles follow
the fractional-destination contract below, with the original
identity-transform, context/paint, opacity, episode/slot, generation/write, wrapper identity,
and pixel replay checks. Each source is independent; a spread may contain different sizes.
The immutable snapshot, replay rectangle, pixel-count checks, exported PNG dimensions, Python
decode, lossless WebP encoding, and capture metadata all use that source's dimensions.

Both source and display canvases must have strictly positive integer dimensions no greater
than 4096 per side and at most 4,000,000 pixels. Before snapshot allocation, the observer enforces
eight cached candidates and 12,000,000 cached source pixels (about 48 MB RGBA); overflow latches
failure. Python also validates native dimension limits before decoding the PNG. Existing encoded
image byte limits and bounded capture/encode timeouts remain unchanged. These are resource guards,
not a claim that every image/source/context format is supported.

Native source absence, unsupported dimensions, missing observer, invalid replay/context, stale
candidate, or source readback failure now returns an error without reading/saving the display
canvas. An incomplete native spread cannot produce partial captures or fall back to a rendered
spread. The adapter also rejects legacy/non-native capture results. The terminal error includes
the failed reason and explains that rendered PNG fallback is disabled; failure diagnostics retain
the observed per-slot source dimensions when available. A failure after native encoding still
uses the original strict post-encoding proof and never retries or weakens it. If only lossless
WebP encoding fails, the same verified source PNG may be retained at its original dimensions;
this does not restore the removed rendered-canvas fallback.

No new CLI/config is required. No normal Catalog state, completed status, old ZIP, access rule,
ticket operation, or browser ownership contract changes. Variable-size captures are verified in
synthetic tests and a separate isolated live run; detailed results are recorded below.

Final validation: 236 Hanayume adapter/native Unit and adapter-browser Integration cases passed
(0 failed/skipped; 284 existing deprecation warnings; 79.40s). The full Discovery/Batch browser
file passed 96 cases (0 failed/skipped; 5 warnings; 265.69s), for 332 distinct affected cases.
Six Discovery-to-Batch ZIP and grant-only success/failure cases were additionally rerun after
the final source API-shadow rejection gate (all passed). Ruff (`src tests`) and diff checks pass.
Coverage includes 960x1540, 960x1508, 1200x1600 and 640x480 through complete native capture to END;
mixed-size spreads retain each source size and last-pixel values after the mutable source is
cleared. Unsupported source dimensions stop the real Runner with an empty manifest and no body
files. The reduced-cache-budget test preserves normal drawing while making capture fail closed.
Missing observers, stale/reset/tampered targets, and replay errors now stop rather than render-fallback.
Codec-failure tests still preserve exactly the same original-size source PNG.

Live evidence is `output/hanayume-native-size-live-20261018/report.json`. An isolated direct
Runner run reached END on Yona Item/Source 26977 with 30 native 960x1508 lossless WebP pages;
the ordinary control Source 25326 (`90868f4de278f`) reached END with 12 native 960x1540 pages.
An independent document-start hook copied the source canvas at draw time, outside the production
observer. Its deferred readback matched decoded output RGBA for all 42 pages before advance.
This is decoded source-canvas equality, not original JPEG proof. Both runs used owned new Pages,
blocked mutating requests, had zero checkout attempts, and made no normal Catalog/old archive
writes. The control's first verification script used a nonexistent result `page_count` accessor
after END; its 12 verified pages and END were retained and the count was reconciled from the
existing manifest without another control crawl. After the final source API-shadow gate, a
fresh one-page Yona smoke passed at 960x1508 WebP with the normal strict proof and no consumption;
its evidence is `final-source-guard-smoke.json` in the same directory. The isolated outputs are
retained; the prior 20 completed PNG archives are unchanged and were not automatically reacquired.

### Post-recrawl Yona 764x1200 verification

The user's normal recrawl on 2026-10-18 completed Item/Source 26957, episode `209e25d120624`,
第274話, at END with 30 WebP pages. Read-only inspection of its current ZIP found all 30 at
764x1200. This does not contradict the prior 960x1508 observation on Item/Source 26977,
episode `b0115b14b2324` (a different episode); source dimensions are not work-wide constants.

A bounded direct probe on the completed 26957 episode observed full-frame draws from 764x1200
source canvases into the Viewer's 846x1329 display canvas. Five naturally delivered Viewer JPEG
responses also decoded as 764x1200. Production capture on the first body page returned
`source_canvas_lossless_webp`, `reason=null`, with source/output dimensions both 764x1200.
Thus this observed output preserves the supplied source size; the Viewer is enlarging it for
display, rather than the crawler downscaling a 960x1508 source. The JPEG observations cover the
natural first-page/preload responses, not an independent all-30-page response attribution audit.
No claim of original JPEG byte preservation is made.

Evidence: `output/hanayume-yona-26957-source-dimensions-20261018.json`. Checkout attempts and
new resource consumption were zero; only the owned shared-CDP Page was closed. No production
code, normal Catalog state, or archives were changed by this investigation. Only this note is
updated, so no production test rerun is needed. The per-episode observation must not be used to
force 764x1200 or 960x1508 onto other episodes.

### Preparing existing Yona archives for re-crawl

`scripts/prepare_recrawl.py` now has an explicit Hanayume archive policy: WebP is preferred,
PNG is the fallback format. This labels formats, not pixel fidelity; native-size codec-fallback
PNGs also match, so use the dry-run before applying. For the known resized Yona archives,
`python scripts/prepare_recrawl.py --site hanayume --work "暁のヨナ" --catalog catalog.sqlite
--ignore-missing` selects completed Items for that exact site/title. The 2026-10-18 real
dry-run found 20 candidates (Items 26957–26976), all FALLBACK_INCLUDED, with zero preferred,
unexpected, broken, missing, or ambiguous artifacts. Its report is
`output/hanayume-yona-recrawl-dry-run-20261018.txt`; no real apply was performed.

Adding `--apply` moves each selected ZIP to `output/reimport-backup/<timestamp>/`, updates its
Artifact locator, and marks the Item pending. Prior runs/artifacts and source/work access state
are retained. Merely resetting status would leave the existing ZIP at its destination and can
cause a packaging name collision. Normal Batch, without `--grant-only`, performs the later
recrawl. Its `--site hanayume` scope includes other pending Hanayume Items; `--work` is supported
by this preparation script only. This statement describes the historical
pre-v7 preparation helper: current Batch always requires the shared Watchlist
scope-sync gate, and target enabled controls Discovery execution only.

Changed files for preparation support: `scripts/prepare_recrawl.py`, its existing Unit tests,
and the Core/site notes. All 24 preparation tests passed, zero skipped, plus Ruff on the script
and tests. Synthetic apply covers Hanayume backup/locator/pending behavior and byte preservation.
No browser/Live/full-suite rerun is needed for the static policy addition; existing capture code
is unchanged by this preparation support.

Full repository and Research/Probe helper suites were not run: this change is confined to
Hanayume production capture and its synthetic fixtures. No newly consuming ticket run was needed;
the existing grant-only/access behavior is covered by the browser tests without live consumption.

## Initial body-canvas quiet wait (2026-10-11)

After rewind, ordinary-layout initialization waits at counter 1 / body slot 1; top-empty
initialization first performs its existing intro seek, then waits at counter 3 / body slots 2/3.
These first-body readiness waits now require 1000 ms of unchanged selected-canvas state, sampled
every 100 ms, with a separate 5000 ms deadline including observation calls. Native-observer
generation/write counts and ephemeral wrapper/canvas IDs join the existing counter, seek,
active/ready/body layout, plus selected-row bitmap dimensions, classes, geometry and viewport.
Any observed change restarts the quiet interval. The strict parser still rejects UNKNOWN/layout
drift; persistent rendering/loading times out rather than capturing or navigating past it.

Sampling is metadata-only: it does not encode, hash, read pixels, delete source candidates, or
create native proofs. Node identity tracking uses a WeakMap; only selected rows are returned.
If the source observer is unavailable or fails its integrity check, initialization can complete
the quiet interval using visible metadata only, but capture fails closed without rendered PNG. Diagnostics
mark this distinction with `adapter_debug.initial_canvas_settle.canvas_tracking=false`.
The settle diagnostic also records status, quiet/timeout/elapsed milliseconds and the final
selected-row generation/write/identity sample. Successful tracked waits use `canvas_tracking=true`.
These fields carry no pixels or credentials and require no new CLI option.

Only the first body capture gets this extended quiet wait. Ordinary page-turn pacing/readiness,
native source attribution, WebP/PNG encoding, post-encoding proof, ordered page coverage and END
are unchanged. A reset during later native encoding still stops with the existing detailed error;
no automatic capture retry or acceptance of stale/same-pixel proof is added. This is mitigation
based on the observed initial-reset race, not a guarantee against arbitrarily late initialization.

Synthetic browser tests reproduce a late same-pixel bitmap reset for ordinary and top-empty
layouts, require a fresh quiet interval and verified native capture, and reject continuous resets
at the deadline. Observer-missing capture now stops without a rendered-PNG fallback. Existing post-encode
generation/write/identity/layout/position failure tests continue to require rejection.
Validation: affected Adapter/native-capture Unit tests passed (45); Adapter browser Integration
passed (87), totaling 132 unique cases with zero skips. The new stalled-observation Unit test
also proves the initial quiet deadline bounds the observation itself. Ruff and diff checks passed;
existing asyncio deprecation warnings remain. Before the main merge, the standard full suite
was run in an isolated merged worktree containing both Hanayume and main's existing Piccoma
changes: 2214 passed, 0 skipped, 587.26 seconds. Ruff and the complete staged diff check passed.
Two pre-existing trailing blank lines in runbook Markdown were removed during that diff check;
no runbook behavior changed. No separate Research/Live probes were added for this merge.
No new live run is performed while the user's two existing Batch processes are active; the shared
browser remains untouched. Live reduction in failure frequency needs subsequent user runs.
Source changes are limited to Hanayume Adapter/native observer, their Unit/Integration tests,
README and this site note; the shared Core note is unchanged because Core behavior is unchanged.

## R5 bounded readiness handling (independent review PASS; final E2E PASS)

On an exact canonical series route with a structurally valid listing, authentication polling waits at 150 ms intervals for at most five seconds for the complete positive marker set. The route and listing are revalidated on every poll. Deadline means authentication was not proven and exact `今なら無料` remains unknown; it is not treated as proof of logout. Viewer initialization waits up to five seconds for the known unique current/total counter nodes to contain text before the first strict observation; duplicates or malformed nonempty values still fail closed.
The probe `output/hanayume_experiment/tester/runs/r5-auth-preflight-20261010T225759Z-d73d76a9/probe_report.json` observed the positive marker set at 150 ms after an initially absent snapshot. `r5-auth-preflight-20261010T225635Z-7417bdd0/probe_report.json` recorded successful auth preflight followed by a missing Viewer counter. The counter's delayed transition itself was not directly observed; delayed and never-present cases are covered by synthetic fixtures. Final E2E passed after these bounded readiness checks.

## R4 public-list correction (independent review PASS)

Discovery recognizes the observed `pageSeries` ancestry on the canonical work route and the separate episode route `pageEpisode` ancestor > `series.mode-ep` child (without `data-e2e`). It reads rows only from the unique direct public `epList`; rows are descendants inside the observed `.series-eplist-default.has-store-item.mode-last` child, so readiness waits for rows beneath the root rather than direct root children. A directly scoped `epListUser` history sibling is ignored for enumeration, while overlapping row labels are compared; only the exact authenticated active manual-grant row may have a different public/history badge. Other conflicts and unknown/nested/duplicate roots fail closed. Runtime preflight applies the same public-root rule. Complete range validation, row uniqueness, global positions, and buffering are unchanged.

## R2 reviewer correction checkpoint (independent local review PASS; final all-page native E2E PASS)

The episode entry check requires the unique public `epList` directly under `.series-eplist-main` in the verified `pageEpisode > series.mode-ep > wrapper > main` ancestry. It permits only the observed direct `epListUser` sibling, checks overlapping copies for identical labels, and rejects unknown target-like copies, duplicate roots, unknown roots, and nested branches. Native proof records the exact episode pathname at draw time and checks saved Canvas context/transform APIs and paint descriptors. Native source copies are made at draw time; readback/replay/encoding occur only after selection. A native proof exception or miss uses clean rendered PNG for the whole spread; an unreadable selected rendered canvas fails closed. Only one proof is outstanding, and selected-slot cleanup preserves future preloads. The R1 focused replay/readback ran synchronously inside the draw wrapper; it did not demonstrate deferred replay.

R2 independent local review passed BLOCKING 0 (109 tests, 0 skipped; Ruff/diff PASS). The final E2E verified 134/134 native 960x1540 source-canvas pages with exact independent RGBA matches and no rendered fallback. The earlier R1 synchronous replay control did not prove deferred replay; the production and final independent draw-time audit did.

## Batch policy and execution

`HanayumeSitePolicy` admits available `free` sources as direct, available `quota` sources with a future `access_granted_until` as non-consuming direct, and other eligible `quota` sources as one `work_ticket` candidate scoped to `work` with `quota_limit=1` and `after_observed_consumption`. It declares the same resource for grant-only. The local work-ticket recovery check is at least 23 hours; caller configuration may lengthen it but cannot shorten it. Batch uses only the selected Catalog episode URL and validates the exact work/episode, target-local hydrated `epListUser` root, native eligibility, and unique enabled free-reading control under the observed central charge ancestry. Preview rows require unique canonical episode links and exactly one title each; WF/IF icon counts remain diagnostic only and are not identity or access evidence. Read-only observations showed non-target rows without either icon, a target blank row with both, and a target read row with neither account-row icon while the public copy had both. Target identity, target-specific classes/rental state, native identity/access, and the scoped control remain independently validated. After the isolated 9a failure-before-click exposed the unsupported icon requirement, the icon-only predicate was removed; focused synthetic verification passed 77 adapter Unit cases, 22 ticket-selected Adapter browser cases (87 intentionally deselected), and 48 ticket-selected Discovery/Batch browser cases (41 intentionally deselected), all with zero skips. Three supplementary absent-preview denial cases passed with zero skips. Independent review passed; no live click was performed for this correction. Ordinarily the target account-preview row is present and must show a known blank/read state. The exact observed ungranted account classes `mode-current mode-store-item-blank` and `mode-current mode-store-item-start` are both accepted only with zero rental markers; the `store-item-start` class alone does not prove an active grant. A false `waitAndFree` current row may have `timeRemainingInSeconds=null`; a strict positive integer is required only for active-grant proof. A read-only probe of 1d107 confirmed this exact row shape, and the two-class predicate passed independent review at checkpoint `467dc69a1ca093ac07e6024b5bddb6575d6cf24c`. If both unique, nonempty public and account previews are structurally valid but omit the selected episode, the same-page exact `/api/episodes/<episode-id>` response must match `episode.id`, `episode.series.id`, and `episode.access.episodeId` to the selected Catalog work/episode, with strictly typed `hasAccess`, `accessType`, and bounded `timeRemainingInSeconds`. This exact current-episode proof is required to establish an ungranted prestate in both the initial and final pre-click snapshots when the target is absent; a series-level false row alone cannot authorize a click. Duplicate/malformed rows, another `mode-current` row, and any present contradiction still fail closed. The exact visible/enabled free-reading control remains mandatory before one click.

The CLI prints the policy-owned next check time for both normal quota and grant-only local cooldown SKIPs when `grant_only_retry_at()` supplies one. If the hook is absent or returns `None`, the output remains reason-only; metrics still record the local skip reason without a retry timestamp. These Catalog-only skips do not open a Page or wait.

Native consumption confirmation requires a same-page checkout `POST /api/checkout/rental` HTTP 200 after the attempted click plus fresh exact native grant evidence. A fresh current-episode `waitAndFree` transition from `hasAccess=false` to `true`, with positive bounded remaining time and all three current endpoint IDs matching the Catalog work/episode, latches `AccessConsumption` before post-action account-list DOM validation. A later account-list, Viewer, capture, or packaging failure cannot erase that confirmed consumption. If a later-started exact series response includes the target, it must also report active `waitAndFree`; expiry is the earlier of the current and series request-start plus `remainingSeconds - 1` values. A newer parsed series denial, paid/unknown target state, duplicate target row, or identity conflict blocks the latch; a later series snapshot that simply omits the target is not a denial. When no fresh current positive proof is available, the existing stricter series-positive response plus exact `mode-read`/rental-history path remains supported. That read row accepts the observed `mode-store-item-start` or `mode-store-item-blank` class only with one rental-expiry marker; a blank row without that marker cannot establish a grant. If the natural current response is missing or the newest native state still explicitly reports `hasAccess=false`, the same Page may make at most two exact read-only GETs within one attempt-scoped five-second recovery deadline. The budget does not reset on exception-path reentry; no navigation or ticket retry occurs. Confirmation time anchors the 23-hour work cooldown. The source grant uses conservative native expiry, capped by policy fallback at confirmation plus 72 hours. An invalid native expiry does not erase confirmed consumption: the generic executor records the policy fallback when possible, then reports the metadata error. Normal Batch continues in the same Page through Viewer capture, END, and ZIP; grant-only validates same-page Viewer readiness with zero CONTENT page captures, zero ZIP, and no completion. A failing candidate may still emit a generic UI screenshot diagnostic. A configured direct candidate fails closed on the exact observed central Work Ticket/login gate during initialization and again at each Viewer CONTENT state, before capture; ordinary free direct and anonymous free paths remain supported. Manual Discovery grants remain target-local and do not invent work cooldowns. Unknown, paid, owned, and rental remain ineligible. No Catalog schema or site-specific Core branch was added; `AccessConsumption` carries an optional generic native expiry. For identity-bound configured Batch, `configure_run` installs a Page route guard before the selected episode `goto`; manual entry and Discovery are unaffected. It passes the exact selected canonical episode document and selected-page RSC, and leaves API/static/image content routes outside guarded `/episodes/*` and `/series/*` families untouched. It aborts only a known nonselected route-data request matching the observed HTTPS/allowed-host, no-userinfo/default-port, GET, single nonempty `_rsc`, `rsc: 1`, `fetch`/`other`, optional `next-router-prefetch: 1` shape and a 13-lowercase-hex episode/work path with an observed range-number or `old` suffix. This conservative signature identifies route data but does not claim every such request is a Next prefetch. Unknown IDs/suffixes, malformed signatures, off-target documents, non-GET requests, or other unrecognized episode/work routes are aborted and latch fatal before ticket click/capture. A response from any off-target episode/work route increments a distinct escaped-response counter and latches fatal. Audit metadata contains only counters and a fixed reason code; it omits request URLs/query values. Stage 5ca6372 live serial validation used the already-granted `49b7e11049871` (30 PNG pages, 925x1329) and free `8c6` work (VP8L); both reached END and passed ZIP audit, with zero checkout and no work quota consumption. Page A closed before Page B opened. Two observed off-target RSC attempts in that run were blocked with Chromium's default `ERR_FAILED`; the explicit `blockedbyclient` error code is covered by synthetic tests, which report `net::ERR_BLOCKED_BY_CLIENT.Inspector` and zero off-target responses. The bounded post-commit live error-code re-audit passed with zero off-target responses; no additional ticket was used for that audit. The later 9a grant-only live check confirmed ticket use. The initial 0699 normal Batch observed checkout HTTP 200 and current-episode false-to-true native access but did not persist consumption in the then-current adapter; the native-first correction later passed independent review and the 342-case affected suite. Full/incremental Discovery and normal direct Batch on the already-granted 0699 source then passed without reconsumption. The separate 1d107 quota candidate stopped before click: source-order review places its UnknownPageStateError before exact-control validation and before `_ticket_click_attempted`; the exact native response reported matching IDs and `hasAccess=false/accessType=waitAndFree`, for which null remaining seconds is valid ungranted state. Offline HTML and a bounded read-only probe found the exact account/public target row as `mode-current mode-store-item-start` with no rental marker. Checkout/read POSTs were 0; the original Tester unresolved label is superseded by source-order adjudication. The targeted two-class recognition change passed 103 unit/browser tests and independent review; the final normal consuming Batch passed Tester and independent Reviewer audit with one checkout, fresh current-episode native grant, source/work persistence, END, and a verified 30-page PNG ZIP. Cumulative confirmed live ticket use is 4.


The document-start source observer copies an opaque sRGB/unorm8 full-frame canvas at its actual bounded dimensions. The cache holds at most eight candidates and 12,000,000 source pixels (about 48 MB RGBA). Exact target, wrapper/slot, generation/write/dimensions, safe geometry/context, and same-episode provenance must remain valid. Validated native pixels are encoded as strict single-chunk VP8L lossless WebP method 4 only after full RGBA round-trip validation; encoder failure returns the same verified source PNG at the same dimensions. Missing, over-limit, or unsafe native proof stops capture without rendered PNG. The historical final run verified 134 pages at 960x1540 with independent RGBA equality; the variable-size live run described above adds a separate 960x1508 case. This is decoded source-canvas fidelity, not original JPEG bytes or tile reconstruction.

Phase 03 verification: the affected unit suite passed 370 tests with 0 skips. The full
Hanayume Discovery/Viewer browser group completed with 166 passed, 1 failed, and 0 skipped. Its one failure was in the
existing `same-width-attribute` rendered-PNG fallback case. Its test-only default
initial-canvas settle deadline was 800ms and expired with about 6 microseconds left
before `Page.evaluate` under the broad run. That fixture default is now 2000ms;
production capture proof and deadlines are unchanged. The exact fallback case and
four explicit settle variants passed 5/5 after this adjustment. The seven focused
ticket/gate cases passed 7/7. Selected ComicDAYS/Zeblack browser tests previously
passed 242/242. `ruff check src tests` and `git diff --check` pass; no test was
skipped or deselected. The formal Phase 03 Reviewer result is PASS / BLOCKING 0.
The Lead full-suite run on the pre-guard source snapshot `1256d3b` completed with
3718 passed, 2 failed, 0 skipped/deselected, 4737 warnings, and 1581.78s. The
failures were a Kadocomi synthetic redirect fixture denied by the environment and a
Younganimal rendered-PNG case that ended after seven saved files with a generic
fallback error. The Kadocomi test-only fixture/validator follow-up passed its focused
selection (6 passed, 227 intentionally deselected); the exact Younganimal case passed
an isolated timing trace, which did not establish the original cause. No production
change was made for either site.

The first broad changed-source Hanayume browser run had 237 passed and two failures
in fixture Discovery setup for logged-out targets. Exact isolated reruns passed; the
failure cause was not preserved. A separate fake-clock/FakePage test then proved a
deadline-boundary inconsistency in the auth observation helper: its inner timeout at
or after the total auth deadline was reported as incomplete rather than unauthenticated
unknown. This controlled bug reproduction is not proof that it caused those earlier
failures. The minimal site-local fix preserves exact route validation and returns
unauthenticated only when the total deadline has expired. Four new unit contracts
cover deadline expiry, an earlier observation timeout, route drift at timeout, and
cancellation. The auth-focused family passed 16 tests (110 intentionally deselected).

Final affected Hanayume suite (unit adapter + unit Discovery + both browser files)
passed 281 tests, with zero skips/deselections, 225 pytest-asyncio deprecation
warnings, in 263.35s. The temporary ignored diagnostic recorded expected malformed /
incomplete fixture cases; neither of the prior failed nodes emitted an exception or
incomplete Discovery result on this final run. This does not explain the earlier
failures. Route-guard selected tests passed 22 (119 intentionally deselected), and
independent route-guard unit validation passed 27. The two initial full-suite failures
remain recorded above; no full-suite rerun was performed on the changed source.
The post-change route-audit command
`.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.p6 tests/unit/test_hanayume_adapter.py tests/integration/test_hanayume_discovery_browser.py -k "batch_route_handler_passes_selected_and_blocks_unknown or batch_route_signature or discovery_to_batch_zip_completes_only_eligible_candidate or batch_route_guard_fails_closed_before_ticket_or_capture"`
passed 32 tests, with 120 intentionally deselected, zero skipped, 95 pytest-asyncio
deprecation warnings, in 15.71s. Its browser family observed four blocked off-target
requests as `net::ERR_BLOCKED_BY_CLIENT.Inspector` and zero off-target responses.
`ruff check src tests` and `git diff --check` both passed after this documentation
synchronization. The only confirmed ticket remains the Phase 01 authorized grant on
`49b7e11049871` / Work `34bf61d51ebc3`; no tickets were used in Phase 03/04 follow-ups.
The bounded post-commit live error-code audit passed with zero off-target responses.
The independent review of the current-episode fallback fix passed with zero blockers. The fixture-only delayed-body correction passed its focused family and the five-file affected suite (333 passed, 0 failed, 0 skipped/deselected; 306 pytest-asyncio warnings; 459.91s) before the preview-icon correction. The later icon fix passed its selected Unit/browser tests and three supplemental denial cases. Live grant-only on `9a2b14d706281` confirmed a second ticket use. The following normal quota Batch on `06994043345b1` confirmed a third site ticket use through checkout HTTP 200 plus a fresh exact current-episode `false → true` access transition, but the adapter reported unconfirmed consumption and persisted neither source grant nor work quota state; the Item stayed pending and no artifact was produced. Offline review of that trace is pending. Do not retry or spend another ticket. Current CLI output work does not change adapter confirmation behavior. Exact debit and recovery counters remain unknown.

## R9 configured Batch live verification

The configured direct-entry target `aca2240729bd0` completed 10 pages at END. Its isolated artifact audit passed for a 7,161,994-byte ZIP containing 10 960x1540 single-chunk VP8L WebP pages (SHA-256 `69e1ff1fcd1bc460e3ab76d28289454cd2432e74c9b23d25f74b35baa37232c9`). Batch metrics counted 260 requests (257 HTTP 200, 3 HTTP 204), one canonical episode document request, zero series/range document requests, and zero 403/429/5xx, challenge/CAPTCHA aggregate events, or retries. Independent source-canvas RGBA equality was not measured.

A separate normal-control run used standard full-mode Discovery with one isolated Watchlist entry, created one source in a new isolated Catalog, and then ran standard Batch. The `90868f4de278f` item completed at END with 12 pages, zero quota-resource rows, and one present 7,256,143-byte ZIP. Read-only artifact audit passed ZIP CRC/order/member hashes and archive hash/size checks; all 12 members are 960x1540 VP8L WebP. Batch document metrics counted one canonical episode document and zero series document requests. There was one HTTP 502 from a relevant non-document Hanayume episode resource; the run completed with zero retries and no 403/429 or aggregate challenge/CAPTCHA events. Independent visual review of first/middle/last samples passed. The report and sample images are in `output/hanayume_experiment/tester/runs/r9-control-diagnostic-20261011T015208Z/`.

The control CLI emitted a new metrics file at `output/metrics/20261011T105245520580+0900-hanayume-normal-2b28c7b9cef6484db24baf49b8aeec01.jsonl` despite isolated Catalog/output arguments; it was left untouched. The initial control attempt failed at Discovery with a generic report and no per-target logs; its cause is unknown, no Batch ran, and the later successful attempt does not establish the cause. R9 code/test and manual-preview evidence are recorded in `runbooks/hanayume-free/PROGRESS.md`. These two new R9 cases do not expand the separate historical 134/134 independent RGBA proof.

## Verification and limits

R4 route-specific public-root correction passed independent review and a fresh full Discovery validated 296 rows. R5 readiness corrections passed 264 affected tests (0 skipped; 333 deprecation warnings), independent review, and full `ruff check src tests`. The initial logged-in Batch preflight stopped before capture because positive auth markers were not yet present; the R5 probe later observed them at 150 ms, and the final E2E completed all four candidates. The full suite was not rerun after later site-local changes; its earlier 2,037-pass result is historical.

The logged-in one-episode Viewer pilot evidence is `output/hanayume_experiment/tester/login-nowfree-metadata-20261010T210447Z-86b4f281.json`; it records a ready 1/17 viewer for one exact `今なら無料` target at 828x1329, with no ticket/purchase/quota action. The later `output/hanayume_experiment/tester/r3-auth-marker-20261010T214015Z-6fc6ccb8.json` supports the series auth-marker check only and has no viewer-entry result. Neither report proves all-page capture or a logged-in Batch artifact. Full-work 296-row, three-episode rendered-PNG E2E remains historical and does not verify R2 native WebP output.

## Final live E2E (2026-10-11; Tester PASS / BLOCKING 0)

Final run 20261010T231618Z-a02345e9 performed fresh standard Discovery, validated all 296 rows, applied the standard inclusive Watchlist scope, synchronized four records into a new isolated Catalog, and ran standard Batch for these four candidates. No Catalog backup was reused. The full-work observation had 296 unique IDs and contiguous global positions 1-296: 3 exact `無料` and 293 exact `今なら無料`. The fresh authenticated attempt classified all as free; the four scoped records were selected latest-first.
The four selected episodes were `90868f4de278f` (12 pages), `2ec9c6b024ee0` (50), `9202b052ad237` (40), and `8c6f15923caa0` (32). All reached END and completed their Catalog items. The four ZIP artifacts passed CRC, Manifest order, member-count, and SHA-256 checks; all four are present.
All 134 body pages are 960x1540 original source-canvas pixels encoded as single-chunk VP8L lossless WebP. An independent document-start hook copied the source canvas at draw time; deferred RGBA readback matched all 134 output pages exactly before advance. Rendered fallback count was zero. Tester visual review passed 12 first/middle/final samples. Access metrics recorded 2,426 requests, zero 403/429/challenge/CAPTCHA events, and CLI-reported retries 0. Quota-resource count remained zero and quota/grant state remained unchanged.
The prior 122-page logged-out PNG run remains historical fallback evidence, not native proof. The initial discovery/preflight failures and an ignored Tester slot-attribution mismatch are recorded in `runbooks/hanayume-free/PROGRESS.md`; each was followed by a bounded fix or evidence correction before the final passing run.
Limits: no original JPEG bytes or DCT coefficient reconstruction is claimed. The observed display canvas was 828x1329 (CSS 552x886, DPR 1.5); native capture avoids that resize. The tested 385px tile height rejected the specific MCU-8 DCT permutation. The historical rendered-PNG fallback has since been removed; current variable-size capture requires verified native proof or stops. A ready Viewer overlapping a login/paid-entry dialog and universal overlay detection remain unverified.
Final independent review PASS / BLOCKING 0.

## R7 leading-empty failure evidence (historical cause checkpoint; implementation is described below)

The later user Batch failure for item/source `25036` maps to episode `c8904d8e3f912` in work `1f9f5b0d4cd52`. Three saved diagnostic directories under `output/batch/hanayume/item-25036-source-25036-*` have sibling `diagnostics/page.html` snapshots showing the same initial state: counter `1/17`, 18 wrappers, and wrapper slot 1 with classes `-cv-page mode-empty`, no canvas, and a 946x886 inline box. The sibling `diagnostics/metadata.json` files record `captured_body_slots=0` and `body_total=null`; they do not contain the wrapper/class snapshot. The error is `Hanayume body slot has an unknown state class`. The parser treats indices 1 through 12 as body slots and rejects `mode-empty` before active/ready checks. The saved screenshot visibly identifies a top empty lead-in (“次のページから始まります”) beside a volume-promotion panel.

A single guarded metadata-only probe passed the existing same-work free preflight: the exact target row was `今なら無料` and authentication was verified on the canonical series listing. No reader control, capture, image readback, purchase, quota, ticket, or grant action occurred. Snapshots were scheduled at offsets 0, 150, 500, 1500, and 3000 ms; actual elapsed offsets were 0, 182, 548, 1534, and 3032 ms. Slot 1 remained `mode-empty`, had no canvas, and was centered in the viewport throughout; the viewer retained `mode-first-page` and `mode-has-top-emptypage`. Slots 2 and 3 changed from offscreen `mode-loading mode-req-render` placeholders to offscreen `mode-loaded mode-rendered` canvases (828x1329) by actual elapsed 548 ms. This is bounded evidence of a stable empty lead-in for this episode, not a claim that every `mode-empty` slot has the same role.

The live seek property was min 1, max 17, step 2, value 17 while the counter was 1/17; the saved HTML `value` attribute was 1. The strict viewer parser still stops at slot 1 before capture or END. No general skip or body-count adjustment is justified without proving the page-to-counter mapping and terminal coverage. The previous four-episode/134-page PASS applies only to those verified targets/layouts and does not cover this episode.

Evidence: `output/hanayume_experiment/tester/runs/r7-first-slot-20261011T000424Z-fd0e6310/probe_report.json` and the ignored probe `output/hanayume_experiment/tester/r7_first_slot_metadata_probe.py`. The user Batch metrics contained 445 requests (443 HTTP 200, 2 HTTP 204), one failed candidate, and CLI retry count 0; the probe observed no 403/429/challenge/CAPTCHA. At this checkpoint no production or test files had changed; R8 below supersedes the no-fix status.

## Fractional destination draw dimensions (2026-10-19)

User metrics run `ad9622c2079f48ba8846a8767001dc33` failed for Item/Source 27945,
episode `a087973196a9d` (`第10翼②`), before saving a page. Its failure metadata records
ready physical slots 2/3, native sources 960x1364 (inside the supported bounds), display bitmaps
934x1329, and `native_candidate_missing_or_stale`. The one-second initial quiet interval completed;
the metrics have zero HTTP 403/429/5xx, challenge, CAPTCHA, or retry events.

The bounded shared-CDP draw probe `output/hanayume-draw-probe-20261019/report.json` reproduced
the failure. Its observed drawImage rectangle is `[0,0,960,1364,0,0,934.5,1329]` into a
934x1329 target, with identity transform, alpha 1, source-over, no filter/shadow/clip, and
sRGB/unorm8 source/target contexts. The former integer-only, exact-target-size rectangle check
excluded this draw before snapshot creation. This is a distinct cause from the historical
initial-reset race and fixed-source-dimension failures above.

The observer now accepts finite destination width/height only when their floors equal the
positive, bounded target bitmap dimensions. This permits the observed subpixel overhang but
rejects underfill, a whole-pixel overhang, source crops, nonzero origins, and nonfinite sizes.
Source dimensions and the entire source rectangle remain exact. Each candidate retains all
eight actual draw arguments. Replay uses them unchanged rather than substituting integer target
dimensions, preserving exact full-display RGBA comparison. Native opacity, immutable draw-time
snapshot, paint/context, episode/slot, generation/write, cache/memory bounds, all-or-none spread,
post-encoding proof, and no-rendered-fallback rules remain in force. Output remains native-size
lossless WebP, or the same verified native PNG on codec failure. No CLI/config change is needed.

Live evidence: `output/hanayume-fractional-live-20261019/report.json`, generated by the adjacent
ignored Python verification script. A direct Runner run on the affected active grant reached
END with nine 960x1364 lossless WebP pages; ordinary free control Source 25326,
episode `90868f4de278f`, reached END with twelve 960x1540 lossless WebP pages. A separate
document-start draw hook copied the full source before production observation; all 21 decoded
outputs matched those independent snapshots in every RGBA byte before advance. This proves
decoded source-canvas equality, not original JPEG byte preservation. Both Pages blocked mutating
requests, attempted zero checkout requests, and reported no resource consumption. Only owned
Pages were closed. The normal Catalog, Item status, and existing archives were not written.
This verification used Runner; standard Batch orchestration and packaging were not rerun live.

Synthetic browser coverage uses patterned mutable sources to check fractional width, height,
and combined subpixel overhangs, native dimensions, and exact source RGBA after the source is
cleared. Negative cases retain strict failure for underfill, whole-pixel overhang, crop, offset,
and nonfinite geometry. The complete affected suite passed 244 cases, 0 failed/skipped/deselected
(284 existing pytest-asyncio deprecation warnings; 91.02 seconds):
`tests/unit/test_hanayume_adapter.py`, `tests/unit/test_hanayume_native_capture.py`, and
`tests/integration/test_hanayume_adapter_browser.py`. Command: `.venv/Scripts/python.exe -m pytest
-q -p no:cacheprovider --basetemp output/hanayume-fractional-pytest-20261019 <the three files>`.
The initial run had nine tmp_path setup errors because the default
`AppData/Local/Temp/pytest-of-kensu` directory was inaccessible; the explicit isolated workspace
base temp resolved them without fixture or production changes. The first focused geometry run
passed 8 cases (124 unrelated cases deselected). `ruff check src tests` and changed-file
`git diff --check` passed. The full repository suite and Research/Probe helper tests were not
run because the production change is limited to Hanayume draw geometry/replay, with its complete
adapter/native Unit and browser-backed Integration contracts covered. Shared Core, Discovery,
Batch orchestration, access policy, and their notes are unchanged.

## R8 top-empty layout implementation (implementation review PASS / BLOCKING 0; artifact audit PASS / BLOCKING 0)

The bounded mapping probe `output/hanayume_experiment/tester/runs/r8-topempty-mapping-20261011T001336Z-a1f9f190/probe_report.json` used one fresh exact-target/authenticated preflight and metadata-only observations. At counter 1/17, the viewer had `mode-has-top-emptypage` and `mode-first-page`; slot 1 was exactly `-cv-page mode-empty`, centered, and canvas-free. The top-empty marker remained present at counters 1 through 17; `mode-first-page` appeared only at counter 1 and the terminal marker only at 17. The public seek property was 17 at counter 1; eight ordinary step-2 seek changes reached counters 3 through 17. Body candidates 2 through 12 were active and ready exactly once across counters 3 through 13; counter 15 showed promotional slots and counter 17 showed the known terminal tail. No pixels or image bytes were read. The probe observed no 403/429/challenge/CAPTCHA.

Production derives and freezes an explicit physical `body_slots` tuple using `last_slot = wrapper_count - 1` and the exact validated CI position: normal layout starts at 1; the narrowly flagged layout starts at 2; both end immediately before CI. The physical tail must be exactly CI, two or three PR wrappers, good, last. For two PR wrappers the final body slot remains `last_slot-5`; for three it is `last_slot-6`. Both Python and native collection/post-encoding proof enforce this tail. For the R8 layouts `last_slot == total`, so their bounds and identity numbering remain unchanged. It accepts the leading blank only with the exact viewer flag, exact slot-1 class set, and zero canvas; `mode-first-page` is required for the initial counter-1 intro, followed by one public seek to the ready counter-3 spread. Capture identity, sequential body coverage, END, and native proof use physical slots. Synthetic browser tests cover top-empty success, missing first marker, failed initial seek, interior empty state, layout drift before/after native encoding, missing spread side, and premature END. Two R8 standard CLI E2E cases passed; see the R8 live verification below and the newer wrapper-variant verification above.

### Three-PR tail correction (2026-10-21)

Source 36494, episode `3a165f3a11574` (`おまけ.鍵とお嬢`), failed before
capture with `Hanayume body slot has an unknown state class`. Its saved
diagnostic has 11 counters and 11 wrappers: top PR 0, exact flagged blank 1,
body 2–4, CI 5, PR 6–8, good 9, last 10. The previous fixed five-slot tail
misclassified CI 5 as body. This was a viewer layout issue, independent of
Discovery access classification and recrawl Item status.

The adapter now recognizes the exact CI marker at either observed tail
position, validates the entire two/three-PR suffix, and derives body slots
before CI. It does not skip arbitrary PR/empty/unknown body slots. Native
capture uses the same bound at collection and after encoding. Sequential
coverage, frozen body slots, empty-lead-in proof, active spread checks,
no rendered fallback, and full-coverage END remain required. No configuration,
CLI, output format, shared Core, Discovery, or Batch policy change is needed.

Live verification used the shared CDP BrowserSession with serial owned Pages
and first-party mutations blocked. The affected episode saved exactly three
960x1508 WebP pages (body 2–4) at END. Ordinary two-PR control Source 25326,
episode `90868f4de278f`, saved twelve 960x1540 WebP pages at END. Both isolated
ZIPs passed CRC, manifest order/member count, and full image decode checks.
Checkout attempts were zero and adapter consumption was false. Read/readCompleted
and mission POSTs were blocked. Normal Catalog access was read only, so the
pending Item and normal archive were not updated. Evidence and the adjacent
verification script: `output/hanayume-tail-live-20261021/report.json`. This
was Runner plus standard packaging; normal Batch orchestration was not rerun.
Independent source-canvas RGBA comparison was not measured in this live run.

Regression coverage extends the existing top-empty parser/capture-to-END and
post-encoding drift tests for the observed three-PR shape. Additional parser
cases reject changed body/CI/each PR/good/last classes. The focused 20-case
Unit/Integration run passed with zero skips. The complete affected suite
(`tests/unit/test_hanayume_adapter.py`, `tests/unit/test_hanayume_native_capture.py`,
`tests/integration/test_hanayume_adapter_browser.py`) passed 255 tests,
0 failed/skipped/deselected, 284 existing pytest-asyncio deprecation warnings,
100.00 seconds. Command: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
--basetemp output/hanayume-tail-affected-r2-20261021 <the three files>`.
The first affected run passed 253 and failed two existing 0.4-second initialization
timing assertions (actual 0.494/0.465 seconds); the expected immediate exceptions
were correct. Both passed an isolated rerun, then the entire suite passed
without changes to production timeouts or test timing limits. The initial new
fixture had a stale seek maximum of 9 for the 11-counter variant; correcting
the fixture resolved that focused failure. `ruff check src tests` and changed-file
`git diff --check` passed. Full repository and Research/Probe suites were not
run because only Hanayume viewer/native layout changed; relevant browser
Integration and bounded live verification were completed. No shared/site-other
note update is needed.

R8 post-fix standard CLI E2E and independent artifact audit (2026-10-11)

The Tester summary is `output/hanayume_experiment/tester/runs/r8-standard-summary-20261011T003109Z-1e6a033f/tester_report.json`. Two separate isolated Catalogs each ran fresh standard Discovery for one Watchlist target and standard CLI Batch with `--limit 1`; no Catalog backup, user Catalog, in-process observer, timing hook, or CLI retry was used. Case artifacts are under `r8-standard-topempty-20261011T002945Z-f731eae9/` and `r8-standard-ordinary-20261011T003026Z-ba275b57/`.

Episode `c8904d8e3f912` completed 11 physical body pages; ordinary-layout control `90868f4de278f` completed 12. Both runs reached END, succeeded, completed their isolated Catalog Items, and produced present ZIP Artifacts with verified CRC, member order, member hashes/sizes, and whole-ZIP hash/size. Read-only SQLite audit passed. All 23 output members were 960x1540 single-chunk VP8L lossless WebP. Six independent visual samples (first/middle/final for both episodes) passed. The standard capture gate completed, but `capture_mode` was not persisted and the Tester did not independently compare source-canvas RGBA for these 23 pages; exact source-pixel equality is therefore not claimed here. This differs from the prior 134-page E2E, which had independent RGBA proof.

The two metric summaries recorded 610 and 448 requests, respectively, with zero 403, 429, or 5xx responses and zero CLI-reported retries. Aggregate `batch_summary` counters reported zero challenge/CAPTCHA events; this does not prove detection of every possible challenge UI. Quota-resource states were zero and no grant timestamps or entitlement changes were found. Independent read-only audit confirmed ZIP/member hashes and sizes, CRC/order, SQLite integrity, exact target eligibility, END/page counts, completed items, and present Artifacts: PASS / BLOCKING 0. Final documentation review: PASS / BLOCKING 0.

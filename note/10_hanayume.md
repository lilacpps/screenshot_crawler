# Hanayume current implementation

Updated: 2026-10-17. Phases 01-03 Work Ticket implementation passed independent review. Phase 04 site-local Next-route containment and the current-episode proof passed their material review gates. The pre-guard full-repository snapshot at `1256d3b` had 3718 passed and two failures outside Hanayume: the Kadocomi test-only fixture repair passed its focused validation; the Younganimal cause remains unknown. The earlier two Hanayume broad-run failures were not reproduced and their cause remains unknown. Stage 5ca6372 live serial Batch validation passed on the existing-grant `49b7e11049871` and free `8c6` works; the abort-error-code follow-up passed independent review. A read-only current-episode API transport probe on existing-grant 49b confirmed the exact endpoint and positive access schema. The first final affected Hanayume run reported 332 passed and one failure because its synthetic fixture left the current-episode fallback false after a successful checkout. A fixture-only correction now models the grant and delays that truthful current response only in the delayed-body case; the focused family passed 12 cases with no production change. The final five-file affected Hanayume suite then passed 333 tests with zero failures, skips, or deselections (306 pytest-asyncio warnings; 459.91s); the full console is recorded in the Work Ticket progress log. Consuming normal Batch / grant-only workflow audits remain pending. No new ticket was consumed. Earlier direct Batch and R9 live evidence remains historical below.

## Registration and browser use

`HanayumeDiscoveryAdapter` is registered in the CLI Discovery registry. `HanayumeAdapter` is registered in the manual Viewer and Batch adapter registries; `HanayumeSitePolicy` is registered in the Batch policy registry. All paths use the shared Crawler Chrome through the existing CDP `BrowserSession` and Playwright `Page`; none launches Chrome or selects a profile. Discovery writes through the existing `DiscoveryService` and Catalog schema. Batch uses the existing Planner/Executor/Runner/Packager; no site-specific Core branch or Catalog schema was added.

The strict Watchlist episode URL is `https://hanayume.com/episodes/<13-lowercase-hex-id>`. Episode IDs are paired with the work ID from the unique `#xHeader a.ep-h-main-h-series` link. Episode pages use `div.ep-main.series-safe-filter-target[data-e2e="pageEpisode"] > div.series.mode-ep` (the inner `.series` has no `data-e2e`) > `.series-eplist-wrap` > direct `.series-eplist-main`. Canonical series routes use `div.series.mode-series-top.series-safe-filter-target[data-e2e="pageSeries"]` as the wrapper parent. Both require a unique public `epList` direct under main; `eli` rows are descendants within `.series-eplist-default.has-store-item.mode-last`. The header work link is outside the episode-list subtree. Global series links are not used because related works appear on the page.

## Enumeration and ordering

The observed listing declares ten contiguous oldest-first ranges, from `1-30` through `271-296`. Discovery reads the whole declared range set, then navigates each numbered route once with finite navigation, DOM, and observation timeouts plus bounded 350 ms inter-range pacing. Every page must return HTTP 200 at the exact requested route, preserve its work identity and full range set, and expose one selected marker whose exact label matches the range. The actual page URL must equal the declared route. Live evidence showed the active selected anchor points to the seed episode path on all ten ranges; only that unique selected anchor may use this exact seed alias. All nonselected range links must retain their exact numbered paths.

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

The reader contract remains the observed desktop `mode-spread` layout. Viewer counters and `#xCVPages` wrappers are checked together, active slots must be structurally valid and fully visible, and capture proceeds in contiguous page order. The selected canvas is read atomically and PNG output uses its actual dimensions. Only after every body slot is captured does the observed terminal state produce END; the adapter never follows a next-episode card. Site-local hooks prevent generic locator/UI screenshot fallback.

For the R8-probed leading-empty layout, `mode-has-top-emptypage` must be present and physical slot 1 must be exactly `-cv-page mode-empty` with no canvas. That slot is excluded from the body; physical body slots are frozen as 2 through `total-5`, giving 11 body pages for the observed 17-page episode. The initial counter-1 state must also contain `mode-first-page`; the adapter uses one normal public seek step to counter 3, then captures body slots 2/3 onward. The top-empty flag, exact blank lead-in, and body-slot tuple remain bound through native collection and verification. Unflagged blanks, interior empty slots, changed layout, missing spread sides, or incomplete terminal coverage fail closed. Archive capture order is sequential while identities retain physical slot IDs.

### Supported counter/physical-wrapper variant: episode `e2a7ca7bd6dd7`

Investigation on 2026-10-11 reproduced the normal Batch failure for Item/Source `25142` (`番外編 食の都③`). The failing metrics run `4082ffbbf88447dca0c2032c5562bf51` stopped after 1.946 seconds with `Hanayume viewer page-wrapper count is incomplete`; its summary records no HTTP 403/429/5xx, challenge, or CAPTCHA event. Two bounded fresh-page CDP metadata probes reproduced a stable counter `1/17` with **17 physical wrappers**, rather than the former parser's required `total + 1 = 18`. The first probe retained that shape through 8.671 seconds, excluding a short initialization delay as the explanation for the observed mismatch.

There is no `mode-has-top-emptypage` flag: slot 1 is rendered body, slots 1–11 precede `mode-ci` at 12, PR placeholders at 13/14, `mode-good` at 15, and `mode-last` at 16. Every trailing role is one physical slot earlier than the former `total`-based contract. A normal public seek `Home` produced counter `17/17`, seek value 1, and `mode-last-page` with the same 17 wrappers. The probe rewound to counter 1 and closed only its own page. The metadata probe alone did not establish captured coverage; the subsequent standard Batch verification below did. The viewer's internal rounding/padding algorithm remains unproven and is not used as an implementation assumption.

Current behavior accepts the existing `wrapper_count == total + 1` layout, and additionally the observed `wrapper_count == total` variant only for an odd total without the top-empty flag. Let `last_slot = wrapper_count - 1`. Both variants require the exact top PR and five-tail structure relative to `last_slot`; unknown/missing/shifted tail classes fail closed. Body slots are frozen from 1 (or 2 for the existing flagged leading blank) through `last_slot - 5`. The public counter/seek validation remains unchanged. For the affected target this yields exactly physical slots 1–11, rather than incorrectly treating slot 12 (`mode-ci`) as body.

Native collect and post-encode verification independently validate this physical tail and exact body tuple. Proofs also retain the wrapper count; count/tail/flag drift rejects the capture, with no generic screenshot fallback. Existing leading-empty support is unchanged and does not admit the shorter wrapper variant. Synthetic tests cover the 17-counter/17-wrapper observation, complete native capture to END, rejected tail/count/flag changes, missing spread halves, and premature END alongside the prior layouts.

Probe evidence: `output/hanayume-wrapper-investigation-20261011.json`; bounded metadata probe: `output/hanayume_wrapper_probe.py`. Post-fix standard CLI Batch evidence: `output/hanayume-wrapper-live-20261011-bc7bbdb0/verification.json`, prepared/audited by `output/hanayume_wrapper_live_verify.py`. The affected target completed 11 pages, ordinary control `90868f4de278f` completed 12, and leading-empty control `c8904d8e3f912` completed 11; all reached END, completed their isolated Items, and created present ZIP Artifacts. All 34 members decoded as 960x1540 VP8L WebP; ZIP CRC, sequential member names, whole-archive size/SHA-256, SQLite integrity, and crawl-status page counts passed. Packaging removed generated source directories as designed. The initial audit incorrectly expected retained manifests; its correction audited the existing completed target ZIP without repeating that crawl. No independent source-canvas RGBA comparison or visual review was performed for these 34 pages, and those historical 134-page proofs are not extended by this run.

Each live case used a dedicated Catalog/output/library and working directory (including metrics). Exact available/free source, target, work, and item metadata were copied from the explicitly selected normal Catalog through a read-only connection; only the isolated retry Item was set pending. The normal Catalog, including the affected Item's existing skipped status, was not written. Access eligibility, pacing, CLI, and max-pages/same-content safeguards did not change. Adapter/native Unit + viewer browser Integration: 115 passed, 0 skipped; Discovery/policy Unit + Discovery browser Integration: 69 passed, 0 skipped (184 total). Ruff (`src tests`) and diff checks passed. All three live metrics summaries recorded zero HTTP 403/429/5xx and zero retries. Full suite was not run because this is confined to the Hanayume viewer/native layout contract; research-helper tests were not needed for production acceptance.

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
If the source observer is unavailable or fails its integrity check, the existing rendered-PNG
fallback remains available after the same quiet interval using visible metadata only. Diagnostics
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
at the deadline. They also preserve observer-missing rendered-PNG fallback. Existing post-encode
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

`HanayumeSitePolicy` admits available `free` sources as direct, available `quota` sources with a future `access_granted_until` as non-consuming direct, and other eligible `quota` sources as one `work_ticket` candidate scoped to `work` with `quota_limit=1` and `after_observed_consumption`. It declares the same resource for grant-only. The local work-ticket recovery check is at least 23 hours; caller configuration may lengthen it but cannot shorten it. Batch uses only the selected Catalog episode URL and validates the exact work/episode, target-local hydrated `epListUser` root, native eligibility, and unique enabled free-reading control under the observed central charge ancestry. Ordinarily the target account-preview row is present and must show a known blank/read state. If both unique, nonempty public and account previews are structurally valid but omit the selected episode, the same-page exact `/api/episodes/<episode-id>` response must match `episode.id`, `episode.series.id`, and `episode.access.episodeId` to the selected Catalog work/episode, with strictly typed `hasAccess`, `accessType`, and bounded `timeRemainingInSeconds`. This exact current-episode proof is required to establish an ungranted prestate in both the initial and final pre-click snapshots when the target is absent; a series-level false row alone cannot authorize a click. Duplicate/malformed rows, another `mode-current` row, and any present contradiction still fail closed. The exact visible/enabled free-reading control remains mandatory before one click.

Native consumption confirmation requires a same-page checkout `POST /api/checkout/rental` HTTP 200 after the attempted click plus fresh exact grant evidence. When both previews omit the target, that evidence must be a current-episode `waitAndFree` transition from `hasAccess=false` to `true`, with positive bounded remaining time and all three current endpoint IDs matching the Catalog work/episode. When a target account-preview row is present, the existing stricter series-level positive response plus the exact `mode-read`/rental-history proof remains supported. Current and series snapshots are ordered by request-start, and equal-time conflicts fail closed; a present blank row remains contradictory. For absent-preview confirmation, a fresh current-episode 3-ID positive proof remains valid when a later-started series response also confirms active `waitAndFree`; both must report `hasAccess=true` and strictly positive bounded remaining time. Countdown values may differ naturally, so the grant expiry is the earlier of the two request-start plus `remainingSeconds - 1` expiries. A newer denial, paid/unknown state, invalid remaining value, or differing entitlement state fails closed, and a fallback read cannot override that contradiction. If the natural current response is missing or the newest native state still explicitly reports `hasAccess=false`, the same Page may make at most two exact read-only GETs within one attempt-scoped five-second recovery deadline. That budget does not reset on exception-path reentry; no navigation or ticket retry occurs. Confirmation time anchors the 23-hour work cooldown. The source grant uses the conservative native expiry, capped by the policy fallback at confirmation plus 72 hours. An invalid native expiry does not erase confirmed consumption: the generic executor records the policy fallback when possible, then reports the metadata error. Normal Batch continues in the same Page through Viewer capture, END, and ZIP; grant-only validates same-page Viewer readiness with zero CONTENT page captures, zero ZIP, and no completion. A failing grant-only or normal candidate may still emit a generic UI screenshot diagnostic. A configured direct candidate fails closed on the exact observed central Work Ticket/login gate during initialization and again at each Viewer CONTENT state, before capture; ordinary free direct and anonymous free paths remain supported. Manual Discovery grants remain target-local and do not invent work cooldowns. Unknown, paid, owned, and rental remain ineligible. No Catalog schema or site-specific Core branch was added; `AccessConsumption` carries an optional generic native expiry. For identity-bound configured Batch, `configure_run` installs a Page route guard before the selected episode `goto`; manual entry and Discovery are unaffected. It passes the exact selected canonical episode document and selected-page RSC, and leaves API/static/image content routes outside the guarded `/episodes/*` and `/series/*` families untouched. It aborts only a known nonselected route-data request matching the observed HTTPS/allowed-host, no-userinfo/default-port, GET, single nonempty `_rsc`, `rsc: 1`, `fetch`/`other`, optional `next-router-prefetch: 1` shape and a 13-lowercase-hex episode/work path with an observed range-number or `old` suffix. This conservative signature identifies route data but does not claim every such request is a Next prefetch. Unknown IDs/suffixes, malformed signatures, off-target documents, non-GET requests, or other unrecognized episode/work routes are aborted and latch fatal before ticket click/capture. A response from any off-target episode/work route increments a distinct escaped-response counter and latches fatal. Audit metadata contains only counters and a fixed reason code; it omits request URLs/query values. Stage 5ca6372 live serial validation used the already-granted `49b7e11049871` (30 PNG pages, 925x1329) and free `8c6` work (VP8L); both reached END and passed ZIP audit, with zero checkout and no work quota consumption. Page A closed before Page B opened. Two observed off-target RSC attempts in that run were blocked with Chromium's default `ERR_FAILED`; the new explicit `blockedbyclient` error code is now covered by synthetic tests, which report `net::ERR_BLOCKED_BY_CLIENT.Inspector` and zero off-target responses. The bounded post-commit live error-code re-audit passed with zero off-target responses; no additional ticket was used. Consuming normal-Batch and grant-only Work Ticket live audits remain pending.


The document-start source observer copies an observed opaque sRGB/unorm8 960x1540 full-frame canvas into a bounded cache of up to eight candidates (about 47.3 MB). Exact target, wrapper/slot, generation/write/dimensions, safe geometry/context, and same-episode provenance must remain valid. Validated native pixels are encoded as strict single-chunk VP8L lossless WebP method 4 only after full RGBA round-trip validation; encoder failure returns the same verified source PNG. Missing or unsafe native proof uses clean rendered-canvas PNG for the whole spread at actual dimensions. The final live run verified all 134 pages as native WebP with exact independent RGBA equality and zero fallback. This is decoded source-canvas fidelity, not original JPEG bytes or tile reconstruction.

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
The independent review of the current-episode fallback fix passed with zero blockers. The fixture-only delayed-body correction passed its focused family and the final five-file affected suite (333 passed, 0 failed, 0 skipped/deselected; 306 pytest-asyncio warnings; 459.91s). Consuming normal Batch and grant-only Work Ticket live audits remain pending. Exact debit/recovery counters remain unknown.

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
Limits: no original JPEG bytes or DCT coefficient reconstruction is claimed. The observed display canvas was 828x1329 (CSS 552x886, DPR 1.5); native capture avoids that resize. The tested 385px tile height rejected the specific MCU-8 DCT permutation. Other works/native dimensions can use whole-spread rendered PNG fallback. A ready Viewer overlapping a login/paid-entry dialog and universal overlay detection remain unverified.
Final independent review PASS / BLOCKING 0.

## R7 leading-empty failure evidence (historical cause checkpoint; implementation is described below)

The later user Batch failure for item/source `25036` maps to episode `c8904d8e3f912` in work `1f9f5b0d4cd52`. Three saved diagnostic directories under `output/batch/hanayume/item-25036-source-25036-*` have sibling `diagnostics/page.html` snapshots showing the same initial state: counter `1/17`, 18 wrappers, and wrapper slot 1 with classes `-cv-page mode-empty`, no canvas, and a 946x886 inline box. The sibling `diagnostics/metadata.json` files record `captured_body_slots=0` and `body_total=null`; they do not contain the wrapper/class snapshot. The error is `Hanayume body slot has an unknown state class`. The parser treats indices 1 through 12 as body slots and rejects `mode-empty` before active/ready checks. The saved screenshot visibly identifies a top empty lead-in (“次のページから始まります”) beside a volume-promotion panel.

A single guarded metadata-only probe passed the existing same-work free preflight: the exact target row was `今なら無料` and authentication was verified on the canonical series listing. No reader control, capture, image readback, purchase, quota, ticket, or grant action occurred. Snapshots were scheduled at offsets 0, 150, 500, 1500, and 3000 ms; actual elapsed offsets were 0, 182, 548, 1534, and 3032 ms. Slot 1 remained `mode-empty`, had no canvas, and was centered in the viewport throughout; the viewer retained `mode-first-page` and `mode-has-top-emptypage`. Slots 2 and 3 changed from offscreen `mode-loading mode-req-render` placeholders to offscreen `mode-loaded mode-rendered` canvases (828x1329) by actual elapsed 548 ms. This is bounded evidence of a stable empty lead-in for this episode, not a claim that every `mode-empty` slot has the same role.

The live seek property was min 1, max 17, step 2, value 17 while the counter was 1/17; the saved HTML `value` attribute was 1. The strict viewer parser still stops at slot 1 before capture or END. No general skip or body-count adjustment is justified without proving the page-to-counter mapping and terminal coverage. The previous four-episode/134-page PASS applies only to those verified targets/layouts and does not cover this episode.

Evidence: `output/hanayume_experiment/tester/runs/r7-first-slot-20261011T000424Z-fd0e6310/probe_report.json` and the ignored probe `output/hanayume_experiment/tester/r7_first_slot_metadata_probe.py`. The user Batch metrics contained 445 requests (443 HTTP 200, 2 HTTP 204), one failed candidate, and CLI retry count 0; the probe observed no 403/429/challenge/CAPTCHA. At this checkpoint no production or test files had changed; R8 below supersedes the no-fix status.

## R8 top-empty layout implementation (implementation review PASS / BLOCKING 0; artifact audit PASS / BLOCKING 0)

The bounded mapping probe `output/hanayume_experiment/tester/runs/r8-topempty-mapping-20261011T001336Z-a1f9f190/probe_report.json` used one fresh exact-target/authenticated preflight and metadata-only observations. At counter 1/17, the viewer had `mode-has-top-emptypage` and `mode-first-page`; slot 1 was exactly `-cv-page mode-empty`, centered, and canvas-free. The top-empty marker remained present at counters 1 through 17; `mode-first-page` appeared only at counter 1 and the terminal marker only at 17. The public seek property was 17 at counter 1; eight ordinary step-2 seek changes reached counters 3 through 17. Body candidates 2 through 12 were active and ready exactly once across counters 3 through 13; counter 15 showed promotional slots and counter 17 showed the known terminal tail. No pixels or image bytes were read. The probe observed no 403/429/challenge/CAPTCHA.

Production derives and freezes an explicit physical `body_slots` tuple using `last_slot = wrapper_count - 1`: normal layout 1 through `last_slot-5`; the narrowly flagged layout 2 through `last_slot-5`. For the R8 layouts `last_slot == total`, so their bounds and identity numbering remain unchanged. It accepts the leading blank only with the exact viewer flag, exact slot-1 class set, and zero canvas; `mode-first-page` is required for the initial counter-1 intro, followed by one public seek to the ready counter-3 spread. Capture identity, sequential body coverage, END, and native proof use physical slots. Synthetic browser tests cover top-empty success, missing first marker, failed initial seek, interior empty state, layout drift before/after native encoding, missing spread side, and premature END. Two R8 standard CLI E2E cases passed; see the R8 live verification below and the newer wrapper-variant verification above.

R8 post-fix standard CLI E2E and independent artifact audit (2026-10-11)

The Tester summary is `output/hanayume_experiment/tester/runs/r8-standard-summary-20261011T003109Z-1e6a033f/tester_report.json`. Two separate isolated Catalogs each ran fresh standard Discovery for one Watchlist target and standard CLI Batch with `--limit 1`; no Catalog backup, user Catalog, in-process observer, timing hook, or CLI retry was used. Case artifacts are under `r8-standard-topempty-20261011T002945Z-f731eae9/` and `r8-standard-ordinary-20261011T003026Z-ba275b57/`.

Episode `c8904d8e3f912` completed 11 physical body pages; ordinary-layout control `90868f4de278f` completed 12. Both runs reached END, succeeded, completed their isolated Catalog Items, and produced present ZIP Artifacts with verified CRC, member order, member hashes/sizes, and whole-ZIP hash/size. Read-only SQLite audit passed. All 23 output members were 960x1540 single-chunk VP8L lossless WebP. Six independent visual samples (first/middle/final for both episodes) passed. The standard capture gate completed, but `capture_mode` was not persisted and the Tester did not independently compare source-canvas RGBA for these 23 pages; exact source-pixel equality is therefore not claimed here. This differs from the prior 134-page E2E, which had independent RGBA proof.

The two metric summaries recorded 610 and 448 requests, respectively, with zero 403, 429, or 5xx responses and zero CLI-reported retries. Aggregate `batch_summary` counters reported zero challenge/CAPTCHA events; this does not prove detection of every possible challenge UI. Quota-resource states were zero and no grant timestamps or entitlement changes were found. Independent read-only audit confirmed ZIP/member hashes and sizes, CRC/order, SQLite integrity, exact target eligibility, END/page counts, completed items, and present Artifacts: PASS / BLOCKING 0. Final documentation review: PASS / BLOCKING 0.

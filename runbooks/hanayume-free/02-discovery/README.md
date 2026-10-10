# Phase 02 — Discovery / Catalog

Status: Phase 02 and the later R4/R5 corrections passed independent review. Fresh full Discovery validated all 296 unique global positions and the final authenticated E2E confirmed 3 exact `無料` plus 293 exact `今なら無料` rows classified free under a verified same-work series listing; standard inclusive scope yielded four records. Missing or ambiguous auth still leaves `今なら無料` unknown.

## Scope and observed authority

Discovery starts from the strict episode URL `https://hanayume.com/episodes/<13-hex-id>`. The target work is identified by the unique `#xHeader a.ep-h-main-h-series` link, outside the listing subtree. Episode pages use `div.ep-main.series-safe-filter-target[data-e2e="pageEpisode"] > div.series.mode-ep` (the child `.series.mode-ep` has no `data-e2e`) > `.series-eplist-wrap` > direct `.series-eplist-main`; canonical work pages instead use `div.series.mode-series-top.series-safe-filter-target[data-e2e="pageSeries"]` as the listing wrapper parent. The unique public `epList` is a direct child of the main root; rows are descendants inside the observed `.series-eplist-default.has-store-item.mode-last` container. `epListUser` is a known direct history sibling and is never enumerated. R4 fixtures mirror both route-specific structures. Global series links are not a work authority because related works also appear on the page. The observed range navigation contains ten contiguous oldest-first ranges (`1-30` through `271-296`), with requested routes `/episodes/<seed-id>/<ordinal>`. The selected anchor alias and all other range links remain subject to the existing exact route validation.

Each declared range is fetched once with finite navigation/DOM/observation timeouts and bounded pacing. Discovery checks the current range label and exact actual page URL, the unchanged complete range set, the same work identity, exact row counts, unique episode IDs, and presence of the seed. A missing row, duplicate ID, foreign work link, redirect, incomplete range, or AccessGuard stop fails closed. The loader is not used as a completion signal.

All ranges are buffered and validated before the adapter yields its first record, for both full and incremental modes. Native row titles stay separate from list position, so split episodes remain distinct. Global positions are assigned in the observed oldest-first order; records are then yielded latest-first. Inclusive bounded scope is applied only after complete validation and retains the original global positions.

## Access classification

Classification reads exact access badges inside each episode row. One exact `無料` badge maps to `access_mode=free`. One exact `今なら無料` badge maps to `free` only when the current attempt proves the complete observed authentication marker set on the canonical same-work series route; otherwise it remains `unknown`. On an exact route and listing, auth evaluation polls for that positive set at 150 ms intervals for at most five seconds. Route/listing drift fails immediately, and timeout means authentication was not proven, not that logout was established. Missing, duplicate, conflicting, or any other badge state maps to `unknown`.

The current Catalog schema stores only `access_mode`; the raw Japanese badge is used by the site-local classifier and tests and is not persisted in Catalog, title, order, or work key. Discovery includes all observed rows; only records classified `free` are eligible for later Batch work. Authentication remains attempt-local. The original logged-out baseline kept `今なら無料` unknown. No login, registration, entitlement, ticket, purchase, or quota action is performed by the adapter.

## Implementation and verification

- Site-local adapter: `src/screenshot_crawler/site_adapters/hanayume/`.
- CLI registration: Discovery registry only. No site-specific Core, Catalog schema, Batch registry, viewer, or other-adapter changes were made. One narrowly scoped shared AccessGuard cancellation fix is recorded in the Core note.
- Tests: `tests/unit/test_hanayume_discovery.py`, `tests/integration/test_hanayume_discovery_browser.py`, `tests/unit/test_access_guard.py`, `tests/integration/test_access_guard_browser.py`, and the CLI registry test cover strict URL/work identity, exact labels and conflicts, range completeness/drift, selected-alias and actual-URL checks, global positions, bounded scope, Catalog preservation, access stops, and guard cancellation.
- Targeted verification passed: 46 unit/browser tests across Hanayume Discovery, AccessGuard, CLI registration, and the local Discovery integration; 0 skipped. Full `ruff check src tests` passed.
- Isolated live CLI full Discovery passed: 296 observed/new, complete `True`, stopped `exhausted`. Catalog audit found 296 unique work-scoped sources, positions 1-296, with 3 `free` and 293 `unknown`.
- Isolated live CLI incremental Discovery passed: 5 observed/known, complete `None`, stopped `known_streak`; the adapter validates and buffers all ten ranges before yielding those records.
- Isolated live CLI bounded Discovery passed: 3 observed/new, complete `True`, stopped `exhausted`; Catalog audit returned latest-first global positions `[3, 2, 1]`.
- All live runs used only `output/hanayume_experiment/` Watchlists/Catalogs. No normal Catalog or output fallback was used.
- Independent Phase 02 reviewer: PASS / BLOCKING 0. Lead authorized Phase 03-A bounded probe; production viewer/capture implementation remains gated on evidence and a Lead contract.

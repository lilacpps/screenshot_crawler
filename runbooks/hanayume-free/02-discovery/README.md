# Phase 02 — Discovery / Catalog

Status: Implementation, focused local tests, isolated live full/incremental/bounded Discovery, and independent review complete (PASS / BLOCKING 0).

## Scope and observed authority

Discovery starts from the strict episode URL `https://hanayume.com/episodes/<13-hex-id>`. The target work is identified by the unique `#xHeader a.ep-h-main-h-series` link; that header link is a sibling of the episode-list subtree, so the adapter separately requires the unique `.series-eplist-wrap` inside the unique `div.series.mode-ep`. Global series links are not a work authority because the page also contains recommendations. The observed range navigation contains ten contiguous oldest-first ranges (`1-30` through `271-296`), with requested page routes `/episodes/<seed-id>/<ordinal>`. On all ten observed routes the active link pointed to the seed path `/episodes/<seed-id>`; the adapter accepts that alias only for the unique selected anchor after the actual browser URL equals the requested numbered route and the selected label matches. Every nonselected numeric link remains strict.

Each declared range is fetched once with finite navigation/DOM/observation timeouts and bounded pacing. Discovery checks the current range label and exact actual page URL, the unchanged complete range set, the same work identity, exact row counts, unique episode IDs, and presence of the seed. A missing row, duplicate ID, foreign work link, redirect, incomplete range, or AccessGuard stop fails closed. The loader is not used as a completion signal.

All ranges are buffered and validated before the adapter yields its first record, for both full and incremental modes. Native row titles stay separate from list position, so split episodes remain distinct. Global positions are assigned in the observed oldest-first order; records are then yielded latest-first. Inclusive bounded scope is applied only after complete validation and retains the original global positions.

## Access classification under the no-login run scope

Classification reads exact access badges inside each episode row. One exact `無料` badge maps to `access_mode=free`. One exact `今なら無料` badge is retained as `access_mode=unknown`; login/registration was required in the logged-out viewer probe, and authenticated non-consuming access is not verified. Missing, duplicate, conflicting, or any other badge state maps to `unknown`.

The current Catalog schema stores only `access_mode`; the raw Japanese badge is used by the site-local classifier and tests and is not persisted in Catalog, title, order, or work key. Discovery includes all observed rows, but only the three logged-out-confirmed `無料` rows are eligible for later Batch work in this run. Do not add login, registration, entitlement, ticket, purchase, or quota actions. Supporting `今なら無料` later requires separate authenticated, non-consuming evidence for the same live identity.

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

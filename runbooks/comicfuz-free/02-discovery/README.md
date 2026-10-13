# Phase 02 — Full / Incremental Discovery and Catalog

**Initial status: NOT STARTED.** [Main contract](../README.md) / [evidence ledger](../PROGRESS.md). Phase 01 establishes authoritative selectors/API, not this plan.

## Change boundary

Implement `site_adapters/comicfuz/discovery.py`, package exports and minimum registration in the real CLI Discovery registry; unit/integration tests and the site README/note. Reuse `DiscoveredRecord`, `DiscoveredItem`, `DiscoveredSource`, `DiscoveryAdapter` and existing Catalog service. No direct Catalog writes from adapter. No new schema unless the Lead demonstrates a concrete uncovered requirement, documents tradeoffs and obtains review.

## Required behavior

- Accept the user-supplied work URL as a Watchlist seed. Strict HTTPS host/path/work ID validation; normalize decorative query only if confirmed safe; follow redirects only after work identity verification. Reject cross-work/bad-host/ambiguous routes.
- Enumerate the **provably complete anonymous published-list scope** using observed native API/DOM, pagination and correct ordering. If the site hides old episode identities from anonymous listings, do not claim they were observed or reconcile them as absent. Distinguish explicit unavailable records from missing, unknown historical rows. Verify list boundaries, empty/duplicate/loop, totals, and consistent snapshots before committing/yielding a list likely to be incomplete.
- Model each observed episode as stable site-local external ID, canonical episode URL and item metadata. If chapter IDs can collide across works, use a work:episode composite from the outset. Episode title and order_key are not substitutes for identity. Preserve stable site-native global display positions when provable. When a bounded selection is requested, retain the work-global positions; no range-local 001 prefix. If a complete ordering/position cannot be proved, leave uncertainty explicit and do not overwrite good existing positions.
- Access classification: only **positively verified currently unconditional public free** maps to `access_mode=free`. Exact first-party observed non-free codes can map to `paid` or `quota` when clear, but neither is required for v1. Everything else maps to `unknown`; no guessed logged-in, charge, medal or rent semantics. No read/unlock attempt in Discovery.
- Observed public deadlines become `free_until`; when the current validated row has no deadline, explicitly clear a previous expiry. If a previously free chapter is now non-free, persist the observed non-free/unknown state without resetting completed items or saved artifacts.
- `full` exhausts the actual complete scope and only reconciles absence when valid complete coverage has been proved. Fail `DiscoveryIncompleteError` for incomplete/errorful full scans; partial/unverified lists must not cause mass unavailable transitions. `incremental` is latest-first and normally stops on existing-known streak, preserving unseen historical rows; update the state of every actually visited row. It does not need to scan all old rows merely to find vanished episodes. An explicit removals marker may be honored only if it reliably identifies a Catalog source.
- Support native `from_url`/`through_url` bounded discovery if Phase 01 verifies reliable ordering, identity and global positions. If not, reject explicitly rather than silently deriving a false range.

## Tests and gate

Focused tests: host/redirect/URL validation, work+episode collision, malformed ID, duplicate rows, pagination loop, changing counts, incomplete full without destructive reconciliation, anonymous positive free vs unknown, stale free→unknown/paid, deadline update/clear, oldest-to-newest global display position, ranges, incremental known-streak, rerun idempotence and already-completed artifact preservation. Integration with a synthetic page/API and an isolated Catalog/Watchlist; no live ticket or charge probes.

**Acceptance:** full/incremental on a real publicly enumerable work complete within the documented scope; correct Catalog IDs, order and access, no missing IDs or accidental eligibilities; tests pass and Reviewer reports BLOCKING 0. If only a bounded public subset is provable, record precisely the limitation and do not label it a complete full run. Advance to Phase 03 once validated free episode identity and access evidence are available.

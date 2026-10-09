# 02 — Discovery and Catalog integration

Status: PLANNED. Entry: accepted Phase 01 native listing and access facts.
Implementer is the only production writer; Reviewer gates completion.

## Objective and changes
Add site-local piccoma discovery and minimal registry/CLI integration. Prefer
src/screenshot_crawler/site_adapters/piccoma/discovery.py, package init,
site tests, site README and note/09_piccoma.md. Do not change Catalog schema
or generic Discovery until a concrete blocker is proved and Lead approves.

## Behavior
- Start with a canonical viewer Watchlist URL. Verify allowed domain,
  product/episode identity, redirect and index URL mapping before querying.
- Expand native listing to completion with bounded pagination/counters.
  Verify total, order, duplicated/missing IDs, target membership and
  inconsistent page snapshots. Validate all evidence **before yielding any
  records** to the Catalog service.
- Preserve site-native global display positions/order labels. Never number
  a requested range 001..N instead of positions in the full work.
- Support full and incremental according to generic discovery contracts;
  support from_url/through_url bounded discovery using the site's true
  native order after its identity and bounds have been proved. If an
  observed site variant cannot do this safely, record unsupported scope
  rather than silently approximating.
- Classify explicit currently unconditional ¥0 as free; observed waiting/
  charge/¥0+ etc as non-free (quota when safely established, otherwise
  unknown), and paid as paid. A readable personal entitlement is not free.
  Stale free campaigns must refresh to non-free in subsequent Discovery.
- Do not enter or consume quota to infer access; unknown flags/contradictions
  stay unknown or cause incomplete discovery depending on whether the
  underlying complete listing can be trusted.

## Tests / gate
Unit tests: URL allowlist, identities including cross-product collisions,
native order/global numbering, pagination, duplicate/missing/loop, free
classification matrix, stale free→non-free, incomplete list, full/incremental,
bounded range and malformed bounds.
Browser integration: synthetic listing with expansion and mixed labels.
Test no entitlement-related actions. Run affected Discovery/Catalog/CLI
tests; full suite only for shared changes.

Accept when data from the two product listings are accounted for (or
unsupported variants documented), no partial list is silently accepted,
tests pass, Reviewer has zero BLOCKING. Record exact live-observed counts
as ephemeral evidence, not constants.

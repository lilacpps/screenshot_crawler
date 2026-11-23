# Phase 02 — Full / incremental Discovery and registration

**Status: PASS, including reopened B3 redirect review (see current [PROGRESS](../PROGRESS.md)).** The implementation follows the Phase 01 evidence, parent contract and current Hanayume/Younganimal references.

## Goal / code

Implement `HeroswebDiscoveryAdapter` under `site_adapters/herosweb/discovery.py`, site-local URL parsing, registration resolution and metadata/preview hooks; register in the existing Discovery registry and, after supported live evidence, registration GUI preview coverage. Keep Catalog writes in existing DiscoveryService.

## Mandatory behavior

1. Strictly validate the canonical current HERO'S WEB **work seed** and its observed path. Work ID and episode ID formats are taken from Phase 01, not borrowed `[0-9a-f]{13}`. Unsupported `/seriesh/` and unknown episode→work conversions remain blocked until an exact positive mapping is observed. No cross-work/cross-host redirect accepted.
2. Use the full-list traversal proven in Phase 01. For range routes or loader, validate all declared intervals, per-range counts, stable Work identity, row ordering and a deterministic final condition; bound navigation, retries, memory/row count and pacing.
3. Buffer **every** record before yielding for **both full and incremental**; duplicate IDs, missing range, repeated page, inconsistent title/identity, unstable DOM, 429, timeout or ambiguous final marker raises `DiscoveryIncompleteError`. A failed pass must not yield a partial set or set missing sources unavailable.
4. Encode stable Catalog external identity including Work+episode when episode ID is not globally unique or reuse is plausible. A displayed chapter number/title is not the primary key; preserve series parts, side stories and chronology.
5. Classify exact positive non-consuming free signals as `free`, verified ticket/wait gate as `quota`, verified coin/pay-only gate as `paid`, and all ambiguity as `unknown`. Sample/validate live site-native access data only when identity/host/response structure is fully matched. Never click an entitlement action. Persist existing grant metadata only if observed and compatible, never invent expiry.
6. Use existing `DiscoveryScope`, full listing inventory/preview/exclusion replay and incremental stop interfaces; ensure a truncated scope does not alter the authority of complete enumeration. New GUI Watchlist additions must actually support saving, preview and the existing safe registration contract.

## Tests / gate

- Unit: canonical + malicious/ambiguous URL, wrong Work, split titles, duplicate episodes, missing/overlapping intervals, unstable total, special episode order, access label conflict, site-native identity mismatch, `free/quota/paid/unknown`, active-grant preservation.
- Browser fixtures: multi-range/loader completion, bounded retry/403/429/challenge/incomplete listing; full/incremental consistency and no Catalog unavailability writes from failed scans; registration and preview/scoping.
- Live with isolated Watchlist/Catalog: one full Work enumeration, verify exact number/positions/unique IDs against visible site total, sample the four access categories where available, then incremental rerun with unchanged identity. Distinguish not-observed category from successfully tested category.
- Read-only Reviewer PASS with BLOCKING 0 before accepting complete Discovery. **Do not call a partial range crawl “full Discovery.”**

Update `PROGRESS.md` and site note. Then continue to Phase 03.

# 11. Younganimal current implementation

## Discovery registration and flow

`YounganimalDiscoveryAdapter` is registered in the `discover` CLI registry.
Manual crawl, Batch adapter, and Batch Site Policy registries do not include
Younganimal. The adapter uses the existing shared CDP `BrowserSession` and
Playwright `Page`; it does not launch a browser or own a profile.

Discovery accepts only the exact canonical first-party series listing URL
shape `https://younganimal.com/series/<13-lowercase-hex-work-id>`, with no
credentials, query, fragment, or trailing slash. The supplied episode URL
resolved in Phase 01 to work `aee4fa742b0fe`; this concrete series URL is an
example and future continuation entry, not an ID allowlist. Episode URLs are
rejected before AccessGuard startup or any navigation because opening an episode
seed would reach the viewer before Discovery has established its row's free
label. The episode URL parser remains for public row identity and bounded-scope
boundaries. This is a Lead-approved Phase 02 safety deviation from the original
episode-seed plan; no live request has tested this corrected seed contract after
the HTTP 429 stop.

The adapter validates the canonical work title and buffers every contiguous
numeric range before yielding a record. Each range must preserve the same full
range map, expected row count, unique episode IDs, and first-party canonical
episode URLs. The selected current range may use the canonical work URL only at
the corresponding numeric position. Output order is latest-first while
`global_display_position` remains the episode's oldest-first whole-work index.
Inclusive bounded Discovery slices after the complete listing and preserves
those global positions. No episode-seed containment is claimed.
A nonempty `epListUser` history root is rejected before any record can be
yielded. The adapter does not currently compare same-ID history rows against
public titles/access labels because that DOM identity relation is unverified.

The range selector currently recognizes the exact `最新話から` label only at
the same-work `/new` route and an optional `...` placeholder only when the raw
anchor has no `href`. Unknown controls, route drift, incomplete ranges,
duplicates, and timeouts fail closed. The shared `DiscoveryService` receives no
partial records on an incomplete full traversal, preventing missing Catalog
sources from being marked unavailable.

One exact row-local `無料` label maps to `access_mode=free`. `今なら無料`,
`待つと無料`, missing, duplicate, conflicting, or unrecognized labels map to
`unknown`. The row's displayed text is retained only in the transient adapter
observation; Catalog schema is unchanged. Authentication state is unknown and
is not inferred. No waiting, ticket, coin, purchase, grant, or resource action
is implemented.

The adapter has a maximum of 100 ranges / 3,000 rows, 350 ms between range
navigations, finite navigation/DOM/observation deadlines, and a 5-second
best-effort AccessGuard cleanup bound. It relies only on the shared generic
AccessGuard signals and does not add site-specific challenge text heuristics.

## Current verification and limits

The user-provided work resolved to work ID `aee4fa742b0fe`. Its public listing
declared 31 ranges from `1-30` through `901-925`. Bounded probes observed the
canonical root, `/1`, `/2`, and `/3`–`/5`; sampled range pages returned 30 public
rows with unique IDs. On `/1`, the selected `1-30` link resolves to the
canonical work URL. The first-party range page uses a public `epList` root plus an optional
separate `epListUser` root. Empty history roots are supported; any history row
fails closed until duplicate identity/title/access consistency is verified.

Full live Discovery is **not verified**. The final 180-second-capped,
31-range-capped attempt stopped after nine range pages (11 navigations total)
in 13.066 seconds when the shared AccessGuard observed HTTP 429 at
`/series/aee4fa742b0fe/9`. No episode records were yielded. `Retry-After` was
not captured; no request was made after the 429. Earlier diagnostic timeouts
are recorded in the runbook; their cause is unknown and they do not override
the explicit 429 stop. The final live traversal used the earlier episode-seed draft, before the
series-only seed and history-row review fixes; the corrected code has not been
live-tested. The isolated DiscoveryService catalogs contain one Work row
created before the adapter runs and zero items, episode sources, targets, runs,
artifacts, or quota states. No normal Catalog was used.

Final local validation: targeted Younganimal Unit/Integration plus the Discovery CLI registry test passed (`28 passed`, 23 existing pytest-asyncio warnings). The independent Tester reran the two Younganimal files: `27 passed, 0 skipped`, 23 warnings, 4.31s. Full `ruff check src tests` passed. Lead-run regressions passed separately: Hanayume `201 passed, 0 skipped`; generic CLI/registry/discovery/catalog/watchlist `214 passed, 0 skipped` (the focused Younganimal CLI registry test is part of this generic group).

The final Reviewer verified the partial Discovery implementation, tests, and docs with BLOCKING 0. The Tester local artifact audit also passed: both isolated Catalogs contain one pre-created Work row and zero other records; JSON sanitation passed; no live call followed HTTP 429. Complete live range coverage, full Catalog synchronization, and site-wide behavior remain unverified. The corrected series-seed/history handling has not been live-tested. The HTTP 429 is the sole external live blocker; no human approval is pending. Wait eligibility and timer/resource semantics remain unknown and waiting stays unimplemented.

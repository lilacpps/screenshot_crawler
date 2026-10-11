# Younganimal adapter

Younganimal currently has a site-local Discovery adapter registered for the
`discover` CLI only. It accepts only the exact canonical first-party series
listing URL shape `https://younganimal.com/series/<13-lowercase-hex-work-id>`
with no credentials, query, fragment, or noncanonical trailing slash.
Episode URLs are rejected before AccessGuard startup or navigation because
the row-level free label has not been proven. Episode URL parsing remains
available for row identities and bounded-scope boundaries. The adapter
buffers the complete declared range map before yielding Catalog records.
It does not register manual crawl or Batch support.

## Discovery contract

- Episode identity is work-scoped as `<work_id>:<episode_id>`.
- The adapter follows the work's numeric ranges in oldest-first order, validates
  each range against the same declared map, requires the declared row count and
  unique episode URLs, and verifies one consistent work title. It buffers all
  ranges before yielding. There is no episode-seed containment claim. A failed or incomplete traversal
  yields no partial records, so a full Discovery cannot mark unseen sources
  unavailable.
- The range selector accepts the observed `最新話から` control only at the
  exact same-work `/new` path. It ignores an observed `...` placeholder only
  when the raw anchor has no `href`; every other non-range selector fails
  closed. The currently selected numeric range may resolve to the canonical
  work URL, but only at its matching position.
- A nonempty `epListUser` history root is rejected before yielding any
  records. Same-ID history title/access consistency has not been proven,
  so current support is limited to listings with an empty history root.
- One exact row-scoped `無料` label maps to `free`. `今なら無料`, `待つと無料`,
  absent, repeated, conflicting, and unrecognized labels map to `unknown`.
  Login state is not inferred. No wait, ticket, coin, purchase, or grant action
  is implemented.
- Full and incremental modes both require complete-work buffering. Inclusive
  bounded scopes retain the whole-work display positions.

The adapter uses the existing shared CDP `BrowserSession` and Playwright Page,
the shared `AccessGuard`, 350 ms between range navigations, finite navigation
and observation deadlines, a maximum of 100 ranges / 3,000 rows, and bounded
AccessGuard cleanup. It does not launch Chrome or select a browser profile.

## Verification status

Unit and browser-backed synthetic tests cover strict seed URLs, episode rejection with zero navigation, history conflict preservation, known selector controls, exact labels, route/range completeness, global positions, bounded scope, incomplete Catalog preservation, and cleanup deadlines.
The user-provided work declared 31 ranges (`1-30` through `901-925`). The final bounded live run
used the earlier episode-seed draft and stopped on the shared AccessGuard's
HTTP 429 signal at range `/9`; the corrected series-seed code has not been live
tested. Full live Discovery is **not verified**. The isolated DiscoveryService
Catalogs contain one pre-created Work row and no items/sources or other run
data; the normal Catalog was untouched. No alternate endpoint/profile or retry
is allowed while the 429 stop remains.

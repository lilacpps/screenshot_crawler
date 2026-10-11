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
the shared `AccessGuard`, and a 1-second wait immediately before every numeric
range navigation, including canonical-root-to-first-range. It keeps finite
navigation and observation deadlines, a maximum of 100 ranges / 3,000 rows,
and bounded AccessGuard cleanup. A Playwright `DOMContentLoaded` timeout is
retried only when that exact `goto` attempt observed one matching main-frame
document request and its HTTP 200 response, the current page URL is still the
expected URL, and the guard permits continuing. The adapter waits 2 seconds,
checks the guard and URL again, then allows at most one retry for that route
and two retries across the whole work. Unknown status, non-200, redirect or
route drift, other Playwright errors, and guard stops are not retried. This is
bounded recovery, not proof of the earlier timeout's cause. It does not launch
Chrome or select a browser profile.

## Verification status

Unit and browser-backed synthetic tests cover strict seed URLs, episode rejection with zero navigation, history conflict preservation, known selector controls, exact labels, route/range completeness, global positions, bounded scope, incomplete Catalog preservation, cleanup deadlines, attempt-specific timeout evidence, retry backoff/guard ordering, cancellation cleanup, and the two-retry work budget.
The user-provided work declared 31 ranges (`1-30` through `901-925`). The
reviewed-recovery full pass returned matching main-frame HTTP 200 responses for
`/1`–`/5`, buffering 150 distinct rows at positions 1–150. `/6` had no response
status, so it was not eligible for retry; Discovery yielded no episode records.
Full 925-row Discovery remains **not verified**. The isolated Catalog had one
pre-created Work and zero episode items/sources; the normal Catalog was
untouched.

Viewer/Capture is **not implemented**. The first bounded 03A probe verified the
exact target row as free and navigated to its exact episode route, but the
public seek read `1..1` immediately after DCL, unlike prior durable evidence of
`1..21 step 2`; the probe stopped before seeking. A second 03A attempt stopped
before episode main-frame navigation when a page-originated Younganimal fetch
to the target path returned HTTP 429 (`Retry-After: 1`). No manual navigation
or retry followed; in-flight automatic requests are not ruled out. No page or
response bytes were saved. Readiness, 11 positions, canvas stability, body
continuity, END, and source/native attribution remain unverified. Do not add
viewer/capture behavior from these probes. Any 403/429/challenge/CAPTCHA is an
immediate stop. The latest independent Tester audit passed 42 tests, 0 skipped,
140 existing asyncio deprecation warnings; four isolated Catalogs were read
only and each contained one pre-created Work with all other tables empty.

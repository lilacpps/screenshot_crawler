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
episode-seed plan. Later bounded preflight and partial full traversals exercised
the corrected series-seed contract but did not prove all 925 rows.

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

The adapter has a maximum of 100 ranges / 3,000 rows, a 1-second wait before
every numeric range navigation (including canonical-root-to-first-range),
finite navigation/DOM/observation deadlines, and a 5-second best-effort
AccessGuard cleanup bound. A Playwright `DOMContentLoaded` timeout is eligible
for one retry only when that exact `goto` attempt observed one main-frame
navigation request for the exact expected URL and the matching request object
returned HTTP 200, with `page.url` still exact after timeout and again after a
2-second backoff plus guard check. There is at most one retry per navigation
and two per whole work. Unknown status, non-200, redirect/drift, other
Playwright errors, and access stops do not retry. The cause of the previously
observed `/3` timeout remains unknown; this fail-closed recovery does not
attribute it. The adapter relies only on shared generic AccessGuard signals
and adds no site-specific challenge text heuristics.

## Current verification and limits

The user-provided work resolved to work ID `aee4fa742b0fe`. Its public listing
declared 31 ranges from `1-30` through `901-925`. Bounded probes observed the
canonical root, `/1`, `/2`, and `/3`–`/5`; sampled range pages returned 30 public
rows with unique IDs. On `/1`, the selected `1-30` link resolves to the
canonical work URL. The first-party range page uses a public `epList` root plus an optional
separate `epListUser` root. Empty history roots are supported; any history row
fails closed until duplicate identity/title/access consistency is verified.

Full live Discovery is **not verified**. The earlier 180-second-capped attempt
used the episode-seed draft and stopped at HTTP 429 after nine range pages;
no further manual navigation or retry followed within that run, while any
in-flight automatic request is not ruled out. The resumed bounded preflight
returned HTTP 200 at the canonical root and `/1`. A full canonical-series pass
then stopped at `/3` after 24.010 seconds with no response status. A later
bounded diagnostic returned HTTP 200 at `/3` and `/2` and strictly validated
30 unique rows at positions 61–90 and 31–60, but did not explain the earlier
delay. The reviewed positive-response retry rule was implemented and locally
verified. Its single full pass completed `/1`–`/5` with matching main-frame
HTTP 200 responses, buffering 150 distinct rows at positions 1–150; `/6` had
no response status, so no retry was eligible and no records were yielded. The
isolated Catalog had one pre-created Work and zero episode items/sources.
Report: ignored
`output/younganimal_experiment/resume_20261011_retry1/phase02_full_discovery_retry_20261011.json`.

Viewer/Capture remains **not implemented**. A separate Lead-approved 03A probe
freshly validated the exact free target before opening it. Its first episode
navigation returned 200, but immediately after DCL the public seek read
`value=1,min=1,max=1,step=1`, unlike prior durable same-target evidence
`21,1..21,step2`. The probe stopped before seeking; early initialization is
possible but unproven. On a second 03A attempt, the canonical `/1` listing and
free-row check passed, then a page-originated `younganimal.com` fetch for the
episode path returned HTTP 429 (`Retry-After: 1`) before any episode main-frame
navigation. AccessGuard stopped; no manual navigation or retry followed, and
in-flight automatic requests are not ruled out. The fetch cause is unknown.
No image, HTML, or response body was saved. No viewer readiness, seek positions,
body continuity, END, canvas stability, source/native attribution, or capture
behavior is verified. Current Viewer/Capture implementation is absent. No
further live operation may follow the 429 without new authorization/state
change.

The independent local Tester rerun passed 42 tests, 0 skipped, with 140
existing asyncio deprecation warnings in 9.00s. Four isolated Catalogs were
opened read-only; each had one pre-created Work and all other tables empty.
JSON sanitation passed. Full live Discovery, Viewer capture, and E2E remain
incomplete; no normal Catalog was used.

Local validation after the bounded retry change: targeted Younganimal Discovery Unit/Integration plus the CLI registry test passed (`42 passed, 0 skipped`, 140 existing pytest-asyncio deprecation warnings in 9.20s); full `ruff check src tests` passed. The independent Tester and Lead regression groups from the earlier phase checkpoint remain recorded in the runbook: Younganimal `27 passed, 0 skipped`; Hanayume `201 passed, 0 skipped`; generic CLI/registry/discovery/catalog/watchlist `214 passed, 0 skipped` (the focused Younganimal CLI registry test overlaps this generic group).

The Final Reviewer gate for the safe partial implementation/tests/docs is PASS / BLOCKING 0. The latest full Discovery pass used 0 retries, buffered 150 rows from `/1`–`/5`, and stopped at `/6` without response status; it yielded no episode records, so full range coverage and Catalog synchronization remain unverified. The later 03A attempt stopped on an AccessGuard HTTP 429 before the episode main-frame navigation. No explicit site navigation or retry was issued after that stop; in-flight automatic traffic is unknown. The independent Tester audit passed 42 tests, 0 skipped, with 140 existing asyncio deprecation warnings; the four isolated Catalogs were read-only and each contained one pre-created Work row with all other tables empty. Wait eligibility/resource semantics remain unknown and waiting stays unimplemented. Viewer/Capture, body continuity, END, Phase 04, and live E2E remain unverified or unimplemented.

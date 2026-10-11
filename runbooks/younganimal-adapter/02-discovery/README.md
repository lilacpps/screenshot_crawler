# Phase 02 - Younganimal Discovery

Status: PARTIAL DISCOVERY IMPLEMENTATION VERIFIED by Reviewer (BLOCKING 0); local checks PASS; complete live Discovery INCOMPLETE (HTTP 429; corrected code not live).
Prerequisite: Phase 01 VERIFIED / BLOCKING 0.

## Contract and safety deviation

Discovery currently accepts only the exact canonical first-party series listing URL shape
`https://younganimal.com/series/<13-lowercase-hex-work-id>` with no credentials, query, fragment, or trailing slash. The user-supplied episode URL resolved to work `aee4fa742b0fe`; `https://younganimal.com/series/aee4fa742b0fe` is the current example and future continuation entry, not a work-ID allowlist.

The original proposal used an episode URL as the Watchlist seed. Review rejected that entry because navigating to an episode before reading its row-level free label would enter the viewer without positive free proof. The adapter now rejects episode seeds before AccessGuard startup or any navigation. Episode URLs remain valid for public row identities and optional bounded-scope boundaries. No episode-seed containment is claimed.

## Implemented behavior

- Validate the unique work title and the complete declared numeric range map, then visit each range in oldest-first order. Require the expected row count, stable routes and labels, unique episode IDs, and a consistent work title before yielding any episode record.
- Output source identity as `work_id:episode_id`, latest-first, with `global_display_position` retained from the oldest-first work position. Full and incremental modes both buffer the complete work; bounded slices preserve whole-work positions.
- Emit only canonical public `epList` rows. Reject any nonempty `epListUser` history root because the same-ID identity, title, and access-label relation is unverified. This deliberately limits current support to listings with an empty user/history root.
- Map only one exact row-scoped `無料` label to `free`. `今なら無料`, `待つと無料`, missing, repeated, conflicting, or unknown labels remain `unknown`. No wait, ticket, coin, purchase, grant, or resource action is implemented.
- On any incomplete or changed listing, fail before yielding episode records so the Catalog cannot mark unseen sources unavailable.

## Validation

Unit tests cover strict site/work URLs, episode-seed rejection, range maps, duplicate identities, classification, positions, and bounded cleanup. Synthetic Playwright Integration tests cover full/incremental/bounded Discovery, a conflicting duplicate in `epListUser` with zero records yielded and existing sources preserved, and episode-seed rejection with zero navigation. The CLI registry test confirms Discovery-only registration.

## Live evidence and gate (2026-10-11)

- The canonical work page declared 31 numeric ranges, `1-30` through `901-925`. Fresh `/1` returned 30 rows and 30 unique IDs; its selected `1-30` route pointed to the canonical work URL. Bounded samples `/2` and `/3` through `/5` also returned 30 rows. These samples do not establish all 925 rows.
- The final live attempt used the earlier episode-seed draft, before the current series-only and history-row fixes. It stopped after nine range pages (11 navigations total) in 13.066 seconds when the shared AccessGuard observed HTTP 429 at `/series/aee4fa742b0fe/9`. No episode records were yielded. `Retry-After` was not retained. No live request followed; the corrected implementation has not been live-tested.
- Both isolated DiscoveryService Catalogs contain one Work row created before adapter invocation and zero items, episode sources, targets, runs, artifacts, or quota states. No normal Catalog was used.
- A separate 90-second diagnostic harness stopped at `/28`; it did not complete and does not prove an AccessGuard failure. Earlier timeout causes remain unknown.

Do not retry the live site. The HTTP 429 is the current external blocker; no human approval is pending. Any future authorized validation must resume only at `https://younganimal.com/series/aee4fa742b0fe` after the stop signal is absent. The 925-row target remains unverified; Phase 03/04 production work is not implemented. Reviewer gate: PASS for the partial Discovery implementation, BLOCKING 0.

Final local gates: Reviewer VERIFIED the partial implementation/tests/docs with BLOCKING 0. Targeted tests: 28 passed, 23 existing asyncio warnings; independent Tester run over the two Younganimal files: 27 passed, 0 skipped, 23 warnings in 4.31s. Full `ruff check src tests` passed. Root regression groups passed: Hanayume 201/0 skips and generic CLI/registry/discovery/catalog/watchlist 214/0 skips; the focused Younganimal registry test is included in the latter.
Tester local artifact audit PASS: both read-only isolated Catalogs contain one pre-created Work row and zero other records; JSON sanitation passed. No live E2E was run and no site call followed HTTP 429.

# Young Animal `work_ticket` progress

**Date:** 2026-10-18
**Branch / baseline:** `feat/younganimal-work-ticket` from `origin/main` `fd10a2ee2b1876bbd79dae85e898cf0a8de4cd4c`.
**Protected pre-existing files:** `crawler.yaml`, `watchlist.yaml`, and `debug.log` are user-owned changes and are not part of this work.
**Ticket ledger:** 1 observed `work_ticket` use of the authorized maximum 5. The only used ticket was on episode `856137d88753b` / work `8246f8b8b2e6c`; no account balance delta was recorded. The minimum same-work cooldown ends at `2026-10-19T05:05:50.550591Z` (`2026-10-19 14:05:50.550591 JST`). No additional ticket may be used for that work before then.
**Current checkpoint:** Phase 01 evidence passed review. Phase 02 implementation and its late-AccessGuard ordering fix passed independent review. Phase 03 is waiting for the Lead's formal contract; Phase 04 remains unstarted.

## Phase status

| Phase | Status | Current gate |
| --- | --- | --- |
| 01 — repository and live evidence | PASS | One exact wait-free action was independently adjudicated as one observed resource use. The same-work Viewer became ready on the same Page. No balance-delta claim. |
| 02 — Discovery and SitePolicy | PASS | Independent review passed. The delayed final-response regression verifies late AccessGuard stops prevent result publication and preserve Catalog state. |
| 03 — Batch entry and grant-only | NOT STARTED | Waiting for formal Lead Phase 03 contract. |
| 04 — end-to-end tests and live verification | NOT STARTED | Waits for Phase 03 review and ticket/work-specific cooldown-safe live plan. |

## Phase 01 — reviewed observations

- The first sequentially inspected allowlisted URL, `77d27c1572ac7`, belongs to work `a3ca78e2ee97a` and was directly readable with the production Viewer ready. No ticket gate was present and no ticket was used. Whether access came from free publication or a previous grant remains unknown.
- The next URL, `856137d88753b`, belongs to work `8246f8b8b2e6c`. Before action, its exact native episode object reported `hasAccess=false` and `accessType=waitAndFree`; its direct ancestor identified the same work. The hydrated page showed a unique visible, enabled `button[data-e2e=wfRead].mode-waitfree` in the charge scope, distinct from the rental control, with positive auth evidence. The visible control said **待つと無料で読む**.
- After Reviewer approval and Lead GO, exactly one retained wait-free control was clicked. The exact episode state changed false-to-true while remaining `waitAndFree`; same-work series access showed the episode accessible, the charge gate cleared, and the same Page's production Viewer parser reported the first body slot active and ready. A target-bound `POST /api/checkout/rental` returned HTTP 200. Reviewer and Lead adjudicated the combined evidence as one observed `work_ticket` use. The endpoint alone is not claimed as proof of a balance debit. No retry, reload, second click, or other episode action followed.
- The action was at `2026-10-18T06:05:50.550591Z`. Two exact same-page native GET samples 5.174 seconds apart showed `timeRemainingInSeconds` 258952 then 258947. The decrement supports a request-start-derived candidate expiry `2026-10-21T06:04:58.528Z`; this is an inference, not an absolute server expiry. A separate visible work countdown showed `22:59`, whose relation to recovery is unknown. The account/listing row was classified by the existing rental-label logic with an earlier conservative expiry; that lower bound remains in effect when both observations exist.
- The Viewer parser reported the standard layout, seek max 33, 28 body slots, first body slot active and ready, navigation closed, and no splash nodes. No screenshot, pixel inspection, seek, or capture was performed.
- An earlier diagnostic stopped before its action latch because a series response omitted the exact target row; it used zero tickets and was superseded by the exact episode payload observation and the later approved action. Earlier incomplete DOM-only probes for the first URL were also superseded by the corrected direct-readable observation.
- Reduced ignored evidence is under `output/younganimal_work_ticket/`: `phase01_readonly_probe_77d27c1572ac7.json`, `phase01_episode_payload_observation_856137d88753b.json`, `phase01_ticket_action_gate_856137d88753b.json`, `phase01_postgrant_countdown_viewer_856137d88753b.json`, and `phase01_target_listing_label_856137d88753b.json`. The no-retry latch is `ticket_action_latch_856137d88753b.json`. Probe artifacts do not contain cookies, tokens, raw page content, or balance data.

## Phase 02 — live listing evidence and implementation

Lead authorized the standard Discovery listing base `https://younganimal.com/series/8246f8b8b2e6c` as a separate read-only observation after the episode Page was closed. The bounded observer repair visited only that canonical base listing; it did not visit an episode or numbered range route. First-party non-GET requests were blocked. The settled public and account roots each contained the target row, and the account row was recognized as paid by the pre-existing rental classifier. The listing emitted two natural `GET /api/series/access` responses and an auth-session response. Both access payloads were parsed successfully; `$.seriesAccess.seriesId` matched the canonical work and `$.seriesAccess.episodeAccesses[*]` exposed exact row IDs, `accessType`, `hasAccess`, and, on an active ticket row, `timeRemainingInSeconds`. The auth response had a positive integer `user`. The request did not carry a work ID query parameter; the work binding is the response's series ID. The target row appeared as active `waitAndFree` after the prior authorized ticket use. No ticket was used during this listing observation. The reduced report is `output/younganimal_work_ticket/phase02_listing_probe_repair2_8246f8b8b2e6c.json` (ignored).

Phase 02 implementation changes are confined to Younganimal Discovery and SitePolicy plus focused tests and synchronized authority/site documentation. Discovery observes only naturally emitted same-origin access/auth GET responses during its existing canonical work traversal; it makes no API request and performs no work-page preflight. It joins exact row IDs to validated public identities and requires positive authentication plus matching response work ID. Only exact `waitAndFree` rows are eligible for interpretation: false with a missing or exact zero timer is a quota candidate; false with a null, positive, or malformed timer remains unknown. True with a valid positive timer is a manually active ticket grant with a request-start-derived conservative expiry. A recognized account rental lower bound can shorten that expiry. Unsupported types, contradictory timers, absent or ambiguous rows, foreign work IDs, and unavailable auth remain unknown and preserve stored grant state. Native state does not override an exact free label or active rental.

`YounganimalSitePolicy` exposes the `work_ticket` resource with work scope, quota limit one, and `after_observed_consumption` commit. Its local same-work cooldown is at least 23 hours; a longer configured value is honored. Active ticket grants are selected as non-consuming direct access. The generic Batch layer is reused without a shared production change. Batch entry behavior is not yet wired in this phase.

Phase 02 validation:

- Unit selection `tests/unit/test_younganimal_discovery.py`, `tests/unit/test_younganimal_policy.py`, and `tests/unit/test_batch_executor.py`: 145 passed, 0 skipped. This includes the work-scoped one-per-work Catalog planner contract and cooldown-before-adapter checks for both normal and grant-only Executor entrypoints. Existing pytest-asyncio deprecation warnings remain.
- Browser-backed `tests/integration/test_younganimal_discovery_browser.py`: 9 passed, 0 skipped after the review fix. These exercise naturally emitted fixture GETs, authenticated work binding, wait-free candidate, manually active grant, unsupported access types, unauthenticated fail-closed behavior, full/incremental refresh, existing rental behavior, and a delayed final 429 during native-body draining.
- Targeted `ruff check` for changed implementation and tests and `git diff --check`: passed.
- Phase 02 review found that a fatal AccessGuard event could arrive while the final native response body was draining. Discovery now checks the guard after `native_observer.finish()` and before record construction. A browser-backed regression holds a natural native response body while a delayed 429 arrives, then checks that Discovery yields no rows, preserves Catalog state, and detaches listeners. The regression passed independently (1 passed); the Discovery Unit suite passed (62 passed); the full Discovery browser-backed Integration file passed (9 passed). Targeted Ruff passed.
- Independent Phase 02 re-review decision: PASS, no blocking findings. The Reviewer independently ran 78 tests with 0 skipped.

## Remaining unknowns and constraints

- The action endpoint and native transition support the reviewed classification of one observed resource use, but no balance delta was available; none is claimed.
- The episode timer is relative. The exact server ticket recovery timestamp and its relation to the separate `22:59` work countdown are not established. Production uses the measured native timer only for active grant expiry, never as a fixed-duration fallback or the work cooldown.
- Four of the maximum five authorized ticket uses remain unspent. Other allowlisted episode work IDs have not been pre-scanned. Before any later use, inspect only the next authorized episode in sequence, establish its exact work identity, and account for same-work cooldown. Do not use any other episode URL.
- Discovery hydration attempted first-party mutations in the live probe; non-GET requests were blocked. Their meaning remains unknown, and they are not treated as ticket consumption.
- Phase 03 must retain the approved one-work-at-a-time sequence: use the Catalog candidate URL directly, never preflight all works or visit a series page from Batch, and process one work completely before the next.

## Phase 03 — pending

- Adapter entry, final retained-control checks, single-click latch, observed-consumption persistence, same-Page Viewer handoff, and `--grant-only work_ticket` remain unimplemented until Phase 02 is independently approved.
- The existing direct free/rental and Capture paths must remain unchanged.

## Phase 04 — pending

- Production Unit / Integration / E2E and independent review after Phase 03.
- Live `--grant-only work_ticket` and normal Batch verification on separate cooldown-safe authorized episode URLs, only after confirming each selected work ID. Track exact consumption count; stop at five total.
- Same-work cooldown rerun must prove zero site requests and no Page creation. Normal Batch must prove one exact ticket action followed by existing Viewer/Capture on the same Page. Manual ticket Discovery must be observed without a second action.
- Record any remaining risk and test categories not run before marking this runbook complete. Do not merge `main` automatically.

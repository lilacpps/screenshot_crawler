# Yanmaga access expansion progress

**Status:** Stage 01 PASS (observed Discovery subset); independent BLOCKING 0.
**Plan authored:** 2026-11-15.
**Implementation branch:** `feat/yanmaga-access`, created from latest `origin/main` (`4407e975`).
**Authority:** [README.md](README.md), `runbooks/yanmaga-free/README.md`, `AGENTS.md`.
**Workspace boundary:** live artifacts are isolated under `output/yanmaga_access_experiment/stage01/`. No normal Catalog, Watchlist, library, or capture output was used. User-edited `crawler.yaml` and `watchlist.yaml` were preserved.

| Stage | Status | Gate |
| --- | --- | --- |
| 01 Site probe / Discovery | PASS (observed subset); independent BLOCKING 0 | Wait-free, paid-only, and grant/expiry evidence remains unverified. |
| 02 First-free capture | NOT STARTED | Needs Stage 01 review and a Lead phase contract. |
| 03 Work ticket | NOT STARTED / NOT VERIFIED | No wait-free signal or ticket/cooldown behavior has been confirmed live. Do not infer or enable quota. |
| 04 E2E / final review | NOT STARTED | Depends on earlier accepted stages and live access evidence. |

## Stage 01: site probe and Discovery

### Live evidence

- Connected to the existing shared Crawler Chrome through the standard CDP helper; Lead verified process/profile provenance. All site interaction used Playwright pages/locators in a newly created page. No Chrome launcher, profile change, login action, episode navigation, access CTA, or rights-consuming action was used.
- Evidence timestamps are 2026-11-15 JST, based on isolated evidence-file modification times: initial dual sample 09:41-09:44; wife-list continuation 09:46; wait-candidate scan 09:50; post-change verification 10:12-10:13.
- Stable sample IDs map to user-provided samples: `work-dual` is the dual-access sample (`/comics/%E5%8F%8C%E6%98%9F%E3%81%AE%E3%82%A2%E3%83%9D%E3%82%AF%E3%83%AA%E3%83%95%E3%82%A1`); `work-wife` is the wife/child-care sample (`/comics/%E5%A6%BB%E3%81%A8%E5%83%95%E3%81%AE%E5%B0%8F%E8%A6%8F%E6%A8%A1%E3%81%AA%E8%82%B2%E5%85%90`); `work-amateur` and `work-company-stars` are the two inspected wait candidates.
- Authenticated shared-profile `work-dual` returned HTTP 200. The post-change complete listing had 57 rows: 27 exact first-free rows, 8 red public-free rows, and 22 unknown. Snapshot state was authenticated, with no continuation left. Counts match the pre-implementation DOM audit. Before the change, the old adapter classified all 57 rows as unknown.
- Two first-free rows appeared in the initial viewport; 27 appeared in the complete 57-row listing. Positive UI evidence was five visible same-origin `/mypage` links, no visible sign-in/sign-out label, and the current top-level work document. `ep.is_logged_in=true` was consistent supporting evidence, not the authority. A temporary empty-context comparison had no `/mypage` link, two sign-in links, and `ep.is_logged_in=false`. No account/profile values were captured.
- A request-method-only counter during full traversal saw 25 POST requests. A separate short reload recorded 18 POSTs with sanitized host/path; all were third-party analytics endpoints (TikTok, Meta, and Google measurement). No first-party Yanmaga POST was seen in that endpoint sample. This is not a network-wide POST-zero claim. The synthetic browser fixture separately asserts no first-party non-GET or episode-route request and zero access-control button clicks.
- On `work-wife`, the initial listing had no wait marker. One authorized ordinary More click on a dedicated page issued only `GET /episodes?offset=5&sort=older`, without `limit`; it inserted 150 rows at positions 5-154. All 10 original IDs remained in their original relative order, but did not remain a prefix. This shape stays outside the strict pagination contract; no adapter broadening was made.
- On `work-amateur` and `work-company-stars`, the inspected first view had no wait marker. Their episode identities failed the adapter's strict row-URL check, so no records were emitted. These failures remain closed.
- No wait-free row, paid-only/coin-only row, active grant, safe grant expiry, or 23-hour recovery behavior was observed. Numeric point badges coexisted with free states and do not prove paid-only access. These states remain unknown and are not implemented.

### Evidence files

All files below are sanitized and isolated under `output/yanmaga_access_experiment/stage01/`:

- `probe-dual-sample.json` and `probe-visible-dom-summary.json`: initial complete-list and rendered DOM summaries.
- `auth-ui-compare.json`: shared-profile and temporary empty-context UI/telemetry comparison.
- `wife-list-single-continuation.json` and `wife-list-order-summary.json`: the one bounded ordinary list expansion and identity/order summary.
- `wait-sample-scan.json`: first-view observations for the two wait candidates.
- `post-implementation-live-counts.json` and `post-request-endpoints.json`: final classifier counts and sanitized POST endpoint hosts/paths.

### Implementation decisions

- Positive authenticated evidence is a visible exact same-origin `/mypage` UI link without credentials/query/fragment, no visible sign-in link, current work-document identity, and no observer overflow. Analytics true is supporting only; it may be absent, but any observed state must agree.
- First-free classification requires exactly one total free marker and one first-free marker, exact displayed badge text translated as `first-free`, exact class-token set `mod-episode-point--free` + `by_first_time`, authenticated page proof, and no wait/modal/red/conflicting free badge. Public red-free classification retains its exact marker proof and accepts verified anonymous or authenticated page identity.
- Confirmed first-free and public-free rows map to existing `access_mode=free`; no schema or new mode was added. Capture remains anonymous-only in Stage 01, so Discovery recognition does not authorize first-free Viewer entry.
- Wait-free, paid, quota, grant, expiry, and reset-time selectors remain unsupported. Missing `data-limit` continuation and invalid episode URL shapes continue to fail closed. No shared Core, Catalog, or Planner policy behavior changed.
- Yanmaga planning remains direct-only and uses Catalog order. `test_yanmaga_planner_keeps_only_free_direct_and_preserves_positions` confirms two free direct candidates retain Catalog insertion order while artifact prefixes preserve `display_position` (`013`, `002`); unknown/quota/paid/owned/unavailable rows are skipped. The shared `test_display_position_order_preserves_direct_quota_slots_and_quota_selection` confirms direct candidates stay before work-quota candidates and `display_position` reorders only within each pool. This is shared planner behavior, not evidence for a future Yanmaga quota policy.
- Every Yanmaga refresh sends `free_until=None` because no expiry was observed; the existing Catalog contract clears stale free expiry. Yanmaga does not observe grants, so `access_granted_until_observed=False` preserves an existing grant. An explicitly observed null remains authoritative and clears it. Lead separately ran both Catalog grant-preservation regression cases; Stage 01 had no live grant evidence.

### Tests and checks

Pre-change baseline run by Lead: `test_yanmaga_policy.py` 24 passed; Discovery and adapter unit tests 27 passed; Discovery browser integration 21 passed; total 72 passed / 0 skipped.

Post-change Stage 01 runs:

- `tests/unit/test_yanmaga_discovery.py`: 29 passed / 0 skipped.
- `tests/integration/test_yanmaga_discovery_browser.py`: 24 passed / 0 skipped; after adding the strict first-party request spy, the focused authenticated/non-consumption case passed 1 / 0 skipped.
- `tests/unit/test_yanmaga_policy.py`: 24 passed / 0 skipped.
- Independent Reviewer reran `tests/unit/test_yanmaga_discovery.py` (29 passed) and two browser-backed Discovery cases (2 passed); 0 skipped, then reported BLOCKING 0.
- `tests/unit/test_batch.py::test_display_position_order_preserves_direct_quota_slots_and_quota_selection`: 1 passed / 0 skipped.
- Lead separately verified existing Catalog grant-preservation contracts: 2 passed / 0 skipped. This verifies the existing shared contract only; Stage 01 did not observe a live grant.
- An initial unit run found one misplaced multi-marker case in the public-free classifier table; it was moved to the first-free classifier table. The focused node then passed 7 cases and the full Discovery unit file passed. No implementation failure remained.
- Pytest reported existing pytest-asyncio / Python 3.14 deprecation warnings. No test was skipped.
- Full `ruff check src tests` passed after import sorting (Lead verification). Independent Reviewer verified the owned-file diff and reported BLOCKING 0. `git diff --check` was clean for owned files; the unrelated user-edited `watchlist.yaml` contains trailing whitespace and was not changed to avoid overwriting user work.

Capture/native/END tests were not rerun because Stage 01 did not change the capture adapter, native capture, END, packaging, or executor path; Lead supplied the existing baseline. Full `pytest -q` was not run for this site-local Discovery change.

### Modified implementation and documentation

- `src/screenshot_crawler/site_adapters/yanmaga/discovery.py`
- `src/screenshot_crawler/site_adapters/yanmaga/__init__.py`
- `tests/unit/test_yanmaga_discovery.py`
- `tests/integration/test_yanmaga_discovery_browser.py`
- `src/screenshot_crawler/site_adapters/yanmaga/README.md`
- `note/14_yanmaga.md`
- `runbooks/yanmaga-access/PROGRESS.md`

No cookies, auth state, personal account data, or full analytics request URLs were recorded.

### Stage 01 gate

**PASS (observed Discovery subset); independent BLOCKING 0.** Lead accepted the review. Stage 02 may start under its own Lead phase contract, but has not started. Stage 03 remains not verified and cannot be treated as implemented without a live wait-free signal and a separate bounded quota/ticket contract. Unknown behavior remains fail-closed.

## Stages 02-04

Not started. Record the Lead-approved scope, live evidence, tests, independent review, and gate outcome here before advancing each stage. Do not infer missing site behavior to satisfy a stage.

# Phase 3D Runtime Assessment

Date: 2026-09-29
Scope: Phase 3D-0 measurement and Phase 3D-1 targeted test-only timing assessment

This note is an assessment snapshot, not a test-policy authority. Phase 3D-0
was measurement-only. Phase 3D-1 made only explicit test-side strict-entry
settle/poll overrides in the BookWalker Adapter browser test; production code,
pytest configuration, dependency, fixture scope, assertions, and parameterized
cases remain unchanged.

## Executive Summary

| Item | Result |
|---|---:|
| Integration run 1 | 129 passed in 81.83s |
| Integration run 2 | 129 passed in 90.72s |
| Integration run 3 | 129 passed in 87.50s |
| Integration median / min / max | 87.50s / 81.83s / 90.72s |
| Phase 3D-0 full runtime | 817 passed in 120.47s with `-p no:warnings` |
| Phase 3D-0 collection | Unit 624 / Integration 129 / Research 64 / Total 817 |
| Dominant phase | `call`: 65.97s of 79.49s in the phase-instrumented Integration run |
| Safely removable time | 1.66s demonstrated in BookWalker Adapter; below High threshold |

The previous 80.75s Integration result was a valid observation but not a stable
baseline. The three-run median is 87.50s, with an 8.89s spread. Browser
lifecycle is no longer the dominant repeated cost. The largest file-level
call costs are BookWalker Discovery (16.91s), BookWalker Adapter (15.95s), and
Local Viewer (13.90s) in the phase-instrumented run.

The Phase 3D-0 slow tests mostly exercised meaningful DOM transition,
strict-entry settlement, end/grace behavior, image reconstruction, or
filesystem capture. Phase 3D-1 subsequently demonstrated a safe but modest
1.66s median saving by opting six successful strict-entry selection tests into
10ms initial settle / 20ms polling. This is below the 5s High threshold, so no
broader rollout is currently justified.

## Runtime Measurements

### Integration repetitions

Command:

```text
pytest -q -p no:warnings tests/integration --durations=50
```

All three runs passed 129 cases with zero skips or failures. The slowest-test
ordering varied between runs, especially for Local Viewer and browser startup,
so the median is used as the current runtime baseline rather than the earlier
single 80.75s result.

### Full suite

Command:

```text
pytest -q -p no:warnings --durations=50
```

Result: 817 passed in 120.47s. The collection increased from 816 to 817 due
to a current Research-side change outside this Phase; no test was added or
modified by this assessment.

### setup / call / teardown

A temporary in-process pytest hook recorded report durations and was not saved
in the repository. It measured 129 passed in 79.49s of test-reported phase
time:

| Phase | Time | Share of instrumented phase time |
|---|---:|---:|
| setup | 11.298s | 14.3% |
| call | 65.966s | 83.3% |
| teardown | 1.954s | 2.5% |
| total reported phases | 79.218s | 100% |

The small difference between the summed report phases and the process runtime
is pytest collection/plugin/process overhead. The conclusion is unchanged:
the test body (`call`) now dominates; fixture teardown is not a worthwhile
target.

### File-level timing

| File | Setup | Call | Teardown | Total |
|---|---:|---:|---:|---:|
| `test_access_guard_browser.py` | 0.459s | 0.931s | 0.149s | 1.539s |
| `test_bookwalker_adapter_browser.py` | 1.668s | 15.946s | 0.247s | 17.861s |
| `test_bookwalker_discovery_browser.py` | 1.451s | 16.914s | 0.258s | 18.623s |
| `test_bookwalker_original_capture_browser.py` | 0.614s | 0.285s | 0.084s | 0.983s |
| `test_local_viewer_flows.py` | 1.481s | 13.897s | 0.494s | 15.873s |
| `test_magapoke_adapter_browser.py` | 2.917s | 5.577s | 0.338s | 8.832s |
| `test_magapoke_discovery_browser.py` | 0.917s | 2.981s | 0.128s | 4.026s |
| `test_magapoke_local_viewer.py` | 0.612s | 5.143s | 0.121s | 5.876s |
| `test_mangaone_adapter_browser.py` | 0.705s | 3.689s | 0.090s | 4.484s |
| `test_mangaone_discovery_browser.py` | 0.474s | 0.603s | 0.045s | 1.123s |
| **Total** | **11.298s** | **65.966s** | **1.954s** | **79.218s** |

The Magapoke Adapter setup value includes its existing module-local browser
fixture. It is already module-scoped and is therefore outside the intended
Phase 3D optimization scope.

## Slowest Tests

The following Top 30 was captured in the phase-instrumented 79.49s run. Values
are per-test setup/call/teardown report durations; ordering can vary because
the three standard runs had an 81.83--90.72s range.

| # | Test | Setup | Call | Teardown | Total | Cause |
|---:|---|---:|---:|---:|---:|---|
| 1 | `magapoke_local_viewer.py::test_magapoke_reconstructs_jpeg_and_falls_back_to_screenshot` | .511 | 2.233 | .009 | 2.754 | D/E/A |
| 2 | `magapoke_local_viewer.py::test_magapoke_runner_stops_at_terminal_card_without_opening_next_episode` | .048 | 2.517 | .004 | 2.570 | A/D |
| 3 | `bookwalker_discovery_browser.py::test_bookwalker_full_reconciles_first_volume_after_later_release` | .053 | 2.421 | .005 | 2.480 | D/E |
| 4 | `bookwalker_discovery_browser.py::test_bookwalker_full_clean_exhaustion_reconciles_missing_source` | .065 | 2.320 | .005 | 2.390 | D/E |
| 5 | `bookwalker_adapter_browser.py::test_bookwalker_strict_quota_clicks_only_maruyomi` | .420 | 1.362 | .007 | 1.789 | A/D |
| 6 | `bookwalker_discovery_browser.py::test_bookwalker_incremental_stable_boundary_via_service[initial0-observed0]` | .066 | 1.698 | .004 | 1.768 | A/D |
| 7 | `local_viewer_flows.py::test_mangaone_unknown_after_image_and_viewer_disappear_times_out` | .047 | 1.299 | .394 | 1.740 | A |
| 8 | `local_viewer_flows.py::test_mangaone_graceful_end_and_chapter_change_are_distinct` | .043 | 1.658 | .004 | 1.704 | A |
| 9 | `access_guard_browser.py::test_visible_captcha_providers_stop_but_hidden_provider_does_not` | .459 | .931 | .149 | 1.539 | D |
| 10 | `bookwalker_adapter_browser.py::test_bookwalker_strict_waits_for_delayed_maruyomi` | .048 | 1.424 | .006 | 1.479 | A/B |
| 11 | `bookwalker_adapter_browser.py::test_bookwalker_strict_waits_for_transient_duplicate_to_settle` | .044 | 1.427 | .004 | 1.476 | A/B |
| 12 | `mangaone_adapter_browser.py::test_mangaone_quota_entry_waits_for_async_button` | .049 | 1.409 | .005 | 1.463 | A/B |
| 13 | `bookwalker_adapter_browser.py::test_bookwalker_strict_overlapping_scopes_count_same_element_once` | .047 | 1.370 | .004 | 1.422 | A/D |
| 14 | `local_viewer_flows.py::test_mangaone_offscreen_terminal_marker_does_not_become_end` | .049 | 1.356 | .005 | 1.411 | A |
| 15 | `bookwalker_adapter_browser.py::test_bookwalker_strict_direct_clicks_only_owned` | .057 | 1.302 | .005 | 1.364 | A/D |
| 16 | `bookwalker_adapter_browser.py::test_bookwalker_strict_direct_clicks_purchased_owned_control` | .053 | 1.297 | .004 | 1.354 | A/D |
| 17 | `bookwalker_adapter_browser.py::test_bookwalker_strict_direct_allows_owned_without_control_uuid` | .048 | 1.284 | .007 | 1.339 | A/D |
| 18 | `bookwalker_adapter_browser.py::test_bookwalker_strict_uuid_comparison_is_case_insensitive` | .047 | 1.275 | .004 | 1.326 | A/D |
| 19 | `bookwalker_discovery_browser.py::test_bookwalker_special_card_does_not_use_hash_number_as_order_and_never_clicks` | .053 | 1.241 | .004 | 1.299 | D |
| 20 | `mangaone_adapter_browser.py::test_mangaone_quota_entry_clicks_observed_button_once` | .423 | .808 | .006 | 1.237 | A/D |
| 21 | `bookwalker_discovery_browser.py::test_bookwalker_discovery_scans_series_pages_and_product_controls` | .048 | 1.119 | .005 | 1.173 | A/D |
| 22 | `bookwalker_discovery_browser.py::test_bookwalker_incremental_stable_boundary_via_service[initial2-observed2]` | .046 | 1.079 | .005 | 1.130 | A/D |
| 23 | `local_viewer_flows.py::test_mangaone_terminal_marker_on_next_chapter_is_not_end` | .053 | 1.063 | .007 | 1.123 | A/B |
| 24 | `mangaone_discovery_browser.py::test_mangaone_discovery_scans_pages_and_maps_cards` | .474 | .603 | .045 | 1.123 | D |
| 25 | `local_viewer_flows.py::test_mangaone_visible_terminal_marker_becomes_end[img]` | .081 | 1.018 | .007 | 1.106 | A |
| 26 | `bookwalker_discovery_browser.py::test_bookwalker_incremental_stable_boundary_via_service[initial1-observed1]` | .058 | 1.041 | .005 | 1.103 | A/D |
| 27 | `local_viewer_flows.py::test_mangaone_terminal_marker_wins_over_transient_page_identity` | .079 | .954 | .005 | 1.038 | A/B |
| 28 | `local_viewer_flows.py::test_mangaone_image_gap_becomes_end_after_grace_period` | .069 | .965 | .004 | 1.038 | A |
| 29 | `magapoke_discovery_browser.py::test_magapoke_full_discovery_expands_validates_and_syncs_catalog` | .530 | .494 | .007 | 1.031 | D/E |
| 30 | `local_viewer_flows.py::test_mangaone_visible_terminal_marker_becomes_end[div]` | .052 | .940 | .010 | 1.003 | A |

The standard runs additionally surfaced `test_runner_local_dom_exact_max_pages_can_stop`
and `test_runner_local_dom_state_flows[...]` at approximately 5.5--5.6s in one
run. Their implementation path is capture plus temporary filesystem output and
local DOM state transitions; they did not remain consistently slow in the
phase-instrumented run. The AccessGuard case also peaked at 4.16s in one run,
while its representative call is under 1s and consists of four synthetic DOM
checks. These are runtime variance and browser setup effects, not evidence of a
new fixed timeout.

## Cause Classification

### A. Intentional timeout, grace, or polling

This is the largest recurring category. Manga ONE slow tests use the existing
Phase 3B values (`page_change_timeout_ms=500` and `end_grace_ms=200`) and
100ms polling. The unknown/offscreen cases intentionally wait for failure or
end classification. Magapoke terminal handling uses a 500ms test timeout,
render-stability checks, bounded retry, and 100ms polling. BookWalker strict
entry uses a 250ms initial settle, 100ms candidate polling, and two stable
samples. BookWalker Discovery uses bounded 100ms listing/product polling.

These waits are part of the behavior being tested. They should not be shortened
only to improve runtime.

### B. Fixture-side artificial delay

Several tests deliberately use browser `setTimeout` values of 50ms, 150ms,
300ms, or 350ms to prove delayed DOM/control settlement. The local viewer
fixture uses a default 20ms transition and a 10ms test polling interval. These
delays are small and semantic; removing them would weaken the scenario.

### C. Production retry logic exercised in real time

Local Viewer same-content and loading paths exercise bounded Runner retries and
same-content guards. Magapoke `wait_for_change()` can retry the next action and
re-check render stability. These costs are bounded and generally below the
largest file-level costs, but they are contract paths rather than accidental
sleep.

### D. Browser / DOM processing

BookWalker Adapter and Discovery dominate call time through locator traversal,
DOM metadata evaluation, listing/product navigation, strict candidate
settlement, pagination, and account/control classification. AccessGuard scans
several synthetic CAPTCHA DOM variants. Manga ONE Discovery and Adapter also
perform real Locator/DOM checks. This category is not removable without
changing the browser boundary being tested.

### E. Filesystem / image processing

Magapoke local JPEG reconstruction decodes/reconstructs image bytes, compares
the result with a screenshot fallback, and runs capture/output logic. Local
Viewer runner tests capture PNGs and write manifests/progress under `tmp_path`.
BookWalker Discovery also performs SQLite Catalog reconciliation in its full
tests. These are real local I/O or image contracts, not browser lifecycle.

### F. Unavoidable contract timing

The delayed-control, strict uniqueness, end-grace, timeout, and stable-boundary
tests intentionally assert wall-clock-adjacent behavior. Their timing is not
currently separable from the contract with high confidence.

The Phase 3B values were not changed or re-evaluated as optimization targets:

```text
Manga ONE missing: page_change_timeout_ms=200
Manga ONE grace: page_change_timeout_ms=500, end_grace_ms=200
Local Viewer: page_turn_delay_ms=0
Magapoke terminal: page_change_timeout_ms=500, page_turn_delay_ms=0
```

## Focused Analysis

### Local Viewer

`test_local_viewer_flows.py` measured 15.873s in the instrumented run, with
13.897s in call. The remaining cost comes from real Browser/DOM transitions,
capture and filesystem output, Manga ONE end/grace and timeout scenarios, and
the local fixture's bounded 10ms loading polling. `page_turn_delay_ms=0` is
already applied. The 500ms/200ms Manga ONE values are already Phase 3B
test-specific values and must not be shortened further.

There is no broad fixed sleep dominating the file. The 5.5--5.6s observations
for max-pages/state-flow cases were isolated outliers and included capture or
filesystem work. A targeted follow-up could instrument capture versus
`wait_for_change`, but an immediate optimization is not justified.

### BookWalker Discovery and Adapter

BookWalker Discovery measured 18.623s total and 16.914s call. Its full
reconciliation tests combine listing traversal, product-page observation,
access classification, and SQLite Catalog reconciliation. Its delayed-control
tests use the 300ms synthetic DOM delay and the production 100ms polling / 500ms
settlement rules.

BookWalker Adapter measured 17.861s total and 15.946s call. Strict-entry tests
deliberately exercise the 250ms initial settle, transient duplicate replacement
after 350ms, delayed Maruyomi insertion after 300ms, stable candidate samples,
and DOM identity/UUID filtering. These are fail-closed access semantics, so a
timing reduction has medium-to-high semantic and flakiness risk.

### Magapoke Adapter and Local Viewer

The Magapoke Adapter measured 8.832s total, including 2.917s setup and 5.577s
call. Its browser lifecycle is already module-scoped; the remaining call cost
is canvas/render-ready polling, bounded transition checks, and capture paths.
The Magapoke Local Viewer measured 5.876s, with the JPEG reconstruction/fallback
test and terminal-card runner accounting for most of it. Image processing and
the 500ms terminal contract make this a low-to-medium ROI target, not a safe
large saving.

## Optimization Candidates

| Candidate | Current cost | Estimated safe saving | Complexity | Flakiness / semantic risk | Recommendation |
|---|---:|---:|---|---|---|
| Local Viewer wait/capture attribution | 15.873s | 0--2s | Medium | Medium | Instrument only if Phase 3D-1 is opened; do not shorten Phase 3B waits |
| BookWalker Discovery wait decomposition | 18.623s | 1--3s | Medium | Medium | Conditional Phase 3D-2; preserve listing/product settlement |
| BookWalker strict-entry test-side profile | 17.861s -> 16.32s median | 1.66s demonstrated | Low | Low for selected tests; high if applied broadly | Completed in Phase 3D-1; do not broaden without new evidence |
| Magapoke Local Viewer image path | 5.876s | 0.5--1.5s | Medium | Medium/High | Low priority; retain JPEG/screenshot semantics |
| Magapoke Adapter residual polling | 8.832s | 0--1s | Medium | High | Stop; browser lifecycle is already optimized |
| Manga ONE Adapter / Discovery | 5.607s combined | <1s | Low/Medium | Medium | Stop; waits and DOM checks are contract coverage |
| AccessGuard / Original Capture | 2.522s combined | <0.5s | Low | Medium | Stop |

No candidate meets the Phase 3D High threshold of at least 5s safe saving
without semantic change. Phase 3D-1 demonstrated 1.66s on the BookWalker
Adapter file, which is useful but remains below the threshold for a wider
optimization campaign.

## Recommended Phase 3D Plan

### Phase 3D-1: BookWalker strict-entry test-only timing (completed)

The six successful, timing-independent strict-entry selection tests now pass
explicit test-side values of `initial_settle_ms=10` and
`poll_interval_ms=20`. The adapter still requires
`strict_candidate_stability_samples=2`; only the initial settle and interval
were overridden. The timing-dependent delayed-Maruyomi and transient-duplicate
tests retain their 300ms/350ms fixture delays and production-like timing
semantics.

#### 26-case classification

The classification is by expanded pytest case, so the parameterized groups are
counted individually.

**A. Timing-independent (24 cases)**

- Fast profile, six successful selection cases: `strict_quota_clicks_only_maruyomi`,
  `strict_direct_clicks_only_owned`, `strict_direct_clicks_purchased_owned_control`,
  `strict_direct_allows_owned_without_control_uuid`,
  `strict_uuid_comparison_is_case_insensitive`, and
  `auto_trial_fallback_still_navigates`.
- Selection/rejection semantics, retained at the helper's 250ms/100ms profile
  after measurement: `strict_direct_rejects_maruyomi_only` (1),
  `strict_direct_multiple_owned_controls_fail` (1),
  `strict_trial_only_fails_before_click` (2),
  `strict_subscription_only_fails` (2),
  `strict_generic_viewer_only_fails` (2),
  `strict_wrong_strategy_does_not_fallback` (1),
  `strict_multiple_matching_controls_fail` (1),
  `strict_overlapping_scopes_count_same_element_once` (1),
  `strict_uuid_mismatch_is_excluded` (1),
  `strict_requires_product_identity_before_candidates` (2), and
  `strict_rejects_already_viewer_url` (1).
- Cover/canvas and local byte behavior: `keeps_first_page_cover_spread_as_one_target`,
  `crops_first_page_cover_to_draw_geometry`, and
  `crops_cover_from_pixels_when_geometry_is_missing` (3).

**B. Timing-dependent (2 cases)**

- `strict_waits_for_transient_duplicate_to_settle` (350ms duplicate
  replacement fixture).
- `strict_waits_for_delayed_maruyomi` (300ms delayed-control fixture).

The two B cases keep their fixture delays and production-like timing
relationship. The A cases that retain 250ms/100ms are still semantically
timing-independent, but broad fast polling caused more DOM scans in persistent
rejection paths and did not produce a safe saving.

The helper default remains `250ms` initial settle and `100ms` polling. An
experiment applying the faster interval to all helper calls made persistent
rejection tests slower because it caused more DOM candidate scans. The final
change therefore opts in only the successful selection tests, rather than
using a hidden test mode or changing production defaults.

Before/after medians for the 26-case file were 17.98s and 16.32s
respectively; the three after runs were 16.32s, 16.23s, and 17.36s. The
Integration suite then passed 129 cases in 87.80s, and the current full suite
passed 821 cases in 115.64s. The current collection is Unit 624 / Integration
129 / Research 68 / Total 821; the Research increase is outside this Phase.

### Phase 3D-2: Local Viewer targeted attribution (conditional)

If further work is desired, first measure capture, filesystem, and
`wait_for_change` separately for the two Local Viewer outlier groups. Only a
non-contract cost should be optimized. Keep `page_turn_delay_ms=0`, existing
500ms/200ms Manga ONE settings, same-content guards, max-pages guards, and
fresh BrowserContext/Page isolation unchanged.

### Phase 3D-3: BookWalker Discovery wait decomposition (conditional)

Measure strict-entry candidate polling separately from listing/product route and
Catalog work. Any change must preserve delayed-control, duplicate settlement,
stable candidate, UUID filtering, and fail-closed behavior. The current data
does not yet justify implementation.

### Phase 3D-4: Residual cleanup / stop

Do not introduce session-scoped Browser, shared Context/Page, xdist, or parallel
execution for this runtime range. If targeted attribution cannot demonstrate a
contract-neutral saving of at least 2--5s, stop Phase 3D optimization and accept
the 80--90s Integration range as the cost of meaningful browser-boundary
coverage.

## Stop Condition

Stop runtime optimization when all of the following remain true:

- Integration median is approximately 80--90s with normal variance.
- The slowest tests are dominated by intentional wait/grace/polling, DOM
  settlement, image processing, or filesystem contracts.
- No single candidate demonstrates at least 5s safe saving.
- Further savings require changing timeout/grace/polling semantics, browser
  isolation, or adding fixture complexity.

The Phase 3D-0 measurements satisfied this stop condition provisionally.
Phase 3D-1 then confirmed a narrow, contract-preserving 1.66s saving, but no
High-threshold candidate. Stop after this targeted Phase 3D-1 result unless a
future measurement demonstrates at least 5s of safe saving with comparable
semantic and flakiness risk. Do not proceed to BookWalker Discovery or Local
Viewer wait changes by default.

## Verification

- Phase 3D-0: `pytest -q -p no:warnings tests/integration --durations=50`: 3 runs, all 129 passed
- Phase 3D-1 target: 3 runs, 26 passed each; median 16.32s
- Phase 3D-1 timing cases: delayed Maruyomi and transient duplicate passed individually
- Phase 3D-1 Integration: 129 passed in 87.80s
- Phase 3D-1 full: 821 passed in 115.64s
- `pytest --collect-only -q`: 821 collected
- Current collection breakdown: Unit 624 / Integration 129 / Research 68
- `uv run ruff check src tests`: passed
- Chromium unavailable skips: 0 observed
- Temporary phase timing hook: not saved

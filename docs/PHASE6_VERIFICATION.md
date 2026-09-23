# Phase 6 Verification

## Summary

- Verification date: 2026-09-23 (JST)
- Verification target commit: `4b42b7c` (`Add Jump+ J2 reconstruction PoC`)
- Automated status: **PASS**
- Live status: **PARTIAL**
- Final Phase 6 status: **AUTOMATED VERIFIED / LIVE PARTIAL**

Phase 6 was treated as a regression and verification phase. No new access
control, pacing, resource, or anti-detection behavior was added. The latest
main also contains unrelated Jump Plus probe changes; those files were not
modified by this verification work.

## Environment and commands

The verification used the repository Python 3.12 virtual environment:

```text
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check src tests
```

Results:

- `pytest -q`: **647 passed, 2341 warnings**
- `ruff check src tests`: **PASS — All checks passed!**

The checked-in `catalog.sqlite` was schema v4 while the current application
expects v5. For read-only live planning, a temporary copy was migrated with
the normal CLI migration command. The source Catalog was not changed.

## Automated regression matrix

| Area | Result | Evidence |
| --- | --- | --- |
| CONTENT save/progress -> page delay -> `go_next` -> wait | PASS | `tests/unit/test_core_features.py::test_runner_persists_then_paces_then_advances_once_per_spread` |
| CONTENT pacing aborts a new navigation after fatal stop | PASS | `tests/unit/test_core_features.py::test_runner_does_not_start_content_navigation_after_pacing_stop` |
| AD navigation checks AccessGuard first | PASS | `tests/unit/test_core_features.py::test_runner_checks_access_before_ad_navigation` |
| Pacing excluded from page-change timeout budget | PASS | `tests/unit/test_core_features.py::test_runner_page_delay_is_outside_wait_timeout_budget` |
| Candidate pacing only after close and between site candidates | PASS | `tests/unit/test_cli.py::test_batch_candidate_delay_runs_after_close_only_between_site_candidates` |
| Empty/local-only candidates do not sleep | PASS | `tests/unit/test_cli.py::test_batch_empty_candidate_list_has_no_candidate_delay`, `test_grant_only_local_skip_does_not_open_page_or_delay` |
| Relevant 403/429 fatal and third-party filtering | PASS | `tests/unit/test_access_guard.py::test_relevant_403_is_fatal_and_unrelated_403_is_not`, `test_relevant_429_records_retry_after_and_stop_flag_can_disable_stop` |
| Explicit challenge and visible CAPTCHA classification | PASS | `tests/unit/test_access_guard.py::test_explicit_challenge_marker_has_distinct_reason`, `test_visible_captcha_providers_stop_but_hidden_provider_does_not` |
| Fatal stop does not start the next candidate/delay | PASS | `tests/unit/test_access_guard.py::test_batch_access_stop_does_not_start_remaining_candidate_or_delay` |
| Incremental metrics flush | PASS | `tests/unit/test_access_guard.py::test_metrics_writer_flushes_request_candidate_and_summary_records` |
| Adapter call timeout/retry boundary | PASS | `tests/unit/test_core_features.py::test_adapter_call_preserves_inner_page_change_timeout`, `test_adapter_call_grace_allows_inner_timeout_to_surface`, `test_adapter_call_timeout_still_bounds_hung_adapter` |
| Generic resource contract and unsupported-resource fail-closed | PASS | `tests/unit/test_batch.py::test_access_resource_contract_is_policy_owned`, `test_planner_rejects_unsupported_explicit_resource`, `test_unsupported_access_resource_is_explicitly_rejected` |
| Magapoke Work old-to-new Batch ordering | PASS | `tests/unit/test_batch.py::test_magapoke_batch_orders_each_work_old_to_new_without_reversing_discovery` |
| Magapoke Work/Premium Policy order | PASS | `tests/unit/test_magapoke_policy.py::test_premium_ticket_pass_groups_all_pending_episodes_by_oldest_work`, `test_magapoke_policy_declares_premium_as_following_resource_pass` |
| `all` pass order, replan, shared limit | PASS | `tests/unit/test_cli.py::test_grant_only_all_uses_policy_order_replans_and_shares_limit` |
| Resource exhaustion vs next pass | PASS | `tests/unit/test_cli.py::test_grant_only_all_moves_to_next_policy_pass_after_resource_exhaustion` |
| Work cooldown local skip | PASS | `tests/unit/test_magapoke_policy.py::test_grant_only_work_ticket_cooldown_is_strict_at_expiry`, `tests/unit/test_cli.py::test_grant_only_local_skip_does_not_open_page_or_delay` |
| Confirmed Work/Premium persistence after later failure | PASS | `tests/unit/test_batch_executor.py::test_grant_only_consumption_survives_later_failure`, `test_grant_only_premium_consumption_survives_later_failure`, `test_premium_ticket_consumption_and_later_failure_are_persisted` |
| Resource mismatch and unconfirmed consumption fail closed | PASS | `tests/unit/test_batch_executor.py::test_mismatched_observed_resource_fails_closed_without_persistence`, `test_grant_only_premium_mismatch_does_not_persist_work_consumption`, `test_grant_only_unconfirmed_failure_does_not_record_consumption` |
| Grant-only no capture/package/completion | PASS | `tests/unit/test_batch_executor.py::test_grant_only_work_ticket_persists_state_without_completion_or_artifact`, `test_grant_only_premium_ticket_persists_source_only` |
| Magapoke Premium live balance/priority/zero/ambiguous UI | PASS | `tests/unit/test_magapoke_adapter.py::test_premium_ticket_click_requires_semantic_positive_balance_and_confirms`, `test_zero_premium_balance_is_expected_exhaustion_without_click`, `test_premium_balance_unknown_fails_closed_without_click`, `test_premium_request_skips_work_only_control_without_fallback` |
| Magapoke native capture and retry | PASS | `tests/integration/test_magapoke_local_viewer.py`, `tests/unit/test_magapoke_adapter.py::test_adapter_retries_current_spread_after_retryable_observation_failure` |
| Manga ONE source retry/native WebP/fallback/direct-quota entry | PASS | `tests/unit/test_mangaone_adapter.py::test_mangaone_source_capture_retries_after_one_transient_failure`, `test_mangaone_source_capture_falls_back_after_all_attempts_fail`, `test_mangaone_quota_entry_clicks_observed_button_once` |
| BookWalker navigation retry/native capture/quota behavior | PASS | `tests/unit/test_bookwalker_adapter.py::test_bookwalker_wait_for_change_alternates_click_and_arrow_retries`, `tests/unit/test_bookwalker_original_capture.py::test_original_capture_retries_twice_then_returns_native_fallback`, `tests/unit/test_bookwalker_batch.py` |
| Catalog v5 fresh/migration/backup/atomic state | PASS | `tests/unit/test_catalog_migrations.py::test_current_v5_migration_is_noop_without_backup`, `test_production_v3_to_v5_migration_preserves_rows_and_creates_backup`, `tests/unit/test_catalog.py::test_quota_resource_state_and_source_grant_commit_atomically` |

The inventory found no important uncovered Phase 1–5 regression requiring a
new test. Existing integration fixtures cover local viewer navigation and
Magapoke native capture; site-specific live runs are listed separately below.

## Read-only live planning

The original `catalog.sqlite` was not run because the current CLI correctly
rejects schema v4 until migration. A temporary copy was migrated using:

```text
python -m screenshot_crawler.cli catalog migrate --catalog <temporary-copy> --backup-dir <temporary-backup>
```

The migration created a pre-migration backup and completed v4 -> v5. On that
copy, all three read-only plans completed:

| Site | Scenario | Result | Observation |
| --- | --- | --- | --- |
| Magapoke | `batch plan` | PASS | 1 quota candidate; 143 skipped; Premium potential pass reported |
| Manga ONE | `batch plan` | PASS | 4 quota candidates; 1847 skipped; quota exhausted locally |
| BookWalker | `batch plan` | PASS | 1 quota candidate; 156 skipped; quota exhausted locally |

The plan output is not a live access grant or resource availability proof.

## Live verification matrix

| Site | Scenario | Result | Reason |
| --- | --- | --- | --- |
| Magapoke | normal direct/free Batch | NOT RUN — no direct candidate in the verification Catalog | The migrated plan exposed only a quota candidate; no free/active-grant candidate was available for a non-consuming run. |
| Magapoke | Work Ticket grant-only | NOT RUN — would consume scarce resource | No live Work Ticket was intentionally consumed during regression verification. |
| Magapoke | Premium Ticket grant-only | NOT RUN — would consume scarce resource | No live Premium Ticket was intentionally consumed during regression verification. |
| Magapoke | `grant-only all` | NOT RUN — would consume scarce resource | Work/Premium consumption was not forced merely to mark the phase complete. |
| Manga ONE | normal Batch | NOT RUN — quota/resource consumption risk | The plan exposed quota candidates but no safe direct candidate. |
| BookWalker | normal Batch | NOT RUN — quota/resource consumption risk | The plan exposed quota candidates but no safe direct candidate. |
| All sites | real-browser UI/access signal verification | NOT RUN — browser environment unavailable | The in-app browser bootstrap did not expose the required browser agent in this environment. No cookies, storage state, or profile data was inspected. |

These are not failures. Earlier site-specific live observations remain
documented in the corresponding site notes, but they are not relabeled as a
new Phase 6 cross-site run.

## Metrics, migration, and architecture checks

- Metrics: existing tests confirm request/candidate/summary JSONL records are
  appended and flushed incrementally, including abnormal-stop coverage. The
  metrics path remains `output/metrics/*.jsonl`; metrics do not read response
  bodies solely for accounting.
- Catalog migration: fresh v5 initialization, v4/v5 behavior, backup and
  v3 -> v5 production migration are covered by the migration suite. The
  checked-in v4 database was only copied before migration.
- Generic architecture scan: no concrete `work_ticket` or `premium_ticket`
  resource branch was found in `src/screenshot_crawler/core`,
  `src/screenshot_crawler/batch`, or `src/screenshot_crawler/cli.py`. The one
  match is the existing generic executor use of the configured
  `work_ticket_cooldown_hours` setting; it is not a resource-name orchestration
  branch. Existing site-specific planner ordering and artifact-collision
  handling were not changed.
- Anti-pattern scan: Phase 6 added no session-size cutoff, browser restart,
  random jitter, proxy/UA/fingerprint rotation, CAPTCHA solving, or challenge
  bypass.

## Issues and fixes

No Phase 6 implementation bug was found. No source-code fix was necessary.
The only environment issue was the checked-in schema-v4 Catalog and the
unavailable in-app browser bootstrap; both are recorded above without changing
the user's Catalog or browser state.

## Limitations and Phase 6 status

Automated regression is complete and green across the three site adapters.
Live verification is intentionally partial: normal live Batch and actual Work
or Premium consumption were not run because the available candidates/resources
were quota-limited or would consume scarce access, and browser bootstrap was
unavailable. Therefore this repository records **Phase 6: AUTOMATED VERIFIED /
LIVE PARTIAL**, not full live verification.

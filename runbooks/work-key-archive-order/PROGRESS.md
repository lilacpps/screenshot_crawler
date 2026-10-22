# Work-key acquisition scope / archive ordering — Progress

> Status: **PLANNED / NOT IMPLEMENTED** (2026-10-22)
> Main runbook: [README.md](README.md)
> Baseline: GitHub main inspected 2026-10-22. Planning only; no production code or live Catalog changed.

## Phase gates

| Phase | Status | Evidence / next action |
|---|---|---|
| P0: Current contract / fixture | NOT STARTED | Verify v6 behavior, bounded scope, site-native positions, existing ZIP/renumber |
| P1: Watchlist + Catalog v7 | NOT STARTED | archive_order, acquisition_enabled, scope-sync fingerprint, migration |
| P2: Scope reconciler | NOT STARTED | dry-run/apply, new/old/orphan Sources, fail-closed |
| P3: Batch integration | NOT STARTED | normal/grant-only/deferred/replan filtering and consistency gate |
| P4: Naming + renumber | NOT STARTED | work-key cross-site numbering and ZIP/status/Artifact transaction checks |
| P5: Verification + rollout | NOT STARTED | isolated full test, selected-work dry-run, backup, docs/note sync |

## Adopted constraints

- No site-crossing Item merge; stable Source.discovery_key; no same-site key reparenting.
- Watchlist.discovery_scope is the acquisition scope authority; no separate acquisition_scope YAML.
- archive_order opt-in is whole-work: all keys set or none.
- Exclusion does not change Item.status, Source.available/access_mode, source history or existing artifacts.
- Incomplete scope sync, unknown boundary, stale fingerprint, and filename collision fail closed.
- No automatic rename, delete, purchase or quota consumption during verification.
- GUI follows in a separate workstream after backend is stable.

## Update contract

After each phase record: commit/ref, files touched, design deviations, test command/results,
skipped/failed tests and reasons, integration/live verification limits, reviewer findings,
and the next blocking issue. Do not label planning as implemented.

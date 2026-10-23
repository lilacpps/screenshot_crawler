# Windows GUI P2/P3 — Implementation Progress

> **PLANNED / NOT IMPLEMENTED** (2026-10-23).
>
> [Master runbook](README.md). P2 gate must pass before P3. Stop after P3 for user GUI review. This commit creates **docs only**, no production functionality or live Catalog changes.

## Baseline

- 2026-10-23 `main` commit `5382b046bd93ed7848721a966a60229e3f1ef9c8` contains merged P1 PySide6 GUI.
- P1 selected-key set is already stable across Site/Work views. P1's Catalog read is strict read-only with WAL rejection.
- BatchPlanner currently plans whole site; P2 must add selected_keys before quota allocation and propagate through all replan/resources.
- Existing DiscoveryService and BatchExecutor have Catalog job locking; P3 must preserve it.
- This runbook does **not** include Watchlist editing, Site Source reassignment, source deletion, Scope Sync apply, ZIP renumber, or scheduling.

## Gates

| Stage | Status | Implementation and review evidence |
|---|---|---|
| P2.0 Contract and call graph | NOT STARTED | Inventory all plan/replan/Grant paths, classifier/Quota rules |
| P2.1 Selected-key Batch Planner / CLI | NOT STARTED | Filter before quota allocation, no-selection ≠ all-site, legacy preserved |
| P2.2 Grant-only and resolver selector | NOT STARTED | All resource passes/replans preserve selected_keys |
| P2.3 Discover and preview | NOT STARTED | Key-specific full/incremental, read-only preview, drift gate |
| P2.4 GUI dialogs and security gate | NOT STARTED | Selected keys, explicit confirm, independent review / BLOCKING=0 |
| **P2 safety gate** | **NOT STARTED** | **Do not enter P3 until passed** |
| P3.0 Durable Job schema | NOT STARTED | Independent job SQLite, idempotent event format |
| P3.1 Subprocess worker / Queue | NOT STARTED | One worker, site-serial, events, existing CDP/lock contract |
| P3.2 Cancellation and recovery | NOT STARTED | Cooperative stop, forced-kill warning, crash/unknown results |
| P3.3 JobsPage | NOT STARTED | History, progress, errors, manual retry as new Job |
| P3.4 Tests/Windows QA/review | NOT STARTED | Isolated E2E, Qt offscreen, screenshots, docs/note sync |
| **User UI review** | **WAITING FOR P3** | Stop; P4/P5 remain out of scope |

## Non-negotiable rules

1. GUI selection applies to *every* planning, re-planning, deferred, all-resource, grant-only and execution path.
2. Site-wide consumed quota state remains authoritative; do not recalculate slots from selected keys alone.
3. Preview is read-only and must recheck critical changes before Browser/Quota access.
4. No actual paid actions or entitlement-consuming live tests without explicit user permission.
5. Cancellation request is not success; uncertain grant consumption forbids automatic retry.
6. Do not modify operational Catalog, Watchlist, Books or Archive as part of isolated verification.
7. Preserve P1 GUI and all backward-compatible CLI site-wide behavior.

## Record template (append per completed gate)

- Commit / branch / reviewed diff:
- Changed production and test files:
- Interface/contract changes and rationale:
- Security and Scope/Quota/Grant/replan verification:
- Targeted / affected / integration / full-suite / Ruff (pass, fail, skipped):
- Windows UI verification / screenshots:
- Reviewer findings (BLOCKING / NONBLOCKING), fixes and rerun:
- Non-Live testing and real-site limitations:
- Outstanding issues / next gate:

**Current status:** Planning documents written only; Codex implementation not yet started.

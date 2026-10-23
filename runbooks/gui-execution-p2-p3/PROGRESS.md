# Windows GUI P2/P3 — Implementation Progress

> **P2 IMPLEMENTED / SAFETY REVIEW PASS; P3 NEXT** (2026-10-24).
>
> [Master runbook](README.md). P2 gate has passed before P3. Stop after P3 for user GUI review. All execution verification uses isolated fixtures and mock site entry.

## Baseline

- 2026-10-23 `main` commit `5382b046bd93ed7848721a966a60229e3f1ef9c8` contains merged P1 PySide6 GUI.
- P1 selected-key set is already stable across Site/Work views. P1's Catalog read is strict read-only with WAL rejection.
- BatchPlanner currently plans whole site; P2 must add selected_keys before quota allocation and propagate through all replan/resources.
- Existing DiscoveryService and BatchExecutor have Catalog job locking; P3 must preserve it.
- This runbook does **not** include Watchlist editing, Site Source reassignment, source deletion, Scope Sync apply, ZIP renumber, or scheduling.

## Gates

| Stage | Status | Implementation and review evidence |
|---|---|---|
| P2.0 Contract and call graph | PASS | All plan/replan/Grant paths inventoried and reviewed |
| P2.1 Selected-key Batch Planner / CLI | PASS | Filter before quota allocation; empty selection stays empty; legacy preserved |
| P2.2 Grant-only and resolver selector | PASS | All resource passes/replans preserve selected_keys |
| P2.3 Discover and preview | PASS | Exact key execution, read-only plans, input/endpoint/output drift rejection |
| P2.4 GUI dialogs and security gate | PASS | Full/incremental, limits, per-site resources, explicit confirmation |
| **P2 safety gate** | **PASS — BLOCKING=0** | **Independent reviewer approved 2026-10-24; P3 authorized** |
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

**Current status:** P2 implemented and independently approved. P3 begins only after this gate; P4/P5 remain excluded.

## Implementer checkpoint — P2 selected execution (2026-10-24)

- Branch: `feat/gui-execution-p2-p3`; production work is isolated from the
  user's dirty `crawler.yaml`, `watchlist.yaml`, and Catalog lock file.
- Implemented `BatchPlanner.plan(selected_keys=...)`. Selection is validated
  against the Watchlist and site before candidate construction. Site-wide
  quota accounting, Work-wide archive positions, collision identity, and
  `acquisition_enabled`/Scope checks remain based on their existing authorities.
  `None` preserves legacy whole-site behavior; `[]` is an explicit empty plan.
- Added repeatable `batch plan/run --key`; all grant-only resource passes,
  deferred resolver input, post-grant re-plan, and additional resource passes
  carry the selector. Batch candidates retain `discovery_key` for execution
  revalidation.
- Added Qt-independent `ExecutionSelection`, `JobExecutionRequest`, and
  read-only `ExecutionPlanService` DTOs, plus the P2 confirmation dialog and a
  GUI worker entry. The preview uses a strict read-only Catalog facade,
  Inventory Scope status, archive/output preflight, and actual BatchPlanner
  plans. The subprocess worker acquires the Catalog job lock, rebuilds every
  selected site plan, compares the confirmation fingerprint, and only then
  calls the existing site operation; disabled Discover keys are skipped before
  BrowserSession creation. Grant-only confirmation explicitly warns that an
  entitlement may be consumed. Full/Incremental Discover and Resource/all
  controls are exposed in the GUI.
- Validation: `test_cli.py` + `test_batch.py`: 145 passed; selected-key planner
  tests: 3 passed; offscreen GUI smoke: 5 passed; Ruff and compileall passed.
  The default pytest temp/cache locations are inaccessible in this managed
  Windows workspace, so runs use `.tmp/<run>` as `--basetemp` and cache.
- P2 safety review is still pending independent Lead/Reviewer acceptance;
  P3 has not been started by this implementer. Live paid/ticket tests and the
  operational Catalog/Watchlist/Books remain unmodified.

## Implementer checkpoint update — selector safety regressions (2026-10-24)

- Added adversarial planner coverage for a one-slot site quota: a selected
  later Work receives the available slot even when an unselected Work sorts
  first, while a quota consumed by that unselected Work correctly leaves the
  selected plan with zero quota and no candidates.
- Added same-Work, multi-key archive coverage. A subset plan keeps the selected
  key's Work-wide archive prefix from the complete plan; it does not renumber
  the subset.
- Validation: `test_cli.py` + `test_batch.py` + `test_batch_selected_keys.py` +
  `test_gui_smoke.py`: **156 passed**, 397 warnings. Selected-key module:
  **6 passed**. The final worker serialization and CLI selected-scope gate
  run increased the combined affected set to **177 passed**, 415 warnings.
  `python -m ruff check src tests` and `compileall` passed.
- CLI `batch run --key` now validates each selected Work's current Scope sync
  while holding the Catalog job lock, before endpoint resolution or browser
  connection. This complements the worker's global multi-site preflight.
- Confirmed requests are serialized through a JSON-safe helper. The worker
  rejects missing/altered selection projections and confirmation fingerprints,
  keeps a per-site Grant-only Resource mapping, and treats incomplete Discover
  results as failures. Preview fingerprints include complete input-file hashes
  (Catalog, Watchlist, runtime, and env), resolved output paths, execution
  settings, and candidate access/archive fields; read-only preview hashes are
  checked before and after planning.
- GUI exposes a maximum-candidate control and per-selected-site Resource
  selectors. The worker passes the explicit metrics root through to Batch
  metrics instead of relying on a hardcoded path.
- Worker preflight validates Discover mode and every Watchlist key-to-site
  projection before invoking the discovery target, including the disabled-key
  skip path.
- Added real isolated worker drift coverage using generated Catalog/Watchlist
  inputs: post-confirmation Watchlist, runtime, env, Catalog, and ZIP collision
  changes are rejected before the mocked site entry. Missing env files follow
  existing CLI semantics (`{}`), and effective process/env CDP endpoint
  identities are hashed without persisting endpoint values.
- No P2 command intentionally targeted the operational Catalog, Watchlist, or
  Books directory. During the shared-worktree audit, an external Hanayume
  refresh was observed in the operational Catalog; it is not attributed to
  this work and was preserved without revert. Independent P2 safety review
  remains the gate. P3 remains unstarted.

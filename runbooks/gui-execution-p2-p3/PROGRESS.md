# Windows GUI P2/P3 — Implementation Progress

> **P2/P3 IMPLEMENTED / INDEPENDENT SAFETY REVIEW PASS / FULL TEST RUNNING** (2026-10-24).
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
| P3.0 Durable Job schema | PASS | Separate versioned management SQLite, no auto-migration, idempotent JSONL import |
| P3.1 Subprocess worker / Queue | PASS | Single controller claim, start barrier, site-serial worker, structured events |
| P3.2 Cancellation and recovery | PASS | Cooperative/force distinction, identity gate, interrupted/unknown consumption, no auto-retry |
| P3.3 JobsPage | PASS | Queue/history/tasks/events/log paths, stop/cancel, fresh-preview rerun |
| P3.4 Tests/Windows QA/review | FULL TEST RUNNING | Latest affected tests 255 passed; native Windows captures and final independent review PASS |
| **User UI review** | **WAITING FOR FULL TEST RESULT** | Stop after P3; P4/P5 remain out of scope |

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

**Current status:** P2 independently approved (BLOCKING=0, checkpoint `cc7a4bb`). P3 and the final Resource-selection corrections independently passed (BLOCKING=0). Latest affected tests and native Windows screenshot inspection passed; the broad full suite is still running. P4/P5 remain excluded.

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

## Implementer checkpoint — P3 queue and job management (2026-10-24)

- Added `management.sqlite` schema v1 in `management/jobs.py`, separate from
  Catalog. Existing/unsupported or corrupt management databases fail closed;
  the store never migrates or overwrites them. A one-shot SQLite backup API
  refuses to overwrite an existing destination. Jobs retain redacted request
  metadata, per-site tasks, metrics/log references, and event-derived counts.
- Added append-only worker `events.jsonl` with complete-line import,
  idempotent event IDs/sequences, partial-tail handling, task progress updates,
  and tri-state `resource_consumed`. Token-like fields and explicit CDP
  endpoint values are excluded from persisted metadata; an in-memory GUI
  request may pass the endpoint to the child through process environment only.
- Added `JobController` and `job_worker`: one in-process and stable OS advisory
  lease claim (Windows `msvcrt` / POSIX `flock`), explicit queue start, a child
  start barrier before Catalog access, PID/token
  plus OS process-start identity checks, site-serial P2 execution, structured
  candidate / grant / task events, cooperative cancel checkpoints, force-stop
  as `interrupted` with unknown consumption, and no automatic restart after GUI
  restart. CLI candidate loops now emit events without parsing stdout.
- Added `JobsPage` to the existing GUI and connected confirmation to the
  persistent queue. History shows task/event state and exact metrics/log
  references; stop, queued-cancel, explicit Resume, and confirmation-gated
  force termination are distinct, and rerun starts from a new current
  preview/job. P1 selection/search/focus model remains in place. The GUI CLI
  accepts `--management` for an isolated management DB path.
- Isolated validation so far: management/worker/CLI/P2/Qt affected tests pass
  (latest targeted run: 141 passed, plus 18 management/job lifecycle tests and
  29 execution worker tests in the focused rerun), and Ruff passes. A Windows-style actual
  worker subprocess E2E with two synthetic sites completed sequentially with
  9 structured events, unchanged Catalog hash, and no browser connection;
  artifact: `.tmp/root-job-e2e-dd2438e8a2dd4d27a69c5a547833ca06/`.
  Metrics events now persist the writer-created path, and zero-candidate tasks
  carry the explicit `no_candidates` outcome. Event import is byte-offset based
  and bounded to 500 complete lines per poll; a 1,200-event isolated reducer
  test confirms terminal success is still found beyond the GUI's last-500 view.
  Full suite and independent P3 rereview remain before the final gate. No
  live site or paid/resource-consuming test ran.

## Implementer checkpoint — P3 final safety and Windows UI evidence (2026-10-24)

- Fixed the final controller safety findings: startup gate publication is
  atomic and inside the startup failure boundary; failed gate/DB setup kills
  and waits for the child, records `interrupted`, and closes log resources.
  Finished workers with an incomplete JSONL tail are detected without a
  retry loop and become unverified/interrupted. Log reader threads must drain
  before a result can be accepted. When management SQLite is unavailable,
  cancellation writes the filesystem sentinel first, supervision writes a
  durable marker, and the live worker is stopped cooperatively rather than
  being allowed to continue or be reported successful. An inherited
  `CRAWLER_CDP_ENDPOINT_OVERRIDE` is removed unless the request explicitly
  provides one.
- Added isolated regression tests for startup gate failure cleanup, finished
  workers with a partial event tail, undrained log readers, explicit endpoint
  environment handling, and management DB failure while a worker is live.
  The tests confirm fail-closed interruption and filesystem stop markers.
  The controller also verifies the worker's real PID/token/OS-start identity
  before force termination; session queue advancement now occurs only after
  `succeeded`, so unknown/partial/interrupted jobs cannot auto-retry.
  The focused management suite is now **24 passed**, and the combined
  management/execution-worker/CLI affected run is **44 passed**.
- `ruff check src tests` passes. The GUI smoke suite is now **8 passed**. All
  runs use `.tmp` basetemp and
  cache paths and do not touch operational Catalog/Watchlist/Books.
- Native Windows synthetic screenshots were generated and inspected by the
  Lead with `tools/gui_execution_screenshots.py`:
  `p2-execution.png`, `p2-confirmation.png`, `p2-grant-confirmation.png`,
  `p3-jobs.png`, and `p3-interrupted.png` under `docs/gui-screenshots/`.
  The tool uses synthetic data only and never starts a worker or connects to
  a site. The actual isolated two-site worker subprocess E2E separately
  completed sequentially with structured events and unchanged Catalog hash.
- Process liveness on Windows uses `OpenProcess`/`GetExitCodeProcess`; query
  failures remain live/unknown to prevent an unsafe second worker. A local
  Windows probe observed the launcher and child PID distinction, while child
  survival after launcher termination was not established; no stronger claim
  is made. The verified child PID plus token and OS start identity are used
  for force-stop when available.
- Added a shipped Qt offscreen lifecycle test,
  `test_gui_confirm_to_real_worker_history_and_fresh_rerun_offscreen`. It
  queues through `MainWindow._start_execution`, observes the real production
  child process and structured events, verifies persistent JobsPage history
  and selected-key retention, then invokes the history rerun path and asserts
  a new queued job ID. The isolated sample has completed items and therefore
  produces no candidate/browser/resource access. The test uses the real preview, confirmation
  dialog, production worker subprocess, Catalog/Watchlist reload, metrics
  paths, persistent JobsPage history, changed-input rerun fingerprint, removed
  key stop, and invalid-YAML stop checks. It complements the native Windows
  screenshot inspection and the two-site production worker E2E.
- Independent final rereview passed with BLOCKING=0. The guarded full suite is
  still running; focused reruns of the Comic DAYS timeout and four Hanayume
  cases passed. This is not yet a full-suite PASS. No P4/P5 work has started.
- Final rereview's nonblocking quota-display note is addressed: Grant-only
  previews now show deterministic `site/resource/quota available` lines for
  each planned resource instead of selecting an arbitrary value.
- The selected-site Resource controls are contained in a bounded 420px
  horizontal scroll area, so a large multi-site selection remains usable at
  the 1400px Windows inventory window size while preserving per-site choices.

## Lead final safety receipts (2026-10-24)

- P2 passed independent review before P3 began (`cc7a4bb`). Final P3 and
  Resource UI re-review also passed with **BLOCKING=0**. Findings corrected
  during review include endpoint transport/priority, terminal-event regression,
  confirmation before observed consumption, startup-barrier cleanup, partial
  JSONL tails, log draining, management DB failure, unknown-outcome queue stops,
  process identity, and fresh input reload before rerun.
- Final native UI QA found an ignored global Resource selector and a rebuild
  path that reset explicit per-site choices to `all`. The global control was
  removed. Specific choices now survive key additions and reload; unsupported
  old choices remain visible and blocked across repeated rebuilds until the
  user explicitly chooses a supported value. Missing selectors block Preview.
  The existing multi-site Qt test now covers these adversarial transitions.
- `tests/unit/test_cli_job_events.py` permanently verifies four consumption
  cases without browser access: observed false, unknown, cancellation during a
  consuming attempt, and confirmed consumption. Unconfirmed results never emit
  or print `grant confirmed`; a cooperative stop allows the current observation
  to finish and prevents the next candidate. Independent final transition
  verification: **9 passed**, including the real worker Qt lifecycle test.
- Latest affected run: **255 passed, 0 skipped**, 451 Python/pytest deprecation
  warnings, 78.24 seconds. It covers GUI smoke, management jobs, execution
  worker, selected-key planner, CLI event truth, CLI, Batch, Inventory, and GUI
  model tests. Command: `.venv/Scripts/python.exe .tmp/root_guarded_pytest.py
  <those test modules> -q --basetemp=.tmp/fa3 -o cache_dir=.tmp/root-pytest-cache`.
  The local audit wrapper rejects connections/writes to operational Catalog,
  Watchlist/runtime inputs and Books; child tests use explicit isolated paths.
  Ruff (`src tests tools/gui_execution_screenshots.py`) and diff whitespace
  checks pass.
- Windows native captures were regenerated after the final UI correction:
  `.tmp/p3-native-release2`, Qt platform `windows`, Inventory 1400x850, all five
  images in `docs/gui-screenshots/`, screenshot helper exit 0. The helper starts
  no worker. Its Qt widgets are explicitly deleted on the GUI thread before
  interpreter exit. Production worker execution is verified separately by the
  shipped real-Preview/worker/Qt E2E and isolated two-site, 13-event subprocess
  runs, including transient endpoint priority and non-persistence checks.
- Full-suite run is still in progress (5,450 tests collected at launch).
  Final counts and failure/skip analysis will be recorded before handoff.
  No live site, paid purchase, or real ticket/Quota consumption was tested.
  P4/P5 remain unstarted; user Windows operation review is the next phase.

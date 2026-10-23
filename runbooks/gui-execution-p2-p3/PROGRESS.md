# Windows GUI P2/P3 — Implementation Progress

> **P2/P3 IMPLEMENTED / INDEPENDENT SAFETY REVIEW PASS / READY FOR WINDOWS UI REVIEW** (2026-10-24).
>
> [Master runbook](README.md). P2 gate passed before P3. Work stops after P3. Clean committed affected tests pass; the broad worktree full suite completed with six failures, analyzed below. All execution verification uses isolated fixtures and mock site entry.

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
| P3.4 Tests/Windows QA/review | PASS WITH FULL-SUITE CAVEATS | Clean commit 249 passed; worktree affected 255 passed; full suite 5444 passed / 6 failed / 0 skipped, failure analysis below; final independent review BLOCKING=0 |
| **User UI review** | **READY** | Native Windows screenshots supplied; implementation stops after P3; P4/P5 unstarted |

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

**Current status:** P2 independently approved before P3 (BLOCKING=0, checkpoint `cc7a4bb`). Final P3 code checkpoint `b0467b2` passed independent review (BLOCKING=0), clean-checkout affected tests (249 passed), source compilation, Ruff, and native Windows screenshot inspection. The worktree full suite completed: 5444 passed, six failures, no skips; this is not an all-green full-suite result. The failures and successful focused checks are documented below. P4/P5 remain unstarted. Windows manual operation review is now possible.

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
- Windows native captures were regenerated after the final UI corrections and
  JobsPage metadata display: `.tmp/p3-native-handoff`, Qt platform `windows`, Inventory 1400x850, all five
  images in `docs/gui-screenshots/`, screenshot helper exit 0. The helper starts
  no worker. Its Qt widgets are explicitly deleted on the GUI thread before
  interpreter exit. Production worker execution is verified separately by the
  shipped real-Preview/worker/Qt E2E and isolated two-site, 13-event subprocess
  runs, including transient endpoint priority and non-persistence checks.
- Final committed source `b0467b2` was exported to a separate checkout at
  `.tmp/p3-reviewed-b0467b2` to exclude concurrent unrelated worktree changes.
  All `src` Python files compile. The same affected modules pass with
  **249 passed, 0 skipped**, 433 warnings, 70.11 seconds; Ruff also passes.
  The six-case count difference from the worktree's 255 is external Discovery
  coverage absent from this commit. Evidence: `.tmp/root-p3-committed.xml`
  and `.tmp/p3-committed-checkout.log`.
- The guarded full worktree suite completed with **5444 passed, 6 failed,
  0 skipped**, 5601 warnings, 3395.01 seconds. Command:
  `.venv/Scripts/python.exe .tmp/root_guarded_pytest.py -q --basetemp=.tmp/root-full-p3-final-1 -o cache_dir=.tmp/root-pytest-cache --tb=short -ra --junitxml=.tmp/root-p3-final.xml`.
  The full run began before the final GUI display/Resource-control refinements;
  the clean committed affected run above includes those refinements. Full-suite
  evidence: `.tmp/root-p3-final.xml` and `.tmp/root-p3-full.log`.
- Full-suite failure analysis (no failures hidden or marked skipped):
  - Comic DAYS hidden ticket-control case: DOM snapshot timeout. Its unchanged
    test function passed both cases on focused rerun (2 passed, 3.40 seconds)
    and both cases on the clean P2 baseline (2 passed, 4.11 seconds). One earlier
    focused attempt also timed out, so browser timing instability remains.
  - Hanayume existing-grant cases: two Windows path-length failures, including
    `WinError 206`. Two duplicate-current-latch cases observed
    `window.ticketClicks is None`. All four passed together on focused rerun
    using the short isolated basetemp `.tmp/hf1` (4 passed, 25.96 seconds).
    The latter two failure causes are not established beyond the failed DOM
    observation and passing rerun. Concurrent Hanayume code/test changes remain
    outside the P2/P3 commit. Evidence: `.tmp/root-hanayume-recheck.log`.
  - Distributed runtime settings test: the user's dirty `crawler.yaml` has
    BookWalker `page_turn_delay_ms: 0`, while the test expects the tracked
    distributed default `200`. The same test passed against the clean tracked
    configuration (1 passed). The user's operational setting was preserved.
- The independent reviewer assessed these full-suite results after the run
  completed and confirmed no remaining P2/P3 BLOCKING finding. No unrelated
  adapter or user configuration was changed to make these tests green.
- Final behavior choices: complete input fingerprints conservatively stop an
  old queued request after relevant files change, including changes made by an
  earlier job; the user must create a fresh preview. A removed/invalid selected
  key stops rerun rather than silently executing a smaller selection. Restarted
  queued jobs never auto-start; uncertain consumption never auto-retries.
- No live site, paid purchase, or real ticket/Quota consumption was tested.
  Real-site/paid Live verification was intentionally excluded. All requested
  unit, local browser integration, Qt offscreen, subprocess and full-suite
  categories were exercised; zero tests were skipped. P4/P5 remain unstarted.

## Final changed files

Relative to implementation baseline `b556ec9`; concurrent worktree changes are
not included. `note/00_core.md` is synchronized with the implementation.

```text
docs/ARCHITECTURE.md
docs/DISCOVERY_AND_BATCH.md
docs/GUI_INVENTORY.md
docs/GUI_README.md
docs/gui-screenshots/p2-confirmation.png
docs/gui-screenshots/p2-execution.png
docs/gui-screenshots/p2-grant-confirmation.png
docs/gui-screenshots/p3-interrupted.png
docs/gui-screenshots/p3-jobs.png
docs/gui-screenshots/p3-render.json
note/00_core.md
runbooks/gui-execution-p2-p3/02-execution/README.md
runbooks/gui-execution-p2-p3/03-job-management/README.md
runbooks/gui-execution-p2-p3/PROGRESS.md
runbooks/gui-execution-p2-p3/README.md
src/screenshot_crawler/batch/executor.py
src/screenshot_crawler/batch/models.py
src/screenshot_crawler/batch/planner.py
src/screenshot_crawler/cli.py
src/screenshot_crawler/execution_worker.py
src/screenshot_crawler/gui/__init__.py
src/screenshot_crawler/gui/execution_dialog.py
src/screenshot_crawler/gui/jobs_page.py
src/screenshot_crawler/gui/main_window.py
src/screenshot_crawler/management/execution.py
src/screenshot_crawler/management/job_controller.py
src/screenshot_crawler/management/job_worker.py
src/screenshot_crawler/management/jobs.py
src/screenshot_crawler/management/process_identity.py
tests/integration/test_gui_smoke.py
tests/unit/test_batch_selected_keys.py
tests/unit/test_cli.py
tests/unit/test_cli_job_events.py
tests/unit/test_execution_worker.py
tests/unit/test_management_jobs.py
tools/gui_execution_screenshots.py
```

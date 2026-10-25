# GUI Live Monitor Progress

## Current status (2026-10-25)

- Baseline HEAD: `6f436a2d371633fa480e57b61ff1f4b54d751cf2`; branch: `feat/gui-live-monitor`.
- Phase 01: implemented and independently approved (54 targeted tests, Ruff and diff check pass).
- Phase 02: implemented and independently approved (15 GUI smoke tests, native baseline recorded; upper layout preserved).
- Phase 03: implemented and independently approved (13 Presenter / 37 with management, 17 GUI tests; Ruff and diff check pass).
- Phase 04 baseline: implemented, correction set and integrated run revalidated; independently approved (BLOCKING 0).
- Follow-up geometry/interaction fix: implemented and independently approved (BLOCKING 0).
- Validation remains isolated/offscreen/mock only; no real site, CDP, quota, ticket, or operational Catalog/Watchlist access.
- Follow-up changes: upper content uses a scrollable viewport, initial tree is fully collapsed, user splitter ratios persist across resize/poll/follow, and the pre-follow-up QSplitter warning path is removed.

- 2026-10-25: Historical planning note; superseded by the current status above.
- Phase01 Console tail / Discover parity: APPROVED
- Phase02 Docked monitor: APPROVED
- Phase03 Structured summaries: APPROVED
- Phase04 Jobs history / Windows QA: APPROVED

Current evidence is the Phase 04 synthetic-content capture set under `docs/gui-screenshots/phase4-live-monitor-*` and its `.actual.json`, plus the follow-up isolated/offscreen geometry tests; earlier empty-monitor captures remain historical diagnostics and are not acceptance evidence. The prior 980x628 native geometry is historical pre-follow-up evidence.

## Follow-up geometry and interaction correction (2026-10-25)

- The existing upper path/toolbar/tree/detail/action/error widgets remain in the same order and retain their settings. The upper content is wrapped in a `QScrollArea` viewport; its content minimums remain intact while the viewport scrolls when the monitor is enlarged. The main window remains usable at 980x600, and an actual vertical handle drag reaches at least 400px of monitor height at 1400x850.
- Resize, supervisor polling, and active-job follow no longer reset a user-selected splitter ratio. The monitor remembers its expanded size across its collapse toggle. The initial inventory tree is fully collapsed; later snapshot reloads restore user expansion.
- `QSplitter` children are added before `setCollapsible(1, False)`, removing the startup `QSplitter::setCollapsible` out-of-range warning.
- Targeted validation: GUI smoke **29 passed**, related GUI model/management tests **37 passed**, no tests skipped. The populated synthetic fixture checks form/table non-overlap, path/action scroll reachability, vertical and horizontal handle drags, resize/follow retention, collapse/expand restoration, initial collapse/reload restoration, and warning capture. The first GUI invocation using the host Temp directory hit 13 setup `WinError 5` ACL errors; workspace basetemp reruns passed. Independent follow-up review: **APPROVED; BLOCKING 0**.
- Root's independent synthetic native helper also passed in exit 0: Windows/DPR 1.5, actual 980x600, monitor 230px, upper viewport 326px, bounded header widths, collapsed tree, Japanese log text, and no startup QSplitter warning. No worker, browser, operational Catalog/Watchlist/Books, quota, or ticket access was used.

## Historical Phase 04 final correction record (2026-10-25)

- The existing upper path/toolbar/tree/detail/action/error layout remains the first pane. Its geometry is clamped before monitor expansion; at a small height the monitor body collapses while its heading remains reachable. The lower splitter pane is non-collapsible and the monitor's explicit toggle is the only body-collapse path. Header action/state widths are bounded and long values are elided with tooltips.
- The persistent fake-child test exercises Discover, Batch Run, and Grant-only through the real preview, JobController queue/start/poll, heartbeat/identity, UTF-8 stdout/stderr, structured summary, history, and fresh rerun path. It asserts isolated input hashes and no worker/browser connection to a real site.
- The real Qt stress test appends 50,000 lines and more than 5 MiB through `LogTailReader` into `QPlainTextEdit`, checks bounded blocks/chars, timer responsiveness, manual anchor/bottom follow, independent history scrolling, and source-file hash/size preservation. The Presenter stress fixture reads 50,000 Events under default limits and retains latest context while exposing omission metadata.
- Child-only UTF-8 is enforced for execution subprocesses; parent CLI encoding is unchanged. Synthetic Japanese/emoji output is asserted in all three action paths. Native captures use synthetic jobs only, with worker/browser startup disabled; the report records Windows/DPR and requested 980x600, 1400x850, and additional high-DPI logical sizes.
- Targeted results after correction: GUI smoke **26 passed**, Presenter stress and management/worker tests **59 passed**, and fake-child lifecycle **3 passed**. Ruff and diff checks pass; independent integration/native visual review is approved with the non-blocking constraints recorded below. The pre-follow-up native report records a 980x600 request clamped to actual 980x628 by the existing populated detail minimum; this capture is historical after the scrollable viewport correction.

## Historical implementation and review records

> The phase records below are historical implementation notes. They are
> superseded by the current status above and the final integration/reviewer
> results below.

## Phase 01 implementation record (2026-10-25)

- Phase 01 is implemented; independent review gate is pending.
- Scope: added the Qt-free bounded ``LogTailReader``; launched only the
  management worker unbuffered; preserved separate sanitized stdout/stderr
  sinks; added Discover result events and CUI-equivalent output; preserved
  fail-stop and keyed ``candidate_finished failed`` behavior.
- Files: ``src/screenshot_crawler/management/log_tail.py``,
  ``src/screenshot_crawler/management/job_controller.py``,
  ``src/screenshot_crawler/execution_worker.py``,
  ``tests/unit/test_management_log_tail.py``,
  ``tests/unit/test_management_jobs.py``, and ``note/00_core.md``.
- Tests: ``pytest -q --basetemp .pytest-tmp-gui01b
  tests/unit/test_management_log_tail.py tests/unit/test_management_jobs.py``
  passed: 29 passed, 2 existing warnings. The first run without an explicit
  workspace basetemp was blocked by the host Temp directory ACL; rerunning in
  the workspace passed.
- Not run: browser integration, real-site/live verification, ticket or quota
  consumption, and full suite. Phase 01 is mock/local only by contract.
- Do not start Phase 02 until the reviewer records approval and any blocking
  corrections here.
## Phase 01 current status (2026-10-25 review correction)

- Baseline HEAD: ``6f436a2d371633fa480e57b61ff1f4b54d751cf2``
- Branch: ``feat/gui-live-monitor``
- Phase 01: implementation plus reviewer BLOCKING corrections in progress;
  Phase 02 remains gated.
- Corrections: detect missing/recreated files by stream identity, reset stale
  decoder state, expose per-stream ``tail_omitted``/``history_omitted`` and
  initial byte metadata, and add real ``DiscoveryResult`` parity/redaction/
  fail-stop coverage.
- Previous targeted result: 48 passed. The corrected targeted run is recorded
  below after completion; the earlier 29-case log-tail/management count was
  superseded by the broader execution-worker and corrected tail coverage.
## Phase 01 correction verification (2026-10-25)

- Reviewer BLOCKING items addressed: recreated same-size logs reset offsets and
  incremental decoders using per-stream file identity; missing logs reset state;
  ``metadata(stream)`` exposes ``tail_omitted``, ``history_omitted``,
  ``initial_offset``, ``initial_size`` and ``file_present``.
- Added coverage for actual ``DiscoveryResult`` success/incomplete/warnings,
  CUI field parity, keyed exception failure, redaction, fail-stop, CRLF, long
  lines, 1 MiB input, bounded reads, no duplicate/lost bytes, and same-size
  recreation.
- Tests: targeted Phase 01 selection now passes **52 passed, 2 existing
  warnings**. Ruff and ``git diff --check`` pass.
- Review state: correction ready for independent re-review. Phase 02 remains
  blocked until approval.
## Phase 01 BLOCKING2 correction verification (2026-10-25)

- Removed POSIX ``st_ctime_ns`` from identity tracking; ordinary append now
  retains the same stream identity. Windows creation time remains an optional
  immutable fallback when inode identity is unavailable.
- Bounded UTF-8 continuation-byte skipping to three bytes.
- Added tests for changing ctime with stable identity and malformed
  continuation runs.
- Final targeted result after this correction: **54 passed, 2 existing
  warnings**; Ruff and ``git diff --check`` pass.
- Phase 02 remains blocked pending independent re-review approval.
## Phase 02 implementation record (2026-10-25)

- Added lower ``ExecutionMonitor`` pane without changing the existing upper
  path/toolbar/horizontal splitter/action/error layout or execution controls.
- Reused ``JobController.poll`` and ``JobStore``. The monitor is passive,
  bounded, read-only, and failure-isolated from queue/stop/reconcile. It
  supports separate stdout/stderr switching, open/copy, follow-at-bottom,
  manual viewport retention during trim, job history selection, queued versus
  running versus terminal display, and missing-DB health display.
- New confirmed jobs are selected automatically; session jobs follow when they
  actually start. Manual history selection suppresses auto-follow. Current
  key/item values are shown only when backed by events; selected-key guesses
  are not used.
- Tests: ``QT_QPA_PLATFORM=offscreen pytest -q --basetemp .pytest-tmp-gui02b
  tests/integration/test_gui_smoke.py`` passed **11 passed, 2 existing
  warnings**. Targeted Ruff passed. Lead affected safety regression passed
  **210 passed, 0 skipped** across CLI/job-events/selected-Batch/Batch/
  Inventory/GUI-model coverage (operationally protected, no site access).
- Synthetic native capture: ``.tmp/gui-live-monitor-phase02-shots/``;
  ``phase02-execution-monitor.png`` was saved under a new name, with worker
  startup false. Existing P2/P3 screenshot artifacts were not overwritten.
- Not run: real-site/CDP, quota/ticket consumption, full suite, and manual
  Windows user review. Phase 03 remains gated on independent review.

## Phase 03 implementation record (2026-10-25)

- Added the Qt-free immutable `JobResultPresenter` DTO layer. The DB job/task
  state remains authoritative; events and metrics only add observed context.
- Added keyset event reads (`list_events_after` and latest-window reads) without
  a schema migration. Semantic latest candidate/discovery/grant facts survive
  bounded raw-event memory, and current context switches to the newest
  `task_started` site without carrying a previous key or item.
- Added bounded incremental JSONL metrics reading. It keeps a per-file offset
  and partial line, handles CRLF, long files, append, truncation, and
  recreation, validates the metrics root plus batch site/run scope, and keeps
  planned versus execution skips separate. Invalid or unauthorized metrics do
  not change the DB job state.
- Discover summaries expose per-site/key success, failed, disabled, unstarted,
  or unknown status plus observed/new/known/complete/reason/warnings. Batch
  summaries use `batch_summary` evidence, and grant results deduplicate by site,
  work, and resource. A consumed grant with an aligned structured candidate
  failure is shown as consumed with post-processing failure; no text heuristic
  promotes it to success. Direct grant events remain minimal and tri-state.
- Summary and problem panes are read-only, scrollable, and copyable. Raw
  stdout/stderr remain separate, while structured evidence is shown alongside
  them. Long structured diagnostics are not placed in the upper control row.
- Tests: presenter and management target selection passed **30 passed** after
  adding the Phase 03 fixtures; presenter-specific coverage passed **7 passed**.
  GUI smoke passed **16 passed, 2 existing warnings**. Ruff passed for the
  changed presenter, monitor, main window, and tests. No Phase 04 work started.
- Review state: implementation is ready for independent Phase 03 review;
  Phase 04 remains gated. No real-site/CDP, quota/ticket consumption,
  operational input, browser integration, or full-suite run was performed.

## Phase 03 pre-review correction record (2026-10-25)

- Metrics invalid/scope-invalid state is sticky while the same file identity
  remains in place; only truncation or recreation resets the reader. A summary
  seen in a non-EOF chunk remains partial until the reader reaches EOF.
- Post-processing failure association now requires a matching strong identity
  (`item_id` or `source_id`) and compatible resource, so same-resource
  different-work records cannot be conflated. Direct grant latest facts are
  replaced by the newest site/item/source/resource event.
- Added malformed-after-summary, CRLF/partial append/recreate, over-total-cap
  long metrics, and latest direct-grant fixtures. Final Phase 03 targeted
  selection passed **47 passed, 2 existing warnings** (Presenter, management
  jobs, and GUI smoke); Ruff and diff check passed.
- Independent Phase 03 review is still required before any Phase 04 work.

## Phase 03 independent review BLOCKING corrections (2026-10-25)

- Review findings: Batch and Grant summary fields were too terse; missing or
  partial metrics could retain a stale `no_candidates`; task metrics paths
  were being taken from task rows instead of only validated metrics events;
  consumed OK grants without aligned completion/failure evidence were shown
  too optimistically; semantic grant facts and diagnostic events needed
  bounded retention; discovery errors and process-exit success handling were
  incomplete; and summary/problem panes needed explicit display caps and
  anchor retention.
- Corrections: Batch/Grant DTO fields are rendered in the lower summary;
  Discover actions no longer show Batch unknown rows. Metrics paths are
  accepted only from matching `metrics_started`/`batch_finished` task/site
  events, with valid batch site/run scope and EOF required for completion.
  Missing, invalid, or partial metrics cannot classify `no_candidates`.
- Consumed OK grants now require aligned structured completed/failed candidate
  evidence; otherwise outcome is `postprocess_unknown` and the reason remains
  visible as a problem. Failed candidates, unknown consumption, and invalid
  metrics are surfaced as structured problems. Metrics candidate/grant facts
  are capped with `metrics_omitted` coverage metadata.
- Semantic selected-key/task facts are retained outside the raw event window;
  recent diagnostic events use a deduplicated bounded ring. Grant semantic
  facts have a bounded omission counter. Discovery payload errors/warnings are
  structured problems, and successful process-exit events are ignored.
  Backlogged keys remain unknown until the event page is complete.
- Summary/problem displays are capped with an explicit omission marker and
  preserve manual scroll position; context includes source IDs. Synthetic
  secret strings in metrics reasons are sanitized through the existing
  `sanitize_text` helper.
- Re-review status: targeted validation is rerunning after these corrections;
  Phase 04 remains prohibited until independent Phase 03 approval.
- Additional correction: grant post-processing now uses the latest aligned
  candidate result, so a later completed/replanned attempt supersedes an older
  failed attempt. Semantic grant facts are capped with an omission counter and
  repeated diagnostic sequence numbers are not duplicated in the problem ring.
- Latest targeted checks: Presenter **10 passed**, Presenter plus management
  jobs **34 passed**, GUI smoke **17 passed**, 2 existing warnings per pytest
  group; Ruff and diff check passed. Phase 03 remains in re-review.

## Phase 03 final review correction (2026-10-25)

- Grant DTOs are now shown for both Batch and Grant-only actions. A metrics
  Grant report suppresses only a matching direct grant event with the same
  site and strong source/item identity; different sites, sources, or resources
  remain visible as separate minimal observations.
- Semantic grant retention uses an O(1) counter. Overflow is counted only for
  new cursor-page sequences, so repeated latest-window reads cannot inflate
  omission counts. Batch metrics missing warnings require an expected path;
  Discover and not-started tasks do not emit that warning.
- Batch skip summaries retain `candidates_skipped` as direct evidence. When a
  complete summary explicitly reports zero skips, planned and execution skip
  fields are shown as zero; without that evidence they remain unknown.
- Revalidation: Presenter/management target selection passed **34 passed**,
  GUI smoke passed **17 passed**, 2 existing warnings per run; Ruff passed.
  Phase 04 remains prohibited pending independent re-review.

## Phase 03 final review correction 2 (2026-10-25)

- Batch actions now include structured Grant reports. A direct
  `grant_confirmed`/`grant_unknown` event is suppressed only when a report
  matches the same site/resource and strong source or item identity; unrelated
  sites, sources, and resources remain separate minimal observations.
- Semantic grant overflow uses an O(1) count and increments only for new
  cursor-page sequences; latest-window rereads do not increase the omission
  count. Batch missing-metrics problems require an expected metrics path, so
  Discover and not-started tasks remain quiet.
- Batch DTOs retain explicit `candidates_skipped`. A complete summary with
  `candidates_skipped=0` renders planned and execution skip counts as zero;
  missing evidence remains unknown.
- Verification after correction: Presenter **10 passed**, Presenter plus
  management jobs **34 passed**, GUI smoke **17 passed**, 2 existing warnings
  per pytest run; py_compile, Ruff, and diff check passed. Phase 04 remains
  prohibited pending independent Phase 03 approval.

## Phase 03 persistent assertion completion (2026-10-25)

- Extended persistent tests to exercise Batch metrics Grant reports in
  `result.grants` and the GUI summary, and to prove that a matching direct
  grant event (same site/resource and source/item) is rendered once.
- Added coverage that a source/item mismatch, different resource, different
  site, or different source remains a separate direct observation. Repeated
  Presenter calls with the bounded grant semantic window keep the same
  `grant_facts_omitted` value; latest-window rereads do not inflate it.
- Added the expected-metrics-missing problem assertion for Batch and the
  Discover control assertion that no metrics warning is emitted without an
  expected path. Complete `candidates_skipped=0` evidence remains covered.
- Verification: Presenter plus management selection **37 passed**, GUI smoke
  **17 passed**, 2 existing warnings per pytest run. Ruff and
  `git diff --check` passed. Phase 04 was not started.

## Phase 02 review correction (2026-10-25)

- Isolated monitor and JobsPage refresh exceptions in ``_poll_jobs`` so
  controller terminal handling and queued-session advancement always continue;
  monitor follow failures after starting a queued job are isolated as well.
- Added a monitor collapse control that preserves the heading and expands when
  a newly followed job is selected. Existing upper controls and layout order
  remain unchanged.
- Re-ran offscreen GUI smoke: **12 passed, 2 existing warnings**. Ruff and
  ``git diff --check`` pass.
- The first correction run exposed only a synthetic test teardown omission
  (fake controller lacked ``close``); the fixture was corrected and the final
  run passed. No production failure remained.

## Phase 02 blocking correction 2 (2026-10-25)

- Job changes now reset reader/view/cache state, preventing A竊達竊但 duplicate
  text and retaining cache only for the current job's bounded streams.
- Header location values use constrained/elided labels with full-value tooltips;
  a 10,000-character event-key fixture verifies the 980px window stays bounded.
- Collapsing can shrink below the former 140px minimum while retaining the
  heading; collapsed panes skip log reads/appends and expansion catches up.
- Auto-follow is keyed to active-job transitions and explicit next-job start,
  preserving a manual queued-history selection during unrelated polls.
- Tail/history omission and stdout/stderr cross-stream ordering limits are
  shown in the monitor metadata. Character-prefix trim contributes removed
  blocks to scroll-anchor correction. A dedicated 200-line anchor fixture
  passes.
- Final offscreen GUI smoke: **15 passed, 2 existing warnings**. Ruff and
  ``git diff --check`` pass.
- Native capture evidence from Lead is recorded as
  ``.tmp/glm-phase2-native-shots/p2-execution.png`` (Windows, DPR 1.5).
  The worker capture remains synthetic/offscreen and is not described as native.
- Phase 03 remains blocked pending independent review. Current event view still
  uses the existing first-500 event query; keyset/latest-event improvements are
  explicitly deferred to Phase 03/04.
- Final rerun after constrained action/state label sizing: **15 passed, 2
  existing warnings**; Ruff and ``git diff --check`` remain passing.


## Phase 04 implementation and QA (2026-10-25)

- JobsPage now shares the existing JobStore, JobController, ExecutionMonitor,
  fixed-path LogTailReader, and immutable JobResultPresenter. Its list/detail
  selection remains independent from the monitor job/stream selection.
- History refresh uses `list_events_latest(... DESC LIMIT ...)` and renders the
  bounded window chronologically, avoiding the old first-500 event view. An
  unchanged job list is not rebuilt; changed detail text preserves a manual
  scrollbar anchor. Raw monitor append uses an independent QTextCursor so a
  user selection survives new output.
- MainWindow queue/start keeps the controller as the safety boundary. Monitor
  follow/clear and optional monitor/JobsPage initialization failures are
  isolated; controller/database failures remain fail-closed. Existing stop,
  force-stop, cancel, resume, rerun, queue, reconcile, and session-advance
  meanings remain unchanged.
- Presenter current context is retained separately from capped semantic facts,
  so a latest event beyond the grant cap remains visible. Report/direct-grant
  and candidate outcome lookups use strong-identity indexes, avoiding per-row
  scans of fallback facts or the full candidate window.
- Targeted validation: GUI smoke **19 passed**; Presenter plus management
  selection **37 passed**; 2 existing warnings per pytest run. Ruff and
  `git diff --check` passed. No tests skipped.
- Isolated default-limit stress evidence from `.tmp/glm_root_load.py`:
  **50,001 events**, **50,000 log lines / 5,150,000 bytes**, 101 Presenter
  calls, max 30.14 ms / mean 21.26 ms, 101 timer callbacks, event cursor
  50,001, 2,001 retained grants, 48,001 omitted, omission stable, and latest
  context correct after a live append. Metrics probe with 2,000 work reports
  completed in 11 incremental reads, max 67.47 ms / last 67.47 ms.
- Native Windows synthetic captures (DPR 1.5) are in new isolated paths:
  `.tmp/glm-phase4-native-shots/phase4-monitor-1400x850.png` (2100x1275),
  `.tmp/glm-phase4-native-980-shots/phase4-monitor-980x600.png` (1470x900),
  and `.tmp/glm-phase4-native-shots/phase4-history-1150x850.png` (1725x1275).
  Japanese text was visually checked; existing P2/P3 artifacts were not
  overwritten. No worker was started.
- Not run: real-site/CDP, quota/ticket, operational Catalog/Watchlist/Books,
  browser integration, and full pytest. These remain outside the isolated GUI,
  management-event, and log-reader scope.

## Final integration result (2026-10-25)

- Root integrated 11-module affected run completed **304 passed / 0 skipped**,
  **451 existing pytest-asyncio deprecation warnings**, exit 0, in 100.82s.
  Root also confirmed Ruff over `src`, `tests`, and the new screenshot helper,
  plus `git diff --check`, pass.
- Final synthetic native helper run completed exit 0. Its report records
  `capture_sizes.window_1400=[1400,850]` and
  `capture_sizes.history_1150=[1150,850]`; the 980 request remains actual
  `[980,628]` with upper `[558,548]` hint/minimum and a 26px monitor heading.
  Discover, Batch Run, Grant-only, and history captures contain structured
  summary/problem content; worker/browser startup remains false.
- Final independent reviewer/native visual gate: **APPROVED; BLOCKING 0**.

## Final QA handoff (2026-10-25)

- The first broad affected invocation exited **1** without XML/summary. This
  was treated as an abnormal diagnostic, not a pass. The diagnostic rerun
  completed **296 passed / 0 skipped** with 451 existing Python/pytest
  deprecation warnings in 58.74s; the initial abnormal exit was not reproduced.
  Root's final integrated 11-module run (session `24501`) completed **304
  passed / 0 skipped**, exit 0, and remains the acceptance authority.
- Root's independent default-limit probes are recorded separately from the
  worker/UI runs: the 50k-event/5MiB log probe measured max **53.86 ms**, and
  the 2,000-work-report metrics probe measured max **88.68 ms**. Earlier local
  Phase 04 observations (30.14 ms / 67.47 ms) are not substituted for those
  independent values.
- Current synthetic native report: Windows, DPR 1.5; requested 980x600 is
  clamped to actual 980x628 by the existing populated Detail minimum. Upper
  pane is 558px with hint/minimum 548px; monitor heading is 26px. Requested
  1400x850 and additional 1150x850 logical sizes are also captured.
- Current implementation/doc/test files owned by this task: `docs/ARCHITECTURE.md`,
  `docs/GUI_INVENTORY.md`, `docs/GUI_README.md`,
  `docs/gui-screenshots/phase4-live-monitor-1400-batch.png`,
  `docs/gui-screenshots/phase4-live-monitor-1400-discover.png`,
  `docs/gui-screenshots/phase4-live-monitor-1400-grant-failed.png`,
  `docs/gui-screenshots/phase4-live-monitor-980-failed.png`,
  `docs/gui-screenshots/phase4-live-monitor-history.png`,
  `docs/gui-screenshots/phase4-live-monitor.actual.json`, `note/00_core.md`,
  `runbooks/gui-live-monitor/README.md`, `runbooks/gui-live-monitor/PROGRESS.md`,
  `src/screenshot_crawler/execution_worker.py`,
  `src/screenshot_crawler/gui/execution_monitor.py`,
  `src/screenshot_crawler/gui/jobs_page.py`,
  `src/screenshot_crawler/gui/main_window.py`,
  `src/screenshot_crawler/management/job_controller.py`,
  `src/screenshot_crawler/management/jobs.py`,
  `src/screenshot_crawler/management/log_tail.py`,
  `src/screenshot_crawler/management/result_presenter.py`,
  `tests/integration/test_gui_smoke.py`,
  `tests/unit/test_execution_worker.py`,
  `tests/unit/test_management_jobs.py`,
  `tests/unit/test_management_log_tail.py`,
  `tests/unit/test_result_presenter.py`, and
  `tools/gui_live_monitor_phase4_screenshots.py`.
- Full pytest, Research/Probe, and browser/live integration were omitted by
  scope selection: this change is limited to GUI observation, child-log
  capture, and read-only management queries; Core/Runner/Policy/schema/browser
  contracts are unchanged, the 11-module affected run covers the boundary,
  and Research/Probe production contracts were not changed. Real-site/CDP,
  operational Catalog/Watchlist/Books access, quota or ticket consumption
  were also not run. No tests were skipped in the targeted runs. User-modified
  `crawler.yaml`, `watchlist.yaml`, lock files, and `debug.log` were preserved
  and are excluded from the task file list above.
- Review state: Phase 01-04 approved; Root integration and native visual
  review are complete. Two non-blocking geometry observations remain documented
  below; no further production change is required.
- Follow-up state: geometry/interaction implementation is complete and the
  targeted validation above passes; independent follow-up review is **APPROVED;
  BLOCKING 0**. Optional Windows user-operation review remains.

## Final reviewer result (2026-10-25)

- Independent Phase 04 review: **BLOCKING 0; APPROVED**. Root integration
  completed **304 passed / 0 skipped**, 451 existing deprecation warnings, exit
  0, 100.82s. Ruff and diff check passed.
- Non-blocking observation: an artificial snapshot-before-resize/show ordering
  probe can leave a 600px window whose upper actual height is below the
  populated Detail minimumSizeHint. The normal flow and native synthetic helper do not reproduce it; no
  production change was made after approval.
- Non-blocking observation: at the native minimum 628px window, expanding the
  monitor leaves only a compact detail body; users can enlarge the window for
  full summary/log content. This preserves the existing upper Detail geometry
  and is documented as the accepted constraint.
- Final native helper/captures are synthetic only and exit 0. The helper records
  exact 1400x850 and 1150x850 capture sizes and actual 980x628 for the 980x600
  request.

## Final follow-up closeout (2026-10-25)

- Root final affected run (`.tmp/gm-followup-final.xml/.log`) completed **89
  passed / 0 skipped**, with **1 existing pytest-asyncio deprecation warning**,
  exit 0 in 56.76s. Ruff over `src`, `tests`, and the new tool plus diff
  checks passed. Independent follow-up review: **BLOCKING 0; APPROVED**.
- Root synthetic native helper passed in isolation: Windows/DPR 1.5, actual
  980x600, monitor 230px, upper viewport 326px, header action/state/location
  widths 110/180/228, collapsed tree, Japanese log text, and no startup
  QSplitter warning. The real splitter checks cover 400px monitor expansion,
  monitor width drag, resize/follow/collapse size retention, control reachability,
  and populated form/table non-overlap.
- Follow-up changed files (7): `src/screenshot_crawler/gui/main_window.py`,
  `src/screenshot_crawler/gui/execution_monitor.py`,
  `tests/integration/test_gui_smoke.py`,
  `runbooks/gui-live-monitor/README.md`,
  `runbooks/gui-live-monitor/PROGRESS.md`, `docs/GUI_README.md`, and
  `note/00_core.md`. Existing user-modified configs, locks, and debug.log were
  preserved.
- Full pytest, browser-backed Integration, Research/Probe, and Live verification
  were not run: this follow-up changes GUI view geometry/interaction and its
  isolated management observation boundary only; Core/Runner/Policy/schema/browser
  contracts and production Research/Probe contracts are unchanged, and the
  targeted plus affected runs cover the changed boundary. No real site, CDP,
  operational Catalog/Watchlist/Books, quota, or ticket access was used.

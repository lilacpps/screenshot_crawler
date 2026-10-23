# Windows GUI Inventory — PROGRESS

> Status: **P0 / P1 COMPLETE — USER UI REVIEW REQUIRED** (2026-10-23)
> Workstream: [README.md](README.md)
> Scope: **P0 + P1 only**. After P1: **USER UI REVIEW REQUIRED**. Do not start P2 without review.

## Phase gates

| Phase | Status | Checkpoint / expected deliverables |
|---|---|---|
| P0 Design | COMPLETE | [Design decisions](../../docs/GUI_INVENTORY.md), frozen DTO contract, independent review and 48 existing Policy/Scope tests passed |
| P1 Read-only GUI | COMPLETE | Native Windows startup/screenshots, 48 targeted tests, 422 affected tests, independent code approval |
| P1 UI review | USER UI REVIEW REQUIRED | Ready for human inspection; P2 is not started |
| P2+ | OUT OF SCOPE | Discover, Batch, grant-only execution, jobs, scheduler, Watchlist editing, rename |

## Baseline evidence

- Main branch inspected on 2026-10-23, repository tree `277b464bed28dc738d0d433bd74275dca0594ba7` (reconfirm at start).
- Catalog schema v7; Source.acquisition_enabled, Source.display_position, Work/Item/Source, Scope synchronization/evidence available.
- Current CLI and Batch Planner can read Catalog/Watchlist and run site-scoped tasks, but GUI not implemented.
- Current `CatalogService.read_works_items_sources_and_targets` uses read-only connection; `list_crawl_runs` and `list_artifacts` use normal connection, so GUI must add read-only history access.
- Current work-key archive-order implementation finished P0-P5 in earlier workstream; no user operational Catalog/Watchlist/ZIP file modifications implied by this GUI plan.

## Non-negotiable safety

- P1 is view-only. No Catalog/Watchlist/ZIP/metrics modification, migration, Scope apply, CLI dispatch, CDP/browser connection, quota/ticket consumption, or network calls.
- Correctly distinguish assigned vs out-of-scope, completed vs external vs skipped, site/work/item aggregates, and actual vs estimated availability.
- Unknown/stale policy or Scope must not be displayed as zero or success.
- Stable selected-key set across view, search, sort, and reload; detailed focus is independent of checked rows.
- PySide6 is optional; existing CLI remains usable without GUI dependency.

## Per-phase entry to be completed by Codex

After each phase update:
1. Commit/ref, files created/modified, decisions and deviations.
2. Targeted/affected tests with pass/fail/skip and environment.
3. Qt offscreen and/or Windows real-GUI verification, screenshots path.
4. Reviewer findings, blocking fixes, unresolved issues.
5. Read-only proof for synthetic (and any real user Catalog opened).
6. Next checkpoint; after P1 **STOP for UI review**.

## Current work

Feature branch `feat/gui-inventory-p1`, based on `76dbf1f` (runbook-only updates
since baseline 277b464). Existing user edits to crawler.yaml/watchlist.yaml and
untracked lock/debug files are preserved.

### P0 checkpoint

- Contract: [docs/GUI_INVENTORY.md](../../docs/GUI_INVENTORY.md); immutable DTOs in
  `management/models.py`. Item-deduplicated totals, Source-count out-of-scope,
  separate site slots, Policy-owned expiry, explicit unknown/partial states.
- Independent reviewer accepted indexed in-memory ScopeReconciler reuse. Required
  clarifications incorporated: no writable facade methods, frozen Watchlist,
  no archive stat/rename preview, detailed stale reasons, quota pool evaluated
  with quota_available=None, registry parity verification and all eleven policies.
- The reviewer reported possible encoding artifacts from shell output. UTF-8
  file reads verified the design text; GUI labels/tests will use UTF-8.
- Tests: `test_bookwalker_policy`, `test_magapoke_policy`, `test_scope_reconciler`:
  **48 passed, 0 skipped** (12.28s). Initial test selection used a nonexistent
  Manga ONE policy file; corrected before the successful run. Pytest cache and
  temporary data are isolated under `.tmp/`.
- Authority discrepancy: SPEC's historical non-goal list includes GUI. The user's
  explicit request authorizes only this optional read-only management layer;
  no Crawler/Core/Adapter behavior or schema is changed. No silent spec rewrite.
- Existing full-suite baseline has 4,991 passes and two known failures (local
  runtime configuration and unexplained Piccoma timing); P1 will use affected
  tests and isolated Qt integration per the runbook, without operational edits.
- P0 gate passed; continue directly to P1. Stop after P1 for human UI review.

### P1 implementation / review checkpoints

- New `management/` is Qt-free. Reader validates existing schema and reference
  integrity, bulk reads one read-only transaction and closes it. Snapshot mappings
  and DTOs are immutable. Existing Policy classes/registry membership and scope
  evidence rules are reused; no Core or Site Adapter production files changed.
- The first independent management review found a genuine false-zero edge:
  complete-listing evidence could remain while all matching Catalog Sources were
  missing. Fixed to return unknown counts unless a synchronized zero-row proof
  certifies empty inventory. Both missing and proven-empty regressions pass.
- Independent GUI review found external/skipped were included in the unfinished
  filter, and proof/range/JST fields were missing from details. The pending-only
  filter was corrected and explicit external-only/skipped-only tests added.
  Details, checkbox/focus separation and Qt model notifications were iterated.
- Root added stronger real integration: actual asynchronous synthetic SQLite load,
  detail navigation, view/filter/selection/reload, failed reload with stale warning,
  hash+mtime invariance, event-loop heartbeat and queued result after close.
  A tight QTest.qWait polling loop starved the Python worker on Python 3.14;
  replacing the test wait with a real bounded QEventLoop/QTimer resolved it.
  This was a test-harness issue, not a production worker fix.
- Important safety discovery: SQLite `mode=ro` may change WAL `-shm` bytes even
  without changing mtime. The initial reviewer probe checked metadata and missed
  this; root's hash regression exposed it. P1 now rejects WAL headers **before**
  SQLite opens, with an actionable error and no checkpoint/journal mutation.
  `immutable=1` is not used because it can ignore committed WAL data. The independent
  reviewer approved this bounded limitation. Use an operator-created consistent
  rollback-journal backup; concurrent external journal-mode changes are outside
  the GUI's snapshot-input contract.
- Finalized service tests so far: **32 passed, 0 skipped** (6.34s). They include
  all eleven Policy classes, pool-vs-slots, active/expired grants, missing/invalid
  inputs, ambiguity, scope binding/digest/position/flag/evidence/sync, configuration
  retries, read-only SQL tracing, WAL hash proof and CLI with Qt imports blocked.
- Affected regression: Catalog, Watchlist, ScopeReconciler, ten site-policy test
  files, Batch (including Manga ONE policy) and CLI: **422 passed, 0 skipped**
  (50.08s). 397 existing Python 3.14/pytest-asyncio deprecation warnings.
- Performance fixture: 1,000 managed keys plus one undiscovered key and an
  unmanaged group; **100,000 Sources**. Full Reader+foreign_key_check+Policy+Scope
  aggregation **4.49s**, initial tree **15ms**, projection switch **9ms** on this
  Windows/Python 3.14.6/PySide6 6.12 environment. Search is in-memory; final
  end-to-end UI timing will also be recorded after the last layout pass.
- Windows native `windows` Qt platform startup and 1400×850 widget capture worked.
  Root inspected v1 screenshots and found a too-small detail form; worker is
  corrected pane allocation and hid empty tables before final screenshots.
- Full pytest / browser integration / Research / external Live are not selected:
  this isolated new UI has no Crawler/Core/Adapter or existing schema changes.
  Qt local integration is required and executed. No real-site, CDP, quota, ticket
  or operational Catalog/Watchlist/ZIP activity is part of this workstream.

### P1 final gate / handoff

- **Independent code review: APPROVE.** Final required housekeeping was test
  import formatting and this completion status; both are resolved. Independent
  final Inventory/Qt/local integration rerun: **48 passed**. Root final combined
  run: **48 passed, 0 skipped** (5.77s). The deprecated Qt delegate overload was
  then replaced with `itemDelegateForIndex`; the actual mouse/sort regression
  passed again (0.30s), leaving only the existing pytest-asyncio Python 3.14
  deprecation. `ruff check src tests tools/gui_*.py` and `git diff --check` pass.
- Native screenshot review exposed a second real counting bug: WORK child Site
  nodes had no work_key and showed site-global totals. Fixed node identity and
  pair-summary lookup, then added a real multi-Work snapshot regression. Final
  screenshots show each Site child at 4/11 and its four-site Work at 16/44.
- Actual mouse tests also caught the wrong QTreeView.initStyleOption overload.
  Fixed delegate-based checkbox hit testing; checkbox clicks leave details alone,
  row clicks focus details, actual header clicks and mode switches preserve focus.
  Sort/filter resets now obey Qt notification contracts and preserve stable IDs.
- Two initial combined Qt runs crashed (Qt abort/access violation); the second
  stack showed Python cyclic GC on the loader thread collecting old UI objects.
  Fixes: GUI models/widgets have explicit Qt parents, test QApplication lifetime
  is session-scoped, and tests close/deleteLater/flush DeferredDelete/collect on
  the GUI thread before launching the next worker. This is not treated as a
  flaky test to ignore. Root and independent combined runs pass after the fix.
- **Windows native verification performed**: Qt platform `windows`, 1400×850,
  real widgets, synthetic data, four PNGs visually inspected. This is programmatic
  native rendering and QTest mouse validation, not a human UI usability review.
  High-DPI/multiple-monitor and operational real-Catalog UI review remain for
  the user; no external website was accessed.
- Final native background performance, including rendering:
  [machine-readable report](../../docs/gui-performance.json). 100,000 Sources /
  1,002 groups; Inventory **3.50s**, load-to-window **3.90s**, 50 timer heartbeats
  while loading, maximum gap **0.58s**, view switch **53ms**, search **32ms**,
  expand **13ms**. Large-load allocation has a brief measurable UI delay; no
  indefinite wait. Sample input hashes **and mtimes unchanged** after the journey.
- Final screenshots: [site](../../docs/gui-screenshots/site.png),
  [work](../../docs/gui-screenshots/work.png),
  [Work detail](../../docs/gui-screenshots/work-detail.png),
  [Item detail](../../docs/gui-screenshots/item-detail.png). These use invented
  titles/URLs/paths and redacted local snapshot paths; no authentication or
  personal information. Reproduce with `tools/gui_screenshots.py` and a new
  `--sample-output` directory.
- Changed production files: new `management/{__init__,models,catalog_reader,inventory}.py`,
  new `gui/{__init__,__main__,main,main_window,model,details}.py`; optional gui extra
  and script in pyproject.toml/uv.lock. Existing Core, Site Adapters, Catalog schema,
  Watchlist service, ScopeReconciler and Site Policies were not modified.
- Tests: `test_inventory.py`, `test_gui_model.py`, `test_gui_smoke.py`.
  Synthetic-only tooling: `tools/gui_sample.py`, `tools/gui_screenshots.py`,
  `tools/gui_benchmark.py`. `.tmp/` ignored for isolated fixtures/caches.
- Docs/current note: root README; SPEC historical GUI non-goal clarified to
  exclude GUI from Crawler Core while allowing the explicitly authorized optional
  P1; ARCHITECTURE; GUI_INVENTORY; GUI_README; **note/00_core.md**; this runbook.
- Known limits: WAL input rejected to prevent -shm writes; latest-history subset
  only; archive existence unverified; availability/retries are local estimates;
  very large startup may show a subsecond allocation delay. No unresolved code
  blocker. User UI review is still required before any P2 work.
- Full/browser/Research/Live categories remain unexecuted for the reasons above.
  **0 skipped** in selected suites. Original crawler.yaml/watchlist.yaml edits
  are excluded from the implementation changes. No operational DB/ZIP output
  is part of this change.

Start on this Windows checkout:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.gui --catalog catalog.sqlite --watchlist watchlist.yaml
```

See [GUI_README](../../docs/GUI_README.md) for synthetic sample startup.
**STOP: P1 is complete. P2 has not been started. Await user UI review.**

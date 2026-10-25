# GUI Watchlist Scope Editor - Progress

> 2026-10-25: Stage 00-04 COMPLETE / INDEPENDENT REVIEW APPROVED (BLOCKING 0). Root full gate APPROVED WITH QUALIFICATIONS.
>
> Main runbook: [README.md](README.md)

## Phase gates

| Stage | Status | Evidence / next action |
|---|---|---|
| 00 Current-code/spec audit | COMPLETE | Reviewed authority docs, current Watchlist/Discovery/Catalog/Batch/GUI paths, tests, and live-monitor boundary. Baseline targeted suites passed 70 tests; GUI suite passed 42. Design discrepancies and bounded resolutions are recorded below. |
| 01 Watchlist model/edit API | COMPLETE | Approved after independent review. Implemented exclusions, canonicalization, legacy-compatible fingerprints/config restoration, lossless ordinary-block YAML edits, CAS/atomic replacement, and tests. |
| 02 Read-only listing | COMPLETE | Independent review approved. Catalog-free ListingPreviewService, shared DTOs/digest, Magapoke capability, unsupported blockers, and synthetic Chromium no-write coverage are complete. |
| 03 Scope selection/sync | COMPLETE | Pure checkbox and Catalog diff planning, exclusion preflight/masking, exact Batch/Grant-only deny overlay, immutable archive facts, and shared full-stem prediction are implemented. Independent review and the root full gate approved the stage. |
| 04 GUI integration/E2E | COMPLETE | Independent final review APPROVED / BLOCKING 0. Final affected suite 259 passed; final GUI/model/smoke 67 passed; independent editor suite 25 passed. Native Windows 1,000-row rendering and isolated full workflow passed. |

## Stage 00 audit decisions

- Existing Batch intentionally uses the last Catalog acquisition flags and does not impose a global scope-sync proof gate. Stage 03 adds a narrow safety overlay for newly saved exact exclusion IDs before Policy/Executor/resolver entry. Outer range edits remain pending Full/scope apply and must be shown as such in the GUI.
- excluded_external_ids are site-native Source.external_id strings. Unknown or unproven exclusion evidence must fail closed; no ownership reparenting or broad Core gate is introduced.
- Preview remains read-only: no Catalog/Watchlist/ZIP mutation, ticket use, or quota consumption. The GUI must explicitly warn that saved outer-boundary edits remain on the prior Catalog flags until Full/Apply.
- The editor is a separate page so existing live-monitor upper layout remains intact.

## Implementation record

- Baseline branch: feat/gui-watchlist-scope-editor, base 779df98a8fa33338d1dfdf7cc7069ea684771c86.
- Writer: /root/implementer for Stages 00-03 and initial Stage 04; explicit single-writer handover to /root for final Stage 04 safety, lifecycle, tests and documentation. Independent /root/reviewer approved every stage after blocking findings were resolved.
- Stage 00 files read: docs/SPEC.md, docs/ARCHITECTURE.md, docs/DISCOVERY_AND_BATCH.md, GUI contracts, runbook stages, current notes, and affected tests.
- Stage 00 baseline: watchlist/scope-reconciler/batch-acquisition-scope 70 passed; GUI 42 passed; no live browser or operational Catalog/Watchlist/ZIP writes.
- Stage 01 changes: watchlist/models.py, service.py, fingerprints.py, reconcile.py, package exports, tests/unit/test_watchlist.py, and note/00_core.md.
- Stage 02 changes: discovery/listing.py, listing_service.py, discovery/base.py, discovery/service.py, site_adapters/magapoke/discovery.py, discovery exports, tests/unit/test_listing_preview.py, and tests/integration/test_magapoke_discovery_browser.py.
- Stage 02 validation: 74 unit tests passed, 18 Magapoke Chromium integration tests passed, and ruff check src tests passed. No Catalog/Watchlist/ZIP/management writes or paid-resource operation occurred.
- Stage 01 validation: Watchlist unit 57 passed; scope-reconciler 19 passed; batch-acquisition-scope 9 passed; combined total 85 passed; ruff check src tests passed. Independent review approved Stage 01 after the writer fixed unknown-key loss, nested-scope comment fail-closed behavior, duplicate saved exclusions, strict saved boundaries, sorted fingerprints, serialized Watchlist CAS, and legacy fingerprint/config compatibility, and nested unknown-scope-key preservation/fail-closed editing.
- Stage 03 changes: watchlist/selection.py and lazy exports, Discovery exclusion preflight/replay and complete-list proof validation, Magapoke exclusion masking, Batch Planner/Executor deny overlays, and regression tests for checkbox/catalog previews, 140 -> 100 -> 140 holes, owner conflicts, newly excluded candidates, no partial Catalog writes, and preserved last-Catalog archive naming until Full/apply. Archive deltas now require an immutable, source-joined artifact/collision facts snapshot and shared full-stem naming calculation (including hyphenated metadata); missing, ambiguous, or colliding facts remain UNKNOWN blockers. The pure source classification helper is used by both SelectionPlanner and ScopeReconciler.
- Stage 03 validation: the targeted listing/Scope Reconciler/Batch selection passed 44 tests, including the final 14 archive-stem/facts preview tests; the affected Watchlist/Discovery/Scope/Batch/archive suite passed 254 tests; Magapoke Chromium integration passed 20 tests; `ruff check src tests` passed. Independent Stage 03 review approved; the qualified root full gate is recorded below.
- Root full-suite gate: attempt 01 was interrupted after progress stalled at a COMICFUZ initial-page test for more than eight minutes; it produced no XML or summary and is not claimed as a test failure or pass. Attempt 02 encountered a pytest-asyncio browser fixture finalizer hang; root manually closed only the verified headless fixture process and resumed. The completed run reported exactly 5700 passed, 4 failed, 0 skipped, and 5808 warnings. Three browser failures were covered by four isolated browser-family rerun passes (16.50 seconds); the fourth configuration mismatch separately passed one unchanged test against an isolated HEAD `crawler.yaml`. The mismatch was the expected dirty user `crawler.yaml` versus the distributed baseline. Root approved the Stage 03 full gate with these qualifications; no production configuration was changed.
- Live verification: not run by design; no real-site browser or operational data was used.
- Stage 04 changes: watchlist_editor.py adds a virtual Watchlist table, a hierarchical InventoryTreeModel Catalog projection with search/status filtering, independent complete-list checkbox model, async shared-CDP listing preview, basic/scope/archive-order editing, preview-before-save, per-Watchlist CAS, and async Catalog scope preview/apply. Adapter capability is checked before CDP connection and adapter-owned navigation performs the listing read; the GUI never performs a generic target goto. MainWindow adds a separate Watchlist management window and routes Full through a fresh Inventory reload and explicit key without changing Inventory checkbox selection. WatchlistService.apply_edit combines target/scope/archive-order changes in one lock/CAS/atomic replace and preserves CRLF bytes. Catalog-bound preview/save workers capture immutable listing/draft state on the GUI thread, read one real Catalog transaction, bind a content identity and source-joined artifact/run facts, and revalidate the immutable preview and Catalog identity inside the Catalog job lock. SelectionPlanner.preview_edit is consumed when a complete listing is checked, binding the listing digest, Watchlist revision, Catalog snapshot identity, freshness age, row deltas, and sibling-listing overlap evidence. Same-site sibling listing overlap is blocked before Catalog ownership is required. Legacy all-None archive order keeps its existing naming path and does not fabricate ordinals.
- Stage 04 final validation: affected Watchlist/selection/Scope/Batch/naming/archive/GUI/management suite **259 passed, 73 warnings, 0 skipped, 122.10s** (`.tmp/gwse-root-final-affected02.xml`). Following the final Scope-apply/refresh race fix, editor + existing GUI model/smoke passed **67 tests, 1 warning, 0 skipped, 47.84s** (`.tmp/gwse-root-finalgui.xml`). The independent reviewer separately ran all editor tests: **25 passed, 2 warnings**. `ruff check src tests` and `git diff --check` passed. Stage 04 production source received final independent approval with **BLOCKING 0**.
- Unresolved blocking issues: **none**. Known limits: complete-list checkbox editing is currently Magapoke-only; unsupported sites allow basic metadata/new-key registration and Catalog reference. Unknown numbered/unregistered sources or sibling evidence block selection-affecting saves. Complex YAML forms may be rejected without writing. Existing ZIPs require separate explicit maintenance for renaming. Live-site operation remains unverified.

## Final Stage 04 evidence

- GUI E2E uses temporary Watchlist/Catalog, a synthetic Adapter and a real ZIP. Checkbox → no-write Catalog-bound preview → atomic save → Full request → real DiscoveryService Full → Scope preview → concurrent flag change → stale apply rejection → re-preview/apply → Batch plan all pass. The excluded episode has no Batch candidate and the existing ZIP SHA remains unchanged. Grant-only/Executor deny coverage is in the Stage 03 shared tests.
- Additional GUI regressions cover raw Watchlist CAS, same-size/same-mtime Catalog content changes and latest CrawlRun changes, same-site sibling overlap before Source registration, manual/one-sided bounds, unsupported capability before any browser connection, supported listing worker lifecycle, page-creation failure cleanup, dirty discard/cancel, saved/draft archive order separation, new-key Full without altering execution checks, close/reopen, active jobs and snapshot/worker races.
- Snapshot refresh invalidates both preview types. A Scope apply may already have committed when a refresh arrives: its obsolete callback cannot mark the old snapshot successful, and a fresh asynchronous read refreshes editor and parent instead.
- Native Windows Qt rendering used synthetic 1,000-row data at DPR 1.5, logical 1400x1000 and 980x700. The small editor scrolls and keeps action/status controls visible. Captures were rendered without displaying a desktop window or starting a browser/worker: `.tmp/gwse-root-visual-01/editor-native-large.png`, `editor-native-small.png`, `editor-native-small-listing.png`.
- Root full-suite result remains a **qualified gate, not a clean pass**. Its three browser failures comprised one Comic DAYS DOM timeout and two Hanayume long temporary-path errors; the short-path family rerun passed four cases. The fourth failure was the distributed-config expectation against the user's changed `crawler.yaml`; an unchanged isolated copy of that test passed against HEAD's config. The run required a verified fixture-headless-process cleanup to recover a teardown hang. Evidence: `.tmp/gwse-root-full-02.xml`, `.tmp/gwse-root-failure-retry.xml`. A fresh full rerun after GUI-only follow-ups was not repeated; affected/GUI suites cover those final contracts.
- No separate Research/Probe campaign or Live verification was required/run for this feature. Browser-backed Magapoke Integration passed 20 synthetic tests during Stage 03; no real account, quota, ticket or reader was used. No tests were skipped in the recorded final gates.
- The user's pre-existing `crawler.yaml`, `watchlist.yaml`, lock files and `debug.log` were preserved; config SHA256 values were verified unchanged. All validation writes were isolated under `.tmp` or an explicitly selected short temporary test directory. No operational Catalog/Watchlist/ZIP was modified. No push or main merge was performed.

## Changed files

- `src/screenshot_crawler/gui/watchlist_editor.py`
- `src/screenshot_crawler/gui/main_window.py`
- `src/screenshot_crawler/watchlist/models.py`
- `src/screenshot_crawler/watchlist/service.py`
- `src/screenshot_crawler/watchlist/fingerprints.py`
- `src/screenshot_crawler/watchlist/reconcile.py`
- `src/screenshot_crawler/watchlist/selection.py`
- `src/screenshot_crawler/watchlist/__init__.py`
- `src/screenshot_crawler/discovery/listing.py`
- `src/screenshot_crawler/discovery/listing_service.py`
- `src/screenshot_crawler/discovery/base.py`
- `src/screenshot_crawler/discovery/service.py`
- `src/screenshot_crawler/discovery/__init__.py`
- `src/screenshot_crawler/site_adapters/magapoke/discovery.py`
- `src/screenshot_crawler/batch/exclusions.py`
- `src/screenshot_crawler/batch/planner.py`
- `src/screenshot_crawler/batch/executor.py`
- `tests/unit/test_gui_watchlist_editor.py`
- `tests/unit/test_listing_preview.py`
- `tests/unit/test_watchlist.py`
- `tests/unit/test_scope_reconciler.py`
- `tests/unit/test_batch_acquisition_scope.py`
- `tests/integration/test_magapoke_discovery_browser.py`
- `docs/GUI_README.md`
- `docs/BOUNDED_DISCOVERY.md`
- `docs/DISCOVERY_AND_BATCH.md`
- `docs/DECISIONS.md`
- `note/00_core.md`
- `note/03_magapoke.md`
- `runbooks/gui-watchlist-scope-editor/README.md`
- `runbooks/gui-watchlist-scope-editor/PROGRESS.md`
- `runbooks/gui-watchlist-scope-editor/00-contract/README.md`
- `runbooks/gui-watchlist-scope-editor/01-watchlist-service/README.md`
- `runbooks/gui-watchlist-scope-editor/02-readonly-listing/README.md`
- `runbooks/gui-watchlist-scope-editor/03-scope-planning/README.md`
- `runbooks/gui-watchlist-scope-editor/04-gui-integration/README.md`

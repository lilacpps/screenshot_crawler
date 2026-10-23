# Windows GUI Inventory — PROGRESS

> Status: **PLANNED / NOT IMPLEMENTED** (2026-10-23)
> Workstream: [README.md](README.md)
> Scope: **P0 + P1 only**. After P1: **USER UI REVIEW REQUIRED**. Do not start P2 without review.

## Phase gates

| Phase | Status | Checkpoint / expected deliverables |
|---|---|---|
| P0 Design | NOT STARTED | [00-design](00-design/README.md): existing contracts, value classifications, Inventory DTO, reader/Qt UI wireframe and tests |
| P1 Read-only GUI | NOT STARTED | [01-readonly-gui](01-readonly-gui/README.md): PySide6 app, site/work views, key selection, item detail, synthetic fixture and screenshots |
| P1 UI review | BLOCKED ON P1 | Human inspection of layout, density, sorting/selection and details |
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

Documentation only. No implementation, Catalog migration, production GUI, or test run performed as part of this runbook creation.

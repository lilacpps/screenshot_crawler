# Phase 04 — Direct-only Site Policy and Batch wiring

**Status: NOT STARTED.** Scope intentionally excludes all ticket/work/premium/paid paths.

## Goal

Expose HEROS WEB to the existing `Discovery → Catalog → Batch Planner/Executor → Runner → Packager` process with zero resource consumption.

## Site Policy

Implement `HeroswebSitePolicy` in `site_policies/herosweb.py`:
- `site = "herosweb"`, existing stable catalog ordering unless real-site evidence requires otherwise.
- `available=true` and `access_mode=free` => `PolicyDecision(True, "direct", "free")`.
- `quota`, `paid`, `unknown`, `owned`, `rental`, `grant`, unavailable and unsupported => **ineligible**, with explicit reason. **Even active quota/paid grants are not a free target in this iteration.**
- No `quota` strategy, no ticket inventory/pass, no grant-only pass, no `quota_resource`, no cooldown/resolver, and no mutation to entitlement/grant state. Resource extension APIs may be added in a later independent task.

## Integration

- Register `herosweb` in each existing `cli.py` registry: manual Viewer, Batch Viewer, Discovery and Site Policy.
- Integrate supported URL registration and complete-listing preview with GUI/Watchlist; add only site runtime configuration in `crawler.yaml` as needed.
- Configured Batch must bind canonical episode URL and Catalog external_id/work identity before Viewer entry; prefer direct URL with validated current free/identity gate, without unnecessary series roundtrip. Ad hoc crawl uses fresh same-work read-only preflight.
- Reuse current Batch planning, sequential execution, zip packaging/manifest, source status, progress, diagnostics and resumability. Failed/incomplete episode is not a completed Item/Archive. The next candidate must not start after fatal access stop.
- Existing user Watchlist/Catalog/library are NEVER touched by test execution.

## Tests / exit

- Policy table tests: only `free+available` eligible; `quota` does not become eligible even when `quota_available > 0` or an old grant exists. `paid` always excluded; absent eligibility does not mutate resources.
- Registry/CLI/GUI registration tests and synthetic BatchExecutor→Runner→ZIP integration for direct entries and failure recovery.
- Tests proving wrong Work ID, stale `free`, redirected URL, missing/nonfree Viewer, no END, invalid ZIP cannot transition Catalog to completed.
- Isolated live free batch sample (one first, then another layout/Work if available): exact selected free episodes only, no spend/login/charge action and no unintended series traversals; manifest/ZIP and statuses verified by independent audit.
- Existing Hanayume/Younganimal targeted regressions and `ruff check src tests`; list any blocked tests and reasons rather than claiming the full suite passed.

Reviewer PASS / BLOCKING 0 before Phase 05 acceptance; PROGRESS includes observed eligible/skipped counts.

# Phase 04 — Direct-only Free Policy and Standard Batch

**Initial status: NOT STARTED.** [Main contract](../README.md) / [evidence ledger](../PROGRESS.md).

## Scope / implementation

Add `src/screenshot_crawler/site_policies/comicfuz.py`, minimal CLI registry wiring, relevant tests and `note/13_comicfuz.md`. Keep site-neutral Batch Planner, Executor, CrawlerRunner, Catalog, artifact lifecycle and ZIP packager. Do not create charge/medal/ticket quota resources, grants, cooldown tables, resolver, grant-only pass or generic Batch branch.

Policy matrix:

| Source state | Eligible | Strategy | Notes |
| --- | --- | --- | --- |
| `available=true` and `access_mode=free` | yes | `direct` | subject to fresh anonymous free+ID reader gate |
| `available=false` | no | — | irrespective of old mode |
| `unknown` | no | — | includes undecidable charge/medal/account UI |
| `quota` | no | — | charge/ticket support deferred |
| `paid` / `owned` / `grant` / `rental` | no | — | not proven unconditional public-free |

There is **no automatic quota fallback** when a planned `free` source loses eligibility. At runtime, check exact current anonymous public-free status and work/episode/reader identity before saving. Prefer a direct single target-navigation path if target-local first-party proof exists; only if it does not, perform the smallest verified same-work read-only preflight. No paid/next-episode actions.

## Acceptance tests

- Policy table above; `batch plan` candidate selection, ordering, global archive numbering, stable output naming and skipped reasons.
- CLI registration for `comicfuz` in all relevant adapter/discovery/policy registries; Watchlist seed and `discover --site comicfuz`/`--key`, then `batch plan` and `batch run`.
- Synthetic isolated Catalog end-to-end: Discovery → Catalog → Planner → Executor → Runner → Manifest/ZIP → Completed with at least one free fixture. Re-Discovery and re-plan do not duplicate completed outputs.
- Negative paths: formerly free now denied; wrong work/episode; unexpected login/resource gate; unsupported reader; last-page timeout; source capture failure; ZIP failure. Must leave pending/unsucceeded state with no false Completed/Artifact.
- Targeted, affected and necessary browser-backed tests per `docs/TEST_STRATEGY.md`, `ruff check src tests`. Full suite only when shared changes warrant it. Reviewer BLOCKING 0.

**Gate:** a normal `batch plan` only selects positive free sources, and a normal `batch run` produces a correct manifest, complete ZIP and Catalog Completed/Artifact only after actual verified END. Resource mutations and charge/ticket/medal interactions remain exactly zero. Record exact local commands/results in `PROGRESS.md`.

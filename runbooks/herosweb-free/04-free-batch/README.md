# Phase 04 — Direct-only Site Policy and Batch wiring

**Status: PASS / BLOCKING 0.** Independent review is complete. Scope intentionally excludes all ticket/work/premium/paid paths.

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

## Phase 04 implementation checkpoint

- `HeroswebSitePolicy` is registered for Batch and allows only available
  `free` sources with `direct` strategy. Quota, paid, unknown, owned, rental,
  grant and unavailable sources are skipped. The policy exposes no resource,
  quota, grant-only or mutation behavior.
- The manual Viewer, Batch Viewer, Discovery and policy CLI registries contain
  `herosweb`. Runtime settings use a 1500 ms page-turn delay and 5000 ms
  inter-candidate delay; the existing 5000 ms Discovery delay and stop flags
  remain configured. Adapter output metadata supplies `genre="漫画"` while
  preserving explicit request-field precedence.
- Focused synthetic Batch coverage exercises Planner → Executor → Runner →
  Packager → Catalog, a no-END pending failure, a fresh successful retry, and
  completed-item exclusion on replanning. Generic `AccessStopError` coverage
  verifies the sequential Batch does not open a later candidate after a fatal
  stop.
- One isolated standard CLI run selected only Work A episode
  `4fe9831c6f540`, using a Watchlist exclusion scope for the other 20 rows.
  It completed as direct/free with a succeeded Run, completed Item, one present
  ZIP Artifact and ten PNG members. The source remained available/free and its
  quota/grant timestamps remained unset. Full artifact metadata and command
  output are recorded in `runbooks/herosweb-free/PROGRESS.md` and the ignored
  `output/herosweb_experiment/phase04-live-A-20261122/` directory.
- The CLI currently emits metrics beneath its default `output/metrics` even
  when other paths are explicit; the exact run-owned metrics file was moved to
  the isolated experiment directory after execution. Later isolated CLI runs
  should use the experiment directory as the working directory and pass all
  other paths explicitly.
- This live sample reused an isolated Catalog whose Work title is the earlier
  seed `HEROS WEB supplied work A`; its Watchlist label is the observed title
  `サヴマ`. The output directory reflects that Catalog title. No Catalog schema
  or production Work title was changed.

### Current Phase 04 verification

- Broad unit/CLI/registration/runtime/policy command: 451 passed and one
  optional `pykakasi` skip; no other skips. Generic fatal-stop test passed.
- The focused adapter run passed the direct Batch completion and no-END retry
  cases. A combined focused command had two Windows `WinError 3` failures
  while creating explicit-genre ZIPs beneath the long `output/h04final` temp
  path. The complete adapter-browser file then passed with a short system temp
  path: exit 0, 44 passed, 0 skipped, 5 existing Python 3.14 asyncio warnings.
  The earlier failures were a temp-path issue; the final complete run is clean.
- Changed-path Ruff completed with `All checks passed!`; `git diff --check`
  exited 0. Independent Phase 04 review passed with BLOCKING 0. Phase 05
  Tester A/B standard CLI E2E and independent artifact audit have passed; the
  final Reviewer/Lead gate passed with BLOCKING 0. See the proof set under
  `output/herosweb_experiment/phase05-independent/proofs/`.
- Independent reference regression across Hanayume, Younganimal and HERO
  policy/Batch code passed: 56 passed, 0 skipped, 64 existing warnings.

## Tests / exit

- Policy table tests: only `free+available` eligible; `quota` does not become eligible even when `quota_available > 0` or an old grant exists. `paid` always excluded; absent eligibility does not mutate resources.
- Registry/CLI/GUI registration tests and synthetic BatchExecutor→Runner→ZIP integration for direct entries and failure recovery.
- Tests proving wrong Work ID, stale `free`, redirected URL, missing/nonfree Viewer, no END, invalid ZIP cannot transition Catalog to completed.
- Isolated live free batch sample (one first, then another layout/Work if available): exact selected free episodes only, no spend/login/charge action and no unintended series traversals; manifest/ZIP and statuses verified by independent audit.
- Existing Hanayume/Younganimal targeted regressions and `ruff check src tests`; list any blocked tests and reasons rather than claiming the full suite passed.

Reviewer PASS / BLOCKING 0 before Phase 05 acceptance; PROGRESS includes observed eligible/skipped counts.

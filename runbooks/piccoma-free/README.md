# Piccoma Free-Only Site Adapter — Autonomous Runbook

Status: Required Phases 01-05 and extensions 06-B/06-C are accepted historical checkpoints. Phase 06-D code review and independent live Tester both passed with BLOCKING 0. The standard two-product Batch-to-ZIP run verified 39 lossless WebP pages, current RGB comparisons, explicit END, and Catalog completion. See [PROGRESS](PROGRESS.md) for evidence and limits.
Execution branch for the historical implementation: feat/piccoma-adapter. The current performance research/planning branch is research/piccoma-performance-20261010; preserve its existing changes.
The execution contract is defined below; verified observations, artifact checks and remaining limits are recorded in [PROGRESS](PROGRESS.md).

## Goal and authority

Implement Piccoma support for **currently and unconditionally free (¥0) episodes only**:
Watchlist → Discovery (full, incremental, and site-native bounded as supported)
→ Catalog → direct-only Batch → Crawl → manifest/ZIP.

Follow AGENTS.md, docs/SPEC.md, docs/ARCHITECTURE.md,
docs/DISCOVERY_AND_BATCH.md, docs/CAPTURE_STRATEGY.md,
docs/TEST_STRATEGY.md, docs/SITE_ADAPTER_GUIDE.md, and
docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md. These authorities take priority
over this implementation plan. No generalized Core redesign without proof
that the existing extension points cannot support the site.

## Assigned roles

| Role | Model / effort | Ownership |
| --- | --- | --- |
| Lead/root | gpt-6.1-sol / xhigh (Very High) | Overall consistency, design decisions, checkpoints and orchestration |
| Explorer | gpt-6-luna / xhigh (Very High) | Existing-code investigation, live-site observation, specifications and risks (read-only) |
| Implementer | gpt-6-luna / xhigh (Very High) | Sole production writer, PoCs, implementation, unit/integration tests |
| Reviewer | gpt-6.1-sol / high | Independent bugs, contract/security/access safety/regression review (read-only) |
| Tester, as needed | gpt-6-luna / high | Independent live E2E, logs, images and artifacts; no production source edits |

Use site_adapter_explorer, site_adapter_implementer, site_adapter_reviewer,
site_adapter_tester defined in .codex/config.toml. The existing
site_adapter_worker remains a legacy role for prior tasks, not this work.
Lead selects its own model and effort at session start, not as a repo-global
override.

Per phase: Lead states objective, evidence, allowed paths, constraints, tests,
acceptance and exit → Explorer resolves missing facts → Lead decides scope →
Implementer changes files → Reviewer reports BLOCKING/NON-BLOCKING/VERIFIED →
Implementer fixes BLOCKING → Reviewer rechecks → Lead advances. Tester performs
independent browser/E2E verification when needed. Do not create ceremonial
agent turns for trivial work. One production writer, and only **one operator
of the live shared browser at a time**; parallelism is for independent
read-only code investigation.

## Scope and exclusions

IN: episodes truly offered unconditionally as ¥0, including a time-limited
campaign **only while** it is currently ¥0, backed by positive evidence.
Only live-verified viewer modes are in scope.

OUT: 待てば¥0, ¥0+, 爆読み¥0, gift/ticket/voucher, time charge,
quota, coin/point/payment, rental, previously unlocked or purchased content,
and any personally owned material whose readability does not prove public ¥0.
No charge, purchase, login, ticket or unlock click; no DRM/access-control
bypass. A legitimate page-turn in an already-verified free reader is allowed
only after the control has been proven to be non-consuming. Never follow a
paid next-episode link. Quota semantics will be designed separately.

If site state is ambiguous, mark UNKNOWN, not free. A current readable viewer
is not sufficient proof of unconditional ¥0 in a logged-in profile. Discovery
and pre-crawl access checks must both enforce this. Skip/stop rather than fall
back to another access resource. Never use real quota as a negative test.

## Seed URLs and hypotheses

- https://piccoma.com/web/viewer/28600/1910027
- https://piccoma.com/web/viewer/28600/4142286
- https://piccoma.com/web/viewer/28606/2001009
- https://piccoma.com/web/product/28600/episodes

Hypothesis (must verify): 28600/28606 = product ID, final viewer segment =
episode ID. Check whether episode ID is globally unique; if not, persist a
stable composite source identity. Preserve canonical URLs and Watchlist
work_key independently. Derive a product 28606 episode index only after
verification. The three URLs are study seeds, **not presumed currently free**.
A public 28600 HTML listing displays a ¥0 label on some episodes; this does
not establish that a specific seed viewer can be entered without a charge.

Full episode order must follow the **native complete list**, not numeric
episode IDs or numbering relative to a bounded range. Honor the existing
global position and archive naming contracts. Never hard-code live episode
counts, which change.

Live listing, viewer navigation, terminal state, and the two-product
Discovery-to-ZIP path were verified through shared Crawler Chrome/CDP under
the historical PNG output contract. For the observed horizontal reader, a
strict exact-response-to-image-to-canvas draw graph was proven and replayed
with the browser's normal JPEG decoder, followed by a verified solid-white
composite. Phase 06-D now encodes those verified RGB pixels as lossless WebP;
native encoding fallback and Core fallback remain PNG. Raw tiled JPEG bytes
are not saved as page output. Independent live verification of the WebP
change passed for all 39 pages in two selected episodes, with no fallback.
Other viewer/draw/backdrop variants remain unsupported. See PROGRESS.md for
observed counts, outputs, and limits.

## Required stages

1. [01: repository and site Probe](01-site-probe/README.md)
2. [02: Discovery](02-discovery/README.md)
3. [03: Viewer and Capture](03-viewer-capture/README.md)
4. [04: direct-only Site Policy and Batch](04-batch/README.md)
5. [05: independent E2E and final gate](05-e2e/README.md)

Additional adopted plan (2026-10-10): [07: full JSON trace transfer and crawler.yaml pacing 200ms](07-performance/README.md). Stages A and B are implemented and passed independent review; Stage C interleaved manual comparison, 24-page Batch END/ZIP/Catalog checks, and fresh per-page manifest audit passed. Final Stage C Reviewer review passed with BLOCKING 0. Existing DPR tolerance/raw viewport equality is retained. Phase 07 changes neither the source-native image pipeline nor rendering-stability checks; WebP method/PNG/refactoring remain outside its implementation scope. The separate [genre correction plan](../../research/piccoma-performance/GENRE_FIX_PLAN.md) remains planned.

Lead may split, repeat, or reorder stages based on evidence, but may not
advance across an unresolved BLOCKING review finding. Unavailable Chrome,
region blocking, missing ¥0 examples, and changed site behavior are explicit
blockers, not invitations to guess.

## Site-neutral safety contract

- No Discovery partial success from incomplete list/pagination. Validate
  IDs, counts, ordering, target identity, duplicates and access classification
  **before** yielding records. Unknown states may be represented individually
  when the list itself is complete, but conflicting/missing list data is
  incomplete.
- Stale Catalog free never authorizes entry. Verify target identity and
  genuinely free conditions against current live state before capture.
- Do not assume a sample viewer is public; prefer current ¥0 items found by
  verified Discovery, and keep unsupported states out of Batch.
- Capture priority from docs/CAPTURE_STRATEGY.md: original response bytes
  → provably attributable source-native pixels → rendered canvas → safe
  Locator screenshot. Preserve JPEG/WebP/PNG if exact source is known. Never
  claim provenance from just filename/dimensions; do not save incomplete
  spreads or traverse into next content.
- Preserve timeout, max_pages, same-content, AccessGuard/pacing and manifest
  authority. Fail closed on unknown panels, unproven END, unbounded loading,
  access control and cross-product redirects.
- No site-specific branches in shared Runner/Batch; avoid new schema and
  premature reuse abstractions.
- Do not commit copyrighted image payloads, user cookies, tokens, signed URLs,
  profile data or unsanitized logs.

## Working environment / evidence

Work on feat/piccoma-adapter; do not overwrite unrelated local changes or
merge automatically. Use the existing shared dedicated Crawler Chrome via
Playwright/CDP. All real tests use isolated files, for example:

- output/piccoma_experiment/watchlist.yaml
- output/piccoma_experiment/catalog.sqlite
- output/piccoma_experiment/crawls/
- output/piccoma_experiment/library/
- a protected evidence directory outside auto-cleaned output/tmp

Never silently fall back to catalog.sqlite or user production outputs. A git
branch does not isolate browser profile or runtime files.

After each stage, record progress in a newly created
runbooks/piccoma-free/PROGRESS.md: last commit, verified facts vs hypotheses,
test counts/skip reasons, reviewer findings, remaining risks and next action.
Maintain note/09_piccoma.md and site README with current **implemented**
behavior once production code exists; do not claim planned code is present.
Use existing docs to record new general decisions when necessary.

## Final acceptance

- Discover full native lists for both products, or report explicit unsupported
  product/list variant and why.
- Correctly identify truly public ¥0 vs quota/paid/owned/unknown without
  entitlement consumption.
- Demonstrate direct-only Batch and verified capture of **at least one
  currently ¥0 episode per product, if such eligible items exist**.
- Audit first/middle/last body page, all page counts/order/quality, END,
  manifest/ZIP, and Catalog completion via the **real standard pipeline**.
- Reviewer has zero BLOCKING; Tester independently verifies risky real-site
  outputs where available. If live testing cannot run, report NOT VERIFIED.
- Tests and scope limits documented, including deferred ticket work.
- Leave final changes on a reviewable feature branch; no automatic merge.

See stage runbooks for exact deliverables and test matrices.

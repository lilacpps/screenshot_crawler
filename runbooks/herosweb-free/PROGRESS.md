# HERO'S WEB Free-only Site Adapter — Progress

Date initialized: 2026-11-22  
Status: **RUNBOOK WRITTEN; IMPLEMENTATION NOT STARTED; LIVE-SITE FACTS UNVERIFIED**.  
Site key planned: `herosweb`.  
Implementation branch: create from the then-current `main`, e.g. `feat/herosweb-free`; do not auto-merge.  
Authority: [README.md](README.md), subordinate to `AGENTS.md` and repository design documents.

## Confirmed user requirements

- Build complete `Discovery → Catalog → Batch Run → Manifest / ZIP`, using Hanayume / Younganimal implementations as references but not assuming their DOM/layout/access semantics transfer.
- First iteration only directly free episodes. Discovery **must recognize** `quota` and `paid`; their ticket, rental, wait or charge actions are deferred. Keep `unknown` for ambiguity.
- Fidelity priority: unchanged correct original bytes (or rigorously lossless JPEG restoration when possible) → verified source-native lossless WebP → rendered canvas PNG → body screenshot PNG.
- User corrected the earlier `/seriesh/` suggestion: reports `https://heros-web.com/series/fdf345d17d2b6` works for 「はんばけ」. This is user-observed; independent current-site URL/identity checks **pending**. `/seriesh/` is not a supported canonical seed.

## Evidence status (do not elevate hypotheses)

| Topic | Classification | Detail / next proof |
| --- | --- | --- |
| Work URL example | USER-OBSERVED | `https://heros-web.com/series/fdf345d17d2b6`, confirm canonical identity in Phase 01 |
| `/seriesh/` | CORRECTED / UNSUPPORTED | Mistaken prior suggestion; do not add alias without independent evidence |
| Site platform / DOM / Viewer roles | HYPOTHESIS | Similar to Hanayume/Younganimal; must probe current HERO'S WEB |
| Complete episode listing / range routes | UNKNOWN | Need whole-Work all-or-nothing live traversal |
| `free/quota/paid` exact markers | UNKNOWN | Need row-scoped/native observed semantics; do not guess |
| Original response bytes / scramble mapping | UNKNOWN | Need real response-to-page and decoded pixel proof |
| Source-native WebP possibility | HYPOTHESIS | Existing two-site capture pattern, no HERO'S WEB proof |
| Safe direct Batch/free END | UNKNOWN | Need actual non-consuming Viewer and full live E2E |
| Tests and regressions | NOT RUN | Documentation-only change; record actual future test results |

## Phase gate

| Phase | State | Evidence to attach |
| --- | --- | --- |
| [01 Site Probe](01-site-probe/README.md) | NOT STARTED | Canonical sample Work + free episode; access/classification; Viewer/end; image candidate; Reviewer |
| [02 Discovery](02-discovery/README.md) | NOT STARTED | Complete all-position unique inventory; full/incremental Catalog; safe failed traversal; Reviewer |
| [03 Viewer/Capture](03-viewer-capture/README.md) | NOT STARTED | Exact free Viewer, body order, END, original/native versus PNG evidence; Reviewer |
| [04 Free Batch](04-free-batch/README.md) | NOT STARTED | Direct-only Site Policy, CLI/GUI wiring, synthetic/limited live Batch, unchanged quota state |
| [05 Independent E2E](05-e2e/README.md) | NOT STARTED | Standard CLI E2E, independently audited ZIP/CRC/pixels and Catalog, regression and Reviewer |

## Checkpoint template (append, never overwrite old factual claims)

- Timestamp, implementation branch/commit and diff scope.
- Phase, objective and finite probe allowance.
- OBSERVED, HYPOTHESIS, UNKNOWN, BLOCKED: concrete evidence (no account secrets or copyrighted page images in Git).
- Exact tested canonical URLs/Work and episode identities, current access label, role/layout/END, page count and capture modes. No signed query/cookie/token.
- Tests: command, passes/fails/skips, actual artifact location, what was NOT run and why.
- Independent Reviewer: PASS / BLOCKING and resolution, Tester evidence if used.
- Next phase and unresolved decision(s).

## Initial instruction to Codex

Read `runbooks/herosweb-free/README.md`, this file, Phase 01, the repository authorities and current Hanayume/Younganimal code. Create an isolated implementation branch from current `main`, preserve all user work, execute Phase 01 bounded current-site verification, and advance through Phases 02–05 as their evidence gates permit. Never click ticket/paid/wait or start rights acquisition, and do not assert implementation or E2E PASS until actually observed. Update this progress file and `note/16_herosweb.md` as real implementation is added.

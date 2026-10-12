# ComicFUZ (comic-fuz.com) — anonymous public-free Site Adapter Runbook

**Status: PLANNED / NOT IMPLEMENTED (2026-10-12).** Phase 01 site evidence and all implementation/test gates remain **NOT VERIFIED**; see [PROGRESS](PROGRESS.md).
**Branch:** `feat/comicfuz-adapter` (created from `main`). **Site key:** `comicfuz`.
**Seed:** https://comic-fuz.com/manga/1970?position=thumbnail
The query parameter is an input hint, not a proven canonical identity; determine the canonical work route in Phase 01.

## 1. Goal, scope and explicit deferral

Implement a new independent ComicFUZ adapter in `screenshot_crawler`:
`Watchlist → discover (full/incremental; bounded when provable) → Catalog → batch plan/run → Crawl → Manifest/ZIP → Completed`.
**The v1 success criterion is anonymous, presently public and unconditionally free episode(s) only.** No login is assumed or required. Do not use a logged-in/purchased entitlement to prove free availability.

**Not in v1:** login/account recognition; charge recovery, balance, eligibility or consumption; tickets; Silver/Gold medals; payment, purchase, rental, unlock, grant-only flows; app-only episodes. The user has explicitly postponed investigation of these mechanisms until the next ticket/charge implementation step because the current browser is logged out. **Do not block free-only completion for lacking any of that information.** Do not invent resource, cooldown, per-work limits or expiry models now. Revisit as a separate runbook/phase after v1.

Anonymous listing rows which cannot be positively shown to be public-free may still be registered in Catalog as `unknown`, or `paid`/`quota` ONLY with reliable first-party evidence; they must never become eligible through guessed semantics. Preserve enough stable source identity to support later re-Discovery and independent access-policy extension. Do not require numeric charge/ticket/medal fields in the current parser.

The seed is a **probe work**, not a claim that it currently offers free episodes or exposes every historical episode anonymously. If it has no verifiable free sample, find a second current public-free ComicFUZ work for v1 E2E; report this explicitly. If none is available, implement and test everything possible, then mark the live gate BLOCKED/NOT VERIFIED, not PASS.

## 2. Authority and implementation strategy

Read: `AGENTS.md`; `docs/SPEC.md`; `docs/ARCHITECTURE.md`; `docs/DISCOVERY_AND_BATCH.md`; `docs/ACCESS_CONTROL_AND_PACING.md`; `docs/CAPTURE_STRATEGY.md`; `docs/TEST_STRATEGY.md`; `docs/CODEX_IMPLEMENTATION_GUIDE.md`; `docs/SITE_ADAPTER_GUIDE.md`; `docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md`, current code/tests and site notes. Authority order is defined in `AGENTS.md`; this runbook is narrower, not overriding.

Reference code, **in order of relevance to check, not an asserted shared platform**:
- `site_adapters/zeblack/`: protobuf network/list observation, catalog identity, free versus work-ticket states.
- `site_adapters/mangaone/`: chapter URL/list and visible-page viewer.
- `site_adapters/comicdays/`: access guard, free evidence and native capture.
- `site_adapters/piccoma/`, `hanayume/`, `younganimal/`: direct-only free Batch, site-native ordering and image fidelity.
ComicFUZ might share a vendor or protocols with existing sites, but **its current API, response encoding, viewer family, encryption, tiling, image format and navigation are UNKNOWN until observed**. Never transplant protobuf schemas/DOM selectors/tile maps based on superficial similarity. Old third-party clients, if consulted, are hypothesis sources, not authoritative current live behavior.

Prefer independent `src/screenshot_crawler/site_adapters/comicfuz/` and `src/screenshot_crawler/site_policies/comicfuz.py`. Reuse shared Session, AccessGuard, DiscoveryService, Catalog, Planner, Executor, Runner and Packager. No Core/Catalog schema migrations or deep refactor for a single site unless the Lead documents a concrete blocked use case, options/tradeoffs and reviewer-approved minimal change. There is no mandatory cross-site shared code extraction.

### Multi-agent ownership

Use the existing roles/config in `.codex/` and `docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md`:
- **Lead/root**: `gpt-6.1-sol` / `xhigh` — phase contract, evidence, decisions, checkpoint and signoff.
- **Explorer**: `site_adapter_explorer` / `gpt-6-luna` `xhigh` — read-only independent investigation.
- **Implementer**: `site_adapter_implementer` / `gpt-6-luna` `xhigh` — sole production writer and bounded probes.
- **Reviewer**: `site_adapter_reviewer` / `gpt-6.1-sol` `high` — independent BLOCKING/NON-BLOCKING review.
- **Tester**: `site_adapter_tester` / `gpt-6-luna` `high` — independent live/E2E/artifact audit when needed; no production edits.

Lead controls shared Chrome/CDP with one operator at a time. Read-only research can overlap where safe, but no concurrent production writers. Validate available agent models at execution; do not silently substitute. For each phase, Lead states objective, evidence, allowed files, constraints, acceptance, tests and checkpoint; Reviewer inspects the actual diff. Fix BLOCKING and repeat review before next phase. Continue autonomously through v1 rather than ending after reconnaissance; a truly external blocker is an explicit partial result, not permission to assume behavior.

## 3. Non-negotiable contracts

1. **Anonymous access, no consumption.** No login, click on charge/ticket/medal/purchase/pay/unlock/rent, paid next-episode navigation or resource acquisition. Page-turn controls must be shown non-consuming. No auth/DRM bypass. Never reuse active personal grants as `free`.
2. **Positive public-free proof.** `free` requires an exact public row/API state showing unconditional current eligibility, corroborated by a non-consuming anonymous reader entry. The mere ability to render a chapter, absence of a price/expiry badge, or a thumbnail is not enough. If labels are absent, investigate other first-party public state; do not hardcode “visible=free”. Conflicting evidence fails closed.
3. **Live crawl gate.** A previously Cataloged free source may change. At entry confirm same work/episode and currently public-free state from an observed site-native signal (target-local if possible; otherwise a bounded fresh public listing probe). Do not force a whole-work reread for every direct crawl if safe target-local proof exists. Stop before capture if proof fails; never fall back to resource consumption.
4. **Identity/order.** Validate work and episode IDs in exact URLs/first-party metadata. Choose `source.external_id` globally unique within `comicfuz` (composite work+episode when episode ID uniqueness is not proven). Preserve native oldest-to-newest global positions where provable; `discovery_scope` must not renumber a segment 001..N. Separate order labels from authoritative positions. Never silently mislabel uncertain positions.
5. **Discovery completeness.** `full` must validate total/pagination/coverage and duplicate/reordered/looped lists before claiming complete reconciliation. Missing public historical episodes may be unobservable; do not mark absent records unavailable without a provably complete scope. `incremental` uses latest-first known streak by default and leaves unvisited source availability unchanged; refresh every actually observed free/access/expiry field. If the site safely exposes an explicit removal for a known ID, handle it only with first-party evidence.
6. **Date/expiry.** Update `free_until` from actual observed public deadlines on every observed source; if the validated source has no deadline, explicitly clear stale expiry. A display deadline alone is not a proof of current free availability; no invented expiry. An expired campaign is not eligible.
7. **Capture fidelity.** Prefer attributable original JPEG/WebP/PNG bytes when available and authorized; otherwise proven source-native pixels/safe viewer reconstruction, then clean rendered canvas/image, then screenshot as last resort. Use exact page/source attribution and pixel/geometry evidence; preserve native bytes, use lossless formats for derived pixels. Never substitute compressed tile/thumbnail bytes for a full page without reconstructing and verifying correct content. Do not circumvent access protections.
8. **Page lifecycle.** Detect first page, lazy loading, identity change, spread in RTL reading order where observed, blank/promotional screens, actual END and NEXT_CONTENT, and resumed reader position. Do not infer END from a fixed sleep or fixed page count; no missing half, repeated page, extra recommendation/ad or next episode in saved body. Respect max_pages, same-content guard, bounded retries and access pacing.
9. **Data safety.** Use feature branch and isolated Watchlist/Catalog/output for live work. No real production Catalog modifications, no overwrite of existing downloaded files, no sensitive logs/cookies/auth headers, no copyrighted page fixtures in Git. Successful validated END plus packaging alone can mark Completed/Artifact; failures stay pending and are retryable.

## 4. Required phases / autonomous execution

| Phase | Contract | Review gate |
| --- | --- | --- |
| [01 — Site probe](01-site-probe/README.md) | Establish anonymous listing, stable IDs, positive free evidence, viewer and source formats; log UNKNOWNs | Evidence sufficient for the free-only subset |
| [02 — Discovery](02-discovery/README.md) | Full/incremental, bounded only if native positions are proved, Catalog reconciliation | No silent partial list, collisions or wrong free class |
| [03 — Viewer/Capture](03-viewer-capture/README.md) | Direct target and verified free preflight; correct source/page/END | No missing, repeated, wrong-episode or unsupported output |
| [04 — Batch](04-batch/README.md) | Direct-only free policy and normal CLI pipeline | Correct skip/complete/ZIP behavior; no resource actions |
| [05 — E2E](05-e2e/README.md) | Independent isolated CLI, image and Catalog audit | Reviewer BLOCKING 0; Tester evidence or explicit NOT VERIFIED |

Stage documents are the execution contracts; [PROGRESS](PROGRESS.md) is the evidence/status ledger. Phase 01 is not a separate terminal research task: after sufficient free-only evidence, move through 02–05, adding small bounded probes only where a material unknown blocks implementation. Do not probe/develop deferred charge/ticket/medal features as a prerequisite.

## 5. Expected files and change constraints

- `src/screenshot_crawler/site_adapters/comicfuz/{__init__.py,discovery.py,adapter.py,access.py,README.md}` plus a capture helper only if proven useful.
- `src/screenshot_crawler/site_policies/comicfuz.py` (free only, direct).
- Minimal registration in `src/screenshot_crawler/cli.py` and relevant registries/Watchlist integration.
- Focused `tests/unit/test_comicfuz_*.py` and `tests/integration/test_comicfuz_*.py`; `note/13_comicfuz.md` on implementation, consistent with `note/README.md`.
- Site-local probe evidence and [PROGRESS](PROGRESS.md) updates. Do not add unused YAML mirrors or a generic client API layer without concrete benefit.

**Definition of Done:** free-only `full` and `incremental` Discovery work with faithful identities/access, standard `batch plan` selects only public free, normal `batch run` produces a verified complete Manifest/ZIP and Catalog Completed state for at least one currently free real episode (preferably two different layout examples), and independent review shows BLOCKING 0. If an external constraint prevents live validation, report exact partial scope and mark live gates NOT VERIFIED. Deferred charge/ticket/medal features are NOT v1 defects.

## 6. Next phase (separate user authorization)

After v1, investigate login state and ComicFUZ charge/ticket/medal semantics from live first-party state: work versus site scope, eligibility, reset clock, active grant and expiry, actual cost and explicit confirmation, idempotency and rerun rules. Then design a resource-aware `SitePolicy` / grant-only / deferred access flow reusing existing Batch orchestration if justified. **No inferred cooldown, currency model, entitlement click or grant persistence in the current work.**

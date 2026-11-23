# HERO'S WEB — Free-only Site Adapter Runbook

Status: **Phases 01-06 PASS / BLOCKING 0. A10 passed independent full A capture audit (10/10 VP8L pages at 1440x2048); B14 passed independent full B capture audit (38/38 VP8L pages at 844x1200), both with actual END and ZIP/Catalog proof. B14 also verified exact source-PNG RGBA, 16-tile history, replay and stability. Original JPEG bytes/recovery remain unproven and are separate from Phase 06.** (2026-11-23)
Site key: `herosweb`  
Implementation: new feature branch from the then-current `main`; **do not merge automatically**.  
Authority for execution evidence: [PROGRESS.md](PROGRESS.md).

## 1. Goal and scope

Add a dedicated HERO'S WEB adapter to the existing `screenshot_crawler` pipeline:

`Watchlist / URL registration → full or incremental Discovery → Catalog → Batch Plan → Batch Run → Viewer → Manifest / ZIP`.

This iteration **downloads only directly readable, non-consuming `free` episodes**. Discovery must also recognize and persist evidence-supported `quota`, `paid`, and `unknown` classifications. No tickets, waiting, daily recovery, rental checkout, paid coins, account-resource inventory, purchase, or rights-acquisition action in this iteration. An already-accessible rental does not become `free` merely because the viewer opens; any later support is separate.

HERO'S WEB current-site observations and verification evidence are recorded in [PROGRESS.md](PROGRESS.md) and `note/16_herosweb.md`. Hanayume and Younganimal evidence is reference material only; each HERO'S WEB gate uses its own current-site probe, tests and independent review.

### User-confirmed URL correction

- User reports `https://heros-web.com/series/fdf345d17d2b6` is accessible for 「はんばけ」 after changing `/seriesh/` to `/series/`. Treat **`/series/` as the initial candidate**, not `/seriesh/`.
- Previous `/seriesh/fdf345d17d2b6` suggestion was erroneous/unverified: **never add it as a canonical seed**. Do not silently normalize arbitrary `/seriesh/` URLs to `/series/`; prove any conversion with site identity/redirect evidence, otherwise reject and request the canonical URL.
- At initial planning the Work/episode ID formats and route behavior were **UNKNOWN**. Phase 01 observed 13-character lowercase hexadecimal Work and episode IDs, `/episodes/<episode-id>` reader routes, and `/series/<work-id>/<range>` listing routes on the two supplied Works; the adapter validates only this proven route family. Redirects are rejected by the guarded document transport.
- Legacy `viewer.heros-web.com` pages/search indices are not evidence of the post-2026-06-01 production website. Site changeover: https://viewer.heros-web.com/news/entry/heros-info2603 . Probe the current `https://heros-web.com/` only.

## 2. Authorities and references

Before implementation read, in repository-authority order:
- `AGENTS.md`; `docs/SPEC.md`; `docs/ARCHITECTURE.md`;
- `docs/DISCOVERY_AND_BATCH.md`; `docs/ACCESS_CONTROL_AND_PACING.md`; `docs/DECISIONS.md`;
- `docs/CAPTURE_STRATEGY.md`; `docs/SITE_ADAPTER_GUIDE.md`; `docs/TEST_STRATEGY.md`;
- `docs/CODEX_IMPLEMENTATION_GUIDE.md`; `docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md`.

Reference **current main**, not stale research branches:
- `site_adapters/hanayume/{discovery,adapter,access,native_capture}.py`;
  `site_policies/hanayume.py`; `runbooks/hanayume-free/`; `note/10_hanayume.md`.
- `site_adapters/younganimal/{discovery,adapter,access,capture,native_capture}.py`;
  `site_policies/younganimal.py`; `runbooks/younganimal-adapter/`; `note/11_younganimal.md`.
- Their relevant unit/browser/Batch tests, `src/screenshot_crawler/cli.py`, `registration/resolver.py`, `registration/draft.py`, `crawler.yaml`.

### Crucial differences to inspect, not transplant blindly

| Area | Hanayume | Younganimal | HERO'S WEB decision |
| --- | --- | --- | --- |
| Range routes | Seed-episode based `/episodes/<seed>/<n>` | Work based `/series/<work>/<n>` | Derive from current website; don't assume either |
| Listing DOM | `.series-eplist-wrap` | `.series-eplist-main` | Observe and validate own row scope |
| `今なら無料` | May be free with positive same-work auth proof | Needs stronger exact native/auth entitlement proof | No badge-only promotion to free |
| Viewer | Special leading blank, wrapper/count variants | Multiple distinct body/lead/tail/seek profiles | Prove roles, stable ordering, END and all variants in tested scope |
| Native capture | Source-canvas draw snapshot + verified WebP | Geometry/epoch/source replay + verified WebP | Reuse design, not pixel dimensions or presumed layout |
| Batch | Catalog-based direct entry with guard | Catalog-based direct entry with exact episode/work proof | Prefer direct only if HERO'S WEB confirms non-consuming entry |

**Implementation preference:** site-local independent adapter and policy; extract only small already-verified reusable helpers. Do not refactor Core/Batch or change Catalog schema for speculative abstractions.

## 3. Access contract (Discovery versus execution)

| Catalog access_mode | Required evidence | Phase 04 action |
| --- | --- | --- |
| `free` | Exact same-work episode is directly readable **without new grant, login-derived checkout, ticket, rental or coin consumption**; positive current label/native/rendered evidence as applicable | `direct` only |
| `quota` | Current site evidence identifies access by a ticket, wait or other consumable/limited entitlement; entry is not executed in this iteration | Persist, skip |
| `paid` | Current site evidence identifies pay/coin-only gated entry, not merely a generic locked icon | Persist, skip |
| `unknown` | Ambiguous/missing/conflicting access signals, uncertain auth, unexpected mode, unresolved native response | Persist, skip |

- Scope labels to the exact episode row. Do not infer access from neighboring rows, color, icon alone, stale login, or shared Comici identity from another site.
- `今なら無料`, `無料`, `レンタル中`, `待つと無料` and API names are **candidates only** until exact current HERO'S WEB samples are observed. If native signals distinguish `trial`, `memberOnlyFree`, `waitAndFree`, `paidContent`, confirm their actual semantics on this site before mapping.
- An independently granted but ticket-origin episode may have a current viewer entitlement; do **not** treat this as `free` for this iteration. Record existing grant/expiry only when authoritative and compatible with the existing Catalog contract, without consuming or altering it.
- Do not force ambiguous states to `quota` or `paid` for completeness statistics. Document observed `raw_labels` as diagnostics if needed; don't corrupt title/source identity or extend Catalog schema for raw badges.
- An episode having `free` in Catalog is not proof its current viewer entry remains readable. Recheck same episode/work identity and deny/purchase gates at entry. **Never click through** a changed gate.

## 4. Discovery integrity

- Accept strict canonical work seed, validate HTTPS host/port, prohibit credentialed URLs/unsafe redirects, and bind all episode IDs to that Work. Require positive site proof to resolve a supplied episode URL to its Work.
- Select ONE fully observed enumeration method (range navigation, loader, etc.). **Buffer complete listing before yielding any record**, including incremental mode. Compare declared range counts/coverage, first/last, ordered positions, unique IDs, Work identity and stable final signal; bound every navigation/loop.
- An incomplete/429/challenge/timeout listing **must not** be treated as complete or mark unvisited old sources `unavailable`. Preserve listing position and source identity across updates, split parts, repeated titles and exclusions.
- Reuse existing complete-listing preview/exclusion replay extension points when supported. No Discovery-side Catalog write.
- Maintain `available`, `access_mode`, grant state and full/incremental semantics per existing service contract, without reinterpreting one as the other.

## 5. Capture fidelity: exact priority

Follow `docs/CAPTURE_STRATEGY.md`, prove source-to-visible-page identity, and keep page order:

1. **Original / lossless transformed original bytes:** If exact complete displayed body-page bytes exist in network responses, save unchanged in their original JPEG/WebP/PNG format. If a scrambled baseline JPEG can be **losslessly** reconstructed by validated MCU/DCT coefficient rearrangement, that is eligible here only after a rigorous page/mapping proof. A scrambled raw response is *not* a valid completed page and cannot simply be saved as original.
2. **Verified source-native pixels → lossless WebP:** If bytes cannot be used, attribute source pixels and any tile permutation, crop/scale/draw sequence to the exact displayed body page. Snapshot mutable canvas at draw time; validate re-rendered pixel mapping and source dimensions, encode **lossless** WebP and verify decoded RGBA against captured source-native pixels. If encoding validation fails but source pixels are verified, retain lossless source-native PNG per the shared capture strategy.
3. **Completed body canvas → PNG:** If source attribution is not provable, capture stable rendered body canvas pixels without UI/ads. Validate DOM/canvas identity, draw epochs, dimensions and no race.
4. **Body Locator screenshot → PNG:** Only if direct canvas extraction is unavailable. Explicitly bounded and content-only; viewport screenshot is last resort.

Do not claim source-original when only rendered pixels were saved. Lossless WebP preserves reconstructed pixels, not the original JPEG bitstream. A response with an unproven scramble table, mismatched page identity, missing spread half or arbitrary dimensions fails back to safer capture. Avoid synchronous encode/hash/network inside `drawImage` hooks; bounded candidate caching and cleanup. Compare first/middle/last, spreads, transformed geometry and slow-render cases. Preserve mixed formats and truthful manifest/provenance. **Do not block the viewer merely to obtain higher-priority bytes.**

Any third-party downloader/API hints (including `/api/book/contentsInfo` and `scramble`) are *unverified hypotheses*, never grounds to assume page mapping or issue unauthorized requests. Observe first-party network traffic generated by legitimate free viewing, and stop on access rejection.

## 6. Engineering boundaries

Expected site-local files (adjust to observed site architecture):
```text
src/screenshot_crawler/site_adapters/herosweb/
    __init__.py  discovery.py  adapter.py  access.py  native_capture.py  README.md
src/screenshot_crawler/site_policies/herosweb.py
tests/unit/test_herosweb_*.py
tests/integration/test_herosweb_*_browser.py
note/16_herosweb.md
```
Wire the necessary CLI registries (`_registry`, `_batch_adapter_registry`, `_discovery_registry`, `_batch_policy_registry`), URL/GUI registration preview support and site `crawler.yaml` settings. Follow `registration/draft.py`'s existing preview-site capability contract instead of blindly advertising unsupported preview.

Do not add site-specific branches to generic Core/Runner/Batch. Do not change Catalog schema, direct/grant semantics, other adapters, downloader defaults, or global browser profile without an evidenced blocker and explicit design review. Site owns access and capture, while existing services own Catalog, BrowserSession/CDP, planning, status, packaging and resume.

One shared Crawler Chrome operator at a time. Use isolated ignored `output/herosweb_experiment/{watchlist.yaml,catalog.sqlite,batch,library,diagnostics}` with **every** CLI path explicit; never fall back to real Watchlist/Catalog/library. Preserve working tree and existing sessions. No browser/profile launch from adapter. No auth bypass, WAF workaround, CAPTCHA automation, brute retry or unauthorised content access. Bounded timeouts, pacing, AccessGuard (403/429/challenge/captcha stop), max-pages and same-content guards. Do not commit raw manga images, cookies, JWTs, signed URLs or personal account payloads.

## 7. Phases and gates

| Phase | Task | Acceptance |
| --- | --- | --- |
| [01 Site Probe](01-site-probe/README.md) | Current URL/identity, complete-list candidate, access signals, viewer, original/native candidate | Bounded evidence; OBSERVED / INFERRED / UNKNOWN distinguished; independent review |
| [02 Discovery](02-discovery/README.md) | Registration, full/incremental inventory, exact classification, Catalog | Strict all-or-nothing listing + relevant unit/integration checks |
| [03 Viewer / Capture](03-viewer-capture/README.md) | Free-only entry/END, original-first and verified fallbacks | Identity/ordering/capture proof, browser tests, independent review |
| [04 Batch](04-free-batch/README.md) | Direct-only policy, CLI wiring, sequential ZIP | PASS / BLOCKING 0; synthetic retry/no-END, isolated CLI sample and independent audit pass |
| [05 E2E](05-e2e/README.md) | Isolated live CLI E2E and artifact audit | Tester A/B CLI runs, independent artifact/Catalog audit and final Reviewer/Lead gate PASS / BLOCKING 0; prior two 429 Runs preserved |

Phase 01 must not become a research-only dead end: move directly through supported phases when evidence suffices. Probe and implement in small bounded slices; reviewer findings on identity, entitlement, incomplete inventory or capture pixels are blocking until corrected. If a higher-fidelity capture path cannot be proven in a bounded investigation, complete the correct PNG path and record the native follow-up rather than falsifying success.

## 8. Codex workflow and final report

Use `.codex/agents/site-adapter-*.toml` roles and `docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md` where supported: Lead scopes, Explorer read-only, one Implementer production writer, independent Reviewer read-only, Tester for risky live E2E. No concurrent writes to production or concurrent shared Chrome use. Record gates, tests, observed URLs/labels/layouts, native-versus-PNG counts, blocker severity, and output evidence locations in [PROGRESS.md](PROGRESS.md); update `site_adapters/herosweb/README.md` and `note/16_herosweb.md` after implementing.

Final report: code diff/commit, access classification evidence, completeness results, actual formats and sample dimensions, per-phase PASS/BLOCKED, targeted test commands/pass/fail/skips, independent ZIP/image validation, regressions run, known missing variants and deliberate ticket deferral. **No claim of live success until an actual live run finished.**

# Hanayume Site Adapter

Status: Discovery, manual Viewer capture, and direct-only Batch are implemented on `feat/hanayume-adapter` and passed independent review. The final logged-in standard E2E completed four candidates and 134/134 original 960x1540 source-canvas pages as lossless WebP, with four verified ZIPs and zero rendered fallbacks. The full list contained 296 unique rows (3 exact `無料`, 293 exact `今なら無料`); current verified auth classified them free, and the inclusive scope selected four. Final independent review PASS / BLOCKING 0.

## Discovery

Watchlist targets use the strict episode URL `https://hanayume.com/episodes/<13-lowercase-hex-id>`. Discovery reads rows only from the unique public `epList` under the route-specific observed ancestry. Episode pages use `div.ep-main.series-safe-filter-target[data-e2e="pageEpisode"] > div.series.mode-ep` (the child has no `data-e2e`) > `.series-eplist-wrap` > `.series-eplist-main`; canonical work pages use `div.series.mode-series-top.series-safe-filter-target[data-e2e="pageSeries"]` directly above the wrapper. The public root is direct under main; `eli` rows are descendants inside `.series-eplist-default.has-store-item.mode-last`. The observed direct `epListUser` history sibling is not enumerated; overlapping copies must agree on exact labels. Unknown/nested/duplicate roots and conflicts fail closed. Full range/count/identity validation, global oldest-first positions, buffering, and latest-first/bounded output remain unchanged.

Only exact row-scoped labels are classification evidence. One exact `無料` maps to `access_mode=free`. One exact `今なら無料` maps to `free` only when the current Discovery attempt verifies the observed account markers on the canonical `/series/<work-id>` route; otherwise it remains `unknown`. Missing/duplicate/conflicting/other labels are `unknown`. Catalog stores only `access_mode`, not the raw label. Auth is attempt-local and never persisted. On an exact route/listing, a missing positive marker set is polled for at most five seconds at 150 ms intervals; deadline means no proof and keeps `今なら無料` unknown. Discovery follows the seed's observed work link, reads auth on the canonical series route, returns to the exact seed, and revalidates work/title/ranges before enumeration.

## Viewer capture

Before entry the adapter validates the exact episode URL and unique scoped work link, then checks the exact canonical same-work `/series/<work-id>` page. A unique observed account marker set on that route is an attempt-local authentication proof. It finds the target in the bare listing or follows only observed numbered ranges, validating exact routes, selected markers, stable range set, declared row counts, and unique row identity. `無料` remains eligible regardless of auth markers; `今なら無料` is eligible only with the fresh verified series auth. The exact row/work identity is checked again after episode entry. Login or paid-entry dialogs and an unavailable viewer fail closed without clicks. Page-wide upsell or resource text is not an access gate.

The observed desktop spread layout uses explicit counter, wrapper, readiness, visibility, and terminal checks. The adapter captures every body slot in order and cannot reach generic locator/UI screenshot fallback. END is accepted only after full body coverage and the observed terminal UI.

## Bounded readiness

On a structurally valid canonical series listing, authentication proof is polled for up to five seconds at 150 ms intervals until the complete positive marker set appears. The route and listing must remain exact throughout; timeout leaves `今なら無料` unknown. Viewer initialization waits up to five seconds for the existing unique current/total counter nodes to contain text. Duplicate nodes fail immediately and malformed values still fail in the strict parser. Synthetic browser tests cover delayed and missing counter/auth states. The auth probe observed markers arriving at 150 ms; the counter-missing probe did not directly measure a delayed transition. The final E2E passed after these bounded readiness checks.

## Capture fidelity

R2 captures the observed opaque sRGB/unorm8 960x1540 full-frame canvas at draw time into a bounded immutable copy tied to the exact target and episode. Selection requires target/slot/generation/write proof, safe full-frame state, and exact no-background RGBA replay. Strict single-chunk VP8L WebP method 4 is accepted only after full RGBA round-trip validation; encoder failure returns the same verified native PNG. Native unavailability uses clean rendered-canvas PNG for the whole spread at actual dimensions. In the final E2E all 134 pages were native source-canvas WebP with 134/134 independent exact RGBA matches and zero rendered fallbacks. This is decoded source-canvas fidelity, not original JPEG bytes or tile reconstruction.

## Batch policy and execution

`HanayumeSitePolicy` remains direct-only and admits only available sources with `access_mode=free`; it rejects `unknown`, `quota`, `paid`, `owned`, `grant`, and `rental` and declares no quota resource or grant-only pass. Discovery may classify `今なら無料` as free only after the current run's verified series auth; older or logged-out unknown Catalog values do not become eligible on their own. Each Batch attempt repeats fresh auth and target checks. Failed entry or capture creates no Artifact and does not complete the Item.

The earlier logged-out Phase 05 E2E completed 122 rendered-canvas PNG pages and remains historical baseline evidence only. The final run `output/hanayume_experiment/tester/runs/20261010T231618Z-a02345e9/` completed four candidates (12+50+40+32 pages), all at END, with four ZIPs and four completed Catalog items. All 134 original 960x1540 canvas outputs were lossless WebP and independently RGBA-equal; rendered fallback was zero. The Tester visually reviewed 12 first/middle/final samples. `login-nowfree-metadata-20261010T210447Z-86b4f281.json` contains the one-entry ready Viewer pilot; `r3-auth-marker-20261010T214015Z-6fc6ccb8.json` contains series auth/listing only, not Viewer entry. Final full-run evidence is in `final_report.json` and independent audit files in the run directory.

## Runtime and verification

The adapter uses the shared Crawler Chrome through the existing CDP `BrowserSession` and Playwright `Page`; it does not launch Chrome or select a profile. The AccessGuard relevant-host profile includes `hanayume.com`, `www.hanayume.com`, and the observed image host `viewer.hanayume.com`.

Implementation details, live evidence, test results, deferred authentication, and the next phase gate are recorded in the [Hanayume site note](../../../../note/10_hanayume.md) and [free-only runbook](../../../../runbooks/hanayume-free/README.md).

# ebookjapan purchased-only Site Adapter ? Progress

Last updated: 2026-11-07 (Asia/Tokyo)

**Current gate: Stage 00 VERIFIED; Stage 01 VERIFIED / ACCEPTED by the independent Reviewer and Lead. Stage 02 is authorized for bounded Viewer research; production implementation remains gated on the new probe evidence.**

## Scope and safeguards

- Register only purchased books found by authenticated Full Discovery of an ebookjapan series listing.
- Batch acquisition is planned for a later approved stage and must use the existing `owned` / `direct` path. Stage 01 does not implement or run Batch, create ZIP files, or renumber archives.
- Work is on feature branch `feat/ebookjapan-owned`. Verification uses only `output/ebookjapan_experiment/phase00/` and `phase01/` artifacts, an isolated Catalog and Watchlist, and the shared Crawler Chrome through existing CDP/Playwright integration.
- No credentials, cookies, account identity, signed URLs, image bytes, or private page content are retained in evidence.

## Stage 00 ? Site probe ? VERIFIED

**Listing facts observed on 2026-11-07:**

- Angel listing `/books/all/134336/`: native header total 10; oldest-first `1巻から` selected. Ten product IDs and positions were stable across three settled bottom reads, with no pagination/load-more control. Volume 10 (`エンジェル伝説（10）`, product `A000083590`, position 10) had one visible card-local `購入済み` badge and no price/cart control. Positions 1–9 had a positive 646円 price and one card-local basket action, with no owned badge. Therefore the observed state is **1 owned book out of 10 listed volumes**, not ten owned books.
- Mudazumo listing `/books/all/115888/`: native header total 16; oldest-first `1巻から` selected. Sixteen product IDs and positions were stable across three settled bottom reads, with no pagination/load-more control. All sixteen cards had one visible card-local purchased badge and no conflicting price/cart controls. The first title had no observed volume label; its global position 1 is known, but no volume number was inferred.
- Both listings showed the signed-in account shell and a `/mypage/` control without reading personal identity text. Ownership required visible, unique, card-local evidence. The bottom navigation link is `作品詳細に戻る`.
- All-card collection and ownership states are distinct from the public card `読む` control shared by owned and unowned items. Only the verified owned Angel volume was opened for the bounded Reader probe.

**Reader and source observations:**

- The owned Angel card opened a Reader whose visible title matched the card title and whose opaque purchased route remained stable during the probe. The A-series product ID remains the Catalog external ID; the opaque Reader route ID is not used as the product ID.
- The ordinary viewer interaction advanced from page 146 to 148 while retaining the same purchased route/title. After a normal advance at final 287/287, a viewport-visible dead-end message appeared and no next-volume or purchase action was shown. A fresh owned-card reopen returned to 1/287, which was verified as persisted position.
- A first-party PNG response with observed length 364,375 bytes was only an unbound candidate. No response-to-current-page/source relationship was proven. A, B, and C remain **UNKNOWN / unproven**. A temporary compositor screenshot was used only as a visual diagnostic control (D); it was removed and is not an accepted capture method. No DRM/access-control bypass or decryption was attempted.
- Canvas readback probe raised an uncharacterized local `TypeError`; this is not evidence of a site security rejection or proof that source pixels are inaccessible. Source provenance work remains for Stage 03.

**Probe safety review:**

- Independent Reviewer verified the Stage 00 probe cleanup/privacy gate with zero blockers. Probe page ownership was corrected to close only pages explicitly opened by the probe, and raw URLs, hidden form values, and Viewer identity false claims were removed from retained diagnostics.
- Stage 00 ignored evidence is under `output/ebookjapan_experiment/phase00/`. No Stage 00 probe is active.

## Stage 01 ? Full Discovery ? IMPLEMENTED / LIVE PASS / REVIEW PENDING

- Added `EbookJapanDiscoveryAdapter` and Discovery registry/registration support. Registration accepts only exact canonical HTTPS `/books/all/<positive-series-id>/` URLs, with no query, fragment, foreign host, or ambiguous redirect; registration leaves title metadata unknown for existing manual label confirmation.
- The adapter supports Full only. `supports_incremental_discovery=False`; bounded scope is rejected. Shared mode capability defaults to incremental-supported for existing adapters. Service checks an unsupported mode before Catalog locking/writes, CLI checks before CDP resolution, GUI rejects before queueing, and the worker rejects a mixed incremental selection before any target session starts. Unsupported incremental is never silently converted to Full.
- Full listing metadata is buffered and validated before the first yield. The adapter requires authenticated account-shell evidence, exact native total, selected oldest-first order, stable full IDs and card/layout order, exhausted bottom state, no list-local pager/load-more control, and explicit tri-state rights for every card. One visible card-local `購入済み` without price/cart/conflicting right is owned; one positive price plus one basket and no owned badge is explicitly not-owned; any ambiguity fails closed. Rights snapshots must be stable across three bottom reads before emission. The complete inventory records all products/positions while only owned records are emitted.
- Adapter performs no Catalog writes. The existing `DiscoveryService` persists owned sources and complete-list inventory using isolated test/runtime Catalogs.
- First isolated production CLI Full acceptance (`_run_discover` with the existing CLI registry/BrowserSession path):
  - Angel: `complete=True`, observed/new/known `1/1/0`; inventory 10, only position 10 owned (`A000083590`), source path `/books/134336/A000083590/`, `access_mode=owned`, `available=True`.
  - Mudazumo: `complete=True`, observed/new/known `16/16/0`; inventory 16, all owned at positions 1–16, each `access_mode=owned`, `available=True`.
  - Full reruns: Angel `1/0/1`, Mudazumo `16/0/16`; Source IDs and Item statuses were unchanged. All 17 Items remain `pending`; no Batch/Crawl has run.
  - No AccessGuard stop occurred. The CLI probe did not open a Reader, click basket/purchase, or open a trial. Root independently audited the isolated Catalog: 17 owned/available Sources, 17 pending Items, and canonical web targets for all 17.
- The first CLI attempt before tightening the pager detector was incomplete with zero emitted records because a generic page-control heuristic matched unrelated site controls. This was an adapter-local false positive, not a site rejection. The detector now inspects only native list header/bottom controls, and a synthetic outside-list `次へ`/numeric-control fixture passes.
- Same-response hydration witness: the adapter parses only the exact HTTP 200, non-redirect main-document response body from `page.goto`, with a 32 MiB input limit. It retains only ordered A-ID product paths and structural per-card purchase bits; raw HTML and inline JSON are discarded. Angel positions 1–9 each had one static price element and zero exact purchased spans; position 10 had one exact purchased span and no price element (plus one unrelated tag span). Mudazumo had one exact purchased span and no price element for each of 16 cards (position 16 also had an unrelated tag span). Both static ID/order/masks matched the hydrated dynamic listing. Static no-badge/price-element is only a witness bit: dynamic visible positive price text plus one visible basket is still required to classify NOT_OWNED. Static account shell and native total were absent, so dynamic account/total/sort checks remain required. Details: `stage01-source-document-readiness-detail.json`.
- The approved static/dynamic binding now blocks emission until the entire dynamic ordered card set and tri-state rights mask matches the same-document witness. Unknown, duplicate, hidden/template/noscript, partial, reordered or conflicting source structure fails closed; no timer is treated as ownership authority. A `registration_document` diagnostic previously ended with a failed request and no HTTP status (`ObservationUnavailable`), so it proves neither an access rejection nor absence of server listing content.
- Durable initial Stage 01 CLI evidence: `stage01-live-cli-summary-afterfix.json`. After the witness implementation, the production CLI Full path was rerun using the isolated phase01 Catalog and Watchlist. Angel completed with 1 owned/1 known at position 10; Mudazumo completed with 16 owned/16 known. Both reruns preserved Source IDs and Item statuses. No Reader, cart, purchase, or trial action occurred. Evidence: `stage01-live-cli-summary-hydration-witness.json`.
- Targeted/synthetic test evidence: `tests/unit/test_ebookjapan_discovery.py` passed 34 tests; `tests/integration/test_ebookjapan_discovery_browser.py` passed 11 tests, including a statically-owned card temporarily rendered as positive price plus basket for 2.6 seconds before the badge returns, a complete verified zero-owned listing, permanent static/dynamic mismatch preserving existing availability, and all existing history/guard cases. The affected shared Discovery/CLI/registration/worker/GUI selection passed 393 tests. Standalone unrelated suites passed: ComicDays browser 136, ComicFuz browser 69. Ruff and `git diff --check` passed.
- Full-suite status: 7,533 tests were collected in the frozen Stage 01 tree. An initial run was interrupted after a ComicFuz browser test produced no output for over five minutes. A bounded run timed out in pytest-asyncio teardown for `test_comicfuz_other_episode_route_fails_closed` while Windows IOCP polling (`event_loop.run_until_complete`); this ComicFuz browser teardown is outside the touched paths and causality remains unresolved. That exact node passes in the 69-test isolated ComicFuz module. The approved bounded 7,532-selected run excluded only that node and stopped at the first failure: **873 passed, 1 failed, 1 deselected, 107 warnings** (the other selected tests did not run because `--maxfail=1`). The failure was Hanayume `test_hanayume_ticket_read_preview_without_account_icons_uses_existing_grant_directly[already-granted]` with WinError 3 while creating a 260-character path beneath the long basetemp. The same exact node passed once under verified workspace-contained `.tmp/ej1h`; the candidate output path was 230 characters. This is consistent with a path-length issue, but causality is not asserted. Separate browser suites passed: ComicFuz 69 and ComicDays 136. No ComicFuz/ComicDays/Hanayume source change was made. **No full-suite PASS is claimed.** Detailed sanitized test diagnostics: `stage01-full-suite-timeout-summary.json` and `stage01-full-minus-teardown-node.log`.

## Stage 01 documentation reconciliation

- Shared Discovery capability, ebookjapan README/note and this progress record are synchronized with this stage's current implementation.
- Approved docs-only correction: stale fingerprint-only duplicate statements now match the already-implemented generic Core key `(ContentIdentity fields, part_count, part_index, capture SHA-256)` from commit `17e9115908582ad7627beef3742ea5c97e705a5b`. No Core runtime, schema, or duplicate policy changed. Root ran four existing duplicate-contract test nodes: 4 passed, 0 skipped. Identity-all-`None` fallback and repeated-content guard remain unchanged.

## Stage checkpoints

| Stage | Status | Evidence / next gate |
| --- | --- | --- |
| 00 Site Probe | VERIFIED | Runbook evidence and independent Reviewer gate passed; A/B/C source attribution remains unknown for Stage 03. |
| 01 Full Discovery | VERIFIED / LIVE PASS / REVIEWER + LEAD ACCEPTED | Two isolated CLI Full targets and Full reruns passed; 34 unit, 11 browser-backed and 393 affected tests passed; Ruff/diff check passed. Broad full-suite evidence remains incomplete as detailed above; no full-suite PASS is claimed. Reviewer and Lead accepted Stage 01 with the cross-site test-order/path limitation disclosed. |
| 02 Viewer baseline | BOUNDED RESEARCH AUTHORIZED | Read-only live probe only; first report native slot/ID mapping, adjacent transitions, unique loaded canvases, RTL and restoration evidence. Production implementation remains gated on the probe and Lead's next contract. |
| 03 Source-native capture | NOT STARTED | Investigate and prove A/B/C without DRM bypass; record tried methods and exact constraints. |
| 04 Batch / GUI | NOT STARTED | Integrate only after approved source/capture stages; use owned/direct. |
| 05 E2E | NOT STARTED | Run isolated owned-only Batch, ZIP and E2E checks after earlier gates; no archive renumbering. |

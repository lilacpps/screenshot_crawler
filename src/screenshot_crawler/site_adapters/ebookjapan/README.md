# ebookjapan purchased-only Discovery and partial Reader entry

This adapter implements authenticated **Full Discovery** for ebookjapan series
listing pages. It emits only books with an unambiguous, visible,
card-local `購入済み` badge. The complete inventory retains every listing
product and its observed oldest-first global position so the existing
`DiscoveryService` can reconcile ownership safely.

The package has a reviewed Reader entry, D capture, normal navigation and scoped terminal-state implementation, with a Stage 04 owned/direct Batch success. Run 4 reached strict END after 287 ordered D pages and produced an isolated ZIP (SHA-256 `364623441ab91a0aa5638bf7d4260822d8534e4b3c5a9f2219eae2fd698e71ae`) with the retained manifest SHA-256 `e8a1c37e9f709089f733f1ee8e4a44f105bffa8a41b94681e5d714b73b372c80`; strict and independent ZIP audits and Reviewer B0 passed. Stage 05 Full 17 / Plan 17 preflight passed, but all 17 Items remain pending and no page capture has run. Stage 03 has seven reviewed C3 candidate comparisons; all remain actual-site `NOT_VERIFIED` / `UNASSIGNED`, and Muda 1 final is UNKNOWN at a 320 x 49 div. The private C2 research entry now passes a generated local Chromium comparison, but C1 current remains false, actual-site source status is unchanged, normal capture remains D, and no production C or output integration is adopted. The independent generated-fixture audit found 256 ROIs, 1088 x 1600, two exact D references, RGB max 0, alpha exact, and lossless WebP roundtrip. See the owned runbook for evidence paths and hashes.

## Registration and mode

- Accepted registration URL: exact canonical HTTPS
  `https://ebookjapan.yahoo.co.jp/books/all/<positive-series-id>/` form.
- Query strings, fragments, aliases, foreign hosts, zero/leading-zero IDs and
  ambiguous redirects are rejected.
- Registration metadata leaves the work title unknown. The existing manual
  label confirmation remains the title source for a new Work.
- Only Full Discovery is supported. Incremental mode and bounded scope are
  rejected before Catalog synchronization; neither is silently converted to
  Full.

## Full listing proof

Before yielding the first record, the adapter buffers and validates the full
listing. It requires the exact series path, an authenticated account shell and
`/mypage/` control, the native full-list total, the selected `1巻から` order,
stable bottom-of-list snapshots, matching DOM/layout order, unique product IDs
belonging to the same series, and no list-local pagination/load-more control.
The account shell is checked structurally; personal identity text is not
retained. A fresh Page may render its owned card before hydrating the account
shell. The adapter waits within the existing eight-second ownership-settle bound
for the exact visible shell and `/mypage/` link. An owned card alone never proves
the current signed-in session; timeout remains fail-closed.

Every card must have an explicit ownership state:

- **Owned:** one visible card-local `購入済み` badge, with no visible price,
  basket action or conflicting rental/free/trial right.
- **Not owned:** one positive visible price and one card-local basket action,
  with no owned or conflicting right.
- **Unknown:** hidden, missing, duplicate or contradictory signals. The whole
  Full run fails before yielding any record.

Before trusting hydrated rights, the adapter also parses the bounded body
(maximum 32 MiB) of
the exact HTTP 200, non-redirect main-document `page.goto` response. It retains
only each card's official product path and a structural ownership bit: a
unique exact `購入済み` span with no price element, or no such span with one
price element. This is a hydration witness, not a complete rights result. A
static unowned bit never makes a card `NOT_OWNED`; the visible positive price
and unique basket action must be observed in the hydrated card. The complete
static ID/order/bit set must match the dynamic listing before any record can be
emitted. Unknown, duplicate, hidden/template/noscript, partial, reordered or
mismatched source structure fails closed. Raw HTML is parsed in memory and is
not retained.

The adapter yields owned records only. Their external IDs are the official
product A-IDs, URLs are the exact card product paths, `access_mode` is `owned`,
`available` is true, and global display positions come from the observed
oldest-first listing. Explicit volume labels are used only when present in the
card title; an unnumbered title keeps an unknown volume label while retaining
its observed global position. Complete listing inventory records all cards and
the owned mask through the existing `CompleteListingInventory` hook.

The Discovery adapter does not write Catalog state, open a book, click a basket
or purchase control, inspect trial content, or implement Batch policy. Existing
`DiscoveryService`, Catalog, GUI registration, shared CDP BrowserSession and
Playwright Page are reused.

## Partial Reader entry slice (Stage 02; not end-to-end)

`EbookJapanAdapter` supports only `access_strategy="direct"` and no quota
resource. Before opening a book it checks the same exact static owned witness
used by Discovery, then waits up to eight seconds for three stable visible
owned-card snapshots. If the static witness says owned but hydration temporarily
shows price/cart, it waits; it never clicks before the visible badge settles to
owned. Immediately before the click it rechecks the target A-ID path, card
title, owned state, and unique observed `読む` action.

The entry slice accepts only the same-page HTTPS purchased Viewer route
`/viewer/purchased/B<digits>/`, exact title equality with the owned card, the
observed harmless onboarding notice, a visible native counter whose total
matches all actual slot nodes, and the observed horizontal RTL spread layout.
It pins the Page document, exact route, slot node references/order and the same
layout element. A resumed Reader is returned to 1/N using the observed native
range `End` key. Readiness waits for the observed full-size, same-dimension
three-argument `drawImage` transfer and complete visible part shape. Scaled or
cropped overloads and changes to title, route, document, slots, layout,
observer state, native canvas reset or canvas dimensions fail closed.

This observed mutation set is conservative, not a proof that every possible pixel mutation or clipping operation was observed. `capture_page()` currently emits D compositor PNGs only: it uses a guarded normal center action to hide the toolbar; rejects clipped/off-viewport/transform/opacity/filter/mask/blend effects and intersecting visible painted DOM elements from a bounded inventory independent of pointer-events; checks two CSS-scale PNG samples; and returns all spread parts atomically. Per-capture diagnostics keep run-local slot IDs, physical part order, `native_page_number=None`, actual visible native counter or `None`, and `source_provenance=UNKNOWN`. The generic Core locator fallback is blocked.

`go_next()` binds the observed non-interactive left-edge hit to the last committed canvas/frozen slot and paint/geometry state in the same fresh DOM sample; drift and interactive/modal/terminal/unknown ancestors fail before click. `wait_for_change()` requires the next contiguous frozen slot order. END is available only after every frozen slot was captured in order and one of two observed scoped profiles is present: Angel's exact dead-end root with its legacy partition or lottery and three scoped native header controls, or the observed Mudazumo `.book-last` shell/cell and action partition. After full ordered coverage, only the fully bound Angel UNKNOWN terminal candidate may be held inside the existing 20-second wait; it requires the pinned purchased route, marker, shell/layout, zero visible slots/canvases, no modal/cap, and no outside-region action. The adapter does not capture or advance during the hold and accepts END only through the unchanged strict verifier. Identity, slot, layout, observer, modal, coverage, and outside-region anomalies fail immediately; persistent UNKNOWN fails closed. Diagnostics use fixed safe fields, and debug collection does not read Page state. Stage 04 run 4 passed END/ZIP audits and Reviewer B0; Stage 05 Full 17 / Plan 17 preflight passed, with page captures unexecuted.

## Stage 03 source-native research update

C3 now covers first, middle and final positions in both works: seven candidate-comparison cases across eleven parts. The two new final cases were accepted by independent Reviewer B0 against two exact D references; per-part metrics and evidence SHAs are in the [owned runbook](../../../../runbooks/ebookjapan-owned/PROGRESS.md#stage-03-source-research-and-offline-preparation). All records remain NOT_VERIFIED/UNASSIGNED, so no C production method is adopted. Muda 1 final ended UNKNOWN at source metadata with a 320 by 49 div; the notification cause is unconfirmed.

The source helper has 35 B0-accepted tests. The Page-only `__ejSourceObserver` hook joins generated Offscreen ROI/transfer records to the existing D callback; 31 local generated-Chromium cases pass, including reset, unknown-mutation, stale-bitmap, bounded-eviction, and source-instrumentation diagnostics. The private `_research_compare_source_capture(page)` path adds current document currentSrc to unique response to one bounded body read to source ROI reconstruction to two exact D-reference comparison to lossless roundtrip for generated local fixtures. It is not called by normal capture. The independent local browser audit verified 256 ROIs at 1088 x 1600, exact D references, RGB max 0, alpha exact, and exact lossless WebP roundtrip. The C1 Muda 2 site probe remains current=false; v3 diagnostics report install-unknown 1/current-slot-unknown 0, and source paint history remains incomplete. Before returning research results, each part now rechecks current source context/dimensions, latest transfer, source and target own-dimension absence, reset sequence, source identity and target binding; final same-dimension reset, source width shadow and context-loss races fail fatally. Actual-site source status stays NOT_VERIFIED/UNASSIGNED and normal output stays D. No source URL/body is emitted in proof metadata; no live page/body or shared Chrome was used. Full affected test and audit details are in the [owned progress ledger](../../../../runbooks/ebookjapan-owned/PROGRESS.md).

**Source-host evidence (metadata only; no C proof):** A fresh normal-owned Muda 2 cover observation found the current Image `currentSrc` on exactly `prod-contents-br-page.akamaized.net`, with stable natural dimensions 1280 x 1792, one exact current-document Request match and no request overflow. No response body or pixels were read. Evidence: `output/ebookjapan_experiment/e2e-validation/source-url-metadata-20261109/source-url-metadata-live-v1.json` (SHA-256 `58cd4c442f4160cb39ba0e74752760ba006a95b4de054967991e8ecd2b5f7487`). The earlier actual-page C2 attempt stopped before body/pixel retrieval with `D_FALLBACK` / `source-current-src-host-unobserved`: `output/ebookjapan_experiment/e2e-validation/source-c2-pilot-20261109/source-c2-pilot-live-v3-phase-separated.json` (SHA-256 `7dc9f7e6093bbba6b9d1192378a4a78da58275ef360bae9e9acc38d3bf62e73a`). The adapter now recognizes that exact observed hostname for source Request/currentSrc binding and AccessGuard relevance; host equality stays exact, with no suffix or wildcard matching. Generated-browser coverage exercises both the earlier cache host and this exact production hostname through the research Request/Response/ROI path; suffix lookalikes, subdomains and HTTP are rejected. The C2-focused source-host selection passed 31 tests, and the affected EbookJapan selection passed 268 tests, 0 skipped. This host support does not establish source body/pixel capture on the actual site: A/B/C remains `NOT_VERIFIED` / `UNASSIGNED`, C is unadopted, and the public `capture_page()` default remains D.

## Access and limits

The AccessGuard watches `ebookjapan.yahoo.co.jp` and source image responses
on the exact observed hosts `cache2-ebookjapan.akamaized.net`,
`ebookjapan.akamaized.net`, and `prod-contents-br-page.akamaized.net`; it stops
on a relevant 403, 429, challenge or CAPTCHA. The adapter performs no DRM bypass, token
extraction, key extraction or decryption. Live evidence verifies Full Discovery and the accepted one-work Angel 10 D baseline. Stage 04 Batch run 4 reached strict END after 287 ordered D pages and produced an isolated 209,716,162-byte ZIP with retained manifest; the strict audit passed 11 checks and independent current-ZIP review plus Reviewer B0 were accepted. Three earlier 287-page terminal failures remain historical; the third has no terminal snapshot. Repeat Full preserved identities, history, ZIP, and status hash/mtime; repeat Batch yielded zero new runs, HTTP requests, or artifacts and unchanged Catalog SHA. Actual GUI validation on isolated clone `gui/r11` used real MainWindow/Controller/worker without fakes and succeeded with 1 skipped, 0 started, 0 HTTP. Stage 05 isolated Full 17 / Plan 17 preflight passed; 26 inventory entries contained 17 distinct owned Source/Items, all pending, 0 CrawlRun rows and 0 Artifact rows. No page capture has run. Affected tests: 162 passed, 0 skipped (158 warnings); independent validation 35 passed, 0 skipped; Ruff passed. The full suite remains incomplete as recorded in `PROGRESS.md`.

## Batch plan order

The EbookJapan Site Policy opts into `display_position` candidate ordering.
Within each Work, first-seen `discovery_key` groups remain contiguous and keep
their first-appearance order; candidates within a group sort by positive
integer `Source.display_position`, ascending and stable for ties. A NULL key is
one group at its first-appearance position among explicit keys, and missing or
invalid positions remain stable at the end of their group. `selected_keys` continues to filter the plan. An
owned Source without a positive integer position is skipped with
`owned_display_position_invalid` until Full Discovery repairs the Catalog
metadata. `archive_order` is used for archive naming and does not determine
Batch execution order.

The normal CLI Plan was rechecked on the isolated Stage 05 Catalog: 17
candidates appeared as Angel 10, then Muda positions 1 through 16. The Catalog
SHA was unchanged, and the read-only evidence is recorded in the owned
runbook. This confirms Plan ordering only; no capture was run.

## Live verification

On 2026-11-07, the existing CLI Full path completed against two isolated
Watchlist targets and an isolated Catalog:

- Angel listing: 10 total cards, only position 10 owned; 1 Source emitted.
- Mudazumo listing: 16 total cards, all 16 owned; 16 Sources emitted.
- Full reruns preserved Source IDs and Item statuses.

The first live attempt failed closed with zero emitted records because an early
generic pager heuristic matched unrelated controls. It was narrowed to the
native listing header and bottom region. Browser fixtures cover an unrelated
outside-list `次へ`/numeric control, a statically owned card temporarily
hydrated as price plus basket for 2.6 seconds before its badge returns, a
verified zero-owned listing, and an unresolved static/dynamic mismatch that
preserves prior Catalog state.

The exact main-document responses were inspected in memory using regular
shared-CDP navigation; only structural summaries were saved. Product paths and
static ownership bits matched dynamic Full Discovery. Angel positions 1–9 each
had one static price element and no exact purchased span; position 10 had one
exact purchased span and no price element. Position 10 also had a second
non-purchase tag span, so matching uses the exact purchase label rather than
total tag count. Mudazumo's 16 cards each had one exact purchased span and no
price element; position 16 had an extra unrelated tag span. In both listings
the complete static bitset and order matched the hydrated UI. Static price
elements did not contain a positive price string, so they are not a not-owned
authority. The original responses did not include the account shell or native
total string; they did include the selected oldest-first sort control. Dynamic
authentication, native total/sort and visible card rights remain mandatory.
Raw HTML and inline JSON are not retained.

## Capture-stage research boundary

The Discovery module does not capture page images. The Stage 04 owned/direct Batch run 4 reached strict END after 287 ordered D pages and produced an isolated 209,716,162-byte ZIP with retained manifest. Strict audit passed 11 checks and independent current-ZIP review plus Reviewer B0 were accepted. The first three terminal failures are historical; attempt 3 has no terminal snapshot. Repeat Full preserved Source identity, run history, ZIP, and status hash/mtime; repeat Batch made zero new runs, HTTP requests, or artifacts and left the Catalog SHA unchanged. Actual GUI validation used isolated clone `gui/r11` with real MainWindow/Controller/worker and no fakes; it succeeded with 1 skipped, 0 started, 0 HTTP. Stage 05 Full 17 / Plan 17 preflight passed (26 inventory entries, 17 owned Source/Items pending, 0 CrawlRun rows and 0 Artifact rows), evidence SHA-256 `7b8ffde11bee85b21514e412eff97e8ecdf8272bf303f3408103ea66b6c2836b`; page capture has not run and full Stage 05 E2E is incomplete. See `PROGRESS.md` for artifact references and historical context.

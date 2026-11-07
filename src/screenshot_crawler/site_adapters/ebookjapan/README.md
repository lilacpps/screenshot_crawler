# ebookjapan purchased-only Discovery and partial Reader entry

This adapter implements authenticated **Full Discovery** for ebookjapan series
listing pages. It emits only books with an unambiguous, visible,
card-local `購入済み` badge. The complete inventory retains every listing
product and its observed oldest-first global position so the existing
`DiscoveryService` can reconcile ownership safely.

The package contains an **incomplete** Reader entry, D capture, normal navigation and scoped terminal-state slice. Local neutral Chromium coverage is accepted by Reviewer and Lead. The accepted one-work Angel 10 CoreRunner baseline `core-run-angel10-20261107-215910-399914` reached native END after 287 ordered D pages and produced a completed isolated ZIP with its exact prepackage manifest retained; the independent audit passed 20 artifact checks and 9 visual samples. Current affected tests: 115 (24 adapter unit + 91 local Chromium, 0 skipped); independent review: 37 browser + 4 geometry cases. A/B/C remain unproven and the D baseline is not a final source-native capture policy. Stage 03 has three bounded Muda 1 metadata-only attempts. The latest bound canvas 13 received ImageBitmap 12, produced by transfer sequence 5 from HTMLImage source 11 and 256 draw operations linked to one same-document HTTP 200 WebP response, but observer health had two additional unidentified context-method descriptor mismatches outside the six critical keys; their drawing relevance is unknown. Evidence remains `UNHEALTHY_METADATA_ONLY`, `proof_status=NOT_VERIFIED`, `capture_class=UNASSIGNED`. The copied health verifier passed 64 local checks and metadata harness 17 self-checks; these are diagnostic checks only. No response body or pixels were read, and A/B/C remain unproven. CLI/Batch registration and production E2E are not enabled.

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

`go_next()` binds the observed non-interactive left-edge hit to the last committed canvas/frozen slot and paint/geometry state in the same fresh DOM sample; drift and interactive/modal/terminal/unknown ancestors fail before click. `wait_for_change()` requires the next contiguous frozen slot order. END is available only after every frozen slot was captured in order and one of two observed, scoped profiles is present: Angel's exact viewport-visible dead-end root and exhaustive review/coupon/recommendation action partition, or Mudazumo's pinned `.book-last` shell/cell, observed module/action partition and scoped native header controls. Hidden/offscreen terminal roots alone remain LOADING while the profile activates; visible malformed, unknown, modal or extra actions fail closed. No terminal CTA was clicked. The accepted Angel 10 D baseline reached END after 287 ordered pages and produced a manifest-retained isolated ZIP, independently audited with 20 artifact checks and 9 visual samples. The current affected suite passes 115 tests (24 adapter unit + 91 local Chromium, 0 skipped); independent review passed 37 browser and 4 geometry cases. Stage 03 diagnostic prep passed 64 copied-verifier checks and 17 harness self-checks. Three bounded Muda 1 metadata-only attempts were made; the latest reached 1/193 and linked 256 tile draw operations to one same-document HTTP 200 WebP response, but two unidentified context-method descriptor mismatches outside six critical keys left observer health incomplete. Evidence remains `UNHEALTHY_METADATA_ONLY` / `NOT_VERIFIED` / `UNASSIGNED`; no response body or pixels were read, and A/B/C remain unproven. The adapter is not registered with production CLI/Batch and production E2E is not verified.

## Access and limits

The AccessGuard watches only `ebookjapan.yahoo.co.jp` and stops on a relevant
403, 429, challenge or CAPTCHA. The adapter performs no DRM bypass, token
extraction, key extraction or decryption. The current live evidence verifies
Full Discovery only. Batch eligibility and `owned` / `direct` acquisition are
later-stage work.

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

The Discovery module does not capture page images. The package has a Reviewer/Lead-accepted local D compositor capture slice and the accepted one-work Angel 10 production baseline `core-run-angel10-20261107-215910-399914`, which reached END after 287 ordered pages and produced a manifest-retained isolated ZIP. Historical 202212 failure at `outset-painted-element:img` remains unresolved; the accepted run does not identify its cause or establish universal CSS safety. The hide-before-fit diagnostic produced one QA-passed D cover PNG. Current affected tests pass 115 (24 adapter unit + 91 local Chromium, 0 skipped); independent review passed 37 browser + 4 geometry cases. Stage 03 has three bounded Muda 1 metadata-only attempts. The latest linked 256 draw operations to one same-document HTTP 200 WebP response, but two unidentified context-method descriptor mismatches outside the six critical keys left observer health incomplete; their drawing relevance is UNKNOWN. Evidence remains `UNHEALTHY_METADATA_ONLY` / `NOT_VERIFIED` / `UNASSIGNED`; no response body or pixels were read. A/B/C remain unproven. CLI/Batch registration and production E2E remain incomplete.

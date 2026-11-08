# ebookjapan purchased-only Discovery and partial Reader entry

This adapter implements authenticated **Full Discovery** for ebookjapan series
listing pages. It emits only books with an unambiguous, visible,
card-local `購入済み` badge. The complete inventory retains every listing
product and its observed oldest-first global position so the existing
`DiscoveryService` can reconcile ownership safely.

The package contains an **incomplete** Reader entry, D capture, normal navigation and scoped terminal-state slice. The accepted one-work Angel 10 CoreRunner baseline `core-run-angel10-20261107-215910-399914` reached actual native END after 287 ordered D pages and produced an isolated ZIP with the exact prepackage manifest retained (20 artifact checks, 9 visual samples). Stage 03 source research exit is accepted; A/B/C remain unverified and the source-native class is unassigned. Five Pillow page-part samples across four profiles and several Angel cover decoder/replay paths differ from stable D samples; the literal HTMLImage replay raised `EncodingError` before copy. The standard scratch-profile API descriptor probe created 1x1 HTML/Offscreen contexts but invoked none of five undefined pixel/export APIs and read no pixels. The scoped D fallback is accepted under revision `ebookjapan-owned-rendered-png-v1-20261108`; one bounded Muda 16 cover capture passed independent artifact and visual QA, without testing full-book END/ZIP behavior. It records `capture_class=D`, `fallback_reason_code=SOURCE_NATIVE_PROOF_NOT_ESTABLISHED`, and `ebookjapan_capture_policy_revision=ebookjapan-owned-rendered-png-v1-20261108`; `source_provenance=UNKNOWN` and `native_page_number=None` are retained. Current affected tests pass 124 (31 adapter unit + 93 local Chromium, 0 skipped); the scoped D policy has independent review and Lead acceptance. The prior implementation review passed 37 browser + 4 geometry cases. The offline ZIP checker passed 2 positive and 37 negative cases; this is offline-only and does not verify Stage 05 live E2E. Manual Crawl and Batch adapter/policy registration are implemented locally and await independent review; no live Batch execution or production E2E has run. See runbook [`PROGRESS.md`](../../../../runbooks/ebookjapan-owned/PROGRESS.md) for the current evidence ledger.

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

`go_next()` binds the observed non-interactive left-edge hit to the last committed canvas/frozen slot and paint/geometry state in the same fresh DOM sample; drift and interactive/modal/terminal/unknown ancestors fail before click. `wait_for_change()` requires the next contiguous frozen slot order. END is available only after every frozen slot was captured in order and one of two observed, scoped profiles is present: Angel's exact viewport-visible dead-end root and exhaustive review/coupon/recommendation action partition, or Mudazumo's pinned `.book-last` shell/cell, observed module/action partition and scoped native header controls. Hidden/offscreen terminal roots alone remain LOADING while the profile activates; visible malformed, unknown, modal or extra actions fail closed. No terminal CTA was clicked. The accepted Angel 10 D baseline reached END after 287 ordered pages and produced a manifest-retained isolated ZIP, independently audited with 20 artifact checks and 9 visual samples. The current affected suite passes 124 tests (31 adapter unit + 93 local Chromium, 0 skipped). The scoped D policy has independent review and Lead acceptance; the prior local implementation review passed 37 browser and 4 geometry cases. Stage 03 evidence, including the five Pillow ROI profiles, the Angel cover RGB atlas copy and default Blob/createImageBitmap/VideoFrame replay, the ImageDecoder candidate, and the literal HTMLImage replay failure, is summarized in `PROGRESS.md`. A/B/C candidates remain unverified and the source-native class remains unassigned; the adopted production capture class is scoped D, not source-native. The offline ZIP checker passed 2 positive and 37 negative cases, which is offline-only. See runbook `PROGRESS.md` for evidence paths. The adapter is registered in the local manual Crawl and Batch CLI registries; independent review and live Batch verification remain pending.

## Access and limits

The AccessGuard watches only `ebookjapan.yahoo.co.jp` and stops on a relevant
403, 429, challenge or CAPTCHA. The adapter performs no DRM bypass, token
extraction, key extraction or decryption. Live evidence verifies Full Discovery and the accepted one-work Angel 10 D baseline. Batch execution remains later-stage work; CLI registries are wired locally and await independent review.

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

The Discovery module does not capture page images. The package has a Reviewer/Lead-accepted local D compositor capture slice and the accepted one-work Angel 10 baseline `core-run-angel10-20261107-215910-399914`, which reached actual END after 287 ordered pages and produced an isolated ZIP with the exact prepackage manifest retained. Historical 202212 failure at `outset-painted-element:img` remains unresolved and does not establish the cause of that failure or universal CSS safety. Stage 03 research exit is accepted: Pillow replay, RGB atlas copy, default browser decoder replay and literal HTMLImage replay are recorded in `PROGRESS.md`; none establishes A/B/C. Ordinary scratch API profiling created blank HTML/Offscreen contexts but invoked none of five undefined pixel/export APIs. The scoped D fallback is accepted under revision `ebookjapan-owned-rendered-png-v1-20261108`; one bounded production Muda 16 cover probe passed artifact and visual QA, with no full-book END/ZIP claim. Toolbar hiding is limited to the observed 1906x986 viewport and exact backing/rect pairs for 816x1200 Angel 10, 1088x1600 Muda 1, and 1120x1600 Muda 16. Other geometry fails closed; normal new-page viewport normalization is not implemented. Current affected tests pass 124 (31 adapter unit + 93 local Chromium, 0 skipped); no A/B/C method is verified; the accepted capture policy is scoped D. The offline ZIP checker is offline-only; CLI registry wiring is implemented locally; independent review, live Batch execution, and production E2E remain pending.
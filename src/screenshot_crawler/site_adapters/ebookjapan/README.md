# ebookjapan purchased-only Discovery

This adapter implements authenticated **Full Discovery** for ebookjapan series
listing pages. It emits only books with an unambiguous, visible,
card-local `購入済み` badge. The complete inventory retains every listing
product and its observed oldest-first global position so the existing
`DiscoveryService` can reconcile ownership safely.

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
retained.

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

The adapter does not write Catalog state, open a book, click a basket or
purchase control, inspect trial content, or implement Batch policy. Existing
`DiscoveryService`, Catalog, GUI registration, shared CDP BrowserSession and
Playwright Page are reused.

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

This Discovery module does not capture page images. Stage 00 found an unbound
first-party PNG candidate, while A (original bytes), B (lossless
reconstruction) and C (source-derived pixels) remain unproven. The temporary D
compositor screenshot was diagnostic only. See `runbooks/ebookjapan-owned/PROGRESS.md`
for the stage evidence and remaining source-attribution work.

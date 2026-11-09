# ebookjapan purchased-only Discovery and Reader capture

This adapter implements authenticated **Full Discovery** for ebookjapan series
listing pages. It emits only books with an unambiguous, visible,
card-local `購入済み` badge. The complete inventory retains every listing
product and its observed oldest-first global position so the existing
`DiscoveryService` can reconcile ownership safely.

The package has a reviewed Reader entry, conditional source ROI C capture with atomic D fallback, normal navigation and scoped terminal-state implementation. The user-approved two-representative scope is complete: Angel 10 passed strict END with 287/287 C/WebP pages and an accepted 13-check C/D ZIP audit; Muda 1 DP1 Run 8 passed strict END at 193/193 pages (191 C/WebP, 2 D/PNG) and a strict 13-check archive audit. Root's final artifact identity/visual/numeric audit passed. The current isolated Catalog has 2 completed Items / 15 pending, 2 successful Runs / 6 failed Runs / 2 Artifacts; the other 15 Muda Items were intentionally excluded, so Full 17 capture is not claimed. The Independent Reviewer B0 accepted Run 8's strict 13-check archive audit and the final artifact identity/visual/numeric evidence. The actual Muda 2 C pilot remains one-cover evidence under incomplete paint history; seven earlier C3 cases remain `NOT_VERIFIED` / `UNASSIGNED`. Current C policy revision `ebookjapan-owned-source-roi-v2-20261109` keeps exact source/ROI and D-reference proof, dimensions, alpha and lossless roundtrip; per exact D reference, the union-pixel count with any RGB channel delta > 2 must satisfy `count * 10000 <= width * height`. Each per-part proof records both reference counts, total pixels and half-open bounding boxes. The output RGBA remains the reconstructed source RGBA. See the owned runbook for evidence and status.

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

Normal rendered capture hides the toolbar with the public Reader `i` shortcut.
Before pressing it, the adapter pins a fresh content frame and verifies the
current Reader identity, route, viewport, slot/canvas identities, and complete
paint signature. The active element must be BODY with no editable mode or
visible modal. A focused range is blurred only when it is the exact validated
native seekbar; after the final frame read the adapter requires BODY again
without another focus change. After the shortcut it requires the same pinned
frame and checks any still-visible native counter; a hidden counter remains unknown.
It then applies the existing D
surface and two-sample capture checks. Unknown focus, modal UI, ignored keys,
or any frame drift fails closed before coverage is committed. The action does
not depend on a fixed entry viewport, DPR, canvas backing size, or canvas rect;
the existing fit still derives its Page viewport from the live canvas.

This observed mutation set is conservative, not a proof that every possible pixel mutation or clipping operation was observed. `capture_page()` first attempts the bounded source ROI comparison. It returns C only when every part passes current document/Image/response/transfer/target binding, complete integer ROI coverage, two exact same-frame D references, exact dimensions and alpha, the v2 RGB outlier rule, and exact lossless output roundtrip. For each D reference independently, a pixel is an outlier when any RGB channel delta exceeds 2; C is allowed only when `outlier_pixels * 10000 <= width * height`. There is no mean-delta or cluster-shape gate. An expected proof-unavailable result captures a fresh full D spread using the existing compositor guards: guarded toolbar hide, clipped/off-viewport/transform/opacity/filter/mask/blend rejection, bounded painted-DOM inventory, and two CSS-scale samples. Fatal rights, route, layout, access, reset, context-loss, or internal errors propagate without D fallback. Per-capture metadata includes run-local slot/part IDs, method/class/revision, safe source-response and ROI facts, source epoch/encoded dimensions, target canvas/token/reset/draw generation, output RGBA hash and separate D-reference hashes, and per-reference outlier counts/total/bounding boxes; it omits raw URLs, response body bytes, pixels, and Playwright objects. `source_epoch` and `source_width`/`source_height` describe source-side ROI input; `width`/`height`, target IDs/tokens and D draw generation describe the emitted target part. The selected Muda 2 history profile remains incomplete and is identified as limited; C proof rests on source lineage and per-part full-pixel comparison, not complete paint-history observation. `native_page_number=None`; generic Core locator fallback remains blocked.

`go_next()` binds the observed non-interactive left-edge hit to the last committed canvas/frozen slot, paint/geometry state and current frame before clicking. Muda END is scoped to the pinned seven-module `.book-last` layout. The terminal classifier recognizes only the observed single `a.matilda-banner` under its exact banner module; it reports `loading` through bounded header/control hydration only while all visible actions remain classified and no outside/modal/risky action appears. END requires the complete three-control header and exact required action partition after full ordered coverage. Missing modules, malformed/duplicate anchors, unknown/outside actions and persistent partial hydration remain fail-closed.

## Stage 03 source-native research update

The seven earlier C3 candidate-comparison cases across eleven parts remain `NOT_VERIFIED` / `UNASSIGNED`; the two latest final comparisons passed independent Reviewer B0 but did not by themselves establish source provenance. An earlier Muda 1 final metadata candidate remained UNKNOWN at a 320 x 49 div; the later Stage 05 Muda 1 Run 2 failure after 191 C pages is separate, stopped on an unsafe intersecting DIV, and has an unknown cause. A separate actual-source v5 pilot independently accepted one Muda 2 cover under conditional C. These samples do not generalize to all 17 works.

The source helper has 35 B0-accepted tests. The Page-only `__ejSourceObserver` hook joins generated Offscreen ROI/transfer records to the existing D callback; 31 local generated-Chromium cases pass, including reset, unknown-mutation, stale-bitmap, bounded-eviction, and source-instrumentation diagnostics. The same `_research_compare_source_capture(page)` pipeline now serves public `capture_page()` and generated fixtures: it binds the current document image `currentSrc` to one unique non-redirected 200 response, reads the body once within fixed size/time limits, replays source ROIs, compares each reconstructed part against two exact same-frame D references, then verifies a lossless output roundtrip. The local independent audit verified 256 ROIs at 1088 x 1600, exact D references, RGB max 0, alpha exact, and exact lossless WebP roundtrip. C1 Muda 2 `current` remains false; v3 diagnostics report install-unknown 1/current-slot-unknown 0, so the accepted Muda 2 limited-history profile does not assert complete paint history. Immediately before result, each part rechecks current source context/dimensions, latest transfer, source and target own-dimension absence, reset sequence, source identity and target binding; final same-dimension reset, source width shadow and context-loss races fail fatally. Raw URL/body/pixels and Playwright objects are never projected. No live page/body or shared Chrome was used for the local generated-browser checks. Full affected test and audit details are in the [owned progress ledger](../../../../runbooks/ebookjapan-owned/PROGRESS.md).

**Source-host and actual capture evidence:** A metadata-only normal-owned Muda 2 observation established `prod-contents-br-page.akamaized.net` as an exact currentSrc host with stable natural size 1280 x 1792, one exact current-document Request match and no overflow; it read no body or pixels. Evidence: `output/ebookjapan_experiment/e2e-validation/source-url-metadata-20261109/source-url-metadata-live-v1.json` (SHA-256 `58cd4c442f4160cb39ba0e74752760ba006a95b4de054967991e8ecd2b5f7487`). Host matching is exact; suffixes and wildcards are not accepted. The later actual-source v5 pilot passed for one Muda 2 cover: `output/ebookjapan_experiment/e2e-validation/source-c2-pilot-20261109/source-c2-pilot-live-v5-schema-correct.json` (SHA-256 `E96C58A2CE0B691455310912C946521E73F0CEA1A939703D39456D917A540D76`), with 256 ROIs, 1088 x 1600 output, two exact D references, RGB maxima [1,1,2], alpha mismatch 0 and exact lossless WebP roundtrip. This single verified capture is distinct from the earlier seven C3 candidate records, which remain unassigned.

## Access and limits

The AccessGuard watches `ebookjapan.yahoo.co.jp` and source image responses
on the exact observed hosts `cache2-ebookjapan.akamaized.net`,
`ebookjapan.akamaized.net`, and `prod-contents-br-page.akamaized.net`; it stops
on a relevant 403, 429, challenge or CAPTCHA. The adapter performs no DRM bypass, token
extraction, key extraction or decryption. Live evidence verifies Full listings for both works, the 17-item Plan and the two completed representative C/D Batches. Current Catalog: 2 completed Items, 15 pending, 2 successful Runs, 6 failed Runs and 2 Artifacts. The other 15 Muda Items were intentionally excluded. Final Reviewer B0 accepted the Run 8 strict audit and artifact identity/visual/numeric evidence. The full suite remains incomplete as recorded in `PROGRESS.md`.

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

The Discovery module does not capture page images. The Stage 04 owned/direct Batch run 4 reached strict END after 287 ordered D pages and produced an isolated 209,716,162-byte ZIP with retained manifest. Strict audit passed 11 checks and independent current-ZIP review plus Reviewer B0 were accepted. The first three terminal failures are historical; attempt 3 has no terminal snapshot. Repeat Full preserved Source identity, run history, ZIP, and status hash/mtime; repeat Batch made zero new runs, HTTP requests, or artifacts and left the Catalog SHA unchanged. Actual GUI validation used isolated clone `gui/r11` with real MainWindow/Controller/worker and no fakes; it succeeded with 1 skipped, 0 started, 0 HTTP. Stage 05 Full 17 / Plan 17 preflight passed (26 inventory entries, 17 owned Source/Items pending, 0 CrawlRun rows and 0 Artifact rows), evidence SHA-256 `7b8ffde11bee85b21514e412eff97e8ecdf8272bf303f3408103ea66b6c2836b`; no Stage 05 multi-work capture had run at that earlier preflight checkpoint. The later two-representative capture scope is complete as described above; the other 15 Items are intentionally excluded and Full 17 capture is not claimed. See `PROGRESS.md` for artifact references and historical context.

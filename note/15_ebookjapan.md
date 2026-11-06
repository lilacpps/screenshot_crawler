# ebookjapan purchased-only Discovery — current implementation

## Scope

`EbookJapanDiscoveryAdapter` supports authenticated Full Discovery for ebookjapan
series listings and emits only explicitly purchased books. It reuses the
existing Discovery registry, registration resolver, `DiscoveryService`,
Catalog reconciliation, GUI Full registration flow, and shared CDP
BrowserSession/Playwright Page. The adapter never writes Catalog state itself.

The registration URL is exactly
`https://ebookjapan.yahoo.co.jp/books/all/<positive-series-id>/`, with no
query, fragment, alias, foreign host or ambiguous redirect. Registration leaves
title unknown so the existing manual label confirmation supplies a new Work
title. Incremental Discovery and bounded scope are unsupported and fail before
Catalog reconciliation; unsupported incremental is not coerced to Full.

## Full listing and ownership

The adapter requires an exact series path, structural signed-in account shell
with `/mypage/` link, native total, selected `1巻から` order, complete stable
bottom listing IDs/count, matching DOM and layout order, and no list-local
pagination/load-more control. It buffers all card metadata and validates the
whole listing before the first yield. It first parses only the card structure
from the exact HTTP 200, non-redirect main-document response returned by
`page.goto`. The HTML parser accepts up to 32 MiB and retains each card's official path and a static
purchase-bit witness; raw HTML and inline JSON are discarded after parsing.

Each card is classified independently. One visible card-local `購入済み`
without a price, basket action, or conflicting right is owned. One positive
visible price plus one card-local basket action and no owned/conflicting badge
is explicitly not owned. Hidden, missing or conflicting evidence aborts the
whole run as unknown. Static purchase bits are a hydration witness, not a
complete rights classification: an unowned static bit cannot prove
`NOT_OWNED`; only hydrated positive price text and one visible basket action
can do that. Before emission, the entire static ID/order/bit set must match the
authenticated hydrated listing, including each card's tri-state evidence.
Unknown, duplicate, hidden/template/noscript, partial, reordered or mismatched
source structure fails closed. Only owned records are emitted, with official product
A-ID external IDs, exact card product URLs, `access_mode=owned`,
`available=True`, and oldest-first global display positions. Volume labels are
only populated from explicit title text; missing numbering remains unknown.
All cards and positions plus the selected owned subset are attached using the
existing `CompleteListingInventory` hook.

The AccessGuard is site-local to `ebookjapan.yahoo.co.jp`, stops on 403/429,
challenge or CAPTCHA, and is checked after the final snapshot before inventory
or record emission. The adapter does not open a Reader or click purchase, cart,
trial or other rights-changing controls.

## Verified behavior

On 2026-11-07, isolated production CLI Full Discovery completed for:

| Listing | Full inventory | Owned records | Re-run |
| --- | ---: | ---: | --- |
| Angel | 10 cards | 1 at global position 10 | 1 known; IDs/status preserved |
| Mudazumo | 16 cards | 16 at positions 1–16 | 16 known; IDs/status preserved |

The isolated Catalog contains 17 owned/available Sources and 17 pending Items;
no Batch or Crawl has run. The live run used only the phase01 Catalog and
Watchlist under `output/ebookjapan_experiment/phase01/`.

The original server response was also inspected in memory using a regular
shared-CDP GET; only a structural summary was saved. The exact product paths
matched dynamic Full Discovery. Angel positions 1–9 each had one static price
element and no exact purchased span; position 10 had one exact purchased span
and no price element. Position 10 also had one unrelated additional tag span.
Mudazumo's 16 cards each had one exact purchased span and no price element;
position 16 also had one unrelated additional tag span. The complete static
bitsets and product order matched dynamic Full Discovery. Static price elements
did not contain positive price text, so they are not a not-owned authority.
The original responses did not include the account shell or a native total
string; they did include the selected oldest-first sort control. Dynamic
authentication, native total/sort and visible card-right checks remain
mandatory. The bounded `registration_document` diagnostic ended in
`ObservationUnavailable` with a failed document request and no HTTP status; this
did not trigger AccessGuard and is unavailable transport evidence, not a site
rejection or proof that the server response lacks listing content.

## Source-capture boundary

The first-party PNG response observed during Stage 00 is not bound to a current
page. A (original bytes), B (lossless reconstruction) and C (source-derived
pixels) are unproven. D was used only as a temporary visual diagnostic and was
not adopted. No DRM/access-control bypass or decryption was attempted. Batch
policy, owned/direct execution, ZIP creation and end-to-end acquisition remain
later stages. See `runbooks/ebookjapan-owned/PROGRESS.md` for the current gate.

## Stage 01 verification

- Unit parser/inventory tests: 34 passed.
- Browser-backed listing/history tests: 11 passed, including the 2.6-second
  temporary owned-to-price-to-owned hydration case, a complete zero-owned
  listing and an unresolved ownership mismatch that preserves prior Catalog
  availability.
- Affected shared Discovery, CLI, registration, worker and GUI tests: 393
  passed. Ruff and `git diff --check` passed.
- Broad full-suite validation is incomplete. A 7,533-test run timed out in
  pytest-asyncio teardown for `test_comicfuz_other_episode_route_fails_closed`
  while waiting in Windows IOCP polling. The 7,532-selected run excluded only
  that node and stopped at the first failure: 873 passed, 1 failed, 1
  deselected, 107 warnings; the Hanayume failure was WinError 3 creating a
  260-character path under the long temporary base. That exact node passed
  once under the verified short `.tmp/ej1h` base (230-character candidate
  path). This fits a path-length cause but does not prove it. The isolated
  ComicFuz module passed 69 tests, including the teardown node; ComicDays
  passed 136. No full-suite PASS is claimed. See the phase01 diagnostic JSON
  and log in `output/ebookjapan_experiment/phase01/`.

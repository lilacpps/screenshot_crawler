# Piccoma current implementation snapshot

## Implemented scope

The current Piccoma implementation covers Discovery only. It uses the
site-local `PiccomaDiscoveryAdapter` registered by the `discover` CLI. There is
no Piccoma viewer adapter, current viewer access guard, Site Policy, Batch
execution, image capture, or ZIP generation yet.

The Watchlist URL is a canonical HTTPS viewer URL of the form
`https://piccoma.com/web/viewer/{product_id}/{episode_id}`. Discovery parses
that product and episode identity, derives
`https://piccoma.com/web/product/{product_id}/episodes`, and confirms that the
requested episode belongs to the product listing before any record is yielded.
The adapter does not read or write Catalog directly; the existing Discovery
service owns persistence and full/incremental behavior.

## Listing, identity, and ordering

The live page exposes one `#js_episodeList` with `PCM-list_asc` and anchors
carrying `data-product_id` / `data-episode_id`. Rows contain a title and one
`.PCM-epList_status` wrapper. The adapter checks the visible product heading,
declared `全N話` count, exact row count, product membership, unique numeric IDs,
non-empty titles, and the target episode. A redirect to another host/product,
unexpected list order, missing boundary, duplicate ID, or incomplete row
causes `DiscoveryIncompleteError` before this adapter yields any records.

The DOM order is oldest-to-newest. Both full and incremental streams are
latest-to-oldest for the generic Discovery service. The source identity is the
product-scoped string `{product_id}:{episode_id}`. Source URLs are canonical
viewer URLs. Each row's title is retained as `order_label`; `order_key` is not
inferred from episode IDs or titles. Whole-work display position is
`DOM index + 1` in oldest-to-newest order and is attached before bounded
filtering. `from_url` and `through_url` use viewer identities, are inclusive in
latest-to-oldest order, and are validated against the complete list before
yielding. Positions are never renumbered inside the selected range.

## Access state

The adapter collects `PCM-epList_status_*` markers from both the
`.PCM-epList_status` wrapper and its descendants. Unconditional free requires
the exact marker set `PCM-epList_status_free` and exact visible `¥0`. A
conflicting wait-free or other marker on the wrapper or a descendant maps to
`unknown`. A recognized wait-free marker maps to `quota`; an exact point marker
with a positive integer price maps to `paid`. Missing and other states map to
`unknown`. The generic `.PCM-epList_status` class alone, title, readable status,
and `data-user_access` attribute do not establish free access. The adapter does
not inspect personal entitlements or enter a viewer.

On 2026-10-09, the logged-out listing page showed 432 of 432 exact free rows for
product 28600, and product 28606 showed 12 exact free rows, 167 wait/binge-free
rows, and 39 point-priced rows. The seed IDs were present in the full list:
28600/1910027 at DOM index 0, 28600/4142286 at index 421, and 28606/2001009 at
index 1. Counts are live evidence only and are not hard-coded.

## CLI and output

Discovery uses the existing CLI and isolated Watchlist/Catalog paths:

```powershell
python -m screenshot_crawler.cli discover --site piccoma --mode full --watchlist output\piccoma_experiment\watchlist.yaml --catalog output\piccoma_experiment\catalog.sqlite
```

The normal Discovery service writes source target locators and access state to
Catalog. The bounded diagnostic under ignored `output/piccoma_experiment/`
records only sanitized listing metadata and never writes comic images, browser
storage, cookies, or signed URLs.

## Tests and live verification

Unit tests cover strict viewer and final listing URL parsing, product-scoped
IDs, exact access classification, full-list completeness, canonical
latest-first traversal, inclusive bounds, and original global positions.
Browser-backed fixture tests exercise the DOM adapter through Discovery and
Catalog, including no-write failure on invalid/incomplete listings, wrapper
status conflicts, and free-to-paid/quota/unknown rediscovery. Access refresh
preserves operator-completed Item status. Shared Crawler Chrome/CDP listing
verification was performed on 2026-10-09.

Viewer layout, current access revalidation at entry, page readiness and
navigation, source-byte mapping, rendered capture, page order/quality, and END
remain NOT VERIFIED. These are required before implementing the viewer adapter
and direct-only Batch path. Ticket, wait-free, point, purchase, rental, and
unlock entry are outside the free-only scope.

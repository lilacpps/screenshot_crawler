# Piccoma

## Current support

Piccoma Discovery is implemented for public product episode lists. The
Watchlist target must be a canonical HTTPS viewer URL:

```text
https://piccoma.com/web/viewer/{product_id}/{episode_id}
```

Discovery validates that identity, opens the corresponding
`/web/product/{product_id}/episodes` page, validates its complete episode list,
and only then yields records to the existing Discovery service. The viewer
adapter, fresh viewer access check, Site Policy, Batch execution, capture, and
ZIP flow are not implemented yet.

## Listing and identity

The observed listing uses `#js_episodeList.PCM-list_asc`. Each row is an anchor
with `data-product_id` and `data-episode_id`, containing one
`.PCM-epList_ep`, `.PCM-epList_title`, and `.PCM-epList_status`. The product
heading is `#js_contentBody .PCM-headTitle_name`, and the page text declares
the complete count as `全N話`.

The adapter requires the DOM row count to equal that declared count, every row
to have the requested product ID, a unique numeric episode ID, a non-empty
title and one status wrapper, and the Watchlist episode to be present. It
buffers and validates the complete list before yielding. The native DOM is
oldest-first; records are yielded latest-first. Global display position is
`original_dom_index + 1`, so it remains unchanged when an inclusive bounded
range is selected. The Catalog source identity is
`{product_id}:{episode_id}`, and its canonical target URL is
`https://piccoma.com/web/viewer/{product_id}/{episode_id}`.

## Access classification

The adapter collects `PCM-epList_status_*` markers from the status wrapper and
its descendants. Unconditional free requires the exact marker set
`PCM-epList_status_free` and exact visible `¥0`. A conflicting wait-free or
other marker on the wrapper or a descendant maps to `unknown`. A recognized
`PCM-epList_status_waitfree` signal maps to `quota`; an exact
`PCM-epList_status_point` marker with a positive integer price maps to `paid`.
Other states map to `unknown`. The generic `.PCM-epList_status` class by itself
and `data-user_access` are not access-mode signals. A readable or previously
opened viewer is not proof that an episode is unconditionally free.

The 2026-10-09 listing snapshot observed 432/432 rows marked free for product
28600. Product 28606 had 12 exact free rows, 167 wait/binge-free rows, and 39
point-priced rows. These counts are evidence snapshots, not constants.

## Verification and limits

The bounded metadata-only CDP probe lives under ignored
`output/piccoma_experiment/`. It stores IDs, status labels/classes, counts, and
paths only; it does not save image payloads, cookies, or signed URLs. Unit tests
cover strict viewer and final listing URL parsing, complete-list validation,
access states, latest-first order, bounds, and global position preservation.
Browser-fixture tests cover wrapper marker conflicts, access refresh from free
to paid/quota/unknown, and retention of a completed Item status.

Live listing verification used the shared Crawler Chrome through the existing
BrowserSession/CDP integration on 2026-10-09. Viewer entry, page layout,
navigation, capture provenance, terminal END, and free-state revalidation at
the viewer remain NOT VERIFIED and are Phase 3 gates. No ticket, point,
purchase, rental, or unlock operation is part of this implementation.

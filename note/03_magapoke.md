# 03. Magapoke

## Purpose and scope

`MagapokeAdapter` crawls one episode through the shared Crawler Chrome/CDP
session. Discovery, batch, catalog, login, purchase, quota, and watchlist
flows are out of scope.

## URL and context

The supported identity is `/title/{title_id}/episode/{episode_id}`. The URL
strings are preserved: `work_id=title_id`, `episode_id=episode_id`,
`content_id=episode_id`, and `chapter_id=None`. A change to another episode is
`NEXT_CONTENT`; the adapter does not navigate back.

## Viewer structure and mapping

The content target is `.c-viewer__comic canvas`. In the live viewer, an
`OffscreenCanvas` first receives the complete CDN JPEG and then receives tile
`drawImage()` calls. The visible canvas receives the completed OffscreenCanvas.
The final visible-canvas draw is recorded separately. Native reconstruction is
accepted only when that draw is also a full-size 1:1 identity draw with the
expected source/destination geometry, transform, composite operation, and
filter. A later crop, scale, flip, or other renderer change therefore falls
back to a screenshot.

`prepare_page()` installs a bounded, metadata-only hook before navigation. It
records source path/type/dimensions, source and destination rectangles, the
canvas backing size, transform, composite operation, filter, and sequence.
The hook performs no encoding, base64 conversion, hashing, network access, or
pixel copying. The latest render generation is copied when it is drawn to the
visible canvas. Network response arrival order is never used as page order.

The production path uses the mapping observed for the current source object;
it does not assume 4x4, 16 tiles, a fixed permutation, or divisible image
dimensions. The sampled live pages used 16 tile calls with 168x256 rectangles
on a 685x1024 source, leaving a 13px right edge from the initial full draw.

## Capture strategy

The CDN JPEG is a scrambled transport image, not a finished page. It is never
saved directly and is never JPEG-reencoded.

```text
scrambled CDN JPEG
    -> validate source/episode, JPEG magic and dimensions
    -> decode with Pillow
    -> replay verified identity-transform tile mapping at native pixels
    -> PNG
    -> if any visible part is unsafe/unavailable, all visible parts use
       canvas Locator screenshot PNG
```

The reconstruction starts with the decoded full source and pastes the
verified tile crops into the observed destination rectangles. This mirrors
the viewer's initial full draw and preserves an uncovered edge strip. It
requires integer, equal-size source/destination rectangles, identity
transform, `source-over`, `filter=none`, bounded coordinates, non-overlapping
source/destination coverage, and complete inferred tile extents. Missing,
ambiguous, overlapping, gapped, scaled, transformed, invalid, or undecodable
input falls back without stopping the crawl.

The compressed-domain JPEG option was investigated only as a short feasibility
check. The live source is 685x1024, the observed tile boundaries include
x=168, 336, and 504, and the sampled JPEG MCU is 8x8, so these observed
boundaries are MCU-aligned. However, arbitrary coefficient-domain tile
permutation still requires JPEG coefficient tooling that is not a simple,
maintainable runtime dependency. Therefore lossless JPEG reconstruction is not
adopted. Lossless WebP is not used.

## Page identity and navigation

Identity combines the visible canvas page index and current source path. The
source path is used only as a current-page identity signal, not as response
arrival order. The next operation clicks `.c-viewer__pager-next` once and
bounded `wait_for_change()` waits for either identity or URL change. A URL
change from episode 244815 to 244816 is a normal `NEXT_CONTENT` completion and
244816 is not captured.

## Output metadata

Title and order are read from the page title where available. Author is
currently unavailable and genre is `漫画`. Native reconstruction artifacts are
PNG at the canvas backing dimensions (the live target is normally 685x1024).

## Browser session

The adapter receives a Playwright `Page`. It does not launch Chrome, select a
profile, resolve a CDP endpoint, or manage browser lifecycle. Use the shared
`.chrome-crawler/` profile and `CRAWLER_CDP_ENDPOINT` through the common CLI.

## Tests and live verification

Unit tests cover URL/context, response filtering, JPEG magic/dimensions/MCU
inspection, non-divisible synthetic tile permutation, missing/overlap/gap and
unsafe mapping rejection. The local Playwright fixture covers native PNG
reconstruction, bad JPEG response-header fallback, tainted canvas screenshot
behavior through Core, and episode URL change.

The real-site CDP smoke on 2026-09-21 captured 25 artifacts from episode
244815, all as PNG at 685x1024, and packaged them successfully. The run stopped
at `NEXT_CONTENT` after navigating to episode 244816 without capturing it.
Representative first/middle/end comparisons were made against Locator
screenshots; the native results have the same orientation, panel order, and
crop. The sampled live mapping remained 16 tiles with 8x8 JPEG MCUs. Do not
report the former raw-JPEG smoke result as valid for this reconstruction
implementation.

## Known limitations

Only the observed HTMLImageElement -> OffscreenCanvas renderer path is accepted
for native reconstruction. ImageBitmap/unknown source objects, complex
transforms, filters, composites, incomplete mapping, and missing response
bodies use screenshot fallback. The mapping is intentionally bounded to the
current render generation; a future renderer change should fail safe rather
than infer a new permutation.

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
saved directly and is never pixel-decoded/JPEG-reencoded.

```text
scrambled CDN JPEG
    -> validate source/episode, JPEG structure and observed mapping
    -> verified quantized-DCT block permutation
    -> lossless reconstructed JPEG
    -> if coefficient path is unsafe/unavailable, verified pixel reconstruction PNG
    -> if both native paths are unsafe/unavailable, canvas Locator screenshot PNG
```

The reconstruction starts with the decoded full source and pastes the
verified tile crops into the observed destination rectangles. This mirrors
the viewer's initial full draw and preserves an uncovered edge strip. It
requires integer, equal-size source/destination rectangles, identity
transform, `source-over`, `filter=none`, bounded coordinates, non-overlapping
source/destination coverage, and complete inferred tile extents. Missing,
ambiguous, overlapping, gapped, scaled, transformed, invalid, or undecodable
input falls back without stopping the crawl.

The production coefficient path uses the normal `jpeglib>=1,<2` dependency and
is implemented in `native_capture.py`; the diagnostic reference remains in
`poc/magapoke_lossless_jpeg.py`. It does not decode pixels or JPEG-reencode
them. It is enabled only for grayscale or three-component 4:4:4 JPEGs where
every component has 1x1 sampling, every observed source/destination rectangle
is 8x8 aligned, the base/final draws are full-size identity draws, and
coefficient/header/edge validation succeeds. The mapping is calculated from
the observed rectangles; no fixed tile count or permutation is assumed.
4:2:2 and 4:2:0 are rejected rather than assumed safe.

The artificial 70x48 fixture verified forward and inverse coefficient
permutation, including a 72px coded width with the rightmost coded block left
untouched, and matched the existing PNG reconstruction at every decoded RGB
pixel. A live run from episode 244815 verified five 685x1024 artifacts. All
five were baseline grayscale JPEGs with one Y component at 1x1 sampling; the
16 observed tiles cover 0..671 and the two coded block columns covering the
right edge remained unchanged. Per-component coefficient arrays, quantization
tables, Huffman tables, dimensions, and decoded pixels all validated. The
reconstructed JPEG was 0.998488--0.999121 of the source JPEG and
0.199810--0.236303 of the existing PNG size.

`jpeglib.write_dct()` changes the JPEG container: it duplicates the JFIF APP0
marker and can renumber component IDs (for example, live grayscale ID 1 to 0),
while retaining the tested quantization/Huffman tables and live image pixels.
The production validator requires source APPn/COM payloads to remain present,
and exact dimensions, sampling, quantization, DQT/DHT/DRI payloads, progressive
mode, coefficient arrays, and untouched right-edge blocks. It does not promise
bit-for-bit JPEG container preservation.

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
JPEG when the coefficient path is safe, otherwise PNG at the canvas backing
dimensions (the live target is normally 685x1024).

## Browser session

The adapter receives a Playwright `Page`. It does not launch Chrome, select a
profile, resolve a CDP endpoint, or manage browser lifecycle. Use the shared
`.chrome-crawler/` profile and `CRAWLER_CDP_ENDPOINT` through the common CLI.

The CLI closes the crawl Page and disconnects the Playwright/CDP session before
filesystem-only ZIP packaging. This prevents late viewer/CDP events from
writing to a transport that is already being torn down.

## Tests and live verification

Unit tests cover URL/context, response filtering, JPEG magic/dimensions/MCU
inspection, coefficient-domain aligned tile permutation, non-divisible PNG
tile permutation, missing/overlap/gap and unsafe mapping rejection. The local
Playwright fixtures cover the complete Adapter-level hierarchy: an aligned
fixture returns coefficient-domain JPEG, while the existing non-aligned and
bad-header fixture exercises PNG reconstruction and Locator screenshot
fallback. They also cover tainted canvas screenshot behavior through Core and
episode URL change.

The real-site CDP smoke on 2026-09-21 captured 25 artifacts from episode
244815, all as JPEG at 685x1024 through the coefficient path, and packaged them
successfully. The run stopped at `NEXT_CONTENT` after navigating to episode
244816 without capturing it. A prior PNG smoke remains the fallback reference.
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

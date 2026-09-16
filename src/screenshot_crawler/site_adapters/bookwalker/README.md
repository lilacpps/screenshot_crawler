# BookWalker adapter

## Entry flow

The crawler accepts either the direct viewer URL or a BookWalker product URL
such as `/de<content-id>/`. For a product URL, `initialize()` searches the
product reading controls and ranks `試し読み`, `読む`, and `10分まる読み`
links by reader URL, content ID, action label, and visible label. A
`target=_blank` attribute is removed so the existing page follows the link;
login automation is not performed.

## Viewer and capture target

The viewer is a canvas renderer. The observed current screen is
`#renderer .currentScreen canvas:not(.dummy)`. BookWalker draws viewer chrome
in the same visual layer, so the adapter returns the canvas and Core reads the
canvas's own PNG buffer. This avoids saving the toolbar and browser UI.

The DOM does not expose individual page elements: the page is drawn directly
into the current canvas. Before navigation, the adapter installs a bounded
`drawImage` geometry trace. It uses the current canvas DOM element plus the
renderer destination rectangles to create page-sized temporary canvases. This
handles a centered single page, landscape pages, and true spreads without
guessing margins from colors. When the renderer geometry is unavailable, the
older center-split fallback remains bounded and conservative.

The dedicated Chrome launcher uses a `1920x1080` logical window. This lets
BookWalker render a spread while the adapter detects the wide backing canvas,
splits it at the center, and saves the right half followed by the left half.
Each split file records `metadata.part` and `metadata.parts` in the manifest.

## Navigation and page change

BookWalker advances from the left side of `#viewport1`. The adapter clicks a
small left-edge position in that viewport because a bare `ArrowLeft` can cause
horizontal scrolling when a spread is wider than the viewport. The gray
`#loaderStatusDialog` must disappear and the canvas signature must remain
stable before capture. `#pageSliderCounter` is the primary page identity
signal, with the viewer `cid` as a secondary signal.

Some opening image/cover transitions can consume the first left-side action.
`wait_for_change()` retries the bounded left-side action at most twice within
the page-change timeout; it never waits indefinitely.

## Content context and stopping

The URL `cid` is stored as `content_id`, `work_id`, and the page source ID.
`#eobNext` is checked before capture and becomes `NEXT_CONTENT`. A visible
`#endOfBook` becomes `END`. Only explicit ad markers (`[data-ad]`, `.ad`,
`#ad`, `#advertisement`) become `AD`; ambiguous screens stop as `UNKNOWN`.

The runner does not delete trailing pages based on a rendered-screen cycle.
At the last page counter, the adapter gives the viewer a bounded grace period
to expose `#endOfBook`; when it appears, the screen is classified as `END`
before capture. This avoids saving the BookWalker logo screen without guessing
from colors or deleting otherwise valid pages.

## Live verification

Using the dedicated headed Chrome CDP session, the product URL navigated to
the available trial reader. With the earlier narrow window, three one-page
PNGs were saved; the observed files were `1329x1209` and had distinct
fingerprints.

With a temporary `1200x900` window, the live viewer produced a spread. The
adapter saved two files of `890x1209` and `889x1209`; visual inspection showed
the first file was the right page and the second was the left page, with no
toolbar or side whitespace. The launcher now uses the wider `1920x1080`
logical viewport for the same split path; a fresh live run after restarting
that launcher is still recommended to confirm the exact backing dimensions on
the user's 4K/150% display.

With the geometry trace active at `30/59` in the Full HD viewport, the viewer
reported two page rectangles of `1111x1481`. This confirms that the main novel
spread is split by renderer page geometry rather than by the screen midpoint.

At the live end of the observed trial reader, `59/59` was followed by a
BookWalker logo rendered inside the canvas. At the same time `#endOfBook`
became visible. `detect_state()` checks this marker before CONTENT capture,
so the logo screen is classified as `END` and is not saved. The live check
also confirmed that the URL and page counter did not change during this
transition.

## Output naming and packaging

When the entry URL is a product page, the adapter reads the main title, author
and the series card matching the current product URL before opening the viewer.
Campaign labels enclosed by `【...】`, such as `【期間限定】` and
`【電子特別版】`, are removed. A trailing numeric volume is converted to the
two-digit form required by `docs/BOOK_NAMING_RULES.md`; for example, `作品名4`
is stored as `作品名-第04巻-著者.zip`. If the series has 100 or more books,
the adapter uses three digits for that series. If the current product has no
numeric volume, the volume component is omitted.

On a normal `END` or `NEXT_CONTENT` stop, the current viewer tab is closed and
the crawl directory is archived under:

```text
output/Books/<genre>/<title>/<title>-<volume>-<author>.zip
```

After a successful archive, the intermediate crawl directory is removed. A
completion record is kept under `output/crawl-status/`; it records the archive
path, page count, and whether cleanup succeeded. Failed runs retain their
crawl directory and diagnostics for inspection. Use `--library-dir` on `crawl`
to select another library root. Direct viewer URLs without a product page can
still be crawled, but they do not provide BookWalker author metadata and
therefore may produce an `unknown-title` archive name.

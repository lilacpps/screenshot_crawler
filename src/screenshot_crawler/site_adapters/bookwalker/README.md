# BookWalker adapter

## Entry flow

The crawler accepts a direct viewer URL or a BookWalker product URL such as `/de<content-id>/`. For a product URL, `initialize()` locates the product reading control and follows the best reader candidate in the same tab.

## Viewer and capture target

BookWalker uses a canvas renderer. The observed current screen is `#renderer .currentScreen canvas:not(.dummy)`. Core reads the canvas PNG buffer so viewer toolbar/browser UI is not included.

The adapter traces renderer `drawImage` geometry and creates temporary page-sized canvases. This handles centered single pages, landscape pages, and true spreads. When geometry is unavailable, a bounded center-split fallback remains.

## Spread and order

With the dedicated wide Chrome window, BookWalker can render a spread. The adapter saves the right page first and the left page second. Split files record `metadata.part` / `metadata.parts`.

## Navigation and page change

The adapter advances by clicking the left side of `#viewport1`. `#loaderStatusDialog` must disappear and the canvas signature must stabilize before capture. `#pageSliderCounter` is the primary page identity signal, with viewer `cid` as a secondary signal.

Some transitions consume the first action, so `wait_for_change()` performs bounded retry and never waits indefinitely.

## Content context and stopping

The URL `cid` is stored as content/work/source ID.

- `#eobNext` → `NEXT_CONTENT`
- visible `#endOfBook` → `END`
- known final navigation from page counter `N/N` is handled so the following BookWalker logo canvas is not captured as content
- known ad markers → `AD`
- otherwise ambiguous state → `UNKNOWN`

Do not simplify this to a single END signal without live verification.

## Live verification

Live headed-CDP checks confirmed:

- single-page PNG capture
- spread capture in right-to-left order
- renderer geometry-based page split
- final `59/59` transition where the BookWalker logo appears in the canvas while `#endOfBook` becomes visible

These observations are the basis for the current site-specific logic.

## Output naming and packaging

For product-page entry, the adapter collects title/author/category/series metadata before opening the reader. Campaign tags such as `【期間限定】` are removed and numeric volume suffixes are normalized according to `docs/BOOK_NAMING_RULES.md`.

On normal `END` / `NEXT_CONTENT`, manifest-declared PNGs are archived under:

```text
output/Books/<genre>/<title>/<title>-<volume>-<author>.zip
```

A completion record is kept under `output/crawl-status/`. The intermediate crawl directory is removed only when its complete contents are generated run artifacts (manifest, progress, and manifest-declared PNGs). If unrelated or extra files exist, the directory is retained rather than deleted.

Direct viewer URLs may lack product metadata and can produce an `unknown-title` archive name.

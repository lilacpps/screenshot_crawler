# BookWalker adapter

## Entry flow

The crawler accepts a direct viewer URL or a BookWalker product URL such as `/de<content-id>/`. For a product URL, `initialize()` locates the product reading control and follows the best reader candidate in the same tab.

## Viewer and capture target

BookWalker uses a canvas renderer. The observed current screen is `#renderer .currentScreen canvas:not(.dummy)`. Core reads the canvas PNG buffer so viewer toolbar/browser UI is not included.

The adapter first traces renderer `drawImage` geometry and source metadata. When one visible page
rectangle maps safely to one source rectangle, it copies that source rectangle synchronously to a
temporary canvas during the intercepted draw and returns the source-native PNG. The native path
requires valid source dimensions, matching PNG dimensions, identity transform, `source-over`, and
`filter: none`; it rejects ambiguous multiple draws, atlas/composition cases, and invalid copies.
Native capture is cleared after every attempt and does not retain `ImageBitmap` references.

If native capture is unavailable or fails any safety check, the adapter uses the existing geometry
crop path with temporary page-sized canvases. This handles centered single pages, landscape pages,
and true spreads. When geometry is unavailable, the bounded center-split fallback remains. Spread
parts stay in right-to-left reading order in both paths.

## Spread and order

BookWalker can render a spread in a wide Chrome window. The adapter saves the right page first and the left page second. Split files record `metadata.part` / `metadata.parts`.

## Navigation and page change

The adapter advances with the viewer's `ArrowLeft` keyboard handler and falls back to a left-edge `#viewport1` click only when page identity remains unchanged. `#loaderStatusDialog` must disappear and the canvas signature must stabilize before capture. `#pageSliderCounter` is the primary page identity signal, with viewer `cid` as a secondary signal.

Some transitions consume the first action, so `wait_for_change()` performs bounded retry and never waits indefinitely.

## Content context and stopping

The URL `cid` is stored as content/work/source ID.

- `#eobNext` → `NEXT_CONTENT`
- visible `#endOfBook` → `END`
- known final navigation from page counter `N/N` is handled so the following BookWalker logo canvas is not captured as content
- known ad markers → `AD`
- otherwise ambiguous state → `UNKNOWN`

Do not simplify this to a single END signal without live verification.

## Browser Session policy

The adopted target architecture uses one shared Crawler Chrome/profile for all real sites.

```text
shared Crawler Chrome (.chrome-crawler/)
    ↑ CDP
Playwright Page
    ↓
BookWalker adapter
```

The adapter should not own Chrome launch, profile selection, CDP endpoint resolution, or `connect_over_cdp()`.

CDP is the connection transport; normal BookWalker interaction remains Playwright `Page` / `Locator` operations.

Authentication state should normally stay in the shared Chrome profile. A BookWalker-specific endpoint/profile is an exception override, not the default design.

### Current launcher state

The only standard launcher is `scripts/start_crawler_chrome.ps1` with the shared `.chrome-crawler` profile. BookWalker and Manga ONE sessions can coexist there. Site-specific launcher/profile paths are not part of the current operation; site-specific CDP endpoint/profile settings remain exception overrides only.

## Authentication

BookWalker login DOM automation remains site-specific, but it should receive a Playwright Page from the common Browser Session layer.

Target endpoint precedence:

1. `--cdp-endpoint`
2. `BOOKWALKER_CDP_ENDPOINT`
3. `CRAWLER_CDP_ENDPOINT`
4. `http://127.0.0.1:9222`

`CRAWLER_CDP_ENDPOINT` is the standard global endpoint. `BOOKWALKER_CDP_ENDPOINT` remains an exception override.

The login CLI always creates a dedicated new Page, does not reuse another site's tab, closes that Page after login, and leaves the remote Chrome/profile running.

CAPTCHA / MFA / validation errors are not automatically bypassed.

## Live verification

Live headed-CDP checks confirmed:

- single-page PNG capture
- spread capture in right-to-left order
- renderer geometry-based page split
- final `59/59` transition where the BookWalker logo appears in the canvas while `#endOfBook` becomes visible

These observations remain the basis for the site-specific logic and should not be changed merely as part of Browser Session unification.

Source-native live verification on 2026-09-19 used the four trial samples recorded in
`note/01_bookwalker.md`: 960x1280, 1443x2048 portrait, 2048x1090 landscape, and a two-page
1303x2048 spread. All produced native source crops; unsupported or ambiguous pages remain covered
by the existing Canvas crop fallback.

Shared-profile live verification confirmed BookWalker login and crawl, coexistence with the Manga ONE session, dedicated login Page cleanup, remote Chrome preservation, and no regression in the adapter-specific capture, navigation, or END behavior.

## Output naming and packaging

For product-page entry, the adapter collects title/author/category/series metadata before opening the reader. Campaign tags such as `【期間限定】` are removed and numeric volume suffixes are normalized according to `docs/BOOK_NAMING_RULES.md`.

On normal `END` / `NEXT_CONTENT`, manifest-declared PNGs are archived under:

```text
output/Books/<genre>/<title>/<title>-<volume>-<author>.zip
```

A completion record is kept under `output/crawl-status/`. The intermediate crawl directory is removed only when its complete contents are generated run artifacts (manifest, progress, and manifest-declared PNGs). If unrelated or extra files exist, the directory is retained rather than deleted.

Direct viewer URLs may lack product metadata and can produce an `unknown-title` archive name.

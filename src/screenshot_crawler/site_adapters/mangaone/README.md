# Manga ONE adapter

## Viewer and capture target

Observed chapter URL example:

`https://manga-one.com/manga/2379/chapter/214131`

Manga ONE renders chapter pages as individual images under `.viewer-container`, currently with `alt="page_N"`. The adapter presses the visible `全画面` control when available and captures only ready images overlapping the viewport.

## Spread and order

The normal view is a two-page spread. The right-hand image is returned first, then the left-hand image. Opening/final views may contain one page only. No blank-side inference is used.

## Navigation and page change

The adapter clicks the left side of `.viewer-container`. Page identity is the visible `page_N` label set with chapter ID as source ID. Render readiness requires stable visible labels/geometry. Advance retry is bounded.

## Content context and stopping

The URL provides `work_id` and `chapter_id`; chapter ID is also used as `content_id` / `episode_id`.

- chapter URL change → `NEXT_CONTENT`
- after an advance, if visible page images disappear continuously for `end_grace_ms` (currently 2500 ms) → `END`

The image-disappearance rule is a **site-specific practical heuristic based on the implementation that has worked against the live viewer**. It is not a claim that Manga ONE exposes an explicit END DOM marker. Do not replace it with guessed generic END selectors without live evidence.

If no valid transition can be established within the bounded page-change timeout, the adapter raises a page-change error instead of progressing indefinitely.

## Ads and known limitations

Chapter-end promotional pages are ordinary chapter images and currently have no stable DOM marker that distinguishes them from manga pages. They are kept to avoid deleting valid final content. A fixed number of trailing pages is intentionally not enabled.

## Browser Session policy

The adopted target architecture uses one shared Crawler Chrome/profile for all real sites.

```text
shared Crawler Chrome (.chrome-crawler/)
    ↑ CDP
Playwright Page
    ↓
Manga ONE adapter
```

The adapter should not own Chrome launch, profile selection, CDP endpoint resolution, or `connect_over_cdp()`.

CDP is the connection transport; normal Manga ONE interaction remains Playwright `Page` / `Locator` operations.

Authentication state should normally stay in the shared Chrome profile. A Manga ONE-specific endpoint/profile is an exception override, not the default design.

### Current launcher state

The only standard launcher is `scripts/start_crawler_chrome.ps1` with the shared `.chrome-crawler` profile. Manga ONE and BookWalker sessions can coexist there. Site-specific launcher/profile paths are not part of the current operation; site-specific CDP endpoint/profile settings remain exception overrides only.

## Authentication

Authentication uses the shared `login` CLI against a CDP-connected Chrome. Credentials come from `.env`; the command does not print them or create a separate auth-state file.

Target endpoint precedence:

1. `--cdp-endpoint`
2. `MANGAONE_CDP_ENDPOINT`
3. `CRAWLER_CDP_ENDPOINT`
4. `http://127.0.0.1:9222`

`CRAWLER_CDP_ENDPOINT` is the standard global endpoint. `MANGAONE_CDP_ENDPOINT` remains an exception override.

The login CLI always creates a dedicated new Page, does not reuse another site's tab, closes that Page after login, and leaves the remote Chrome/profile running.

The site-specific login handler should receive a Playwright Page from the common Browser Session layer. CAPTCHA / MFA / validation errors are not automatically bypassed.

## Current crawl example

The common launcher is the standard path:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_crawler_chrome.ps1
```

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli login --site mangaone
```

Then:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site mangaone `
  --url "https://manga-one.com/manga/2379/chapter/214131" `
  --output-dir output\crawl-mangaone
```

## Output naming and ZIP packaging

The adapter exposes the chapter title as archive title and the episode label as generic `order` metadata.

```text
獣王と薬草-第01話.zip
獣王と薬草-第80話-後編.zip
```

Normal `END` / `NEXT_CONTENT` completion packages manifest-declared PNG/WebP
artifacts under `output/Books/漫画/<title>/` by default. Manga ONE prefers the
original blob WebP bytes per visible page and allows an initial source-body
attempt plus two short bounded retries for transient retrieval failures. After
those attempts, it falls back to the existing PNG Locator screenshot
independently for that visible page if the source bytes remain unavailable or
invalid. Deterministic validation failures do not trigger extra retrieval.
Episode parts remain separate archives.

## Live verification

Shared-profile live verification confirmed Manga ONE login and crawl, coexistence with the BookWalker session, dedicated login Page cleanup, remote Chrome preservation, and no regression in the adapter-specific capture, navigation, or END behavior.

Last verified for the shared-profile workflow: 2026-09-17.

## Discovery adapter

`MangaOneDiscoveryAdapter` is separate from `MangaOneAdapter`. It accepts an
arbitrary chapter URL, reads `#chapterList`, and follows the observed
newest-first 10-chapter pagination. Cards are identified by chapter id from a
href when available, or from the observed `/chapter/<id>.webp` image URL. The
adapter maps `無料`/`FREE` to `free`, `先読`/`先読み` to `paid`, and other
ordinary cards to `quota`; it does not guess free expiry or quota state.

The adapter yields site-neutral records and does not import Catalog or manage
BrowserSession. The `discover` CLI supplies a Page through shared CDP Chrome.
An incomplete listing is not a complete full scan, so DiscoveryService does
not reconcile missing sources. Promotion/PR cards are not removed by title
heuristics.

# Kadocomi Discovery adapter

## Current phase

P1 Discovery and P2 capture passed independent review (P2 BLOCKING=0). The corrected production Runner also passed live verification on the observed episode 4.1 variant. P3 Batch/ZIP integration and P4 independent end-to-end verification are not implemented. Other observed reader layouts remain unsupported and fail closed.

## Discovery contract

The adapter accepts HTTPS work-detail routes on `comic-walker.com` matching the strict `KC_<six digits>_S` work-ID shape and observed query forms. The live-verified work is `KC_004915_S`; the no-deadline free classification is limited to that work. Other no-deadline works remain unknown. Bounded `from_url` / `through_url` input is unsupported. It uses the unique work-scoped `UL.EpisodesTabContents_episodeList__*` under `DIV.EpisodesTabContents_root__*`; page-wide recommendations and teasers are outside the scope.

When present, exactly one visible expansion button must match `\u5168{N}\u8a71\u3092\u8868\u793a`. The parser waits no more than 12 seconds for two identical scoped snapshots 500 ms apart. The number of validated episode rows must equal the declared total. It buffers and validates the complete list before yielding newest-first.

Each episode row must be a direct `LI` with one episode anchor. Its unique `EpisodeThumbnail_title__*` title node must be inside that anchor. Work and episode IDs must match the supported URL shape; saved URLs omit query parameters. Source IDs are work-scoped as `work_id:episode_id`.

The only accepted non-episode list child observed for this work is the ended-publication marker `\u305d\u306e\u4ed6\u306e\u8a71\u306f\u516c\u958b\u7d42\u4e86\u3057\u307e\u3057\u305f`. It must be one attribute-free `LI` containing exactly one direct paragraph, no links, no episode title, and no other text. Its direct-child index, text, and previous/next episode labels are part of the stable snapshot. Zero or one such marker is allowed. Any other non-episode child, duplicate marker, changed marker, duplicate episode ID, malformed row, wrong-work URL, ambiguous deadline, gate-like text, or incomplete list fails closed. This marker signals that other episodes have ended publication; it does not identify their exact IDs or lifetime order.

## Access and Catalog safety

The row deadline is read only from the observed `\u914d\u4fe1\u671f\u9650\uff1aYYYY/MM/DD HH:MM` label, separate from publication date and title. A future explicit deadline is classified free and saved as `free_until`; a later observed missing deadline clears stale expiry. A no-deadline row is classified free only for the independently verified work `KC_004915_S`. No-deadline rows on other works and expired rows remain unknown. Current validated public rows are `available=true`.

The adapter sets `allow_inferred_display_positions=False` and emits no global position hints. Existing positions stay unchanged and new positions remain NULL. A complete full Discovery can mark absent Sources unavailable; an incomplete full run cannot reconcile missing Sources. Incremental Discovery leaves unseen Sources unchanged. Reusing an external ID preserves Source, Item, Completed, CrawlRun, and Artifact history through disappearance and republication.

The shared Discovery service initializes `Work.title` from the dedicated Watchlist label and does not apply the adapter's `canonical_title`. Set that label to the actual work title.

## P2 direct capture behavior

`KadocomiAdapter` accepts only `access_strategy="direct"`, rejects quota resources and entry-only runs, and requires an exact episode URL. It initially navigates to the corresponding work page, re-runs the complete public-list Discovery contract, and proceeds only when that exact row is present, available, currently classified free, and not expired. It then opens the canonical query-free episode URL and verifies the final work/episode IDs, exact episode H1 and `og:title`, and absence of a visible dialog. The canonical Catalog source URL is retained.

The adapter installs a non-interfering observer before navigation. It preserves the original `URL.createObjectURL` and `drawImage` calls, retaining only bounded Blob references and immutable draw-time metadata. A capture succeeds only when the active unique Kadocomi reader slide has the next expected content slot or right-to-left spread; each canvas must map through its last full-frame identity `HTMLImageElement` draw to the retained Blob, and decoded Blob RGBA pixels must equal the finished canvas both before and after asynchronous byte reads. The original Blob bytes are returned unchanged as `.webp` / `image/webp`. Missing, changed, composed, transformed, oversized, or non-WebP proof fails hard. Locator and screenshot fallback are disabled.

The content slot inventory is derived from the live reader DOM. The observed shape is one first canvas, then two canvases per content slide in physical right-to-left order, followed by the explicit end-of-book slide. The end marker defines the stop boundary; one observed trailing non-content recommendation slide may follow, but the adapter never turns into or captures it. It stops only after every unique content slot has been captured and the active slide contains the explicit end-of-book marker. The bounded native capture currently covers at most 8,000,000 total decoded pixels per capture and 4 MiB per source Blob.

Local synthetic browser tests use the observed DOM shape: content wrappers `DIV._pageCanvasWrapper_...[data-type=contents]` each own one `canvas._root_bx4cr_1`; the paired main END wrappers are distinguished from the trailing recommendation end marker. They cover byte-exact WebP output, spread order, explicit END/trailing-slide exclusion, wrong Blob attribution, asynchronous canvas mutation, transformed draws, expired/missing targets, foreign-episode redirects, missing main END, and skipped/reversed slots. The corrected live Runner completed all 21 content slots and stopped at the paired main-reader END markers; every output passed native WebP provenance/pixel checks at 836x1200. The independent Reviewer also passed P2 with BLOCKING=0. The live audit and earlier selector failure are recorded in `runbooks/kadocomi/PROGRESS.md`; P3 is not started.

## Operational validation

Use only a dedicated Watchlist and Catalog beneath ignored `work/kadocomi/`; never point at the normal user Catalog/output. Real-site browser access uses the existing shared Crawler Chrome through CDP and Playwright. The adapter does not launch Chrome or select a profile. Do not log in, buy, consume tickets/coins/points, access rental/purchased content, or bypass gates.

For phase status, exact observed counts, test commands, live results, uncertainties, and P2 source evidence, see `runbooks/kadocomi/PROGRESS.md`. Detailed phase contracts are in `runbooks/kadocomi/`.

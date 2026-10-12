# Kadocomi Site Adapter

## Current phase

P1 Discovery and P2 capture passed independent review (BLOCKING=0). P3 direct-only Batch policy, CLI registration, and local Catalog-to-ZIP integration passed independent review (BLOCKING=0, NONBLOCKING=0). P4 Tester and Reviewer passed isolated shared-CDP CLI Batch/ZIP/source/Completed audits for both episode 4.1 and the first-episode 38-slot target (BLOCKING=0, NONBLOCKING=0); the 21-slot normal CLI control and final post-Discovery/Catalog audit also passed. Final docs synchronization review passed (Reviewer BLOCKING=0, NONBLOCKING=0); Lead accepted closeout. The earlier repository-wide pytest run had one known baseline failure reproduced at `ceb3434`; full Ruff passed. Episode 79 is a known unsupported layout: its empty paired END is followed by a recommendation slide with a secondary END marker, so inventory validation fails before capture. Other unobserved reader layouts also remain unsupported and fail closed.

## Discovery contract

The adapter accepts HTTPS work-detail routes on `comic-walker.com` matching the strict `KC_<six digits>_S` work-ID shape and observed query forms. The live-verified work is `KC_004915_S`; the no-deadline free classification is limited to that work. Other no-deadline works remain unknown. Bounded `from_url` / `through_url` input is unsupported. It uses the unique work-scoped `UL.EpisodesTabContents_episodeList__*` under `DIV.EpisodesTabContents_root__*`; page-wide recommendations and teasers are outside the scope.

When present, exactly one visible expansion button must match `\u5168{N}\u8a71\u3092\u8868\u793a`. The parser waits no more than 12 seconds for two identical scoped snapshots 500 ms apart. The number of validated episode rows must equal the declared total. It buffers and validates the complete list before yielding newest-first.

Each episode row must be a direct `LI` with one episode anchor. Its unique `EpisodeThumbnail_title__*` title node must be inside that anchor. Work and episode IDs must match the supported URL shape; saved URLs omit query parameters. Source IDs are work-scoped as `work_id:episode_id`.

The only accepted non-episode list child observed for this work is the ended-publication marker `\u305d\u306e\u4ed6\u306e\u8a71\u306f\u516c\u958b\u7d42\u4e86\u3057\u307e\u3057\u305f`. It must be one attribute-free `LI` containing exactly one direct paragraph, no links, no episode title, and no other text. Its direct-child index, text, and previous/next episode labels are part of the stable snapshot. Zero or one such marker is allowed. Any other non-episode child, duplicate marker, changed marker, duplicate episode ID, malformed row, wrong-work URL, ambiguous deadline, gate-like text, or incomplete list fails closed. This marker signals that other episodes have ended publication; it does not identify their exact IDs or lifetime order.

## Access and Catalog safety

The row deadline is read only from the observed `\u914d\u4fe1\u671f\u9650\uff1aYYYY/MM/DD HH:MM` label, separate from publication date and title. A future explicit deadline is classified free and saved as `free_until`; a later observed missing deadline clears stale expiry. A no-deadline row is classified free only for the independently verified work `KC_004915_S`. No-deadline rows on other works and expired rows remain unknown. Current validated public rows are `available=true`.

The adapter sets `allow_inferred_display_positions=False` and emits no global position hints. Existing positions stay unchanged and new positions remain NULL. A complete full Discovery can mark absent Sources unavailable; an incomplete full run cannot reconcile missing Sources. Incremental Discovery leaves unseen Sources unchanged. Reusing an external ID preserves Source, Item, Completed, CrawlRun, and Artifact history through disappearance and republication.

The shared Discovery service initializes `Work.title` from the dedicated Watchlist label and does not apply the adapter's `canonical_title`. Set that label to the actual work title.

## P3 Batch eligibility and CLI

`KadocomiSitePolicy` selects only `site=kadocomi`, `available=true`, `access_mode=free` Sources with a strict work-scoped `work_id:episode_id`. `free_until` may be NULL (no deadline was displayed at the last Discovery) or an aware future datetime. Expired/equal, malformed, or timezone-naive values fail closed. Quota, paid, unknown, owned, grant, rental, quota-resource, and grant-only paths are unsupported. The P1 Discovery adapter marks a no-deadline row free only for the independently verified work; the policy trusts Catalog's current `access_mode` classification and never infers free from NULL expiry alone.

The manual `crawl` CLI registry and Batch adapter/Policy registries include Kadocomi. Manual Crawl must use `--access-strategy direct`; the default `auto` is rejected. Batch keeps the generic pending-only Planner and Executor. The Batch adapter requires a canonical query-free exact episode Catalog target matching its configured external identity, then repeats target-local listing membership and current free/deadline validation immediately before viewer navigation. Candidate URLs and display positions are not renumbered or rewritten.

## P2 direct capture behavior

`KadocomiAdapter` accepts only `access_strategy="direct"`, rejects quota resources and entry-only runs, and requires an exact episode URL. It initially navigates to the corresponding work page, re-runs the complete public-list Discovery contract, and proceeds only when that exact row is present, available, currently classified free, and not expired. It then opens the canonical query-free episode URL and verifies the final work/episode IDs, exact episode H1 and `og:title`, and absence of a visible dialog. The canonical Catalog source URL is retained.

The adapter installs a non-interfering observer before navigation. It preserves the original `URL.createObjectURL` and `drawImage` calls, retaining only bounded Blob references and immutable draw-time metadata. A capture succeeds only when the active unique Kadocomi reader slide has the next expected content slot or right-to-left spread; each canvas must map through its last full-frame identity `HTMLImageElement` draw to the retained Blob, and decoded Blob RGBA pixels must equal the finished canvas both before and after asynchronous byte reads. The original Blob bytes are returned unchanged as `.webp` / `image/webp`. Missing, changed, composed, transformed, oversized, or non-WebP proof fails hard. Locator and screenshot fallback are disabled.

The content slot inventory is derived from the live reader DOM. Two observed topologies are accepted. Episode 4.1 starts with one canvas, continues with two canvases per content slide in physical right-to-left order, and stops at the paired `n=1`,`n=2` END slide; its observed trailing recommendation slide is excluded. The first-episode variant starts with one slot, has paired spreads, ends content with a single slot owning main END `n=2`, then requires the immediately following empty slide with main END `n=1`,`n=2`. For that mixed-final topology, ordinary overlay turns are used through the final content slide; only after its unique slot is captured does a safe `ArrowLeft` action request the next slide, which must settle exactly one index later as the explicit empty END. Marker class, number, slide ownership, geometry, and the entire slot inventory are revalidated. Any extra marker, slide, content, missing transition, skipped index, or changed inventory fails closed. This evidence is limited to the observed episode 4.1 and first-episode route on the verified work. The bounded native capture currently covers at most 8,000,000 total decoded pixels per capture and 4 MiB per source Blob.

Local synthetic browser tests exercise both reader topologies through Runner and Batch-to-ZIP, keep all source WebP bytes in order, and cover wrong Blob attribution, asynchronous canvas mutation, transformed draws, expired/missing targets, foreign-episode redirects, marker omissions/moves/duplicates/wrong numbers, content at END, extra slides, missing terminal pairs, reversed spreads, skipped turns, and a final ArrowLeft that does not advance. The original 21-slot layout and its independent P2 source audit remain unchanged. The 38-slot implementation passed independent review, normal live CLI Batch/ZIP, and an all-38 independent source-byte/full-RGBA audit. The final post-Discovery/Catalog audit preserved Catalog identities, statuses, Artifacts, and NULL positions; details are recorded in `runbooks/kadocomi/PROGRESS.md`.

The local Kadocomi Batch integration test uses real Discovery, Catalog, Planner, Executor, Runner, and packager code with browser fixtures. It verifies byte-preserved WebP ZIP members for both reader topologies, canonical Catalog source identity, Watchlist/Catalog title and episode-label naming, Artifact registration, and Completed only after END. Runtime expiry, foreign-episode redirect, missing END, missing mixed-final marker, and a final no-advance leave the Item pending without a ZIP/Artifact. The earlier targeted P3 set passed 27 / 0 skipped; affected Batch, Executor, naming, Catalog, packaging, and existing site-policy regressions passed 301 / 0 skipped (469 pytest-asyncio deprecation warnings). The independent Reviewer passed P3 with BLOCKING=0 and NONBLOCKING=0: 54 independent tests passed, none skipped (25 selected plus 29 CLI/packaging; 13 deselected by selection).

The P4 Tester used fresh isolated Catalogs and the normal `batch run --limit 1` path for the episode 4.1 and first-episode targets. For 4.1, all 21 ZIP members matched the P2 page files and separate live Blob audit, passed CRC, and decoded as 836x1200 WebP; ZIP SHA-256 is `d64fd2a66c6982c3045a70940b36846cd7f12af4685551f9488174673099e6ff`. For the first episode, all 38 ordinal members matched the independent live Blob/full-RGBA audit, passed CRC, and decoded as 835x1200 WebP; ZIP SHA-256 is `7a98969ce7c2ee05c4ac93a0a593fa671451f7b5389f1fe74eeccad37c5365ea`. The separate 21-slot normal CLI control also passed against the independent P2 page files; its ZIP SHA-256 is `943c469041da7a2629eea810927694acea7cb5e6bdaf09b5441735edac089942`. Both primary runs reached explicit END and registered Artifact/Completed; the CLI removed temporary page output after packaging, so these audits do not claim a retained manifest. Final Discovery/Catalog audit preserved all 53 Sources/IDs, 53 available/free rows, 46 deadlines and 7 NULL deadlines, NULL positions, two Completed Items, 51 pending Items, and both Artifacts; integrity was `ok` and actual-catalog renumber dry-run proposed no moves. Full commands, counts, and limitations are in `runbooks/kadocomi/PROGRESS.md`; the prior full-suite baseline failure is documented there.

## Operational validation

Use only a dedicated Watchlist and Catalog beneath ignored `work/kadocomi/`; never point at the normal user Catalog/output. Real-site browser access uses the existing shared Crawler Chrome through CDP and Playwright. The adapter does not launch Chrome or select a profile. Do not log in, buy, consume tickets/coins/points, access rental/purchased content, or bypass gates.

For phase status, exact observed counts, test commands, live results, uncertainties, and P2 source evidence, see `runbooks/kadocomi/PROGRESS.md`. Detailed phase contracts are in `runbooks/kadocomi/`.

Example isolated direct-only commands (using the already-populated dedicated Watchlist/Catalog):

```powershell
python -m screenshot_crawler.cli crawl --site kadocomi `
  --url https://comic-walker.com/detail/KC_004915_S/episodes/KC_0049150000400011_E `
  --access-strategy direct --output-dir work/kadocomi/manual-output `
  --library-dir work/kadocomi/manual-library
python -m screenshot_crawler.cli batch plan --site kadocomi `
  --catalog work/kadocomi/catalog.sqlite
python -m screenshot_crawler.cli batch run --site kadocomi `
  --catalog work/kadocomi/catalog.sqlite --output-root work/kadocomi/batch-output `
  --library-dir work/kadocomi/batch-library --limit 1
```

Always use a dedicated test Catalog, Watchlist and output root. P4 live validation uses separate fresh paths and must not reuse an already-completed item.

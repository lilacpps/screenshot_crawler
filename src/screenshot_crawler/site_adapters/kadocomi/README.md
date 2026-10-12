# Kadocomi Discovery adapter

## Current phase

P1 Discovery passed independent review (BLOCKING=0). P2 implementation is pending its phase contract; P3 Batch/ZIP integration and P4 independent end-to-end verification are not implemented. The source-native reader research in `runbooks/kadocomi/PROGRESS.md` is evidence for later work, not a production capture guarantee.

## Discovery contract

The adapter accepts HTTPS work-detail routes on `comic-walker.com` matching the strict `KC_<six digits>_S` work-ID shape and observed query forms. The live-verified work is `KC_004915_S`; the no-deadline free classification is limited to that work. Other no-deadline works remain unknown. Bounded `from_url` / `through_url` input is unsupported. It uses the unique work-scoped `UL.EpisodesTabContents_episodeList__*` under `DIV.EpisodesTabContents_root__*`; page-wide recommendations and teasers are outside the scope.

When present, exactly one visible expansion button must match `\u5168{N}\u8a71\u3092\u8868\u793a`. The parser waits no more than 12 seconds for two identical scoped snapshots 500 ms apart. The number of validated episode rows must equal the declared total. It buffers and validates the complete list before yielding newest-first.

Each episode row must be a direct `LI` with one episode anchor. Its unique `EpisodeThumbnail_title__*` title node must be inside that anchor. Work and episode IDs must match the supported URL shape; saved URLs omit query parameters. Source IDs are work-scoped as `work_id:episode_id`.

The only accepted non-episode list child observed for this work is the ended-publication marker `\u305d\u306e\u4ed6\u306e\u8a71\u306f\u516c\u958b\u7d42\u4e86\u3057\u307e\u3057\u305f`. It must be one attribute-free `LI` containing exactly one direct paragraph, no links, no episode title, and no other text. Its direct-child index, text, and previous/next episode labels are part of the stable snapshot. Zero or one such marker is allowed. Any other non-episode child, duplicate marker, changed marker, duplicate episode ID, malformed row, wrong-work URL, ambiguous deadline, gate-like text, or incomplete list fails closed. This marker signals that other episodes have ended publication; it does not identify their exact IDs or lifetime order.

## Access and Catalog safety

The row deadline is read only from the observed `\u914d\u4fe1\u671f\u9650\uff1aYYYY/MM/DD HH:MM` label, separate from publication date and title. A future explicit deadline is classified free and saved as `free_until`; a later observed missing deadline clears stale expiry. A no-deadline row is classified free only for the independently verified work `KC_004915_S`. No-deadline rows on other works and expired rows remain unknown. Current validated public rows are `available=true`.

The adapter sets `allow_inferred_display_positions=False` and emits no global position hints. Existing positions stay unchanged and new positions remain NULL. A complete full Discovery can mark absent Sources unavailable; an incomplete full run cannot reconcile missing Sources. Incremental Discovery leaves unseen Sources unchanged. Reusing an external ID preserves Source, Item, Completed, CrawlRun, and Artifact history through disappearance and republication.

The shared Discovery service initializes `Work.title` from the dedicated Watchlist label and does not apply the adapter's `canonical_title`. Set that label to the actual work title.

## Operational validation

Use only a dedicated Watchlist and Catalog beneath ignored `work/kadocomi/`; never point at the normal user Catalog/output. Real-site browser access uses the existing shared Crawler Chrome through CDP and Playwright. The adapter does not launch Chrome or select a profile. Do not log in, buy, consume tickets/coins/points, access rental/purchased content, or bypass gates.

For phase status, exact observed counts, test commands, live results, uncertainties, and P2 source evidence, see `runbooks/kadocomi/PROGRESS.md`. Detailed phase contracts are in `runbooks/kadocomi/`.

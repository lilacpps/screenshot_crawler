# Comic DAYS adapter

The adapter supports canonical `comic-days.com/episode/<id>` pages. Discovery
validates the complete official Atom feed against the site's pagination total,
the complete paginated readable-product listing, and the `free_only=1`
subset. It preserves the latest-first site order and classifies each row from
first-party state: `free`, a positively eligible Work Ticket candidate
(`quota`), an active Work Ticket grant (`quota` plus the native
`rental_end_at`), `paid`, or fail-closed `unknown`. All identities, counts,
orders, and access rows are validated before the first record is yielded.
The official free-feed membership is authoritative for a coherent free row:
`can_read=true`, `is_free=true`, no ticket rental, no ownership, no
unavailability, and no expiry. Comic DAYS currently also emits two such free
rows with `is_support_ticket=true`, numeric `rental_price=0`, and integer
`rental_term=72`; this metadata is supporting evidence and remains `free`,
never `quota`. Malformed or contradictory variants remain fail-closed.

The verified viewer mode is the horizontal RTL canvas viewer. Active pages are
selected from the runtime slider and canvas-bearing page areas. Volume links,
questionnaire/premium blocks, blank areas, and the colophon are excluded. The
adapter first attempts a strict site-local reconstruction from the exact blob
image drawn into each selected canvas; unsafe or incomplete provenance falls
back to the normal canvas locator capture for the whole spread.
Render readiness is tracked separately from native safety: incomplete or
one-sided spreads remain `LOADING`, while a completed but unsafe canvas may use
the all-spread locator fallback.  Readiness requires the observed 4x4 integer
tile grid to cover both source and destination frame geometry, preserving only
the narrow right edge.  A canvas width/height reset clears the observed draw
generation; a complete redraw is required before it can become ready again.
`clearRect` is treated conservatively as a destructive reset of observed pixel
traces.  A clip operation remains native-unsafe across later base/tile draws
until an actual canvas width/height assignment or
`CanvasRenderingContext2D.reset()` is observed; `clearRect` does not clear the
canvas clipping region.  Source-body
fetch deadlines remain active through `arrayBuffer()` and always clear in a
`finally` path.
If clipping or a fully suppressing composition such as `globalAlpha=0` occurs
during the current base/tile generation, readiness is withheld until reset and
redraw.  A clip applied only after a proved complete composition remains
render-ready for the ordinary whole-spread fallback.
Capture compares the selected identity and generation before source fetch and
again after reconstruction, so a source replacement or canvas mutation fails
closed instead of saving bytes under a stale identity.

At the observed active-grant tail, body slider 17 is followed by slider 19,
which contains exactly one on-screen `js-back-link-page` (two images, no
canvas) and one on-screen `js-page-ad` (two iframes, no canvas), then slider
21's visible `#viewer-colophon` with no body rows.  Only that validated,
viewport-intersecting pattern is treated as the generic `AD` transition;
unknown, blank, paid, mixed, or stagnant non-body panels fail closed.  The
adapter records the actual slider before each forward action and requires a
monotonic, bounded transition, so the tail controls are never captured or
clicked.
The free 32-page episode has the same indexed back-link/ad wrappers at areas
33/34 and a visible colophon at area 35 while the slider reports 35/36. This
is a normal terminal observation rather than an advertisement skip. The
adapter ends at that colophon and does not press the control again, because a
read-only live check showed that the next press can leave the canonical viewer
scope.

The site-local capture hook caps each source body at 2,000,000 bytes (decimal),
retains at most 256 image references, and keeps separate rolling draw and
mutation traces of 6,000 records each. Image references are not evicted: once
the reference cap is exhausted, a new image is recorded as an unsupported
mutation. A source-body fetch failure, oversized/invalid payload, or unsafe
native provenance uses the normal whole-spread locator fallback only when the
selected spread is positively render-ready. Missing or incomplete render
readiness remains `LOADING` and reaches the bounded timeout instead of
capturing a blank or partial spread. Behavior for unusually long runs that
exhaust these caps is not verified across other works.
The latest unsafe mutation sequence is retained separately in a WeakMap keyed
by the canvas object, so rolling trace eviction cannot revive native capture;
an actual reset clears that marker and a complete later base/tile generation
can recover native capture.

Initialization positively identifies the horizontal viewer and requires a
numeric slider within its advertised range.  A shared-profile reopen at the
colophon may have no active body canvas; the adapter rewinds with the validated
backward control first, then waits for the first fully ready spread.  Missing,
invalid, or non-progressing slider/control state fails within the adapter's
bounded initialization timeout.  The timeout is one monotonic budget covering
viewer observation, rewind control inspection/clicks, transition waits, and the
final readiness check; initialization cannot return while the slider is later
than position 1.

Discovery, Policy, the site-owned read-only resolver, and the exact Work Ticket
entry path are implemented and synthetic-browser verified. The policy uses `work_ticket` with work
scope, deferred grant resolution, a 23-hour resource cooldown, and
observed-consumption commits. Generic observed-consumption commit uses the
policy's conservative 71-hour value; a later fresh Discovery refreshes the
source with the exact native `rental_end_at` when available. The resolver
preserves Catalog order, validates one complete native listing per work, and
selects at most one pending candidate. The policy keeps `quota_limit=None` so
the resolver sees the broad pool; its work-scoped resource gate permits at
most one actual selection per work. Entry accepts only the unique visible
enabled series-ticket control with the exact observed Japanese label and
matching episode identity inside the target locked
`section.private-viewer.js-viewer[data-json-url]` JSON scope and its unique
`.read-button-container`; the unlocked capture viewer uses the separate
`section.viewer.js-viewer` scope. The sibling
`[data-aggregate-id][data-type="episode"]` surface binds the work identity.
Paid and premium controls are never fallback paths; the live Work5 guard
observed the purchase control separately with a 90pt price. Consumption is latched
once after positive native rental and work-ticket debit/recharge evidence. A
bounded read-only readiness stage then waits for the same episode's unlocked
viewer, matching JSON identity, visible canvas, and render-ready native row;
loading is transient, while identity ambiguity fails closed. A subsequent
viewer failure preserves the first observed consumption. Successful entry
still requires the usable viewer,
and `chargedAt` must be newer than the pre-click value and current observation
time. Discovery and Policy never click or consume an access control. A fresh
temporary-Catalog production CLI direct run for an already-active grant
completed the 17-page crawl, reached `END`, packaged a 17-entry ZIP, and left
the Item completed with a present Artifact and no quota-resource consumption.
The bounded 2026-10-03 reserved-ticket production Batch attempt completed the
work1 32-page free Phase A, then consumed exactly one Work Ticket for work4
source 168. Its grant and work-scoped resource state were persisted, but the
same run stopped during the first post-grant viewer readiness check before
Phase C. A production-hook cold-navigation probe later observed the unlocked
viewer become render-ready at about 2 seconds; no retry or additional ticket
was used. Fresh Discovery updated the Catalog to the exact native 72-hour
expiry. That historical third-ticket run stopped before Phase C; the later
authorized fourth-ticket Work5 run verified the complete same-normal-CLI
grant-only → replan → direct crawl → packaging flow.
The later non-consuming Phase5C recovery ran source168 directly from the same
isolated Catalog, completed its 38-native-PNG crawl and ZIP, and preserved the
unchanged Work Ticket resource timestamp. Fresh Discovery afterward preserved
the completed Item, Artifact, and native expiry while advancing
`access_checked_at`. A new Work5 Discovery produced 77 validated records
(1 paid, 4 free, 72 quota); its real resolver preflight selected source75 and
verified native term 72, `isCharged=true`, canonical identity, one exact
enabled ticket control, and a distinct paid control. No ticket was used in
this preflight.
The separate non-consuming work1/work4 preflight used the real
`BatchPlanner`: one direct source and 159 deferred candidates. It skipped
work1 because its Work Ticket was on cooldown and selected work4 source 168
(`13933686331677356244`) as the first live candidate; the native 72-hour term,
ready resource, exact locked control, and distinct paid control were verified
read-only. The later bounded Batch attempt used exactly one ticket for this
candidate; paid operations remained at zero. Across the four-ticket ledger,
paid operations remained at zero. The Work4 active-grant recovery produced 38
native PNGs at 1125x1600; the Work5 ticket crawl produced 20 native PNGs at
1121x1600. The historical cold-viewer value 42 was a total page-area count,
not a body PNG count. Generic 4x4 native geometry and known tail handling
remain unchanged. A dedicated CDP operation logger was not installed for the
fourth probe; exact guard, native pre/post state, resource timestamp, SQL
phase transition, and fresh Discovery state are retained as evidence.
Ownership, unavailable, point, premium, paid, login, and non-72-hour new-ticket
states fail closed or remain unsupported. Whole-work Discovery aborts on an
unsupported or contradictory access row; only observed native tail patterns
are skippable, and existing long-run capture caps remain bounded.

The quota entry stage keeps one shared 10-second monotonic page-change budget
across pre-observation, control/click, native grant confirmation, and viewer
readiness; a separate 3-second read-only recovery window is used only after a
possibly dispatched click. Ordinary quota initialization also needs metadata
and viewer normalization, so the Runner-facing site-local budget is 35 seconds
including those stages and headroom, without changing the page-change default.

## Isolated operation

Use an explicit experiment Catalog and an isolated watchlist when running the
real-site path. Discovery reads the watchlist target; Batch runs from the
already populated Catalog and therefore does not take a watchlist argument.

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli watch add `
  --watchlist output\comicdays-watchlist.yaml `
  --key comicdays-target `
  --work-key comicdays:series:2550689798737278979 `
  --site comicdays `
  --url "https://comic-days.com/episode/2550689798754939004" `
  --label "かみあそび！～カードゲーマー少女の日常～"

.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover `
  --site comicdays --mode full `
  --watchlist output\comicdays-watchlist.yaml `
  --catalog catalog_comicdays.sqlite

.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run `
  --site comicdays --limit 1 `
  --catalog catalog_comicdays.sqlite `
  --output-root output\comicdays-batch `
  --library-dir output\comicdays-library
```

The representative direct run uses the adapter's bounded viewer
normalization/rewind guard. Grant-only Work Ticket runs use the generic Batch
entry-only lifecycle; the Item remains pending until the subsequent replan
selects its active grant for direct crawl. The controlled live evidence used
four Work Tickets total and zero paid operations, confirmed a 72-hour episode
grant and separate 23-hour work-ticket cooldown, and verified the complete
Work5 grant-only → replan → direct crawl → packaging cycle.

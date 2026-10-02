# Comic DAYS adapter

The adapter supports canonical `comic-days.com/episode/<id>` pages that are
members of the site's current official `atom/series/<series>?free_only=1`
feed. Discovery validates the complete official Atom feed against the site's
pagination total first, preserves its
latest-first order, and marks entries outside the free subset as `unknown` so
the free-only policy skips them without attempting an access action.

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

Ticket, point, coin, purchase, rental, owned, grant, and quota flows are not
implemented. The adapter refuses those access strategies before navigation and
revalidates free-feed membership after navigation.

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

The representative run uses `max_pages=40` and the adapter's bounded
64-step viewer normalization/rewind guard. Only the current `free_only=1`
episode subset is eligible; non-free, ticket, owned/grant, quota, and other
viewer modes are skipped or rejected without an access action.

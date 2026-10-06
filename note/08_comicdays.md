# Comic DAYS

## Current implementation

The production adapter is registered as `comicdays` for direct crawl,
Discovery, and Batch policy evaluation. Discovery loads the canonical episode,
derives its series identity, validates the complete official Atom feed against
the site's pagination-information count, the complete paginated readable-
product listing, and the `free_only=1` subset. It yields the full feed in the
observed latest-first order only after all invariants pass. Sources are mapped
from first-party state to `free`, Work Ticket candidate `quota`, active Work
Ticket grant `quota` with native `access_granted_until`, `paid`, or safe
`unknown`. The Atom `updated` value is not copied to `published_at`.
The free Atom membership is authoritative only with coherent free state:
`can_read=true`, `is_free=true`, no ownership/unavailability, no ticket
rental, and no expiry. The live Work5 listing also emits two free rows with
`is_support_ticket=true`, numeric zero `rental_price`, and integer
`rental_term=72`; this observed supporting metadata remains `free` and never
becomes a quota candidate. Other malformed or contradictory combinations fail
closed before any record is yielded.

The viewer adapter supports the observed horizontal RTL canvas viewer. It
selects only the current slider spread's logically expected canvas-bearing page
areas. Capture attempts lossless JPEG coefficient reconstruction first, then
uses exact canvas-to-blob provenance for all reconstructed PNG parts, and
falls back to locator capture for the entire spread when provenance or pixel
mutation safety cannot be proven. A body spread is complete only when every
expected area is visible with exactly one ready canvas; a missing or hidden
second area remains loading. The 20-page leading-area live variant uses body
areas 1..20 with sliders 1, 2, 4, ..., 20 and terminal sliders 22/23.
Terminal state requires a completed forward
transition to the visible colophon with no active body canvas. URL changes are
reported as `NEXT_CONTENT`. Render readiness is tracked separately from native
provenance: incomplete or one-sided spreads remain `LOADING`, while a
completed but unsafe canvas uses the whole-spread locator fallback. Initialization
positively identifies the horizontal viewer and requires a numeric slider within
the advertised range. Because the shared profile can reopen at the colophon with
no active body canvas, it rewinds with the validated backward control until
slider position 1, then waits for the first fully ready spread. Missing, invalid,
or non-progressing slider/control state fails within the bounded initialization
timeout. The same monotonic deadline covers viewer observation, control
inspection/clicks, transition waits, and final readiness; initialization cannot
return while the slider is later than position 1.

The live granted viewer also has a non-body tail between content and the
colophon: body slider 17 advances to slider 19 with one on-screen
`js-back-link-page` (two images, no canvas, wrapped by exactly one
`link-page-content`) and one on-screen `js-page-ad` (two iframes, no canvas,
wrapped by exactly one `ad-nav-area-wrap page-content`), then advances to slider 21 with a visible
`#viewer-colophon` and no active rows; its ten images are under exactly one
`back-matter-content` child. The adapter treats only this exact
viewport-intersecting pattern as `AD`, tracks the actual pre-advance slider,
and requires bounded monotonic progress. Unknown, blank, paid, mixed, repeated,
or retrograde panels fail closed and are never captured or clicked.

Phase3A research used the hook's exact source URL/id and draw generation and
isolated source bytes from the current shared-CDP viewer. The sampled JPEGs
were baseline SOF0, 1125x1600 for free/granted samples and 1127x1600 for the
target episode. They were either grayscale 1x1 or three-component Y/Cb/Cr
4:4:4, all with 8x8 MCU blocks. The runtime mapping is 16 tiles of 280x400
(35x50 coefficient blocks), covering 1120x1600; the final coded block column
is preserved as the 5px or 7px visible right edge. Production now attempts
this coefficient reconstruction first. It requires exact geometry, a
bijective block mapping, source APPn/COM preservation, unchanged quantization,
sampling, colorspace, SOF, and exact post-write coefficient readback. The
writer may re-encode DHT entropy tables, and may remove one observed leading
duplicate JFIF APP0; any other marker change, post-scan marker, unsupported
sampling/progressive source, malformed input, or unsafe canvas falls back to a
whole-spread reconstructed PNG and then locator capture. JPEG and PNG parts
are never mixed within one spread. The bounded source report is
`output/comicdays_phase3a_report/report.json`; current live reports record
capture mode and exact manifest/ZIP audits.

The same lossless path now has one explicit additional geometry whitelist for
the observed 720x1024 grayscale variant: sixteen 176x256 tiles cover
704x1024, preserving the two untouched right-edge coefficient columns. This
variant must be baseline 8-bit, one-component 1x1 sampling; color, subsampled,
progressive, malformed, incomplete, or non-8px-aligned inputs still fall back
to reconstructed PNG. The bounded 2026-10-06 proof used areas 1, 2, 16, and
17 with coefficient readback, metadata/SOF/quantization/sampling/colorspace/
progressive checks, and exact decoded JPEG/PNG pixel equality. The compact
metadata report is `docs/research/comicdays_png_fallback_20261006.md`.
The post-change bounded crawl of the requested 22-page episode reached `END`
with 22 native JPEG pages, including atomic two-part spreads; the same crawl
had 22 reconstructed PNG pages before this whitelist and no locator fallback.

The free 32-page regression has indexed back-link/ad wrappers at areas 33/34
and a visible colophon at area 35 while the slider reports 35/36. The adapter
accepts that observed colophon as terminal; it does not issue another forward
action after it, since a read-only live check showed that such an action can
leave the canonical viewer scope.

The current Comic DAYS policy supports one named resource, `work_ticket`, with
work-scoped state, `quota_limit=1`, non-deferred quota execution, a 23-hour
cooldown, and `after_observed_consumption` commits. Discovery records the
site's observed 72-hour `rental_end_at` when a grant is active. Generic
observed-consumption commit uses the conservative 71-hour
`access_grant_until()`; a later fresh Discovery refreshes the exact native
expiry. Planner ordering remains the existing Catalog ordering, with at most
one quota candidate per work. Comic DAYS no longer has a production live
candidate resolver: Discovery full is the candidate-state authority.
An episode URL supplied for live verification is the seed for full Discovery
of its native work; the natural Planner candidate may be another episode in
that work. The Catalog classification and existing Planner ordering are kept
unchanged.

Normal quota Batch opens the selected episode once, validates the target-local
identity and contract, uses the exact visible/enabled Work Ticket control once,
confirms positive debit plus unlocked viewer evidence, and continues crawling
on that same Page. Grant-only uses the same entry path, records the resource
state, leaves the Item pending, and creates no Artifact. It requires the unique
visible/enabled Work Ticket control,
matching episode/work identity inside the target locked
`section.private-viewer.js-viewer[data-json-url]` JSON scope and unique
`.read-button-container`; the unlocked capture viewer uses the separate
`section.viewer.js-viewer` scope. The sibling
`[data-aggregate-id][data-type="episode"]` surface binds the work. A separate
paid control may coexist only when its price attributes are explicit and it is
never used; the Work5 preflight observed a separate 90pt purchase control.
If a Work Ticket control is hidden or duplicated while a purchase control is
also present, the target state is `unknown` and the adapter fails closed; it is
not reinterpreted as positive paid state during viewer hydration.
It clicks once only, latches the first positive native rental and
work-level debit/recharge observation. The common positive confirmation
requires the canonical target episode, work, and viewer JSON identities to
match, exactly one visible normal viewer with no private viewer, the target
Work Ticket control to be gone, and `chargedAt` to be newer than both the
pre-click value and current observation time. Grant-only does not require
body/capture readiness. Normal quota continues on the same Page into the
existing initialize, viewer normalization, and capture guards; if those
guards fail closed, the recorded consumption is retained.
Discovery and Policy never click or consume an access control. A
candidate-local Catalog/live identity mismatch skips only that candidate with
`comicdays_discovery_refresh_required`; no alternate candidate or paid fallback
is attempted for that candidate. A changed or unknown Work Ticket contract is
the pass-wide stop case. Positive `isCharged=false` is a separate
`work_ticket_cooldown` outcome. The dated live evidence below predates this
current resolver-free flow; resolver/replan references there are historical.
Current isolated Test A evidence (2026-10-04) used seed
`12207421984217275863` and the natural Planner quota episode
`12207421983943213206` in work `comicdays:series:12207421983893924879`.
Grant-only opened the candidate once and recorded one exact Work Ticket click,
positive native debit plus unlocked target evidence, zero paid operations, and
zero resolver calls. The Item remained pending and no Artifact was created.
The CLI then returned `AccessConsumptionUnconfirmedError` after the positive
consumption latch; no second click or same-work retry occurred. The isolated
Catalog retained the resource timestamp. The policy's calculated 71-hour
fallback is `2026-10-07T16:35:36.501568+09:00`; its pre-Discovery source
snapshot was not captured. A complete post-grant Discovery refreshed native expiry and
`access_checked_at`. Adapter instrumentation recorded three small ticket
GraphQL checks and zero adapter whole-work listing calls. The browser page's
own JavaScript emitted 31 Atom/readable-product requests; these are separated
from crawler-side adapter traffic in
`output/tmp/comicdays_phase2a_liveA_20261004/evidence/request_classification.json`.
The bounded diagnostic then observed the correct normal viewer and identity but
the capture hook stayed incomplete with
`expected_body_area_not_visible_or_extra` (expected area 2 and no visible body
areas). This explains the known normal-crawl readiness failure for that target;
grant-only confirmation uses the separate target-local debit/unlock evidence.
The historical A/2R/3P raw directories under `output/tmp` are currently
unavailable; the original Catalogs, raw events, and positive-consumption files
cannot be revalidated. The reviewer verified the A evidence before the raw
artifacts disappeared, but the disappearance cause and any recovery location
are unknown, and no raw evidence was reconstructed. Future B/C evidence uses
an explicit protected task directory outside `output/tmp`.
The protected 2026-10-04 normal quota Test B then used source165
(`10834108156719217950`) in work
`comicdays:series:10834108156713445245` from the protected task directory
`output/comicdays_one_navigation_liveB_20261004_protected_1859/`. The real
Planner/Executor/Runner/Adapter path used one crawler target navigation and
one `Viewer_PurchaseViaTicket` mutation with positive debit/unlock evidence,
zero paid/premium operations, and no resolver/replan. The same Page captured
28 native JPEG pages, reached `END`, packaged a CRC-valid ZIP, and completed
the Item with a present Artifact. Adapter target GraphQL checks were 3 and
 adapter whole-work listing calls were 0. Raw AccessEvent classification
 recorded 31 page-JavaScript listing requests (Atom 28,
 `readable_product_pagination_information` 2, and
 `pagination_readable_products` 1); the harness's limited marker pattern
 counted 30. Page.goto and Locator.click were not directly instrumented: the
 one crawler target open is inferred from target-document ordering, and the one
 exact ticket click is inferred from the single `Viewer_PurchaseViaTicket`
 mutation plus positive debit/unlock evidence because reload removed selector
 metadata from the DOM listener. The protected audit is
`normal_batch_report.json` in that task directory, with a pre-package output
copy under `evidence/normal_batch/pre_package_output`. The B-run snapshot was
Ledger A=1, B=1, C=0; the corrected grant-only Test C below brings the current
task ledger to A=1/B=1/C=1.

The corrected isolated 2026-10-04 grant-only Test C used seed
`12207421983645809730`; full Discovery selected source39, episode
`2550912965783608326`, in work `comicdays:series:14079602755643699323`.
The production CLI exited successfully after one positive debit/unlock, left
 the Item pending, created no Artifact or images, and persisted the work resource
 state. The `consumed_at + 71h` value was calculated from policy; a separate
 pre-refresh source/SQLite snapshot of that value was not persisted. A second production
grant-only run selected another same-work quota candidate but stopped at the
Catalog-only `work_ticket_cooldown` gate with zero page, goto, click, or request
activity. A subsequent isolated full Discovery observed 63/63 and refreshed the
native expiry to `2026-10-07T19:22:14+09:00`.

 Durable page AccessEvents recorded three site-JavaScript
 `Viewer_SeriesTicketQuery` requests; the adapter-specific GraphQL call count is
 unknown because its wrapper output was not persisted. The quota path has zero
 whole-work adapter calls by code-path verification, rather than a persisted
 runtime counter. The C harness installed direct `Page.goto` and `Locator.click` wrappers, but a
harness-only nested-async error while writing post-Discovery output lost those
in-memory callback records. Durable production AccessEvents recover one
crawler target open, one same-target site transition, one
`Viewer_PurchaseViaTicket` mutation, and zero paid mutations; the report marks
these recovered counts separately from direct wrapper callbacks. Full audit:
`output/comicdays_grant_only_liveC_20261004_protected_1920/grant_only_report.json`.
The charged ticket state must include a native `chargedAt` baseline before a
click; a missing baseline is unknown and fails closed. Executor also rejects a
populated candidate external ID that differs from the current Catalog source
before any page is opened.
Comic DAYS Batch treats `Work.work_key` as the site-neutral stable Catalog
identity. Quota and grant-only execution therefore accepts arbitrary stable
keys such as `uchu-kyodai`; it neither rewrites the key during Discovery nor
uses it as the native series identity. Before a Work Ticket click, the adapter
checks the Catalog `Source.external_id` against the canonical episode URL and
then validates the live episode URL, native series/aggregate binding, private
viewer, ticket control, and viewer JSON as one target-local site-native
identity. The live series ID is used only for that page-local evidence and is
never compared with `Work.work_key`.

Candidate-local identity or locator mismatches use
`comicdays_discovery_refresh_required` with `stop_resource_pass=False`; they
skip only that candidate, do not click, and do not record consumption. A
changed/unknown Work Ticket contract such as a non-72-hour rental remains a
pass-wide stop. Work Ticket cooldown remains work-scoped (`work_id × site ×
resource`) and is written only from confirmed native consumption via the
`after_observed_consumption` path. Free/direct candidates may use arbitrary
Work keys as well.

The repaired live verification used the shared CDP endpoint and isolated
output/library paths. It captured 32 pages and reached `END`; manifest and
progress were copied before packaging to
`output/comicdays_c2_live8_evidence/`. The archive in
`output/comicdays_c2_library8/` matched all manifest fingerprints and
dimensions. The first identity was area 1 / slider 1 and the last body identity
was area 32 / slider 33; the following terminal state was the visible colophon.

Status: **PHASE 5 FINAL SAME-NORMAL-CLI GRANT→REPLAN→DIRECT CRAWL VERIFIED / 4 TICKETS TOTAL / PAID 0**

The fresh temporary-Catalog production CLI direct Batch check for already-
granted work2 completed 17 native body pages, reached `END`, produced a
17-entry ZIP with valid CRCs, completed the Item, and stored a present archive
Artifact. The Catalog has no `quota_resource_states` row because no grant was
needed. Fresh Discovery afterward preserved completion, the native
`access_granted_until`, and the Artifact while updating `access_checked_at`.
The bounded 2026-10-03 Phase5B production CLI run completed work1 free Phase A
with 32 pages and an archive, then consumed exactly one Work Ticket for work4
source168. The native grant and work-scoped resource state were persisted, but
the run stopped at the first post-grant viewer readiness check before Phase C;
no retry or extra ticket was made. A production-hook cold navigation probe on
the already-granted episode observed 42 total native page areas and the first
render-ready body row at about 2 seconds. Fresh Discovery then refreshed the
exact native 72-hour expiry and advanced `access_checked_at`; Item168 remained
pending. That historical third-ticket run stopped before Phase C; the later
authorized fourth-ticket Work5 run verified the complete same-normal-CLI
grant-only → replan → direct crawl → packaging flow.

The subsequent non-consuming Phase5C recovery used the same isolated Catalog
and selected source168 as a direct active-grant candidate. It completed 38
native PNGs, reached `END`, packaged a verified ZIP, completed Item168, and
left the Work Ticket resource timestamp unchanged. Fresh Discovery preserved
the completed Item/Artifact and exact native expiry while advancing
`access_checked_at`. A fresh Work5 Discovery then validated 77 records (1
paid, 4 free, 72 quota). Its real BatchPlanner/resolver preflight selected
source75, verified native integer term 72, `isCharged=true`, canonical episode
and work identity, one exact visible/enabled ticket control, and a distinct
paid control. This was the read-only preflight before the authorized fourth
ticket; the subsequent normal Batch run completed the flow with source75.
Across four tickets, paid operations remained at zero.

A separate fresh work1/work4 preflight used the real `BatchPlanner` ordering:
one direct source and 159 deferred Work Ticket candidates. The resolver
skipped work1 because its resource was on cooldown and selected work4 source
168, episode `13933686331677356244` (the actual order-3 candidate). Its native
72-hour term, ready resource, canonical identity, exact visible/enabled locked
ticket control, and distinct paid control were verified read-only. The later
bounded Batch run used exactly one ticket for this candidate; paid operations
remained at zero.

The quota entry stage keeps one shared 10-second monotonic page-change budget
across pre-observation, control/click, native grant confirmation, and viewer
readiness; a separate 3-second read-only recovery window is used only after a
possibly dispatched click. Ordinary quota initialization also needs metadata
and viewer normalization, so the Runner-facing site-local budget is 35 seconds
including those stages and headroom, without changing the page-change default.

The 2026-10-03 read-only/controlled live evidence used work
`2550689798737278979` (episode `12207421983645809792`) and work
`2551460909766308490` (episode `2551460909766314566`). Each observed grant
lasted 72 hours via native `rental_end_at`; the Work Ticket resource became
ready again after 23 hours via its separate `chargedAt` signal. The first
work's successful click run lost its durable click-result file during an early
helper iteration; the later repair on work2 retained an atomic pre-state,
exact-control guard, `Viewer_PurchaseViaTicket` operation, post-state, refresh,
and new-page evidence. No paid operation was executed.

The final current-code direct live run used fresh isolated paths under
`output/comicdays_c2_final_*`. `CrawlerRunner` returned `END` with 32 native
PNG outputs. Manifest identities covered ordered unique area IDs 1 through 32;
all outputs were 1125x1600 and native. Before packaging, manifest/progress and
RunResult evidence were copied to
`output/comicdays_c2_final_evidence13/`. Normal packaging produced a 32-entry
ZIP with valid CRCs and matching manifest SHA256/dimensions; the crawl source
directory was removed after successful packaging.
The bounded normal Locator probe observed a 1008x624 viewport at DPR 1.5,
recorded center hit-testing and `trial=True` success for three forward
transitions, and retained its script as
`output/comicdays_forward_stability_probe_v2/probe.py`. A subsequent fresh
current-code crawl produced the same per-page SHA256 sequence as the earlier
C2/C3 archives; the crawl harness did not claim to enforce that viewport. The
earlier 1-second actionability failure remains an observed failure without a
definitive root-cause claim.

The final C3 E2E used the registered Discovery, Policy, and viewer Adapter
registries with the explicit experiment Catalog
`catalog_comicdays.sqlite` and an isolated watchlist under
`output/comicdays_c3_e2e11/`. Discovery completed with 79 sources: four
currently `free` and 75 `unknown`; the full feed count matched the observed
pagination total. The normal Batch plan selected the target episode as a
`direct` candidate with `consumes_quota=false` and no quota resource. The
registered `BatchExecutor` then persisted a successful `CrawlRun`, completed
the Item, and stored a present archive Artifact. It reached `END` with the
ordered body areas 1 through 32, native 1125x1600 PNGs, and a 32-entry ZIP
whose CRCs, SHA256 values, and dimensions matched the pre-package manifest.
Retained evidence is under `output/comicdays_c3_evidence11/`; no ticket,
point, coin, purchase, login, or next-episode action was used.
The isolated C3 watchlist deliberately supplied a stable label as the initial
Catalog Work title. The ZIP/archive title therefore follows the explicit
Catalog metadata, while the manifest `content_context.title` records the
verified Comic DAYS page title. This preserves the documented field-level
metadata precedence while retaining the observed series title in crawl output.

The production hook reports render readiness only after the latest full-base
generation has the observed four-column by four-row, non-overlapping integer
tile grid in both source and destination rectangles, preserving only the
narrow right edge.  An arriving subset or area sum/percentage is insufficient.
`wait_for_change` also requires slider/page-area progression and a fully ready
spread, so same-area repaint does not advance.  The
artificial Chromium integration covers rewind from a resumed slider, a
two-canvas RTL spread, one-side-unready loading, a safe outside spacer, unsafe
mutation fallback, ad exclusion, the `CrawlerRunner` path, `END`, and URL-change
`NEXT_CONTENT`.

Canvas width/height assignment and `clearRect` conservatively invalidate the
observed draw/readiness trace; a complete redraw is required.  A `clip()` call
is sticky native-unsafe across later full-base/tile generations until an actual
canvas width/height assignment or `CanvasRenderingContext2D.reset()` is observed;
`clearRect` does not clear the canvas clipping region.  Native source-body deadlines
remain active through `arrayBuffer()` and clear in `finally`; the browser
integration includes a headers-success/stalled-body case proving abort and
settlement.
Readiness also withholds a composition drawn under the persistent clip or a
fully suppressing supported-state case such as `globalAlpha=0`; a clip applied
only after an already complete composition remains eligible for whole-spread
fallback capture.

This note records the bounded C0 and C1 access/listing live observations for the target episode
`https://comic-days.com/episode/2550689798754939004`.  The probe was run on
2026-10-02 through the shared Crawler Chrome CDP endpoint using
`poc/comicdays_probe.py` and `poc/comicdays_c1_access_probe.py`; the redacted
reports are under `output/comicdays_probe_c0i/` and
`output/comicdays_c1_access_probe_v5/`.  Capture/terminal evidence is under
`output/comicdays_c1_capture_probe_v13/`.  It did not launch Chrome, select a profile, log in,
or click any ticket, point, coin, purchase, or next-episode control.

## Observed identity and listing

- The target is episode ID `2550689798754939004`, titled `第１話 かみあそび？`.
- The page exposes a series RSS link whose series ID is
  `2550689798737278979`; its corresponding Atom endpoint is
  `/atom/series/2550689798737278979`.
- The Atom response was HTTP 200 and contained 79 entries in latest-first
  order.  Each entry supplied a stable `comicdays:episode:<id>` identity,
  canonical `/episode/<id>` link, title, and updated timestamp.  The target
  appeared as the oldest observed entry in this feed.  The feed did not expose
  an access classification in the fields inspected.  `updated` is retained as
  feed metadata only; no publication-date meaning was established.
- The page also fetched `/api/viewer/readable_product_pagination_information`,
  which reported `is_support_ticket=true`, `per_page=50`,
  `readable_product_index=0`, and `readable_products_count=79`.
- The page issued `GET /atom/series/2550689798737278979?free_only=1`.
  This official free-only response was HTTP 200 and contained four entries in
  latest-first order: episode IDs `12207421983645809804` (第78話),
  `12207421983645809798` (第77話), `2550689798754939012` (第2話), and
  `2550689798754939004` (第1話).  The C1 parser was tested against an inline
  Atom shape containing a CDN thumbnail link followed by a canonical episode
  link; it selects the `/episode/<id>` link and verifies the ID relationship.
- The volume page showed the separate paid-book state `ログインして読む 795pt`.
  No login, point purchase, bulk purchase, ticket, or other access control was
  clicked.  The paid volume state must not be confused with the free-only
  episode listing.
- The free-only Atom response proves a positive site-native free-listing signal
  for the four current entries, including the target.  For this target work,
  the full Atom feed was validated against the observed readable count of 79;
  completeness/generalization for other works, expiry/rotation behavior, and
  whether a free episode can ever transition to a ticket gate remain
  unverified.

## Observed viewer

- The viewer root is `section.viewer.js-viewer` with
  `data-json-url="/episode/<id>.json"`; that JSON URL returned HTTP 400 in this
  guest probe and is not a usable listing/source contract.
- The viewer is horizontal RTL: `.content-inner.scroll-horizontal.js-horizontal-viewer`
  contains `.image-container.js-viewer-content.is-spread` and 36 page areas,
  followed by a back-matter `#viewer-colophon` area.
- The initial slider state was page 1 of 36.  Five canvas page images were
  initially mounted; each observed canvas was `1125x1600` and had class
  `page-image js-page-image`.
- The normal forward control is `.page-navigation-forward.js-slide-forward`.
  A bounded sequence of 17 forward clicks advanced the slider by two pages at
  a time from 1 through 35 without changing the episode URL.  As pages became
  active, the site loaded HTTP 200 JPEG responses from the CDN
  `/public/page/2/` route.  The first content canvas is area 1; initial area 0
  is an image-only prefetch/link slot.  At slider 35/36, areas 33 and 34 are
  image/blank terminal-side slots and area 35 is the visible
  `#viewer-colophon`; these are not additional manga canvases.
- The bounded terminal-resume probe in
  `output/comicdays_terminal_resume_probe_v8/report.json` confirmed free-feed
  membership, normal forward progression from slider 1 to the viewport-visible
  colophon at slider 35/36, and a visible backward control with no episode href
  or forbidden access label. One backward action moved to slider 33, and bounded
  backward actions returned to slider 1 with body canvases restored on the same
  episode URL. Before every forward/backward activation it revalidated free
  membership, the exact episode path, a single visible control, and the absence
  of an episode href or forbidden access label; unsafe or ambiguous cases stop
  with zero control clicks. Its DOM click fallback is used only for the
  validated terminal backward anchor because Playwright actionability was
  obstructed there. The probe did not click any episode link or access control.
- The page visibly included `作品チケット対象（ログインが必要です）` and the
  API reported ticket support.  C1 now has the official `free_only=1` episode
  signal, but no ticket action was invoked and no positive ticket-consumption
  or no-consumption transition was inferred.

## Source and capture evidence

The target uses HTTP 200 `image/jpeg` page responses, but the displayed
`canvas.page-image.js-page-image` has no usable network source.  The site
decodes each response into a `blob:` image and draws a full 1125x1600 base
followed by a 4x4 grid of 280x400 tiles.  The source/destination rectangles
were recorded from runtime `drawImage` calls; the observed tile placement
transposes the grid while the base preserves the untiled five-pixel edge.
The strict research extractor now requires one canvas identity, one latest full
base generation, all 16 exact tiles, matching source identity, identity
transform, source-over/alpha-one/no-filter state, integer equal-size
rectangles, and complete non-overlapping source/destination bijections.  It
rejects mixed/incomplete sequences, later incomplete redraws, extra
`drawImage` calls, and in-canvas tile mutation; only a draw proven wholly
outside the canvas with a safe identity state may be ignored as a spacer.
The C1 research hook did not monitor `clearRect`/`fillRect`; the production hook
now records destructive mutations and resets conservatively.  After selection, the probe fetched
the exact in-page `blob:` URL for
the selected visible canvas probe ID: first area 1 selected probe/canvas 1
(509,643 bytes, diagnostic MAE about 16.8), normal spread area 4 selected
probe/canvas 4 (479,795 bytes, MAE about 11.3), and final content area 32
selected probe/canvas 32 (520,567 bytes, MAE about 10.4).  MAE is diagnostic;
source selection is by exact visible probe ID, not lowest difference.

Native `toDataURL('image/png')` was attempted after selecting the first page,
normal spread, and final content canvas.  Both visible and retained
intermediate canvases raised a browser `SecurityError` because they are
tainted by cross-origin content.  Native pixel export is therefore unavailable
for this guest session.  First, normal-spread, and terminal references remain
visual diagnostic artifacts under `output/comicdays_c1_capture_probe_v13/`; no
page images or response bytes are repository fixtures.

The production hook caps a source body at 2,000,000 decimal bytes, retains at
most 256 image references, and keeps separate rolling 6,000-record draw and
mutation traces. Image references are not evicted; once that cap is exhausted,
a new image becomes an unsupported mutation. A source fetch failure,
oversized/invalid payload, or unsafe provenance falls back to whole-spread
locator capture only after the selected spread is positively render-ready.
Missing or incomplete readiness remains `LOADING` and ends at the bounded
timeout. Exhaustion behavior for unusually long runs and other works remains
unverified.
The latest unsafe mutation sequence is retained separately in a WeakMap keyed
by the canvas object, so rolling trace eviction cannot revive native capture.
An actual reset clears that marker; a complete later base/tile generation can
recover native capture.

The first and normal-spread references were visually inspected.  The final
candidate and post-forward state both remained slider 35/36 with the colophon
in the viewport.  A forced normal forward action returned without a slider or
URL change, so the colophon plus unchanged terminal state is the observed
positive end condition.  The `次の話を読む` colophon link was observed but
not clicked.

## Remaining verification and constraints

- Discovery and Policy classify Work Ticket candidates and active grants, and
  the Adapter implements the bounded `quota`/`work_ticket` entry path. The
  same-normal-CLI grant-only → replan → direct crawl → packaging flow was
  verified on Work5 with one ticket. Point, coin, purchase, rental, owned, and
  login flows remain unsupported; publication dates are not inferred from Atom
  `updated`.
- The research helper bounds page-side fetches with `AbortController`, wraps
  Playwright evaluation in a Python timeout, caps response-body inspection to
  first-party pagination/profile endpoints, and has focused tests proving a
  stalled page evaluation coroutine is cancelled.  The full probe also has a
  60-second outer deadline so cancellation reaches the existing page/session
  cleanup path.  The focused test does not claim BrowserSession or remote Page
  cleanup semantics.
- The capture probe has strict runtime provenance tests and reports 32 canvas
  content areas in canonical area order.  Area 0 is a volume/link ad, area 33
  is a questionnaire/premium ad, area 34 is blank, and area 35 is the
  colophon; they are excluded from content selection.  Exact blob-to-render
  association was proven for the representative first, middle, and final
  content areas in this viewer session; behavior across other works remains
  unverified.
- `NEXT_CONTENT` remains guarded by URL/context change; the observed colophon
  link is not followed by the production crawl. Loading/interstitial behavior
  outside the verified horizontal viewer and feed rotation/expiry behavior
  remain unverified. The earlier direct full live crawl is preserved in
  `output/comicdays_c2_live8_evidence/`; the current-code final evidence is in
  `output/comicdays_c2_final_evidence13/`.

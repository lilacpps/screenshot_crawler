# YanmagaWeb Site Adapter

**Implemented scope:** public-list Discovery (Phase 02), the observed
rendered-page Viewer/Capture path (Phase 03), and direct-only normal Batch
(Phase 04). CLI registrations cover Discovery, manual Crawl/Runner, Batch
adapter, and Batch policy. Existing Planner, Executor, packager, Artifact, and
Completed services are reused without a shared Core or Catalog change.

## Discovery

`YanmagaDiscoveryAdapter` is registered in the CLI Discovery registry under
`yanmaga`. It accepts a canonical HTTPS work URL on the exact `yanmaga.jp`
host with one work slug, and uses the public episode route
`/comics/<work-slug>/<32-lowercase-hex-episode-id>` as the Catalog web target.
The source identity is `<decoded-work-slug>:<episode-id>` so identical episode
IDs from different works cannot collide. Query strings, fragments, foreign
hosts, work redirects, canonical/`og:url` mismatches, foreign episode links,
and bounded scopes are rejected.

The adapter reads the rendered `.detailv2-episodes` listing and its
`.mod-episode-item` rows. Before yielding anything, it validates the work
identity and every row, expands the native `.mod-episode-more-button` by normal
Playwright click until the control disappears, and requires the rows to be
stable across repeated reads. The continuation must declare the observed
`もっと見る`, positive `data-limit`, `data-offset`, `data-sort="older"`, and
the matching work's `/episodes` path. Each expansion must add new, unique rows
at the declared native insertion position while preserving existing row order.
Expansion/row bounds and unsupported controls stop the run as incomplete.
Incomplete results are buffered before yield, so `DiscoveryService` cannot
partially reconcile a full Catalog run or mark prior sources unavailable.

The observed listing is oldest-first. The adapter emits its complete snapshot
latest-first for shared incremental Discovery, while `global_display_position`
comes from the observed full DOM order (oldest is 1). It does not infer or
repair positions from episode IDs, dates, or titles; bounded Discovery is
unsupported and inferred positions are disabled.

`free` requires all of these live row/page signals together:

- a single visible `.mod-episode-point--free` marker with exact text `無料`,
  exact class name, and computed `rgb(220, 0, 0)`;
- no `.by_wait` or `.js-modal` marker, no visible exact `初回無料` label, and no
  separate exact `無料` badge in the native `mod-episode-point*` badge family;
- at least one visible sign-in link to `/customers/sign-up` with a sign-in or
  registration label, no visible sign-out control, and an explicitly observed
  `ep.is_logged_in=false` value in an analytics request.

The anonymous-state observer is installed before page navigation. It reads
only that exact query field from requests to the observed
`analytics.google.com` and `www.google-analytics.com` hosts; it never records
the complete request URL. It accepts only main-frame requests while both the
frame and page still identify the requested work document; main-frame
navigation resets its evidence. More than 64 matching events invalidates the
current document's proof. Missing, `undefined`, malformed, conflicting, stale,
subframe-only, or overflowing telemetry and any missing sign-in proof leave
rows `unknown`. The observer is bounded and detached on every exit. A visible
exact `初回無料` label or a separate native `mod-episode-point*` `無料` badge
conflicts with the red marker. Repeated plain `無料` text in the row's detail or
price elements is not treated as another badge; a numeric point badge alone
does not conflict. Row attributes such as `data-is-free` and
`data-modal` are not authoritative: the sampled red row had
`data-is-free="false"` and `data-modal="registration"` but no `.js-modal`.
Orange `.by_wait`, point-only, and ambiguous rows remain `unknown`. Discovery
does not enter episode links or consume tickets, points, quota, or grants.

Every observed row is persisted as `available=True`; access uncertainty is
represented separately by `access_mode="unknown"`. No explicit free expiry
was observed, so `free_until=None` is sent on every refresh to clear stale
expiry values. `access_checked_at` and `last_seen_at` use the current aware UTC
time. The listing notice says daily free reading is limited, but its scope for
red rows is unknown; this adapter does not infer a no-cap rule. Any later
visible access/limit gate must be handled by Viewer/Batch preflight before
entry.

## Viewer and capture

`YanmagaAdapter` binds the configured `<decoded-work-slug>:<episode-id>` to the
original Catalog `source_url`, freshly repeats full public Discovery, and
enters the exact requested URL only when the current anonymous listing still
has one unambiguous red unconditional-free row. A complete same-work listing
that now proves a restricted state is reported as a lost free resource;
missing/contradictory anonymous evidence, identity drift, and malformed listing
state fail closed. `direct` and `auto` are supported; quota/resource strategies
are rejected. The current listing and reader are checked for a visible access
gate before accepting capture. This does not establish that the site has no
daily cap beyond the observed sample.

The public episode route normally redirects to
`/viewer/comics/<same-slug>/<same-episode-id>`. Live navigation also showed the
viewer route with one `cid` query field containing 20 ASCII alphanumeric
characters. The reader identity is always taken from the strict path; only no
query or this single observed query shape is accepted. Duplicate, additional,
malformed query data, credentials, fragments, or a different host/work/episode
are rejected. The opaque `cid` is not included in adapter-owned metadata, and
the original public `source_url` remains the Manifest source. Generic Core
failure diagnostics record the current page URL and can therefore contain this
opaque query value; those ignored diagnostic artifacts are sensitive and must
not be committed.

The current supported reader shape is the observed 36-page episode: a native
`1/36` counter and direct `#content-pN` body wrappers, with two consecutive
pages visible as a spread. The adapter uses a bounded normal-keyboard rewind to
page 1, validates complete unclipped wrappers containing the observed three
loaded overlapping image segments, then captures unseen native page IDs in
order as Playwright locator screenshots. Every segment must span the wrapper
from left to right within a 3 CSS-pixel rounding tolerance; the final segment
must end between 4 pixels above and 3 pixels below the wrapper bottom. This
matches measured rendered-layout overlap and rejects narrow or oversized
segments; it does not infer or reconstruct arbitrary crops. PNGs represent rendered locator
pixels (for the verified 2560×1800 viewport), not the original segment bytes.
Ephemeral SHA-256 fingerprints of current image sources bind stable snapshots
and before/after capture checks without retaining or exposing `blob:` URLs.
At completion, every body index must have been captured and the stable final
counter and native wrapper must match the requested episode. A single sibling
`#rental` card and its title must be fully inside the viewport, visible, and
center-owned by that element (or one of its descendants). The card must contain
either exactly one presented `次の話を読む` control and no signup control, or
exactly one presented `無料登録して読む` signup control at the same-origin
`/customers/sign-up` path and no valid-next control. That signup URL must use
HTTPS, have no credentials or fragment, and contain exactly one raw query field:
`forward=<32 lowercase hex episode ID>`. The token must identify the unique
immediately following episode row in the fresh, validated listing for the same
work, and the whitespace-normalized rental title must exactly match that row's
title. The token is compared only; it is never used to construct or navigate a
route, and the signup control is never activated. Hidden, off-screen, clipped,
obstructed, conflicting, duplicate, foreign, non-adjacent, title-mismatched, or
malformed preloaded-card signals fail closed. These presentation checks and the
final-body proof must remain stable across repeated snapshots within the bounded
page-change window. The reader next arrow is retained as diagnostic metadata
only because its visibility is transient during normal traversal. Unknown
layouts, missing halves, page/source drift, gates, or an unproven terminal state
fail closed.

A fresh reader can show the native full-screen `#menu` over its first page. The
adapter tolerates only the observed menu/header/controller/transparent-overlay
combination during initialization, advances one body page with the normal
keyboard control, then rewinds to page 1. Capture begins only after the menu is
proven `display:none` with zero dimensions and all eight perimeter hit tests
belong to each captured body wrapper. The verified spread wrappers overlap by
2 CSS px; perimeter samples use a 4 px inset so each sample lies outside that
measured sibling overlap. A separate overlay within the inset still fails
before saving the page; no CSS is changed to conceal reader controls.

## Batch

`YanmagaSitePolicy` admits only `site="yanmaga"`, `available=True`,
`access_mode="free"`, and a valid work-slug/32-hex-episode identity. It always
chooses `direct`, never consumes quota, and exposes no access-resource or
grant-only pass. `free_until=None` is allowed because current Discovery
explicitly refreshes public-free rows with no observed deadline; NULL alone
does not create a free classification. A valid aware future timestamp is
allowed, while expired/equal, malformed, or timezone-naive expiry values are
ineligible. The shared Planner parses free timestamps before calling Policy,
so a malformed persisted timestamp can fail the whole plan with
`BatchPlanningError`; this remains fail-closed and no Core behavior changed.

The normal Batch Executor creates a fresh Yanmaga adapter, which repeats the
same-work complete public Discovery and checks the exact target row before
opening its episode URL. A clearly observed loss of the red-free state is a
resource-unavailable skip; missing/conflicting identity or anonymous evidence
fails the candidate. Only a successful positive END and normal packaging flow
can create a ZIP/Artifact and mark the Catalog Item completed. Ticket, points,
quota, grant-only, purchase, and alternate resource passes are unsupported.

## Verification and limits

Synthetic Unit and browser-backed Discovery tests cover strict URL identity,
free marker/anonymous proof, initial-free badge conflicts, telemetry conflict,
subframe and overflow rejection, listener cleanup, hidden/foreign rows,
canonical mismatch, sort drift, unsupported paging, no-progress and failed
continuation requests, native expansion/order, full/repeat and
latest-first incremental Catalog behavior, access refresh, failed-full
preservation, completed Artifact retention, and duplicate pagination rows.
The real shared-CDP run on `ウサギとカメのゆる山歩` observed 13 unique rows after
native continuation exhaustion. Full Discovery completed 13 records;
incremental observed the five-item shared known streak. The current snapshot
classified five rows `free` and eight `unknown`, with global positions 1–13.
No episode was opened during this Phase 02 verification. This proves the
currently served listing snapshot, not the site's lifetime or unpublished
catalog.

The fresh Phase 03 shared-CDP `CrawlerRunner` run on the same red-free Chapter 1
sample returned `stop_state=end`, wrote 36 rendered PNG pages, and produced a
36-page Manifest. The page sequence includes native `content-p1` through
`content-p36`; spread parts are captured separately. Dimensions are
1266/1268×1800 at the verified viewport. Manifest `source_url` remains the
public episode URL and capture metadata identifies rendered locator screenshots
rather than source-native bytes. Independent image audit decoded all 36 files,
found 36 unique payload hashes, and visually checked pages 1, 18, 29, and 36 as
body pages without reader UI, ads, or the rental card. The run did not activate
the next-episode control or consume a ticket, point, quota, or grant.

The shared Discovery service currently uses a known-source streak of five;
Yanmaga does not override that shared behavior. The authority documents also
mention a default of two, so that shared discrepancy remains unchanged and is
recorded for follow-up without broadening this adapter.

The daily-limit applicability to the red-free state and broader Yanmaga reader
layouts remain unverified. Phase 03 passed independent review with BLOCKING 0,
including the bounded geometry hardening re-review. Phase 04 Batch
policy/registry and synthetic Batch-to-ZIP/Completed behavior passed
independent review with BLOCKING 0.

The first isolated Phase 05 normal-CLI attempt selected Chapter 11 as the first
eligible candidate, captured 20 body pages, and failed closed at the chapter
boundary because its next episode is a registration-only signup card. It
created no ZIP or successful Artifact and did not mark the Catalog Item
Completed. The attempt also exposed first-page reader chrome on a fresh viewer.
A corrected official-menu roundtrip produced a clean first-page capture. A
subsequent retry failed before capture because a 1 px perimeter sample on p3
landed on the adjacent validated p2 wrapper at their measured 2 px overlap;
the same points 4 px inward belonged to p3. The adapter now uses the measured
4 px inset; the geometry fix passed independent review.

The next retry failed after 20 body PNGs because the signup URL's `forward`
query was not supported yet. Read-only comparison showed its single 32-lowercase-
hex value matched the unique immediately following row in the fresh same-work
listing, and the visible rental title matched that row's normalized title. The
CTA was not activated. The adapter now accepts only that strict token-to-row
binding; it does not interpret the token as a URL or navigate to the CTA.

The final independent ordinary CLI E2E passed for the observed Chapter 11
candidate. Full Discovery exhausted 13 rows, incremental observed five known
rows, and the initial plan contained five `free/direct` candidates and eight
`unknown` skips with quota 0. Normal Planner order selected Item/Source 2
(`aac67662e0d47437726ee7034126a8ea`). `batch run --limit 1` exited 0 with
`stop_reason=end`; the successful CrawlRun recorded 20 pages. The ZIP contains
the 20 ordered Manifest pages, passes CRC validation, matches every Manifest
payload fingerprint, and has 20 decodable PNGs with 20 distinct hashes. Eleven
images are 1266×1800 and nine are 1268×1800. Tester and Root independently
audited the archive; first/middle/last samples show body pages without reader
chrome. The Artifact is present and matches the archive; Item 2 is completed.
Repeated full/incremental Discovery retained all 13 Source/Item IDs and
positions, `completed_at`, and the Artifact; the final plan skips the completed
Item. No ticket, point, grant, login, purchase, quota operation, signup CTA, or
next-episode action was used.

This was a dedicated isolated Watchlist/Catalog/archive and capture-output run. The Watchlist
explicitly supplied label `yanmaga-usagi`, and the archive path used fallback
genre `小説`; those output metadata values do not assert the site's displayed
work title. The final run's archive SHA-256 is
`e0f3fc218937699e957c5854633f70291d22069ca83284235f13029291d5cc88` and its
size is 53,755,787 bytes. Detailed sanitized evidence is in the ignored
`output/yanmaga_experiment/phase05-independent-token/qa/tester-report.md`.

The unique task metrics file was emitted to the CLI's default `output/metrics`
location and moved by exact path into isolated QA; the Watchlist, Catalog,
archive, and capture output used dedicated paths throughout. The final independent
Reviewer accepted the implementation and documentation with BLOCKING 0; root
commit/push handoff remains. The CLI E2E verifies one currently free candidate
and the observed reader layout only. The site's daily-free-limit applicability
remains unknown, missing or conflicting anonymous telemetry remains `unknown`,
and other layouts and original image bytes are unsupported. The captured files
are rendered locator PNG pixels (1266/1268×1800), not source-native image bytes.

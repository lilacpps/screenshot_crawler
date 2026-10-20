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

### Captured pixels and source attribution

No complete page image was observed in the upstream responses. The matching
upstream JPEG is a shuffled tile atlas; the viewer draws those tiles into three
canvas segments and encodes each segment as JPEG at quality 0.9 before creating
the body-image Blob. The saved page is therefore not an unchanged original
server image or the original segment bytes.

For the verified 36-page reader layout, the observer runs only in the top-level
Yanmaga viewer document and copies RGBA pixels only immediately before the
observed JPEG encoding call. It associates a copy with a visible segment only
when the generated JPEG payload, the `Blob` bytes, and the `blob:` image source
have one unique exact byte match. Ambiguous matches, missing or changed sources,
hook conflicts, budget overflow, non-opaque pixels, or unverified styles
reject the native group. The hook preserves the viewer's original call,
arguments, return value, and exceptions and is removed on adapter cleanup.

The logical `.pt-img` box and first-party metadata establish a 1125×1600 page
at 1.125 CSS scale. The verified nested DOM is one `.pt-img` containing three
absolute clipped segment hosts, each with one image. Their source images are
1127×536, 1127×536, and 1127×538 at logical Y offsets 0, 532, and 1064. They
overlap in DOM paint order, and the outer viewer may add a 0 or 2 CSS px right
gutter. The adapter composites the verified pre-JPEG pixels in that order and
crops to the logical 1125×1600 page, excluding the viewer gutter. It permits
only the observed normal inner/host/image styles and pure horizontal wrapper
translation. The observed host `::after` is accepted only with an exact empty,
fully transparent, non-painting computed style; other generated paint is
rejected. Page/host/image geometry, source bindings, and computed-style proof
are rechecked before accepting the page and atomically across the captured
spread.

The page is encoded as single-frame lossless WebP (`VP8L`). The encoder checks
opaque pixels and verifies that decoding the WebP reproduces the composed RGBA
pixels exactly. Successful captures use `image/webp` / `.webp`, dimensions
1125×1600, and metadata distinguishes reconstructed pre-JPEG viewer pixels
from original bytes (`source_native_bytes_used=false`,
`source_native_pixels_used=true`). If any page in a visible capture group fails
proof or encoding, that group uses the existing rendered locator PNG fallback
with an explicit reason. The fallback is 1266/1268×1800 for the verified
2560×1800 viewport; it is not described as source-native bytes.

The supported reader shape is the observed 36-page episode: a native `1/36`
counter and direct `#content-pN` body wrappers, with two consecutive pages
visible as a spread. The adapter uses a bounded normal-keyboard rewind to page
1 and captures unseen native page IDs in order. Every segment must span the
wrapper from left to right within a 3 CSS-pixel rounding tolerance; the final
segment must end between 4 pixels above and 3 pixels below the wrapper bottom.
This matches measured rendered-layout overlap and rejects narrow or oversized
segments; it does not infer arbitrary crops.

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

The first Phase 03 shared-CDP run used rendered locator PNGs; that run is now
historical evidence of the safe fallback path. The N2 source-native-pixel
follow-up on the same red-free Chapter 1 completed with `stop_state=end`, a
36-page Manifest, and 36 `image/webp` files at 1125×1600, all using
`native_pre_jpeg_lossless_webp` with no fallback. An independent offline audit
found 36 distinct hashes, matched every file to its Manifest fingerprint,
decoded every file as one VP8L frame, and confirmed fully opaque pixels.
Pages 1, 18, and 36 were visually compared with the earlier rendered controls:
they contain the same full body page without reader UI, ads, or rental overlay;
this visual comparison is not a byte-identity claim. The WebP encoder itself
verifies exact RGBA round-trip equality for each accepted capture. Manifest
`source_url` remains the public episode URL. No next-episode control or paid
resource was activated. The current normal Chapter 11 native-WebP Batch/ZIP E2E
passed below; independent all-20-page RGBA reference equality also passed.

The observer retains copied source pixels under a fixed 256 MiB
(`268,435,456` byte) raw-pixel cap. This is not a preallocation and does not
measure total JavaScript heap or Chrome RSS. Other bounds remain 192 total
candidates, 48 pending candidates/tasks, 32 MiB encoded payload characters,
192 URL bindings, and 1 MiB per segment. No compression occurs in viewer hooks.
The cap covers the known 36-page profile's 108 source segments totaling
261,283,680 bytes (about 249.2 MiB), with finite remaining capacity. It is not
a claim about other layouts or whole-process memory.

A browser-backed eager-preload test binds 60 exact canvas/Blob candidates
before capture, retains 145,157,600 bytes, captures page 1 as native WebP, and
checks one-page release accounting. A separate numeric-boundary case verifies
acceptance exactly at the limit and rejection of the next segment before pixel
copy. The current Unit + browser Integration selection passed **76 tests**,
**0 skipped**, with 23 existing pytest-asyncio/Python 3.14 deprecation warnings
(209.57 seconds). Full `ruff check src tests` passed. Both the N2 capture and N4
cap changes have independent Reviewer BLOCKING 0. The earlier Chapter 11 Batch
ZIP result was for the historical rendered-PNG path; the current native-WebP
packaging result is recorded below.

A bounded isolated normal Chapter 11 CLI run with `--max-pages 1` observed 21
exact-bound candidates / 50,805,160 raw bytes before its first capture,
5,807,040 encoded characters, no in-flight reads or observer errors, and a
native 1125×1600 WebP for page 1. Releasing that page reduced retained pixels
to 43,547,280 bytes. The command intentionally stopped at the one-page limit
and exited 1; it did not reach END, ZIP, Artifact, or Completed. That diagnostic
did not establish page IDs for every other retained candidate. A later normal
Chapter 11 native-WebP Batch/ZIP E2E passed; the one-page diagnostic itself did
not reach END or packaging.

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

The current independent ordinary CLI E2E passed for the observed Chapter 11
candidate using the N2 native-WebP capture path. Full Discovery returned 13,
incremental returned five known rows, and the first plan contained five
`free/direct` candidates, eight `unknown` skips, and quota 0. Normal Planner
order selected Item/Source 2 (`aac67662e0d47437726ee7034126a8ea`).
`batch run --limit 1` exited 0 with `stop_reason=end` and a successful 20-page
CrawlRun. All 20 ordered Manifest entries are native-pixel 1125×1600 lossless
WebP (`VP8L`), with distinct hashes and no fallback. The ZIP contains exactly
those ordered Manifest pages, passes CRC, and every payload matches its
Manifest fingerprint. Archive SHA-256 is
`8d32c1ba953e2093e4c42945ce8bd1c2ff940884d2c343f6b68dc5ba6d4232b5`, size
18,830,115 bytes; Manifest snapshot SHA-256 is
`e4d0bdec2c96606023a10c085dd100d8c952b5a598f9e6343f50ea7da2d68daa`. Tester
and Root independently audited all 20 members. Tester visually checked
first/middle/last body pages; Root's all-page contact sheet showed body pages
without reader UI or terminal-card contamination. The Artifact is present and
matches the archive; Item 2 is completed. Full/incremental rediscovery
preserved Source/Item IDs, positions, completion time, and Artifact; the final
plan had four direct, eight unknown, and one completed skip. No ticket, point,
grant, login, purchase, quota, signup, or next-episode action occurred.

The run is isolated under `output/yanmaga_experiment/nv-e2e3/q/primary/`.
The Watchlist explicitly supplied label `yanmaga-usagi`; this is not an
assertion about the site's displayed work title. Detailed independent audits
are `archive-audit.json` and `root-independent-audit.json` in that folder.
The prior Chapter 11 E2E under `phase05-independent-token/` remains historical
evidence for the rendered-PNG path.

The unique task metrics file was emitted to the CLI's default `output/metrics`
location and moved by exact path into isolated QA; the Watchlist, Catalog,
archive, and capture output used dedicated paths throughout. The Phase 05
independent Reviewer accepted the implementation and documentation with
BLOCKING 0; the N2 capture and N4 cap reviews also passed with BLOCKING 0. The
implementation commit recorded in the progress ledger predates the N2/N4
follow-ups. The CLI E2E verifies one currently free candidate and the observed
reader layout only. The site's daily-free-limit applicability remains unknown,
missing or conflicting anonymous telemetry remains `unknown`, and other
layouts remain unsupported. A complete original server page response was not
observed in these probes. The current verified layout reconstructs pre-JPEG
viewer pixels and emits lossless WebP; `source_native_bytes_used` remains
false. The rendered locator PNG (1266/1268×1800) is retained only as the
fail-closed fallback. Independent reference capture completed 60 segments for the same 20-page Chapter 11 run without overflow, send failures, or scan errors. Pillow-composited RGBA references exactly match the decoded ZIP WebP pixels on all 20 pages; Root's independent result is recorded at `output/yanmaga_experiment/nv-e2e3/q/primary/root-independent-pixel-equality.json`. The earlier zero-snapshot control was a QA observer initialization issue, and the QA-only four-contender lock fixture passed. No production code changed for that QA harness correction.

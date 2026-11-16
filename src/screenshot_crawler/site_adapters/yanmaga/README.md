# YanmagaWeb Site Adapter

**Implemented scope:** public-list Discovery, the observed rendered-page
Viewer/Capture path, and normal Batch. Batch supports public-free and
first-free direct access, trusted existing grants, and the bounded Yanmaga
`work_ticket` resource path described below. CLI registrations cover
Discovery, manual Crawl/Runner, Batch adapter, and Batch policy. Existing
Planner, Executor, packager, Artifact, and Completed services are reused.
Shared Core exposes only site-neutral access-grant and entry-only hooks.

## Stage 02 current state (2026-11-16; C8 verified, Stage 02 PASS with independent BLOCKING 0)

The C sort and canonical/og corrections and the BODY pre-live review passed
independent review with BLOCKING 0. A metadata-only probe verified the Rental
History helper for the already opened `episode-ff-probe-01`: H=17 at
2026-11-15T08:11:29.019643Z produced the conservative
`site_countdown_lower_bound` 2026-11-16T00:11:24.019643Z from GET start plus
(H - 1) hours minus 5 seconds. This is a lower bound, not an absolute expiry.
That probe used zero rights. A separate metadata-only preparation confirmed a
one-candidate direct plan for `episode-ff-capture-01`, position 31, with zero
rights; it is a different episode from the prior position-32 Research release.
The preparation Catalog contained 1 Work, 57 Items, 57 Sources, and 57
SourceTargets. The selected target IDs were Work 1 / Item 27 / Source 27 /
Target 27; these are identifiers, not row totals.

C1 used one additional first-free entry for position 31. The exact Viewer and
first-free completion notice were confirmed, and the finite grant was saved
synchronously before pixel-readiness work. After readiness and rewind, an
intentional `capture_page` failure occurred before the first content page was
saved. The Item remained pending and no image Artifact was created. C2 then
retried without rerunning the external Catalog DiscoveryService; the Adapter
performed its fresh internal listing preflight and used the same future-aware
saved grant. Its grant value remained unchanged, with no new first-free use.
Both C1 and C2 used one Source GET and one Viewer GET, with no other episode or
first-party non-GET request. Research plus C1 make two confirmed first-free
uses total; C2 used zero additional rights, and the additional first-free
allowance is exhausted. The C1/C2 Catalog audit found 1 Work, 57 Items, 57
Sources, 57 SourceTargets, 2 CrawlRuns, 0 Artifacts, and 0 Work-resource rows;
the target IDs remained Work 1 / Item 27 / Source 27 / Target 27.
Ticket, point, coin, and paid actions remain zero. The stored bound represents a
native countdown lower bound, not the site's actual expiry or a fixed 24-hour
lifetime.

Post-C2 metadata-only v4 full and incremental Discovery completed with
zero rights and zero Source/Viewer/first-party non-GET/fatal requests. The
report is `output/yanmaga_access_experiment/stage02/metadata-only-v4-refresh-report.json`
(SHA-256 `0b62fbb74622ef25e30f4f38d64ebc0c30d112365b894a56cc99dc29b85a100b`).
Both snapshots had 57 rows and matching target position/identity; full was
complete/exhausted with 57 observed rows, while incremental had
complete=null/known_streak with five observed rows and did not yield the
target. Fresh history plus the trusted grant preserved its Catalog free
mode and future expiry; flags were reapplied only to the target after each
run. Root's independent audit confirmed the pending Item, unchanged grant,
zero Artifact/quota state, and one direct non-quota plan. No capture was
attempted. The v3 QA report remains unresolved because its raw Discovery result was not
saved; this does not change the later successful v4 metadata refresh. The Stage
02 final gate is PASS; the independent Reviewer reported BLOCKING 0 after Root
completed documentation synchronization.

The adapter still permits at most one normal public-episode GET for a fresh,
exact authenticated first-free candidate, after rechecking the current work
identity, visible login evidence, unique visible marker, row, and queryless
source href. The observed public episode route can grant access automatically.
Before any pixel-readiness wait, the adapter requires the same exact Viewer
episode, a unique page counter and visible body wrapper, no known access gate,
the exact first-free completion notice `無料レンタルが完了しました`, and a
fresh finite same-target Rental History proof. It persists an immutable
site-neutral grant synchronously through Batch
before capture readiness. Unknown access, missing or stale expiry, route drift,
or any gate stops without another entry. Existing grants require fresh active
same-target countdown evidence and a still-future stored Catalog bound.

C1/C2 verified grant persistence through intentional capture-hook failures
after readiness/rewind but before the first saved content page. Post-C2
full/incremental metadata Discovery and the one-candidate direct plan were
independently audited. C3 stopped before Source entry on an incorrect QA
request budget. C4 ran once and failed in the normal CLI after one Source
and one Viewer request; no genuine Manifest page progress or ZIP was saved.
The C4 failure does not establish a site failure. Its diagnostics are
preserved. C5 ran once and failed before content capture because the body did
not stabilize. The Item remained pending, the existing grant was preserved,
and no Artifact was created. C6 used the existing grant and verified one Source
302 to exact Viewer 200 chain and one content-info XHR, but the body still did
not stabilize. Its run failed with page_count null; the Item stayed pending,
the grant stayed unchanged, and no Artifact was created. No additional right
was used. C7 then saved 13 native WebP pages and reached reader counter 14/14,
but did not establish END or create an Artifact. Root traced the failure to the
broad modal-class gate matching the nonsemantic inline rental card under the
unique `#rental` auxiliary. The adapter now exempts only the observed static
class/id shapes inside `#rental`; semantic dialogs and existing body ownership,
viewport, menu, pixel, page-count, and positive-END checks remain in force. The
synthetic browser fixture verifies the inline-card final page reaches END and
that a semantic dialog within the same card still stops. The adapter Unit file
passed 10 tests, the Yanmaga adapter browser file passed 106 tests, and the
independent Reviewer reported 8 pass / 0 skip and BLOCKING 0. C8 completed the same target through the ordinary CLI using the existing
future-aware grant. The run succeeded with 14 pages and positive END; Item 27
completed and one Artifact was present. The genuine 14-page Manifest matches
the ZIP exactly. Root's artifact audit passed, and an independent visual check
confirmed the first, middle, and final pages belong to chapter 27, ending with
`第27話 完`. The ZIP has 13 native WebP pages and one safe PNG fallback
for the last page (`segment_source_not_exactly_bound`); no format fallback was
changed. C8 used one Source GET and one Viewer GET, with zero other-episode,
non-GET, or observer-error events and no additional first-free use. The saved
grant stayed unchanged and future-aware; quota and work-resource state stayed
empty.

The passive watcher ended before writing its auxiliary watch-result marker, so
its standard audit command could not run. Root independently audited the
genuine Manifest and ZIP successfully. No marker was fabricated and no retry
was made. Post-capture metadata checks then ran against the completed target. Full
Discovery exited 0 with 57 observed/known rows, `complete=true`, and
`stopped_reason=exhausted`; the before/after Catalog comparison passed. The
incremental CLI also exited 0 without error and observed 5 known rows, 0 new,
then stopped with `known_streak`. Its `complete` value is null, so incremental
completion was not evaluated and is not claimed. The incremental report did not
install the Source/Viewer request observer; those request counts are unknown.
The Catalog retained Source 27 as the only enabled source, Source 28 disabled,
Item 27 completed, the existing Artifact and grant unchanged, and quota state
zero. The post-full plan contained zero candidates because Item 27 was already
completed. The bounded work-intro popup observation found a visible
`DIV.mod-modal-close.js-modal-close`, but its one click did not confirm popup
disappearance; the listing remained at 57 rows with no More control, so no
further popup action was attempted. The ignored QA popup helper, including this
observed DIV shape, has only passed compile checks and has not been live tested.
The Stage 02 final gate is PASS. Stage 03 is accepted with qualified composite live evidence and independent BLOCKING 0: wait classification, work-scoped Policy, automatic ticket persistence, grant-only, same-grant capture, positive END, ZIP, and Completed were verified across the bounded runs. Two ticket uses were recorded: dual chapter 29 from frozen exact-history evidence and novel chapter 10 through automatic grant-only persistence. A5 completed the dual chapter-29 same-grant capture with 14 pages and positive END; Root audited the genuine Manifest and ZIP. The grant and work cooldown remained unchanged and A5 used no ticket POST. Post-capture full/incremental Discovery completed and preserved the target, grant, and artifacts with zero Source, Viewer, or native rental POST activity. Stage 04 A6 existing-grant capture on work-novel chapter 10 and A7 public-free capture on work-dual chapter 51 both completed with positive END, ZIP, and Completed; neither changed grant/quota state or used a new right. Independent Tester audits and 261 affected tests passed (0 skipped, 305 deselected). The final Reviewer gate passed with independent BLOCKING 0; the full-suite run was controlled-stopped and is not a full pass.

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

The adapter normalizes the supported listing to oldest-first before emitting
its complete snapshot latest-first for shared incremental Discovery, while
`global_display_position`
comes from the observed full DOM order (oldest is 1). It does not infer or
repair positions from episode IDs, dates, or titles; bounded Discovery is
unsupported and inferred positions are disabled.

The current listing classification recognizes verified public-free and
first-free rows as `access_mode="free"`, and recognizes the wait marker as
`access_mode="quota"` when authenticated exact-row proof is present. Before
ticket use, the Adapter additionally requires a fresh work-level charged
state. Rows remain `available=True`; other or unverified states start as
`unknown`.

On an authenticated complete listing, Discovery also makes one bounded
same-work Rental History lookup for raw-unknown rows and same-work sources with
trusted grants. An exact active Rental History card with a fresh finite native
countdown can promote a raw-unknown row to `quota` and set the observed grant
expiry. This recovers previously absent or unknown Catalog sources without
inferring a consumption time or cooldown. Active evidence without a finite
bound, missing or duplicate cards, and identity mismatches do not promote a
row; `owned` rows are never imported. A previously trusted future grant keeps
its existing mode and expiry when active history confirms it; Discovery does
not extend that expiry. The lookup is metadata-only and does not open an
episode or invoke an access control.

On 2026-11-16, an isolated validation and the authorized normal-Catalog full
Discovery both recovered the previously `unknown` work-dual chapters 26, 27,
and 29 as `quota` with finite observed bounds. The normal run preserved their
Source/Item identities and states, Artifacts, acquisition flags, and work
state; its direct plan consumed no resource. Source/Viewer/rental POST counts
were zero. The evidence report is
`output/yanmaga_access_experiment/followup-active/normal-repair-v1/report.json`.
The focused unit/browser and existing-grant checks passed 96 tests, with 0
skips and 126 deselected; the full suite was not rerun.

A public-free row requires one visible `.mod-episode-point--free` element with
exact text `無料`, the exact class name, and computed color
`rgb(220, 0, 0)`. It must have no `.by_wait` or `.js-modal` marker, no exact
`初回無料` label, and no separate exact `無料` badge in
the native `mod-episode-point*` family. This proof is accepted only on a
verified anonymous or authenticated work document.

A first-free row requires a verified authenticated work document, exactly one
`.mod-episode-point--free` marker in the row, exactly one first-free marker,
exact text `初回無料`, and the exact class-token set
`{"mod-episode-point--free", "by_first_time"}`. Wait/modal markers, a public-red
marker, or another conflicting native free badge leave it `unknown`. A numeric
normal point badge may coexist, as observed in the sample. The classifier also
requires the total free-marker count to be exactly one, so any extra or unknown
free badge fails closed.

Anonymous proof still requires a visible sign-in link, no sign-out or visible
`/mypage` link, current work-document identity, and explicit consistent
`ep.is_logged_in=false` evidence. Positive authenticated proof uses the
observed visible same-origin `/mypage` link with exact path and no credentials,
query, or fragment; no sign-in link; current work-document identity; and no
telemetry overflow. Analytics is supporting evidence only: it may be absent,
but any observed state must be `true`. The observer remains main-frame bound,
resets on navigation, reads only the exact login field, and is detached on all
exit paths.

The Stage 01 `work-dual` snapshot was a historical checkpoint: two first-free
rows were visible in the initial viewport, and its complete 57-row listing
contained 27 first-free rows, 8 public-free rows, and 22 then-unclassified
rows. The wait marker was positively identified and added to the current
classifier in Stage 03; later authenticated Rental History recovery is
described above. This does not establish paid-only or daily-limit behavior. A separate
temporary empty-context comparison saw no `/mypage` link, two sign-in links,
and false login telemetry. No episode or access CTA was opened in Stage 01. A
read-only request observer found analytics POSTs to third-party hosts only and
no first-party Yanmaga POST during that sampled listing read.

All listed rows remain `available=True`. Yanmaga sends `free_until=None` on
each refresh because no explicit free expiry was observed; the existing Catalog
refresh contract clears stale free expiry. No grant is observed, so
`access_granted_until_observed=False` preserves an existing Catalog grant; an
explicitly observed null is authoritative and clears it. Stage 01 had no live
grant evidence. The daily-limit notice scope for red rows remains unknown.
`access_checked_at` and `last_seen_at` use the current aware UTC time.

During Stage 01, the capture adapter remained anonymous-only. Stage 02 adds
the bounded authenticated first-free entry path described above. C8 verified
the existing-grant production capture flow for the selected target; a complete
fresh-first-free capture remains unverified. Missing/contradictory evidence, unknown markers, and unsupported
row identity remain fail-closed. The list expansion contract remains strict:
positive `data-limit`, native offset/sort/path, unique inserted rows, and stable
ordering are required. The sample wife listing's missing-limit pagination
shape is deliberately unsupported in this stage. Discovery never opens
an episode to classify access. Row attributes such as `data-is-free` and
`data-modal` are not authoritative: the sampled first-free rows had
`data-is-free="false"` and `data-modal="registration"` without `.js-modal`.

## Stage 02 Discovery sort identity correction (accepted sub-gate)

The initial C sort implementation expected canonical and og:url to stay on the
unqueried work URL after an oldest-first UI navigation. A bounded read-only
production Discovery diagnostic found that the actual sorted work document,
canonical, and og:url all used the same exact-work `?sort=older` shape. Discovery
therefore stopped with the allowlisted reason `redirected_to_different_work_or_route`.
The diagnostic confirmed one base GET and one oldest-sort GET (both HTTP 200),
then no More click attempt, no continuation XHR, no metadata helper call, and no
Source or Viewer route. It used zero additional rights; no first-party non-GET
was observed, and 30 foreign non-GET attempts were aborted.

Discovery now accepts either a matching unqueried canonical/og:url pair, or a
matching exact `?sort=older` pair only when the same inspected document has the
exact same-work older URL and the unique observed oldest-first control is active.
Mixed pairs, extra or duplicate query fields, fragments, userinfo, foreign or duplicate
identity tags, and sorted identity without that UI proof fail closed. Public
input work URLs, episode URLs, and Source targets remain queryless. Legacy pages
without sort controls retain their existing base-URL contract.

A separate earlier read-only Rental History check observed the exact target
card with H=22 and matched it through one same-origin no-store HTML GET (HTTP
200, 33,971 bytes, Age absent, private max-age=0 must-revalidate). The request
started at 2026-11-15 03:10:49.892907 UTC. The then-current diagnostic
recorded 2026-11-16 00:10:49.892907 UTC (GET start plus 21 hours) as its
countdown-derived result; it was not an absolute site expiry. The current
runtime rule is more conservative: `site_countdown_lower_bound` is GET start
plus (H - 1) hours minus 5 seconds, yielding 2026-11-16 00:10:44.892907 UTC
(09:10:44.892907 JST) for H=22. This is also a lower bound, not an absolute
expiry. This countdown observation predates later Lead-authorized
metadata-only listing probes. The latest bounded probe used zero
additional rights and zero Source/Viewer requests, called the production
helper once, and confirmed H=17 with a finite conservative lower bound. This
verifies the helper on the exact already-open target only; it does not verify
production capture or retry recovery.

The production failure document exposed one exact More control with offset 5,
limit 47, older sort, and same-work episodes path. That control was not clicked
in this diagnostic. Synthetic browser fixtures cover the exact sorted identity
pair, the compatible base pair, mixed and unknown query forms, duplicate query
tags, fragments, duplicate canonical/og tags, and sorted identity without a
matching current document or UI proof. Discovery unit tests passed 31 cases;
the Yanmaga Discovery browser file passed 49 cases with 0 skips. The canonical/og follow-up was accepted with independent BLOCKING 0. Stage 02
capture and immediate grant persistence remain incomplete.

## Viewer and capture

`YanmagaAdapter` binds the configured `<decoded-work-slug>:<episode-id>` to
the original Catalog `source_url` and freshly validates the exact requested
source. The normal public-free path still requires the exact visible red-free
marker. Stage 02 also permits one public-episode GET for a fresh authenticated
exact first-free row; that route may grant access automatically, and the
adapter requires the exact Viewer, the exact first-free notice
`無料レンタルが完了しました`, and finite target-bound Rental History evidence
before synchronously saving the grant. A trusted
stored grant can authorize direct retry only when its Catalog expiry is still
future and a fresh same-target countdown is active. All other unknown,
conflicting, expired, or unsupported access states fail closed. For wait-free
rows, the adapter also requires the exact image marker, charged signal, and
verified target absence from Rental History; it validates the observed
same-episode modal and POST form before one normal click. Its exact completion
notice is `レンタルが完了しました`; it does not accept the first-free notice
as a substitute. Novel chapter 10 grant-only verified the exact post-click
Viewer, notice, active history, and automatic persistence. Dual chapter 29 Run
10 required later frozen-history recovery; its same-grant capture succeeded in
a separate run. `direct`, `auto`, and the bounded `work_ticket` strategy are
supported. This does not establish the
site's daily-cap scope beyond the observed samples.

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
only because its visibility is transient during normal traversal. If the card
has no next/read or signup control, one exact visible
`.aspect-ratio-2-27.mt-wait > div.episode-modal-wait.content` block can be the
terminal signal when it contains the observed clock image followed by one span
matching `あとH:MMで無料` (H 0–23, minutes 00–59). Its title must match the unique
immediate next row in the fresh listing, and that row must carry the exact wait
marker without a conflicting free marker. The timer is not activated. All
existing route, captured-body, ownership, access-gate, and stable-END checks
still apply. Unknown layouts, missing halves, page/source drift, gates, or an
unproven terminal state fail closed.

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

`YanmagaSitePolicy` admits a valid available `free` source directly. A
`quota` or `paid` source is also direct only when Catalog has a valid aware
future confirmed grant. Without one, a validated wait-free `quota` source may
use one work-scoped `work_ticket` pass with after-observed-consumption
persistence. Grant-only supports that resource and excludes ordinary `free`
and first-free rows. Invalid or expired grants do not become direct.
`free_until=None` is allowed because current Discovery
explicitly refreshes public-free rows with no observed deadline; NULL alone
does not create a free classification. A valid aware future timestamp is
allowed, while expired/equal, malformed, or timezone-naive expiry values are
ineligible. The shared Planner parses free timestamps before calling Policy,
so a malformed persisted timestamp can fail the whole plan with
`BatchPlanningError`; the shared Planner keeps its existing fail-closed behavior.

The normal Batch Executor creates a fresh Yanmaga adapter and validates the
exact target before opening its public episode URL. Public-free, first-free,
and trusted-grant checks remain in place. The wait-ticket path requires an
authenticated exact row, one observed wait image marker, visible charged state,
verified target absence from the complete Rental History collection, and the
observed exact modal form. The POST is initiated only by one normal click; no
resource fallback is used. The source modal and pre-click history shapes were
observed read-only on `work-dual` chapter 29 and `work-novel` chapter 10. The
Root later verified the exact native ticket notice, Viewer, and active history from retained evidence; the production run itself did not latch or persist the use.
Wait countdown parsing accepts the observed exact `残りH時間` or `残りD日`
field only when the explicit wait/trusted-history bound permits it (up to 72
hours); ordinary first-free history remains capped at 23 hours and does not
accept day fields. A day countdown of D>=2 yields the conservative
`site_day_countdown_lower_bound` at observation start plus (D-1) days minus 5
seconds; D=1 proves active access but gives no finite expiry. Hour and day
evidence remain distinct, and no fixed grant duration is synthesized.
Entry-only writes no page Manifest or Progress state, captures no image,
creates no ZIP, and leaves the Item pending; failure diagnostics are
metadata-only. Normal capture, positive END, and packaging checks remain strict.
Yanmaga's `prepare_entry_only_page()` skips its capture-only native pixel
observer on the fresh Batch-owned Page; no general Page-reuse guarantee is
added for a Page that already has that observer.

### Stage 03 live and test status

Read-only Discovery observed the image-only wait marker on 22 of 57 `work-dual`
rows and 29 of 37 `work-novel` rows, plus the exact charged label. Read-only
Source GETs for dual chapter 29 and novel chapter 10 showed the exact modal,
three-day period, and episode-bound `/by_free_waits` form. Run 9 stopped before
submit because the client-rendered modal was not yet visible. Run 10 emitted one
native ticket POST, but the then-current production postcondition did not latch
or persist the use. Root later verified the exact native notice, Viewer, and
active history from retained evidence and applied one frozen history observation
to Source 25/work state. Its bound is anchored at observation time, not a claim
about the exact POST timestamp.

Novel chapter 10 grant-only then succeeded with one native wait-ticket POST,
`stop_reason=entry_confirmed`, zero pages, Item 26 pending, and no Artifact. Its
Source grant expiry is `2026-11-17T09:35:11.467066+09:00`; quota start and work
last-consumed time are `2026-11-16T09:35:16.467066+09:00`. Source=3 and Viewer=2
are request totals; route types were not recorded. The successful automatic
notice/history confirmation and persistence are covered by
`stage03/novel/grant_only-report.json`.

Dual chapter 29 same-grant retry attempt 3 had Source=1, Viewer=1, and no native
ticket POST. It saved 13 pages, then failed before END with a reader-gate
timeout; no Artifact was created and the grant remained unchanged. Attempt 4
saved all 14 body pages but failed to recognize the terminal boundary, with no
Artifact. A5 later completed the same target with 14 pages and positive END;
Root audited the genuine Manifest and ZIP. The stored grant and work cooldown
remained unchanged, and no ticket POST occurred. The observed next-chapter card under the
unique `#rental` auxiliary includes point and rental-short metadata; the gate
now excludes the exact `.episode-modal-point`,
`dl.episode-modal-point--posession`,
`dl.episode-modal-point--necessary`, and `.episode-modal-short` nodes there.
Semantic dialogs remain gates, and the existing body ownership, pixel, and END
checks are unchanged. The observed inline wait countdown terminal variant is
accepted only when it matches the immediate next wait-marked listing row and no
next/read or signup CTA is present. No further ticket action is authorized.

Wait/trusted history accepts exact `残りH時間` or `残りD日` within the explicit
72-hour bound. D>=2 uses observation start plus (D-1) days minus 5 seconds as
`site_day_countdown_lower_bound`; D=1 and H=1 are active without finite expiry.
First-free remains limited to 23-hour hour notation; no fixed grant period is
invented.

Focused synthetic checks: Rental History browser tests 37; wait-ticket/rental-
form adapter browser selection 18 passed / 106 deselected; first-free regression
selection 15 passed / 109 deselected; adapter and policy unit files 41 passed.
The first-free selection initially exposed six cases with a stale fixed-time
fixture; it now uses a test-relative observation and passes. Independent review
of the notice/day/late-record changes passed BLOCKING 0. Five focused browser
cases cover the observed terminal countdown branch, and the Yanmaga adapter
unit file passed 10 tests. Stage 03 is accepted with qualified composite
evidence and independent BLOCKING 0. Post-capture full/incremental Discovery
preserved the target, grant, and artifacts with zero Source, Viewer, or native
rental POST activity. Stage 04 A6/A7 captures, independent Tester audits, and
the 261-test affected scope passed with 0 skips and 305 deselections. The final
Reviewer gate passed with independent BLOCKING 0; the full-suite run was controlled-stopped and
is not a full pass.

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

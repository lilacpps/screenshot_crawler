## Common Batch retry boundary (2026-11-22)

Normal CLI/GUI Batch can retry an eligible acquisition timeout once on a fresh
Page/Adapter, using the same target and freshly validated non-consuming direct
access. Two failures stop the Batch. AccessGuard rejection, UNKNOWN/proof/guard
errors, cancellation, output/Catalog failures and grant-only never retry. New quota
intent cannot replay; only confirmed observed consumption with a persisted grant
can authorize direct recovery. First-attempt diagnostics/history remain; final
candidate counts and --limit count once. See [shared current behavior](00_core.md#normal-batch-single-retry-2026-11-22).
Adapter navigation/capture proof is unchanged. Local synthetic/browser coverage
is available; no new real-site retry verification was performed.

## Discovery target pacing (2026-11-13)

CLI/GUI Discover uses shared `discovery_inter_target_delay_ms` (3000 ms in
the root YAML) after this target closes, only before another target starts.
The first/single/final target adds no delay; site changes retain the previous
site setting. Existing listing-page waits remain independent. See
[shared runtime details](00_core.md#phase-1-runtime-settings--pacing).
Synthetic CLI/worker ordering is verified; live timing is unverified.

## Stage07 complete-list investigation (2026-11-03)

Preview/detail remains unsupported. Static Work1970 has34native chapter rows
in4groups but no chapter DOM while scripts/resources are denied. Matching native
and visible public inventory, count/terminal and access evidence remain unproven.
The current work frontend references WEB_MANGA_VIEWER with useTicket/consumePoint
arguments; enabling this bootstrap just to obtain a listing is not authorized
by the read-only preview contract. No viewer/API/ticket/point/purchase/Capture or
store operation was attempted. This does not assert normal acquisition failure:
ordinary Discovery is unchanged. Safe single-key URL/title registration remains.
Follow-up must establish a list-only complete public path before enabling detail.
See Stage07 runbook/PROGRESS for evidence boundaries.

## Watchlist URL registration hook (Stage 06A, 2026-11-03)

Work entry and exact position=thumbnail hint; work identity.
Strict new-entry URL validation is supplied by registration/resolver.py and the
site-owned pure hook. Existing Discovery input, capture and access semantics
are unchanged. Title is unknown unless independently observed; no identity is
inferred from a label. Optional exact-work document observation requires matching
canonical, unique `__NEXT_DATA__` page `/manga/[mangaId]`/query.mangaId and
unique og:title equal to document.title. Redirects/subresources/POSTs are blocked.
Viewer-to-work conversion remains unsupported. One-work shared-CDP live check
passed for work 1970 (城下町のダンデライオン), 2026-11-03 05:54 JST; no reader,
Discovery, Catalog/Watchlist/ZIP write or resource operation occurred.
Complete-list preview capability is unchanged (see the site behavior below).
The registration Page is dedicated and its restrictive route remains through
caller cleanup until Page close, including error/delayed-script paths. It is
never reused for reading or Discovery; shared browser/context routing is untouched.
Final Page-lifetime guard live recheck on the same work1970 passed at
2026-11-03 07:43 JST: title and pure validation accepted; one document GET only.


Registration document observation now replaces response CSP with script-src
'none', object-src 'none', worker-src 'none' and form-action 'none'. This blocks
inline viewer bootstrap as well as external scripts, while inert JSON and static
metadata stay readable. The route guard remains installed until dedicated Page
close; lifecycle tests inject timers via Page.evaluate independently of CSP.
This affects metadata observation only, never ordinary Discovery/capture Pages.
Zeblack's fixed public metadata API does not navigate an HTML Page.


CSP-guard live regression passed on the same previously verified Work at
2026-11-03 08:20 JST: title and pure resolution validation accepted; one
work/listing GET only. Evidence: coverage-followup-other-four-live.json.

# 13. ComicFUZ 現行実装ノート

## Work Ticket current status (2026-11-24; Phase 01-03 PASS; Phase 04 in progress; one confirmed use, two potential uses)

Latest Phase 04 accounting: Work3152 run4 and Work3342 run5 remain unknown, one potential ticket use each (aggregate potential 2). Run4's exact `useTicket=true`/zero-point request has no matched response status. Run5's exact request matched HTTP 200, but positive native consumption proof and expiry were not saved; neither the status nor empty Catalog rows establish consumption or its absence. Work3500 run6 is one confirmed ticket use for target `3500:65256`, recorded at `2026-11-24T17:11:33.940579+09:00`, with no observed finite grant expiry. Its grant-only run left the Item pending and produced no captured images, ZIP, or Artifact. Work3500 direct runs7 and 8 failed before viewer entry; run9 reached the strict false/zero-cost direct viewer path but failed native role validation (`ComicFUZ body pages are not a contiguous unlinked prefix`) without making a consuming ticket request. These direct runs add no confirmed ticket use. Preserve every run; do not retry the unknown Works or alter Catalog history. Work3667 remains quarantined. Non-consuming probes do not resolve either unknown run.

The run9 bounded native role probe observed a stable exact tail `[unlinked_extra, unlinked_extra, linked_extra, google_ads, last_page]` after body indices 0–11. Only this exact UUL layout is newly supported; native indices are not renumbered and all body pages remain the complete prefix. Initial restore alone has an explicit validation allowance for the exact final body-plus-extra or U+U group when the Adapter is uninitialized and capture history is empty, so the existing bounded rewind can return to the verified first body group. Capture, identity, advancement, and END retain their normal history checks. Synthetic blank-first and nonblank-first group alignments pass; the nonblank alignment remains fixture-only, not a live observation. The material correction passed independent review (10 Unit and 8 browser cases, 0 skipped, BLOCKING=0); no additional live operation is authorized.

The inventory Result field is a display-only projection: it strips the prefix only for the exact versioned confirmation marker with a valid timezone-aware ISO timestamp and separator, then retains the entire original reason suffix. Unknown/malformed marker strings remain raw. The stored Catalog `stop_reason` is unchanged.

The same-day Work3500 grant-only local skip was separately run with Page creation, `goto`, and network access guarded before the original methods. It returned `work_ticket_daily_reset` and `2026-11-25T00:00:00+09:00`; the isolated Catalog and run history were unchanged. Grant-only received 79 natural image HTTP requests, but read/saved image bodies, ZIPs, and Artifacts were zero. The live response's independent native metadata projection was not retained, so no details are inferred from it. Exact artifacts and the initial non-invoked preflight attempt are in the [Phase 04 progress ledger](../runbooks/comicfuz-work-ticket/PROGRESS.md#phase-04-work3500-grant-only-and-same-day-local-skip-2026-11-24-one-confirmed-use-stop).

Phase 04 A adds a fail-closed same-operation path for the observed relative rental marker `残り2日`: a positive matched ticket response and fresh exact-target React state must agree on the same relative marker and complete zero-point metadata. This marker permits only the current entry; it is not converted to an absolute expiry and does not create a future source grant. A separate non-consuming Work3342 snapshot saw the raw marker; a bounded Work3500 scalar probe confirmed SSR has an own typed amount 30 with no type field while row and runtime share the exact Chapter and point objects whose generated amount/type are known zero. The separate probe is not run5 response proof. Phase 04 A passed independent synthetic review. Run4/run5 remain untouched and no ticket action occurred during these probes. Detailed evidence and sanitizer boundaries are in the work-ticket progress ledger.

Phase 04 B adds a separate non-consuming direct revalidation for a selected Catalog quota source with an old quota timestamp and no finite source grant. That timestamp is only a hint. The adapter revalidates the selected current Work row and exact chapter-native relative rental, then requires one strict `useTicket=false` viewer response with both point amounts zero before using the existing capture/END path. In the B-only `rental_listing` snapshot, the selected row Chapter and runtime Chapter must be the same object and their `pointConsumption` references must be identical; row/runtime generated point type and amount must be known zero. The separate SSR target amount must be an own nonnegative integer, but is not compared with runtime zero; absent SSR type remains absent. Its domain meaning is unverified and it is not current price or rights authority. This does not alter A's ordinary pre-charge listing equality or global Discovery classification. The row root must have exactly the two observed Chapter class tokens, optionally plus the single literal `false` token as cosmetic; this exception is root-only. Unknown/extra root tokens, descendant `false`, and other unfamiliar price/access markers remain fail-closed. A relative rental is valid only for the current entry and is never persisted as a future expiry. Recognized current free/paid/quota access is a typed no-action skip. Ticket availability can be either true or false independently of an active rental. The synthetic B point-delta correction passed independent review. Work3500 run7 failed before viewer entry at the point comparison; run8 failed closed at `rental_listing_row_not_exact`; run9 reached the false/zero direct viewer path and failed at the newly observed UUL body-prefix role. An offline metadata-only read of run8's saved HTML showed 118 headings and target index 79 with the required two root class tokens plus literal `false`; computed CSS visibility/style was not established. The narrowly scoped root-class correction passed independent review with BLOCKING=0. Runs4/5 remain unknown/potential use 1 each, and Work3667 remains quarantined. No live retry is authorized.


The current synthetic route contract accepts only the exact canonical target
viewer path or the exact same path with the sole query `ticket=true`. It rejects
Work paths, wrong chapters, any other/extra query, empty query or fragment
delimiters, explicit ports, credentials, and alternate schemes. The controller
precheck, final navigation wait, native viewer snapshot, and adapter reader
identity share this predicate. The first fixed route-failure reason is retained
if a later route error occurs. Normal Batch and grant-only synthetic E2E cover
both URL forms; the canonical positive branch performs a hard document
navigation and makes one viewer API request from the new document. At that
route-contract checkpoint, the live modal CTA had not been clicked, so this
verified implementation behavior only, not the real CTA route or ticket
response. These tests caused no additional live action; at that time run4 was
unknown/potential use 1. The focused URL unit group passed
26 cases, the ticket-controller browser group passed 63, and the normal/grant-
only adapter E2E selection passed 4 (103 deselected, 0 skipped). Scoped Ruff,
`py_compile`, and `git diff --check` passed. Independent review passed 39
selected synthetic cases in total (including five hard-navigation/Work-replan
cases), 0 skipped, BLOCKING=0; the affected Adapter Unit selection passed 9.

Discovery recognizes an exact visible row-local `無料` marker as `free`, a
single visible price slot containing the observed public gold/silver icon alt
and matching static asset as `paid`, and a fully hydrated, joined row whose
price/access region is genuinely empty as `quota`. Unknown, hidden, incomplete,
conflicting, duplicate, or unfamiliar rights markers stay `unknown`. The
classifier does not use first-party `pointConsumption` or `badge` fields.

ComicFUZ Site Policy currently admits only `work_ticket` for quota, uses Work
scope and a one-candidate-per-Work limit, and computes retry at the next
00:00 JST boundary; the generic `work_ticket_cooldown_hours` value is ignored.
Free remains direct. A source-level active episode grant is also direct and
non-consuming, independently of the Work daily reset; a grant expiring exactly
at the current time is not active. Normal Batch and explicit grant-only both
have a site-local quota entry path. Quota entry uses the one Catalog-selected
chapter's regular work page, exact row selection, and its single visible
`チャージで読む` modal action. It does not rerun full-list
Discovery, inspect another episode, or invent a ticket deep link. A confirmed
grant is read directly on the canonical viewer route. Premium Ticket, coin,
medal, and paid paths remain unsupported.

Shared Planner and Executor use an opt-in, site-neutral unresolved-quota-history
hook. Markerless or malformed quota attempts block another episode in the same
Work across runs and dates. Only a confirmed persisted consumption with exact
candidate/source/work/target binding writes a versioned confirmation marker to
the existing CrawlRun `stop_reason`; a later capture failure remains resolved.
This avoids a new Catalog table/schema migration. Retry timestamps in inventory
are shown only while strictly in the future. Phase 02 tests and live evidence
passed independent review with BLOCKING=0. Gate03 also passed independent
synthetic review with BLOCKING=0. Phase 04's first isolated preflight found that
the actual listing exposes work charge state through a shared runtime
`webMangaViewerData` object, while the Charge component's direct props contain
only availability and label presentation. The adapter now joins the exact
runtime chapter through the same object referenced by the heading and Charge
component, and rejects missing, duplicated, mismatched, or separate messages.
The initial synthetic adapter timeout was caused by a duplicate global
`webMangaViewerData` declaration in listing/viewer fixture scripts; the listing
fixture is now IIFE-scoped. The first isolated `3667:76588` grant-only CLI run
failed inside `observe_target_row`'s `_snapshot` at the list-container lookup
before strict access classification, modal, controller, or charge action: the
visible list had not hydrated by the immediate snapshot. A bounded diagnostic
observed zero matching containers just after DOMContentLoaded and one visible
container with 25 headings 1.2 seconds later. The adapter now waits up to its
existing bounded timeout for the selected list/heading and known runtime
message to attach; already observed route, duplicate-container, SSR work/target,
or runtime identity/count/target contradictions fail immediately. Full chapter
ID-order comparison remains in the subsequent strict snapshot. Strict access
classification and ticket proof checks are unchanged. Synthetic tests cover
DOM+runtime delay, runtime-only delay, timeout without action, duplicate
containers, and invalid runtime data before Charge mounts; delayed-list normal
Batch, grant-only, and unavailable-work replan pass. Independent readiness
review reports BLOCKING=0. The isolated attempt left one failed pre-action
`DiscoveryIncompleteError` CrawlRun in `%TEMP%/cfzgt1/catalog.sqlite`; its item
is pending and source/resource/grant/artifact state is empty. Preserve this
run and keep work 3667 quarantined; do not retry it. The attempt consumed zero
tickets. Work 3152's first grant-only attempt ended with the typed
`target_ticket_modal_not_exact` no-action sentinel. After the modal-scope
correction passed review, one Lead-authorized reattempt (CrawlRun 3) ended with
the same pre-click no-action reason. A passive Page observer recorded one
canonical viewer endpoint POST/200, but its body was rejected by the strict
request decoder as unknown; chapter/useTicket/point flags were not established
and the event is not classified as a consuming request. The post-run Catalog has
no Work 3152 quota start, grant expiry, resource state, or Artifact; the Item
remains pending and the previous runs are unchanged. The separate non-consuming
probe observed the exact native available state and modal without clicking the
CTA. That sentence described the earlier checkpoint; later Lead-authorized non-consuming probes and the current stop state are recorded below and in the Phase 04 ledger.

Current Phase 04 modal scope is based on the observed visible
`div[class*="Dialog_modal__"]` root. The target title is a unique exact
`p[class*="Dialog_chapter__mainText__"]`; the CTA is a unique exact visible
anchor inside that root. The unique ticket amount is a direct-text `1` in
`p[class*="Dialog_items__amount__"]`; visible unknown/extra price markers,
other access controls, duplicate title/dialog/amount, or disabled CTA fail
closed. The root contains the target title, CTA, price, Cancel, app, and comments
controls while the parent body wrapper also contains the same-label background
chapter `h3`. Read validation, trusted-click arming, and final CTA locator use
this same modal scope and visible-state contract. Native consumption proof,
zero-point request validation, route guard, and one-click latch were unchanged.
The public `5061` asset (32,022 bytes, SHA-256
`81b37aa63715952b699341c36226472198b088ed7613a14c2bc8fb07395d267c`) was
fetched without credentials or referrer and its bounded excerpt records the
Dialog control CSS mapping, not a saved Dialog JSX caller. Real post-consumption
request flags and grant expiry remain unverified. The isolated 3152 attempt and
modal probe each observed an endpoint POST/200 event with flags unrecorded; do
not interpret those events as a ticket charge or claim endpoint HTTP count zero.

After the no-action CrawlRun 3, one bounded non-consuming modal diagnosis
found the exact false gate: the visible Dialog contains an exact app-caption
anchor with an empty class and an exact app-caption button with the observed
`Dialog_appflow__button__` prefix. The previous inspector expected only the
button, so `allowedControls.app` is 2 and `allowedControlShapes.app` is false.
The exact target title, charge CTA, ticket amount, Cancel/comments controls,
unknown-control count, native state, and unchanged-before/after state all pass.
The probe clicked only the target row; charge and other control clicks were 0.
The shared inspector now accepts exactly that observed app-caption pair: one
classless `A` and one `BUTTON` with the known
`Dialog_appflow__button__` prefix. It rejects third app controls, unfamiliar A/B
classes, unknown role-button tags, and unknown captions; it does not assume a
containment relationship. The same inspector still gates reading, trusted-click
arming, and final CTA selection; all ticket/native/API/price guards remain
unchanged. The corrected synthetic controller browser module passed 57 cases, the
affected ComicFUZ Unit group passed 64 cases, and the normal/grant-only/
unavailable-work E2E selection passed 3. Scoped Ruff, compile, and diff checks
passed. Independent review covered 17 modal cases and 3 adapter E2E cases
(20 passed, 142 deselected, 0 skipped), BLOCKING=0. This is synthetic
verification only; no live CTA or additional CLI attempt was made. The sanitized
modal diagnostic is in the Phase 04 ledger.

The public first-party client binds `/v1/web_manga_viewer_2` to
`WebMangaViewer2Request` and `WebMangaViewer2Response`; the similarly named
legacy `/v1/manga_viewer` message is not the endpoint contract. Request fields
are deviceInfo=1, useTicket=2, consumePoint=3, chapterId=4, and
chapterArgument=5. Ticket requests require exact chapter/work identity,
BROWSER device, an explicit true `useTicket`, and zero free/paid points.
Response fields include viewerData=2, chapter groups=5, manga=11, and current
chapterId=12. Manga fields 1/12/13/18 carry mangaId/isTicketAvailable/
isChargeNeeded/chargeStatus; Chapter fields 1/5/10 carry chapterId/
pointConsumption/endOfRentalPeriod. The viewer's bound client decodes that
response and supplies the resulting `E.data` as
`webMangaViewerData` to the same component.
The sanitized public asset names, byte counts, SHA-256 values, binding excerpt,
and native field map are recorded in
`runbooks/comicfuz-work-ticket/PROGRESS.md` and the local evidence artifact
`.tmp/comicfuz-work-ticket/evidence/public-bundle-provenance.json`.
The listing Charge presentation/dataflow was also checked against the sanitized
public bundle evidence `phase04-charge-source-provenance-3667.json`; the
same-object runtime chapter projection for `3667:76588` is in
`phase04-runtime-chapter-projection-76588.json`. The runtime chapter is the
authority for point type and rental defaults because SSR omits them; SSR values
are not completed from assumptions. These bounded live reads did not click the
charge control or open a viewer for the quota target.

The controller records consumption only after the exact same-Page main-frame
ticket request returns HTTP 200 on the same JST date and its exact native
response positively shows ticket availability true→false, charge-needed true,
and the precise `0時に回復!` recovery text for the same work/chapter. The
request start time is the observed `consumed_at`; no server consumed timestamp
was found. A future aware expiry is stored only if the response and fresh React
projection agree. If consumption is proven but route/readiness/expiry later
fails, the consumed resource is retained with unknown expiry and cannot be
retried. Missing or ambiguous response proof remains an unknown work attempt.
No fixed 72-hour expiry is used.

The endpoint route is limited to the known API host/path and rejects noncanonical
scheme, port, credentials, query, fragment, path, or method before forwarding.
The bounded response read validates declared Content-Length and uses the
remaining action deadline, with a two-megabyte post-read cap. Once the operation
is terminal, both in-flight handlers and later same-Page ticket POSTs abort
before forwarding. A typed no-action before the ticket click remains eligible
for Batch replanning; its strict CrawlRun evidence accepts the executor's
pre-initialization `page_count=None` or exact zero pages. `configure_run()`
resets the previous entry proof while retaining the new target identity,
existing-grant context and observers. Fresh expiry is checked again immediately
before grant commit; if it expired while waiting for viewer state, consumption
remains confirmed with expiry absent.

A bounded free-viewer probe on work 3667/chapter 76561, using canonical viewer
URL without a ticket query, observed `webMangaViewerData.manga` and `.chapters`
in React props. The generated Manga prototype defaults are
`isTicketAvailable=false`, `isChargeNeeded=false`, `chargeStatus=""`; Chapter
`endOfRentalPeriod` has an inherited empty default. `isRead` is not used as an
access predicate. The default interpretation is restricted to this observed
generated-message shape; a missing or plain empty object stays unknown. No image
body or ticket response was read during that probe. Live consume response
values, server time and a real grant expiry remain unverified. Gate03 passed
independent review. The bounded Phase 04 readiness review also passed with
BLOCKING=0; synthetic tests cover delayed DOM/runtime, runtime-only delay,
timeout without action, duplicate-container rejection and known runtime
contradictions. One isolated CLI attempt on `3667:76588` failed before row
observation or charge action with `DiscoveryIncompleteError`; the failed
CrawlRun remains in the isolated Catalog and work 3667 is quarantined. A
read-only DOM count observed zero matching containers immediately after
DOMContentLoaded and one visible container with 25 headings 1.2 seconds later.
The adapter now has a bounded presence wait before its unchanged strict
snapshot. The attempt consumed zero tickets; sanitized metrics and diagnostic
artifact paths are documented in `runbooks/comicfuz-work-ticket/PROGRESS.md`.
This described an earlier checkpoint. Later free-only observations and the current ticket stop state are recorded above and in the Phase 04 progress file. Full suite history and live-audit boundaries remain in that progress file.


### Phase 04 non-consuming sequence evidence (2026-11-24)

- Run4's exact allowlisted reason is `ticket_request_or_response_missing`. Its single decoded target request used `useTicket=true` with both point fields zero; the response status was not observed. The metrics API status=200 record is not attributed to that request. Treat this as unknown/potential consumption 1; DB absence of a grant/resource row is not a no-consumption proof. Do not retry the quota target or rewrite the run.
- Current Work3152 availability/rental state was read on a separate non-consuming Page. Availability remained true with the recognized charge presentation; rental was the known inherited empty default. This current snapshot does not negate a possible earlier consumption.
- A free-only probe on Work3152 used one canonical Work navigation and the nine Catalog-known free sources as the full candidate set. The normal bootstrap was decoded as false/zero cost with `chapterId` omitted and `chapterArgument` present, on the Work main frame, HTTP 200. Only selected source `3152:40956` was row-clicked after exact live `free` classification, native/runtime identity/order join, and known runtime point type/amount defaults of zero. Its UI `isReading` prop was false; source `3152:40905` was the one candidate with `isReading=true`. The UI click navigated to the canonical viewer route before one main-frame `useTicket=false`, point-zero request. No Dialog appeared; no charge CTA or other row was clicked. The viewer request's response status was not captured, so the free-path observation proves route order but not response success.
- For `3667:76561`, an earlier over-broad diagnostic guard aborted two unrecognized Work-page bootstrap requests before hydration and no row was selected. Its readiness failure may have resulted from the diagnostic abort. A follow-up Work3152 free probe passed the ordinary zero-cost bootstrap before installing a strict zero-envelope guard after free proof.
- A diagnostic-only envelope parser passed 3 synthetic acceptance and 11 rejection cases. Production ticket decoding remains unchanged and strict. It retains `chapterId`/device omission as unknown and never treats `chapterArgument` as chapter or resource authority.
- A quota-row route probe used one Work3152 navigation and one `46873` row selection. Native state matched strict quota preconditions. The unique React chapter prop exposed `onSelect`, while `isReading` was absent; it was not interpreted as false. The user-authorized non-consuming row selection opened an exact Dialog with one enabled charge CTA, one direct price `1`, matching target title and only known controls. The page remained on the Work route; the guarded interval forwarded and blocked zero viewer API requests. CTA and other-control clicks were zero.
- The visible modal CTA anchor classified as the Work route with no `ticket`, `free`, `paid`, or `chapterId` query; no `href`/`as` props appeared among its React fiber ancestors. Public `5061` and viewer-route assets were fetched without credentials or referrer and stored only as SHA-256, size, and bounded sanitized excerpts. The generic `chapter` ticket branch excerpt is not bound to the modal CTA. The exact CTA navigation/request order remains unknown. No raw URL/query, headers, request/response body, image body, or Catalog data was saved. Sanitized artifact: `.tmp/comicfuz-work-ticket/evidence/phase04-ticket-link-route-3152-46873.json`; metadata scan found none of the prohibited raw fields.
- Evidence is sanitized under `.tmp/comicfuz-work-ticket/evidence/phase04-free-transition-3667-76561.json`, `.tmp/comicfuz-work-ticket/evidence/phase04-3152-and-3667-nonconsume-diagnostics.json`, and `.tmp/comicfuz-work-ticket/evidence/phase04-ticket-link-route-3152-46873.json`. These probes did not read/save image bodies, invoke paid/premium/ticket controls, write Catalog state, or resolve the run4 outcome. At that checkpoint, no further ticket or site action was authorized without a new Lead instruction; later run4/run5 outcomes and the current stop state are summarized at the start of this note and in the progress ledger.

## Login-independent public-free access (2026-11-22)

Discovery and public-free capture work with the existing shared-Chrome session
whether logged in or anonymous. Neither path requires `/account/signin` nor
rejects sign-out/my-page links. The old anonymous-only gate rejected the user's
logged-in work 3140 before any records were emitted: the initial server-rendered
sign-in link disappeared during hydration and the settled header showed
`/mypage`. Login-header changes are unrelated to work/chapter identity.

Access classification uses a visible exact row-local `無料` marker for `free`,
recognized S/G icons in the visible price slot for `paid`, and only a fully
hydrated, identity-joined row with a genuinely empty price/access region for
`quota`. Incomplete, hidden, conflicting or unfamiliar markers remain
`unknown`; login, account rights, rentals, stock and balances never independently
prove access. The existing direct/free capture adapter still validates the
complete same-work listing and exact target free row before reader navigation,
then binds native episode/title/page-role and visual-safety proofs. The separate
quota entry path validates only its selected exact target row and modal before
the one ticket action. No login/logout, Premium Ticket, coin, medal or paid
operation is added.

Live verification used the shared browser over CDP and a dedicated Page with an
isolated Catalog under `.tmp/comicfuz-login-20261122/`. The old code reproduced
the anonymous-state error with 0 observations; the corrected Full Discovery
completed with 241 records, and a repeat completed with 0 new / 241 known. A
separate temporary anonymous browser context on
the same remote browser showed the same 241 native rows and 241 exact free
markers, so the current count is not inferred from the logged-in user's rights.
The user's session and operational Catalog were preserved. This live check
opened only the work listing, not a reader or purchase/resource UI. A subsequent
signed-in normal Batch capture through positive END is verified for chapter
82123 as described below; nonfree rejection is covered synthetically.

Validation: all 118 affected ComicFUZ Unit/Integration cases passed in three
isolated invocations (48 Discovery/Unit + 1 route-drift + 69 other viewer cases),
with zero skips. The first combined run stopped progressing at the route-drift
case and was interrupted, so it is not counted as a successful run; that case
passed alone and the remaining viewer module passed separately. Targeted login
and identity checks had also passed (17 cases). `ruff check src tests` and scoped
`git diff --check` passed. Full repository pytest was omitted for this site-local
change; Research helper tests were omitted because no durable research code
changed. This was the verification selection for the initial login-state fix;
the subsequent Batch compatibility changes and verification are described next.

## Work 3140 / chapter 82123 Batch compatibility (2026-11-22)

The reported item 56381 / source 56688 failed because Discovery normalized the
listing label to `第12巻 特典情報` while native `chapterMainName` contained an
ideographic space (`第12巻　特典情報`). Native main titles now use the same Python
`" ".join(value.split())` rule before comparing them with the bound listing
label. Work/chapter IDs, other characters/punctuation, subtitle binding and
rendered-title checks remain strict; no fuzzy matching or Unicode folding is
used. Synthetic title variants cover ordinary, ideographic and repeated mixed
whitespace; native main-title, work-ID and chapter-ID drift still fail closed.

The exact native manifest observed on this chapter has ordinary body indices
0-1, three extras 2-4 with link flags `(true,false,true)`, and `googleAds` /
`lastPage` slots 5-6. A sanitized runner probe showed a pending transition from
the captured final `(1,2)` spread toward extra-only `(3,4)`, with active rows
`[1,2,3]`: the old body and new unlinked extra were clipped, while linked extra
2 was ready. The existing body-to-body overlap wait is extended only for this
known three-extra shape on that path: all body indices must already be captured, the prior
group must be `(extra-1,extra)`, and no extra-tail advance may have occurred.
Only a contiguous duplicate-free subset of the exact prior/next group union,
with both groups represented and at least one not-ready row, can wait. Exact
native roles and dimensions remain bound, including `unlinked_extra`; ready
images retain their source/visual checks. The overlap is never captured.
That path retains its single extra-group turn, timeout, strict capture and
positive-END requirements. The alternate extra layout is described below. Synthetic cases cover both overlap
sizes, persistent transition failure, malformed roles, all-ready wide shapes,
unsafe ready pixels and descriptor dimension mismatch.

The logged-in no-next END panel also includes a second direct
`ChapterLastPage_lastpagetitle__*` block headed `チャージが回復した作品`.
The adapter now selects the existing positive recommendation block by its
expected `この作品を読んだあなたにおすすめ` heading before requiring uniqueness.
The three exact action labels, one matching viewer title, full captured body
prefix and cleared/matching inactive image shells remain mandatory. Duplicate
matching recommendation blocks, missing/hidden evidence and partial panels
still fail. No account section or action is clicked.

Normal CLI `batch run --limit 1 --max-pages 10` succeeded for the same failed
Catalog item/source using a SQLite backup, single-key Watchlist and dedicated
outputs under `.tmp/comicfuz-82123-20261122/`. It reached positive END and saved
two unique, decodable 1351x1920 JPEGs in the isolated `241-...` ZIP, with a
present Artifact and Completed item. CRC and Catalog Artifact SHA-256/size
checks passed. Both ZIP payloads equal the prior same-chapter body-prefix
evidence saved before the extras-transition failure. The successful attempt's
pre-package Manifest was not retained, so that specific comparison is not
claimed. Audit: `.tmp/comicfuz-82123-20261122/audit.json`. The operational Catalog,
Watchlist and library were not updated. No ticket/charge/medal/purchase action,
Policy change, Core change, new CLI/configuration or output format is introduced.

Verification covered all 8 ComicFUZ adapter Unit cases and 84 viewer Integration
cases with passing results across the isolated invocations, with zero skips.
The broad viewer invocation finished with 82 passed / 1 failed (one route-drift
case was selected separately and passed). Its failure was the existing normal
signed-in Runner fixture's 800 ms page-change budget during the final turn;
the case passed alone. That success-path fixture now uses the same bounded
2-second budget as its Runner config, allowing the 350 ms animation, repeated
stable reads and browser overhead; both anonymous/signed-in variants then
passed. Production timeout settings and negative timeout tests are unchanged.
Earlier broad attempts were stopped when new live findings required another
implementation iteration, and are not counted as successful complete runs.
Targeted title/identity (10), overlap (18) and account-END/duplicate-END (2)
selections also passed. Reports are under the same isolated directory.
`ruff check src tests` and scoped `git diff --check` passed. Full repository
pytest was omitted for this site-local change; durable Research helpers were
not changed, so their separate tests were omitted. Only the exact reported
chapter was live-crawled; the other pending chapters were not batch-executed.

## One-body-page / two-extra-group layout (chapter 81871, 2026-11-22)

The next reported failure, item 56382 / source 56689, is work 3140 / chapter
81871 (SSSオフショット101). Shared-CDP probing confirmed one native body image
at index 0, the already supported three-extra manifest at indices 1-3 with
link flags `(true,false,true)`, and `googleAds` / `lastPage` at 4-5. Native
`isFirstPageBlank=true` renders `(0,)`, then `(1,2)` with roles
`(linked_extra,unlinked_extra)`, then a single `(3,)` linked extra, followed by
the positive next-chapter END panel. No next chapter was opened.

The previous adapter accepted only the other extra alignment: final mixed
`(body, first linked extra)` followed by `(unlinked extra, linked extra)`.
It stopped after saving body 0 because the first extra pair used a different
role order. The adapter now tracks a bounded tuple of advanced extra groups.
After all body indices are captured, the exact last rendered group chooses
one of the two observed paths: a final mixed group requires the remaining
extra pair; a final body-only group requires the first two extras and then
the final linked extra. Native indices/roles, complete body prefix and prior
group are mandatory, and each group receives at most one ArrowLeft. The
maximum is two extra-group advances. Stale groups wait under the existing
deadline and cannot receive another turn. Skips, unexpected order or role,
early extras, and missing positive END still fail closed. Neither extra path
produces CONTENT or image artifacts.

The existing pending-overlap check uses the exact next extra group from the
same bounded state, including body-only to extra-pair and extra-pair to single
extra transitions. A duplicate-free contiguous subset of the prior/next union,
both groups represented and at least one not-ready row are still required.
Ready images retain native dimension, source and visual-safety checks;
arbitrary wide shapes and all-ready wide rows are still rejected.

Normal CLI `batch run --limit 1 --max-pages 10` completed this exact item/source
using a read-only SQLite backup, a single-key Watchlist and dedicated outputs
under `.tmp/comicfuz-81871-20261122/`. The prior completed chapter 82123 was
excluded by normal planning. Chapter 81871 reached positive END, created a
present ZIP Artifact and marked the isolated Item Completed. Its ZIP contains
only one 1351x1920 JPEG. CRC/decoding and Catalog Artifact SHA-256/size checks
passed; its bytes equal the native body-prefix evidence from the bounded
same-chapter runner probes. The successful Batch's pre-package Manifest was
not retained, so that specific comparison is not claimed. Audit:
`.tmp/comicfuz-81871-20261122/audit.json`. Operational Catalog/Watchlist/library
were preserved. No resource operation, site-ID/title special case, shared
Core/Policy, CLI or output-format change was introduced. Other pending
chapters were not batch-executed.

Validation for this layout change: all 99 distinct affected cases (8 adapter
Unit + 91 viewer Integration) passed across small completed invocations, with
zero skips. The completed reports cover 9 Unit/route cases, 17 Batch/overlap
cases, 11 invalid-overlap cases, 2 skipped-extra/capture-denial cases, 15
opening/restore cases, 13 capture/terminal guards and two remaining groups of
16 cases each. The initial broad browser run stopped during Windows async
fixture teardown and was interrupted; it is not counted as a complete pass.
Its transient invalid-overlap fixture could disappear after 160 ms before a
poll saw it, so invalid variants now persist until validation (11 passed).
The new singleton capture-denial case was already blocked by the layout guard;
its message assertion now expects that guard rather than the pair's no-body
message (both cases passed). These fixture changes do not alter production
timeout or safety checks. `ruff check src tests` and scoped `git diff --check`
passed. Full repository pytest was omitted for the site-local scope; no durable
Research helper was changed, so separate Research tests were omitted.

## Final full body spread / chapter 80350 (2026-11-22)

The reported item 56394 / source 56701 is work 3140 / chapter 80350 (第96話).
A bounded shared-CDP runner reproduced failure after capturing body indices
0-23, with last rendered/captured group `(22,23)` and a pending next turn.
Native `isFirstPageBlank=false` opens with `(0,1)`; the current manifest has
26 ordinary body images, extras 26-28 with flags `(true,false,true)`, followed
by `googleAds` and `lastPage` at 29-30. Active transition rows were `[22,23,24]`,
with clipped old/new outer rows and ready body 23; body 25 and the extras were
still outside the viewport.

The pending-overlap predictor incorrectly appended first extra 26 to the
expected final body pair `(24,25)`, then rejected that impossible three-image
prediction before applying the existing wait allowance. It now appends the
first extra only when the expected final body group contains one image.
A complete final body/body group is predicted as exactly two body images in
either native opening mode. All other requirements remain: exact contiguous
prior/next indices and roles, duplicate-free union with both groups represented,
at least one not-ready row, native dimensions and ready-image source/visual
safety, the existing bounded deadline, and no capture during overlap. No
page-role whitelist, END condition, retry/pacing limit or Core code is relaxed.

Existing synthetic overlap tests now include both three/four-row transitions
into the final body pair for a false-mode opening and a true-mode final pair.
Expected captured identities follow the declared opening mode, and all body
pages must be captured in order through positive END. A persistent false-mode
final-pair overlap must still time out without an Artifact or Completed item.
The existing mixed body/extra and both extra-only paths are retained.

CLI/Executor live verification used a read-only SQLite backup, a single-key
Watchlist and dedicated outputs under `.tmp/comicfuz-80350-20261122/`. A temporary
Executor package-function hook copied `manifest.json` before calling the normal
packager; no production code or package behavior was changed by that hook.
`batch run --limit 1 --max-pages 80` completed the exact reported item/source
through positive END, ZIP/Artifact creation and isolated Completed status.
The ZIP contains 26 unique JPEGs: first two 1512x2150, remaining 24 1351x1920.
Every member name/order, SHA-256 and dimension matches the pre-package Manifest;
native body pair identities cover 0-25, excluding extras 26-28. All members
decode, CRC passes, and Catalog Artifact hash/size matches the ZIP. Evidence:
`manifest-before-package.json` and `audit.json` in the isolated directory.
The operational Catalog/Watchlist/library were preserved. No ticket/charge/
medal/purchase or next-chapter operation occurred. Other pending episodes were
not batch-executed.

Verification: all 103 distinct affected cases (8 adapter Unit + 95 viewer
Integration) passed, zero skips. The targeted overlap/persistent-overlap group
passed 14 cases; the Unit group passed 8; the remaining 81 cases passed in four
small completed browser invocations (21/20/20/20), avoiding the previously
observed long-module Windows teardown stall. The opening-mode matrix now
covers final body/body and final body/extra transitions for both native modes.
`ruff check src tests` and scoped `git diff --check` passed. Full repository
pytest was omitted for this site-local predicate change. No durable Research
helper changed, so separate Research tests were omitted. Live scope remains
the exact reported episode, rather than the entire pending Batch.

## Initial manifest readiness / chapter 73083 (2026-11-22)

The reported item 56437 / source 56744 is work 3140 / chapter 73083
(Episode.79). Its production diagnostics show `saved_pages=0`, empty content
context and the manifest-disappeared error before initialization completed;
the saved HTML already contains opening images page_0 through page_3. The
implementation had bound a manifest once, then treated any subsequent missing
read as fatal even while waiting for the initial images to settle or rewind.
This readiness gap is consistent with the evidence. The exact transient was
not reproduced in a fresh pre-fix runner or a pre-fix isolated CLI retry;
both reached END. A particular React/hydration event is therefore a hypothesis,
not a newly observed live fact.

During initialization only (`_initialized=false` with explicit initial-loading
permission), `_validate_reader_identity` may now return not-ready after a
previously established manifest becomes temporarily unavailable. Initial body
stability and rewind loops reset their counters, skip image processing and wait
under their existing page-change deadlines. They do not clear or replace the
first bound manifest, advance again while waiting, return CONTENT, or capture
from cached metadata. Work/chapter/title/subtitle/route checks still run before
that not-ready result. Once a current manifest returns, all descriptors,
body/extra roles, chapter identity and native first-page mode must equal the
original binding before normal image validation resumes. Permanent absence
times out; changed manifests or metadata fail immediately. Detect/capture
after initialization still reject disappearance. The existing positive-END
exception remains separate and unchanged.

Synthetic browser fault injection removes the real fixture image-fiber props
after the first successful read, then restores them only after a missing read
has actually been observed. It covers single and pair openings, a gap during
rewind, non-returning metadata, changed native dimensions and chapter-ID drift.
No case captures during initialization; negative cases stop. The existing
post-initialization disappearance test now checks both detect and capture.
The initial-gap exception is not enabled for normal page turns or capture.

Post-fix CLI/Executor verification used a fresh read-only SQLite backup,
single-key Watchlist and dedicated outputs under
`.tmp/comicfuz-73083-20261122/verified/`, with a temporary pre-package Manifest
copy hook and a guard refusing any candidate other than source 56744. The exact
item completed with positive END, a present ZIP Artifact and isolated Completed
status. Native `isFirstPageBlank=false`; body indices are 0-28, extras 29-31,
then `googleAds` / `lastPage`. The ZIP contains 29 unique 1351x1920 JPEGs.
All member names/order, SHA-256 and dimensions match the pre-package Manifest;
all decode, CRC passes, and Catalog Artifact hash/size matches. Evidence:
`manifest-before-package.json` and `audit.json` in that directory. The original
live gap did not recur in this check, so recovery from that exact live event is
not claimed; its controlled equivalent is covered by browser tests. Operational
Catalog/Watchlist/library were preserved. No ticket/purchase/account action,
shared Core/Policy, CLI, timeout configuration or output-format change was made.
Other pending episodes were not batch-executed.

Validation for the initial-readiness change: all 110 distinct affected cases
(8 adapter Unit + 102 viewer Integration) passed with zero skips. The targeted
group passed 9 cases, Unit passed 8, and the remaining cases passed in four
small completed browser runs (24/23/23/23). The new cases prove an actually
observed missing read before restoring fixture data, including both opening
modes and rewind; permanent and changed-data cases cannot initialize.
Strict detect/capture rejection after initialization also passed. `ruff check
src tests` and scoped `git diff --check` passed. Full repository pytest was
omitted for this site-local initialization change; no durable Research helper
changed, so separate Research tests were omitted. The original live timing
event remains unreproduced; successful exact-target live capture and byte-level
archive checks are separate from the deterministic missing-read tests.

## Shared Catalog v7 / automatic acquisition scope (2026-10-23)

The site behavior below uses Catalog v7 and an explicit matching Watchlist.
Discovery never migrates Catalog implicitly. Successful Discovery automatically
reflects the current key's acquisition flags; Incremental enables observed
Sources, while failed runs preserve existing flags. Batch uses current flags
without requiring a sync marker, matching fingerprint, or complete evidence.
Temporary extra acquisitions and provisional ordinals are accepted. Target
`enabled` controls Discovery only. `watch scope-sync` remains optional strict
whole-Work maintenance; access/resource and output guards are unchanged.
See `note/00_core.md` for the current shared contract. This common change has
synthetic/local-browser coverage; it has not been live-verified on this site.

Current shared simplification (2026-10-24): GUI/Batch/audit/renumber use current
acquisition flags and key order directly, with archive_order applied at ZIP naming.
No sync stamp or complete-listing proof gates ordinary operation or final renumber;
intermediate numbers may be provisional. Explicit scope-sync remains for deletions
and repair. DB stays v7 and no JSON fields are added. File/identity safeguards and
site-specific access/capture behavior are retained; no new live claim is made.

ComicFUZ now supplies target-bound complete-listing proof for its validated
current public work listing (`comicfuz-work:<work_id>`) and supports native
bounded `discovery_scope`. Existing latest-first listing order and global
positions are retained before slicing. The page identity/list snapshot is
rechecked before emission; proof is published only after a normal Full
iterator exhaustion. Successful Full also reflects classified acquisition
flags for its key. Incremental enables observed rows; failed/partial runs keep
existing flags. Missing proof rows still block strict optional reconciliation,
but do not block Batch merely because proof/sync state is incomplete.

A Full run still invalidates strict maintenance proof/sync state as appropriate,
but Batch does not use that marker. Continue from Discovery to Batch directly;
optional scope preview/apply can reconcile an entire Work without Discovery.
No Source is moved between keys or deleted.

Optional strict maintenance examples (scope-sync is not required for Batch).
Use the same isolated Catalog, Watchlist and library paths under COPY_ROOT:

    python -m screenshot_crawler.cli catalog migrate --catalog <copy/catalog.sqlite> --backup-dir <copy/backups>
    python -m screenshot_crawler.cli watch scope-sync --watchlist <copy/watchlist.yaml> --catalog <copy/catalog.sqlite> --work-key <work-key> --dry-run --json
    python -m screenshot_crawler.cli watch scope-sync --watchlist <copy/watchlist.yaml> --catalog <copy/catalog.sqlite> --work-key <work-key> --apply --json
    python -m screenshot_crawler.cli batch plan --site <site> --catalog <copy/catalog.sqlite> --watchlist <copy/watchlist.yaml> --library-dir <copy/Books>

The scope-sync apply example can also be used after a successful full scoped
ComicFUZ Discovery. Batch plan remains read-only; use the same copy paths for
any separately authorized execution.

## Work 3140 compatibility (2026-10-17)

The work-3140 compatibility fix (`f847af0`, developed on `fix/comicfuz-3140-page-roles`) is included in `main`.

2026-10-17 isolated normal-CLI verification for work 3140 / chapter 81136 (第98話 無敵の魔法): full Discovery observed 233 records, with 134 free candidates and 99 unknown skips. `batch run --limit 1` reached positive END, produced 29 JPEG pages, a present Artifact, and Completed status. All ZIP members decoded; CRC and 29 unique payload hashes passed. The first two pages are 1512x2150 and the remaining 27 are 1351x1920. Catalog Artifact SHA-256 and byte size match the archive. First/middle/last samples were visually inspected; the last saved image is the work relationship chart, while all three marked extras are excluded. Evidence and archive audit are isolated under `output/comicfuz-3140-role-probe/`. No pre-package Manifest copy was retained in this run, so member-to-Manifest comparison is not claimed. The other 133 free candidates were not crawled. Login/resource/purchase flows remain unsupported and were not used.

Verification selection (2026-10-17): 116 affected ComicFUZ Unit, browser Integration, and CLI tests passed in five isolated groups, with zero skips; `ruff check src tests` and `git diff --check` passed. An earlier combined invocation stopped making progress and was terminated; it is not counted as a pass. Separate focused runs also passed. Full suite was omitted for this site-local change; separate Research tests were omitted because no durable PoC/research helper changed. The normal-CLI live and archive audit above are separate from synthetic tests.

## Phase 02: public-list Discovery

`ComicFuzDiscoveryAdapter` is the site's Discovery implementation and uses the shared `BrowserSession`-provided Playwright `Page` through `DiscoveryService`; it does not launch Chrome, connect to CDP, or write Catalog directly. The current CLI also registers ComicFUZ manual crawl and normal Batch. This Phase 02 section describes Discovery's own boundary, not the current site's complete registration state. Phase 01 observations and current phase gates are in `runbooks/comicfuz-free/PROGRESS.md` and `runbooks/comicfuz-free/research/phase01-20261012.md`.

The accepted input is `https://comic-fuz.com/manga/<numeric-work-id>` with no query or the observed decorative `position=thumbnail` query. The adapter rejects other hosts, routes, fragments, ports, credentials, and query parameters. After navigation it requires the current URL and canonical link to remain on the requested work. Work identity is rechecked at every snapshot and immediately before the first emitted record; delayed route or canonical-link changes fail closed. Login state and account-header changes do not gate listing observation or free classification.

The public Next.js `#__NEXT_DATA__` route `/manga/[mangaId]` supplies `props.pageProps.chapters`, grouped as objects with `chapters` arrays. Discovery flattens those groups and joins every record by exact sequence and normalized label to headings under the unique `div[class*="title_detail_chapters__list__"]`. A heading must have the observed two-level detail/row parent, the row must contain exactly one chapter heading, and each row identity must be unique. Exactly one visible row-local `p[class*="Chapter_chapter__price_free__"]` with exact text `無料` proves `free`. A single visible price slot with the recognized public S/G icon alt and matching static asset proves `paid`; a fully joined row with a genuinely empty price/access region proves `quota`. Hidden, incomplete, malformed, conflicting, duplicate, or unfamiliar rights markers remain `unknown` or invalidate the listing. `pointConsumption`, `badge`, dates and account/resource fields are not access or expiry proof.

The adapter requires nonempty groups, numeric unique chapter IDs, nonempty labels, exact hydration/DOM count and order, row visibility, no semantic paging/expand controls, stable repeated snapshots, and an unchanged snapshot after scrolling to the bottom. All records are buffered until every check passes because `DiscoveryService` upserts as the adapter yields. It emits all observed identities, including unknown rows, with composite external ID `<work-id>:<chapter-id>`, viewer target `/manga/viewer/<chapter-id>`, `kind=episode`, raw native chapter label, `free_until=None`, and `available=True`.

`DiscoveryService` initializes `Work.title` from the Watchlist label; set that label to the work's actual title. The adapter exposes the page title as `canonical_title`, but the existing shared service does not overwrite Work metadata from it.

The currently served public list is newest-first. After validating the whole list, global display positions are assigned as the reverse ordinal (oldest is position 1). An optional inclusive scope uses observed viewer URLs and must resolve both boundaries inside the same validated work list; positions are preserved from the full list. Incremental traversal remains latest-first and uses the existing shared known-streak limit of five. A full run reconciles only the currently served public list and does not claim that hidden historical/backend chapters do not exist.

## Verification and limits

Phase 01 live evidence on 2026-10-12 confirmed an anonymous `/account/signin` header, canonical work 1970, 34 unique hydrated chapter IDs and exact ordered DOM-label joins, four exact row-local public-free markers, and no pagination/expand control in the observed listing. The current-public-list completeness and reverse native order were accepted by independent review (BLOCKING=0) and Lead. The seed evidence is in the sanitized runbook report; no image bytes, signed URLs, screenshot, or comic content is retained.

Synthetic unit and browser-backed Catalog tests cover URL validation, hydration parsing, visible positive-free/unknown classification in logged-in and anonymous sessions, full and bounded positions, incremental known-streak behavior, hidden or duplicate free markers, delayed route/canonical drift, account-header hydration without failure, access refresh to unknown with expiry clearing, completed Artifact preservation, incomplete-full availability preservation, and rerun stability. The Phase 02 live isolated Catalog/Watchlist run and independent review are recorded in the progress ledger. This historical Discovery stage did not test charge, ticket, or medal mechanics; current Work Ticket implementation and gate status are at the top of this note.

## Phase 03: public-free viewer and manual crawl (original anonymous live run PASS)

Manual crawl first buffers and validates the current same-work public listing and checks the exact target row is positively marked `無料` before opening the viewer. It binds the exact work/chapter route and first-party viewer hydration, independently of account-header state: `mangaId` must match the configured work, `chapterMainName` must match the freshly verified row label, and `mangaName` supplies the work title in output metadata. The viewer title must match the listing-bound main title plus the independently bound optional native subtitle, after whitespace normalization. Existing Runner max-pages and same-content guards remain enabled; the adapter does not launch Chrome or modify Core. Any route change before positive END fails closed; `NEXT_CONTENT` is not accepted.

The supported reader manifest has a contiguous prefix of ordinary unlinked image descriptors, followed by one of the exact native tails `[linked extra]`, `[linked, unlinked, linked]`, or `[unlinked, unlinked, linked]`, then exactly `googleAds` and `lastPage`. The legacy three-extra shape was observed on work 3140, chapter 81136 (第98話): body indices 0-28, extra indices 29-31, and terminal slots 32-33. Visual inspection identified those extras as an official-X promotion, a volume promotion, and another-work recommendation. The UUL shape was observed read-only on Work3500 chapter 65256: body indices 0-11, unlinked extra indices 12-13, linked extra 14, then terminal slots 15-16. Four role-probe snapshots were identical; they did not capture page-turn groups or save images. Only the ordinary prefix is captured; its work-related introductory/relationship charts are retained. Descriptor indices and dimensions must join exactly to rendered `page_N` identities. Any final mixed spread must be fully ready; only its body half is saved. For the legacy `(linked, unlinked, linked)` tail, the two supported layouts are final `(body, first linked extra)` followed by `(unlinked extra, linked extra)`, or final body-only followed by `(linked extra, unlinked extra)` and then `(linked extra)`. For UUL, synthetic fixtures verify blank-first final `(body, first unlinked extra)` then `(unlinked extra, linked extra)`, and nonblank final body-only then `(unlinked extra, unlinked extra)` then `(linked extra)`. The UUL descriptor-role sequence is live-observed, but both group alignments are synthetic and not live-observed. Each exact extra group is AD, never capture, with at most two extra-group turns and one turn per group. Index/role/prior-group history rejects skips and repeated advances. Repeated extra tails time out without further turns. Missing/clipped halves, unsafe pixels, body gaps, changed manifests, other extra/link sequences, and unverified terminal states fail closed. This supports only the three exact role sequences, not arbitrary `isExtraPage` semantics.

END still requires the entire body prefix to be captured, matching episode identity, and cleared or matching inactive image shells. A positive panel can be the original next-chapter panel, or the observed no-next latest-episode panel: exactly one visible last-page root, direct three-action block with exact labels お気に入り / いいね / コメント, a visible direct recommendation block with the expected heading, and exactly one shown matching viewer title. The latter title may be below the viewport; hidden titles and ambiguous/partial panels are rejected. It requires no next-chapter link/panel, never infers END from their absence, and never clicks any action or recommendation. First-party `chapterMainName` remains bound to the freshly verified listing label. Optional `chapterSubName` is bound separately; the viewer title must match the whitespace-normalized main title plus subtitle. Absent/null subtitles are empty; other non-string subtitles and subtitle drift fail closed.

The initial body group is bound to the native boolean `viewerData.isFirstPageBlank`: `true` requires body index `(0,)`, and `false` requires `(0, 1)`. Bounded anonymous probes observed chapter 80641 with `true` and a single first page, and chapter 23325 with `false` and the first pair `(0,1)`. The chapter 23325 projection has body indices 0-14, linked extra 15, `googleAds` 16, and `lastPage` 17. The false value was inherited through the viewer-data prototype in the observed page and is read as a normal JavaScript boolean; the adapter does not require an own property. A missing/nonboolean flag, a flag change after binding, or a false-mode opening with only one mounted half cannot be captured. Both `(0,)` and `(1,)` remain loading until the complete first pair is stable. Synthetic browser tests cover inherited false, pair restore, delayed and permanently missing left/right halves, flag absence/type/drift, all 15 body pages through positive END, and the final `(14, linked-extra 15)` spread while excluding the extra from capture; they also retain the original true/single-page mode. The first Phase 05 normal Batch attempt for chapter 23325 failed during initialization with `ComicFUZ reader did not restore to its first body page`; a later normal Batch run completed 15 pages and is audited below.

During `wait_for_change` only, a pending page turn may contain a transient three- or four-row snapshot when it is a duplicate-free contiguous subset of the exact last-rendered and next expected rendered groups, represents both groups, and has at least one not-ready row. Every row remains joined to a known native index/role; descriptor dimensions are checked when its image has loaded, and ready images retain their source and visual-safety checks. The adapter resets the stability counter and waits under the existing deadline; it never captures the overlap. Other wide shapes fail closed, while initialize, detect, identity, and capture continue to enforce the normal one/two-row contract. This site-local exception is limited to the observed transitions; UUL group alignment remains synthetic; it does not generalize to arbitrary wider spreads. Synthetic tests assert the exact three-image transition with all images loaded but clipped outer rows and a ready middle row, a four-image union, final body-plus-extra settlement, strict capture/state guards, persistent overlap timeout without Artifact/ZIP, malformed indices/roles, all-ready wide rejection, ready visual-effect rejection and native-dimension mismatch rejection. The affected ComicFUZ/CLI selection passed 104 tests with no skips; the final clipped-overlap and two additional negative variants passed 5 focused tests with no skips. Independent code review passed with BLOCKING=0 (13 selected tests), and the fresh normal CLI retry for chapter 80641 passed as documented below.

END requires one of the positive same-episode panels described above, cleared/matching rendered shells, and completed capture of every native-prefix body index. It is never inferred from count, dimensions, alt ordering, or a quiet viewport. The original 2026-10-13 isolated run produced ten body JPEGs.

A previous isolated 11-JPEG ZIP is rejected: Root's independent audit found its last member was a recommendation image for another work. The corrected isolated run on 2026-10-13 saved exactly ten body JPEGs and reached positive END. Root independently decoded all archive members, checked CRC and unique hashes, and visually checked first/middle/last samples; the final member is chapter body. A viewer-delivered blob JPEG probe verified complete framing, native dimensions, and sampled browser-decoded pixel equality. This proves current viewer-delivered bytes only; it does not prove upstream publisher-master identity. If exact complete blob bytes are unavailable, the adapter captures the current authorized `HTMLImageElement` at its natural pixel dimensions into PNG and rechecks node/source identity. The site AccessProfile includes the public host, `api.comic-fuz.com`, and the observed image host for generic AccessGuard monitoring; adapter capture does not invoke resource or charge APIs. The original public-free runbook deferred charge, ticket and medal handling within its free-only scope; current Work Ticket support is described at the start of this note.

Image capture rejects filters, masks, crop, opacity, blend, rotation/reflection, perspective, individual `rotate`/`scale`/`translate`, legacy clip, and unverified object-fit. Only no effect or positive axis-aligned 2D transforms are allowed. After common page-role and episode-identity validation, capture stops only if neither verified viewer-delivered source bytes nor safe native-pixel PNG readback is available. Viewer response observation is limited to 16 entries, a 2-second body-read deadline, and 4 MiB declared and returned body limits. Playwright `Response.body()` buffers before return, so the returned-size limit cannot bound pre-return memory. Reads and listeners are canceled or cleared at failure, END, and page close. Adapter manifests/metadata omit blob and signed source URLs; this is not a guarantee about generic Core diagnostics. The safe first-party projection omits signed image URLs, leaving same-dimension descriptor replacement unverified by descriptor-to-blob URL hash comparison; native index, role, title, dimensions, current image binding, and geometry are checked.

Phase 03 implementation review and isolated live artifact verification are recorded in `runbooks/comicfuz-free/PROGRESS.md`; Reviewer reported BLOCKING=0, Tester and Root's archive audits passed, and Lead accepted the phase. Phase 04 direct-only Batch policy and registry passed independent review with BLOCKING=0. Charge/ticket/medal behavior remains deferred.

## Phase 05 current status (2026-10-13)

The first isolated normal Batch attempt for chapter 23325 (global position 3) failed during initialization with `ComicFUZ reader did not restore to its first body page`; the original diagnostic log confirms this error, not an unsupported-spread error. A bounded follow-up probe established the native false-mode opening pair `(0,1)`, which is now implemented and independently reviewed. A subsequent normal CLI Batch run completed 15 JPEG pages and reached END. Its ZIP contains 15 decodable 1350x1915 JPEG members with passing CRC and unique payload hashes; the Catalog Artifact SHA-256 and byte size match the archive. The pre-package QA manifest copy was not captured for this successful run, so comparison of saved archive members against the manifest at packaging time is still unverified.

Chapter 80641 (global position 33) initially had multiple normal-CLI failures after five captures with `ComicFUZ visible page spread has an unsupported shape`. A saved error-only snapshot showed a transient contiguous overlap `[3,4,5]` while a page turn was pending; the site-local wait-only fix now waits for the exact expected next spread under the existing deadline, without allowing overlap capture or relaxing detection/capture guards. A fresh normal Batch retry completed ten body JPEGs and reached positive END. The pre-package manifest snapshot is `output/comicfuz_experiment/phase05-tester-20261013/final-fix-80641/qa/manifest-before-package.json`; its audit passed at `.../qa/final-archive-manifest-audit.json`. Root independently audited the ZIP against both the manifest and the Phase 03 reference archive: 10 ordered 1353x1920 JPEGs, CRC PASS, 10 unique SHA-256 values, and all page payloads byte-equal to the reference. Archive SHA-256: `44c92fc64d3c7b3fbb2e8f1c8ff7959354510f370444280fec9c851cfade4836`. An earlier validator-logging diagnostic success remains timing-sensitive and is not treated as normal-CLI evidence. The successful retry verifies this sampled shape; it does not guarantee universal or long-term repeatability. The other two currently free candidates, chapters 23142 and 23002, were not crawled.

## Historical Phase 04 snapshot (2026-10-13; superseded by Phase 02 above)

At the original Phase 04 checkpoint on `main`, `ComicFuzSitePolicy` admitted only sources where `site=comicfuz`, `available=true`, and `access_mode=free`; its only strategy was `direct`. The current Work Ticket branch extends Discovery and policy as described at the top of this note. The historical tests and live captures below describe the original free-only implementation and do not establish current quota entry support.

The CLI Batch adapter and Site Policy registries now include ComicFUZ. Batch reads optional `COMICFUZ_WORK_URL` from the selected environment file and otherwise derives the canonical same-work listing from the validated composite Catalog identity; any supplied URL must match the target work. The adapter validates the same-work public listing and exact current free row before opening the viewer. `batch plan` uses Catalog position and provisional archive numbering; `batch run` uses the standard BatchExecutor, Runner, ZIP packager, Artifact, and Completed lifecycle. The original public-free Phase 04 did not change shared Core or Catalog schema; shared Catalog v7 now automatically reflects acquisition scope through Discovery, without a mandatory sync gate. Charge/ticket/medal handling was deferred by that historical free-only phase; current Work Ticket support is described at the start of this note.

Synthetic policy/planner and browser-backed Batch integration cover the allowed/rejected access states, direct-only resource contract, global display-position prefixes, Discovery-to-Catalog-to-Plan-to-Runner-to-ZIP completion, rediscovery/replan retention of the completed artifact, loss of free proof before reader entry, route drift, unknown END, and packaging failure. Failed Batch attempts leave the Item pending with a failed CrawlRun and no Artifact. Reviewer selected 20 tests and reported 20 passed, 0 skipped, BLOCKING=0. Phase 05 isolated E2E is complete; the final overall Reviewer gate passed with BLOCKING=0 and the Lead accepted Phases 01-05. The original implementation commit `4b64a3c` is now included in `main`.


Phase 04 modal diagnostic on Work 3152 / chapter 46873: one Page navigation and
one target-row selection, zero CTA/other-control clicks. Native ticket state was
available before and unchanged after selection; `rental_value=""` with
`rental_present=false` is the observed strict generated-prototype empty default,
not unknown. The modal had an exact enabled CTA, a target title `p`, one price
`p.Dialog_items__amount__*` with direct text `1`, and exactly the known app,
comments, and Cancel controls. The production helper's old count of 29 came
from the page-level ancestor that included background links; the new root
`Dialog_modal` isolates it. Sanitized evidence is in
`runbooks/comicfuz-work-ticket/PROGRESS.md` and the linked metadata artifact.
No real ticket has been consumed, and the one viewer POST/200 event's request
flags are unknown.

# Zebrack Z0/Z1/Z2 viewer probe と production adapter 現行ノート

## Z6 current implementation snapshot (2026-09-30)

This section is the current authority for the implementation after the Z6
Batch orchestration change. Older Z5 live-verification sections below remain
historical observations and are superseded where they describe the former
`access_granted_until=NULL` policy or candidate-by-candidate planning.

Catalog schema version 5 is unchanged. No migration, table, or column was
added. Discovery still keeps broad Zeblack `quota` classification for POINT,
TICKET_UNAVAILABLE, TICKET_AVAILABLE, and RENTAL. For an observed RENTAL
ChapterV3 with `remainingRentalTime > 0`, it stores the current observation
time plus that remaining duration in the existing
`access_granted_until` field and sets the existing observed-grant contract.
For every explicitly observed non-RENTAL status it clears a stale observed
grant through the same Discovery refresh contract. Item status is preserved,
including completed Items. Latest-first ordering, bounded boundaries, exact
DOM/protobuf set validation, and incremental behavior are unchanged.

`ZeblackSitePolicy` treats a future `access_granted_until` on a quota Source
as `direct / active_rental / consumes_quota=False`. Confirmed Work Ticket
consumption uses `consumed_at + 71 hours` for the local grant deadline. The
existing `resource_state_scope("work_ticket")` remains `None`.

The site-owned Work Ticket resolver receives only pending quota/work-ticket
Batch candidates. It groups by Work/title, loads one live chapter/list
protobuf snapshot per title, reuses `discovery_protobuf.py`, and intersects
live `TICKET_AVAILABLE` IDs with Catalog `Source.external_id` values. It
preserves snapshot order and selects the first matching pending candidate.
Completed or missing Catalog targets are never used as an implicit fallback;
missing matches return `work_ticket_target_not_in_catalog`, while an empty
ticket set returns `work_ticket_unavailable`. The selected candidate retains
the existing production preflight and bounded modal/direct-viewer guards.

Normal Zeblack Batch now runs `direct -> grant-access -> one replan direct`.
Grant-access uses the existing grant-only executor and creates no capture,
package, Artifact, or Item completion. The post-grant direct phase crawls
only newly active Sources, and no further grant loop runs. Normal `--limit`
is a final crawl/package Item-slot limit; grant-only `--limit` counts selected
grant attempts, not read-only resolver snapshots. `inter_candidate_delay_ms`,
page pacing, AccessGuard, 403/429/challenge/CAPTCHA handling, and metrics are
kept active for resolver and production attempts.

The former Z5 behavior and live verification records below are retained as
history. This Z6 implementation was validated with synthetic/unit and
browser-backed existing tests only; no real Work Ticket was consumed.

## Z5 Site Policy / runtime Work Ticket status (2026-09-30)

`ZeblackSitePolicy` is implemented and registered for Batch planning. The
policy keeps one supported access resource, `work_ticket`, and uses:

```text
quota_scope=work
quota_limit=None
quota_commit_mode=after_observed_consumption
resource_state_scope=None
access_grant_until=None
```

`FREE` Catalog sources plan as `direct`. Broad Catalog `quota` sources plan
as `quota` / `work_ticket`; `paid`, `unknown`, unavailable, and unverified
`owned` sources are skipped. Work-scoped candidates are ordered oldest-first
by the existing numeric item order fallback. No local 23-hour cooldown or
work-wide ticket capacity is inferred, so multiple candidates in one Work
remain in the plan.

For an explicit Zeblack quota run, `CrawlerRunner` first uses the Adapter's
initial-navigation hook to enter the canonical
`/title/{title_id}/chapter/list` while keeping the viewer URL as the crawl
target. The existing `observe_zeblack_live_access()` then performs its bounded
site-local list navigation and observes the page-triggered
`title_chapter_list` protobuf, so the current implementation loads chapter/list
twice. It reuses the production ChapterV3 decoder, does not call
DiscoveryService, and does not update Catalog. The target chapter must be
present. The live `ConsumptionStatus` and target `mainName` are authoritative,
and the current `TICKET_AVAILABLE` chapter IDs are retained for pass-local skip
decisions:

```text
target unavailable + another ticket available -> work_ticket_not_available_for_chapter
target unavailable + no ticket available     -> work_ticket_unavailable, stop pass
unknown status                                -> fail closed
```

For `TICKET_AVAILABLE`, only the bundle-observed exact text
`チケットを使って読む` is eligible. The Adapter validates one visible target
row and one exact visible `mainName` descendant, clicks that chapter control
only when the control itself and its ancestors contain no `a[href]` direct-link
ancestor (relative hrefs are rejected too). After that click it requires the
URL to remain the exact chapter-list URL, then finds a visible common DOM
ancestor containing the exact target mainName, ticket control, and exact
`キャンセル` control. CSS-module modal class fragments remain diagnostic only.
Work Ticket entry accepts only that modal scope; the former page-global ticket
control fallback is not supported. The ticket control must be the single
visible/enabled exact control in that bounded scope, with no visible
point/item/coin/purchase control.
The Adapter sets `_ticket_click_attempted` before the consuming click and never
retries it. After the click, it requires navigation to the same target viewer
and stable same-chapter `page_N` content before recording
`AccessConsumption(consumed=True, resource="work_ticket")` with a UTC-aware
timestamp. A POINT chapter exposes the distinct `ポイントを使って読む`
action, which is never a Work Ticket fallback. Loading, timeout, unknown UI,
ambiguous identity, and unexpected navigation remain fail-closed outcomes.

`FREE` / `RENTAL` live statuses go directly from chapter/list to the canonical
target viewer without opening the ticket modal. `entry_only` returns
`work_ticket_not_needed` before that viewer navigation. Direct/auto runs keep
the viewer as their initial URL and retain the preexisting viewer flow.

`--grant-only work_ticket` uses the generic entry-only path, persists only
confirmed observed consumption, leaves the Item pending, and creates no
content package. `--grant-only all` resolves to the single Work Ticket pass.
`batch run --site zeblack` uses the existing generic Executor; no Zeblack
branch was added to Batch Core.

### Z5 confirmation-modal lookup performance fix (2026-09-30)

The first final production `grant-only work_ticket` attempt for title `3890`,
chapter `58493` reached the confirmation modal after one target chapter click,
but ticket consumption remained zero. The production modal validation timed out
because `_find_ticket_modal_scope()` used `_exact_leaf_text_matches(page, ...)`
and enumerated the full live DOM; the failure occurred around
`locator("*").nth(1652)`.

The Adapter now starts from one visible exact `チケットを使って読む`
candidate obtained through Playwright's exact-text locator, then walks only
that element's ancestors with a maximum depth of 12. Each bounded ancestor
must contain exactly one visible target `mainName`, ticket control, and
`キャンセル`, and must contain no point/item/coin/purchase control. `BODY` and
`HTML` are never accepted as modal scopes. The existing direct-link guard,
single-click guards, exact ticket validation, and stable viewer-content
consumption rule remain unchanged.

The fix is covered by browser-backed normal and 2,500-node large-DOM flows,
ambiguous ticket, missing modal identity, paid-control contamination, and
direct-link rejection cases. The final production Work Ticket consumption
verification is recorded below as verified.

### Z5-5 controlled live verification: title 3890 / chapter 58493 (2026-09-30)

The latest `main` was reviewed at commit `f475a75`. The shared Crawler Chrome
was used through `http://127.0.0.1:9222`; no credentials, cookies, storage
state, request bodies, or tokens were read or saved. This was a research-only
check and did not modify the production implementation.

The read-only `title_chapter_list` observation for title `3890` decoded 201
chapters:

```text
FREE=24, RENTAL=0, TICKET_AVAILABLE=1,
TICKET_UNAVAILABLE=0, POINT=150, COIN=26,
TICKET_UNAVAILABLE_COIN_ONLY=0, UNKNOWN=0
oldest/current ticket candidate: chapter 58493
mainName: 第25話 プロの実力
chapter-list: https://zebrack-comic.shueisha.co.jp/title/3890/chapter/list
```

The target `#chapter58493` existed once and was visible. Its root was a
pointer-cursor `div` with no semantic link/button descendant. Clicking the root
once kept the page on chapter-list and did not open the expected modal. DOM
inspection showed the visible chapter-title `<p>` as the user-facing pointer
target. Clicking `#chapter58493 p` once opened the modal while keeping the URL
on chapter-list.

The modal has no `role=dialog`, `alertdialog`, native `dialog`, or
`aria-modal=true`; its observed container was the visible CSS-module element
`div[class*="_modalBase_"]`, with nested `_animation_`, `_container_`, and
`_inner_` elements. The modal text was:

```text
支払い・提供時期
キャンセル・申込期限について
第25話 プロの実力
所持チケット
× 1枚
チケットを使って読む
コメントを見る
キャンセル
```

The exact ticket control was one visible `div` with text
`チケットを使って読む`, pointer cursor, and an `onclick` function. The
exact cancel control was one visible `button` with text `キャンセル`. POINT,
ITEM, COIN, and coin-purchase controls were all absent. The CSS-module class
names were recorded as diagnostics only; a production selector should use the
exact text within the selected chapter modal and fail closed on ambiguity.

The exact cancel control was clicked once. The modal disappeared, the URL
remained `/title/3890/chapter/list`, and the subsequent read-only protobuf was
unchanged: `58493=TICKET_AVAILABLE`, `TICKET_AVAILABLE=[58493]`, with the
same status counts. No `POST /api/v3/chapter_viewer` was observed. No ticket,
point, item, coin, or purchase control was clicked, and Work Ticket consumption
remained zero.

This verifies the safe UI sequence for this title as:

```text
chapter/list
-> #chapter58493 p
-> confirmation modal
-> exact ticket control (consuming action, not clicked here)
-> viewer
```

The title-402 direct-navigation result remains the separate warning: direct
viewer navigation can consume a ticket, while opening this chapter-list modal
and cancelling it did not. The production adapter was intentionally left
unchanged; hashed CSS classes are not approved as production selectors.

### Z5-6 final production Work Ticket verification: title 3890 / chapter 58493 (2026-09-30)

The latest `main` was reviewed at commit
`002eeb4e3250d513e4c2d4ebb3fdd5c04cd1c6d2`
(`Fix Zeblack Work Ticket modal lookup`). The shared Crawler Chrome was used
through `http://127.0.0.1:9222`. No viewer URL was opened during either
read-only preflight; the production run entered through chapter/list. No
credentials, cookies, storage state, request bodies, or tokens were saved or
reported.

Target:

```text
title_id=3890
chapter_id=58493
mainName=第25話 プロの実力
chapter-list=https://zebrack-comic.shueisha.co.jp/title/3890/chapter/list
viewer=https://zebrack-comic.shueisha.co.jp/title/3890/chapter/58493/viewer
```

Before the production run, the read-only `title_chapter_list` protobuf decoded
201 chapters:

```text
target 58493=TICKET_AVAILABLE
TICKET_AVAILABLE=[58493]
FREE=24, RENTAL=0, TICKET_AVAILABLE=1,
POINT=150, COIN=26,
TICKET_UNAVAILABLE=0, TICKET_UNAVAILABLE_COIN_ONLY=0, UNKNOWN=0
```

The reused temporary Catalog matched the target identity. Before execution,
`Item=pending`, `Source.access_mode=quota`, `Source.available=true`,
`Source.quota_started_at=NULL`, `Source.access_granted_until=NULL`,
`Artifact=0`, `QuotaResourceState=0`, and two earlier failed CrawlRuns were
preserved. The read-only Batch Plan contained exactly one candidate with
`locator=.../title/3890/chapter/58493/viewer`,
`access_strategy=quota`, `quota_resource=work_ticket`, `quota_scope=work`,
`quota_limit=NULL`, and
`quota_commit_mode=after_observed_consumption`.

The production command was executed exactly once:

```text
batch run --site zeblack --grant-only work_ticket --limit 1
```

The observed entry sequence was:

```text
chapter/list
-> live TICKET_AVAILABLE preflight
-> #chapter58493 exact mainName selection (one click)
-> chapter/list confirmation modal
-> bounded ticket-anchored modal lookup
-> exact チケットを使って読む (one consuming click)
-> target viewer 3890 / 58493
-> stable in-viewport page_N content
```

The modal validation passed with exactly one visible target identity, exact
`チケットを使って読む`, and exact `キャンセル`, with zero visible point,
item, coin, or purchase controls in scope. The implementation bound was
`MAX_MODAL_ANCESTOR_DEPTH=12`; the successful run did not persist the actual
ancestor depth. The previous page-wide `locator("*").nth(...)` timeout did not
recur.

The strict viewer identity matched `title_id=3890` and `chapter_id=58493`.
Stable `page_N` content was confirmed for entry-only validation, but no page
was captured. The production result was `entry_confirmed` with
`resource_consumed=true`; `AccessConsumption` was
`consumed=True, resource=work_ticket`.

After execution, the Catalog contained `Source.quota_started_at != NULL`
(`2026-09-30T16:37:19.291767+09:00`), while
`access_granted_until=NULL` as expected from the current default policy.
`QuotaResourceState` remained absent because
`resource_state_scope("work_ticket")=None`. The new CrawlRun was
`status=succeeded`, `page_count=0`, `stop_reason=entry_confirmed`; the two
earlier failed runs were unchanged. `Item` remained `pending` and
`Artifact=0`.

The post-run read-only protobuf still used chapter/list only and reported:

```text
target 58493=RENTAL
remainingRentalTime=259113
TICKET_AVAILABLE=[]
FREE=24, RENTAL=1, TICKET_AVAILABLE=0,
POINT=150, COIN=26,
TICKET_UNAVAILABLE=0, TICKET_UNAVAILABLE_COIN_ONLY=0, UNKNOWN=0
```

The three signals agree: Adapter `AccessConsumption.consumed=True`, Catalog
`quota_started_at` committed, and live protobuf `TICKET_AVAILABLE -> RENTAL`.
Exactly one Work Ticket was consumed. Current status:
**production-managed Work Ticket consumption verified**.

### Z5-4 controlled live verification: title 402 / chapter 341029 (2026-09-30)

The latest `main` was reviewed at commit `8c84b5a`. The shared Crawler Chrome
was used through `http://127.0.0.1:9222`; no credentials, cookies, storage
state, request bodies, or tokens were read or saved. This was a research-only
check and did not modify the production implementation.

The read-only `title_chapter_list` observation for title `402` decoded 167
chapters:

```text
FREE=3, RENTAL=0, TICKET_AVAILABLE=1,
TICKET_UNAVAILABLE=0, POINT=139, COIN=24,
TICKET_UNAVAILABLE_COIN_ONLY=0, UNKNOWN=0
oldest/current ticket candidate: chapter 341029
mainName: 第4話 電話できないッ!!
viewer: https://zebrack-comic.shueisha.co.jp/title/402/chapter/341029/viewer
```

The exact DOM target `#chapter341029` existed once and was visible. It was
clicked exactly once. The URL remained the chapter-list URL, no new page was
opened, no visible ticket/point/item/coin/purchase control or dialog appeared,
and the read-only protobuf still reported `341029=TICKET_AVAILABLE` with one
available ticket. Therefore the chapter-list row click itself was not observed
to consume the ticket in this run.

Because the target remained available, one direct navigation to the viewer URL
was performed without clicking any control. The resulting viewer URL was
correct, three visible `page_N` images were present, and the exact ticket,
point, item, coin, and coin-purchase control counts were all zero. A subsequent
read-only chapter-list protobuf observation reported:

```text
FREE=3, RENTAL=1, TICKET_AVAILABLE=0,
TICKET_UNAVAILABLE=0, POINT=139, COIN=24,
TICKET_UNAVAILABLE_COIN_ONLY=0, UNKNOWN=0
target 341029: RENTAL, remainingRentalTime=259195
```

The direct navigation produced a document `GET` followed by a successful
`POST /api/v3/chapter_viewer` (`200`, `application/protobuf`) and page-image
requests. Request paths were recorded without query strings or bodies. The
status transition from `TICKET_AVAILABLE` to `RENTAL` immediately after this
direct navigation is strong live evidence that direct viewer navigation can
consume a Work Ticket even when the exact ticket control is never clicked.
The endpoint name and request ordering are supporting evidence; the protobuf
state transition is the authority for this conclusion.

This supersedes the earlier general assumption that selecting/opening a
`TICKET_AVAILABLE` viewer only reveals the ticket action. The chapter-list row
click and direct viewer URL must be treated as distinct operations: the former
was non-consuming in this check, while the latter consumed the only available
ticket. The current production adapter still contains the prior assumption and
was intentionally left unchanged; production quota entry should not start from
a direct viewer URL until the adapter flow is redesigned and re-verified.

### Z5-3 controlled live verification: title 66 / chapter 6077 (2026-09-30)

The latest `main` was reviewed at commit `e990c97`. The shared Crawler Chrome
was used through `http://127.0.0.1:9222`; no credentials, cookies, or storage
state were read or saved. A read-only `title_chapter_list` observation for
title `66` decoded 229 chapters:

```text
FREE=3, RENTAL=0, TICKET_AVAILABLE=1,
TICKET_UNAVAILABLE=0, POINT=193, COIN=32,
TICKET_UNAVAILABLE_COIN_ONLY=0, UNKNOWN=0
oldest/current ticket candidate: chapter 6077 / viewer
  https://zebrack-comic.shueisha.co.jp/title/66/chapter/6077/viewer
```

The title-top ticket indicator was recorded as a diagnostic signal only. The
temporary singleton Discovery used the chapter-list URL with identical
`from_url` and `through_url` viewer boundaries and completed with
`observed=1`, `complete=True`, `external_id=6077`, and `access_mode=quota`.
The read-only Batch plan contained exactly one candidate:
`eligible=1`, `quota=1`, `quota_resource=work_ticket`, and
`quota_commit_mode=after_observed_consumption`. The initial Catalog state was
`Item=pending`, `quota_started_at=NULL`, `access_granted_until=NULL`, with no
CrawlRun or Artifact.

The final read-only preflight immediately before execution still observed
target `6077=TICKET_AVAILABLE` and `TICKET_AVAILABLE=[6077]`. The production
command was run with `--grant-only work_ticket --limit 1`. It did not click the
ticket control. The Adapter debug record instead shows:

```text
live target status=RENTAL
TICKET_AVAILABLE count=0
preexisting_accessible=true
ticket_click_attempted=false
ticket_confirmation_state=preexisting_accessible
AccessConsumption.consumed=false
```

The grant-only CrawlRun was therefore safely skipped as
`work_ticket_not_needed`; no quota timestamp or Artifact was persisted, and
the Item remained pending at that point. Relevant run diagnostics contained
viewer/list loading and source-image requests only; no ticket click was
attempted and no point, coin, item, or purchase fallback was used. The
transition from the immediate preflight `TICKET_AVAILABLE` state to the
grant-run `RENTAL` state cannot be attributed to an exact ticket action in
this run, so Work Ticket consumption is **NOT VERIFIED**.

After that live state transition, a separate normal Batch run was performed
against the same temporary Catalog. It observed the target as `RENTAL`, did
not click a ticket, captured 19 source-native JPEG pages at `760x1200`, and
stopped at `next_content`. The ZIP Artifact is present under
`output/zeblack_z5_title66/Books/`; the Item is `completed`, while
`quota_started_at` remains NULL because no confirmed Work Ticket consumption
was reported. The post-attempt protobuf snapshot is
`FREE=3, RENTAL=1, TICKET_AVAILABLE=0, POINT=193, COIN=32`.

Title 66 therefore verifies singleton Discovery, Batch planning, safe
grant-only fail-closed behavior, and normal RENTAL capture, but does not meet
the Z5 completion criterion for exact Work Ticket consumption. Final status:
**BLOCKED / Work Ticket consumption not verified**.

### Z5-2 controlled live verification: title 53 / chapter 4844 (2026-09-30)

This is the current title-53 result and supersedes neither the generic
two-step Work Ticket semantics above nor the earlier title-5123 history below.
The shared Crawler Chrome was used through
`http://127.0.0.1:9222`; no credentials, cookies, or storage state were read
or saved.

The read-only title-53 protobuf observation contained 411 chapters. Before
the grant-only attempt the status counts were:

```text
FREE=3, TICKET_AVAILABLE=1, POINT=377, COIN=30, RENTAL=0
oldest/current ticket candidate: chapter 4844 / #4 標的4 退学クライシス
```

The title top independently showed the diagnostic CTA
`チケットでさっそく読もう！` and `× 1`. This CTA/count is diagnostic only;
the chapter-list protobuf remained the runtime authority. Full read-only
Discovery observed 411 records. A bounded singleton Discovery for chapter
4844 observed one record with `complete=True`; the read-only Batch plan was
`eligible=1`, `quota=1`, resource `work_ticket`.

The first grant-only run exposed a production bug: locked viewer `page_N`
placeholders were being treated as preexisting readable content before the
live protobuf status was consulted. The adapter now waits for viewer hydration,
consults live status first, and only then considers preexisting content for
`FREE`/`RENTAL`. Viewer readiness recognizes the known non-ticket access gates
before protobuf preflight, while those gates remain hydration signals rather
than access authority. Unit coverage asserts that `TICKET_AVAILABLE` wins over
those placeholders. The exact ticket control was never clicked in this
verification:
both the adapter debug metadata and the run records show
`ticket_click_attempted=false` and `AccessConsumption.consumed=false`.

After the read-only/preflight sequence, the post-observation was:

```text
FREE=3, RENTAL=1, TICKET_AVAILABLE=0, POINT=377, COIN=30
target 4844: RENTAL / 標的4 退学クライシス
```

The transition `TICKET_AVAILABLE -> RENTAL` is not attributed to the
read-only checks or the skipped grant-only runs because no exact ticket click
was recorded. No point, coin, or purchase fallback was used, and no local
quota timestamp was committed.

With the target now `RENTAL`, a normal `batch run --site zeblack --limit 1`
completed without another ticket action. The viewer needed two site-local
bounded interstitial states: a visible ad spread and the volume-purchase /
next-story spreads. These are advanced with the existing non-clicking
`ArrowLeft` AD path. The explicit in-viewport `次の話を読む` signal remains
required for terminal `NEXT_CONTENT`; last-page interstitial detection is
visible/in-viewport only, and page counters or DOM-only offscreen markers are
not sufficient. The successful output contains 19 source-native
JPEG entries, all `760x1200`, and a ZIP Artifact. Catalog `Item=completed`,
the successful CrawlRun stop reason is `next_content`, and the ZIP is at
`output/zeblack_z5_title53/Books/漫画/Zeblack Z5 title 53  chapter 4/`.

The title-top post-check showed the target chapter with an active rental
remaining-time label and the diagnostic ticket balance `× 0`; it did not
override the protobuf result. Production-ready normal RENTAL capture is
verified. Production Work Ticket consumption for title 53 remains
**NOT VERIFIED**, because the live target changed before the exact consuming
control could be safely reached.

The exact ticket control and point/coin distinction are supported by
read-only inspection of the current public frontend bundle. On 2026-09-30,
the earlier title
`5123` protobuf status was observed. Before the preflight, the counts were
`FREE=16`, `TICKET_AVAILABLE=3`, `POINT=188`, `COIN=43`, and `RENTAL=0`.
The oldest-first candidate was chapter `198365` (`#17 問題ないです`). Its
viewer identity matched, but one visible/in-viewport `page_0` blob image was
already present and the exact ticket text was visible zero times. Point,
item, coin, and purchase controls were also zero; no dialog was visible.
The production fail-closed path stopped before any ticket click, so no
`AccessConsumption` was recorded and no grant-only run was executed. Under the
human-observed two-step behavior, that means this check did not consume a
ticket.

After the stopped preflight, a later read-only protobuf observation reported
chapter `198365` as `RENTAL`, `TICKET_AVAILABLE=0`, and counts
`RENTAL=1`, `POINT=190`. This transition is not attributed to the check:
the verified flow did not click `チケットを使って読む`, and the human
observation says that the preceding chapter selection/viewer opening is not
the consuming action. The temporary singleton Discovery/Batch plan completed
read-only (`observed=1`, `complete=True`, `eligible=1`, `quota=1`,
`work_ticket`), while the temporary Catalog remained `pending` with no quota
timestamp, CrawlRun, or Artifact.

The detailed operator artifacts are in `output/zeblack_z5_live/`. They are
temporary and contain no credentials, cookies, or storage state. Explicit
ticket consumption remains unverified and was intentionally not performed.
The next experiment may use another account/address; it must preserve the
two-step distinction and never click the point action.

### Z5-1 controlled live verification (2026-09-30)

Target: title `5123`, oldest-first candidate chapter `198365` (`#17
問題ないです`). Shared Crawler Chrome was verified through the repository CDP
endpoint `http://127.0.0.1:9222`; authentication data was not read or saved.

```text
before status counts: FREE=16, RENTAL=0, TICKET_AVAILABLE=3,
  TICKET_UNAVAILABLE=0, POINT=188, COIN=43,
  TICKET_UNAVAILABLE_COIN_ONLY=0, UNKNOWN=0
before TICKET_AVAILABLE: 198365 (#17 問題ないです),
  224191 (#26 応援するよ), 226849 (#27 脈アリ)

viewer identity: title=5123, chapter=198365 (matched)
preexisting content: true; visible page_N rows=1 (page_0, blob, 760x1194)
exact ticket control: visible count=0, enabled=false
paid controls: point=0, item=0, coin=0, coin purchase=0
dialog before click: 0
ticket_click_attempted: false
chapter selection/viewer navigation: performed; ticket not consumed by this step
operational conclusion: no ticket consumption; exact ticket action was not clicked

singleton Discovery: observed=1, complete=True, external_id=198365
Batch plan: eligible=1, quota=1, resource=work_ticket,
  quota_commit_mode=after_observed_consumption
Catalog before grant: Item=pending, quota_started_at=NULL,
  access_granted_until=NULL, CrawlRun=0, Artifact=0

after status counts: FREE=16, RENTAL=1, TICKET_AVAILABLE=0,
  TICKET_UNAVAILABLE=0, POINT=190, COIN=43,
  TICKET_UNAVAILABLE_COIN_ONLY=0, UNKNOWN=0
target observed transition: TICKET_AVAILABLE -> RENTAL
TICKET_AVAILABLE ids after: none
causality: not attributed to this verification; no exact ticket action was clicked
POINT negative check: not run after unexpected preflight state
package: not generated

The earlier report's observation that no ticket action was clicked was correct,
but its interpretation of the later status transition was left ambiguous. The
human-observed UI sequence resolves the ambiguity: only the exact ticket action
consumes a Work Ticket, while the point action is never clicked.
```

## Z4-1 production Discovery status (2026-09-30)

`ZeblackDiscoveryAdapter` is implemented and registered under `zeblack` in
the Discovery registry. Z5 additionally registers the Zeblack Site Policy
for Batch planning; Discovery and Batch remain separate boundaries.

The Watchlist target is the strict HTTPS URL
`/title/{title_id}/chapter/list`. The adapter installs a response listener
before navigation and accepts only the exact
`api2.zebrack-comic.com/api/v3/title_chapter_list` response with status 200,
`application/protobuf`, and a body no larger than 4 MiB. Duplicate responses
are accepted only when their raw bytes or decoded ChapterV3 content agree;
conflicting or malformed responses fail closed.

DOM `id="chapter{chapter_id}"` rows provide identity and observed order.
The production decoder recognizes only title-correlated ChapterV3 messages
with numeric `id`, expected `titleId`, non-empty `mainName`, and at least one
additional evidenced ChapterV3 field. It decodes `remainingRentalTime`,
`status`, and `price`; an absent status is protobuf default `FREE` (0), and
unknown status values remain `unknown` at the Catalog boundary. DOM and
protobuf IDs must be duplicate-free and exactly equal in both directions.

Validated DOM order is reversed to the canonical latest-first Discovery
order. Numeric `mainName` labels are used only as an oldest-first sanity
check; special/non-numeric labels retain `order_key=None` and their raw
`order_label`. Sources use `chapter_id` as `external_id` and canonical,
query/fragment-free viewer URLs. `FREE` maps to `free`; rental, ticket, and
point statuses map to `quota`; coin and coin-only statuses map to `paid`;
unknown enum values map to `unknown`. `POINT -> quota` is a Catalog access
class only and does not consume points or infer future ticket capability.

Full and incremental Discovery use the generic service semantics. Bounded
Discovery supports inclusive `from_url` / `through_url` viewer boundaries,
validates the same `title_id`, matches boundaries by `chapter_id` only, and
buffers the complete result until listing/protobuf/set/order/boundary
validation has passed. Thus invalid scope or DOM/protobuf mismatch yields no
partial records. Dynamic POINT-to-ticket changes and rental-time units remain
unresolved live-state questions for Z5.

### Z4-1 live verification (2026-09-30)

Using the shared Crawler Chrome/CDP session and a temporary
`output/zeblack_z4_live/` Watchlist/Catalog for title `5123`:

```text
full:
  observed=250, complete=True, stopped_reason=exhausted
  sources=250, distinct external_id=250, web/default targets=250
  free=16, quota=191, paid=43, unknown=0

incremental against the full Catalog:
  observed=5, new=0, known=5
  complete=None, stopped_reason=known_streak

bounded from chapter 226849 (#27) through chapter 198365 (#17):
  observed=11, complete=True, stopped_reason=exhausted
  actual external-id slice was 226849, 224191, 220222, 218317,
  216130, 212824, 210415, 207986, 204233, 200528, 198365

reversed bounded boundaries (#17 -> #27):
  observed=0, complete=False, stopped_reason=incomplete
```

Sampled Catalog web targets were canonical query/fragment-free viewer URLs
of the form
`https://zebrack-comic.shueisha.co.jp/title/5123/chapter/{chapter_id}/viewer`.
The temporary live Catalog and Watchlist are operator artifacts only and are
not part of the repository change.

## Scope

これはゼブラック（Zebrack）の対象chapter限定のread-only viewer probe、production
Discovery、Viewer Adapter、Site Policy、Batch access entryの現行記録である。
login automationと実ticket消費は対象外である。Z0/Z1では観測できた事実と
未確認事項を分離し、POINT/COIN自動消費や23時間モデルを推測しない。

## Z3 production status (historical baseline)

Z3時点ではViewer Adapterだけをproduction実装した。site keyは`zeblack`で、通常の
`crawl --site zeblack`から利用できた。Discovery、Site Policy、ticket/access acquisition、
daily-free consumption、quota resource、login automation、next chapter clickはZ3時点では
未実装であった。現在のDiscovery / Site Policy / runtime accessは本note上部のZ4-1/Z5を参照する。

### Viewer / page order

対象viewer URLは、HTTPSの
`/title/{numeric_title_id}/chapter/{numeric_chapter_id}/viewer`だけを受け付ける。
query/hashは許容するが、host/path identityが変わった場合は自動操作を停止する。
本文候補はCSS module hashに依存せず、`img`のexact `alt=page_N`、visible、viewport内、
正の`naturalWidth`/`naturalHeight`、`blob:https://zebrack-comic.shueisha.co.jp/` sourceを
要求する。active rowsは`page_N`数値昇順で処理し、DOM orderやscreen x座標からreading orderを
補完しない。duplicate、malformed、invalid dimensions、blob欠落、ambiguous sourceはfail
closedである。

### Direct capture / fallback

`prepare_page()`はnavigation前にexact viewer-origin blob response listenerを登録する。
response bodyはasync taskとして最大128件のbounded cacheに保持する。asset transport
(`asset.zebrack-comic.com`)はcapture sourceに使わない。direct captureではcurrent spreadの
全rowについてexact blob URLのbodyを待ち、JPEG decode成功とDOM natural dimensions一致を
全件確認してから、元JPEG bytesを再encodeせず`.jpg`の`CaptureResult`として返す。一件でも
失敗すればspread全体を`CaptureUnavailableError`でfallbackへ渡し、mixed direct/locator
spreadは作らない。direct成功後は使用済みblob entryをcacheから解放する。fallbackは同じ
active `page_N` img locatorを数値昇順で返す。

### Navigation / state / identity

`go_next()`はsame-chapter URLとactive contentを再確認し、form input/textarea/select/
contenteditableにfocusがある場合は停止する。その後に`ArrowLeft`だけを送る。next chapter
button/controlはclickしない。`wait_for_change()`はURL、active page_N集合、blob source identity、
visible terminal signalをpollし、changed後の連続stable checksを要求する。no-change timeout
はENDと推測しない。

`ContentIdentity`はcurrent in-viewport page_N集合を`page_0`または`page_1+page_2`のように
数値順で表し、`page_number`は補助値である。`ContentContext`はtitle/chapter IDから
`work_id=title_id`、`chapter_id=chapter_id`を返す。

本文がactiveなら、同じDOM内に「次の話」候補があっても`CONTENT`を優先する。本文がなく、
same chapter viewer URL、直前のArrowLeft transitionがchanged+stable、かつviewport内の
visible button/controlに「次の話を読む」系の明示signalがある場合だけ`NEXT_CONTENT`とする。
page counterだけではterminalにしない。Z2で独立したEND UIは確認していないため、未確認の
END文言から`END`を生成しない。

### Z3 historical access strategy status

Z3時点では`auto`と`direct`だけを受け付け、access resource操作を行わなかった。
Z5では明示的な`quota + work_ticket`だけを追加し、`auto`でticketを自動クリック
しない。Z5のAccessProfileは`zebrack-comic.shueisha.co.jp`、
`api2.zebrack-comic.com`、`asset.zebrack-comic.com`を403/429 relevant hostとして
扱う。challenge/login detectorは追加していない。

Production unit testsとlive production crawlを実行済みである。共有Chromeを使った指定chapter
のproduction CLI runは、chapter URLを離れず`stop_state=NEXT_CONTENT`、
`stop_reason=next_content`で停止し、next chapter controlはclickしなかった。live artifactは
23枚で、direct blob JPEGが22枚保存され、最後の`page_23`はexact blob response bodyが
JPEGではなくWebP (`RIFF...WEBP`)だったため、設計どおりlocator PNG fallbackになった。
`page_22`のdirect JPEG bytesは`page_1`と同一fingerprintで、Coreの既存fingerprint dedupeに
より保存対象から除外された。このため今回のlive resultは、Z3の安全なfallback/terminal契約の
検証には成功したが、受入目標の24枚全JPEG (`24 JPG`)には未達である。WebPをJPEGへre-encode
したり、重複pageを保存するためにCoreを変更したりはしていない。
実行コマンドは、指定outputが初回失敗runで非空になったためretry用outputを使った次のもの。

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site zeblack `
  --url "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer" `
  --output-dir "output\test-zeblack-production-retry" `
  --library-dir "output\test-books" `
  --access-strategy direct --max-pages 100
```

保存画像はdirect JPEGが`760x1080`、fallback PNGが`782x1479`。最終URLは対象chapter viewer
URLのままである。

Z0/Z1/Z2のresearch-only観測と、Z3のproduction実装契約は混同しない。

## 対象URL / identity

対象は次のURLだけである。

```text
https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer
```

`title_id=118286`、`chapter_id=9265713`。probeはhostと
`/title/{title_id}/chapter/{chapter_id}/viewer`を検証し、query/hashだけの変化は
同一chapterとして記録する。別title、別chapter、別path、別hostへ遷移した場合は
自動操作を停止する。今回の実行では全stateで対象URLのままだった。

## Probe entry point / Browser Session

実装は `poc/zeblack_probe.py`。既存のshared Crawler Chromeへ
`BrowserSession` と `resolve_cdp_endpoint()`でCDP接続し、probe自身はChrome launch、
profile作成、storage state管理、loginを行わない。接続後の操作はPlaywrightのPage/
Locator/keyboardを使用した。

```powershell
.\.venv\Scripts\python.exe poc\zeblack_probe.py `
  --url "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer" `
  --output-dir "output\zeblack_probe" --steps 3
```

`--steps`は0〜3にbounded clampされる。response body候補は最大20件である。
初期artifactは `output/zeblack_probe/initial/`、state artifactは `state_000`〜である。

Z1は通常Z0と分離した明示的opt-inである。

```powershell
.\.venv\Scripts\python.exe poc\zeblack_probe.py `
  --url "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer" `
  --output-dir "output\zeblack_probe" --steps 3 --z1
```

Z1 artifactは `output/zeblack_probe/z1/` に保存し、`report.json`、
`comparison.json`、`summary.md`、`pages/page_NNN.jpg`、各stateの`z1.json`を含む。

## Live verification (2026-09-27)

shared Crawler Chromeで対象URLを実行済み。3回の通常ページ送りを行い、
`initial`、`state_000`、`state_001`、`state_002`、`state_003`を保存した。

- viewportは`1906x986` CSS pixels、devicePixelRatioは`1.5`だった。
- titleは「「真の実力はギリギリまで隠していようと思う」1話 を漫画アプリで読む | ゼブラック」だった。
- final URLはtarget URLと同一で、chapter外遷移はなかった。
- 無料、毎日無料、待てば無料、ポイント、コイン、購入、レンタル、閲覧期限、残り時間、
  次回無料時刻、利用可能、利用済み等のaccess表示は、viewerのvisible textからは観測しなかった。
  これはaccessが存在しないという意味ではなく、今回の対象URL/stateでnot observedという意味である。

## Viewer structure

本文候補はcanvasではなく`img`で描画されていた。

- 初期stateではvisible DOM `img`が12件、うち`alt=page_0`〜のpage-like imageが3件、
  in-viewportは`page_0`の1件だった。recommendation等の本文外imgも同じDOMに存在した。
- page-like imageは`blob:` URL、natural sizeは`760x1080`、初期表示サイズは概ね
  `693.84x986` CSS pixelsだった。
- viewer-like DOMには`viewer` wrapper、slide container、spread-like element、
  page container、page imageが含まれた。実際のclass/id/data-* attribute、rendered x/y、
  width/heightは各`dom.json`と`viewerTree`に保存している。CSS module hashは観測値として
  artifactに残すが、production selectorとして採用していない。
- canvasは初期および3回のnavigation後もvisibleには観測されなかった。
- CSS `background-image`候補は観測されなかった。
- cross-origin広告iframeも存在したため、frame URLを記録したが、広告frameの操作は行っていない。

したがって今回のchapterについては「page-like `img` + `blob:` sourceが観測された、canvas/
backgroundはnot observed」が確認事実である。本文が常に同じ構造であることや、他chapterへ
一般化することはまだ確認していない。

## Network observation

navigation前からrequest/responseを記録し、`initial/network.json`と各stateのnetwork deltaに
URL、method、resource type、status、content-type、content-length、timestamp、frame URL等を保存した。

本文候補として次の二種類が観測された。

1. `asset.zebrack-comic.com` の対象title/chapter/page系JPEG response。content-typeは
   `image/jpeg`だったが、保存した元bytesはPillowでJPEGとしてdecodeできなかった。
2. `blob:https://zebrack-comic.shueisha.co.jp/...` のresponse/body候補。Playwright上の
   content-typeは`text/plain`だったが、保存bytesはJPEGとしてdecodeでき、代表的に
   `760x1080`だった。

Z0ではasset responseとblob bodyをURLや時刻、byte lengthだけで一対一対応と確定していない。
asset側bodyがそのままページ画像でない可能性、blob生成前後に変換がある可能性は残すが、
scramble、暗号化、tile permutation、reconstructionの方式は未確定である。保存bodyは
diagnostic candidateであり、production captureには使っていない。

実行時は最大20件のimage-classified candidate bodyを保存し、各候補にsource URL、content-type、
byte size、encoded SHA-256、format、dimensions、decode error、相対pathを記録した。
network全体にはJSON/fetch/xhr/script等も保存している。network artifact内のsigned queryは
運用上の秘密情報としてnoteには転記していない。

## Canvas / drawImage observation

`page.add_init_script()`でnavigation前にmetadata-only hookを注入した。対象は
`CanvasRenderingContext2D.drawImage()`、`OffscreenCanvasRenderingContext2D.drawImage()`、
`createImageBitmap()`である。hookはsource type/URL/dimensions、sourceRect、destinationRect、
canvas identity、transform、globalCompositeOperation、filter、globalAlpha、sequenceだけを
boundedに記録する。

今回の実行では以下はすべてnot observedだった。

- `drawImage()` call
- `OffscreenCanvasRenderingContext2D.drawImage()` call
- `createImageBitmap()` event
- canvas mutation

従ってgeometry分類は`unknown`であり、full-frame copy、tiled、cropped、scaledのいずれも
このchapterについて結論していない。hook内でPNG/JPEG encode、base64化、hash計算、network
access、全canvas pixel copyは行っていない。

## Navigation / page-change signal

初期DOMには本文page-forward buttonが明示的には見つからず、`< 次の話`はnext-content候補
として拒否した。viewer wrapperが1件だけあり、img/canvas contentを持ち、access/next-content
語を含まないことを再確認した上で、keyboard `ArrowLeft`をpage navigationとして観測した。
click直前のDOM candidateについてtext、aria-label、title、class、href、visibility、selector
を再検証し、hrefがある場合はtarget identityも検証する。今回の3回はすべて次を満たした。

```text
changed = true
stable = true
URL     = target chapterのまま
method  = keyboard / ArrowLeft
```

固定sleepだけではなく、visible img/canvas/page-text metadataのfingerprintが変化し、続けて
2回同一fingerprintになることをbounded waitで確認した。初期ページカウンタ候補は`1 / 25`、
navigation後は順に`2 / 25`、`4 / 25`、`6 / 25`だった。これはviewerが表示するcounter
候補として記録しており、production page number authorityとはしていない。

## Spread / reading order

初期stateはpage-like imgが1件viewport内だった。後続stateでは2件が同時にviewport内に入り、
spread-like classとpage containerが確認できた。観測したin-viewport geometryは、例えば
state_001で`page_2`が左側（x約259）、`page_1`が右側（x約953）、state_002で`page_4`が
左側、`page_3`が右側だった。初期の単ページから最初の送りでpage-like image集合が
`[page_0]`から`[page_1,page_2]`へ変化し、その後の送りでは`[page_1,page_2]`、
`[page_3,page_4]`、`[page_5,page_6]`のように2枚単位の変化が観測された。

これはspread-like表示とx/y配置の事実を示すが、意味上のreading orderをZ0でproduction確定
していない。DOM上の`page_N` labelとscreen geometryの対応はartifactで確認できる。

## Identity / END / NEXT_CONTENT candidates

URL identityは全stateでtitle/chapter targetと一致した。document title、visible heading/meta、
data-*、page alt、page counter、chapter/title link候補を保存した。

初期DOMで`< 次の話`というbuttonは観測したが、next chapter/next storyの可能性があるため
クリックしていない。chapter末尾へは進んでいないため、END screen、completion state、final
page後の遷移、next chapter IDは未確認である。`1 / 25`等のcounter候補はEND判定のproduction
実装には使わない。

## Z1 live verification (2026-09-27)

shared Crawler Chromeで上記targetだけを`--z1 --steps 3`で実行した。initialを
`state_000`として、`state_001`〜`state_003`へArrowLeftでbounded navigationした。
全3回が`changed_and_stable`で、全stateのURLはtarget chapterのままだった。access、
ticket、購入、ポイント、コイン、広告、login、next chapter controlは操作していない。

### Visible page image attribution

Z1は全`img`から厳密な`alt=page_N`を抽出し、visibility、inViewport、natural size、
rendered x/y/width/height、`src`、`currentSrc`、document.imagesのDOM orderを保存した。
本文候補として採用したのは、exactな`page_N`、natural sizeが非zero、visible、viewport内で、
source URLが`blob:`であるものだけである。viewer/class hashは補助metadataであり、唯一の
authorityにはしていない。本文外画像をpage画像として推測していない。

今回のstable stateは次のpage集合だった。

```text
state_000: page_0
state_001: page_1 (x=953, 右), page_2 (x=259, 左)
state_002: page_3 (x=953, 右), page_4 (x=259, 左)
state_003: page_5 (x=953, 右), page_6 (x=259, 左)
```

各pageのnatural dimensionsは`760x1080`、表示サイズはおよそ`693.84x986` CSS pixels
だった。DOM orderはscreen左右順と同一とは限らないため、x/yからlogical orderを推測しない。

### Blob retrieval and encoded JPEG

各current stateでvisible imgのblob URLを完全一致で記録し、まず同じPage内の
`fetch(blobUrl)`を試行した。しかし今回の実サイトでは、表示中のimgが描画を継続していても、
後発の`fetch(blob:)`は全7件で`TypeError: Failed to fetch`になった。state遷移後の
lifetime checkも2件（page_0 after state_001、page_1 after state_002）を行い、両方とも
fetch不可だった。従って、後から同じblob URLを取得できるとは仮定しない。

Z0から継続している同一Playwright Pageのresponse listenerが、blob URLのresponse bodyを
load時にbounded保存していたため、Z1は`blob_url`の完全一致が確認できる場合だけ、その
既取得bodyをfallbackとして比較した。外部HTTP clientでblob URLを取得せず、別URL、asset
URL、byte順推測へのfallbackも行っていない。今回の7件は全て
`bytes_source=playwright_blob_response_body`で取得できた。

7件すべてで次を確認した。

- detected format: `JPEG`
- dimensions: `760x1080`
- JPEG decode success: true
- encoded bytesは再encodeせず`pages/page_000.jpg`〜`page_006.jpg`へ保存

### Pixel equivalence

各blob response bodyをPillowでRGB decodeし、SHA-256を計算した。同じstable stateの
visible `HTMLImageElement`をnatural size`760x1080`の一時canvasへ描画し、CSS表示サイズや
viewport/device scaleを入れず、RGBAからRGBだけを取り出してSHA-256を計算した。

`page_0`〜`page_6`の7/7で、decoded JPEG RGB hashとvisible img RGB hashが完全一致した。
canvas read時のSecurityErrorは発生せず、mismatch、inconclusive、unavailableは0件だった。

判定は次のとおりである。

```text
blob JPEG direct capture: confirmed
pages: 7
exact_pixel_match: 7
mismatch: 0
inconclusive: 0
unavailable: 0
```

これは今回の対象chapter・対象state・対象page集合でのlive verificationであり、他chapterや
別access stateへの一般化ではない。

Z1 verdictの集約はfail-closedである。`confirmed`は、今回の検証対象として採用した全pageが
`exact_pixel_match`で、minimum page数、stable ordering、spread、gapなしをすべて満たす場合
だけにする。1件でも`unavailable`または`inconclusive`があれば全体を`inconclusive`とし、
1件でも明確なpixel/dimension `mismatch`があれば`rejected`とする。empty、duplicate index、
malformed index、ambiguous ordering、non-monotonic transitionもconfirmedにしない。

`exact_pixel_match`には、JPEG decode dimensions、HTMLImageElementのnatural dimensions、
canvas read時の`img_pixel_dimensions`の3者一致と、decoded RGB hash / HTMLImageElement RGB
hashの一致をすべて要求する。dimensionsまたはhash等の必要metadata欠落はexactと推測せず、
`inconclusive`として扱う。

### Page_N attribution / spread / reading order

`page_N`の観測indexは`[0,1,2,3,4,5,6]`で、欠落・malformed alt・duplicate indexは
なかった。state間のpage集合は単調に進み、spread内の左右両pageを別々のblob URL、JPEG
bytes、pixel hashとして検証できた。page counter候補は既存DOM artifactで
`1 / 25`、`2 / 25`、`4 / 25`、`6 / 25`だった。

したがって、このbounded runでは次が安定した。

```text
logical page order candidate = numeric page_N ascending
```

screen左右位置、DOM order、page counterは対応証拠として保存するが、logical page orderの
authority候補は`page_N`の数値順である。missing、duplicate、non-monotonic transitionが
出た場合はconfirmedにしない実装にしている。

### Asset responseとの関係

同じstateの`asset.zebrack-comic.com` image response候補はtimestamp、URL、content-type、
content-length、body保存結果としてartifactに記録した。今回もasset側の`image/jpeg`
response bytesはJPEG decode不能だった。一方、exact blob URLのresponse bodyはJPEG decode
可能でvisible imgとpixel exact matchした。

asset responseとblob生成の一対一生成時刻・変換過程は観測できていないため、asset bodyから
blob bodyへのmapping、暗号化、scramble、tile permutation、compression方式は推測していない。
同一stateに存在することは記録したが、asset transport bytesをcapture sourceとして採用していない。

### Capture strategy conclusion

今回のZ1証明により、このchapterについては次をZeblack固有の最上位capture候補としてよい。

```text
visible HTMLImageElement
  -> exact blob URL / blob response bytes in the same browser context
  -> encoded JPEG bytes
  -> unchanged .jpg save
```

`CAPTURE_STRATEGY.md`のshared hierarchy自体は変更していない。用語上は、visible pageに
一対一対応しdecode pixelsもexact matchしたencoded source bytesなので、Level 1 original
bytesに相当するdirect-source候補として扱える。ただし、client側のblob生成過程やasset
transportの原形式までoriginalと断定するものではない。重要なのは、PoCがJPEG bytesを
再encodeせず保存できたことである。

Production Site Adapterはまだ実装していない。productionでは、blob URLのlifetimeに依存せず、
stable stateで必要なbytesを即時に確保する必要がある。fetch(blob:)が失敗する実サイト状態を
踏まえ、response body listener等の同一browser context内の取得経路を、別Phaseでproduction
設計として明示検討する。

## Capture candidates

Z0のassessmentは次のとおり。

| method | status | 根拠 |
| --- | --- | --- |
| original / direct blob response bytes | confirmed for this Z1 run | 7ページでJPEG decode、natural dimensions一致、visible img native RGBとのexact matchを確認。production Adapterは未実装 |
| source-native | possible but not selected | encoded blob bytesが直接使えるため、source pixelの再materializeは不要。別chapterへの一般化は未確認 |
| native reconstruction | unknown | drawImage/canvas mappingが未観測で、再構成実装は未作成 |
| canvas | rejected for this run | visible canvas/drawImageはnot observed |
| locator screenshot | possible | page-like img locator候補とviewport screenshotは取得できたが、本文のみlocator screenshotは未保存 |

Z1ではdirect blob response bytesを対象chapter限定でconfirmedとしたが、production Site Adapter
へは変更を入れていない。

## Next phase

次Phaseでは、Z1の境界を越えない範囲で次を検討する。

1. production Adapterへ入れる前に、同じsafe capture契約をsite-specific実装として分離し、
   current stable stateで即時取得・bounded memory・all-or-none spreadを設計する。
2. 別chapterで同じ`page_N`/blob response/pixel exact条件が成立するかを、access操作なしで確認する。
3. END/NEXT_CONTENT、別access state、loginは別phaseのread-only調査とし、Z1のdirect capture
   結論へ混ぜない。
4. asset transport bytesの復号・scramble・tile解析は、blob direct captureが利用できる限り行わない。

## Z2 live verification (2026-09-29)

This section supersedes the preceding pre-Z2 statement that chapter-end behavior had not yet been observed. The older text is retained only as the Z0/Z1 investigation history; the current terminal understanding is the one below.

The research-only Z2 probe was run against the same target chapter using the shared Crawler Chrome and bounded `ArrowLeft` navigation (`13` successful advances; hard cap `100`). No next-chapter, access, purchase, ticket, point, coin, advertisement, or login control was clicked. The target host/title/chapter/viewer identity stayed unchanged for every before/after operation.

Observed page progression was:

```text
state_000: page_0, page_1, page_2       counter 1 / 26
state_001: page_1, page_2, page_3, page_4 counter 2 / 26
state_002: page_3, page_4, page_5, page_6 counter 4 / 26
...
state_011: page_19, page_20, page_21, page_22, page_23 counter 22 / 26
state_012: page_21, page_22, page_23 counter 24 / 26
state_013: page_23 (not in viewport) counter 26 / 26
```

The final content state was `state_012`: `page_23` was the only in-viewport `page_N` image and the counter was `24 / 26`. One further `ArrowLeft` transition produced `state_013`, where no `page_N` image was in the viewport and the counter remained visible as `26 / 26`. The terminal screenshot showed the end-of-viewer UI, including `次の話を読む` with `2話`, comment/favorite controls, and recommendation content. This is a NEXT_CONTENT candidate, not a click or an observed next-chapter navigation.

The earlier partial Z1 artifact recorded a `1 / 25` counter, while this full Z2 run recorded `1 / 26` through `26 / 26`. That discrepancy was not resolved in this probe; the denominator is therefore evidence only and must not be treated as a standalone total-page authority.

The first terminal transition was therefore the advance from `24 / 26` to `26 / 26`. The URL remained the target viewer URL; no automatic chapter change was observed. A next-content DOM button was observed without an `href`; no next-chapter identity was obtained from a clickable chapter link. Recommendation links were recorded as recommendation evidence only and were not treated as next-chapter authority.

The Z2 report classification is:

```text
Zeblack terminal behavior: next_content_confirmed
```

The classifier is fail-closed: it does not treat a page counter or a no-change result alone as END. A confirmed verdict now requires all of the following: terminal state content is absent, an explicit END/NEXT_CONTENT signal exists, the terminal URL still matches the expected title/chapter/viewer identity, and the navigation record with the same `step` has `changed=true`, `stable=true`, and an in-chapter URL change kind (`unchanged` or `query_or_hash_changed`). If the transition is unstable or the matching navigation record is missing, the result is `terminal_but_type_unknown`; it is never confirmed. `end_confirmed` was not observed in this run; the observed terminal signal was NEXT_CONTENT. This probe does not implement production PageState or click the next-content control.

Production Adapter recommendation: retain `page_N` numeric tracking for content order, treat `26 / 26` as supporting evidence only, and classify the terminal state as `NEXT_CONTENT` only after the same current-chapter guard and explicit visible `次の話を読む`-type evidence. Keep the next-content action non-clicking. Behavior for other chapters, access states, login states, and a separate explicit END UI remains unknown.

## Z3 follow-up corrections (2026-09-29)

The production adapter now treats exact Zeblack blob response bytes as
source-native when Pillow can decode them as either JPEG or WebP and the
decoded dimensions match the visible `HTMLImageElement` natural dimensions.
The original bytes are preserved without re-encoding; JPEG is saved as `.jpg`
and WebP as `.webp`. Unsupported, corrupt, or dimension-mismatched bodies use
the existing all-or-none direct-capture failure and locator fallback path.

`ContentIdentity.page_number` is the one-based logical first page number:
`page_0` is `1`, `page_1+page_2` is `2`, `page_3+page_4` is `4`, and `page_23`
is `24`.

Core duplicate detection is generic. It uses the complete logical identity,
spread part count, spread part index, and encoded capture fingerprint. A later
logical page may therefore reuse identical bytes without being dropped, while
the same logical spread repeated unchanged still triggers `max_same_content`.

Follow-up live verification against the target chapter completed successfully:

```text
Saved 24 pages; stopped at next_content
archive: page-0001.jpg ... page-0023.jpg, page-0024.webp
decoded formats: JPEG=23, WebP=1, PNG fallback=0
JPEG dimensions: 760x1080
WebP dimensions: 960x1817
final URL: same target chapter viewer (no chapter navigation)
next chapter click: no
```

The prior Z3 result of 23 saved pages / 22 JPEG + 1 PNG was caused by the
global fingerprint dedupe and JPEG-only source validation. That historical
result remains recorded above; the corrected run stores all 24 logical pages
and the source-native WebP artifact.

## Z4-0 chapter-list / access-state probe (2026-09-30, research only)

Z4-0 was run against the final requested target:

```text
https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list
```

The probe used the shared Crawler Chrome through the existing `BrowserSession` /
CDP path. It created no browser/profile lifecycle, did not inspect cookies or
storage, and did not perform login. No chapter/access control was clicked. The
live page showed a visible account indicator (`マイページ`); this is only an
account-context observation, not an authentication proof.

This section records the superseded **Z4-0 research-only** state. At that
point Z4-1 production Discovery existed, while Site Policy, Batch Policy,
ticket consumption, rental start, and purchase were outside the Z4-1 scope.
The current Z5 Site Policy/runtime status is recorded at the top of this note.

### Chapter-list structure and identity

The list rendered all `250` chapter cards in the initial DOM. After one bounded
scroll-to-bottom observation the count remained `250`; no pagination or
"more" control was observed, and no lazy-load growth occurred. The card is not
an anchor: the observed stable DOM identity was `id="chapter{chapter_id}"` on
the card root. For example, the first card had `id="chapter132107"` and the
active-rental card had `id="chapter224191"`.

Every card produced a unique numeric `chapter_id`, `title_id=5123`, and a
candidate viewer URL of the form
`/title/5123/chapter/{chapter_id}/viewer`. The card did not expose a direct
chapter href in this snapshot. This is sufficient evidence for a bounded
boundary candidate, but no production parser has been added.

The raw DOM order was `#1` through `#250`, therefore **oldest-first** based on
the visible labels and preserved DOM index. This is separate from the future
canonical Discovery order (`latest-first`) and from Web ticket-consumption
order, which Z4-0 intentionally did not test.

### Observed native access signals

The current account snapshot yielded these raw DOM/icon classes:

| raw site signal | count | observed meaning | Z4-0 derived hypothesis |
| --- | ---: | --- | --- |
| `無料` text | 16 | campaign/free label | `free_unconditional` |
| blue `Free` / `チケット利用可` icon alt | 2 | current ticket-available-looking icon | `ticket_available_now` |
| `ポイント画像` icon alt | 188 | point/P icon signal | `ticket_candidate_later` hypothesis only |
| rental expiry text | 1 | `閲覧期限 残り2時間`-type active rental signal | `rental_active` |
| `コイン画像` icon alt | 43 | coin-only signal | `coin_only` |

The visible `無料` signal is stable to identify in this snapshot, but its
campaign end date means it must not be promoted to a permanent chapter type.
The point icon and coin icon are distinct and were stable across their DOM
cards, so P/point and coin-only are distinguishable in this observation. The
P mapping to `ticket_later` remains an explicit observation hypothesis, not a
production semantic. The separate `チケット利用可` icon is a stronger
candidate for a site-intrinsic ticket-eligibility signal, but Z4-0 did not
prove whether it means current frontier eligibility or merely ticket
eligibility.

Chapter `224191` was the only observed rental-active row. Its DOM exposed a
remaining-time/expiry display, but the origin of the rental (ticket, point, or
coin) was not inferred. The probe did not click it or enter the viewer.

The snapshot is not a simple permanent frontier property: the observed raw
sequence was Free rows, ticket-icon row, P/point rows, rental-active row,
ticket-icon row, more P/point rows, then coin rows. A ticket use can change the
account-dependent `currently_ticket_available` boundary; this artifact must
not be treated as a persistent chapter classification.

### API / structured-data observation

The page made a bounded request to:

```text
https://api2.zebrack-comic.com/api/v3/title_chapter_list
```

The response was `application/protobuf`, `20493` bytes, status `200`. The
probe saved bounded metadata and a prefix hash artifact, but did not decode
the protobuf schema. No JSON chapter listing or embedded hydration payload was
found. Therefore the current authority recommendation is **DOM + explicit
icon/alt signals**, with the protobuf API as the next structured-data
investigation target; production should not rely on CSS module hashes.

The final research artifact is under
`output/zeblack_discovery_probe/`:

```text
report.json
summary.md
dom/listing.json
network/responses.json
network/relevant_payloads/api_001.json
```

The compact DOM snapshot removes query strings from stored `src`/`href` and
subtree HTML so signed thumbnail parameters are not retained in the artifact.

### Discovery and bounded-Discovery implications

`chapter_id` is a viable external-id candidate and maps one-to-one to the
candidate viewer boundary URL for all 250 observed cards. A future Discovery
implementation should preserve the distinction below:

```text
site-intrinsic candidate: chapter_id, listing label/order, point-vs-coin-vs-ticket icon
account-dependent state: currently ticket-available, rental_active, expiry/remaining time
```

The result does **not** yet justify a design that avoids all post-consumption
refreshes. Such a design is plausible only if the protobuf or another stable
signal separates `ticket_eligible` from a dynamic current-eligibility flag.
Until that field is identified, a future access pass must reconcile dynamic
state explicitly and must not persist `ticket_later` as permanent.

### Z4-0 test status

Pure research helpers are covered by
`tests/research/test_zeblack_discovery_probe.py`; the live site is not a CI
dependency. The probe itself remains outside the production Discovery tree.

## Z4-0.5 access semantics / protobuf investigation (2026-09-30, research only)

Z4-0.5 followed up the Z4-0 artifact for title `5123`:

```text
https://zebrack-comic.shueisha.co.jp/title/5123/chapter/list
```

This is **research only** and predates the Z4-1 production adapter. The probe
used
the existing shared Crawler Chrome/CDP path, opened only the chapter-list page,
and did not inspect cookies/storage or perform login.

### Corrected state model

The previous Z4-0 `Free -> ticket_now` mapping was only a research hypothesis
and is superseded. `無料` and the blue Free/ticket image are separate signals:

```text
無料 text/badge           -> free_unconditional
blue Free / チケット利用可 -> ticket_available_now
P / ポイント画像          -> ticket_candidate_later (hypothesis only)
rental expiry display     -> rental_active
コイン画像                -> coin_only
```

The classifier does not treat English `Free` as unconditional free. The live
snapshot produced:

```text
free_unconditional       16
ticket_available_now      2
ticket_candidate_later  188
rental_active             1
coin_only                43
unknown                   0
```

The verification anchors matched the user observation: the blue
`チケット利用可` image was found on exactly two rows, and rental-active on
exactly one row. The two ticket rows were index `16` / chapter `198365` / `#17`
and index `26` / chapter `226849` / `#27`. Both expose the same ticket-image
signal (`img` alt `チケット利用可`, research-observed class
`sc-jptKe hfdkkM`); the image `src` is a data URI and is omitted from the
artifact. Their neighboring rows and complete icon metadata are in
`output/zeblack_access_semantics_probe_v2/report.json`.

### Frontend and protobuf schema evidence

The frontend bundles provided bounded generated-code evidence:

```text
fetchChapterListV3 -> Proto.TitleChapterListViewV3.decode
record message    -> Proto.ChapterV3
status enum       -> Proto.ConsumptionStatus
```

The `ChapterV3` field mapping recovered from generated encode/decode snippets
is:

```text
1 id
2 titleId
3 mainName
4 alreadyViewed
5 remainingRentalTime
6 campaignLabel
7 canComment
8 numberOfComments
9 isUpdated
10 isAdvanced
11 status
12 price
13 canUseVideoReward
14 publishedDeadline
15 consumptionDialog
```

The recovered `ConsumptionStatus` enum is:

```text
0 FREE
1 RENTAL
2 TICKET_AVAILABLE
3 TICKET_UNAVAILABLE
4 POINT
5 COIN
6 TICKET_UNAVAILABLE_COIN_ONLY
```

`Proto.TitleChapterListViewV3` top-level evidence includes `titleId`,
`lastChapterId`, `advertisements`, `groups`, and `indexGroups`. No global
ticket stock, next recovery time, or recovery interval field was identified in
the captured list schema or DOM. The current status is therefore a chapter
record field, not a recovered global account-ticket object.

The list response was `application/protobuf`, 20,493 bytes. In the hardened
v2 artifact, the bounded ChapterV3 extractor found `250` records and compared
the sets in both directions:

```text
DOM chapter IDs:          250
protobuf ChapterV3 IDs:   250
intersection:             250
DOM-only IDs:                0  []
protobuf-only IDs:           0  []
duplicate ChapterV3 IDs:    0  []
```

This is an exact bidirectional set match, not merely evidence that each DOM ID
appeared somewhere as a generic protobuf scalar. The extractor requires the
ChapterV3 shape (`id`, `titleId`, `mainName`, plus another evidenced field) and
the expected `titleId=5123`; unrelated protobuf messages with numeric field 1
are excluded. The final v2 raw body SHA-256 is
`3241317c8688a3cdae0b36ebced37ad1f919aad789350589bcb94042a84f6b9a`.
The probe stores raw-byte and text hashes separately and treats the raw hash as
authoritative.

The v2 artifact also records separate evidence states:
`protobuf_body_observed=true`, `frontend_decoder_observed=true`,
`chapter_schema_recovered=true`, and
`consumption_status_enum_recovered=true`. If frontend ChapterV3 evidence is
absent, the probe fails closed and does not publish semantic field names or
ChapterV3 records merely because a protobuf body exists.

Structured state correlation for this snapshot was:

```text
無料                 status absent/default 0 (FREE)
blue Free            status 2 (TICKET_AVAILABLE)
P / point image      status 4 (POINT)
rental_active       status 1 (RENTAL), remainingRentalTime field 5 present
coin image           status 5 (COIN)
```

This confirms that current ticket availability is represented as a dynamic
structured status. It does **not** confirm a stable `ticket_capable` field for
P rows. P is currently `POINT`, and the frontend's consumption logic treats
`POINT` as point/coin consumption. The hypothesis that a P row later changes
to `TICKET_AVAILABLE` after earlier ticket consumption remains unproven in
this read-only phase. `TICKET_UNAVAILABLE` and
`TICKET_UNAVAILABLE_COIN_ONLY` were present in the frontend enum but were not
observed among the 250 current records.

The rental record had `status=RENTAL` and `remainingRentalTime` in the
final snapshot. The frontend formats this value into the displayed remaining
time; the exact unit was not independently confirmed. The original grant
source (ticket, point, or coin) remains unknown.

### Stable versus dynamic state

The evidence supports keeping these separate in future design:

```text
relatively stable: chapter id, title id, main name, listing order, viewer URL shape
dynamic/account:   status, alreadyViewed, remainingRentalTime, isUpdated
time/campaign:     campaignLabel and free presentation
```

No stable future-ticket capability flag was found in the recovered `ChapterV3`
schema. Therefore Candidate design A (`P + ticket_available_now -> quota`) is
**not adopted** by this phase. P and blue Free should not yet be persisted as
one quota class without a before/after account-state observation or another
endpoint/schema field proving the relationship.

Full Discovery is not needed to preserve chapter identity/order after each
ticket use, but the current dynamic `status` still needs a live refresh. No
separate lightweight access-state endpoint was found in this probe. The
natural future responsibility is a lightweight status check at Site Policy
planning or strict-entry time, falling back to the bounded list API if no
smaller endpoint exists.

The `chapter_id -> /title/{title_id}/chapter/{chapter_id}/viewer` boundary
candidate remains one-to-one for bounded Discovery. The production parser and
adapter are now implemented in the Z4-1 section at the top of this note.

### Z4-0.5 artifacts and tests

The hardened live research artifact is under
`output/zeblack_access_semantics_probe_v2/`:

```text
report.json
summary.md
dom/states.json
protobuf/response.bin
protobuf/wire.json
protobuf/decoded.json
protobuf/field_correlation.json
network/responses.json
network/frontend_schema_evidence.json
```

`response.bin` is a local research artifact and is not a repository fixture.
Data URI image bodies are omitted from DOM snapshots. The pure research tests
cover the corrected five-state classifier, conflicting signals, ChapterV3
fail-closed extraction, exact/protobuf-only/DOM-only bidirectional set
correlation, unrelated numeric field rejection, frontend-evidence schema
gating, field-shape comparison, raw-byte hashing, and before/after report
comparison. The live site is not a CI dependency.

## Known limitations

- 対象はこの1 title/chapterだけで、他chapter・別title・別access stateは未確認。
- CSS module class hashはlive observation artifactであり、production selectorのauthorityではない。
- cross-origin frameの内部viewer構造は調査していない。
- response body保存は最大20件で、network responseの全body保存ではない。
- Z0 artifactの画像候補は実サイト著作物を含み得るため、fixtureやCI入力として扱わない。

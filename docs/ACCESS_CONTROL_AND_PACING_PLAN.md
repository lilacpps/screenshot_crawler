# Access Control / Pacing Implementation Plan

## Normal Batch single retry (2026-11-22)

Status: IMPLEMENTED / TARGETED AND LOCAL-BROWSER VERIFIED. Full collection
coverage: 10,211 passed, 2 existing operator-config expectation failures, 0 skipped;
the two tests pass against isolated tracked defaults. Windows long-path failure
was resolved by short isolated test output paths. Details: note/00_core.md.
No new live consumption was used.
The current execution contract is in docs/DISCOVERY_AND_BATCH.md, "Normal Batch
single retry". This extends ordinary normal-capture timeout handling and does
not change the earlier grant-only phases or Adapter-internal retry algorithms.

Acceptance: failure then success continues; two failures stop even with different
errors; first/final diagnostics and independent CrawlRuns remain; logical counts
and limits count once; fresh Pages/Adapters are cleaned up before replay;
cleanup failure/open Page and cancellation prohibit replay. Confirmed ticket
grants allow direct recovery with no new debit and retain pass exhaustion;
unknown consumption and before-run reservations never authorize replay.
AccessGuard fatal stops, including late stops during diagnostics, remain fatal.
BookWalker quota/resume and Yanmaga entry-replay prohibitions remain in force.

## Younganimal Premium extension (2026-11-21)

Status: IMPLEMENTED / TARGETED VERIFIED / BOUNDED LIVE VERIFIED.
Existing per-Work stock hooks, exhaustion/last-ticket flags and native expiry
commits are used without shared production edits. Younganimal-local auth,
aggregate conflict and episode route guards accompany the two-step entry.
Home campaign `popClose`, one native gacha spin (zero / はずれ), grant-only and
normal END/ZIP were live verified. Two tickets total were consumed (18 -> 16);
the gacha was never replayed. Synthetic coverage includes absent/delayed popup,
absent/used gacha, ignored positive/zero/unknown result, 9000-candidate stock bounds,
last-ticket completion, identity/account conflicts and post-debit failure.
Current evidence, test counts and live limits: `note/11_younganimal.md`.

## Hanayume Premium extension (2026-11-21)

Status: IMPLEMENTED / TARGETED VERIFIED / BOUNDED LIVE VERIFIED.
The site uses existing resource-aware per-Work resolver hooks only for Premium,
existing exhaustion/last-ticket flags, and one optional bounded daily-gacha UI
preparation. No durable gacha ledger or stock state is added. Resource-specific
grant expiry defaults to existing policy behavior; Hanayume Premium requires its
native 15-day expiry while Work Ticket keeps the 72-hour fallback/cap.

Acceptance covers 9000 quota candidates bounded before entry, zero/unknown stock,
Work Ticket priority, exact zero-coin single-ticket checkout, two distinct UI
actions without replay, 15-day persistence without Work state, pending grant-only,
same-Page normal Viewer, last-ticket completion, and debit preservation through
later failure. The 2026-11-23 gacha contract removes result verification and its
35-second wait: click once, settle five seconds, request fresh stock. Both sites
accept old/new campaign close markers through the spin, once per home/gacha route.
Optional gacha errors continue only after positive auth and fresh valid stock;
unknown stock and fatal access/cancellation still stop. Hanayume failure diagnostics
include the spin cover/ancestors and unknown modal controls for future patterns.
Gacha fixtures cover absent/used/ignored outcomes, no share/replay, both close
markers, delayed home/gacha overlays and failure/cancellation boundaries.
Three authorized live tickets total verified probe/grant-only/normal paths;
the once-daily spin was exercised once. Current evidence and limitations are in
`note/10_hanayume.md`; the remaining unused-gacha production branch is synthetic
only today because a second live spin is deliberately not attempted.

## Comic DAYS Premium extension (2026-11-21)

Implemented: policy-ordered Work → Premium passes, stock-bounded per-Work
selection in normal/additional Batch and grant-only, and empty-pool positive
exhaustion stopping before any entry or next Work. Required coverage includes
resource-specific opt-in (Work Ticket uses the original candidate path), zero
Page/resolver/sleep for multiple local cooldown skips, continued exact entry
after those skips in normal/work-only/all runs, and
explicit Work-only isolation, native Work priority, N-stock/N-target selection,
zero/unknown stock, exact one-unit debit plus target unlock, no click retry,
last-ticket completion, shared limits/order and no Premium cooldown writes.
Current validation and bounded live evidence are in `note/08_comicdays.md`;
shared contract changes are summarized in `note/00_core.md`.

This implementation plan accompanies `docs/ACCESS_CONTROL_AND_PACING.md` and the site-specific access specifications.

Phase 1 status: **IMPLEMENTED**. Phase 2 status: **IMPLEMENTED**.
Phase 3 status: **IMPLEMENTED**. Phase 4 status: **IMPLEMENTED**.
Phase 5 status: **IMPLEMENTED**. Phase 6 status: **AUTOMATED VERIFIED / LIVE PARTIAL**.

Piccoma normal Batch and grant-only ticket execution are implemented as a
site-specific integration, not as a new generic resource policy phase. Normal
Batch uses `piccoma_ticket_auto`; grant-only uses `work_ticket` (waitfree/¥0+)
and `binge_ticket` (binge-free) as distinct ordered passes within each Work for
`all`, with one combined initial listing/home check per Work. Both use
existing `quota_resource` /
`AccessConsumption` contracts plus the site-neutral candidate-sequence and
durable access-attempt observer hooks. Generic behavior remains unchanged for
policies that do not use those hooks. The implementation, historical live
ledger, current synthetic regression status and remaining evidence are tracked in
[`runbooks/piccoma-ticket-auto/PROGRESS.md`](../runbooks/piccoma-ticket-auto/PROGRESS.md).

Explicit Piccoma grant-only now opts into Work-level stock resolution through
`resolve_grant_only_per_work()`. One guarded non-consuming snapshot bounds a
Work's selected grant pool; zero stock skips the Work, and later unavailability
does not probe its other episodes. Normal Batch ordering and the existing
single-target deferred/prepared flows keep their contracts. Acceptance covers
waitfree/¥0+/Binge stock bounds, unknown balances, next-Work advancement,
shared limits, pass exhaustion, failure stops and Page cleanup. This revision's
stock-selection checks are synthetic; no additional live ticket use is claimed.

The 2026-11-21 Work-first revision adds default-false
`grant_only_all_per_work()` and a guarded combined-resource resolver. Piccoma
opts in; zero stock in both pools requires one listing navigation and one home
GET. Earlier entry attempts invalidate the next resource's initial selection:
the Catalog is replanned and only the current Work's remaining original pool is
refreshed. The global attempt limit, resource-wide exhaustion, Work-local
unavailability, unknown stop, pacing and cleanup retain their contracts.
Normal Batch and single-resource grant-only also remove the redundant listing
GET during stock preselection; entry/debit proof is unchanged. Acceptance covers
cross-Work order, shared limits, mutations, exact resource/source coverage,
AccessGuard cleanup, zero-stock request counts and actual Runner entry for
grant-only all and normal Batch. This revision's live behavior remains unverified.

Normal Piccoma Batch now also opts into `resolve_batch_quota_per_work()`.
The shared orchestration resolves a Work/resource lazily, caches its selected
quota pool for the phase, and preserves interleaved direct/quota candidate order.
Zero stock skips the pool before entry; later unavailability skips only its
remaining quota rows. Acceptance includes daily/secondary stock bounds,
normal Batch-to-ZIP/Catalog execution, empty and interleaved Works, no-action
races, pass/unknown stops, metrics/events, pacing and Page cleanup. The hook
defaults to false for other policies. This extension uses synthetic checks;
no new real-site ticket use is claimed.

## Bounded resolver prerequisite extension (2026-10-29)

Implemented the optional site-neutral resolver configuration hook supplying
runtime page-turn delay and explicit excluded external IDs, with a validated
positive total operation budget. Per-observation timeout, borrowed AccessGuard,
bounded cancellation and prepared-entry document validation are retained.
Zeblack opts in to one stock-confirmed predecessor reread, with no rights
acquisition for the predecessor. Its exact behavior and bounds are specified in
`DISCOVERY_AND_BATCH.md`. Acceptance coverage includes default/invalid/extended
budgets, runtime pacing propagation, expired/paid/excluded predecessors,
rewind/forward/terminal/close, no-change/max-pages/deadline guards, final-snapshot
handoff and no repeated reread. Existing grant-only tests continue to cover
consumption persistence and later Work sequencing.

## Phase 1 - Runtime settings, pacing, and site ordering

Discovery extension (2026-11-13): implemented independent
`discovery_inter_target_delay_ms` (default 3000 ms, explicit zero accepted).
Acceptance tests cover config defaults/overrides/invalid values, previous-site
selection across site changes, cleanup before waiting, no first/single/final
delay, disabled/capability skips, failed-attempt continuation, GUI custom runtime
paths and cooperative cancellation during a chunked wait. Sleeps are faked;
no new adapter/browser behavior or live timing claim is introduced.

### Changes

- add `crawler.yaml` loader and typed per-site runtime settings,
- add safe non-zero pacing defaults,
- pass resolved `page_turn_delay_ms` into `RunConfig`,
- pass resolved `inter_candidate_delay_ms` into Batch orchestration,
- insert CONTENT pacing after all capture artifacts and progress are persisted and immediately before the initial `adapter.go_next()`,
- keep the pacing sleep outside adapter timeout/retry calls,
- apply candidate pacing only between candidates that contacted the site,
- update Magapoke and Jump+ Batch ordering to old-to-new within a Work,
- preserve latest-first Magapoke and Jump+ Discovery,
- use `published_at ASC` with NULL last and `source_id DESC` as the same-date tie-breaker,
- preserve existing adapter-owned retry algorithms for Magapoke, Manga ONE, and BookWalker.

### Acceptance tests

- config present/missing/site-missing/default behavior,
- non-negative validation and explicit zero override,
- `save -> delay -> go_next -> wait_for_change`,
- one delay for a spread/multi-artifact logical page,
- no page pacing for AD,
- no duplicate pacing on adapter retry,
- page pacing excluded from page-change timeout budget,
- one candidate delay between site-accessing candidates,
- no candidate delay for local-only skips,
- Magapoke / Jump+ ordering regression,
- Manga ONE / BookWalker navigation regression.

## Phase 2 - Shared AccessGuard and metrics

Status: **IMPLEMENTED**.

### Changes

- add reusable response/access observation,
- add per-site relevant-host classification,
- support site settings for 403/429/challenge/CAPTCHA stops,
- classify distinct stop reasons: `http_403`, `http_429`, `challenge_detected`, `captcha_detected`,
- recognize explicit challenge response markers such as `cf-mitigated: challenge`,
- add conservative generic visible CAPTCHA detection for known provider UI,
- add site-specific challenge/CAPTCHA hook for separately verified states,
- stop the Batch run without automatic reload/retry/solve on challenge/CAPTCHA,
- add incremental JSONL run/candidate metrics,
- print concise normal/abnormal summaries and metrics paths,
- wire the shared mechanism to Magapoke, Manga ONE, and BookWalker without changing normal viewer retry semantics.

### Acceptance tests

- relevant-host 403 stops,
- relevant-host 429 stops and records `Retry-After`,
- unrelated third-party 403/429 does not stop,
- explicit challenge stops with distinct reason,
- visible CAPTCHA stops with distinct reason,
- hidden/background CAPTCHA integration alone does not stop,
- no automatic challenge/CAPTCHA retry or reload,
- partial JSONL survives abnormal stop,
- metrics collection does not fetch response bodies solely for accounting.

## Phase 3 - Generic access-resource selection

Status: **IMPLEMENTED**.

### Changes

- evolve the existing `quota_resource` extension points instead of adding a Magapoke-only path,
- let SitePolicy/integration expose supported access resources,
- let SitePolicy/integration expose ordered resource passes,
- keep generic Batch free of concrete resource-name branches,
- make one resource attempt consume only the explicitly configured resource,
- treat another resource being offered by live UI as resource-unavailable for the current pass,
- implement generic `all` as policy-ordered passes with Catalog replanning between passes,
- preserve `AccessConsumption` as observed adapter evidence.
- preserve the existing normal/default Batch pass and replan from Catalog between
  policy-ordered explicit resource passes.

### Acceptance tests

- unsupported resource fails clearly,
- requested resource is passed through Policy -> Adapter,
- resource A attempt never silently consumes resource B,
- timeout/ambiguous UI/access rejection never triggers fallback resource consumption,
- `all` follows policy ordering,
- replan happens between passes,
- no Magapoke resource strings in generic Batch orchestration.

## Phase 4 - Generic grant-only + Magapoke Work Ticket

Status: **IMPLEMENTED**.

### Changes

- add generic `batch run --site <site> --grant-only <resource>` validation and
  orchestration for the first Work Ticket pass; Phase 5 adds `all`,
- validate resource support through selected site policy,
- refactor/reuse normal pre-capture entry semantics so grant-only does not duplicate resource click/initialization logic,
- add Work-scoped resource persistence needed for Magapoke Work Ticket,
- apply configured 23-hour local negative gate,
- persist Work Ticket `last_consumed_at` only after observed confirmed consumption,
- persist source access grant,
- use the same observed-consumption persistence helper for normal Batch and grant-only;
  confirmed consumption survives later crawl/finalization failure,
- leave Item pending and do not capture/package/complete.

### Acceptance tests

- cooldown local skip performs no site access,
- cooldown expiry only permits live check; it does not imply ticket availability,
- unavailable Work Ticket creates no timestamp/grant,
- confirmed Work Ticket updates state/grant,
- click without confirmed viewer does not update resource state,
- grant-only produces no content artifact and does not complete Item,
- existing normal Batch Work Ticket flow remains unchanged.

Normal deferred Batch follow-up (2026-10-17): use the same per-Work prepared
resolver/entry as explicit grant-only. Verify multi-Work ordering, one-list-load
handoff, local cooldown and unavailable skips, fatal stop, remaining-slot limits
without later Work visits, and one post-grant replan containing only grants
confirmed during the current run. Preserve direct-phase and cross-phase pacing.
Normal Batch also uses the Work-result report/metrics: check OK/NG/local SKIP,
unattempted limits after Phase A, fatal stop/interruption, current Watchlist labels
and confirmed grants remaining OK after a later capture failure.

Deferred grant-only follow-up (2026-10-14): sequential Work resolution/entry,
no all-Work pre-scan, pacing after unavailable snapshots, stop visiting later
Works at the shared selected-attempt limit, current Watchlist label reporting,
resolver-only NG outcomes, and stopped/limited unattempted Work summaries are
covered by CLI/local Catalog tests. Existing executor tests also assert positive
consumption evidence survives a later grant-only failure and unconfirmed failure
exposes no positive evidence. Normal Batch and non-deferred resource-pass tests
remain regression coverage. The synthetic Zeblack entry Integration
tests now also exercise the real CLI/Executor/Runner handoff with one list
navigation, one selected ticket click, source/work persistence and a second run
that creates no site Page during cooldown. Same-URL reload, wrong Page/target,
reused handle, declining adapter, paid-control ambiguity and a stopped guard
fail before consumption. Confirmed consumption followed by finalization failure
retains work cooldown and positive reporting. The document is bound before
protobuf body observation and validated within the shared observation deadline.
Core local-viewer and AccessGuard tests cover the default lifecycle. Real ticket
consumption is separate live verification, not a CI dependency.

## Phase 5 - Magapoke Premium / all

Status: **IMPLEMENTED**.

### Changes

- expose Magapoke `premium_ticket` through generic resource support/order,
- preserve semantic live Premium Ticket balance parsing,
- stop Premium pass at zero balance,
- check the semantic account balance before episode navigation, including when
  zero hides the episode's Premium control/balance; unknown balance stops the pass,
- finish the confirmed last-ticket candidate successfully, then stop before
  any further account/episode navigation via the generic success-result flag,
- preserve Work Ticket priority in normal UI,
- treat Work-only UI during Premium pass as `premium_ticket_unavailable`,
- implement Magapoke `all` through generic Work Ticket pass -> replan -> Premium pass,
- preserve conservative 71-hour grant persistence.
- keep Premium balance live-only and do not persist Premium resource state in Catalog,
- apply the total `--limit` across all resource passes, counting only site attempts,
- continue to the next policy pass after non-fatal resource exhaustion while
  propagating AccessGuard fatal stops to the whole run.

### Acceptance tests

- Premium-only never consumes Work Ticket,
- Work Ticket is never bypassed to force Premium,
- zero balance stops remaining Premium attempts,
- starting zero/unknown makes no episode requests; 9,000 pending candidates
  still cause only the first preflight attempt,
- the last ticket preserves normal completion or grant-only persistence and
  prevents the next Page and inter-candidate sleep,
- ambiguous balance/UI fails closed,
- confirmed Premium grant persists while Item stays pending in grant-only,
- normal Premium capture/package flow remains unchanged.
- `--grant-only all` replans between Policy-ordered passes and applies one shared limit,
- local-only skips do not consume the limit or trigger candidate pacing,
- Premium exhaustion does not execute later Premium candidates.

## Phase 6 - Cross-site regression and live verification

Status: **AUTOMATED VERIFIED / LIVE PARTIAL**. See
`docs/PHASE6_VERIFICATION.md` for the test inventory, read-only plans, and
truthful live-verification matrix. Ticket-consuming and normal quota live runs
were not forced when a safe non-consuming candidate or usable browser session
was unavailable.

Verify:

- Magapoke normal Batch,
- Manga ONE normal Batch,
- BookWalker normal Batch,
- manual crawl pacing,
- direct/quota entry paths,
- adapter retry timing and timeout boundaries,
- shared 403/429/challenge/CAPTCHA stop behavior,
- third-party rejection filtering,
- abnormal metrics persistence,
- generic resource pass orchestration,
- grant-only no-capture/no-package/no-completion behavior,
- Magapoke Work/Premium confirmed consumption and grant persistence.

Do not add guessed session-size cutoffs, automatic browser restarts, anti-detection behavior, CAPTCHA solving, or site-specific resource branches to generic Core/Batch during these phases.

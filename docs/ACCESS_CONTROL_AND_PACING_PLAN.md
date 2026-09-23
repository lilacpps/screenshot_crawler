# Access Control / Pacing Implementation Plan

This implementation plan accompanies `docs/ACCESS_CONTROL_AND_PACING.md` and the site-specific access specifications.

Phase 1 status: **IMPLEMENTED**. Phase 2 status: **IMPLEMENTED**.
Phase 3 status: **IMPLEMENTED**. Phase 4 status: **IMPLEMENTED**.
Phase 5 status: **IMPLEMENTED**. Phase 6 remains **PLANNED / NOT YET IMPLEMENTED**.

## Phase 1 - Runtime settings, pacing, and site ordering

### Changes

- add `crawler.yaml` loader and typed per-site runtime settings,
- add safe non-zero pacing defaults,
- pass resolved `page_turn_delay_ms` into `RunConfig`,
- pass resolved `inter_candidate_delay_ms` into Batch orchestration,
- insert CONTENT pacing after all capture artifacts and progress are persisted and immediately before the initial `adapter.go_next()`,
- keep the pacing sleep outside adapter timeout/retry calls,
- apply candidate pacing only between candidates that contacted the site,
- update Magapoke Batch ordering to old-to-new within a Work,
- preserve latest-first Magapoke Discovery,
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
- Magapoke ordering regression,
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

## Phase 5 - Magapoke Premium / all

Status: **IMPLEMENTED**.

### Changes

- expose Magapoke `premium_ticket` through generic resource support/order,
- preserve semantic live Premium Ticket balance parsing,
- stop Premium pass at zero balance,
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
- ambiguous balance/UI fails closed,
- confirmed Premium grant persists while Item stays pending in grant-only,
- normal Premium capture/package flow remains unchanged.
- `--grant-only all` replans between Policy-ordered passes and applies one shared limit,
- local-only skips do not consume the limit or trigger candidate pacing,
- Premium exhaustion does not execute later Premium candidates.

## Phase 6 - Cross-site regression and live verification

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

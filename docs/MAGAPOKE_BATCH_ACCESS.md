# Magapoke Batch Access / Resource Specification

## 1. Status and authority

This document defines the adopted **Magapoke-specific** Batch access-resource behavior.

Shared runtime pacing, AccessGuard, CAPTCHA/challenge/HTTP rejection handling, metrics, generic access-resource selection, and generic grant-only semantics are defined in:

```text
docs/ACCESS_CONTROL_AND_PACING.md
```

The behaviors described here are **planned unless the current code already provides them**. Existing live-verified Magapoke capture, ticket entry, quota persistence, Discovery, navigation retry, and packaging behavior must not be weakened while implementing this specification.

This document supplements `docs/DISCOVERY_AND_BATCH.md` and the shared access-control specification. If an implementation detail conflicts with current live-verified behavior, preserve the verified behavior and make the conflict explicit before changing semantics.

## 2. Existing Magapoke behavior that remains authoritative

Unless explicitly changed here:

- Discovery incremental traversal remains latest-first so generic known-streak stopping continues to work.
- Magapoke `order_key` may remain NULL.
- Batch remains sequential through the shared Batch contract.
- Existing adapter-owned page-change retry behavior remains unchanged.
- Ticket consumption is successful only after the requested ticket action disappears and usable viewer content is observed.
- `access_granted_until` remains the conservative observed Magapoke grant (`consumed_at + 71 hours`) unless separate live evidence changes it.
- Premium Ticket balance is live external state and is not persisted as a Catalog balance.
- Points/coins/subscriptions/unknown purchase actions are never used as fallback.
- Normal real-site operation remains shared Chrome/profile through CDP.

## 3. Magapoke Batch ordering

### 3.1 Discovery order does not change

Do **not** reverse Magapoke Discovery traversal. Incremental Discovery remains latest-first.

### 3.2 Batch candidate order

Within the same Work, process candidates old-to-new using:

```text
published_at ASC (NULL last), source_id ASC
```

`source_id` is only a stable tie-breaker.

Across Works, preserve existing stable Work ordering unless a separate specification changes it.

This ordering applies to normal Batch and grant-only/resource passes.

## 4. Magapoke access resources

Magapoke currently defines two access resources:

```text
work_ticket
premium_ticket
```

These names are site-specific instances of the generic access-resource contract in `docs/ACCESS_CONTROL_AND_PACING.md`.

The normal Magapoke resource order is:

```text
work_ticket
premium_ticket
```

Generic Batch orchestration must not hard-code these names. The Magapoke policy/integration provides resource support and ordering.

## 5. Work Ticket state and cooldown

### 5.1 Work-scoped state

A Work Ticket is Work-scoped. Persist its local state separately from episode-level `Source.quota_started_at` and separately from Premium Ticket state.

A minimal generic persistence shape is preferred, for example:

```text
quota_resource_states
  site
  work_id
  resource
  last_consumed_at
```

The exact table name may differ, but state must distinguish at least:

```text
(site, work_id, resource)
```

A Catalog schema migration is expected. Use the existing explicit migration and backup mechanism.

### 5.2 Local negative gate

Magapoke runtime settings include:

```text
work_ticket_cooldown_hours = 23
```

Before site access for a Work Ticket pass:

```text
last_consumed_at exists
AND now - last_consumed_at < work_ticket_cooldown_hours
    -> skip locally
    -> do not open an episode
    -> do not apply inter-candidate delay solely for this local skip
```

This is only a negative local gate. Reaching 23 hours does **not** prove the Work Ticket is available; live UI remains authoritative.

### 5.3 Work Ticket unavailable

If cooldown permits checking but the live page does not offer a usable Work Ticket:

- return/record `work_ticket_unavailable` or equivalent expected resource-unavailable result,
- do not update `last_consumed_at`,
- do not create a grant,
- close the page safely,
- apply shared inter-candidate pacing because the site was contacted.

### 5.4 Work Ticket consumed

Only after one Work Ticket click is confirmed by viewer availability:

- persist source access grant,
- update Work-scoped `work_ticket.last_consumed_at`,
- never update the timestamp merely because the button was visible or clicked without confirmed entry.

## 6. Magapoke resource selection semantics

The live Magapoke UI is final authority for actual resource consumption.

An observed Magapoke constraint is:

> When a Work Ticket is available, normal UI guides entry through Work Ticket use rather than allowing Premium Ticket to be forced instead.

The implementation must respect that behavior and must not attempt to bypass or hide the Work Ticket path.

### 6.1 Work Ticket pass

Allowed resource: `work_ticket` only.

- apply the 23-hour local cooldown before site access,
- if Work Ticket is available, consume it and confirm viewer access,
- if unavailable, skip as expected resource-unavailable,
- never fall back to Premium Ticket inside the same candidate attempt.

### 6.2 Premium Ticket pass

Allowed resource: `premium_ticket` only.

- do not intentionally consume a Work Ticket,
- if normal UI requires/offers Work Ticket and Premium cannot normally be selected, return `premium_ticket_unavailable`,
- do not manipulate the page to bypass Work Ticket priority,
- if normal Premium path is exposed, read the live semantic Premium Ticket balance and proceed,
- a semantic balance of zero stops further Premium attempts for that resource pass,
- Premium balance is never persisted as Catalog balance.

### 6.3 `all`

Shared `all` orchestration executes Magapoke's policy-defined resource passes in order:

```text
work_ticket pass
  -> replan against current Catalog state
  -> premium_ticket pass
```

This is intentionally an orchestration rule, not an instruction for one candidate to click whichever resource appears first.

After one Work Ticket has been consumed for a Work, later pending episodes in that Work may become eligible for Premium Ticket when the normal live UI exposes the Premium path.

### 6.4 Fail-closed fallback

Resource switching occurs only through explicit resource-pass orchestration.

Examples:

- Work Ticket unavailable during Work Ticket pass -> do not click Premium in that attempt,
- Premium unavailable because Work Ticket is the normal UI path -> skip Premium attempt,
- timeout -> do not try another resource,
- unknown/ambiguous purchase UI -> fail closed,
- HTTP rejection/challenge/CAPTCHA -> shared AccessGuard stop,
- DOM classification failure -> fail closed.

This prevents a detection bug from accidentally consuming a different resource.

## 7. Grant-only behavior for Magapoke

The shared grant-only contract is defined in `docs/ACCESS_CONTROL_AND_PACING.md`.

Supported Magapoke forms are intended to be:

```text
batch run --site magapoke --grant-only work_ticket
batch run --site magapoke --grant-only premium_ticket
batch run --site magapoke --grant-only all
```

The generic CLI/orchestration validates these names through the Magapoke policy rather than hard-coding them globally.

Successful Magapoke grant-only:

```text
select candidate for explicit resource pass
  -> open episode
  -> use only the configured resource if normal UI permits it
  -> confirm viewer content
  -> persist confirmed grant/resource state
  -> close page
  -> shared inter-candidate delay
  -> next candidate
```

Grant-only must not capture pages, package output, create a successful content artifact, or complete the Item.

Existing `--limit` behavior should remain available and should count actual site attempts consistently.

## 8. Normal Batch after grants

Normal:

```text
batch run --site magapoke
```

continues to capture/package pending items.

An episode with an active persisted `access_granted_until` is treated as direct access according to the existing Magapoke SitePolicy.

Grant-only is preparatory and does not replace normal Batch crawling.

Explicit grant-only resource passes must avoid unnecessary traversal of unrelated resource passes.

## 9. Shared AccessGuard application

Magapoke uses the shared AccessGuard defined in `docs/ACCESS_CONTROL_AND_PACING.md`.

Magapoke integration must provide the relevant first-party/page/API/image hosts required for its viewer so shared 403/429 stop policy does not react to unrelated third-party traffic.

Magapoke must stop safely when enabled shared policy detects:

```text
relevant-host HTTP 403
relevant-host HTTP 429
explicit challenge
visible CAPTCHA
```

An explicit response challenge marker such as `cf-mitigated: challenge` is valid evidence.

Site-specific challenge/CAPTCHA states may be added only when separately live-verified and conservatively classified.

Do not add broad title/body heuristics merely to increase detections.

## 10. Shared metrics application

Magapoke normal Batch and grant-only/resource passes emit the shared incremental JSONL metrics defined in `docs/ACCESS_CONTROL_AND_PACING.md`.

In addition to shared fields, expose successful resource grants/consumption by resource where practical.

Do not persist Premium Ticket balance as a metric-backed Catalog state.

## 11. Implementation phases

The repository-wide implementation order is defined by the shared specification. Magapoke-specific work lands in these steps:

### Shared Phase 1 integration

- apply shared runtime settings/pacing,
- change Magapoke Batch ordering to `published_at ASC (NULL last), source_id ASC` within a Work,
- preserve latest-first Discovery,
- preserve Magapoke navigation retries.

### Shared Phase 2 integration

- provide Magapoke relevant-host classification,
- wire shared 403/429/challenge/CAPTCHA stop behavior,
- wire shared JSONL metrics,
- preserve existing ordinary 5xx/transient retry behavior unless separately specified.

### Shared Phase 3 integration

- **IMPLEMENTED**: expose `work_ticket` and `premium_ticket` through the generic
  supported-resource/order contract,
- **IMPLEMENTED**: preserve existing `quota_resource` and `AccessConsumption` semantics,
- **IMPLEMENTED**: generic Batch obtains additional resource passes from Site Policy
  and does not interpret Magapoke resource names.

### Shared Phase 4 integration - Work Ticket grant-only

**IMPLEMENTED** for Work Ticket grant-only. Premium/all behavior is implemented
in the Phase 5 section below.

- add Work-scoped resource state migration,
- add 23-hour local negative gate,
- wire generic grant-only to `work_ticket`,
- persist `last_consumed_at` only after confirmed Work Ticket entry,
- persist conservative source grant,
- normal Batch and grant-only share the observed-consumption persistence path;
  later failure does not roll back confirmed source/state updates,
- do not capture/package/complete.

### Shared Phase 5 integration - Premium/all

**IMPLEMENTED**.

- wire `premium_ticket` into the generic resource pass contract,
- preserve live semantic Premium balance checks,
- stop Premium pass at zero,
- preserve Work Ticket UI priority,
- implement `all` as policy-defined Work Ticket pass then replan then Premium pass,
- fail closed on ambiguous/error states.

Premium grant-only uses the same `entry_only=True` adapter path as Work Ticket.
Confirmed Premium consumption records the source grant through
`policy.access_grant_until(consumed_at)` and does not create a Work-scoped
resource state. Premium balance remains live-only. `all` resolves the ordered
grant-only resources from Site Policy, replans Catalog between passes, and
shares one total site-attempt limit; local Catalog skips do not consume it.
Resource exhaustion ends only the current pass, while AccessGuard fatal stops
end the complete run. No grant-only pass captures, packages, creates an
Artifact, or completes an Item.

### Phase 6 verification status

**AUTOMATED VERIFIED / LIVE PARTIAL**. Cross-site regression evidence,
read-only planning results, and intentionally unrun ticket-consuming scenarios
are recorded in `docs/PHASE6_VERIFICATION.md`.

## 12. Magapoke acceptance criteria

Magapoke-specific work is complete when:

- Discovery remains latest-first,
- Batch within a Work is old-to-new by `published_at`, then `source_id`,
- `work_ticket` and `premium_ticket` are exposed through generic resource contracts,
- generic Batch does not hard-code those resource names,
- Work Ticket cooldown can skip a Work without site access,
- Work Ticket state is Work-scoped and distinct from Premium state,
- live UI remains authoritative after cooldown,
- confirmed Work Ticket consumption updates `last_consumed_at`,
- Premium-only pass never intentionally consumes Work Ticket,
- available/required Work Ticket is never bypassed to force Premium,
- `all` follows policy-defined Work Ticket then Premium passes with replanning,
- Premium balance remains live-only and zero stops Premium attempts,
- grant-only never captures/packages/completes,
- confirmed grants update Catalog while Item remains pending,
- shared relevant-host 403/429/challenge/CAPTCHA behavior works without reacting to unrelated third-party traffic,
- shared metrics cover normal and abnormal Magapoke Batch completion,
- existing native capture, ticket confirmation, 71-hour conservative grant, END/NEXT_CONTENT, packaging, and navigation retry behavior remain covered by regression tests.

## 13. Explicit Magapoke non-goals

Not part of this Magapoke-specific work:

- changing shared Batch to parallel execution,
- storing Premium Ticket balance in Catalog,
- bypassing Work Ticket priority to force Premium,
- points/coins/subscription purchase fallback,
- reversing incremental Discovery,
- assuming a Work Ticket must exist after 23 hours without live confirmation,
- changing adapter-owned retry algorithms merely because shared pacing is added,
- duplicating shared CAPTCHA/challenge/metrics logic inside Magapoke when the shared mechanism can be used.

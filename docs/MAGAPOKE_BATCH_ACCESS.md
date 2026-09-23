# Magapoke Batch Access / Load Control Specification

## 1. Status

This document defines the adopted design for the next Magapoke Batch iteration.

The behaviors described here are **planned unless the current code already provides them**. Existing live-verified capture, ticket-entry, quota persistence, Discovery, and packaging behavior must not be weakened while implementing this specification.

This document supplements `docs/DISCOVERY_AND_BATCH.md`. If an implementation detail conflicts with current code or live-verified behavior, preserve the verified behavior and make the conflict explicit before changing semantics.

## 2. Goals

The change has six main goals:

1. avoid unnecessarily dense automated access,
2. allow ticket grants to be performed separately from image capture,
3. process Magapoke candidates in a stable old-to-new order,
4. avoid probing Work Ticket state when local state already says the ticket cannot have recharged yet,
5. stop safely when the site returns explicit access/rate-limit rejection,
6. make access volume observable through lightweight runtime metrics.

This is load-control and fail-safe behavior. It is not intended to bypass rate limits, WAFs, access controls, or site UI rules.

## 3. Existing behavior that remains authoritative

The following existing behaviors remain unchanged unless this specification explicitly changes them:

- Batch execution is sequential. Do not introduce parallel episode execution.
- There is no need to add a configurable `max_concurrency`; the current sequential `for`/`await` execution is the desired behavior.
- Discovery incremental traversal remains latest-first so that generic known-streak stopping continues to work correctly.
- Magapoke `order_key` may remain NULL.
- Ticket consumption is considered successful only after the requested ticket action disappears and usable viewer content is observed.
- `access_granted_until` remains the conservative Magapoke grant used by the current implementation (`consumed_at + 71 hours`) unless separate live evidence changes that rule.
- Premium Ticket balance is live external state and is not persisted as a Catalog balance.
- Points/coins/subscriptions/unknown purchase actions are never used as fallback.

## 4. Runtime settings

### 4.1 Configuration file

Add a small human-editable root configuration file:

```text
crawler.yaml
```

`watchlist.yaml` continues to define **what to discover**. `crawler.yaml` defines **how the crawler runs**.

Initial Magapoke shape:

```yaml
sites:
  magapoke:
    page_turn_delay_ms: 1000
    inter_candidate_delay_ms: 3000
    work_ticket_cooldown_hours: 23
```

The implementation may use typed settings internally, but YAML must remain simple configuration rather than a rule DSL.

### 4.2 Safe defaults

The code must contain safe defaults for these values. If `crawler.yaml` is missing, deleting the file must not silently turn Magapoke into an unrestricted zero-delay crawler.

Initial defaults:

- `page_turn_delay_ms = 1000`
- `inter_candidate_delay_ms = 3000`
- `work_ticket_cooldown_hours = 23`

No random jitter is required in the first implementation. Delays exist to reduce request density, not to imitate human timing.

### 4.3 Delay semantics

`page_turn_delay_ms`:

- applies to normal page-by-page crawl,
- is inserted after the current page has been successfully captured/saved and before intentionally advancing to the next page,
- must not replace readiness/change waits,
- must not be multiplied accidentally by retry loops.

`inter_candidate_delay_ms`:

- applies between site-accessing Batch candidates,
- applies to normal Batch crawl and `--grant-only` execution,
- occurs after the current candidate/page is closed and before opening the next network candidate,
- is not required for a candidate skipped entirely from local Catalog state without contacting the site.

## 5. Batch ordering

### 5.1 Discovery order does not change

Do **not** reverse Magapoke Discovery traversal. Incremental Discovery must continue to enumerate latest-first because the generic known-streak stop relies on that contract.

### 5.2 Magapoke Batch candidate order

Within the same Work, process candidates old-to-new using:

```text
published_at ASC (NULL last), source_id ASC
```

`source_id` is a stable tie-breaker only; it is not the primary semantic ordering key.

Across Works, preserve the existing stable Work ordering unless a separate specification changes it.

This ordering applies consistently to normal Batch processing and grant-only processing.

## 6. Grant-only mode

### 6.1 CLI

Extend Magapoke Batch with:

```text
batch run --site magapoke --grant-only work_ticket
batch run --site magapoke --grant-only premium_ticket
batch run --site magapoke --grant-only all
```

`--grant-only` is Magapoke-specific behavior exposed through Batch orchestration. Unsupported sites/resources must fail clearly rather than silently changing behavior.

### 6.2 Meaning of grant-only

Grant-only performs access acquisition without capturing the episode.

Successful grant-only flow:

```text
select candidate
  -> open episode
  -> choose only an allowed ticket resource according to site UI
  -> click once
  -> confirm viewer content is available
  -> persist access grant / resource state
  -> close page
  -> inter-candidate delay
  -> next candidate
```

Grant-only must **not**:

- capture pages,
- package a ZIP,
- mark the Item completed,
- create a successful content artifact merely because access was granted.

The Item remains pending and can later be processed by normal `batch run` using its active grant as direct access.

Existing `--limit` behavior should remain available and should count actual site attempts consistently.

## 7. Work Ticket state and cooldown

### 7.1 Why local cooldown state is needed

A Work Ticket is work-scoped. Repeatedly opening a Work when the locally known previous consumption occurred less than the configured recharge interval ago creates unnecessary traffic.

Therefore persist a work-scoped resource state independent of episode `Source.quota_started_at`.

A minimal generic model is preferred, for example:

```text
quota_resource_states
  site
  work_id
  resource
  last_consumed_at
```

The exact table name may differ, but the state must distinguish at least:

```text
(site, work_id, resource)
```

so Work Ticket state cannot be confused with Premium Ticket consumption.

A Catalog schema migration is expected for this state. Use the existing explicit migration and backup mechanism.

### 7.2 Cooldown rule

For `work_ticket`, before any site access for that Work:

```text
last_consumed_at exists
AND now - last_consumed_at < work_ticket_cooldown_hours
    -> skip locally
    -> do not open an episode
    -> do not apply inter-candidate delay solely for this local skip
```

Default cooldown is 23 hours.

This is only a negative local gate: it says "do not bother checking yet". Reaching 23 hours does **not** prove that a ticket is available; the live UI remains authoritative.

### 7.3 Work Ticket unavailable

If the cooldown permits checking but the live page does not offer a Work Ticket:

- return/record an expected `work_ticket_unavailable` style skip,
- do not update `last_consumed_at`,
- do not create a grant,
- close the page safely,
- apply the normal inter-candidate delay because the site was contacted.

### 7.4 Work Ticket consumed

Only after one Work Ticket click is confirmed by viewer availability:

- persist source access grant,
- update the Work-scoped `work_ticket.last_consumed_at`,
- never update the timestamp merely because the button was visible or clicked without confirmed entry.

## 8. Ticket selection semantics

The live Magapoke UI is the final authority. An important observed constraint is:

> When a Work Ticket is available, the UI guides access through Work Ticket consumption rather than allowing Premium Ticket to be forced instead.

The implementation must respect that behavior and must not attempt to bypass or hide the Work Ticket path.

### 8.1 `--grant-only work_ticket`

Allowed resource: Work Ticket only.

- Apply the 23-hour local cooldown before site access.
- If Work Ticket is available, consume it and confirm the viewer.
- If Work Ticket is unavailable, skip.
- Never fall back to Premium Ticket.

### 8.2 `--grant-only premium_ticket`

Allowed resource: Premium Ticket only.

- Do not intentionally consume a Work Ticket.
- If the live UI requires/offers Work Ticket for that candidate and Premium cannot be selected under normal UI behavior, treat the candidate as `premium_ticket_unavailable` and skip it.
- Do not manipulate the page to bypass Work Ticket preference.
- If the page exposes the normal Premium-only path, read the live Premium balance and proceed.
- A semantic balance of zero stops further Premium grant attempts for the run/resource pass.

### 8.3 `--grant-only all`

Allowed resources: Work Ticket and Premium Ticket.

Preferred behavior follows the live UI:

```text
Work Ticket available
    -> consume Work Ticket
else Premium Ticket available
    -> consume Premium Ticket
else
    -> expected resource-unavailable skip
```

Do not implement "Premium first" behavior.

After a Work Ticket has been consumed for one Work, later pending episodes in the same Work may continue old-to-new and use Premium Ticket where the UI naturally exposes the Premium path.

### 8.4 Fail-closed fallback

Resource fallback is allowed only when the live UI gives a known, explicit state.

Examples:

- known Work Ticket unavailable + valid Premium UI in `all` mode -> Premium may be used,
- timeout -> do not consume another resource as fallback,
- HTTP 403/429 -> stop according to section 10,
- unknown/ambiguous purchase UI -> fail closed,
- DOM classification failure -> fail closed.

This prevents an implementation bug in Work Ticket detection from accidentally consuming Premium Tickets.

## 9. Normal Batch after grants

Normal:

```text
batch run --site magapoke
```

continues to capture/package pending items.

An episode with an active persisted `access_granted_until` is treated as direct access according to the existing Magapoke Site Policy.

Grant-only is therefore a preparatory operation; it does not replace normal Batch crawling.

The eventual implementation should avoid unnecessary duplicate resource passes. In particular, an explicit `--grant-only premium_ticket` must not first traverse every Work Ticket candidate merely because the old normal Batch implementation performed Work Ticket before the Premium additional resource pass.

## 10. HTTP 403 / 429 fail-safe

### 10.1 Stop behavior

During normal Batch and grant-only processing:

- HTTP 429 from a relevant Magapoke content host -> stop the Magapoke Batch run/resource processing immediately,
- HTTP 403 from a relevant Magapoke content host -> stop immediately,
- do not repeatedly retry 403/429,
- if 429 includes `Retry-After`, record it in logs/metrics,
- preserve already confirmed Catalog updates from earlier candidates.

This should be represented as a distinct stop/error state rather than an ordinary capture failure.

### 10.2 Relevant hosts only

Do not stop because an unrelated analytics, ad, or third-party request receives 403/429.

The set of relevant hosts is site-specific code/configuration owned by the Magapoke integration. It should cover the page/API/image hosts required for the viewer, including the known Magapoke origin/CDN paths used by the implementation.

Do not place WAF-bypass behavior, proxy rotation, User-Agent rotation, fingerprint spoofing, or CAPTCHA bypass in this feature.

## 11. HTTP/access metrics

Add lightweight in-process metrics for Batch runs. No Prometheus stack or persistent metrics database is required initially.

At minimum, Batch summary should expose:

```text
site
mode (normal / grant-only resource)
batch_start_time
batch_end_time
elapsed
candidates_started
candidates_completed
candidates_failed
candidates_skipped
http_requests_total
http_403_count
http_429_count
http_5xx_count
retry_count
```

For grant-only, also make successful grants observable by resource where practical.

Candidate-level information should include at least:

```text
item/source identity
start time
elapsed
request count
retry count
result / stop reason
resource consumed, if any
```

Also record:

- request count by relevant host,
- response-byte total where it can be obtained cheaply from response metadata such as `Content-Length`.

Do not fetch/read response bodies solely to improve byte accounting. An unknown/incomplete byte total is preferable to extra traffic.

Metrics must be emitted on normal completion and abnormal Batch stop.

## 12. Retry interaction

- Existing bounded retries for ordinary transient viewer/capture behavior remain.
- 403/429 are not ordinary retryable capture failures.
- 5xx may continue to follow the existing bounded retry behavior unless a later policy explicitly changes it.
- Metrics must count retries without changing their semantics.

## 13. Implementation phases

Implement in small reviewable phases.

### Phase 1 - settings, delays, ordering

- add `crawler.yaml` loader and safe Magapoke defaults,
- add `page_turn_delay_ms`,
- add `inter_candidate_delay_ms`,
- change Magapoke Batch ordering to `published_at ASC (NULL last), source_id ASC` within a Work,
- preserve latest-first Discovery,
- preserve sequential Batch execution,
- add tests for settings/defaults/delay placement/order.

### Phase 2 - Work Ticket grant-only

- add Catalog work-scoped quota-resource state and migration,
- add `--grant-only work_ticket`,
- implement 23-hour local negative gate,
- skip locally when cooldown has not elapsed,
- otherwise check live UI,
- persist `last_consumed_at` only after confirmed Work Ticket entry,
- persist `access_granted_until`,
- do not capture/package/complete,
- add tests for cooldown, unavailable, confirmed consumption, and failure persistence boundaries.

### Phase 3 - Premium / all grant-only

- add `--grant-only premium_ticket`,
- add `--grant-only all`,
- respect Work Ticket UI priority,
- never bypass an available Work Ticket to force Premium,
- preserve live Premium balance semantics,
- stop Premium attempts on zero balance,
- allow `all` to continue with Premium on later candidates after Work Ticket use where the live UI exposes it,
- fail closed on ambiguous UI or errors,
- add resource-selection tests.

### Phase 4 - HTTP fail-safe and metrics

- observe relevant Magapoke HTTP responses,
- stop on relevant 403/429,
- record `Retry-After`,
- add Batch/candidate access metrics,
- keep third-party requests out of stop decisions,
- preserve existing 5xx/retry behavior,
- add tests for 403/429 stop propagation and metrics summaries.

## 14. Acceptance criteria

The implementation is complete when all of the following are true:

- normal Magapoke Batch remains sequential,
- no configurable concurrency feature is added merely for this work,
- Discovery remains latest-first,
- Batch within a Work is old-to-new by `published_at`, then `source_id`,
- page and candidate delays come from `crawler.yaml`/safe defaults rather than required CLI flags,
- grant-only Work/Premium/all modes are independently selectable,
- grant-only never packages or completes an Item,
- Work Ticket cooldown can skip a Work without touching the site,
- Work Ticket state is work-scoped and distinguished from Premium usage,
- live UI remains authoritative after cooldown,
- an available Work Ticket is not bypassed to force Premium,
- Premium-only skips candidates where normal UI requires Work Ticket,
- `all` uses Work Ticket when available and Premium otherwise,
- confirmed grants update Catalog even though the Item remains pending,
- relevant 403/429 stop the Magapoke Batch safely,
- unrelated third-party 403/429 do not stop it,
- metrics are printed on success and abnormal stop,
- MangaOne and BookWalker behavior is not changed by the Magapoke-specific implementation,
- existing Magapoke native capture, ticket confirmation, and 71-hour conservative grant behavior regressions are covered.

## 15. Explicit non-goals

Not part of this work:

- parallel Magapoke crawling,
- IP/proxy rotation,
- User-Agent/fingerprint spoofing,
- CAPTCHA/WAF bypass,
- random timing intended to disguise automation,
- persistent monitoring infrastructure,
- storing Premium Ticket balance in Catalog,
- reversing incremental Discovery traversal,
- replacing the live UI with a purely local assumption that a ticket must be available after 23 hours.

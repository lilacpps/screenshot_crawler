# Magapoke Batch Access / Load Control Specification

## 1. Status

This document defines the adopted design for the next Magapoke Batch iteration and the small shared runtime pacing mechanism introduced with it.

The behaviors described here are **planned unless the current code already provides them**. Existing live-verified capture, ticket-entry, quota persistence, Discovery, navigation retry, and packaging behavior must not be weakened while implementing this specification.

This document supplements `docs/DISCOVERY_AND_BATCH.md`. If an implementation detail conflicts with current code or live-verified behavior, preserve the verified behavior and make the conflict explicit before changing semantics.

The shared pacing portion applies to Magapoke, Manga ONE, and BookWalker. Magapoke ticket/resource semantics remain Magapoke-specific.

## 2. Goals

The change has seven main goals:

1. avoid unnecessarily dense automated access without trying to imitate human behavior,
2. provide one small site-configurable pacing mechanism usable by Magapoke, Manga ONE, and BookWalker,
3. allow Magapoke ticket grants to be performed separately from image capture,
4. process Magapoke candidates in a stable old-to-new order,
5. avoid probing Magapoke Work Ticket state when local state already says the ticket cannot have recharged yet,
6. stop safely when the site returns explicit access/rate-limit/challenge rejection,
7. make Batch access volume observable through lightweight runtime metrics.

This is load-control, observability, and fail-safe behavior. It is not intended to bypass rate limits, WAFs, access controls, CAPTCHA, challenge systems, or site UI rules.

## 3. Existing behavior that remains authoritative

The following existing behaviors remain unchanged unless this specification explicitly changes them:

- Batch execution is sequential. Do not introduce parallel episode execution.
- There is no need to add a configurable `max_concurrency`; the current sequential `for`/`await` execution is the desired behavior.
- Existing adapter-owned page-change retry logic remains authoritative. The pacing change must not rewrite Magapoke, Manga ONE, or BookWalker retry/timeout behavior.
- Discovery incremental traversal remains latest-first so that generic known-streak stopping continues to work correctly.
- Magapoke `order_key` may remain NULL.
- Magapoke ticket consumption is considered successful only after the requested ticket action disappears and usable viewer content is observed.
- `access_granted_until` remains the conservative Magapoke grant used by the current implementation (`consumed_at + 71 hours`) unless separate live evidence changes that rule.
- Premium Ticket balance is live external state and is not persisted as a Catalog balance.
- Points/coins/subscriptions/unknown purchase actions are never used as fallback.
- The standard real-site browser model remains the shared real Chrome/profile connected through CDP. This work does not add browser fingerprint manipulation or session-reset behavior.

## 4. Runtime settings and shared pacing

### 4.1 Configuration file

Add a small human-editable root configuration file:

```text
crawler.yaml
```

`watchlist.yaml` continues to define **what to discover**. `crawler.yaml` defines **how the crawler runs**.

Initial shape:

```yaml
sites:
  magapoke:
    page_turn_delay_ms: 1000
    inter_candidate_delay_ms: 3000
    work_ticket_cooldown_hours: 23

  mangaone:
    page_turn_delay_ms: 1000
    inter_candidate_delay_ms: 3000

  bookwalker:
    page_turn_delay_ms: 1000
    inter_candidate_delay_ms: 3000
```

The implementation may use typed settings internally, but YAML must remain simple configuration rather than a rule DSL.

Do not add a YAML inheritance/default hierarchy in the first implementation. The known sites may be listed explicitly. Code must still have safe defaults if the file or a site entry is absent.

### 4.2 Shared versus site-specific settings

The following settings are generic runtime pacing settings:

```text
page_turn_delay_ms
inter_candidate_delay_ms
```

They must be reusable by Magapoke, Manga ONE, and BookWalker without placing site-name branches in Core.

The following setting is Magapoke-specific:

```text
work_ticket_cooldown_hours
```

The configuration loader/runtime orchestration resolves the current site's settings and passes the generic page delay into `RunConfig`. `CrawlerRunner` must not parse `crawler.yaml` directly and must not contain site-specific configuration branches.

### 4.3 Safe defaults and validation

Safe initial code defaults:

- `page_turn_delay_ms = 1000`
- `inter_candidate_delay_ms = 3000`
- Magapoke `work_ticket_cooldown_hours = 23`

Deleting `crawler.yaml`, or omitting one of the known site entries, must not silently turn that site into an unrestricted zero-delay crawler.

Delay values must be non-negative integers. An explicit zero may be supported as an intentional operator override, but zero is not the missing-configuration default.

No random jitter is required. Delays exist to reduce request density, not to imitate human timing.

### 4.4 `page_turn_delay_ms` ownership and exact placement

`page_turn_delay_ms` is a Core run input and applies to normal page-by-page CONTENT crawling, including manual crawl and Batch crawl.

For a successfully captured CONTENT state, the sequence must be:

```text
capture current content
  -> save all new capture artifacts for that logical page/spread
  -> persist manifest/progress
  -> page_turn_delay_ms
  -> initial adapter.go_next()
  -> adapter.wait_for_change()
       -> adapter-owned bounded retry if required
```

The delay is applied **once per intentional initial CONTENT advance**, not once per saved artifact. A spread or multi-part capture therefore waits once after all parts are saved.

The delay must be implemented outside `SiteAdapter.go_next()` and outside `SiteAdapter.wait_for_change()`.

This boundary is mandatory because the existing adapters already own bounded advance retries:

- Magapoke may retry `go_next()` while the previous identity remains unchanged,
- Manga ONE may retry its viewer advance while the previous identity remains unchanged,
- BookWalker may alternate known advance inputs while the previous identity remains unchanged.

Those internal retries must remain unchanged and must **not** receive an additional pacing delay on every retry.

### 4.5 Timeout interaction

`page_turn_delay_ms` is intentional pacing before the initial page advance. It must not consume the adapter's page-change timeout budget.

In particular:

- do not put the delay inside the timed `_adapter_call(adapter.go_next(...))`,
- do not start `wait_for_change()` before the delay,
- do not reduce `page_change_timeout_ms` by the delay amount,
- do not multiply the delay through adapter retry loops.

The intended timing is:

```text
save complete
  -> pacing delay
  -> start initial go_next operation
  -> start normal page-change observation/retry budget
```

This preserves the current adapter retry semantics instead of making a 1-second pacing choice consume a 10- or 14-second navigation budget.

### 4.6 States that do not receive page-turn pacing

`page_turn_delay_ms` is for successful CONTENT capture followed by an intentional advance.

It does not apply to:

- AD advancement in the Core state loop,
- adapter-internal advance retries,
- loading polling,
- same-content/change waiting where no new content was saved,
- initialization/entry clicks,
- local Catalog skips,
- ticket confirmation clicks.

Readiness/change waits remain signal-driven and bounded; the pacing delay must not replace them.

### 4.7 `inter_candidate_delay_ms`

`inter_candidate_delay_ms` is Batch-orchestration pacing, not Core page navigation.

It:

- applies between site-accessing Batch candidates,
- applies to normal Batch crawl and Magapoke `--grant-only` execution,
- occurs after the current candidate/page is safely finished/closed and before opening the next network candidate,
- is not required for a candidate skipped entirely from local Catalog state without contacting the site,
- is applied once between candidates and is not multiplied by candidate-internal retry loops.

## 5. Magapoke Batch ordering

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

## 6. Magapoke grant-only mode

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

After a Work Ticket has been consumed for one Work, later pending episodes in the same Work may continue old-to-new and use Premium Ticket where the live UI naturally exposes the Premium path.

### 8.4 Fail-closed fallback

Resource fallback is allowed only when the live UI gives a known, explicit state.

Examples:

- known Work Ticket unavailable + valid Premium UI in `all` mode -> Premium may be used,
- timeout -> do not consume another resource as fallback,
- HTTP 403/429/challenge -> stop according to section 10,
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

## 10. Access rejection / challenge fail-safe

### 10.1 Stop behavior

During Magapoke normal Batch and grant-only processing:

- HTTP 429 from a relevant Magapoke content host -> stop the Magapoke Batch run/resource processing immediately,
- HTTP 403 from a relevant Magapoke content host -> stop immediately,
- a relevant response explicitly marked as a Cloudflare challenge, including `cf-mitigated: challenge`, -> stop immediately,
- a site-specific, explicitly recognized challenge/interstitial state may also stop the run when it can be classified without broad heuristic guessing,
- do not repeatedly retry 403/429/challenge responses,
- do not automatically reload/solve/continue through a challenge,
- if 429 includes `Retry-After`, record it in logs/metrics,
- preserve already confirmed Catalog updates from earlier candidates.

Challenge detection should produce a distinct stop reason such as `challenge_detected`, rather than being folded into an ordinary capture failure.

The fail-safe mechanism may be implemented in a reusable way, but this specification requires Magapoke integration first. Do not silently alter another site's stop behavior merely because the shared collector exists.

### 10.2 Relevant hosts only

Do not stop because an unrelated analytics, ad, or third-party request receives 403/429.

The set of relevant hosts is site-specific code/configuration owned by the site integration. For Magapoke it should cover the page/API/image hosts required for the viewer, including the known origin/CDN paths used by the implementation.

A first-party response carrying an explicit challenge marker is stronger evidence than a generic DOM/title guess. Avoid broad challenge heuristics in Core.

### 10.3 No challenge-evasion behavior

Do not place any of the following in this feature:

- WAF/CAPTCHA challenge solving or bypass,
- proxy/IP rotation,
- User-Agent rotation,
- Canvas/WebGL/TLS/fingerprint spoofing,
- synthetic mouse movement, scroll, or keyboard activity intended to imitate a person,
- random human-like timing,
- browser/profile/session cycling intended to reset a challenge/behavioral session.

The crawler should use the normal shared Chrome/CDP model, perform only the interactions required by the viewer, pace access conservatively, and stop when the site explicitly rejects/challenges the run.

## 11. HTTP/access metrics

### 11.1 Purpose and storage

Add lightweight runtime metrics for Batch runs so access volume and rejection behavior can be inspected after a run.

These metrics are operational/diagnostic data, not Catalog domain state. Do **not** add a Catalog table or schema migration for them initially.

Persist them as append-friendly JSON Lines under the ignored runtime output tree, for example:

```text
output/metrics/
  20260923T140512-magapoke-normal-<run-id>.jsonl
  20260923T151022-mangaone-normal-<run-id>.jsonl
```

The exact filename format may differ, but it must be unique per Batch run and include enough identity to find the site/mode.

Write records incrementally and flush them so an abnormal process exit can still leave useful partial history. A single giant JSON document written only at graceful shutdown is not preferred.

The CLI should also print a concise end-of-run summary and the metrics path.

### 11.2 Batch summary fields

At minimum, the Batch summary should expose:

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
challenge_count
retry_count
```

For grant-only, also make successful grants observable by resource where practical.

### 11.3 Candidate-level fields

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

Where available cheaply, it may also include captured page count.

Also record:

- request count by relevant host,
- response-byte total where it can be obtained cheaply from response metadata such as `Content-Length`,
- `Retry-After` when a 429 provides it,
- explicit challenge stop reason/count.

Do not fetch/read response bodies solely to improve byte accounting. An unknown/incomplete byte total is preferable to extra traffic.

Metrics must be emitted on normal completion and abnormal Batch stop.

The metrics writer/collector should be site-neutral where practical. Site-specific relevant-host classification and stop policy remain outside Core site branches.

### 11.4 No guessed request/page threshold yet

Do not add a guessed rule such as "stop every 100 pages" or "restart the browser every 200 pages" merely to approximate an unknown bot-detection threshold.

The existing `--limit` may be used operationally to bound a run when desired, but the first implementation should collect real request/elapsed/challenge data before introducing another hard session-size policy.

## 12. Retry interaction

- Existing bounded retries for ordinary transient viewer/capture behavior remain.
- `page_turn_delay_ms` is not a retry delay and must not alter adapter retry timing.
- 403/429/challenge are not ordinary retryable capture failures.
- 5xx may continue to follow the existing bounded retry behavior unless a later policy explicitly changes it.
- Metrics must count retries without changing their semantics.
- A pacing change must not add duplicate page advances. The initial Core advance remains one call; any subsequent advance attempts remain adapter-owned retries conditioned on unchanged content/state.

## 13. Implementation phases

Implement in small reviewable phases.

### Phase 1 - shared settings/pacing and Magapoke ordering

- add `crawler.yaml` loader,
- add safe per-site runtime defaults for Magapoke, Manga ONE, and BookWalker,
- add generic `page_turn_delay_ms` to the resolved run settings / `RunConfig`,
- add generic `inter_candidate_delay_ms` to Batch orchestration settings,
- apply CONTENT page-turn pacing in Core only after successful capture/save and before the initial `adapter.go_next()`,
- do not apply page-turn pacing to AD advancement or adapter-internal advance retries,
- keep the pacing delay outside adapter timeout budgets,
- apply candidate pacing between site-accessing Batch candidates,
- change Magapoke Batch ordering to `published_at ASC (NULL last), source_id ASC` within a Work,
- preserve latest-first Discovery,
- preserve sequential Batch execution,
- do not change existing Magapoke/Manga ONE/BookWalker adapter retry algorithms.

Required Phase 1 tests include:

- config loading/defaults and non-negative validation,
- missing file/site still uses safe defaults,
- CONTENT order is save -> one delay -> initial go_next -> wait_for_change,
- multi-part/spread capture receives one delay, not one per artifact,
- AD advancement does not receive page-turn delay,
- adapter-internal retry does not receive another Core pacing delay,
- page-turn delay does not consume the `wait_for_change` timeout budget,
- explicit zero preserves the previous immediate initial-advance behavior,
- inter-candidate delay is once between site-accessing candidates and not for local-only skips,
- Magapoke Batch ordering,
- Manga ONE and BookWalker capture/navigation/retry semantics otherwise remain unchanged.

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

### Phase 4 - access fail-safe and metrics

- add lightweight JSONL Batch metrics under `output/metrics/`,
- print a concise Batch summary and metrics path,
- observe relevant Magapoke HTTP responses,
- stop Magapoke on relevant 403/429,
- stop on explicit challenge detection (`cf-mitigated: challenge` and any separately live-verified explicit site challenge state),
- record `Retry-After`,
- keep third-party requests out of 403/429 stop decisions,
- preserve existing 5xx/retry behavior,
- do not fetch response bodies solely for metrics,
- add tests for 403/429/challenge stop propagation, partial metrics persistence, and normal/abnormal metrics summaries.

The metrics collector/writer should be reusable for Manga ONE and BookWalker. Wiring the same passive metrics to those sites is acceptable as long as it does not change their capture/navigation semantics; site-specific rejection stop policies require their own explicit evidence/specification.

## 14. Acceptance criteria

The implementation is complete when all of the following are true:

- normal Batch remains sequential,
- no configurable concurrency feature is added merely for this work,
- `crawler.yaml` is a small runtime configuration file, not a rule DSL,
- Magapoke, Manga ONE, and BookWalker can resolve site-specific `page_turn_delay_ms` and `inter_candidate_delay_ms`,
- missing configuration retains safe non-zero pacing defaults,
- generic page-turn pacing is applied by Core after successful CONTENT save and immediately before the initial `go_next`,
- generic page-turn pacing does not run for AD advancement or adapter-internal retries,
- generic page-turn pacing does not consume the adapter page-change timeout budget,
- existing adapter retry algorithms and identity/change checks are not rewritten for pacing,
- generic inter-candidate pacing is owned by Batch orchestration,
- Magapoke Discovery remains latest-first,
- Magapoke Batch within a Work is old-to-new by `published_at`, then `source_id`,
- Magapoke grant-only Work/Premium/all modes are independently selectable,
- grant-only never packages or completes an Item,
- Work Ticket cooldown can skip a Work without touching the site,
- Work Ticket state is work-scoped and distinguished from Premium usage,
- live UI remains authoritative after cooldown,
- an available Work Ticket is not bypassed to force Premium,
- Premium-only skips candidates where normal UI requires Work Ticket,
- `all` uses Work Ticket when available and Premium otherwise,
- confirmed grants update Catalog even though the Item remains pending,
- relevant Magapoke 403/429 stop the Batch safely,
- explicit challenge detection stops safely with a distinct reason and is not automatically retried/solved,
- unrelated third-party 403/429 do not stop the Magapoke run,
- Batch metrics are stored as runtime JSONL rather than Catalog rows,
- metrics are usable after both normal completion and abnormal stop,
- metrics collection does not create extra network/body-fetch traffic solely for accounting,
- no arbitrary 100/200-page session threshold or automatic browser restart is introduced without evidence,
- existing Magapoke native capture, ticket confirmation, and 71-hour conservative grant behavior regressions are covered,
- existing Manga ONE and BookWalker capture/END/navigation/retry semantics are preserved except for the intentional shared pacing before initial CONTENT advances and between Batch candidates.

## 15. Explicit non-goals

Not part of this work:

- parallel crawling,
- IP/proxy rotation,
- User-Agent/fingerprint spoofing,
- Canvas/WebGL/TLS manipulation to disguise automation,
- CAPTCHA/WAF/challenge bypass or automatic challenge solving,
- synthetic pointer/scroll/keyboard behavior intended to imitate a person,
- random timing intended to imitate a person,
- browser/profile/session cycling intended to reset challenge or behavioral state,
- persistent monitoring infrastructure such as Prometheus,
- a persistent metrics database or Catalog metrics schema,
- an arbitrary fixed per-session page cap based on an unverified bot-detection threshold,
- storing Premium Ticket balance in Catalog,
- reversing incremental Discovery traversal,
- replacing the live UI with a purely local assumption that a ticket must be available after 23 hours,
- changing adapter-owned navigation retry algorithms merely because pacing is being added.

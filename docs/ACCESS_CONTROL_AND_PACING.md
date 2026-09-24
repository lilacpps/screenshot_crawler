# Shared Access Control, Pacing, Resource Selection, and Batch Observability

## 1. Status

This document defines the adopted shared design for runtime pacing, access fail-safe behavior, Batch access metrics, and extensible access-resource selection.

The behaviors described here are **planned unless the current code already provides them**. Existing live-verified capture, navigation retry, access-consumption confirmation, quota persistence, Discovery, and packaging behavior must not be weakened while implementing this specification.

This document is site-neutral. Site-specific resource names, UI selectors, relevant hosts, cooldowns, grant durations, and live-verified access rules remain owned by each site integration and its site-specific specification.

`docs/MAGAPOKE_BATCH_ACCESS.md` defines the first site-specific implementation of the shared resource-selection and grant-only contracts.

## 2. Goals

The shared change has six goals:

1. reduce unnecessary request density without trying to imitate human behavior,
2. provide small per-site runtime settings for pacing and access-stop policy,
3. stop safely on explicit rejection, challenge, or CAPTCHA states,
4. make access volume and abnormal stops observable with lightweight metrics,
5. define a reusable access-resource selection contract for future site integrations,
6. support access-grant-only orchestration without coupling Batch to Magapoke ticket names.

This work is load-control, fail-safe, observability, and access-resource orchestration. It is not intended to bypass rate limits, WAFs, access controls, CAPTCHA, challenge systems, or normal site UI rules.

## 3. Existing behavior that remains authoritative

Unless this specification explicitly changes behavior:

- Batch execution remains sequential.
- Do not add configurable candidate concurrency merely for this work.
- Existing adapter-owned page-change retry algorithms remain authoritative.
- Existing site-specific access-consumption confirmation remains authoritative.
- Existing site-specific quota/resource persistence semantics remain authoritative.
- Existing real Chrome/profile/CDP operation remains the browser model.
- Site-specific selectors and UI classification remain outside Core.
- Discovery traversal order remains site-specific and unchanged unless a site specification says otherwise.

## 4. Runtime configuration

### 4.1 Configuration file

Add a small root runtime configuration file:

```text
crawler.yaml
```

`watchlist.yaml` defines **what to discover**. `crawler.yaml` defines **how the crawler runs**.

Initial shape:

```yaml
sites:
  magapoke:
    page_turn_delay_ms: 1000
    inter_candidate_delay_ms: 3000
    stop_on_http_403: true
    stop_on_http_429: true
    stop_on_challenge: true
    stop_on_captcha: true
    work_ticket_cooldown_hours: 23

  mangaone:
    page_turn_delay_ms: 1000
    inter_candidate_delay_ms: 3000
    stop_on_http_403: true
    stop_on_http_429: true
    stop_on_challenge: true
    stop_on_captcha: true

  bookwalker:
    page_turn_delay_ms: 1000
    inter_candidate_delay_ms: 3000
    stop_on_http_403: true
    stop_on_http_429: true
    stop_on_challenge: true
    stop_on_captcha: true
```

The file must remain simple configuration rather than becoming a selector/host/rule DSL.

Do not put site DOM selectors, detailed hostname lists, CAPTCHA URL patterns, resource labels, or resource-priority rules into YAML merely to avoid site code. Those behaviors belong to the site integration.

### 4.2 Shared settings

The following settings are generic and per-site:

```text
page_turn_delay_ms
inter_candidate_delay_ms
stop_on_http_403
stop_on_http_429
stop_on_challenge
stop_on_captcha
```

Site-specific settings may coexist in the same site section. For example, Magapoke additionally uses:

```text
work_ticket_cooldown_hours
```

The configuration loader/runtime orchestration resolves the current site's settings. Core must not parse `crawler.yaml` directly and must not branch on site names.

### 4.3 Defaults and validation

Safe initial pacing defaults:

- `page_turn_delay_ms = 1000`
- `inter_candidate_delay_ms = 3000`

Missing `crawler.yaml`, or a missing known site entry, must not silently turn the crawler into zero-delay operation.

Delay values must be non-negative integers. Explicit zero may be supported as an operator override.

Access-stop flags are booleans. Their code defaults should fail safe for supported sites once the shared AccessGuard is wired.

No random jitter or human-like timing is required.

## 5. Page-turn pacing

### 5.1 Ownership

`page_turn_delay_ms` is a Core run input. It applies to successful CONTENT capture followed by an intentional initial advance, including manual crawl and Batch crawl.

The exact sequence is:

```text
capture current CONTENT
  -> save all new artifacts for that logical page/spread
  -> persist manifest/progress
  -> page_turn_delay_ms
  -> initial adapter.go_next()
  -> adapter.wait_for_change()
       -> adapter-owned bounded retry if required
```

The delay runs once per logical CONTENT advance, not once per saved artifact.

### 5.2 Timeout boundary

The pacing delay is outside page-change timeout/retry budgets.

Do not:

- put the delay inside the timed adapter call for `go_next()`,
- start `wait_for_change()` before the delay,
- subtract the delay from `page_change_timeout_ms`,
- treat the delay as `adapter_timeout_grace_ms`,
- reapply the delay for adapter-owned advance retries.

The intent is:

```text
save complete
  -> pacing delay
  -> initial advance begins
  -> normal page-change observation/retry budget begins
```

### 5.3 States that do not receive the delay

Do not apply `page_turn_delay_ms` to:

- AD advancement,
- adapter-internal advance retries,
- loading polling,
- same-content waits when no new content was saved,
- initialization/entry clicks,
- resource/ticket confirmation clicks,
- local Catalog skips.

The delay does not replace readiness or change detection.

## 6. Inter-candidate pacing

`inter_candidate_delay_ms` is Batch-orchestration pacing.

It:

- applies once between site-accessing Batch candidates,
- applies to normal Batch and grant-only execution,
- runs after the current page/candidate is safely finished or closed and before the next network candidate begins,
- does not run solely because of a local-only skip,
- is not multiplied by candidate-internal retries.

## 7. Shared AccessGuard

### 7.1 Purpose

Add a shared fail-safe mechanism that can observe browser/network state and stop a run when the configured site explicitly rejects or challenges automated access.

The mechanism should be reusable across Magapoke, Manga ONE, and BookWalker. Site-specific evidence and classification remain owned by each site integration.

### 7.2 Stop reasons

Keep these reasons distinct:

```text
http_403
http_429
challenge_detected
captcha_detected
```

They must not be collapsed into ordinary capture failures.

### 7.3 HTTP rejection

When enabled for a site:

- relevant-host HTTP 403 -> stop the Batch run safely,
- relevant-host HTTP 429 -> stop the Batch run safely,
- do not repeatedly retry these responses as ordinary capture failures,
- record `Retry-After` when available,
- preserve confirmed Catalog updates from earlier candidates and confirmed resource use for the current candidate.

Do not stop because unrelated analytics, ad, telemetry, or other third-party requests receive 403/429.

Relevant-host classification is site-specific code or typed site integration metadata, not a Core site-name branch.

### 7.4 Explicit challenge detection

When enabled, stop on explicit challenge evidence, for example:

- a relevant response explicitly marked as a challenge such as `cf-mitigated: challenge`,
- a separately live-verified, site-specific challenge/interstitial state.

Prefer explicit response markers and live-verified site states over broad title/body guessing.

Do not automatically reload, solve, or continue through the challenge.

### 7.5 CAPTCHA detection

When enabled, a user-facing CAPTCHA stops the run with `captcha_detected`.

Generic detection may recognize visible, actionable challenge UI from established providers such as:

- reCAPTCHA,
- hCaptcha,
- Cloudflare Turnstile.

Detection must be conservative. The mere presence of a provider script, hidden DOM node, background integration, or non-visible iframe is not sufficient by itself.

Site adapters/integrations may add separately live-verified site-specific CAPTCHA states.

On CAPTCHA detection:

- stop the current candidate,
- stop remaining Batch access for that site/run,
- do not auto-retry,
- do not auto-reload to evade it,
- do not solve or bypass it,
- emit diagnostics and metrics.

### 7.6 Non-goals

Do not implement:

- CAPTCHA/WAF solving or bypass,
- proxy/IP rotation,
- User-Agent rotation,
- Canvas/WebGL/TLS/fingerprint spoofing,
- synthetic mouse/scroll/keyboard activity intended to imitate a person,
- random timing intended to imitate a person,
- browser/profile/session cycling intended to reset challenge state.

## 8. Shared Batch metrics

### 8.1 Storage

Operational access metrics are not Catalog domain state.

Persist append-friendly JSONL under the ignored runtime tree, for example:

```text
output/metrics/<timestamp>-<site>-<mode>-<run-id>.jsonl
```

Write incrementally and flush records so abnormal process termination can leave useful partial history.

Print a concise end-of-run summary and metrics path on normal and abnormal completion.

### 8.2 Batch fields

At minimum:

```text
site
mode
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
captcha_count
retry_count
```

For resource/grant-only runs, make successful grants observable by resource where practical.

### 8.3 Candidate fields

At minimum:

```text
item/source identity
start time
elapsed
request count
retry count
result / stop reason
resource consumed, if any
```

Where cheap and already available, also record:

- captured page count,
- request count by relevant host,
- response-byte total from metadata such as `Content-Length`,
- `Retry-After`,
- challenge/CAPTCHA classification.

Do not read/fetch response bodies solely for metrics.

### 8.4 No guessed session threshold

Do not add arbitrary fixed limits such as 100 pages or 200 requests, and do not restart browsers periodically based only on an unverified bot-detection theory.

Existing operator `--limit` remains available for intentionally bounded runs. Collect real metrics before adding a separate session-size policy.

## 9. Access Resource Selection contract

### 9.1 Terminology

Use **access resource** as the generic concept.

Examples may include:

- Magapoke `work_ticket`,
- Magapoke `premium_ticket`,
- Manga ONE `free_life`,
- future site-specific tickets, passes, quota units, or equivalent entry resources.

Batch/Core must not assume that access resources are literally tickets.

### 9.2 Existing extension points

The existing generic `quota_resource` contract remains the starting point:

- `SitePolicy.evaluate_for_quota_resource(...)` decides whether a source may be attempted for a requested resource,
- `SiteAdapter.configure_quota_resource(...)` validates/configures that resource before navigation,
- `AccessConsumption` reports observed resource use.

Evolve these extension points rather than creating a parallel Magapoke-only path.

### 9.3 Policy versus live UI

The shared rule is:

```text
Policy / planner
    decides which resource may be attempted

Adapter / live site state
    decides whether that requested resource is actually available and safely selectable
```

Live UI/state is authoritative for actual consumption.

A local policy decision that a resource may be tried never proves that the resource is currently available.

### 9.4 Explicit resource passes

Resource switching must be orchestrator-controlled.

If a candidate is being attempted for resource A and the live UI only offers resource B:

- do not silently click B,
- return a resource-unavailable result for A,
- leave fallback/switching to an explicit subsequent resource pass.

A timeout, ambiguous UI, classification failure, HTTP rejection, challenge, or CAPTCHA must not trigger consumption of another resource as fallback.

### 9.5 Supported resources and ordering

SitePolicy should expose the resources it supports and their normal pass ordering through a generic contract.

The exact method names are implementation details, but the behavior must support concepts equivalent to:

```text
supported_resources(site)
ordered_resource_passes(site)
```

Do not hard-code Magapoke resource names in generic Batch orchestration.

Resource ordering is meaningful. A site may define, for example:

```text
resource_a
resource_b
resource_c
```

A future site can therefore reuse the orchestration without changing Batch semantics.

### 9.6 `all`

Generic `all` means:

> execute the site's configured/supported resource passes in policy-defined order, replanning against current Catalog state between passes where necessary.

`all` does not mean "click whichever resource appears first" inside a candidate.

## 10. Grant-only contract

### 10.1 Meaning

Grant-only performs access acquisition without content capture/package completion.

Generic flow:

```text
select candidate for one explicit access resource
  -> open target
  -> use only that configured resource if normal live UI permits it
  -> confirm usable viewer/content access
  -> confirm and report observed resource consumption when applicable
  -> persist grant/resource state
  -> close page
  -> inter-candidate delay
  -> next candidate
```

Grant-only must not:

- capture content pages,
- package ZIP/CBZ output,
- create a successful content artifact merely because access was granted,
- mark the Item completed.

The Item remains pending for a later normal Batch run.

### 10.2 CLI direction

The generic orchestration should support the shape:

```text
batch run --site <site> --grant-only <resource>
batch run --site <site> --grant-only all
```

CLI parsing must not hard-code Magapoke resource names as the only possible values. Validate resource support against the selected site's policy/integration.

### 10.3 Shared entry path

Normal crawl and grant-only should reuse the same pre-capture entry semantics where practical:

```text
prepare_page
configure_run
configure requested resource
goto
initialize / access entry / viewer readiness
```

Avoid duplicating ticket/resource click and initialization logic into a second independent implementation.

The exact refactoring may use a shared entry helper/result, but it must preserve existing initialization timeout and live-verified adapter behavior.

## 11. Implementation phases

Implement in small reviewable phases.

### Phase 0 - documentation and authority cleanup

- establish this document as the shared authority for pacing, AccessGuard, metrics, generic resource selection, and grant-only semantics,
- keep site-specific rules in site-specific specifications,
- update note/authority references so planned behavior is not described as already implemented.

### Phase 1 - runtime settings, pacing, and site ordering changes

- add `crawler.yaml` loader and typed resolved settings,
- add safe per-site defaults,
- add `page_turn_delay_ms` to resolved Core run settings / `RunConfig`,
- add `inter_candidate_delay_ms` to Batch orchestration settings,
- implement exact CONTENT pacing placement,
- preserve adapter retry algorithms and timeout budgets,
- apply inter-candidate pacing only between site-accessing candidates,
- implement site-specific ordering changes explicitly adopted by the site spec (Magapoke and Jump+ old-to-new within Work),
- preserve existing Discovery traversal semantics.

### Phase 2 - shared AccessGuard and metrics

- add reusable HTTP/access observation,
- add per-site relevant-host integration,
- add configured 403/429 stops,
- add explicit challenge stop,
- add conservative visible CAPTCHA stop,
- add distinct stop reasons,
- add incremental JSONL metrics,
- emit normal/abnormal summaries,
- wire the shared mechanism to Magapoke, Manga ONE, and BookWalker without changing unrelated capture/navigation semantics.

### Phase 3 - generic access-resource selection contract

- expose supported resources and pass order through site policy/integration,
- keep Batch free of Magapoke resource-name branches,
- preserve existing `quota_resource` and `AccessConsumption` semantics while evolving them as needed,
- implement generic resource-unavailable/pass behavior,
- implement policy-defined `all` orchestration with replanning between passes.

### Phase 4 - generic grant-only + first Magapoke Work Ticket integration

Status: **IMPLEMENTED** for generic grant-only Work Ticket. Premium Ticket and
`all` are implemented in the Phase 5 section below.

- add generic `--grant-only <resource>` CLI validation/orchestration for the
  first Work Ticket grant-only pass,
- share normal entry semantics rather than duplicating adapter logic,
- implement Magapoke Work Ticket work-scoped resource state and cooldown per its site spec,
- persist confirmed grants/resource state without capture/package/completion.

### Phase 5 - Magapoke Premium/all integration

Status: **IMPLEMENTED**.

- wire Magapoke Premium Ticket into the generic resource-pass contract,
- preserve live Premium balance behavior,
- preserve Work Ticket priority and fail-closed semantics,
- implement Magapoke `all` using policy-defined resource passes rather than Batch hard-coding.

`--grant-only premium_ticket` uses the normal `entry_only` adapter path. A
confirmed Premium Ticket consumption persists only the source grant using the
policy's conservative 71-hour grant; Premium balance and state are never
stored in Catalog. `--grant-only all` executes the Policy-ordered passes,
replans Catalog between passes, shares the total site-attempt `--limit`, and
keeps local skips out of that limit. A resource-pass exhaustion stops only the
current pass, while AccessGuard fatal stops end the whole run. Grant-only
passes never capture, package, create artifacts, or complete Items.

### Phase 6 - regression and live verification

Status: **AUTOMATED VERIFIED / LIVE PARTIAL**. The regression inventory and
live-verification results are recorded in `docs/PHASE6_VERIFICATION.md`.

Verify at minimum:

- normal Batch for Magapoke, Manga ONE, BookWalker,
- manual crawl pacing,
- existing direct/quota access,
- adapter-owned retry timing,
- timeout behavior with pacing excluded,
- relevant-host 403/429 stops,
- unrelated third-party 403/429 does not stop,
- explicit challenge stop,
- visible CAPTCHA stop,
- abnormal metrics persistence,
- grant-only no-capture/no-package/no-completion semantics,
- resource-pass ordering and resource-unavailable behavior,
- Magapoke Work/Premium consumption/grant persistence.

## 12. Acceptance criteria

The shared implementation is complete when:

- Batch remains sequential,
- runtime configuration remains simple and site-scoped,
- missing pacing configuration retains safe non-zero defaults,
- CONTENT pacing occurs exactly once after successful save/progress persistence and before the initial `go_next`,
- pacing does not run for AD advancement or adapter retries,
- pacing does not consume page-change timeout budgets,
- candidate pacing occurs once between site-accessing candidates and not for local-only skips,
- 403/429/challenge/CAPTCHA policies are configurable per site,
- relevant-host classification remains site-specific,
- visible CAPTCHA stops with a distinct reason and is not solved/retried automatically,
- shared access metrics survive normal and abnormal completion,
- metrics do not create extra body/network reads solely for accounting,
- generic Batch does not hard-code Magapoke resource names,
- resource priority/order is provided by site policy/integration,
- one resource pass never silently consumes another resource,
- live site state is authoritative for actual resource use,
- `all` follows site-defined resource-pass order with replanning as needed,
- grant-only never captures/packages/completes an Item,
- existing site-specific capture/navigation/retry semantics remain intact except for the intentional pacing and explicit fail-safe behavior.

## 13. Explicit non-goals

Not part of this work:

- parallel crawling,
- proxy/IP rotation,
- User-Agent/fingerprint spoofing,
- CAPTCHA/WAF/challenge bypass or solving,
- synthetic human-like interaction,
- random human-like timing,
- browser/profile cycling to evade challenge state,
- Prometheus or other persistent monitoring infrastructure,
- a metrics database/Catalog metrics schema,
- arbitrary per-session page/request caps without evidence,
- a generic YAML rule engine for selectors/hosts/resource semantics,
- prematurely modeling every future site's quota/resource persistence shape before a concrete need exists.

## 14. Candidate failure and operator interruption

Site-operation failures isolated to one candidate are recorded as failed and
stop the surrounding sequential Batch after the current candidate is cleaned
up. The original exception type and message remain visible in candidate
metrics and CrawlRun records. Expected resource-unavailable and local cooldown
outcomes remain skips and may continue within the explicit resource pass.
AccessGuard stops, stale-plan/configuration errors, and Catalog persistence
errors remain fatal to the Batch.

Operator interruption is recorded with `stop_reason=interrupted` and a
dedicated interruption error type. No later candidate is started. Confirmed
resource consumption is persisted before the interrupted candidate is
finalized; unconfirmed consumption is never inferred from interruption.
Cleanup is bounded and best-effort so it cannot replace the original failure
or interruption reason.

AccessGuard, page, and BrowserSession shutdown each use a bounded wait. A
timeout cancels the pending cleanup task without an unbounded follow-up wait;
an already active candidate error remains the primary result.

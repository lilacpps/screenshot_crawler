# Shared Access Control / Pacing Plan (planned, not yet implemented)

Status: **PLANNED / NOT YET IMPLEMENTED**.

Authority: `docs/ACCESS_CONTROL_AND_PACING.md`.

This note records the adopted shared plan without describing the behavior as already implemented. Current implementation snapshots remain in each site's existing note until the relevant phase lands; implementation changes must update the applicable current-state note in the same change.

Planned shared changes:

- keep Batch sequential,
- add root `crawler.yaml` for runtime behavior,
- resolve per-site settings without making Core parse YAML or branch on site names,
- add shared `page_turn_delay_ms` and `inter_candidate_delay_ms`,
- apply CONTENT pacing exactly once after successful save/progress persistence and before the initial `adapter.go_next()`,
- keep pacing outside `page_change_timeout_ms`, `adapter_timeout_grace_ms`, and adapter-owned retry budgets,
- do not pace AD advancement, loading polling, same-content waits, ticket/resource confirmation clicks, or adapter retries,
- add per-site `stop_on_http_403`, `stop_on_http_429`, `stop_on_challenge`, and `stop_on_captcha`,
- add a reusable AccessGuard with distinct `http_403`, `http_429`, `challenge_detected`, and `captcha_detected` reasons,
- stop only on relevant-host 403/429 rather than unrelated third-party traffic,
- detect CAPTCHA conservatively from visible user-facing challenge UI; script presence alone is insufficient,
- do not auto-retry/reload/solve/bypass CAPTCHA or challenge states,
- add incremental JSONL Batch metrics under `output/metrics/`, including CAPTCHA counts and abnormal-stop persistence,
- keep relevant-host and site-specific challenge/CAPTCHA classification in each site integration,
- define a generic **access resource** selection contract using the existing `quota_resource`, `SitePolicy.evaluate_for_quota_resource()`, `SiteAdapter.configure_quota_resource()`, and `AccessConsumption` extension points,
- let site policy/integration expose supported resources and pass order,
- keep generic Batch free of Magapoke resource-name branches,
- make resource switching explicit through resource passes; one resource attempt must never silently consume another resource,
- make live site state authoritative for actual resource consumption,
- define generic `--grant-only <resource>|all` orchestration,
- define `all` as site-policy-ordered resource passes with replanning between passes,
- reuse normal entry semantics for grant-only rather than duplicating ticket/resource click and initialization logic,
- do not capture/package/complete an Item in grant-only mode.

The planned repository-wide implementation remains intentionally phased:

1. runtime settings/pacing + site-specific ordering changes,
2. shared AccessGuard + CAPTCHA/challenge/403/429 + JSONL metrics,
3. generic access-resource selection contract,
4. generic grant-only + first Magapoke Work Ticket integration,
5. Magapoke Premium/all integration,
6. cross-site regression and live verification.

The shared contract is intentionally future-facing: Magapoke Work/Premium Ticket is the first implementation, but Manga ONE, BookWalker, and future site adapters may add their own access resources later without changing generic Batch semantics.

See the authority document for detailed semantics, acceptance criteria, and non-goals.

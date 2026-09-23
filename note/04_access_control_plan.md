# Shared Access Control / Pacing Plan

Status: **Phase 1 IMPLEMENTED**. Phase 2 and later remain **PLANNED / NOT YET IMPLEMENTED**.

Authority: `docs/ACCESS_CONTROL_AND_PACING.md`.

This note records the adopted shared plan without describing the behavior as already implemented. Current implementation snapshots remain in each site's existing note until the relevant phase lands; implementation changes must update the applicable current-state note in the same change.

Phase 1 current state: root `crawler.yaml` is parsed outside Core into typed per-site settings with safe
non-zero defaults and explicit zero overrides. CONTENT pacing occurs once after all logical-page artifacts
and manifest/progress persistence, before the initial `go_next()`, outside adapter timeout/retry budgets.
Batch pacing occurs once after a site-accessing candidate's Page is closed and only before another such
candidate. Magapoke Discovery remains latest-first; Batch is old-to-new within each Work by
`published_at ASC (NULL last), source_id ASC` while existing direct/quota phases and Work ordering remain.

The remaining AccessGuard, 403/429 stop, challenge/CAPTCHA detection, JSONL metrics, resource-selection
expansion, grant-only, and Work Ticket cooldown persistence are still planned and not implemented.

Remaining planned shared changes:

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

1. shared AccessGuard + CAPTCHA/challenge/403/429 + JSONL metrics,
2. generic access-resource selection contract,
3. generic grant-only + first Magapoke Work Ticket integration,
4. Magapoke Premium/all integration,
5. cross-site regression and live verification.

The shared contract is intentionally future-facing: Magapoke Work/Premium Ticket is the first implementation, but Manga ONE, BookWalker, and future site adapters may add their own access resources later without changing generic Batch semantics.

See the authority document for detailed semantics, acceptance criteria, and non-goals.

# Shared Access Control / Pacing Plan

Status: **Phase 1 IMPLEMENTED; Phase 2 IMPLEMENTED; Phase 3 IMPLEMENTED; Phase 4 IMPLEMENTED**.
Phase 5 and Phase 6 remain **PLANNED / NOT YET IMPLEMENTED**.

Authority: `docs/ACCESS_CONTROL_AND_PACING.md`.

This note records the adopted shared plan and the current Phase 1/2/3/4 implementation state. Current implementation snapshots remain in each site's note and are synchronized when shared behavior affects that site.

Phase 1 current state: root `crawler.yaml` is parsed outside Core into typed per-site settings with safe
non-zero defaults and explicit zero overrides. CONTENT pacing occurs once after all logical-page artifacts
and manifest/progress persistence, before the initial `go_next()`, outside adapter timeout/retry budgets.
Batch pacing occurs once after a site-accessing candidate's Page is closed and only before another such
candidate. Magapoke Discovery remains latest-first; Batch is old-to-new within each Work by
`published_at ASC (NULL last), source_id ASC` while existing direct/quota phases and Work ordering remain.

Phase 2 current state: the shared `AccessGuard` observes body-free response metadata and
candidate-scoped visible CAPTCHA/challenge signals for Magapoke, Manga ONE, and BookWalker.
Relevant first-party 403/429 responses stop the current crawl and Batch, while unrelated
third-party responses do not. Explicit `cf-mitigated: challenge` and visible reCAPTCHA,
hCaptcha, and Turnstile UI use distinct fatal reasons. Batch metrics append and flush JSONL
records under `output/metrics/`; diagnostics include the access stop details. No response body
is read for metrics. No site-specific challenge/CAPTCHA hook has been live-verified yet.

Phase 3 current state: Site Policies expose supported resources and policy-defined ordering.
The generic Planner validates explicit `quota_resource` values, passes the requested resource
through Policy and Adapter, and never silently falls back to another resource. Batch executes
the normal/default pass, replans Catalog state between policy-ordered additional resource passes,
and keeps `AccessConsumption` matching against the requested resource. Magapoke exposes
`work_ticket` then `premium_ticket`; Manga ONE and BookWalker expose no additional named resource.

Phase 4 current state: generic `batch run --site magapoke --grant-only work_ticket`
is policy-validated and reuses the normal adapter entry path with `entry_only` Core
execution. A confirmed Work Ticket updates the source grant and the Work-scoped
`quota_resource_states` row atomically, while the Item remains pending and no
artifact/package is created. A local `work_ticket_cooldown` skip is evaluated before
opening a Page; the default cooldown is 23 hours and exactly-expired state is live-checked.
Metrics use the existing incremental `output/metrics/*.jsonl` writer with mode
`grant-only`. `premium_ticket` grant-only and `--grant-only all` remain unimplemented.
Normal Batch and grant-only now use one observed-consumption persistence path, so a
confirmed Work Ticket updates both source grant and Work state even when a later
crawl/finalization step fails.

Remaining planned shared changes:

- define `all` as site-policy-ordered resource passes with replanning between passes,
- extend grant-only to later resources without changing generic Batch semantics,
- retain no-capture/no-package/no-completion semantics for grant-only.

The planned repository-wide implementation remains intentionally phased:

- Phase 1 — Runtime settings, pacing, and site ordering: **IMPLEMENTED**
- Phase 2 — Shared AccessGuard + CAPTCHA/challenge/403/429 + JSONL metrics: **IMPLEMENTED**
- Phase 3 — Generic access-resource selection contract: **IMPLEMENTED**
- Phase 4 - Generic grant-only + first Magapoke Work Ticket integration: **IMPLEMENTED**
- Phase 5 — Magapoke Premium/all integration: **PLANNED / NOT YET IMPLEMENTED**
- Phase 6 — Cross-site regression and live verification: **PLANNED / NOT YET IMPLEMENTED**

The shared contract is intentionally future-facing: Magapoke Work/Premium Ticket is the first implementation, but Manga ONE, BookWalker, and future site adapters may add their own access resources later without changing generic Batch semantics.

See the authority document for detailed semantics, acceptance criteria, and non-goals.

# Shared Access Control / Pacing Plan

Status: **Phase 1 IMPLEMENTED; Phase 2 IMPLEMENTED; Phase 3 IMPLEMENTED; Phase 4 IMPLEMENTED; Phase 5 IMPLEMENTED**.
Phase 6 status: **AUTOMATED VERIFIED / LIVE PARTIAL**.

Phase 6 verification evidence is maintained in `docs/PHASE6_VERIFICATION.md`.

Authority: `docs/ACCESS_CONTROL_AND_PACING.md`.

This note records the adopted shared plan and the current Phase 1–6 implementation/verification state. Current implementation snapshots remain in each site's note and are synchronized when shared behavior affects that site.

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
`grant-only`; Phase 5 adds Premium Ticket and `--grant-only all` on the same path.
Normal Batch and grant-only now use one observed-consumption persistence path, so a
confirmed Work Ticket updates both source grant and Work state even when a later
crawl/finalization step fails.

Phase 5 current state: Magapoke also supports
`batch run --site magapoke --grant-only premium_ticket` and generic
`--grant-only all`. The ordered resources come from Site Policy
(`work_ticket`, then `premium_ticket`); `all` replans Catalog between passes and
shares one total site-attempt limit. Premium balance is read live, never stored
in Catalog, and a clear zero stops only the Premium pass. Work Ticket priority
and fail-closed ambiguous UI behavior remain enforced by the Adapter. Confirmed
Premium consumption persists only the source grant via the Policy's conservative
71-hour grant. Both grant-only resources leave Items pending and create no
capture/package/Artifact; AccessGuard fatal stops still terminate the whole run.

Remaining planned shared changes:

- retain no-capture/no-package/no-completion semantics for future grant-only resources.

The planned repository-wide implementation remains intentionally phased:

- Phase 1 — Runtime settings, pacing, and site ordering: **IMPLEMENTED**
- Phase 2 — Shared AccessGuard + CAPTCHA/challenge/403/429 + JSONL metrics: **IMPLEMENTED**
- Phase 3 — Generic access-resource selection contract: **IMPLEMENTED**
- Phase 4 - Generic grant-only + first Magapoke Work Ticket integration: **IMPLEMENTED**
- Phase 5 — Magapoke Premium/all integration: **IMPLEMENTED**
- Phase 6 — Cross-site regression and live verification: **AUTOMATED VERIFIED / LIVE PARTIAL**

Phase 6 automated regression is green for Magapoke, Manga ONE, and BookWalker,
including pacing, AccessGuard, metrics, resource orchestration, grant-only
semantics, persistence, and Catalog migration. Read-only plans succeeded on a
temporary migrated Catalog copy. Normal live Batch and actual Ticket
consumption remain intentionally unrun; see the verification document.

The shared contract is intentionally future-facing: Magapoke Work/Premium Ticket is the first implementation, but Manga ONE, BookWalker, and future site adapters may add their own access resources later without changing generic Batch semantics.

See the authority document for detailed semantics, acceptance criteria, and non-goals.

# 04 — Direct-only Policy / Batch

Status: PASS, BLOCKING 0 (130 passed, 0 skipped). Local policy verification and the Phase 05 live E2E: [PROGRESS](../PROGRESS.md).
Implementer writes; Reviewer performs independent access-safety review.

## Goal
Reuse site-neutral Catalog/Planner/Executor for unconditional ¥0 only.
Add src/screenshot_crawler/site_policies/piccoma.py and minimum necessary
CLI registrations. No quota consumption, grant-only, resolver, cooldown,
Catalog migration, or new generic Executor branch.

## Policy
When source.available is true and source.access_mode is free:
eligible=true, access_strategy=direct, reason=free.
All other modes (quota, paid, owned, grant, rental, unknown, unavailable)
are ineligible. Model the policy on the simple Jump+ direct path but **do not
inherit its active rental exception**.
Batch must invoke target-local, fresh, positive free and ID validation.
If a title or episode became non-free after Discovery: skip/fail closed and
request refresh; never click for entitlement or silently choose another mode.
Use native full-work position/metadata from Catalog rather than range-local
indexes.

## Tests
Policy decision matrix; stale free after planning; canonical URL mismatch;
cross-product episode collision; redirect; no paid/quota resource operations;
Planner eligibility; Executor success/failure completion; manifest/ZIP
naming and Catalog status; CLI site registration. Use isolated test Catalog.
Run affected Batch/Policy/CLI tests and browser integration; widen for shared
changes.

## Acceptance
batch plan reports only public free as eligible; batch run can produce
normal ZIP/manifest and set completed only on success; zero entitlement
actions, zero unknown/paid fallback; Reviewer zero BLOCKING. Record evidence
and remaining limitations in PROGRESS.md and note/09_piccoma.md.

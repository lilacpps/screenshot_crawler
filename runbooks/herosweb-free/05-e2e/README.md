# Phase 05 — Independent end-to-end verification

**Status: NOT STARTED.** Use only supported public/current free examples; no entitlement or payment actions.

## Objective

On the final reviewed code, verify the actual standard CLI/GUI route from an isolated Watchlist through full/incremental Discovery, Catalog, Batch Plan, sequential Batch Run, full free Viewer capture, END, Manifest, ZIP and final Catalog status. Synthetic tests are necessary but not substitutes for live evidence.

## Test plan

1. Freeze code revision/branch. Select **two different works if available**, each with one or more directly free episodes; include a short and a different/longer layout, a leading blank or spread variant when observed. Record any missing second example as a limitation, never invent.
2. Use explicit isolated paths under ignored `output/herosweb_experiment/`. Register canonical `/series/` work URLs. Execute standard full Discovery and audit declared total, unique work-scoped IDs, positions, labels and exclusions; run incremental and verify no identity churn or duplicate writes.
3. Capture direct-only eligible `free` candidates; inspect planned/executed/skipped counts. Confirm no ticket/currency/entitlement CTA, checkout request or rights mutation. Check that nonfree/unknown remain in Catalog but are not entered by Batch.
4. Independently audit each completed ZIP: member names, CRC, decoded dimensions/format and actual image byte SHA-256; page/spread counts and ordering; first/middle/last samples; END and final-Catalog/Artifact status. For native WebP, verify decoded RGBA equals the specific draw-time proven native source; for unchanged original, assert byte equality with proven response; for PNG fallback, assert stable rendered-content pixel proof. Do not claim original byte fidelity merely from visual similarity.
5. Intentionally test a recoverable one-episode failure, resume/idempotency and a rejected gate (synthetic or safely read-only) to confirm no partial completion/phantom ZIP. Verify records and normal output untouched.
6. Run relevant targeted unit/integration tests plus Hanayume and Younganimal regression sets, static lint and `git diff --check`. Track skips, non-run categories, and whether all tests used the frozen final code.

## Required independent sign-off

Reviewer/Tester provide PASS or precise BLOCKING issue(s) on:
- identity, exact Work scope, complete inventory and free-only access;
- correct order and body-only capture, truthful native/original/PNG provenance;
- reliable END, manifest/ZIP integrity, Catalog completed status only after archive success;
- no unsafe regression, no 403/429/challenge bypass, no shared profile/user data modification.

Report exact count of free/quota/paid/unknown sources, run results per Work, original/native/canvas/screenshot page totals, failed/fallback reasons and remaining unverified layouts. Document data-only status carefully: a successful PNG-only Batch is valid free-only E2E, **not** proof that original recovery is impossible or complete.

Close runbook only when requested free-only E2E genuinely passes and independent review has no BLOCKING issues. Ticket work remains expressly deferred regardless of completion.

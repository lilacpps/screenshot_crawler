# Phase 05 — Independent end-to-end verification

**Status: PASS / BLOCKING 0.** Tester E2E, independent artifact/Catalog audit and final Reviewer/Lead gate passed. Use only supported public/current free examples; no entitlement or payment actions. The two earlier HTTP 429 attempts remain failed historical Runs.

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

## Current checkpoint — 2026-11-22

### Final Tester evidence — 2026-11-23

- After the user reported normal display, the Tester confirmed the current freeze and ran one new isolated standard CLI Batch attempt for A, followed by B's first attempt. Both processes exited 0: A captured 10 PNG pages and B captured 38. The combined audit is `output/herosweb_experiment/phase05-independent/proofs/20261123/phase05-final-independent-audit.json`.
- The audit confirms 108 sources (84 free / 20 quota / 4 paid), unchanged resource fields and stable identities/positions; Items 21 and 103 are completed, new Runs 3 and 4 succeeded at END, and two present ZIP Artifacts match the audited SHA-256 and byte sizes. Replanning returns zero eligible candidates. The two earlier 429 Runs 1 and 2 remain preserved.
- Before/after freeze manifests match for 230 Python files plus runtime config; imported module paths resolve to this worktree. The shared Phase 05 browser lease is released. Final independent Reviewer/Lead sign-off passed with BLOCKING 0.
- Native/original implementation remains a separately authorized post-Phase05 follow-up and has not started. One bounded A diagnostic has completed; source evidence review is pending. See the Phase 06 checkpoint in PROGRESS before any further live probe.

### Historical access-stop checkpoint (superseded by the successful 2026-11-23 runs above)

- The isolated setup's Watchlist add and unscoped Full/Incremental Discovery completed successfully. The 108-source audit remains stable at 84 free / 20 quota / 4 paid; the unscoped Batch plan is 84 direct / 0 quota / 24 skipped. Proofs are under `output/herosweb_experiment/phase05-independent/proofs/`.
- The first selected Work A Batch job's initial main-document request received HTTP 429 with `Retry-After: 1` at 23:10:17 JST. It stopped with exit 2 before capture; no PNG/ZIP/Artifact was made, and Work B was not started. The post-stop Catalog audit found access modes, availability, quota and grant state unchanged.
- Independent Reviewer approved one fresh same-A guarded attempt only after at least five minutes without HERO traffic, with the same profile/endpoint/headers/transport/config and the first failed Run preserved. That one recovery also returned HTTP 429 and exited 2 before capture. Evidence is in `output/herosweb_experiment/phase05-independent/proofs/recovery-20261122T2316JST/`; the Reviewer independently matched the exact 253-entry pre/post-freeze comparison in this proof set. The two Runs are failed IDs 1 and 2, with zero Phase05 Artifacts. Structured Catalog reports retain the expected 84 free / 20 quota / 4 paid counts and unchanged source availability/grants/quota state. No B or subsequent HERO request followed the second response.
- At that historical checkpoint, automatic requests were stopped pending external site availability. The user later reported normal display and separately authorized one bounded new A attempt followed by B; the successful results and final audit are recorded above.
- The Phase04 raw file hashes are the reviewed baseline. Although the earlier Phase05 freeze helper omitted the `src/` prefix, the corrected Reviewer comparison matched all 253 entries; executable files and config stayed frozen. Only documentation was updated after freeze.
- The user-requested original/source-native fidelity investigation remains planned for after a successfully closed Phase05; it is not implemented or started by this blocked E2E attempt.

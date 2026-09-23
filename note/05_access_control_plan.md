# Shared Access Control Implementation Plan (planned, not yet implemented)

Status: **PLANNED / NOT YET IMPLEMENTED**.

Authority:

- shared specification: `docs/ACCESS_CONTROL_AND_PACING.md`,
- phased implementation plan: `docs/ACCESS_CONTROL_AND_PACING_PLAN.md`.

This note mirrors the adopted phased implementation plan without describing planned behavior as already implemented.

Phases:

1. runtime settings/pacing + site ordering changes,
2. shared AccessGuard + metrics,
3. generic access-resource selection contract,
4. generic grant-only + Magapoke Work Ticket,
5. Magapoke Premium/all,
6. cross-site regression and live verification.

Key implementation boundaries:

- Core owns generic CONTENT pacing only; it does not parse YAML or branch on site names,
- Batch owns candidate pacing and generic resource/grant-only orchestration,
- SitePolicy/integration owns supported resource names and pass order,
- SiteAdapter/live site state owns actual resource availability and consumption confirmation,
- AccessGuard owns shared stop propagation while site integrations provide relevant hosts and verified site-specific challenge/CAPTCHA evidence,
- resource switching is explicit between passes; one candidate attempt never silently consumes another resource,
- grant-only reuses normal entry semantics and never captures/packages/completes an Item.

See the authority documents for acceptance tests and detailed semantics.

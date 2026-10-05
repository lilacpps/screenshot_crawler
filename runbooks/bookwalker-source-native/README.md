# BookWalker Source-Native Capture Runbooks

This workstream investigates and improves BookWalker capture while preserving the
authoritative source-native representation.

## Role model

Unless a stage explicitly says otherwise:

- Lead / root orchestrator: **GPT-6.1 Sol**, high reasoning
- Worker: **GPT-5.6 Luna**, high reasoning, single production writer
- Reviewer: **GPT-6.1 Sol**, read-only quality gate
- Critic: **GPT-6.1 Sol**, read-only adversarial evidence/design gate

The worker is the only agent allowed to drive the live BookWalker viewer.

## Sequence

### Foundation / baseline workflow

Current location:

`docs/BOOKWALKER_SOURCE_NATIVE_CAPTURE_RUNBOOK.md`

This is the original workstream runbook that established the source-native objective,
model roles, viewer-position protocol, A/B/C/D classification, and baseline research
workflow.

It should eventually move into this workstream directory in a documentation-only change,
but **do not move it during the active provenance-resolution stage**.

### 02 — Provenance resolution and minimal implementation

`02-provenance-resolution/README.md`

Starts from research checkpoint:

`1040abce1e130ce69e7a82812ea924315e06f78c`

Goals:

- run the pending independent Critic gate;
- explain the manga ordinary-body D cases;
- resolve or bound the light-novel opening D cases;
- implement only confirmed B cases;
- leave A/C unchanged and D fail-closed;
- finish with Reviewer + Critic sign-off and bounded cross-content live verification.

## Naming guidance for future stages

Add a new numbered stage only when there is a new execution objective, for example:

- `03-cross-title-generalization/`
- `04-performance-hardening/`
- `05-production-rollout/`

Do not create a new runbook for every tiny code edit or reviewer fix.

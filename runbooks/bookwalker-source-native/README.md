# BookWalker Source-Native Capture Runbooks

This workstream investigates and improves BookWalker capture while preserving the
authoritative source-native representation.

## Default operating model

> **Research is lead-driven. Review is change-driven. Critic is risk-driven.**

Default research:

- Lead: **GPT-6.1 Sol**
- Worker: **GPT-5.6 Luna**

Reviewer and Critic are not routine research participants.

- Reviewer: mandatory for production implementation before merge; optional for research.
- Critic: only for high-risk design decisions such as weakening proof gates, introducing
  heuristics, broad generalization, or large/shared abstraction.

The Worker is the only production writer and the only live BookWalker viewer operator.

## Sequence

### Foundation

Current location:

`docs/BOOKWALKER_SOURCE_NATIVE_CAPTURE_RUNBOOK.md`

This defines the source-native objective, A/B/C/D classification, browser-position
protocol, and the lightweight role policy.

It may later move into this directory in a documentation-only cleanup.

### 02 — Provenance resolution

`02-provenance-resolution/README.md`

Current checkpoint:

`02-provenance-resolution/CHECKPOINT.md`

Current execution status (2026-10-08): **COMPLETE / NO PRODUCTION CHANGE**.
The active research branch contains the fetched current `origin/main` baseline.
Fresh manga `9/159` and LN `2/314` / `3/314` remain D at the safe page-artifact
boundary. Exact upstream JPEGs were established for manga and LN `3/314`, but
complete output/reconstruction proof was not. See the checkpoint for limits.

Goals:

- resolve only the manga/LN provenance questions that can change an operational
  decision;
- avoid finishing diagnostic machinery for its own sake;
- implement only confirmed B cases;
- allow a safe no-change conclusion;
- invoke Reviewer only if production changes are made;
- invoke Critic only when a material design-risk trigger appears.

## Future stages

Add a numbered stage only for a new execution objective, for example:

- `03-cross-title-generalization/`
- `04-performance-hardening/`
- `05-production-rollout/`

Do not create a runbook for every small probe, code edit, or review fix.

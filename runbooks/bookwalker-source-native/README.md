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

Current execution status (2026-10-08): **COMPLETE — LN2 production integration accepted**.
The user authorized automatic capture integration after the successful LN2 PoC.
Automatic LN2 capture now returns a 1443x2048 reconstructed JPEG through a
bounded cropped one-hop provenance contract. Its A snapshot, B snapshot and
final renderer destination region all match at zero differing pixels, with
the optional older-path verification flag off. Regression evidence and document
synchronization are complete; final production Reviewer confirmed PASS with
no remaining BLOCKING.
The research branch includes fetched current `origin/main`. The minimal direct
partial-MCU path is implemented: manga `9/159` and `11/159` each return two
844x1200 reconstructed JPEGs from 848x1200 coded sources; LN `3/314` and `4/314`
return 2048x1453 JPEGs from 2048x1456 coded sources. Full coded MCU coverage,
unique exact candidate, coefficient/quantization/selector equality and mandatory
native pixel equality pass for every new cropped part. The user-requested LN2
follow-up proved B at recovery-PoC level and now has automatic-capture live
acceptance. Its 722x1024 intermediate and selected 721.5x1024 source rectangle
remain distinct. Final replay uses the actual 1904x985 backing canvas and
destination offset; no color tolerance or heuristic attribution is used.
Existing LN text controls 8/10 remain A.
Current cover controls use actual fallback, separately from historical A.
The direct-contract baseline passed 180 targeted tests, 46 browser-backed
Integration tests and its final Reviewer gate. The LN2 extension currently
passes 195 targeted tests, 52 browser-backed Integration tests and Ruff/diff
checks, with zero skipped tests. Its separate production review passed after
the explicit proof gates and legacy regression checks were completed. Manga2
was unnecessary. Unproved covers and uncaptured LN5-7 retain D; no C is inferred.
See the checkpoint for positions, hashes and D limits.

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

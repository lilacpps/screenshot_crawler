# BookWalker Source-Native Capture — Stage 02: Provenance Resolution

## 1. Starting checkpoint

Continue from branch:

`research/bookwalker-source-native-20261005`

Starting research checkpoint:

`1040abce1e130ce69e7a82812ea924315e06f78c`

At this checkpoint:

- production capture code is unchanged;
- only `note/01_bookwalker.md` was updated with bounded observations;
- targeted capture tests: 153 passed;
- BookWalker browser-backed integration tests: 45 passed;
- Ruff passed;
- independent Critic gate is still pending.

Do not treat the checkpoint note as final implementation approval.

## 2. Known evidence

### Manga target

Product:

https://bookwalker.jp/de038ee678-e389-4ceb-a13e-4f7f0154d79e/

Observed:

- actual and restored anchor: `1/159`;
- bounded observation reached `23/159`;
- cover is proven A / original JPEG at 844x1200;
- seven ordinary body spreads, roughly `9/159` through `21/159`, currently return
  native-PNG fallback;
- those ordinary-body cases failed current dimension/mapping proof and do not yet have
  proven upstream exact response attribution;
- therefore ordinary manga body is currently **D**, not C.

The second manga target remains optional:

https://bookwalker.jp/deeb7abe07-9147-4959-b490-75fa6743d8f2/

Do not use it until the first manga's ordinary-body rendering path is understood well
enough that a second title answers a concrete generalization question.

### Light-novel target

Product:

https://bookwalker.jp/dea0961d33-6ef8-4673-a455-0ec0ecd5de47/

Observed:

- actual and restored anchor: `1/314`;
- cover `1/314` is proven A / original JPEG at 1443x2048;
- ordinary text positions including `8/314`, `10/314`, `11/314`, `13/314`,
  and `15/314` use the existing proven reconstructed-JPEG path at 960x1280;
- opening/front-matter `2/314` through `7/314` remain D;
- `2/314`: a 1448x2048 JPEG exactly matches a bitmap, but visible selected native draw
  and retained source-canvas geometry do not yet prove visible-output attribution;
- `3/314`: a 2048x1456 bitmap has one exact JPEG candidate, but crop/padding/coded
  mapping and source-native output proof remain incomplete;
- no confirmed C case exists yet; PNG fallback is safe but is not evidence that the
  network source itself is PNG.

## 3. Objective

Resolve the unresolved D cases far enough to make a justified decision.

For each investigated pattern, end in exactly one of:

- **A — already source-native**
- **B — recoverable source-native**
- **C — source-native PNG / current PNG correct**
- **D — ambiguous/unsupported and intentionally fail-closed**

Implementation is optional.

A successful Stage 02 may conclude with no production code change if no B case can be
proven safely.

## 4. Multi-agent roles

Use the existing BookWalker roles.

### Lead — GPT-6.1 Sol

The Lead owns phase decisions, evidence sufficiency, and browser-lease coordination.

The Lead must:

- start with the pending Critic gate;
- convert Critic challenges into bounded probe questions;
- prevent implementation until a B case has exact enough provenance;
- keep probes narrow and hypothesis-driven;
- decide whether the optional second manga is necessary;
- require Reviewer after every material Worker result;
- require final Critic sign-off.

### Worker — `bookwalker_worker`, GPT-5.6 Luna

The Worker performs:

- bounded live probes;
- diagnostic instrumentation;
- any minimal implementation;
- tests;
- live verification;
- note synchronization.

The Worker is the only production writer and the only live-viewer operator.

### Reviewer — `bookwalker_reviewer`, GPT-6.1 Sol, read-only

Reviewer checks:

- probe evidence quality;
- implementation correctness;
- regressions;
- fail-closed boundaries;
- tests;
- note accuracy.

Any `BLOCKING` finding stops phase advancement.

### Critic — `bookwalker_critic`, GPT-6.1 Sol, read-only

Critic challenges provenance and generalization.

Use Critic:

1. immediately at Stage 02 entry;
2. after a B classification is proposed but before production implementation;
3. at final sign-off.

A material `CHALLENGE` is blocking.

## 5. Browser-position protocol

Persisted reader position remains a first-class hazard.

For every independent live probe:

1. attach/open via the shared Crawler Chrome/CDP path;
2. read the actual visible page counter/state;
3. compare with the intended anchor;
4. explicitly rewind/reposition if different;
5. verify the resulting page counter/state;
6. collect only the bounded evidence window;
7. record observed start and end positions;
8. restore the intended anchor before ending the probe when practical.

Never infer current position from the previous probe.

Do not let Reviewer or Critic operate the live viewer.

## 6. Phase A — Independent Critic gate

Before new implementation, give Critic the Stage 01 evidence and current production
capture logic.

Critic must answer:

1. What is the strongest alternative explanation for manga ordinary-body PNG fallback?
2. What exact missing evidence prevents those manga pages from B or C?
3. For LN `2/314` and `3/314`, what exact provenance step is missing between the
   matched JPEG/bitmap and the visible page?
4. Which currently recorded facts are merely correlated rather than authoritative?
5. What is the smallest probe that could falsify each proposed recovery hypothesis?
6. Is any current note wording stronger than the evidence?
7. Is a second manga title useful now, or only after the first manga renderer path is
   understood?

Lead converts the answer into bounded Worker tasks.

Do not skip directly to implementation.

## 7. Phase B — Manga ordinary-body deep probe

Investigate only enough representative ordinary-body pages to explain the rendering path.

Recommended first sample:

- one early ordinary spread near the start of the observed D range;
- one later ordinary spread from the same stable-looking range.

Do not probe all seven D spreads unless evidence requires it.

For each selected spread, identify:

- selected renderer/native draw;
- selected source constructor and identity;
- source and destination dimensions;
- sourceRect / destination;
- transform matrix;
- alpha/composite/filter;
- canvas identities;
- operation ordering;
- upstream ImageBitmap identities;
- response candidates with MIME, dimensions, and hashes;
- whether any candidate can be matched exactly to the upstream bitmap;
- whether the visible page is a crop, rotation, scale, padded canvas, composed canvas,
  or another bounded pattern;
- whether the same pattern is present on both representative spreads.

The probe must be able to distinguish:

- source JPEG recoverable through a new proven transform;
- source PNG already correct;
- renderer-owned canvas with no recoverable direct source artifact;
- unsupported/ambiguous chain.

### Manga exit rule

After the bounded probe, classify the ordinary-body pattern.

If B is proposed, run Critic before implementation.

If C is proposed, require evidence of authoritative PNG source-native representation;
"current output is PNG" is insufficient.

If D remains, document the exact missing proof and stop broadening the implementation.

## 8. Phase C — Light-novel opening provenance probe

Focus first on `2/314` and `3/314`.

The objective is not to "make them JPEG"; it is to prove or disprove that the exact
matched JPEG source can be mapped to the visible output without unsupported inference.

For each target page, capture enough bounded trace data to answer:

- exact selected renderer draw and source identity;
- exact upstream canvas/bitmap lineage;
- whether width/height swaps imply a real rotation and, if so, the exact transform;
- sourceRect and destinationRect;
- any padding, crop, clear, intermediate canvas, or scaling operation;
- whether all pixels in the candidate participate in the visible page;
- whether any pixels are added/removed/reordered;
- whether reconstruction can preserve source-native dimensions and semantics;
- whether one exact response candidate remains after attribution;
- whether the rule also rejects a near-miss page or geometry.

Do not treat a 90-degree-looking dimension swap as proof of rotation without the traced
operation/transform that establishes it.

### LN exit rule

Each opening pattern must end as A/B/C/D with explicit evidence.

A B classification requires a precise recovery contract that can be expressed without:

- nearest candidate selection;
- dimension-ratio guessing;
- filename/path heuristics;
- request-order/timing heuristics;
- visual-similarity heuristics.

## 9. Phase D — Optional second manga

Use the second manga only if one of these is true:

- a B pattern from manga 1 appears safe but needs cross-title confirmation before
  production generalization;
- manga 1 exposes multiple possible renderer patterns and a second title can distinguish
  which is normal;
- Reviewer/Critic identifies a concrete generalization risk that manga 2 can answer.

Do not use manga 2 merely to increase sample size.

If used, inspect only the pages needed to answer that question.

## 10. Phase E — Minimal implementation

Only confirmed B cases are implementation candidates.

Implement by renderer/provenance cause, not by content label.

Good scopes:

- one exact transform lineage;
- one exact rotation/crop/padding chain;
- one exact upstream source attribution rule.

Bad scopes:

- "manga mode";
- "light-novel front matter";
- "first 7 pages";
- "2x-ish candidate";
- "portrait/landscape mismatch";
- "closest request".

For every production change:

- keep original-JPEG priority unchanged;
- keep existing proven reconstructed-JPEG paths unchanged unless necessary;
- preserve fail-closed behavior;
- keep spread all-or-none semantics where applicable;
- avoid shared/Core abstraction unless more than one proven BookWalker pattern genuinely
  needs it;
- update `note/01_bookwalker.md` in the same change.

## 11. Tests

Follow `docs/TEST_STRATEGY.md`.

For each new proof path, include:

- positive proven case;
- ambiguous candidate case;
- wrong identity case;
- wrong geometry/transform case;
- unsafe operation case where relevant;
- near-miss dimensions;
- fallback preservation;
- existing original-JPEG path regression;
- existing ordinary reconstructed-JPEG regression.

Use browser-backed Integration where the proof depends on actual Canvas/ImageBitmap
behavior.

Do not add copyrighted BookWalker page bodies as fixtures.

Run Ruff when practical.

Full pytest is required only if the change becomes shared, large, or impact scope is
uncertain.

## 12. Live verification

After implementation, perform bounded live verification.

At minimum:

### Manga

- cover;
- one opening/special page if affected;
- at least two ordinary body spreads using the changed or intentionally unchanged path.

### Light novel

- cover;
- `2/314` and/or `3/314` if changed;
- one additional opening D/fallback page if left unsupported;
- at least two ordinary text pages using the existing reconstructed-JPEG path.

For any new recovery path, use the strongest available bounded diagnostic comparison.

Pixel equality may support the evidence but does not replace provenance.

Always verify/restore page position around each independent probe.

## 13. Reviewer final gate

Reviewer must confirm:

- every production change corresponds to a confirmed B case;
- no C/A case was needlessly rewritten;
- D remains fail-closed;
- no heuristic candidate selection was introduced;
- manga and LN existing A paths still work;
- ordinary LN reconstructed-JPEG behavior still works;
- tests cover positive and rejection boundaries;
- live verification targeted the intended actual pages;
- note wording does not overclaim.

No `BLOCKING` finding may remain.

## 14. Critic final gate

Critic independently challenges the final result.

Required questions:

1. Can any new rule return the wrong response for another page?
2. Is any rule broader than the observed renderer/provenance evidence?
3. Did any PNG fallback get "improved" merely because JPEG existed nearby?
4. Could a source PNG be incorrectly reinterpreted as JPEG?
5. Are visible-page semantics preserved, including rotation/crop/padding?
6. Are unsupported cases still clearly D rather than silently accepted?
7. Was the optional second manga used only for a concrete generalization question?
8. Are the final note claims exactly supported by evidence?

Any material `CHALLENGE` returns to Lead/Worker.

## 15. Completion criteria

Stage 02 is complete when:

1. the pending Critic gate has been performed;
2. manga ordinary-body D behavior is explained enough to classify it A/B/C/D;
3. LN `2/314` and `3/314` are individually classified A/B/C/D with the missing or
   proven provenance stated explicitly;
4. any confirmed B case is either implemented safely or intentionally deferred with a
   documented reason;
5. A/C cases are not changed unnecessarily;
6. D cases remain fail-closed;
7. required tests pass;
8. bounded live verification passes for changed and regression paths;
9. viewer-position handling is recorded;
10. `note/01_bookwalker.md` is synchronized;
11. Reviewer has no `BLOCKING`;
12. Critic has no material `CHALLENGE`.

It is valid for Stage 02 to finish with **zero production changes** if evidence does not
justify a B implementation.

## 16. Final Lead report

Report:

- Critic entry findings;
- probes actually run and why;
- manga A/B/C/D conclusion;
- LN opening A/B/C/D conclusion;
- whether manga 2 was used and why;
- implemented changes, if any;
- unchanged cases and why they were already correct or intentionally fail-closed;
- tests and results;
- live verification;
- viewer-position restoration evidence;
- Reviewer findings/resolution;
- Critic final findings/resolution;
- remaining D cases;
- recommended next runbook, if any.

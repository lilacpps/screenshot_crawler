# BookWalker Source-Native Capture — Stage 02: Provenance Resolution

## 1. Starting point

Continue from:

`research/bookwalker-source-native-20261005`

Latest published checkpoint before this workflow revision:

`efbadb8a4a1f503705546b1eb37375c30a9e6beb`

Production capture code is still unchanged.

The previous workflow attempted frequent Reviewer/Critic gates and hit agent-thread
capacity. This revised Stage 02 removes those gates from ordinary research.

The previous unreviewed OBJECT-A/B/C diagnostic work is **not repository authority**.
Use it only if Lead decides it is the shortest path to a concrete unanswered question.
It is valid to retire it.

## 2. Known evidence

### Manga 1

https://bookwalker.jp/de038ee678-e389-4ceb-a13e-4f7f0154d79e/

Known:

- cover baseline A / original JPEG;
- ordinary manga body remains D;
- R5 verified selected native lineage at `9/159`;
- two native PNG parts were 844x1200;
- renderer/canvas/mapping identity and ordering were observed;
- each selected mapping had 1,026 tiles and 38 destination-edge clips;
- no eligible full-resolution encoded candidate was proven;
- candidate inventory contained only 158x224 JPEG thumbnails;
- R5 therefore does **not** prove source PNG, JPEG reconstruction, or complete encoded
  source attribution.

Manga 2 remains optional:

https://bookwalker.jp/deeb7abe07-9147-4959-b490-75fa6743d8f2/

### Light novel

https://bookwalker.jp/dea0961d33-6ef8-4673-a455-0ec0ecd5de47/

Known:

- cover A / original JPEG;
- ordinary text pages use the existing proven reconstructed-JPEG path;
- opening `2/314` through `7/314` remain D;
- `2/314`: a 1448x2048 JPEG exactly matched a bitmap, but exact visible-output
  attribution was incomplete;
- `3/314`: a 2048x1456 bitmap had one exact JPEG candidate, but
  crop/padding/coded-mapping/output proof was incomplete.

## 3. Goal

Get to an operationally useful classification with the least additional work.

For each investigated pattern:

- A — already source-native;
- B — recoverable source-native;
- C — source-native PNG/current PNG correct;
- D — ambiguous/unsupported and intentionally fail-closed.

Stage 02 may finish with zero production changes.

The goal is not complete viewer reverse engineering.

## 4. Active roles

### Lead — GPT-6.1 Sol

Lead decides:

- the next bounded question;
- whether existing evidence is enough;
- when a D case is no longer worth deeper investigation;
- whether a B recovery contract is sufficiently proven;
- whether Reviewer or Critic should be invoked.

### Worker — GPT-5.6 Luna

Worker performs:

- bounded live probes;
- minimal diagnostics;
- implementation if approved by Lead;
- tests/live verification;
- note/checkpoint synchronization.

Worker is the only live-viewer operator and only production writer.

### Reviewer

Do **not** invoke Reviewer for normal research probes.

Invoke Reviewer only when:

- production code is changed;
- a diagnostic helper is being promoted into a durable test/production contract;
- Lead explicitly asks for one consequential conclusion review.

Production code may not be merged without Reviewer approval.

### Critic

Do **not** invoke Critic at stage entry or stage completion by default.

Invoke only if Lead proposes:

- weakening proof/fail-closed gates;
- heuristic attribution;
- generalizing beyond observed exact provenance;
- large/shared abstraction;
- another change with material silent-wrong-artifact risk.

## 5. Resume policy after the previous checkpoint

The previous `agent thread limit reached` problem no longer blocks research under this
runbook.

Do not begin by restoring Reviewer or Critic.

Do not mechanically finish OBJECT-A/B/C.

Instead:

1. Lead reads R5 and Stage 01 evidence.
2. Lead chooses the smallest direct unanswered question.
3. Worker performs one bounded probe.
4. Lead decides whether that materially changes A/B/C/D.
5. Repeat only while another bounded answer could change the operational decision.

Unreviewed OBJECT-A output may not be used as production/source-format authority.
If not needed, leave it unused.

## 6. Manga research

Start with at most two representative ordinary-body spreads unless evidence requires
more.

For each, answer only the minimum useful questions:

- What exact selected renderer/native source is used?
- Can the visible page be tied one-to-one to an upstream encoded source?
- Is there a real rotation/crop/scale/padding/composition step?
- Is a full-resolution JPEG or PNG candidate actually attributable?
- What single fact prevents B or C?

Possible exits:

### A

Existing path already preserves source-native output.

### B

A specific exact recovery contract exists.

Before implementation, Lead checks whether any Critic risk trigger applies.

### C

Authoritative source-native PNG is proven. Current PNG remains correct.

### D

Exact encoded-source attribution is not available or recovery remains unsafe.
Document the missing fact and stop unless a concrete next probe could change the
decision.

Do not probe all unresolved spreads merely to increase confidence.

## 7. Light-novel research

Focus first on `2/314` and `3/314`.

For each, determine whether the exact JPEG/bitmap can be tied to visible output through
an explicit traced lineage:

- selected draw/source identity;
- upstream canvas/bitmap identity;
- sourceRect/destinationRect;
- transform/rotation;
- crop/padding;
- scale/composition;
- whether all candidate pixels correspond to the visible page;
- whether exactly one candidate remains.

A width/height swap is not itself proof of rotation.

If the exact lineage cannot be proven with a bounded probe, D is an acceptable final
classification.

## 8. Optional manga 2

Use manga 2 only when manga 1 has produced a concrete pattern whose generalization needs
cross-title confirmation.

Do not use it for sample-size inflation.

## 9. Production implementation

Only B cases are candidates.

Implement the smallest renderer/provenance cause, not content labels such as:

- manga;
- front matter;
- first N pages.

Preserve:

- original-JPEG priority;
- existing proven reconstruction;
- fail-closed fallback;
- all-or-none spread behavior where applicable.

If the implementation is exact and does not trigger Critic risk conditions, Critic is
not required.

After implementation:

1. Worker runs targeted tests and bounded live verification.
2. Reviewer reviews the production diff and evidence.
3. Worker fixes all `BLOCKING`.
4. Reviewer confirms no `BLOCKING`.

## 10. Tests

Research diagnostics only need enough checking to trust the immediate probe.

Do not create a large synthetic test matrix unless it is needed for a production
contract.

For production recovery logic, test:

- positive proven path;
- ambiguous/wrong identity path;
- wrong geometry/transform;
- near miss;
- fallback;
- existing original JPEG;
- existing reconstructed JPEG.

Use browser-backed Integration when the proof depends on Canvas/ImageBitmap behavior.

## 11. Live verification

If production changes are made, verify a bounded set covering:

### Manga

- cover or known A control;
- at least two ordinary body spreads relevant to the changed path.

### Light novel

- cover or known A control;
- changed opening page(s);
- one unsupported/fallback opening page if relevant;
- at least two ordinary text controls.

Always check and restore actual viewer position.

If no production changes are made, additional regression live runs are optional unless
Lead needs them to support the final classification.

## 12. Completion

### No production change

Stage 02 may complete when Lead has documented:

- manga conclusion A/B/C/D;
- LN `2/314` and `3/314` conclusions;
- exact missing evidence for remaining D;
- why further research is not worth its cost;
- whether manga 2 was unnecessary.

Reviewer and Critic are not mandatory.

### Production change

Stage 02 completes when:

- B recovery contract is explicit;
- relevant tests/live verification pass;
- note is synchronized;
- Reviewer has no `BLOCKING`;
- Critic has no unresolved challenge **only if Critic was triggered by a material risk
  condition**.

## 13. Final report

Report:

- probes actually run;
- manga conclusion;
- LN opening conclusion;
- manga 2 usage and reason;
- implementation, if any;
- tests/live verification, if any;
- remaining D cases;
- Reviewer/Critic usage and why;
- recommended next stage, if any.

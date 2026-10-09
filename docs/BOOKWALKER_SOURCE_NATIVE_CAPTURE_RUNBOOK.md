# BookWalker Source-Native Capture Runbook

## 1. Purpose

This runbook defines the default autonomous workflow for investigating and improving
BookWalker capture behavior in the existing adapter.

The objective is **source-native preservation**, not JPEG conversion:

- source JPEG -> preserve/recover JPEG when exact visible-page provenance is proven;
- source PNG -> keep PNG;
- provenance insufficient -> keep the existing fail-closed native/rendered fallback.

This runbook complements `AGENTS.md`, `docs/CAPTURE_STRATEGY.md`,
`docs/TEST_STRATEGY.md`, and `note/01_bookwalker.md`.

## 2. Workflow principle

Use this rule throughout the workstream:

> **Research is lead-driven. Review is change-driven. Critic is risk-driven.**

Do not create gates merely because multiple agent roles exist.

The default active research team is only:

- Lead / root orchestrator: **GPT-6.1 Sol**
- Worker: **GPT-5.6 Luna**

Reviewer and Critic are dormant unless their trigger conditions below are met.

## 3. Roles

### Lead — GPT-6.1 Sol

The Lead owns:

- the research question;
- evidence sufficiency;
- A/B/C/D classification;
- the next bounded probe;
- whether additional research is worth its cost;
- whether production implementation is justified;
- whether Reviewer or Critic should be invoked.

The Lead should read Worker evidence directly and keep the investigation moving.
The Lead does not need independent review for every probe or research checkpoint.

### Worker — GPT-5.6 Luna

Use `bookwalker_worker` for:

- repository inspection;
- bounded live-site probes;
- diagnostic helpers;
- implementation;
- tests;
- live verification;
- note synchronization.

The Worker is the only production writer and the only agent allowed to drive the live
BookWalker viewer.

### Reviewer — GPT-6.1 Sol, read-only

Reviewer is **not part of the normal research loop**.

Use `bookwalker_reviewer` when:

- production code is implemented or modified;
- a diagnostic/research helper is being promoted into a durable production or test
  contract;
- the Lead explicitly wants one independent check of a consequential conclusion.

Reviewer is mandatory before merging a production implementation.

Reviewer is not required for:

- ordinary probes;
- A/B/C/D research classification with no production change;
- a safe no-change conclusion;
- recording that evidence remains insufficient and D stays fail-closed.

### Critic — GPT-6.1 Sol, read-only

Critic is **exceptional**, not a routine phase gate.

Use `bookwalker_critic` only when a proposed decision has material design risk, such as:

- weakening an existing proof/fail-closed gate;
- introducing heuristic attribution by dimensions, timing, filename, proximity, or
  similarity;
- generalizing a rule beyond the observed rendering pattern;
- introducing a large/shared abstraction or refactor;
- changing semantics in a way that could silently return the wrong source artifact.

Critic is not required merely because research starts or ends.

A normal narrow implementation with exact provenance can proceed with Lead + Worker +
Reviewer without Critic.

## 4. Core capture rules

Conceptually:

```text
verified source-native artifact
    ├─ JPEG -> byte-preserving original JPEG when possible
    └─ PNG  -> source/native PNG
        ↓
verified source-native reconstruction
        ↓
native rendered artifact
        ↓
rendered canvas fallback
```

Required rules:

- Never re-encode source PNG to JPEG just to produce `.jpg`.
- Never treat PNG output itself as evidence of a PNG source.
- Never bind a candidate from dimensions alone.
- Never bind a candidate from filename/path proximity alone.
- Never bind a candidate from request timing/order alone.
- Never bind a candidate from visual similarity alone.
- Prefer fail-closed fallback over uncertain attribution.
- Preserve existing original-JPEG priority.
- Do not weaken reconstruction proof gates merely to increase JPEG coverage.

## 5. Evidence classification

Use:

- **A — already source-native**
- **B — recoverable source-native**
- **C — source-native PNG / current PNG correct**
- **D — ambiguous/unsupported; intentionally fail-closed**

Only B is normally an implementation candidate.

A and C need no capture-path change.

D may remain D. The crawler does not need a complete reverse-engineering model of the
viewer when the safe operational answer is "do not recover this source".

## 6. Research loop

Default research loop:

```text
Lead defines one bounded question
    ↓
Worker probes
    ↓
Lead reads evidence
    ↓
classify / ask one more bounded question / stop
```

Do not insert Reviewer or Critic automatically.

A useful research iteration should answer one question, for example:

- Is there an exact upstream encoded source?
- Is this a real rotation, crop, scale, padding, or composition?
- Can the visible page be attributed one-to-one?
- Is the current PNG source-native or merely a fallback?
- What single missing fact prevents B?

Stop building diagnostic infrastructure when it is no longer the shortest path to one
of those answers.

## 7. Implementation loop

When Lead concludes that a B case is sufficiently proven:

```text
Lead defines exact recovery contract
    ↓
Critic only if a risk trigger applies
    ↓
Worker implements smallest change
    ↓
Worker runs targeted tests + bounded live verification
    ↓
Reviewer reviews production diff/evidence
    ↓
Worker fixes BLOCKING findings
    ↓
Reviewer confirms no BLOCKING
```

Do not make Critic a mandatory final sign-off unless a risk trigger actually applies.

## 8. Viewer-position protocol

BookWalker persists reader position. Previous-run position is never authority.

For every independent live probe:

1. attach/open through the shared Crawler Chrome/CDP path;
2. read actual visible page counter/state;
3. compare with intended anchor;
4. explicitly rewind/reposition if different;
5. verify position again;
6. collect only the bounded probe window;
7. record start/end page identity/counter;
8. restore the intended anchor when practical.

Only Worker manipulates the live viewer.

## 9. Research scope discipline

Prefer representative bounded samples.

Do not:

- probe every page because some pages are unresolved;
- add a second title merely to increase sample size;
- complete a diagnostic framework merely because it was started;
- keep researching a D case without a concrete question whose answer could change the
  operational decision.

A second manga/title is justified only when it answers a specific generalization
question.

## 10. Branch and workspace policy

Before production edits:

- confirm branch/worktree state;
- use a feature/research branch;
- preserve unrelated user changes;
- never reset or discard user work.

Ignored live artifacts may be used locally but are not repository authority unless their
relevant structural evidence is recorded in a durable text artifact.

## 11. Tests

During research, run only checks necessary to trust the diagnostic being used.

Production implementation follows `docs/TEST_STRATEGY.md`:

```text
targeted tests
-> affected BookWalker tests
-> browser-backed integration when required
-> bounded live verification
-> broader/full suite only for shared/large/uncertain changes
```

For a new proof path, test positive and near-miss/fail-closed cases.

Do not commit copyrighted BookWalker page bodies as fixtures.

## 12. Documentation

Production behavior changes require `note/01_bookwalker.md` synchronization.

Research checkpoints may also update the note when they materially change the known
current-state understanding, but should clearly distinguish:

- observed fact;
- diagnostic inference;
- unresolved question;
- production behavior.

## 13. Completion

A research stage can complete with **zero production changes**.

If no production code changed:

- Lead may close the stage after evidence is documented;
- Reviewer is optional;
- Critic is unnecessary unless a risk-triggering design conclusion was made.

If production code changed:

- relevant tests/live verification must pass;
- Reviewer must have no remaining `BLOCKING`;
- Critic is required only if one of the risk triggers in section 3 applies.

Final reporting should state:

- evidence/classifications;
- probes actually run;
- implementation, if any;
- tests/live verification, if any;
- remaining D cases;
- Reviewer/Critic usage and why they were or were not invoked.

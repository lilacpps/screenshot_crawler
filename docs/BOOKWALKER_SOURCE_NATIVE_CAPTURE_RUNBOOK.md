# BookWalker Source-Native Capture Multi-Agent Runbook

## 1. Purpose

This runbook defines the autonomous multi-agent workflow for investigating and improving
BookWalker capture behavior in the existing adapter.

The current investigation has two representative targets:

1. one purchased manga volume;
2. the opening/front-matter region of one purchased light novel.

The objective is **not** "convert everything to JPEG".

The objective is:

> Preserve the source-native image format and source-native image quality whenever the
> exact visible page can be attributed safely. If the source is JPEG, keep/recover JPEG.
> If the source is PNG, keep PNG. If provenance is not strong enough, fail closed to the
> existing native/rendered fallback.

This runbook is for existing BookWalker capture research and maintenance. It complements,
but does not replace, the repository authorities in `AGENTS.md`,
`docs/CAPTURE_STRATEGY.md`, `docs/TEST_STRATEGY.md`, and
`note/01_bookwalker.md`.

## 2. Model and role assignment

### Lead / root orchestrator — GPT-6.1 Sol

Run the root Codex session with **GPT-6.1 Sol**, high reasoning effort.

The Lead:

- owns the research question and acceptance criteria;
- reads repository authorities and current BookWalker implementation before delegating;
- decides what evidence is sufficient;
- chooses the next phase from observed facts rather than following a fixed script;
- controls the single live-browser lease;
- separates "source PNG and therefore already correct" from "recoverable source JPEG";
- sends every writer iteration to Reviewer;
- sends important design/evidence decisions to Critic;
- keeps the work moving until acceptance criteria are satisfied or a genuine external
  blocker is reached.

The Lead should not make production code edits during the gated workflow.

### BookWalker Worker — GPT-5.6 Luna

Use `bookwalker_worker` for:

- repository investigation;
- bounded live-site probes;
- diagnostic/PoC helpers;
- production implementation;
- targeted tests;
- browser-backed tests;
- live verification;
- synchronization of `note/01_bookwalker.md`.

The Worker is the **only production writer**.

Research and implementation may use the same Luna worker sequentially. Do not introduce
multiple production writers merely to parallelize work.

### Reviewer — GPT-6.1 Sol, read-only

Use `bookwalker_reviewer` after every Worker iteration that produces code, tests,
diagnostics, or a material research conclusion.

Reviewer responsibilities:

- compare changes against repository authorities and the current phase contract;
- inspect observed evidence versus assumptions;
- check correctness, regressions, edge cases, tests, and note synchronization;
- distinguish material defects from style preferences.

Reviewer reports:

- `BLOCKING`: must be resolved before the phase completes;
- `NON-BLOCKING`: useful follow-up but not required now;
- `VERIFIED`: evidence/contracts checked and consistent.

Reviewer never edits files.

### Critic — GPT-6.1 Sol, read-only

Use `bookwalker_critic` as an adversarial design/evidence check, not as a second code
reviewer.

Critic is invoked at minimum:

1. after baseline manga + light-novel observations are classified and before production
   implementation;
2. before final completion/sign-off;
3. whenever the Lead proposes weakening an existing proof gate or adding a heuristic
   attribution rule.

Critic should actively challenge:

- whether an alleged JPEG source is actually authoritative for the visible page;
- whether a PNG result is already source-native and therefore needs no change;
- whether dimensions, filenames, URL proximity, timing, or visual similarity are being
  mistaken for provenance;
- whether crop/scale/canvas-copy reconstruction is completely proven;
- whether the evidence generalizes beyond one accidental page;
- whether a proposed abstraction is broader than required;
- whether the implementation can silently degrade quality or return the wrong page.

Critic reports:

- `CHALLENGE`: evidence/design is insufficient and must be revisited;
- `CAUTION`: plausible risk worth recording but not blocking;
- `CLEAR`: no material challenge found for the current decision.

A material `CHALLENGE` is treated as blocking by the Lead.

## 3. Core capture principle

The conceptual priority is:

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

The existing concrete BookWalker implementation may keep its current
`original_jpeg -> reconstructed_jpeg -> native_png -> rendered_canvas` shape. Do not
perform a broad abstraction refactor unless observed requirements justify it.

Required rules:

- Never re-encode a source PNG to JPEG merely to obtain a `.jpg` artifact.
- Never claim "JPEG is better" as a reason to change a correct source-native PNG.
- Never select a candidate from dimensions alone.
- Never select a candidate from filename/path proximity alone.
- Never select a candidate from request timing/order alone.
- Never select a candidate from visual similarity alone.
- Existing fail-closed behavior is preferred to an uncertain source attribution.
- Existing byte-preserving original-JPEG priority remains first when already proven.
- Existing reconstruction proof gates must not be weakened merely to increase JPEG
  coverage.

## 4. Research scope

### 4.1 Manga target

Start with exactly one representative purchased manga volume.

The first pass should classify a bounded, representative sample rather than immediately
crawling the whole book for diagnosis.

At minimum inspect:

- first logical page / cover-like page;
- opening/front-matter pages;
- enough early pages to reach stable ordinary manga body rendering;
- at least five ordinary body spreads after the rendering pattern is stable;
- any color, single-page, or special-geometry page encountered in that bounded region;
- one additional distant region only if needed to test whether the ordinary pattern is
  stable.

If a specific end-region question emerges, inspect a small bounded end-region sample.
Do not add end-region work mechanically when it does not answer an open question.

### 4.2 Light-novel target

Inspect only the opening/front-matter region in this work item.

At minimum classify:

- cover/first visible page;
- leading illustration(s);
- front matter;
- transition into normal text body;
- a few ordinary text-body pages as a regression/control sample.

The important question is whether the cover and leading illustrations are source JPEG,
source PNG, or another proven source-native path. If they are source PNG, remaining PNG
is a successful result, not a failure.

## 5. Viewer-position protocol

BookWalker persists reader position. Closing and reopening the viewer may resume from the
last location. Therefore **the previous run's expected end position is never authority**.

Only one agent may control the live BookWalker viewer at a time.

For every bounded live probe:

1. Open/attach through the existing shared Crawler Chrome/CDP path.
2. Read the actual visible page counter/state before advancing.
3. Compare the observed position with the probe's intended anchor.
4. If it differs, explicitly rewind/reposition before collecting evidence.
5. Verify the page counter/state again after repositioning.
6. Run only the bounded probe window.
7. Record the observed start and end page identity/counter.
8. Before a logically independent probe, re-check position and rewind again as needed.
9. Do not infer that reopening the viewer resets to page 1.
10. Do not let Reviewer or Critic manipulate the live viewer.

When investigating the opening pages, favor returning to the opening anchor between
experiments so later runs do not accidentally start deep in the volume.

If automatic rewind/reposition is unreliable, stop that probe and improve the bounded
diagnostic/control path instead of silently testing the wrong pages.

## 6. Evidence contract

For every representative page/part investigated, preserve a compact evidence record.
The exact transport format is flexible, but the logical fields should include:

| Field | Meaning |
| --- | --- |
| target | manga or light novel |
| visible page identity/counter | actual viewer state used for the observation |
| page role | cover, front matter, illustration, ordinary body, special geometry, etc. |
| current returned path | `original_jpeg`, `reconstructed_jpeg`, `native_png`, `rendered_canvas` |
| output MIME/extension | current artifact format |
| output dimensions | current artifact dimensions |
| observed response candidates | bounded MIME/dimensions/hash metadata only |
| native source | source constructor/type and dimensions |
| renderer/canvas chain | relevant proven draw/copy/scale/crop chain |
| mapping provenance | direct / scaled one-hop / unavailable / other observed state |
| classification | A/B/C/D below |
| evidence | why the classification is justified |
| action | no change / more probe / implementation candidate |

Do not commit copyrighted BookWalker page bodies, raw image payloads, cookies, tokens,
credentials, storage state, or base64 image data. Hashes and bounded structural metadata
are sufficient for repository evidence.

### Classification

Use exactly these semantic classes:

- **A — already source-native**: current artifact already preserves the authoritative
  source-native format/quality.
- **B — recoverable source-native**: a better source-native artifact exists and the
  exact visible-page provenance can plausibly be proven with a bounded implementation.
- **C — source-native PNG / current PNG correct**: PNG is authoritative or the current
  PNG is the correct native representation; no JPEG work is needed.
- **D — ambiguous/unsupported**: evidence is insufficient; retain fail-closed fallback
  and investigate further only if valuable.

A page being PNG does not imply B or D. It may be C.

## 7. Gated workflow

### Phase 0 — Preflight and current-state read

Lead reads:

- `AGENTS.md`;
- `docs/CAPTURE_STRATEGY.md`;
- `docs/TEST_STRATEGY.md`;
- `docs/CODEX_IMPLEMENTATION_GUIDE.md`;
- `note/01_bookwalker.md`;
- BookWalker capture code and relevant tests.

Confirm the current known baseline:

- verified original JPEG remains first priority;
- ordinary purchased pages can use proven lossless/source-native reconstruction;
- the current one-hop scaled source path is supported only under strict provenance;
- unsupported geometry falls back safely;
- BookWalker position is persistent and must be explicitly managed.

No production change in this phase.

### Phase 1 — Baseline manga observation

Worker uses current `main` behavior without production changes.

Goals:

- determine the current output path across representative manga pages;
- identify the actual response/source formats and dimensions;
- determine whether ordinary manga pages already fit the proven BookWalker path;
- isolate only the pages whose output is not clearly source-native.

Lead reviews the evidence table.

Reviewer checks factual consistency.

Do not implement yet unless the result is a trivial already-proven regression with no
open provenance question.

### Phase 2 — Light-novel opening observation

Worker investigates the light-novel opening/front-matter window.

Goals:

- classify cover and leading illustrations as source JPEG, source PNG, or unresolved;
- distinguish current PNG correctness from a missed JPEG source;
- record any special crop/scale/intermediate-canvas chain;
- use ordinary text pages as a control for the already-supported body path.

Again, no format conversion is justified merely because the output is PNG.

### Phase 3 — Critic evidence gate

Lead provides the combined manga + light-novel evidence to Critic before designing a
production fix.

Critic must answer at least:

1. Which observed PNG pages genuinely need a code change?
2. Which are already source-native/correct?
3. For each proposed recovery path, what exact evidence connects candidate bytes to the
   visible page?
4. What observation would falsify that attribution?
5. Is the proposed rule narrower than the evidence, equal to it, or broader than it?
6. Can current fail-closed gates remain unchanged?

If Critic returns a material `CHALLENGE`, return to bounded research.

### Phase 4 — Minimal implementation by cause

Lead groups only confirmed B-class cases by rendering/provenance cause.

Worker implements one cause at a time.

Examples:

- a strictly proven additional one-hop geometry;
- a source-native PNG path that is currently unnecessarily re-materialized;
- a narrow front-matter provenance pattern.

Non-examples:

- "all first pages";
- "all 2x-size candidates";
- "nearest response before render";
- "JPEG-looking filenames";
- broad dimension-ratio heuristics.

Each implementation iteration must include:

- the smallest production change;
- regression tests for the exact proof/fail-closed boundary;
- affected BookWalker tests;
- relevant browser-backed verification where required;
- `note/01_bookwalker.md` synchronization.

After every iteration, Reviewer runs the quality gate. Any `BLOCKING` finding returns
to Worker before another cause is implemented.

### Phase 5 — Cross-content live verification

After production changes, Worker performs bounded live verification with explicit
position resets.

Minimum verification set:

- representative manga opening pages;
- representative ordinary manga body pages;
- light-novel cover/front matter/leading illustration;
- ordinary light-novel text pages;
- any previously verified original-JPEG path affected by the changed code;
- any fallback path intentionally left unsupported.

For each changed path, verify both positive proof and at least one meaningful rejection
or fallback boundary when practical.

If the implementation changes a reconstruction proof gate, use the strongest existing
diagnostic comparison available for a bounded sample, including pixel-exact diagnostics
where applicable. Diagnostic equality is evidence; provenance remains the authority.

### Phase 6 — Reviewer final gate

Reviewer checks:

- no unsupported attribution heuristic was introduced;
- source PNG is not converted to JPEG without a separate explicit requirement;
- original-JPEG priority is preserved;
- reconstruction remains fail-closed;
- manga changes do not regress light novels and vice versa;
- position-dependent live evidence was collected from the intended pages;
- tests cover positive and negative proof boundaries;
- notes reflect current behavior rather than only appending stale history.

No `BLOCKING` finding may remain.

### Phase 7 — Critic final challenge

Critic independently examines the final evidence and diff.

Required questions:

- Are we returning a higher-quality/source-native artifact, or merely a different one?
- Could the same rule return the wrong response for another page in the same book?
- Could the rule accidentally reinterpret a source PNG as JPEG?
- Is any proof step based on coincidence rather than identity/provenance?
- Did live verification actually start on the intended pages after persisted-position
  handling?
- Is any new abstraction unnecessary for the observed problem?
- Are any claims in `note/01_bookwalker.md` stronger than the evidence?

A material `CHALLENGE` sends the work back to Lead/Worker.

## 8. Parallelism and browser ownership

The repository currently limits concurrent subagent threads. Do not use concurrency as
a goal by itself.

Allowed parallel work:

- independent read-only repository inspection;
- independent analysis of already-produced metadata/logs;
- Reviewer or Critic reading a completed diff while no writer is changing it.

Not allowed:

- multiple production writers;
- two agents driving the BookWalker viewer concurrently;
- Reviewer/Critic changing repository files;
- one agent advancing the viewer while another assumes a fixed page position.

The live viewer has a single logical lease owned by the Worker under Lead coordination.

## 9. Branch and workspace policy

Research-only browser probing may begin from the current checked-out state, but before
the first production edit:

- confirm the worktree/branch state;
- use a feature branch for production changes;
- do not discard or overwrite unrelated user work;
- do not reset user changes;
- if branch creation or safe isolation is impossible, report the blocker rather than
  forcing it.

Generated crawl outputs and shared browser-profile state are outside Git branch
isolation, so bounded output directories and explicit viewer-position checks remain
required.

## 10. Test policy

Follow `docs/TEST_STRATEGY.md`.

Typical progression:

```text
targeted pure/helper tests
-> affected BookWalker adapter/capture tests
-> relevant browser-backed integration
-> bounded live verification
-> broader/full suite only when the change is shared, large, or uncertain
```

Do not run the full suite after every small research iteration.

For proof logic, tests should cover both:

- a valid proven path that returns the source-native artifact;
- a near-miss/ambiguous/unsafe path that remains fallback.

Do not add real BookWalker copyrighted page images as fixtures.

Run `ruff check src tests` when practical.

## 11. Note/documentation policy

BookWalker production behavior changes require synchronizing
`note/01_bookwalker.md` in the same change.

The note should state current behavior clearly:

- source-native priority;
- verified rendering/provenance patterns;
- manga observations;
- light-novel opening observations;
- output format behavior;
- known fallbacks/unsupported geometry;
- live verification scope.

Do not make the note an ever-growing chronological log when an existing current-state
section can be corrected instead. Preserve historical detail only when it remains useful
for understanding a current limitation or decision.

## 12. Overall acceptance criteria

The work is complete when all applicable criteria hold:

1. One purchased manga volume has a representative, bounded capture classification.
2. Ordinary manga pages are confirmed either to use the existing safe source-native path
   or to have a narrowly implemented additional proven path.
3. The light-novel cover and leading illustrations are classified by actual source
   format/provenance.
4. A source PNG is allowed to remain PNG and is not treated as a JPEG failure.
5. If a source JPEG is returned/reconstructed, exact visible-page provenance is proven;
   dimension/path/timing similarity alone is never sufficient.
6. Ambiguous or unsupported pages remain fail-closed.
7. Persisted BookWalker viewer position is explicitly checked and corrected before every
   independent live probe.
8. Existing verified original-JPEG and ordinary-body behavior does not regress.
9. Targeted/affected tests and required live verification pass.
10. `note/01_bookwalker.md` matches the implemented behavior and evidence.
11. Reviewer has no remaining `BLOCKING` findings.
12. Critic has no remaining material `CHALLENGE`.

## 13. Lead final report

The Lead's final report must include:

- phases actually executed;
- manga and light-novel targets used;
- representative evidence classification;
- pages/patterns that were already correct and required no change;
- implemented causes and changed files;
- viewer-position handling used during live verification;
- tests and results;
- live verification performed;
- Reviewer findings and their resolution;
- Critic challenges and their resolution;
- known limitations / D-class cases;
- important verification not performed and why.

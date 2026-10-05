# Comic DAYS Source-Native JPEG Fallback Investigation Runbook

## 1. Purpose

This runbook investigates why Comic DAYS pages that arrive from the site as JPEG
frequently end up as reconstructed PNG in the current crawler.

Primary live target:

- `https://comic-days.com/episode/10834108156628508775`

The goal is **cause identification first, production changes second**.

Do not treat "PNG output" itself as a bug. The Comic DAYS transport JPEG is a
scrambled source image. A JPEG result is acceptable only when the visible page can be
reconstructed without introducing a lossy JPEG re-encode and while preserving the
existing provenance/safety guarantees. If the current PNG fallback is required for a
source layout that cannot be reconstructed losslessly, that is a valid outcome.

This runbook applies to the existing Comic DAYS adapter. Repository authorities remain
`AGENTS.md`, `docs/CAPTURE_STRATEGY.md`, `docs/TEST_STRATEGY.md`,
`docs/CODEX_IMPLEMENTATION_GUIDE.md`, current code/tests, and
`note/08_comicdays.md`.

## 2. Roles

### Leader / root orchestrator — GPT-6.1 Sol

Run the root Codex session with GPT-6.1 Sol, high reasoning effort.

The Leader:

- owns the research question and acceptance criteria;
- reads the current Comic DAYS implementation and tests before delegating;
- decides how much live evidence is sufficient;
- reviews research findings directly;
- decides whether a production change is justified;
- keeps the investigation bounded and focused on the observed fallback;
- invokes the production Reviewer only after production code has changed.

Do not add a separate critic role for this investigation unless an unexpected design
question genuinely requires one.

### Worker — GPT-5.6 Luna

Use the existing Luna worker role for:

- repository inspection;
- bounded live probes;
- research-only diagnostics / PoC helpers;
- production implementation if justified;
- targeted tests;
- browser-backed tests;
- bounded live verification;
- synchronization of `note/08_comicdays.md` after production behavior changes.

Only one Worker may modify production code.

### Production Reviewer — GPT-6.1 Sol, read-only

Use the existing Sol reviewer role **only for production code changes**.

The Reviewer checks:

- the patch matches the established source-native/fallback hierarchy;
- no provenance gate was weakened without evidence;
- no lossy JPEG re-encode is presented as source-native;
- edge cases and regressions are covered;
- tests are sufficient;
- `note/08_comicdays.md` matches the implemented behavior.

Reviewer findings are:

- `BLOCKING`: must be fixed before completion;
- `NON-BLOCKING`: useful follow-up but not required now;
- `VERIFIED`: reviewed and consistent.

Research-only observations and PoC output do not require a Reviewer gate; the Leader
reviews those directly.

## 3. Current known behavior

The existing Comic DAYS capture path is:

```text
strict visible-canvas/source provenance
    -> lossless JPEG coefficient reconstruction
    -> reconstructed PNG from the exact source blob
    -> whole-spread locator screenshot fallback
```

The current production code already observes that Comic DAYS:

- serves JPEG page responses;
- decodes them to page-local `blob:` images;
- draws a full source image and then a 4x4 permutation of 280x400 tiles;
- leaves a narrow right edge outside the 1120px tiled region for observed
  1125/1127px-wide sources.

Current lossless JPEG reconstruction intentionally accepts only a narrow proven subset,
including:

- valid baseline JPEG;
- 8-bit precision;
- grayscale or 3-component JPEG;
- 1x1 sampling for all components (grayscale / 4:4:4);
- exact 16-tile 280x400 source and destination geometry;
- 8px-aligned coefficient movement;
- preserved JPEG structure/quantization/sampling/colorspace and exact coefficient
  readback.

The current tests explicitly reject 4:2:2, 4:2:0, progressive JPEG, malformed JPEG,
unsafe/incomplete plans, and metadata structures outside the proven writer contract.
Those cases currently continue to reconstructed PNG when native pixel reconstruction is
safe.

Therefore the main question is not merely "is the source JPEG?" but:

> Which exact JPEG reconstruction proof gate rejects each observed page, and is that
> rejection a true technical limitation, an obsolete assumption, or a transient capture
> problem?

## 4. Safety and scope constraints

- Use the provided episode as the primary live target.
- Do not consume Work Tickets, points, coins, paid resources, or purchases for this
  investigation.
- Existing already-active access may be used.
- Do not save or commit copyrighted page image bodies or raw source JPEGs to the
  repository.
- Output under ignored `output/` may contain temporary local artifacts needed for the
  investigation.
- Repository evidence should contain only bounded metadata, hashes, JPEG structure,
  geometry, reason codes, and test fixtures synthesized locally.
- Do not weaken `strict_canvas_sequence()` merely to increase JPEG coverage.
- Do not JPEG-encode reconstructed pixels and call the result source-native.
- Do not perform broad refactors of Comic DAYS capture while diagnosing this issue.
- Do not run the full test suite after every research iteration.

## 5. Investigation question and reason taxonomy

Before changing production behavior, make the JPEG path explain **why** it rejected a
candidate.

The diagnosis must distinguish at least the following classes:

1. `not_jpeg`
2. `unsupported_sof_or_precision`
3. `progressive`
4. `unsupported_component_count`
5. `unsupported_sampling`
6. `dimension_mismatch`
7. `unexpected_tile_geometry`
8. `non_8px_aligned_mapping`
9. `dct_read_failed`
10. `component_block_shape_mismatch`
11. `writer_failed`
12. `metadata_normalization_failed`
13. `coefficient_readback_mismatch`
14. `quantization_or_sampling_changed`
15. `colorspace_or_progressive_state_changed`
16. `header_or_sof_changed`
17. `untouched_edge_changed`
18. `unsafe_or_incomplete_canvas_provenance`
19. `source_snapshot_unavailable`
20. other explicitly observed cause

The exact implementation of the diagnostic may differ, but the final evidence must map
each sampled PNG fallback to a concrete first failing reason rather than a generic
"JPEG reconstruction returned None".

Prefer a **research-only diagnostic helper** or a diagnostic mode that calls the same
production validation logic without altering production success/fallback semantics.

## 6. Gated workflow

### Phase 0 — Preflight

Leader reads:

- `AGENTS.md`
- `docs/CAPTURE_STRATEGY.md`
- `docs/TEST_STRATEGY.md`
- `docs/CODEX_IMPLEMENTATION_GUIDE.md`
- `note/08_comicdays.md`
- `src/screenshot_crawler/site_adapters/comicdays/adapter.py`
- `src/screenshot_crawler/site_adapters/comicdays/native_capture.py`
- `src/screenshot_crawler/site_adapters/comicdays/README.md`
- relevant Comic DAYS unit/integration/research tests
- existing `poc/comicdays_lossless_jpeg.py` and capture probes

Confirm current branch/worktree state. Do not overwrite unrelated user changes.

No production change in this phase.

### Phase 1 — Reproduce the fallback on the target

Worker uses current production behavior against the provided episode.

Collect a bounded representative sample first:

- opening content;
- at least 6 ordinary body spreads/pages;
- one later body region if easy to reach;
- any visibly different/color/special page encountered in that sample.

For each captured part/spread record:

- slider/current visible identity;
- output capture mode (`jpeg`, `reconstructed_png`, locator fallback);
- source byte MIME and JPEG dimensions;
- JPEG SOF marker / baseline vs progressive;
- component count;
- sampling factors;
- source/canvas dimensions;
- observed tile geometry;
- whether `strict_canvas_sequence()` passed.

If the sample already demonstrates one dominant deterministic cause, do not crawl the
whole episode merely to collect more copies of the same fact. If causes vary, expand the
sample until the important classes are understood.

### Phase 2 — Identify the exact first failing JPEG gate

If current diagnostics are insufficient, Worker adds or extends a **research-only**
diagnostic path.

Preferred approach:

- reuse the existing production parsing/validation helpers where practical;
- expose a structured validation result such as
  `{ok, first_failure, facts}` in PoC/research code;
- keep `reconstruct_jpeg()` production behavior unchanged during diagnosis.

For each representative PNG fallback, identify the exact first failing gate.

The Leader should specifically test these hypotheses, but must not assume any is true:

- the site now commonly serves 4:2:0 or 4:2:2 rather than 4:4:4;
- the source is progressive JPEG;
- dimensions/tile geometry changed;
- the source/canvas provenance sequence is incomplete;
- the DCT writer/normalizer rejects an otherwise supportable JPEG;
- a transient source snapshot failure is causing native capture to miss the JPEG path.

### Phase 3 — Determine whether each dominant cause is fixable losslessly

For each dominant fallback class, classify it as:

- **A — current fallback is correct**: source-native lossless JPEG cannot currently be
  proven/reconstructed without quality loss or weakening provenance;
- **B — production bug/regression**: an already-supported case is failing because of an
  implementation defect;
- **C — safely extendable**: the JPEG remains losslessly reconstructable with a narrow
  additional proven rule;
- **D — unresolved**: more evidence is needed.

Important example: if 4:2:0 / 4:2:2 dominates, do not automatically add support. The
280px horizontal tile boundary is not an MCU boundary for horizontally subsampled
chroma. The Worker must prove coefficient/pixel equivalence across those boundaries
before claiming a lossless JPEG path. If that proof cannot be made, reconstructed PNG
is the correct source-native-pixel fallback.

Likewise, progressive JPEG support must prove that coefficient reconstruction and the
resulting JPEG structure remain acceptable under the repository's lossless/source-native
contract; merely decoding and re-encoding is not sufficient.

Leader must explicitly document why a cause is A/B/C/D.

### Phase 4 — Production implementation, only if B or C exists

If all important cases are A, make no production code change. Record the conclusion and
any useful diagnostic improvement separately.

If B/C exists, Worker implements the smallest cause-specific change.

Requirements:

- preserve the current hierarchy:
  lossless JPEG -> reconstructed PNG -> locator fallback;
- preserve all-or-none spread behavior;
- preserve strict canvas/source provenance;
- no lossy JPEG re-encoding;
- do not broaden geometry/sampling support beyond observed/proven cases;
- add positive and negative boundary tests;
- update `note/08_comicdays.md` in the same production change.

After each production implementation iteration, invoke the Sol Reviewer. Any
`BLOCKING` finding returns to Worker before proceeding.

### Phase 5 — Verification

For a production fix, Worker verifies:

1. targeted unit tests for the changed JPEG validation/reconstruction contract;
2. affected Comic DAYS adapter tests;
3. relevant browser-backed integration tests;
4. bounded live verification on the provided target;
5. at least one negative/fallback case showing unsupported input still goes to PNG;
6. `ruff check src tests` when practical.

Run full `pytest -q` only if the change becomes shared, broad, or impact is uncertain.

For the live sample, report the before/after capture-mode distribution. A successful
change should explain exactly which former PNG cases became JPEG and why.

If no production change is made, verification should instead demonstrate that the
observed PNG fallback is intentional and technically justified.

## 7. Decision rules for likely causes

### 4:4:4 / grayscale baseline JPEG unexpectedly falling back

Treat this as a likely bug or overly strict secondary gate. Inspect:

- exact source/canvas dimensions;
- 16-tile geometry;
- 8px alignment;
- `jpeglib` DCT shapes;
- metadata normalizer;
- coefficient readback;
- untouched right-edge proof.

Do not accept a generic fallback reason.

### 4:2:2 or 4:2:0 JPEG

Current production rejection is intentional.

A change is allowed only if the Worker proves a genuinely lossless reconstruction for
the observed 280px tile boundaries. Because horizontally subsampled chroma uses wider
MCUs, a tile boundary can split a chroma MCU. If exact equivalence cannot be proven
without re-encoding, keep reconstructed PNG.

### Progressive JPEG

Current production rejection is intentional.

Support requires a narrow proof that the reconstructed quantized coefficients and
required JPEG structural properties remain correct. Do not convert to baseline through
ordinary decode/re-encode.

### Unsafe/incomplete provenance or source snapshot failure

Do not relax identity/provenance checks. Determine whether this is transient and can be
fixed by bounded re-observation/retry without mixing generations or source identities.

## 8. Acceptance criteria

The work is complete when:

1. The provided episode has been reproduced with current production capture.
2. A representative set of PNG fallbacks has an exact first-failing reason.
3. The dominant cause distribution is known; generic "JPEG failed" is insufficient.
4. Each important cause is classified A/B/C/D with a technical justification.
5. If production code changed, the change is minimal, source-native/lossless, and has
   positive + negative tests.
6. Unsupported/ambiguous cases still fall back safely to reconstructed PNG or locator
   capture.
7. No paid/quota resource was consumed.
8. If production behavior changed, `note/08_comicdays.md` was synchronized.
9. Production Reviewer has no remaining `BLOCKING` findings.
10. The final report clearly states whether "mostly PNG" is a bug, an encoding/layout
    limitation, or a mixture of causes.

## 9. Final report format

Leader reports:

- target URL;
- phases executed;
- sample size;
- capture-mode counts before changes;
- JPEG source facts (SOF, dimensions, components, sampling);
- fallback reason counts;
- A/B/C/D classification by cause;
- production files changed, if any;
- tests and results;
- live verification and capture-mode counts after changes, if any;
- Reviewer findings/resolution, if production changed;
- known remaining PNG cases and why they remain PNG;
- any verification not performed and why.

# Stage 02 checkpoint — 2026-10-08

Status: **COMPLETE / NO PRODUCTION CHANGE**. Authority is [README.md](README.md).

This checkpoint preserves the useful evidence from the earlier heavier workflow while
making clear that Reviewer/Critic are no longer required for ordinary research.

## Final Lead decision

| Investigated case | Final classification | Evidence and remaining boundary |
| --- | --- | --- |
| Manga cover | A, historical control | No fresh cover regression is claimed |
| Manga ordinary body, representative `9/159` | D | Two exact upstream tile JPEGs; complete selected-visible-output and 848-to-844 edge/crop/padding/reconstruction proof missing |
| LN `2/314` | D | Native 1443x2048 output obtained, but exact selected-canvas to upstream bitmap identity/geometry missing |
| LN `3/314` | D, unsupported JPEG recovery | Unique exact upstream JPEG; tile reordering plus bottom-three-row clipping reproduces native output exactly; coefficient-level JPEG recovery unverified |

No B artifact recovery contract or C/source-PNG case was established. The
source-native priority and all production proof/fail-closed gates remain
unchanged. Exact upstream JPEG/bitmap equality alone is not a finished-page
artifact proof, and PNG output alone is not source-PNG evidence.

The initial closure retained native/rendered fallback while edge/output proof
was missing. The user's size/crop question then prompted the single-page image
audit below, which resolved that boundary for LN `3/314`. That case is now a
concrete recovery candidate, but no coefficient-level JPEG artifact has been
verified and no production contract is changed. Further live samples are not
needed to answer this image question; any next LN `3/314` work can start with
offline JPEG recovery from the proven mapping. Manga's missing proof and LN
`2/314`'s unjoined source canvas remain separate questions. Manga 2 was not used.
Uninvestigated LN opening pages
`4/314` through `7/314` retain their historical D status without new claims.

Only Lead + Worker participated. Reviewer was not needed because no production
or durable test/diagnostic contract changed. Critic was not triggered: no gate
was weakened, no heuristic attribution was adopted, and no cross-title or
shared abstraction was proposed.

Final verification: metadata-only live research at manga `9/159` (R6/R7), LN
`2/314` and `3/314`, followed by one LN `3/314` image audit saved only under
ignored `output/`; verified restoration to `1/159` or `1/314` after each
independent probe. Production regression/END/full-book live runs were not
required or claimed. Cleanup retains thread limit 2 and the corrected note
scope. Final local artifact identities and checks are recorded below.

## Baseline synchronization completed (not research evidence)

- Continued on `research/bookwalker-source-native-20261005` in the existing worktree.
- Initial local HEAD: `0209a8791a3d2bc7b11b0bff8018a7c039a24b8c`.
- Fetched `origin`; current `origin/main` was
  `96fd5fff84567a4e2c644978d2b4c297174fa2ca`.
- Merged that main baseline, then preserved the remote research branch's preflight
  documentation through `7d199d6`. Resulting baseline HEAD:
  `ef956698f92d30441a71be785b6bb5ac874011a5`.
- Both merges completed without conflicts. Stage 02 README/checkpoint and the
  BookWalker note remained present. Main's packaging/status documentation was
  retained; no BookWalker production Python change arrived through these merges.
- The unrelated untracked `debug.log` was left untouched; its before/after SHA-256
  was `13195f4a9302dee588b1705b9d691d4d1999b91505cfecedc70196edbc3db489`.

These SHAs record this execution, not a pinned main requirement for a future run.

## Post-login continuation — accepted manga findings

The user corrected the login state and requested resumption. A new fetch found
the same current `origin/main`; merging it again reported already up to date.
The existing branch and unrelated `debug.log` were preserved. The access block
below is historical and no longer prevents the bounded research.

Manga R6 observed only `9/159` as the ordinary-body sample: actual entry/anchor
`1/159`, navigation `1 -> 3 -> 5 -> 7 -> 9`, observation start/end `9/159`,
and verified restoration to `1/159`. It recorded two 844x1200 native canvas
sources and full-frame, identity-transform renderer draws scaled to 998x1416.
Its dimension-ranked 848x1200 JPEGs were **not** candidate attribution evidence.
The legacy transform helper discarded its initial trace after initialization;
its empty trace and `PART_MAPPING_AMBIGUOUS` are collector limitations, not a
proven site ambiguity. R6's earlier cover-only attempt is excluded from body
evidence and is not a fresh cover regression.

R7 repeated the same spread with the corrected lifecycle: verify `1/159`, arm
native capture before the final `7/159 -> 9/159` turn, snapshot before any
trace-clearing capture/comparison, then restore and verify `1/159`.

- The production trace contained 4,133 observed operations; exact compact fetch
  returned both requested mapping IDs, with zero missing mappings.
- Renderer canvas 3 drew source canvas 6 at 844x1200 through exact completed
  mappings `mapping-3092` / `mapping-4124` and renderer operations 3092 / 4124.
- Each mapping contained 1,026 tiles. Its unique ImageBitmap source was 23 / 25,
  respectively, both 848x1200. Identity transform, source-over and filter none
  were observed in both the tile and renderer draws. No rotation is inferred
  from dimensions.
- The renderer used full source rectangles `(0,0,844,1200)` and destinations
  `(1430,0,998,1416)` / `(432,0,998,1416)`: a display scale is explicit.
- Existing `imagebitmap_pixel_exact_match` compared full decoded pixels without
  resize against 19 candidates per source. All 19 comparisons per source were
  available; exactly one JPEG matched each bitmap. This proves upstream tile
  JPEG attribution within the observed bounded candidate pool, not a complete
  page artifact or an original finished-page JPEG.
- A separate 400x1 HTMLImageElement was drawn to `(1230,1416,400,2)` outside
  the two body rectangles. It is not evidence of composition inside the body.
- The production selector retained a third transition geometry box and returned
  no capture. The diagnostic's two mapping-bearing calls are upstream evidence,
  not a substitute for successful production visible-page selection. A default
  `returned_path=native_png` debug field with zero captures is not PNG success.

Lead classification: **D / unsupported or incomplete artifact proof**. JPEG
source identity is now established, but complete selected-visible-output proof
and the 848-to-844 partial-edge/crop/padding correspondence remain unproven for
safe source-native recovery. No B artifact contract or C/source-PNG conclusion
is adopted. R5's 38 destination-edge clips remain historical evidence; they
must not be silently counted as a fresh R7 measurement.

No further manga live sample is warranted in this stage: fixing the transition
box alone would not establish the missing edge/padding and reconstruction
proof. A new partial-edge recovery contract would go beyond the bounded
attribution question. Manga 2 remains unused because no safe new recovery
pattern was established that needs cross-title confirmation.

## Post-login continuation — LN `2/314`

Actual entry was `3/314`, not an assumed page 1. Worker explicitly returned to
and verified `1/314`, probed `2/314` only, then returned to and verified `1/314`.

- The production selector chose one draw on renderer canvas 3 (2861x1418).
  Its source was canvas 4 at 1443x2048, full source rectangle
  `(0,0,1443,2048)`, destination `(931,0,1000,1416)`, identity transform,
  alpha 1, source-over and filter none. Display scale is explicit. No upstream
  rotation or padding interpretation is inferred from dimensions.
- The selected renderer operation was 2946, but `mappingId` was absent and
  `completedMappings` was empty. The trace was not generally empty: it recorded
  2,960 operations / 2,956 draws / one clear. This bounded production trace did
  not establish upstream bitmap identity or geometry for the selected draw.
  It does not prove that the site has no upstream lineage.
- Production returned one native PNG at 1443x2048 and the reconstruction path
  failed closed with `selected renderer draw mapping identity unavailable`.
- Seven JPEG candidates were compared against that returned native PNG without
  resizing. None was exact; the sole same-dimension candidate was not exact.
  This comparison is against the visible native output, **not** the previously
  observed 1448x2048 bitmap. The historical full-pixel bitmap/JPEG match is not
  contradicted or promoted into visible-output proof by this result.

Lead classification: **D**. The missing evidence is the exact selected-canvas
to upstream-bitmap mapping, including source/destination rectangles and
crop/padding/composition, followed by complete candidate-to-page attribution.
The current PNG remains a fail-closed native output; no source-PNG claim is made.

## Post-login continuation — LN `3/314`

Actual entry was `2/314`. Worker explicitly restored/verified `1/314`, navigated
through `2/314` to observe only `3/314`, then returned via `2/314` and verified
`1/314`. No previous end position was assumed.

- The production selector accepted one geometry box. Renderer canvas 1
  (2861x1418) used exact mapping `mapping-8852`, renderer operation 8852, source
  canvas 4 at 2048x1453, full rectangle `(0,0,2048,1453)` and destination
  `(431,0,1999,1416)`. Transform was identity, alpha 1, source-over, filter none.
- The selected completed segment contained 2,944 tiles from ImageBitmap source 7
  at 2048x1456. Clear operation 5903, tile operations 5908-8851 and renderer
  operation 8852 establish the observed ordering. Tile transform was also
  identity with source-over/filter none; no rotation is inferred from a
  width/height swap.
- The trace contained 8,860 operations. Exact compact fetch returned one
  requested mapping, with zero missing mappings, no reported trace overflow and
  no completed-mapping eviction.
- Full decoded-pixel comparison without resize against eight candidates was
  available for all eight and found exactly one JPEG matching ImageBitmap 7.
- Production returned one native PNG at 2048x1453. The mapping validator rejected
  reconstruction with `ImageBitmap dimensions differ from source canvas`.
  Eight JPEG candidates had zero exact matches against this native PNG, a
  separate comparison from the successful upstream bitmap match.

Initial R7 Lead classification: **D**. Selected mapping and unique upstream JPEG
identity were established, while edge coverage and complete output proof were
still missing. The image audit below supersedes those missing-output claims;
safe encoded JPEG recovery remains unverified. No source-PNG claim is adopted.

## Follow-up image audit — LN `3/314`

The user's question about the small dimension difference warranted one direct
image comparison instead of treating the initial stopping decision as final.
The branch was fetched and merged with current `origin/main` again (already
up to date at the baseline above). This synchronization is not research evidence.
Worker observed actual entry `2/314`, explicitly verified anchor `1/314`, visited
only target `3/314` via `2/314`, and restored/verified `1/314` afterward.

- Renderer selected source canvas 4 (2048x1453), full source rectangle,
  destination `(431,0,1999,1416)`, mapping `mapping-5896`. The upstream JPEG
  hash is `c6eade9c2c94d7dd7c47eb630a08765e88e1c4765f848400ac116cd11b6e0555`,
  matching the exact R7 candidate. In this new window, full-pixel comparison
  against the retained selected-mapping source object 7 was available for all
  eight candidates and again found exactly one match. IDs are window-local.
- Direct inspection of the raw 2048x1456 JPEG shows scrambled image tiles, not
  a readable page. Cropping it at vertical offsets 0, 1, 2 or 3 does not match
  the native output; approximately 99.5% of pixels differ in each comparison.
- The recorded 2,944 source rectangles cover the full encoded image. Tiles are
  32x32 or 32x16 and are copied without tile resizing/rotation. Replaying the
  exact source/destination rectangles into a 2048x1453 image fills every pixel
  once, with no holes or overlaps. It matches the native PNG at **zero differing
  pixels**. This is diagnostic RGB reconstruction, not a JPEG re-encode or a
  supported production recovery implementation.
- Clipping occurs at the **reconstructed page's bottom edge**, zero-based rows
  1453–1455 across its full 2048-pixel width. Sixty-four destination tiles cross
  that boundary. Because the JPEG is scrambled, their omitted source fragments
  are scattered through the raw JPEG; this is not simply its bottom-three-row
  crop. The visible output has no missing coverage or inserted padding.
- The JPEG has RGB 4:4:4 sampling. Every source/destination tile coordinate and
  dimension is divisible by eight. This is promising for coefficient reordering,
  but does not itself verify a recovered JPEG, its quantization/layout, or the
  final partial-MCU crop. The production uniform-tile/same-dimension contract
  has not been broadened.

Local evidence: `output/stage02-ln3-image-audit-20261008/audit.json`, SHA-256
`64443bbe278980c443309eeaf46ef62f1a662dc1bd846b0fb3770e264912e697`.
Raw JPEG, native PNG, complete selected tile metadata, full 2048x1456 RGB
reconstruction and bottom-edge strip are ignored research artifacts in that
directory. Image hashes and source-object comparison metadata are in the audit.
PASS: reconstruction/coverage assertions, restored anchor, image hashes,
unrelated `debug.log` hash preservation and `git diff --check`. No production
or test code changed; Unit/Integration/full pytest were not run for this follow-up.

Thus the uniquely attributed JPEG is the right **input for recovery**, but
saving its original bytes directly would save the scrambled transport image.
The current fallback is an implementation-support boundary, not evidence that
this page's source format is PNG or that a three-pixel difference makes JPEG
recovery inherently invalid. A next recovery investigation should preserve the
JPEG coefficients while handling the observed nonuniform tiles and final crop;
it must verify the recovered artifact before adopting B. No production gate was
weakened, and no Reviewer/Critic was required for this image-only research.

## Final checks and artifact identities

The live helpers reused production selection, compact mapping, candidate and
full-resolution comparison mechanisms where available. R6's legacy empty trace
was excluded and replaced by the corrected R7 lifecycle. No diagnostic was
promoted into a supported production or test contract. Artifact hashes identify
local metadata; relevant observations are recorded above so a fresh clone need
not contain the ignored files. Mapping/source IDs are capture-window-local.

PASS: final JSON parsing, report SHA-256 consistency, final D fields, anchor
restoration fields, thread-limit-2 TOML parsing and `git diff --check`. The
earlier Ruff PASS below applies to the same unchanged `src`/`tests` baseline.
No pytest was invoked (zero pytest skips). Unit, browser-backed Integration and
full suite were not rerun because production and tests were unchanged. Research
trust checks were the actual-counter/anchor protocol, corrected snapshot order,
nonempty trace/exact mapping checks where available, production selector result,
existing full-pixel comparisons, and metadata/hash consistency checks. No new
synthetic producer matrix or full viewer reverse engineering was attempted.

No image bytes, signed URLs, credentials, Cookie or storage state were committed.
The remote Chrome/profile was preserved. `debug.log` remains unrelated user data.

| Metadata-only local artifact | Final SHA-256 |
| --- | --- |
| `output/stage02-manga1-r6-summary-20261008.json` | `561423769fb7b8a1f96ebf548c27151e040309a002e7e48232f6c436bb1cdb03` |
| `output/stage02-manga1-r7-summary-20261008.json` | `a549bc41bf9117725f695ea9d74ec962106c5cd727643014b4901089a66c8d94` |
| `output/stage02-ln2-r7-summary-20261008.json` | `ea84e876e5d2720310372697aa105c8ef7dd72fcaba88f607dc7fd8a822cbabf` |
| `output/stage02-ln3-r7-summary-20261008.json` | `d75461cfec7ba214f8c7f9cf9d7602bbdbe22a7c004b4cf20bd89edf46dabe8b` |
| `output/stage02-offline-audit-20261008.json` | `e5acc0ff66a94e7d6d856fb0fa76ac56f675a66268f23488353e979023eb9002` |

The final audit adds Lead's D decision to the manga R7 metadata; its earlier
upstream-only B-candidate wording is explicitly superseded. R7 manga edge-clip
count, full tile-coverage bounds, overflow and eviction fields were not retained
in the local metadata summary and remain unreported. Do not infer their values
from R5 or from a successful two-record compact fetch. The earlier LN2 hash was
superseded by the offline evidence-separation clarification; final hashes above
identify the accepted metadata versions.

## 2026-10-08 access-only precheck (historical; resolved before R6/R7)

The Lead selected one fresh manga question: can the selected ordinary-body bitmap
at `9/159` be attributed one-to-one to an exact upstream encoded source? The
Worker could not reach that anchor. No fresh source/geometry/pixel probe ran.

- Initial manga `direct` entry reached a login form; an `auto` attempt also failed
  to reach a ready viewer. A quota control lookup found no matching maruyomi
  control and did not click a resource control. These attempts are access
  observations only, not provenance probes or a supported fallback strategy.
- Configured email/password presence was true. The existing login-form helper
  submitted once in a dedicated new Page, observed a viewer destination and
  disappearing login form, then closed only that Page. No credential value,
  Cookie, storage state, or signed viewer URL is recorded here.
  An initial helper invocation could not find the home-page login button and
  submitted no form; the subsequent visible member-form submission was the
  single actual login submission.
- After login, manga strict-direct control kinds were `trial`, `unknown`, and
  `generic_reader`; no `owned` control was available, so no direct click ran.
- The independent LN strict-direct precheck observed `generic_reader`, `maruyomi`,
  `subscription`, and `unknown`; no `owned` control was available and no direct
  click ran. There was no quota/auto/trial switch for LN.
- No quota control was clicked and no resource consumption was reported. The
  cause of missing owned controls and the current account's entitlement are not
  proven by these observations.
- Actual reader counters, start/end positions, and anchor restoration were
  unavailable for both targets. No fresh `1/159`, `9/159`, `1/314`, `2/314`, or
  `3/314` position is claimed.
- The Lead requested that the user make the intended account available in the
  shared Crawler Chrome. Live operations then stopped to avoid competing with
  manual login. No new viewer/probe helper, fixture, or production code was added.

The Worker confirmed the CDP endpoint at `http://127.0.0.1:9222` and the Chrome
process's repository `.chrome-crawler` profile. Each access attempt used and
closed a dedicated Page; remote Chrome remained running. The metadata-only local
report `output/stage02-access-precheck-20261008.json` has SHA-256
`cc0507be54346bed35b108eef08a3614ffd57ac38a4e71f33128b575b0547997`.
It records the seven entry/login attempts without image bytes or secrets. Its
structural observations are summarized above so the ignored local report is
not required to understand this checkpoint.

At this precheck, Stage 02 was **not complete**. Access failure did not establish
D. Classification was retained from the historical evidence below; the later
R7 attribution above supersedes the manga's missing-upstream-source statement:

| Case | Retained classification | Still missing |
| --- | --- | --- |
| Manga cover | A (historical) | No fresh regression claim |
| Manga ordinary body | D | Exact encoded JPEG/PNG attribution and complete source/output proof |
| LN `2/314` | D | Exact selected-output lineage from the all-pixel-matched 1448x2048 JPEG/bitmap |
| LN `3/314` | D | Exact selected-output lineage, crop/padding/coded mapping and complete visible-output proof |

At this precheck, manga 2 remained unused and research stopped for target access,
not because further provenance research had been judged unproductive.

## Checks and cleanup before the post-login probes

- PASS: `.codex/config.toml` parses with `tomllib`; spawned-thread limit is 2.
- PASS: `.venv/Scripts/ruff.exe check src tests`.
- PASS: `git diff --check` after the merges and documentation/cleanup changes.
- Production Unit/Integration/full pytest were not rerun: this continuation
  changed documentation and the research thread cap only, with no production or
  durable diagnostic/test contract change. No pytest skips occurred because
  pytest was not invoked. Fresh provenance Live verification remains unexecuted;
  only the access checks above ran. Old Stage 01 test counts are historical.
- Restored `max_concurrent_threads_per_session = 2`; no reason remains to retain 4.
- Replaced the BookWalker note's universal PNG-saving scope, dedupe and packaging
  wording with the current original/reconstructed JPEG, source/native PNG and
  rendered fallback behavior.
- Reviewer/Critic were not invoked: no production change, proof-gate change,
  heuristic attribution, or broader generalization was proposed.

## Precheck resume instruction (subsequently followed)

After the intended account can open the targets in the shared Crawler Chrome,
Worker must recheck actual counters and strict access. Do not assume the login
Page's viewer destination was either research target. Resume the single
`9/159` manga spread question first; classify its evidence before deciding on a
second spread. Then probe LN `2/314`, inspect the result, and only then select
the bounded `3/314` question. Do not rerun credentials or choose another resource
merely to bypass the missing owned control.

## Historical Stage 01 / R5 evidence

- Production capture code remains unchanged.
- Stage 01 cover A and ordinary LN-text A evidence remain historical controls.
- Manga ordinary body remains D.
- LN opening remains D.
- Manga 2 has not been used.

Historical manga R5:

- actual initial position was `9/159`;
- Worker rewound and verified `1/159`;
- captured `1/159`, `3/159`, `5/159`, `7/159`, `9/159`;
- ended at `9/159`;
- restored and verified `1/159`;
- at `9/159`, two selected native PNG artifacts were 844x1200;
- selected lineage had two 1,026-tile mappings with 38 destination-edge clips each;
- exact encoded-source attribution was not proven;
- inventory contained only 158x224 JPEG thumbnails among eligible observed JPEGs.

R5 establishes bounded native lineage, not source-PNG authority or reconstructable JPEG
proof.

Its first capture used rendered fallback and is not a fresh cover-A regression pass.

## Previous diagnostic work

OBJECT-A and related local diagnostic files were developed under the previous workflow.

They were not fully reviewed and are **not production/source-format authority**.

They may be:

- reused if Lead decides they directly answer a concrete bounded question;
- ignored or retired if a simpler direct probe is more efficient.

There is no requirement to finish OBJECT-B/C or a synthetic producer matrix.

The earlier agent-thread-capacity problem no longer blocks research because normal
research now uses only Lead + Worker.

## Historical workflow-revision resume order (superseded by completion)

1. Continue on `research/bookwalker-source-native-20261005`; do not create a replacement
   branch just because `main` has advanced.
2. Fetch `origin` and merge the current `origin/main` into this branch before new
   live research or production edits. Preserve both newer main behavior and this
   checkpoint/runbook evidence when resolving conflicts.
3. Lead reads this checkpoint and the current Stage 02 README after the merge.
4. Do **not** restore Reviewer/Critic merely to satisfy the old gate sequence.
5. Pick the smallest direct unresolved manga or LN provenance question.
6. Worker performs one bounded probe.
7. Lead classifies the result A/B/C/D or asks one more bounded question.
8. Stop research when another probe is unlikely to change the operational decision.
9. If production code is implemented, invoke Reviewer.
10. Invoke Critic only if a material risk trigger in the README applies.

## Local ignored artifacts

The following hashes identify earlier local files but do not make them repository
authority:

| Local file | SHA-256 |
| --- | --- |
| `output/stage02_manga_provenance_probe.py` | `95a8c17d3801022ba2e797c69d94f1249942edf0a3351073a5e93a2514ccc634` |
| `output/stage02_create_image_bitmap_synthetic_browser_check.py` | `2174c62fb749daf425ffb1aae5ae8aa1d46aa75cf4df59cdec023549d65253af` |
| `output/stage02_create_image_bitmap_observer.py` | `c5aab98c6584b5f6d1c1439d7523503a3322f592500e08218046df1cf64c5517` |
| `output/stage02-manga-ledger/create-image-bitmap-synthetic-evidence.json` | `644d29f3fc885bc0294d699d54067b33cb0da6c397e74332632d96fcc90d2fc7` |

A fresh clone need not reproduce or complete these files unless Lead explicitly chooses
that route.

# 11. Younganimal current implementation

## Current verification snapshot (2026-10-11)

Full live Discovery passed all 31 ranges and 925 positions with a 3000 ms
harness override; the production default was set to 3000 ms after that run.
Its isolated Catalog has 925 Items/Sources/Targets, 0 Runs/Artifacts, and 3
exact-free rows; the other 922 remain UNKNOWN, not paid.

Attempt 9 passed both final-code live free-work runs. The standard target
captured 16/16 pages as native VP8L across 9 spreads; the top-empty target
captured 44/44 pages as native VP8L across 22 spreads. Both reached Runner END,
passed ZIP and isolated Catalog audits, and preserved source fingerprints. The
top-empty audit confirms physical slots 2-45, 44 CRC-valid members, and one
completed isolated Catalog item/artifact; seven earlier failed attempts remain
in the isolated Catalog history. The standard target completed one item. Reports:
`output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/provided-free/audit.json`
and `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/topempty-free/audit.json`.

Earlier attempts 7 and 8 remain historical: attempt 7's top-empty portion timed
out before capture;
attempt 8 reached the exact episode with HTTP 200 and failed closed at native
post-encoding verification before saving a page. Its selected body proof fields
matched, but the exact failed subcondition is not attributed beyond the stored
`native_reader_layout_changed` reason. Attempt 8's audit is
`output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-8/topempty-free/offline-final-audit.json`.

The final capture-epoch rule exempts only observed ordinary `class` mutations
on the exact nested CI scroll widget: same-token-set no-ops in its two known
states, and the observed base-to-`mode-scroll-bottom` transition when finite
raw geometry proves the widget/CI is offscreen or disjoint from every active
body wrapper/canvas. Missing or ambiguous geometry and overlap fail closed.
The raw global DOM epoch still counts every observed mutation. Candidate,
selected-page, post-encode, frozen-mapping, pixel, END, atomic-spread, and
cleanup gates remain unchanged. The current revision passed independent review
and the latest affected local suite; see the current progress checkpoint.

The reviewed initial UI settle waits until the read-only viewer `mode-nav-open`
state is false and the `.-cv-splash` count is zero, then requires the existing
one-second stable canvas/capture-epoch quiet interval within the same five-second
deadline. Reappearing UI resets that interval. Missing or malformed metadata
and non-settling UI fail closed before collection. Native selection,
post-encoding verification, D fallback, and the frozen viewer mapping remain
unchanged. The raw global DOM epoch remains available for diagnostics while
capture stability uses a separate epoch. The final-code top-empty live pass
reached END for all 44 pages after this settle and CI-widget proof rule.

The preceding diagnostics iteration added a bounded YA mutation journal and
typed native failure metadata: expected/observed seek, route, DOM epoch, viewer
node identities, wrapper count, selected canvas identity/generation/write,
dimensions, rectangles, readiness/context, and pixel/replay equality when safe.
Pixel diagnostics run only for the exact selected target, wrapper, holder, and
proof dimensions within the existing per-canvas pixel bound; otherwise those
readbacks are explicitly unavailable. Rectangle predicates use unrounded DOM
coordinates, while serialized coordinates remain rounded. The journal holds at
most 64 safe class/id/child-list records. DOM generation advances by the full
MutationObserver batch before diagnostic summarization; a per-record summary
failure is contained, later records continue, and the report marks coverage
incomplete with an unrecorded count. Overflow also reports incomplete coverage.
URL query/hash values, HTML, arbitrary text, image bytes, and full RGBA buffers
are excluded. The reviewed capture-epoch implementation retains these bounds
and adds the narrow CI rule summarized above. Attempt 9 exercised this final
revision on both live profiles: the 16-page standard target and the 44-page
top-empty target.

## Registration and crawl entry

The CLI registers Younganimal for Discovery, manual Crawl, Batch adapter, and
Batch Site Policy. All paths use the repository's shared CDP BrowserSession and
Playwright Page; the adapter does not launch Chrome or select a profile. The
policy selects only currently available sources with `access_mode=free`; the
configured Batch adapter requires direct strategy and a strict work/episode
external identity. No shared Core or Catalog schema changes were made.

Manual Crawl requires:
- source URL: the exact canonical episode URL, for example
  https://younganimal.com/episodes/55889b8a851cb
- environment value YOUNGANIMAL_WORK_URL:
  https://younganimal.com/series/&lt;13-lowercase-hex-work-id&gt;

The configured work listing is the initial navigation route. The episode URL stays
the source URL in the output manifest. Missing or mismatched work configuration,
malformed episode routes, or non-auto access strategy fails before unsafe entry.
The site adapter visits numeric ranges in the configured listing with a 3-second
delay, validates each visited range, and stops after finding the exact target row.
This manual path does not require all 925 rows to be enumerated. Before entering
the episode it requires one row-scoped exact 無料 label; after entry it repeats
the exact route, same-work, unique-row, and exact-label checks against the embedded
public listing. It performs no login, wait, ticket, coin, point, purchase, grant,
or next-episode action.

## Discovery

Discovery accepts only a canonical first-party series URL matching
https://younganimal.com/series/<13-lowercase-hex-work-id>. Episode seeds are
rejected before AccessGuard startup/navigation because a row's free label has not
been proven. Episode URL parsing remains available for public row identities and
bounded-scope boundaries. This is a Lead-approved safety deviation from the
original episode-seed plan; the work ID from the supplied target is an example,
not an allowlist.

The Discovery adapter validates the canonical work title and buffers the complete
declared range map before yielding. It checks each route against the same range
map, declared row count, unique episode IDs, and first-party canonical URLs.
Output order is latest-first while global display positions remain the
oldest-first whole-work indices. Inclusive bounded scopes retain global positions.
A nonempty epListUser history root is rejected because same-ID title/access
consistency has not been established. The observed 最新話から control is accepted
only at the same-work /new path. An optional ... placeholder is ignored only when
the raw anchor has no href; unknown controls and route changes fail closed.

One exact row-local 無料 label maps to free. 今なら無料, 待つと無料, blank,
repeated, conflicting, and unrecognized labels remain unknown. Authentication is
unknown and not inferred. Full Discovery buffers before yielding, so an incomplete
traversal cannot mark unseen sources unavailable. Maximums are 100 ranges and
3,000 rows.

Discovery waits 3 seconds before every numeric range route. A Playwright
DOMContentLoaded timeout is retried only when the exact current attempt proves one
matching main-frame document request and its matching response is HTTP 200, and
the current route remains exact after the timeout and again after a 2-second
backoff plus AccessGuard check. There is at most one retry per route and two
retries per work. Unknown response evidence, non-200, redirect/drift, other
Playwright errors, and access stops are not retried. Request/response listeners
are removed on every path, and no response body or retry header is read. The
earlier /3 timeout cause remains unknown; this recovery does not assign a cause.
AccessGuard cleanup is bounded.

## Viewer layout and capture

A metadata-only direct target probe, after a fresh exact-free listing proof,
returned HTTP 200 at the supplied episode route. The embedded public row proved
one exact target route, work aee4fa742b0fe, and exact label 無料. The report is
ignored at
output/younganimal_experiment/phase03a_viewer_probe_20261011_direct_target.json;
it contains metadata and in-page pixel digests, not page images, HTML, or response
bodies. The reported prior-listing-age value is invalid because it mixed a
monotonic timestamp with file modification time; age is UNKNOWN.

Observed viewer contract in that probe:
- unique #comici-viewer, #xCVSeekBar, and #xCVPages;
- 22 direct physical wrappers; public seek min=1, max=21, step=2;
- physical slot 0 is the exact mode-empty/mode-pr/mode-top-pr lead-in with no
  canvas; body slots 1–16 are contiguous; tail roles are CI at 17, empty PR at
  18–19, Good at 20, and Last at 21;
- public seek values 21,19,…,1 were observed. A resumed value was rewound to 21
  using the public control. At minimum seek 1, #xCVLastPage was visible in slot 21;
- body canvas bitmaps sampled in the probe were 984×1329, with 656×886 CSS bounds.
  The first-state source trace also saw WebP transport images at 960×1297 and
  960×1296 intermediate tiled draws. It did not link those responses to individual
  body slots or prove original-byte/pixel reconstruction.

The resource summary also lists api-ai.comici.jp image responses. They are
treated as tracking/pixel traffic, not body-source evidence, and that host is
excluded from the Younganimal AccessGuard relevant-host profile. The profile
includes the observed site, viewer-image, and public-content image hosts.

The initial probe's same_candidate_identity field compared slot/canvas IDs and
indices; it did not prove JavaScript object identity, mutation generation, or
write continuity. Its body_continuity_proven and end_semantics_proven flags are
false because that diagnostic did not assert those contracts. Attempt 9 later
verified the production Runner's strict mapping, ordered body capture, native
output, and terminal checks on both final-code profiles.

The live sample has 22 wrappers and 16 body slots, but the adapter does not fix
that count. It validates the exact observed lead/tail role classes and their
positions, then derives the contiguous body interval and requires the public
seek range to match the physical wrapper count. A second exact-free work exposed a distinct top-empty profile. Its observed sample had 51 wrappers and seek 1..51 by 2. The root flag `mode-has-top-emptypage` is required; in that sample, slot 0 was the exact lead-in, slot 1 the centered `-cv-page mode-empty` wrapper with no canvas, body slots were 2..45, and tail roles were CI 46, PR 47-48, Good 49, Last 50. At max seek 51, first/top-PR flags accompanied the centered blank. One public step to 49 centered body slots 2 and 3 and cleared those transient flags. This bounded evidence is in `output/younganimal_experiment/blank_variant_probe/blank_wrapper_probe_20261011.json`. It did not test terminal seek, a full 44-page crawl, native capture, or a challenge detector. The production parser does not allowlist 51: it accepts the dynamic profile only with the positive root flag, exact lead/blank/tail roles, contiguous derived body interval, and `min=1`, `step=2`, `max=wrapper_count` relation. Other wrapper totals for the standard profile have not been individually verified live. No generic blank skip is inferred. Unrecognized wrapper classes, interior gaps,
changed range/route, duplicate canvas candidates, unreadable pixels, and
incomplete spreads fail closed. It rewinds any resumed public seek to the maximum and
requires the first body canvas to stay unchanged for 1 second within a 5-second
bound. Before that interval starts, typed read-only metadata must show the viewer
navigation panel closed and no `.-cv-splash` nodes. Reappearing UI resets the
interval; malformed metadata or UI that remains active through the same deadline
fails closed. Capture stability uses a separate epoch; raw global DOM
generation remains available in diagnostics. Subsequent seeks use the public range value with ordinary
input/change events. After all body slots are captured it seeks to the minimum and reports END
only when the unique Last marker is visible and no body wrapper center is in view.

The top-empty profile's slot 1 is a non-body initial blank and is skipped only after max-seek structural proof and one public seek step to `max - step`; both first body slots must be ready. Known temporary body classes (`-cv-page`, `mode-loading`, `mode-loading mode-req-render`, `mode-loaded`, and `mode-loaded mode-rendered`) remain structural states only. An active blank/loading body cannot be captured. Unknown wrappers fail closed.

The adapter prefers verified C source-native pixels when every active half has a
supported full-frame draw candidate. The observer copies the source canvas into a
private immutable canvas at draw time, then replays the source-to-target draw using
runtime dimensions and captured smoothing/context state. It selects the native
snapshot only when replay RGBA exactly matches the active body canvas and the full
strict Python viewer parser validates the current spread against the frozen
body/tail mapping, layout variant, and seek bounds recorded at initialization.
A single-use post-Python proof binds the route, viewer/wrapper/canvas nodes, physical slot, seek, dimensions,
generation/write counts, layout, readiness and pixels. Unsupported, clipped,
incomplete, over-bound or mismatched candidates fall back for the whole active
spread to D. Any mutation after native selection fails with UnknownPageStateError.
PNG encoding and hashing stay outside the draw hook. Verified native PNG is
converted to VP8L WebP only when the decoded RGBA is identical; otherwise the same
verified PNG is retained. Candidate and proof references are bounded. A failed or
cancelled selection clears the bounded window even when Python did not receive its
token; successful cleanup releases only the selected slots so later draw-time
candidates remain available. Rendered observations and native pre/post proofs all
retain the frozen mapping.

D rendered body-canvas PNG remains the atomic fallback. A document-start observer
records canvas object IDs, dimensions, Canvas 2D writes, dimension resets, viewer
mutations, and RGBA fingerprints. One synchronous capture retains actual DOM
references and checks route, seek, roles, dimensions, generation/write counters,
layout, and pixels. Python decodes every PNG and checks its RGBA fingerprint
against the in-page readback. Generic locator/screenshot fallback is disabled.
Neither path hard-codes Hanayume dimensions or wrapper arithmetic.

Bounded source attribution reports are ignored at
`output/younganimal_experiment/native_attribution_probe_20261011_retry2.json` and
`native_attribution_validation_20261011.json`. Slots 1, 8, 9, and 16 have sampled
draw-time snapshot/replay and selected target node/generation/write/layout/pixel
proof. For sampled first/middle paths, actual response bytes were WebP at
960×1297, tiled as sixteen 240×324 pieces into a 960×1296 intermediate, then
scaled to the 984×1329 body canvas. The nonidentity map and pixel difference rule
out saving those sampled response bytes as-is; JPEG DCT does not apply to those
WebP samples. Slot 16 response-byte attribution remains UNKNOWN. This is not an
all-page original-byte claim; no research image bodies were saved.

## Current verification status and remaining work

The final reviewed capture code passed the affected local suite: 84 passed,
0 skipped, 5 existing pytest-asyncio deprecation warnings in 133.19s.
`ruff check src tests` also passed. The separate read-only CLI review used a
SHA-snapshotted code view; it was not an independent test execution. No full
`pytest -q` run was performed because this remains a site-local adapter change.

Attempt 9 verified the final code on both live exact-free profiles: the standard
target captured all 16 pages as native VP8L over 9 spreads; the top-empty target
captured all 44 pages as native VP8L over 22 spreads. Both reached END, passed
independent ZIP/CRC, raw hash and decoded-RGBA audits, completed one isolated
Catalog item/artifact, and retained unchanged source fingerprints. The separate
reports are `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/provided-free/audit.json`
and `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/topempty-free/audit.json`;
the combined independent audit is `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-9/independent-final-audit.json`.
Attempts 7 and 8 remain historical incomplete attempts; attempt 6 used the
preceding geometry rule. None is substituted for attempt 9's final-code proof.

The independent 44-page synthetic Runner compares every native output against
fixture-source RGBA and verifies END/ZIP bytes. The current geometry contract
accepts same-state token-set no-ops on the exact nested CI widget, and the
observed base-to-`mode-scroll-bottom` transition only with positive finite proof
that the widget/CI is offscreen or geometrically disjoint from all active body
wrappers/canvases. Ambiguous/missing geometry and overlap fail closed. Attempt
8 does not prove that its slot-46 record satisfies this widget/geometry rule.
Global mutation accounting and all candidate, selected-page, post-encode, mapping,
layout, pixel, cleanup, and whole-spread gates remain intact.

Phase 02 full live Discovery and Phase 04 direct-only Batch are complete. Phase
06 free E2E is verified on both live profiles under the final code. Phase 05
remains UNKNOWN-only and unimplemented: both SVG icons on blank rows were
visible, but active-icon, wait/access, resource, and positive authentication
semantics were not established. Therefore the wait-free request is not
complete. No full-suite run was made; the final affected suite skipped 0.

## Historical native geometry diagnostic (2026-10-11)

A bounded diagnostic observed a same-size pure translation between draw and selection for slot 2: target x moved from -947.333 to 944.667, and the wrapper shared that displacement. Relative offset, actual node identities, dimensions, generation/write counters, paint state, exact replay pixels, readiness, visibility, and centering remained valid. The underlying CSS cause is UNKNOWN. The reviewed C change permits only that equal-size target/wrapper translation with unchanged relative offset at selection; all identity, generation/write, paint, source snapshot, replay, frozen mapping, and visibility gates remain. Post-encode verification still requires exact full rectangles and rejects any later movement. Synthetic browser tests prove two-half VP8L RGBA equality, whole-spread D fallback for size/relative-offset changes, and failure after post-encode movement. Any native coverage gain on other pages remains UNKNOWN until a later standard Runner audit.

## Historical failure-diagnostics iteration (2026-10-11)

The top-empty 44-page live attempt 3 failed at native postproof before any
page save. The exact failed proof subcondition was not retained by its Runner
harness, so it remains UNKNOWN. The local diagnostics-only change preserves the
static failure reason and a bounded expected/observed report for canonical
episode path (never query/hash values), seek, DOM epoch, node-reference
identity, wrapper count, active slots, viewport, selected canvas generation
and write values, dimensions, rectangles, and readiness/context. Pixel and
replay equality are read only for the exact proof target/wrapper/holder and
exact proof dimensions within the existing pixel bound; otherwise the booleans
are null. Rectangle equality uses raw DOM values before the reported
coordinates are rounded. A 64-record journal returns allowlisted target
area/node/slot, safe class flags or changed booleans, and bounded child/tag
summaries. Mutation generations advance for the entire observer batch before
summaries are attempted; a failed summary is contained, later records continue,
and missing coverage is explicit. Overflow also marks coverage incomplete.
Initial quiet metadata is retained through Runner exceptions. This earlier
iteration did not change capture gates and was not live-run.

## Historical capture-epoch implementation checkpoint (2026-10-11)

Top-empty Batch attempt 5 failed closed before saving a page. The isolated
report is `output/younganimal_experiment/phase04_batch_e2e_20261011/attempt-5/offline-final-audit.json`.
The provided-target 16-page Batch still passed with all pages native; the
top-empty first spread failed native postproof with global DOM epoch 682 to
684 and capture epoch 677 to 679. Both complete records were class mutations
associated with physical CI slot 46, but `canonicalCiWrapper=false` and
`canonicalCiClassNoop=false`. The prior attempt-4 interpretation that these
were CI-wrapper no-ops is withdrawn.

A separate one-capture bounded probe at
`output/younganimal_experiment/canonical_ci_role_probe_20261011/attempt-3/canonical-ci-role-probe-attempt-3.json`
observed an ordinary class assignment on a nested `DIV.-cv-ci-content`. Its
immediate parent was the sole-child `DIV.-cv-ci.-cv-page-content`, directly
under the canonical `DIV.-cv-page.mode-ci` wrapper; the target and wrapper
were wholly outside the viewport. The target's class changed only from
`{-cv-ci-content}` to `{-cv-ci-content, mode-scroll-bottom}`. The single probe
capture returned successfully, but it was not a Runner crawl or saved page.
Connecting that observed transition to attempt 5's failure is an inference
across separate attempts, not a directly recorded identity match.

The local, not-yet-reviewed change keeps the raw global DOM generation
incrementing for every observed mutation and adds a separate capture-stability
epoch. It exempts only an ordinary class mutation on the exact, offscreen,
sole-child nested CI widget under the canonical CI wrapper. Allowed token sets
are base-to-base, scroll-state-to-the-same-scroll-state, or base-to-scroll-state
using ASCII HTML whitespace tokenization. Reverse transitions, unknown tokens,
namespace or missing values, other ancestors or widgets, IDs, viewer changes,
and structure still advance the capture epoch. Candidate draw-to-selection
eligibility, global generation, native post-encode proof, Python quiet
signatures, rendered-D before/after checks, frozen mapping, node, generation /
write, layout, context, readiness, pixel proofs, and cleanup remain unchanged.

Synthetic browser coverage captures all 44 top-empty pages as native VP8L,
matches every decoded RGBA to independent fixture-source pixels, reaches END,
and verifies ZIP bytes. Twenty-two fixture verifications include the approved
CI serialization and widget transition; negatives cover unknown tokens,
reverse transition, non-CI lookalikes, reparenting/replacement/missing widget,
and namespace changes, with no save, locator fallback, or leaked proof.
Focused browser/unit selection passed 29 tests, 0 skipped, with 5 existing
pytest-asyncio warnings; the complete capture unit file passed 32 tests, 0
skipped, with 1 existing warning. Ruff, compileall, and `git diff --check`
passed. These are synthetic results. At this historical checkpoint, independent
review and another top-empty live run were pending; attempt 9's final-code
independent audits are recorded in the current verification snapshot above.

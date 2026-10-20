# 11. Younganimal current implementation

## Current verification snapshot (2026-10-20)

### No lead wrapper and no CI: Item/Source 35814

Normal Batch `0be4eb4073ce404ab5593b27b2486c70` failed before capture on
`07e91638d2a1b` / work `932cedf273921` (ナナとカオル Last Year / 最終話②).
Its N=17/max=17 structure was mistaken for the standard odd-body candidate;
the missing comic-info capability caused the reported readiness timeout.
The saved DOM and bounded shared-CDP probe instead prove no lead wrapper,
no CI wrapper, thirteen contiguous body slots 0-12, PR 13-14, Good 15, Last 16.
This is a structural mismatch, so a longer wait cannot resolve it.

`no_lead_no_ci` requires positive horizontal/spread/RTL and PR/Good flags,
absent top-empty/comic-info/vertical/single flags, exact canvas-free
PR/PR/Good/Last roles, contiguous known body classes, derived odd B=N-4>=5,
and range min=1/max=N/step=2. No episode IDs or wrapper totals are allowlisted.
Every phase and centered wrapper must match:

| Seek | Centered wrappers in the live B=13 sample | Phase/state |
|---|---|---|
| 17 | 0, 1 | first-only / two body pages |
| 15..7 by -2 | 2/3..10/11 | no phase flags / body pairs |
| 5 | 12, 13 | PR-only / final body plus first PR |
| 3 | 14, 15 | PR-only / PR plus Good, no body capture |
| 1 | 16 | Last-only / unique visible and centered Last |

Initialization and public rewind require both first body pages ready, followed
by the existing UI-settle/quiet proof. Physical slot identity starts at zero;
saved artifact sequence remains one-based. Python parsing and native layout
proof use the same body/tail map, range, phases and final centers. Native
draw-time observation alone permits pending CSS translation: the exact roles,
capabilities, seek and expected body slots must already match, while selection
and post-encoding proof still require every final wrapper center. The existing
source/target replay RGBA, retained node/write/epoch and equal-size wrapper/target
translation checks bind the incoming draw to the selected body. There is no CI
mutation exception for this profile. Frozen mapping, all-body coverage before
END, source replay/node/write/epoch proof, atomic rendered PNG fallback,
max_pages, timeouts and access rules remain unchanged. Other no-lead body
parities, tails and short layouts remain unsupported.

Evidence: `output/younganimal-fix-35814/metadata-probe.json` checks all nine
public seek states without pixel reads and restores the starting seek. The
initial layout-only fix still produced two native WebPs and eleven rendered
PNGs with `native_candidate_missing_or_stale`. The bounded read-only draw probe
`output/younganimal-native-35814/baseline-draw-probe.json` establishes why:
at seek 15 the incoming slots 2/3 draw while centers remain 0/1; at seek 13
slots 4/5 draw while centers remain 2/3. Centers settle correctly afterwards,
but the old unconditional draw-time center check discarded the candidates.
An artificial fixture with this order failed before the correction and now
passes source-native capture. Extending waits would not recover a missed draw.

Current direct production Runner verification on the existing grant is in
`output/younganimal-native-35814/verified/live-report.json` and
`live-manifest.json`: max_pages=13, all slots 0-12 captured in order through END
at seek 1, **13 native 960x1364 WebPs and zero rendered PNG fallbacks**.
A separate draw observer's source RGBA SHA-256 matches the decoded output for
every page; ZIP CRC, decode, manifest order, encoded hashes and dimensions pass.
The check proves draw-time source canvas pixels, not original response bytes.
One target main-document request, no checkout POST and no adapter ticket action
were observed. Normal Catalog and library were not modified; only the owned
Page was closed. A convenient copy is `output/younganimal-native-35814/35814-native.zip`,
SHA-256 `e3418a294152fa8ab77f28b8987b8669092dac12116674414aad6c0cea956817`.
This verifies Runner/capture/packaging, not a new Catalog completion or ticket
consumption. The first additional audit attempt stopped before saving pages
because its independent filter incorrectly excluded fractional destination sizes;
it is not a passing run. The corrected audit follows the existing subpixel
destination rule without changing production draw bounds. Natural site traffic
and site-side reading effects are not excluded.

Synthetic coverage extends the existing no-CI cases for all phases and missing
capabilities, changed roles/ranges/centers/Last markers. Browser coverage includes
B=5/B=13 native source RGBA and B=13 rendered fallback through END/ZIP, resumed
seek rewind to the first pair, and direct native collector rejection of drift.
No-CI fixtures now draw before repositioning, matching the live evidence. Both
no-CI variants additionally cover equal-size translation versus resizing/relative
drift, and post-encoding canvas replacement/seek changes that save no artifact.
The new structure adds no setting or CLI option. Existing completed mixed-format
archives are not rewritten by the code change; the verified replacement ZIP is
available at the isolated path above. The final capture Unit file passed 295
cases; affected browser Integration passed 76 cases (163 deselected) in 165.54
seconds, including both no-CI variants, native Runner spread families, geometry,
direct collector rejection and post-encoding failures. There were zero failed
or skipped tests; the browser run reported five existing pytest-asyncio
deprecation warnings. The earlier focused/geometry/postproof runs overlap these
final selections and are not additional unique cases. `ruff check src tests`
and scoped `git diff --check` passed. Full-suite and unrelated Research/Discovery
runs were not needed for this site-local native observer change. This verification
does not run a normal multi-candidate Batch or modify Catalog completion; it
deliberately uses isolated Runner/packaging output.

### Odd body plus three trailing PRs: Item/Source 35766

Normal Batch `7c508b7bf8ca4334bd6914847d1d9756` failed before capture on
`f6064d438ba06` (ナナとカオル / 第2話 交渉①) with
`PR/Good/Last tail roles changed`. The saved layout has 18 wrappers, no extra
initial blank, eleven bodies and three trailing PRs. The previous three-PR
detector required an odd wrapper count and max=N, so it missed this max=N-1
shape and fell through to the old two-PR tail check. Increasing the wait
cannot resolve that structural mismatch.

Bounded shared-CDP metadata report:
`output/younganimal-layout-35766-probe-20261020/report.json`. It reproduced the
old rejection through six seconds, checked every public seek and rewound to
17, blocked 32 mutating requests and attempted zero checkouts. Exact roles:
top PR 0, body 1-11, CI 12, PR 13-15, Good 16, Last 17.

| Seek | Centered wrappers | Phase | State |
|---|---|---|---|
| 17 | 0, 1 | first + top-PR | first body |
| 15..7 by -2 | 2/3..10/11 | none | body pairs |
| 5 | 12, 13 | CI + PR | CI + first PR |
| 3 | 14, 15 | PR | other PR pair |
| 1 | 16, 17 | Last + PR | Good + unique visible/centered Last |

`standard_three_pr_odd_body` is an explicit three-PR profile with no top-empty,
vertical or single flags, positive horizontal/spread/RTL and PR/CI/Good
capabilities, exact canvas-free lead/tail roles, and a contiguous known body
region. Derived B=N-7 is odd and at least three; min=1/max=N-1/step=2. Tail
recognition is independent of the subsequent validated seek/parity relation.
The CI phase is at P+2=5 and END has Last+PR flags and Good/Last centers,
distinct from the even-body three-PR profile's CI phase P+4=7 and Last-only
END. Python parsing, native JS layout proof and CI mutation geometry all use
this distinction. Odd-body single-PR, arbitrary PR counts, missing body/role
proof, wrong flags/ranges/centers, canvas changes and premature END still fail
closed. Existing top-empty and prior parity profiles retain their contracts;
no Core, resource, fallback, retry or production timeout policy was changed.

Unit tests cover all nine observed phases and capability/blank/range/body/
tail/canvas/CI/Last/center mutations. Browser fixtures extend the existing PR
tail Runner tests with B=11 and boundary B=3, verify native source RGBA through
END/ZIP and disjoint CI-widget mutation behavior, and reject direct native
profile drift, premature END and post-encoding canvas/seek changes. Synthetic
B=3 is structural coverage, not a separately live-observed episode.

Isolated normal Batch evidence: `output/ya35766-live-20261020/report.json`.
Only pending free Source 35766 was cloned to a dedicated Catalog; direct entry
blocked mutating requests and used no ticket. It captured all eleven slots
1-11 as native 960x1364 WebP, independently equal to draw-time source RGBA,
reached END with max_pages=11, created a CRC/decode/order-checked eleven-entry
ZIP and completed only the isolated Item. Thirty mutating requests were
blocked and zero checkout attempts occurred. Normal Catalog/archives and
settings were not modified. Only the owned browser Page was closed.

Final complete affected selection: **475 passed**, zero failed/skipped/
deselected, five existing pytest-asyncio deprecation warnings, in 379.74
seconds. Files: `tests/unit/test_younganimal_capture.py` (263 cases) and
`tests/integration/test_younganimal_adapter_browser.py` (212 cases), using
`-q -p no:cacheprovider --disable-warnings --tb=short --maxfail=1` and an
isolated short temporary directory. This includes every prior layout, the
previous top-empty/three-PR fix and the new odd-body three-PR tests. The new
focused browser selection separately passed 11 cases in 14.17 seconds. Ruff
`src tests` and whitespace checks passed. Full repository/Research test suites
were not selected because the production change is site-local, with no shared
runtime, data-model or research changes. Live verification above covers the
actual failing episode; no ticket-consuming scenario was needed or attempted.

### Initial blank plus three trailing PRs: Item/Source 35765

Normal Batch `c6b82ccc69f7498583eecd3ca5ae7eb7` failed before capture on
`a4457c04d74fc` (ナナとカオル / 第2話 交渉②) with
`PR/Good/Last tail roles changed`. The saved 17-wrapper layout combines the
known initial blank and three-PR structures, which were previously supported
separately. It has top PR 0, exact blank 1, body 2-10, CI 11, PR 12-14, Good 15
and Last 16. Waiting cannot change this valid role sequence into the old
two-PR top-empty sequence.

The bounded shared-CDP metadata probe
`output/younganimal-layout-35765-probe-20261020/report.json` reproduced the old
rejection and checked every seek 17..1 by -2 before rewinding to 17. It blocked
37 mutating requests and attempted zero checkouts. Exact observations:

| Seek | Centered wrappers | Phase | State |
|---|---|---|---|
| 17 | 0, 1 | first + top-PR | initial blank |
| 15..9 by -2 | 2/3..8/9 | none | body pairs |
| 7 | 10, 11 | CI + PR | last body + CI |
| 5 | 12, 13 | PR | PR pair |
| 3 | 14, 15 | PR | PR + Good |
| 1 | 16 | Last only | unique visible/centered Last |

`top_empty_three_pr` requires the positive top-empty flag, exact top-PR lead
and separate canvas-free blank, exactly three PRs, and contiguous derived body
slots starting at 2. B=N-8 must be odd and at least three, with min=1/max=N/
step=2, horizontal/spread/RTL and PR/CI/Good capabilities, and no vertical or
single mode. Selected centers and phase flags must match at every seek.
Initialization/rewind recognizes only this positively proven blank and uses
one public seek step to the first body pair. Python parsing, native JS layout
proof and CI mutation geometry share the role map. P=1 plus a separate blank,
arbitrary PR counts, changed roles/ranges, wrong Last and premature END remain
fail-closed. Every body slot is still required before END; source/replay,
node/write/generation, final geometry, post-encoding proof and size guards stay
unchanged. Existing profiles retain their contracts. No Core, access-resource,
PNG policy, retry or production timeout changes were made.

Synthetic Unit tests cover all nine observed seek states and invalid blank,
canvas, capability, phase, center, tail, range and Last mutations. Extended
browser fixtures exercise B=9 and structural boundary B=3 through native
RGBA-equal capture/END/ZIP, including incoming draws before final translation
and permitted disjoint CI-widget mutations at seek 7. Browser rejection cases
cover profile drift, premature END and canvas/seek changes after encoding.
These alternate body totals are structural regression coverage, not additional
claims of live-verified episode shapes.

An isolated normal Batch copied only pending free Source 35765 to a dedicated
Catalog and used `direct`, with all mutating requests blocked. Evidence:
`output/ya35765-live-20261020-2/report.json`. It completed all nine body slots
2-10 as native 960x1364 WebP, independently equal to draw-time source RGBA,
reached END at max_pages=9, packaged a nine-entry CRC/decode-checked ZIP and
marked only the isolated Item completed. Thirty-three mutating requests were
blocked; zero checkouts, HTTP 403/429/5xx, challenge/CAPTCHA and retries occurred.
The normal Catalog, its pending Item 35765, settings and existing archives were
not changed. An earlier isolated attempt failed before site access because
shared CDP was closed; the shared launcher/profile was verified and restarted
before the successful run. Only the owned Page was closed after verification.

Affected verification covered 445 distinct cases: 242 capture Unit and 203
real-browser Integration cases, zero skipped. The first complete affected run
had 444 passes and one PNG positive-path timeout under the test's four-second
Core call budget (369.56 seconds total). The committed-module control passed;
an instrumented current-module rerun also passed with capture calls around
1.1-2.1 seconds, confirming timing sensitivity rather than a role rejection.
Only that PNG positive test's `adapter_timeout_grace_ms` was raised from 2,000
to 6,000 (eight-second total call budget); it passed in 19.87 seconds. Production
timeouts were not changed. All six extended top-empty Runner/END/ZIP cases
also passed after adding initial-seek-at-END rewind coverage (13.79 seconds).
The other affected cases passed in the complete selection; no full repository
suite is claimed. Full suite/Research were not selected because this change
is site-local and touches no shared runtime or research code. Ruff `src tests`
and whitespace checks passed.

### Three trailing PRs: Item/Source 35579

Normal Batch run `f067d1301504474a9f87c5aa63d1b0cf` failed on episode
`be702296e543c` (work `b10a2a258e602`, ナナとカオル / 第100話 失われた誇り①-1)
before Capture in 22.836 seconds with `PR/Good/Last tail roles changed`.
HTTP 403/429/5xx, challenges/CAPTCHA, and retries were all zero. Saved HTML:
`output/batch/younganimal/item-35579-source-35579-20261019T202845772787+0900-f6b94f78787842cc992092aa87133770/diagnostics/`.
Its fully formed seventeen-wrapper Viewer has **three** trailing PR wrappers.
The old parser supported one-PR and two-PR sequences, so waiting could not fix
the rejection. The extra PR also moves the final body/CI seek from 5 to 7.

The bounded metadata-only shared-CDP probe
`output/younganimal-layout-35579-probe-20261019/report.json` reproduced the old
rejection through six seconds, verified every public seek 17..1 by -2 and rewound
to 17. It blocked 37 mutating requests with zero checkout attempts. Exact roles:
top PR 0, body 1-10, CI 11, PR 12-14, Good 15, Last 16.

| Seek | Centered wrappers | Phase flags | Role |
|---|---|---|---|
| 17 | 0, 1 | first + top-PR | top PR + first body |
| 15..9 by -2 | 2/3..8/9 | none | body pairs |
| 7 | 10, 11 | CI + PR | final body + CI |
| 5 | 12, 13 | PR | first two PRs |
| 3 | 14, 15 | PR | third PR + Good |
| 1 | 16 | Last only | unique visible/centered Last marker |

`standard_three_pr` now recognizes this family with exactly P=3 PRs, derived
even B=N-P-4>=4, exact top-PR lead, contiguous known body classes and exact
CI/PR/PR/PR/Good/Last tail without canvases. The positive horizontal/spread/RTL
and PR/CI/Good capabilities are mandatory; top-empty/vertical/single are forbidden.
Seek is min=1/max=N/step=2. The shared PR-tail helpers explicitly support P=1
and P=3, preserving the existing `standard_single_pr` variant, and derive CI,
every PR, Good, Last and final-body seek P+4 from P. An arbitrary PR count is
not accepted. The two-PR and other profile guards are retained. Every selected
center and phase must match, the Last marker must be unique/visible/centered,
and all frozen contiguous body slots are still required before END.

Python parsing, native JS proof and CI mutation geometry share this role map.
Existing draw-time immutable source, full-frame fractional draw replay, paint,
node identity, dimensions, generation/write, byte bounds, pure same-size
translation and full RGBA checks remain. Source draw observation may precede
settled centers under that existing proof; selection/postproof require the exact
final geometry. CI widget mutation exceptions retain the disjoint/contained
active-body geometry and capture-epoch proof. No retry, timeout increase, generic
blank skip, PNG fallback change or access-resource change was introduced.

Isolated standard CLI Batch evidence is `output/ya35579-live/report.json` and
`postflight.json`. Read-only SQL copied exactly this source into a private Catalog
with an empty Watchlist, preserving its grant through 2026-10-22T07:29:57+09:00.
Planner selected direct=1/quota=0. Standard Executor/Runner/packager/metrics used
shared CDP, an owned Page, max_pages=10, a mutating-request blocker and independent
draw-time source audit. All ten ordered physical body slots were native 960x1364
WebP, every RGBA byte equal to source, and six captures reached END and produced
a CRC-valid ten-member WebP ZIP with isolated Item completed. This proves decoded
source equality, not transport-byte identity. Artifact hash and size matched:
5,605,663 bytes, `ec86bcd185ddf8e63ca666450a843e4e6e9132bb1096b1f56aeb80d4dac6c0de`.
SQLite integrity_check returned ok. Metrics run `f5d25350cc91413ca2d025f1c3993b6b`
completed in 26.953 seconds with 255 requests and zero failed candidates, HTTP
403/429/5xx, challenges/CAPTCHA, and retries. Thirty-six mutating requests were
blocked and zero checkout attempts occurred. Only the owned Page closed. The
normal Catalog's Item 35579 remains pending with its same grant, and normal
archives were not modified.

Synthetic fixtures now parameterize explicit PR counts while retaining all
prior default shapes. Coverage includes every live P=3 phase, P=1/P=3 role,
capability, range, CI-phase and interstitial-phase rejection, bad Last markers,
direct native rejection and premature END, post-encoding replacement, unsupported
P=5 rejection, B=10/B=4 source RGBA through Runner/END/ZIP and permitted disjoint
CI-widget changes at seek 7. The first focused run had 67 passes and one fixture
failure because its hard-coded invalid max=13 was valid for the new P=3 sample;
the mutation now changes max relative to the fixture's actual range. Production
range proof was not changed for that correction.

The final complete affected selection passed **412 cases**, zero failed/skipped/
deselected, five existing pytest-asyncio deprecation warnings, in 376.09 seconds:
`tests/unit/test_younganimal_capture.py` and
`tests/integration/test_younganimal_adapter_browser.py`. Command:
`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp output/ya35579-f
tests/unit/test_younganimal_capture.py tests/integration/test_younganimal_adapter_browser.py --tb=short`.
Log: `output/ya35579-tests.txt`. This includes every previously supported capture
profile, earlier short/odd-body changes and ticket/route diagnostics. Ruff
(`src tests`) and changed-file diff whitespace checks passed. Full repository,
unrelated Discovery and standalone Research-helper suites were not rerun for
this site-local change; complete affected synthetic Unit/browser and bounded
live metadata/standard Batch verification cover the contract. Core/Catalog/
access/pacing have no new changes, so `note/00_core.md` needs no synchronization.
Unobserved PR counts remain unsupported and unproven sources retain the existing
PNG fallback; the observed verification above produced ten native WebP pages.

### One-body bonus Viewer: Item/Source 35233

Normal Batch run `467bd2ca7d34430d812534a2acacd157` failed on free episode
`ccae6b96885d7` (work `e594f5430dabe`, 俺は何度でもお前を追放する / おまけ)
before Capture in 22.380 seconds, with `physical page wrappers are incomplete`.
HTTP 403/429/5xx, challenges/CAPTCHA, and retries were zero. Saved HTML:
`output/batch/younganimal/item-35233-source-35233-20261019T180118309347+0900-2635f64bca5f4f1296372ad1ee7d534f/diagnostics/`.
The fully formed Viewer has only one body page and seven wrappers, below the
previous eight-wrapper minimum. Its seek max is seven, like the two-body bonus,
but the tail positions and terminal flags differ. A count-only minimum decrease
would not establish correct body and END semantics.

The metadata-only shared-CDP probe
`output/younganimal-layout-35233-probe-20261019/report.json` reproduced the old
rejection through six seconds, observed every public seek 7/5/3/1 and rewound
to 7. Thirty-two mutating requests were blocked with zero checkout attempts.
Exact roles are top PR 0, body 1, CI 2, PR 3-4, Good 5, Last 6:

| Seek | Centered wrappers | Phase flags | Role |
|---|---|---|---|
| 7 | 0, 1 | first + top-PR | top PR + only body |
| 5 | 2, 3 | CI + PR | CI + first PR |
| 3 | 4, 5 | PR | second PR + Good |
| 1 | 6 | Last only | unique visible/centered Last marker |

`standard_one_body` now recognizes this exact one-body map, distinct from
`standard_two_body`. Both require positive horizontal/spread/RTL and PR/CI/Good
capabilities, absent top-empty/vertical/single modes, exact lead/tail classes,
known contiguous body states, zero non-body canvases, range min=1/max=7/step=2,
and every selected center and phase. The shared short-layout JS helper derives
CI and all tail roles from the one/two body count, and filters the nonexistent
second centered wrapper at one-body END. Python uses the same map, including
CI/PR and PR/Good interstitial states; after the sole body is captured, Runner
seeks to minimum and requires the unique visible/centered Last plus full frozen
body coverage. Fewer than seven wrappers and unknown short shapes fail closed.
No episode-ID exception, generic blank skip, retry, timeout increase, or access
change was introduced. Existing source/full-frame draw, paint, immutable source,
node identity, dimensions, generation/write, same-size translation, full RGBA
replay and post-encoding proof remain. Selection/postproof still require final
centers even where source draws precede final CSS translation.

The isolated standard CLI Batch evidence is `output/ya35233-live/report.json`
and `postflight.json`. Read-only SQL copied exactly this free source to a private
Catalog with an empty Watchlist; Planner selected direct=1/quota=0. Standard
Executor/Runner/packager/metrics used shared CDP and an owned Page, max_pages=1,
mutating-request blocker and independent draw-time source audit. The single
output was native 960x1376 WebP, every RGBA byte equal to source, and the run
reached END, produced a CRC-valid one-member WebP ZIP and marked the isolated
Item completed. This proves decoded source equality, not transport-byte identity.
Artifact SHA-256 and size matched: 916,815 bytes,
`399b54f60ce6d055e152965db2054ae2233e2392ba39ba49fdcbe79ef0c52da7`.
SQLite integrity_check returned ok. Metrics run `6cc12fcca7e64bbc8f45b24aae33fb64`
completed in 9.393 seconds with 228 requests and zero failed candidates, HTTP
403/429/5xx, challenges/CAPTCHA, and retries. Thirty mutating requests were
blocked, zero checkout attempts occurred, and only the owned Page closed.
The normal Catalog still has pending Item 35233; normal archives and access
state were not modified.

Existing synthetic short-profile cases were parameterized for one/two bodies:
all phases/roles/ranges/centers, missing capabilities, tail canvases, incorrect
Last markers, direct native rejection, premature END before coverage, post-encode
replacement, source RGBA, permitted disjoint CI-widget changes, full Runner/ZIP
completion. The focused selection passed 59 cases, 317 deselected, zero failed/
skipped, five existing pytest-asyncio deprecation warnings in 13.75 seconds.
The final complete affected selection passed **376 cases**, zero failed/skipped/
deselected, five existing pytest-asyncio deprecation warnings, in 274.30 seconds:
`tests/unit/test_younganimal_capture.py` and
`tests/integration/test_younganimal_adapter_browser.py`. Command:
`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp output/ya35233-f
tests/unit/test_younganimal_capture.py tests/integration/test_younganimal_adapter_browser.py --tb=short`.
Log: `output/ya35233-tests.txt`. The short basetemp avoids the previously observed
Windows diagnostic temporary-path limit. This selection includes the preceding
odd-body and two-body changes and existing ticket/route/capture behavior. Ruff
(`src tests`) and changed-file diff whitespace checks passed. Full repository,
unrelated Discovery and standalone Research-helper suites were not rerun for
this site-local change; synthetic Unit/browser plus bounded live metadata and
standard Batch verification cover the changed contract. Core/Catalog/access/
pacing have no new changes; `note/00_core.md` needs no synchronization. Unknown
short layouts still fail closed, and unproven sources retain the existing PNG
fallback; the verified run above produced native WebP.

### Two-body bonus Viewer: Item/Source 35228

Normal Batch run `287fd51f31e24502b80dfe34b85b0c41` failed on free episode
`9f869e61ae122` (work `e594f5430dabe`, 俺は何度でもお前を追放する / おまけ).
It failed before Capture in 22.112 seconds with `physical page wrappers are
incomplete`; HTTP 403/429/5xx, challenges/CAPTCHA, and retries were all zero.
The saved HTML is under
`output/batch/younganimal/item-35228-source-35228-20261019T173419871705+0900-ba1739668c7c44579189f4869935363e/diagnostics/`.
It has a fully formed eight-wrapper two-body layout and seek max 7. The generic
Python and native/CI layout guards required nine wrappers, so waiting longer
could not resolve the rejection.

The bounded metadata-only shared-CDP probe
`output/younganimal-layout-35228-probe-20261019/report.json` reproduced the rejection
through six seconds and checked all public seeks 7/5/3/1, then rewound to 7.
It blocked 32 mutating requests with zero checkout attempts. The exact roles
are top PR 0, body 1-2, CI 3, PR 4-5, Good 6, Last 7:

| Seek | Centered wrappers | Phase flags | Role |
|---|---|---|---|
| 7 | 0, 1 | first + top-PR | top PR + first body |
| 5 | 2, 3 | CI + PR | second body + CI |
| 3 | 4, 5 | PR | both PRs |
| 1 | 6, 7 | Last + PR | Good + unique visible/centered Last |

The minimum wrapper guard now admits eight only through explicit
`standard_two_body` proof: horizontal/spread/RTL and PR/CI/Good capabilities,
no top-empty/vertical/single modes, exact top-PR lead and five-tail roles,
exact two-body interval with known loading/rendered classes, zero non-body
canvases, range min=1/max=7/step=2, and every observed center/phase. Unknown
short layouts still fail closed; the separately verified seven-wrapper one-body
profile is documented above. Python parsing,
native layout proof and CI geometry agree on the new variant. Initialization
captures body 1; seek 5 captures body 2; END still requires both frozen body
slots and the unique visible/centered terminal marker. Existing source/draw,
node/paint/write/generation, immutable snapshot, full RGBA replay, same-size
translation, byte limits and post-encoding proof remain. Draw-time binding may
precede final CSS translation only under that existing proof; selection and
postproof require the exact final centers. No retry, extra navigation, deadline
increase, generic blank skip, or access-policy change was introduced.

The isolated standard CLI Batch evidence is `output/ya35228-live/report.json`
and `postflight.json`. Read-only SQL copied only this free source into a private
Catalog and empty Watchlist. Standard Planner/Executor/Runner/packager/metrics
ran through shared CDP with direct=1/quota=0, max_pages=2, an owned Page, mutating
request blocker and independent draw-time source audit. Both physical body
slots were native 960x1376 WebP, every RGBA byte equal to source; the run reached
END, created a CRC-valid two-member WebP ZIP and marked the isolated Item
completed. This is decoded source equality, not transport-byte preservation.
Artifact hash and size matched: 664,227 bytes,
`3473687fceaf27dc580ce4aac3099b994fd02be73e7232de0d5d3165223929c6`.
SQLite integrity_check returned ok. Metrics run `4733748f40cf4162881126e63e01c572`
completed in 10.858 seconds with 232 requests and zero failed candidates,
HTTP 403/429/5xx, challenges/CAPTCHA, and retries. Thirty-one mutating requests
were blocked, zero checkout attempts occurred, and only the owned Page closed.
The normal Catalog's Item 35228 remains pending; normal archives and access
state were not modified.

Synthetic tests cover all four phases, exact roles/capabilities/range/centers,
invalid Last markers, native collector rejection, premature END before coverage,
post-encoding replacement rejection, source RGBA for both captures, disjoint CI
widget changes, and Runner/ZIP completion. The initial fixture audit expected
rendered slot 3 even though it is CI in this profile; it was corrected to audit
the two actual body slots, without changing production. The focused final
selection passed 32 cases, 317 deselected, zero failed/skipped, five existing
pytest-asyncio deprecation warnings (8.60 seconds).

The final complete affected selection passed **349 cases**, zero failed/skipped/
deselected, five existing pytest-asyncio deprecation warnings, in 268.27 seconds:
`tests/unit/test_younganimal_capture.py` and
`tests/integration/test_younganimal_adapter_browser.py`. Command:
`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp output/ya35228-f
tests/unit/test_younganimal_capture.py tests/integration/test_younganimal_adapter_browser.py --tb=short`.
Log: `output/ya35228-tests.txt`. The short basetemp avoids the Windows temporary
path-length problem documented in the previous snapshot. This full selection
includes the preceding no-top-PR odd-body fix and the existing ticket/route cases;
no test assertion was relaxed for path length. Ruff (`src tests`) and changed-file
diff whitespace checks passed. Full repository, unrelated Discovery, and standalone
Research-helper suites were not rerun for this site-local capture change; synthetic
Unit/browser and isolated live metadata/Batch verification cover the changed
contract. Core/Catalog/access/pacing have no changes in this fix, so
`note/00_core.md` needs no additional synchronization. Other unobserved short
profiles remain unsupported, and the existing unproven-source PNG fallback remains.

### No top PR with odd body: Item/Source 35225

Normal Batch metrics run `e05e23b6032f48abae61244b307bbdc4` failed on free episode
`fe0edd24d59ae` (work `7103c2c1e9f08`, 藍より青し / 第一話 縁ーえにしー).
It stopped before Capture in 22.214 seconds with the seek-range rejection and zero
HTTP 403/429/5xx, challenge/CAPTCHA, or retries. The saved HTML at
`output/batch/younganimal/item-35225-source-35225-20261019T171042252727+0900-29f20c42b35045e686e5123d984bb9b3/diagnostics/`
has 35 wrappers, seek max 35, positive top-empty capability, and exact empty/no-PR
slot 0. The former `top_empty_no_pr` branch required max=N-1; this odd-body
variant instead requires max=N. It is a structural mismatch, not slow loading.

The metadata-only shared-CDP probe
`output/younganimal-layout-35225-probe-20261019/report.json` confirmed the range
rejection through six seconds and observed every public seek from 35 through 1,
then rewound to 35. It blocked 32 mutating requests with zero checkout attempts.
The exact map is empty lead 0, body 1-29, CI 30, PR 31-32, Good 33, Last 34:

| Seek | Centered wrappers | Phase flags | Role |
|---|---|---|---|
| 35 | 0, 1 | first only | empty lead + first body |
| 33..7 by -2 | 2/3..28/29 | none | fourteen body pairs |
| 5 | 30, 31 | CI + PR | CI + first PR |
| 3 | 32, 33 | PR | second PR + Good |
| 1 | 34 | Last only | unique visible/centered Last marker |

`top_empty_no_pr_odd_body` now derives B=N-6, odd and at least three, with exact
empty lead and five-tail classes, contiguous known body states, and zero non-body
canvases. It requires top-empty, horizontal/spread/RTL, and PR/CI/Good capabilities;
vertical/single modes are forbidden. Range is min=1/max=N/step=2. All selected
centers and phase flags must match, including visible/centered unique Last, and
the frozen complete body interval is still required before END. The count 29,
wrapper count 35, and episode ID are not production exceptions. The even-body
no-top-PR profile retains max=N-1; standard odd-body behavior retains its top PR.
Python observation, native layout proof, and CI geometry use the same mapping.
Existing exact odd-body helpers now accept an explicit no-top-PR mode; default
calls preserve the former standard profile. CI scroll-widget exceptions still
require the existing disjoint/contained active-body geometry and epoch proof.

For this explicit no-top-PR odd family only, draw-time source binding may precede
final CSS translation. The draw-time route/seek/role, source/full-frame draw,
nodes, dimensions, generation/write/context and immutable source snapshot gates
remain. Selection/postproof require exact final centers and the existing same-size
pure translation plus full replay RGBA. The bounded draw trace
`output/younganimal-png-investigation-35225-20261019/report.json` observed incoming
2/3 draws at seek 33 while centers were still 0/1, then native capture of that
pair. No new retry, timeout increase, public-seek refresh, blank skip or weaker
source/pixel proof was introduced.

The first isolated auditing Batch in
`output/younganimal-no-top-pr-odd-batch-live-20261019/report.json` parsed the new
layout but stopped at its audit assertion because the first native candidate was
missing/stale and production returned the permitted rendered PNG. That attempt
is not successful native verification. The separate bounded draw trace saw early
draws with no proven native layout, followed by a later proven redraw of slot 1
and native 1/2/3 capture. Which initial layout condition was incomplete is UNKNOWN;
native availability at load is not guaranteed. Production still falls back for
an unproven source, rather than inferring provenance or reusing a stale snapshot.

The final independent normal CLI Batch evidence is
`output/younganimal-no-top-pr-odd-batch-live-20261019-attempt2/report.json` and
`postflight.json`. Read-only SQL copied exactly this free source into an isolated
Catalog with an empty Watchlist. Standard Planner selected direct=1/quota=0, and
Executor/Runner/packager/metrics used shared CDP and an owned Page. The auditing
Adapter compared all outputs to independent draw-time source copies. It completed
29 ordered native 960x1364 WebP pages (fifteen captures), every RGBA byte equal to
source, reached END, produced a 29-member CRC-valid WebP ZIP, and marked the
isolated Item completed. This is decoded source equality, not transport-byte
preservation. ZIP SHA-256 and size matched Artifact: 16,677,529 bytes,
`8682f22c93ffa07062a1b6a174c0575ac1b79e3ca39b321de28ba650ee705903`.
SQLite integrity_check returned ok. Metrics run `532e5c30b234450d8e474b0790e24fdd`
completed in 50.071 seconds with 254 requests and zero failed candidates, HTTP
403/429/5xx, challenges/CAPTCHA, and retries. Thirty mutating requests were blocked;
zero checkout attempts were observed. The normal Catalog still has pending Item
35225; normal archives and access state were not modified. Only the owned Page
was closed.

Synthetic regressions cover both top-PR/no-top-PR odd profiles, B=29 metadata,
all phases and exact roles/centers, missing capabilities/halves, invalid Last,
direct native collector rejection, B=7 and B=3 full native pixel/END/ZIP runs,
incoming draws before translation, disjoint CI-widget changes, post-encoding
replacement and premature terminal seek. The focused selection passed 38 cases,
283 deselected, zero failed/skipped, five existing pytest-asyncio deprecation
warnings (6.60 seconds).

The complete affected selection exercised 321 cases: 319 passed and two existing
route-diagnostic tests failed to find metadata.json (265.76 seconds, five existing
warnings, zero skipped). Command:
`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp
output/younganimal-no-top-pr-odd-final-pytest-20261019
tests/unit/test_younganimal_capture.py tests/integration/test_younganimal_adapter_browser.py --tb=short`.
Log: `output/younganimal-no-top-pr-odd-final-tests-20261019.txt`.

Both failures were reproduced with the long basetemp, then both passed unchanged
in 3.61 seconds with short basetemp `output/ya35225-r`, using the exact two test
node IDs: `test_younganimal_unknown_ticket_route_persists_first_failure_before_click`
and `test_younganimal_work_ticket_route_drift_after_proof_keeps_consumption_pending`
in `tests/integration/test_younganimal_adapter_browser.py`. Zero failed/skipped,
five existing warnings. A bounded synthetic atomic-write probe in the long failed
directory confirmed FileNotFoundError for the sibling `.path-probe.json.tmp`
(destination absolute path length 260, temporary path longer); evidence is
`output/younganimal-35225-path-probe-20261019.json`. This is the Windows path-length
limit of the chosen test directory, not a Viewer or route-decision regression.
Use a short basetemp for future runs. No production filesystem or diagnostic
change, test assertion relaxation, or additional site retry was made. All 321
affected cases therefore have passing evidence across the full selection and
the two-case short-path recheck; this is not one clean 321-case invocation.

Ruff (`src tests`) and diff whitespace checks passed. Full repository, unrelated
Discovery and standalone Research-helper suites were not rerun for this site-local
Viewer/capture change; synthetic Unit/browser tests and bounded live metadata,
draw-trace, and standard Batch verification cover the changed contract. Shared
Core, Catalog, access policy and pacing are outside this change, so no additional
`note/00_core.md` update is needed. The initial native audit's missing-candidate
limitation above remains: no guarantee of native availability during loading.

### Single trailing PR Viewer: Item/Source 34211

Normal Batch run `e05dba45a6f54557b94b47264e9a3401` stopped on episode
`1517292f23ad0` (番外編 ポーラの水浴び), after 35 completed candidates, with
`PR/Good/Last tail roles changed`. Its candidate failed before capture in 21.918 seconds;
the summary recorded zero HTTP 403/429/5xx, challenges/CAPTCHA, and retries. The matching
saved HTML is under
`output/batch/younganimal/item-34211-source-34211-20261019T103450371155+0900-92d8c989135a421eab77e58570884893/diagnostics/`.
It has eleven wrappers and seek max 11, with only **one** trailing PR, rather than the
previously supported two-PR tail. Increasing the readiness timeout would not resolve
that structural mismatch.

The bounded metadata-only shared-CDP probe
`output/younganimal-layout-34211-probe-20261019/report.json` reproduced the rejection
after three and six seconds and verified all public seek positions, then rewound:

| Seek | Centered wrappers | Phase flags | Role |
|---|---|---|---|
| 11 | 0, 1 | first + top-PR | top PR + first body |
| 9 | 2, 3 | none | body pair |
| 7 | 4, 5 | none | body pair |
| 5 | 6, 7 | CI + PR | last body + CI |
| 3 | 8, 9 | PR | single PR + Good |
| 1 | 10 | Last only | unique visible/centered Last marker |

The new `standard_single_pr` profile derives body count `B=N-5`, requiring even B>=4,
the exact top-PR lead, contiguous known body classes, exact CI/PR/Good/Last roles with
zero tail canvases, horizontal/spread/RTL and PR/CI/Good capabilities, and absent
top-empty/vertical/single flags. The range must be min=1/max=N/step=2. Python observation,
native JS layout proof, and capture observer CI geometry share that mapping. Every phase
and selected center must match; no episode ID or fixed total is allowlisted. The four-tail
profile is distinguished from the existing five-tail profiles. Missing/unknown roles,
changed capabilities/ranges, extra selected centers, and invalid Last markers fail closed.
END still requires all frozen contiguous body slots. Source snapshots may precede final
translation only at draw time, under the already established exact route/seek/node,
generation/write/context, same-size translation, full-frame fractional draw replay, and
RGBA proof. Selection and postproof still require final centers. No new retry, deadline
increase, PNG fallback rule, or shared Core/access change was introduced.

The standard CLI Batch validation is
`output/younganimal-single-pr-batch-live-20261019/report.json`. Source 34211 was copied
using read-only SQL into an isolated Catalog, preserving its existing grant through
2026-10-22; Planner selected direct=1/quota=0. An auditing Adapter subclass blocked
mutating requests and compared each capture to an independent draw-time source copy.
It completed six ordered native 960x1364 WebP pages (physical 1-6), every RGBA byte equal
to its source, reached END, created a six-member CRC-valid WebP ZIP, and marked the
isolated Item completed. This proves decoded source equality, not response-byte
preservation. ZIP SHA-256 and size matched the Artifact record (2,589,609 bytes,
`faf8a0e82ac2dd9b147a1889491a556b9d32e8831143e37695847de18e91d061`);
SQLite integrity_check returned ok. Metrics run `1cf638404e934546a26b517a72955ab2`
completed one candidate in 16.065 seconds with 234 requests and zero failed candidates,
HTTP 403/429/5xx, challenge/CAPTCHA, and retries. It blocked 35 mutating requests and
observed zero checkout attempts. The normal Catalog still has pending Item 34211 and
the same grant; existing archives were not modified. Only the owned Page was closed.

Regression coverage uses synthetic pages, not saved site artwork: all seek phases,
role/capability/range/center/Last rejection, direct native collector rejection, source RGBA
through END/ZIP for B=6 and the B=4 boundary, permitted disjoint CI widget changes, and
post-encoding canvas replacement/root mutation rejection. The initial focused run exposed
a synthetic fixture whose listing pushed the Viewer below the viewport; its single-PR
fixture now fixes the Viewer to the viewport, matching the observed site. No production
visibility check was relaxed. The corrected focused selection passed 34 cases, 254
deselected, zero failed/skipped.

The complete affected selection (`tests/unit/test_younganimal_capture.py` and
`tests/integration/test_younganimal_adapter_browser.py`) exercised 290 cases: 289 passed
and one existing whole-spread fallback test failed under its short operation budget
(342.41 seconds; five existing pytest-asyncio deprecation warnings; zero skipped).
Log: `output/younganimal-single-pr-final-tests-20261019.txt`; basetemp:
`output/younganimal-single-pr-final-pytest-20261019`. The failure was also reproduced
alone. The Runner caught a capture timeout and attempted its generic locator path, which
this Adapter correctly rejects. A bounded timing trace of the original test subsequently
passed, recording 3.22-3.70 seconds per two-canvas readback against that test's four-second
outer operation budget (two seconds plus two seconds grace). This supports timing
instability rather than a changed layout decision; it does not assign a machine-load cause.

That existing atomic fallback/cleanup fixture now uses synthetic 98x133 bitmaps, retaining
its full sixteen-body Runner/END, clipped first candidate, missing second-half candidate,
whole-spread PNG, cache cleanup, and dimension assertions. It tests atomic fallback, not
large-bitmap throughput. Full-size pixel/proof fixtures and production timeouts are
unchanged. A final seven-case recheck passed in 5.81 seconds: the corrected test, four
following odd-body rejection cases (also verifying fixture globals are restored), and both
single-PR post-encoding mutation cases; 152 deselected, zero failed/skipped, five existing
warnings. Together with the unchanged passing cases, all 290 affected cases have passing
evidence; this is not a claim of one clean 290-case invocation. Commands used
`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp <isolated output>`.
The final selection used the browser test file with
`-k 'unsafe_or_missing_native_half or odd_body_native_collector_rejects or replacement_single_pr or root_class_noop_single_pr'`
and basetemp `output/younganimal-single-pr-final-recheck-20261019`.

Ruff (`src tests`) and diff whitespace checks passed. Full repository, unrelated Discovery,
and standalone Research/Probe-helper suites were not rerun: production changes are local
to Younganimal Viewer/capture contracts with complete affected Unit/browser coverage and
an isolated live Batch. Core, Catalog, access policy and runtime pacing have no new changes
in this fix, so `note/00_core.md` requires no additional synchronization.

### Shorter top-empty Viewer: Item/Source 33100

User normal Batch metrics run `641c9898f3a24e519fb1434f5a38357a` failed on episode
`24c5d5dae77b0` (`act.1 少年達 ~Downtown boys~②`) before capture, after 23.780 seconds.
The summary reports zero HTTP 403/429/5xx, challenges/CAPTCHA, and retries. The saved HTML
under `output/batch/younganimal/item-33100-source-33100-20261019T091919973178+0900-a31a48741fc9401192662fecf9c42b1c/diagnostics/`
has 18 physical wrappers, a top-empty flag and exact blank slot 1, but max seek 17. The old
top-empty parser required max seek to equal wrapper count, so waiting longer could not fix
this structurally unsupported layout. Its timeout preserved only the exception class.

The bounded shared-CDP metadata report `output/younganimal-layout-33100-probe-20261019/report.json`
reproduced the exact range rejection in samples through six seconds. Normal public seeks
17,15,13,11,9,7,5,3,1 confirmed top PR 0, blank 1, body 2-12, CI 13, PR 14-15, Good 16,
and Last 17, then rewound to 17. At 17 the centered pair is 0/1 with first+top-PR flags;
15 through 7 select body pairs with no phase flags; 5 selects last body 12 plus CI 13 with
CI+PR flags; 3 selects PR 14/15 with PR; 1 selects Good 16 and Last 17 with Last+PR and
the unique visible/centered Last marker. This probe saved metadata, blocked mutations,
used no checkout, and closed only its owned Page.

Python parsing, native layout proof, and active-body geometry now accept that shorter
top-empty family with even wrapper count and max=N-1 only when the derived odd body has
at least three slots, the full horizontal/PR/CI/Good capability set is positive, vertical/single
modes are absent, blank/body/five-tail roles are exact, and every selected pair and phase
matches. Body slots remain frozen and contiguous; initialization still advances past only
the proven blank, the last single body is captured at seek 5, and END requires all body
slots plus the observed Last proof. The original odd-count top-empty, standard, odd-body,
no-PR, and no-CI contracts remain supported. This is structural support, not an episode-ID
or fixed-page-count exception.

The first instrumented Batch validation reached CONTENT but returned rendered PNG because
incoming pairs are drawn before CSS translation reaches their final centers. The bounded
draw trace `output/younganimal-png-investigation-33100-20261019/report.json` recorded seek 15
with body 2/3 draws while centers were still 0/1, and seek 13 with body 4/5 draws while
centers were still 2/3. Full-frame source/destination checks passed. Only draw-time source
observation may now precede those final centers; its phase, exact seek/role/node binding,
generation/write, context/paint, source rectangle, and immutable snapshot checks remain.
Selection/postproof still require exact final centers and phases, existing same-size pure
wrapper/target translation proof, and full RGBA replay. Missing halves, changed sizes/offsets,
and unknown layout do not become successful native captures. The fractional draw correction
is retained. No capture retry, deadline increase, or weaker pixel proof was introduced.

Readiness failures now include the bounded static parser message (256 characters) in
`adapter_debug.capture.viewer_readiness.last_error_message` and the timeout exception for
CLI/metrics correlation. The production readiness deadline remains 20 seconds. Unit and
browser regressions cover all phases, capability/blank/tail/range/center/Last rejection,
direct native-collector rejection, source RGBA through END/ZIP, a source draw before final
translation, and persistence of the timeout's parser reason. The final affected selection
passed 262 cases, 0 failed/skipped/deselected (five existing pytest-asyncio deprecation
warnings; 266.32 seconds): `tests/unit/test_younganimal_capture.py` (111 cases) and
`tests/integration/test_younganimal_adapter_browser.py` (151 cases). Command:
`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp
output/younganimal-short-top-final-pytest-20261019 <the two files>`. Log:
`output/younganimal-short-top-final-tests-20261019.txt`. The earlier 261-case run predates
the draw-time translation correction; the final focused 24 cases and full 262 cases passed
after that correction and are overlapping selections, not additive totals. Ruff (`src tests`)
and changed-file diff checks passed. Full repository, unrelated Discovery, and standalone
Research/Probe-helper suites were not rerun because this is a site-local Viewer/proof change
with complete capture Unit and browser Integration coverage. Shared Core and Catalog code,
schema, access policy, and runtime pacing did not change; their notes need no synchronization.

The final isolated normal CLI Batch evidence is
`output/younganimal-short-top-batch-live-20261019-attempt4/report.json`. One exact free
source was copied through read-only queries into its own Catalog; the standard CLI Planner,
Executor, Runner, packager, metrics, and shared CDP lifecycle were used with a source-auditing
Adapter subclass and mutating-request blocker. It completed eleven native 960x1364 WebP
pages (physical 2-12), reached END, created a CRC-valid eleven-member WebP ZIP, and marked
the isolated Item completed. Every output matched a separate draw-time source copy in every
RGBA byte before advance. This is decoded source equality, not response-byte preservation.
ZIP hash and size matched its Artifact record; SQLite integrity_check returned ok. Its metrics
run `c0eb8329b59c4235b97cfe8869e6aab4` completed one candidate with zero failed candidates,
HTTP 403/429/5xx, challenges/CAPTCHA, and retries (238 requests, 25.248 seconds).
Zero checkout attempts were observed; the source was free. The normal Catalog, its pending
Item 33100, and existing archives were not modified. The first two isolated harness setups
failed before browser access because SQLite integer boolean fields had not been converted
for the Catalog API; attempt 3 exposed the draw-time center issue above. Those failures are
retained and are not successful verification claims. No extra ticket was used.

### PNG fallback investigation: Item/Source 33083

Read-only inspection of the user's completed `act.10 街 ~Downtown~①` ZIP found ten PNG
members, all 933x1327. Catalog Run 12027 reached END with ten pages in metrics run
`bb610d9cc2d84ba887950c9be7c26f95`. The packaged ZIP contains images only; its removed
temporary manifest and the completion metrics do not retain per-page capture/fallback reasons.

A bounded shared-CDP probe on the same episode `f14dc7e0ac3f4`, using its existing grant
and blocking mutating requests, reproduced `mode=rendered_canvas_png` with
`native_fallback_reason=native_candidate_missing_or_stale` for physical slot 1 and spread 2/3.
The observed source-to-body draw was `[0,0,960,1364,0,0,933,1327.5]` into a 933x1327
bitmap. Active-slot samples had valid layout/location, bounded dimensions, no unsafe clip,
identity transform, alpha 1, source-over, no filter/shadow, and sRGB/unorm8 contexts, but
`fullFrame=false`. The pre-fix native observer's `fullFrame` required all eight arguments to be
safe integers and the destination to equal the bitmap exactly; the fractional height therefore
prevented candidate creation. Its replay also substituted integer bitmap dimensions rather
than retaining the observed draw rectangle. Hanayume's earlier fractional-destination correction
was site-local and did not change this observer. The subsequent Younganimal correction is below.

This is rendered-size fallback, rather than native PNG retention after a WebP codec failure.
The original ZIP confirms PNG dimensions for all ten pages; the new probe establishes the
specific fallback reason/source/draw geometry for the first three physical pages only, and
does not reconstruct historical per-page reasons. Evidence:
`output/younganimal-png-investigation-33083-20261019/report.json` and its adjacent ignored
probe script. It attempted zero rental checkouts, reported no resource consumption, closed
only its owned Page, and did not write the normal Catalog or archives. That investigation
checkpoint changed only this note and ran no pytest suite. Its live coverage is limited to the
two captures described above; the implementation and validation below are a separate checkpoint.

### Fractional destination capture correction

The native observer now accepts finite destination draw dimensions only when their floors equal
the positive, bounded target bitmap dimensions. Both origins remain exactly zero; the source
rectangle must be exactly the full native source. This admits the observed 0.5px height overhang
without accepting underfill, a whole-pixel overhang, source crop, nonzero offset, or nonfinite
geometry. Each candidate retains all eight draw arguments and replays them unchanged during
selection and postproof, rather than substituting integer bitmap dimensions. Native output
retains the actual source dimensions. Native context/paint, immutable snapshot, exact full-pixel
replay, node/episode/seek, frozen body mapping, generation/write, memory bounds, and all-or-none
spread gates remain strict. This change does not weaken post-selection mutation failures or
the existing fallback rules for genuinely unsupported native evidence. Codec failure may still
retain the same verified source PNG. No CLI/configuration or shared Core change is needed.

The added browser regression family uses patterned mutable sources and checks native WebP
RGBA after source clearing for fractional width, height, and combined subpixel overhangs.
Negative cases alter one spread half using underfill, whole-pixel overhang, cropped source,
nonzero destination origin, or nonfinite geometry and verify whole-spread rendered fallback
with exact rendered RGBA. The focused family passed eight cases (0 failed/skipped, 135 unrelated
cases deselected). The complete affected selection passed 238 cases, 0 failed/skipped/deselected:
`tests/unit/test_younganimal_capture.py` (95 cases) and
`tests/integration/test_younganimal_adapter_browser.py` (143 cases), including Runner-to-END,
packaging, whole-spread fallback, native postproof mutation, and ticket-entry boundaries.
Command: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp
output/younganimal-fractional-pytest-20261019 <the two files>`. The result was 268.67 seconds
with five existing pytest-asyncio deprecation warnings; the log is
`output/younganimal-fractional-tests-20261019.txt`. `ruff check src tests` and changed-file
`git diff --check` passed. Full repository, unrelated Discovery tests, and standalone
Research/Probe-helper tests were not rerun: the production diff is limited to the Younganimal
native rectangle gate/replay and the complete capture Unit/browser Integration boundary passed.

Isolated live verification is `output/younganimal-fractional-live-20261019/report.json`,
generated by the adjacent ignored script. The affected active-grant Source 33083 and exact-free
control Source 33096 (`d661579d9e75d`, same work) each reached END with ten native
960x1364 lossless WebP pages, with zero rendered fallback captures.
An independent draw observer copied each complete source before rendering; decoded capture
RGBA matched those copies on all twenty pages. Both runs used one owned shared-CDP Page at a
time, blocked mutating requests, attempted zero rental checkout requests, reported no resource
consumption, and observed zero HTTP 403/429/5xx responses. The normal Catalog, Item status,
and existing ZIPs were not changed. These were direct Runner checks; live standard Batch and
packaging were not rerun. This is source-canvas pixel equality, not original response-byte proof.

### Preparing existing PNG archives for re-crawl

`scripts/prepare_recrawl.py` now explicitly supports Younganimal with WebP preferred and
PNG fallback. This is a ZIP-member extension policy: PNG-only and WebP/PNG mixed archives
are FALLBACK_INCLUDED, WebP-only is PREFERRED_ONLY, and unknown formats remain unexpected.
A native-size codec-fallback PNG also matches; the classification does not infer pixel fidelity.
Default operation is dry-run, scoped to completed Items with exact site and optional Work title.
`python scripts/prepare_recrawl.py --site younganimal --catalog catalog.sqlite --ignore-missing`
found two candidates among eight completed Items on 2026-10-19: Item 25335 (`1.冬のキリン`,
`スピカ～羽海野チカ初期短編集～`, six PNG members) and Item 33083 (`act.10 街 ~Downtown~①`,
`ホーリーランド`, ten PNG members). Six archives were preferred; unexpected/broken/missing/
ambiguous counts were zero. The report is `output/younganimal-recrawl-dry-run-20261019.txt`.

Adding `--apply` moves each candidate ZIP to `output/reimport-backup/<timestamp>/`, preserves
its library-relative path where possible, updates the existing Artifact locator, and returns
the Item to pending. Source grants, cooldowns/quota state, prior CrawlRuns, and archived bytes
are retained; the command does not crawl or acquire access. Add `--work "ホーリーランド"` to
limit preparation to that exact title. The subsequent normal `batch run --site younganimal`
includes other pending Younganimal Items too; Batch has no `--work` filter.

Only dry-run was executed against the real Catalog; no real ZIP move, status reset, or re-crawl
was performed for this script extension. The existing preparation Unit suite was expanded and
passed 29 cases (0 failed/skipped; one existing pytest-asyncio warning), including format policy
and synthetic apply with byte-preserving backup plus unchanged Source and historical CrawlRun.
Ruff and changed-file diff checks passed. Browser Integration, standalone Research/Probe, live
apply/re-crawl, and full repository pytest were not rerun because only the preparation script's
static site policy changed. Shared Core, Catalog schema, Batch, and Viewer code are unchanged
by this extension; the earlier Viewer correction above is a separate change.

The store-item RSC prefetch follow-up recognizes only same-origin
`/store_items/<positive-id>` GET fetches on the main frame with no navigation
and both `_rsc` query and `rsc` header markers. Like the existing known-page
prefetches, these requests are aborted before downstream dispatch without
failing the selected episode. Other signatures and unknown routes remain fatal.
Fatal route errors now include their classification in the exception message,
and `diagnostics/metadata.json` exposes
`adapter_debug.ticket_action_attempted` and `adapter_debug.ticket_route_guard`.
The latter contains the first fatal reason/request, total blocked count, and
bounded known-page prefetch count/paths. The request stores host (253 characters),
path (512), method (16), resource type (32), and navigation/main-frame flags;
it omits credentials, query/header values, fragments, and bodies. Guard-internal
errors may have no request details. No CLI/configuration change is required.

The follow-up passed 94 live-access/policy/batch unit tests and 24 ticket-entry
browser Integration tests, with 0 skipped, plus an earlier overlapping 73-test
route-focused selection. Tests verify normal and grant-only continuation with
zero downstream product-prefetch dispatch, rejection of near-miss signatures,
first-failure diagnostics before clicking, and post-consumption diagnostic and
quota preservation. `ruff check src tests` and `git diff --check` passed.
Read-only live verification on `f14dc7e0ac3f4` used the updated production guard:
`/store_items/1888` was recorded and aborted, guard failure remained null,
the target URL remained exact, and click events/rental-checkout attempts were
both zero. It blocked 28 non-GET/HEAD requests. Evidence:
`output/younganimal-error-33083-fixed-readonly.json`. A consuming grant-only
retry, full repository suite, unrelated Viewer/capture Integration cases, and
standalone Research tests were not run; the change is limited to site-local
route classification and diagnostic reporting.

The work-ticket implementation, the narrow 78 CI-widget change, and the
horizontal top-empty/no-CI Viewer profile passed independent source review. The
earlier seven-file Younganimal selection covered 379 tests with 0 skipped:
95 capture-unit tests, 133 adapter-browser tests, and 151 tests across the other
five files. After the final no-CI marker and fake-widget test corrections, its
10 affected adapter cases were rerun and passed; those are part of, not in
addition to, the 133 adapter-browser cases. `ruff check src tests` and
`git diff --check` passed. The full repository suite was not run. An earlier
106-test adapter-browser run was incomplete after a prolonged hang of unknown
cause and was superseded by the completed focused selection; no RAF or
production-timeout change was made.

The fresh-quota normal Batch run on episode `849948508c8bc` / work
`71460b2b6686f` used one retained wait-free click and one target-bound rental
checkout (HTTP 200, exact target in `articleIds`). Authenticated native state
changed from `hasAccess=false`, `waitAndFree`, timer missing to
`hasAccess=true`, `waitAndFree`, 259147 seconds remaining. Consumption was
recorded at `2026-10-19T00:06:51.538338+09:00`; the grant expires at
`2026-10-22T00:05:58.369033+09:00`, and the local 23-hour cooldown ends at
`2026-10-19T23:06:51.538338+09:00`. No balance delta is claimed.

The same Page reached END on the 12-body standard Viewer and produced 12 ordered
934x1329 PNGs. ZIP CRC, full decode, order, MIME/dimensions, manifest,
Catalog completion, and Catalog/archive SHA checks passed. The Item completed;
the Run succeeded with page_count=12. Archive SHA-256 was
`cf4a3f5d897f762dc042d770f3ad04ebb192ad2855255d8cb7711dca321de0c1`
(11,388,813 bytes). This is not a source-native format or per-image hash claim.
The sanitized audit is `output/younganimal_work_ticket_tester/normal-849-attempt1-postflight.json`.

Eight ticket uses are recorded: all five original uses, DD9 (use six), 849
(use seven), and the user-triggered 8d92 run (use eight). Two of three
additional candidate authorizations were used;
`4ba85f4c9e538` was unopened and unused. Existing-grant direct captures on 856,
0634, C781, and 78 passed through END/ZIP (28, 15, 7, and 12 pages); the 0634
capture used the earlier count-specific fix, while C781 used the parametric
`standard_odd_body` profile. The separate 849 fresh-quota run is the verified
normal entry path. DD9's third normal attempt consumed its ticket but failed
before Capture on an unsupported `mode-v`/`mode-single` no-seek/no-CI Viewer;
that shape remains fail-closed. The earlier 78 action sentinel is absent, so
its click/checkout counts remain UNKNOWN.

Episode `8d92e88ab93ec` / work `cded52d3dfcd3` used a ticket at
`2026-10-19T05:58:32.801441+09:00`; its 23-hour cooldown ends at
`2026-10-20T04:58:32.801441+09:00`, and the observed grant expiry is
`2026-10-22T05:57:58.790933+09:00`. The earlier run failed before Capture
because the Viewer had an unsupported horizontal top-empty/no-CI layout. Its
metadata has since been mapped and the strict `top_empty_no_ci` capture profile
implemented and synthetic-verified. A later existing-grant direct run on the
updated implementation completed 10 pages through END/ZIP; it consumed no
additional ticket. The earlier quota-use run remains a failed-before-Capture
historical Run, and its Source grant/quota timestamps and Work consumption
timestamp were preserved.

The 849 navigation audit recorded one owned Page, one Python initial goto, zero
reload attempts, two same-target main-document requests, and four same-target
navigation/frame events of unknown cause. Seven off-target episode RSC GETs
were aborted; no series/off-target main-frame navigation occurred. Natural
mission/reward, read-completion, pixel/analytics, notification, and points
traffic was observed, so no claim of zero total site traffic or known initiators
is made. Phase 04 passed; the remaining authorized `4ba85f4c9e538` was not
needed. Full details are in the Younganimal work-ticket progress log.

The capture-start gate requires the Viewer navigation panel to be closed, no
`.-cv-splash` nodes, and the first body canvas/capture epoch to remain stable for
1 second within a 5-second bound. UI reappearance resets the quiet interval;
missing or unsettled metadata fails closed.

The current CI-widget exception is narrow. On the exact canonical child, exact
base-to-overflow and overflow-to-same-overflow writes require strict before/after
widget and selected-body geometry plus active-body proof. The legacy exact
base-to-base and scroll-bottom-to-same-scroll writes remain canonical-identity
no-ops; the existing base-to-scroll-bottom exception retains its geometry
requirement. Other transitions, extra/combined classes, namespaces, wrong
parents, or ambiguous geometry fail closed. Global DOM generation, native proof,
identity/epoch, frozen mapping, and END requirements remain unchanged.

## Historical verification snapshot (2026-10-18; superseded by the current checkpoint above)

Rental Discovery and direct reader entry are supported. Full live Discovery of
the supplied work enumerated six public positions and selected three current
rentals in an isolated Catalog. Episode `37d94ac0d8242` remained at position 2
with `access_mode=paid` and a conservative rental grant. Final-code Batch
captured all 28 body pages through END and packaged 28 CRC-valid ZIP members.
The only main-frame Crawl document navigation was the exact supplied episode
URL; no listing route was visited during Crawl and no quota consumption was
recorded. The report is
`output/younganimal_rental/crawl_20261012_065928/report.json`.

On 2026-10-18, one authorized research action was observed on episode
`856137d88753b` / work `8246f8b8b2e6c`. The exact wait-free control, same-row
`waitAndFree` false-to-true transition, target-bound successful checkout, and
same-Page ready Viewer were adjudicated as one resource use. Its 23-hour
minimum same-work cooldown ends at `2026-10-19T05:05:50.550591Z`.

A second authorized use occurred through live `--grant-only work_ticket` on
episode `e15e15c6ec11a` / work `128888a1fb162`. The CLI returned
`entry_confirmed` with `resource_consumed=true`, and the isolated Catalog
recorded `quota_started_at=2026-10-18T17:14:10.767250+09:00` and
`access_granted_until=2026-10-21T17:13:58.168443+09:00`. Pre/post native state
changed from authenticated `waitAndFree` without access to authenticated
`waitAndFree` with access and a positive 259187-second timer. One retained free
control click was delegated, and one target-bound checkout returned HTTP 200;
no balance-delta claim is made. The Item stayed pending with zero captured pages
and no artifact/ZIP. The trusted DOM event list was empty, so trusted-event proof
is NOT VERIFIED. The same-Page audit recorded two selected-episode main-document
requests and zero series/off-target main-document requests; source contains no
post-click goto/new-Page call, but the second request's initiator is unknown.
Do not repeat the action to repair telemetry. Its local 23-hour cooldown ends at
`2026-10-19T07:14:10.767250Z`.

One normal Batch work-ticket use occurred on episode `0634e2ac53df6` / work
`145fe0e303563` at `2026-10-18T17:32:39.739556+09:00`. The target-bound
checkout and authenticated native `waitAndFree` transition confirmed the third
resource use; the isolated Source recorded grant expiry
`2026-10-21T17:31:58.911149+09:00`. The CLI then failed Viewer readiness with
`PageChangeTimeoutError`: no stable known layout within 20 seconds, Capture
`not_started`, zero pages, pending Item, and no artifact. The 23-hour minimum
cooldown ends `2026-10-19T16:32:39.739556+09:00`. No quota-consuming retry
occurred. A later direct run used the already-active grant without consuming a
resource; details are recorded below. Evidence:
`output/younganimal_work_ticket_tester/NORMAL_BATCH_0634_REPORT.md` and
`output/yanc-0634/younganimal/`.

A bounded read-only diagnostic on this already-granted exact episode confirmed
the canonical route/work header, positive authentication, and current native
`hasAccess=true`, `accessType=waitAndFree` state with a positive timer. It made
one direct load, blocked 25 non-GET/HEAD requests before dispatch, had zero
checkout mutations and zero click events, and closed its Page. Two existing
`SNAPSHOT_SCRIPT(pixelSlots=[])` observations 5.03 seconds apart were fully
sanitized to structural metadata. The first snapshot had one Viewer root but no
`#xCVPages` or seek control and failed parser root-selector validation. The
second had 21 wrappers and live seek value 21, min 1, max 21, step 2; the unique
Last marker was at slot 20 and the tail roles were CI/PR/PR/Good/Last at
16-20. Slots 1-15 were body-class candidates; only 1-3 had loaded/rendered
925×1329 canvases, 4-5 were loaded without canvases, and 6-15 had only
`-cv-page`. The earlier read-only snapshot was rejected because the standard
parser expected `seek_max=len(slots)-1` (20 for these 21 wrappers). A later
bounded public-seek probe on the exact active grant observed values 21, 19, 7,
5, 3, and 1 mapping to body slot 1; body 2-3; body 14-15; CI/PR 16-17;
PR/Good 18-19; and Last 20. The `standard_odd_body` profile recognizes a
conditional structural family: no top-empty flag; positive
`mode-has-pr`, `mode-has-comic-info`, and `mode-has-good-page`; exact lead,
contiguous odd body B>=3, and CI/PR/PR/Good/Last tail roles; and seek min=1,
max=wrapper_count, step=2. Every accepted member also requires exact marker
sets and selected wrapper centers at maximum, body, CI/PR, PR/Good, and minimum.
Live B=15 metadata (21 wrappers, body 1-15, tail 16-20) establishes the
observed structure. Its separate existing-grant direct Capture through END/ZIP
ran under the earlier count-specific `standard15_body` fix, before the current
parametric generalization. Live B=7 metadata (13 wrappers, body 1-7, tail
8-12) confirms its marker/center mapping but does not itself establish Viewer
readiness. A later existing-grant direct Capture on C781 completed B=7 through
END/ZIP on the current parametric implementation. Synthetic B=9 full Runner coverage passed. Python
parsing, JS capture geometry, and native proof apply the same contract;
unsupported shapes remain fail-closed. At this 2026-10-18 snapshot, a fresh
quota-consuming run through END/ZIP had not yet validated that path; the later
849 run is recorded in the current snapshot above. The public-seek
probe restored value 21, read metadata only, and made no capture, click, or
checkout. Evidence:
`output/younganimal_work_ticket_tester/readonly_viewer_diag_0634.json`,
`public_seek_metadata_0634_attempt3.json`, and
`saved_viewer_structure_0634.json`.

An independent direct Batch capture on the already-active grant for episode
`856137d88753b` / work `8246f8b8b2e6c` completed 28 pages through END and
produced a 28-member CRC-valid ZIP with zero click/checkout and no new ticket
use. It validates the existing-grant direct path only. Evidence:
`output/younganimal_work_ticket_tester/direct-one-shot-856.json` and
`direct-postflight-856.json`.

After the earlier count-specific `standard15_body` fix, direct Batch on the already-granted episode
`0634e2ac53df6` / work `145fe0e303563` also exited 0 and completed a new Run
with 15 pages through END. The Page audit recorded one owned Page, one goto,
and one main-document request, with zero reloads, off-target/series navigation,
commerce clicks, or checkout POSTs. The prior failed Run, Source grant/quota
timestamps, and Work last-consumed time were unchanged. The ZIP contained 15
ordered 925×1329 PNGs; CRC, decode, manifest order, Catalog completion, and
archive SHA validation passed. No per-image hash or source-native format claim
is made. Independent review passed. Evidence:
`output/younganimal_work_ticket_tester/direct-postflight-0634.json` and
`direct-preflight-0634-provenance.json`. This verifies direct capture with an
existing grant. At this 2026-10-18 checkpoint, fresh quota consumption through
same-Page END/ZIP remained pending; it was later verified on 849.

The second normal quota attempt, using the fourth ticket overall, was on episode
`c7819ded99f66` / work `5d1e949cd0b52` at `2026-10-18T18:33:53.283098+09:00`.
One exact wait-free click, target-bound checkout HTTP 200, and authenticated
native `waitAndFree` false-to-true transition confirmed resource use. The Source
grant expires at `2026-10-21T18:32:56.842671+09:00`; the same-work 23-hour
cooldown ends at `2026-10-19T17:33:53.283098+09:00`. The CLI then failed before
Capture with `PageChangeTimeoutError`; the Item remains pending with no pages,
END, ZIP, or Artifact. A bounded read-only follow-up on the active grant
verified exact work/auth/native state and a 13-wrapper profile. Public seek
values 13, 11, 7, 5, 3, 1 mapped to body slot 1, body 2-3, body 6-7, CI8+PR9,
PR10+Good11, and Last12. Marker flags matched. The current parser recognizes
this as a B=7 member of `standard_odd_body` only when its positive capability
flags, exact wrapper roles, marker phases, and selected centers validate. The
diagnostic observed nav-open and one splash
marker throughout, so it does not establish Viewer readiness. It made no click,
checkout, image read, or Capture call. Evidence: `output/younganimal_work_ticket_tester/normal-postflight-c781.json` and
`output/younganimal_work_ticket_tester/public_seek_metadata_c781_attempt1.json`.
No balance-delta claim is made. At this 2026-10-18 checkpoint, the original five uses were exhausted and the
user had authorized three additional candidate uses on `dd9facaba1704`,
`849948508c8bc`, and `4ba85f4c9e538`. DD9 had passed one-work Discovery and its
first normal Batch attempt failed before Page creation during Core/Playwright
CDP attach without consuming a ticket. The later DD9 and 849 attempts and the
current 7-use ledger are recorded in the current snapshot above.

On frozen implementation commit `f2d7ad8`, direct Batch on C781's already-active
grant exited 0 and captured 7 ordered 925x1329 PNGs through END. ZIP CRC,
decode, manifest order, Catalog completion, and archive SHA checks passed. The
old failed Run, Source grant/quota timestamps, and Work `last_consumed_at` were
unchanged. It used one Page, one initial goto, and one main-document request;
two same-target frame events were recorded with cause UNKNOWN. No commerce click
or checkout occurred. No per-image hash or source-native format claim is made.
Evidence: `output/younganimal_work_ticket_tester/direct-postflight-c781.json`
and `output/ydr-c781/runDB/precli-baseline.json`. This verifies existing-grant
capture only.

The final bounded read-only recheck of `77d27c1572ac7` matched the exact route,
work header `a3ca78e2ee97a`, and positive authentication. Natural
series-access responses had no target row; no current episode access record or
free-ticket/charge control appeared. Eligibility is UNKNOWN. The probe used one
canonical goto, no click or checkout, and no explicit series/other-episode
request. One main-document request and two same-target frame navigation events
were recorded; the latter's cause is UNKNOWN. First-party read/mission POSTs
and two off-target RSC reads generated during hydration were aborted before
network; one incidental other-episode-like GET API path and same-target reader
subpath GETs were observed. These were site-generated incidental requests,
not explicit probe requests. No retry or ticket use followed. Evidence:
`output/younganimal_work_ticket_tester/readonly-77-final.json`.

At the 2026-10-18 checkpoint, DD9 (`dd9facaba1704` / work
`06e1b9373ea6e`) had passed isolated one-work Discovery. Its first normal Batch
attempt failed at Core/Playwright CDP attach before Page creation, with no
resource use. After the user reported restarting shared Chrome, a standard
attach-only health check passed; the attach cause remains UNKNOWN. The second
attempt then failed closed as `work_ticket_unavailable` without click or
resource use. The third DD9 attempt consumed use six but failed before Capture
because the saved Viewer was an unsupported `mode-v`/`mode-single` shape without
the supported seek/CI layout. The grant and Work timestamp persisted; no capture
support was added for that shape.

The subsequent 849 (`849948508c8bc` / work `71460b2b6686f`) one-work Discovery
and normal Batch passed, consuming use seven and completing same-Page Capture
through END/ZIP. At that checkpoint, two of three additional authorizations
were consumed;
`4ba85f4c9e538` remains unopened and unused. A zero-resource DD9 public-mode
probe did not click because its exact control was not visible/in scope and one
unknown mutation was aborted; no Viewer mode change or capture support was
established. The complete evidence at that checkpoint is summarized in the
following historical snapshot; the current eight-use ledger is at the top of
this note and in `runbooks/younganimal-work-ticket/PROGRESS.md`.


## Registration and crawl entry

The CLI registers Younganimal for Discovery, manual Crawl, Batch adapter, and
Batch Site Policy. All paths use the repository's shared CDP BrowserSession and
Playwright Page; the adapter does not launch Chrome or select a profile. The
policy selects available free sources, paid sources with a future observed rental
grant, and explicitly identified work-ticket quota sources. Batch supports the
non-consuming `direct` strategy and the explicit `quota + work_ticket` entry; the
quota path remains bound to the strict external work/episode identity. No shared
Core or Catalog schema changes were made.

Manual Crawl requires:
- source URL: the exact canonical episode URL, for example
  https://younganimal.com/episodes/55889b8a851cb
- environment value YOUNGANIMAL_WORK_URL:
  https://younganimal.com/series/&lt;13-lowercase-hex-work-id&gt;

Both manual and Batch Crawl navigate directly to the canonical episode URL.
The configured manual work URL validates the episode header's exact same-work
link; it is never visited by Crawl. The adapter does not traverse or read episode
listing rows during Crawl. Exact route/header identity and the strict body-canvas
viewer parser provide entry proof. A visible `.ep-main-content.mode-charge` /
`.ep-main-content .ep-charge`, or a visible reader control for すぐ無料で読む,
待つと無料で読む or この話をレンタルする, stops entry without clicking.
The check repeats before viewer observations. Missing/unknown reader state
remains fail-closed. No login, ticket, coin, point, purchase, rental activation,
or next-episode action is performed.

## Discovery

Discovery accepts only a canonical first-party series URL matching
https://younganimal.com/series/<13-lowercase-hex-work-id>. Episode seeds are
rejected before AccessGuard startup/navigation because only a series URL defines
the supported Discovery scope. Episode URL parsing remains available for public row identities and
bounded-scope boundaries. This is a Lead-approved safety deviation from the
original episode-seed plan; the work ID from the supplied target is an example,
not an allowlist.

The Discovery adapter validates the canonical work title and buffers the complete
declared range map before yielding. It checks each route against the same range
map, declared row count, unique episode IDs, and first-party canonical URLs.
Output order is latest-first while global display positions remain the
oldest-first whole-work indices. Inclusive bounded scopes retain global positions.
An optional epListUser root is awaited until `mode-loading` clears within 12
seconds. Its canonical unique episode IDs and titles are validated; matching
public/user identities must have identical normalized titles. User rows supplement
public access observations but never add Items or positions. Duplicate IDs,
malformed identities and conflicting titles fail buffered Discovery. User rows
outside the current public range are not yielded.
The observed 最新話から control is accepted
only at the same-work /new path. An optional ... placeholder is ignored only when
the raw anchor has no href; unknown controls and route changes fail closed.

One exact row-local 無料 label maps to free. A matching user's exact normalized
`レンタル中 閲覧期限 D日+H時間` label maps to paid with
`access_granted_until = observation time + D days + H hours - 1 hour`.
This is a conservative lower bound, not exact expiry; days 0..14, hours 0..23
and a positive lower-bound duration are required. Other countdown formats,
near-expiry durations, 今なら無料, 待つと無料, blank, repeated and unrecognized
labels remain unknown. Free takes precedence over rental on the same identity.
Unknown observations preserve a stored grant; a positively observed exact
denial or valid grant refreshes it. Policy selects only a strictly future,
timezone-aware paid grant as non-consuming `direct` / `active_rental`;
unavailable, expired and malformed grants are excluded.

During the existing canonical work-listing traversal, Discovery observes the
site's natural `GET /api/series/access` and `GET /api/auth/session` responses;
it issues no additional request. A positive integer session user and an exact
response `seriesAccess.seriesId` matching the canonical work are required
before joining episode rows by ID. Only `accessType=waitAndFree` is classified:
`hasAccess=false` with a missing or exact zero timer is a `quota` candidate;
null, positive, or malformed timers remain unknown. An exact active row with a
valid positive `timeRemainingInSeconds` is a manually used ticket grant; its
conservative expiry is request-start plus timer seconds minus one, shortened
when the account rental label provides an earlier lower bound. Other access
types, contradictory timer states, foreign/duplicate or missing rows, and
unavailable authentication remain unknown. Native observations do not
override an exact free label or active rental. The live listing
observation confirmed this schema and positive auth; no ticket was used during
Discovery.

The Younganimal Policy exposes one `work_ticket` resource pass scoped to a work,
with quota limit one and a local minimum 23-hour cooldown after observed
consumption. A longer configured cooldown is honored. The adapter supports only
explicit quota/work_ticket entry: it verifies the canonical target, exact work
header, positive auth and current native `waitAndFree` state before considering
one exact free control. Already-active grants are non-consuming direct access
in normal Batch and skip grant-only. A single retained control is clicked once
after a trial and final same-Page checks; repeated attempts are forbidden.
Consumption is exposed immediately after a post-click target-bound successful
checkout plus the exact same-work/episode native false-to-true transition. A
valid positive native timer supplies a conservative expiry; otherwise expiry is
unknown. Normal Batch hands that same Page to the unchanged Viewer/Capture/END/ZIP
flow; grant-only creates no capture/package and leaves the Item pending. The
route guard aborts and records recognized same-work read-only RSC GET prefetches
without failing the episode run. Phase 04 observed one off-target episode `GET`
fetch with the `_rsc` query key and an `rsc` header. The exact same-origin
canonical route signature is now recorded and aborted before reaching the
network handler, without retaining or using query/header values or its
response; the selected episode run may continue. The guard retains an internal count capped
at 16 and up to 16 sanitized paths. Known-page counts/paths are also exposed
through diagnostic metadata. Missing either marker,
another method, resource, navigation, or frame shape, other series routes,
off-target navigation, unexpected subframe navigation, and unknown RSC routes
remain fatal. Immediately before the action latch, both route evidence and
recorded 403/429 access stops are checked again. The post-consumption route-drift failure branch remains covered by a synthetic
regression. The later live 849 normal run passed with the reviewed route guard
enabled, but did not itself trigger route drift. Exact other-episode page paths
are classified before the generic static-resource pass-through; asset suffix
paths keep their previous handling.
The later zero-dispatch guard trace also observed same-origin RSC GET fetches
for `/` and `/store_items/series/<positive-id>/<positive-id>`, plus Stripe
controller/m-outer and Facebook `/tr/` third-party subframe navigations. These
route families now have narrow abort-only predicates; requests never reach the
downstream test/application handler, and bounded diagnostics store paths only.
Stripe matching ignores URL fragments. The earlier zero-dispatch trace omitted
request-fragment presence; the later 849 production audit classified an observed
subframe as `facebook_known_subframe_navigation`. The audit records that bounded
classification, not the fragment value. No resource use is attributed to the
zero-dispatch trace.

A 2026-10-19 read-only investigation of failed grant-only Item/Source `33083`
(episode `f14dc7e0ac3f4`, work `ce92c1172487c`) initially reproduced an unsupported
same-origin `GET`/`fetch` RSC prefetch to `/store_items/1888`, with both `_rsc`
query and `rsc` header markers, on the main frame without navigation. The
pre-fix guard classified this as fatal `unknown_rsc_page_route`; its abort-only
store predicate covered `/store_items/series/<id>/<id>`, not individual
store-item pages. The updated predicate and verification are described in the
current snapshot above. The selected episode URL remained exact. The bounded probe
made one navigation, observed zero click events and zero rental-checkout
attempts, and aborted 28 non-GET/HEAD requests. Sanitized evidence is
`output/younganimal-error-33083-readonly.json`.

The original metrics run `32012afaa3b14a07a3ba1c8f9d0dd10a` failed before the
adapter's ticket-action latch with `UnknownPageStateError`, no retry, no
403/429/5xx responses, and `resource_consumed=null`; diagnostics retained the
exact target URL and Capture `not_started`. Its fatal guard reason/path was
not persisted, so the reproduced store prefetch is a supported explanation,
not proof of the original blocked request's exact identity. No ticket retry or
Catalog update was made during the investigation or the later fix verification.

An earlier seven-file Younganimal regression selection passed 313 tests with 0
skipped: capture+adapter passed 162 (5 existing warnings), and the remaining
policy/live-access/discovery/batch-unit plus Discovery-browser files passed 151
(203 existing warnings). The final seven-file selection later passed 322 tests;
see the current verification snapshot above. The route-drift fixture triggers the exact
series main-frame navigation only after positive consumption proof and asserts the guard's observed rejection. Phase 04
grant-only and both-mode before-Page/site cooldown verification passed. One
normal Batch ticket grant was confirmed; its first Viewer attempt failed before
Capture. Direct Batch on that episode's already-active grant later completed 15
pages through END and passed ZIP/Catalog validation with no further resource
use. The conditional `standard_odd_body` signature is implemented consistently
in Python parsing, JS geometry, and native proof, and passed independent review
plus focused synthetic checks. The live B=7 existing-grant direct capture
passed on the current parametric implementation; the B=15 existing-grant direct
capture ran under the earlier count-specific `standard15_body` fix, before the
current generalization. Synthetic B=9 Runner coverage passed. At that checkpoint, fresh quota-consuming
normal END/ZIP remained pending; the 849 result is recorded in the current
snapshot above. The full repository suite was not run.
Full Discovery buffers before yielding, so an incomplete
traversal cannot mark unseen sources unavailable. Maximums are 100 ranges and
3,000 rows.

Incremental Discovery refreshes the entire validated requested scope rather
than stopping at a newest known streak: old episodes can gain or lose rental
access. The adapter's existing stop hook returns CONTINUE. All ranges were
already buffered before yielding, so this adds no browser requests. Incremental
still does not reconcile unseen sources as unavailable.

Discovery waits 3 seconds before every numeric range route. A Playwright
DOMContentLoaded timeout is retried only when the exact current attempt proves one
matching main-frame document request and its matching response is HTTP 200, and
the current route remains exact after the timeout and again after a 2-second
backoff plus AccessGuard check. There is at most one retry per route and two
retries per work. Unknown response evidence, non-200, redirect/drift, other
Playwright errors, and access stops are not retried. Request/response listeners
are removed on every path, and no response body or retry header is read. The
earlier /3 timeout cause remains unknown; this recovery does not assign a cause.
AccessGuard cleanup is bounded. After the native access observer drains its
bounded response tasks, Discovery checks AccessGuard again before constructing
or yielding any records. A fatal response arriving during the final body drain
therefore leaves the full listing uncommitted.

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

The shorter top-empty variant also supports even N and max=N-1, only with the exact
horizontal/PR/CI/Good capability set, absent vertical/single modes, exact blank and
five-tail roles, and derived odd body B>=3. It checks every selected center and phase;
seek 5 is last body+CI, seek 3 is PR/PR, and seek 1 is Good/Last with Last+PR.
Item 33100's eleven-body live verification and bounds are recorded in the current snapshot.

### One-body standard layout

`standard_one_body` is the verified seven-wrapper shape: top PR 0, body 1,
CI 2, PR 3-4, Good 5, Last 6, range min=1/max=7/step=2. It requires the same
positive horizontal/spread/RTL and PR/CI/Good capabilities and exact role/no-tail-
canvas proof as the two-body profile, without top-empty/vertical/single modes.
Every selected center and phase is checked: 7 first/top-PR with body 1, 5 CI/PR
with CI+PR, 3 PR/Good with PR, 1 Last-only with a unique visible/centered marker.
END requires the sole frozen body slot to have been captured. The shared native
and CI geometry helpers distinguish the one/two body maps while retaining strict
source/replay, identity/write/epoch, disjoint CI geometry and final-center proofs.
The current snapshot records max_pages=1 live source RGBA/ZIP/Catalog validation
and parameterized rejection tests. Unproven shorter/other shapes remain unsupported.

### Two-body standard layout

`standard_two_body` admits exactly the observed two-body/eight-wrapper shape
with range min=1/max=7/step=2, top PR 0, body 1-2, CI 3, PR 4-5, Good 6 and
Last 7. The root must be horizontal/spread/RTL with PR/CI/Good capabilities,
without top-empty/vertical/single flags; every role class and non-body no-canvas
condition must hold. Every phase and selected center is checked: 7 first/top-PR,
5 second body/CI with CI+PR, 3 both PRs with PR, 1 Good/Last with Last+PR and a
unique visible/centered Last marker. Both body slots are required before END.
Native capture and CI mutation exceptions use this same map and existing strict
source/replay and disjoint geometry proofs. No arbitrary short/incomplete layout
is accepted. The current snapshot records the two-page source RGBA/ZIP/Catalog
live verification with max_pages=2 and the synthetic rejection/coverage tests.

### Horizontal layout with one trailing PR

`standard_single_pr` supports the separately observed four-tail CI/PR/Good/Last shape,
with an exact top-PR lead, no top-empty flag, contiguous even body B=N-5>=4, horizontal/
spread/RTL and positive PR/CI/Good capabilities, no vertical/single flags, and range
min=1/max=N/step=2. Non-body wrappers have exact classes and no canvases. Unlike the
two-PR profiles, seek 3 centers PR/Good and seek 1 centers only Last, with Last-only phase
and a unique visible/centered marker. Maximum has first/top-PR; body pairs have no phase
flags; seek 5 captures the final single body beside CI with CI+PR. All selected centers
must match, all body slots must be captured before END, and native capture retains the
same source/replay/identity/mutation proof. CI widget mutations require the existing
strict disjoint geometry checks using the derived CI index. Live B=6/N=11 evidence for
Item 34211 and synthetic B=4 coverage are recorded above. Other unknown shapes remain
unsupported; neither counts nor episode IDs are allowlisted.

### Horizontal layout with three trailing PRs

`standard_three_pr` uses a top-PR lead, contiguous even body B=N-P-4>=4,
CI, exactly P=3 empty PR wrappers, Good and Last; range is min=1/max=N/step=2.
It requires horizontal/spread/RTL and PR/CI/Good capabilities with no top-empty/
vertical/single flags, exact non-body classes and no canvases. The shared PR-tail
proof helper supports explicit P=1/P=3 only and derives all role indices and
final body/CI seek P+4. For P=3, seek 7 is final body/CI with CI+PR, seeks 5/3
are PR/PR then PR/Good with PR, and 1 centers only Last with Last-only and a
unique visible/centered marker. Initial maximum and body-pair flags/centers are
also exact. END still requires complete frozen body coverage. Native source/
replay, identity/write/epoch and CI disjoint-geometry checks remain. The current
snapshot records existing-grant live B=10 evidence, synthetic B=4/B=10 captures
and rejection of unobserved PR counts and incorrect CI/interstitial phases.

### Horizontal no-top-PR layout with odd body

`top_empty_no_pr_odd_body` uses the positive top-empty flag and an exact empty
slot 0 without PR markers or a second blank. It has contiguous odd body B=N-6>=3
and exact CI/PR/PR/Good/Last tail with no canvases, horizontal/spread/RTL and
positive PR/CI/Good capabilities, and no vertical/single modes. Range is
min=1/max=N/step=2, whereas the existing even-body no-top-PR layout uses max=N-1.
At maximum the lead and body 1 are selected with first-only; intermediate seeks
through 7 select body pairs without phase flags. Seeks 5/3 select CI/PR then
PR/Good with CI+PR then PR flags, and 1 selects only Last with Last-only and a
unique visible/centered terminal marker. Every selected center is checked. END
requires complete frozen body coverage; no initial blank skip is inferred.
Native capture keeps exact source/replay/node/write/epoch proof and requires
final centers at selection/postproof, even when the incoming draw occurs before
translation. Unproven native candidates retain the existing rendered fallback.
The current snapshot records B=29/N=35 live evidence, all source RGBA/ZIP/Catalog
checks, initial audit limitations, synthetic B=3/B=7 tests, and unsupported shapes.

### Horizontal top-empty layout without a CI slot

A bounded public-seek metadata probe on already-granted episode
`8d92e88ab93ec` observed a distinct horizontal `top_empty_no_ci` profile:
15 wrappers, seek `min=1`, `max=15`, `step=2`; root flags for horizontal,
spread, RTL, top-empty, PR, and Good; and no comic-info, vertical, or
single-page flag. Slot 0 is the empty lead-in, body slots 1-10 are contiguous,
and the tail is PR 11-12, Good 13, Last 14. The selected centers were 0+1 at
15, 2+3 at 13, 4+5 at 11, 6+7 at 9, 8+9 at 7, body 10 plus PR 11 at 5,
PR 12 plus Good 13 at 3, and Last 14 at 1. All ten body canvases were observed
ready when selected. The probe used only the public seek control and metadata;
it did not read image pixels or run Capture.

The parser, capture geometry, and native proof use the same strict structural
contract: `ci_slot=None`, explicit PR/Good/Last roles, `B = wrapper_count - 5`
even and at least four, exact horizontal/root flags, exact role classes and
seek range, and the observed center/marker state at each phase. The profile
starts with body slot 1 at maximum seek; it does not skip the lead-in as a
blank-only page. At the minimum it accepts END only after all derived body
slots were captured, the unique `#xCVLastPage` marker is visible and centered,
and the final Last wrapper remains centered. No CI mutation exception is
available in this profile; the existing native identity,
generation/write, replay-pixel, frozen-role, readiness, and post-encode proofs
remain unchanged. Synthetic B=6 and B=10 full Runner fixtures pass ordered
capture, pixel comparison, END, and ZIP checks. Marker identity, parent,
visibility, viewport, role, and fake-CI mutation cases fail closed. An
existing-grant direct Batch on 8d later parsed the final state as
`top_empty_no_ci`, B=10, N=15, `ci_slot=None`, seek=1, and END. The same Page
completed 10 ordered PNGs at 925x1329; ZIP CRC, decode, manifest order and
metadata, Catalog completion, and Catalog/archive SHA checks passed. The
archive SHA-256 is `c21eabe0f0c67459bf95fb789c5175b3d865d79d30621f4a177465e532d04772`
(11,643,064 bytes). No source-native format or per-image-hash claim is made.
The direct run used one owned Page and one adapter `goto`, with no reload,
commerce click, or checkout POST. The audit recorded one main-document request
and two frame-navigation events whose cause is unknown; natural read-completion,
mission/reward, and pixel/analytics traffic also occurred, with no claim about
all resulting site-side effects. Evidence: `output/younganimal_work_ticket_tester/direct-8d-fix/postflight.json`,
`output/younganimal_work_ticket_tester/direct-8d-fix/sentinel.json`,
`output/younganimal_work_ticket_tester/direct-8d-fix/page-audit.jsonl`, and
`output/younganimal_work_ticket_tester/direct-8d-fix/pre-package-manifest.json`.

The separate `no_lead_no_ci` variant starts its body at slot 0 and requires
absent top-empty capability, odd B=N-4>=5 and the same exact four-tail roles.
At maximum seek both slots 0 and 1 are body pages; no blank or lead is skipped.
Its remaining phases and Last proof match the no-CI table above. Current
Item 35814 live evidence and output-format limits are recorded in the current
verification snapshot. The top-empty even-body variant retains slot 0 as its
empty lead and B=N-5; removing a flag without changing roles is rejected.

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

## Current verification status (2026-10-19)

At this historical checkpoint, Phase 04 had passed independent review. The
seven-file Younganimal selection then passed 322 tests, 0 skipped, with 207
existing pytest-asyncio warnings; Ruff and diff checks passed. The full
repository suite was not run. The separate fresh-
quota normal run on 849 completed same-Page Capture -> END -> ZIP, with a
completed Catalog Item and independently validated archive; its exact evidence
and limitations are in the current snapshot above and
`runbooks/younganimal-work-ticket/PROGRESS.md`.

The ledger at that checkpoint recorded seven uses (five original plus DD9 and
849). Two of three additional uses were consumed; `4ba85f4c9e538` remains
unopened and unused.
Existing-grant direct runs on 856, 0634, C781, and 78 passed END/ZIP. Normal
quota attempts on 0634, C781, 78, and DD9 each persisted resource use but failed
before artifacts. DD9's third attempt failed before Capture because its Viewer
had unsupported `mode-v`/`mode-single` classes and no supported seek/CI layout;
that DD9 layout remains unsupported. The missing 78 action sentinel leaves
its click/checkout counts UNKNOWN. The earlier incomplete 106-test run had an
unknown hang cause and was superseded by the saved 322-test run; no timeout/RAF
behavior was changed.

The fresh 849 run recorded one Page, one Python initial goto, zero reloads,
two same-target main-document requests, and four same-target navigation/frame
events whose cause is UNKNOWN. Seven off-target episode RSC GETs were aborted.
Natural site traffic occurred; this is not a claim that all traffic was zero or
that every initiator is known. No balance delta, source-native format, or
per-image hash is claimed.

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

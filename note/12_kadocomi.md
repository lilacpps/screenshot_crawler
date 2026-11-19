## Discovery target pacing (2026-11-13)

CLI/GUI Discover uses shared `discovery_inter_target_delay_ms` (3000 ms in
the root YAML) after this target closes, only before another target starts.
The first/single/final target adds no delay; site changes retain the previous
site setting. Existing listing-page waits remain independent. See
[shared runtime details](00_core.md#phase-1-runtime-settings--pacing).
Synthetic CLI/worker ordering is verified; live timing is unverified.

## Stage07 complete-list investigation (2026-11-03)

Preview/detail now supports continuous URL-bound ranges and open oldest/newest
ends. Static Work native first/latest arrays must have equal exact declared
counts, unique work-bound IDs/UUIDs, strictly ordered explicit episodeNo and
exact reverse projection; a stable second read and canonical Work are required.
An immutable NativeListingProof binds declared count and the whole ID/position
projection into the GUI digest. Existing default contiguous proofs remain strict.
Native gaps are retained, never compressed/filled. Preview uses one guarded Work
document GET with inline/external scripts disabled; no expand/reader/access
classification/store. Public rows show unknown access; inactive native rows show
公開終了. SelectionPlanner/WorkDraft reject holes, empty assignments and disjoint
selections that need exclusions. Exclusion replay remains unsupported and is
rejected before Catalog or page activity. Ordinary native/legacy Discovery,
positions, classification and capture are unchanged. Freshness, ownership,
Watchlist CAS and Catalog snapshot checks remain mandatory for GUI save.
KC_004915_S has123rows/25active/native1..127 gaps15/17/96/102; the collapsed
active DOM alone is not the complete site-provided inventory. Current native
GUI and regression evidence/limits are in the Stage07 PROGRESS:181related passes,
native GUI twice, full6884 current passing witnesses/0skip via partitioned runs
and an18-test rerun of the corrected capability expectation. No live Full/Capture
or access-classified preview is implied; individual exclusions remain unsupported.

The Stage07 GUI preview limitation does not disable existing URL-bound YAML
scopes. Read-only verification of KC_002911_S on2026-11-03 found109 native
entries,4active, with internal positions1..122 and13gaps. Visible 第108話 is
position121 and episodeKC_0029110010900011_E; 第109話 is position122. The existing
latest-first selector with only through_url set to the canonical 第108話 URL
selects those two entries inclusively. Future newer entries remain within that
one-sided scope. Never use visible chapter108 as internal position108 or infer
an episode URL from its label. This probe read the guarded Work document twice
and exercised identity-only selection; it did not execute DiscoveryService,
Capture, reader navigation, store writes or access classification. Existing
from-only/through-only/both/singleton selector tests4passed/0skip. The subsequent
GUI follow-up uses this native proof to edit/save the same boundary. In the Work
editor choose開始=第108話, uncheck最古から, keep新着も含める checked, then担当範囲を設定.
URL registration detail remains draft-only until the parent's atomic save.

## Watchlist URL registration hook (Stage 06 follow-up, 2026-11-03)

Work entry and same-prefix episode→work / supported query removal preserve
URL-derived Work identity. Optional detail metadata now uses the shared
registration_document guard (retained until Page close), plus exact canonical.
The exact dehydrated query key `/api/contents/details/work` with workCode must
bind native work.code to the requested Work; native work.title is preferred.
Unique og:title with the known site suffix remains a fallback. Native/og title
or Work-code disagreement blocks. Comics/volume labels are never stripped by
guessing, so legitimate digits and official subtitles are preserved.
Live 2026-11-03: KC_004915_S「夫婦以上、恋人未満。」、KC_005686_S
「シンコンクエスト 魔王の娘は真面目勇者を堕としたい♡」verified, from
user inputs with episodeType=first. The latter is the official full Work name;
the requested shorthand is not hardcoded as a replacement. No episode/viewer
navigation is needed for Kadocomi. Complete-list preview remains Stage 07.

Strict new-entry validation stays in registration/resolver.py and site-owned
hooks. Metadata is optional (GUI checkbox initially on); safe canonical URLs
with missing metadata retain explicit human confirmation, while identity or
navigation contradictions block. Human labels never become site evidence.
Each document observer denies scripts/images/iframes/POSTs and redirects and
keeps its guard until the caller closes the dedicated shared-CDP Page.
Registration performs no ticket/point/purchase/Capture, full Discovery or
Watchlist/Catalog/ZIP/history write. Tests use artificial isolated data. URL/label
samples from operational Watchlist were read only with the user's explicit
permission, never used as a runtime title lookup or copied into fixtures.
Existing Discovery/scope/order/segments/access/capture behavior is unchanged.
Evidence and test/review results: runbooks/watchlist-url-registration/PROGRESS.md.


Registration document observation now replaces response CSP with script-src
'none', object-src 'none', worker-src 'none' and form-action 'none'. This blocks
inline viewer bootstrap as well as external scripts, while inert JSON and static
metadata stay readable. The route guard remains installed until dedicated Page
close; lifecycle tests inject timers via Page.evaluate independently of CSP.
This affects metadata observation only, never ordinary Discovery/capture Pages.
Zeblack's fixed public metadata API does not navigate an HTML Page.

# 12. Kadocomi current implementation

## Shared Catalog v7 / automatic acquisition scope (2026-10-23)

The site behavior below uses Catalog v7 and an explicit matching Watchlist.
Discovery never migrates Catalog implicitly. Successful Discovery automatically
reflects the current key's acquisition flags; Incremental enables observed
Sources, while failed runs preserve existing flags. Batch uses current flags
without requiring a sync marker, matching fingerprint, or complete evidence.
Temporary extra acquisitions and provisional ordinals are accepted. Target
`enabled` controls Discovery only. `watch scope-sync` remains optional strict
whole-Work maintenance; access/resource and output guards are unchanged.
See `note/00_core.md` for the current shared contract. This common change has
synthetic/local-browser coverage; it has not been live-verified on this site.

Current shared simplification (2026-10-24): GUI/Batch/audit/renumber use current
acquisition flags and key order directly, with archive_order applied at ZIP naming.
No sync stamp or complete-listing proof gates ordinary operation or final renumber;
intermediate numbers may be provisional. Explicit scope-sync remains for deletions
and repair. DB stays v7 and no JSON fields are added. File/identity safeguards and
site-specific access/capture behavior are retained; no new live claim is made.

Kadocomi now provides a strict native-history inventory path when a target has
`discovery_scope` or `archive_order`. It binds the requested work to the exact
native query and validates both site-provided episode arrays, their counts,
identities, UUIDs, types, explicit `episodeNo` order, and reverse ordering.
`supports_bounded_discovery` uses those validated native identities and
positions for inclusive boundaries. A normal Full publishes the complete
observed inventory only after safe exhaustion; Incremental, failed, and
early-closed runs do not publish proof. Successful Full also reflects classified
flags for its key, while Incremental enables observed Sources. Missing Sources
remain blockers for strict optional reconciliation, not ordinary Batch.

This new proof is bounded by current site evidence: it covers the native lists
observed for `KC_004915_S` (123 rows) and `KC_011605_S` (33 rows), not a claim
that every episode ever published is represented. Native episode numbers have
gaps (the first sample includes positions up to 127); missing numbers have no
observed Source identity and must not be synthesized. Inactive native rows are
retained as unavailable/unknown Sources with their observed positions. Existing
Catalog Sources absent from the validated native list keep their historical
position and cause scope sync to block. This position-retention statement does
not override ordinary Full Discovery availability reconciliation. The old
unconfigured unordered path remains current-public-only and does not infer
global display positions. The native parser accepts at most 1,000 entries and
a 2,000,000-byte response body.
Leading or all-inactive placeholder patterns have not been established and
remain fail-closed; no position or Source is inferred for them.

A Full run still invalidates strict maintenance proof/sync state as appropriate,
but Batch does not use that marker. Continue from Discovery to Batch directly;
optional scope preview/apply can reconcile an entire Work without Discovery.
No Source is moved between keys or deleted.

Optional strict maintenance examples (scope-sync is not required for Batch).
Use the same isolated Catalog, Watchlist and library paths under COPY_ROOT:

    python -m screenshot_crawler.cli catalog migrate --catalog <copy/catalog.sqlite> --backup-dir <copy/backups>
    python -m screenshot_crawler.cli watch scope-sync --watchlist <copy/watchlist.yaml> --catalog <copy/catalog.sqlite> --work-key <work-key> --dry-run --json
    python -m screenshot_crawler.cli watch scope-sync --watchlist <copy/watchlist.yaml> --catalog <copy/catalog.sqlite> --work-key <work-key> --apply --json
    python -m screenshot_crawler.cli batch plan --site <site> --catalog <copy/catalog.sqlite> --watchlist <copy/watchlist.yaml> --library-dir <copy/Books>

The scope-sync apply example can also follow a successful opt-in native-history
Full Discovery for scoped or archive-ordered Kadocomi work. Batch plan remains
read-only; use the same copy paths for any separately authorized execution.

## Status (2026-10-22)

P1 Discovery, P2 native capture, P3 direct-only policy/CLI/Batch, and P4 Tester/live-evidence Reviewer/Lead gates passed for seven observed reader layouts using six strict adapter profiles; the mixed-final profile supports two reviewed recommendation forms. The final P4 sweep completed all 15 selected target episodes and a normal CLI control retest for Episode 22.2. Its earlier control attempt failed before capture with the unchanged beginning-PR guard; the cause is unknown and the failure remains in history. Final documentation review PASS (Reviewer BLOCKING=0; Lead accepted bounded scope). Exact P0/P4 evidence, tests, hashes, and limits are in `runbooks/kadocomi/PROGRESS.md`. Unobserved reader layouts remain unsupported. Current Discovery classifies validated public rows without restriction flags or deadlines as free for all work IDs, following the user-confirmed Kadocomi convention.

Current capture supports the explicitly observed layouts and strict profiles described below.
The latest 40-candidate maintenance begins with Item 36662 and is described below.
The additional `paired_first_double_end` profile was verified on
`KC_011605_S:KC_0116050001200031_E` (第12話-3, Item/Source 26200).
Its live inventory is eight RTL pairs, one final singleton with exactly one
main-wrapper PR `n=2`, and two consecutive empty main END slides, each owning
`n=1,n=2`. No beginning slide, initial PR, or secondary recommendation exists.
The profile requires at least one pair, the final singleton, exactly these four
main END markers, valid marker ownership/geometry, and no extra content/slides.
After all slots are captured, a guarded ordinary ArrowLeft must advance exactly
once to the first END. The second END remains inactive and is never captured.
PR markers participate in snapshot stability and both native/Python async-change
checks. Unknown topology, missing/changed markers, skipped/no-advance turns and
content at either END fail closed. Core, native source proof and access policy
are unchanged by this capture extension; current no-deadline eligibility is
described in the Discovery section below.

Fresh bounded source proof at the failed run's 1904x985 viewport captured all
17 native WebP slots (1284x1825) and observed exact final index 8 -> first END
index 9 with second END index 10 inactive. Normal CLI `batch run --limit 1`
then completed the exact target in an isolated online-backup Catalog
(CrawlRun 9370, END, one ZIP Artifact). All ordered ZIP members passed CRC and
decoding and matched fresh source SHA-256, length and dimensions. The source
probe uses production native-capture proof, not an independent observer.
At that earlier verification the original Item remained pending with its two failed runs preserved. Evidence:
ignored `work/kadocomi/work011605-20261013/`. The original seven-layout P4
independent gates above do not claim independent review of this extension.
All affected Kadocomi unit and browser integration tests passed: 196 passed,
0 failed, 0 skipped (274.96 seconds; 9 existing asyncio deprecation warnings).
Global Ruff and diff checks passed. Full repository/Research suites and other
live episodes were not rerun for this site-local change; see the progress ledger
for the exact selection and the preceding historical full-suite baseline.

The integration combines the main-branch Kadocomi fixes with the
ComicFUZ feature branch. Before the additional double-END fix, its native
capture and reader acceptance rules matched main commit `470ba45`.
The 2026-10-13 Episode 7.2 failures
(`item=source=26187`) ran on the older `feat/comicfuz-adapter` branch, which
diverged before the direct-entry and PR-layout fixes. At the failed run's
1906x987 viewport, one current live snapshot with slot counts
`[1,2,2,2,2,2,2,1,0,0]` reproduces the exact spread-shape error with that old
adapter and passes as `content_first_final_pr` with the integrated adapter.
This is a missing-fix integration issue, not evidence of a new reader layout.

A fresh normal CLI Batch run using an isolated online-backup Catalog completed
the exact Episode 7.2 target with 14 pages and explicit END. All ZIP members
passed CRC and decoded as 835x1200 WebP; every ordered hash, length and dimension
matched the prior P0 source proof. This comparison is against prior live source
records, not a fresh independent Blob/RGBA audit. At that earlier verification the original Item remained
pending with both failed runs preserved. Evidence is under ignored
`work/kadocomi/reader-hydration-20261013/`; the directory name reflects the initial
hypothesis, not the established cause. Current test results are in the progress
ledger. When running another feature branch, synchronize these existing fixes
before diagnosing the same topology as unsupported.

Two additional paired-first profiles were verified on `KC_011605_S`:

- `paired_first_pr_end`: all content slides are RTL pairs (第12話-2: 16
  pages; 第12話-1: 14). The next empty slide owns exactly one main-wrapper PR
  `n=1` and main END `n=2`; the following final empty slide owns main END
  `n=1,n=2`. No beginning, secondary recommendation or extra slide is accepted.
  After every source slot is captured, the last ordinary overlay turn must
  settle exactly on the empty PR/END slide. Within the same bounded transition,
  its stable inventory/metadata, visible target and focus are checked before
  exactly one ordinary ArrowLeft reaches the next paired END. The intermediate
  empty slide is never captured or treated as completion; no advance, skipped
  slides, missing/changed markers or early END fail closed.
- `paired_first_final_pr`: pairs from the first slide, a final singleton owning
  only PR `n=2`, an empty main paired END and zero or one recognized secondary
  recommendation (第11話-3: 21 pages with recommendation; Episode 4.2 below: 7 pages without).
  All slots must be captured before one guarded ArrowLeft reaches the paired
  END; an existing recommendation remains inactive.

Both profiles require exact marker classes, numbers, ownership and positive
contained geometry, no content at/after END, complete ordered source inventory,
and PR stability during snapshot settlement and native/Python async capture.
Core, native WebP source proof, access eligibility, pacing, max-pages and
same-content guards remain unchanged. No-deadline access follows the current
Discovery contract below.
Fresh bounded source probes used the production native-capture proof, not an
independent observer. Exact routes, output audits and test results are recorded
in `runbooks/kadocomi/PROGRESS.md`.

A third maintenance variant, `direct_first_final_pr`, was verified on
第3話-3/-2 (26227/26228, 20/16 pages). Their first slide has one directly typed
`canvas._root_bx4cr_1[data-type=contents]` inside the unique known beginning root,
which owns no PR marker. It is a real source page, not an empty beginning slide.
It is followed by pairs, a final singleton owning the only main-wrapper PR n=2,
an empty paired main END and one secondary recommendation. The first captured
source is followed by one guarded ordinary ArrowLeft to exact index 1; final
ArrowLeft reaches the paired END, leaving the recommendation inactive.

The native DOM collector recognizes a directly typed canvas only when it is
the sole contents node on the first slide. Adapter acceptance additionally
requires one of the explicit direct-first profiles and validated beginning ownership/geometry; direct
canvases elsewhere, duplicates or unknown beginning/END topology fail closed.
Native capture still requires the original Blob, full-frame identity draw,
matching source/canvas RGBA, bounded budgets, ordered slots and async stability.
No screenshot/re-encoding fallback or synthetic page is introduced. Native
signature and Python settlement include the direct-first role and owner.

The previous inventory sweep did not establish support for all 29 episodes.
Seven rows failed collection; only two were rechecked before the prior report.
The five unrechecked rows included 26207, which still failed. The new sweep and
full Batch/ZIP scope are recorded below; prior all-supported claims are withdrawn.
Five representative live episodes completed normal CLI Batch/ZIP (16/14/21/20/16
pages). All 87 ordered members matched fresh source hashes, lengths and dimensions
and passed CRC/decoding; archive hash/size matched Catalog Artifacts. The original
five Items were pending at that verification; only dedicated Catalog copies were completed. Other
works and a separate independent source observer were not tested.

Previous paired/direct-first maintenance validation: all 246 Kadocomi unit/browser integration cases
passed, with 0 failed / 0 skipped (340.47s, 9 existing asyncio deprecation
warnings). Ruff and diff checks passed. Full repository and separate Research
suites were not rerun for the site-local change; all known original layouts,
the new profiles, native source failures and Batch/ZIP boundaries are covered.
Shared code/contracts are unchanged, so `00_core.md` needs no synchronization.

## Episode 108 direct-first final-PR without recommendation (2026-11-11)

Item/Source 47778, `KC_002911_S:KC_0029110010900011_E` (Episode 108),
uses `direct_first_final_pr` with no trailing recommendation. A fresh
shared-CDP observation reproduced the failure with 54 native slots:
`[1, 2 x 26, 1, 0]`. The unique known beginning root owns the directly typed
first canvas and zero PR markers. Final singleton index 27 owns exactly one
main-wrapper PR n=2. Empty index 28 owns exactly main END n=1,n=2 and is the
last slide; no secondary END/recommendation is present. The previous profile
required a recommendation after END, so it failed before capture.

The direct-first final-PR profile now accepts the observed zero/one trailing
recommendation forms. Inventory validation still requires exact beginning
ownership and geometry, one first singleton, paired middle, one final singleton,
one final PR and the empty paired END. An existing recommendation must still
pass all prior marker, owner, number, geometry and empty-slide checks. Absence
must be exact: no trailing slide or secondary marker. Other reader profiles
retain their established requirements; the paired-first final-PR zero/one
recommendation forms are documented below.

The final ArrowLeft guard receives a no-recommendation flag only for the
validated direct-first or paired-first final-PR layouts with exactly END+1
total slides. That mode rejects bridge/double-END combinations and requires exactly
two main END markers, correct ownership/geometry, one final content slot,
visible reader/PR and safe focus. All ordered sources must be captured before
the single key attempt reaches the immediately following empty END. Unknown
markers, missing/misowned/duplicate PR, extra slides/content, no advance,
skipped turns or asynchronous mutations remain fail-closed. Native Blob,
full-frame/RGBA proof, Core, access rules, pacing, max-pages and same-content
contracts are unchanged; no `note/00_core.md` update is needed.

A bounded source probe passed the production native proof for all 54 original
WebPs and verified ordinary turns through exact final index 27 -> 28. Proof
metadata and isolated artifacts are under ignored
`work/kadocomi/error-47778-20261111/`. This uses the production native observer,
not a separate independent source observer. Live scope is only the reported
Episode 108; no other episode sweep is authorized by this maintenance.

Normal CLI `batch run --limit 1` then completed only this episode in an
isolated SQLite online-backup Catalog, retaining the Watchlist's real URL scope
and archive settings and enabling only Source 47778 in the copy. Dedicated
output/library paths produced one 54-page ZIP and a succeeded/end CrawlRun
23107. All 54 ordered members passed CRC and WebP decoding and matched fresh
source SHA-256, byte lengths and dimensions; archive hash/size matched the
Artifact. The copied Catalog passed SQLite quick_check. Read-only before/after
audit confirmed the operational target's Source, pending Item, CrawlRuns and
Artifacts were unchanged. Other live candidates were not run. Exact evidence:
`work/kadocomi/error-47778-20261111/live-batch.log`, `source-proof.json` and
`audit.json`.

Validation: 17 focused new-topology browser tests passed (including a final
rerun after making the skip fixture land on a real wrong slide and asserting
exactly one key attempt). The affected browser selection passed 209 tests,
with another 6 existing direct/paired PR-END bridge positives passed separately;
all 7 adapter/native-capture unit tests passed. Total distinct affected tests:
222 passed, 0 failed/0 skipped. The browser selection covers the changed final-PR
ArrowLeft helper's final, double-END and bridge callers, both CSS directions,
exact Runner/Batch ZIP bytes, direct beginning faults, missing/duplicate/misowned
PR, final-slot/END faults, extra content/slides, no advance/skipped turns,
asynchronous PR mutation and the preceding mixed-final recommendation fix.
Global `ruff check src tests` and diff checks for this change passed. Full
repository, unrelated reader-profile integrations, Discovery/Policy selections
and separate Research/Probe pytest suites were not rerun: this is a bounded
site-local topology and key-guard extension; the previous 408-case capture
baseline is recorded below. Other live episodes and an independent source
observer were not run. Logs are under `error-47778-20261111/pytest-affected.log`;
the 209 deselected browser cases are outside that affected selection, not skips.

## Episode 10.1 direct-first mixed-final recommendation (2026-11-11)

Item/Source 47775, `KC_008463_S:KC_0084630001200011_E` (Episode 10.1),
uses `direct_first_mixed_final` with one trailing secondary recommendation.
A fresh shared-CDP observation reproduced the failure with slot counts
`[1,2,2,2,2,2,2,2,1,0,0]`: one directly typed first canvas in the unique
known beginning root, seven RTL pairs, a final singleton at index 8 owning
main END n=2, the empty paired main END n=1,n=2 at index 9, and one empty
recognized secondary recommendation at index 10. No PR marker is present.
The previous profile-selection branch accepted this direct-first mixed-final
only without the recommendation, fell through to the wrapped-first profile,
and failed before capture. This was a missing topology combination.

The direct-first mixed-final selection now accepts zero or one trailing
recommendation, retaining the existing exact secondary marker class, number,
ownership and positive contained geometry checks. The paired-first mixed-final
profile remains limited to its previously observed no-recommendation form.
The beginning owner, first singleton, paired middle, final singleton and exact
three main END markers remain required. Extra slides, missing/duplicate/misowned
secondary markers, content at/after END, unknown PR, no advance, skipped indices
and asynchronous mutations fail closed. Existing native Blob/full-frame/RGBA
proof, complete ordered capture, first/final ArrowLeft guards, max-pages,
same-content, access rules, shared Core and CLI/settings are unchanged.

A bounded source probe verified all 16 original WebPs and ordinary turns
0 -> 1 through 8 -> 9, leaving recommendation 10 inactive. A normal CLI
`batch run --limit 1` completed only this target in an isolated online-backup
Catalog with dedicated Watchlist/output/library paths: CrawlRun 23103,
16 pages, explicit END, one ZIP Artifact. All ordered ZIP members passed CRC
and WebP decoding and matched the fresh source SHA-256, byte lengths and
dimensions; archive hash/size matched its Artifact. The copied Catalog passed
SQLite quick_check. This comparison uses production native proof, not an
independent source observer. Read-only before/after audit confirmed the
operational target's Source, pending Item, CrawlRuns and Artifacts were
unchanged. No other live candidate was run. Metadata-only source proofs,
copy Catalog, CLI log, ZIP and audit are ignored under
`work/kadocomi/error-47775-20261111/`.

Validation: the focused new topology selection passed 16 tests; after the
negative-fixture image-count adjustment, its final affected subset also passed
16/0 failed/0 skipped. The full affected capture selection passed 408 tests,
0 failed/0 skipped (593.71s, 41 existing pytest-asyncio/Python deprecation
warnings): `tests/unit/test_kadocomi_adapter.py`,
`tests/unit/test_kadocomi_native_capture.py`, and
`tests/integration/test_kadocomi_adapter_browser.py`. Coverage includes both CSS
directions, exact ordered Runner/Batch ZIP, all previous reader profiles,
secondary missing/duplicate/wrong-owner faults, content at END/recommendation,
extra slides, invalid beginning/main markers, no advance/skipped turns and
unexpected/asynchronous PR insertion. Global `ruff check src tests` and diff
checks for this change passed. Full repository, separate Research/Probe test
suites and Discovery/Policy selections were not rerun because this changes only
site-local reader topology selection. Live verification was limited to the
reported target; other episodes and an independent source observer were not
run. Shared Core is unchanged, so `note/00_core.md` needs no synchronization.

## Remaining 40-candidate topology maintenance (2026-10-22)

The Item/Source 36662 failure is a separate unsupported layout from 36661:
`direct_first_mixed_final` has a directly typed first page inside the validated
beginning root, paired middle slides, a final singleton owning main END n=2,
and an empty paired main END. Its failed-run DOM and fresh settled live state
agree on `[1,2,2,2,2,2,2,2,2,1,0]` (18 pages). The previous fix only supported
PR-free direct-first content ending with two main END slides; it did not cover
this final singleton or the other remaining layouts.

A bounded CDP/Playwright inventory sweep inspected all 40 remaining pending,
available/free candidates 36662..36701 across the two batch works. Exact
markers, source-slot order, directly typed beginning ownership and contained
geometry are validated per profile; no unknown reader structure is accepted.
The new observed profiles are:

- `direct_first_mixed_final` (6 candidates) and `paired_first_mixed_final` (6):
  no PR; final singleton owns main n=2, immediately followed by paired main END.
- `direct_first_paired_end` (13): directly typed first page followed by zero or
  more pairs, paired main END, and either no trailing slide or exactly one
  recognized secondary recommendation. Zero middle pairs were observed on
  36668 (one page). `paired_first_paired_end` (1) has pairs from the first slide,
  paired main END and no trailing recommendation.
- `direct_first_secondary_end` (2) and `paired_first_secondary_end` (2): no PR;
  final singleton owns the sole main n=2 marker. The immediately following empty
  slide owns the sole recognized secondary END marker and is the exact terminal.
  Main n=2 on the content slide alone never establishes completion.
- `direct_first_pr_pair_double_end` (1) and
  `direct_first_pr_pair_recommendation` (4): directly typed first page, pairs,
  final singleton owning PR n=2, an empty PR n=1,n=2 slide, then paired main END.
  The former has one further paired main END; the latter one recognized
  secondary recommendation. Neither trailing slide is entered or captured.
- `direct_first_pr_pair_bridge` (4) and `paired_first_pr_pair_bridge` (1): all
  body slides after the optional direct-first singleton are pairs; then an
  empty PR n=1,n=2 slide, an empty PR n=1 / main END n=2 slide, and paired main
  END. The direct-first one-page case was observed on 36693/36696.

Direct beginning role/owner/geometry and the absence or exact ordered PR roles
participate in inventory settlement and native/Python async-change checks.
First direct content uses the existing guarded ArrowLeft. Mixed-final body
singletons use the existing final-END ArrowLeft guard. The new PR sequences
require complete ordered body capture before empty slides are advanced. Each
empty PR slide must settle twice; its exact inventory, metadata, visible
reader target and focus are checked before one ordinary ArrowLeft. The same
12-second bounded change wait must reach the next exact slide and ultimately
END; a failed key is not repeated. Empty PR slides are neither captured nor
terminal. Missing/misowned/duplicate markers, content at END, extra slides,
unknown geometry, no advance, skipped slides and asynchronous mutations fail
closed. Native source Blob/full-frame/RGBA proof, Core, access policy, settings,
CLI, max-pages and same-content contracts remain unchanged. No `00_core.md`
update is needed for this site-local change.

Thirteen bounded representative source probes covered the observed ordinary,
single-page, secondary-END and PR-sequence transitions. Every expected body
source passed the existing production native proof and reached the exact
terminal without entering later slides. These probes share the production
native observer; they are not an independent source observer. Dedicated
Watchlist, online-backup Catalog, source records, snapshots, CLI logs and audits
are ignored under `work/kadocomi/error-36662-20261022/`.

The focused new-profile selections passed 43 and 75 cases. Final local affected
capture regression passed **392 / 0 failed / 0 skipped** (529.53 seconds):
`tests/unit/test_kadocomi_adapter.py`, `tests/unit/test_kadocomi_native_capture.py`
and `tests/integration/test_kadocomi_adapter_browser.py`. The 41 warnings are
existing pytest-asyncio/Python deprecations. This includes the original wrapped
singleton/mixed-final profiles, legacy unrelated PR handling (one/three markers),
all new profiles, both CSS directions, source proof failures, exact ordered
Runner/Batch ZIP, malformed ownership/markers/content, secondary END faults,
no advance, skipped steps and asynchronous PR mutation. PR bridge no-advance
cases verify exactly one key attempt per bridge. Ruff (`ruff check src tests`)
and diff checks passed. No further live verification is running.
At the user's explicit stop request, the isolated normal CLI Batch was stopped:
36662..36668 had completed (7 episodes, 99 pages), and 36669 was interrupted.
The interrupted record remains running in the disposable copied Catalog; it is
not a successful or completed crawl. The normal Catalog's 40 Items and their
existing failure history were unchanged at the read-only audit. All seven
completed ZIPs passed ordered inventory counts, CRC, WebP decoding and Artifact
hash/length checks. Four of these episodes (51 pages), including all 18 pages
of 36662, also matched the fresh source hashes, byte lengths and dimensions.
The other three archives were not compared against separate fresh source records.
The stopped stock CLI run did not reach the PR-sequence candidates: their
ordinary live keyboard/source probes passed, and the new production bridge
orchestration is covered by local synthetic Runner/Batch tests; live stock-CLI
verification of that orchestration remains incomplete.
All-40 Batch/ZIP completion is explicitly unverified and will not be resumed
unless the user asks. The 194 planning skips are not test skips. The user will
report subsequent real-site failures. Per the user's 2026-10-22 instruction,
future maintenance must limit live verification to the reported target and
necessary bounded representative cases. Do not proactively run all-episode
inventory/capture/Batch sweeps; require a new explicit request for that scope. Separate Research/Probe, Discovery/
Policy and full repository suites were not run because only site-local capture
acceptance and transitions changed. Core and other sites are unchanged.

## Episode 9.2 direct-first double-END maintenance (2026-10-22)

Item/Source 36661, `KC_008463_S:KC_0084630001100021_E`, uses
`direct_first_double_end`: one directly typed first canvas inside the unique
known beginning root (zero owned PR), seven RTL pairs, then two consecutive
empty main END slides, each owning exactly n=1,n=2. Slot counts are
`[1,2,2,2,2,2,2,2,0,0]`; PR and secondary recommendation inventories are empty.
The two failed run DOMs and repeated fresh live snapshots agree. The previous
four-main-END branch assumed paired-first content with a final PR n=2 and
therefore raised `Kadocomi paired-first final PR role or geometry is unknown`
before capture. This was an unsupported topology, not a transient loading error.

The new profile requires validated direct-first beginning ownership and
positive contained geometry, at least one following pair, the exact ordered
four main END markers, no PR/recommendation, no additional slides, and no
content at either END. First-source capture is followed by the existing guarded
ArrowLeft to exact index 1. Subsequent turns, including the final pair, use the
verified ordinary overlay. Completion requires every ordered source slot and
exactly the first END; the second END remains inactive. Beginning/PR data stay
in settlement and native/Python async stability checks, including absence of PR.
Unknown structures, source-proof failures, no advance and skipped END fail closed.
Core, native Blob/full-frame/RGBA proof, access policy, CLI/config and output
contracts are unchanged; `note/00_core.md` needs no update.

A bounded live probe verified all 15 original WebP sources with the existing
production native proof and exact index 7 -> 8 overlay transition. A fresh
normal CLI `batch run --limit 1` completed the exact target in an isolated
SQLite online-backup Catalog (CrawlRun 13764, 15 pages, explicit END, one ZIP).
All ordered ZIP members passed CRC/decoding and matched the fresh source
SHA-256, byte length and dimensions; archive hash/size matched its Artifact.
At that checkpoint the original Item was pending and unchanged, with both
failed runs preserved; the user subsequently completed 36661 in the normal Catalog. Evidence/scripts/logs and the dedicated Catalog/library are ignored
under `work/kadocomi/error-36661-20261022/`. The source probe uses production
native proof, not a separate independent observer. At that checkpoint, other episodes in the
41-candidate batch were not run; unobserved layouts remain unsupported.

Previous checkpoint validation: the focused new-profile selection passed 21 cases; the final
capture selection passed **257 / 0 failed / 0 skipped** (340.76 seconds), covering
`tests/unit/test_kadocomi_adapter.py`, `tests/unit/test_kadocomi_native_capture.py`
and `tests/integration/test_kadocomi_adapter_browser.py`. Its 41 warnings are
existing pytest-asyncio/Python deprecations. Coverage includes all prior reader
profiles, both CSS directions, byte-preserved Runner/Batch ZIP, malformed
beginning roles, missing/wrong END, extra slides/content, unexpected and
asynchronous PR insertion, early/skipped END and no advance. Global
`ruff check src tests` and `git diff --check` passed. Full repository,
separate Research/Probe and Discovery/Policy suites were not run because only
site-local capture profile acceptance changed. Live metrics recorded one
completed target, zero retries and zero relevant HTTP errors. The 233 planning
skips in the dedicated Catalog are not test skips. Live execution of the
remaining 40 batch candidates and an independent source observer were not run.

## 第10話-2 direct-first PR/END maintenance

The `direct_first_pr_end` maintenance profile was observed on Item/Source 26207,
`KC_011605_S:KC_0116050001000021_E` (第10話-2). Its slot counts are
`[1,2,2,2,2,2,2,2,0,0]`: the unique beginning root owns the directly typed
first canvas and zero PR markers, followed by seven RTL pairs. Empty slide 8
owns exactly PR n=1 and main END n=2; empty slide 9 owns main END n=1,n=2.
There is no secondary recommendation or extra slide. The previous direct-first
profile required a final singleton with PR n=2 and therefore rejected this
different ending. Acceptance requires at least one middle pair, exact roles,
contained positive geometry, complete unique ordered slots and stable PR data.
After first-source capture, the existing guarded ArrowLeft must reach index 1.
After all sources, the ordinary overlay must reach the stable empty PR/END
slide; the existing guard, with direct-first ownership validation, allows one
ArrowLeft within the same bounded wait to reach the paired END. The empty
intermediate slide is neither captured nor completion. Missing/changed markers,
unknown roots, duplicate or misplaced canvases, early/skipped END and no advance
fail closed. Native source/RGBA proof, Core, access policy, pacing and guard
budgets are unchanged. Only site-local Python profile handling changed.

A fresh production-native source probe at 1904x985 captured all 15 WebPs and
reached index 9. The probe uses the adapter's Blob/full-frame/RGBA proof, not an
independent observer. The new full inventory sweep covered all 23 remaining
sources 26207..26229: 26207 required this extension; the other 22 matched existing
profiles. Evidence is under ignored `work/kadocomi/direct-first-26207-20261013/`.
CLI/config/output contracts are unchanged; verification uses dedicated Catalog,
Batch output and library paths, with the normal Catalog untouched.


Normal CLI Batch `--limit 23` completed all 23 exact targets (26207..26229),
347 pages, explicit END and one ZIP Artifact each in an isolated online-backup
Catalog (CrawlRuns 9381..9403). Every archive passed CRC and WebP decoding;
page counts matched settled inventories, filenames/order were contiguous, and
archive SHA-256/length matched Catalog Artifacts. All 15 ordered members of
26207 additionally matched the fresh source hashes, lengths and dimensions.
No separate fresh source-byte comparison is claimed for the other 22 episodes.
The normal Catalog's 23 Items remained Pending and existing failures were
preserved; only the isolated Catalog was completed. Packaging removed generated
page directories, so no retained per-run manifest is claimed. Evidence:
`current-inventory.json`, `failed-dom-topology.json`, `source-proof-26207.json`,
`batch.log`, `zip-audit.json` under the ignored directory above.

Final affected Kadocomi selection: **269 passed / 0 failed / 0 skipped**
(387.13s, 9 existing asyncio deprecation warnings), covering
`tests/unit/test_kadocomi_{native_capture,policy,discovery}.py` and
`tests/integration/test_kadocomi_{adapter,discovery}_browser.py`.
The focused new-profile selection passed 23 cases; an initial negative-fixture
failure was corrected to exercise early END through the actual keyboard path.
The final selection includes both CSS directions, byte-exact Runner/Batch ZIP,
missing/duplicate/misowned PR and beginning roles, invalid END/content topology,
no advance with exactly one bridge key, skipped/early END, and async PR mutation.
Global Ruff and diff checks passed. Full repository and separate Research/Probe
suites were not rerun because only the site-local profile and its existing
browser fixture changed. Other works and an independent source observer were
not tested. Shared contracts are unchanged; `note/00_core.md` needs no update.

After preserving the fixture's existing two-page paired-first minimum, final
focused direct/paired PR/END regressions passed 40 / 0 failed / 0 skipped
(47.91s). Live metrics `de66a848e24747c3a511236f8a28f3c1` recorded 23 completed,
0 failed/retry/403/429/5xx/challenge/CAPTCHA. The 118 skipped planning rows include
the deliberately excluded Items in the dedicated Catalog; they are not test skips.

## Discovery behavior

### Short public lists without an expansion control (2026-11-11)

Unconfigured targets still emit only currently public Sources, newest-first,
with no global position hints, inactive Sources or complete-native inventory
proof. If the unique visible `全N話を表示` control exists, its declared total
continues to validate the expanded list. If no such control exists, Discovery
reads the strict native first/latest inventory and requires the settled public
DOM to match all active native IDs, labels and order. Inactive native runs must
match the existing native marker validator, including proven trailing runs.
Two identical snapshots 500 ms apart must settle within 12 seconds. Native data
and DOM must remain unchanged through the final read, exact work-route check
and AccessGuard check before emission. Missing or incomplete native evidence,
unknown types, row/label/marker disagreement or changed identity remains an
incomplete run with no records emitted. DOM row count alone never proves Full
exhaustion. The expanded legacy marker rules below remain specific to that path.

The shared site-local native parser now also accepts observed WEB `type=pr`
only when `internal.episodetype=pr`; all identity, UUID, type, count, reverse
array and order validation remains required. KC_007220_S naturally includes
holiday illustration, comics announcement and extra-publication rows with this
type; KC_008463_S also includes a PR listing identity. These are native episode
identities, distinct from capture-time viewer PR markers. Their access still
requires the validated public DOM, and this adds no reader profile or purchase.

Live normal CLI Full with an isolated online-backup Catalog and dedicated
Watchlist passed all four enabled operational targets: KC_004915_S observed 7
(0 new/7 known), KC_008463_S 7 (0/7), KC_008719_S 3 (1/2), KC_007220_S 5 (0/5),
all complete/exhausted. The latter two list their public rows without an expand
button, which caused the prior failure. KC_004915_S has 123 native entries with
7 active, exactly matching the expanded DOM, through 第79話. Read-only checks of
the operational Catalog found 第78話/第79話 already available/free/acquisition
on/completed, and the recorded 第79話 ZIP exists. No newer WEB episode was
observed. Discovery's new=0 refers to existing identity, not missing acquisition.
The operational Watchlist/Catalog were not written; no viewer, Capture, Batch,
ticket or purchase action was executed. Ignored metadata/log/copy evidence:
`work/kadocomi/discovery-20261111/`. Future WEB releases and app-only inventories
are outside this observation. CLI options are unchanged.

Validation: 177 affected tests passed, 0 failed/0 skipped, covering Kadocomi
Discovery/policy/GUI scope and shared Discovery units, plus real-Chromium local
Discovery, complete-list preview and registration integrations. Regressions
cover three/five active rows without expansion, explicit PR types and rejected
unknown/mismatched types, repeat-Full identity, incomplete-Full preservation,
missing/foreign native proof, pre-emission identity/title drift and final guard
stops. `ruff check src tests` and diff checks for the five changed files passed;
the isolated live Catalog passed SQLite quick_check. Full repository,
Research/Probe tests and reader/Capture/Batch live verification were not run:
this is a site-local listing change with no capture/runtime contract change.
The shared Service/Core are unchanged, so `note/00_core.md` needs no update.


`src/screenshot_crawler/site_adapters/kadocomi/discovery.py` implements the site adapter. `screenshot_crawler.cli` registers it only for Discovery. It uses the connected Playwright `Page` and shared access guard; the adapter does not launch Chrome or select a browser profile.

Supported input is an HTTPS work-detail route on `comic-walker.com` matching the strict `KC_<six digits>_S` work-ID shape and observed query forms. Live listing verification was performed for `KC_004915_S` and `KC_011605_S`; no-deadline free classification applies to validated public rows without access gates for all work IDs. The unconfigured legacy path remains unbounded, current-public-only, and does not infer global positions. When `discovery_scope` or `archive_order` is configured, the adapter uses a separate strict native-history path that supports bounded `from_url` / `through_url` Discovery. Both public-list forms require the unique work-scoped `DIV.EpisodesTabContents_root__* > UL.EpisodesTabContents_episodeList__*` container and exact visible expansion control `\u5168{N}\u8a71\u3092\u8868\u793a` when present. It waits at most 12 seconds for two identical scoped snapshots 500 ms apart; the active public-row count must match the native active IDs and any expansion count. Page-wide recommendations and teaser links do not count.

Every public row is validated before any record is yielded. A row must be a direct `LI` with exactly one episode link; the unique `EpisodeThumbnail_title__*` title node must be contained inside that link. The URL must identify the same work and a unique episode. Saved episode URLs are canonical query-free paths. Publication dates and deadline dates are separate from the title node and do not become the order label. Any malformed row, sibling title outside the link, duplicate ID, wrong-work identity, unsupported query, unknown deadline syntax, gate-like text, changed work metadata, missing title, or incomplete count fails closed. Legacy records are buffered and emitted newest-first. The opt-in native path and the no-expansion public-list proof bind one exact `/api/contents/details/work` query to the requested work and require complete, unique `firstEpisodes` and reverse-ordered `latestEpisodes` arrays with matching totals. Each native row needs a matching work-prefixed code, canonical UUID, `serviceId=web`, a recognized `normal` / `extra` / `pr` type matching `internal.episodetype`, strict boolean `isActive`, and positive unique ascending `internal.episodeNo`. It rejects missing, duplicated, reordered, cross-work, oversized, or inconsistent data before yielding.

For opted-in native history, active rows must match the settled public DOM IDs, labels and order exactly. Native inactive runs may correspond only to the observed internal and trailing ended-publication markers; expected marker groups are derived from actual `isActive=false` rows, never from gaps between `episodeNo` values. Leading or all-inactive histories remain unsupported and fail closed. Inactive observed rows are preserved as `available=false`, `access_mode=unknown`, with no invented expiry or grant and with their explicit native positions. Scope selection is inclusive and uses the latest-first validated native ID order. A final access guard and exact same-work route check run after all final listing/DOM reads before record emission.

In the expanded legacy public-list settlement path, the observed ended-publication marker is `\u305d\u306e\u4ed6\u306e\u8a71\u306f\u516c\u958b\u7d42\u4e86\u3057\u307e\u3057\u305f`. Each marker must be one attribute-free direct `LI` with exactly one direct paragraph, no links, no episode title, and no other text. Multiple markers are accepted only in distinct internal gaps, each directly between two validated episode rows whose labels match its previous/next snapshot labels. With N declared episode rows, the marker count must be an integer in 0..N-1 (bool rejected). Adjacent markers, leading/trailing markers, malformed markers, and other non-episode children fail closed in this legacy path. Every marker's direct-child index, exact text, and adjacent episode labels participate in the two identical snapshots required for settlement. Markers are excluded from the declared episode count and do not become Sources, identify missing episode IDs, or establish lifetime ordering. The opt-in native-history path uses a separate settlement validator: it permits only the observed internal-gap or trailing marker groups derived from actual inactive native rows; leading/all-inactive patterns remain unsupported.

Live validation on 2026-10-15 confirmed two exact ended-publication markers on `KC_004915_S`, between 第3話その2 / 第27話その1 and 第43話 / 第78話. The visible expansion control declares 42 episodes; the scoped list has exactly 42 valid episode rows plus the two markers, with no malformed children. The old 0..1 marker restriction caused the reported zero-observation incomplete run; a new browser regression reproduced that failure before the fix. After the site-local fix, the normal CLI full Discovery with a dedicated Watchlist and online-backup Catalog completed with 42 observed / 35 new / 7 known, `complete=True`, `exhausted`, and zero failed targets. The copied Catalog held 88 Sources (42 available / 46 unavailable) and passed `quick_check`. All 53 pre-existing Source IDs, Item links and display positions, existing Item statuses/completion times/operator notes, CrawlRuns and Artifacts were preserved. Read-only comparison confirmed that the normal Catalog was unchanged. Metadata-only diagnostics, isolated Catalog/Watchlist, CLI log and audit are ignored under `work/kadocomi/discovery-diagnosis-20261015/`; no reader capture was performed. The shared Service still exposes adapter incomplete exceptions only as `incomplete` / `Discovery incomplete`; error-message propagation is unchanged.

Validation for multiple ended-publication gaps: 95 affected unit tests (`test_kadocomi_discovery`, `test_kadocomi_policy`, `test_discovery`) and 11 browser-backed Discovery integration tests passed, with zero skipped. Existing history/republication tests are parameterized for zero, one and two markers; incremental checks use two markers, and negative fixtures cover adjacent, leading/trailing and malformed markers as well as unknown children, sibling titles and incomplete counts. `ruff check src tests` and `git diff --check` passed. Full suite, separate Research tests, live reader capture and Batch execution were not run because only site-local Discovery settlement changed; live CLI full Discovery and Catalog preservation auditing cover the affected operational boundary. Core/Runner and shared Discovery contracts are unchanged, so `note/00_core.md` does not require synchronization.

Source external IDs are `work_id:episode_id`; saved targets are canonical query-free episode paths. The adapter sets `allow_inferred_display_positions=False`. The legacy unordered path preserves existing positions and leaves new positions NULL. The opt-in native path supplies explicit `episodeNo` positions for the verified native rows. Complete-listing proof refreshes positions only for rows present in the proof; absent Catalog Sources retain prior position/history and remain unresolved blockers in Scope Reconciler. Incomplete Full runs do not reconcile missing Sources or publish evidence. Incremental Discovery leaves unseen Sources unchanged and does not publish a complete-listing proof. Reusing the same external ID preserves the Source and its Item, status, CrawlRuns, and Artifacts across disappearance and republication.

## Work-key native inventory follow-up (2026-10-22)

The opt-in path was verified against two sanitized metadata-only observations.
`KC_004915_S` supplied matching, reverse-ordered first/latest arrays of 123
native rows (24 active and 99 inactive), with explicit `episodeNo` values up
to 127 and gaps. `KC_011605_S` supplied 33 rows (3 active and 30 inactive)
and exercised the observed settled DOM containing only the three public rows
plus one trailing ended marker, with no expand control. These observations
support the validated response shapes and strict parser for the tested works;
they do not establish a site-wide guarantee that the endpoint always exposes
every episode ever published. No Source is fabricated for an episode-number
gap.

The isolated-copy validation for `KC_004915_S` completed Full Discovery with
123 observed / 18 new / 105 known, then scope sync enabled all 123 Sources.
The copy retained 24 available and 99 unavailable rows; archive preview
reserved 001–123 from actual Sources, not through native number 127. The
`KC_011605_S` copy completed Full with 33 observed / 33 known and then enabled
all 33; 3 were available and 30 unavailable, with ordinal range 001–033.
Both copy audits preserved all seeded Source IDs, Item states, CrawlRuns,
Artifacts, and quota-history digests, and did not open the Executor or perform
capture, purchase, ticket, or quota actions. Evidence is under
`output/acquisition-site-followup/kadocomi-copy-live-report.json` and
`kadocomi-second-copy-live-report.json`; these are isolated working copies,
not mutations to the operational Catalog, Watchlist, or Books.

Targeted verification passed 63 Kadocomi unit/browser Discovery tests (five
existing asyncio deprecation warnings, zero skips); Ruff passed. Parser
corruption cases cover duplicate code/UUID, wrong query/work binding, totals,
native order/type and extra rows. Unit tests cover inclusive from-only,
through-only, both-boundary, and singleton slices. Browser cases cover full
native inventory/scope synchronization, shrink/re-expand identity/history
retention, unavailable ordinal reservation, Incremental without proof,
pre-emission drift, and a final access-guard stop before any Catalog row is
written. Full repository tests are run separately and recorded in the work-key
runbook.

An exact future row deadline is classified as free and recorded as `free_until`; a later observed NULL clears stale expiry. Following the user-confirmed Kadocomi convention, a validated public row without restriction flags or a deadline is free with NULL expiry, regardless of work ID. The previous single-work allowlist is removed. Expired/equal deadlines remain unknown. Purchase, paid (including bare `有料`), login, ticket, coin, point, rental and app text fails closed, as do malformed deadlines and list shapes. This changes site-local Discovery classification; the Policy still rejects unknown Sources and NULL expiry alone does not establish free access. The adapter reports `available=true` for validated public rows.

Live full Discovery on 2026-10-13 observed all 33 rows of `KC_011605_S`. In an isolated online backup of Catalog, Items/Sources 26230 (第2話-2), 26231 (第2話-1), and 26232 (第1話) changed from unknown to free with NULL expiry; all three became direct Batch candidates. Source/Item IDs, display positions, all 30 completed statuses and completion times, CrawlRuns and Artifacts were preserved. The normal Catalog was not modified. Evidence is under ignored `work/kadocomi/unflagged-free-20261013/`. This confirms listing classification, Catalog reconciliation and planning; it does not add reader-capture evidence for these three episodes.

Existing older unknown rows require full rediscovery because incremental mode can stop before reaching them:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover --key midori-no-uta-shuushuu-gunfuu --mode full --catalog catalog.sqlite
```

Validation for this classification change: 95 affected unit tests (`test_kadocomi_discovery`, `test_kadocomi_policy`, `test_discovery`) and 5 browser-backed Discovery integration tests passed, with no skips. Tests cover no-deadline rows across work IDs, expired/equal deadlines, explicit access gates, malformed lists, Catalog identity/history, stale-expiry clearing and reconciliation. `ruff check src tests` and `git diff --check` passed. Full suite, Research tests and new live reader captures were not run because the change is limited to Discovery classification; live full Discovery and read-only Batch planning covered the affected operational boundary.

The shared Discovery service initializes `Work.title` from `WatchlistTarget.label` and does not apply `DiscoveredItem.canonical_title`. Kadocomi validates and exposes the work-page `og:title`; it does not rewrite Work metadata. Use the actual work name in the dedicated Watchlist label.

## Episode 4.3 empty PR bridge / secondary END (2026-11-18)

Item 50781 / Source 51088, `KC_019661_S:KC_0196610000500031_E`
(第4話-3), failed after reader detection with
`Kadocomi no-PR profile roles or boundary are unknown`. Repeated shared-CDP
snapshots show counts `[1,2,2,2,2,2,0,0]`: a directly typed first canvas in the
known beginning root, five body pairs, an empty slide 6 owning main-wrapper
PR n=1 and the sole main END n=2, then an empty secondary END slide 7 with
null data-n. The old single-main/secondary-END branch assumed a PR-free final
content singleton and correctly rejected this different topology.

The new `direct_first_pr_secondary_end` profile requires the validated direct
beginning, at least one following body pair, exactly this empty bridge and
terminal, one correctly owned/geometrically valid PR n=1, exactly one main
END n=2 on the bridge, exactly one secondary END on the next slide, and no
additional slides or content. The no-PR profiles retain their old rules.
The existing PR/END bridge path waits for two identical snapshots, requires
all ordered body slots captured, rechecks metadata and a guarded ordinary
ArrowLeft target, and presses once. It must reach exactly the next secondary
END; no advance, skipped turns and unsafe focus/dialog/geometry fail closed.
Neither empty slide is captured. The bridge alone cannot complete the run.
PR stability is tracked by native capture and Python checks. Native Blob/full
RGBA proof, max-pages/same-content, Core, access policy and CLI are unchanged;
`note/00_core.md` needs no update for this site-local change.

Normal CLI direct crawl of only this target completed all 11 original WebPs,
reached END and packaged a ZIP in dedicated output/library paths. All ordered
members passed CRC and decoding as 768x1092 WebP. This uses production native
source/pixel proof, not a separate independent source observer. The operational
Catalog, Watchlist and library were not written; the reported 10-candidate
Batch was not rerun. Inventory, CLI log, ZIP audit and test logs are ignored
under `work/kadocomi/error-50781-20261118/`. Other episodes were not inspected
or captured for this fix.

Synthetic Runner/Batch tests cover both reader builds and CSS directions,
byte-preserved ordered ZIPs, exactly one bridge key, missing/duplicate/misowned
PR and END markers, wrong numbers/classes/types, invalid secondary geometry,
content on empty slides, extra slides, malformed beginning/body shape, premature
END, asynchronous PR changes and no advance/skips. Final affected selection
passed 180 tests (including 176 browser Integration cases and 4 adapter Unit
cases); all 3 native-capture Unit tests passed separately. Total: 183 passed,
zero failed/skipped. The 346 deselected cases are outside this bounded selection,
not skips. The completed `pytest-verified.log` and native-unit run are acceptance
evidence; earlier fixture-development/interrupted selections are not counted.
The affected selection includes all shared PR/END key-helper callers, both
secondary-END profiles, new topology faults and the earlier class alternatives.
Global `ruff check src tests --no-cache` and changed-file diff checks passed.
Full repository, unrelated integrations and separate Research suites were not
rerun because this is a bounded site-local extension; normal live CLI and ZIP
validation cover only the reported target. No other live sweep was performed.

## Episode 4.2 paired-first final PR without recommendation (2026-11-18)

Item 50782 / Source 51089, `KC_019661_S:KC_0196610000500021_E`
(第4話-2), failed with `Kadocomi reader spread shape is unsupported`.
Repeated shared-CDP snapshots at 1904x985 show `[2,2,2,1,0]`: three wrapped
RTL pairs, a final singleton owning the only main-wrapper PR n=2 at slide 3,
and an empty paired main END n=1,n=2 at slide 4. There is no beginning root,
directly typed first canvas or secondary recommendation. The old
`paired_first_final_pr` selection required a trailing recommendation, so this
valid observed form fell through to the singleton-first profile and failed.

`paired_first_final_pr` now accepts either no trailing slide or one validated
secondary recommendation. It still requires at least one body pair, the final
singleton, exactly one correctly owned/geometrically valid PR n=2, and the
immediately following empty paired main END. No additional content/slides,
unknown marker roles or beginning root are accepted. Secondary marker checks
remain mandatory when a recommendation exists. The existing final-PR keyboard
guard permits the no-recommendation form for both the direct-first and
paired-first profiles, rejects bridge/double-END combinations, and requires
exact END ownership/geometry, safe focus and no dialogs. All ordered body slots
must be captured before one ArrowLeft; only the exact next empty END completes
the run. No advance/skipped turns fail closed. Native Blob/full-RGBA proof,
PR async stability, Core, access policy, CLI and max-pages/same-content guards
are unchanged. No `note/00_core.md` update is needed for this site-local change.

Normal CLI direct crawl of only this target saved all 7 original WebPs, reached
END and packaged a ZIP under dedicated output/library paths. All numbered
members passed CRC and decoding as 768x1092 WebP. The production capture proof
checked source provenance/full RGBA; the ZIP audit is not an independent
source observer. The operational Catalog, Watchlist and library were not
written. The remaining Batch was not rerun and other episodes were not
inspected/captured. Evidence is ignored under
`work/kadocomi/error-50782-20261118/`.

Synthetic Runner/Batch tests cover the observed counts under both reader
builds/CSS directions, original WebP order and ZIP/Completed registration.
Faults cover malformed first/final spread, missing/wrong/duplicate/misowned PR,
missing/wrong END, content at END, extra slides/markers, async PR mutation,
early END, reversed pairs and no advance/skips with exactly one key attempt.
Targeted coverage passed 24 cases. Final affected validation passed 84 tests
(7 Unit and 77 browser Integration), zero failures/skips; the 24 targeted cases
are included in that total. The 466 deselected cases are outside this bounded
selection, not skips. Coverage includes paired-first recommendation/no-
recommendation forms, direct-first final PR and no-recommendation failures,
double-END/PR-END positives, the preceding secondary-END bridge guards, exact
Runner/Batch ZIP bytes and single-key no-advance/skipped-turn behavior.
Global `ruff check src tests --no-cache` and changed-file diff checks passed.
Full repository, unrelated integrations and separate Research suites were not
rerun because this only extends a site-local final-PR topology. Live validation
was limited to the reported target; no other episode inventory/capture sweep
or independent source observer was run. Evidence: `pytest-focused.log`,
`pytest-affected.log`, `live-crawl.log` and `zip-audit.json` in the path above.

## Episode 2.2 paired-first PR bridge / secondary END (2026-11-18)

Item 50788 / Source 51095, `KC_019661_S:KC_0196610000300021_E`
(第2話-2), failed with `Kadocomi no-PR profile roles or boundary are unknown`.
Repeated shared-CDP snapshots at 1904x985 show `[2,2,2,2,0,0]`: four wrapped
RTL body pairs, an empty slide 4 owning exactly main-wrapper PR n=1 and main
END n=2, followed by an empty secondary END slide 5 with null data-n. There
is no beginning root or directly typed canvas. The previous secondary-END
bridge extension supported a direct-first singleton entry only, so this
paired-first form still fell through to the PR-free profile and failed.

The new `paired_first_pr_secondary_end` profile requires at least one body
pair, no beginning role, exactly one empty PR n=1 / main END n=2 bridge and
the immediately following secondary END, with exact classes, marker counts,
numbers, ownership and positive contained geometry. All body slides are
strict RTL pairs; no content is permitted at either empty slide or after END.
The direct-first bridge retains its existing beginning/first-singleton and
following-pair requirements. The PR-free secondary-END profiles are unchanged.

Both PR-secondary-END profiles share the existing bounded bridge orchestration:
all ordered body slots must be captured, bridge snapshots must settle twice,
metadata and the visible safe keyboard target are checked, then one ordinary
ArrowLeft must reach exactly the next empty secondary END. Neither empty
slide is captured or treated as early completion. PR tracking includes the
paired-first variant in both native and Python async stability checks.
No advance/skips, malformed markers/content, changed inventory and unsafe
targets fail closed. Native Blob/full-RGBA proof, Core, access policy, CLI,
max-pages and same-content guards remain unchanged; `note/00_core.md` needs
no update for this site-local extension.

Normal CLI direct crawl of only this target captured all 8 original WebPs,
reached END and packaged a ZIP under dedicated output/library paths. All
numbered members passed CRC and decoded as 768x1092 WebP. The production
native proof checked source provenance/full RGBA; the ZIP audit is not an
independent source observer. The operational Catalog, Watchlist and library
were not written. The reported three-candidate Batch was not rerun; other
episodes were not inspected/captured. Inventory, CLI, ZIP audit and tests are
ignored under `work/kadocomi/error-50788-20261118/`.

Synthetic tests reuse Runner/Batch-to-ZIP coverage across both reader builds
and CSS directions and verify exact source bytes/order, complete capture and
single bridge key. Paired/direct bridge faults cover missing/duplicate/misowned
PR and END, wrong classes/types/numbers, secondary geometry, content on empty
slides, extra slides, asynchronous PR mutation, malformed body/RTL order,
premature END, no advance and skipped turns. New-topology targeted coverage
passed 28 cases. Final affected validation passed 95 tests (7 Unit and
88 browser Integration), zero failures/skips; those 28 targeted cases are
included in the total. The 483 deselected cases are outside the bounded
selection, not skips. Coverage includes both PR-secondary-END variants,
PR-free secondary END, direct/paired PR-END and final-PR/double-END turns,
both reader builds/CSS directions, exact Runner/Batch ZIP bytes and the
single-key failure behavior. Global `ruff check src tests --no-cache` and
changed-file diff checks passed. Full repository, unrelated integrations and
separate Research suites were not rerun because this only extends a site-local
bridge profile. Live verification was limited to this reported target; no
other episode sweep or independent source observer was run. Completed evidence:
`pytest-focused.log`, `pytest-affected.log`, `live-crawl.log` and `zip-audit.json`
in the path above.

## Episode 1 final-PR body / PR bridge / secondary END (2026-11-18)

Item 50790 / Source 51097, `KC_019661_S:KC_0196610000200011_E`
(第1話), failed with `Kadocomi no-PR profile roles or boundary are unknown`.
Eleven stable shared-CDP inventory snapshots agree on 40 unique body slots:
`[1, 2 x 19, 1, 0, 0]`. The first singleton is a directly typed canvas in
the known beginning root. Final body slide 20 owns main-wrapper PR n=2;
empty slide 21 owns PR n=1 and the sole main END n=2; empty slide 22 owns
the sole secondary END with null data-n. The old one-PR bridge and three-PR
sequence profiles did not support this two-PR combination. Selection fell
through to the PR-free secondary-END profile and failed before capture.

The new `direct_first_final_pr_bridge_secondary_end` profile requires the
validated direct-first beginning, paired middle body, final singleton,
exact ordered PR roles `(n=2, END-2)` and `(n=1, END-1)`, exactly one main
END n=2 on the empty bridge and the immediately following secondary END.
It requires at least one middle body pair, exact slide count/ownership and
positive contained marker geometry, with no extra slides/content. It shares
the existing final-PR sequence navigation: all ordered sources must be captured
before one guarded ArrowLeft leaves the final singleton, then the empty bridge
must settle twice and pass metadata/keyboard-target checks before one further
ArrowLeft reaches exactly the next secondary END. Neither empty slide is
captured or completes the run early. PR async stability is tracked in both
native and Python checks. Unknown/missing/duplicate/misowned roles, changed
inventory, source/pixel mismatch, no advance or skipped turns fail closed.
Native Blob/full-RGBA proof, Core, access policy, CLI, max-pages and same-content
guards are unchanged; this site-local change needs no `note/00_core.md` update.

Initial inventory rejection now adds a bounded `inventory=` summary to the
exception and `adapter_debug.kadocomi_capture` diagnostics, with mode
`initial_inventory_failed`. It contains slide count, up to 32 content counts
and up to 8 `(number, slide)` records for each PR/main/secondary marker group.
Only expected marker numbers and bounded integer positions are retained;
unknown values are normalized. No canvas data, source/Blob URLs, titles or
authentication data are included in this added summary. Native source proof
and the existing shared diagnostic writer are unchanged.

Normal CLI direct crawl of only the reported target saved all 40 original
WebPs, reached END and created a ZIP in dedicated output/library paths.
All numbered members passed CRC and decoded as 768x1092 WebP. Production
native capture checked source provenance/full RGBA during acquisition; the
ZIP audit is not an independent source observer. The operational Catalog,
Watchlist and library were not written, and the user's one-candidate Batch
was not rerun. Inventory, CLI, ZIP audit and test evidence are ignored under
`work/kadocomi/error-50790-20261118/`.

Synthetic Runner/Batch tests cover the 40-page shape across both reader builds
and CSS directions, exact source-byte order/ZIP registration, missing/duplicate/
misowned PR and END, secondary faults, wrong final content shape, extra slides,
async PR changes, and both key attempts failing/skipping without repetition.
Diagnostics tests check bounded/redacted payloads and actual Runner metadata/
error files for an initial rejected shape. Final affected validation passed
192 tests (8 Unit, 184 browser Integration), zero failures/skips. The 413
deselected cases are outside the bounded selection, not skips. Coverage includes
all three-PR sequence layouts and both one-PR secondary-END bridge forms,
existing final-PR/double-END positives, the new two-PR shape/faults and initial
diagnostics. `pytest-affected.log` is the completed acceptance witness; earlier
fixture-development logs are not acceptance results. Global
`ruff check src tests --no-cache` and changed-file diff checks passed. Full
repository, unrelated integrations and separate Research suites were not rerun
because this only extends a site-local profile and initial diagnostics. Live
verification was limited to the reported target; no other episode sweep or
independent source observer was run. Completed live/ZIP evidence is in
`live-crawl.log` and `zip-audit.json` in the path above.

## Current P2 capture implementation

### Reader class update (2026-11-18)

Item 50779 / Source 51086 (`KC_019661_S:KC_0196610000600021_E`,
第5話-2) failed before capture because the observer only selected the original
reader CSS classes. Shared-CDP observation at 1904x985 found a rendered public
reader while every old observer snapshot returned `status=root, screenCount=0`;
the bounded 35-second initial wait therefore could never settle.

The current build uses `_mainScreen_1omf6_1`, `.splide._root_uhrbw_1`,
canvas `_root_1ncjq_21`, overlay `_cover_1ncjq_33`, beginning root
`_root_1iarr_1`, and secondary END `_endOfBook_1iarr_51`. The original
screen/root/overlay selectors remain supported alongside these exact observed
selectors; canvas and beginning checks accept only the original or newly observed
class families. Observer, native capture and all guarded navigation scripts use
the same supported alternatives. Multiple matched screens/roots, unknown classes,
unknown topology, source/pixel mismatch and unsafe navigation still fail closed.
No timeout, layout, access policy, Core or Catalog contract changed.

The target has the existing `direct_first_final_pr` layout: content counts
`[1,2,2,2,2,2,1,0,0]`, final PR on slide 6, paired main END on slide 7,
and excluded recommendation on slide 8. A normal CLI crawl using dedicated
output/library paths completed 12 original WebP pages and explicit END. All ZIP
members passed CRC and decoded as 768x1092 WebP, in numbered order. The production
capture proof checked Blob provenance and full RGBA equality during capture;
the ZIP audit is not an independent source observer. The operational Catalog,
Watchlist and library were not written by this verification, and the original
12-candidate Batch was not rerun. Sanitized diagnostics, CLI log and ZIP audit
are under ignored `work/kadocomi/error-50779-20261118/`.

Synthetic browser coverage exercises both builds through Runner and
Discovery/Catalog/Batch/ZIP, all existing accepted layouts, current-build source
mapping/mutation/transform failures, and unknown or duplicate reader DOM.
Validation: the affected unit files `test_kadocomi_adapter.py` and
`test_kadocomi_native_capture.py` plus the browser adapter suite passed 481 tests;
the subsequently added current-build source/DOM guard selection passed 16 tests
(497 covered cases total, zero skips). Before the fix, the two selected
current-build direct-first final-PR regression cases reproduced the same initial
reader timeout; both passed after the fix. `ruff check src tests --no-cache` and
diff checks restricted to the five changed files passed. Full suite and unrelated
Research probes were not run because this is a site-local selector update;
normal live CLI verification and the ZIP audit cover the reported target.

### Capture contract

`KadocomiAdapter` accepts only the direct WEB path, rejects auto/quota/entry-only use and all quota resources, and requires one exact episode URL. The P1 Discovery and P3 Policy establish Catalog eligibility; capture does not re-open the work list. The Runner's one initial navigation targets the canonical query-free episode URL. A page observer installed before navigation records only main-frame document responses; initialization requires an HTTP 200 final response and every redirect in that navigation to retain the configured work/episode identity. It waits a bounded interval for one visible H1 whose `【order】work` heading agrees exactly with both `og:title` and `document.title` plus the observed Kadocomi suffix, rejects visible dialogs, and then requires the settled native reader. No reload or second document navigation is issued. The Catalog source URL remains unchanged. Every capture rechecks URL and same-page metadata identity while retaining the existing native Blob, pixel, slot-order, and END proofs.

Before navigation, a bounded page observer retains eligible already-created WebP Blob references while preserving the site's original `URL.createObjectURL` and `drawImage` calls. It stores draw-time `currentSrc`, intrinsic dimensions, full source/destination rectangles, transform, alpha, composite mode and filter without retaining image elements or encoding pixels in the renderer hook. Capture requires the next unique canvas slot(s), an exact last full-frame identity `HTMLImageElement` draw, matching retained Blob identity, exact decoded Blob-to-canvas RGBA pixels, and unchanged pixels/layout/draw record after all asynchronous reads. Capture returns the original Blob bytes unchanged as WebP and releases consumed Blob references. Any missing or changed proof raises an adapter error; generic locator and screenshot fallback are disabled.

The active reader uses either observed screen/root selector pair documented above and carries `splide--rtl`. Computed CSS direction was `ltr` in prior P0 inspection and `rtl` in the later 1920x1080 anonymous context; physical wrapper/canvas geometry, not that CSS value, establishes spread order. Wrapped content slots use `DIV._pageCanvasWrapper_k9w27_25[data-type="contents"]` containing exactly one `canvas._root_bx4cr_1` or `canvas._root_1ncjq_21`; wrapped canvases have no `data-type`. The strictly validated direct-first beginning-content variant described above instead types its first canvas directly. The explicitly observed reader profiles described above are accepted; the mixed-final profile supports its two reviewed recommendation forms. Episode 4.1 starts with one slot, continues with paired spreads, and ends at the paired `n=1`,`n=2` main-reader END slide; its observed trailing recommendation slide has separate `DIV._root_1w5tt_1[data-type="end"]` and `DIV._endOfBook_1w5tt_50[data-type="end-of-book"]` and is never captured. The first-episode route starts with one content slot plus a PR item, continues with paired spreads, has one final content slot on a slide owning main END `n=2`, and then an empty terminal slide owning main END `n=1`,`n=2`. Episode 79 starts with one content slot, nine paired spreads, a final singleton owning `n=2`, and an empty paired END slide, followed by one recognized non-content recommendation slide owning the secondary END marker. Its PR `data-type=pr` item is not an END marker. Episode 22.2 starts at index 0 with no content slot and exactly one visible `data-type=beginning` root owning one positive-geometry `data-type=pr` child; the PR element has the observed secondary class prefix and no `data-n`. One ordinary ArrowLeft must advance to exact active index 1 with the same inventory, where the 18 content slots appear as nine RTL pairs; paired main END is at index 10 and the secondary recommendation is index 11. The observed Episode 20.2 starts with the same strictly owned empty beginning-PR slide, then five paired content slides, a final singleton at index 6 owning main END n=2, and an empty paired END at index 7 owning n=1 and n=2; no recommendation follows. Episode 8.2 adds a known empty beginning slide owning one secondary wrapper PR with null `data-n`, five paired spreads, a final singleton with main-wrapper PR `n=2`, and an empty paired END. Episode 7.2 has no beginning slide: its first content slide is a singleton, it requires at least one middle pair and `end index >=3`, and its final singleton is followed by the empty paired main END (`n=1`,`n=2`) and one recognized recommendation. The main-reader slide at index 0 owns a wrapper `data-type=pr,n=1` marker, and the final content slide (`end index - 1`) owns a wrapper `data-type=pr,n=2` marker; neither PR is an END marker. Native JavaScript and Python PR async-change tracking covers this validated content-first/final-PR profile and the validated paired-first and direct-first profiles described above. Existing content-first profiles retain their prior nonconstraint on unrelated PR metadata. The accepted beginning-PR mixed-final profile requires at least one paired content slide (end index >=3), not a hardcoded five. One validated ordinary ArrowLeft enters content; ordinary overlay turns traverse the observed five spreads, and after the final singleton is captured, one ArrowLeft reaches the empty END. Unknown or duplicate beginning/PR markers, unsafe/hidden targets, no advance, skipped turns, or changed inventory fail closed. The entry action applies only to this observed empty-first-slide topology; PR metadata on existing content-first layouts stays outside their historical acceptance rule. For the mixed-final layouts, the final source is captured before a safe `ArrowLeft` requests the exact next empty END; the following recommendation is never entered. Marker class, number, slide owner and positive in-slide geometry, along with the complete content inventory, are rechecked across snapshots and capture. Extra/unknown markers, slides or content, skipped turns, or changed inventory fail closed. The new Episode 79 extension passed independent code review (45 targeted tests, BLOCKING=0); normal CLI and independent all-20 source/RGBA-to-ZIP audit passed; final post-Discovery audit passed; final live-evidence Reviewer gate passed (BLOCKING=0, NONBLOCKING=0) and Lead accepted the bounded target; the prior milestone documentation review passed (Reviewer BLOCKING=0, NONBLOCKING=0). These original seven variants were verified on the observed routes on work `KC_004915_S`; the additional paired-first double-END evidence is scoped to the exact `KC_011605_S` route described above. Current per-capture limits are 4 MiB per Blob and 8,000,000 total decoded pixels.

Local browser fixtures exercise one exact episode navigation, byte-exact native WebP output, right-to-left order, and explicit END for the observed layouts. They cover wrong Blob attribution, asynchronous canvas mutation, transformed draws, 404/500 responses, non-render, delayed or inconsistent same-page metadata, dialogs, a same-work foreign-episode client navigation, main and recommendation END omissions/ownership/duplicates/wrong numbers, content at END or recommendation, extra slides, missing terminal pairs, reversed slots, skipped turns, and final keypresses that do not advance. The foreign-episode fixture is a synthetic HTTP 200 page that calls `location.replace`; it exercises a second document navigation deterministically because Chromium's HTTP 302 follow-up bypasses the fixture route in this environment. Separate unit cases validate that a 302-only recorded navigation whose final response remains 302, any foreign-identity response, and a 302-to-foreign-200 response all fail closed, while the exact HTTP 200 response passes. The first bounded production Runner attempt failed closed because code looked for `data-type="contents"` on the canvas instead of the wrapper. The original 21-slot episode 4.1 path and 38-slot first-episode path passed independent live source/ZIP audits and Reviewer gates. Episode 79's bounded all-20 native source proof and empty-END transition passed independent review (45 targeted tests, BLOCKING=0); normal CLI and independent all-20 source/RGBA-to-ZIP audit passed; final post-Discovery audit passed; final live-evidence Reviewer gate passed (BLOCKING=0, NONBLOCKING=0) and Lead accepted the bounded target; the prior milestone documentation review passed (Reviewer BLOCKING=0, NONBLOCKING=0). Those CLI/ZIP audits predate direct entry. The full local test set for the direct-entry change and current Ruff results are recorded in `runbooks/kadocomi/PROGRESS.md`.

Independent Tester used a separate normal-renderer Blob/draw hook to audit all 21 saved P2 page files: every file matched its corresponding WebP Blob byte-for-byte, decoded to 836x1200, and had zero RGBA mismatch against its canvas. Physical slot x-coordinates descended in right-to-left order; 11 ordinary one-slide advances, including the final advance to END, reached explicit END with the same episode identity. This is independent viewer-source-to-page-file verification for the observed renderer, not a ZIP audit and not a claim that opaque original network responses carry those bytes.

## Current P3 direct-only Batch integration

`KadocomiSitePolicy` admits only available `kadocomi` Sources with `access_mode=free`, a strict work-scoped external ID, and either NULL `free_until` or a valid aware future value. Expired/equal, malformed, naive, quota, paid, unknown, owned, grant, rental, and unsupported IDs are ineligible. NULL means no deadline was observed by Discovery; it does not independently grant free access. Discovery classifies validated public rows without restriction flags or deadlines as free for all works.

Manual Crawl, Batch adapter, and Batch Policy CLI registries include Kadocomi. Manual crawl requires `--access-strategy direct`; auto/quota and all named resources remain rejected. A Batch run requires a canonical query-free exact Catalog episode target matching the configured external ID. Catalog availability, free classification, and deadline eligibility remain the P1 Discovery/P3 Policy authority. The Runner navigates directly to the exact episode once; the Adapter rejects unsuccessful document responses, redirect identity changes, inconsistent same-page metadata, visible dialogs, and a reader that does not settle. It does not re-run Discovery or navigate to the work list at capture time.

The local end-to-end fixture runs Discovery, Catalog, Planner, Executor, Runner, and the production packager. It confirms native WebP bytes in the ZIP, canonical source identity, Catalog title/order metadata, ZIP Artifact registration and Completed only after explicit END. In the current direct-entry fixtures, HTTP 404, HTTP 500 with otherwise valid viewer content, non-render, foreign-episode client navigation, missing/inconsistent metadata, and visible dialogs fail closed; policy expiry remains covered by Site Policy tests. Runtime failures leave the Item pending and create no ZIP/Artifact. The earlier P3 targeted and affected regression results are historical checkpoint evidence; current direct-entry test results are in `runbooks/kadocomi/PROGRESS.md`.

## Current P4 independent live validation

Tester used a fresh isolated Watchlist, Catalog, output root, and library for one live CLI Batch run of the exact episode 4.1 target. Full Discovery returned 53/53 complete; incremental returned 5 known and left 48 unseen Sources unchanged. With 52 non-target Items skipped in the test Catalog, the normal `batch run --limit 1` captured 21 WebP pages, reached explicit END, and created one archive Artifact and one Completed Item. An independent audit matched every ZIP member byte-for-byte to both the P2 page file and independently observed live renderer Blob; all CRCs passed and all members decoded to 836x1200 WebP. ZIP SHA-256 is `d64fd2a66c6982c3045a70940b36846cd7f12af4685551f9488174673099e6ff` (3,278,163 bytes). Full/incremental rediscovery preserved the completed Artifact and Catalog target identity. The actual-catalog renumber dry-run proposed no moves because all positions remain NULL; one isolated synthetic apply preserved archive bytes. No real archive was renamed.

The CLI removes temporary page output after packaging, so P4 validates ZIP, run/status, Artifact, and Completed state rather than a retained manifest. The final P4 sweep completed 15 selected target episodes across initial and resumed runs, plus the Episode 22.2 control retest. ZIP hashes, per-file comparisons, the preserved first-attempt failures, and final Catalog state are recorded in `runbooks/kadocomi/PROGRESS.md`; the first 22.2 failure remains unexplained. No fresh independent P4 Blob/RGBA observer was run for the 8.2, 7.2, or 22.2 ZIPs. Final live-evidence Reviewer and Lead gates passed; Final documentation review PASS (Reviewer BLOCKING=0; Lead accepted bounded scope).

## Observed evidence and limits

The anonymous public list for `KC_004915_S` settled to 53 of 53 distinct episode rows in the exact list container, plus one ended-publication marker. The visible labels run 1 through 26 and then 78/79. The marker text is `\u305d\u306e\u4ed6\u306e\u8a71\u306f\u516c\u958b\u7d42\u4e86\u3057\u307e\u3057\u305f`, between `\u7b2c26\u8a71\u305d\u306e2` and `\u7b2c78\u8a71`. Exact missing episode IDs and lifetime numbering remain unknown. Forty-six rows showed an explicit 2026-10-14 11:00 delivery deadline and seven had no deadline. Official Comic Walker help describes WEB as a free manga portal and says episodes without configured deadlines may end without notice. Anonymous readability of a no-deadline episode was independently confirmed only for this work.

The work detail `og:title` and `document.title` are `\u592b\u5a66\u4ee5\u4e0a\u3001\u604b\u4eba\u672a\u6e80\u3002\uff5c\u30ab\u30c9\u30b3\u30df (\u30b3\u30df\u30c3\u30af\u30a6\u30a9\u30fc\u30ab\u30fc)`. Its H1 is chapter-prefixed and is not a Work title. A query-free exact episode route returned the same work/episode identity as the observed `co=true&episodeType=first` row link; saved episode locators omit those query values.

Independent P2 research retained five WebP Blob references created by the normal renderer without replacing the site's `URL.createObjectURL` call. Draw-time `HTMLImageElement.currentSrc` mapped DOM slots 0, 1, 2, 19, and 20 to the exact Blob and content canvas. The observed byte lengths were 169566, 141084, 133452, 126880, and 199144, with RIFF/WEBP signatures. Five full-RGBA comparisons had zero mismatches. Each observed image and canvas was 836 by 1200 with a full-frame identity draw. These are native viewer source-image bytes, not proof that opaque initial network responses contain the same bytes.

Ordinary `LEFToverlay` navigation traversed 21 content slots over 11 right-to-left content slides while staying on the exact episode. The next slide had no content and exposed the two main-reader wrapper markers with data-n 1 and 2. The 21 canvases were children of content wrappers, not themselves marked `data-type=contents`; a separate PR element was excluded. No source bytes or copyrighted pixels are stored in the repository.

The adapter requires per-capture currentSrc-to-immutable-Blob provenance, dimensions, full-frame identity, pixel equality, exact work/episode/page identity, safe state, validated content order, and one of seven observed layouts represented by six strict main-reader profiles. Screenshot fallback remains disabled. The original two variants passed independent review and live CLI/ZIP/source audits for the verified work. Episode 79's strict trailing-recommendation variant passed bounded live source/END proof, local Runner/Batch tests, independent code review, normal CLI and independent all-20 source/RGBA-to-ZIP audit, final post-Discovery audit, and final live-evidence review. Episode 22.2's bounded source/END probe, local Runner/Batch tests, independent code review, and normal CLI/ZIP run passed. The 21-slot Episode 4.1 CLI control also passed; its current control audit verified the ZIP and END but did not compare against prior per-page source bytes. Final post-Discovery/backup and P4 Reviewer audits passed, and Lead accepted the bounded scope. The direct-entry Runner probe described below is earlier evidence and did not itself run Batch CLI. Those original capture gates do not verify other works, additional reader layouts, transformed draws, or no-deadline reader variants on other works; subsequent bounded evidence is described above.

## Episode 79 failed-trial diagnosis (2026-10-12)

A bounded fresh-anonymous recheck of the exact query-free episode route found the public row in the complete 53-row list as available/free with `free_until=NULL`; direct navigation returned HTTP 200 and retained the exact episode identity. At both 1920x1080 and the measured 1906x986 viewport, the reader settled by about one second and remained unchanged through 12 seconds. It contains 13 slides with content counts `[1, 2 x 9, 1, 0, 0]` (20 content slots). The slide-0 `data-type=pr`, `data-n=1` promotion is not an END marker. Main END wrappers are `(n=2, slide 10)` and `(n=1,n=2, slide 11)`; slide 12 is a trailing recommendation with a secondary `data-type=end-of-book` marker and a separate `data-type=end` node. Independent review of the saved trial DOM confirms three main END markers, not four; the PR element's marker-like class does not make it an END.

The earlier user trial failed closed during initialization because the then-current mixed-final contract required the empty paired END to be the last reader slide and forbade a secondary END marker. It left the Item pending and created no Artifact or ZIP; this was a structural contract mismatch, not delayed reader readiness. The trial Catalog/output remains unchanged. A later user-approved extension now supports only this exact observed topology: 20 slots `[1, 2 x 9, 1]`, main END at index 11, and one recognized recommendation at index 12.

## Episode 79 native source and END proof (2026-10-12)

A fresh anonymous shared-CDP context confirmed the target remained available/free with NULL expiry in the complete 53-row list. The exact route returned HTTP 200 and preserved work/episode identity; the site added query values after the query-free input. Production native capture proved 20/20 source Blob streams byte-preserved in memory with exact full-RGBA equality to their completed canvases, in slot order. The sources total 4,904,084 bytes and included measured dimensions 1115x1600 and 1129x1600. After the 20th source on slide 10, one normal `ArrowLeft` reached empty paired END slide 11; the same episode remained active and recommendation slide 12 was not entered. The PR element on slide 0 was excluded from END classification. Sanitized proof is ignored at `work/kadocomi/p0-episode79-analysis-20261012/episode79-full-source-proof-attempt3.json`. Its event log was empty, but HTTP status-count telemetry was unavailable, so no all-responses status claim is made. Independent review passed (45 targeted tests, BLOCKING=0); normal CLI and independent all-20 source/RGBA-to-ZIP audit passed; final post-Discovery audit passed; final live-evidence Reviewer gate passed (BLOCKING=0, NONBLOCKING=0) and Lead accepted the bounded target; the prior milestone documentation review passed (Reviewer BLOCKING=0, NONBLOCKING=0).

## Operational checks

Use a dedicated Watchlist and Catalog beneath ignored `work/kadocomi/`. Never allow Discovery to fall back to the user's normal Catalog or Watchlist. The CLI shape is:

```powershell
python -m screenshot_crawler.cli discover --key kadocomi-sample --mode full `
  --watchlist work/kadocomi/watchlist.yaml --catalog work/kadocomi/catalog.sqlite
```

The Watchlist target URL must be the observed work-detail URL, and its label must be the true work title. Shared Chrome uses the existing CDP endpoint configuration. P1 validation results, current phase gate, and remaining uncertainties are in `runbooks/kadocomi/PROGRESS.md`.

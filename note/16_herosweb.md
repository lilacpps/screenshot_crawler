# HERO'S WEB current implementation

## Discovery and registration (Phase 02)

`src/screenshot_crawler/site_adapters/herosweb/discovery.py` implements
read-only Work registration metadata, complete range listing previews and
Discovery. The CLI Discovery registry and manual crawl registry include
`herosweb`; `registration.draft.PREVIEW_SITES` enables its complete-list
preview. Phase 04 registers the direct-only Batch adapter and site policy.

Work title extraction removes the exact leading site boilerplate
`HERO'S Web（ヒーローズウェブ）公式サイトの` and trims surrounding whitespace.
The same site-local normalization applies to URL registration metadata and
Discovery Work/range headers, so later Discovery keeps the clean title.
Occurrences inside a title are preserved; a boilerplate-only heading provides
no title and fails the existing missing-title checks. Existing saved titles
are not migrated by this change. Synthetic Unit/browser regression tests
cover this normalization; this title fix has not been live-verified.

The supported Work URL is canonical HTTPS
`https://heros-web.com/series/<13 lowercase hexadecimal Work ID>` with no
query, fragment or credentials. Discovery freezes Work identity/title/range
metadata, loads every numeric range as a full document, and validates exact
range coverage, same-Work routes, row counts, unique ordered episode IDs and
two stable observations. It waits at least 3.2 seconds between range loads and
buffers all records before yielding, including Incremental mode. The Work
page's latest-episode preview and SPA-retained range rows are not complete-list
evidence.

Authenticated range pages can contain a current owner and a duplicate mirror.
The owner must be exactly one CSS-visible positive-size root. One zero-size
mirror is accepted only beneath the observed plain `.series-eplist` parent
with a `block / none / block` style chain and complete ordered row equality.
The authenticated owner may instead be beneath the observed
`.series-eplist.mode-user.mode-has-eps` wrapper. Anonymous roots are also
under the plain `.series-eplist` wrapper, not direct children of
`.series-eplist-main`. Unexpected ancestry, extra rendered roots, malformed
mirrors, duplicate/divergent rows and hydration drift fail closed.

Access classification is exact-row scoped:

- `無料` with `.mode-free` and `data-e2e="eliFreeBadge"` is `free`.
- `今なら無料` with `data-e2e="eliMemFreeBadge"` is `free` only with positive
  same-document `/api/auth/session` user evidence and a stable positive
  account header. For a positive current session, Viewer and Discovery wait
  passively up to five seconds for two equal positive header snapshots while
  rechecking current URL, document generation and the existing AccessGuard.
  Anonymous, stale and unknown auth remain `unknown`.
- `paid` requires the observed exact-row paid-item tree, a positive variable
  price (`data-e2e="eliPrice"`) and the first-party coin icon
  (`/images/icons/coin.svg`, `alt="コイン"`,
  `data-e2e="eliCoinIcon"`).
- `quota` requires one each of the same-row
  `.series-eplist-item-access-icon[data-e2e="eliWfIcon"]` and
  `eliIfIcon` markers, without competing signals. Partial, duplicate,
  conflicting or unfamiliar structures remain `unknown`.

The adapter uses only naturally emitted site data. Presence in the complete
listing supports `available=True`; it invents no grant or expiry. It does not
open a ticket, wait, coin, purchase, login or rights-acquisition flow.

The exact expected main-document GET is fetched with redirects/retries
disabled. Redirect responses are aborted before the destination request;
other statuses/headers/body are forwarded so the existing AccessGuard remains
authoritative. Discovery aborts non-GET requests to the observed first-party
host; other subresources keep their existing route. Viewer entry aborts all
non-GET requests before dispatch. Relevant unknown writes and unsafe
navigation fail closed; irrelevant external non-navigation writes are aborted
and recorded. The current HERO page fails closed if its own service-worker
controller is active or its expected document did not traverse the guard.
This is not a global service-worker guarantee.

## Normal Batch retry (shared generic contract)

HERO'S WEB inherits the generic Normal Batch retry policy; its Site Policy does
not add or override retry behavior. An eligible acquisition timeout may receive
one retry on a fresh Page for the same Item/Source/Target after the configured
inter-candidate pacing, for at most two attempts total. The retry rechecks the
exact target and current direct/free eligibility before entry. AccessGuard
403/429/challenge/CAPTCHA stops, UNKNOWN state, same-content/max-pages failures,
capture/native-proof failures and other non-eligible errors do not retry. The
contract is defined in `docs/DISCOVERY_AND_BATCH.md`. Local merge validation is
tracked in [PROGRESS.md](../runbooks/herosweb-free/PROGRESS.md); post-merge live
verification has not been performed.

## Manual Viewer and capture (Phase 03)

`HeroswebAdapter` supports only `auto` and `direct`. It rejects quota/resource
strategies before navigation. Manual entry requires fresh same-Work free
evidence; a title match or historical Catalog classification is insufficient.
It binds the exact Work and episode route, then rechecks the current header,
free proof, Viewer roles, public seek, active body canvas, draw epoch and stable
pixels.

Verified live profiles:

- Work `dca88b215773f`, episode `4fe9831c6f540`: 17 wrappers and 10 body slots.
- Work `0f023839d7bca`, episode `b92706d1ebe2e`: 45 wrappers and 38 body
  slots; the row was `今なら無料`, and entry required fresh authenticated
  same-Work evidence after its header hydrated.
- Work `0f023839d7bca`, episode `e1d105f22de45`: 22 wrappers and 15 body
  slots, public seek 1–21 by 2. A bounded live probe verified first pair
  (lead PR/body 1), body 2/3, final body 14/15, and terminal Good/Last.

Public seek maximum is the largest odd integer at or below the wrapper count:
`2 * floor((wrapper_count - 1) / 2) + 1`. Initialization/loading, Python layout
validation and the native draw observer use the same rule. Even body counts
retain a lone terminal Last wrapper; odd body counts end in the exact frozen
Good/Last pair. END still requires minimum seek, `mode-last-page`, that exact
terminal slot set and complete ordered body coverage. Arbitrary shortened seek
ranges and missing/unknown roles remain rejected. No timeout, access, route,
pixel-proof or same-content guard is relaxed. The earlier direct-entry live
sample covered only an even body count and did not expose this preexisting
layout assumption. Failure evidence: Batch Run 29127 (Item 56761 / Source
57068). Live layout probe: `output/herosweb-odd-e1-probe/snapshots.json`.
The corrected same-episode identity-bound direct Runner completed all 15 body
slots in order, including final pair 14/15, then reached actual END at seek 1
and produced an isolated ZIP. All 15 members are valid 1440x2048 WebPs; ZIP CRC
and Pillow image verification passed. Exactly one episode document navigation
was observed, with no Work listing navigation. Normal Catalog/Library were not
modified. Evidence: `output/ho-live-be28109b/verification.json` and the retained
pre-packaging `manifest-proof.json` beside it. This verifies Runner + Packager
on the supplied target; Catalog Batch orchestration is covered by synthetic
browser tests for both odd/even bodies, native WebP and rendered PNG fallback.

The adapter captures body slots in observed order, excludes lead/CI/PR/Good/
Last wrappers, and accepts actual terminal END only after all body slots are
captured. It never advances to another episode. The original Phase 03/05
Runner artifacts were 10 and 38 rendered-canvas PNGs at 934×1329 and passed
their ZIP/image audits. They remain valid historical fallback artifacts; the
later A10 and B14 full runs verify source-native output at the two observed
profiles. Original response bytes are unproven; scrambled JPEG responses are
not saved as finished pages. The
current runtime also contains the separately reviewed source-native path
described below. The A03 first-body attempt and its later successful full-run
successor A10 are historical checkpoints; current full-run evidence is listed
below. Do not use A03's earlier pre-manifest failure as the current run status.

## Current verification and limits

After the exact-route redirect guard and positive-session header hydration
changes, isolated Full and Incremental Discovery both succeeded for the two
supplied Works. The audit found 21 and 87 unique Work-bound sources, complete
positions 1–21 and 1–87, and stable source/item ID digests across Incremental.
Access counts were 84 free, 20 quota, 4 paid and 0 unknown. A and B Runner
artifacts and terminal proofs were independently audited. Detailed commands,
review status and isolated evidence paths are in
`runbooks/herosweb-free/PROGRESS.md`.

Phase 06 source-native capture is now independently verified for both observed
profiles: A10 saved 10/10 VP8L pages at 1440x2048; B14 saved 38/38 VP8L pages
at 844x1200. Both matched retained source-PNG RGBA, verified full ordered tile
history/replay/stability, reached actual END and passed ZIP/Catalog audits.
B14 audit: `output/herosweb_experiment/native-independent/live-20261123-03/proofs/B14-full-independent-audit.json`.
Original JPEG bytes or lossless JPEG reconstruction remain unproven; this does
not establish that such recovery is impossible.

## Direct-only Batch policy (Phase 04)

`HeroswebSitePolicy` allows only `available=True` sources with `access_mode`
`free`, using the existing `direct` strategy and catalog ordering. Quota,
paid, unknown, owned, rental, grant and unavailable sources are ineligible,
even when a source has an active grant or positive quota state. This policy
does not expose access resources, ticket passes, grant-only passes or grant
mutation. The CLI Batch adapter and policy registries include `herosweb`;
runtime uses 1500 ms page turns and 5000 ms between candidates.
For GUI Inventory, available quota Sources set the existing display-only
`pending_quota` flag and appear as `quota`/Quota対象残. The shared Inventory
projection maps `paid_not_supported` to `paid`/有償未取得. They retain the
`quota_not_supported`/`paid_not_supported` rejection reasons and remain
ineligible for Batch, with no supported resources. Known quota/paid Sources
are no longer counted as unknown/要確認. No Catalog rewrite or Discovery is
required; restart an already-running GUI to load the changed code.
Read-only operational Inventory verification on 2026-11-23 confirmed quota 66,
paid 2 and unknown 0. Inventory/Policy Unit and Qt-offscreen model validation
passed (74 tests in total); no real-site or Catalog write was performed for
this display change.

Identity-bound Batch `direct` entry stays on the canonical Catalog episode
URL. It verifies the current episode/Work header, rejects visible charge/login
gates and nested viewer frames, and requires the existing strict Viewer/body
readiness and capture proof. It does not traverse any Work/range listing or
reload the episode before capture. The diagnostic `free_proof.source` is
`catalog_direct_episode_entry`; this records direct entry evidence, not a fresh
listing classification. Batch output title/order come from the existing Catalog
metadata override; missing adapter title/order remain unset. Manual entry
without Catalog identity retains the fresh same-Work listing preflight.
Synthetic browser tests cover single episode navigation through END/ZIP with
native WebP and PNG fallback, current gate rejection, Work mismatch, and manual
entry preservation. On 2026-11-23, an isolated identity-bound `direct` Runner
verification of Work `dca88b215773f` / episode `4fe9831c6f540` captured all ten
1440x2048 WebPs through END. All ten manifest pages record exactly one guarded
document interception, the target episode URL, and no navigation violation;
all ten images passed Pillow verification. Catalog was not modified. This is
direct Runner verification; normal Batch orchestration/ZIP is covered by the
synthetic browser test. Evidence:
`output/herosweb-direct-live-c382b471/verification.json`.
Current layout/entry validation passes all 103 native-capture Unit and
adapter-browser cases, with no skips (`output/ho-all` temporary root).
This includes odd/even body counts through END/ZIP, loading-shell hydration,
native WebP/PNG fallback, resumed entry, inconsistent seek rejection and access
guards. Policy/Discovery were unchanged by the odd-body correction; the earlier
direct-entry validation also covered those contracts. Short temporary paths
avoid the Windows path length failures seen in the earlier validation run.
Changed-file Ruff and whitespace checks pass; repository-wide Ruff still
reports 13 unrelated existing findings. Full suite and Research/Probe tests
were not run for this site-local entry change.

The adapter output metadata supplies genre `漫画` without replacing explicit
request metadata. Synthetic coverage exercises a full Planner → Executor →
Runner → Packager → Catalog success, no-END failure, retry, and completed-item
idempotency. Existing generic AccessGuard/Batch coverage proves a fatal access
stop prevents later candidates.

One isolated standard CLI Batch sample selected only Work A episode
`4fe9831c6f540`: the Watchlist label was `サヴマ`, with all other 20 Work A
sources excluded by its explicit scope. CLI exit was 0; the Item completed, a
succeeded direct Run and one present ZIP Artifact were recorded, and the ZIP
contains ten valid 934×1329 PNG members. The Source stayed available/free and
its quota/grant timestamps remained unset. Audit:
`output/herosweb_experiment/phase04-live-A-20261122/standard-batch-audit.json`.
The isolated Catalog retained its earlier seed Work title
`HEROS WEB supplied work A`, which appears in the archive path; no production
Catalog title was rewritten.

The CLI currently emits metrics under the default `output/metrics` even when
the other paths are explicit. The exact run-owned file was relocated beneath
the isolated experiment diagnostics. For later isolated CLI runs, use the
experiment root as the process working directory and pass absolute paths for
all other files. Independent Phase 04 review passed with BLOCKING 0. Phase 05
Tester E2E passed for standard CLI A/B: 10/38 rendered-PNG pages, actual END,
completed Items, succeeded Runs and two independently audited ZIP Artifacts.
The final audit is
`output/herosweb_experiment/phase05-independent/proofs/20261123/phase05-final-independent-audit.json`;
the final independent Reviewer/Lead gate passed with BLOCKING 0. Watchlist add,
Full/Incremental and the 108-source Catalog remain stable at 84 free / 20
quota / 4 paid with resource fields unchanged. The two earlier HTTP 429 Runs
1 and 2 are preserved without Artifacts. The final freeze comparison matched
230 Python files plus runtime config and modules resolved to this worktree;
the Phase 05 browser lease is released. A separate bounded A-episode
diagnostic and source-native implementation followed Phase 05. **Historical
A06 checkpoint (superseded by A10/B13 below):** the base implementation review
passed and its 63-test synthetic suite passed, but episode-wide native
verification was incomplete. A04 persisted the first-body
native WebP. A05 stopped before any manifest page, END, or ZIP; its audit
proved that the only changing signature field was root token `mode-nav-open`.
The approved correction masks only that token for a fully verified native
capture group. Global signatures, readiness/END, PNG fallback and all other
fields remain strict. The affected native unit + adapter-browser suite passes
(67 tests, no skips), and independent source re-review passed. A06 standard A
Batch then completed with END, a 10-page ZIP and Catalog completion, but
native coverage acceptance failed: only slot 1 was VP8L at 1440×2048; slots
2–10 were rendered PNG at 934×1329. Packaging removed manifest/progress
before durable per-page identity/END evidence could be copied, so the
independent audit is incomplete. No B was run. Original response bytes remain unproven.
No ticket or paid action was performed; the earlier Phase 03 ZIPs used the
fallback genre folder `小説` and
remain valid capture evidence. See the Phase 06 checkpoint in
`runbooks/herosweb-free/PROGRESS.md`.

## Source-native pixel capture follow-up (Phase 06)

This is a site-local optimization, not original-byte recovery. Current production
can capture a source-canvas snapshot only when it is bound to the exact viewer
Work/episode, frozen layout, body wrapper and canvas. It supports two bounded
observed profiles: a 1440 x 2048 HTMLCanvasElement source with a complete
16-tile 4 x 4 history of 360 x 512 `HTMLImageElement` operations, and an
844 x 1200 HTMLCanvasElement source with 16 `HTMLImageElement` operations on a
4 x 4 grid of 211 x 300 tiles. Both require sRGB/unorm8 contexts, exact source
replay, and RGBA identity with the rendered body canvas. No raw JPEG response or
signed URL is saved or claimed as original bytes.

Draw-time eligibility now uses the unique observed viewer tree, exact body
wrapper role, current public seek and logical spread. It does not require the
offscreen target to meet the final visibility or loaded/rendered checks at the
draw instant. It snapshots the source pixels, source history, root/pages/
wrapper/canvas/seek identities, target epoch/generation, and wrapper/target
rectangles around the draw. At most two candidates for the current logical
spread are retained. A seek change clears them; every write or reset invalidates
the previous target candidate, including a later non-eligible write.

Materialization remains strict: the final frozen layout and seek must match,
the body wrapper must be loaded/rendered and at least 98% visible, and target
node, dimensions, epoch, generation and pixels must remain stable. The draw and
final target/wrapper rectangles must preserve their dimensions and show the
same common translation, with a 0.001 CSS-pixel rounding epsilon. The one
observed pending-`mode-has-pr` exception applies only to a draw at the initial
seek maximum with pair start 0; the final frozen layout still requires that
mode, and later spreads require it at draw time. All other root modes,
roles and identities remain strict.

Both source and target contexts must explicitly report sRGB and `unorm8`
before pixel readback. The adapter replays the captured source through the
observed draw arguments/context and compares exact RGBA. It checks the current
identity, seek, slot, node, epoch, generation, geometry and target pixels again
after asynchronous PNG conversion. Identity/access/target drift is fatal. A
missing or unsafe source proof, incomplete spread, unsupported context format,
or bounded native materialization error uses the independent rendered-canvas
PNG fallback. Only VP8L WebP whose decoded RGBA equals the captured source is
retained; a verified native PNG is kept if WebP validation fails. Only one
native materializer may be in flight per document. Metadata reports native
pixels, not original bytes.

The A03/A04/A05 history remains: A03 materialized a first-body PNG and VP8L
but stopped before a manifest page; A04 persisted a first-body WebP; A05
stopped before manifest/END/ZIP. The A05 trace showed only `mode-nav-open`
disappearing. The reviewed exception masks exactly that root token only for a
fully verified native group; global/readiness/END signatures, PNG fallback and
every other field remain strict.

The A10/B10 paragraph below is a historical checkpoint, superseded by the B14 audit. A10 passed with 10/10 pages saved as lossless VP8L WebP at 1440x2048; decoded RGBA matched each draw-time native source PNG, complete history/replay/stability proof was present, RTL order and actual END were confirmed, and ZIP/Catalog evidence matched the pre-package proof. B10 completed 38 rendered-PNG pages at 934x1329 with actual END and ZIP/Catalog audit passing. B13 later observed B's 844x1200 source-canvas history for slots 2/3: 16 HTMLImageElement draws cover an exact 4x4 grid of 211x300 tiles. B14 subsequently verified full native output for all 38 B pages. Do not infer wire format or original bytes. A10/B10 proofs are in output/herosweb_experiment/native-independent/live-20261123-02/proofs/.

B11 is a separate historical bounded diagnostic on an isolated clone: it captured three rendered PNGs with max_pages=3 and stopped before END, ZIP and Artifact creation. Twelve viewer draws were observed; the first body used an immediate 844x1200 HTMLCanvasElement source and a 934x1329 target. Its upstream history was not logged, so B11 alone cannot establish a tile mapping. B13 subsequently captured the missing source-history evidence for the exact observed 844x1200 profile on slots 2/3; see the current profile contract and B13 checkpoint below. B11 audit: output/herosweb_experiment/native-independent/live-20261123-03/proofs/B11-first3-diagnostic-audit.json; raw metadata: output/herosweb_experiment/native-independent/proofs/live20261123B11first3/. The clone preserved 108 source/resource rows and five existing Artifacts, added no Artifact, and left Item 103 pending after public reset. Original JPEG bytes remain unproven.

A06 was the earlier successful full live run: it reached END and produced a 10-page ZIP
and Catalog completion, but only slot 1 was native VP8L and slots 2-10 were
rendered PNG. Durable per-page identity/END audit was incomplete after
packaging cleanup. A07 diagnostic evidence at
`output/herosweb_experiment/native-independent/proofs/live20261123A07diag01/`
showed actual draws for slots 2/3 at seek 15 while both wrappers were offscreen
with zero viewport intersection. The earlier 98% draw-time gate therefore
rejected valid candidates. This A07 production fix has synthetic coverage.
Post-fix A08 stopped before encoder/capture with an observed-layout error, but
its exact failing parser input was not saved. A09 retained the failing input at
`output/herosweb_experiment/native-independent/proofs/live20261123A09full01/herosweb-dca88b215773f/parse-layout-audit.json`.
That snapshot proves the only missing required root mode was `mode-has-pr` at
seek 13/17, with the active body pair and next body slot loading and no canvases.
At the A09 checkpoint, A06 was the latest successful full run; A10 and B10 have since superseded that checkpoint.

The bounded initialization wait now recognizes only two observed resumed profiles: A (17 wrappers, 10 body slots, seek max 17/value 13) and B (45 wrappers, 38 body slots, seek max 45/value 41). In both cases the current pair and next slot (indices 4-6) are loading with no canvases, and only mode-has-pr is missing. A shallow provisional snapshot passes the strict structural parser, but is never accepted or frozen. URL/header/access guards remain active until the actual PR mode appears; the adapter then follows the normal strict freeze and rewind path. This remains initialization-only: the draw-time pending-PR exception is still restricted to initial max seek/pair start 0.

The synthetic browser tests cover pre-slide pair acquisition, the initial
pending-PR shell, later-pair missing-PR rejection, wrong seek/owner, subpixel
and larger geometry changes, reset invalidation, asynchronous target drift,
PNG fallback and the existing `mode-nav-open` boundary. The final affected
suite passed (81 tests, no skips, 5 existing asyncio warnings) before removal
of a redundant episode-ID check; the final targeted resumed cases then passed
(4 tests, no skips). A07 and A09 source reviews passed. **At this B12-era
checkpoint**, A10/B10 live outcomes and the B11/B13 diagnostics were current;
B13 had established an observed 844x1200 source-tile profile and synthetic
support, while full B native output was then unverified. B14 later passed that
full B audit as summarized above. The B12 synthetic regression extends only
the bounded initial wait to the observed 45/38/45/41 profile; independent
source review passed with BLOCKING 0. See
`runbooks/herosweb-free/PROGRESS.md` for command, duration and history.
Original response bytes remain unproven;
the bounded JPEG reconstruction helper accepted no candidate, which does not
prove restoration impossible. A future evidence-driven original-byte task must
remain separate from the current rendered and source-native paths.

## B13 observed source-grid profile - historical diagnostic, superseded by B14

B13's bounded max-pages-3 diagnostic observed slots 2/3 at public seek 43 on
Work B. Each 844x1200 source canvas received 16 upstream `HTMLImageElement`
draws covering an exact 4x4 grid of 211x300 source/destination rectangles.
The source canvas was reused across slots; the browser regression checks
distinct point-in-time pixel snapshots by matching saved decoded RGBA to each
slot's source proof. Context evidence was sRGB/unorm8, identity transform,
alpha 1 and source-over. This establishes the observed canvas/tile profile,
not a JPEG wire format or original-byte claim.

The native validator accepts only the observed A profile (1440x2048 with
360x512 `HTMLImageElement` tiles) and this B profile (844x1200 with 211x300
`HTMLImageElement` tiles). Both require exact integer 1:1 full-grid coverage
and exact source replay/decoded RGBA checks. B does not claim MCU alignment.
A10 was the only full native episode audit at this checkpoint; B14 later
verified all 38 B pages. B13 evidence: `output/herosweb_experiment/native-independent/live-20261123-03/proofs/B13-live-first3-audit.json` and
`output/herosweb_experiment/native-independent/proofs/live20261123B13first3/herosweb-0f023839d7bca/capture-signature-audit.json`.

The affected verification command
`.venv\Scripts\python.exe -m pytest tests/unit/test_herosweb_native_capture.py tests/integration/test_herosweb_adapter_browser.py --basetemp "$env:TEMP\hweb-profile-affected" -q --tb=short`
passed with 96 tests, 0 skips and 5 existing pytest-asyncio deprecation
warnings (260.95 s). The focused A/B profile gate passed 34 tests, 0 skips.
Changed-path Ruff, `py_compile` and `git diff --check` passed. No new live
browser request was made for this implementation.

## B14 full B source-native capture - current Phase 06 result

Tester and independent Reviewer passed the standard-CLI B14 audit. All 38
ordered ZIP members are lossless VP8L WebP at 844x1200. Every decoded RGBA
image matches its retained exact source-PNG proof; full 16-tile history,
replay, pixel stability and free-entry identity were confirmed. After all 38
bodies were captured, actual END was confirmed at public seek 1 with Last
wrapper index 44. ZIP order/CRC and pre-package manifest/progress digests
matched. The independent contact sheet was upright and contained page content
without UI.

- Audit: `output/herosweb_experiment/native-independent/live-20261123-03/proofs/B14-full-independent-audit.json`.
- Run 19 succeeded at END with 38 pages; Artifact 6 is 17,021,762 bytes with SHA-256 `70b6c574e7cce30654ee2cb22e1da44fdb071848d1e63abad396c6cc2b084d95`. Item 103 completed. All 108 Source rows and the resource rows are unchanged; prior Run/Artifact history is preserved. The final replan has no eligible/direct/quota candidates and skips the completed item.
- 719 requests returned HTTP 200; no 403/429/5xx, challenge, CAPTCHA or retry was observed. The source/config freeze was unchanged (230 Python files plus runtime configuration and the four native code/test hashes recorded in `PROGRESS.md`). A diagnostic recorder still emitted stale 1440-only profile warnings; the retained proof and independent full audit confirmed all 38 images use the 844x1200 profile successfully.
- B10 (rendered PNG), B11 (first-body bounded diagnostic), B12 (resumed loading), and B13 (three-page source-grid diagnostic) are historical checkpoints superseded for current full-run status. Their individual observations and limitations remain recorded above. Original JPEG bytes remain unproven, not impossible.

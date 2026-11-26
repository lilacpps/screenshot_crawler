# HERO'S WEB site adapter (Phases 02–04)

## Current scope

Phase 02 provides strict Work registration previews and complete episode
Discovery. Phase 03 provides a site-local manual Viewer adapter for directly
readable `free` episodes and rendered-canvas PNG capture. The CLI manual-crawl
registry, Discovery registry and read-only registration preview include
`herosweb`. Phase 04 also registers the direct-only Batch adapter/policy and
does not add site branches to Core or Runner.

The only supported seed is a canonical HTTPS URL on `heros-web.com` at
`/series/<13 lowercase hexadecimal Work ID>`, without credentials, query or
fragment. Episode routes are `/episodes/<13 lowercase hexadecimal ID>`.
Every episode is bound to its exact Work. No `/seriesh/` alias is accepted.

## Discovery and access classification

Discovery freezes the Work title and numeric range declaration, then opens
each declared range as a full document. It uses the exact current list scope
`.series-eplist-main .series-eplist-default`, validates contiguous range
coverage, per-range counts, unique ordered episode IDs, and two stable current
snapshots. The Work page's latest-row preview and SPA-retained rows are not a
complete inventory. Range navigation is paced at least 3.2 seconds apart and
all rows are buffered before any record is yielded, including incremental
Discovery.

Authenticated pages may expose two copies of a range list. The accepted owner
is one CSS-visible positive-size root. A matching zero-size mirror is accepted
only beneath the observed plain `.series-eplist` parent, with the exact
observed `block / none / block` style chain and complete ordered row-record
equality, with the authenticated rental exception below. The authenticated
owner is beneath `.series-eplist.mode-user.mode-has-eps`. The anonymous root
is under the plain `.series-eplist` parent.
Unexpected ancestry, extra rendered roots, malformed mirrors, duplicate or
divergent rows, and unstable hydration fail closed.

Only exact row-scoped evidence is classified:

- `無料` with `.mode-free` and `data-e2e="eliFreeBadge"` is `free`.
- `今なら無料` with `data-e2e="eliMemFreeBadge"` is `free` only when the same
  current Work document has a naturally emitted `/api/auth/session` response
  with a non-null user and a stable positive user header. A positive session
  waits up to five seconds for two identical positive header snapshots, while
  rechecking document generation and the existing AccessGuard. Anonymous,
  stale, or unknown session state stays `unknown`.
- `paid` requires the exact row's observed paid-item structure, a positive
  variable numeric price (`data-e2e="eliPrice"`), and the observed coin image
  (`/images/icons/coin.svg`, `alt="コイン"`,
  `data-e2e="eliCoinIcon"`). The price is not fixed to one observed amount.
- `quota` requires exactly one each of the same-row
  `.series-eplist-item-access-icon[data-e2e="eliWfIcon"]` and
  `eliIfIcon` markers, without competing access markers. Partial, extra,
  conflicting or unfamiliar structure remains `unknown`.

Ticket/quota, waiting, coin, purchase, login, and rights-acquisition actions
are not implemented. Listing presence determines `available`; it does not
invent a grant or expiry from presence alone.

Authenticated `eliRentStat` rows with the observed exact span/two-BR tree and
`レンタル中 閲覧期限 D日+H時間` or `レンタル中 閲覧期限 M分` retain
`quota`. The scheduling bound is scan start plus the displayed duration
minus one hour for rounding. Day/hour displays are bounded to 15 days and
hours to 0–23. Minute-only displays accept 0–59 minutes and leave no active
grant after the one-hour deduction. Known free/quota/paid observations
explicitly clear or replace the old grant. Unknown evidence preserves it.

Only for this positively authenticated rental may the zero-area hidden public
list retain the exact quota pair while the visible owner shows the rental.
Ordered identity and all non-access metadata must still match exactly;
all root/style/stability/navigation checks remain enforced.

The exact expected main-document GET is fetched with redirects and retries
disabled, then the original non-redirect response is forwarded unchanged for
the shared AccessGuard. 3xx is aborted before the destination request. In
Discovery, non-GET requests to the observed first-party host are aborted;
other subresources retain their route. In the Viewer, all non-GET requests
are aborted before dispatch; relevant unknown writes and unsafe navigation
fail closed, while irrelevant external non-navigation writes are aborted and
recorded. A current HERO page with an active service-worker controller or an
unguarded expected route is rejected. This is a narrow HERO page guard, not a
general service-worker guarantee.

## Viewer and capture

The adapter supports `auto` and `direct` entry only. It rejects quota/resource
strategies before navigation. Manual entry first obtains fresh same-Work free
evidence; a previously free Catalog row or title match alone is insufficient.
The exact episode route and header are then revalidated. It never clicks a
ticket, payment, wait, login, or rights CTA.

Identity-bound Batch `direct` entry uses the canonical Catalog episode URL
without visiting Work/range listings or reloading the episode. It checks the
current exact episode/Work header and charge/login/frame gates, then uses the
existing strict Viewer and capture checks. Catalog metadata supplies Batch
title/order; absent adapter metadata remains unset. Diagnostics identify this
as `catalog_direct_episode_entry`, rather than fresh listing free proof.
Synthetic browser coverage verifies one episode navigation through END/ZIP
with native WebP and PNG fallback and rejects current gates/Work mismatch.
An isolated identity-bound direct Runner verification on 2026-11-23 saved all
ten A-profile pages as 1440x2048 WebP through END, with exactly one guarded
episode document interception in every manifest page and no navigation
violation. All images passed verification; Catalog was not modified. This
checks direct Runner entry; normal Batch orchestration/ZIP is covered locally.
Evidence: `output/herosweb-direct-live-c382b471/verification.json`.

Live reader layouts have been observed:

- Work `dca88b215773f`, episode `4fe9831c6f540`: 17 wrappers, 10 body slots.
- Work `0f023839d7bca`, episode `b92706d1ebe2e`: 45 wrappers, 38 body slots;
  entry required fresh authenticated `今なら無料` proof.
- Work `0f023839d7bca`, episode `e1d105f22de45`: 22 wrappers, 15 body slots,
  seek 1–21 by 2. A bounded live probe verified the initial, ordinary/final
  body pairs and terminal Good/Last pair.

The public seek enumerates odd-valued spread starts: its maximum is the largest
odd number at or below the frozen wrapper count. Python layout/loading checks
and native draw attribution share this rule. The odd-body terminal is the exact
Good/Last pair; the even-body terminal remains Last alone. Both require full
ordered body coverage, minimum seek and `mode-last-page` before END. Unknown
roles or inconsistent ranges still fail closed. This corrects the assumption
behind the Item 56761 / Source 57068 initialization failure without extra
navigation, access actions or a broader timeout.
The corrected same-episode direct Runner + Packager verification completed all
15 ordered body slots through actual END at seek 1. The isolated ZIP passed CRC
and image verification with 15 valid 1440x2048 WebPs and exactly one episode
document navigation; normal Catalog/Library were not changed. Evidence:
`output/ho-live-be28109b/verification.json` (retained manifest alongside it).

For all supported layouts, the Runner captures all body slots in order, excludes the
lead/CI/PR/Good/Last wrappers, and accepts actual terminal END only after full
body coverage. The original two layouts' Phase 03/05 audited ZIPs were rendered-canvas PNGs at
934×1329; those are historical fallback artifacts. Later A10/B14 full runs
verified source-native output for all 10 A pages and all 38 B pages at their
respective observed profiles. Original response bytes remain unproven, so
scrambled JPEG responses are never represented as completed original pages.

## Verification and limits

Phase 02 Full and Incremental Discovery were rerun after the exact-route
redirect guard and auth-header hydration changes. Both supplied Works yielded
21 and 87 unique episodes; the isolated Catalog audit found 84 free, 20 quota,
4 paid, 0 unknown, complete positions, and unchanged source/item identities
across Incremental.

The A and B full Runner artifacts, terminal proofs and ZIPs passed independent
artifact audits. Those Phase 03–05 artifacts are rendered canvas PNGs; they
were not rewritten by the later source-native work. Evidence paths and exact
test/CLI results are in `runbooks/herosweb-free/PROGRESS.md`.

## Source-native pixel capture follow-up

The adapter can use a source-canvas snapshot only when the current body target
matches the frozen slot, node, epoch and generation, and its source canvas
matches one of two observed profiles. Profile A is 1440 x 2048 and requires 16
`HTMLImageElement` draws that prove a complete 4 x 4 grid of 360 x 512 tiles.
Profile B is 844 x 1200 and requires 16 `HTMLImageElement` draws that prove a
complete 4 x 4 grid of 211 x 300 tiles. Both profiles require exact integer
1:1 source/destination coverage and exact decoded RGBA proof; Profile B does
not claim 8-pixel or MCU alignment. Draw-time acquisition binds the unique observed
viewer tree, exact body-wrapper owner, current public seek and logical spread.
It does not require the offscreen target to pass the final 98% visibility or
loaded/rendered checks at that instant. It snapshots the source pixels, source
history, root/pages/wrapper/canvas/seek identities, target epoch/generation and
wrapper/target rectangles around the draw. At most two candidates for that
current spread are retained; a seek change clears them, and any write or reset
invalidates the target's old candidate.

The bounded B13 diagnostic observed the B profile for slots 2/3 at seek 43 and
recorded the exact 16-image tile history. It stopped at max_pages=3 before END
or packaging. This was the evidence checkpoint before the full B14 run; B14
later verified all 38 pages natively. See `runbooks/herosweb-free/PROGRESS.md`
for the final independent capture and artifact audit.

Materialization remains strict: the final frozen layout and seek must match,
the body wrapper must be loaded/rendered and at least 98% visible, and target
node, dimensions, epoch, generation and pixels must be unchanged. Draw and
final target/wrapper geometry must have the same dimensions and common
translation, within a 0.001 CSS-pixel rounding epsilon. The only draw-time
root-mode exception is the observed initial first-spread shell with
`mode-has-pr` still pending, and only when the public seek is at its maximum
and the logical pair starts at slot 0. The final frozen layout must have that
required mode, and later spreads require it at draw time.

Both source and target contexts must report sRGB and `unorm8`. The adapter
replays the captured source through the observed draw arguments/context,
compares exact RGBA pixels, and checks the episode, seek, target node, epoch,
generation, geometry and pixels again after asynchronous PNG materialization.
Identity/access/target drift is fatal; missing or unsafe source proof,
incomplete spread, unsupported context format, or bounded materialization
failure uses the existing rendered-canvas PNG fallback. Verified source pixels
produce lossless VP8L WebP only after decoded RGBA matches; a verified native
PNG is retained if WebP validation fails. The page manifest contains only a
sanitized point-in-time proof, not source bytes or signed asset URLs.

The A05 trace showed only root token `mode-nav-open` disappearing. Its reviewed
exception masks that token only for a fully verified native group; global and
END/readiness signatures, PNG fallback and all other fields remain strict. A06
standard A Batch reached END with a 10-page ZIP and Catalog completion, but
only slot 1 was VP8L and slots 2-10 were rendered PNG. Packaging cleanup
prevented a durable per-page identity/END audit.

A07 evidence showed slots 2/3 drawn at public seek 15 while both wrappers were
offscreen with zero viewport intersection; the former draw-time 98% gate
rejected these records. The approved change acquires the exact current logical
pair before the slide moves and requires the strict final visibility and
common-translation proof above. Synthetic browser regressions cover pre-slide
pair acquisition, wrong seek/owner, geometry changes, reset invalidation and
the initial pending-PR shell. A07's affected suite passed 78 tests with no
skips, and its source review passed. The first post-fix A08 live run stopped
before encoder/capture with `HERO'S WEB Viewer layout is not the observed RTL
spread`. A08's failing snapshot was not saved; A09 retained an
exact parser input proving the only missing required root mode was
`mode-has-pr` at seek 13/17 with the active body pair and next body slot
loading and no canvases. The bounded initial wait now recognizes only the two observed resumed profiles: A (17 wrappers, 10 body slots, seek max 17/value 13) and B (45 wrappers, 38 body slots, seek max 45/value 41). Both require only mode-has-pr to be missing, loading wrappers 4-6 with no canvases, and a strict provisional parse. The provisional layout is never accepted or frozen; URL/header/access guards remain active until the real PR mode appears, then the existing strict freeze and rewind proceed. The affected suite then passed 81 tests
before a small episode-ID-neutral refinement; the final targeted resumed cases
pass 4/4. A09 and subsequent capture fixes passed review. This A10/B10/B11/B12 checkpoint is historical and is superseded by B13's observed source grid and B14's full audit below. Original JPEG bytes remain unproven. A07 evidence is under
`output/herosweb_experiment/native-independent/proofs/live20261123A07diag01/`.
The B14 final full-capture audit passed all 38 pages at 844 x 1200 as lossless
VP8L WebP, with exact retained source-PNG RGBA, complete tile history/replay/
stability, terminal END, ZIP order/CRC and Catalog completion. Its audit is
`output/herosweb_experiment/native-independent/live-20261123-03/proofs/B14-full-independent-audit.json`.
Original response bytes remain unproven. See
`runbooks/herosweb-free/PROGRESS.md` for test results and attempt history.
## Direct-only Batch policy (Phase 04)

`HeroswebSitePolicy` selects available free sources and quota sources with an
aware future `access_granted_until`, using `direct` without consumption.
Expired or unproven quota, paid, unknown, owned, rental, grant and unavailable
modes are skipped. Actual episode/Work/Viewer and gate checks remain the final
entry authority; manual crawl retains the fresh free-only preflight.
It does not expose ticket/resource
passes, grant-only execution or entitlement mutation. Runtime settings use a
1500 ms page-turn delay and 5000 ms inter-candidate delay.

`HeroswebAdapter.get_output_metadata()` supplies the observed comic genre
`漫画`; explicit crawl-request metadata still takes precedence field by field.
The manual and Batch adapter registries and the Batch policy registry include
`herosweb`.

One standard CLI Batch sample ran against an isolated Catalog and Watchlist:
only Work A episode `4fe9831c6f540` was selected, with the other 20 rows
excluded by Watchlist scope. The CLI exited 0 with one succeeded direct Run,
one completed Item, one present ZIP Artifact and ten valid 934×1329 PNG members.
The source remained `free` and `available`; quota/grant timestamps stayed
unset. The complete sanitized audit is
`output/herosweb_experiment/phase04-live-A-20261122/standard-batch-audit.json`.
The copied Catalog retained its earlier seed Work title `HEROS WEB supplied
work A` while the Watchlist label uses the observed `サヴマ`; the archive path
therefore uses the seed title. No production Catalog or Work title was
modified.

The CLI emitted this run's metrics at its default `output/metrics` path despite
the explicit isolated Catalog and output paths. The exact run-owned file was
moved to the isolated experiment diagnostics after execution. Future isolated
CLI runs should set their current directory to the experiment root and pass
absolute paths for the remaining inputs and outputs.

Independent Phase 04 review passed with BLOCKING 0. Phase 05 Tester E2E passed
for standard CLI A/B: 10 and 38 PNG pages, END, two completed Items and two
audited ZIP Artifacts. The combined independent audit is
`output/herosweb_experiment/phase05-independent/proofs/20261123/phase05-final-independent-audit.json`;
the final Reviewer/Lead gate passed with BLOCKING 0. The two earlier same-A HTTP 429 Runs
(IDs 1 and 2) remain preserved with no Phase05 Artifacts. The final freeze
comparison matched 230 Python files plus runtime config, and imported modules
resolved to this worktree. The Phase 05 browser lease is released. A separate
post-Phase05 A-episode diagnostic proved exact sampled draw-time source-to-
canvas replay, and the source implementation review passed. A06 later
completed ordinary A Batch capture but did not meet native full-episode
coverage; details and evidence are in `runbooks/herosweb-free/PROGRESS.md`.
Original-byte recovery remains unproven. No ticket or paid action was performed.

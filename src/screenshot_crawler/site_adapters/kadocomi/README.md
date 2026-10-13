# Kadocomi Site Adapter

## Current phase

Current capture supports twelve observed layouts through eleven strict profiles,
including the 第10話-2 direct-first PR/END maintenance fix described below.
Latest maintenance validation, live Batch/ZIP runs and
source comparisons are recorded in the progress ledger.
The independent P4 gates in the following paragraph cover the original scope.
Final maintenance selection: 269 passed / 0 failed / 0 skipped; Ruff and diff
checks passed. Normal CLI Batch completed all 23 remaining episodes of
`KC_011605_S` (347 pages) in an isolated Catalog. Every ZIP passed
inventory-count, CRC, decoding and Artifact checks; all 15 target pages
also matched fresh source hashes/lengths/dimensions. The earlier all-29
inventory claim was incorrect and is corrected below. See the ledger
for the exact evidence and limits.

P1 Discovery, native P2 capture, P3 direct-only Batch, and P4 Tester/live-evidence Reviewer/Lead gates passed for seven observed reader layouts across six strict profiles (the mixed-final profile supports two reviewed recommendation forms). The final normal CLI Batch/ZIP sweep completed all 15 selected target episodes and the Episode 22.2 control retest. Its earlier pre-capture failure remains recorded with unknown cause; the successful retest did not clear that failed run. Final documentation review PASS (Reviewer BLOCKING=0; Lead accepted bounded scope). Evidence and limits are in `runbooks/kadocomi/PROGRESS.md`; other unobserved layouts fail closed.

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
  only PR `n=2`, an empty main paired END and one recognized secondary
  recommendation (第11話-3: 21 pages). All slots must be captured before one
  guarded ArrowLeft reaches the paired END; the recommendation remains inactive.

Both profiles require exact marker classes, numbers, ownership and positive
contained geometry, no content at/after END, complete ordered source inventory,
and PR stability during snapshot settlement and native/Python async capture.
Core, native WebP source proof, access eligibility, pacing, max-pages and
same-content guards remain unchanged. Other-work no-deadline access stays UNKNOWN.
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
requires one of the two direct-first profiles and validated beginning ownership/geometry; direct
canvases elsewhere, duplicates or unknown beginning/END topology fail closed.
Native capture still requires the original Blob, full-frame identity draw,
matching source/canvas RGBA, bounded budgets, ordered slots and async stability.
No screenshot/re-encoding fallback or synthetic page is introduced. Native
signature and Python settlement include the direct-first role and owner.

The previous inventory sweep did not establish support for all 29 episodes.
Seven rows failed collection; only two were rechecked before the prior report.
The five unrechecked rows included 26207, which still failed. The new sweep and
full Batch/ZIP scope are recorded below; prior all-supported claims are withdrawn.
Five representative live episodes were captured and compared with ordered ZIP
members; other works and a separate independent source observer were not tested.

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

## Discovery contract

The adapter accepts HTTPS work-detail routes on `comic-walker.com` matching the strict `KC_<six digits>_S` work-ID shape and observed query forms. The live-verified Discovery work is `KC_004915_S`; the no-deadline free classification is limited to that work. Other no-deadline works remain unknown. Bounded `from_url` / `through_url` input is unsupported. It uses the unique work-scoped `UL.EpisodesTabContents_episodeList__*` under `DIV.EpisodesTabContents_root__*`; page-wide recommendations and teasers are outside the scope.

When present, exactly one visible expansion button must match `\u5168{N}\u8a71\u3092\u8868\u793a`. The parser waits no more than 12 seconds for two identical scoped snapshots 500 ms apart. The number of validated episode rows must equal the declared total. It buffers and validates the complete list before yielding newest-first.

Each episode row must be a direct `LI` with one episode anchor. Its unique `EpisodeThumbnail_title__*` title node must be inside that anchor. Work and episode IDs must match the supported URL shape; saved URLs omit query parameters. Source IDs are work-scoped as `work_id:episode_id`.

The only accepted non-episode list child observed for this work is the ended-publication marker `\u305d\u306e\u4ed6\u306e\u8a71\u306f\u516c\u958b\u7d42\u4e86\u3057\u307e\u3057\u305f`. It must be one attribute-free `LI` containing exactly one direct paragraph, no links, no episode title, and no other text. Its direct-child index, text, and previous/next episode labels are part of the stable snapshot. Zero or one such marker is allowed. Any other non-episode child, duplicate marker, changed marker, duplicate episode ID, malformed row, wrong-work URL, ambiguous deadline, gate-like text, or incomplete list fails closed. This marker signals that other episodes have ended publication; it does not identify their exact IDs or lifetime order.

## Access and Catalog safety

The row deadline is read only from the observed `\u914d\u4fe1\u671f\u9650\uff1aYYYY/MM/DD HH:MM` label, separate from publication date and title. A future explicit deadline is classified free and saved as `free_until`; a later observed missing deadline clears stale expiry. A no-deadline row is classified free only for the independently verified work `KC_004915_S`. No-deadline rows on other works and expired rows remain unknown. Current validated public rows are `available=true`.

The adapter sets `allow_inferred_display_positions=False` and emits no global position hints. Existing positions stay unchanged and new positions remain NULL. A complete full Discovery can mark absent Sources unavailable; an incomplete full run cannot reconcile missing Sources. Incremental Discovery leaves unseen Sources unchanged. Reusing an external ID preserves Source, Item, Completed, CrawlRun, and Artifact history through disappearance and republication.

The shared Discovery service initializes `Work.title` from the dedicated Watchlist label and does not apply the adapter's `canonical_title`. Set that label to the actual work title.

## P3 Batch eligibility and CLI

`KadocomiSitePolicy` selects only `site=kadocomi`, `available=true`, `access_mode=free` Sources with a strict work-scoped `work_id:episode_id`. `free_until` may be NULL (no deadline was displayed at the last Discovery) or an aware future datetime. Expired/equal, malformed, or timezone-naive values fail closed. Quota, paid, unknown, owned, grant, rental, quota-resource, and grant-only paths are unsupported. The P1 Discovery adapter marks a no-deadline row free only for the independently verified work; the policy trusts Catalog's current `access_mode` classification and never infers free from NULL expiry alone.

The manual `crawl` CLI registry and Batch adapter/Policy registries include Kadocomi. Manual Crawl must use `--access-strategy direct`; the default `auto` is rejected. Batch keeps the generic pending-only Planner and Executor. The Batch adapter requires a canonical query-free exact episode Catalog target matching its configured external identity. Catalog eligibility remains governed by the current Source and `KadocomiSitePolicy`; capture opens that exact episode as its only main-document navigation. Candidate URLs and display positions are not renumbered or rewritten.

## P2 direct capture behavior

`KadocomiAdapter` accepts only `access_strategy="direct"`, rejects quota resources and entry-only runs, and requires an exact episode URL. Before Runner's single initial episode navigation, it installs an observer for the main-frame document response. It requires a successful final HTTP 200 response, preserves the configured work/episode identity through redirects, and verifies on that same page that exactly one visible H1 (`【order】work`), `og:title`, and `document.title` agree, with no visible dialog. Metadata hydration and the recognized native reader must settle within bounded waits. It performs no work-list navigation, reload, or second document navigation. P1 Discovery and P3 Policy remain the Catalog free/availability authority; source URL and manifest authority are retained.

The adapter installs a non-interfering observer before navigation. It preserves the original `URL.createObjectURL` and `drawImage` calls, retaining only bounded Blob references and immutable draw-time metadata. A capture succeeds only when the active unique Kadocomi reader slide has the next expected content slot or right-to-left spread; each canvas must map through its last full-frame identity `HTMLImageElement` draw to the retained Blob, and decoded Blob RGBA pixels must equal the finished canvas both before and after asynchronous byte reads. The original Blob bytes are returned unchanged as `.webp` / `image/webp`. Missing, changed, composed, transformed, oversized, or non-WebP proof fails hard. Locator and screenshot fallback are disabled.

The content slot inventory is derived from the live reader DOM. Eleven observed reader layouts are accepted through ten strict profiles; the mixed-final profile supports two reviewed recommendation forms. Episode 4.1 starts with one canvas, continues with two canvases per content slide in physical right-to-left order, and stops at the paired `n=1`,`n=2` END slide; its observed trailing recommendation slide is excluded. The first-episode variant starts with one slot plus a PR item, has paired spreads, ends content with a single slot owning main END `n=2`, then requires the immediately following empty slide with main END `n=1`,`n=2`. Episode 79 starts with one content slot, has nine paired spreads, and ends content with a single slot owning `n=2`; its empty paired END is followed by one recognized recommendation slide. Episode 22.2 starts on an empty slide containing one visible beginning root and its owned PR marker, advances once with the observed ordinary `ArrowLeft` action, then has nine paired content spreads and a paired main END slide at index 10. Its recommendation at index 11 is excluded. The observed Episode 20.2 uses the same strict owned beginning-PR entry, five paired content slides, one final singleton owning main END n=2, and the immediately following empty paired END (n=1,n=2); there is no trailing recommendation. Episode 8.2 adds an empty beginning-PR slide with paired content, a final singleton with main-wrapper PR n=2, and an empty paired END. Episode 7.2 is content-first with at least one pair, a final singleton with main-wrapper PR n=2, an empty paired END, and one recognized trailing recommendation. These PR markers are not END markers. The accepted profile requires at least one paired content slide (end index >=3), not a fixed five-slide count. The beginning-slide rule applies only to this observed empty-first topology; PR metadata on existing content-first layouts remains outside their prior acceptance rule. For the mixed-final layouts, ordinary overlay turns are used through the final content slide; only after its unique slot is captured does a safe `ArrowLeft` action request the next slide, which must settle exactly one index later as the explicit empty END. The recommendation slide is never entered or captured. Marker class, number, slide ownership, positive geometry, and the entire slot inventory are revalidated. Any unrecognized marker, extra slide, content at/after END, missing transition, skipped index, or changed inventory fails closed. Evidence for these original seven layouts is limited to the observed routes on `KC_004915_S`; the additional `KC_011605_S` route is described below. The Episode 79 normal CLI run and independent all-20 source/RGBA-to-ZIP audit passed; final post-Discovery audit passed; live-evidence Reviewer and Lead gates passed; the prior Episode 79 milestone documentation review passed (Reviewer BLOCKING=0, NONBLOCKING=0). The bounded native capture currently covers at most 8,000,000 total decoded pixels per capture and 4 MiB per source Blob.

Local synthetic browser tests exercise all eleven observed layouts through Runner and Batch-to-ZIP, keep source WebP bytes in order, and cover wrong Blob attribution, asynchronous canvas mutation, transformed draws, 404/500 responses, non-render, delayed or inconsistent metadata, visible dialogs, foreign-episode redirects, main and recommendation marker omissions/ownership/duplicates/wrong numbers, content at END or recommendation, extra slides, missing terminal pairs, reversed spreads, skipped turns, and final ArrowLeft transitions that do not advance. The original 21-slot layouts and their independent P2 source audits remain unchanged. The 38-slot implementation passed independent review, normal live CLI Batch/ZIP, and an all-38 independent source-byte/full-RGBA audit. Episode 79 passed live source proof for all 20 slots, reached the empty END without entering its recommendation, passed local tests and independent review (45 targeted tests, BLOCKING=0), and completed a normal CLI ZIP run. The separate all-20 independent source/RGBA-to-ZIP audit also passed. Those CLI runs predate direct entry; the post-change isolated Runner probe is recorded in `runbooks/kadocomi/PROGRESS.md`.

The local Kadocomi Batch integration test uses real Discovery, Catalog, Planner, Executor, Runner, and packager code with browser fixtures. It verifies byte-preserved WebP ZIP members for the eleven observed reader layouts, exactly one canonical episode navigation, source identity, Watchlist/Catalog title and episode-label naming, Artifact registration, and Completed only after END. HTTP failure, non-render, foreign-episode redirect, missing END, main/recommendation marker faults, extra slides/content, and final no-advance leave the Item pending without ZIP/Artifact or without completion. Eligibility expiry remains covered by Site Policy tests; capture no longer repeats the work-list query. Previous P3 review results and current follow-up test results are recorded in `runbooks/kadocomi/PROGRESS.md`.

Earlier P4 checkpoint ZIPs and audits are historical. The final normal CLI sweep completed 15 selected target episodes across the initial and resumed runs, plus an Episode 22.2 control retest. Episode 8.2 and 7.2 ZIPs matched saved P0 source records; the 22.2 retest matched its P0 files. The first Episode 7.2 and 22.2 failures remain in run history; the control failure cause is unknown. The P4 ZIP audit did not use a fresh independent Blob/RGBA observer. Final post-Discovery/backup, Reviewer, and Lead gates passed; Final documentation review PASS (Reviewer BLOCKING=0; Lead accepted bounded scope). See `runbooks/kadocomi/PROGRESS.md` for evidence and limits.

The current adapter additionally supports `paired_first_double_end`, verified
on `KC_011605_S:KC_0116050001200031_E` (第12話-3): eight RTL pairs, a final
singleton owning the only main-wrapper PR `n=2`, then two consecutive empty
main END slides, each owning `n=1,n=2`. Together with the maintenance profiles described above, current support is eleven
observed layouts through ten strict profiles. It requires at least one pair,
the final singleton, no beginning/initial PR/secondary recommendation, exactly
four correctly owned END markers with valid geometry, and no additional slides
or content. All source slots must be captured before one guarded ArrowLeft
advances exactly to the first END; the second END stays inactive. Snapshot and
async capture checks track the final PR. Malformed topology, no advance or a
skipped END leaves Batch pending without ZIP/Artifact. The earlier independent
P4 gates cover the original seven layouts; this maintenance extension has local
browser tests and a fresh bounded live source/CLI/ZIP verification, recorded in
`runbooks/kadocomi/PROGRESS.md`. Access eligibility and native WebP proof are
unchanged, including UNKNOWN for other works without explicit free deadlines.

## Operational validation

Use only a dedicated Watchlist and Catalog beneath ignored `work/kadocomi/`; never point at the normal user Catalog/output. Real-site browser access uses the existing shared Crawler Chrome through CDP and Playwright. The adapter does not launch Chrome or select a profile. Do not log in, buy, consume tickets/coins/points, access rental/purchased content, or bypass gates.

For phase status, exact observed counts, test commands, live results, uncertainties, and P2 source evidence, see `runbooks/kadocomi/PROGRESS.md`. Detailed phase contracts are in `runbooks/kadocomi/`.

Example isolated direct-only commands (using the already-populated dedicated Watchlist/Catalog):

```powershell
python -m screenshot_crawler.cli crawl --site kadocomi `
  --url https://comic-walker.com/detail/KC_004915_S/episodes/KC_0049150000400011_E `
  --access-strategy direct --output-dir work/kadocomi/manual-output `
  --library-dir work/kadocomi/manual-library
python -m screenshot_crawler.cli batch plan --site kadocomi `
  --catalog work/kadocomi/catalog.sqlite
python -m screenshot_crawler.cli batch run --site kadocomi `
  --catalog work/kadocomi/catalog.sqlite --output-root work/kadocomi/batch-output `
  --library-dir work/kadocomi/batch-library --limit 1
```

Always use a dedicated test Catalog, Watchlist and output root. P4 live validation uses separate fresh paths and must not reuse an already-completed item.

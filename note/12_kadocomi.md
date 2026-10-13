# 12. Kadocomi current implementation

## Status (2026-10-13)

P1 Discovery, P2 native capture, P3 direct-only policy/CLI/Batch, and P4 Tester/live-evidence Reviewer/Lead gates passed for seven observed reader layouts using six strict adapter profiles; the mixed-final profile supports two reviewed recommendation forms. The final P4 sweep completed all 15 selected target episodes and a normal CLI control retest for Episode 22.2. Its earlier control attempt failed before capture with the unchanged beginning-PR guard; the cause is unknown and the failure remains in history. Final documentation review PASS (Reviewer BLOCKING=0; Lead accepted bounded scope). Exact P0/P4 evidence, tests, hashes, and limits are in `runbooks/kadocomi/PROGRESS.md`. Unobserved layouts and other-work no-deadline access remain unsupported.

Current capture supports twelve observed layouts through eleven strict profiles.
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
are unchanged; other-work no-deadline eligibility remains UNKNOWN.

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

`src/screenshot_crawler/site_adapters/kadocomi/discovery.py` implements the site adapter. `screenshot_crawler.cli` registers it only for Discovery. It uses the connected Playwright `Page` and shared access guard; the adapter does not launch Chrome or select a browser profile.

Supported input is an HTTPS work-detail route on `comic-walker.com` matching the strict `KC_<six digits>_S` work-ID shape and observed query forms. Live listing verification was performed for `KC_004915_S`; the no-deadline free classification is limited to that work, and other no-deadline works remain unknown. Bounded `from_url` / `through_url` Discovery is unsupported. The adapter requires the unique work-scoped `DIV.EpisodesTabContents_root__* > UL.EpisodesTabContents_episodeList__*` container and exact visible expansion control `\u5168{N}\u8a71\u3092\u8868\u793a` when present. It waits at most 12 seconds for two identical scoped snapshots 500 ms apart; the validated episode-row count must equal the declared total. Page-wide recommendations and teaser links do not count.

Every row is validated before any record is yielded. A row must be a direct `LI` with exactly one episode link; the unique `EpisodeThumbnail_title__*` title node must be contained inside that link. The URL must identify the same work and a unique episode. Saved episode URLs are canonical query-free paths. Publication dates and deadline dates are separate from the title node and do not become the order label. Any malformed row, sibling title outside the link, duplicate ID, wrong-work identity, unsupported query, unknown deadline syntax, gate-like text, changed work metadata, missing title, or incomplete count fails closed. Valid records are buffered and emitted newest-first.

The observed ended-publication marker is `\u305d\u306e\u4ed6\u306e\u8a71\u306f\u516c\u958b\u7d42\u4e86\u3057\u307e\u3057\u305f`. The only accepted marker shape is one attribute-free direct `LI` with exactly one direct paragraph, no links, no episode title, and no other text. Zero or one marker is allowed. The marker's direct-child index, exact text, and adjacent episode labels participate in settlement. Other non-episode children and multiple markers fail closed. It indicates that other episodes ended publication, but does not establish their IDs or lifetime ordering.

Source external IDs are `work_id:episode_id`; saved targets are canonical query-free episode paths. The adapter sets `allow_inferred_display_positions=False`: existing positions are preserved, new positions remain NULL, and no global position hints are emitted. Full Discovery may mark absent Sources unavailable only after a complete validated list. Incomplete full runs do not reconcile missing Sources. Incremental Discovery leaves unseen Sources unchanged. Reusing the same external ID preserves the Source and its Item, Completed status, CrawlRuns, and Artifacts across disappearance and republication.

An exact future row deadline is classified as free and recorded as `free_until`; a later observed NULL clears stale expiry. A no-deadline row is classified free only for the independently verified work `KC_004915_S`. Other no-deadline works and expired deadlines remain unknown. The adapter reports `available=true` for validated public rows; gate-like row text fails closed.

The shared Discovery service initializes `Work.title` from `WatchlistTarget.label` and does not apply `DiscoveredItem.canonical_title`. Kadocomi validates and exposes the work-page `og:title`; it does not rewrite Work metadata. Use the actual work name in the dedicated Watchlist label.

## Current P2 capture implementation

`KadocomiAdapter` accepts only the direct WEB path, rejects auto/quota/entry-only use and all quota resources, and requires one exact episode URL. The P1 Discovery and P3 Policy establish Catalog eligibility; capture does not re-open the work list. The Runner's one initial navigation targets the canonical query-free episode URL. A page observer installed before navigation records only main-frame document responses; initialization requires an HTTP 200 final response and every redirect in that navigation to retain the configured work/episode identity. It waits a bounded interval for one visible H1 whose `【order】work` heading agrees exactly with both `og:title` and `document.title` plus the observed Kadocomi suffix, rejects visible dialogs, and then requires the settled native reader. No reload or second document navigation is issued. The Catalog source URL remains unchanged. Every capture rechecks URL and same-page metadata identity while retaining the existing native Blob, pixel, slot-order, and END proofs.

Before navigation, a bounded page observer retains eligible already-created WebP Blob references while preserving the site's original `URL.createObjectURL` and `drawImage` calls. It stores draw-time `currentSrc`, intrinsic dimensions, full source/destination rectangles, transform, alpha, composite mode and filter without retaining image elements or encoding pixels in the renderer hook. Capture requires the next unique canvas slot(s), an exact last full-frame identity `HTMLImageElement` draw, matching retained Blob identity, exact decoded Blob-to-canvas RGBA pixels, and unchanged pixels/layout/draw record after all asynchronous reads. Capture returns the original Blob bytes unchanged as WebP and releases consumed Blob references. Any missing or changed proof raises an adapter error; generic locator and screenshot fallback are disabled.

The active reader uses `.splide._root_1542n_1` inside `._mainScreen_191o7_1` and carries `splide--rtl`. Computed CSS direction was `ltr` in prior P0 inspection and `rtl` in the later 1920x1080 anonymous context; physical wrapper/canvas geometry, not that CSS value, establishes spread order. Wrapped content slots use `DIV._pageCanvasWrapper_k9w27_25[data-type="contents"]` containing exactly one `canvas._root_bx4cr_1`; wrapped canvases have no `data-type`. The strictly validated direct-first beginning-content variant described above instead types its first canvas directly. Twelve observed reader layouts are accepted through eleven strict adapter profiles; the mixed-final profile supports its two reviewed recommendation forms. Episode 4.1 starts with one slot, continues with paired spreads, and ends at the paired `n=1`,`n=2` main-reader END slide; its observed trailing recommendation slide has separate `DIV._root_1w5tt_1[data-type="end"]` and `DIV._endOfBook_1w5tt_50[data-type="end-of-book"]` and is never captured. The first-episode route starts with one content slot plus a PR item, continues with paired spreads, has one final content slot on a slide owning main END `n=2`, and then an empty terminal slide owning main END `n=1`,`n=2`. Episode 79 starts with one content slot, nine paired spreads, a final singleton owning `n=2`, and an empty paired END slide, followed by one recognized non-content recommendation slide owning the secondary END marker. Its PR `data-type=pr` item is not an END marker. Episode 22.2 starts at index 0 with no content slot and exactly one visible `data-type=beginning` root owning one positive-geometry `data-type=pr` child; the PR element has the observed secondary class prefix and no `data-n`. One ordinary ArrowLeft must advance to exact active index 1 with the same inventory, where the 18 content slots appear as nine RTL pairs; paired main END is at index 10 and the secondary recommendation is index 11. The observed Episode 20.2 starts with the same strictly owned empty beginning-PR slide, then five paired content slides, a final singleton at index 6 owning main END n=2, and an empty paired END at index 7 owning n=1 and n=2; no recommendation follows. Episode 8.2 adds a known empty beginning slide owning one secondary wrapper PR with null `data-n`, five paired spreads, a final singleton with main-wrapper PR `n=2`, and an empty paired END. Episode 7.2 has no beginning slide: its first content slide is a singleton, it requires at least one middle pair and `end index >=3`, and its final singleton is followed by the empty paired main END (`n=1`,`n=2`) and one recognized recommendation. The main-reader slide at index 0 owns a wrapper `data-type=pr,n=1` marker, and the final content slide (`end index - 1`) owns a wrapper `data-type=pr,n=2` marker; neither PR is an END marker. Native JavaScript and Python PR async-change tracking covers this validated content-first/final-PR profile and the validated paired-first and direct-first profiles described above. Existing content-first profiles retain their prior nonconstraint on unrelated PR metadata. The accepted beginning-PR mixed-final profile requires at least one paired content slide (end index >=3), not a hardcoded five. One validated ordinary ArrowLeft enters content; ordinary overlay turns traverse the observed five spreads, and after the final singleton is captured, one ArrowLeft reaches the empty END. Unknown or duplicate beginning/PR markers, unsafe/hidden targets, no advance, skipped turns, or changed inventory fail closed. The entry action applies only to this observed empty-first-slide topology; PR metadata on existing content-first layouts stays outside their historical acceptance rule. For the mixed-final layouts, the final source is captured before a safe `ArrowLeft` requests the exact next empty END; the following recommendation is never entered. Marker class, number, slide owner and positive in-slide geometry, along with the complete content inventory, are rechecked across snapshots and capture. Extra/unknown markers, slides or content, skipped turns, or changed inventory fail closed. The new Episode 79 extension passed independent code review (45 targeted tests, BLOCKING=0); normal CLI and independent all-20 source/RGBA-to-ZIP audit passed; final post-Discovery audit passed; final live-evidence Reviewer gate passed (BLOCKING=0, NONBLOCKING=0) and Lead accepted the bounded target; the prior milestone documentation review passed (Reviewer BLOCKING=0, NONBLOCKING=0). These original seven variants were verified on the observed routes on work `KC_004915_S`; the additional paired-first double-END evidence is scoped to the exact `KC_011605_S` route described above. Current per-capture limits are 4 MiB per Blob and 8,000,000 total decoded pixels.

Local browser fixtures exercise one exact episode navigation, byte-exact native WebP output, right-to-left order, and explicit END for all eleven observed layouts. They cover wrong Blob attribution, asynchronous canvas mutation, transformed draws, 404/500 responses, non-render, delayed or inconsistent same-page metadata, dialogs, foreign-episode redirects, main and recommendation END omissions/ownership/duplicates/wrong numbers, content at END or recommendation, extra slides, missing terminal pairs, reversed slots, skipped turns, and final keypresses that do not advance. The first bounded production Runner attempt failed closed because code looked for `data-type="contents"` on the canvas instead of the wrapper. The original 21-slot episode 4.1 path and 38-slot first-episode path passed independent live source/ZIP audits and Reviewer gates. Episode 79's bounded all-20 native source proof and empty-END transition passed independent review (45 targeted tests, BLOCKING=0); normal CLI and independent all-20 source/RGBA-to-ZIP audit passed; final post-Discovery audit passed; final live-evidence Reviewer gate passed (BLOCKING=0, NONBLOCKING=0) and Lead accepted the bounded target; the prior milestone documentation review passed (Reviewer BLOCKING=0, NONBLOCKING=0). Those CLI/ZIP audits predate direct entry. The full local test set for the direct-entry change and current Ruff results are recorded in `runbooks/kadocomi/PROGRESS.md`.

Independent Tester used a separate normal-renderer Blob/draw hook to audit all 21 saved P2 page files: every file matched its corresponding WebP Blob byte-for-byte, decoded to 836x1200, and had zero RGBA mismatch against its canvas. Physical slot x-coordinates descended in right-to-left order; 11 ordinary one-slide advances, including the final advance to END, reached explicit END with the same episode identity. This is independent viewer-source-to-page-file verification for the observed renderer, not a ZIP audit and not a claim that opaque original network responses carry those bytes.

## Current P3 direct-only Batch integration

`KadocomiSitePolicy` admits only available `kadocomi` Sources with `access_mode=free`, a strict work-scoped external ID, and either NULL `free_until` or a valid aware future value. Expired/equal, malformed, naive, quota, paid, unknown, owned, grant, rental, and unsupported IDs are ineligible. NULL means no deadline was observed by Discovery; it does not independently grant free access. P1 classifies no-deadline sources as free only for the verified work `KC_004915_S`.

Manual Crawl, Batch adapter, and Batch Policy CLI registries include Kadocomi. Manual crawl requires `--access-strategy direct`; auto/quota and all named resources remain rejected. A Batch run requires a canonical query-free exact Catalog episode target matching the configured external ID. Catalog availability, free classification, and deadline eligibility remain the P1 Discovery/P3 Policy authority. The Runner navigates directly to the exact episode once; the Adapter rejects unsuccessful document responses, redirect identity changes, inconsistent same-page metadata, visible dialogs, and a reader that does not settle. It does not re-run Discovery or navigate to the work list at capture time.

The local end-to-end fixture runs Discovery, Catalog, Planner, Executor, Runner, and the production packager. It confirms native WebP bytes in the ZIP, canonical source identity, Catalog title/order metadata, ZIP Artifact registration and Completed only after explicit END. In the current direct-entry fixtures, HTTP 404, HTTP 500 with otherwise valid viewer content, non-render, foreign-episode redirect, missing/inconsistent metadata, and visible dialogs fail closed; policy expiry remains covered by Site Policy tests. Runtime failures leave the Item pending and create no ZIP/Artifact. The earlier P3 targeted and affected regression results are historical checkpoint evidence; current direct-entry test results are in `runbooks/kadocomi/PROGRESS.md`.

## Current P4 independent live validation

Tester used a fresh isolated Watchlist, Catalog, output root, and library for one live CLI Batch run of the exact episode 4.1 target. Full Discovery returned 53/53 complete; incremental returned 5 known and left 48 unseen Sources unchanged. With 52 non-target Items skipped in the test Catalog, the normal `batch run --limit 1` captured 21 WebP pages, reached explicit END, and created one archive Artifact and one Completed Item. An independent audit matched every ZIP member byte-for-byte to both the P2 page file and independently observed live renderer Blob; all CRCs passed and all members decoded to 836x1200 WebP. ZIP SHA-256 is `d64fd2a66c6982c3045a70940b36846cd7f12af4685551f9488174673099e6ff` (3,278,163 bytes). Full/incremental rediscovery preserved the completed Artifact and Catalog target identity. The actual-catalog renumber dry-run proposed no moves because all positions remain NULL; one isolated synthetic apply preserved archive bytes. No real archive was renamed.

The CLI removes temporary page output after packaging, so P4 validates ZIP, run/status, Artifact, and Completed state rather than a retained manifest. The final P4 sweep completed 15 selected target episodes across initial and resumed runs, plus the Episode 22.2 control retest. ZIP hashes, per-file comparisons, the preserved first-attempt failures, and final Catalog state are recorded in `runbooks/kadocomi/PROGRESS.md`; the first 22.2 failure remains unexplained. No fresh independent P4 Blob/RGBA observer was run for the 8.2, 7.2, or 22.2 ZIPs. Final live-evidence Reviewer and Lead gates passed; Final documentation review PASS (Reviewer BLOCKING=0; Lead accepted bounded scope).

## Observed evidence and limits

The anonymous public list for `KC_004915_S` settled to 53 of 53 distinct episode rows in the exact list container, plus one ended-publication marker. The visible labels run 1 through 26 and then 78/79. The marker text is `\u305d\u306e\u4ed6\u306e\u8a71\u306f\u516c\u958b\u7d42\u4e86\u3057\u307e\u3057\u305f`, between `\u7b2c26\u8a71\u305d\u306e2` and `\u7b2c78\u8a71`. Exact missing episode IDs and lifetime numbering remain unknown. Forty-six rows showed an explicit 2026-10-14 11:00 delivery deadline and seven had no deadline. Official Comic Walker help describes WEB as a free manga portal and says episodes without configured deadlines may end without notice. Anonymous readability of a no-deadline episode was independently confirmed only for this work.

The work detail `og:title` and `document.title` are `\u592b\u5a66\u4ee5\u4e0a\u3001\u604b\u4eba\u672a\u6e80\u3002\uff5c\u30ab\u30c9\u30b3\u30df (\u30b3\u30df\u30c3\u30af\u30a6\u30a9\u30fc\u30ab\u30fc)`. Its H1 is chapter-prefixed and is not a Work title. A query-free exact episode route returned the same work/episode identity as the observed `co=true&episodeType=first` row link; saved episode locators omit those query values.

Independent P2 research retained five WebP Blob references created by the normal renderer without replacing the site's `URL.createObjectURL` call. Draw-time `HTMLImageElement.currentSrc` mapped DOM slots 0, 1, 2, 19, and 20 to the exact Blob and content canvas. The observed byte lengths were 169566, 141084, 133452, 126880, and 199144, with RIFF/WEBP signatures. Five full-RGBA comparisons had zero mismatches. Each observed image and canvas was 836 by 1200 with a full-frame identity draw. These are native viewer source-image bytes, not proof that opaque initial network responses contain the same bytes.

Ordinary `LEFToverlay` navigation traversed 21 content slots over 11 right-to-left content slides while staying on the exact episode. The next slide had no content and exposed the two main-reader wrapper markers with data-n 1 and 2. The 21 canvases were children of content wrappers, not themselves marked `data-type=contents`; a separate PR element was excluded. No source bytes or copyrighted pixels are stored in the repository.

The adapter requires per-capture currentSrc-to-immutable-Blob provenance, dimensions, full-frame identity, pixel equality, exact work/episode/page identity, safe state, validated content order, and one of seven observed layouts represented by six strict main-reader profiles. Screenshot fallback remains disabled. The original two variants passed independent review and live CLI/ZIP/source audits for the verified work. Episode 79's strict trailing-recommendation variant passed bounded live source/END proof, local Runner/Batch tests, independent code review, normal CLI and independent all-20 source/RGBA-to-ZIP audit, final post-Discovery audit, and final live-evidence review. Episode 22.2's bounded source/END probe, local Runner/Batch tests, independent code review, and normal CLI/ZIP run passed. The 21-slot Episode 4.1 CLI control also passed; its current control audit verified the ZIP and END but did not compare against prior per-page source bytes. Final post-Discovery/backup and P4 Reviewer audits passed, and Lead accepted the bounded scope. The direct-entry Runner probe described below is earlier evidence and did not itself run Batch CLI. Other works, additional reader layouts, transformed draws, and no-deadline variants on other works remain unverified.

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

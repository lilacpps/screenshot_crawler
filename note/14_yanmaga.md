# 14. YanmagaWeb (`yanmaga.jp`) 現行実装ノート

## Odd-page terminal-only reader position (2026-11-17)

Chapter 15 (Item 49631 / Source 49938) failed in normal Runs 25364 and 25427
after all 15 body pages had already been saved as native WebP. After the final
14/15 spread, the viewer's next turn displayed only the next-episode rental
card. Its exact native `#menu_seekbar > #menu_slidercaption_base >
#menu_slidercaption` changed to `-/15`; the last body moved beyond the right
viewport edge and the rental occupied x=1280, y=0, width=1272, height=1800.
The old positive-number counter parser returned no snapshot, so change-wait
timed out instead of recognizing the terminal position. This was neither a
grant failure nor a missing captured page.

The ordinary public body-counter parser remains unchanged: `-/N` and N+1/N
are not body counters. A separate private snapshot mode recognizes only the
unique native caption/ancestry with exact `-/N`, odd N>=3, and the existing
page-total bound. It uses an internal terminal position N+1, never a body
identity or capture target. General total/duplicate/route/viewport/menu/gate
checks still apply. The layout must have zero visible body wrappers, one loaded
final N wrapper with the verified three-segment geometry and full height,
all retained bodies beyond the right viewport edge, and the exact native
rental slot above. The whole rental must be presented and own its center and
eight inset perimeter points.

END additionally requires the already captured sequence to be exactly 1..N
and an existing proven terminal-card branch. For a next/read card, the unique
normalized title must also match the unique immediately following same-work
listing row; signup/wait/point/latest-author retain their existing stronger
bindings. No click or next-episode navigation is performed. A terminal-only
screen at initialization may be rewound through the existing bounded normal
ArrowRight path, but cannot become END without all body pages being saved.
Exact max-pages=N still permits final END, without a fabricated N+1 image.

The dash counter also precedes the actual slide animation. Change-wait first
waits for the same terminal layout/control signature to stabilize, then applies
the positive-END predicate within the original deadline. It never presses a
second key or spends the same budget on two successive stabilization waits.
Transient body-visible/card-offscreen frames remain pending; malformed,
obstructed, wrong-title, incomplete-sequence or unsupported layouts do not end.
Diagnostics retain raw `native_counter="-/N"`, expose `terminal_only` and
`terminal_only_layout_exact`, and set `native_counter_complete=false` for this
mode rather than pretending the UI reports N/N. Existing complete body-count
and sequence fields remain separate.

The synthetic odd-three-page viewer starts on this terminal position, rewinds,
captures all three body pages, and tests both next/read and point cards. It
also covers delayed layout, bad/even/foreign/duplicate caption, wrong title,
missing control/final wrapper, edge obstruction, wrong card size, visible body,
and premature terminal entry. The final targeted group passed 14 tests with 0
skipped, including explicit refusal to supply a body identity at `-/N`.
The first live implementation exposed the counter-before-animation race and
failed closed after saving all 15 pages; its isolated evidence is retained
under `output/yanmaga-png-investigation/fixed-odd15-final/`. That incomplete
attempt is not a successful crawl or Artifact verification.

The final post-stabilization live check used a fresh isolated Catalog backup,
the exact normal Planner candidate, real `BatchExecutor`, shared CDP Page, and
normal packager. It completed Chapter 15 with 15 pre-JPEG WebP pages, zero PNG,
positive END, ZIP, Completed, and one Artifact in that copy. The final UI had
`-/15`, no visible body, a fully presented exact rental slot, and the proven
next/read card. The previous stored grant was preserved exactly. Source GET=1,
Viewer GET=1, other-episode/non-GET requests=0; quota/Work-resource state and
the normal pending Catalog were unchanged. Evidence:
`output/yanmaga-png-investigation/fixed-odd15-stable/` (`report.json`,
`reader-trace.json`, genuine Manifest, Catalog, archive, and `audit.json`).
`odd15_audit.py` independently verified the 15 ordered Manifest members,
fingerprints, unique VP8L/opaque 1125×1600 decodes, ZIP CRC, real Artifact and
Completed state, and absence of a terminal-card/fake page-16 entry. Archive
SHA-256 is `c86179f88aa54abbccb67ffa6937fa6230ffffa9bca5216ff1fc944c479ad7b1`;
the convenient exact copy is `fixed-odd15-stable/chapter-15-fixed.zip`.

Adapter Unit/browser regression passed 198 tests with 0 skipped (477.07 seconds;
23 existing asyncio/Python deprecation warnings). After the final bounded
terminal-stabilization adjustment, all 14 affected odd-terminal cases passed
again with 0 skipped, including counter-before-animation and no terminal body
identity. Ordinary parser checks explicitly reject dash and N+1/N as body
counters. `ruff check src tests` and changed-files diff checks passed. Full
repository pytest and unrelated-site/Discovery suites were not rerun for this
site-local counter/layout/END change; shared Core, Catalog, resource policy,
capture format, and browser lifecycle code are unchanged. Other terminal
layouts, even-total dash states, and one-page dash states remain unsupported.

## Chapter 17 existing-rental recovery and delayed layout (2026-11-16)

The reported normal Run 25360 (Item 49628 / Source 49935, Chapter 17) stopped
in listing preflight with zero saved pages and no Source or Viewer entry.
Catalog still classified the Source as `free` from the 14:21 observation and
had no stored grant. An earlier 17:35 attempt had reached the requested Viewer
but failed first-free notice/finite-grant confirmation before persistence.
The later listing was markerless with a rental countdown. A metadata-only live
probe confirmed an authenticated exact active Rental History card (`残り21時間`)
and a finite conservative hour bound. Internal full Discovery already emitted
`quota` plus `access_granted_until_observed=true` for that exact row; the Adapter
had ignored that fresh evidence because its separate Catalog-grant input was
empty. The original entry's precise consumption time remains unproven.

For direct/auto capture only, the current Adapter can recover this exact state:
authenticated, markerless raw-unknown row; no public/first-free/wait/red or
restricted marker; internal Discovery's explicitly observed future grant;
and a fresh second Rental History observation for exactly the requested ID.
The second proof must be active with aware, future, finite hourly evidence and
an observation no later than now. It retains the earlier of the Discovery and
second bounds. After the existing live listing/URL/login/row pre-entry check,
the existing synchronous `ConfirmedAccessGrant` observer must save that bound
before Source GET or capture. Missing/duplicate/foreign/inactive/unbounded,
expired/malformed, future-observed or conflicting evidence, missing observer,
row drift, and persistence failure stop before Source entry. A still-future
Catalog grant keeps the old path and is not extended or reported again.

Only the source grant/timestamp is persisted through the existing site-neutral
observer. No access-mode rewrite, inferred use time, quota start, Work cooldown,
resource attempt, or fixed 24/72-hour lifetime is introduced. Day-only evidence
is intentionally outside this automatic recovery path because the current
observer's supported countdown category is hourly; normal full Discovery can
still import a validated day bound for the existing trusted-Catalog-grant path.
The quota/work-ticket attempt path never silently switches to recovery.
`history_grant_recovery_state` records `not_attempted`, `candidate`,
`reconfirmed`, or `persisted` in site-owned capture/failure metadata.

The first isolated Batch check saved the recovered grant before its one Source
GET, then failed after page 1 with `page turn did not reveal a new body page`.
A second bounded same-grant check completed all 14 pages; its numeric reader
trace proved that every turn's counter could lead the old visible frame by
several reads. The wait loop had treated even a still-stable old captured frame
as an immediate failure. It now continues observing the same turn inside the
original deadline until an advanced, stable uncaptured body is proven. No
second key press, forced identity, skipped page, or timeout extension is used.
If the layout never arrives it times out. Page-total, route, geometry, gate,
sequence, max-pages, and same-content protections remain. Diagnostics now also
include `native_counter`, `visible_body_indices`, and `captured_body_indices`.

Final verification used a fresh isolated SQLite backup and Watchlist copy,
selected the exact normal Planner direct candidate, and ran the real
`BatchExecutor` with its normal grant observer and packager. Chapter 17 reached
positive END, 14 pre-JPEG WebP pages, ZIP, Completed, and one Artifact in that
copy. A route observer independently checked the grant was already durable
before Source entry. Source GET=1, Viewer GET=1, other-episode/non-GET requests=0;
quota and Work-resource state were unchanged. The normal Catalog remains
pending with no grant and was not written by these checks; its next Batch run
will perform the same verified recovery automatically.

Evidence is under ignored `output/yanmaga-png-investigation/`:
`access17-preflight.json` is the metadata-only probe; `fixed-access17/` is the
grant-persisted/page-turn-failed check; `fixed-access17-retry/` is the successful
pre-wait-fix check with `reader-trace.json`; and `fixed-access17-final/` is the
post-fix real Batch verification with its genuine Manifest, ZIP, Catalog,
reader trace, and report. Final archive SHA-256:
`6ed9db258fdea0df7994356b5799b952bbc87ee85af52ac181b91629d043bbcc`.
The genuine Manifest's ordered members and all fingerprints matched the ZIP,
which passed CRC. Each run was limited to the one exact existing rental; no
ticket/point action or next-episode entry was performed.

Final verification: the complete Adapter Unit and browser Integration files
passed **185 tests, 0 skipped** in 426.24 seconds (23 existing asyncio/Python
deprecation warnings). Targeted recovery/layout checks passed 17; the earlier
affected access/grant group passed 45. Cases cover exact finite evidence,
min-bound persistence before capture, missing/duplicate/wrong-target evidence,
inactive/unbounded/day-only/future-observed/expired/malformed bounds, missing
observer, write failure, pre-entry DOM drift, delayed layout without extra key
presses, and bounded timeout if layout never arrives. `ruff check src tests`
and changed-files diff checks passed. The final offline audit also verified
all 14 unique VP8L/opaque 1125×1600 images, Manifest identities/fingerprints,
and the isolated Catalog's real Completed/Artifact state. It is
`fixed-access17-final/audit.json`; a convenient exact copy of the archive is
`fixed-access17-final/chapter-17-fixed.zip`. Full repository pytest and
unrelated-site/Discovery suites were not rerun because the changes are
Yanmaga Adapter entry/wait logic and existing-observer use only. No shared
Catalog schema, Batch, resource rule, or Core code changed.

## Chapter 29 point-rental END and decoded-segment recovery (2026-11-16)

The normal Batch failures for Item 49615 / Source 49922, Runs 25265 and 25266,
saved all 14 body pages of `第２９話 調和` before timing out in `go_next`.
The saved diagnostics prove a complete counter/sequence, correct route, hidden
menu, unobstructed final body and rental card/title. The next Chapter 30 card
instead had the observed point-rental CTA `レンタルして読む`; none of the
previous next/read, signup, countdown, or latest-author branches accepted it.
One failed run had all 14 WebP pages, while the other had 13 WebP plus one PNG,
so the END failure was independent of the last page's file format.

The current point-card branch requires all existing complete-body, route,
ownership, semantic-gate, and stable-END checks. It additionally requires one
presented exact `a#js-btn-rental.mod-button--orange.rental.content`, its direct
native `form#form-rental.ga-viewer-rental-point`, POST to same-origin HTTPS
`/viewer/rental` without credentials/query/fragment, one hidden 20-alphanumeric
`jdcn`, one hidden `rental_type=point_rental`, and positive displayed point cost.
The observed CDN thumbnail path must contain that exact code. The unique
normalized title must match the unique immediately following row of the fresh
same-work listing. Other terminal controls conflict. Point-code identity and
button geometry participate in the stable snapshot signature. The form and
button are observed only; no submission, point use, or next-episode entry is
performed. Diagnostics expose the point-card count, presentation, exact-shape,
and following-row proof booleans, without hidden form/account/token values.

An isolated same-grant capture first verified the END correction with 13 WebP
and one PNG. The separate bounded PNG trace identified the remaining cause:
the regenerated middle segment of page 14 had exactly the same JPEG payload
as its predecessor, but 1,151 RGBA channels differed by one. The predecessor
was retained and valid; this was an actual pre-JPEG pixel collision, not missing
history or a memory cap. The strict pre-JPEG matcher correctly rejected it and
remains unchanged for this case; no tolerance or newest-candidate guess is used.

When the pre-JPEG attempt specifically reports `segment_source_not_exactly_bound`,
the adapter now tries the actual currently selected DOM image objects for the
whole visible group. It reuses the complete geometry/style/ownership proof,
validates each Blob as a bounded static JPEG (Content-Length and body size at
most 1 MiB, JPEG MIME and signature), and reads opaque sRGB pixels at intrinsic
segment dimensions. These are composited at the existing offsets/crop into
1125×1600 and encoded as lossless WebP with exact RGBA round-trip verification.
Only current browser-owned Blob URLs are read; this adds no server request.
Actual image-object identities, immutable source URLs, geometry, and styles are
revalidated through composition, encoding, and the final atomic spread check.
Unknown/changed sources, non-JPEGs, or failed proof still use the safe PNG path
or stop on changed body identity. No JPEG-image tolerance is added to pre-JPEG
attribution, and all existing observer/transfer/page/retry caps remain.

The lower source level is explicit: `capture_method=decoded_viewer_segment_lossless_webp`,
`capture_provenance=decoded_visible_image_composition`,
`source_native_bytes_used=false`, `source_native_pixels_used=true`, and
`pre_jpeg_pixels_used=false`. A successful pre-JPEG capture sets the last flag
true. The group retains the original native `fallback_reason`; a failed decoded
attempt also records `decoded_failure_reason`. Both successful pixel paths use
intrinsic dimensions, never a resized Locator screenshot. Decoded JPEG pixels
are not claimed to be the earlier pre-JPEG pixels or original server-page bytes.

The final same-grant shared-CDP `CrawlerRunner` verification reached positive
END with 14 WebP pages and zero PNG: 13 pre-JPEG pages and one decoded-source
page. Page 14's decoded WebP matched every RGBA byte of an independent direct
DOM-image reference composition. All 14 files passed ordered Manifest hashes,
unique fingerprints, VP8L/opaque decoding and dimensions; the exact-members ZIP
passed CRC and every fingerprint. ZIP SHA-256:
`caa6e5d6156e57f600597538e5ccde95366da2fe0600e7b0b1550bc38dc905a1`.
One exact Source GET and one exact Viewer GET were used, with zero other-episode
or first-party non-GET requests. The stored grant and null quota start were
unchanged. This isolated verification did not rewrite normal failed runs,
mark the normal pending Item completed, or create a normal Artifact.

Evidence is under ignored `output/yanmaga-png-investigation/`:
`fixed-point29/` is the END-only 13-WebP/1-PNG run;
`point29-png-diagnostic/observations.json` records the exact collision;
`fixed-point29-final/` contains the genuine Manifest, `decoded-reference-audit.json`,
`audit.json`, and `chapter-29-fixed.zip`. The QA wrapper's native-attempt log
still reports the page-14 native failure; the final Manifest and report record
the successful decoded-source result. `audit_point29_final.py` is the offline
artifact/Catalog audit. The observation does not guarantee other point-card
layouts or that every unavailable source can avoid the retained PNG fallback.

Verification: `tests/unit/test_yanmaga_adapter.py` and the entire
`tests/integration/test_yanmaga_adapter_browser.py` passed **169 tests, 0
skipped** (406.75 seconds; 23 existing asyncio/Python deprecation warnings).
Coverage includes normal/native/decoded capture, exact all-pixel references,
whole-spread selection, non-JPEG rejection, image/style drift, menu/gate/END,
point-card positive and malformed/hidden/conflicting cases, resource entry,
and Batch success/failure packaging contracts. `ruff check src tests` and the
changed-files diff check passed. Full repository pytest and unrelated-site
Integration/Discovery tests were not rerun because this changes only Yanmaga's
capture and END contracts. No normal-Catalog Batch or extra paid/ticket action
was performed; same-episode live verification and its offline audit are above.

## Native capture: regenerated-segment PNG fallback (2026-11-16)

The production observer now accepts a regenerated segment only with one fresh
exact-byte candidate and a still-bound immediately preceding same-payload
candidate with complete validated pixel history. After asynchronous Blob
reading, dimensions and every immutable RGBA byte must be equal. A successful
comparison carries that history forward; released history, any intervening
rejected copy, differing RGBA despite identical JPEG, or multiple fresh matches
still reject pre-JPEG attribution. The decoded-source path above may then be
used after its independent proof. A later rejected Blob preserves earlier proven bindings.
Full pixel comparisons run outside viewer hooks, no additional pixel copies
are retained for history, and all existing caps and source/style/spread proof
checks remain. Observer stats add `regeneratedBlobBindings`.

The normal Catalog's latest Yanmaga Run 25261 completed `双星のアポクリファ`
`第５３話 帰路へ` (episode `b7ae4530792bea5b258f31967418f513`) with 16
pages. Its existing archive contains WebP pages 1–9 and PNG pages 10–16;
its SHA-256 remains the Catalog Artifact's
`955509d9128388c9cb32f591e25b69c93eb370eaf0f52ebacc6429920db39bac`.
The original observer events were not logged, so that run's exact internal
event sequence cannot be established retrospectively.

Two fresh shared-CDP, isolated `CrawlerRunner` runs of the same public-free
episode reproduced `segment_source_not_exactly_bound`: both reached positive
END with 16 pages, WebP 1–13 and rendered PNG 14–16. Production capture code
was unchanged. A QA-only instrumented observer logged bounded candidate,
exact-byte Blob match, URL binding, and release events. Blob URLs were replaced
by document-local numeric IDs in these logs; no source pixels or JPEG payloads
were exported into the event log. Each run made one exact Source GET and one
exact Viewer GET, with zero other-episode or first-party non-GET requests.
The normal Catalog, its Artifact, and its archive were not rewritten.

The observer initially copied and bound 48 segments. During navigation the
viewer generated nine more segments, with JPEG payloads equal to existing
bound candidates. The pre-fix `matchBlobParts()` searched both pending and
already bound candidates; the duplicate triggered its ambiguity branch,
removed the previous `byUrl` entry, and released both candidates. The new Blob
was marked invalid and not bound. The later DOM images for pages 14–16 used the new URL IDs,
so preserving only the previous bindings would not recover those pages.
Capture then waits up to the existing 750 ms bound and falls back for the
whole visible group. Neither run had pixel-buffer overflow, hook conflict,
Blob read failure, or outstanding reads at the failed captures. The exact
viewer-internal reason for regenerating these segments was not instrumented.

The second diagnostic compared the immutable pre-JPEG RGBA arrays: all nine
duplicate pairs were dimension-equal and byte-for-byte pixel-equal. This is
evidence for the observed regeneration, not a general JPEG-to-RGBA equivalence
rule. Two offline synthetic browser cases independently reproduced the old
binding's removal: one used identical pixels, while the other changed one
source channel by one and still produced identical JPEG bytes. Consequently,
accepting repeated JPEG bytes alone cannot safely recover native pixels.
The current pre-JPEG correction uses the exact pixel-history proof above rather
than accepting JPEG equality alone. Missing/released history remains a pre-JPEG
limitation; decoded-source proof is now attempted before the safe PNG fallback.

A fresh post-fix shared-CDP `CrawlerRunner` recapture of the same Chapter 53
reached positive END with all 16 pages native 1125×1600 WebP and zero fallback.
The unmodified production observer reported 57 copies, 57 exact bindings,
nine regenerated bindings, and zero ambiguity/miss/read-failure/overflow/hook
conflict. One exact Source GET and one exact Viewer GET occurred; other-episode
and first-party non-GET requests were zero. The isolated
`fixed/chapter-53-fixed.zip` has SHA-256
`410f21db7a0fc615b2ed53992bada4811193470cc8e3a5b0e61791dd33a4d12f`.
All 16 files passed unique-hash, Manifest identity/order, VP8L/opaque decode,
dimensions, and ZIP CRC/member/fingerprint checks. The old normal archive's
hash and the completed Catalog Item were independently rechecked unchanged.

Evidence and QA scripts are under ignored
`output/yanmaga-png-investigation/`: `summary.json`, `probe.py`, `synthetic.py`,
`audit.py`, and each run's `observations.json`, `report.json`, and genuine
`capture/manifest.json`. `baseline/` stopped during listing preflight because
the initial QA request allowlist incorrectly blocked `/episodes`; the corrected
`baseline2/` and `attribution/` runs are the successful recaptures. The isolated
`attribution/chapter-53-diagnostic.zip` preserves the final recapture's exact
16 Manifest files. Its SHA-256 is
`e05cebe51a6c066767804e12060814ffba5729b64c7c95f9cad48648d2fb5c3d`.
The post-fix output, `fixed/audit.json`, and `audit_fixed.py` are in the same
ignored investigation directory. `probe.py fixed` selects the production
observer without the prior QA observer-script instrumentation.

Verification: both offline synthetic causal assertions passed; all 32 recaptured
files passed Manifest hash, image decoding, MIME, dimensions, and sequential
group-identity checks; the diagnostic ZIP passed CRC, exact member order, and
all 16 Manifest fingerprints. Post-fix affected native Unit/browser Integration
passed 34 tests (0 skipped, 115 deselected), including two regeneration rounds,
exact native output, preserved old bindings, pixel-collision rejection,
released/rejected history, and simultaneous fresh-candidate ambiguity. The
final rejection-history assertions were rerun with the encoder and existing
Batch recrawl-sidecar boundary: 6 passed, 0 skipped, 249 deselected. Recrawl
Unit tests passed 105 with 0 skipped. `ruff check scripts/prepare_recrawl.py
src tests` passed. The initial targeted group passed 7 with 0 skipped; its
pytest cache permission warning was avoided in the later checks by disabling
the cache provider. Existing asyncio deprecation warnings remain. The full
suite and unrelated site Integration were not rerun for this site-local
capture fix and explicit recrawl-policy entry. The earlier offline synthetic
probes are pre-fix causal evidence, not current-production expectations. The
instrumentation and request routing can affect timing, so a fixed PNG boundary
is not guaranteed, and original-run attribution remains qualified as above.

### Recrawl preparation

`scripts/prepare_recrawl.py` explicitly supports Yanmaga with WebP preferred
and PNG fallback at every position; JPEG is unexpected. The existing
classification and backup/apply services are reused. The normal-Catalog
dry-run below reported Item 49591 as `FALLBACK_INCLUDED`, preferred 9 / fallback
7, with one recrawl candidate and no unexpected/ambiguous/missing archive.
No `--apply` was performed. Apply-policy Unit coverage verifies unchanged ZIP
bytes after backup, Source and CrawlRun preservation, and Item-to-pending.

```powershell
.venv/Scripts/python.exe scripts/prepare_recrawl.py --site yanmaga --item-id 49591 --show-all
```

The default is read-only scanning; an explicit `--apply` moves the old archive
to the configured backup tree and returns the Item to pending. It does not
start capture, reset rights, or change the site's live access semantics.

## Existing-unknown Rental History recovery (2026-11-16)

Authenticated full Discovery now joins raw-unknown listing rows and same-work
trusted-grant targets to one bounded native Rental History observation. An
exact active card with a fresh finite countdown promotes a raw-unknown row to
`quota` and stores the conservative observed expiry; it does not infer
`quota_started_at` or a cooldown. Active history without a finite bound,
missing/duplicate evidence, and identity mismatches do not promote a row, and
`owned` rows are excluded. A still-valid trusted grant preserves its existing
mode and expiry when active; the new history bound never extends it. The join
does not enter a Source or Viewer or consume a right.

Root's normal-Catalog full Discovery repair changed only the three exact
`work-dual` rows for chapters 26, 27, and 29 from `unknown`/no grant to
`quota`/finite grant. The standard run preserved Source/Item identities,
Completed state, Artifacts, acquisition flags, and work state; its direct plan
did not consume a resource. Source, Viewer, and rental POST counts were zero.
Evidence: `output/yanmaga_access_experiment/followup-active/normal-repair-v1/report.json`.
The isolated validation run and normal-Catalog repair both used the updated
full Discovery path. Focused tests passed 96 with 0 skipped and 126 deselected;
the full suite was not rerun.

## Stage 02 current implementation (2026-11-16; capture and post-capture audit verified, PASS / BLOCKING 0)

The C sort and canonical/og corrections and BODY pre-live review passed
independent review with BLOCKING 0. A metadata-only probe verified the Rental
History helper for the already opened alias `episode-ff-probe-01`: H=17 at
2026-11-15T08:11:29.019643Z produced
`site_countdown_lower_bound=2026-11-16T00:11:24.019643Z` as GET start plus
(H - 1) hours minus 5 seconds. This lower bound is not an absolute expiry or a
fixed 24-hour lifetime. That probe used zero additional rights. A separate
metadata-only check planned one direct candidate, `episode-ff-capture-01` at
position 31, without rights; it differs from the earlier position-32 episode.
The preparation Catalog contained 1 Work, 57 Items, 57 Sources, and 57
SourceTargets. The selected target IDs were Work 1 / Item 27 / Source 27 /
Target 27; these are identifiers, not row totals.

C1 used one additional first-free entry on position 31. It confirmed the exact
Viewer and completion notice, then synchronously stored the finite countdown
lower-bound grant before pixel-readiness work. After readiness and rewind, the
intentional `capture_page` failure occurred before the first content page was
saved. C2 retried without rerunning the external Catalog DiscoveryService; the
Adapter did perform its fresh internal listing preflight and preserved the same
future-aware grant. Both runs used one Source GET and one Viewer GET; C2 used no
new first-free right. Each run had zero other-episode and first-party non-GET
requests. At the C1/C2 checkpoint, the Item was pending, both CrawlRuns had failed after
readiness and rewind but before a content page was saved, and no Artifact,
quota start, or Work resource state had been created. Research plus C1 account for two confirmed first-
free uses; the additional allowance is now exhausted. Ticket, point, coin, and
paid actions remain zero.

The adapter permits a normal public-episode GET only for a fresh exact
first-free candidate after rechecking the authenticated work identity, row,
marker, and queryless public URL. Because this GET may grant access
automatically, it requires the exact Viewer, visible body wrapper and counter,
no known gate, the exact first-free notice `無料レンタルが完了しました`, and
fresh finite same-target Rental History evidence. The site-neutral grant is saved synchronously before pixel
readiness. Unknown evidence, route drift, or persistence failure does not
trigger another entry. Trusted existing grants require a still-future Catalog
bound and fresh active evidence for the exact target.

C1 and C2 verify grant persistence and preservation through intentional
capture-hook failures after readiness/rewind but before the first saved content
page. Post-C2 v4 metadata Discovery and the one-candidate direct plan were
independently audited. C3 stopped before Source entry on an incorrect QA
request budget. C4 ran once and failed in the normal CLI after one Source
and one Viewer request; no genuine Manifest page progress or ZIP was saved.
The C4 failure does not establish a site failure. Its diagnostics are
preserved. C5 ran once and failed before content capture because the body did
not stabilize. The Item remained pending, the existing grant was preserved,
and no Artifact was created. C6 used the existing grant and verified one Source
302 to exact Viewer 200 chain and one content-info XHR, but the body still did
not stabilize. The run failed with page_count null; the Item stayed pending,
the grant stayed unchanged, and no Artifact was created. No additional right
was used. C7 then saved 13 native WebP pages and reached reader counter 14/14,
but did not establish END or create an Artifact. Inspection identified the
false stop: the broad modal-class gate matched a nonsemantic inline rental card
inside the unique `#rental` auxiliary. The adapter now exempts only the observed
static class/id shapes inside `#rental`. Semantic dialogs and existing body
ownership, viewport, menu, pixel, page-count, and positive-END checks remain
unchanged. Synthetic browser coverage confirms that this inline card permits
the final body page and END, while a semantic dialog in the same card still
fails closed. The adapter Unit file passed 10 tests, the adapter browser file
passed 106 tests, and independent review reported 8 pass / 0 skip and BLOCKING
0. C8 then completed the same target through the ordinary CLI using the
existing future-aware grant and passive request observation. Run 8 succeeded
with 14 pages and positive END; Item 27 completed and one Artifact was present.
The genuine 14-page Manifest matches the ZIP exactly, and Root's artifact audit
passed. The ZIP contains 13 native WebP pages and one safe PNG fallback for the
last page (`segment_source_not_exactly_bound`). An independent visual check
confirmed the final page is chapter 27's ending page (`第27話 完`). C8 used one Source GET and
one Viewer GET, no other episode or non-GET request, and no new first-free
right; the saved grant was unchanged, with quota and work-resource state empty.

The passive watcher did not produce its auxiliary watch-result marker, so its
standard audit command could not run. Root directly audited the genuine
Manifest and ZIP successfully; no marker was fabricated and no retry was made.
Post-capture metadata checks then ran against the completed target. Full
Discovery exited 0 with 57 observed/known rows, `complete=true`, and
`stopped_reason=exhausted`; the before/after Catalog comparison passed. The
incremental CLI also exited 0 without error and observed 5 known rows, 0 new,
then stopped with `known_streak`. Its `complete` value is null, so incremental
completion was not evaluated and is not claimed. The incremental report did not
install the Source/Viewer request observer; those request counts are unknown.
The Catalog retained Source 27 as the only enabled source, Source 28 disabled,
Item 27 completed, the existing Artifact and grant unchanged, and quota state
zero. The post-full plan contained zero candidates because Item 27 was already
completed. The bounded work-intro popup observation found a visible
`DIV.mod-modal-close.js-modal-close`, but its one click did not confirm popup
disappearance; the listing remained at 57 rows with no More control, so no
further popup action was attempted. The ignored QA popup helper, including this
observed DIV shape, has only passed compile checks and has not been live tested.
The Stage 02 final independent review accepted the implementation with BLOCKING 0.

Post-C2 v4 full/incremental metadata Discovery completed with rights 0,
Source/Viewer/non-GET/fatal requests 0, and an independently audited exact
one-candidate direct plan. The report is
`output/yanmaga_access_experiment/stage02/metadata-only-v4-refresh-report.json`
(SHA-256 `0b62fbb74622ef25e30f4f38d64ebc0c30d112365b894a56cc99dc29b85a100b`).
Full Discovery was complete/exhausted with 57 observed rows; incremental had
complete=null/known_streak with five observed rows and did not yield the
target, while both snapshots contained 57 rows with the same authenticated
identity and position-31 ordering. Fresh history plus the trusted grant
preserved Catalog free mode and the future bound; the target flag was reapplied
after each run. Root's read-only Catalog audit confirmed the unchanged grant,
pending Item, IDs Work 1 / Item 27 / Source 27 / Target 27, zero Artifacts and
quota/resource state, two CrawlRuns, and one direct non-quota plan. No capture
was attempted. The v3 raw result remains unavailable, so its QA stop's
underlying production outcome is unknown.

C8 verified image capture, positive END, ZIP, and Completed for the selected
existing-grant target. The post-capture audit is recorded above: full Discovery
was complete/exhausted; incremental stopped at `known_streak` with
`complete=null` (not evaluated); and incremental Source/Viewer counts are unknown
because its request observer was not installed. Root directly audited the genuine
Manifest, ZIP, Catalog, and Artifact. The independent final review accepted Stage
02 with BLOCKING 0. Stage 03 has since implemented the observed wait-marker
classification, `work_ticket` Policy and one-shot modal entry. Run 10's postcondition
did not latch inline; Root later verified the exact native notice, Viewer, and
active history from retained evidence and recorded one use from a frozen exact-
history observation. Its timestamp is an observation anchor, not the precise
POST time. Same-grant attempts 3 and 4 exposed and fixed inline-card gate and END
recognition issues. Attempt 5 then completed the same target with 14 pages and
positive END; Root audited the genuine Manifest and ZIP, and the grant and work
cooldown remained unchanged. Post-capture full/incremental Discovery has also
completed. Stage 03 is accepted with qualified composite live evidence and
independent BLOCKING 0. Stage 04 has started. Its existing-grant work-novel
chapter-10 capture completed with 18 WebP pages and positive END; the grant was
unchanged. The work-dual chapter-51 public-free capture completed with 16 WebP
pages and positive END, with grant/quota state unchanged. Both ZIPs and
Completed states passed Root's artifact audits. Independent Tester audits of
both A6/A7 ZIPs, Manifests, Catalog state, and first/middle/final pages passed.
The affected scope passed 261 tests with 0 skips and 305 deselections. The final
Reviewer gate passed with independent BLOCKING 0; the full-suite run was controlled-stopped and
is not a full pass.

## Stage 03 current implementation (2026-11-16; qualified PASS, independent BLOCKING 0)

Authenticated Discovery classifies the exact image-only
`span.mod-episode-free_browse` marker as `quota` when bound to a unique
authenticated row/source without conflicting access markers. The image has no
text node; `data-is-free="true"` alone is not evidence. Metadata Discovery
verified 22 such rows among 57 in `work-dual` and 29 among 37 in `work-novel`;
two `work-dual` rows remain unknown. The visible exact
`.episode-free-time.charged` / `チャージ完了` is required before a ticket action.

Yanmaga Policy supports one work-scoped `work_ticket` pass, limit one,
after-observed-consumption persistence, grant-only, and the existing 23-hour
local cooldown. A trusted future Catalog grant plus fresh active same-target
Rental History remains direct without extending its stored expiry. Separately,
Discovery may import a fresh finite grant for an exact active Rental History
card when the current row is raw `unknown`; it does not infer a cooldown or
import an `owned` row.
The shared `entry_only` path writes no page Manifest or Progress state, image,
ZIP, or completed Item; failure diagnostics are metadata-only. Normal capture
output is unchanged. Yanmaga's `prepare_entry_only_page()` skips its
capture-only native pixel observer for the fresh Batch-owned Page; it does not
generalize reuse behavior for a Page that already has that observer.

Read-only Source GETs for `work-dual` chapter 29 and `work-novel` chapter 10
showed the exact episode-bound modal, three-day period, and normal same-origin
POST form at `/rental/episodes/<episode-id>/by_free_waits`. The first-free
notice remains exact `無料レンタルが完了しました`; ticket success uses the distinct
exact `レンタルが完了しました`. The work-ticket path does not accept a generic
notice or the first-free notice.

Dual chapter 29 Run 10 emitted one native ticket POST, but the then-current
production postcondition did not latch or persist it. Root later verified the
exact notice, Viewer, and active history from retained evidence and applied one
frozen exact-history observation to Source 25 and work cooldown state. The
observation at `2026-11-16T00:23:46.090627Z` showed `残り2日`, producing lower bound
`2026-11-17T00:23:41.090627Z`; this anchor is not the precise POST time. The
applied record is `stage03/dual/late-confirmation-applied.json`; reapplication
is rejected. Same-grant attempts 3 and 4 were incomplete: attempt 3 saved 13
pages before a reader-gate timeout; attempt 4 saved 14 body pages but did not
establish END. Root's saved page showed the next-chapter point/rental metadata inside the unique
`#rental` auxiliary. The site-local gate now excludes only the observed
`.episode-modal-point`, `dl.episode-modal-point--posession`,
`dl.episode-modal-point--necessary`, and `.episode-modal-short` nodes there;
semantic dialogs and all body/END checks remain gates. Attempt 5 then completed
all 14 pages with positive END and no new ticket POST. Root audited the genuine
Manifest and ZIP. The existing grant and work cooldown were unchanged. The
Stage 03 full/incremental post-capture metadata refresh also completed with zero
Source, Viewer, and native rental POST activity. Its audit confirmed the target
and completed Item/Artifact state remained unchanged. No second ticket submit
is authorized.

Novel chapter 10 grant-only run succeeded with `stop_reason=entry_confirmed`,
zero pages, pending Item 26, and no Artifact. It emitted one native ticket POST;
Source=3 and Viewer=2 are request totals whose route types were not recorded.
The updated automatic notice/history proof and persistence succeeded. The
Source grant expiry is `2026-11-17T09:35:11.467066+09:00`; quota start and work
last-consumed time are `2026-11-16T09:35:16.467066+09:00`. The report is
`stage03/novel/grant_only-report.json`. These are the two Stage 03 ticket uses;
no more ticket action is authorized.

Wait and trusted-history parsing accepts exact `残りH時間` or `残りD日` within the
explicit 72-hour bound. For D>=2 the lower bound is observation start plus
(D-1) days minus 5 seconds with evidence `site_day_countdown_lower_bound`;
D=1 and H=1 prove active access but have no finite expiry. No fixed 72-hour
grant is created. Ordinary first-free remains capped at 23 hours and rejects
day notation.

Focused synthetic verification: Rental History browser tests 37; wait-ticket /
rental-form browser selection 18; first-free adapter regression 15; adapter and
policy unit files 41. Six initial first-free failures were caused by a fixed
November 15 test grant that had expired; the test fixture now uses a fresh
relative timestamp and all selected tests pass. Independent review of the
notice/day/late-record code passed BLOCKING 0. Five focused browser cases cover
the observed terminal countdown branch, and the Yanmaga adapter unit file passed
10 tests. Attempt 5 completed 14 pages with positive END and an audited genuine
Manifest/ZIP; the existing grant and work cooldown remained unchanged. The
post-capture full/incremental metadata refresh also preserved the target,
grant, and artifacts with zero Source, Viewer, and native rental POST activity.
Stage 03 is accepted with qualified composite evidence and independent BLOCKING
0. Stage 04 A6/A7 captures completed: work-novel chapter 10 used its existing
grant for 18 WebP pages; work-dual chapter 51 used public-free access for 16
WebP pages. Both reached positive END, ZIP, and Completed with no new right and
unchanged grant/quota state. Pre/post full/incremental Discovery preserved
Catalog state without Source, Viewer, or native rental POST. Independent Tester
audits passed. The affected scope passed 261 tests with 0 skips and 305
deselections. The final Reviewer gate passed with independent BLOCKING 0; the full-suite run was
controlled-stopped and is not a full pass.

## Latest-listed terminal follow-up (2026-11-16)

The normal Catalog still contains the original failed chapter-53 item and its
saved output. A separate isolated Catalog/output copy was used to verify the
new latest-listed END branch. On that copy, Source 49898 / Item 49591 completed
Run 25261 with 16 pages and `stop_reason=end`; the final UI had the observed
author-follow card and matched the unique last row of the complete fresh
listing. The run used one Source GET and one Viewer GET, with no other episode
request or ticket POST. Root audited the genuine 16-page Manifest and ZIP
(SHA-256 `61f770a67145554065ea67f9ccec243abc91f6f8030451845eb314adb90e53f4`).
The isolated run did not modify the user's normal Catalog or overwrite the
original failed output. Focused verification passed 30 relevant adapter browser
tests and 10 adapter unit tests; no full-suite rerun was performed.

## Discovery target pacing (2026-11-13)

CLI/GUI Discover uses shared `discovery_inter_target_delay_ms` (3000 ms in
the root YAML) after this target closes, only before another target starts.
The first/single/final target adds no delay; site changes retain the previous
site setting. Existing listing-page waits remain independent. See
[shared runtime details](00_core.md#phase-1-runtime-settings--pacing).
Synthetic CLI/worker ordering is verified; live timing is unverified.

## Stage 02 Discovery sort identity correction (accepted sub-gate)

The initial C implementation assumed canonical and og:url remained unqueried
after selecting the oldest-first control. A bounded, read-only production
Yanmaga Discovery uses `YanmagaDiscoveryAdapter` with the standard
`DiscoveryService`; the adapter does not write Catalog directly. The optional
`configure_source_snapshots(target, snapshots)` hook receives an immutable
tuple filtered to the same site and exact Discovery key. Discovery rechecks
the full listing after asynchronous Rental History proof and emits no rows on
identity or content drift.

Shared Batch adds a site-neutral immutable `ConfirmedAccessGrant` observer.
The Executor binds it to the validated Catalog source and synchronously
calls the grant-only Catalog API before capture continues. That API updates
only the source grant expiry and timestamp. The schema is unchanged; other
site adapters retain default no-op hooks, and Runner remains Catalog-free.

### Historical main integration baseline (2026-11-06; pre-Stage 02)

At the original integration checkpoint, Batch required an explicit
Watchlist and synchronized acquisition scope. The split Yanmaga Unit,
Viewer, Discovery, CLI, registry, and common Planner/Executor selection
passed 407 tests with 0 skips, and the historical full Ruff and independent
review checks passed. Those counts describe that earlier baseline, not the
current Stage 02 implementation. The Stage 02 affected tests and final full
suite status are recorded in `runbooks/yanmaga-access/PROGRESS.md`.

## URL・Identity

- HTTPS / exact host `yanmaga.jp` / canonical work path
  `/comics/<slug>` を要求する。query、fragment、認証情報、foreign host、
  foreign redirect、canonical/`og:url` の不一致を拒否する。
- Episode identity は作品slugと32桁小文字hex IDの組
  `<decoded-work-slug>:<episode-id>`。Catalogのweb targetは作品slugを保持する
  公開URL `/comics/<slug>/<episode-id>`。
- `discovery_scope` は未対応。`supports_bounded_discovery=False`、
  `allow_inferred_display_positions=False`。

## Listing・順序

`.detailv2-episodes` 内の `.mod-episode-item` 全件を検証する。行ごとに
一つのanchor、同じwork slugのepisode URL、表示中のrow、非空の
`.mod-episode-title` を確認する。`もっと見る` の
`.mod-episode-more-button` だけを通常clickで展開する。limit/offset/sort/path
とrow挿入位置を検証し、追加IDが既存IDと重複せず既存順序が保たれること、
一覧が安定すること、他の有効なpaginationがないことを確認する。
最大100回/5,000行までで、未知のcontrol・重複・partial・driftは
`DiscoveryIncompleteError`。全レコードをbufferしてからyieldする。

Work pages are not assumed to be oldest-first by default DOM order. When the
observed sort controls are present, Discovery validates and selects the exact
oldest-first same-work URL. The resulting complete DOM order supplies
global_display_position; records are yielded latest-first. Without sort
controls, the existing oldest-first fixture contract remains. Order and
missing rows are never inferred from IDs, dates, or titles. A complete public
listing snapshot does not prove unpublished or future backend rows.

## Viewer・Capture

`YanmagaAdapter` binds the configured `<decoded-work-slug>:<episode-id>` to
the original Catalog `source_url` and freshly validates the exact requested
source. The normal public-free path still requires the exact visible red-free
marker. Stage 02 also permits one public-episode GET for a fresh authenticated
exact first-free row; that route may grant access automatically. The adapter
requires the exact Viewer, the exact first-free completion notice, and finite
target-bound Rental History evidence before synchronously persisting the
grant. A trusted stored
grant can authorize direct retry only when its Catalog expiry is still future
and a fresh same-target countdown is active. The markerless existing-rental
recovery above also permits a newly observed finite hourly grant to be
reconfirmed and durably saved through the Batch observer before entry.
Unknown, conflicting, expired,
or unsupported states fail closed. The Stage 03 wait path requires a unique
image-only marker, fresh charged state, verified no-target Rental History, and
the exact source modal/form before one normal `読む` click. The wait path
requires the distinct exact work-ticket completion notice. Novel chapter 10
grant-only verified the exact post-click Viewer, notice, active history, and
automatic persistence. Dual chapter 29 Run 10 required later frozen-history
recovery; its same-grant capture succeeded in a separate run. `direct`, `auto`,
and the bounded `work_ticket` strategy are supported; daily-limit scope remains
unverified.

実navigationではpublic episode URLが同じslug/episode IDを持つ
`/viewer/comics/<slug>/<episode-id>` にredirectした。Viewer URLには一度、
`cid` query field一つ（値は20文字のASCII英数字）が付いた形も観測した。
episode identityはstrict pathから判定し、no-queryまたはこの単一query形だけを
許可する。duplicate/additional/malformed query、credential、fragment、別host/slug/
episodeは拒否する。Adapter所有metadataには`cid`値を含めず、Manifestのsource URLは
元のpublic episode `source_url` のままにする。Generic Core failure diagnosticsは現在URLを
記録するため、このopaque query値が診断artifactに入る場合がある。ignored diagnosticは
sensitive扱いとし、commitしない。

### 観測済みsource pipelineとcapture方式

完全なページ画像を含むupstream配信は確認できなかった。対応upstream JPEGは
shuffleされたtile atlasで、viewerがatlasの矩形をcanvasへ複数回`drawImage`し、
3つのsegment canvasをJPEG quality 0.9で再encodeしてからbody imageのBlobを作る。
したがってatlasやJPEG segment bytesはページ原本ではなく、すでにlossyなtransport
imageである。

Observerはstrictなtop-level Yanmaga viewer documentにだけinstallし、確認済みの
`toDataURL('image/jpeg',0.9)`直前に限定サイズ・色空間のcanvas RGBAをcopyする。
JPEG payload、Blob bytes、body image `blob:` sourceに一意なfresh candidateをexact byte
matchで結びつける。同payload再生成時には下記の画素履歴証明も必須とする。
曖昧match、hook conflict、source drift、非opaque画素、
上限超過、未確認style/layoutはnative groupを拒否する。hookは元のviewer呼び出しの
引数・戻り値・例外を保ち、owned hookだけをcleanup時に復元する。
同じJPEG payloadの再生成では、一意なfresh candidateと直前の同payload candidateの
検証履歴・未解放のRGBA全byte一致をBlob非同期read後に確認する。履歴欠落・衝突・複数fresh
候補は拒否し、既存の検証済みbindingは保持する。第53話は修正後16ページ全WebP・ENDを
確認済み。詳細な判定とlive evidenceは本note冒頭を参照。

確認済みのnested DOMは`#content-pN > .pt-img > 3 absolute clipped segment host > img`
である。first-party page metadataとlogical `.pt-img` boxがnative pageを1125×1600と
定め、CSS scaleは1.125。source segmentsは1127×536、1127×536、1127×538で、native
Y offsetは0、532、1064。DOM順に重ねてlogical 1125×1600 boundsへclipすることで4-row
overlapと最終segment下の2-row overrunを処理する。wrapperのright paddingは0または2 CSS px
の観測形だけ許可し、viewer gutterは出力へ含めない。wrapperはpure horizontal translation
だけ許可する。segment host `::after`はcomputed styleが正確なempty content・fully transparent
で、border/shadow/filter/backdrop-filter/transform/blend/mask等のpaintがない観測形のみ許可し、
style proofはcapture後・spread全体でも再検証する。

再構成画素をsingle-frame lossless WebP (`VP8L`)へencodeし、opaque RGBA、1125×1600
dimensions、Pillow decode後のpixel equalityを確認する。Manifestは`image/webp` / `.webp`
を記録し、metadataは`source_native_bytes_used=false`、
`source_native_pixels_used=true`とする。source/geometry/style/group proofまたはencode検証が
不成立なら理由を記録する。`segment_source_not_exactly_bound`に限り、表示中の実img参照から
上記decoded-source pathをgroup全体で試す。こちらも証明できなければrendered locator PNGへ
fail-closed fallbackする。decoded経路はJPEG decode後の画素でありpre-JPEG画素とは区別する。
Fallbackは検証viewport 2560×1800で1266/1268×1800であり、source-native bytesとは呼ばない。

Readerはnative counter `1/36`、direct `#content-pN` wrappers、見開き時の連続2ページ表示。
初期位置が末尾でもbounded normal keyboard turnでpage 1へ戻す。capture前にはfirst page menuを
通常keyboard 1→2→1で隠し、stable hidden-menuと8-point perimeter proofを要求する。全body indexの
順次capture、route/counter/index/source/styleの安定性も必須。

positive ENDは全body indexのcapture完了、同じepisode route、stable final counter/body wrapperに加え、
別領域の単一`#rental` cardがviewport内に全体表示され、visibleで他elementに覆われていないことを要求する。
奇数ページで最後の見開きを送った後のnative `-/N` は、冒頭のterminal-only専用検証で扱う。
通常の本文counterやcapture identityにはせず、全本文保存済み・右側へ退避した最終wrapper・
既知のslotに安定表示された正しい次話card・全周の遮蔽なしを要求する。
既存のnext/read・signup・waitと新しいpoint-rental終端では一意のtitleが表示される必要がある。
signup・wait・point-rentalではさらにfresh listingの対応rowと一致することを確認する。
card内controlはexact `次の話を読む`一つとsignupなし、またはvalid-nextなしでexact
`無料登録して読む` signup control一つのどちらか。signup URLはsame-origin HTTPS
`/customers/sign-up`、credentials/fragmentなし、唯一のraw query fieldは
`forward=<32 lowercase hex episode ID>`。tokenはfresh same-work listingのunique immediate next row IDと一致し、
表示titleもnormalized exact matchする。tokenをURLとして解釈・遷移せず、CTAを操作しない。
これらのcontrolが無い場合は、unique immediate next listing rowがexact wait markerとして
分類され、表示titleと一致するときに限り、unique visible `.aspect-ratio-2-27.mt-wait >
div.episode-modal-wait.content` blockを代替終端として受け入れる。blockのdirect childは
`img.icon-clock`（観測済みclock asset）と`span`の順で、表示文言は`あとH:MMで無料`
（Hは0〜23、分は00〜59）に一致する必要がある。countdownや他controlは操作しない。
これは終端cardの一種として本文全page capture、route、ownership、semantic-gate、安定性検査を
置き換えない。完全なfresh listingで対象話が一意な最後のrowの場合は、例外として、同じ
`#rental`配下にある観測済みauthor-follow cardを終端証拠にできる。対象話のtitle、next/read、signup、wait markerは存在してはいけない。
一意の`a.author-info`、正確な表示文言`作者をフォローして次の更新を待つ！`、観測済みX/arrow画像、HTTPS `x.com`リンクと既知祖先構造を要求する。リンクは観測だけで、押さない。
このbranchでもbody/route/ownership/access-gate/ENDの他検証はすべて維持する。
観測済みpoint-rental cardも冒頭の厳密なform/thumbnail/title/表示検証で終端にできる。
`レンタルして読む`やformは押さず、ポイントを使用しない。他の終端controlとの競合は拒否する。
Unknown layout、page gap/duplicate、spread片側欠落、未知auxiliary/access gate、source/style drift、
終端不明はfail-closed。next arrowは診断のみ。

## Access behavior: current Discovery evidence

The login observer is attached before work-page navigation. It accepts only
main-frame telemetry while the current page and frame identify the requested
work document, resets on main-frame navigation, caps matching events at 64, and
detaches on every exit. It retains the exact `ep.is_logged_in` state only; it
does not retain complete request URLs.

Anonymous proof requires a visible sign-in link, no visible sign-out or exact
same-origin `/mypage` link, current work-document identity, no telemetry
overflow, and consistent explicit `ep.is_logged_in=false` values.

Authenticated proof requires a visible same-origin `/mypage` anchor whose exact
path is `/mypage` and which has no credentials, query, or fragment; no visible
sign-in link; current work-document identity; and no telemetry overflow.
Analytics is supporting evidence only: it may be absent, but any observed state
must be `true`. Visible, query/hash/userinfo, foreign-host, trailing-slash, and
hidden link cases are covered by browser fixtures.

A public-free row requires one visible `.mod-episode-point--free` element with
exact text `無料`, exact class name, computed color `rgb(220, 0, 0)`, and
no `.by_wait` or `.js-modal` marker, first-free label, or conflicting native
free badge. It is accepted only on a verified anonymous or authenticated work
document.

A first-free row requires authenticated proof, exactly one total
`.mod-episode-point--free` marker and one first-free marker, exact text
`初回無料`, and the exact class-token set
`{mod-episode-point--free, by_first_time}`. Wait/modal markers, a red-public
marker, or another conflicting native free badge leaves the row unknown. A
numeric normal point badge may coexist. Only these observed public-free and
first-free states map to `access_mode=free`; other access states remain
`unknown` and every row remains `available=True`.

Yanmaga sends `free_until=None` on each refresh because no free-expiry value was
observed; under the existing Catalog refresh contract this clears a stale
free-expiry value. A public listing does not assert a new grant expiry, so
`access_granted_until_observed=False` and Catalog preserves an existing grant.
Fresh exact-target Rental History evidence retains a previous mode only while
its trusted stored expiry remains future; it does not extend that expiry. For
raw-unknown rows, a fresh exact active card with a finite countdown imports a
new `quota` classification and observed expiry. Missing, duplicate, mismatched,
or active-without-finite-expiry evidence leaves the raw classification
unchanged; `owned` is excluded. The general Catalog contract still treats an
explicitly observed null as authoritative. Lead's isolated regression run
confirmed preservation and clear behavior.

The Stage 01 authenticated sample had no wait marker classification and kept
those rows unknown at that checkpoint. Stage 03 added the observed image marker
and charged-state requirement for ticket use; the later authenticated Rental
History join above recovers exact active rentals with finite bounds. Discovery
still opens no episode or access CTA. Paid-only classification and daily-limit
scope remain unverified.

Live evidence on 2026-11-15 JST: `work-dual` returned 57 rows after the
Discovery change: 27 first-free, 8 public-free, 22 unknown. The authenticated
shared-profile page had five visible exact `/mypage` links, no sign-in/out
labels, current work identity, and consistent true telemetry. The temporary
empty-context comparison had no `/mypage` link, two sign-in links, and false
telemetry. The wife-list continuation had no `data-limit`; the single authorized
listing GET remains unsupported by the strict pagination contract. Refer to
`runbooks/yanmaga-access/PROGRESS.md` and its isolated stage01 evidence files.

## 実サイト確認・テスト・既知の制約

Browser Integrationは、成功時とfailure時のobserver listener cleanupに加え、hidden row、foreign episode/canonical、
continuation sort drift、unsupported paging、no-progress、continuation fetch failureについて、recordをyieldせず
既存Catalogをunavailable化しないことを検証する。fetch/no-progressとhidden rowの待機はテスト内で短縮する。

指定作『ウサギとカメのゆる山歩』をshared Crawler Chrome/CDPとPlaywrightで
Discoveryした。native continuationを通常clickで展開後、13 unique rows、
continuation control消失、安定snapshotを確認。fullは13件完了、incrementalは
共通serviceのknown streak 5件で停止。current Catalog snapshotでは5件が`free`、
8件が`unknown`、global positionsは1〜13。Discoveryのlive検証では話を開かず、
チケット/ポイント/Grantを消費していない。これは現在のpublic listingの観測であり、
全バックエンド話数を証明しない。

対象Unit/Browser Integrationは `tests/unit/test_yanmaga_discovery.py` と
`tests/integration/test_yanmaga_discovery_browser.py`。URL/host、marker、
anonymous proof、展開・順序、full/repeat/incremental、stale expiryの消去、
incomplete fullの既存Catalog保護、Completed/Artifact保持、重複失敗を検証する。


### Phase 03 Viewer/Capture (N2/N4 accepted; Chapter 11 WebP Batch E2E passed)

N1の初回Runnerはrendered locator PNG fallbackを36ページ保存した。この出力は現在方式ではなく、
安全なcapture proofが成立しないときに使用するfallback pathの履歴として残す。
N2ではfresh shared-CDP normal `CrawlerRunner`を対象Chapter 1へ実行し、`stop_state=end`、
36 body indices、36 Manifest pages、36 filesを完了。全36が`native_pre_jpeg_lossless_webp`、
`image/webp`、1125×1600で、fallback reasonは0。別のoffline auditで36ファイルすべてを
Manifest SHA-256 fingerprintに照合し、36 unique hashes、single VP8L frame、decode success、alpha255を確認した。
Page 1/18/36を前回rendered PNG controlと目視比較し、本文全体・順序・cropが揃い、reader UI/広告/終端cardが
混入していないことを確認した。この比較はvisual/geometry確認でありpixel identityではない。
WebP encoderは各pageでcomposed RGBAとの厳密なdecode round-trip equalityを別途確認する。

Live output/evidence: `output/yanmaga_experiment/native-live-full-webp-20261020/`
(sanitized summary and offline audit). Complete original page responseは観測せず、保存形式は
viewer canvasのJPEG再encode前RGBAからのlossless再構成である。No ticket/point/quota/grant/next action。
The current Yanmaga Unit + browser Integration selection passed 76 tests, 0 skipped, with 23 existing pytest-asyncio/Python 3.14 deprecation warnings. Full `ruff check src tests` passed. N2 capture and N4 retention-cap changes were accepted by the independent Reviewer with BLOCKING 0. The normal Chapter 11 WebP Batch/ZIP E2E and exact all-20-page RGBA reference comparison passed; details are in the N4 and Phase 05 sections of `runbooks/yanmaga-free/PROGRESS.md`.

#### N4 bounded raw-pixel retention

An ordinary Chapter 11 preload reached the previous 96 MiB raw-pixel cap before first capture.
Separate first-party evidence showed 60 segment responses before first PNG and 145,157,600 raw
bytes for the known 20-page chapter, so 128 MiB was insufficient. The accepted fixed cap is
256 MiB (268,435,456 bytes) in both the Python helper and browser observer. The known 36-page
profile uses 261,283,680 bytes (about 249.2 MiB). This limits retained pixel arrays only; it is
not a preallocation or a limit on all JavaScript heap/Chrome RSS. Other finite bounds are unchanged.

The eager-60 browser regression verifies exact candidate binding, retained-byte accounting before
first capture, native WebP for page 1, and one-page release. A numeric test covers the exact cap
boundary without allocating a cap-sized buffer. A bounded isolated ordinary CLI probe observed
21 bound candidates / 50,805,160 raw bytes before capture, then 43,547,280 bytes after releasing
page 1; it saved one native 1125×1600 WebP and intentionally exited at `--max-pages 1`, without
reaching END or packaging. No page-ID association is inferred for the other retained candidates.

### Phase 04 Batch, extended by Stages 02 and 03

`YanmagaSitePolicy` admits an available, correctly identified `free` source
when its observed `free_until` is absent or still future. An available
`quota` or `paid` source is direct only with a valid exact episode identity and
a timezone-aware future `access_granted_until`. Without that grant, a validated
wait-free `quota` source uses one work-scoped `work_ticket` pass with
after-observed-consumption persistence. The resource supports grant-only while
ordinary free and first-free rows remain excluded from that pass. Malformed,
expired, or missing grants do not become direct; the Planner's existing
fail-closed behavior remains.

The capture adapter preserves three direct-entry cases: the public red-free
row, the fresh authenticated first-free row with one bounded source entry
and finite grant proof, and a trusted stored grant revalidated by fresh
same-target active Rental History evidence. A work-ticket candidate requires
the exact authenticated wait row and charged signal, a verified absent target
in the supported Rental History collection, and the observed same-episode
modal with its exact native POST form. Only its visible enabled `読む` button
may be clicked, once. The source modal and pre-click history shapes were
observed read-only. Run 10 made one normal click and emitted one native POST,
but its automatic postcondition did not latch or persist the use. Root later
verified the exact notice, Viewer, and active history read-only and applied the
frozen history observation once to Source/work state; its anchor is not the
precise POST time. The same-grant direct retry is described in the current
Stage 03 section above. No second click is authorized. Unknown access, paid-only without a trusted grant, identity drift,
or a visible gate does not authorize entry. Normal image, END, and packaging
checks remain strict.
A bounded Stage 02 C1 CLI run used one additional first-free entry on the
separate candidate `episode-ff-capture-01` (position 31; the earlier research
release was position 32). It confirmed the first-free access and synchronously
stored the native countdown's conservative lower-bound grant before an
intentional `capture_page` failure after readiness/rewind but before the first
saved content page. Source GET=1, Viewer GET=1, other episodes=0, first-party
non-GET=0. The Item remained pending, one CrawlRun failed with
`page_count=null`, and no page file, Artifact, quota start, or Work resource
state was created. This does not verify successful capture, END, ZIP, or
Completed state; the countdown lower bound is not the site's absolute expiry.
The separate C2 retry without an external Catalog DiscoveryService run has also
completed: the Adapter still performed its fresh internal listing preflight. It
used one Source GET, one Viewer GET, and the capture hook after readiness/rewind
but before the first saved content page, with no new first-free use, other-
episode attempt, or first-party non-GET request. The same future-aware native-
countdown lower-bound grant remained unchanged; the Item stayed pending, two
CrawlRuns failed before a content page was saved, and no Artifact or
quota/resource state was created. This does not verify successful capture, END,
ZIP, or Completed state.
Research plus C1 consumed two first-free uses in total; C2 consumed none, and the
additional allowance is exhausted. Ticket/point/paid actions remain zero.
Post-C2 full/incremental metadata Discovery and direct-plan validation are
complete and independently audited. The later C8 ordinary capture with the same
grant also completed successfully. Post-capture full Discovery and incremental
results, plus the Stage 02 PASS / BLOCKING 0 gate, are in the current-state
section above. The v3 QA stop's raw result is missing, so its underlying
production outcome remains unknown. Evidence is in the ignored Stage 02 reports documented by
`runbooks/yanmaga-access/PROGRESS.md`.

The earlier synthetic Batch Integration verified the normal public-free
path through Catalog planning, capture, ZIP CRC, Artifact, CrawlRun, and
Completed state. The separate Phase 05 live CLI evidence below is limited
to the observed Chapter 11 case and is historical site evidence.

### Phase 05 isolated real-site CLI (historical PNG E2E and current WebP E2E PASS)

Tester used an isolated Watchlist, Catalog, archive/output, and library under
`output/yanmaga_experiment/phase05-independent-token/`. Full Discovery completed 13 rows;
incremental observed five known rows; the initial plan contained five `free/direct` candidates,
eight `unknown` skips, and quota 0. Normal Planner order selected Item/Source 2, Chapter 11
(`aac67662e0d47437726ee7034126a8ea`); selection and access state were not manually changed.

The ordinary `batch run --limit 1` exited 0 with `stop_reason=end`. CrawlRun 1 succeeded with
20 pages. The ZIP contains exactly 20 ordered Manifest pages; CRC passed, each payload matched
the Manifest fingerprint, all PNGs decoded, and all 20 payload hashes were distinct. Eleven
images are 1266×1800 and nine are 1268×1800. Tester and Root independently audited the archive.
First/middle/last images show manga body pages without reader chrome; the final image has no
terminal card. ZIP SHA-256 is `e0f3fc218937699e957c5854633f70291d22069ca83284235f13029291d5cc88`,
size 53,755,787 bytes. The Artifact is `archive`/`zip`, state `present`, and matches the on-disk
ZIP; Item 2 is `completed`.

A repeated full Discovery (13) and incremental Discovery (5) preserved all Source/Item IDs and
display positions, Item `completed_at`, and Artifact. The final plan contains four direct
candidates, eight unknown skips, and one completed skip. No ticket, point, grant, login,
purchase, quota operation, signup CTA, or next-episode action was used. Ordinary CLI metrics
defaults remained enabled. The unique task metrics file was emitted to the CLI's default
`output/metrics` location, then moved by exact path into isolated QA; the Watchlist, Catalog,
archive, and capture output used dedicated paths throughout.

The Watchlist explicitly supplied label `yanmaga-usagi`; the archive path used fallback genre
`小説`. These explicit/fallback metadata values do not assert the site's displayed work title.
The successful capture in this E2E was rendered locator PNG output, not source-native bytes; it
predates N2 and does not verify the current WebP Batch packaging path. N2's 36-page Chapter 1
Runner traversal is separately verified above. The E2E proves only this observed Chapter 11
candidate/layout. The daily-free notice's scope remains unknown,
missing or conflicting anonymous analytics remains `unknown`, and other reader layouts are
unsupported.

Earlier failed attempts remain historical: the first reached the signup boundary after 20 pages
before a positive END contract existed; one subsequent attempt failed before capture on the
measured 2px p2/p3 wrapper overlap; another reached the end after 20 pages but failed closed
because the signup CTA's `forward` query was not yet recognized. The final strict predicate now
requires a same-origin HTTPS `/customers/sign-up` URL with no credentials/fragment and exactly
one raw 32-lowercase-hex `forward` value matching the unique immediate next row in the fresh
same-work listing and the normalized rental title. The token is compared only; it is never
interpreted as a URL or navigated. The CTA is never activated.

Historical Phase 05 combined tests: **209 passed, 0 skipped**, with 423 existing pytest-asyncio/Python 3.14
deprecation warnings (148.67s). `ruff check src tests` and `git diff --check` passed. Full
`pytest -q` and the standalone Research suite were not run because changes were site-local plus
registries and did not alter shared Core, schema, or Probe contracts. The independent Reviewer
accepted the current N2/N4 implementation with BLOCKING 0. The implementation commit recorded above predates the
N2/N4 follow-up. Detailed sanitized audit is in the ignored
`output/yanmaga_experiment/phase05-independent-token/qa/tester-report.md`.

### Current Chapter 11 native-WebP E2E

The first fresh ordinary CLI attempt in `output/yanmaga_experiment/nv-e2e3/` returned a
complete=false Discovery result with zero observed/new/known records; the isolated Catalog
contained only its Watchlist Work and no Items, Sources, Runs, or Artifacts. A single direct
normal CDP adapter diagnostic then completed with 13 rows, no continuation, HTTP 200 for the
work document and native episode-list request, and explicit anonymous telemetry `false` with
no overflow. It did not identify why the first CLI attempt was incomplete. The subsequent
unmodified ordinary CLI retry completed successfully; no production code was changed for this
transient/unreproduced result.

The successful isolated run returned full Discovery 13 and incremental Discovery 5. Its initial
plan contained five `free/direct` candidates, eight `unknown` skips, and quota 0; normal Planner
order chose Item/Source 2, Chapter 11 (`aac67662e0d47437726ee7034126a8ea`). Normal
`batch run --limit 1` exited 0 with positive END and 20 pages. All 20 Manifest entries are
1125×1600 native-pixel lossless WebP (`VP8L`), with unique payload hashes and no fallback. The
ZIP contains exactly those ordered pages, passes CRC and Manifest hash checks, and is 18,830,115
bytes with SHA-256 `8d32c1ba953e2093e4c42945ce8bd1c2ff940884d2c343f6b68dc5ba6d4232b5`. The
Manifest snapshot SHA-256 is `e4d0bdec2c96606023a10c085dd100d8c952b5a598f9e6343f50ea7da2d68daa`.
The Artifact is present and matches the ZIP; Item 2 is completed. Repeated full/incremental
Discovery preserved Source/Item IDs, positions, completion time, and Artifact; the final plan
had four direct candidates, eight unknown skips, and one completed skip.

Tester audit: `output/yanmaga_experiment/nv-e2e3/q/primary/archive-audit.json`;
Root's independent archive audit: `output/yanmaga_experiment/nv-e2e3/q/primary/root-independent-audit.json`.
Both passed. Tester visually checked first/middle/last body pages; Root's all-page contact sheet
and ZIP audit found body pages without reader UI or terminal-card contamination.
Independent reference capture obtained 60 segments for all 20 pages with no overflow, send failures, or scan errors. Pillow-composited references exactly match decoded WebP pixels. Tester audit: `output/yanmaga_experiment/nv-e2e3/q/tester-report.md`, `output/yanmaga_experiment/nv-refcontrol4/q/primary-vs-reference-audit.json`, and `output/yanmaga_experiment/nv-refcontrol4/q/assembly-report.json`; Root's independent comparison is `output/yanmaga_experiment/nv-e2e3/q/primary/root-independent-pixel-equality.json`.
No next-episode/signup action or ticket, point, quota, grant, login, or purchase operation occurred.

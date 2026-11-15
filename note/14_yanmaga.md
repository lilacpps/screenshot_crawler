# 14. YanmagaWeb (`yanmaga.jp`) 現行実装ノート

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
no known gate, the exact completion notice, and fresh finite same-target Rental
History evidence. The site-neutral grant is saved synchronously before pixel
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
02 with BLOCKING 0. Wait-free, paid-only classification, charged state semantics,
and 23-hour recovery remain unverified and unsupported. Stage 03 read-only
investigation has started; its implementation and Stage 04 have not started.

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
requires the exact Viewer, completion notice, and finite target-bound Rental
History evidence before synchronously persisting the grant. A trusted stored
grant can authorize direct retry only when its Catalog expiry is still future
and a fresh same-target countdown is active. Unknown, conflicting, expired,
or unsupported states fail closed. `direct` and `auto` are supported; ticket
or quota selection is not enabled. Daily-limit scope remains unverified.

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
JPEG payload、Blob bytes、body image `blob:` sourceの一意なexact byte matchだけで
candidateを結びつける。曖昧match、hook conflict、source drift、非opaque画素、
上限超過、未確認style/layoutはnative groupを拒否する。hookは元のviewer呼び出しの
引数・戻り値・例外を保ち、owned hookだけをcleanup時に復元する。

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
不成立なら該当のcapture group全体をrendered locator PNGへfail-closed fallbackし、理由を記録する。
Fallbackは検証viewport 2560×1800で1266/1268×1800であり、source-native bytesとは呼ばない。

Readerはnative counter `1/36`、direct `#content-pN` wrappers、見開き時の連続2ページ表示。
初期位置が末尾でもbounded normal keyboard turnでpage 1へ戻す。capture前にはfirst page menuを
通常keyboard 1→2→1で隠し、stable hidden-menuと8-point perimeter proofを要求する。全body indexの
順次capture、route/counter/index/source/styleの安定性も必須。

positive ENDは全body indexのcapture完了、同じepisode route、stable final counter/body wrapperに加え、
別領域の単一`#rental` cardとtitleがviewport内に全体表示され、visibleで他elementに覆われていないことを要求する。
card内controlはexact `次の話を読む`一つとsignupなし、またはvalid-nextなしでexact
`無料登録して読む` signup control一つのどちらか。signup URLはsame-origin HTTPS
`/customers/sign-up`、credentials/fragmentなし、唯一のraw query fieldは
`forward=<32 lowercase hex episode ID>`。tokenはfresh same-work listingのunique immediate next row IDと一致し、
表示titleもnormalized exact matchする。tokenをURLとして解釈・遷移せず、CTAを操作しない。
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
The adapter uses fresh exact-target Rental History evidence only to retain a
previous access mode while its trusted stored expiry remains future; it does
not extend or replace that expiry during Discovery. The general Catalog contract
still treats an explicitly observed null as authoritative. Lead's isolated
regression run confirmed preservation and clear behavior.

Stage 01's anonymous-only capture limitation was superseded by the Stage 02
first-free and trusted-grant paths described above. Wait-free and paid-only
classification, charged-state semantics, and 23-hour recovery remain unverified
and unsupported. Discovery itself opens no episode or access CTA.

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

### Phase 04 Batch, extended by Stage 02

`YanmagaSitePolicy` admits an available, correctly identified `free` source
when its observed `free_until` is absent or still future. An available
`quota` or `paid` source is eligible for the same `direct` strategy only
when it has a valid exact episode identity and a timezone-aware
`access_granted_until` later than the current time. Malformed, expired, or
missing grants fail closed. No Yanmaga resource or grant-only pass is
enabled; `quota_available` is not consumed.

The capture adapter preserves three direct-entry cases: the public red-free
row, the fresh authenticated first-free row with one bounded source entry
and finite grant proof, and a trusted stored grant revalidated by fresh
same-target active Rental History evidence. Unknown access, wait-free,
paid-only without a trusted grant, identity drift, or a visible gate does
not authorize entry. Normal image, END, and packaging checks remain strict.
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

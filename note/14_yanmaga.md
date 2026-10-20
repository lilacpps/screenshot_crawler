# 14. YanmagaWeb (`yanmaga.jp`) 現行実装ノート

## 現在の実装範囲

Phases 02-05 passed independent review for the observed Chapter 11 layout. The normal CLI Chapter 11 E2E used native-pixel lossless WebP for all 20 pages with positive END, Manifest/ZIP, Artifact, and Completed. Independent reference capture and pixel comparison also passed exactly for all 20 pages. The N2 follow-up completed the red-free Chapter 1 Reader to END with WebP for all 36 pages. Complete original server page bytes were not observed; verified output is reconstructed pre-JPEG viewer pixels, not original bytes. Daily-limit scope and other reader layouts remain unverified.


Discovery は `src/screenshot_crawler/site_adapters/yanmaga/discovery.py`
の `YanmagaDiscoveryAdapter` が担当する。AdapterからCatalogへ直接書かず、
標準`DiscoveryService`を利用する。Batchは既存Planner/Executor/Packagerを利用する。
共通Core、Catalog schema、他siteは変更していない。

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

実測のDOM順はoldest-firstであり、complete snapshotの位置を古い順1基準で
記録し、yieldはlatest-first。数値ID・日付・話タイトルから順序や欠落を
推測しない。現在配信されているpublic listingのcomplete snapshotの証明であり、
未公開/将来分を含むバックエンド全件の証明ではない。

## Viewer・Capture

`YanmagaAdapter` はCatalogの `<decoded-work-slug>:<episode-id>` と元の
`source_url` を照合し、Viewerへ入る直前に同じworkのcomplete anonymous
Discoveryを再実行する。current listingで対象が一意な赤い通常無料rowなら
通常navigationで同じepisodeへ進む。same-work complete listingで通常無料条件が
明確に消えた場合はresource unavailable、それ以外の匿名性/identity/DOMの不明や
競合はunknownで停止する。`auto` / `direct` のみを許可し、quota/resource方式を拒否。
初回無料/待ち/pointだけのrowは対象にしない。Daily limit注意の赤字rowへの適用範囲は
未確認であり、no-capの一般化はしない。Viewer上でlogin/quota/resource gateが
見えた場合も停止する。

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

## Access判定

追加のfail-closed条件: main-frame navigationごとにanalytics evidenceをresetし、requestのframe URLとPage URLの双方が
対象work documentに一致したrequestだけを受け付ける。subframeや前documentの値は採用しない。対象documentで64件を超える
一致field requestを受けたら、そのdocumentのanonymous proofを無効にする。可視の正確な「初回無料」labelまたは別要素の
native `mod-episode-point*` badgeで正確な「無料」表示が赤い無料markerと同じrowにある場合はunknownとする。rowの
detail/price要素に同じ「無料」文字列が繰り返されても別badgeとはみなさない。point表示の数値70だけならconflictにしない。

`free` は同一rowに一つだけ見える `.mod-episode-point--free` があり、
テキスト`無料`、class名完全一致、computed color `rgb(220, 0, 0)`、
同じrowに`.by_wait`/`.js-modal`がない場合に限る。さらにpage全体で、
`/customers/sign-up`の表示中sign-in/registration linkと、実測したanalytics
request query field `ep.is_logged_in=false` が必要。`ep.is_logged_in`の値は
request URL全体を保存せず、観測済みの2 analytics hostから対象fieldだけ読む。
Observerはnavigation前にattachし、最大64 eventを保持、最大3秒だけ正の
login stateを待ち、すべての終了経路でdetachする。sign-out、missing/undefined/
conflicting telemetry、markerの欠損/競合は`unknown`。表示ラベルだけ、
`data-is-free`、`data-modal`、point badgeの有無はfree判定にしない。

通常無料以外を`paid`/`quota`に分類しない。全listed rowは
`available=True`。無料期限は実測されていないため`free_until=None`を毎回送信し、
以前の期限をクリアする。`access_checked_at`/`last_seen_at`は現在のaware UTC。
ページの「無料は1日で読める数に限りがあります」という注意の赤字行への
適用範囲は不明であり、no-capの一般化はしない。Discoveryではepisode linkを開かない。

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

### Phase 04 Batch (Reviewer accepted)

`YanmagaSitePolicy`は正しいsite、available、`access_mode="free"`、有効な
`<decoded-work-slug>:<episode32hex>`、期限の安全な状態だけをeligibleにする。
期限が未観測の`free_until=None`は、Discoveryがfree分類を独立に立証している場合だけ
許可し、NULLからfreeを推定しない。awareな将来期限は許可し、期限切れ/equal、naive、
malformedは除外する。PlannerがPolicy呼出し前にfree expiryをparseするので、Catalog内の
malformed timestampはcandidate skipではなくplan全体をfail-closedにする。共通Core変更はない。

Batchは`direct`のみで、quota/resource/grant-only passなし。fresh same-work Discoveryで
target rowが現在も赤字通常無料と確認された場合だけViewerへ進む。明確にfreeでなくなった
targetはunavailableとしてskip、anonymous/identity/list状態の不明や矛盾はfailure/pending。
positive ENDと標準packagingが完了するまでArtifact/Completedを作らない。

Synthetic Batch IntegrationでCatalog Plannerからdirect candidateを作り、fresh free preflight、
4ページcapture、ZIP CRC、present Artifact、成功CrawlRun、Completedを検証する。再無料確認で
restrictedになったsourceはViewerへ入らずpending/Artifactなし。END不成立・synthetic ZIP失敗も
pending/Artifactなし。実サイトBatch CLI E2EとManifest/ZIPの独立Tester監査はPhase 05で実施済みで、
Chapter 11の限定ケースでpassした。最新のChapter 11 E2EはN2 native-pixel lossless WebP outputを通常CLIで検証した。
All-20-page RGBA reference equality passed: 60 control segments were captured without overflow, send failures, or scan errors, then independently composited and compared with decoded ZIP WebP pixels. All 20 pages matched exactly. The earlier zero-snapshot result was a QA observer initialization issue now resolved; details are in PROGRESS.

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

# 14. YanmagaWeb (`yanmaga.jp`) 現行実装ノート

## 現在の実装範囲

Phases 02–04 passed independent review, and the Phase 05 ordinary CLI E2E passed for the observed free Chapter 11 candidate. The fresh run produced and independently audited a 20-page Manifest/ZIP, present Artifact, successful CrawlRun, and Completed Item; rediscovery preserved the Catalog IDs, positions, completion timestamp, and Artifact. Final independent Reviewer accepted with BLOCKING 0; the implementation commit is recorded in the progress ledger. The daily-limit scope, other reader layouts, and source-native image bytes remain unverified.


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
episode identityは常にstrict pathから判定し、no-queryまたはこの単一query形だけを
許可する。duplicate/additional/malformed query、credential、fragment、別host/slug/
episodeは拒否する。Adapter所有metadataには`cid`値を含めず、Manifestのsource URLは
元のpublic episode `source_url` のままにする。Generic Core failure diagnosticsは現在URLを
記録するため、このopaque query値が診断artifactに入る場合がある。ignored diagnosticは
sensitive扱いとし、commitしない。

観測済み対象reader形状はnative counter `1/36`、direct childの`#content-pN` body
wrapper、見開き時の連続2ページ表示。初期位置が末尾でもbounded normal keyboard turnで
page 1へ戻す。全body indexの連続capture、wrapperの非clipped/非obstructed状態、各wrapper
内の3つのloaded overlapping segmentを確認し、見たことのあるbody wrapperだけを順番に
Playwright locator screenshotする。成果物は2560×1800 viewportのrendered locator PNGで、
original segment bytesではない。current image sourceは各snapshot内でSHA-256 fingerprint
化し、生URLを保持/露出せず、capture直前後のsegment/source/geometryが一致することを
確認する。sourceがsame dimensionで置き換わってもsnapshot driftとして失敗する。各segmentの
左右端はwrapper端から3 CSS px以内、最終segment下端はwrapper下端から−4〜+3 CSS pxの範囲を
要求する。この許容は検証済み描画のrounding/overlapに基づき、任意cropの復元には使わない。

positive ENDは全body indexのcapture完了、同じepisode route、stable final counter/body wrapperに加え、
別領域の単一 `#rental` cardとtitleがviewport内に全体が入り、visibleで、他elementに覆われていないことを要求する。
card内の終端controlは、exact `次の話を読む` valid-next controlが単一でsignup controlがない形、または
valid-next controlがなく、exact `無料登録して読む` signup controlが単一である形のどちらかである。signup URLはsame-origin HTTPSの
`/customers/sign-up`、credentials/fragmentなし、唯一のraw query fieldが`forward=<32 lowercase hex episode ID>`であることを要求する。
tokenはfresh full listingの同一work内で現episodeの直後にあるunique rowのepisode IDと一致し、表示titleはそのrow titleと
whitespace-normalized exact matchでなければならない。tokenは比較にだけ使い、URL構築やnavigationには使わない。どちらのcontrolも
viewport内に全体が入り、visibleかつcenter ownershipが必要。signup controlは現episodeの登録必要境界としてのみ認め、決して操作しない。
duplicate、conflicting、foreign、non-adjacent、title mismatch、malformedはfail-closed。必要なterminal signalは
cardとbody/index/route proofである。reader next arrowは通常読書中に表示状態が変わるためdiagnosticのみで、END判定には使わない。
全ての終端signalがbounded page-change window内で複数snapshotにわたって安定することを要求する。next-episode linkとsignup CTAは操作しない。
未知layout、page gap/duplicate、spread片側欠落、広告等未知auxiliary、access gate、capture中のsource変化、
終端不明はfail-closed。
fresh viewerのfirst pageでは、native full-screen `#menu` と
`#menu_header` / `#menu_controller` / `#menu_transparent` overlayが初期表示される場合がある。
shared-CDPの通常keyboard操作で1→2→1へ移動すると、同一episodeのまま`#menu`が
`display:none`かつ0×0になり、body wrapper周囲の8点すべてが自身または子孫要素を指す状態を観測した。
Adapterはこの既知のmenu形状だけをbounded initialization transition中に許容し、1→2の通常key、
同じreaderでの1へのrewind、stable hidden-menuと8-point perimeter proofを得た後にcaptureする。
他のoverlay、hideできないmenu、edge obstructionは画像保存前にfail-closedとする。

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


### Phase 03 Viewer/Capture (PASS)

fresh shared-CDP `CrawlerRunner`のnormal live runは `stop_state=end`、
36 rendered PNG captures、36-page Manifest、36 native body indices `content-p1`〜
`content-p36`を完了した。dimensionsは1266/1268×1800、capture metadataは
`playwright_locator_screenshot_png` / rendered DOM wrapperであることを示す。
Manifestの`source_url`は公開episode URLのまま。opaque `cid`はadapter所有
metadataには入らない（Coreの一般failure diagnosticsには現在URLが入る制約は前述）。
independent image auditは36 PNG全てをdecodeし、36 unique hashesを確認。
先行目視済みのpage1/18/36は同一内容、新ランで差分のあったpage29も本文画像と目視確認した。
ネクストepisode linkは操作していない。ticket/point/quota/Grant消費も0。

最後のEND proofは、全body indexの連続capture、同一episode route、final counter/wrapper、
viewport内で全体表示されcenter ownershipが確認された単一`#rental` card/title/
`次の話を読む` controlである。off-screen/obstructed cardをnegative browser testsで拒否した。
reader next arrowは通常操作中に表示が変わるためdiagnosticのみで、END gateには使わない。

対象adapter/Discovery/CLI/registry Unit・browser test群は158 passed、0 skipped、
pytest-asyncio deprecation warnings 423。geometry gate hardening後のfocused Unit/Browser
checksは23 passed、0 skipped。対応ruff checkはpass。Phase 03 independent Reviewerは
BLOCKING 0で受理し、geometry修正も独立再review済み。
Daily capの適用範囲と他のreader layoutは未検証。画像はrendered PNGであり、
original/native bytesの取得・復元は行わない。
共有DiscoveryServiceの
known streak実装は5件で、authority本文のdefault 2と差がある。本site実装では
shared behaviorを変更せず、5件をテストしている。

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
Chapter 11の限定ケースでpassした。最終結果は次節に記録する。

### Phase 05 isolated real-site CLI (E2E PASS for one observed candidate)

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
The successful capture is rendered locator PNG output, not source-native bytes. The E2E proves
only this observed Chapter 11 candidate/layout. The daily-free notice's scope remains unknown,
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

Final combined tests: **209 passed, 0 skipped**, with 423 existing pytest-asyncio/Python 3.14
deprecation warnings (148.67s). `ruff check src tests` and `git diff --check` passed. Full
`pytest -q` and the standalone Research suite were not run because changes were site-local plus
registries and did not alter shared Core, schema, or Probe contracts. Final independent Reviewer
accepted with BLOCKING 0; the implementation commit is recorded in the progress ledger. Detailed sanitized audit is in the ignored
`output/yanmaga_experiment/phase05-independent-token/qa/tester-report.md`.

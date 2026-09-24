# Jump+ J0 probe 現行観測ノート

## Scope

Production Site Adapter, Discovery, Site Policy, and normal Batch are
implemented. Jump+ Discovery remains latest-first, while normal Batch orders
pending candidates within each Work by `published_at ASC` (NULL last) and
`source_id DESC` for same-date ties. Jump+ has no supported automatic quota or
resource pass: paid episodes are eligible only when Discovery observed an
active manual rental grant. Point purchase, rental automation, ticket access,
and login automation remain out of scope.

このファイルのJ0 probe記録はviewer構造を調査した時点の履歴であり、現在の
production Discovery / Site Policy / Batchの挙動を置き換えない。通常のBatchは
Discoveryの取得順を変更せず、Batch PlannerのWork内orderingだけを変更する。

対象は次のepisode URLのみ。

```text
https://shonenjumpplus.com/episode/13932016480029111789
```

## Probe entry point

実装は `poc/jumpplus_probe.py`。shared Crawler Chromeへ既存の
`BrowserSession` / `resolve_cdp_endpoint()`でCDP接続し、probe自身はChrome
launch、profile選択、CDP接続処理を所有しない。

```powershell
.\.venv\Scripts\python.exe poc\jumpplus_probe.py `
  --url "https://shonenjumpplus.com/episode/13932016480029111789" `
  --output-dir "output\jumpplus_probe" --steps 3
```

`--steps`は最大5に制限される。対象episodeのhostまたは`/episode/<id>`が
変わった場合は自動操作を停止する。

## Live verification (2026-09-23)

指定URLでshared Crawler Chromeへ1回実行済み。結果は
`output/jumpplus_probe/summary.md` と `report.json` に保存した。

- 初期ページのviewportは`1302x986`のCSS viewport、devicePixelRatioは1.5。
- 初期DOMには`section.viewer.js-viewer`、
  `div.image-container.js-viewer-content.is-spread`、4個のvisible canvas、
  `img.page-image.js-page-image`が観測された。ページ全体にはviewer以外の
  imgも含まれるため、visible img総数だけを本文ページ数とは扱わない。
- `drawImage`はinit scriptを`goto()`前に注入してmetadataのみを記録した。
  初期状態では`HTMLImageElement`から764x1200 canvasへの9引数drawが確認され、
  変換はidentity、`source-over`、filter `none`、globalAlpha 1だった。
  createImageBitmapは未観測。drawImage hook内でencode、base64、hash、network
  access、全画像copyは行わない。
- 本文候補のresponseは
  `https://cdn-ak-img.shonenjumpplus.com/public/page/2/...` のJPEGで、
  10件を元byteのまま保存した。いずれも実ピクセルは764x1200。保存先は
  `output/jumpplus_probe/network_images/`。
- viewerのsource URLは`blob:https://shonenjumpplus.com/...`としてdraw時に
  観測された。CDN responseとの一対一対応はJ0では検証済みとしない。
- 初期state後、DOMの`page-navigation-forward` /
  `js-slide-forward`を明示的にクリックして3回遷移した。URLは全stateで
  対象episodeのまま、bounded DOM/image/canvas stability waitは成功した。
  `state_000`から`state_003`を保存した。次episodeリンクはDOMに存在したが、
  クリックしていない。
- DOM・script・JSON候補、`/episode/<id>` links、access関連表示を保存した。
  無料に相当する表示は観測したが、free/paid分類ロジックは実装していない。
- END / NEXT_CONTENTの専用signal、page count/current page/total pageはJ0で
  最終判定していない。

## J1 Capture PoC (2026-09-23)

`--j1 --steps 3`で再実行し、`output/jumpplus_probe/j1/`へ比較結果を保存した。

- `state_000`〜`state_003`の4 stateを取得した。各stateで8、10、12、14枚の
  `764x1200` canvasを観測した。
- 本文候補JPEGは16件保存され、全件`cdn-ak-img.shonenjumpplus.com`の
  `/public/page/` response、JPEG、764x1200だった。URL、response timestamp、
  byte length、raw SHA-256、decoded RGB pixel SHA-256、format、dimensions、pathを
  `candidate_images.json`へ保存した。
- canvasのraw `toDataURL("image/png")`は、対象canvasが
  `SecurityError: Tainted canvases may not be exported`となり利用できなかった。
  比較用にはstate安定後のPlaywright locator screenshotをfallbackとして保存した。
  これはraw canvas exportではなく、composited rendered canvasの観測である。
- drawImageでは、764x1200全体を描くcallに加えて、同じsourceから184x296の
  部分rectを多数描き、destinationへ配置するcallを観測した。transformはidentity、
  compositeはsource-over、filterなし、alpha 1だった。
- draw hookでHTMLImageElementをsource ID付きで軽量に保持し、state安定後にsource
  pixelを取得した。4 stateで合計76件のsource PNGを保存し、各sourceについて
  dimensionsとdecoded RGB pixel SHA-256を記録した。hook内ではencode/hashを行っていない。
- 4 stateの全captured canvasについて、16件のJPEG候補とのRGB pixel比較を行った。
  `exact_unique_match`は0件で、全て`no_exact_match`だった。
- CDN JPEGとblob sourceは、候補JPEGが同じstateに保存されていた38件で
  `exact_unique_match`、残り38件は候補未観測のため`ambiguous / unproven`だった。
  blob sourceとrendered canvasは比較可能な38件が全て`no_exact_match`だった。
- canvasのgeometry分類は44件すべて`tiled`。`is-spread`を全stateで観測し、canvasの
  screen x/y位置を`comparison.json` / `equivalence.json`へ保存した。reading orderは未確定。
- 保存JPEG候補を目視確認すると、輸送JPEG側はタイル状に配置が崩れている一方、
  rendered canvas側は漫画ページとして再構成されていた。partial sourceRectと
  no exact matchが複数stateで一致するため、J1では**tile/reconstructionを観測済み**
  と判断する。J1の範囲ではCDN JPEGをそのままLevel 1 original bytesとして保存する
  根拠は得られなかった。

比較詳細は各`j1/state_*/comparison.json`、全体結果は
`j1/comparison_report.json`、人間向け結論は`j1/summary.md`にある。

## J2 transport JPEG + drawImage mapping reconstruction PoC (2026-09-23)

J1の最新artifactを入力に、`poc/jumpplus_reconstruct.py`を実行した。
出力は`output/jumpplus_probe/j2/`に保存した。対象URLはJ1と同じ
`13932016480029111789`で、production Site Adapterやcapture runtimeは変更していない。

- `state_000`〜`state_003`の4 state、44 canvas artifactを処理した。うち14 canvasは
  当該stateでdraw callがあり、30 canvasはcanvas IDは存在するが当該stateのdraw callが
  観測されないstaging/prefetch候補として`inconclusive`にした。
- draw callの紐付けはcanvas width/heightではなく、hookの`draw.canvas.id`とcaptureの
  `canvasId`の一致だけを使用した。各drawにはhookの整数`sequence`を追加し、その順序を
  Pillow再構成で維持した。
- 14個のdraw対象canvasは全て、764x1200のfull-frame drawと184x296の16 tile drawを
  含む同一のgeometry patternだった。transformはidentity、compositeはsource-over、
  filterはnone、alphaは1、source/destinationは整数でscaleなしだった。
- transport JPEGとの対応はblob sourceのdecoded RGB pixel SHA-256とnetwork JPEGの
  decoded RGB pixel SHA-256で行った。10 canvasは対応するJPEGを得て17 drawを適用し、
  4 canvasはnetwork候補範囲外のため`unmatched_source`となった。
- 各canvasの最後にある`https://cdn-ak.shonenjumpplus.com/images/spacer.png`の
  canvas外`(-1,-1,1,1)` drawは、canvasへの影響がないことをgeometryで確認し、
  `ignored_non_content_noop`として記録した。勝手なsource mappingには使用していない。
- reconstruction画像、mapping JSON、visual difference PNGを各stateへ保存した。
  locator screenshotはraw canvas ground truthではなく、表示サイズを考慮したvisual
  referenceとしてのみ比較した。14 draw canvasのうち2件が`close`、8件が`likely`、
  4件がsource未対応による`inconclusive`だった。J2全体の判定は`inconclusive`。
- active draw canvasのgeometryは今回の4 stateで固定だったが、固定static permutationを
  採用する根拠とはしない。実ページのruntime mappingを使うOption Aを候補として残し、
  Option Bは採用しない。

J2の人間向け結果は`j2/summary.md`、全体結果は`j2/reconstruction_report.json`、
canvasごとのmappingは`j2/state_*/canvas_*_mapping.json`にある。J2では、transport JPEG
と観測mappingから正しい漫画ページを生成できるcanvasが存在することは確認できたが、
全canvas・全stateのsource対応とvisual対応が揃っていないため、`J2 reconstruction confirmed`
とはしない。

## Output contract

`initial/`には`page.html`、`dom.json`、`network.json`、`draw_calls.json`,
`scripts.json`、`links.json`、`screenshot.png`を保存する。`state_000`以降は
DOM summary、new network events、new draw calls、scripts/links、screenshotを
保存する。network body取得失敗は記録してprobe全体を失敗させない。本文候補
bodyの保存数は最大20件（今回の実行は16件）。J1比較結果は各stateの
`comparison.json` / `equivalence.json`、`equivalence_summary.md`にも保存する。

## Capture status (J1更新)

- original bytes: `rejected for observed candidates`。元JPEG responseは保存できたが、
  全J1 canvasとexact matchせず、tile/reconstructionが観測された。
- source-native: `transport source confirmed, direct page output rejected`。blob sourceの
  pixelは取得でき、観測可能な一部でCDN JPEGとexactだったが、rendered canvasとは一致しなかった。
- rendered canvas: `confirmed via screenshot fallback`。raw canvas exportはtainted
  canvasで拒否されたため、安定後のlocator screenshotを比較材料にした。
- screenshot: `confirmed`。viewport screenshotを各stateに保存した。

production capture方式はまだ実装していない。J1の推奨は`rendered canvas required`、
または観測済みtile mappingによる別途検証済みの再構成である。CDN JPEGの直接保存は
採用しない。

## Next investigation (J2後)

追加調査では、まずdraw時点のcanvasとsourceの対応を同じstateで保存し、
staging/prefetch canvasを比較対象から分離する。特に次を確認する。

1. unmatched sourceをnetwork response観測範囲内で減らせるか。
2. draw時点のcanvas pixelまたは同じcanvasのvisual referenceを取得できるか。
3. `is-spread`がDOMレイアウト上のspreadを意味する範囲と、readerのreading order。
4. viewer state内のcurrent/total pageとEND/NEXT_CONTENT signal。

不明なものは`unknown / not observed`として扱い、production adapterへの実装は
この確認後に別途行う。

## J2 hardening / JPEG-domain lossless reconstruction (2026-09-23)

指定URLをshared Crawler ChromeでJ1として再実行し、`poc/jumpplus_reconstruct.py`
を更新したJ2 PoCへ入力した。対象URLは
`https://shonenjumpplus.com/episode/13932016480029111789`、stateは
`state_000`〜`state_003`、canvas artifactは44件、draw callを持つactive canvasは
14件だった。production Site Adapterは変更していない。

### Source / renderer hardening

- draw時`sourceId`とsource URL、およびstable後のsource artifactの`sourceId`とURLを
  照合するようにした。同じ`sourceId`でもURLが違う場合は
  `source_changed_after_draw`としてreconstruction対象から除外する。stable後にblob
  source snapshotが得られない場合は`draw_source_snapshot_unavailable`として記録する。
- canvas hookは`drawImage`に加えて`clearRect`、`fillRect`、`putImageData`と、
  `save`、`restore`、`translate`、`scale`、`rotate`、`transform`、`setTransform`を
  軽量metadataだけ記録する。draw/mutationはcanvas IDを使う共有sequenceで保存し、
  encode、hash、network、large pixel copyはhook内で行わない。
- 今回のactive canvasではcontent-affecting mutationは`not observed`だった。mutationが
  観測されたcanvasは`unsupported_canvas_mutation`としてlossless判定しない。
- locator screenshotはvisual referenceに限定し、`visual_close`だけではconfirmedに
  しない。canvasのdraw mapping、source対応、DCT係数、decoded pixel比較を分離して記録する。

### JPEG structure and MCU alignment

- 保存されたtransport JPEGは代表的に`764x1200`、sampling factor`[[1,1]]`、MCU
  `8x8`だった。tileは実測の`184x296`を使用し、`16 tile = 4x4`とは仮定せず、
  source/destinationの実rectをcoverage検証した。
- active draw canvasではfull-frame draw後のpartial tile mappingについて、source coverage
  は`[0,0,736,1184]`、destination coverageも同じ、source/destination areaも一致し、
  gap/overlapなし、MCU alignment成立だった。764x1200全体の右28px・下16pxはbase drawで
  残るedge領域として扱い、tile領域を勝手に全体へ拡張していない。
- MCU alignment判定はJPEGごとに`feasible`、`infeasible`、`unknown`と理由を出力する。
  transform、composite、filter、alpha、scaling、coverage不整合もfail-closedで扱う。

### JPEG-domain DCT reconstruction

`poc/jumpplus_reconstruct.py`はPoC側で`jpeglib`と`numpy`を使い、JPEGをdecodeして
再encodeせず、quantized DCT block arrayをsource rectからdestination rectへコピーする。
full-frame drawはtransport JPEGの初期係数を残し、その後の実測tile drawをsequence順に
適用する。output JPEGについて次を検証する。

- output dimensions、sampling factor、quantization tableの一致
- expected/output DCT coefficient arrayの一致
- APPn/COM等のmetadata preservation状況
- lossless JPEG decode pixelと従来のPillow crop/paste PNGの比較

今回の実測結果:

| 項目 | 結果 |
| --- | --- |
| active draw canvas | 14件 |
| source URL一致 | 10件は候補JPEGへ対応、4件はnetwork候補未取得で`unmatched` |
| JPEG DCT feasibility | 10件 `feasible`、未対応4件は`unknown` |
| DCT reconstruction | 10件 `successful` |
| DCT coefficient一致 | 成功10件すべてtrue |
| decoded JPEG pixel == PNG reconstruction pixel | 成功10件すべてexact |
| metadata | 成功10件でAPP marker保持true、COMは今回0件 |
| drawImage以外のcontent mutation | `not observed` |

成功したcanvasでは、`*_reconstructed_lossless.jpg`、係数hash、sampling/MCU、coverage、
`decoded_pixel_comparison`を`output/jumpplus_probe/j2/state_*/canvas_*_mapping.json`へ保存した。
`summary.md`と`reconstruction_report.json`にもstate/canvas単位の判定を保存する。

### 判定とcapture recommendation

成功10件は`lossless_mapping_complete`であり、これはruntime mappingからJPEG-domain
再構成が成立したというPoC判定である。raw canvas pixel exportは依然taintedで、全canvasの
raw pixel equalityを証明したものではない。4件のsource未対応と30件のdraw未観測
staging/prefetch候補を含む全体判定は`inconclusive`とする。

現時点の第一候補は、固定static permutationではなく:

```text
transport JPEG
→ そのstate/canvasで観測したruntime draw mapping
→ DCT coefficient tile reorder
→ reconstructed JPEG
```

である。DCT alignment、coverage、source対応、係数検証が満たせないページは、既存の
decoded pixel crop/paste→PNGをfallback候補とする。production captureへの組み込み、
固定mappingの採用、Site Adapter実装はまだ行わない。

### Remaining unknowns

- 今回network保存範囲外だった4 active canvasのtransport JPEG対応は`unproven`。
- raw canvasがtaintedなため、再構成JPEGとbrowser canvasの全pixel equalityは未確認。
- 別episode、異なるviewer条件、色付き/subsampled JPEGでのDCT pathは`unknown`。
- mappingが今回の4 stateを越えて固定であることは確認していない。productionではruntime
  observed mappingを使用する前提を維持する。

## J2.1 candidate ambiguity hardening (2026-09-23)

J2のnetwork candidate選択で、decoded pixel SHA一致候補を無条件に先頭選択していた
処理を修正した。`select_transport_candidate()`へ分離し、次のstatusを導入した。

- `unique`: pixel SHA一致候補が1件。JPEG-domain pathで利用可能。
- `equivalent_multiple`: raw SHAが同一、またはdimensions、sampling、quantization table、
  DCT coefficientが同一。代表JPEGはJPEG-domain pathで利用可能だが、metadata差分は記録する。
- `ambiguous`: DCT image contentの差異、またはcandidate解析不能。pixel fallbackだけ許可し、
  JPEG DCT reconstructionは`not_attempted`とする。
- `unmatched`: pixel SHA一致候補なし。

`output/jumpplus_probe/j2/`を既存の対象episode artifactで再生成した。active canvas 14件の
うち、candidate対応が得られた10件はすべて`candidate_count=1`、`unique`、
`single_pixel_match`だった。複数candidateは実サイトartifactでは`not observed`で、
10件のJPEG-domain reconstructionは引き続き`successful`だった。未対応4件はnetwork
candidate不足のため`unmatched`で、全体判定は引き続き`inconclusive`である。

追加unit testでは、unique、raw duplicate、DCT equivalent（metadata差分含む）、DCT distinct、
parse failure、ambiguous時のpixel fallbackとDCT停止を確認した。production Site Adapterは
未実装であり、candidate ambiguityを含む別episode・別JPEG形式の確認後までproductionへは
進めない。

## Production Site Adapter (2026-09-24)

Production implementation files:

- \`src/screenshot_crawler/site_adapters/jumpplus/__init__.py\`
- \`src/screenshot_crawler/site_adapters/jumpplus/adapter.py\`
- \`src/screenshot_crawler/site_adapters/jumpplus/native_capture.py\`
- \`src/screenshot_crawler/site_adapters/jumpplus/access.py\`

The CLI registers \`jumpplus\` only for normal crawl. Discovery, site policy,
batch, watchlist, quota, ticket, point purchase, rental, and login automation
remain unimplemented.

The active viewer is \`section.viewer.js-viewer .image-container.js-viewer-content\`;
only visible \`canvas.page-image.js-page-image\` elements with at least 50 percent
viewport intersection are considered. Staging/prefetch canvases outside that
container are excluded. Live DOM page-area indices, canvas geometry, draw
metadata, and forward transitions confirmed the observed order: rightmost
active canvas first (\`x\` descending). This is based on live viewer behavior,
not on a Japanese-reading-direction assumption.

Only a unique, revalidated viewer page-forward control is clickable. Purchase,
point, rental, and another-episode navigation are rejected. A changed episode
URL is \`NEXT_CONTENT\`. END uses the episode JSON main-page count together with
the active DOM page index and captured active rows; the final page does not
click a next-episode control.

Capture priority is transport JPEG plus runtime drawImage mapping and DCT
coefficient reorder, then safe decoded-pixel replay to PNG, then all-page
locator screenshot. Raw CDN JPEG bytes are never emitted. The hook records only
lightweight IDs, URLs, dimensions, draw rectangles, transforms, compositing,
filter, alpha, sequence, and mutations. Source snapshots occur in capture
phase and are keyed by sourceId plus draw-time blob URL. Candidate selection
uses decoded RGB SHA and the J2.1 \`unique\`, \`equivalent_multiple\`, \`ambiguous\`,
and \`unmatched\` states. A spread is all-native or all-fallback. Response body
retention is bounded to 128 candidates and released after capture.

DCT requires identity/source-over/alpha=1/no filter/no scaling, integer MCU
aligned geometry, valid coverage, a safe compatible candidate, unchanged source,
and no unsupported mutation. JPEG dimensions, sampling, quantization tables,
and reconstructed coefficients are validated. PNG replay has the same safe
mapping requirements and never JPEG-reencodes.

The final shared Crawler Chrome direct-access run completed with \`Saved 65
pages; stopped at end.\` The archive contained page-0001 through page-0065,
all PNG screenshot pages, and no JPEG pages. A complete manifest verification
showed contiguous sequence and no duplicate fingerprints. A two-page production
smoke run exercised \`jpeg_dct\` twice with \`unique\` candidate selection; the
full run fell back to screenshots because transport/blob correspondence was not
proven for every active page. The target title was observed as \`左ききのエレン\`;
no point/ticket UI was clicked and the episode URL did not change.

\`page_number\` remains unset because the viewer DOM index is not treated as an
external page number. Other episodes, alternate JPEG sampling, and access-gated
episodes remain unverified.

## Production hardening: source cache and initialize race (2026-09-24)

The capture lifecycle now retains bounded prefetch JPEG responses across page
turns. `capture_page()` tracks the transport URL actually selected for the
current native attempt and releases only those URLs after capture. A screenshot
fallback with no selected candidate releases nothing, so future-page responses
remain available. `_discard_source(url)` is the source-level cleanup primitive;
`_discard_sources()` remains reserved for run/page setup cleanup. The bound
remains 128 responses.

Initialization no longer treats an empty initial rows result as permission to
advance. It first performs a bounded readiness wait. Startup forward is allowed
only for the observed pre-content state: viewer visible, visible page-area index
before `first_content_page_index`, one visible forward control, one visible
unique hidden/disabled backward control, and unchanged episode URL. The startup
forward is bounded to one action. If content is already present, bounded rewind
is attempted first; initialization fails closed if the first content page cannot
be guaranteed.

Unit coverage now includes used-source release with future cache retention,
screenshot fallback retention, content-before-start race, explicit startup
state, unknown-state fail-closed behavior, and first-page initialization.

The hardening live crawl completed with `Saved 65 pages; stopped at end.` The
archive contained 65 page files: 61 JPEG files and 4 PNG files. The PNG pages
were screenshot fallback; no PNG reconstruction was selected. The retained
manifest inspection run observed 60 `jpeg_dct` / `unique,unique` pages and 4
`screenshot` / `unmatched` pages; the successful archive had one additional
JPEG due to normal viewer timing variation. The fallback reason observed was
`unmatched_transport_candidate`; no duplicate fingerprint or missing archive
sequence was observed. The previous all-screenshot full run therefore improved
to majority native JPEG capture after cache retention. The startup race run
initially exposed that Jump+'s disabled backward control is hidden rather than
visible; the final live run recognized that explicit start state and completed
without skipping the first content page.

Discovery, Site Policy, and Batch remain out of scope.

## Discovery J0 observation (2026-09-24)

This section records an observation-only run. It does not implement or register
`JumpPlusDiscoveryAdapter`; `_discovery_registry()` and production site policy
were not changed.

### Observed scope and identity

The listing is scoped from the work-information section
`section.series-information.type-episode`, through the React episode tab
(`role=tab`, `data-key=episode`, `aria-controls`), into its `role=tabpanel`.
The episode list is the child `ul.index-module--series-episode-list--lqZcz`.
Rows are its `li` children; the current episode row has the additional
`index-module--current-readable-product--HKk5y` class and has no episode anchor,
so the target URL is used only for that current-row identity.

The sample work is `左ききのエレン`, author `かっぴー/nifuni`. The stable work
identifier observed in the HTML `data-gtm-data-layer`, the pagination request's
`aggregate_id`, and Atom URLs is `series_id=13932016480029111788`. The target
episode is `episode_id=13932016480029111789`. Episode anchors use the same
`shonenjumpplus.com` host, `/episode/<numeric-id>` paths, and no query string in
this sample. `external_id=episode_id` and canonical episode URLs are therefore
reasonable production candidates, subject to another-work check in the adapter.

### Ranges, expansion, and ordering

The measured range controls were, in DOM order:

| DOM index | label | episodes before/after expansion | `もっと見る` progress clicks |
| ---: | --- | ---: | ---: |
| 0 | `286 - 187` | 100 -> 100 | 0 |
| 1 | `186 - 87` | 100 -> 100 | 0 |
| 2 | `86 - 1` | 10 -> 86 | 1 |

The target page initially selected `86 - 1`, confirming that the initially
selected range is not necessarily the latest range. Switching a range keeps
the page URL and current episode unchanged. The same episode tabpanel/list DOM
is reused and its rows are replaced/expanded; it was not a navigation to an
episode page. The measured requests include
`/api/viewer/pagination_readable_products?type=episode&aggregate_id=13932016480029111788`
with `offset=0`, `100`, and `200`, `limit=100`, `sort_order=desc`, and
`is_guest=1`. The probe records these as network candidates only and does not
use the endpoint as production code.

The range labels are numeric and parse as `(start, end)` for this sample, but
the values and count are not fixed. Range 0 is the latest range because its
upper bound is greatest; it is also the first DOM control. Each range's row
order is newest-to-oldest: `286 - 187` begins with episode 220 and ends with
episode 202, `186 - 87` begins with 152 and ends with 78, and `86 - 1` begins
with 77 and ends with 1. Date text is `YYYY/MM/DD`. Numeric `order_key` parsing
works for these rows, but special/extra episode labels remain a reason to keep
`order_key` nullable unless separately recognized.

Across all three ranges the probe observed 286 unique episode IDs, 286 row
observations, and zero range-overlap duplicates. A full traversal should still
deduplicate by episode ID and fail closed if a range cannot be visited or a
bounded expansion does not make identity progress.

### Row fields and access states

The row probe records href, episode ID, anchor count, visible text, row classes,
`data-*` attributes, order text, title/date text, access classes/text/icons,
and nested anchors. Published date is taken from the row's visible date text;
the observed format is date-only `YYYY/MM/DD`, suitable for a JST calendar date
after an explicit production policy decision.

Two distinct access displays were observed:

1. Free: class `index-module--series-episode-list-is-free--sMYEt`, visible
   label `無料`.
2. Rental/points: price class
   `index-module--series-episode-list-price--aeph4`, rental-point class
   `index-module--rental-point--kt0LK`, rental-term class
   `index-module--rental-term--BRXkp`, title `40ポイント レンタル・48時間`,
   and visible labels `40pt` / `レンタル・48時間`.

No `レンタル中`, quota/ticket grant, or free-until label was observed. The
row therefore supplies no `free_until`; the visible date must not be reused as
a free-until value. The Atom candidate contains a free-term-start field, but
that is not the same as a row free-until field.

The next-phase mapping proposal is `無料` -> `free`, explicit point/rental or
purchase-required state -> `paid`, and any unrecognized or ambiguous state ->
`unknown`. No mapping function is implemented in J0. A state such as
`レンタル中` must remain a separate observed state until live access behavior
is verified; it must not be inferred as free or quota-granted.

### Embedded data and authority candidates

The HTML root carries a `data-gtm-data-layer` JSON object containing the sample
series ID, episode ID, readable-product ID, title, and `can_read`. No complete
episode listing was found in `script[type=application/json]` in this run. The
page also exposes the pagination-information and pagination-readable-products
network responses, and an Atom series feed candidate. These are useful
structured-data candidates, but the API/Atom formats are internal or access
semantics may be incomplete. For the next phase, DOM listing data remains the
authority candidate for the observed access/published/title fields, with the
network response evaluated as a possible optimization only after schema and
stability checks. No direct API call was added to production.

### Proposed production traversal

Full discovery should identify the episode tabpanel, enumerate every range
control without hardcoding labels/counts, visit each range, and fully expand
that range. A `もっと見る` click counts as progress only when the set of
episode IDs grows; a bounded no-progress or navigation change is incomplete.
After all ranges are visited and stable, deduplicate by `episode_id` and
validate the completeness signals (all controls visited, every expansion
stable, and observed count/range boundaries consistent). Otherwise raise a
fail-closed `DiscoveryIncompleteError`-style result.

Incremental discovery must order ranges by parsed range metadata (latest upper
bound first in this sample), not by the initial selected tab. Within each range
it should read the observed newest-to-oldest DOM order, then use the generic
known-streak stop only after yielding in that global latest-first order. The
sample target being episode 1 demonstrates why selected-tab order is unsafe.

### J0 artifacts and unresolved points

The observation PoC is `poc/jumpplus_discovery_probe.py`. Its output is under
`output/jumpplus_discovery_probe/`, including `report.json`, initial HTML/
listing/control/script/network artifacts, per-range before/expanded/network
artifacts, and screenshots. Safe clicks were limited to revalidated range
controls and the episode-list `もっと見る`; episode links, viewer controls,
purchase/rental/point/login controls, and comments controls were not clicked.

Open questions before production implementation are: whether all works use the
same React tab/list shape; whether nonnumeric/special episode labels require a
stable order policy; whether logged-in, expired, or `レンタル中` displays add
access states; whether the network/Atom schemas remain stable; and whether a
fresh tab's lazy listing mount needs a bounded readiness/fallback strategy.

## Discovery J0 multi-sample verification (2026-09-24)

The observation-only probe was extended and run against four samples using the
same schema. Production `JumpPlusDiscoveryAdapter`, `_discovery_registry()`,
Jump+ Site Policy, Batch, Catalog schema, and the normal Site Adapter remain
unchanged.

### Sample matrix

| sample | series_id | DOM variant | ranges | unique episodes | duplicates |
| --- | --- | --- | ---: | ---: | ---: |
| baseline `13932016480029111789` | `13932016480029111788` | React `role=tabpanel` | 3 | 286 | 0 |
| manual-rental-containing `9253191254047172892` | `9253191254046896629` | direct pagination | 1 | 13 | 0 |
| normal `9253191256637716556` | `9253191256479706037` | direct pagination | 1 | 2 | 0 |
| ultra-long `10833519556325021794` | `10833497643049551729` | React `role=tabpanel` | 12 | 1180 | 0 |

All four use the same work section and `ul.series-episode-list` row
relationship. The difference is that baseline/ultra-long expose the episode
list inside a React episode tab and `role=tabpanel`, while the manual-rental
and normal samples render a direct `.js-readable-products-pagination` with
`#pagination-top`; those direct samples have no episode `role=tab`. The
production scope must support both variants and must not require the React tab
as the only entry point. CSS-module hash suffixes remain diagnostic only.

### Range and more-control behavior

Baseline:

| label | initial -> final | progress clicks |
| --- | ---: | ---: |
| `286 - 187` | 100 -> 100 | 0 |
| `186 - 87` | 100 -> 100 | 0 |
| `86 - 1` | 10 -> 86 | 1 |

The initially selected range is `86 - 1`; it is not latest. Ultra-long has
labels `1180 - 1081`, `1080 - 981`, `980 - 881`, `880 - 781`, `780 - 681`,
`680 - 581`, `580 - 481`, `480 - 381`, `380 - 281`, `280 - 181`, `180 - 81`,
and `80 - 1`. The first eleven contain 100 rows each without more clicks; the
last contains 10 initially and expands to 80 with one progress click. Its
initial selected range is `80 - 1`, again not latest.

The manual-rental-containing series has one direct range (`1話から`) and 10
initial rows, then 13 after one `もっと見る` progress click. The normal
sample has one direct range, two rows, and no more control. A direct single
range control is recorded but is not clicked as a range switch.

The probe now treats more controls fail-closed: zero visible enabled controls
is `no_more` and complete; exactly one is clickable; more than one is
`ambiguous_more_control` and incomplete; a visible disabled control is recorded
as `disabled_more_control` and incomplete. A click is progress only when the
episode identity set grows. Range switches wait for rows to mount before the
range expansion measurement, avoiding a false initial count of zero.

When no selected range marker is present, selected range remains unknown. The
probe does not select the first range heuristically.

Observed pagination request offsets are baseline `0,100,200`, ultra-long
`0,100,...,1100`, and `0` for both direct samples. The request carries the
series `aggregate_id`; the pagination-information response supplies the total
count and per-page size. These remain observed network candidates, not
production API calls.

### Ordering and special labels

All four samples are newest-first within the observed row order. Numeric range
labels are newest-to-oldest by descending upper bound. The ultra-long labels
are therefore traversed from `1180 - 1081` down to `80 - 1`; the direct samples
have no multi-range label. This supports global latest-first incremental
ordering when ranges are sorted by parsed metadata, not by selected state.

Special/non-numeric labels were observed and are not safe numeric order keys:
the manual-rental series contains `イラスト3`, `イラスト2`, and `イラスト`; the
ultra-long series contains `特別収録作品1 麦わら劇場 海の音楽会`. These retain
the visible title as `order_label` and use `order_key=None`. The previous probe
fallback that could read the publication year as an order number was corrected;
numeric parsing is attempted only after the date or from the visible title.

### Manual rental observation

The target URL `9253191254047172892` itself is not rented. Full series
discovery found a different row:

- episode ID: `9253191254350319886`
- href: `/episode/9253191254350319886`
- visible label: `第3話`
- published date: `2026/06/14`
- DOM access class: `index-module--series-episode-list-rental--SWA_e`
- DOM label: `レンタル中 2026/09/26 11:41まで`
- structured `purchase_info.can_read`: `true`
- structured `purchase_info.has_rented_via_point`: `true`
- structured `status.label`: `has_rented`
- structured `status.rental_end_at`: `2026-09-26T02:41:39Z` (JST 11:41:39)

For comparison, a normal paid row in the same series (`9253191254640655914`,
第4話) has `can_read=false`, `has_rented_via_point=false`,
`status.label=is_rentable`, `rental_end_at=null`, and the normal `40ポイント
レンタル・48時間` DOM display. A free row has `can_read=true`,
`purchase_info.is_free=true`, and `status.label=is_free`.

This is sufficient to distinguish normal paid from an active manual rental
without hardcoding episode 3 or any episode number. The authority order for
this distinction prefers structured `purchase_info`/`status` plus matching row
evidence, but production also accepts an explicit DOM `レンタル中` state without
structured evidence. A displayed expiry is parsed when available; without an
expiry the source remains `paid` with no grant timestamp.

### Access and expiry specification decision

The observed states are:

- free: DOM `series-episode-list-is-free`, structured `is_free=true`;
- normal paid/rentable: price/rental DOM classes, `can_read=false`,
  `status.label=is_rentable`, no active rental end;
- active manual rental: `series-episode-list-rental`, `can_read=true`,
  `has_rented_via_point` or `has_rented_via_ticket`, `status.label=has_rented`,
  and exact `rental_end_at`;
- paid with a future scheduled free-publication label: the paid row may also
  carry `episode-read-date` such as `2026年09月29日に無料公開予定`. This is a
  scheduled release signal, not `free_until` and not current free access;
- unknown: conflicting, missing, or unrecognized signals.

The production representation should be:

```text
free -> access_mode=free, access_granted_until=None
normal paid -> access_mode=paid, access_granted_until=None
active manual rental -> access_mode=paid,
                         access_granted_until=<exact rental_end_at>
unknown -> access_mode=unknown
```

Manual rental must not be mapped to `quota`, and the 48-hour product term must
not be converted into an expiry by adding 48 hours to observation time. The
existing Catalog `access_granted_until` field is sufficient; no schema change
is required. If an active-rental signal is present but no exact expiry is
available, keep the source as paid/unknown for direct-access policy purposes
and fail closed rather than inventing a grant timestamp.

Full discovery must enumerate the complete series before reconciliation. It
must not inspect only the target episode URL: the manually rented episode is a
different row in the same series. Discovery should update each row's current
access state and exact grant timestamp independently. Automatic rental,
automatic point/ticket consumption, grant polling, and incremental grant-only
refresh remain out of scope.

### Artifacts and production-readiness decision

The four reports and their before/expanded/network artifacts are under
`output/jumpplus_discovery_matrix/`; `comparison.json` is generated by
`poc/jumpplus_discovery_matrix.py`. The existing probe now also records
structured readable-product access states, manual-rental candidates, direct
pagination scope, disabled/ambiguous more-control outcomes, and unknown
selected-range state.

The information is sufficient to implement a production Discovery design for
DOM-based full/incremental enumeration and source-level access reconciliation.
Before registering production code, a further live check was still advisable
for an expired rental and an active rental with no exact expiry. Those states
remain unresolved live cases, but the production adapter now fails closed on
conflicts and does not invent a grant timestamp.

## Production Discovery (2026-09-24)

`JumpPlusDiscoveryAdapter` is registered under `jumpplus`; Jump+ Site Policy
and Batch policy remain intentionally unregistered. The existing J0 probe and
matrix remain observation-only and are not imported by production code.

### Scope and traversal

The adapter requires an allowed `/episode/<numeric-id>` target and canonicalizes
all discovered row links to `https://shonenjumpplus.com/episode/<id>`, using the
episode id as `external_id`. It validates the unique `series_id` found in the
page data (`data-giga_series` / `data-gtm-data-layer`) and cross-checks any
scoped `pagination_readable_products` `aggregate_id` observed by the bounded
response listener. A missing or conflicting series identity is incomplete.

Both observed listing variants are supported:

- React `[role=tab][data-key=episode]` -> its `aria-controls` tabpanel;
- direct `.js-readable-products-pagination` -> `#pagination-top`.

The semantic `ul` carrying `series-episode-list` is the row scope. React's
episode tab is activated only when its panel is still empty; the initial mount
retry is bounded to three page-load attempts. No episode/access/purchase
control is clicked.

For numeric range controls, the adapter re-reads and revalidates controls
before every click, rejects episode links or forbidden access controls, keeps
DOM order as the traversal order, and requires descending numeric upper bounds.
It does not hardcode range count or labels. A direct one-range display such as
`1話から` is not clicked as a range switch. Each range is fully expanded with a
maximum of 20 `もっと見る` clicks; progress requires a growth in episode-id
identity. Zero enabled controls is complete, while multiple or disabled visible
controls, no-progress clicks, target navigation, and range-count mismatches are
fail-closed.

`full` collects and validates every range before yielding any record. It
deduplicates by episode id and rejects conflicting duplicate metadata. Numeric
range boundaries and any bounded pagination total are used as completeness
checks. `incremental` traverses the newest numeric range first, then each older
range, and yields each range's DOM order (observed newest-to-oldest); the
generic known-streak stop can therefore operate on a global latest-first
stream. The initial selected range is never used as a latestness signal.

### Record and access mapping

The visible title is preserved as `order_label`. `order_key` is populated only
for an unambiguous leading numeric `N話` label; `イラスト*`, special-collection
labels, and date text remain non-numeric. `YYYY/MM/DD` row dates become JST
calendar-day timestamps. `free_until` remains `None`; scheduled labels such as
`無料公開予定` are not current free access.

Access mapping is:

- current free badge/structured `is_free` -> `free` with no grant;
- point/rental-required or `is_rentable` -> `paid` with no grant;
- active manual rental -> `paid` with `access_granted_until` from structured
  `rental_end_at` when present, otherwise the displayed JST minute expiry;
- unrecognized or conflicting evidence -> `unknown` with no grant.

Structured active-rental evidence is preferred, but is not required. An
explicit DOM `レンタル中` state is sufficient to mark `paid` even when the
structured response is unavailable. No 48-hour product duration is added to
the observation time. A structured/DOM conflict is `unknown`. Every Jump+ row
whose access state was observed sets `access_checked_at` and
`access_granted_until_observed=True`.

The manual-rental live validation found episode
`9253191254350319886` in the 13-row series, not the target episode itself. Its
Catalog state was `paid` with
`2026-09-26T11:41:39+09:00`; normal paid rows remained `paid` with no grant.
Manual rental is never mapped to `quota`, and no automatic rental, ticket, or
point behavior is included.

### Catalog grant reconciliation

`DiscoveredSource.access_granted_until_observed` is a site-neutral tri-state
observation flag. `False` preserves an existing Catalog grant when the incoming
timestamp is `None`; `True` writes either the timestamp or SQL `NULL`. The
Discovery Service forwards the flag to `CatalogService.refresh_discovered_source`.
Existing BookWalker, Manga ONE, and Magapoke records retain their prior
behavior because they leave the flag at its default `False`; non-null incoming
grants still update as before. This uses the existing Catalog schema and does
not add quota semantics.

### Live validation and remaining issues

The isolated full-discovery run succeeded with 286, 13, 2, and 1180 unique
episodes for the baseline, manual-rental-containing, normal, and ultra-long
samples respectively; no duplicate episode ids were observed. An incremental
ultra-long run yielded the newest five rows and stopped at the generic
`known_streak` boundary. The unrented paid direct-crawl smoke test failed
closed during initial viewer readiness with zero saved pages and no manifest;
it did not perform purchase, point, or rental controls and did not package the
target as manga content.

Remaining P2 observations are an expired-rental live sample and a DOM-only
active rental with no expiry. They do not block this Discovery phase because
both map conservatively without inventing a grant.

## Site Policy + Batch integration (2026-09-24)

`JumpPlusSitePolicy` is registered for `site="jumpplus"`. It is deliberately
read-only with respect to Jump+ access acquisition: it never selects a point,
rental, ticket, or quota operation.

The decision table is:

| Catalog state | Batch decision |
| --- | --- |
| `available=False` | skip, `unavailable` |
| `free` | `direct`, `free` |
| `paid` + `access_granted_until > now` | `direct`, `active_rental` |
| `paid` + no grant | skip, `paid` |
| `paid` + grant at or before `now` | skip, `expired_rental` |
| `unknown` | skip, `unknown` |
| `quota` | skip, `quota_not_supported` |
| `owned` | skip, `owned_not_verified` |

The grant boundary is strict: `access_granted_until == now` is expired. Both
the stored grant and `now` must be timezone-aware; ISO strings are parsed with
`datetime.fromisoformat()` and normalized to JST. Invalid or naive timestamps
raise `SitePolicyError` rather than being guessed.

The policy uses the existing site-neutral Batch Planner and Executor. Free
episodes and manually rented episodes become ordinary `direct` candidates;
normal paid episodes are skipped. `supported_access_resources()`,
`ordered_access_resource_passes()`, `additional_quota_resources()`, and
`grant_only_supported_access_resources()` remain empty through the base policy
contract. No Catalog schema, Discovery adapter, Capture adapter, Core Runner,
or other-site policy was changed for this phase.

Operational flow for manual rental is:

```text
human rents episode on Jump+
  -> discover --mode full
  -> Catalog paid + observed access_granted_until
  -> batch plan --site jumpplus
  -> direct candidate
  -> batch run --site jumpplus
```

Full discovery is the authority for refreshing current Jump+ access state. A
stale or expired grant is therefore not eligible even if Catalog has not yet
been refreshed. Planning is read-only, and Batch execution revalidates the
candidate against current Catalog state before starting a crawl; an expiry
between planning and execution is rejected as a stale candidate. Automatic
rental, point/ticket consumption, quota, grant-only, and grant polling remain
out of scope.

The isolated live validation used the manual-rental-containing series and a
separate Catalog. Full discovery completed with 13 unique episodes. The live
policy plan produced 8 direct candidates (7 free rows and 1 active manual
rental) and skipped 5 normal paid rows. The active rental was episode
`9253191254350319886`; its Catalog grant was still future at observation time.

Two isolated `batch run --limit 1` attempts were made: one free candidate and
the active manual-rental candidate. Both reached the Jump+ Capture adapter and
saved viewer pages, but stopped at the existing `wait_for_change` terminal
timeout before a successful archive result was reported. The Batch layer did
not select a quota/resource pass and no purchase, point, or rental control was
available to the Jump+ policy. This is a Capture/site-adapter live-validation
blocker, not a Policy eligibility failure; no Capture or Site Adapter change
was included in this phase. The prior negative direct crawl smoke test remains
the safety baseline: an unrented paid episode failed closed without clicking
purchase, point, or rental controls and did not package the target as manga
content.

## Terminal timeout production fix (2026-09-24)

The terminal investigation was fixed in the production Jump+ adapter after
rebasing onto `706a7fb`. The adapter no longer has a global
`first_content_page_index = 2`. Each viewer instance now derives
`_first_content_page_index` from active content rows after a bounded rewind to
the first content state. The runtime boundary is reused by `_rows()`,
`detect_state()`, `go_next()`, and `wait_for_change()` through
`_content_end_index()` and `_all_main_content_captured()`.

The rewind is URL-safe and bounded. It revalidates the unique viewer backward
control, requires changed row identity (including page indexes) when moving
backward, and treats a stable no-op backward transition as a viewer boundary.
If the viewer exposes a pre-content area, the previous content rows are
restored through the validated viewer-forward control before the first index is
committed. A layout with no preceding page areas can therefore establish index
0 without clicking backward and without skipping the first page. The initial
state classifier also no longer compares visible DOM indexes with a fixed
threshold.

The terminal contract is now shared by forward and wait logic:

```text
content_page_count is known
first content index is known
captured_content_page_count >= content_page_count
last_active_max_page_index >= first + content_count - 1
```

Both count and index are required; neither signal alone can produce `END`.
After this contract is true, `go_next()` marks terminal without clicking into
back-matter. If a forward transition has already been issued, an empty/stable
row or disabled-forward fallback is accepted only with the same complete
contract. The disabled-forward state remains auxiliary, not authoritative.

The adapter also waits, with a 5-second bound, for Jump+'s transient
`.js-slide-to-transit-guide` to stop intercepting the validated viewer-forward
control. This remains a viewer transition wait, not a click on the guide or on
any purchase/rental/point/ticket/next-episode control.

### Tests and live validation

Unit coverage includes front-link index 2, no-front-link index 0, the manual
index-0 shape, spread end indexes, index-0 initialization without startup
forward, bounded middle rewind, pre-content restoration, complete/incomplete
count and index terminal cases, and the `wait_for_change()` incomplete-capture
regression. The adapter test file has 25 passing tests.

Isolated shared-CDP live runs produced:

| case | expected main pages | saved pages | result |
| --- | ---: | ---: | --- |
| normal long run 1 | 65 | 65 | END + archive |
| normal long run 2 retry | 65 | 65 | END + archive |
| free `9253191256637716604` | 23 | 23 | END + archive |
| active manual rental `9253191254350319886` | 27 | 27 | END + archive |

The first normal run 2 attempt also saved 65 pages and reached END, but its
archive path collided with run 1 because the same library directory was used;
it was rerun with an isolated library and archived successfully. The initial
free attempt exposed the index-0/backward-control variant and the initial
manual-rental attempt exposed the transient transit-guide race; both succeeded
after the runtime boundary and bounded forward-wait fixes. The successful
archives contained exactly 65, 65, 23, and 27 image entries respectively, with
no duplicate or missing page observed.

The isolated production path was also checked as:

```text
discover --mode full -> 13 records
batch plan -> 8 direct candidates (7 free + 1 active manual rental), 5 paid skipped
batch run -> free candidate archive succeeded
batch run -> active manual-rental candidate archive succeeded
```

The manual-candidate Batch run used a cloned isolated Catalog with unrelated
earlier free candidates marked completed solely to select the manual candidate;
the production `BatchExecutor`, Jump+ Policy, adapter, Catalog finalization,
and archive packaging were otherwise used normally. The manual rental remained
active at observation time and was not reacquired. No purchase, points, rental,
ticket, or next-episode control was clicked.

## Special illustration transit-guide investigation and fix (2026-09-24)

Phase A used an isolated full Discovery Catalog for
`https://shonenjumpplus.com/episode/9253191254047172892`. The special rows
were selected dynamically by `order_label`; no episode ID was hardcoded in the
probe. The current accessible sample was:

| label | episode ID | access | main pages |
| --- | --- | --- | ---: |
| `イラスト` | `9253191255124422366` | free | 2 |
| `イラスト2` | `9253191255561726242` | free | 2 |
| `イラスト3` | `9253191256195090294` | free | 2 |

No current one-main-page illustration row was present in this series. Each
special episode had two `type=main` entries followed by a `link`, two
`other` entries, and `backMatter` in `#episode-json`. The DOM contained an
empty leading page area at index 0, then main canvases at areas 1 and 2. The
initial active row was area 1; area 2 was already in the DOM but outside the
viewport.

The Phase-A probe (`poc/jumpplus_transit_guide_probe.py`) recorded the guide,
controls, `elementsFromPoint()` stack, active rows, page areas, page structure,
adapter counters, and persistence key names. Before adapter initialization the
guide was hidden. Initialization treated page index 1 as having a preceding
area, clicked the backward viewer control while the leading area was empty,
and left the row unchanged. That no-op transition caused
`.js-slide-to-transit-guide` to become a full-viewer overlay. The failing
`_click_forward()` call then came from the normal `go_next` path, not from
startup forward, rewind restore, or `wait_for_change`.

At offsets 0, 100, 300, 500, 1, 2, 3, 5, 8, 10, and 15 seconds after that
forward call, the guide remained `display:flex`, visible, with
`pointer-events:auto` and a full viewer-sized rectangle. The forward center's
top `elementsFromPoint()` result was the guide; both viewer controls were
covered. It did not naturally disappear, change to `pointer-events:none`, or
move. The adapter had `content_page_count=2`, captured one page, and
`last_active_max_page_index=1`, so this was not an early terminal decision.
This is Case D: the rewind boundary classifier treated an empty leading area
as traversable content, with Case F's persistent transit-guide interception as
the resulting symptom.

The production fix is deliberately small: `_has_preceding_page_areas()` now
considers a preceding area a rewind target only when it contains a rendered
page canvas or an explicit link. An empty leading area therefore establishes
the first content index without backward navigation. The normal forward click
then occurs while the guide is hidden. No force click, JavaScript click, guide
click, DOM removal, style mutation, pointer-events mutation, or Batch behavior
change was made.

Post-fix probe and isolated direct crawls produced 2/2 pages and END for all
three special rows, with exactly two archive images and no duplicate/missing
image observed. The normal 23-page free episode, manual-rental 27-page
episode, and normal-long 65-page episode also completed with exact archive
counts. The isolated eight-candidate Batch plan completed the three special
rows and the following candidates (including the active rental); it finally
stopped at the last candidate, item 13, on a separate existing
`wait_for_change` timeout. Generic Batch stop-on-error semantics were left
unchanged, and the special rows no longer stop the queue.

Artifacts:

```text
output/jumpplus_special_guide_phase_a/
output/jumpplus_special_guide_phase_b/
```

Discovery, Site Policy, Batch semantics, Catalog schema, Core Runner, and
native reconstruction logic were not changed by this fix.

## Initial content page resolution fix (2026-09-24)

The item-13 investigation found a separate startup race from the transit-guide
case. The episode has 80 `type=main` pages. In the failing run, the first
capture began at the second active spread and 79 pages were saved; the last
page was present. Because the capture count was still 79, the normal terminal
condition could not complete and `wait_for_change` timed out.

Jump+ can contain an empty leading page-area before the first main page, while
the first main page may exist in the DOM before its canvas is rendered. The
adapter therefore distinguishes these states during rewind:

- a preceding rendered canvas or `kirinuki`/generator content link is a real
  preceding content page and must be rewound through;
- an explicitly empty leading area is not a rewind target, preserving the
  transit-guide protection for short illustration episodes;
- an ambiguous preceding page-area is not accepted as the first content page
  when the backward control is unavailable. The adapter waits boundedly for
  the viewer to settle and fails closed if the boundary remains unknown.

This avoids silently setting `first_content_page_index` to the first row that
happens to be visible during initial rendering. The index remains runtime
derived; no episode-specific or fixed index is used.

Unit coverage includes index-zero layouts, normal front-link layouts, empty
leading illustration layouts, ambiguous preceding areas, and the existing
rewind/restore behavior. Live validation after the change produced 80/80
pages and END for item 13 (`9253191254047172892`). A representative two-page
special illustration (`9253191255124422366`) also produced 2/2 pages and END;
no transit-guide regression was observed.

## Terminal timeout investigation (historical, before production fix)

The investigation used `poc/jumpplus_terminal_probe.py` against the shared
Crawler Chrome/CDP session. It only clicked the existing viewer forward
control; it did not click purchase, point, rental, ticket, login, or episode
navigation controls. Raw artifacts are written under
`output/jumpplus_terminal_probe/` and are intentionally not production input.

The comparison was:

| case | episode | main pages | saved unique pages | last active page index | result |
| --- | --- | ---: | ---: | ---: | --- |
| normal long | `13932016480029111789` | 65 | 65 in the successful baseline run (64 in a repeat race) | 66 | END |
| free timeout | `9253191256637716604` | 23 | 23 | 22 | `wait_for_change` timeout |
| manual-rental timeout | `9253191254350319886` | 27 | 27 | 26 | `wait_for_change` timeout |

The raw `#episode-json` page structures explain the difference. The normal
episode has a front link before its 65 main pages, so its active DOM rows start
at page indexes 2 and finish at 66. The free and manual-rental episodes have
no front-link area: their main pages start at DOM index 0 and finish at 22 and
26 respectively. Their trailing page structures are `link(back)`, two
`other` pages, and `backMatter`; the corresponding final DOM areas are visible
in style but are not active content rows.

The production adapter's global `first_content_page_index = 2` therefore
calculates terminal indexes 24 and 28 for the two failing episodes. After the
last main page is captured, the final forward click leaves the URL unchanged,
the forward control remains visible and not disabled, and active rows become
empty/loading while the viewer transitions into back-matter state. Since the
observed max indexes are 22 and 26, the current terminal condition never
becomes true and `wait_for_change` times out. At timeout, all expected main
pages were already captured, with no duplicate capture and no missing main
page.

The concrete classification is primarily **Case 3: episode-specific
page-index mapping**, with **Case 1: all content was saved but the terminal
signal was missed** as the resulting symptom. There is also a secondary timing
hazard in the current normal-path terminal check: it can rely on the page-index
condition without requiring `captured_content_page_count >= content_page_count`,
which explains the 64-page repeat observed alongside the historical 65-page
successful run.

The production fix derived from this investigation is documented in the
`Terminal timeout production fix` section above. This historical section
records the pre-fix evidence and must not be read as the current adapter
behavior.

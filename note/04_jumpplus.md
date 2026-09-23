# Jump+ J0 probe 現行観測ノート

## Scope

Production Site Adapter is implemented for normal crawl only. Jump+ Discovery,
Site Policy, Batch, Watchlist, quota/resource management, and login automation
remain unimplemented.

少年ジャンプ＋（Jump+）のproduction Site Adapter / Discovery / Site
Policy / Batchは未実装。これはviewer構造を調査するためのread-only J0
probeの現行スナップショットである。ポイント、購入、レンタル、チケット、
ログイン状態変更、次episodeへの遷移は行わない。

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

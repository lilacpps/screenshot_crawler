# 01. BookWalker 現行実装ノート

このファイルはBookWalker Adapterの**現在の実装詳細と実サイト観測**をまとめる。BookWalker固有の実装・運用を変更した場合は、このnoteも同じ変更で更新する。

共通Runner / Browser Session / output / packagingの詳細は `note/00_core.md` を参照。

最終同期: 2026-10-08

## 1. 目的と現在のscope

BookWalkerの商品ページまたはviewer URLから、現在コンテンツの本文だけを読書順で保存する。
優先順位はoriginal JPEG、検証済みlossless reconstructed JPEG、source/native pixelsのPNG、
rendered-canvas PNG fallbackである。PNG出力だけでは配信sourceがPNGだったとは判定しない。

現在対応している主な挙動:

- 商品ページからreader候補を見つけてviewerへ移動
- Canvas本文取得
- 単ページ / 横長ページ / 見開き
- 見開きを右→左の読書順で個別artifact化
- loading待ちとbounded retry
- 最終本文を保存した後のBookWalker logo等を保存しない
- NEXT_CONTENTをcaptureせず停止
- 商品情報からtitle / volume / author / genreを生成
- END / NEXT_CONTENT正常終了時にZIP化
- CDP接続した通常Chrome上でlogin/crawl

実サイト確認では、対象trial readerで59/59まで本文を保存し、その後のlogo screenを保存せず正常終了した実績がある。

BookWalkerのseries-scoped Discovery、Site Policy、Batch実行は実装済みである。Batchからのstrict `direct` / `quota` entryも実装済みである。Adapterを直接生成
した場合のstrategy defaultは`auto`で、`configure_run()`は`auto` / `direct` / `quota`を受け付け、
run stateへ保存する。

## 1.1 Current source-native baseline (2026-10-05)

The current production priority remains unchanged:

```text
verified original JPEG
    -> verified lossless reconstructed JPEG
    -> verified source-native PNG
    -> rendered-canvas PNG fallback
```

The existing original-JPEG matcher uses a bounded deterministic 64x64 browser
signature for production selection. The Phase 1/2 diagnostics additionally used
bounded full-resolution comparisons; those stronger diagnostic results must not be
retroactively attributed to the ordinary matcher.

The representative manga baseline (`de038ee678-e389-4ceb-a13e-4f7f0154d79e`)
was observed with actual position `1/159`, verified anchor `1/159`, captures
through `23/159`, and restoration to `1/159`. The cover was an original JPEG at
844x1200, 306739 bytes, with candidate/output SHA-256
`0f1c65cd495b5bcc0cb6f7c44437706ff850d011ab3fca53b1cf608f330254b3`; its
selected ImageBitmap source was also checked by a full-resolution diagnostic.
Seven ordinary body spreads (`9/159` through `21/159`) returned native-PNG
fallback records with dimension/mapping rejection and no proven upstream exact
response attribution.

The representative light-novel baseline
(`dea0961d33-6ef8-4673-a455-0ec0ecd5de47`) used a verified `1/314` anchor,
captured actual positions through `15/314`, and restored to `1/314`. The cover
(`1/314`, 1443x2048) was original-JPEG A with a full-resolution exact comparison.
Positions `8/314`, `10/314`, `11/314`, `13/314`, and `15/314` used the existing
direct reconstructed-JPEG path at 960x1280 with strict completed mappings,
unique raw-JPEG/ImageBitmap matches, MCU alignment, and coefficient/DCT proof;
the adapter's coefficient gate includes quantization-table equality. Positions
`2/314` through `7/314` were leading illustrations/front matter and remained
PNG fallback D observations; no network-PNG claim was made.

The focused source diagnostic advanced and restored as `1/314 -> 2/314 ->
3/314 -> 1/314`. For `2/314`, bitmap 5 matched a JPEG at 1448x2048 by full
pixels, but the selected native draw was 1443x2048 while the retained source
canvas was 2048x1453, so visible-output attribution remains unusable and D.
For `3/314`, bitmap 8 at 2048x1456 had one exact JPEG candidate; crop/padding/
coded mapping and source-native output proof remain incomplete, so this remains
D and is only evidence for possible future B research. No confirmed B or C
case was observed. The PNG artifact is a correct fail-closed fallback candidate,
not proof of a network PNG.

Invalid earlier constructor-event/zero-or-None candidate probes are excluded
from source-format evidence. Mapping IDs and renderer operation identities are
window-local diagnostic facts; no global association is inferred from timing,
dimensions, path, order, or visual similarity. No second manga was used.

At the Stage 01 checkpoint, targeted capture unit tests (153 passed) and
BookWalker browser-backed integration tests (45 passed) passed. Ruff
(`.venv\\Scripts\\ruff.exe check src tests`) passed. No new fixture, production
implementation, or live-site rerun is included in this publishing synchronization.
Those test counts are the Stage 01 checkpoint, not fresh Stage 02 verification.
The earlier Stage 02 workflow did run an entry Critic gate; visible-output
attribution remained challenged. The workflow has since been simplified:
ordinary research is Lead + Worker only, Reviewer is change-driven, and Critic
is risk-driven. No production implementation has been approved from these
observations.

## 1.2 Stage 02 research status (2026-10-08, complete)

Stage 02 has completed its bounded live acceptance. Final production Reviewer
confirmed PASS with no remaining BLOCKING on code, tests, live evidence and
document synchronization. The current source-native priority is original JPEG,
verified lossless reconstructed JPEG, source/native PNG, then rendered fallback.
A small dimension difference alone is not a reason to require PNG.

| Case | Classification / current behavior |
| --- | --- |
| Manga `9/159`, `11/159` | B; each spread yields two 844x1200 JPEGs from 848x1200 coded JPEG sources |
| LN `3/314`, `4/314` | B; 2048x1456 coded source becomes 2048x1453 JPEG |
| LN `2/314` | D; stable native PNG fallback at 722x1024 with incomplete usable upstream mapping |
| LN text `8/314`, `10/314` | A; existing reconstructed JPEG path at 960x1280 remains correct |
| Current manga cover | D; adapter returns no native artifact; actual Core rendered-canvas PNG fallback at 1386x983 |
| Current LN cover | D; native PNG fallback at 722x1024 |

The historical cover A/original-JPEG observations in section 1.1 remain
historical controls; neither is claimed as a fresh original-JPEG success in
this run. Current fallback is not proof of a PNG source, so no C is established.
The original matcher and original-JPEG priority were not changed. Its existing
regression tests pass; current manga cover had zero match attempts/candidates.
Those unattempted matcher counters are not a raw-response inventory or proof
that no JPEG source exists; current cover provenance simply remains unproved.
A debug default `native_png` with zero returned captures is not PNG success:
the manga cover control actually invoked the existing Core canvas capture.

The unique exact upstream JPEG is the recovery input, but its tiles are
scrambled. Recorded source/destination rectangles, safe draw state and a full
coded MCU bijection establish reconstruction. Manga has 1,026 tiles per part;
LN3/4 have 2,944 tiles. The visible frame omits reconstructed manga columns
844–847 or LN rows 1453–1455. Their corresponding raw-source fragments are
scattered, so simply cropping or saving the raw JPEG is not the recovered page.
Reordering quantized DCT coefficients and setting visible frame dimensions
preserves all Y/Cb/Cr coefficients, quantization tables and table-selector IDs.
Every new cropped part also matches its selected draw-time native snapshot
with zero differing pixels, even while the older optional final-pixel flag is
off. No rotation is inferred from dimensions; no content/page-number rule is used.

The supported extension is direct-only: explicit coded S and visible V,
right/bottom crop smaller than eight pixels, integer 8px-aligned geometry,
complete coded source/destination coverage including invisible edge blocks,
and supported SOF0 three-component 4:4:4 JPEG layout. Unsafe/ambiguous/missing
proof, gaps/duplicates, work-bound excess, or failed intrinsic comparison
falls back for the whole spread. Cropped mappings cannot become one-hop
upstream proofs. Existing equal-size/one-hop behavior and the kill switch remain.

LN2 has a historical unique full-pixel 1448x2048 JPEG/bitmap match. Its current
selected mapping ID does not supply usable retained tile rows, dimensions or
source identity; the complete same-window join to selected output is missing.
The earlier candidate filter using visible rather than coded dimensions was
invalid negative evidence and is excluded. A stable repeat has a different PNG
hash from the cover, but that alone is not source attribution. No no-clear,
canvas-reset, dimension, filename, order, timing or visual-similarity heuristic
has been introduced to bridge the missing proof.

Two manga body spreads, two changed LN openings, the unsupported LN2 case,
two ordinary-text controls and actual cover fallbacks are sufficient for this
bounded direct renderer contract. LN5–7 were only traversed, not newly captured.
Further cached-canvas or cropped one-hop research is a different contract and
is not needed for Stage 02. Manga2 was unused because no specific cross-title
hypothesis required confirmation. Every independent probe checked actual
counters, explicitly restored its anchor and verified page 1 before closing
its dedicated Page. Shared Crawler Chrome and existing user tabs were preserved.
No credential submission occurred after the user's final manual login.

Validation remains 180 targeted tests and 46 browser-backed Integration tests,
including real Canvas nonuniform/nonidentity 40x40-to-37x36 right/bottom crop.
Ruff and diff checks pass. Critic accepted the material partial-MCU contract;
Reviewer requested that one Integration case, then confirmed no code/test/doc
BLOCKING. Final Reviewer also accepted the completed live set, current cover
fallback controls and synchronized notes. Stage 02 is complete with the D
boundaries above; no additional broad research is required.
No full pytest or full-book/END live run is required for this site-local change.

The existing branch contains fetched current `origin/main`
`96fd5fff84567a4e2c644978d2b4c297174fa2ca`; the continuation merge was already
up to date. This is not provenance evidence. `debug.log` remains untouched,
`.codex/config.toml` retains `max_concurrent_threads_per_session = 2`, and
unreviewed OBJECT-A/B/C diagnostics are not production/source-format authority.
The [Stage 02 checkpoint](../runbooks/bookwalker-source-native/02-provenance-resolution/CHECKPOINT.md)
records exact accepted positions, output/metadata hashes, excluded diagnostic
failures and the historical access issues. Artwork is not committed as fixtures.

## 2. Entry flow

入力は直接viewer URLだけでなく、BookWalker商品URLも受け付ける。

```text
https://bookwalker.jp/de<content-id>/
```

`initialize()` 時、viewer shellがまだ存在せず商品ページだと判断した場合、商品metadataを取得してreader入口を探す。

候補signal:

- `試し読み`
- `読む`
- `10分まる読み`
- viewer URL
- `data-action-label`
- 商品content IDと一致する `data-uuid`

DOM順だけには依存せず、reader URL / content ID / action / visible textをスコアリングする。

reader linkが `target=_blank` の場合は、同じCrawler tabで遷移させるためtarget属性を外してclickする。

### 2.1 Reader control classification

商品ページから取得する `text` / `action` / `href` / `uuid` のmetadataは、
`site_adapters/bookwalker/reader_controls.py` のpure classifierでも扱える。
現在の分類は `maruyomi`、`trial`、`owned`、`subscription`、
`generic_reader`、`unknown` である。`read_maruyomi` またはvisible textの
「10分」+「まる読み」をmaruyomiとし、`subscription_reading` 単独はsubscription
として扱う。viewer URLだけの場合はgeneric readerであり、ownedとは断定しない。

既存manual `auto` flowのselector、wait、navigation、trial fallback、scoreは変更していない。
adapterのcandidate判定だけが同値のpure helperへ委譲され、reader control metadataの分類を
Discovery / strict entryから再利用している。

strict entryはDiscoveryと同じ商品自身のmain action scope
(`#js-read-check-book-cover-main-button`、`#js-read-check`、`#js-subscription-check`)に限定し、
各scope内の`a` / `button` / `[role="button"]` / `[data-action-label]`だけを候補にする。
`text` / `action` / `href` / `uuid` metadataを`classify_reader_control()`へ渡し、
`data-uuid`がある場合は現在product UUIDと一致するcontrolだけを残す。selector重複で同じDOM
elementが複数回見える場合はDOM identityで1件にまとめるが、別elementはmergeしない。
strict direct / quotaではproduct URLがproduct pageの形でも、既存`content_id_from_url()`で
exact content UUIDを取得できない場合はcandidate探索前にfailする。これによりproduct identityが
不明なままcontrol UUID欠落だけを根拠にclickすることを防ぐ。control側`data-uuid`が無い場合は、
product UUIDが確定していてkind等の他のstrict条件を満たす限り許容する。UUID比較はcase-insensitive
で行う。

```text
auto   = legacy score / fallback / deferred trial
direct = ReaderControlKind.OWNED exact only
quota  = ReaderControlKind.MARUYOMI exact only
```

strictではtrial、subscription、generic viewer、wrong-kindへのfallbackはない。期待kindが
0件、または候補が安定しない場合はbounded wait後にfailする。候補が1件でも同じ候補を2回連続で
観測して一意性を確認するまでclickせず、候補が複数の間も最初の観測だけで即failしない。strict
errorにはstrategy、expected kind、observed kindsを含める。product page以外のalready-viewer
strict runも、entry条件を検証できないためfailする。
click後はURL changeだけでentry完了とせず、strict entryのdestinationをAdapter内でbounded pollingする。
viewer URLまたはviewer shellを確認できた場合は即座にviewerとして進み、visibleなemail/password
fieldのlogin formを確認できた場合はloginとして扱う。待機総量は既存の
`navigation_wait_timeout_ms`（default 5000ms）、poll intervalは`strict_entry_destination_poll_interval_ms`
（default 100ms）である。期限までにviewer/login formのどちらも明確にならない場合は、render-ready待ちへ
流さずstrict entry errorで停止する。viewer URLへの直接遷移に固定sleepは追加しない。
delayed controlは既存`read_link_wait_timeout_ms`（default 5000ms）のbounded waitで待つ。
quotaではtrial onlyやsubscription onlyの場合もtrialへfallbackせずfailする。

Batchのstrict `quota` entryでは、まる読みcontrolのclick後にvisibleなemail/password fieldを
login formの強いsignalとして確認する。login formへ遷移した場合だけ、Batch用にAdapterへ渡した
optional credentialで既存のBookWalker form submit処理を1回実行する。login成功後は商品ページへ
戻らず、同じ遷移先のviewer URLまたはviewer shellを確認して、そのまま既存のrender-ready待ちへ進む。
viewer以外のredirect、login formの残存、validation error、CAPTCHA、MFA等は推測操作や再loginを
行わずfail-safeで停止する。auto-loginは1 crawl runにつき最大1回であり、まる読みcontrolの再click
は行わない。通常のsessionで最初からviewerへ入れた場合はauto-login処理を呼ばない。

Batch開始時にBookWalker credentialは必須ではない。sessionが有効ならcredentialなしで従来どおり
viewerへ入れる。session切れでlogin formが出た時にcredentialが不足している場合だけ、
`BookWalker auto-login is required but BOOKWALKER_EMAIL / BOOKWALKER_PASSWORD are not configured`
として停止する。credentialは`RunConfig`、`CrawlerRunner`、Catalog、BatchCandidate、DBへ渡さず、
Batch CLIがBookWalker Adapterのoptional site-local設定として生成時に注入する。

auto-loginを含むBookWalker initializeには、通常のCore defaultを変更せずAdapter側のbounded
45秒timeoutを使う。通常のログイン済みrunへ固定sleepは追加していない。

Phase 4のunit testsではstrict quota/direct成功、wrong strategy、trial/subscription/generic only、
multiple candidate、scope overlapの同一DOM dedupe、delayed maruyomi、UUID mismatch、target blank、
already-viewerをsynthetic product pageで確認している。Browser-backed integrationではstrict entry後の
delayed login form mount、viewer即時判定、unknown destinationのentry fail-safeも確認している。
quotaを消費するlive clickは未実施である。

## 3. Viewer / capture target

BookWalker本文は主にCanvas renderer。

優先する現在画面:

```text
#renderer .currentScreen canvas:not(.dummy)
```

fallbackとして `#renderer canvas:not(.dummy)` も見る。

rendered-canvas fallbackではCore `capture.py` がraw PNG bufferを取得する。browser UIや周辺DOMを避ける。

## 4. drawImage geometry trace

`prepare_page()` でnavigation前に `CanvasRenderingContext2D.prototype.drawImage` をhookし、対象Canvasへのdraw callからdestination rectangleを記録する。

現在画面のpage rectangleが得られれば、その範囲を一時Canvasへコピーしてcapture targetとして返す。

対応する主ケース:

- 中央単ページ
- 表紙 / 挿絵
- 横長単ページ
- true spread
- viewer周辺余白を除いた本文

## 5. Spread fallback

drawImage geometryが取得できない場合のみbounded fallbackを使う。

Canvasが十分に横長 (`spread_ratio = 1.25`) なら中央で左右に分ける。

BookWalkerは右開きとして、capture targetを**右ページ → 左ページ**の順で返す。

manifestには複数target時に `part` / `parts` を記録する。

最初の番号付きページが見開きの場合は表紙見開きとして扱い、通常の本文
見開きのように `page-0001` / `page-0002` へ分割せず、draw geometryの
外接範囲を1つのcapture targetとしてrendered PNG fallbackで保存する。複数のdraw rectangleが
ある場合も外側のviewer余白だけを除いた1枚に結合する。draw geometry自体が
取れない場合は、表紙のrendered pixelから非白色領域を検出して切り出す。
geometryとpixel boundsのどちらも取れない場合だけ、表紙artworkを推測で
切らないためviewer canvas全体へfallbackする。2ページ目以降の見開きは
従来どおり右ページ→左ページの個別artifactとする。

## 6. Browser Session / CDP

### 採用済みの目標仕様

BookWalker専用Chromeを標準とせず、共通Crawler Chrome/profileを使う。

```text
.chrome-crawler/
    └─ BookWalker sessionもChrome自身が保持
```

接続はCDP、通常操作はPlaywright。

BookWalker Adapterは:

- Chrome launch
- profile選択
- endpoint解決
- `connect_over_cdp()`

を行わない。

### Browser Session launcher

共通launcherが標準運用である:

```powershell
.\scripts\start_crawler_chrome.ps1
```

profileは `.chrome-crawler` で、Manga ONEとlogin sessionを共存できる。site-specific launcherは現行運用に含めない。

## 7. Navigation

次ページは右開きreaderの左側操作。

優先:

1. viewerへ `ArrowLeft` を送信
2. page identityが変わらない場合のみ `#viewport1` の左端clickへfallback

`go_next()` は操作前に `#pageSliderCounter` が最終 `N/N` か確認し、`_final_navigation_pending` を記録する。

## 8. Render ready

`_wait_for_render_ready()` は固定sleepだけに依存しない。

確認signal:

- `#loaderStatusDialog` がvisibleでない
- 有効なvisible canvas
- Canvas簡易signature
- non-white pixels
- signatureの連続安定

`render_stable_checks = 4`。

`page_change_timeout_ms = 14_000` 内に安定しなければ `PageChangeTimeoutError`。

## 9. Page identity

主signalは `#pageSliderCounter`。

content IDはURL query `cid` または商品URL `/de<uuid>/` から取得する。

概念:

```text
page_id: page counter text。取れない場合content_id fallback
page_number: parsed current page
source_id: content_id
```

**保存duplicate判定はidentityではなくCoreのcapture SHA-256 fingerprintがauthority。**

## 10. Content context

BookWalkerのcontent IDを `content_id` / `work_id` として保持する。

`#pagetitle` があればtitleもcontextへ入れる。

開始時と現在のcontent IDが明確に変わればNEXT_CONTENT扱い可能。

## 11. State detection

### NEXT_CONTENT

- current content IDがinitial content IDから変化
- `#eobNext` がvisible
- Coreのstrong context change

### END

- `#endOfBook` がvisible
- 最終 `N/N` からnext操作済みでcounterがまだ最終
- renderer ready後、最終counter状態でgrace中に `#endOfBook` が出現

最終本文自体は先に保存済み。次操作後のBookWalker logo canvasを再captureしない。

実サイト確認では59/59後にlogoがCanvas内へ出て、同時に `#endOfBook` がvisibleになった。

### AD

```text
[data-ad]
.ad
#ad
#advertisement
```

の明示selectorのみ。

### LOADING

`#loaderStatusDialog` visible。

### CONTENT

terminal/ad/loadingでなくrenderer ready。

### UNKNOWN

どれにも安全に分類できない場合。

## Timeout layering

BookWalker keeps its adapter-local `page_change_timeout_ms = 14_000` deadline
for identity-based page-change detection and raises
`PageChangeTimeoutError` when the viewer does not advance. The Core runner
wrapper has a separate 2,000 ms grace period via
`RunConfig.adapter_timeout_grace_ms`, so the adapter's diagnostic exception is
normally delivered before the Core cancellation guard. The Core guard still
stops an adapter that hangs without returning. The adapter-local budget is used
for both `initialize()` and `wait_for_change()`, so BookWalker initialization
is not cancelled by the Core's shorter generic default. This change does not
alter the normal ArrowLeft/click-fallback navigation path.

## 12. wait_for_change / retry

- AD / END / NEXT_CONTENT → return
- CONTENTでidentity変化 → render ready後return
- CONTENTでidentity同一かつ最終counter → 最終ページ後の既知挙動としてreturn
- CONTENTでidentity同一 → bounded retry

冒頭cover等で最初のclickが消費されるケースに備え、最大6回追加retryする。2秒ごとにclickとArrowLeftを交互に実行する。

## 13. Duplicate / safety

共通仕様は `note/00_core.md`。

BookWalker captureでも保存dedupeは各artifactのSHA-256 fingerprint。

主guard:

- `max_pages = 1000` default
- `max_same_content = 3` default
- bounded page-change timeout
- bounded loading retry
- fingerprint duplicate guard
- content context change

## 14. Product metadata / naming

商品ページから可能なら:

- main title
- author
- series card title
- series count
- category

を取得する。

キャンペーンtag `【...】` はtitleから除去する。

末尾数字はvolume候補。

```text
作品名4【電子特別版】
→ 作品名 / 第04巻
```

series countが100以上なら3桁volumeを使う。

命名詳細は `docs/BOOK_NAMING_RULES.md`。

## 15. Login

Login DOM操作はBookWalker固有だが、Browser Sessionは共通化する。

目標:

```text
shared Crawler Chrome/profile
→ CDP
→ Playwright Page
→ login_bookwalker()
```

credentials input例:

```env
BOOKWALKER_URL=https://bookwalker.jp/
BOOKWALKER_EMAIL=<email>
BOOKWALKER_PASSWORD=<password>
```

通常endpointは `CRAWLER_CDP_ENDPOINT` を使う。`BOOKWALKER_CDP_ENDPOINT` は例外overrideとして残せる。

loginは共通Browser Sessionが作成する専用new Pageで実行し、既存の別site tabは再利用しない。login後はPageを閉じるが、shared Chrome/profileは残す。

`login.py`はlogin formの安全な検出、現在表示中のformへのcredential入力・submit、従来の
standalone login CLI用のCTA入口へ分離している。Batch quotaのsession切れ経路はform操作部分だけを
再利用し、standalone login CLIの入口動作は維持する。

shared launcherは指定portの既存listenerを、Chrome process command lineのremote debugging portと
`--user-data-dir=.chrome-crawler` が一致する場合だけ再利用する。一致しない、または確認できない場合は
別profile Chromeを黙って再利用せずerrorで停止する。

CAPTCHA / MFA / validation errorを自動突破しない。

現行運用はshared launcher/profileのみである。site-specific endpoint/profileは例外overrideとして残し、sessionの最終authorityをsite別JSONへ移す方針ではない。

## 16. Crawl command

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site bookwalker `
  --url "https://bookwalker.jp/de<content-id>/" `
  --output-dir output\crawl-bookwalker
```

endpoint優先順位:

1. `--cdp-endpoint`
2. `BOOKWALKER_CDP_ENDPOINT`
3. `CRAWLER_CDP_ENDPOINT`
4. default `http://127.0.0.1:9222`

`CRAWLER_CDP_ENDPOINT` fallbackは実装済み。

## 17. Output / packaging

正常 `END` / `NEXT_CONTENT` 後、Coreがmanifest記載artifactだけをZIP化する。
BookWalkerの現行出力はcapture proofに応じたJPEGまたはPNGである。

```text
output/Books/<genre>/<title>/<volume>-<author>.zip
```

上記のfilenameは正規化・サニタイズ後のtitleが50文字未満の場合の形式である。
50文字以上の場合はtitleをfilenameから省略し、`<volume>-<author>.zip`とする。
titleはどちらの場合もlibrary directoryに残り、completion status JSONは同じstemを使う。

completion statusは `output/crawl-status/<genre>/<title>/` 配下で、ZIPと同じstemを使う。
Work間で同じstemになる場合もstatus JSONは衝突しない。

中間crawl directoryは、内容がmanifest / progress / manifest記載artifactだけの場合に限り削除する。

## 18. 実サイト確認済み事項

- 商品ページからtrial readerへ遷移
- Canvasから本文領域取得
- centered single page
- spread
- 右→左のsplit order
- left-side navigation
- page counter / loading / canvas stabilityによるchange wait
- 59/59本文まで保存
- 最終本文後のBookWalker logoを非保存
- `#endOfBook` を含むEND遷移
- ZIP化
- CDP Chrome workflow
- BookWalker login form操作

2026-09-17にshared `.chrome-crawler/`でBookWalker login/crawlに成功し、Manga ONE sessionとの共存を確認した。
loginは既存tabを再利用せず専用new Pageで実行し、終了後はPageだけをcloseしてremote Chromeを維持した。
capture・navigation・page counter・END / NEXT_CONTENT・metadata behaviorに回帰はなかった。

### 18.1 Viewer resolution diagnostic (2026-09-19)

`origin/main` の HEAD `ef8930e9197b4cfd470df47c390b8033aaf08864` を基準に、指定された
trial viewer URLを同じ初期ページ（`2/33`）で、別profile・別CDP portのheaded Chromeから測定した。
Chromeは `152.0.7977.83`、screenはCSS `2560x1440` / available `2560x1392`、
`devicePixelRatio=1.5` だった。4K指定時はこの表示領域のためouter heightが2160まで広がらず、
実測値は次の通りだった。

| 条件 | outer / inner | Canvas CSS | Canvas backing = PNG | PNG bytes | SHA-256 |
| --- | --- | --- | --- | ---: | --- |
| FHD `--window-size=1920,1080` | `1920x1080` / `1906x986` | `1906x986` | `2859x1479` | 1,804,531 | `912fa93489c48e03323c16f3e71248ca0754225e9db07147b127267319260518` |
| 4K `--window-size=3840,2160` | `3840x1461` / `3826x1367` | `3826x1367` | `5739x2051` | 3,208,380 | `81b1458c08050bf3291983575917600ce156cfd96f15550774d048f91f49a308` |
| 4K monitor最大化 `--start-maximized` | `2560x1392` / `2560x1305` | `2560x1305` | `3840x1958` | 2,875,423 | `32036d79e493c4d46bcbf7ab1873433ef569b64a1ffee0c97b6acb5f863649b5` |

Canvas `toDataURL('image/png')` のPNG寸法は、3条件ともCanvas backing寸法と一致した。
FHDに対する4K指定の倍率はwidth `2.007345x`、height `1.386748x`、総pixel `2.783682x`。
最大化はそれぞれ `1.343127x`、`1.323867x`、`1.778122x` だった。

diagnostic-onlyの `drawImage` traceでは、3条件とも本文ページのsourceが
`ImageBitmap 960x1280`で一致した。destination rectangleだけがFHDの概ね
`1110x1479`から4K指定の概ね`1539x2051`へ拡大しており、4Kでsource画像自身が高解像度化した証拠は得られなかった。
したがって、この1ページの実測に基づく判定は「Canvas/PNG pixel数は増えるが、sourceは同じで単なるupscaleの可能性が高い」
であり、現行CrawlerのFHD設定を維持する。4K変更は保存PNGのpixel数・bytesを増やすが、実情報量向上の根拠がないため採用しない。
この測定ではproductionコードとshared `.chrome-crawler/`設定を変更していない。

### 18.2 別trial viewer URLの解像度確認 (2026-09-19)

別のtrial viewer URLでも同じFHD / 4K指定 / 4K最大化の比較を行った。対象は初期ページ
`1/11`で、前項のURLとは異なり、本文sourceは3条件すべてで`ImageBitmap 1303x2048`だった。

| 条件 | outer / inner | Canvas backing | drawImage destination | capture PNG | PNG bytes |
| --- | --- | --- | --- | ---: | ---: |
| FHD `--window-size=1920,1080` | `1920x1080` / `1906x986` | `2859x1479` | `941x1479` | `941x1479` | 2,091,499 |
| 4K `--window-size=3840,2160` | `3840x1461` / `3826x1367` | `5739x2051` | `1305x2051` | `1305x2051` | 3,667,037 |
| 4K monitor最大化 `--start-maximized` | `2560x1392` / `2560x1305` | `3840x1958` | `1246x1958` | `1246x1958` | 3,404,443 |

全条件で`devicePixelRatio=1.5`、sourceは同一だった。FHDはsourceに対して縮小、4K指定はほぼ1:1、
最大化は軽い縮小であり、viewerがwindowサイズに応じてCanvas上のdestinationを変えることを確認した。
このURLではsourceが`960x1280`ではないため、前項の`960x1280`基準をそのまま適用しない。
この追加確認でもshared `.chrome-crawler/`、launcher、RunConfig、Adapter、capture.pyは変更していない。

### 18.3 別trial viewer URLで3回左送り後の確認 (2026-09-19)

18.2と同じtrial viewerで、BookWalker Adapterの左端クリックとbounded change waitを3回実行してから測定した。
viewerのページカウンタは`1/11`から`7/11`へ進み、各左送りが見開き単位で進んだ。最終状態では左右2ページの
capture targetが得られ、sourceは全条件で`ImageBitmap 1303x2048`だった。

| 条件 | Canvas backing | destination | capture targets | PNG bytes（左右） |
| --- | --- | --- | --- | ---: |
| FHD `1920x1080` | `2859x1479` | `941x1479` | `941x1479` × 2 | 1,182,036 / 1,131,786 |
| 4K `3840x2160` | `5739x2051` | `1305x2051` | `1305x2051` × 2 | 2,177,191 / 2,088,126 |
| 4K monitor最大化 | `3840x1958` | `1246x1958` | `1246x1958` × 2 | 1,993,944 / 1,907,827 |

3条件とも`devicePixelRatio=1.5`で、sourceの解像度は変わらなかった。今回もproductionコードとshared
`.chrome-crawler/`設定は変更していない。

### 18.4 3つ目のtrial viewer URLで0 / 3 / 17回左送り後の確認 (2026-09-19)

別のtrial viewerで、FHD / 4K指定 / 4K最大化の各条件について、初期ページ、3回左送り後、
17回左送り後をfresh profileで測定した。ページカウンタはそれぞれ`1/53`、`4/53`、`29/53`となった。

| 左送り | FHD source → capture | 4K source → capture | 最大化 source → capture |
| ---: | --- | --- | --- |
| 0回 | `1443x2048` → `1043x1479` (2,766,512 bytes) | `1443x2048` → `1446x2051` (4,764,465 bytes) | `1443x2048` → `1380x1958` (4,428,270 bytes) |
| 3回 | `2048x1090` → `2779x1479` (4,272,052 bytes) | `2048x1090` → `3854x2051` (7,027,187 bytes) | `2048x1090` → `3679x1958` (6,551,351 bytes) |
| 17回 | `960x1280` → `1110x1479` × 2 (693,070 / 694,622 bytes) | `960x1280` → `1539x2051` × 2 (1,211,058 / 1,237,419 bytes) | `960x1280` → `1469x1958` × 2 (1,129,657 / 1,128,289 bytes) |

全条件で`devicePixelRatio=1.5`だった。17回左送り後のページだけはsourceが`960x1280`で、FHDでも拡大描画、
4K指定ではさらに大きく拡大描画されることを確認した。診断traceは各navigation前にリセットし、最終ページの
drawImage geometryだけを評価している。この確認でもproductionコードとshared `.chrome-crawler/`設定は変更していない。

今回の3サンプルの目視分類では、0回（1回目）は他社のライトノベルの表紙、3回左送り後（2回目）は漫画、
17回左送り後（3回目）はKADOKAWA系のライトノベルの表紙・挿絵・通常本文が混在するページだった。

### 18.5 source-native PNG feasibility diagnostic (2026-09-19)

最新`main`のHEAD `a118b5cd643a4b3bddc7e4abce0061b7ed406ef4`を基準に、既存のtrial viewer URLを
fresh profile・専用CDP portで再利用し、`drawImage()`のsourceを呼び出し時に一時Canvasへ即時copyした。
productionの`BookWalkerAdapter`、Core capture、CrawlerRunner、launcher、RunConfigは変更していない。

source-native PNGは、source全体を`source.width`×`source.height`のtemporary canvasへ描画したPNGと、
`source rectangle`だけを同じnative寸法で描画したPNGの両方を保存した。current PNGは既存の
`get_capture_targets()`経由で取得し、native cropをcurrent target寸法へ一時resizeした補助比較も行った。
補助比較の差分値は小さいほど視覚内容が近いことを示す。Pillowを使ったdiagnostic-onlyの比較であり、
productionでresizeする処理ではない。

| sample / viewer state | source / draw | source rectangle | destination | current PNG → native PNG | 補助比較 (mean / RMS) |
| --- | --- | --- | --- | --- | ---: |
| A: `3e1a3eff...&cty=0`, `2/33` | `ImageBitmap 960x1280`, 9引数 | full `0,0,960,1280` | 2 target: `1110x1479` | `1110x1479` → `960x1280` × 2; native `1,240,180 / 102,707` bytes | `1.0979 / 3.6257`; `0.3337 / 5.8903` |
| B: `afea11c1...&cty=0`, `1/53` | `ImageBitmap 1443x2048`, 9引数 | full `0,0,1443,2048` | `1043x1479` | `1043x1479` → `1443x2048`; native `4,624,465` bytes | `1.1041 / 2.6574` |
| C: 同URL、3回左送り後 `4/53` | `ImageBitmap 2048x1090`, 9引数 | full `0,0,2048,1090` | `2779x1479` | `2779x1479` → `2048x1090`; native `2,576,173` bytes | `0.7008 / 2.4888` |
| D: `0d110c3b...&cty=1`, 3回左送り後 `7/11` | `ImageBitmap 1303x2048` × 2, 9引数 | 各sourceともfull | 右 `941x1479` / 左 `941x1479` | 各`941x1479` → `1303x2048`; native `2,174,727 / 2,092,990` bytes | `3.1219 / 6.1734`; `2.8404 / 5.7048` |

全sampleで`devicePixelRatio=1.5`、Canvas transformはidentity (`a=1,b=0,c=0,d=1,e=0,f=0`)、
`globalCompositeOperation=source-over`、filterは`none`だった。source rectangleは全sampleでsource全体と一致し、
atlasの一部cropや複数sourceの合成は今回観測されなかった。current/nativeを目視比較した結果、表紙・本文・
漫画のページ内容、上下左右の余白、回転、反転に明らかな差はなく、spread Dも右ページ→左ページのreading orderを
維持して個別PNG化できた。

ImageBitmapのreferenceを長時間保持せず、`drawImage` interception中にnative copyを完了させる方式で、4種類とも
PNG生成に成功した。sourceを保存したreferenceの寿命問題は避けられる一方、diagnosticでは該当drawごとにPNG化する
ため、同じ方式をproductionへ入れる場合はcapture latencyとmemoryを別途測定する必要がある。各viewer navigationは
既存Adapterのrender-ready / page-counter change waitを通過し、今回の範囲ではnavigation failureは発生しなかった。

この調査範囲ではsource-native captureの feasibility は高い。ただし未観測の複数draw、transform、atlas、transition中の
一時sourceを安全に分類できることまでは証明していないため、実装は「source-native優先 + 失敗時は既存Canvas
cropへfallback」とする。上記のdiagnostic結果を基に、今回の実装でBookWalker Adapterへこのcapture pathを組み込んだ。

再現用scriptは`scripts/diagnose_bookwalker_native_source.py`、生成したdiagnostic PNG/JSONは
`output/diagnostics/bookwalker-source-native/`配下に保存した。実サイトの画像はfixtureやcommitには含めない。

### 18.6 source-native production capture (2026-09-19)

BookWalkerの`capture_page()`は、初回navigation前と`go_next()`クリック前にnative traceをarmし、
`drawImage()` interception中にsource rectangleをtemporary canvasへ即時copyする。`ImageBitmap`等の
source referenceは保持しない。production native採用対象のsource typeは当面`ImageBitmap`だけに限定し、
HTMLImageElement、OffscreenCanvas、HTMLVideoElement、unknownはfallbackする。
購入ビューアーで使われるHTMLCanvasElementは、eager source cropが各draw callに保存されている
場合に限り、同じ安全条件でnative capture対象とする。
CONTENT capture時にvisible canvasのgeometry traceとnative traceを対応付け、
source rectangle cropのPNGがsource rectangle寸法と一致し、transformがidentity、compositeが
`source-over`、filterが`none`の場合だけnative resultを返す。

source trace欠落、PNG生成/検証失敗、寸法不一致、複数sourceによる同一rectangleの合成、atlas rectangleの
変化、transform / composite / filter、またはspread片側の失敗ではページ全体をnative採用せず、Coreの既存
Canvas crop経路へfallbackする。native成功時はnative traceとgeometry traceの両方をclearし、次ページへ
進む前に前ページgeometryを持ち越さない。native失敗時はnative traceだけをclearしてgeometry traceを
残し、fallbackの`get_capture_targets()`が使った後に`cleanup_capture_targets()`でgeometry traceをclearする。
spreadは右ページ→左ページ順を維持する。native hookの成否はCoreの
fingerprint、manifest sequence、`part` / `parts` metadata、page dimensions処理を変更しない。

Coreにはsite-specificな判定を追加せず、base `SiteAdapter.capture_page()`は`None`を返す。native hookが
`None`または`CaptureUnavailableError`を返した場合、Coreは`get_capture_targets()` / `capture_locator()`へ
戻る。direct hookのtemporary stateはhook自身がclearし、fallback時もtraceをdisable・clearする。

Unit testではdirect resultのLocator bypass、unavailable fallbackとcleanup、PNG寸法、transform /
composite / filter、複数source / atlas reject、spread right-to-leftを固定した。先行live diagnosticの
4 sampleではnative copy成功とnavigation failureなしを確認済みであり、実画像はfixture/commitへ保存しない。

### 18.7 Original source bytes feasibility diagnostic (2026-09-19)

GitHub `main` HEAD `727d051db3e847090f46c72f52d5a67a572d27f3`をauthorityとし、過去のlive確認で
使用したtrial viewerを再利用した。対象は`3e1a3eff...&cty=0`（`2/33`）、`0d110c3b...&cty=1`
（`1/11`）、`f5b3ae37...&cty=0`（`1/60`）である。queryの`Policy`、`Signature`、`Key-Pair-Id`、
`pfCd`、`cid`等の値はartifact metadataではredactし、本文画像はcommitしない。

診断script `scripts/diagnose_bookwalker_original_source.py` は、Playwright response監視に加えて、
本文epub hostだけを限定したroute fetchでresponse bodyを即時取得した。CDP `Network` metadataも
併記し、URL、method、status、Content-Type、Content-Length、body bytes、magic bytes、拡張子、
resource typeを記録した。page init scriptでは`Blob`相当、`URL.createObjectURL`、`fetch`、XHR、
`Response.arrayBuffer` / `Response.blob`、`createImageBitmap`、`drawImage`を限定的にhookした。
一般のBlobはJavaScript/Cookie用で観測され、本文JPEGはmain-worldの`Response.blob`や
`createImageBitmap`入力としては直接観測されなかった。一方、本文は次のnetwork responseとして
直接観測できた。

```text
viewer-epubs-trial.bookwalker.jp/.../0.jpeg または 0.jpegbvCoverImage?...
HTTP 200 / Content-Type: image/jpeg / resource type: xhr
magic: ff d8 ff e0 ... (JPEG)
```

同一pixel sourceとの対応は、ImageBitmapのsource寸法と、route fetchで保存したJPEGをbrowser decoderで
比較して確認した。全sampleで差分はmean / RMSとも`0 / 0`だった。

| sample | ImageBitmap | current native PNG | original JPEG | ratio original/native | 判定 |
| --- | ---: | ---: | ---: | ---: | --- |
| `3e1a3eff...&cty=0`, target 1 | `960x1280` | `1,240,180` | `224,798` | `0.181262` | Case 1 |
| 同URL、target 2 | `960x1280` | `102,707` | `39,706` | `0.386595` | Case 1 |
| `0d110c3b...&cty=1` | `1303x2048` | `3,647,962` | `563,803` | `0.154553` | Case 1 |
| `f5b3ae37...&cty=0` | `1443x2048` | `5,806,803` | `917,642` | `0.158029` | Case 1 |

従って今回のsampleでは、配信response自体が標準JPEG bytesであり、復号後に独自の標準画像bytesを
生成している経路ではない。分類は全て**Case 1: 配信された画像bytesをそのまま取得できる**である。
PNG再エンコードに対して容量は約`61.3%`〜`84.5%`削減された。ただし通常のPlaywright
`response.body()` / CDP `getResponseBody`だけでは、XHR画像が遷移・cache扱いになった場合にbodyを
取得できないsampleがあり、diagnosticでは本文host限定のroute fetchで補った。token付きsigned URLを
再生成する必要はないが、response interceptionとsource↔draw対応、body取得失敗時のfallbackが必要になる。

production採用価値は**小規模変更で可能だが、現在のnative PNGを直ちに置き換えるほど単純ではない**。
容量削減は大きく、PNG encode負荷も減る可能性がある一方、route/CDP body bufferingはmemoryを増やし得る。
viewerのXHR/cache挙動、signed URL、先読み複数JPEG、ImageBitmapとの対応づけに依存し、response body取得失敗時
には現在の`ImageBitmap -> PNG`をfallbackにする必要がある。将来候補にはできるが、現時点ではproduction
capture behaviorを維持し、source-native PNGを安全な基準経路として残す判断とする。

diagnostic JSON、redact済みnetwork log、比較用の一時画像は
`output/diagnostics/bookwalker-original-source/`配下に保存した。今回の変更では
`BookWalkerAdapter.capture_page()`、Core、Runner、packaging、launcher、shared profileを変更していない。

### 18.8 original JPEG capture (implemented, enabled by default)

The original-JPEG path remains implemented and
`BookWalkerAdapter.enable_original_jpeg_capture` is currently `True`.
Production runs install the bounded JPEG response listener/route and perform
conservative JPEG candidate matching after deferred source-native capture.
The earlier JPEG-disabled default was introduced after a long-run trial smoke
saved only one JPEG and then stopped in `wait_for_change` after 140 pages; the
failure itself was a page-change timeout rather than a JPEG body error.  The
deferred path and navigation retry budget have since been corrected and
reverified in 18.16.

When explicitly enabled in code, the response listener is limited to
`viewer-epubs*.bookwalker.jp` for trial/free viewers and
`bw-bv-epubs.bookwalker.jp` for the purchased full viewer; signed URLs are
observed as-is and are never reconstructed. JPEG bodies are held in a
deduplicating bounded cache of at most 32 entries and 64 MiB, with an
individual response body limit of 16 MiB.
Body-read failures are ignored so the PNG fallback remains available.

The draw hook records lightweight source metadata and retains the source
objects without PNG-encoding every `drawImage()` call.  After the final draw
calls are selected by geometry, only the selected source rectangles are
materialized as PNG.  When explicitly enabled, JPEG candidates use the same
browser decode, resize, RGBA hashing path.  A JPEG is selected only when magic
bytes, dimensions, exact signature, and candidate uniqueness all pass.
Matching is attempted at most three times with a 150 ms bounded wait between
attempts.
Spread capture is all-or-nothing: if any part is not uniquely matched, every
part returns source-native PNG and no JPEG/PNG mixture is emitted.

The final Core fallback remains unchanged: if source-native capture itself is
unavailable, `capture_page()` returns `None` and Core uses the existing Canvas
crop PNG path.  The ordinary original-JPEG match uses the existing browser
signature; the Phase P1 purchased shadow additionally performs a full-
resolution comparison against the retained ImageBitmap and native PNG.  The
current native PNG is intentionally retained as the conservative comparison
basis.  `.jpg` is now accepted by manifest/package/ZIP validation alongside
`.png` and `.webp`.

No token values or real-site page images are stored in the repository.  Earlier
bounded live smoke on the existing trial viewers produced `.jpg` artifacts for
the 960x1280, 1303x2048, and 1443x2048 source-size samples, but the full
multi-page/END behavior was not established for the JPEG path.  Current unit
coverage includes the enabled production default, JPEG validation, browser
signatures, cache bounds, retries, spread fallback, response filtering, and
`.jpg` packaging.

### 18.9 ArrowLeft navigation fix (2026-09-19)

The BookWalker production navigation now sends `ArrowLeft` directly after
arming the native capture trace.  The previous `#viewport1` left-edge click
could be accepted by Playwright without being handled as a page-turn by the
viewer; `wait_for_change()` then retried the same ineffective click until its
bounded timeout.  A process-local live smoke using the existing trial product
URL, with JPEG capture and packaging otherwise unchanged, completed at END
with 59 `.jpg` artifacts and a ZIP archive.  The change is limited to
`BookWalkerAdapter.go_next()`; capture priority, network interception,
fallbacks, Core, and packaging behavior are unchanged.

### 18.10 Identity-based navigation fallback (2026-09-20)

Navigation keeps `ArrowLeft` as the primary action.  `wait_for_change()` now
uses the page identity as the success condition and sends the legacy
`#viewport1` left-edge click only when the identity remains unchanged after a
bounded retry interval.  This avoids treating a Playwright-successful but
viewer-ignored input as a successful page turn, while also avoiding an
unconditional double action when `ArrowLeft` is merely delayed.  The fallback
remains bounded by the existing page-change timeout and retry count.

### 18.11 Stable strict reader-control detection (2026-09-20)

BookWalker product pages can transiently expose two matching strict reader
controls while the access action scope is replaced. Strict `direct` / `quota`
entry now waits within the existing 5-second bound, applies a short initial
settle of up to 250 ms, and polls at 100 ms intervals. A matching control is
accepted only after the same in-browser candidate identity is observed twice
consecutively. Zero candidates and transient multiple candidates invalidate
the previous sample and are rechecked instead of failing immediately.

Persistent ambiguity still fails before click with the existing fail-safe
behavior. The change is limited to BookWalker product-page entry detection;
quota accounting, reader navigation, Core behavior, and capture behavior are
unchanged.

### 18.12 PNG-only live verification (2026-09-20)

For the trial viewer URL with content ID
`f5b3ae37-360c-45e2-adcf-f2ddfac1251f`, an earlier JPEG-disabled verification
bypassed the original-JPEG response listener, route interception, and JPEG
matching. The run used source-native PNG capture and completed all 60 pages at `end`,
including pages 3 and later.  The resulting archive contained 60 PNG files
and no JPEG files.  This is a live verification that the same URL's earlier
page-3 stop does not reproduce when the JPEG path is disabled; it does not by
itself prove that source-native PNG is the only cause of the earlier stop.

### 18.13 Deferred source-native PNG materialization (2026-09-20)

The source-native PNG path no longer calls `toDataURL("image/png")` inside
every `drawImage()` hook invocation.  The hook records geometry, sourceId,
source rectangle, transform, and composition metadata.  `ImageBitmap` keeps
the existing deferred source-reference path; mutable `HTMLCanvasElement`
sources are copied into bounded snapshot canvases during the draw hook.  Once
the final visible draw calls are selected, only those one or two sources are
encoded as PNG.  Cleanup clears draw calls, retained source objects, and
snapshot canvases.

This is intended to keep the source-native dimensions and lossless PNG
artifact while reducing initial/preload work.  The pre-fix live verification
with the same 60-page trial viewer completed at `end` with 60 PNG pages, but
the deferred error-field defect described in 18.15 meant that run could use
the Core canvas fallback.  Observed page-processing
intervals were about 2.5--3.0 seconds for the first large spread pages and
about 1.0--1.3 seconds for later regular pages; these intervals include page
capture as well as navigation wait, so they are operational timings rather
than an isolated viewer-animation measurement.

### 18.14 JPEG comparison and fallback verification before the fix (2026-09-20)

The same 60-page trial URL was run in three process-local live variants:

| variant | source-native PNG timing | JPEG capture | result |
| --- | ---: | --- | --- |
| pre-optimization equivalent (eager crop on every draw) | 41.0 s | disabled | 60 PNG, `end` |
| pre-optimization equivalent (eager crop on every draw) | 55.0 s | enabled | 60 JPEG, `end` |
| current deferred crop | 44.7 s | disabled | 60 PNG, `end` |
| current deferred crop | 44.7 s | enabled | 60 PNG, 0 JPEG, `end` |

These wall-clock totals are single live runs and include the viewer's network
and navigation timing, so they are directional rather than a benchmark.  They
show that the old eager-plus-JPEG combination can complete but pays the largest
cost, while deferred-plus-JPEG produced no JPEG artifact for this URL.  In that
deferred live run, the PNG files were produced by the Core canvas fallback, not
by a successfully accepted source-native capture; the cause is recorded below.

JPEG is an optimization after source-native PNG capture, not a required path.
The adapter first creates the source-native PNG, then uses browser-image
signatures to accept JPEG only when every visible part has exactly one matching
candidate.  If any part is missing, ambiguous, or fails validation, the
complete visible capture falls back to the source-native PNG.  If source-native
capture itself is unavailable, `capture_page()` returns `None` and the Core
capture fallback may produce a canvas PNG instead.  Production now enables
deferred source-native plus JPEG matching; failed matching still falls back to
source-native PNG.

### 18.15 Deferred materialization error-handling defect and fix (2026-09-20)

The live comparison identified why the deferred-plus-JPEG variant produced
zero JPEG files.  The browser-side materialization wrapper returned a valid
`dataUrl` but converted a normal `copySourceCrop()` result of `error: null`
into the string `"native source crop unavailable"` by using a truthiness
fallback.  The Python safety check then rejected the call because
`sourceCropPngError` was non-empty.  `capture_page()` returned `None` before
JPEG signature matching, so Core captured the visible canvas as PNG.

The eager path does not pass through this error-field conversion and therefore
reached JPEG matching, yielding 60 JPEG files in the same live run.  This
defect was corrected by preserving a normal `null` error value.  Production
now enables deferred source-native plus JPEG matching; failed matching still
falls back to source-native PNG.

### 18.16 Deferred source-native plus JPEG live verification (2026-09-20)

After the error-field fix and retry change, the same 60-page trial viewer
completed at `end` in 54.837 seconds with 60 JPEG artifacts and no timeout.
The run used deferred source-native capture and JPEG matching. One fallback
click occurred, with the remaining navigation actions using ArrowLeft.

The navigation retry behavior is intentionally bounded. `go_next()` sends one
`ArrowLeft`; if identity remains unchanged while the page is still CONTENT,
`wait_for_change()` performs up to six additional actions at 2, 4, 6, 8, 10,
and 12 seconds: `click`, `ArrowLeft`, `click`, `ArrowLeft`, `click`,
`ArrowLeft`. The adapter stops at 14 seconds. AD, END, NEXT_CONTENT, an
identity change, and the final `N/N` counter return without retrying. The Core
runner uses the adapter's page-change budget plus its 2,000 ms grace and does
not independently retry navigation.

### 18.17 Purchased full-reader entry and JPEG host (2026-09-20)

The purchased product-page control uses `data-action-label="read_purchased"`
while its visible label remains `読む`. The strict `direct` entry classifier
now treats this action as `owned`, so it follows the purchased cooperation
link and does not fall back to trial, maruyomi, or subscription controls.

The purchased viewer uses `viewer.bookwalker.jp` as its shell and fetches page
JPEGs through `bw-bv-epubs.bookwalker.jp` as XHR responses. The original-JPEG
capture route and host filter now include that exact host. Trial/free
`viewer-epubs*.bookwalker.jp` capture remains unchanged. JPEG acceptance still
requires valid bytes, matching dimensions, an exact browser-side signature,
and a unique candidate for every visible spread part; otherwise the complete
page remains PNG. The purchased viewer decodes its JPEG tiles into an
`HTMLCanvasElement` before drawing; this source type is accepted only with the
same identity-transform/source-over geometry checks used for `ImageBitmap`.
Because that source canvas is mutable during a spread render, the draw hook
keeps a bounded pixel snapshot, and materialization encodes that snapshot
rather than rereading the mutable source. Repeated source IDs are accepted
for a spread only when each draw call retained its own snapshot. If the raw
tile JPEG does not uniquely match, the verified source-native PNG is returned
as-is; no PNG-to-JPEG re-encoding is performed. A spread still falls back as a
complete unit when its native capture is unavailable.

### 18.18 Purchased viewer live verification (2026-09-20)

An earlier shared-profile CDP live verification used the purchased product URL
`de5a10a196-9a63-4157-974e-e60359518638` with strict `direct` entry. The
product control was `read_purchased`, the resulting viewer was
`viewer.bookwalker.jp`, and a bounded run saved four JPEG artifacts for two
spread transitions (`page-0001.jpg` through `page-0004.jpg`). Each artifact
was 960x1280 and the two parts of each spread had different fingerprints; no
duplicate-source spread was emitted. The bounded run intentionally reached
the `max_pages` guard after collecting those four pages. Those JPEGs depended on
the rendered PNG-to-JPEG fallback that has since been removed; the current
implementation keeps JPEG only when an original response matches exactly and
otherwise preserves the source-native PNG.

### 18.19 Purchased capture safety correction (2026-09-20)

`ImageBitmap` uses bounded deferred source-crop materialization.
`HTMLCanvasElement` uses a bounded draw-time pixel snapshot and is encoded only
after native draw-call selection. Native output priority is verified original
JPEG, verified source-native PNG, then the existing Core canvas PNG fallback.
The old quality-0.92 rendered JPEG fallback is not used, so failed original
matching cannot inflate PNG artifacts or introduce a JPEG/PNG mixture in a
spread.

The runner also applies the adapter-specific page-change timeout to the
duplicate-fingerprint wait branch, matching the normal navigation branch.

### 18.20 Cover geometry correction (2026-09-20)

Shared-profile CDP comparison of a purchased viewer and a trial viewer showed
that both render the actual page into a centered destination rectangle inside a
larger white canvas. The previous first-page special case deliberately kept
that full canvas, which explains the cover-only outer margins. The adapter now
uses the normal draw-geometry crop for a single cover rectangle, combines
multiple cover rectangles into one union crop, and uses a rendered non-white
pixel-bound crop if the first frame arrives before geometry tracing records a
draw. This preserves one cover artifact even in the initial-frame race observed
in `bookwalker-rerun-130`. This is unrelated to PNG/JPEG conversion; native
PNG/JPEG selection remains unchanged.

### 18.21 Capture-mode A/B switch (2026-09-21)

BookWalker capture mode is selected inside the adapter by
`BOOKWALKER_CAPTURE_MODE`; the default is `native`, and the only accepted
values are `native` and `canvas`. `native` enables source-native capture,
original-JPEG matching, and the Core canvas fallback. `canvas` does not arm
native capture, does not retain source objects or draw-time snapshots, does
not observe original JPEG responses, and returns `None` from `capture_page()`
so the existing rendered-canvas path is used.

The mode assignment and draw-trace installation are registered as one init
script, so `canvas` cannot be changed to `native` by init-script execution
order.

For an A/B live run, use the same shared Crawler Chrome/profile, source URL,
and bounded page count in separate empty output directories:

```powershell
$env:BOOKWALKER_CAPTURE_MODE = "native"
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl --site bookwalker --url "https://bookwalker.jp/de<uuid>/" --output-dir output\bookwalker-native --max-pages 10

$env:BOOKWALKER_CAPTURE_MODE = "canvas"
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl --site bookwalker --url "https://bookwalker.jp/de<uuid>/" --output-dir output\bookwalker-canvas --max-pages 10
```

Compare completion state, timeout count, saved page count, skipped pages,
duplicate fingerprints, and observed transition speed. This note records the
mode behavior and test procedure; a live result is added only after that exact
run has been executed.

The requested product URL was live-tested on 2026-09-21 with the shared
Crawler Chrome/profile. A `native` run saved five artifacts (`1/349` through
`5/349`) before the intentional `max_pages=5` guard stopped the run; the first
artifact was original JPEG and the remaining four were PNG. A `canvas` run
from the viewer's remembered position first started at `5/349`, so that run
was retained only as a state-persistence observation. After bounded
ArrowRight navigation returned the viewer to `1/349`, a second `canvas` run
saved five PNG artifacts (`2/349` through `6/349`) before the same guard. Both
runs had no navigation timeout; their process exit was the expected
`MaxPagesExceededError`. Because the canvas fallback advanced past the initial
cover frame during this short run, these outputs are not a page-for-page visual
equivalence result; they do confirm the mode switch and the absence of native
JPEG artifacts in `canvas` mode.

## 19. Known limitations / maintenance

- BookWalker DOM / Canvas renderer変更時は再調査が必要。
- drawImage geometryが取れない未知作品ではfallbackになる可能性がある。
- 直接viewer URLから開始すると商品metadataが不足する可能性がある。
- 同名完成ZIPは上書きしない。
- global fingerprint dedupeのためpixel完全一致の別ページは1枚扱いになる。
- `config.yaml` はruntime authorityではない。
- diagnosticsのAdapter固有metadata統合は未実装。
- BookWalker Site Policyは05:00 JST window / site-wide capacity 1として実装済み。
- BookWalker Adapterのstrict `direct` / `quota` entryとBatch Executor連携は実装済み。
- BookWalker quotaの実サイトlive clickは未確認。synthetic/local Catalogでのpolicy・planner・executor検証までを完了範囲とする。
- Phase 6 automated cross-site regression is green, including BookWalker
  navigation retry, native capture/fallback, quota policy, packaging, and
  shared pacing/AccessGuard behavior. A new normal live Batch was not run
  because the verification Catalog exposed only a quota candidate; see
  `docs/PHASE6_VERIFICATION.md`.
- 2026-09-18にseries 317089をshared Crawler Chromeでlive確認済み（`ul.m-tile-list` / `li.m-tile` 11件 / full Discovery成功）。別構造のpagination variantは未確認。
- 現行reader candidate scoringはmanual `auto` 互換経路として維持する。

## 20. 採用済み次期仕様と現行Discovery境界

authorityは `docs/DISCOVERY_AND_BATCH.md`。ここではBookWalker固有の要点だけを
現行実装との境界が分かる形で記録する。

### 20.1 Watchlist / series scope

BookWalker Discovery targetは初期実装で:

```text
https://bookwalker.jp/series/<series-id>/list/
```

だけを扱う。site全体や「まる読み10分」全対象を探索しない。

同じseries listに列挙された商品は、商品titleの文字列推定にかかわらず同じ
Discovery group / packaging seriesとして扱う。series listには通常巻以外に
購入特典、DJCD、番外編等が混在し得るため、それらを通常巻と推測しない。

identity / metadata:

- `discovery_key` = Watchlist key
- `external_id` = 商品URL `/de<uuid>/` のUUID
- `canonical_title` = non-empty Watchlist label、なければseries pageのseries名
- 通常巻だけ安全に `order_key` を数値化。`#16`、`第16巻`、`16巻`、既存の末尾数字形式を扱う
- series cardのstructured special marker（実DOM未確認）を優先し、特典商品は`order_key`を付けず識別できる`order_label`を保持
- title fallbackは先頭の`【購入特典】` / `【特典】` / `〖購入特典〗` / `〖特典〗`だけをspecialとする。途中の「特典」は対象外
- authorは商品ページの`著者`役割だけを保持し、`イラスト`、`原作`、`作画`、`漫画`、`訳`、`監修`以降の役割は除外する
- series由来titleをBatch explicit metadataとしてCrawlerへ渡し、同一series folderへ揃える

same `external_id` が別non-null `discovery_key` に既存の場合、scopeを黙って
移動せずDiscovery incompleteとする。

現行の `BookWalkerDiscoveryAdapter` はこのscopeを検証し、series list内のproduct cardから
`/de<uuid>/` product linkを重複排除して列挙する。旧fixture/旧DOM互換として
`#js-series-list` + `article`を保持し、現行のserver-rendered listでは
`ul.m-tile-list` + `li.m-tile`を使用する。paginationはboundedに進め、listingが
曖昧・空・loop・上限到達した場合はcomplete扱いにせずincompleteとする。商品ページの
reader control観測はreaderを開かずに行う。

2026-09-18にshared Crawler Chromeで`https://bookwalker.jp/series/317089/list/`
をlive確認した。現行ページは`ul.m-tile-list` 1件、`li.m-tile` 11件で、
canonical product linkは`a[href]`の`/de<uuid>/`形式だった。`#js-series-list`と
`article`は存在しなかったため、旧selectorだけではDiscoveryが最初のrecordをyieldせず
`incomplete`になっていた。現行対象は一覧内に11件が揃い、確認時点でpagination controlは
表示されなかった。product pageのtitle/author/genre/reader-control抽出は同じlive確認で
既存scriptが取得できることを確認した。

selectorの確認状態:

- live確認済みのseries Discovery selector: `ul.m-tile-list`、`ul.m-tile-list > li.m-tile`
- local/synthetic fixtureで確認した互換selector: `#js-series-list`、`#js-series-list article`
- local/synthetic fixtureで確認したspecial marker: `[data-badge]` の「購入特典」
- Discoveryが既存Adapterから再利用するreader control scope: `#js-read-check-book-cover-main-button`、`#js-read-check`、`#js-subscription-check`
- Discovery pagination候補（`rel=next`、`aria-label`、`data-testid`、表示テキスト）は実装済み。今回のlive対象ではpaginationなし

### 20.2 Discovery access classification

Phase 1では、この仕様で使うBookWalker reader-control metadataのpure分類helperを
実装済みであり、Phase 3のDiscovery Adapterが商品詳細ページ観測で再利用する。Catalog更新は
site-neutralなDiscoveryServiceが行う。

Discoveryはseries listから商品詳細ページを開いてcontrolを観測するが、
readerは開かない。まる読み10分timerをDiscoveryで開始しない。

Schema v3では、DiscoveryServiceが商品recordの`DiscoveredSource.url`をWeb取得経路として
`source_targets`へ`backend=web`、`locator=<最新の商品URL>`、`priority=100`、
`enabled=true`でupsertする。source identityは引き続き(site, external_id)であり、
URL再観測では同じWeb targetのlocatorだけが更新される。Batch Plannerはenabledな
Web targetをpriority、target ID順で選び、既存Web Executorがlocatorを
`RunConfig.source_url`へ渡す。別backendのtargetは保存されても現在のWeb flowでは変更・実行しない。

ログイン済みshared Crawler Chromeを前提とし、series pageと各product pageの
header/account領域にある明示的なvisible「ログイン」CTA、login form、password input、
authentication challengeだけを確認する。member.bookwalker.jpへのリンクや本文全体の
「ログイン」文字列はlogged-out根拠にしない。account状態を安全に確認できない場合は
recordをyieldする前にincompleteとする。product navigation後は最終URLの`/de<uuid>/`
が要求UUIDと一致することも確認し、login redirect・外部domain・別UUIDはincompleteとする。

product titleはreader-control ready signalにしない。title等のmetadata取得後も最大5秒間
商品自身のmain action scopeを100ms間隔でbounded waitし、最初の`試し読み`だけでは即確定しない。
`試し読み`観測後は最大500msのsettle期間を置き、その間に遅延表示された強いcontrolを優先する。
全体のcontrol待ちは最大5秒で、timeout後にproduct identity/titleが
正常でcontrolがない商品はunknownとしてyieldし、identity/titleが確認できない場合だけincompleteとする。
series list等の関連商品のtrial controlはproduct access判定から除外する。購入特典・特殊商品は
商品ページにtrial controlが見えてもunknownとして扱う。

access mode:

```text
owned   = 購入済みfull reader「読む」
quota   = 「まる読み10分」の強い固有signal
paid    = 通常の「試し読み」のみ
unknown = reader入口なし、特殊商品、unsupported subscription、曖昧状態
```

購入済み商品の実サイトcontrol `data-action-label="read_purchased"` も
`owned` として分類する。初回full Discoveryでは商品URLをWeb targetへ保存し、
BookWalker Policyはそのsourceを `direct` candidateとして選び、quotaを消費しない。

優先順位:

```text
owned > quota > paid > unknown
```

`subscription_reading` actionだけではquotaとしない。
`read_maruyomi` またはvisible textの「まる読み」+「10分」等を必要とする。

BOOK☆WALKER公式仕様では、まる読み10分は1日合計10分、AM5:00 JST resetで、
当日の10分終了後は対象作品でも通常の試し読み表示へ変わる。そのため:

- existing ownedはquota/paid/unknown観測だけでdowngradeしない
- existing quotaはpaid/unknown観測だけでdowngradeしない
- paid/unknownからquotaへのupgradeは許可
- ownedへのupgradeは許可

### 20.3 BookWalker incremental

genericなknown-source 2件停止は使わない。

newest側から:

1. new sourceを確認して継続
2. existing paid / unknownを再確認して継続
3. run開始前からquota / ownedだった既知sourceを1件確認したらstable boundaryとして停止
4. 今回paid -> quotaへupgradeしたsource自身では停止しない
5. stable boundaryがなければseries末尾まで走査

fullはseries全体と各商品詳細を確認し、clean exhaustion時だけmissing sourceを
unavailableにできる。

### 20.4 BookWalker local quota policy

実site quotaは1日合計10分だが、初期Batchでは時間残量を最適化しない。

local safety policy:

```text
window   = 05:00 JST ～ 翌05:00 JST
capacity = 1 quota book
scope    = BookWalker site-wide
```

quota attemptはreader open前に `quota_started_at` を記録し、crawl失敗でも
同window内ではrefund / automatic retryしない。翌05:00以降に再試行する。

BookWalkerではManga ONEのようなsource単位grantを仮定せず、
`access_granted_until` をdirect判定へ使わない。初期仕様ではNULLのままとする。
Batch Executorはgrantなしquota policyを許容し、`quota_started_at`のみをreader entry前に保存する。

manual browserや別clientでの10分消費はCatalogから観測できない。

Catalog上の誤ったquota予約を明示的に戻す運用には
`scripts/restore_bookwalker_quota.py`を使う。既定はdry-runで、failedなquota
`CrawlRun`を`--crawl-run-id`で指定して確認し、`--apply`時だけ自動backup後に
`quota_started_at` / `access_granted_until`をNULL化する。CrawlRun、Item status、
access mode、Artifactは変更しない。これはlocal reservationの修復であり、
BookWalkerサーバー側で既に消費された10分をrefundするものではない。通常のBatch
Executorは引き続き同一window内のautomatic refund/retryを行わない。

### 20.4.1 Series-list live smoke and first-volume inference

2026-09-18にshared Crawler Chromeで`https://bookwalker.jp/series/317089/list/`を実サイトで確認し、
`mode: full`、`observed: 11`、`new: 11`、`known: 0`、`complete: True`、
`stopped_reason: exhausted`まで成功した。現行DOMでは`ul.m-tile-list`と
`li.m-tile`が使われ、確認時点でpagination controlは表示されなかった。確認範囲は
このseriesの現行DOMと各product detailのmetadata/control取得であり、別のpagination
variantまでlive確認済みとは扱わない。

series listingのproduct titleとseries titleを正規化して比較し、同一タイトルの無印normal
productが一意で、listing内にexplicit order `>= 2` のnormal productが存在する場合だけ、
無印productを第1巻（`order_key="1"`）へ補正する。後続巻がない単巻series、special product、
複数の無印候補、listing title欠落時は補正しない。比較にはWatchlistの`target.label`を使わない。
series pageの表示見出しにある`『...』の電子書籍一覧` wrapperと、確認済みのBookWalker表示用suffix
`（電撃文庫）` / `(ライトノベル)`はseries title側だけから除去する。括弧を一律に除去せず、
商品title側の意味のある括弧を変更しない。
このseries-level evidenceはproduct detailを全件先読みせず、既存のlisting収集後・detail観測前
に計算する。full Discoveryの再実行時には既存itemのorder metadataもupsertで更新される。

### 20.5 strict reader entry

`auto` は現行のreader candidate score/fallbackを維持する。

strict `direct` / `quota` entryは実装済みである。strategyはrun stateに保存され、
product page上のmain action scopeだけをbounded waitで観測する。

Batch用:

```text
quota
  まる読み10分の強い固有controlだけclick
  trial / owned / 読み放題へfallback禁止

direct
  初期実装では購入済みfull reader「読む」だけclick
  trial / maruyomi / 読み放題へfallback禁止
```

strategyに一致するcontrolが0件、複数で曖昧、状態不明ならclick前にfailする。
trial readerへfallbackしてpartial contentを正常END / completed扱いする事故を
防ぐことを最優先とする。

`data-uuid`があるcontrolはcurrent product UUIDに一致するものだけを採用する。strictの
candidateが1件のときだけ、`target="_blank"`を除去して既存Pageからclickし、URL changeを
確認する。viewer URLから始まるstrict runはentry条件を確認できないためfailする。

quotaのlive clickによる実quota消費は未実施である。

BookWalkerのBatch quotaでは、session切れ後のlogin form検出とauto-login分岐を実装済みである。
login成功後に対象viewerへ直接遷移することを前提に、商品ページへ戻る再click処理は持たない。
synthetic browser testでlogin redirect → form submit → viewer、credential未設定、login form残存時の
fail-safeを確認する。実サイトでのquota消費を伴うauto-login live verificationは今回も実施していない。

### 20.6 初期非対象

- 10分残量を秒単位で計測して複数冊を詰め込む最適化
- 10分切れで途中停止した巻を翌日に同じrunへresume
- 読み放題MAX等を自動crawl対象として扱うこと
- BookWalker全作品・全まる読み対象の自動探索

このnoteにはpassword、Cookie、storage state、session secretを記録しない。

### Phase 3 generic access-resource contract

### 20.7 JPEG delivery comparison probe (2026-09-30)

Diagnostic-only probe added at scripts/probe_bookwalker_jpeg_delivery.py.
It reuses the existing BookWalker product-to-viewer entry, access strategy,
render wait, page advance and native draw trace. It does not call production
capture_page() and does not change production route patterns or response
filter. It records broad BookWalker response metadata, bounded body magic
inspection, JPEG metadata, native source constructors, and cumulative
JPEG/native matching. Query values are redacted and JPEG bodies are not saved.

Live run results with the shared Crawler Chrome and max-pages 8:

- trial / auto: 8 pages, 233 BookWalker responses, 72 JPEG bodies. 22 JPEGs
  came from viewer-epubs-trial.bookwalker.jp; all 22 matched current route
  patterns and current _is_original_response(). The other 50 were unrelated
  c.bookwalker.jp or rimg.bookwalker.jp assets. Native draw parts were all
  ImageBitmap (16 parts). All 8 pages classified
  JPEG_EXACT_MATCH_CURRENT_FILTER. Current-route JPEGs were image/jpeg,
  estimated quality 90, 4:2:0, non-progressive marker absent.

- purchased / direct: 8 pages, 305 BookWalker responses, 102 JPEG bodies
  (101 unique SHA-256). 24 JPEGs came from bw-bv-epubs.bookwalker.jp; all 24
  matched current route patterns and current _is_original_response(). The
  other 77 were unrelated c.bookwalker.jp or rimg.bookwalker.jp assets.
  Native draw parts were all HTMLCanvasElement (13 parts). No page had an
  exact current-filter match: 1 JPEG_DIMENSION_MISMATCH and 7
  JPEG_SIGNATURE_MISMATCH. Current-route JPEGs were image/jpeg,
  estimated quality 90, 4:4:4, non-progressive marker absent. Candidate
  dimensions included 960x1280 and 1448x2048; native dimensions included
  960x1280 and 1443x2048.

The result is inconsistent with A (purchased JPEG absent), B (purchased JPEG
outside current route patterns), and C (purchased JPEG rejected by current
response filter). It is consistent with D/E: purchased JPEGs are visible to
the current filter, but native source changes from ImageBitmap to
HTMLCanvasElement and the bounded JPEG/native comparison does not produce a
unique exact match. This is diagnostic evidence only; production fallback
and filter behavior were not changed.

### 20.8 Purchased JPEG transformation probe (2026-09-30)

The diagnostic-only transformation probe is
scripts/probe_bookwalker_purchased_transform.py. It accepts a purchased
product URL, uses the existing adapter entry/navigation and native draw
selection, and does not call production capture_page() or change production
JPEG/PNG selection. It saves raw JPEG candidates, native source crop PNGs,
mutable source-canvas snapshots, ImageBitmap snapshots, diff images, bounded
canvas-operation traces, and redacted JPEG-marker metadata.

The final live check used the purchased URL with access_strategy=direct,
max-pages 1, and two reloads in the shared Crawler Chrome session. Both runs
observed page 23/314 and two spread parts.

- The selected raw JPEG candidates were each an exact decoded-pixel match to
  their corresponding ImageBitmap snapshot. This confirms the network JPEG
  is the ImageBitmap input for the observed parts.
- The purchased source canvas was an HTMLCanvasElement of 960x1280. It
  received two complete 32x32 tile permutations from ImageBitmap sources:
  1200 operations, 1200 unique source tiles, 1200 unique destination tiles,
  and 1199 moved tiles for each visible part.
- The source canvas was then drawn to the renderer canvas with
  source-over, identity transform, and filter none. No putImageData or
  getImageData operation was observed on the large source/renderer canvases.
  fillRect operations were limited to renderer/background or edge rectangles,
  not source-canvas image content.
- Direct raw/native decoded-pixel comparison was not equal. Part 1 had a
  30.6635 percent differing-pixel ratio, PSNR 11.4947 dB, and SSIM
  0.01685. Part 2 had a 28.0673 percent differing-pixel ratio, PSNR
  12.0109 dB, and SSIM 0.01699. Both diff bounding boxes covered the full
  960x1280 image, and exhaustive same-dimension crop offsets did not match.
- The raw JPEGs were quality 90, 4:4:4, and contained only a JFIF APP0
  marker among the inspected metadata markers. No EXIF, XMP, or COM marker
  was observed. Printable marker facts are stored only as boolean/count/hash
  metadata.
- Reload comparison was RAW_SAME_NATIVE_SAME for both spread parts. This
  supports deterministic behavior in the same account/session; it does not
  prove that no user-specific deterministic data exists.

Current classification for the observed purchased parts is
TILE_REARRANGEMENT. The evidence confirms a tile reconstruction step
between the network JPEG/ImageBitmap and the source HTMLCanvasElement. It
does not establish purchaser watermarking, randomized session modification,
or the server-side reason for the tile permutation. Generated artifacts are
local diagnostic output and are not repository fixtures.

### 20.9 Purchased part mapping and JPEG MCU readiness (2026-09-30)

The transformation probe now joins each visible part by object identity and
operation order rather than by part index or dimensions. For an
HTMLCanvasElement source, the init script records the underlying canvasId in
addition to the sourceId. The probe records the renderer canvas id, renderer
draw operation index, source canvas id, selected permutation group, ImageBitmap
source id/snapshot hash, exact raw-JPEG match count, canonical mapping hash,
and reload mapping comparison.

The final two-reload check for the purchased URL observed the following
part-local chains on page 23/314:

- Part 1: renderer canvas 3, draw operation 1203, source canvas 4,
  ImageBitmap source 2, tile operations 3-1202, and mapping hash
  7aefb09c0c62c4f155f38a2e8c5682f58dd200678a1e193f4c35baa625733902.
- Part 2: renderer canvas 3, draw operation 2410, source canvas 4,
  ImageBitmap source 5, tile operations 1210-2409, and mapping hash
  7eb3352ba679b398b0d8d1a5b3b28571f34f165a8b70545a58d89266aec6eecd.

Each selected group has 1200 operations, 1200 expected tiles, 1200 unique
source tiles, 1200 unique destination tiles, 1199 moved tiles, and a complete
bijection. A later ImageBitmap source 7 group is a partial prefetch/transition
group after the next clear boundary and is not assigned to either visible
part. A same-window multi-source case remains fail-safe and is reported as
MULTI_SOURCE_PERMUTATION / PART_MAPPING_AMBIGUOUS rather than being collapsed.

The selected raw JPEG is the unique exact decoded-pixel match for each
selected ImageBitmap. JPEG SOF sampling factors give an 8x8 MCU for the
observed 4:4:4 images; all source and destination tile rectangles are both
edge-aware and strictly MCU aligned. The part-local trace has identity
transform, source-over, filter none, no source-canvas content writes, and no
renderer writes classified as image-content modification. clearRect between
parts is recorded as source-canvas initialization; renderer fillRect calls are
classified as background or thin edge operations.

Both reloads report RAW_SAME_NATIVE_SAME and MAPPING_SAME for both parts.
The final readiness is LOSSLESS_JPEG_REARRANGEMENT_READY and the part
classification is TILE_REARRANGEMENT. The complete part mapping is written to
page-level part-mappings.json and the run-level aggregation to
part_mapping_summary.json. This remains diagnostic-only; no production
capture selection, JPEG/PNG output choice, or Core/DB/packaging behavior is
changed by the probe itself.

### 20.10 Lossless JPEG coefficient rearrangement PoC (2026-09-30)

The diagnostic-only PoC is
`scripts/poc_bookwalker_lossless_jpeg_rearrange.py`. It consumes only the
local output of the transformation probe and requires the complete proven
part evidence, strict MCU alignment, equal source/destination dimensions,
and a uniform complete tile bijection. It uses the installed `jpeglib`
coefficient API (`read_dct` / `write_dct`) and never uses Pillow to write the
reconstructed JPEG. Every component DCT block is copied through a full
temporary coefficient-array copy; no coefficient, including DC values, is
re-quantized or recomputed.

The local PoC was run for both proven purchased parts from
`output/probe-bookwalker-transform-final-part-mapping/run-a/page-0001/`.
Both inputs are baseline SOF0, 3-component 4:4:4 JPEGs at 960x1280 with
8x8 MCUs and 32x32 tiles (1200 tiles / 19200 MCUs). Both parts produced
`LOSSLESS_JPEG_RECONSTRUCTION_PROVEN`:

- coefficient validation: 3,686,400 coefficient values checked per part,
  zero mismatched blocks and zero mismatched coefficient values;
- dimensions, component count, sampling factors, and quantization tables:
  exact;
- Pillow RGB comparison against the native PNG: exact, zero differing
  pixels, RMSE 0, SSIM 1;
- browser `createImageBitmap` plus 1:1 canvas `getImageData` comparison:
  exact RGBA, zero differing pixels, 960x1280.

The output JPEG byte stream is not expected to equal the scrambled input:
entropy coding and marker layout can differ, and `jpeglib/libjpeg` normalized
component IDs from 1/2/3 to 0/1/2 while preserving component order. The
quantized DCT coefficients and quantization tables are the relevant lossless
proof contract. The output also records marker type, length, printable-string
presence, and hashes only; marker string contents are not emitted.

Verified:

- a coefficient backend is available in the current `.venv`;
- identity, two-tile swap, and four-tile cycle synthetic cases reconstruct
  without in-place permutation corruption or coefficient changes;
- duplicate, gap, out-of-bounds, non-MCU, mixed/partial tile, dimension
  mismatch, and progressive JPEG inputs fail closed without output;
- actual local purchased part 1 and part 2 reconstruction is proven at both
  coefficient and browser pixel levels.

Unsupported / fail-closed:

- progressive or non-SOF0 JPEGs, non-3-component layouts, non-4:4:4
  sampling, partial edge MCU/tile layouts, incomplete mappings, and any
  unproven probe evidence;
- broader JPEG layouts and artifact selection remain unsupported; the Phase P1
  production integration below keeps the existing native PNG output and all
  Core/DB/packaging behavior unchanged;
- the PoC does not establish that every purchased BookWalker JPEG uses this
  layout or that a different account/session has the same mapping.

Broader JPEG layouts, normalized marker output, and artifact selection remain
separate future work. The generated reconstructed JPEGs and summaries are
local diagnostic output and are not repository fixtures.

BookWalker exposes no additional named access resource in the Phase 3 Policy
contract. Explicit resource planning therefore fails closed for unsupported
resource names; normal direct/quota planning remains unchanged.

### 20.11 Phase P1 production shadow integration

The current adapter keeps the existing original JPEG path first for trial
pages, trial covers, and purchased covers. A unique full-resolution exact
candidate is returned byte-for-byte, and the purchased lossless helper is not
called after that path succeeds. When the original path fails, native source
PNG remains the returned output.

In `native` mode only, the production trace uses a monotonic absolute
operation counter and does not retain a global operations list. Each source
canvas has a bounded active segment beginning at a verified full-canvas
`clearRect`; the segment retains only tile metadata, source identity, geometry,
and bounded unsafe-operation counters. A renderer draw from an
`HTMLCanvasElement` freezes the current segment into a bounded completed
mapping record. The record retains its renderer identity, clear/tile operation
indexes, tile records, unsafe flags, and overflow state. Completed mappings are
bounded to 12 records and 20,000 retained tile records; active segments are
bounded to eight canvases and each segment to 16,384 tile records. Eviction is
not reconstructed later.

Post-render prefetch operations therefore do not invalidate an already frozen
mapping. Repeated passes on the same canvas are separated by their full-clear
boundaries. Partial clears, unsafe writes, non-ImageBitmap sources, non-identity
drawing, duplicate tiles, gaps, out-of-bounds rectangles, and segment overflow
fail closed. A pure renderer destination scale is allowed when the source
rectangle is the complete source canvas and renderer geometry remains within
the target bounds; source crops and partial-edge source/target dimensions
remain unsupported.

For purchased responses, `site_adapters/bookwalker/purchased_mapping.py`
requires one proven renderer -> source `HTMLCanvasElement` -> one `ImageBitmap`
chain and a unique full-resolution browser pixel match between the raw JPEG
candidate and retained `ImageBitmap`. The synchronous
`site_adapters/bookwalker/lossless_jpeg.py` helper runs inside
`asyncio.to_thread()`, uses internal temporary files for the jpeglib DCT API,
and returns dimensions, tile/MCU geometry, mapping SHA-256, and coefficient
validation. It supports only baseline SOF0, three-component 4:4:4, equal
dimensions, complete uniform strict-MCU bijections, and no partial edge MCU.
Read-back must report zero coefficient mismatches and unchanged quantization
tables.

Purchased candidate matching is bounded in this order: exact
`mapping.source_dimensions`, the existing 64x64 browser signature, then
full-resolution `ImageBitmap` exact comparison. The retained ImageBitmap uses
the same deterministic hash algorithm as `image_signature()`; no new hash
contract is introduced. Zero signature matches are unavailable, one full-size
exact match is accepted, and multiple full-size exact matches remain
ambiguous. The per-part shadow metadata records
`candidate_count_total`, `candidate_count_dimension_match`,
`candidate_count_signature_match`, `candidate_count_full_exact`, and
`full_resolution_comparison_count`; candidate URLs, hashes, and full trace
contents are not emitted as generic debug metadata.

Phase P1 performs a second full-resolution browser pixel comparison against
the current native PNG. Debug metadata records per-part mapping proof, raw JPEG
exactness, JPEG support, strict MCU alignment, coefficient exactness, and
native-pixel exactness, with all-or-none spread readiness. The reconstructed
JPEG is not returned, written to the artifact directory, or added to the
generic Core/DB/packaging contract. Unsupported, ambiguous, segment-overflow,
backend, coefficient, and browser-comparison failures preserve native PNG
fallback. The current completed-segment authority is production-only; the old
operations-array shape remains a bounded unit/probe compatibility fallback.

Trace source objects and snapshot canvases are bounded and cleared at the end
of each capture window. `BOOKWALKER_CAPTURE_MODE=canvas` bypasses original,
native, and lossless shadow processing and preserves the rendered-canvas
fallback.

### 20.12 Phase P1 live shadow investigation (2026-09-30)

This investigation changed only
`scripts/probe_bookwalker_purchased_transform.py` and its unit tests. Production
BookWalker capture, purchased matching, and the 5,000-operation production
trace limit were not changed.

The diagnostic trace now uses a probe-only rolling operation window of 10,000
records. Each retained operation has a monotonic absolute index; the trace
also records the first overflow index, observed count, retained index range,
dropped count, operation categories after overflow, and whether the selected
renderer/mapping window was fully retained. ImageBitmap snapshots are bounded
to eight snapshots and 8 MiB per data URL, HTMLCanvasElement pixel snapshots
are not retained, and source/canvas inventories have explicit caps. The
`--metadata-only` option keeps decoded comparisons in memory but writes no
JPEG/PNG artifacts. Tile groups are segmented at `clearRect` boundaries so a
second render pass is not incorrectly combined with the current mapping.

The shared-CDP live run for the requested purchased URL completed 20 pages in
transform-only (`BOOKWALKER_CAPTURE_MODE=canvas`) mode. The visible bitmap was
1904x944. Diagnostic operation counts ranged from 3,627 to 9,656 on content
pages; the pages corresponding to counters 5/314, 6/314, 8/314, 11/314, and
37/314 exceeded the unchanged production limit of 5,000. The 10,000-record
diagnostic trace did not overflow in this run. The largest observed page had
9,616 `drawImage`, 8 `clearRect`, and 32 `fillRect` operations. This is
evidence that the production 5,000 limit can be reached before the viewer
finishes a page, but it does not by itself establish that every mapping on an
overflowed page is invalid.

The same run showed two distinct mapping cases. On 960x1280 pages, a
clear-bounded group contains 1,200 32x32 tile draws and is a complete
bijection; the previous aggregate view counted two render passes together as
2,400 operations and therefore reported an incomplete mapping. On a large
spread, the observed groups contain 2,944 draws but are not strict lossless
permutations: one source/target pair is 1448x2048 to 1443x2048 with a partial
horizontal edge, and another is 2048x1456 to 2048x1453 with a partial vertical
edge. Those dimension/edge mismatches remain fail-closed and must not be
accepted by the current coefficient-level JPEG rearrangement helper.

The native metadata run reached p.1 and p.2 before the existing native
source-crop retention made the long run impractical. On p.1 the viewer bitmap
was 1904x944, the selected native source was 722x1024, and the bounded JPEG
pool contained an exact-route candidate at 1448x2048. There were 84 unique
JPEG candidates (7 in the current filter), but zero candidate dimension
matches and zero signature matches for the 722x1024 native part. The selected
renderer draw was at operation 2963 after the latest source-canvas clear at
2956; the source canvas was 722x1024. Its source rectangle was 721.5x1024 and
its destination was 666x942, with identity transform, alpha 1, `source-over`,
and `filter=none`. This is renderer scaling/cropping evidence, not a proof of
pixel-preserving equal-dimension drawing. The source canvas also received a
1443x2048 ImageBitmap, while the route JPEG candidate was 1448x2048.

Likely causes are therefore separate: (1) p.1's current original-JPEG
diagnostic evidence is a native-dimension mismatch, so the existing bounded
candidate matcher cannot prove the 1448x2048 JPEG from the 722x1024 native
part; (2) several pages exceed the production trace bound; (3) repeated tile
passes must be separated by the latest clear boundary; and (4) some large
spreads have genuine source/target dimension and partial-edge differences.
The probe intentionally does not call production `capture_page()`, so it does
not prove whether the production original-JPEG path was invoked or why p.1
changed from the earlier JPEG result. Production changes should first add the
same absolute-counter/segment evidence and verify the original-response
selection path, without relaxing dimension or partial-edge fail-closed rules.

Live output was metadata-only in a temporary directory; no repository image
fixtures, cookies, tokens, or credentials were saved. A full 20-page native
run remains unresolved because the existing native source-crop observation can
retain very large canvas snapshots; this is a probe resource limitation, not
a production behavior change.

### 20.13 Purchased p.1 original-JPEG A/B investigation (2026-09-30)

This investigation uses
`scripts/diagnose_bookwalker_original_jpeg_ab.py`. The script calls the
production `BookWalkerAdapter` methods, wraps selection/materialization/matcher
calls read-only, and adds a bounded independent draw trace so older revisions
can be compared with the current trace fields. It resets the persisted viewer
position to p.1 before each observation. It writes only redacted metadata;
candidate query strings, cookies, credentials, and image bodies are not saved.
Production `adapter.py`, `original_capture.py`, and `native_capture.py` were
not changed by this investigation.

#### Reproduced facts

- The latest `main` authority for this run was `ae3f7df` (`Add BookWalker
  original JPEG A/B diagnostic`). Production CLI was run with the requested
  product URL, `direct`, `BOOKWALKER_CAPTURE_MODE=native`, the shared Crawler
  Chrome/CDP/profile, and `--max-pages 1`. The intentional stop raises the
  existing `MaxPagesExceededError` after saving p.1.
- Six fresh-page current-main CLI runs all saved PNG p.1 artifacts. Five
  returned `native_png` at `722x1024`, 1,383,320 bytes, SHA-256
  `b3a388bf46c2aee65291d7f568f4677033afdbd74cc8ebfcf74db3b3c5c5d3ef`.
  One run used the existing rendered-canvas fallback and saved `666x944` PNG;
  it was still p.1 (`1/314`). This is a separate initial-frame native-capture
  availability race, not a JPEG match.
- On successful native p.1 capture, the visible renderer canvas is
  `1904x944`. The selected native call is one renderer draw from an
  `HTMLCanvasElement` of `722x1024`; `sourceRect=721.5x1024`,
  `destination=666x942`, identity transform, alpha 1, `source-over`, and
  `filter=none`. The materialized native PNG is `722x1024`.
- The independent trace shows the same chain in every compared revision:
  `ImageBitmap 1443x2048 -> HTMLCanvasElement 722x1024 -> renderer`. The
  intermediate canvas receives the full ImageBitmap with destination
  `722x1024`; the renderer then crops/scales that canvas into `666x942`.
- The current production original matcher receives native dimensions
  `722x1024`. Its p.1 stages are: candidate pool `7`, dimension matches `0`,
  signature matches `0`, unique matches `0`, returned JPEG `none`. The
  purchased shadow has the same candidate pool and also stops at dimension
  matching.
- The redacted p.1 JPEG candidate pool was identical across all compared
  revisions: 7 candidates, all from `bw-bv-epubs.bookwalker.jp`, with matching
  paths, sequences, dimensions, byte sizes, and SHA-256 values. The relevant
  full-resolution candidates included `p-cover.xhtml` at `1443x2048`,
  567,074 bytes, SHA-256
  `4618b01fd0b726f88e1632d0c27f8888202fffcb26d68d45971b90ad662ba918`, and
  `p-fmatter-001.xhtml` at `1448x2048`, 656,033 bytes, SHA-256
  `4dbc98638f1d8b5fcbbc2f59a4e7761a5b9af48142efc83e675b87c7229e061f`.

#### Revision comparison

| revision | production p.1 result in current viewer state | native source | matcher split |
| --- | --- | --- | --- |
| `c118464` | PNG in the new run | `HTMLCanvasElement 722x1024` | `0` dimension / `0` signature |
| `8c84b5a` | PNG | `HTMLCanvasElement 722x1024` | `0` dimension / `0` signature |
| `a1bd5d9` | PNG | `HTMLCanvasElement 722x1024` | `0` dimension / `0` signature |
| `6331eed` | PNG | `HTMLCanvasElement 722x1024` | `0` dimension / `0` signature |
| latest `main` (`ae3f7df`) | PNG | `HTMLCanvasElement 722x1024` | `0` dimension / `0` signature |

The selected native call list, renderer geometry, candidate bytes, and
matcher decision were stable across three diagnostic p.1 observations for
each revision. The current CLI repeat additionally exposed one native-capture
fallback among six runs; the successful native observations remained the same.

Static diff from `8c84b5a` to latest `main` found no change in
`native_capture.py`. The original matcher in `adapter.py` remains the same
dimension-plus-64x64-signature authority. `a1bd5d9` adds purchased shadow
diagnostics after the ordinary matcher fails, and `6331eed` bounds that shadow
matching; neither changes a successful ordinary JPEG return or native source
selection. `3f4a564` adds the separate transform probe only.

#### Root cause

This is not a Phase P1 code regression from `8c84b5a` to latest `main`:
`8c84b5a` itself produces PNG for p.1 under the current viewer state, and the
same intermediate-canvas chain is present there. The current production path
selects the final visible native draw source, not the upstream full-resolution
ImageBitmap. The existing matcher therefore correctly fails closed at the
dimension stage (`722x1024` versus the full-resolution JPEG candidates such as
`1443x2048`/`1448x2048`). No unconditional dimension relaxation is justified.

The earlier live note for `c118464` reported an original-JPEG first artifact
at `1/349`. Re-running that same code against the current target now observes
`1/314`, the intermediate-canvas chain, and PNG. The historical note does not
retain the exact URL or JPEG body, so the old byte-level JPEG result cannot be
replayed or compared directly. The evidence supports a viewer/content
delivery change between the historical run and the current run, rather than a
production source-selection change in the Phase P1 commits.

#### Regression classification

Primary classification: **VIEWER_BEHAVIOR_CHANGE**. The same pre-P1 code
(`c118464`) is PNG under the current viewer response/render chain, while the
historical live note recorded a JPEG first artifact. Secondary operational
finding: **INITIAL_FRAME_RACE** is present for native availability only (one
of six current CLI attempts used the rendered-canvas PNG fallback); it does
not explain the successful native `722x1024` versus JPEG-candidate mismatch.

This is not `CONFIRMED_PHASE_P1_REGRESSION`: `8c84b5a` is PNG in the current
environment. It is also not evidence that the current JPEG candidate bytes
changed; those bytes were identical across the revision A/B runs.

#### Unresolved points

- The exact historical `c118464` live-run URL, response set, and original JPEG
  body were not stored, so the historical `1/349` artifact cannot be matched
  byte-for-byte against today’s `1/314` response set.
- The server/viewer reason for the change from the historical full-resolution
  JPEG-matching state to the current intermediate-canvas state is not exposed
  by the repository or the redacted browser observations.
- The one current native-capture fallback should be investigated separately if
  native-path stability becomes a requirement; it is not a reason to loosen
  original-JPEG matching.

#### Recommended minimal fix (not implemented)

Keep the capture priority unchanged:

```text
verified original JPEG
    -> verified lossless reconstruction
    -> native PNG
    -> rendered canvas
```

If a future production fix is needed, add a purchased-viewer-specific
original-JPEG authority that can move from the selected intermediate canvas
to its upstream `ImageBitmap` only after proving, for the exact visible page,
candidate identity, pixel equality, source-to-canvas transformation, and
page geometry. A full-resolution candidate must not be returned merely because
its dimensions are related to `722x1024`; otherwise the current fail-closed
PNG path remains correct. The new proof must run after the existing ordinary
original-JPEG path, so verified trial pages, trial covers, and purchased
direct-original covers keep their existing JPEG path unchanged. Unsupported,
ambiguous, or geometry-mismatched cases must continue to native PNG; no
lossless reconstruction should be used as a substitute for an unverified
original JPEG.

### 20.14 Phase P1 completed-segment production trace (2026-10-01)

Production now uses the clear-bounded completed-segment trace described in
20.11. The previous global 5,000-operation list and global overflow rejection
are no longer production authorities. A monotonic `nextOperationIndex` is
assigned to observed operations; each source canvas keeps a bounded active
segment after its latest exact full-canvas `clearRect`, and an
`HTMLCanvasElement` renderer draw freezes that segment into a completed
mapping. The selected native draw carries `mappingId`,
`traceOperationIndex`, and `sourceCanvasId`, so Python selects the exact frozen
record rather than inferring a mapping from dimensions or a later prefetch.

The active-segment bound is eight canvases and 16,384 tile records per segment.
Completed mappings are bounded to 12 records and 20,000 retained tile records;
evicted records are unavailable and are never reconstructed. Unsafe writes
(`putImageData`, partial clear, content-changing fill, non-ImageBitmap draw,
transform changes, alpha/composite/filter changes) are summarized in counters
and types, then rejected. A pure renderer destination scale is accepted only
for a full source rectangle, identity/source-over/alpha-1/filter-none, positive
destination dimensions, and an in-bounds renderer target. Crop geometry,
partial-edge source/target dimensions, and unsupported p.1 intermediate-canvas
geometry remain native-PNG fallback cases.

The Phase P1 order is unchanged: the existing byte-preserving original JPEG
matcher runs first; only when it fails does the purchased evaluation run. Phase
P1 live verification succeeded for ordinary 960x1280 pages: 1200/1200 tiles,
completed mapping proven, one exact raw JPEG candidate, coefficient mismatch
0, equal quantization tables, browser full-resolution pixel exactness, and
successful two-part spread validation. p.1 and large/partial-edge geometry
continue to fail closed to PNG.

Phase P2 adds opt-in reconstructed JPEG output through the BookWalker-local
`BOOKWALKER_LOSSLESS_JPEG_OUTPUT` switch. The default is OFF, preserving the
P1 shadow-only behavior. When ON, the priority is:

```text
verified original JPEG
    -> verified lossless reconstructed JPEG
    -> native PNG
    -> rendered canvas PNG
```

The reconstructed bytes are returned directly from `reconstruct_lossless_jpeg`
as `.jpg`; they are not called original JPEG and are not re-encoded in Pillow.
The output gate requires the completed-segment proof, no overflow/eviction,
unique full-resolution raw match, strict supported JPEG layout, exact
coefficients and quantization tables, browser pixel exactness, and matching
native dimensions. Spread output is all-or-none: if one part is not ready,
all parts remain native PNG and any temporary reconstructed result is discarded.
Trial original JPEG, trial cover, and purchased direct-original JPEG remain
first-priority byte-preserving paths and do not invoke reconstruction. p.1,
crop, partial-edge, overflow, unavailable mapping, and other unsupported
geometry remain PNG fallback cases. `BOOKWALKER_CAPTURE_MODE=canvas` bypasses
the entire native/original/lossless path and continues to use rendered-canvas
fallback.

P2 debug metadata keeps the compatibility key `lossless_shadow` and adds
`output_enabled` and `output_used`; `bookwalker_capture.returned_path` is
`original_jpeg`, `reconstructed_jpeg`, `native_png`, or `rendered_canvas`.
Reconstructed bytes, base64, and raw candidates are never stored in debug or
manifest metadata.

### 20.15 Phase P2 live verification (2026-10-01)

Using the shared Crawler Chrome/CDP session, the target purchased work was
crawled with `BOOKWALKER_CAPTURE_MODE=native`,
`BOOKWALKER_LOSSLESS_JPEG_OUTPUT=1`, `direct`, and `--max-pages 20` into a
new output directory. All 20 saved artifacts were `.jpg` with
`returned_path=reconstructed_jpeg`, `spread_ready=true`,
`output_enabled=true`, and `output_used=true`. The ordinary 960x1280 parts
reported 1200/1200 tiles, completed-segment mapping provenance, one exact raw
JPEG match, coefficient mismatch 0, equal quantization tables, and browser
pixel comparison `differing_pixel_count=0`, `max_channel_difference=0`.

A separate switch-OFF run produced native PNG artifacts. Two page/part
identities overlapped between the runs and were compared after browser decode:

| page/part | reconstructed JPEG | native PNG | byte reduction | pixel diff |
| --- | ---: | ---: | ---: | ---: |
| `41/314` part 1 | 254,718 bytes | 596,941 bytes | 57.33% | 0 pixels |
| `41/314` part 2 | 282,138 bytes | 644,745 bytes | 56.24% | 0 pixels |

Both compared artifacts were 960x1280 and had maximum channel difference 0.
The CLI intentionally raised the existing `MaxPagesExceededError` after the
requested page limit; artifacts and manifests were saved before that terminal
guard. The switch-OFF run retained the P1 native PNG behavior. No repository
image fixture, cookie, token, credential, JPEG byte stream, or base64 payload
was added.

### 20.16 Phase P3 default output and performance instrumentation (2026-10-01)

Phase P3 promotes verified lossless reconstructed JPEG output to the production
default. The BookWalker-local switch is now enabled when
`BOOKWALKER_LOSSLESS_JPEG_OUTPUT` is unset. Explicit `1`, `true`, `yes`, and
`on` also enable output; explicit `0`, `false`, `no`, and `off` are the kill
switch and restore native PNG for purchased reconstruction. Invalid explicit
values fail fast in the adapter. The existing original-JPEG matcher remains
first priority, including trial pages, trial covers, and purchased
direct-original covers; those paths return the original candidate bytes without
calling reconstruction.

The P2 proof gate is unchanged: completed-segment mapping must be proven and
complete, with no overflow or eviction, one unique exact raw JPEG candidate,
supported strict-MCU JPEG structure, exact coefficients and quantization
tables, matching native dimensions, and browser full-resolution pixel exactness.
Spread output remains all-or-none. p.1 geometry, crop, partial MCU edges,
unsupported JPEG layouts, incomplete mappings, and other unsafe cases remain
native PNG fallback. Canvas mode bypasses purchased reconstruction and keeps
the rendered-canvas fallback.

P3 adds observability-only timing metadata at capture, part, evaluation, and
lossless reconstruction levels. It records mapping analysis, ImageBitmap and
candidate signatures, raw and final browser comparisons, native materialization,
coefficient array copy/rearrangement, DCT reads/writes/readback, coefficient
verification, and total elapsed time. Timing does not affect proof, retry,
timeout, navigation, or output selection. JPEG bytes are not stored in debug or
manifest metadata; only the reconstructed size and SHA-256 fingerprint remain
available for diagnosis.

The P3 live benchmark used the shared Chrome/CDP session with the target URL,
default environment (no `BOOKWALKER_LOSSLESS_JPEG_OUTPUT` override), native
capture, direct access, a fresh output directory, and `--max-pages 20`. The
existing terminal `MaxPagesExceededError` was raised after the 20 artifacts and
manifest had been saved. All 20 artifacts were 960x1280 reconstructed JPEGs,
with `returned_path=reconstructed_jpeg`, `output_enabled=true`,
`output_used=true`, and browser pixel differences of zero. Every saved page was
a two-part spread, so this run has no single-part comparison.

Timing summary for the 20 successful pages / 40 successful parts follows. The
values are milliseconds; p90 uses the nearest observed sample.

| measurement | count | median | p90 | max |
| --- | ---: | ---: | ---: | ---: |
| evaluation total | 20 | 2472.13 | 4641.69 | 4835.17 |
| native materialization | 20 | 115.62 | 134.57 | 199.81 |
| mapping analysis | 40 | 52.36 | 62.05 | 86.30 |
| signatures (ImageBitmap + candidates) | 40 | 3.63 | 4.93 | 61.51 |
| raw full-resolution comparison | 40 | 60.28 | 68.70 | 98.96 |
| lossless reconstruction | 40 | 134.50 | 241.84 | 313.63 |
| source DCT read | 40 | 15.12 | 27.37 | 27.72 |
| coefficient array copy | 40 | 21.04 | 35.41 | 47.86 |
| coefficient rearrange | 40 | 4.82 | 7.34 | 10.76 |
| JPEG DCT write | 40 | 27.29 | 30.67 | 61.28 |
| output DCT readback | 40 | 13.46 | 17.31 | 25.32 |
| coefficient readback compare | 40 | 27.01 | 31.86 | 57.87 |
| final browser pixel comparison | 40 | 136.94 | 174.35 | 290.47 |

The two-part capture total was median 3329.85 ms, p90 5614.69 ms, and max
5721.48 ms. The coefficient rearrangement median was 3.81% of the per-part
lossless reconstruction `total_ms` (median of per-part ratios), so the image
reordering loop is not the main measured cost. By median, the requested cost
ranking is final browser pixel comparison (136.94 ms), raw full-resolution
candidate comparison (60.28 ms), combined source-DCT read plus JPEG write and
output-DCT readback (approximately 55.87 ms from the component medians), then
coefficient readback comparison (27.01 ms). These are observations only;
removing or weakening any proof step is deferred to P4.

P4 optimization candidates are therefore the repeated browser full-resolution
comparisons and DCT/file-I/O path, subject to preserving the raw match proof,
coefficient readback validation, and final browser pixel exactness. No such
optimization is included in P3.

The P3 timing table above used artifact rows directly. Because the Runner
copies the same spread-level capture metadata onto both part artifacts, its
`20 successful pages / 40 successful parts` labels were artifact-level counts,
not logical capture counts. The corrected P4-1 analysis below deduplicates by
logical page identity, part count, and identical capture timing metadata.

### 20.17 Phase P4-1 performance accounting (2026-10-01)

P4-1 adds observability only. It does not change the output priority, default
JPEG behavior, proof gate, full-resolution comparisons, coefficient readback,
retry, timeout, or reconstruction algorithm. The trace fetch is timed around
the existing `page.evaluate(() => window.__bookwalkerTransformTrace || null)`;
this wall-clock value includes browser-side object serialization and the
Playwright/CDP transfer into Python. Small bounded trace counts are recorded,
but the trace representation itself is unchanged.

The fresh default-ON live run used the shared Crawler Chrome/CDP session,
native capture, direct access, the target purchased URL, and `--max-pages 20`.
The existing `MaxPagesExceededError` occurred after artifacts and manifest
were saved. Corrected counts are:

```text
20 artifacts
10 logical captures
20 logical parts
10 two-part spreads
```

All 20 artifacts were reconstructed JPEGs for the ordinary 960x1280 pages,
with `returned_path=reconstructed_jpeg`, `output_enabled=true`,
`output_used=true`, and native browser pixel difference zero. The corrected
capture/part timing summary is below; values are milliseconds and p90 is the
nearest observed sample.

| measurement | count | median | p90 | max |
| --- | ---: | ---: | ---: | ---: |
| capture total | 10 | 3747.36 | 5934.02 | 7233.31 |
| lossless evaluation total | 10 | 2863.34 | 4356.70 | 5108.71 |
| trace fetch | 10 | 1757.11 | 3276.00 | 4171.84 |
| measured component total | 10 | 2860.39 | 4353.31 | 5106.08 |
| evaluation unaccounted | 10 | 3.61 | 4.85 | 5.18 |
| capture unaccounted | 10 | 70.40 | 82.60 | 166.17 |
| native materialization | 10 | 114.79 | 136.84 | 138.94 |
| original JPEG matching | 10 | 625.50 | 999.12 | 2600.13 |
| mapping analysis | 20 | 88.34 | 123.73 | 147.47 |
| signatures | 20 | 3.83 | 5.04 | 55.63 |
| raw full-resolution comparison | 20 | 65.76 | 106.56 | 174.85 |
| lossless reconstruction | 20 | 175.88 | 329.62 | 411.24 |
| final browser pixel comparison | 20 | 157.70 | 213.56 | 261.19 |

The reconstruction/file timing breakdown was:

| measurement | median | p90 | max |
| --- | ---: | ---: | ---: |
| source tempfile write | 1.21 | 1.67 | 2.32 |
| source DCT read | 18.45 | 26.46 | 70.42 |
| coefficient array copy | 24.32 | 31.55 | 38.68 |
| coefficient rearrange | 7.97 | 11.05 | 13.65 |
| JPEG DCT write | 35.98 | 49.68 | 74.95 |
| output JPEG file read | 9.04 | 35.12 | 78.26 |
| readback tempfile write | 0.95 | 1.12 | 1.45 |
| output DCT readback | 16.52 | 27.51 | 45.61 |
| coefficient readback compare | 34.80 | 45.64 | 64.37 |

The trace payload was typically three completed mappings and 3,600 completed
tile records. The observed rows were:

| completed mappings | completed tile records | captures | trace fetch range |
| ---: | ---: | ---: | ---: |
| 3 | 3,600 | 8 | 1552.44–1940.31 ms |
| 5 | 6,000 | 1 | 3276.00 ms |
| 7 | 8,400 | 1 | 4171.84 ms |

This small sample shows a clear directional relationship between retained
trace size and fetch time: the 3,600-tile rows were around 1.6–1.9 seconds,
while 6,000 and 8,400 tiles took 3.3 and 4.2 seconds. The evaluation gap is
now only 3.61 ms median after accounting for trace fetch; therefore trace
fetch is the explanation for the P3 unmeasured evaluation time and is the
dominant evaluation cost. It is also much heavier than final browser pixel
comparison (1757.11 ms versus 157.70 ms median). Coefficient rearrangement
remains small: 7.97 ms median and 4.91% median of per-part reconstruction
`total_ms`.

The largest measured stage medians were trace fetch (1757.11 ms), original
JPEG matching at capture level (625.50 ms), lossless reconstruction (175.88
ms), final browser pixel comparison (157.70 ms), and native materialization
(114.79 ms). Original matching is outside evaluation and is reported
separately; within evaluation, trace fetch is followed by lossless
reconstruction, final browser comparison, mapping analysis (88.34 ms), and
raw full-resolution comparison (65.76 ms).

P4-2 candidates, not implemented here:

- Return only the completed mapping record(s) referenced by the selected draw
  call from browser JavaScript, instead of transferring the entire transform
  trace. Preserve the same mapping provenance, overflow/eviction state, and
  fail-closed behavior.
- If that remains necessary, use compact numeric tile arrays for the selected
  mapping and reconstruct the existing mapping contract in Python; compare
  payload size and validation cost before adopting it.
- Keep full pixel exactness while investigating browser-side decode/hash or
  cached comparison strategies; a 64x64 signature cannot replace either full
  resolution proof.
- Keep output DCT reread, coefficient mismatch validation, and quantization
  table equality until a separate proof of equivalent writer guarantees is
  completed.

### 20.18 Phase P4-2 selected completed mapping transfer (2026-10-01)

P4-2 changes only the production transform-trace fetch. The browser still
retains the same bounded `activeSegments` and `completedMappings` stores with
the same active-segment and completed-mapping limits, eviction counters,
overflow metadata, unsafe-operation metadata, and `mappingId` assignment.
The adapter now passes the deduplicated exact `mappingId` values from the
selected native renderer draws to a BookWalker-local browser helper. The
helper filters `completedMappings` with `filter()` and returns every matching
record, never only the first match. It returns the selected records plus
integer summaries for retained completed/active trace size, dropped counts,
requested IDs, returned mappings/tiles, and missing IDs. The full trace is no
longer returned to Python on the production reconstruction path.

When a selected draw has no `mappingId`, the adapter does not fetch the full
trace or guess from dimensions, canvas size, tile count, or source geometry.
It fails closed and the existing all-or-none native-PNG spread fallback is
used. A missing or evicted requested ID is passed as an empty selected
mapping set to the existing Python validator, which keeps
`completed_mapping_evicted=true` and cannot reconstruct. Duplicate completed
records are all returned so the existing `len(matches) != 1` validator check
continues to reject ambiguity. Python remains responsible for renderer
geometry, unsafe metadata, tile bounds/coverage, bijection, operation order,
mapping hash, JPEG coefficient/quantization validation, and final full-size
pixel equality.

The selected-only path is reported as
`trace_fetch_mode=selected_completed_mappings`. The P4-1 compatibility keys
`trace_completed_mapping_count`, `trace_completed_tile_record_count`,
`trace_active_segment_count`, `trace_active_tile_record_count`,
`trace_dropped_completed_mapping_count`, and
`trace_dropped_active_segment_count` continue to describe the retained
browser trace, not the selected return payload. Additional keys are
`trace_requested_mapping_count`, `trace_returned_mapping_count`,
`trace_returned_tile_record_count`, and `trace_missing_mapping_count`.
`trace_fetch_ms` still measures the complete selected browser evaluate,
serialization, Playwright/CDP transfer, and Python materialization wall
clock, so it remains comparable with P4-1.

The parity unit test compares the full-trace and selected-record analyzer
results for the same completed mapping, including status/reason, provenance,
mapping ID/hash, source/destination/tile dimensions, ImageBitmap identity,
segment metadata, and unsafe metadata. Browser-backed fixtures cover
unrelated-record exclusion, two-part `mapping-A`/`mapping-B` selection,
duplicate exposure, missing IDs, and the existing large post-render prefetch
completed-segment freeze.

The fresh default-ON live run used the shared Crawler Chrome/CDP session,
native capture, direct access, the P4-1 target URL, and a new
`output/bookwalker-p4-2-selected-trace` directory. As in P4-1, the CLI raised
the existing `MaxPagesExceededError` after saving the requested 20 artifacts
and the manifest. Corrected counts are:

```text
20 artifacts
10 logical captures
20 logical parts
10 two-part spreads
```

All 20 artifacts were reconstructed `.jpg` files. Across all 20 logical
parts (the spread shadow is copied to both artifact rows, so the artifact
metadata check visits 40 part rows), `output_enabled=true`, `output_used=true`, `mapping_proven=true`,
`raw_jpeg_exact=true`, `coefficient_exact=true`,
`quantization_tables_equal=true`, `native_pixel_exact=true`, and
`differing_pixel_count=0`. All rows reported
`trace_fetch_mode=selected_completed_mappings`, two requested and two
returned mappings, 2,400 returned tile records, and zero missing mappings.
The retained trace was a median of 3 mappings/3,600 tiles, with a p90/max of
7 mappings/8,400 tiles; this is distinct from the selected returned payload.

| measurement | count | median | p90 | max |
| --- | ---: | ---: | ---: | ---: |
| capture total | 10 | 2396.72 | 2443.55 | 4122.33 |
| lossless evaluation total | 10 | 1641.07 | 1702.73 | 1920.20 |
| selected trace fetch | 10 | 846.05 | 929.63 | 933.12 |
| native materialization | 10 | 102.53 | 124.20 | 167.32 |
| original JPEG matching | 10 | 576.24 | 613.87 | 1961.46 |
| mapping analysis | 20 | 49.61 | 55.64 | 120.78 |
| raw full-resolution comparison | 20 | 57.27 | 67.35 | 75.96 |
| lossless reconstruction | 20 | 133.12 | 177.24 | 270.98 |
| final browser pixel comparison | 20 | 127.41 | 146.84 | 170.49 |

P4-1 to P4-2 median comparison:

| measurement | P4-1 | P4-2 | absolute reduction | reduction |
| --- | ---: | ---: | ---: | ---: |
| trace fetch | 1757.11 ms | 846.05 ms | 911.06 ms | 51.85% |
| lossless evaluation total | 2863.34 ms | 1641.07 ms | 1222.27 ms | 42.69% |
| capture total | 3747.36 ms | 2396.72 ms | 1350.64 ms | 36.04% |

The new measured cost ranking is selected trace fetch (846.05 ms), original
JPEG matching (576.24 ms), lossless reconstruction (133.12 ms), final
browser pixel comparison (127.41 ms), native materialization (102.53 ms),
raw full-resolution comparison (57.27 ms), and mapping analysis (49.61 ms).
Original matching remains outside lossless evaluation and its three attempts
with the 150 ms retry wait were not changed. Full-resolution comparisons,
coefficient readback, quantization equality, and all proof gates remain in
place.

P4-3 candidates, not implemented here, are original-JPEG matching, any
careful full-resolution comparison optimization, and bounded mapping-validator
cost reduction such as replacing repeated duplicate counting with `Counter`.
If selected mapping transfer remains material after more representative
measurements, compact numeric tile transport is a separate contract change;
it was intentionally not included in P4-2.

### 20.19 Phase P4-3 compact completed-mapping transport (2026-10-01)

P4-3 keeps the P4-2 exact `mappingId` selection and changes only the
browser-to-Python representation of the selected completed mappings. The
BookWalker browser helper now returns
`transportVersion=1` and `compactMappings`, never the rich tile objects. Each
mapping stores scalar proof metadata once, deduplicated source/target/
transform/composite/filter tables, and numeric-heavy 15-field tile rows.
Unknown strings and malformed values are not replaced with safe defaults; the
browser returns a transport error marker and the Python path falls back to
native PNG when strict decoding fails. Python
`decode_compact_completed_mappings()` accepts version 1 only, validates table
and array shape/indexes/types, rebuilds the existing rich
`completedMappings` contract, and then calls the unchanged proof authority
`analyze_purchased_mapping()`.

Retained browser trace storage is unchanged: active/completed bounds,
eviction, overflow, unsafe metadata, and `mappingId` semantics remain in
`_DRAW_TRACE_SCRIPT`. The retained summary compatibility keys still describe
the full bounded browser store. The selected-payload keys still describe
requested/returned/missing mappings and tile records. New compact table
summary keys report the selected source, target, transform, composite, and
filter table counts. The production mode is
`trace_fetch_mode=selected_completed_mappings_compact_v1`; `trace_fetch_ms`
still covers browser compact construction, serialization, transfer, and
Playwright/Python payload materialization, while `trace_decode_ms` covers
only strict Python reconstruction of the rich contract.

The completed-mapping validator now uses `Counter` for source and destination
position duplicate counts. The duplicate semantics are unchanged: no
duplicate is zero, one repeated position is one duplicate, and a position
appearing three times contributes two duplicates. Renderer geometry, unsafe
operation, clear-boundary, source/target identity, bijection, operation-order,
mapping-hash, coefficient, quantization-table, raw full-resolution, and final
browser pixel proof gates remain Python-side and unchanged.

The proof parity tests compare rich and compact-decoded records for status,
reason, debug provenance, mapping hash and dimensions, ImageBitmap/source and
renderer identities, segment metadata, unsafe metadata, and the complete
`PurchasedMapping` contract. Browser-backed tests cover unrelated mapping
exclusion, two-part `mapping-A`/`mapping-B` ordering and proof, duplicate
record exposure, missing IDs, compact payload shape, and the large
post-render prefetch completed-segment freeze. Strict decoder fixtures cover
unknown versions, malformed arrays/tables/indexes, and impossible types;
malformed/unsafe rich mapping cases retain identical rejection behavior after
compact decode.

The fresh default-ON live run used the shared Crawler Chrome/CDP session,
native capture, direct access, the P4 URL, and a new
`output/bookwalker-p4-3-compact-trace` directory. The CLI raised the existing
`MaxPagesExceededError` after saving the requested 20 artifacts and manifest.
Corrected counts are:

```text
20 artifacts
10 logical captures
20 logical parts
10 two-part spreads
```

The first two artifact rows (one logical spread) had no selected renderer
`mappingId` and correctly used native PNG fallback. The other 18 ordinary
960x1280 parts returned reconstructed JPEGs. For those successful parts,
`output_enabled=true`, `output_used=true`, `mapping_proven=true`,
`raw_jpeg_exact=true`, `coefficient_exact=true`,
`quantization_tables_equal=true`, `native_pixel_exact=true`, and
`differing_pixel_count=0`. No compact decode failure occurred on the selected
reconstruction path. Evaluation `unaccounted_ms` was 1.71 ms median.

The P4-3 timing summary is below; values are milliseconds. Mapping analysis
has 18 successful lossless parts because the initial mapping-ID-unavailable
spread fails closed before analysis.

| measurement | count | median | p90 | max |
| --- | ---: | ---: | ---: | ---: |
| capture total | 10 | 1674.60 | 2085.74 | 2329.53 |
| lossless evaluation total | 10 | 890.38 | 991.80 | 1374.25 |
| compact trace fetch | 10 | 150.91 | 213.14 | 224.29 |
| trace decode | 10 | 10.33 | 28.63 | 84.06 |
| mapping analysis | 18 | 15.71 | 31.28 | 33.32 |

P4-2 to P4-3 median comparison:

| measurement | P4-2 | P4-3 | absolute reduction | reduction |
| --- | ---: | ---: | ---: | ---: |
| selected trace fetch | 846.05 ms | 150.91 ms | 695.14 ms | 82.16% |
| lossless evaluation total | 1641.07 ms | 890.38 ms | 750.69 ms | 45.74% |
| capture total | 2396.72 ms | 1674.60 ms | 722.12 ms | 30.12% |
| mapping analysis | 49.61 ms | 15.71 ms | 33.90 ms | 68.33% |

The selected compact payload was normally two mappings and 2,400 tile rows,
while the retained browser summary was a median three mappings/3,600 tiles
(p90 and max seven mappings/8,400 tiles). The selected compact tables were
two source, target, transform, composite, and filter entries per ordinary
two-part spread. No rich 2,400-tile payload is returned by the browser.

The new median cost ranking is original JPEG matching (581.46 ms), compact
trace fetch (150.91 ms), final browser pixel comparison (139.62 ms), lossless
reconstruction (134.51 ms), native materialization (111.35 ms), raw
full-resolution comparison (59.58 ms), mapping analysis (15.71 ms), and
strict compact decode (10.33 ms). Original matching still uses the existing
bounded attempts and 150 ms retry interval. P4-4 candidates are original JPEG
matching first, then final browser pixel comparison/native materialization,
raw full-resolution comparison, and further mapping-analysis investigation;
compact numeric transport is now implemented and is not a reason to change
the proof contract further.

### 20.20 Phase P4-4 original matcher event-driven retry (2026-10-02)

P4-4 changes only the BookWalker original-JPEG matcher scheduling and its
observability. The original-JPEG priority, native dimensions, browser 64x64
signature, unique candidate requirement, all-part spread requirement, and
byte-preserving return remain unchanged. The old negative path could perform
three scans separated by two blind 150 ms waits. The new path scans the
current candidate snapshot once, retries immediately if the candidate
generation changes during the scan, and otherwise waits only when an eligible
original-response task is still pending. The wait is bounded by the existing
150 ms budget and wakes on a new valid candidate or pending-task completion.
Task completion only removes that task from the wait condition; the matcher
continues waiting while another task from the initial pending set remains.
It returns negative after all initially observed tasks complete without a new
candidate, at timeout, or immediately when no pending work exists.

`_original_candidate_generation` is incremented only when a validated,
non-duplicate candidate is admitted to the bounded cache. An
`asyncio.Event` is used only as a wake-up optimization; the generation counter
is authoritative and is rechecked around event clearing to avoid a lost wake.
Negative decisions store the generation at which they were proven negative.
When a later response admits a candidate, the stale negative is discarded and
the same native decision key is evaluated again. Positive decisions still
resolve the recorded candidate hashes and fail closed if those candidates
were evicted.

The matcher now reports native-signature, candidate-signature, scan, retry
wait, and total timing, together with attempt/wait counts, pending work at
entry, candidate counts, and candidate generations. These values are
diagnostic only and do not select JPEG versus PNG or alter proof behavior.

The targeted unit coverage includes exact-match first priority, positive
decision reuse, mismatch and empty-cache immediate negatives, a later
candidate arriving after an earlier pending task completes without a
candidate, all-pending completion without a candidate, bounded timeout without
cancellation, generation changes during signature scanning, generation-safe
negative-cache invalidation, duplicate-generation suppression, and the
`fetch -> body store -> fulfill` route ordering. The existing purchased
mapping/lossless proof and browser-backed BookWalker integration tests remain
unchanged and pass.

The fresh purchased live run used the P4-3 URL, the shared Crawler Chrome/CDP
session, native capture, direct access, and a new
`output/bookwalker-p4-4-original-match-retry` directory. The first identical
attempt stopped before capture because the strict reader control did not
navigate to a viewer; the fresh retry reached the requested limit and saved
the manifest. The CLI raised the existing `MaxPagesExceededError` after 20
artifacts, as expected. Corrected counts are:

```text
20 artifacts
10 logical captures
20 logical parts
10 two-part spreads
```

All 20 artifacts returned `reconstructed_jpeg`. All 20 logical parts had
`mapping_proven=true`, `raw_jpeg_exact=true`, `coefficient_exact=true`,
`quantization_tables_equal=true`, `native_pixel_exact=true`, and
`differing_pixel_count=0`; output was enabled and used. The compact P4-3
mapping path, full-resolution comparisons, DCT reread, coefficient proof,
quantization-table proof, and all-or-none spread behavior therefore remain
intact.

The P4-4 purchased timing summary is below; values are milliseconds. Capture
and evaluation rows are deduplicated logical captures; original matcher
internal rows are also capture-level.

| measurement | count | median | p90 | max |
| --- | ---: | ---: | ---: | ---: |
| original JPEG matching | 10 | 308.27 | 387.72 | 2035.20 |
| original native signature | 10 | 205.17 | 285.79 | 294.29 |
| original candidate signature | 10 | 96.14 | 117.13 | 1749.22 |
| original match scan | 10 | 0.02 | 0.04 | 0.07 |
| original retry wait | 10 | 0.00 | 0.00 | 0.00 |
| lossless evaluation total | 10 | 898.70 | 1075.20 | 1426.87 |
| capture total | 10 | 1370.08 | 1577.07 | 3649.83 |

P4-3 to P4-4 median comparison:

| measurement | P4-3 | P4-4 | absolute reduction | reduction |
| --- | ---: | ---: | ---: | ---: |
| original JPEG matching | 581.46 ms | 308.27 ms | 273.19 ms | 46.98% |
| capture total | 1674.60 ms | 1370.08 ms | 304.52 ms | 18.18% |
| lossless evaluation total | 890.38 ms | 898.70 ms | -8.32 ms | -0.93% |

The live attempt distribution was `attempt_count=1: 9`, `2: 0`, `3: 1`;
`retry_wait_count=0: 10`, `1: 0`, `2: 0`. Pending response tasks at matcher
entry were zero for every deduplicated purchased capture. Candidate counts
were 23 median (30 p90, 32 max) at both start and end, and the corresponding
generation values were also 23 median (30 p90, 32 max). The one three-attempt
row admitted additional candidates while signature work was in progress and
was retried without sleeping; it did not use a blind timeout.

The retained-vs-selected P4-3 compact trace statistics remained unchanged in
this run: retained completed mappings were 3 median / 5 p90 / 7 max and
retained tiles were 3,600 median / 6,000 p90 / 8,400 max. Selected payloads
were two mappings and 2,400 tiles for every ordinary spread, with two source,
target, transform, composite, and filter table entries. The trace fetch was
145.48 ms median (232.66 p90, 260.86 max) and compact decode was 9.55 ms
median (11.36 p90, 13.79 max); evaluation unaccounted time was 2.04 ms
median. The resulting median cost ranking is original JPEG matching
(308.27 ms), final browser pixel comparison (149.03 ms), compact trace fetch
(145.48 ms), lossless reconstruction (130.82 ms), native materialization
(110.76 ms), raw full-resolution comparison (60.95 ms), mapping analysis
(16.48 ms), and compact decode (9.55 ms). The matcher internals show that
native and candidate signature generation, rather than retry sleep, now
dominate original matching.

The existing recorded trial viewer URL was also reused with automatic access
for an original-path regression. It produced one logical two-part spread and
two artifact rows at 960x1280. Both rows reported `returned_path=original_jpeg`,
`output_used=false`, `original_attempt_count=1`, and
`original_retry_wait_count=0`; no lossless shadow was attempted. The emitted
file SHA-256 matched its manifest fingerprint, preserving the candidate bytes
through the output path. The direct-access form of this viewer URL is not a
strict product entry, so the regression used the recorded viewer URL with
the adapter's existing automatic-entry behavior.

P4-5 candidates are the final browser full-resolution comparison and native
PNG materialization, followed by raw full-resolution comparison and possible
bulk native/candidate signature work. No timing threshold was added to CI;
behavior, counts, generation safety, byte preservation, and proof results are
the authorities.

### Phase 1 runtime pacing

BookWalkerのmanual crawlおよびBatch crawlはroot `crawler.yaml`のresolved `page_turn_delay_ms`を
CONTENT保存後、initial `go_next()`直前に1回だけ使う。Batch candidate間はPage close後に
`inter_candidate_delay_ms`を1回だけ使う。BookWalkerのexisting navigation retry、END判定、timeout budgetは
変更していない。Phase 2ではBookWalker adapterがshared AccessGuardへ接続され、
`bookwalker.jp`、`viewer.bookwalker.jp`、`viewer-epubs*.bookwalker.jp`、
`bw-bv-epubs.bookwalker.jp`等のrelevant hostだけの403/429をfatal stopとする。
explicit challengeとvisible CAPTCHAも共通stop reason/Batch JSONL metricsへ記録する。
site-specific signalのlive verificationは未実施で、grant-onlyは未実装である。

### 20.21 Phase P4-5 final reconstructed-JPEG pixel gate removal (2026-10-02)

P4-5 completes the current BookWalker reconstructed-JPEG performance
optimization series. The per-page full-resolution browser comparison between
the reconstructed JPEG and native PNG is no longer part of the default
production gate. The comparison remains available as a BookWalker-local
diagnostic with `BOOKWALKER_FINAL_PIXEL_VERIFY`; unset, `0`, `false`, `no`, and
`off` mean disabled, while `1`, `true`, `yes`, and `on` mean enabled. An invalid
value fails fast in `BookWalkerAdapter`.

The default production authority is now the verified source JPEG, the complete
MCU-aligned mapping, exact raw-JPEG/ImageBitmap attribution, coefficient-exact
DCT reconstruction, equal quantization tables, matching dimensions, and
supported source/output JPEG structure. Output reread now also requires three
components, 4:4:4 sampling, one scan, and non-progressive mode on the output
DCT object, matching the supported source layout. Mapping proof, overflow and
eviction guards, unsafe geometry checks, strict MCU alignment, raw full-
resolution attribution, coefficient readback, and qtable equality were not
weakened. The original JPEG matcher remains first priority and is not passed
through reconstruction or final-pixel verification.

Each lossless part records `final_pixel_verify_enabled`,
`final_pixel_compare_performed`, and `native_pixel_exact`. With verification
off, the last two remain `false` and `null` respectively; the adapter does not
emit `native_pixel_comparison`, and `final_browser_pixel_compare_ms` remains
`0.0`. With verification enabled, the browser helper returns the available,
exact, dimension, differing-pixel, and maximum-channel fields; exactness is an
additional spread gate and mismatch falls back to native PNG. Thus the default
production path no longer claims runtime browser-decoded full-pixel equality
for every reconstructed page; that equality is optional diagnostic evidence.

The production unit coverage includes the default-off no-call guard (the
`_browser_pixel_exact` helper is made to fail if invoked), enabled exact and
mismatch behavior, strict environment parsing, all-or-none fallback, and
fail-closed proof cases. Lossless-JPEG unit coverage also checks output DCT
component count, sampling factors, progressive mode, and scan count. The
browser integration regression decodes a reconstructed JPEG and its expected
native PNG in Chromium and observed `differing_pixel_count=0` and
`max_channel_difference=0`.

The requested live URL was run with a fresh output directory and default
verification unset. The first 20-artifact attempt began at the shared viewer's
remembered `149/314`; after resetting the shared viewer to page 1, a second
bounded run saved 19 artifacts from 10 logical captures (`11/314` onward; the
first logical capture was a one-part cover). All parts in these live runs
failed before raw matching at the existing mapping proof with
`completed segment has no tile draws` / `trace_returned_tile_record_count=0`.
Consequently, this session produced zero reconstructed-JPEG artifacts and is
not a valid performance comparison against P4-4's successful proof path. It
does verify the default metadata contract on the fallback path:
`final_pixel_verify_enabled=false`,
`final_pixel_compare_performed=false`, `native_pixel_exact=null`, and final
browser comparison timing zero. The reset-run timing snapshot, in
milliseconds, was:

| measurement | count | median | p90 | max |
| --- | ---: | ---: | ---: | ---: |
| capture total | 10 | 138.30 | 158.56 | 161.93 |
| lossless evaluation total | 10 | 3.75 | 4.89 | 5.67 |
| final browser pixel comparison | 19 | 0.00 | 0.00 | 0.00 |
| original JPEG matching | 10 | 56.98 | 62.40 | 65.67 |
| compact trace fetch | 10 | 3.52 | 4.67 | 5.24 |
| lossless reconstruction | 19 | 0.00 | 0.00 | 0.00 |
| native materialization | 10 | 29.27 | 31.62 | 34.37 |
| raw full-resolution comparison | 19 | 0.00 | 0.00 | 0.00 |
| mapping analysis | 19 | 0.04 | 0.08 | 0.20 |
| compact decode | 10 | 0.06 | 0.08 | 0.13 |

P4-4's successful purchased baseline remains capture total `1370.08 ms`,
lossless evaluation total `898.70 ms`, and final browser comparison
`149.03 ms/part`. Absolute and percentage P4-4-to-P4-5 reductions are not
claimed from the failed live proof path: subtracting a run that stopped before
raw matching, DCT reconstruction, and native-pixel comparison would be
misleading. The expected final-comparison production cost is nevertheless
`~149.03 ms/part -> 0.0 ms`, and the unit/integration contracts prove that the
comparison is only paid when explicitly enabled.

A separate diagnostic live run with `BOOKWALKER_FINAL_PIXEL_VERIFY=1` covered
five logical captures / ten artifacts. Verification was enabled in all ten
manifest rows, but zero comparisons ran because the same pre-comparison
mapping proof failed; therefore no live `native_pixel_exact=true` claim is
made. The existing original-JPEG A/B diagnostic was also run after resetting
to page 1 (`37/314 -> 1/314`); it observed no unique original match and fell
back to native PNG, so it did not replace the previously recorded P4-4 trial
original-path regression. Existing unit and browser regression tests continue
to prove that a unique original match returns `original_jpeg` without lossless
evaluation.

The remaining measured costs are understood, but no further optimization is
planned in this series for raw source full-resolution attribution, native PNG
materialization, signatures, or coefficient readback. Their correctness and
complexity balance is preferred at this phase boundary. Native materialization
lazy evaluation, signature redesign, original matcher changes, compact
transport v2, and Core/YAML/DB/packaging changes remain out of scope.

### 20.22 P4-5 mapping provenance regression investigation (2026-10-02)

The P4-5 fallback regression was investigated with bounded provenance
instrumentation before changing any mapping authority. The BookWalker draw
trace now retains at most four `nonImageBitmapDraws` per active segment and
the selected compact transport carries those records plus small summaries of
the bounded retained completed mappings. The summary includes canvas identity,
operation ordering, clear/tile boundaries, tile count, ImageBitmap source IDs,
and source/target dimensions. It does not transfer the full retained trace or
tile payload for unselected mappings.

The fresh default run used the shared Crawler Chrome/CDP session, the requested
purchased URL, `BOOKWALKER_FINAL_PIXEL_VERIFY` unset, and
`output/bookwalker-p4-6-provenance-r4`. It saved four artifacts from two
logical captures (`29/314` and `31/314`); all four returned `native_png`.
Every selected renderer mapping had an exact mapping ID, zero direct tile
draws, one `non_image_bitmap_draw`, and no trace overflow. The selected chains
were:

```text
renderer canvas 3, selected source/segment target canvas 5,
copy source canvas 4 -> target canvas 5,
copy op 6041/7250 on 29/314 and 3620/4829 on 31/314,
copy source 960x1280 -> target 480x640,
sourceRect=(0,0,960,1280), destination=(0,0,480,640),
identity transform, alpha=1, source-over, filter=none.
```

The retained summaries proved that the tile-rich mapping is the immediately
preceding canvas-4-to-canvas-5 mapping, not an unrelated same-size or nearby
mapping. For example, on `29/314`, mapping `mapping-6041` has source canvas 4,
target canvas 5, renderer operation 6041, clear 4835, tile operations
4841-6040, 1,200 tiles, ImageBitmap source 2, and 960x1280 -> 480x640
dimensions; the selected downstream mapping is `mapping-6042` and its copy
operation is 6041 before renderer operation 6042. The corresponding `31/314`
chain is `mapping-3620` -> `mapping-3621` and `mapping-4829` ->
`mapping-4830`, with the same identities and dimensions. Retained traces had
6-10 completed mappings and 3,600-6,000 tile records, while the selected
compact payload returned two mappings and zero tile records.

This is a real one-hop HTMLCanvasElement copy, but it is not hypothesis A's
strict safe full-canvas identity copy: both source and destination rectangles
are full, yet the source canvas is 960x1280 and the target canvas is 480x640,
so the operation is a 0.5x resize. The live root-cause classification is C
(partial/canvas resize path), not a trace reset, wrong active segment, or
dimension/time-proximity selection error. The existing exact renderer
`mappingId` authority therefore remains unchanged.

No production `canvas_copy_1hop` proof was adopted. In particular, the
strict conditions requiring equal source/target dimensions, full-size identity
geometry, one safe non-ImageBitmap copy, no other unsafe operation, exact
canvas identity, and complete upstream mapping proof were not weakened to
accept this scaled copy. The bounded diagnostic fields are the only adopted
change; direct completed ImageBitmap-tile mappings retain
`mapping_provenance=direct`.

Because the live case was not A at the time of this investigation, that section
did not claim reconstructed-JPEG success or infer JPEG/DCT equivalence from the
resize. The follow-up implementation is recorded below; this paragraph remains
the historical investigation snapshot.

### 20.23 Strict one-hop scaled-source provenance recovery (2026-10-02)

The purchased-viewer live shape is now supported with source-native semantics.
The observed ordinary page is:

```text
ImageBitmap tiles -> canvas A 960x1280
canvas A -> canvas B 480x640 (one full-frame draw)
canvas B -> selected renderer
```

The production artifact for this path is the proven source-native reconstructed
JPEG at 960x1280. It is not a JPEG encoding of the 480x640 displayed pixels;
`PurchasedMapping.source_dimensions`, raw JPEG matching, DCT reconstruction,
and `CaptureResult` dimensions remain 960x1280. The native 480x640 PNG is the
displayed comparison/fallback artifact only.

The Python-only resolver accepts exactly one hop and fails closed unless all of
the following are exact: selected mapping ID; zero downstream tile draws;
non-overflow, non-evicted completed segment; exactly one unsafe operation of
type `non_image_bitmap_draw`; HTMLCanvasElement source identity; distinct source
and target canvas IDs; full-frame source and destination rectangles; identity
transform; alpha 1; source-over; filter none; positive aspect-preserving
dimensions; and downstream/upstream operation ordering. The retained summary
must have exactly one match on renderer operation index, source/target canvas
IDs, source/target dimensions, and a positive tile count. No dimension
proximity, operation proximity, nearest mapping, recursion, or two-hop graph is
used. The resolved upstream ID is compact-fetched once for the whole spread,
then the existing `analyze_purchased_mapping()` validator is applied unchanged
and cross-checked against the copy operation.

Direct completed tile mappings remain `mapping_provenance=direct` and do not
perform an upstream fetch. Scaled mappings use
`mapping_provenance=scaled_canvas_source_1hop`; spread output remains all-or-none.
Common readiness still requires exact raw JPEG attribution, unique candidate,
supported JPEG, strict MCU alignment, coefficient and qtable equality, and
`reconstructed_source_dimensions_match`. Historical
`reconstructed_dimensions_match` may be false only for this scaled path.

`BOOKWALKER_FINAL_PIXEL_VERIFY` remains default off: no final browser compare is
performed and `native_pixel_exact` is `null`. When enabled, direct mappings use
the intrinsic comparison helper. Scaled mappings use a diagnostic-only browser
draw of the reconstructed source-native JPEG at the proven 480x640 destination,
with the traced `imageSmoothingEnabled` and `imageSmoothingQuality` applied;
missing smoothing metadata fails closed. A mismatch returns native PNG and is
not used as production provenance authority.

Debug metadata records only the selected/upstream mapping IDs, copy operation,
canvas identities, source/target dimensions, scale factors, provenance, and
stage timing (`selected_trace_fetch_ms`, `upstream_trace_fetch_ms`, and their
decode counterparts); full retained tile traces are never transferred for
resolution. The compact transport version remains 1.

Live validation completed on the requested URL with the shared Chrome/CDP
session. With `BOOKWALKER_FINAL_PIXEL_VERIFY` unset,
`output/bookwalker-onehop-default-20261002` saved 10 JPEG artifacts from five
logical two-part captures. Every part returned `reconstructed_jpeg` at
960x1280 with `mapping_proven=true`, `mapping_provenance=scaled_canvas_source_1hop`,
an upstream mapping ID, unique raw-JPEG attribution, exact coefficient/qtable
proof, and `reconstructed_source_dimensions_match=true`. Final browser pixel
comparison was disabled, so `final_pixel_compare_performed=false`,
`native_pixel_exact=null`, and the final comparison timing was 0 ms.

With `BOOKWALKER_FINAL_PIXEL_VERIFY=1`,
`output/bookwalker-onehop-diagnostic-20261002-r2` saved four JPEG artifacts.
All four used `scaled_source_to_native` diagnostic comparison and reported
`native_pixel_exact=true`, `differing_pixel_count=0`, and
`max_channel_difference=0`. The diagnostic now restores the reconstructed
JPEG into a source-size HTML canvas before applying the proven scale, matching
the traced HTMLCanvasElement source identity. This remains diagnostic evidence
and is not production proof.

The successful default run was summarized with
`scripts/analyze_bookwalker_capture_timing.py`; values are milliseconds,
median / p90 / max. Capture-level values use five logical captures; part-level
values use ten spread parts:

| measurement | median | p90 | max |
| --- | ---: | ---: | ---: |
| capture total | 932.01 | 2233.39 | 2233.39 |
| evaluation total | 808.84 | 2005.95 | 2005.95 |
| selected trace fetch | 6.58 | 9.12 | 9.12 |
| upstream trace fetch | 167.08 | 200.30 | 200.30 |
| total trace fetch | 171.18 | 208.88 | 208.88 |
| selected trace decode | 0.16 | 0.20 | 0.20 |
| upstream trace decode | 8.96 | 9.60 | 9.60 |
| original JPEG matching | 52.25 | 69.21 | 69.21 |
| raw full-resolution compare | 52.38 | 56.63 | 112.18 |
| lossless reconstruction | 125.72 | 293.60 | 305.22 |
| native materialization | 28.61 | 44.59 | 44.59 |
| final browser pixel compare | 0.00 | 0.00 | 0.00 |

Against the successful P4-4 reference (capture 1370.08 ms, lossless
evaluation 898.70 ms, final browser comparison 149.03 ms/part), this run was
438.07 ms lower in median capture total and 89.86 ms lower in median lossless
evaluation. The final comparison cost is now 0 ms by default. The runs are
bounded live samples rather than a controlled benchmark suite, so these
differences are directional only.

### 20.24 Direct partial-MCU reconstructed JPEG path (Stage 02 implementation)

The current BookWalker source-native priority is:

```text
verified original JPEG
    -> verified lossless reconstructed JPEG
    -> source/native PNG
    -> rendered-canvas PNG fallback
```

The direct completed-mapping path keeps coded source dimensions `S` separate
from visible intermediate dimensions `V`. It accepts baseline SOF0, three-component
4:4:4 JPEGs with a unique full-resolution candidate, exact quantized-DCT
reconstruction, unchanged quantization tables and component table-selector IDs.
A cropped frame may differ from `V` by fewer than eight pixels only on the final
right or bottom MCU; all geometry is integer and 8-pixel aligned, and recorded
source/destination rectangles must form a complete non-overlapping MCU bijection.
Unsafe state, hidden edge gaps, duplicates, out-of-bounds records, overflow,
eviction, or ambiguous candidates fail closed.

For this direct cropped path, browser comparison against the selected native
snapshot is mandatory even when `BOOKWALKER_FINAL_PIXEL_VERIFY` is disabled.
The comparison must be available, dimension-equal and zero-difference; an
exception or mismatch returns source/native PNG for the whole spread. Older
equal-size and one-hop paths retain their optional final-pixel diagnostic
behavior. `BOOKWALKER_LOSSLESS_JPEG_OUTPUT` remains the BookWalker kill switch,
and the all-parts-or-PNG spread rule remains unchanged.

Stage 02 live verification selected manga `9/159` and `11/159` as two direct
parts after the explicit predecessor-to-target geometry-clear/native-arm
boundary. Both spreads proved `S=848x1200` and `V=844x1200`, 1,026 tiles,
complete coded MCU coverage, coefficient/qtable/selector equality, one exact
JPEG candidate per part, and native snapshot pixel equality with zero differing
pixels. Bounded LN acceptance likewise proved the direct reconstructed-JPEG
path on `3/314`, `4/314`, `8/314`, and `10/314`: the first two used
`S=2048x1456` and `V=2048x1453` with 2,944 tiles, while the latter two used
equal `S=V=960x1280` with 1,200 tiles. Each had one exact JPEG candidate and
coefficient/qtable/selector equality; the cropped pages also passed mandatory
native comparison with zero differing pixels. `2/314` remained source/native
PNG fallback because usable upstream mapping proof for the selected renderer
was unavailable; the mapping ID alone is insufficient.
The stable current manga cover probe entered at `5/159`, explicitly restored
`1/159`, and returned no native capture parts. Core then materialized one
rendered-canvas PNG fallback at `1386x983`; its original-JPEG matcher had zero
attempts and zero candidates in the unattempted matcher diagnostics; those
counters are not a raw-response inventory. This current observation is separate from
the historical cover A/original-JPEG evidence. The stable current `2/314`
LN record retained a completed-segment mapping ID but had zero segment tiles,
no coded/visible dimensions or source identity, and was therefore rejected as
not reconstruction-ready; this remains D rather than evidence that the
historical bitmap candidate does not exist.
The production unit path and site-local documentation are synchronized. The
implementation was checked by 180 targeted unit tests and 46 browser-backed
integration tests, including a real-canvas nonuniform permutation with
`S=40x40` and `V=37x36`; Reviewer recheck found no blocking code, test, or
documentation issue. The site-local MCU work bound rejects invalid or oversized
mappings before expansion and allocation. Final production Reviewer also
accepted the bounded live evidence and actual cover fallback controls with no
remaining BLOCKING; Stage 02 is complete with the documented D limits.

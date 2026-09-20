# 01. BookWalker 現行実装ノート

このファイルはBookWalker Adapterの**現在の実装詳細と実サイト観測**をまとめる。BookWalker固有の実装・運用を変更した場合は、このnoteも同じ変更で更新する。

共通Runner / Browser Session / output / packagingの詳細は `note/00_core.md` を参照。

最終同期: 2026-09-20

## 1. 目的と現在のscope

BookWalkerの商品ページまたはviewer URLから、現在コンテンツの本文だけを順番にPNG保存する。

現在対応している主な挙動:

- 商品ページからreader候補を見つけてviewerへ移動
- Canvas本文取得
- 単ページ / 横長ページ / 見開き
- 見開きを右→左の読書順で個別PNG化
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
click後はURL changeを確認し、両方のcontent UUIDを取得できる場合は一致を確認する。
delayed controlは既存`read_link_wait_timeout_ms`（default 5000ms）のbounded waitで待つ。
quotaではtrial onlyやsubscription onlyの場合もtrialへfallbackせずfailする。

Phase 4のunit testsではstrict quota/direct成功、wrong strategy、trial/subscription/generic only、
multiple candidate、scope overlapの同一DOM dedupe、delayed maruyomi、UUID mismatch、target blank、
already-viewerをsynthetic product pageで確認している。quotaを消費するlive clickは未実施である。

## 3. Viewer / capture target

BookWalker本文は主にCanvas renderer。

優先する現在画面:

```text
#renderer .currentScreen canvas:not(.dummy)
```

fallbackとして `#renderer canvas:not(.dummy)` も見る。

CanvasはCore `capture.py` がraw PNG bufferを取得する。browser UIや周辺DOMを避ける。

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
外接範囲を1つのcapture targetとしてPNG保存する。複数のdraw rectangleが
ある場合も外側のviewer余白だけを除いた1枚に結合する。draw geometry自体が
取れない場合は、表紙artworkを推測で切らないため、保守的にviewer canvas全体
へfallbackする。2ページ目以降の見開きは従来どおり右ページ→左ページの
個別artifactとする。

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

BookWalker captureでも保存dedupeは各PNGのSHA-256 fingerprint。

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

正常 `END` / `NEXT_CONTENT` 後、Coreがmanifest記載PNGだけをZIP化する。

```text
output/Books/<genre>/<title>/<title>-<volume>-<author>.zip
```

completion statusは `output/crawl-status/` 配下。

中間crawl directoryは、内容がmanifest / progress / manifest記載PNGだけの場合に限り削除する。

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
crop PNG path.  Production does not perform full-pixel comparison; the
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
source rectangle, transform, and composition metadata, while retaining the
current source objects for the bounded capture window.  Once the final visible
draw calls are selected, only those one or two source rectangles are copied to
temporary canvases and encoded as PNG.  Cleanup clears both the draw-call list
and retained source objects.

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
Because that source canvas is mutable during a spread render, purchased
viewer documents enable bounded eager source-crop materialization before the
draw call is cleared. Repeated source IDs are accepted for a spread only when
each draw call retained its own crop; deferred repeated sources remain
rejected. An `HTMLCanvasElement` call without an eager `sourceCropPng` is
rejected before deferred materialization, so it cannot make a mutable source
look stable after the draw. If the raw tile JPEG does not uniquely match, the
verified source-native PNG is returned as-is; no PNG-to-JPEG re-encoding is
performed. A spread still falls back as a complete unit when its native
capture is unavailable.

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

The draw-trace initialization now preserves an eager-capture value already
configured by an earlier init script. Consequently both init-script orders are
safe: `viewer.bookwalker.jp` enables eager capture, while other hosts retain
the default disabled value unless the explicit test/override switch is true.

`ImageBitmap` may still use bounded deferred source-crop materialization.
`HTMLCanvasElement` requires a non-empty eager crop recorded by the draw hook;
without it the native route returns unavailable and Core captures the canvas as
PNG. Native output priority is now verified original JPEG, verified
source-native PNG, then the existing Core canvas PNG fallback. The old
quality-0.92 rendered JPEG fallback is not used, so failed original matching
cannot inflate PNG artifacts or introduce a JPEG/PNG mixture in a spread.

The runner also applies the adapter-specific page-change timeout to the
duplicate-fingerprint wait branch, matching the normal navigation branch.

### 18.20 Cover geometry correction (2026-09-20)

Shared-profile CDP comparison of a purchased viewer and a trial viewer showed
that both render the actual page into a centered destination rectangle inside a
larger white canvas. The previous first-page special case deliberately kept
that full canvas, which explains the cover-only outer margins. The adapter now
uses the normal draw-geometry crop for a single cover rectangle and combines
multiple cover rectangles into one union crop, preserving one cover artifact.
This is unrelated to PNG/JPEG conversion; native PNG/JPEG selection remains
unchanged.

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

### 20.6 初期非対象

- 10分残量を秒単位で計測して複数冊を詰め込む最適化
- 10分切れで途中停止した巻を翌日に同じrunへresume
- 読み放題MAX等を自動crawl対象として扱うこと
- BookWalker全作品・全まる読み対象の自動探索

このnoteにはpassword、Cookie、storage state、session secretを記録しない。

# 01. BookWalker 現行実装ノート

このファイルはBookWalker Adapterの**現在の実装詳細と実サイト観測**をまとめる。BookWalker固有の実装・運用を変更した場合は、このnoteも同じ変更で更新する。

共通Runner / Browser Session / output / packagingの詳細は `note/00_core.md` を参照。

最終同期: 2026-09-19

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

BookWalkerのseries-scoped Discoveryは実装済みである。BookWalker Site PolicyとBatch実行は
未実装だが、Batchからのstrict `direct` / `quota` entryは実装済みである。Adapterを直接生成
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
0件ならbounded wait後にfail、1件なら`target`属性だけを除去して同じPageからclick、2件以上
ならambiguityとしてclick前にfailする。strict errorにはstrategy、expected kind、observed kindsを
含める。product page以外のalready-viewer strict runも、entry条件を検証できないためfailする。
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

1. `#viewport1` の左端付近をclick
2. clickできない場合 `ArrowLeft`

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

`page_change_timeout_ms = 10_000` 内に安定しなければ `PageChangeTimeoutError`。

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

## 12. wait_for_change / retry

- AD / END / NEXT_CONTENT → return
- CONTENTでidentity変化 → render ready後return
- CONTENTでidentity同一かつ最終counter → 最終ページ後の既知挙動としてreturn
- CONTENTでidentity同一 → bounded retry

冒頭cover等で最初のclickが消費されるケースに備え、最大2回追加retryする。

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

## 19. Known limitations / maintenance

- BookWalker DOM / Canvas renderer変更時は再調査が必要。
- drawImage geometryが取れない未知作品ではfallbackになる可能性がある。
- 直接viewer URLから開始すると商品metadataが不足する可能性がある。
- 同名完成ZIPは上書きしない。
- global fingerprint dedupeのためpixel完全一致の別ページは1枚扱いになる。
- `config.yaml` はruntime authorityではない。
- diagnosticsのAdapter固有metadata統合は未実装。
- BookWalker Site Policyは未実装。
- BookWalker Adapterのstrict `direct` / `quota` entryは未実装。
- BookWalker series-listのlive DOM smoke testは未実施。Phase 4移行前に実サイトでselectorと全件列挙を確認する必要がある。
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
- Discoveryが既存Adapterから再利用するreader control scope: `#js-read-check`、`#js-subscription-check`、既存のviewer/action fallback
- Discovery pagination候補（`rel=next`、`aria-label`、`data-testid`、表示テキスト）は実装済み。今回のlive対象ではpaginationなし

### 20.2 Discovery access classification

Phase 1では、この仕様で使うBookWalker reader-control metadataのpure分類helperを
実装済みであり、Phase 3のDiscovery Adapterが商品詳細ページ観測で再利用する。Catalog更新は
site-neutralなDiscoveryServiceが行う。

Discoveryはseries listから商品詳細ページを開いてcontrolを観測するが、
readerは開かない。まる読み10分timerをDiscoveryで開始しない。

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
このため実装時にはBatch Executorがgrantなしquota policyを許容する必要がある。

manual browserや別clientでの10分消費はCatalogから観測できない。

### 20.4.1 Series-list live smoke and first-volume inference

2026-09-18に`https://bookwalker.jp/series/317089/list/`を実サイトで確認し、
`mode: full`、`observed: 11`、`new: 11`、`known: 0`、`complete: True`、
`stopped_reason: exhausted`まで成功した。確認できたのはseries scopeの全件列挙と、
各product detailの既存metadata/control取得であり、未使用のselectorやpagination方式まで
live確認済みとは扱わない。

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

# 01. BookWalker 現行実装ノート

このファイルはBookWalker Adapterの**現在の実装詳細と実サイト観測**をまとめる。BookWalker固有の実装・運用を変更した場合は、このnoteも同じ変更で更新する。

共通Runner / Browser Session / output / packagingの詳細は `note/00_core.md` を参照。

最終同期: 2026-09-17

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

### Legacy / compatibility launcher

共通launcherが標準運用である:

```powershell
.\scripts\start_crawler_chrome.ps1
```

profileは `.chrome-crawler` で、Manga ONEとlogin sessionを共存できる。

rollback用に旧launcherも残している:

```powershell
.\scripts\start_bookwalker_chrome.ps1
```

と `.chrome-bookwalker` が存在する。

これはlegacy / compatibility pathであり、今後新規siteへ同種launcherを増やす設計ではない。

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

現行実装ではlegacyのsite別launcher/profileも使えるが、標準運用はshared launcher/profileである。sessionの最終authorityをsite別JSONへ移す方針ではない。

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

共通 `.chrome-crawler/` でのlogin/crawl live verificationは未実施。site-specific adapter behaviorのlive verification記録は維持する。

## 19. Known limitations / maintenance

- BookWalker DOM / Canvas renderer変更時は再調査が必要。
- drawImage geometryが取れない未知作品ではfallbackになる可能性がある。
- 直接viewer URLから開始すると商品metadataが不足する可能性がある。
- 同名完成ZIPは上書きしない。
- global fingerprint dedupeのためpixel完全一致の別ページは1枚扱いになる。
- `config.yaml` はruntime authorityではない。
- diagnosticsのAdapter固有metadata統合は未実装。
- shared `.chrome-crawler/` login/crawl live smoke test
- 旧site-specific launcher/profile削除の判断（Phase 3）

このnoteにはpassword、Cookie、storage state、session secretを記録しない。

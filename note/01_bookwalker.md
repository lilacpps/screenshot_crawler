# 01. BookWalker 現行実装ノート

このファイルはBookWalker Adapterの**現在の実装詳細と実サイト観測**をまとめる。BookWalker固有の実装・運用を変更した場合は、このnoteも同じ変更で更新する。

共通Runner / output / packagingの詳細は `note/00_core.md` を参照。

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
- 専用Chrome profile + CDP + login CLI

実サイト確認では、対象trial readerで59/59まで本文を保存し、その後のlogo screenを保存せず正常終了した実績がある。

## 2. Entry flow

入力は直接viewer URLだけでなく、次のBookWalker商品URLも受け付ける。

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

`more_read` やcover/check系のcontrolはreader入口として除外する。

reader linkが `target=_blank` の場合は、同じCrawler tabで遷移させるためtarget属性を外してclickする。Crawlerが別windowを追跡する構造にはしていない。

## 3. Viewer / capture target

BookWalker本文は主にCanvas renderer。

優先する現在画面:

```text
#renderer .currentScreen canvas:not(.dummy)
```

fallbackとして `#renderer canvas:not(.dummy)` も見る。

Canvasは単にLocator screenshotするのではなく、Core `capture.py` がcanvas raw PNG bufferを取得する。これによりbrowser UIや周辺DOMを避ける。

## 4. drawImage geometry trace

BookWalkerは1つのCanvasへページを描くため、単純な画面中央splitだけでは表紙・挿絵・横長ページ・spreadを正しく切り出せない。

`prepare_page()` でnavigation前に `CanvasRenderingContext2D.prototype.drawImage` をhookし、対象Canvasへのdraw callからdestination rectangleを記録する。

記録する主情報:

```text
canvas id
x
y
width
height
```

有効な大きさのrectangleだけ残し、完全に包含される古い/小さいrectangleは除外する。

現在画面のpage rectangleが得られれば、その範囲を一時Canvasへコピーしてcapture targetとして返す。

対応する主ケース:

- 中央単ページ
- 表紙 / 挿絵
- 横長単ページ
- true spread
- viewer周辺余白を除いた本文

## 5. Spread fallback

drawImage geometryが取得できない場合のみbounded fallbackを使う。

Canvasが縦長/通常比率なら単一ページとして扱う。十分に横長 (`spread_ratio = 1.25`) なら中央で左右に分ける。

BookWalkerは右開きとして、capture targetを**右ページ → 左ページ**の順で返す。

一時Canvasには `data-bookwalker-capture-run` を付け、capture後に `cleanup_capture_targets()` で削除する。draw traceもcapture cycleごとにclearする。

manifestには複数target時に以下を記録する。

```json
{"part": 1, "parts": 2}
{"part": 2, "parts": 2}
```

## 6. Browser size / CDP

専用Chrome launcher:

```powershell
.\scripts\start_bookwalker_chrome.ps1
```

現在のlauncherは:

```text
--window-size=1920,1080
--user-data-dir=.chrome-bookwalker
--remote-debugging-port=<Port>
```

を使う。

目的はBookWalkerがspreadを描画しやすいFull HD相当のlogical windowを与えること。

実環境ではWindows scaling / devicePixelRatioにより `innerWidth/innerHeight` が完全に1920x1080になるとは限らないため、capture実装は固定pixel cropへ依存しない。

`.chrome-bookwalker` は `.chrome-*` としてgitignore対象。

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
- 有効なvisible canvasがある
- Canvasを64x64へ縮小した簡易signatureが取得できる
- non-white pixelsがある
- signatureが複数回安定する

`render_stable_checks = 4`。

`page_change_timeout_ms = 10_000` 内に安定しなければ `PageChangeTimeoutError`。

## 9. Page identity

主signalは `#pageSliderCounter`。

`parse_page_counter()` は表示文字列から最初の数字を `page_number` として取得し、normalized counter text全体を `page_id` として使う。

content IDはURL query `cid` または商品URL `/de<uuid>/` から取得する。

概念:

```text
page_id: page counter text。取れない場合content_id fallback
page_number: parsed current page
source_id: content_id
```

**保存duplicate判定はこのidentityではなくCoreのcapture SHA-256 fingerprintがauthority。** Identityは主にchange detection / manifest / context補助に使う。

## 10. Content context

BookWalkerのcontent IDを:

```text
content_id
work_id
```

として保持する。

`#pagetitle` があればtitleもcontextへ入れる。

開始時と現在のcontent IDが明確に変わればCore側でもNEXT_CONTENT扱い可能。

## 11. State detection

### NEXT_CONTENT

次のいずれか:

- URLから得られるcurrent content IDがinitial content IDから変化
- `#eobNext` がvisible
- Coreのstrong content context change

NEXT_CONTENT画面は保存せず正常終了。

### END

ENDには複数signalを組み合わせる。

- `#endOfBook` がvisible
- 最終 `N/N` ページからnext操作済み (`_final_navigation_pending`) でcounterがまだ最終
- renderer ready後、最終counter状態でgrace中に `#endOfBook` が出現

重要なのは、**最終本文自体は先に保存済み**であること。次操作後にBookWalker logo canvasへ変わっても、`N/N` が残るケースをCONTENTとして再captureしない。

実サイト確認では59/59後にBookWalker logoがCanvas内へ出て、同時に `#endOfBook` がvisibleになった。

### AD

以下の明示selectorがvisibleの場合だけAD:

```text
[data-ad]
.ad
#ad
#advertisement
```

色や平均輝度だけで広告を推測しない。

### LOADING

`#loaderStatusDialog` visible。

### CONTENT

上記terminal/ad/loadingでなく、rendererがready。

### UNKNOWN

どれにも安全に分類できない場合。無理にadvanceせずCoreで停止する。

## 12. wait_for_change / retry

`wait_for_change()` は次stateをboundedに確認する。

- AD / END / NEXT_CONTENT → return
- CONTENTでidentity変化 → render readyを待ってreturn
- CONTENTでidentity同一かつ最終counter → 最終ページ後の既知挙動としてreturn
- CONTENTでidentity同一 → retry可能

冒頭cover等で最初のclickが消費されるケースに備え、同一CONTENT時だけnext操作を最大2回追加retryする。

無限retryしない。

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

同一fingerprintが繰り返される場合は保存を増やし続けない。

## 14. Product metadata / naming

商品ページからviewerへ移る前に、可能なら以下を取得する。

- main title
- author block / author links
- current productと一致するseries card title
- series count
- category

キャンペーンtag `【...】` はtitleから除去する。

末尾数字はvolume候補。

```text
作品名4【電子特別版】
→ 作品名 / 第04巻
```

series countが100以上なら3桁volumeを使う。

```text
第001巻
```

categoryから現在は概ね:

- マンガ → 漫画
- 技術 → 技術書
- 雑誌 → 雑誌
- その他 → 小説

へ分類する。

命名詳細は `docs/BOOK_NAMING_RULES.md`。

## 15. Login

Real-site login/crawlは専用ChromeへCDP接続する。

`.env` の例:

```env
BOOKWALKER_URL=https://bookwalker.jp/
BOOKWALKER_EMAIL=<email>
BOOKWALKER_PASSWORD=<password>
BOOKWALKER_CDP_ENDPOINT=http://127.0.0.1:9222
```

実値はnoteへ書かない。

launcher後:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli login --site bookwalker
```

login flowは:

1. BookWalker pageへ移動
2. visibleな「ログイン」control
3. email field
4. password field
5. submit
6. post-login navigation / form消失確認

CAPTCHA / MFA / validation errorを自動突破しない。login formが残る場合は安全にerror。

## 16. Crawl command

例:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site bookwalker `
  --url "https://bookwalker.jp/de<content-id>/" `
  --output-dir output\crawl-bookwalker
```

CDP endpointは:

1. `--cdp-endpoint`
2. `BOOKWALKER_CDP_ENDPOINT`
3. default `http://127.0.0.1:9222`

の順。

`crawl` のoutput directoryは存在しないか空である必要がある。既存runへの暗黙resumeはしない。

## 17. Output / packaging

正常 `END` / `NEXT_CONTENT` 後、Coreがmanifest記載PNGだけをZIP化する。

既定:

```text
output/Books/<genre>/<title>/<title>-<volume>-<author>.zip
```

ZIP内:

```text
<archive-stem>/
├─ page-0001.png
├─ page-0002.png
└─ ...
```

manifest/progressは現在ZIPへ入れない。

completion statusは `output/crawl-status/` 配下。

中間crawl directoryは、内容がmanifest / progress / manifest記載PNGだけの場合に限り削除する。余分なPNG、diagnostics、user file等があればdirectory全体を削除しない。

失敗runは残す。

## 18. 実サイト確認済み事項

これまでのlive verificationで確認済み:

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
- 59 PNGのZIP化
- CDP dedicated Chrome workflow
- BookWalker login form操作

過去のlive checkでは、1200x900 windowでspreadを2枚 (`890x1209`, `889x1209`) に分割できた。またFull HD系viewportでdraw traceから2つのpage rectangle (`1111x1481`) を観測した。

これらの数値は観測例であり、固定capture size仕様ではない。

## 19. Known limitations / maintenance

- BookWalker DOM / Canvas rendererが変わればselector・draw trace再調査が必要。
- drawImage geometryが取れない未知作品ではcenter split fallbackになる可能性があるため、少数ページ確認を推奨。
- 直接viewer URLから開始すると商品ページmetadataがないため、title/authorが不足し `unknown-title` 等になる可能性がある。
- 同名完成ZIPが既にある場合は上書きせずerror。
- 保存dedupeがglobal fingerprint authorityなので、別ページがpixel完全一致する特殊ケースは1枚として扱われる。変更は実viewer調査後に行う。
- `config.yaml` は現在runtime loaderから利用されるauthorityではない。実Adapter Pythonを優先する。
- diagnosticsのAdapter固有metadata統合は未実装。

このnoteにはpassword、Cookie、storage state、session secretを記録しない。

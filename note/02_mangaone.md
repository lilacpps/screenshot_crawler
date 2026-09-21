# 02. Manga ONE 現行実装ノート

このファイルはManga ONE Adapterの**現在の実装詳細と実サイト観測**をまとめる。Manga ONE固有の実装・運用を変更した場合は、このnoteも同じ変更で更新する。

共通Runner / Browser Session / output / packagingの詳細は `note/00_core.md` を参照。

最終同期: 2026-09-21

## 1. 目的と現在のscope

Manga ONEのWeb viewerから、指定chapterの本文画像を順番にsource-native WebPまたはfallback PNGとして保存し、話単位ZIPとして残す。

現在対応している主な挙動:

- chapter URL parsing
- `.viewer-container` 内の本文imgだけをcapture
- Full Screen control利用
- 1ページ / 2ページspread
- 右→左の読書順
- page label / geometry / image readyによるchange wait
- bounded navigation retry
- final advance後の終端UI markerまたは画像消失をENDとして扱う既知heuristic
- chapter URL changeをNEXT_CONTENTとして停止
- title / 話数 / 前編後編のZIP naming
- CDP接続した通常Chrome上でlogin/crawl

対象chapterで話単位ZIPが生成されることを実サイト確認している。

## 2. URL / content context

chapter URL:

```text
https://manga-one.com/manga/{work_id}/chapter/{chapter_id}
```

context:

```text
work_id
chapter_id
content_id = chapter_id
episode_id = chapter_id
```

開始chapterと異なるchapter URLへ変化した場合は `NEXT_CONTENT`。

## 3. Viewer / capture target

本文は個別 `img`。

```text
.viewer-container img[alt^="page_"]
```

page label:

```text
page_0
page_1
page_2
...
```

`src` はBlob URL等になり得るため永続page identityには使わない。

Adapterはviewportと重なるready画像だけを本文候補にする。

## 4. Full Screen initialization

`initialize()` の流れ:

1. initial URL記録
2. page image群がstableになるまで待つ
3. visibleな「全画面」buttonがあればclick
4. page image群のgeometry安定を再確認
5. initial content context取得
6. page titleからoutput title / orderを抽出

Full Screen controlが見つからない場合は現在viewerを継続利用する。

## 5. Browser Session / CDP

### 採用済みの目標仕様

Manga ONE専用Chromeを標準とせず、共通Crawler Chrome/profileを使う。

```text
.chrome-crawler/
    └─ Manga ONE sessionもChrome自身が保持
```

接続はCDP、通常操作はPlaywright。

Manga ONE AdapterはChrome launch / profile / endpoint / `connect_over_cdp()` を扱わない。

### Browser Session launcher

共通launcherが標準運用である:

```powershell
.\scripts\start_crawler_chrome.ps1
```

profileは `.chrome-crawler` で、BookWalkerとlogin sessionを共存できる。site-specific launcherは現行運用に含めない。

## 6. 1ページ / spread判定

表示中のpage imgを毎回列挙し、viewportに見えているtargetだけを使う。

- visible target 1枚 → 1 artifact
- visible target 2枚 → 2 artifacts
- opening/finalで片側だけ → 1 artifact

固定中央splitや背景色推測は使わない。

## 7. Reading order

右開きviewerなのでvisible imgのx座標を降順に並べる。

```text
右: page_1
左: page_2

capture order:
page_1 -> page_2
```

## 8. Page identity

表示中labelsを右→左順で連結する。

```text
page_0
page_1|page_2
page_3|page_4
```

`page_number` は表示labelsの最大Nに1を加えた値。

```text
page_id: joined labels
page_number: max(label number) + 1
source_id: chapter_id
```

これはAdapter change detection / manifest等に使う。

**保存duplicateのauthorityはCoreのcapture SHA-256 fingerprint。**

## 9. Render stability

`_page_signature()` はvisible page群の:

```text
alt
x
y
width
height
```

を主に使う。

現行:

```text
render_stable_checks = 3
page_change_timeout_ms = 10000
```

固定sleepだけでcapture開始しない。

## 10. Navigation

次表示への主操作:

1. `.viewer-container` の左端付近をclick
2. bounding boxが取れない場合はwindow左側をmouse click

`go_next()` すると `_advance_pending = True`。

## 11. wait_for_change / retry

新しいpage rowsがありidentityが変わればrender stable後return。

同一identityが続く場合はbounded retry。

```text
advance_retry_count = 2
```

page rowsがなくなった場合は `no_page_since` を記録する。

```text
end_grace_ms = 2500
```

画像なし状態が継続すると `_ended = True`。

さらに、Manga ONE固有の終端画面markerをviewport内で検出する。markerが表示されているpollでは、終端判定が確定するまで一時的な本文imageのidentity変化やimage-gap判定へ進まず、markerの連続表示確認を優先する。

```text
img[src*="/assets/viewer/dialog/app-guidance-"]
[class*="bg-viewer-last-page"]
```

markerはDOM存在だけでなく、display/visibilityとviewportとの交差を確認する。
終端markerが `render_stable_checks` 回連続して表示された場合も `_ended = True` とする。
これは、最終本文の `page_N` imgがDOMに残ったままアプリ案内/最終案内画面へ進む実サイト挙動に対応するためである。
既存の画像消失によるEND heuristicもfallbackとして残し、identity不変だけではENDにしない。

## 12. State detection

### NEXT_CONTENT

initial URLとcurrent URLの `work_id/chapter_id` が明確に異なる場合。

### END

`_ended == True`。

### CONTENT

readyなvisible page rowsが1つ以上。

### LOADING

page selector自体は存在するがready/visible rowsがまだない場合。またviewer container visibleかつ `_advance_pending` の場合。

### UNKNOWN

viewerはあるがadvance待ちでないのにpageが取れない、またはviewer自体を安全に認識できない場合。

UNKNOWNをENDへ推測変換しない。

## 13. ENDとUNKNOWNの境界

- `go_next()` 後、viewerは残りpage imageだけ消える → grace後ENDになり得る
- `go_next()` 後、終端UI markerがviewport内に安定表示される → ENDになり得る
- 終端UI markerがDOMに存在してもviewport外にある → ENDと判定しない
- viewer自体が消えてUNKNOWNになる → timeout/error
- chapter URLが変わる → NEXT_CONTENT

「何も見えない = 常にEND」ではない。

## 14. 宣伝ページ / 終端案内

chapter末尾の宣伝/告知画像が通常本文と同じ `page_N` imgとして配信されるケースがある。

`page_N` img自体は本文capture対象として推測削除しない。一方、アプリ案内および最終案内画面にはviewer固有assetを利用した終端markerがあり、viewport内に表示された場合だけEND判定に利用する。

固定で「末尾N枚削除」はCrawler本体へ入れない。

## 15. Title / episode naming

page titleから作品名とepisode labelを抽出する。

```text
獣王と薬草 第1話 | マンガワン
→ title: 獣王と薬草
→ order: 第01話
```

```text
獣王と薬草 第80話(前編) | マンガワン
→ order: 第80話-前編
```

Adapter output metadata:

```text
title: work title
order: episode label
author: None
genre: 漫画
```

Batchで`order_key`がNULLの非定型item（例: `おまけ`、`特別編`、PR系）を実行する場合、
`order`の人間向け表記は変更せず、`Source.external_id`から作った
`mangaone-{external_id}`をarchive stem末尾のdisambiguatorとして付ける。
そのため、同じ作品の`おまけ`でもchapterごとに
`作品名-おまけ-mangaone-214131.zip`のように安定して分離される。
通常の`order_key`を持つ話、手動crawl、同じchapterの再packageは従来の命名と
destination存在時の停止動作を維持する。

## 16. Login

Manga ONE loginは実装済み。

Browser Session目標:

```text
shared Crawler Chrome/profile
→ CDP
→ Playwright Page
→ login_mangaone()
```

credentials input例:

```env
MANGAONE_URL=https://manga-one.com/login
MANGAONE_EMAIL=<email>
MANGAONE_PASSWORD=<password>
```

通常endpointは `CRAWLER_CDP_ENDPOINT`。`MANGAONE_CDP_ENDPOINT` は例外overrideとして残せる。

loginは共通Browser Sessionが作成する専用new Pageで実行し、既存の別site tabは再利用しない。login後はPageを閉じるが、shared Chrome/profileは残す。

shared launcherは指定portの既存listenerを、Chrome process command lineのremote debugging portと
`--user-data-dir=.chrome-crawler` が一致する場合だけ再利用する。一致しない、または確認できない場合は
別profile Chromeを黙って再利用せずerrorで停止する。

login flow:

1. configured login URLへgoto
2. visible email field探索
3. visible password field探索
4. fill
5. submit
6. URL change待ち
7. login form消失確認

validation error / CAPTCHA / MFA等では安全にerror。

## 17. Crawl command

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site mangaone `
  --url "https://manga-one.com/manga/2379/chapter/214131" `
  --output-dir output\crawl-mangaone
```

endpoint優先順位:

1. `--cdp-endpoint`
2. `MANGAONE_CDP_ENDPOINT`
3. `CRAWLER_CDP_ENDPOINT`
4. default `http://127.0.0.1:9222`

`CRAWLER_CDP_ENDPOINT` fallbackは実装済み。

## 18. Output / ZIP

正常 `END` / `NEXT_CONTENT` 後、Coreがmanifest記載のPNG/WebP artifactだけをZIP化する。

```text
output/Books/漫画/<title>/<title>-<order>.zip
```

BatchのManga ONE非定型itemだけは、次のようにstable disambiguatorが付く。

```text
output/Books/漫画/<title>/<title>-<order>-mangaone-<external_id>.zip
```

ZIP内部のtop-level directoryと`crawl-status`のJSON filenameも同じarchive stemを使う。

source crawl directoryは、manifest / progress / manifest記載artifact以外を含まない場合に限りcleanupされる。

## 19. Tests

Unit testsでは主に:

- chapter URL parse
- `page_N` parse
- right-to-left order
- episode title parse
- identity生成

Playwright local integration testsでは主に:

- image gapがgrace後END
- viewport内の終端UI markerが安定表示された場合のEND
- viewport外にある終端UI markerをEND扱いしない
- chapter changeがNEXT_CONTENT
- viewer/pageが不明状態ならtimeout/UNKNOWN

2026-09-17にshared `.chrome-crawler/`でManga ONE login/crawlに成功し、BookWalker sessionとの共存を確認した。
loginは既存tabを再利用せず専用new Pageで実行し、終了後はPageだけをcloseしてremote Chromeを維持した。

## 20. 実サイト確認済み事項

- chapter viewerで本文img取得
- opening single page
- left-side navigation
- spread遷移
- right→left capture order
- 前編title parse
- chapter単位ZIP生成
- final advance後のpage image disappearanceによるEND
- final advance後の終端UI markerによるEND（2026-09-18にitem=72/source=72、chapter=276852をshared Chrome/CDPのdirect crawlで19ページ保存・END停止・ZIP生成まで確認済み）

capture・navigation・page identity・END / NEXT_CONTENT・metadata behaviorに回帰はなかった。

## 21. Known limitations / maintenance

## Phase 4A Discovery (implemented)

The Manga ONE Discovery entry point is any chapter URL, for example
`https://manga-one.com/manga/2379/chapter/214131`. The adapter opens that
page and reads the chapter listing in `#chapterList` using the observed card
selector `div.cursor-pointer.block.border-b-1.border-primary.p-3`.

Cards are newest-first and are paged in batches of 10 by the `次へ` button.
The adapter waits for a changed card identity after each click. An uncertain
listing or pagination transition is incomplete rather than a successful full
scan. A card href is parsed first; the live card fallback is the observed
`/chapter/<chapter_id>.webp` image URL. The stable source identity is always
`chapter_id`, and only the target `work_id` is accepted.

Schema v3 integration keeps the observed chapter URL on the Web acquisition
route, not on `Source`: DiscoveryService upserts `source_targets` with
`backend=web`, the latest URL as `locator`, priority `100`, and enabled state.
The Batch Planner selects enabled Web targets by `(priority, id)` and the Web
Executor passes the selected locator to the existing `RunConfig.source_url`.
Other backend targets remain untouched and are not executable until an Android
backend is implemented.

`FREE`/`無料` maps to `free`, `先読み`/`先読` to `paid`, and an otherwise
unbadged card to `quota`. `free_until`, quota counts, reset times, consumption,
and `access_granted_until` are not inferred. Promotion/PR cards are not
removed by title heuristics. Records use `kind=episode`, `genre=漫画`, and a
numeric order key when the visible episode label supports one.

The minimal command is:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover `
  --key juou-to-yakusou --mode full `
  --watchlist watchlist.yaml --catalog catalog.sqlite
```

The command uses shared CDP Chrome through `BrowserSession`, closes only its
temporary Page, and leaves remote Chrome running. Phase 5A adds a read-only
Manga ONE Site Policy and Batch Planner. Phase 5B's `batch run` executes Manga
ONE candidates through the existing CrawlerRunner, with direct/quota entry,
quota local-state persistence, packaging, and completed updates.

The planner treats the Discovery mapping as follows: `free` and `owned` are
eligible with `direct`; `quota` with `access_granted_until > now` is eligible
with `direct` and does not consume a local slot; other eligible quota sources
use `quota` when a local slot remains. `paid`, `unknown`, and unavailable
sources are skipped. The policy models four site-wide local quota slots per
half-open JST window (09:00-21:00 and 21:00-next-day 09:00), counts only
Catalog `quota_started_at` values in the current window, and defines a
24-hour grant duration for Phase 5B. Planner reservations are memory-only.
Manual or external free-life consumption is not observable in Catalog, so this
is only a local eligibility estimate.

For multiple pending Manga ONE quota items, new quota consumption is allocated
from the oldest episode order first, independently of Discovery's newest-first
traversal and Catalog item IDs. Numeric `order_key` values use natural numeric
ordering; `12-前編` precedes `12-後編`, which precedes `13`. Missing or unknown
order keys use a stable label fallback and the item ID only as a final
tie-breaker. `free`, `owned`, and quota sources with an active grant remain
`direct`; active grants do not consume a new quota slot. After the older items
are allocated, the remaining quota candidates are skipped as
`quota_exhausted`. `quota_available` is the plan-start local capacity and
`quota_remaining` is the capacity after in-memory reservations.

The planning command is:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch plan `
  --site mangaone --catalog catalog.sqlite
```

The execution command is:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run `
  --site mangaone --catalog catalog.sqlite `
  --output-root output\batch --library-dir output\Books --limit 1
```

`MangaOneAdapter` accepts `auto`, `direct`, and `quota`. `auto` keeps the
manual legacy flow. `direct` never clicks the free-life entry button and
expects the viewer to be available after navigation. `quota` uses the
observed `無料ライフで読む` entry once and bounded-waits for the viewer; it
does not fall back to direct or auto when the entry is ambiguous. Batch quota
state is recorded immediately before the crawl, while completed is recorded
only after crawl and packaging succeed.

## Phase 5B quota reader entry observation (2026-09-17)

The live observation used chapter `358102` with the shared CDP Chrome profile.
The chapter page initially showed one `button` whose accessible name starts
with `無料ライフで読む` and whose subtitle was `閲覧期限 あと24時間`.
There was no open quota dialog at that point. The observed entry button was
clicked once only to reveal the post-entry DOM; no separate `ライフを使う`
affirmative button was observed. After that click, the live page exposed
`.viewer-container` with two `img[alt^="page_"]` elements and no
`dialog[open]`.

The adapter therefore scopes the quota action to the observed role=`button`
whose name starts with `無料ライフで読む`. It requires exactly one visible
match. Because the entry is mounted asynchronously after commit, it polls for
up to 2 seconds at 100ms intervals before failing closed. It performs at most
one click per run and bounded-waits for the viewer;
it never falls back to `auto` or clicks an unrelated affirmative button.
The separate confirmation-dialog flow described as a possible site state was
not observed in this session and is not guessed in the selector logic.

The fixture tests reproduce this observed entry-to-viewer transition without
accessing Manga ONE. The live observation click was not treated as a quota
consumption test; actual quota consumption and the resulting account state
were not independently verified.

## Production source-native capture implementation (2026-09-19)

The feasibility result is now implemented for Manga ONE only. `prepare_page()`
registers a Playwright response listener before navigation and keeps bounded
response references/tasks for `blob:` image bodies. `capture_page()` matches
each visible image's `currentSrc` to that response body, validates WebP/PNG
magic bytes and decoded dimensions, then returns the original bytes unchanged.
The existing right-to-left visible-image order is preserved for spreads and
opening/single-page views return one artifact.

Source-native retrieval is bounded to an initial attempt plus two retries (three
attempts total). Retries are limited to transient retrieval failures: a response
not yet registered, a body-read timeout, a temporary body-read exception, or a
body task returning `None`. A timed-out pending task is kept alive during the
retry window so a later body completion can still succeed; completed failed
body reads may create a fresh read task. Retry waits are short and bounded
(`source_response_retry_interval_ms`, currently 100 ms). Invalid image bytes,
undecodable dimensions, and a mismatch with `naturalWidth/naturalHeight` are
deterministic validation failures and do not trigger another source retrieval.

The Core change is site-neutral artifact metadata: normal Locator/canvas
captures remain PNG, while a direct Adapter result may specify MIME type and
extension. Runner filenames and manifest entries follow that result, and
packaging accepts only safe manifest-declared `.png` / `.webp` artifacts.

After the three retrieval attempts are exhausted, fallback remains per visible
image: that image alone uses the existing Locator PNG screenshot. A spread can
therefore contain a source-native artifact on one side and a PNG fallback on
the other. No Core site-name branch was added.
No quota entry button is clicked by the capture hook.

The fresh direct smoke against chapter `214131` produced `page-0001.webp` at
`720x1020`; the manifest recorded `image/webp` and `.webp`. The smoke command
was intentionally limited to one page and the existing runner then raised its
normal `max_pages` guard while trying to continue; the artifact and manifest
were written before that guard. No BookWalker file, test, or note was changed.

## Source-native capture feasibility diagnostic (2026-09-19)

以下の診断部分はfeasibility investigationとしてproduction behaviorを変更せずに実施した。
その後のproduction capture behavior実装は、このnoteの「Production source-native capture implementation」節に記録している。
変更していない。BookWalker/Coreにも変更はない。計測対象は
`https://manga-one.com/manga/2379/chapter/214131`、`lilacpps/screenshot_crawler`
の `main` HEAD `19fb8b71e1d1eb66e1b82085bf5d1cd0b766c39d` である。共有Crawler
ChromeへCDP接続し、direct閲覧だけを使用した。無料ライフ/quota入口はclickせず、
quota消費は0件だった。

診断script:

```text
scripts/diagnose_mangaone_source_resolution.py
```

最終計測はChrome window `outer 1922x1040` / viewport `1907x945`、DPR `1.5`
（画面 `2560x1441`）で行った。FHD相当のwindow条件は確認したが、4K window条件は
追加実施していない。

15枚（`page_0`〜`page_14`）を計測した。初回は1枚、以降7回は各2枚のspreadで、
visible imgは右→左の順に `page_1 -> page_2` のように独立して取得できた。
atlas/spriteではなく、各 `img` が1ページsourceに対応していた。

各sampleの結果:

```text
natural source:       720 x 1020 (15/15)
CSS rendered size:    564.7 x 800 (15/15)
current screenshot:   848 x 1200 (7), 849 x 1200 (8)
source-native PNG:    720 x 1020 (15/15)
currentSrc:           blob: (15/15)
srcset/sizes:         なし
picture:              なし
object-fit:           fill
transform/clip/filter: none / none / none
```

`currentSrc`のblob URLに対するページ内 `fetch(blob:)` は15/15で
`TypeError: Failed to fetch` になった。一方、Playwrightの同一page response
監視では、blob生成前後のsourceを取得できた。chapter-specific transportは
redacted query付きの `.../manga_page_low/214131/<n>.webp.enc` XHR
（`application/octet-stream`）で、viewerに渡ったblob responseはheaderが
`text/plain`だったが、bytesのmagic bytesは全て `image/webp` だった。
decoded source bytesは15/15で `720x1020`、`naturalWidth/naturalHeight`と一致した。

容量比較（15枚合計）:

```text
decoded WebP source bytes: 777,172 bytes
source-native PNG:       12,780,942 bytes
current locator PNG:     13,405,683 bytes
current/native PNG ratio: 1.049
```

source-native PNGは同一ページ内容を再現し、current screenshotとの目視比較で
crop、左右反転、回転、欠落領域は確認されなかった。current screenshotは
`720x1020`をDPR 1.5のbacking pixel相当の `848/849x1200` に拡大している。
従って、現行captureはsourceより情報量を増やしておらず、source-native化による
画質の新規情報増加はない。PNG出力の容量は今回のsampleでは約4.9%だけ減少する。

Full Screenについては、計測DOM上に `img[alt="full-screen"]` を含むbutton
（表示文字列 `全画面`）が存在したが、現行Adapterのexact role-name locatorは
このsessionではmatchしなかった。安全のため診断ではそのcontrolをclickせず、
前後計測は同一window条件の比較として保存した。sourceの
`naturalWidth/naturalHeight`、`currentSrc`、CSS sizeは変化しなかった。
したがって、この調査だけではFull Screen操作による別source選択は確認できず、
少なくとも現在観測されたsourceはwindow/reader表示を大きくしても
`720x1020`のままである。

### Browser fullscreen + viewer fullscreen follow-up (2026-09-19)

Chromeを別diagnostic profileで起動時browser fullscreenにした条件も確認した。
windowは `outer 2560x1440`、viewportは `2546x1346`、DPRは `1.5` で、指定chapterを
direct閲覧した。viewerの「全画面」buttonをclickする前は、sourceが
`natural 720x1020`、CSS表示が `564.7x800`、Locator screenshotが
`849x1200` であり、通常window条件と同じだった。

button click後はURLとdocument fullscreen stateは変わらなかったが、Manga ONEの
`viewer-container` と `img[alt^="page_"]` がDOMから消えた。10秒間pollしても
viewerは戻らず、button表示だけが「画面に戻る」に変化した。従って、このbrowser
fullscreen + viewer fullscreen条件ではsource-native画像のafter比較まで安全に
進められず、sourceが高解像度へ切り替わった証拠はない。これはproduction変更を
行わずに観測した診断結果であり、現行captureのfallback挙動は変更していない。

追加diagnostic artifactは `diagnostics/mangaone-browser-fullscreen/` に保存した。

結論は、Manga ONE側の配信source自体が低解像度であることが主因（Case C）で、
現行screenshotはそれをupscale保存している。source-native PNGは実装可能だが、
画質向上ではなく、upscaleを避けたsource pixel保持と小幅なPNG容量削減が効果である。
production化する場合はMangaOneAdapter内のsite-specific capture descriptorまたは
temporary native canvasで `naturalWidth x naturalHeight` に描画し、取得不能・
decode失敗・crop/transform検出時は既存Locator screenshotへfallbackする案が妥当。
Coreに `if site == mangaone` 分岐は追加しない。

診断artifactは `diagnostics/mangaone-source-native/` に保存するが、実サイト本文画像
をrepositoryのfixtureとして扱わない。production captureはこの調査後にManga ONEへ実装済みであり、現行Manga ONEの
capture behaviorはsource-native WebP優先、ページ単位PNG fallbackである。

- 末尾promotion pageがZIPへ残ることがある。
- 前編/後編統合はCrawlerで行わない。
- 話数→巻数変換はCrawlerで行わない。
- global fingerprint dedupeによりpixel完全一致別ページは1枚扱いになる。
- `config.yaml` はruntime authorityではない。
- diagnostics Adapter固有metadata統合は未実装。

このnoteにはpassword、Cookie、storage state、session secretを記録しない。

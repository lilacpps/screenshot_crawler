# 02. Manga ONE 現行実装ノート

このファイルはManga ONE Adapterの**現在の実装詳細と実サイト観測**をまとめる。Manga ONE固有の実装・運用を変更した場合は、このnoteも同じ変更で更新する。

共通Runner / Browser Session / output / packagingの詳細は `note/00_core.md` を参照。

最終同期: 2026-09-18

## 1. 目的と現在のscope

Manga ONEのWeb viewerから、指定chapterの本文画像を順番にPNG保存し、話単位ZIPとして残す。

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

- visible target 1枚 → 1 PNG
- visible target 2枚 → 2 PNG
- opening/finalで片側だけ → 1 PNG

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

正常 `END` / `NEXT_CONTENT` 後、Coreがmanifest記載PNGだけをZIP化する。

```text
output/Books/漫画/<title>/<title>-<order>.zip
```

source crawl directoryは、manifest / progress / manifest記載PNG以外を含まない場合に限りcleanupされる。

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

- 末尾promotion pageがZIPへ残ることがある。
- 前編/後編統合はCrawlerで行わない。
- 話数→巻数変換はCrawlerで行わない。
- global fingerprint dedupeによりpixel完全一致別ページは1枚扱いになる。
- `config.yaml` はruntime authorityではない。
- diagnostics Adapter固有metadata統合は未実装。

このnoteにはpassword、Cookie、storage state、session secretを記録しない。

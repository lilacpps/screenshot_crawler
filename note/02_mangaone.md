# 02. Manga ONE 現行実装ノート

このファイルはManga ONE Adapterの**現在の実装詳細と実サイト観測**をまとめる。Manga ONE固有の実装・運用を変更した場合は、このnoteも同じ変更で更新する。

共通Runner / Browser Session / output / packagingの詳細は `note/00_core.md` を参照。

最終同期: 2026-09-17

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
- final advance後の画像消失をENDとして扱う既知heuristic
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

### Legacy / compatibility launcher

共通launcherが標準運用である:

```powershell
.\scripts\start_crawler_chrome.ps1
```

profileは `.chrome-crawler` で、BookWalkerとlogin sessionを共存できる。

rollback用に旧launcherも残している:

```powershell
.\scripts\start_mangaone_chrome.ps1
```

と `.chrome-mangaone` が存在する。

これはlegacy / compatibility pathであり、旧site別profileを標準にはしない。

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

これは実サイトで動作していた既知終端heuristic。未確認generic END selectorへ置換しない。

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
- viewer自体が消えてUNKNOWNになる → timeout/error
- chapter URLが変わる → NEXT_CONTENT

「何も見えない = 常にEND」ではない。

## 14. 宣伝ページ

chapter末尾の宣伝/告知画像が通常本文と同じ `page_N` imgとして配信されるケースがある。

安定したsemantic DOM markerがないため、Adapterは推測削除しない。

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
- chapter changeがNEXT_CONTENT
- viewer/pageが不明状態ならtimeout/UNKNOWN

共通profile/CDPでの実サイトsmoke checkは未実施。

## 20. 実サイト確認済み事項

- chapter viewerで本文img取得
- opening single page
- left-side navigation
- spread遷移
- right→left capture order
- 前編title parse
- chapter単位ZIP生成
- final advance後のpage image disappearanceによるEND

共通 `.chrome-crawler/` でのlogin/crawl live verificationは未実施。site-specific adapter behaviorのlive verification記録は維持する。

## 21. Known limitations / maintenance

- 末尾promotion pageがZIPへ残ることがある。
- 前編/後編統合はCrawlerで行わない。
- 話数→巻数変換はCrawlerで行わない。
- global fingerprint dedupeによりpixel完全一致別ページは1枚扱いになる。
- `config.yaml` はruntime authorityではない。
- diagnostics Adapter固有metadata統合は未実装。
- shared `.chrome-crawler/` login/crawl live smoke test
- 旧site-specific launcher/profile削除の判断（Phase 3）

このnoteにはpassword、Cookie、storage state、session secretを記録しない。

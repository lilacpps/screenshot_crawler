# 02. Manga ONE 現行実装ノート

このファイルはManga ONE Adapterの**現在の実装詳細と実サイト観測**をまとめる。Manga ONE固有の実装・運用を変更した場合は、このnoteも同じ変更で更新する。

共通Runner / output / packagingの詳細は `note/00_core.md` を参照。

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
- 専用Chrome profile + CDP + login CLI

対象chapterで、話単位ZIPが生成されることを実サイト確認している。

## 2. URL / content context

chapter URLは概ね:

```text
https://manga-one.com/manga/{work_id}/chapter/{chapter_id}
```

query stringが追加されてもpathからIDを取得する。

例:

```text
/manga/2379/chapter/214131
```

context:

```text
work_id: 2379
chapter_id: 214131
content_id: 214131
episode_id: 214131
```

開始chapterと異なるchapter URLへ変化した場合は `NEXT_CONTENT`。

## 3. Viewer / capture target

本文はCanvasではなく個別 `img`。

現在のselector:

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

`src` はruntimeでBlob URL等になり得るため、永続page identityとしては使わない。

Adapterはviewportと重なるready画像だけを本文候補にする。

ready条件には概ね:

- rect width / height > 0
- viewportとoverlap
- `element.complete`
- `naturalWidth > 0`

を使う。

## 4. Full Screen initialization

`initialize()` の流れ:

1. initial URL記録
2. 最初のpage image群がstableになるまで待つ
3. visibleな「全画面」buttonがあればclick
4. もう一度page image群のgeometry安定を待つ
5. initial content context取得
6. page titleからoutput title / orderを抽出

Full Screen controlが見つからない場合は、そこで即失敗せず現在viewerを継続利用する。

## 5. Browser / CDP

専用Chrome launcher:

```powershell
.\scripts\start_mangaone_chrome.ps1
```

現在のlauncherは:

```text
--window-size=1920,1080
--user-data-dir=.chrome-mangaone
--remote-debugging-port=<Port>
```

を使う。

`.chrome-mangaone` は `.chrome-*` としてgitignore対象。

注意: BookWalker launcherとManga ONE launcherは現在どちらもdefault port `9222`。すでにそのportでCDP Chromeが動いている場合、launcherは既存listenerを利用する旨を表示して終了する。site専用profileを同時に別々に起動する場合は、portを明示的に分ける必要がある。

Real-site `crawl` は既存ChromeへCDP接続するため、`crawl --headed` は現在の有効CLIではない。headed/native launch optionは主に `probe` 側。

## 6. 1ページ / spread判定

表示中のpage imgを毎回列挙し、viewportに見えているtargetだけを使う。

- visible targetが1枚 → 1 PNG
- visible targetが2枚 → 2 PNG
- opening/finalで片側だけ → 1 PNG

固定の中央splitや背景色推測は使わない。

## 7. Reading order

右開きviewerなので、visible imgのx座標を降順に並べる。

例:

```text
右: page_1
左: page_2

capture order:
page_1 -> page_2
```

Coreへはこの順でLocator tupleを返す。

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

これはAdapterのchange detection / manifest等に使う。

**保存duplicateのauthorityはCoreのcapture SHA-256 fingerprint。** Identityが異なってもPNG bytesが同一なら保存duplicateとして扱われる。

## 9. Render stability

`_page_signature()` はvisible page群について、主に:

```text
alt
x
y
width
height
```

をtuple化する。

`_wait_for_render_ready()` はsignatureが連続で安定することを要求する。

現行:

```text
render_stable_checks = 3
page_change_timeout_ms = 10000
```

固定sleepだけでcapture開始しない。

## 10. Navigation

次表示への主操作:

1. `.viewer-container` の左端付近をclick
2. bounding boxが取れない/操作できない場合はwindow左側をmouse click

右開きreaderの次ページ操作として左側を使う。

`go_next()` すると `_advance_pending = True`。

## 11. wait_for_change / retry

前identityがある場合、timeout内でvisible page rowsを監視する。

### 新しいpage rowsがある

current identityがprevious identityと異なれば:

1. render stableを待つ
2. `_advance_pending = False`
3. return

同一identityが続く場合、bounded retryで `go_next()` を再実行する。

現行:

```text
advance_retry_count = 2
```

### page rowsがない

`no_page_since` を記録する。

画像なし状態が:

```text
end_grace_ms = 2500
```

継続すると `_ended = True` とし、ENDとして扱う。

これはManga ONE実サイトで動作していた既知の終端heuristicを維持したもの。実DOM未確認のgeneric END selectorへ置き換えない。

## 12. State detection

### NEXT_CONTENT

initial URLとcurrent URLの `work_id/chapter_id` が明確に異なる場合。

### END

`_ended == True`。

`_ended` はfinal advance後等にpage imageが `end_grace_ms` 継続して消失した際に設定される。

### CONTENT

readyなvisible page rowsが1つ以上ある。

### LOADING

page selector自体は存在するがready/visible rowsがまだない場合。

またviewer containerはvisibleで `_advance_pending` の場合もLOADING。

### UNKNOWN

viewerはあるがadvance待ちでないのにpageが取れない、またはviewer自体を安全に認識できない場合。

UNKNOWNをENDへ推測変換しない。

## 13. ENDとUNKNOWNの境界

重要:

- `go_next()` 後、viewerは残りpage imageだけ消える → grace後ENDになり得る
- viewer自体が消えてUNKNOWNになる → `wait_for_change()` はtimeoutしてerror
- chapter URLが変わる → NEXT_CONTENT

つまり「何も見えない = 常にEND」ではない。

## 14. 宣伝ページ

chapter末尾の宣伝/告知画像が通常本文と同じ `page_N` imgとして配信されるケースがある。

現在、安定したsemantic DOM markerがないため、Adapterは推測削除しない。

そのため話単位ZIPには末尾promotion pageが含まれる場合がある。

固定で「末尾2枚削除」等はCrawler本体へ入れていない。

## 15. Title / episode naming

page titleから作品名とepisode labelを抽出する。

例:

```text
獣王と薬草 第1話 | マンガワン
→ title: 獣王と薬草
→ order: 第01話
```

```text
獣王と薬草 第80話(前編) | マンガワン
→ title: 獣王と薬草
→ order: 第80話-前編
```

全角/半角括弧の前編・後編に対応。

Adapter output metadata:

```text
title: work title
order: episode label
author: None
genre: 漫画
```

## 16. Login

Manga ONE loginは**現在実装済み**。

`.env` 例:

```env
MANGAONE_URL=https://manga-one.com/login
MANGAONE_EMAIL=<email>
MANGAONE_PASSWORD=<password>
MANGAONE_CDP_ENDPOINT=http://127.0.0.1:9222
```

実値はnoteへ書かない。

専用Chrome起動後:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli login --site mangaone
```

login flow:

1. configured login URLへgoto
2. visible email field探索
3. visible password field探索
4. fill
5. login form内submit button click
6. URL change待ち
7. login formが残っていないことを確認

validation error / CAPTCHA / MFA等でformが残る、またはURLが変わらない場合は安全にerror。

## 17. Crawl command

例:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site mangaone `
  --url "https://manga-one.com/manga/2379/chapter/214131" `
  --output-dir output\crawl-mangaone
```

CDP endpointは:

1. `--cdp-endpoint`
2. `MANGAONE_CDP_ENDPOINT`
3. default `http://127.0.0.1:9222`

の順。

新規output directoryは存在しないか空でなければならない。

## 18. Output / ZIP

正常 `END` / `NEXT_CONTENT` 後、Coreがmanifest記載PNGだけをZIP化する。

既定:

```text
output/Books/漫画/<title>/<title>-<order>.zip
```

例:

```text
output/Books/漫画/獣王と薬草/獣王と薬草-第80話-前編.zip
```

ZIP内:

```text
獣王と薬草-第80話-前編/
├─ page-0001.png
├─ page-0002.png
└─ ...
```

manifest / progressは現在ZIPへ含めない。

source crawl directoryは、manifest / progress / manifest記載PNG以外を含まない場合に限りcleanupされる。

余分なPNG、diagnostics、user file等があればdirectory全体を削除しない。

## 19. Tests

Unit testsでは主に:

- chapter URL parse
- `page_N` parse
- right-to-left order
- episode title parse
- identity生成

を確認する。

Playwright local integration testsでは主に:

- image gapがgrace後ENDになる
- chapter changeがNEXT_CONTENT
- viewer/pageが不明状態ならtimeout/UNKNOWN

を固定する。

固定の `pytest: N passed` はnoteへ現在値として残さない。変更後は実際に `pytest -q` / `ruff check src tests` を実行し、作業報告へ結果を書く。

## 20. 実サイト確認済み事項

これまでに確認した主な事項:

- chapter viewerで本文imgを取得できる
- opening single page
- left-side navigation
- spreadへ遷移
- right→left capture order
- 前編titleから `第80話-前編` を生成
- chapter単位ZIP生成
- 最終advance後のpage image disappearanceによるEND方式で動作

site DOM/classが変われば再調査が必要。

## 21. Known limitations / maintenance

- 末尾promotion pageを本文と確実に区別できないためZIPへ残ることがある。
- 前編/後編の統合はCrawlerでは行わない。
- 話数→巻数変換はCrawlerでは行わない。
- 保存dedupeがglobal fingerprint authorityなので、別ページがpixel完全一致する特殊ケースは1枚として扱われる。
- `config.yaml` は現在runtime loaderのauthorityではなく、Adapter Pythonが実挙動のauthority。
- BookWalker/Manga ONE launcherはdefault CDP portが同じため、同時にsite別profileを立ち上げる場合はport管理が必要。
- diagnosticsのAdapter固有metadata統合は未実装。

このnoteにはpassword、Cookie、storage state、session secretを記録しない。

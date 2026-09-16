# 00. Core 現行実装ノート

このファイルは、Screenshot Crawler Coreの**現在の実装詳細**をまとめる。Core / Runner / browser / output / packaging / diagnostics / resume方針を変更した場合は、このnoteも同じ変更で更新する。

最終同期: 2026-09-17

## 1. Scope

Coreはサイト固有DOMやページ送りを判断しない。共通処理を担当する。

主な責務:

- Playwright browser/context接続補助
- URL navigation
- Site Adapter呼び出し
- PageState loop
- capture / PNG保存
- SHA-256 fingerprint
- duplicate / same-content guard
- manifest / progress
- diagnostics
- max_pages / retry / timeout
- 正常終了後のZIP packaging

Site固有selector、END判定、NEXT操作は `site_adapters/<site>/` の責務。

## 2. Main modules

```text
src/screenshot_crawler/core/
├─ browser.py       browser launch / CDP connection / context
├─ capture.py       Locator / canvas capture, PNG save
├─ diagnostics.py   screenshot / HTML / metadata / error
├─ errors.py        crawler errors
├─ fingerprint.py   SHA-256
├─ models.py        RunConfig / identity / context / captured page
├─ packaging.py     manifest-based ZIP / library output
├─ progress.py      manifest / progress / new-run safety
├─ runner.py        state machine
└─ state.py         PageState
```

`site_adapters/base.py` がAdapter contract。

## 3. Browser / CDP

Coreには通常launch/context作成もあるが、現行のreal-site `crawl` / `login` CLIは既存ChromeへCDP接続する。

理由:

- 通常Chromeのlogin/sessionを維持できる
- viewer固有のbrowser挙動を保ちやすい
- crawl終了時にChrome本体を閉じず、Crawlerが作ったtabだけを閉じられる

現行CLIのCDP endpointは、引数 → site別 `.env` → `http://127.0.0.1:9222` の順で解決する。

BookWalker / Manga ONEとも専用profile launcherがあり、profile directoryは `.chrome-*` としてgitignoreされる。

## 4. PageState loop

PageState:

```text
CONTENT
AD
END
NEXT_CONTENT
LOADING
UNKNOWN
```

Runner概念フロー:

```text
ensure output dir is new/empty
prepare_page
page.goto
adapter.initialize
initial context
ProgressStore作成

loop:
    detect state

    END / NEXT_CONTENT
        -> normal return

    UNKNOWN
        -> error + diagnostics

    AD
        -> go_next + wait_for_change

    CONTENT
        -> max_pages guard
        -> context確認
        -> identity取得
        -> one/multiple capture targets取得
        -> capture
        -> fingerprint dedupe
        -> PNG + manifest/progress保存
        -> go_next + wait_for_change
```

LOADINGはbounded retryし、解消しなければ `PageChangeTimeoutError`。

## 5. max_pages

`max_pages` は保存ページ数の安全上限。

重要な境界仕様:

- `saved == max_pages` のあと次stateが `END` / `NEXT_CONTENT` → 正常終了
- `saved == max_pages` のあとさらに `CONTENT` → `MaxPagesExceededError`
- `max_pages`を超えるPNGは保存しない

この順序は「実ページ数とmax_pagesが同じ本」を異常終了させないために必要。

## 6. Identity / fingerprint / duplicate

`ContentIdentity` はpage id / page number / source id等を保持し、主に以下に使う。

- Adapterのchange detection
- manifest記録
- debug / progress情報

**保存duplicateのauthorityはcapture bytesのSHA-256 fingerprint。**

現行Runnerは、すでに保存済みのfingerprintと同じcaptureを再保存しない。identityが異なっていてもfingerprintが同一ならduplicate扱い。

これはBookWalker / Manga ONEで動いていた既存挙動を維持するための現行仕様。identity優先dedupeへ変更する場合は、実viewerで連続spreadや重なり遷移を観測してから設計する。

複数capture targetのspreadでは各targetごとにfingerprintを計算する。

## 7. same-content guard

新しいcaptureが得られない状態が続いた場合は `same_content_count` を増やす。

既定 `max_same_content = 3`。

上限到達で `PageChangeTimeoutError` として停止し、同じ内容を無限保存/進行しない。

## 8. Context / NEXT_CONTENT

開始時 `ContentContext` と現在contextのstrong fieldを比較する。

strong fields:

- content_id
- work_id
- episode_id
- chapter_id

同じfieldが開始時・現在とも存在し、値が変わった場合だけcontext changeとする。

optional情報が後から埋まっただけではNEXT_CONTENTにしない。

## 9. Capture

基本はLocator単位capture。

Canvas targetの場合、`capture.py` はcanvasのraw PNG bufferを取得できる。これにより画面UIやbrowser chromeを避ける。

Adapterは `get_capture_targets()` で複数targetを返せる。保存順はAdapterが返した順。

一時targetを作るAdapterは `cleanup_capture_targets()` で後始末する。

## 10. Run output safety

新規runの `output_dir` は、存在しないか完全に空でなければならない。

既存ファイルが1つでもある非空directoryは `RunAlreadyExistsError` で拒否する。

目的:

- 前runのPNG混入防止
- manifest/progress上書き防止
- user file削除防止

`ProgressStore` も既存manifest/progressを暗黙上書きしない。

## 11. Manifest / progress

実行中:

```text
<output_dir>/
├─ page-0001.png
├─ page-0002.png
├─ manifest.json
├─ progress.json
└─ diagnostics/  # failure時に作られる場合あり
```

manifestは保存ページ一覧のauthority。

各pageには概ね以下を記録する。

- sequence
- page_number
- file
- width / height
- fingerprint
- identity
- metadata (`part` / `parts` 等)

`progress.json` はlast sequence / identity / fingerprint / contextを持つが、**自動resume機能ではない**。

JSON更新はtemporary file → `os.replace`。

## 12. Resume

現行v1.1ではresume未実装。

- 非空run dirは拒否
- 既存manifest/progressを読み込んで続行しない
- 暗黙resumeしない

将来追加するなら、`--resume` 等で新規runと明示的に分離する。

## 13. Packaging

正常な `END` / `NEXT_CONTENT` 後だけZIP化する。

ZIP対象はdirectory globではなく、`manifest.json` の `pages[].file` がauthority。

安全ルール:

- manifest外PNGをZIPへ入れない
- manifest記載PNGが欠けていればfail
- absolute path / traversal / unsafe pathを拒否
- 同じfileをmanifestに重複指定できない
- 既存同名ZIPは上書きしない

ZIPはlibrary treeへ保存し、completion status JSONを別途残す。

## 14. Intermediate directory cleanup

ZIP作成後、source crawl directoryを削除するのは、directory内容が次だけの場合に限る。

- `manifest.json`
- `progress.json`
- manifestに記載されたpage PNG

余分なPNG、diagnostics、user file、その他directoryがあればsource全体を `rmtree` しない。

失敗runは調査用に残す。

## 15. Diagnostics

Runnerの通常エラー時はbest-effortでdiagnosticsを書く。

現在の `write_diagnostics()` が保存するもの:

```text
screenshot.png
page.html
metadata.json
error.txt
```

metadataにはURL、title、viewport、Runnerから渡されたstate/context/saved count、error type等が入る。

既知の制約:

- diagnostics pathはrun-specific subdirectoryを自動生成しない
- `SiteAdapter.collect_debug_metadata()` hookはcontractにあるが、現行Runnerではまだ統合していない
- diagnostics保存失敗は元例外を隠さない

Adapter固有debug metadata統合は今後の改善候補。

## 16. CLI / packaging flow

Real-site crawlの概念:

```text
CLI
 -> AdapterRegistry
 -> CDP connect
 -> new page
 -> CrawlerRunner.run
 -> END / NEXT_CONTENT
 -> crawler tab close
 -> package_crawl_output
 -> remote Chromeは残す
```

主なcrawl引数:

```text
--site
--url
--output-dir
--diagnostics-dir
--library-dir
--max-pages
--max-same-content
--env-file
--cdp-endpoint
--keep-open
```

`crawl` には `--headed` はない。headed/native launch optionsは主に `probe` 側。

## 17. Tests

Unit testsで主に確認するもの:

- fingerprint
- capture
- Runner guards
- max_pages境界
- duplicate / same-content
- progress safety
- packaging / manifest validation
- site parser/helper

Playwright local integration testsで主に確認するもの:

- CONTENT → CONTENT → END
- AD skip
- NEXT_CONTENT
- LOADING
- UNKNOWN
- spread
- max_pages境界
- Manga ONE終端heuristic

Chromiumが利用できない環境ではintegrationがskipされるため、pytestのpassed/skipped件数も確認する。

## 18. Known maintenance items

現時点の主な未実装/整理候補:

- explicit resume
- Adapter `collect_debug_metadata()` のRunner統合
- diagnostics run directory分離
- config.yamlを実際に使うか削除するかの整理
- identity/fingerprint dedupe方式の再検討
- GitHub CI
- tracked `.egg-info` の整理

これらを変更した場合は、このnoteを必ず更新する。

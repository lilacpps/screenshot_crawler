# Architecture

## 1. 設計原則

依存方向を単純に保つ。

目標architecture:

```text
Dedicated Crawler Chrome
    └─ shared profile (.chrome-crawler/)
            ↑
            │ CDP
            ↓
Browser Session Layer
    └─ Playwright Browser / BrowserContext / Page
            ↓
Core Runner / packaging
            ↓
Site Adapter
    └─ Playwright Page / Locator
```

重要な分離:

- **CDP**: Chrome sessionへ接続するためのtransport
- **Playwright**: navigation / DOM / click / wait / capture等の標準操作API
- **Site Adapter**: site固有viewer logic

Raw CDP Protocolを通常のsite操作APIにはしない。

## 2. ディレクトリ責務

### `core/`

サイト非依存ロジック。

- `models.py`: 共通データ構造
- `state.py`: PageState
- `browser.py`: Playwright lifecycle / CDP接続 / Browser Session補助
- `runner.py`: 状態ループ
- `capture.py`: capture / PNG保存
- `fingerprint.py`: SHA-256
- `progress.py`: manifest / progressと新規run安全確認
- `diagnostics.py`: 異常時情報
- `packaging.py`: manifest基準のZIP/library出力
- `errors.py`: 独自例外

### `site_adapters/`

サイト固有差分。

- `base.py`: Adapter contract
- `registry.py`: site名→Adapter
- `<site>/adapter.py`: サイト固有実装
- `<site>/login.py`: 必要な場合のsite固有login DOM操作
- `<site>/README.md`: 実観測、終了挙動、制約、確認記録
- `<site>/config.yaml`: 実装が明示的に読み込む場合のみ設定として有効

現行real adaptersでは、複雑なselector/state/timeoutはPython Adapter実装がauthorityである。未使用YAMLとPythonを二重authorityにしない。

### `patterns/`

再利用可能な表示方式の補助部品。必須frameworkではない。

### `probe/`

新規サイト調査用。

## 3. Browser Session Layer

Browser Session Layerは、site固有logicの外側で以下を担当する。

- CDP endpoint解決
- 既存Crawler Chromeへ `connect_over_cdp()`
- BrowserContext取得
- Crawler用Page作成
- Crawlerが作成したPageだけclose
- remote Chrome processをCrawler終了時にcloseしない

Site Adapterはこのlayerを知らない。

Adapterへ渡る時点では単なるPlaywright `Page` であり、そのPageがlaunch済みbrowser由来かCDP由来かをAdapterは判断しない。

## 4. 共通Crawler Chrome / profile

Real-site automationの標準は1つのCrawler Chromeと共通profile。

目標:

```text
.chrome-crawler/
├─ bookwalker.jp のCookie / storage
├─ manga-one.com のCookie / storage
└─ その他siteのCookie / storage
```

これは論理的な説明であり、実際のChrome profile filesystem構造をCrawlerが直接管理するという意味ではない。

認証状態のauthorityはChrome profile。CrawlerはCookieやstorage stateをsite別JSONへ複製して標準管理しない。

profile directoryはrepositoryへcommitしない。

## 5. Endpoint resolution

目標のCDP endpoint優先順位:

```text
--cdp-endpoint
    ↓
<SITE>_CDP_ENDPOINT
    ↓
CRAWLER_CDP_ENDPOINT
    ↓
http://127.0.0.1:9222
```

通常は `CRAWLER_CDP_ENDPOINT` またはdefaultだけで全siteを扱う。

site-specific endpointは例外用:

- 別accountが必要
- extension / browser settingが違う
- sessionを分離したい
- 共通profileではsiteが正常動作しない

例外を標準設計へ昇格させない。

## 6. Playwrightを標準操作APIとする

CDPで接続した後も通常操作はPlaywrightで行う。

```python
page.goto(...)
page.locator(...)
locator.click()
page.wait_for_function(...)
locator.screenshot(...)
page.evaluate(...)
```

Raw CDP ProtocolはPlaywrightに適切なAPIがない場合のみBrowser Session/Coreの小さいhelperへ隔離する。

Site Adapterへ低レベルCDP session操作を広げない。

## 7. Authentication

login CLIはBrowser Session Layerから既存Crawler ChromeのPageを受け取り、site固有login functionがPlaywrightでDOM操作する。

```text
Crawler Chrome/profile
    ↓ CDP
Playwright Page
    ↓
login_bookwalker / login_mangaone / future login handler
```

認証情報のinputは `.env` 等から取得してよいが、login後sessionの保存はChrome profileへ任せる。

Crawler独自のsite別auth-state fileは標準経路にしない。

CAPTCHA / MFA / validation errorは自動突破しない。

## 8. Runnerの概念フロー

```text
ensure output directory is new/empty
Browser SessionからPageを取得
prepare page
open URL
adapter.initialize
initial context
create manifest/progress

loop:
    state = adapter.detect_state

    END/NEXT_CONTENT:
        stop normally

    UNKNOWN:
        diagnostics + error

    AD:
        go_next + bounded wait

    CONTENT:
        enforce max_pages before additional capture
        validate context
        get identity
        get one or more capture targets
        capture
        SHA-256 fingerprint dedupe
        save PNG + manifest/progress
        go_next + bounded wait

normal terminal:
    crawler Pageをclose
    package output
    Crawler Chrome自体は残す
```

`max_pages`到達後も、次stateがEND/NEXT_CONTENTなら正常終了できる。

## 9. Duplicateの考え方

現行Runnerはcapture fingerprintを保存重複判定authorityにする。ContentIdentityはAdapterのchange detection、manifest、debug情報として重要だが、保存dedupeをidentity優先へ変更しない。

この判断はBookWalker/Manga ONEの既知挙動維持を優先したもの。変更する場合はreal viewerの連続spread/遷移を先に観測する。

## 10. Output / packaging

manifestのページ一覧を完成成果物のauthorityとする。packagingでdirectory globをauthorityにしない。

新規runは非空output directoryを拒否する。正常packaging後も、無関係ファイルが含まれるdirectoryは丸ごと削除しない。

## 11. Site Adapterの最小契約

概念上:

```python
prepare_page(page)
initialize(page)
detect_state(page)
get_capture_target(page)
get_capture_targets(page)
cleanup_capture_targets(page)
get_content_identity(page)
get_content_context(page)
go_next(page)
wait_for_change(page, previous_identity)
```

実際のdefault method / optional hookは `site_adapters/base.py` をauthorityとする。

Adapterは以下をしない。

```text
Chrome launch
profile選択
CDP endpoint解決
connect_over_cdp
BrowserContext lifecycle管理
```

## 12. Site固有の終了判定

終了方法は共通化しすぎない。

- BookWalkerはviewer DOM / page counter / known final transitionを使う
- Manga ONEはchapter URL changeと、最終advance後にpage imagesが一定時間消失する既知挙動を使う

「明示END DOMがなければENDにしない」のような一般ルールで、実サイト確認済み挙動を置換しない。

## 13. Safety

別コンテンツや無関係ファイルを誤処理するより停止を優先する。

- UNKNOWNは停止
- retryはbounded
- 非空run dirは拒否
- resumeは暗黙実行しない
- packagingはmanifestをauthorityにする
- Coreへsite-specific ifを追加しない
- Adapterへbrowser/session管理を入れない

## 14. 移行状態

このarchitectureは採用済みの目標仕様。

ドキュメント更新時点では、実装にはsite別launcher/profile (`.chrome-bookwalker`, `.chrome-mangaone`) が残っている。次の実装変更で共通 `start_crawler_chrome.ps1` / `.chrome-crawler/` / global endpointへ移行する。

移行時もBookWalker/Manga ONEのviewer/capture/END判定は原則変更しない。Browser Session Layerだけを差し替える。

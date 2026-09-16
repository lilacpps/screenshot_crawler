# Architecture

## 1. 設計原則

依存方向を単純に保つ。

```text
CLI / orchestration
    ↓
Core contracts / Runner / packaging
    ↓
Site Adapter
    ↓
Playwright Page
```

`site_adapters/` は `core/` の型を利用してよい。`core/` は個別サイトAdapterやselectorをimportしない。Adapter解決はregistry / CLI層で行う。

## 2. ディレクトリ責務

### `core/`

サイト非依存ロジック。

- `models.py`: 共通データ構造
- `state.py`: PageState
- `browser.py`: Playwright lifecycle / CDP接続補助
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
- `<site>/README.md`: 実観測、終了挙動、制約、確認記録
- `<site>/config.yaml`: 存在しても自動的にauthorityにはならない。実装が明示的に読み込む場合のみ設定として有効

現行のreal adaptersでは、複雑なselector/state/timeoutはPython Adapter実装がauthorityである。未使用YAMLとPythonを二重authorityにしない。

### `patterns/`

再利用可能な表示方式の補助部品。必須frameworkではない。

### `probe/`

新規サイト調査用。

## 3. Browser / authentication

Coreには通常launch/context管理もあるが、現行real-site crawl/login CLIは既存ChromeへCDP接続する。

理由:

- 通常Chromeのlogin/sessionを維持しやすい
- viewer固有の通常browser挙動を壊しにくい
- crawler終了時にremote Chrome自体を終了しない

Siteごとの専用Chrome profileはrepositoryにcommitしない。

## 4. Runnerの概念フロー

```text
ensure output directory is new/empty
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
```

`max_pages`到達後も、次stateがEND/NEXT_CONTENTなら正常終了できる。

## 5. Duplicateの考え方

現行Runnerはcapture fingerprintを保存重複判定authorityにする。ContentIdentityはAdapterのchange detection、manifest、debug情報として重要だが、保存dedupeをidentity優先へ変更しない。

この判断はBookWalker/Manga ONEの既知挙動維持を優先したもの。変更する場合はreal viewerの連続spread/遷移を先に観測する。

## 6. Output / packaging

manifestのページ一覧を完成成果物のauthorityとする。packagingでdirectory globをauthorityにしない。

新規runは非空output directoryを拒否する。正常packaging後も、無関係ファイルが含まれるdirectoryは丸ごと削除しない。

## 7. Site Adapterの最小契約

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

## 8. Site固有の終了判定

終了方法は共通化しすぎない。

- BookWalkerはviewer DOM / page counter / known final transitionを使う
- Manga ONEはchapter URL changeと、最終advance後にpage imagesが一定時間消失する既知挙動を使う

「明示END DOMがなければENDにしない」のような一般ルールで、実サイト確認済み挙動を置換しない。

## 9. Safety

別コンテンツや無関係ファイルを誤処理するより停止を優先する。

- UNKNOWNは停止
- retryはbounded
- 非空run dirは拒否
- resumeは暗黙実行しない
- packagingはmanifestをauthorityにする
- Coreへsite-specific ifを追加しない

# Architecture

## 1. 設計原則

依存方向を単純に保つ。

```text
CLI / Runner
    ↓
Core contracts
    ↓
Site Adapter
    ↓
Playwright Page
```

`site_adapters/` は `core/` の型を利用してよい。

`core/` は個別サイトのAdapterやselectorをimportしてはならない。Adapter解決はregistryまたはCLI層で行う。

## 2. ディレクトリ責務

### `core/`

サイトに依存しない共通ロジック。

- `models.py`: 共通データ構造
- `state.py`: 状態列挙と遷移補助
- `browser.py`: Playwright lifecycle
- `runner.py`: メインループ
- `capture.py`: 保存処理
- `fingerprint.py`: hash / fingerprint
- `progress.py`: manifest / progress
- `diagnostics.py`: 異常時情報保存
- `errors.py`: 独自例外

### `site_adapters/`

サイト固有差分。

- `base.py`: Adapter抽象インターフェース
- `registry.py`: site名→Adapterの解決
- `<site>/adapter.py`: サイト固有実装
- `<site>/config.yaml`: 単純なselectorやtimeoutなど
- `<site>/README.md`: 調査結果・最終ページ挙動・確認日

### `patterns/`

再利用可能な「表示方式」の補助コード。継承階層を深くしない。Site Adapterが必要な関数だけ利用する。

### `probe/`

新規サイトの観察・診断情報取得。

## 3. なぜSite Adapterを独立させるか

サイト差分はDOMだけではない。

- 広告の入り方
- 次ページ操作
- 見開き/単ページ
- 最終ページ後の画面
- SPAでURLが変わらない
- 次話へ自動遷移

これらをCoreのif文で吸収すると、追加サイトごとに回帰リスクが上がる。

## 4. なぜ設定ファイルだけにしないか

単純selectorはYAMLに置けるが、状態判定や特殊なページ送りを設定だけで表現しようとすると独自DSL化する。

原則:

- データはYAML
- 条件分岐・操作はPython

## 5. Adapterの最小契約

Adapterは以下を実装する。

```python
initialize(page)
detect_state(page)
get_capture_target(page)
get_content_identity(page)
get_content_context(page)
go_next(page)
wait_for_change(page, previous_identity)
```

詳細は `site_adapters/base.py` を参照。

## 6. Runnerの概念フロー

```text
launch browser
open URL
adapter.initialize
initial_context = adapter.get_content_context

loop:
    state = adapter.detect_state

    CONTENT:
        identity = adapter.get_content_identity
        duplicate check
        capture
        save manifest/progress
        adapter.go_next
        adapter.wait_for_change

    AD:
        adapter.go_next
        adapter.wait_for_change

    LOADING:
        wait/retry

    END/NEXT_CONTENT:
        stop normally

    UNKNOWN:
        save diagnostics
        stop with error
```

## 7. Patternの扱い

Patternは「Adapterを薄くするための便利関数」であり、必須の継承基盤ではない。

例:

- imgのsrcをidentityとして取得する
- canvasのPNGをhash化する
- background-image URLを取得する

Adapterが特殊なら直接Pythonで書いてよい。

## 8. 安全側に倒す

誤って別コンテンツを大量保存するより、UNKNOWNで停止する方を優先する。

特に「最終ページ→広告→次話」はCoreが推測せず、Adapterのcontent context判定で止める。

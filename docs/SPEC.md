# Screenshot Crawler 仕様書 v1.1

## 1. 目的

特定のWebビューアにアクセスし、現在コンテンツを1ページずつ進めながら本文だけをPNGとして保存する。

サイトごとに本文描画、ページ送り、広告、最終ページ後の挙動、次コンテンツ遷移が異なるため、完全自動判定は目的にしない。共通エンジンとSite Adapterを分離する。

## 2. 技術

- Python 3.12+
- Playwright Python
- Chromium / Chrome CDP
- asyncio
- PNG出力
- Windowsを主対象

## 3. 入力とBrowser

Crawler本体はURLを収集しない。URLは人手または別プログラムから渡す。

```bash
python -m screenshot_crawler.cli crawl --site <site> --url "https://..."
```

新規サイト調査:

```bash
python -m screenshot_crawler.cli probe --url "https://..."
```

CoreにはPlaywright browser/context管理機能がある。現行の実サイト `crawl` / `login` CLIは、ログイン済み通常Chromeのsessionを維持するためCDP接続を使用する。Probeは通常launchとCDP接続の両方を利用できる。

## 4. PageState

- `CONTENT`: 保存対象本文
- `AD`: 保存対象外の中間画面
- `END`: 現在コンテンツの終了
- `NEXT_CONTENT`: 次話・次章・別コンテンツ
- `LOADING`: 描画途中
- `UNKNOWN`: 安全に判定できない

`UNKNOWN` は無理に突破せずdiagnosticsを残して停止する。

## 5. Coreの責務

- browser/context接続補助
- URLアクセス
- Site Adapter呼び出し
- 状態ループ
- 保存連番
- capture / PNG保存
- SHA-256 fingerprint
- 重複防止
- bounded retry / timeout
- manifest / progress
- diagnostics
- `max_pages` / same-content guard
- 正常終了後のpackaging

Coreはサイト固有DOM、next操作、広告、終了、次コンテンツを推測しない。

## 6. Site Adapterの責務

- `prepare_page`
- `initialize`
- `detect_state`
- `get_capture_target` / `get_capture_targets`
- `cleanup_capture_targets`
- `get_content_identity`
- `get_content_context`
- `go_next`
- `wait_for_change`
- 必要に応じたoutput metadata

詳細は `site_adapters/base.py` をauthorityとする。

## 7. Capture

本文DOM Locatorを優先する。Canvasではraw PNG bufferを利用できる。見開きなど1画面に複数ページがある場合、Adapterは複数capture targetを読書順で返してよい。

保存連番とサイト上のページ番号は別物とする。

## 8. ContentIdentity / fingerprint

`ContentIdentity` はAdapterが取得できるpage id / page number / source id等を保持し、ページ変更待ちや記録に利用する。

現行Runnerの**保存重複判定authorityはcapture bytesのSHA-256 fingerprint**である。同一fingerprintは、identityが異なっていても重複captureとして保存しない。

これは既存BookWalker/Manga ONEで確認済みの挙動を維持するためのv1仕様であり、identity優先dedupeへの変更は実サイト遷移を確認してから別途行う。

fingerprintだけを終了条件にはしない。

## 9. ContentContext

開始作品・話・章を識別する。

- content_id
- work_id
- episode_id
- chapter_id
- title

開始時と現在の同一strong fieldが明確に異なる場合、`NEXT_CONTENT` として正常終了できる。後からoptional fieldが追加されたことだけではcontext changeにしない。

## 10. 広告

`AD` は保存しない。広告表示自体は終了条件ではない。

```text
CONTENT → AD → CONTENT
CONTENT → AD → END
CONTENT → AD → NEXT_CONTENT
```

## 11. 終了条件

`END` / `NEXT_CONTENT` の判定ロジックはSite Adapterに置く。サイト固有の実観測挙動を優先する。

例:

- BookWalker: end DOM、next-content DOM、最終page counter後の既知遷移
- Manga ONE: chapter URL changeは `NEXT_CONTENT`。最終advance後にviewer page imageが一定時間消失する既知挙動を `END` の実用的ヒューリスティックとして利用

一般的な「明示END DOMが必須」という要件は置かない。

異常停止:

- `UNKNOWN`
- `max_pages`を超えてさらにCONTENTが続く
- same-content guard到達
- timeout
- Adapter前提崩壊

`保存済みページ数 == max_pages` の状態でも、次stateが `END` / `NEXT_CONTENT` なら正常終了を優先する。

## 12. Run output

新規runのoutput directoryは、存在しないか空でなければならない。非空directoryは拒否し、自動削除・暗黙上書きをしない。

```text
<output_dir>/
├─ page-0001.png
├─ page-0002.png
├─ manifest.json
├─ progress.json
└─ diagnostics/  # 異常時に作られる場合あり
```

## 13. Manifest / progress

manifestは保存ページのauthorityである。

最低限:

```json
{
  "source_url": "...",
  "site": "example",
  "content_context": {},
  "pages": [
    {
      "sequence": 1,
      "page_number": 1,
      "file": "page-0001.png",
      "width": 1400,
      "height": 2000,
      "fingerprint": "...",
      "identity": {},
      "metadata": {}
    }
  ]
}
```

`progress.json` は実行中のlast sequence / identity / fingerprint / contextを記録するが、現時点では自動resume機能ではない。

JSONはtemporary file → replaceで更新する。

## 14. Packaging

正常な `END` / `NEXT_CONTENT` 後、manifestの `pages[].file` をauthorityとしてZIPを作成する。

- manifestにないPNGをZIPへ入れない
- manifest記載PNGが欠落していれば失敗する
- path traversal等の危険なmanifest pathを拒否する
- 完成ZIPはlibrary treeへ配置する
- completion statusを別途保存する
- 中間crawl directoryは、内容がmanifest / progress / manifest記載PNGだけの場合に限り削除する
- 無関係ファイルや余分なPNGがあればdirectory全体を削除しない

## 15. Resume

**v1.1では自動resumeを実装しない。**

既存の非空run directoryは新規runとして拒否する。`ProgressStore` は既存manifest/progressを暗黙上書きしない。

将来resumeを実装する場合は、明示的な `--resume` 等を導入し、新規runと区別する。

## 16. Retry / safety guard

一時的なloadingやクリックはbounded retryしてよい。

無理に突破しないもの:

- UNKNOWN
- context不整合
- 主要selector消失
- DOM大幅変更

`max_pages` とsame-content guardは無限進行防止として必須。

## 17. Diagnostics

失敗時は設定されたdiagnostics directoryへ、可能な範囲で以下を保存する。

- screenshot
- HTML
- metadata JSON
- error text

metadataは最低限URL / title / viewport / detected state / context / errorを対象とする。Adapter固有debug metadataの拡張は将来対応でよい。

diagnostics保存失敗で元例外を隠さない。

## 18. Probe

新規サイト調査用。Crawler本体とは分離する。

- screenshot / HTML
- URL / title
- img metadata
- canvas metadata
- button候補
- background-image候補

正しいnext selectorの完全自動探索は要求しない。

## 19. Patterns

Patternは必須frameworkではなく補助部品。2サイト以上で実際に共通化できる場合だけ利用し、1サイト固有処理はAdapterに置く。

## 20. v1非対象

- OCR
- PDF化
- AI画像分類
- CAPTCHA回避
- 完全自動selector探索
- GUI
- 複数サイト並列実行
- 独自DSL
- 複雑なPlugin Framework
- 自動resume

## 21. 受け入れ条件

### Core

- Adapter差し替えで動作
- PNG連番保存
- manifest / progress生成
- diagnostics生成
- manifest基準のpackaging
- 非空output directoryを安全に拒否
- `max_pages`境界でEND/NEXT_CONTENTを正常終了
- bounded retry / timeout
- Coreにサイト固有selector/URL分岐を入れない

### Site Adapter

対象サイトについて:

- 本文だけ保存
- ページ順が正しい
- 既知の重複を大量保存しない
- 最終本文を取りこぼさない
- 次コンテンツを本文として保存しない
- UNKNOWNでは停止

## 22. 完了確認

最低限:

- 開始直後
- 通常ページ遷移
- 見開き
- 広告前後（存在するサイト）
- 最終本文
- 最終本文後
- 次コンテンツ遷移
- ページ変更失敗
- UNKNOWN
- `max_pages`境界
- packagingで余分なPNGが混入しないこと

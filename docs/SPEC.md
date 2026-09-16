# Screenshot Crawler 仕様書 v1.2

## 1. 目的

特定のWebビューアにアクセスし、現在コンテンツを1ページずつ進めながら本文だけをPNGとして保存する。

サイトごとに本文描画、ページ送り、広告、最終ページ後の挙動、次コンテンツ遷移が異なるため、完全自動判定は目的にしない。共通エンジンとSite Adapterを分離する。

## 2. 技術

- Python 3.12+
- Playwright Python
- Chrome / Chromium
- Chrome DevTools Protocol (CDP)
- asyncio
- PNG出力
- Windowsを主対象

## 3. Browser Session Model

Real-site automationの標準は、**1つの専用Crawler ChromeへCDP接続し、そのChromeをPlaywrightで操作する方式**とする。

目標構成:

```text
Crawler Chrome
└─ shared profile: .chrome-crawler/
      ├─ BookWalker session
      ├─ Manga ONE session
      └─ other site sessions
          ↑
          │ CDP
          ↓
Playwright Browser / Context / Page
          ↓
Core Runner
          ↓
Site Adapter
```

CDPは接続transportであり、通常のnavigation / DOM / click / wait / captureはPlaywright APIを使う。

Raw CDP ProtocolはPlaywrightで実現困難なChrome固有機能に限る。

### 3.1 Chrome profile

標準profileは:

```text
.chrome-crawler/
```

とする。

BookWalkerやManga ONEのlogin sessionは、Chrome自身がCookie / localStorage / IndexedDB等としてsiteごとに保持する。

Crawlerはsite別storage-state JSONを標準の認証authorityにしない。

### 3.2 CDP endpoint

目標の解決順:

1. `--cdp-endpoint`
2. `<SITE>_CDP_ENDPOINT`
3. `CRAWLER_CDP_ENDPOINT`
4. `http://127.0.0.1:9222`

通常はglobal endpointを使う。

site-specific endpoint/profileは例外として許可する。用途例:

- 複数account
- extension / browser setting差
- session分離
- 共通profileでは正常動作しないsite

### 3.3 Browser lifecycle

Crawlerは既存Chromeへ接続し、Crawler用Pageを作成する。

正常終了時はCrawlerが使用したPageを閉じるが、remote Chrome processは閉じない。

## 4. 入力

Crawler本体はURLを収集しない。URLは人手または別プログラムから渡す。

```bash
python -m screenshot_crawler.cli crawl --site <site> --url "https://..."
```

新規サイト調査:

```bash
python -m screenshot_crawler.cli probe --url "https://..."
```

Probeは通常launchとCDP接続の両方を利用できてよい。

## 5. Authentication

Real-site loginは共通Crawler ChromeへCDP接続し、login用に新規作成したPageをPlaywrightでsite固有login handlerが操作する。

既存Chromeタブは別siteの可能性があるため、loginの標準経路では再利用しない。login完了後はlogin用Pageだけを閉じ、Chrome processとprofileは残す。

認証情報は `.env` 等から入力してよい。

login後のsession保存先はChrome profileであり、Crawler独自のsite別storage stateを標準経路としない。

login handlerは:

- email/password等のform入力
- submit
- login結果確認

を行ってよい。

CAPTCHA / MFA / validation errorを自動突破しない。

## 6. PageState

- `CONTENT`: 保存対象本文
- `AD`: 保存対象外の中間画面
- `END`: 現在コンテンツの終了
- `NEXT_CONTENT`: 次話・次章・別コンテンツ
- `LOADING`: 描画途中
- `UNKNOWN`: 安全に判定できない

`UNKNOWN` は無理に突破せずdiagnosticsを残して停止する。

## 7. Coreの責務

- Browser Session / CDP接続補助
- BrowserContext / Page lifecycle
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

## 8. Site Adapterの責務

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

Site Adapterは以下を担当しない。

- Chrome launch
- profile選択
- CDP endpoint解決
- `connect_over_cdp()`
- BrowserContext lifecycle

AdapterはPlaywright `Page` / `Locator` を操作する。

## 9. Playwright / Raw CDP policy

通常操作はPlaywrightを標準とする。

```text
navigation
DOM query
Locator
click / keyboard / mouse
wait
frame / popup handling
evaluate
screenshot / canvas capture
```

Raw CDP Protocolを使う場合は:

- Playwrightで代替できない理由を明記
- Browser Session/Core側の小さいhelperへ隔離
- site Adapterへ低レベルCDP操作を広げない

ことを原則とする。

## 10. Capture

本文DOM Locatorを優先する。Canvasではraw PNG bufferを利用できる。見開きなど1画面に複数ページがある場合、Adapterは複数capture targetを読書順で返してよい。

保存連番とサイト上のページ番号は別物とする。

## 11. ContentIdentity / fingerprint

`ContentIdentity` はAdapterが取得できるpage id / page number / source id等を保持し、ページ変更待ちや記録に利用する。

現行Runnerの**保存重複判定authorityはcapture bytesのSHA-256 fingerprint**である。同一fingerprintは、identityが異なっていても重複captureとして保存しない。

これは既存BookWalker/Manga ONEで確認済みの挙動を維持するためのv1系仕様であり、identity優先dedupeへの変更は実サイト遷移を確認してから別途行う。

fingerprintだけを終了条件にはしない。

## 12. ContentContext

開始作品・話・章を識別する。

- content_id
- work_id
- episode_id
- chapter_id
- title

開始時と現在の同一strong fieldが明確に異なる場合、`NEXT_CONTENT` として正常終了できる。後からoptional fieldが追加されたことだけではcontext changeにしない。

## 13. 広告

`AD` は保存しない。広告表示自体は終了条件ではない。

```text
CONTENT → AD → CONTENT
CONTENT → AD → END
CONTENT → AD → NEXT_CONTENT
```

## 14. 終了条件

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

## 15. Run output

新規runのoutput directoryは、存在しないか空でなければならない。非空directoryは拒否し、自動削除・暗黙上書きをしない。

```text
<output_dir>/
├─ page-0001.png
├─ page-0002.png
├─ manifest.json
├─ progress.json
└─ diagnostics/  # 異常時に作られる場合あり
```

## 16. Manifest / progress

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

## 17. Packaging

正常な `END` / `NEXT_CONTENT` 後、manifestの `pages[].file` をauthorityとしてZIPを作成する。

- manifestにないPNGをZIPへ入れない
- manifest記載PNGが欠落していれば失敗する
- path traversal等の危険なmanifest pathを拒否する
- 完成ZIPはlibrary treeへ配置する
- completion statusを別途保存する
- 中間crawl directoryは、内容がmanifest / progress / manifest記載PNGだけの場合に限り削除する
- 無関係ファイルや余分なPNGがあればdirectory全体を削除しない

## 18. Resume

**自動resumeは未実装。**

既存の非空run directoryは新規runとして拒否する。`ProgressStore` は既存manifest/progressを暗黙上書きしない。

将来resumeを実装する場合は、明示的な `--resume` 等を導入し、新規runと区別する。

## 19. Retry / safety guard

一時的なloadingやクリックはbounded retryしてよい。

無理に突破しないもの:

- UNKNOWN
- context不整合
- 主要selector消失
- DOM大幅変更

`max_pages` とsame-content guardは無限進行防止として必須。

## 20. Diagnostics

失敗時は設定されたdiagnostics directoryへ、可能な範囲で以下を保存する。

- screenshot
- HTML
- metadata JSON
- error text

metadataは最低限URL / title / viewport / detected state / context / errorを対象とする。Adapter固有debug metadataの拡張は将来対応でよい。

diagnostics保存失敗で元例外を隠さない。

## 21. Probe

新規サイト調査用。Crawler本体とは分離する。

- screenshot / HTML
- URL / title
- img metadata
- canvas metadata
- button候補
- background-image候補

正しいnext selectorの完全自動探索は要求しない。

## 22. Patterns

Patternは必須frameworkではなく補助部品。2サイト以上で実際に共通化できる場合だけ利用し、1サイト固有処理はAdapterに置く。

## 23. 非対象

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

## 24. 受け入れ条件

### Browser Session

- 共通Crawler Chrome/profileをdefaultにできる
- CDP接続後の通常操作はPlaywrightで行う
- site-specific endpoint/profileを例外overrideできる
- Crawler終了時にremote Chromeを閉じない
- Site AdapterがCDP/profile管理を持たない

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

## 25. 移行状態

このv1.2 Browser Session Modelは採用済みで、Phase 2の共通launcher実装まで完了している。

標準運用は以下である。

- `start_crawler_chrome.ps1`
- `.chrome-crawler/`
- `CRAWLER_CDP_ENDPOINT`
- site-specific endpointはoverride扱い

既存の `start_bookwalker_chrome.ps1` / `start_mangaone_chrome.ps1` とsite-specific profileは、rollback用legacy / compatibility pathとして残す。Phase 3で削除を検討する。

移行中もBookWalker/Manga ONEのviewer/capture/END挙動を変更しない。

## 26. 完了確認

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
- 共通Crawler Chromeで複数site sessionを再利用できること
- site-specific endpoint overrideがdefaultを壊さないこと

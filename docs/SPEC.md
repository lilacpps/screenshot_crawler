# Screenshot Crawler 仕様書 v1.4

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

Crawler Core / `CrawlerRunner` 自体はURLを収集しない。1 runの中心入力は引き続き `site + URL` とする。

```bash
python -m screenshot_crawler.cli crawl --site <site> --url "https://..."
```

人手でURLを渡す経路は維持する。

将来追加するDiscovery subsystemは、利用者が明示登録したWatchlist targetだけを探索し、Catalogへsource URLを保存する。そのURLをBatch Runnerが読み、実行条件を解決したうえで既存Crawlerへ渡す。CrawlerRunnerへCatalog依存を追加しない。

Discovery / Catalog / Batchの詳細仕様は `docs/DISCOVERY_AND_BATCH.md` をauthorityとする。

### 4.1 Crawl Request

Batch統合後のCrawler入力は概念上、次の任意情報を追加できる。

```text
site
url
access_strategy      # auto / direct / quota
output metadata      # optional
  title
  author
  order
  genre
```

`access_strategy` のdefaultは `auto` とする。手動crawlでは既存のURL-only運用を維持し、metadataも未指定でよい。

`item_id` / `source_id` 等のCatalog identityはBatch Runnerが保持し、CrawlerRunnerへ持ち込まない。

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
- site-neutralなrun inputの保持
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

Coreはサイト固有DOM、next操作、広告、終了、次コンテンツ、quota ruleを推測しない。

CoreはWatchlist、Catalog、Discovery、Batchの状態を管理しない。

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
- site-neutralな `access_strategy` を必要なsite固有entry logicへ反映する

詳細なAPI形状は実装時に最小変更で決めるが、Site Adapterが今回の `access_strategy` を参照できることを要件とする。

Site Adapterは以下を担当しない。

- Chrome launch
- profile選択
- CDP endpoint解決
- `connect_over_cdp()`
- BrowserContext lifecycle
- Discovery listing traversal
- Catalog read/write
- quota残数、reset時刻、daily limit等のBatch Policy判定

AdapterはPlaywright `Page` / `Locator` を操作する。

## 9. Access strategy

Crawlerへ渡す `access_strategy` は、Catalogの `access_mode` と分離する。

```text
auto
  手動crawlのdefault。Adapterが従来どおりsite状態を観測して適切な入口を選ぶ。

direct
  新規quotaを消費しない前提でreaderへ入る。
  free / owned / quota消費後のgrant期間中等。

quota
  今回はquotaを利用してaccessを開始する意図を示す。
```

Batch Runner / Site Policyが `access_mode`、quota残数、`access_granted_until` 等から今回の `access_strategy` を解決する。

Crawlerにはdaily limitやreset ruleそのものを渡さない。

Coreは `access_strategy` をsite固有ruleとして解釈しない。quota button選択等はSite Adapterに置く。

## 10. Playwright / Raw CDP policy

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

## 11. Capture

本文DOM Locatorを優先する。Canvasではraw PNG bufferを利用できる。見開きなど1画面に複数ページがある場合、Adapterは複数capture targetを読書順で返してよい。

保存連番とサイト上のページ番号は別物とする。

## 12. ContentIdentity / fingerprint

`ContentIdentity` はAdapterが取得できるpage id / page number / source id等を保持し、ページ変更待ちや記録に利用する。

現行Runnerの**保存重複判定authorityはcapture bytesのSHA-256 fingerprint**である。同一fingerprintは、identityが異なっていても重複captureとして保存しない。

これは既存BookWalker/Manga ONEで確認済みの挙動を維持するためのv1系仕様であり、identity優先dedupeへの変更は実サイト遷移を確認してから別途行う。

fingerprintだけを終了条件にはしない。

## 13. ContentContext

開始作品・話・章を識別する。

- content_id
- work_id
- episode_id
- chapter_id
- title

開始時と現在の同一strong fieldが明確に異なる場合、`NEXT_CONTENT` として正常終了できる。後からoptional fieldが追加されたことだけではcontext changeにしない。

## 14. 広告

`AD` は保存しない。広告表示自体は終了条件ではない。

```text
CONTENT → AD → CONTENT
CONTENT → AD → END
CONTENT → AD → NEXT_CONTENT
```

## 15. 終了条件

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

## 16. Run output

新規runのoutput directoryは、存在しないか空でなければならない。非空directoryは拒否し、自動削除・暗黙上書きをしない。

```text
<output_dir>/
├─ page-0001.png
├─ page-0002.png
├─ manifest.json
├─ progress.json
└─ diagnostics/  # 異常時に作られる場合あり
```

## 17. Manifest / progress

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

## 18. Packaging / output metadata

正常な `END` / `NEXT_CONTENT` 後、manifestの `pages[].file` をauthorityとしてZIPを作成する。

- manifestにないPNGをZIPへ入れない
- manifest記載PNGが欠落していれば失敗する
- path traversal等の危険なmanifest pathを拒否する
- 完成ZIPはlibrary treeへ配置する
- completion statusを別途保存する
- 中間crawl directoryは、内容がmanifest / progress / manifest記載PNGだけの場合に限り削除する
- 無関係ファイルや余分なPNGがあればdirectory全体を削除しない

### 18.1 Metadata override / fallback

Crawlerはpackaging用の次のmetadataを任意入力として受け取れるようにする。

```text
title
author
order
genre
```

解決は**field単位**で次の順とする。

```text
1. Crawl Requestで明示されたnon-empty値
2. Site Adapterが取得した値
3. packaging側の既存fallback
```

一部fieldだけ明示してよい。未指定fieldはAdapterから補完する。

metadataが一切渡されなければ従来どおりAdapterから取得する。

metadata overrideはsource URLやmanifestの実URLを置換しない。

## 19. Resume

**自動resumeは未実装。**

既存の非空run directoryは新規runとして拒否する。`ProgressStore` は既存manifest/progressを暗黙上書きしない。

将来resumeを実装する場合は、明示的な `--resume` 等を導入し、新規runと区別する。

## 20. Retry / safety guard

一時的なloadingやクリックはbounded retryしてよい。

無理に突破しないもの:

- UNKNOWN
- context不整合
- 主要selector消失
- DOM大幅変更

`max_pages` とsame-content guardは無限進行防止として必須。

## 21. Diagnostics

失敗時は設定されたdiagnostics directoryへ、可能な範囲で以下を保存する。

- screenshot
- HTML
- metadata JSON
- error text

metadataは最低限URL / title / viewport / detected state / context / errorを対象とする。Adapter固有debug metadataの拡張は将来対応でよい。

diagnostics保存失敗で元例外を隠さない。

## 22. Probe

新規サイト調査用。Crawler本体とは分離する。

- screenshot / HTML
- URL / title
- img metadata
- canvas metadata
- button候補
- background-image候補

正しいnext selectorの完全自動探索は要求しない。

## 23. Patterns

Patternは必須frameworkではなく補助部品。2サイト以上で実際に共通化できる場合だけ利用し、1サイト固有処理はAdapterに置く。

## 24. 非対象

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
- 全site・全作品の無制限Discovery
- site横断automatic item merge

## 25. 受け入れ条件

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
- Coreにサイト固有selector/URL/quota rule分岐を入れない
- Core / CrawlerRunnerがCatalogを知らない
- site-neutralな `access_strategy` をrun inputとして保持できる

### Site Adapter

対象サイトについて:

- 本文だけ保存
- ページ順が正しい
- 既知の重複を大量保存しない
- 最終本文を取りこぼさない
- 次コンテンツを本文として保存しない
- UNKNOWNでは停止
- 必要なsiteでは `auto / direct / quota` の実行意図をsite固有entry logicへ反映できる

### Crawl metadata

- title/author/order/genreをoptional inputとして受け取れる
- metadata未指定ならAdapter取得を利用できる
- 一部metadataのみ指定できる
- `explicit request > adapter > fallback` のfield単位優先順位になる
- metadata overrideでsource URL/manifest URLを置換しない

### Discovery / Catalog / Batch

詳細な受け入れ条件は `docs/DISCOVERY_AND_BATCH.md` をauthorityとする。

最低限:

- Watchlistに明示されたtargetだけをDiscoveryする
- full / incremental syncを分離する
- full syncはcomplete時だけmissing sourceをunavailable化する
- incrementalはknown source 2件連続で停止する
- Catalogは `items / sources` の2テーブルを基本とする
- 別siteの類似itemはwarningのみで自動mergeしない
- Batch Runnerはsite policyを使ってfree/owned/quotaを選択する
- quotaは基本的にcrawl開始時に記録する
- active grant中は新規quotaを消費せず `access_strategy=direct` を選べる
- 新規quota利用時は `access_strategy=quota` を選べる
- Site Policyのquota rule自体をCrawlerへ渡さない
- Catalog metadataをCrawlerへoptional overrideとして渡せる
- crawl成功時だけitemをcompletedへ更新する

## 26. 移行状態

Browser Session Modelは採用済みで、共通launcherとshared-profile live verificationまで完了している。

標準運用は以下である。

- `start_crawler_chrome.ps1`
- `.chrome-crawler/`
- `CRAWLER_CDP_ENDPOINT`
- site-specific endpointはoverride扱い

BookWalker/Manga ONEを含むreal-site運用は、`start_crawler_chrome.ps1` とshared `.chrome-crawler/`を標準とする。site-specific launcherは削除済みであり、site-specific endpoint/profileは例外overrideとしてのみ許可する。

移行後もBookWalker/Manga ONEのviewer/capture/END挙動を変更しない。

Watchlist + Catalog基盤は実装済みである。Discovery Adapter / Service、Batch Runner、Site Policy、Crawl Request拡張は未実装である。実装時も既存Crawlerの1 URL -> 1 run責務を維持する。

## 27. 完了確認

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

Discovery / Catalog / Batch実装時は、`docs/DISCOVERY_AND_BATCH.md` と `docs/TEST_STRATEGY.md` の該当項目も確認する。

Crawl Request拡張時は、手動crawlのdefaultが既存挙動を維持し、`access_strategy` とmetadata overrideの有無で不要な回帰がないことを確認する。

## 28. Discovery / Catalog / Batchの概要

採用する上位フロー:

```text
watchlist.yaml
    ↓
Discovery Service / Discovery Adapter
    ↓
catalog.sqlite (items / sources)
    ↓
Batch Runner / Site Policy
    ↓
Crawl Request
    ↓
existing Screenshot Crawler
```

方針:

- Watchlistは人間がadd/remove/enable/disableできる設定
- Watchlist targetは一意なstable `key` を持つ
- Discovery結果sourceは `discovery_key` を保持し、full syncのscopeを限定する
- 初回・reconciliationはfull、通常更新はincrementalを利用できる
- incrementalはlatest側から走査し、known source 2件連続で停止する
- access stateは `owned / free / quota / paid / unknown`
- 期間限定無料は `free + free_until` で表す
- quota制約はsite-specific Policyで扱い、基本的にcrawl開始時に消費記録する
- quota消費後の再閲覧猶予は `access_granted_until` で扱える
- Batchは今回の実行意図を `access_strategy=auto|direct|quota` としてCrawlerへ渡す
- title/author/order/genreは既知ならCrawlerへ渡し、なければAdapter取得へfallbackする
- 別site同一作品を自動mergeせず、Discovery時に重複候補warningだけを出す
- 詳細schema、sync semantics、failure handlingは `docs/DISCOVERY_AND_BATCH.md` に定める

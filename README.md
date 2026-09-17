# Screenshot Crawler

## Manga ONE Discovery (Phase 4A)

Manga ONE Discovery starts from any chapter URL in the Watchlist and scans the
newest-first `#chapterList` listing. It stores the parsed `chapter_id` as the
stable Catalog source identity and supports bounded `次へ` pagination.

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover `
  --key juou-to-yakusou --mode full `
  --watchlist watchlist.yaml --catalog catalog.sqlite
```

Discovery can also synchronize every enabled Watchlist target in file order:

```powershell
# 通常同期
python -m screenshot_crawler.cli discover --all --mode incremental

# 全件再同期
python -m screenshot_crawler.cli discover --all --mode full
```

`discover` requires exactly one of `--key KEY` and `--all`. Disabled targets
are skipped without changing their existing Catalog data. Each target uses a
target-scoped CDP connection and failures do not stop later targets; a
summary is printed and any failure, including a result with
`stopped_reason=incomplete`, makes the command exit non-zero. The
single-target `--keep-open` behavior is preserved, while `--all --keep-open`
is rejected because each target connection is closed before the next target.

Crawler Chrome must be started in advance. Discovery never starts Chrome, and
Batch remains a separate command.

BookWalker Discovery and Policy remain unsupported. Manga ONE Batch Crawler
execution, quota persistence, packaging, and completed updates are available
through `batch run`.

Python + Playwrightで、Webビューアを1ページずつ進めながら本文だけをPNG保存し、正常終了時にZIPへまとめるクローラです。

万能な自動判定は目的にしていません。共通処理を `core/` に置き、サイト差分は `site_adapters/` に閉じ込めます。新しいサイトは Probe → 調査 → Adapter実装 → テスト → 実サイト確認、の順で追加します。

## 現在実装されているもの

- Core Runnerと6状態 (`CONTENT / AD / END / NEXT_CONTENT / LOADING / UNKNOWN`)
- PNG capture、SHA-256 fingerprint、manifest / progress、diagnostics
- Playwright Probe
- BookWalker Adapter
- Manga ONE Adapter
- 既存ChromeへCDP接続するcrawl/loginフロー
- 共通Crawler Chrome launcher (`scripts/start_crawler_chrome.ps1`)
- BookWalker canvas / spread capture
- Manga ONE img / spread capture
- manifestをauthorityにしたZIP packagingとlibrary出力
- Watchlist YAMLの `watch list/add/remove/enable/disable`
- SQLite Catalog基盤（`items` / `sources`、schema version 1）
- Catalogの閲覧用CSV export（`catalog export`、SQLiteがauthority）
- site-neutral Discovery framework（fake/local Adapter向け、full / incremental sync）
- Phase 5A read-only Batch Planner、Site Policy registry、Manga ONE Policy
- Phase 5B Manga ONE Batch Executor（direct/quota、quota state、packaging、completed更新）
- unit testsとPlaywrightローカルfixture integration tests

Watchlist + Catalog基盤、Crawl Requestの最小基盤、site-neutral Discovery framework、Phase 5Aのread-only Batch Planner / Site Policy registry / Manga ONE Policy、Phase 5BのManga ONE Batch Executorは実装済みです。BookWalker Policy / Batchは未実装です。詳細は `docs/DISCOVERY_AND_BATCH.md` を参照してください。

## 採用するBrowser Session設計

Real-site automationは、**1つの専用Crawler ChromeへCDP接続し、そのChromeをPlaywrightで操作する**構成へ統一します。

```text
Crawler Chrome
└─ shared profile (.chrome-crawler/)
      ├─ BookWalker login session
      ├─ Manga ONE login session
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

役割は明確に分けます。

- CDP: Chromeへ接続する
- Playwright: `Page` / `Locator` で通常操作する
- Site Adapter: 本文・next・END等のsite固有logicを持つ

Raw CDP Protocolを通常のsite操作には使いません。Playwrightで実現できないChrome固有機能が必要な場合だけ例外的に使います。

### Login session

共通Crawler Chromeのprofile内にChrome自身がsiteごとのCookie / localStorage等を保存します。

Crawler側で:

```text
bookwalker-auth.json
mangaone-auth.json
```

のようなsite別auth-state fileを標準管理する設計にはしません。

login CLIは既存Chromeの別site tabを再利用せず、login専用のnew Pageを作成します。login後はそのPageだけをcloseし、remote Chromeとshared profileは維持します。

### CDP endpoint

現在の解決順:

```text
--cdp-endpoint
    ↓
<SITE>_CDP_ENDPOINT
    ↓
CRAWLER_CDP_ENDPOINT
    ↓
http://127.0.0.1:9222
```

通常はglobal endpointを使い、site-specific endpoint/profileは必要なケースだけoverrideします。

## Browser Session移行状態

shared Crawler ChromeへのBrowser Session移行とlive verificationを完了しています。

標準運用は:

```text
scripts/start_crawler_chrome.ps1
.chrome-crawler/
CRAWLER_CDP_ENDPOINT=http://127.0.0.1:9222
```

です。BookWalkerとManga ONEのlogin sessionは同じChrome profileに保存できます。

BookWalker login/crawl、Manga ONE login/crawl、同一profileでのsession共存をshared `.chrome-crawler/`で確認済みです。
既存のcapture・page navigation・END判定にも回帰はありません。

この移行ではBookWalker/Manga ONEのcapture・page navigation・END判定を原則変更せず、Browser Session層だけを整理します。

## 最初に読むもの

1. `docs/SPEC.md` — 現在の製品仕様・受け入れ条件
2. `docs/ARCHITECTURE.md` — 責務分離とBrowser Session / subsystem設計
3. `docs/DISCOVERY_AND_BATCH.md` — Watchlist / Discovery / Catalog / Batch / Crawl Requestの採用仕様
4. `docs/DECISIONS.md` — 重要な設計判断
5. `docs/CODEX_IMPLEMENTATION_GUIDE.md` — 既存実装を変更するときのルール
6. `docs/SITE_ADAPTER_GUIDE.md` — 新規サイト対応の作り方
7. `docs/TEST_STRATEGY.md` — テスト方針
8. `note/README.md` — 現行実装ノートの更新ルールとファイル対応

`note/` は現在の実装詳細を復元するためのcurrent implementation snapshotです。仕様・実装・運用を変更した場合は、対応するnoteも同じ変更で同期します。

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
playwright install chromium
```

Windows PowerShellを主な実行環境として想定しています。

## 基本ワークフロー

現在実装済みの標準workflow:

```text
Crawler Chromeを1回起動
        ↓
必要なsiteへlogin
        ↓
URLを人手または別プログラムから取得
        ↓
必要ならprobe
        ↓
既存Adapterまたは新規Adapterを使用
        ↓
本実行
        ↓
END / NEXT_CONTENTで正常終了したらZIP化
        ↓
Crawler tabだけclose、Chromeは維持
```

Crawler Core自体はURL一覧の収集を担当しません。

将来実装する上位workflow:

```text
watchlist.yaml
    ↓
Discovery (full / incremental)
    ↓
catalog.sqlite (items / sources)
    ↓
Batch Runner / Site Policy
    ↓
Crawl Request
  access_strategy + known metadata
    ↓
既存 crawl
```

DiscoveryはWatchlistに明示した作品だけを対象とし、別siteの同一作品を自動mergeしません。

Batchはquota ruleを解決し、Crawlerへは今回の実行意図だけを `access_strategy=direct|quota` として渡します。手動crawlは `auto` がdefaultです。

Catalogでtitle/author/order/genreが分かっていればCrawlerへoptional metadataとして渡し、未指定fieldはSite Adapterの取得値へfallbackする設計です。

### Batch plan

CatalogからManga ONEのcrawl候補を確認できます。これはread-onlyの計画だけを行い、Crawler実行・quota消費記録・completed更新は行いません。

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch plan `
  --site mangaone `
  --catalog catalog.sqlite
```

Manga ONE PolicyはCatalog-localなquota_started_atを使い、4枠・09:00/21:00 JST reset・active grantのdirect判定を行います。手動で消費した無料ライフはCatalogから把握できないため、結果はlocal eligibility estimateです。

### Batch run

Manga ONEのplan候補を順番に実行し、正常なcrawlとpackagingが完了したitemだけを`completed`へ更新します。quota利用時はCrawler開始直前に`quota_started_at`とPolicyの24時間grantを保存します。失敗時はitemをpendingのままにし、保存済みquota stateや失敗runを保持します。`batch run`はstop-on-first-failureで、`--limit`を指定すると先頭N件だけ実行します。

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run `
  --site mangaone `
  --catalog catalog.sqlite `
  --output-root output\batch `
  --library-dir output\Books `
  --limit 1
```

`batch plan`は引き続きread-onlyです。BookWalkerはPolicy未登録のためBatch実行対象外です。

### CatalogのCSV export

Catalogの確認用に、`items` と `sources` をJOINした1行1sourceのCSV snapshotを出力できます。CSVは閲覧用であり、SQLite Catalogが唯一のauthorityです。

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli catalog export `
  --catalog catalog.sqlite `
  --output catalog-export.csv
```

既定値は入力 `catalog.sqlite`、出力 `catalog-export.csv` です。UTF-8 BOM、header付きで、sourceを持たないitemも出力します。

## 共通Crawler Chromeの起動

通常はrepository rootで次を実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_crawler_chrome.ps1
```

既にport 9222でCDP listenerがある場合、実行中Chromeのcommand lineがshared profileとportを示すときだけ既存Chromeを再利用します。確認できない場合は二重起動せずerrorで停止します。

移行前に作成されたsite-specific profile directoryが残っていても、共通launcherは自動削除しません。不要なruntime directoryは確認のうえ手動削除してください。

## Crawl例

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site bookwalker `
  --url "https://bookwalker.jp/de<content-id>/" `
  --output-dir output\crawl-bookwalker
```

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site mangaone `
  --url "https://manga-one.com/manga/2379/chapter/214131" `
  --output-dir output\crawl-mangaone
```

`--access-strategy auto|direct|quota` と `--title` / `--author` / `--order` / `--genre` を指定できます。defaultは`auto`で、metadataはfield単位に explicit > Adapter > packaging fallback で解決します。Manga ONEは`auto`/`direct`/`quota`をサポートし、BookWalkerの`direct`/`quota`は未対応です。

## Outputの安全ルール

新規crawlの `--output-dir` は、存在しないdirectoryまたは空directoryである必要があります。既存runの暗黙resumeは行いません。

```text
output/crawl-xxx/
├─ page-0001.png
├─ page-0002.png
├─ manifest.json
├─ progress.json
└─ diagnostics/   # 失敗時に作られる場合あり
```

正常な `END` / `NEXT_CONTENT` 後は、manifestに記載されたPNGだけをZIPへ格納します。manifestにない古いPNGは混入しません。中間crawl directoryは、manifest / progress / manifest記載PNG以外のファイルを含まない場合だけ削除されます。

失敗runは調査用に残します。

## Resume

自動resumeは現在未実装です。既存の非空run directoryを新規runとして上書きせず、明示的に拒否します。`progress.json` は実行状況の記録であり、自動resume機能を意味しません。

## サイト固有の挙動

実サイトで確認済みの判定ロジックを、Browser Session整理のために変更しないでください。特にBookWalkerとManga ONEの終了判定・ページ送り・capture方式は各Adapter READMEとsite noteを確認してください。

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

## Magapoke Discovery (M1)

Magapoke Discovery accepts any supported episode URL as a Watchlist target,
extracts the work `title_id` from that URL, expands the scoped episode list
until its visible `もっと見る` control is gone, validates every row, and
synchronizes each row's `episode_id` and canonical URL into Catalog. Rows are
yielded newest-to-oldest. The observed state classes map to `free`, `quota`
(`--ticket-free` and active `--renting`), `paid` (`--point`), or `unknown`.

Both full and incremental discovery fully expand and validate the list before
the generic incremental known-streak logic is applied. Magapoke Batch,
SitePolicy, ticket/point operations, and active-grant persistence are not part
of M1.

Python + Playwrightで、Webビューアを1ページずつ進めながら本文だけをPNG保存し、正常終了時にZIPへまとめるクローラです。

万能な自動判定は目的にしていません。共通処理を `core/` に置き、サイト差分は `site_adapters/` に閉じ込めます。新しいサイトは Probe → 調査 → Adapter実装 → テスト → 実サイト確認、の順で追加します。

## 現在実装されているもの

- Core Runnerと6状態 (`CONTENT / AD / END / NEXT_CONTENT / LOADING / UNKNOWN`)
- Native JPEG/PNG capture、SHA-256 fingerprint、manifest / progress、diagnostics
- Playwright Probe
- BookWalker Adapter
- Manga ONE Adapter
- Magapoke Adapter（scrambled JPEGのtile再構成PNG、canvas screenshot fallback）
- Comic DAYS Adapter (free/active-grant discovery, Work Ticket policy, horizontal RTL canvas, lossless JPEG-first native capture with reconstructed-PNG and locator fallbacks)
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

Comic DAYS supports free episodes, active grants, and one Catalog-selected
Work Ticket candidate per work (`quota_limit=1`). Batch opens the selected
episode once, performs strict target-local safety validation, clicks the exact
Work Ticket control once, confirms positive consumption, and continues from
the same Page for normal quota crawling. Grant-only leaves the Item pending
without an Artifact. Catalog/live mismatch stops the resource pass and
requires a fresh full Discovery; a positive ticket cooldown is reported
separately. The generic live resolver remains for sites whose Discovery cannot
classify native ticket state, such as Zebrack.
For live verification, the supplied episode URL seeds full Discovery for its
native work; the natural Planner candidate may be another episode in that same
work, while Catalog access facts and ordering remain authoritative.
For a consuming Comic DAYS Batch candidate, the Catalog Work key must match
`comicdays:series:<native-series-id>`. The adapter validates that identity
before navigation and returns `comicdays_work_identity_unavailable` with no
navigation or consumption for an arbitrary or malformed key. This is distinct
from `comicdays_discovery_refresh_required`, which means a positive live
mismatch after a valid Catalog identity. Free/direct candidates may retain
arbitrary Work keys; a manually invoked quota run without configured Catalog
expectations keeps the adapter's target-local contract checks.
After a positive mismatch, refresh the isolated Catalog with full Discovery:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover `
  --site comicdays --mode full `
  --watchlist output\comicdays-watchlist.yaml `
  --catalog output\comicdays-refresh.sqlite
```

Native capture is lossless-JPEG first when the observed source and tile
geometry pass coefficient-level validation, with whole-spread reconstructed
PNG and locator fallbacks. Point, coin, paid, and login operations are never
performed. Discovery, Catalog, Batch, and packaging remain available.

The isolated 2026-10-04 Test A used the seed URL above and the native work's
natural Planner quota candidate (`12207421983943213206`). The production
grant-only run opened that candidate once, issued one Work Ticket click, and
durably observed the native debit/unlocked target evidence. The Item remained
pending and no Artifact was created; the CLI subsequently reported an
`AccessConsumptionUnconfirmedError` after the positive latch, so the run was
not retried. The isolated Catalog retained the 23-hour resource timestamp,
and the policy's calculated 71-hour fallback is
`2026-10-07T16:35:36.501568+09:00` (the pre-refresh source snapshot was not
captured). A complete post-grant Discovery then replaced the source value with
the observed native expiry.
Instrumentation recorded three adapter Work Ticket GraphQL checks and zero
adapter whole-work listing calls. The page's own JavaScript emitted 31
first-party Atom/readable-product requests, which are recorded separately from
crawler-side adapter traffic. This evidence is current behavior; older
resolver/replan live runs below are historical.
The same diagnostic target probe showed the native viewer identity and unlocked
normal viewer, while the capture hook remained incomplete with
`expected_body_area_not_visible_or_extra` (expected area 2, no visible body
areas) for the bounded observation window. Grant-only confirmation therefore
uses target-local debit/unlock evidence and does not require body/capture
readiness. The common post-click confirmation requires matching canonical
episode/work/JSON identity, one visible normal viewer, no private viewer, no
remaining target Work Ticket control, and a newer positive `chargedAt`. Normal
crawling continues on that same Page through the existing
initialize/normalization/capture guards; an incomplete body area fails closed
there while the positive consumption record is retained.

The historical A/2R/3P raw directories under `output/tmp` are currently
unavailable; their original Catalogs and raw evidence cannot be revalidated.
The reviewer verified the A evidence before disappearance; the cause and any
recovery location are unknown, and no raw evidence was reconstructed. Future
B/C live evidence uses an explicit protected task directory outside
`output/tmp`.

The protected 2026-10-04 normal quota Test B used
`output/comicdays_one_navigation_liveB_20261004_protected_1859/` and the
natural Planner candidate source165 (`10834108156719217950`) in work
`comicdays:series:10834108156713445245`. The real Planner/Executor/Runner/
Adapter path opened the candidate once, recorded one site-owned
`Viewer_PurchaseViaTicket` mutation with positive debit/unlock evidence, and
performed zero paid or premium operations. The same Page continued through
normalization and native JPEG capture to `END`, producing a 28-page ZIP and a
completed Catalog Item with a present Artifact. Adapter target GraphQL checks:
3; adapter whole-work Atom/free-Atom/pagination/readable-product calls: 0.
 Raw AccessEvent classification recorded 31 site-owned listing requests
 (Atom 28, `readable_product_pagination_information` 2, and
 `pagination_readable_products` 1). The harness's limited marker pattern
 counted 30; the raw sink total is authoritative. Page.goto and Locator.click
 were not directly instrumented: the one crawler target open is inferred from
 the target-document ordering, and the one exact ticket click is inferred from
 the single `Viewer_PurchaseViaTicket` mutation plus positive debit/unlock
 evidence (the reload removed selector metadata from the DOM listener). The
 protected audit is
`output/comicdays_one_navigation_liveB_20261004_protected_1859/normal_batch_report.json`;
the pre-package output copy is under `evidence/normal_batch/pre_package_output`.
The B-run snapshot was A=1 ticket, B=1 ticket, C=0 tickets. The corrected
grant-only Test C below brings the current task ledger to A=1/B=1/C=1.

The corrected isolated 2026-10-04 grant-only Test C used seed
`12207421983645809730`; full Discovery selected source39, episode
`2550912965783608326`, in work `comicdays:series:14079602755643699323`.
The production CLI exited successfully after one positive debit/unlock, left
 the Item pending, created no Artifact or images, and persisted the work resource
 state. The `consumed_at + 71h` value was calculated from policy; a separate
 pre-refresh source/SQLite snapshot of that value was not persisted. A second production
grant-only CLI run selected another same-work quota candidate but stopped at the
Catalog-only `work_ticket_cooldown` gate with zero page, goto, click, or request
activity. The subsequent isolated full Discovery observed 63/63 and refreshed
the native expiry to `2026-10-07T19:22:14+09:00`.

 Durable page AccessEvents recorded three site-JavaScript
 `Viewer_SeriesTicketQuery` requests; the adapter-specific GraphQL call count is
 unknown because its wrapper output was not persisted. The quota path has zero
 whole-work adapter calls by code-path verification, rather than a persisted
 runtime counter. The C harness installed direct `Page.goto` and `Locator.click` wrappers, but a
harness-only nested-async error while writing post-Discovery output lost those
in-memory callback records. Durable production AccessEvents recover one
crawler target open, one same-target site transition, one
`Viewer_PurchaseViaTicket` mutation, and zero paid mutations; the report marks
these recovered counts separately from direct wrapper callbacks. The protected
audit is
`output/comicdays_grant_only_liveC_20261004_protected_1920/grant_only_report.json`.

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli watch add `
  --watchlist output\comicdays-watchlist.yaml `
  --key comicdays-target `
  --work-key comicdays:series:2550689798737278979 `
  --site comicdays `
  --url "https://comic-days.com/episode/2550689798754939004" `
  --label "かみあそび！～カードゲーマー少女の日常～"

.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover `
  --site comicdays --mode full `
  --watchlist output\comicdays-watchlist.yaml `
  --catalog catalog_comicdays.sqlite

.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run `
  --site comicdays --limit 1 `
  --catalog catalog_comicdays.sqlite `
  --output-root output\comicdays-batch `
  --library-dir output\comicdays-library
```

The adapter requires a canonical episode URL validated against the site's
current feed and first-party access state. It supports free and active-grant
episodes, with bounded viewer initialization, rewind, page changes, and native
source-body reads. The verified viewer is the horizontal RTL mode with a
64-step rewind/normalization cap; body spreads are captured only when all
logically expected areas are ready. Paid, owned, and unverified states remain
unsupported.

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

正常な `END` / `NEXT_CONTENT` 後は、manifestに記載されたJPEGまたはPNGだけをZIPへ格納します。manifestにない古い画像は混入しません。中間crawl directoryは、manifest / progress / manifest記載画像以外のファイルを含まない場合だけ削除されます。

失敗runは調査用に残します。

## Resume

自動resumeは現在未実装です。既存の非空run directoryを新規runとして上書きせず、明示的に拒否します。`progress.json` は実行状況の記録であり、自動resume機能を意味しません。

## サイト固有の挙動

実サイトで確認済みの判定ロジックを、Browser Session整理のために変更しないでください。特にBookWalkerとManga ONEの終了判定・ページ送り・capture方式は各Adapter READMEとsite noteを確認してください。

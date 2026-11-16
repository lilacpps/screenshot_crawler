# Architecture

## Work deletion (current implementation, Stage 04, 2026-11-14)

Management gate refinement (2026-11-15): management/jobs.pyのterminal stateをauthorityとし、
interruptedを除く終了履歴と旧completed/abortedをSQLで除外する。過去summary/監督エラー等の
logは読まず、fingerprintにも含めない。queuedでworker_pid/worker_start_token/started_atが
全て存在してNULLなら、未開始予約として同様に除外する（取消やDB更新はしない）。
起動情報があるqueuedとplanning/runningはCatalog binding確認後に書込み競合としてblock。
worker冒頭のadmission/start gate、Catalog lock後のgate、Applyの排他とfresh previewを維持し、
未開始予約のclaimがfresh previewと競合しても実writerが削除中に入らないことをテストする。
interruptedだけはworker.identityとDBのtoken/child・launcher PIDを
確認し、終了またはPID再利用の証明ができれば除外する。実worker生存・identity欠落・読取不能・
生存PIDのOS start identity不明はblockし、signal送信や履歴の状態変更は行わない。
別Catalogのjobは除外し、sealed binding/admission/Catalog lock/Apply fresh previewは維持する。

Previewは全Catalog snapshotとfingerprintを維持したまま、ID辞書でWork/Item/Source/Target/Runを
照合する。library列挙は呼出ごとに一回、status JSONはZIPのlibrary相対pathに対応する候補だけ
読み、全件列挙しない。規定外の歴史的JSONや別名aliasは探索・変更しない。同じZIP/statusのhashを
同一呼出内だけで共有する。各Artifactの宣言・所有検査は省略せず、読取前後および再利用時の
file identity/size/mtimeと、status解析に使ったbytesのSHAを照合する。Applyは新しい呼出で
再検証し、previewのhash cacheを引き継がない。Qt非依存のprogress callback/cancel tokenを
GUIのqueued signalへ接続し、中止したpreviewはPlan/tokenを公開しない。

Work単位の完全削除はRunbook `runbooks/work-deletion/` に従う共通Serviceとして実装済みである。`WorkDeletionPreviewService` はCatalog v7の全依存、Watchlist、Artifact/status/ZIP、全bound management store、active markerをread-onlyで検証し、CLIとWindows GUIは同じcanonical Plan/tokenをApplyへ渡す。CLIは `work delete --work-key KEY --dry-run|--apply --json` と明示的な `recover` / `bind` を提供し、GUIはWork行だけのコンテキストメニューから確認ダイアログを開く。通常のDiscovery、Batch、Capture、Watchlist編集、archive orderingの意味は変更しない。

実装時はcanonical Catalog pathのSHA-256で分離したCatalog固有namespace内のdurable deletion marker、sealed management-store binding registry、短時間admission lockをqueue/start/Discovery/registrationの共通gateとして扱い、任意trash rootだけに未完了状態を置かない。標準management DBだけではcustom storeを証明できないため、registry欠落・未sealed・未知path・読取不能はfail-closedとする。初回導入は全既知storeを明示bindしてからsealedにするbootstrap/migration操作を必要とする。admission lockは通常workerのCatalogJobLockと分離し、既存の実行中queue登録を拒否しない。Delete Applyだけがadmission lockを保持し、その内側でCatalog lock取得後にWatchlist edit lockを同じ順序で保持する。冗長FK（CrawlRunのitem/source/target、Artifactのitem/run）のWork整合性を検証する。詳細な削除順、path alias/reparse/hardlinkのfail-closed条件、failure matrixは [work-deletion Stage 00](../runbooks/work-deletion/00-contract/README.md) に記録する。

Preview performance refinement (2026-11-14): the read-only snapshot remains
the authority and its fingerprint is unchanged, while ownership joins use
call-local ID dictionaries instead of nested scans. The Library ZIP tree is
indexed once; status JSON is read only at packaging-derived paths (2026-11-15).
Duplicate locators reuse stable size/SHA/device/
inode/mtime facts. Index candidates and SHA chunks honor a Qt-free cooperative
cancel token. The GUI receives throttled queued progress with explicit stage,
file-count, and elapsed-time labels; only preview is cancellable, while Apply
close/cancel remains guarded. These optimizations do not change Discovery,
Batch, Capture, or site-adapter semantics.

## Hanayume repair analysis (Stage 01)

`gui/catalog_repair.py` is a separate optional Qt dialog, opened from Inventory
or `--catalog-repair`. Workers read Catalog/Watchlist, generate candidates and
perform bounded API research; GUI-thread callbacks render immutable results.
`maintenance/hanayume_repair.py` owns the read-only analysis and annotations,
not identity apply. `CatalogInventoryReader.read(include_history=True)` reads
all runs and artifacts in the same read-only transaction; the default latest
projection is unchanged. The site-local `hanayume/repair_probe.py` owns exact
metadata endpoints/parsing/network allowlisting; the GUI orchestrates shared
CDP BrowserSession lifecycle and closes only its owned Page. It never opens
the viewer or calls DiscoveryService/Batch/Grant-only. Catalog schema stays v7.
Manual annotations are review data, not body-equivalence or acquisition state.

Stage 02 is a separate `gui/repair_migration.py` dialog backed by
`maintenance/hanayume_migration.py`. It validates saved review bindings, verifies
current ZIP facts and constructs a token-bound migration preview. Only explicit
apply takes Catalog/Watchlist locks, makes a standalone backup and commits one
Catalog transaction. `SourceIdentityMaintenance._apply_connection` shares the
existing per-identity validation inside that caller-owned transaction; its public
apply contract remains unchanged. Site-local maintenance moves inactive Sources
to historical bindings registered in existing scope configuration history, so
ordinary Discovery, Scope Sync, Batch and archive ordering need no site branch.
Unchanged historical identities are retained; vacated IDs get inactive aliases
without copied quota timestamps. Complex reuse records old Artifact references
as manual external coverage; no Run or Artifact is merged or manufactured.
Schema remains v7; Watchlist and ZIP bytes are never changed by Stage 02.
When adopting pending current rows, maintenance may delete obsolete pending
Items/Sources/Targets only if they have no runs, artifacts, usage/grants,
manual title/note, sibling Sources or custom Targets. Exact old IDs are bound
to the preview and revalidated before backed-up transactional deletion. Audit
receipts are written to surviving current Items. Protected pending rows keep
their historical binding. This introduces no ordinary Discovery/Batch branch.

`maintenance/hanayume_history.py` and `gui/repair_history.py` implement separate
Stage 03A history-only ZIP relocation. Source/Item ownership, coverage-note
references and every Artifact locator are checked before moving a file. Stage 02
plans can project future ownership for preview only. Real apply takes a Catalog
job lock, verifies a fresh snapshot inside BEGIN IMMEDIATE, creates a standalone
backup and recovery journal, moves ZIPs with exclusive same-filesystem hardlinks
and updates every matching Artifact locator. Exceptions verify DB rollback and
restore files; ambiguous commit/recovery leaves a journal and blocks reapply.
No shared renumber or ordinary Discovery/Batch contract is changed.
Inventory uses the read-only site-local repair helper `inventory_history_kinds`
to recognize maintained history/old-ID references from saved bindings and
receipts. Generic Inventory/Qt project these as unselectable neutral states;
no Watchlist target or executable identity is synthesized. Invalid/unproven
ownership still follows the existing unmanaged projection.
Inventory tree nodes cache visible child lists per projection/filter state,
invalidated on search/filter/snapshot/sort changes. Qt row lookups reuse those
lists during painting rather than walking every Work sibling. The site-local
history projection indexes only candidate historical Items and bindings.

## Optional inventory, execution, and job-management GUI (P1-P3)

`gui/` contains the PySide6 application and Qt models; `management/` contains
Qt-independent immutable inventory projections and a dedicated SQLite read-only
snapshot reader. Existing Watchlist parsing, Site Policies, ScopeReconciler
(through in-memory read-only facades) and archive-order planning are reused.
P1 inventory reads remain strictly read-only. The main screen's separate Discovery-switch worker
writes only a key's Watchlist `enabled` field through the existing locked/CAS
service. InventorySnapshot carries the Watchlist revision computed from the same
read as its parsed targets. Work archiving additionally uses a Watchlist-only
save worker and the top-level `archived_work_keys` list. `read_document()`
returns frozen targets, Work visibility and revision from one file read;
the legacy `read_snapshot()` target/revision API remains compatible.
InventorySnapshot carries the archived Work-key set without removing domain
rows, changing numbering or writing Catalog. Main-window visibility and
execution selection are enforced in the Qt tree model; maintenance editors
retain the All view. Qt model/delegate emit intent; the main window owns
save serialization, editor rebasing and GUI job-start exclusion. Saved values
are committed before Inventory refresh; refresh failure never reports a failed
save or rolls back the file. Selected execution uses a lightweight
configuration-bound request without a candidate preview; P3 queues each request in a separate,
versioned `management.sqlite` and runs it in one serial worker subprocess. The
worker writes structured JSONL events while the GUI imports them idempotently;
Catalog job locks, shared CLI Scope/Quota/ZIP checks, and fail-closed configuration
drift checks remain authoritative. New requests do not hash Catalog contents or
rebuild Inventory at launch: the shared CLI plans from the latest Catalog under
the lock. Previously persisted plan-bound requests retain their legacy validation.
Cooperative stop, force interruption with unknown consumption,
heartbeat/OS-start identity checks, and explicit post-restart Resume are distinct
operations. See [GUI contract](GUI_INVENTORY.md),
[Windows launch instructions](GUI_README.md), and
[P2/P3 progress](../runbooks/gui-execution-p2-p3/PROGRESS.md).

## Phase 4A status

The Manga ONE Discovery adapter is implemented in
`site_adapters/mangaone/discovery.py` and registered separately from the
viewer `AdapterRegistry`. It reads `#chapterList` newest-first, uses the
chapter id from a card href or the observed `/chapter/<id>.webp` image URL,
and follows bounded `次へ` pagination. Uncertain traversal is incomplete;
only normal exhaustion allows full reconciliation. The adapter does not own
BrowserSession lifecycle or Catalog access. BookWalker Discovery, Batch
Runner, Site Policy, and quota consumption remain unimplemented for Phase 4A.

The Phase 5A read-only Batch Planner and Manga ONE Site Policy are now
implemented. They select Catalog sources and create plan candidates only;
Phase 5B adds sequential Manga ONE candidate execution, quota persistence,
packaging, and completed-item updates. BookWalker Batch execution remains
unsupported.

2026-09-20にCatalog Schema v3 target architectureを採用し、runtimeも
`works / items / sources / source_targets / crawl_runs / artifacts` の6テーブルを使用する。
既存v2 DBはschema-neutralなSQLite backup後に破棄し、full discoveryから新規v3 DBを再構築する。
v2からの自動migrationは行わない。v3以降は明示的な`catalog migrate`とmigration前backupを使う。

`catalog backup`はSQLite online backup APIでWALを含むCatalogをstandalone SQLiteへ保存し、
`PRAGMA quick_check`で検証する。Catalog schema v7はdomain/scope tables、required columns、
foreign keyおよびstatus/position/acquisition flag constraintsをruntime validationする。
明示migration registryはv3→v4→v5→v6→v7を提供し、pre-migration backup、single-transaction
rollback、`quick_check`、final schema validationを行う。通常のCatalog初期化は旧schemaを暗黙移行しない。

## 1. 設計原則

依存方向を単純に保つ。

現行Crawlerの目標architecture:

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

Discovery / Batchを含む上位architecture:

```text
watchlist.yaml
      ↓
Discovery Service
      ↓
Discovery Adapter
      ↓
Catalog Service -> catalog.sqlite (works / items / sources / source_targets / crawl_runs / artifacts)
      ↓
Batch Runner -> Site Policy
      ↓
Crawl Request
  site / URL / access_strategy / optional metadata
      ↓
Core Runner / packaging
      ↓
Site Adapter
```

重要な分離:

- **CDP**: Chrome sessionへ接続するためのtransport
- **Playwright**: navigation / DOM / click / wait / capture等の標準操作API
- **Site Adapter**: site固有viewer logic
- **Discovery Adapter**: site固有listing/discovery logic
- **Catalog Service**: SQLite read/write
- **Batch Runner**: Catalogからcrawl対象sourceを選ぶorchestration
- **Site Policy**: site固有quota/eligibility ruleを解決する
- **Crawl Request**: Batch/CLIから既存Crawlerへ渡すsite-neutralな実行入力

Raw CDP Protocolを通常のsite操作APIにはしない。

CrawlerRunnerとDiscovery AdapterはCatalogを直接知らない。

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

Crawl Requestは既存`RunConfig`を最小限拡張して保持する。Catalog objectをCoreへ流さず、site-neutralなrun inputだけを渡す。

### `site_adapters/`

サイト固有の**1 content viewer**差分。

- `base.py`: Adapter contract
- `registry.py`: site名→Adapter
- `<site>/adapter.py`: サイト固有実装
- `<site>/login.py`: 必要な場合のsite固有login DOM操作
- `<site>/README.md`: 実観測、終了挙動、制約、確認記録
- `<site>/config.yaml`: 実装が明示的に読み込む場合のみ設定として有効

現行real adaptersでは、複雑なselector/state/timeoutはPython Adapter実装がauthorityである。未使用YAMLとPythonを二重authorityにしない。

Site Adapterは、必要なsiteではCrawl Requestの `access_strategy` を参照し、quota用入口かdirect入口か等のsite固有操作を選択できる。quota上限やreset rule自体は知らない。

### Initial navigationとcanonical target

`RunConfig.source_url`は常にCatalog / Crawl Requestのcanonical crawl targetであり、
ProgressStore、CrawlRun、BatchCandidate、SourceTargetのidentityとして保持する。
ブラウザの最初の入口がtargetと異なるsiteでは、`SiteAdapter.resolve_initial_navigation_url(source_url)`
を使ってsite-localな初期遷移先だけを選択する。Base Adapterのdefaultは`source_url`そのものを返し、
CrawlerRunnerは`configure_run`と`configure_quota_resource`の後、最初の`page.goto()`にだけこのhookの結果を使う。
RunnerやGeneric Batch Coreにsite名・selector・URL分岐を追加しない。

明示grant-onlyと通常Batchのdeferred grantフェーズのprepared entryでは、Batch Executorの有界context managerが
resolverとentryに同一Page・Adapter・AccessGuardを渡し、context内で一度だけ利用できる。
Runnerは`entry_only`と借用Guardを要求し、設定・target検証後にAdapterの
`adopt_prepared_access_entry()`で既存document/snapshotを検証して初期gotoを省略する。
未対応Adapter、変更されたtarget/document、期限外context、再使用は停止する。
Runnerは借用Guardを再start/closeせず、所有contextが有界cleanupを行うため、
監視の空白やmetricsの二重計上を作らない。通常runのgoto/Guard所有権は従来どおり。

The optional site-neutral `configure_access_resource_resolution()` hook supplies
runtime content pacing and explicit Watchlist exclusions and returns a bounded
total resolver budget. Observation budgets remain separate. Zeblack's conditional
predecessor reread runs under the existing Page/AccessGuard, with no prerequisite
rights acquisition or content persistence, and replaces the prepared observation
only with a final fresh list document. Site selectors and recovery rules stay in
the Zeblack integration; see `DISCOVERY_AND_BATCH.md` for this bounded exception
to the ordinary single-list-load path. Other adapters keep their prior budget.

Zeblackの明示的な`quota + work_ticket`はcanonical viewer URLをtargetとして保持したまま、
最初のブラウザ入口を`/title/{title_id}/chapter/list`へ切り替える。Adapterはlive protobufで対象章の
statusと`mainName`を再確認し、`TICKET_AVAILABLE`のときだけchapter/listの対象行、確認modal、
exact ticket controlを順に扱う。FREE / RENTALはlive確認後にtarget viewerへ遷移し、POINT等は
target viewerへ遷移せずresource-unavailableとして終了する。

### `discovery/`（framework実装済み、site adapterはplanned）

Normal GUI/Batch/renumber use saved acquisition flags, per-key order and
archive_order. Sync stamps and full-listing proof are not execution/numbering
gates. Intermediate ordinals are provisional; one final renumber aligns archives.
DB stays v7. Optional archive_segments extends the existing saved configuration
JSON for manually interleaved ranges; segment-managed Works validate exact
placement through the shared archive_order module. Legacy configuration remains
compatible. Explicit scope-sync remains for deletion
and repair; identity and file safety checks remain in force.

Watchlist targetからitem/source候補を列挙する。

実装済みの責務:

- Discovery Service
- Discovery Adapter contract / registry
- site-specific discovery Adapterを受け入れるcontract
- full / incremental traversal orchestration
- successful Discoveryごとの取得担当flagの自動反映（key単位）。Batchは現在のCatalog flagsを使い、work全体のscope-sync完了を必須にしない。厳密な全体同期は任意の保守操作として提供する。
- default known-streak incremental stop
- site固有のstable boundaryが必要な場合に小さいincremental stop policyを受け入れる拡張点（BookWalkerが利用）
- duplicate candidate warningのためのCatalog query coordination

Discovery Adapter自身はSQLiteを直接read/writeしない。

共通framework、Manga ONEのreal-site listing Adapter、BookWalkerのseries-scoped real-site
listing Adapterを実装している。BookWalkerはWatchlistへ手動登録した `/series/<id>/list/` を
scope authorityとしてDiscoveryする。

### `catalog/`（Schema v3 target adopted）

SQLite Catalogを扱う。Schema v3のtargetは:

- `works`: 管理上の作品・刊行系列
- `items`: 巻・話・章・特典等の取得単位
- `sources`: site上のcontent identity / access / quota state
- `source_targets`: backend固有のopaqueな取得経路
- `crawl_runs`: 成功・失敗を含む実行履歴
- `artifacts`: ZIP等の成果物metadata / current physical state

DBはidentity、状態、履歴の正本とするが、画像・ZIP binary自体は保持しない。
Item completedとArtifact present/missing/deletedを分離し、成果物の移動・削除で過去のcrawl成功履歴を
失わない。

`source_targets` は `backend + target_key + locator` を持ち、backendはopaque stringとする。
同一SourceにWeb/Androidの複数targetを保持できる。現行runtimeはWebだけを実行可能とし、
Androidは将来の上位Dispatcher / Android Runnerへ分離する。

現在の実装はSchema v3の `works / items / sources / source_targets / crawl_runs / artifacts` である。
詳細schemaとtransition policyは `docs/DISCOVERY_AND_BATCH.md` をauthorityとする。

### `batch/`（implemented）

Catalogから対象sourceのenabled web targetを選び、既存Crawlerを呼ぶ。

- eligible source selection
- source priority
- quota記録
- Site Policy呼び出し
- `access_strategy` 解決
- Crawl Request作成
- known metadataのoptional override入力
- crawl success後のCatalog update

CrawlerRunnerへこの責務を移さない。

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

Discovery実装もreal-site browserを必要とする場合は同じBrowser Session Layerを再利用してよいが、browser lifecycleをDiscovery Adapterへ持ち込まない。

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

Site AdapterやDiscovery Adapterへ低レベルCDP session操作を広げない。

## 7. Authentication

login CLIはBrowser Session Layerから既存Crawler Chromeへlogin用Pageを新規作成し、site固有login functionがPlaywrightでDOM操作する。既存タブは再利用しない。

```text
Crawler Chrome/profile
    ↓ CDP
new login Page
    ↓
login_bookwalker / login_mangaone / future login handler
```

認証情報のinputは `.env` 等から取得してよいが、login後sessionの保存はChrome profileへ任せる。

Crawler独自のsite別auth-state fileは標準経路にしない。

CAPTCHA / MFA / validation errorは自動突破しない。

## 8. Runnerの概念フロー

```text
receive site-neutral Crawl Request
ensure output directory is new/empty
Browser SessionからPageを取得
prepare page
adapter receives run access intent
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
        optional adapter direct capture
        if unavailable, get one or more capture targets
        capture
        full capture-key duplicate guard
        save image artifact + manifest/progress
        go_next + bounded wait

normal terminal:
    crawler Pageをclose
    resolve packaging metadata
    package output
    Crawler Chrome自体は残す
```

`max_pages`到達後も、次stateがEND/NEXT_CONTENTなら正常終了できる。

Batch Runnerはこのflowの外側にあり、CatalogとSite PolicyからCrawl Requestを作る。

## 9. Access strategy boundary

`source.access_mode` と `Crawl Request.access_strategy` は別概念とする。

```text
Catalog source state:
  owned / free / quota / paid / unknown

Crawl execution intent:
  auto / direct / quota
```

Batch Runner / Site Policyがsource stateとgrant状態を評価し、今回のaccess strategyを決める。

例:

```text
quota source + active grant -> direct
quota source + no active grant + eligible -> quota
manual crawl -> auto
```

Coreはdaily limit、reset時刻、quota scope等を解釈しない。

Site Adapterが必要なsite固有button/entry操作だけを担当する。

Manga ONEのquota entryはCSR mount後に現れるため、Adapter内で最大2秒、100ms間隔のbounded waitを行う。候補数1件かつvisibleのbuttonだけをクリックし、曖昧な状態ではfirst要素を選択しない。

入口click前の候補未確認はAdapterが`AccessEntryNotAttemptedError`で報告する。
明示的な「ログインして読む」があればlogin必須をエラーに含める。
Batchはこの証拠がある場合だけ開始前に仮定したgrant期限を元へ戻し、
`quota_started_at`は保持する。開始前に保存した値から変化したgrantは上書きしない。
click開始後・消費不明・通常のtimeoutは従来どおりquota/grantを保持する。

## 10. Duplicate handling

The runner deduplicates each captured part using the complete key:

```text
(ContentIdentity(page_id, page_number, source_id, identity.fingerprint),
 part_count, part_index, capture_bytes_SHA-256)
```

Capture fingerprints are artifact evidence, not global logical-page identity.
Different logical identities with equal bytes and different parts of the same
spread are saved separately. When every identity field is unavailable, the
existing all-`None` identity fallback remains. A repeated full key remains
subject to the existing `max_same_content` guard. This behavior is implemented
in commit `17e9115908582ad7627beef3742ea5c97e705a5b`; adapters still need to
prove frame identity so stale bytes are not admitted as a different page.

Discovery側のcross-site duplicateは別問題として扱う。別siteの類似itemはwarningを出しても、自動mergeしない。

## 11. Output / packaging

Page artifacts are format metadata driven. Locator/canvas capture keeps the
default PNG behavior; Adapter direct capture may return original or
adapter-generated bytes with MIME type and extension. Runner and manifest
persistence follow that metadata, while packaging validates and includes only
manifest-declared safe PNG/JPEG/WebP artifacts. This remains site-neutral; source-byte selection belongs
inside the Site Adapter.

manifestのページ一覧を完成成果物のauthorityとする。packagingでdirectory globをauthorityにしない。

新規runは非空output directoryを拒否する。正常packaging後も、無関係ファイルが含まれるdirectoryは丸ごと削除しない。

packaging自体はCatalogを知らない。Schema v3では上位Batch Executorがpackaging成功後にarchiveのSHA-256/sizeを計算し、ArtifactとCrawlRunをCatalogへ記録する。

### 11.1 Output metadata resolution

packaging用metadataはfieldごとに:

```text
1. Crawl Request explicit metadata
2. Site Adapter metadata
3. packaging fallback
```

の順で解決する。

Crawl Requestでtitleだけ指定し、author/order/genreはAdapterへfallbackするような部分指定を許可する。

metadata overrideはmanifest/source URLのauthorityにはならない。

## 12. Site Adapterの最小契約

現行contractの概念:

```python
prepare_page(page)
prepare_entry_only_page(page)  # optional; defaults to prepare_page
configure_run(page, access_strategy)
initialize(page)
initialize_entry_only(page)  # optional; used when RunConfig.entry_only=True
detect_state(page)
get_capture_target(page)
get_capture_targets(page)
cleanup_capture_targets(page)
capture_page(page) -> tuple[CaptureResult, ...] | None
get_content_identity(page)
get_content_context(page)
go_next(page)
wait_for_change(page, previous_identity)
```

実際のdefault method / optional hookは `site_adapters/base.py` をauthorityとする。

`entry_only=True` は権利確認と消費確認のみを行う。RunnerはContent capture/save,
Manifest / Progress更新、packaging、Item completionを行わず、失敗diagnosticはmetadata/errorに
限定してscreenshotとHTML snapshotを省略する。Adapterがcapture専用の準備（例: pixel observer）を
避ける必要がある場合は`prepare_entry_only_page(page)`をoverrideできる。Base defaultは通常の
`prepare_page(page)`へ委譲する。Overrideはtarget validation、Page/AccessGuard ownershipおよびcleanupを
弱めない。通常capture pathの`prepare_page` behaviorは変更しない。

`capture_page()`は任意の直接capture hookである。非`None`の非空tupleを返した場合、Coreは
Locator captureを行わない。`None`、`CaptureUnavailableError`、bounded timeoutでは既存の
target captureへfallbackする。temporary resourceのcleanupは直接capture hook側が担当する。
このhookのsite-specificな実装はAdapter内に置き、CoreはBookWalker等のsite名を判定しない。

Crawl Requestの実装では、既存`RunConfig`へsite-neutralなrun access intentとoptional output metadataを最小限保持し、Adapterへ`configure_run(page, access_strategy)`で渡す。既定hookは`auto`だけを受け付け、未対応の`direct`/`quota`は明示的に停止する。Manga ONE Adapterは`auto`/`direct`/`quota`を受け付け、site-specific entry操作を実行する。

Adapterは以下をしない。

```text
Chrome launch
profile選択
CDP endpoint解決
connect_over_cdp
BrowserContext lifecycle管理
Discovery listing traversal
Catalog read/write
Site Policyによるquota eligibility判定
```

## 13. Site固有の終了判定

終了方法は共通化しすぎない。

- BookWalkerはviewer DOM / page counter / known final transitionを使う
- Manga ONEはchapter URL changeと、最終advance後にviewport内へ表示される終端UI marker、またはpage imagesが一定時間消失する既知挙動を使う。終端markerの連続表示確認中は、一時的なpage imageのidentity変化より終端判定を優先する。DOM上に存在するだけのviewport外markerは終端扱いしない

「明示END DOMがなければENDにしない」のような一般ルールで、実サイト確認済み挙動を置換しない。

## 14. Safety

別コンテンツや無関係ファイルを誤処理するより停止を優先する。

- UNKNOWNは停止
- retryはbounded
- 非空run dirは拒否
- resumeは暗黙実行しない
- packagingはmanifestをauthorityにする
- Coreへsite-specific ifを追加しない
- Adapterへbrowser/session管理を入れない
- Watchlist外を無制限Discoveryしない
- incomplete full syncでmissing sourceをunavailableにしない
- incrementalで未観測過去sourceをunavailableにしない
- default known-streakがsite固有access遷移に安全でない場合は、site-specific stable boundary policyを許容する
- cross-site duplicateを自動mergeしない
- paid/unknown sourceを自動crawlしない
- active quota grantを新規quotaとして二重消費扱いしない
- Site Policy ruleをCrawlerへ持ち込まない
- BookWalker Discoveryでreaderを開いてまる読みtimerを開始しない
- BookWalker `quota` strategyからtrial/owned/subscriptionへfallbackしない
- BookWalker `direct` strategyからtrial/maruyomi/subscriptionへfallbackしない
- `batch plan` はCatalogのstatus/local/quota stateを変更しない

BookWalkerの手動local quota復元は `scripts/restore_bookwalker_quota.py` が
既存Catalog APIを使い、current windowの予約1件を解除する。失敗後の再実行と
成功後の次冊取得を同じ操作で扱う。job lock内でtimestamp compare-and-setを行い、
履歴・Item status・Artifactは保持する。毎回のbackup、追加許可の保存用schema、
Core/Runnerへのsite固有分岐は追加しない。既定dry-run、空き枠はno-op、複数予約は停止。

## 15. 移行状態

Browser Session architectureは採用済みで、共通launcherとshared-profile live verificationまで完了している。

標準launcherは `start_crawler_chrome.ps1`、profileは `.chrome-crawler`、global endpointは `CRAWLER_CDP_ENDPOINT` である。site別launcherは削除済みで、site-specific endpoint/profileは例外overrideとしてのみ扱う。BookWalker/Manga ONEのshared-profile login/crawlとsession共存はlive verification済みである。

BookWalker/Manga ONEのviewer/navigation/END判定は維持する。BookWalkerだけはAdapter内で
source-native captureを先に試し、必要時に既存Canvas cropへfallbackする。Browser Session Layerと
運用launcherはsite-neutralなままとする。

Watchlist loader、Catalog Service（`items` / `sources` / `source_targets`）、Crawl Requestの最小基盤、site-neutral Discovery framework、
Phase 5AのBatch Planner / Site Policy基盤、Manga ONE Policy、Phase 5BのManga ONE Batch Executor、
BookWalkerのseries-scoped Discovery / Policy / Batch integration / strict direct・quota entry、
およびsource-native captureを実装済みとする。

## 16. Discovery / Catalog / Batch dependency rules

上位subsystemの依存方向は次を守る。

```text
Watchlist loader
      ↓
Discovery Service ─────→ Catalog Service
      ↓                        ↑
Discovery Adapter              │
                               │
Batch Runner ───────→ Site Policy
      │
      ↓
Crawl Request
      │
      ↓
existing crawl orchestration
      ↓
CrawlerRunner -> Site Adapter
```

### Discovery Adapter

site固有の作品一覧・話一覧・access状態の観測だけを担当する。

- DB APIを呼ばない
- cross-site mergeしない
- Batch policyを知らない

### Discovery Service

- Watchlist targetを選ぶ
- `full / incremental` を実行する
- Adapter結果をCatalogへupsertする
- `full + complete` の場合だけscope内missing sourceをunavailable化する
- cross-site duplicate candidateをCatalogから照合しwarningする

### Catalog Service

- Schema v3では `works / items / sources / source_targets / crawl_runs / artifacts` をauthorityとしてread/writeする
- Watchlist `work_key` をstable Work identityへ、`key` をsource `discovery_key`へ対応させる
- external discovery state、Item completed、CrawlRun history、Artifact physical stateを混同しない
- Work / Itemのknown output metadataをNULL許容で保持できる
- Web Discoveryが`source_targets`の`backend=web,target_key=default` targetを最新locatorでupsertする
- backendはopaque stringとし、Android等のtargetをWeb実行可否とは独立して保存できる

### Batch Runner

- Phase 5Aではpending item/sourceをread-onlyでCatalogから読む
- free/owned/quota等の優先順位を適用する
- Site Policyでquota eligibilityを判定する
- active grantを評価し、`direct / quota` を解決する
- Catalog metadataをoptional overrideとしてplan candidateへ入れる
- quota仮予約はmemory内だけで行い、Catalogへ永続化しない
- `quota_available` は計画前のlocal枠、`quota_remaining` は仮予約後の残枠を表す
- Phase 5Bではcandidateを順番に実行し、quota candidateはCrawler開始直前にlocal stateを保存する
- Schema v3では実行開始時にCrawlRun(running)を作り、成功/失敗を履歴として保持する
- crawl + packaging + Artifact persistence成功後だけItemをcompletedにする
- archive pathはItemへ置かずArtifact locatorへ保存する
- crawl、viewer、packaging、Catalog persistenceの失敗時はitemをcompletedにせず、quota stateは保持する
- candidateごとに一意なrun directoryを使い、stop-on-first-failureで後続を実行しない
- 現行Web Executorは`backend=web` targetだけを実行し、`target_id / backend / target_key / locator`を保持する
- `locator`を既存`RunConfig.source_url`へ変換し、実行直前にtarget identity/stateを再検証する
- 将来Android対応は上位dispatcherでbackend別Runnerへ振り分け、CrawlerRunner/Pageを無理に共通化しない

### Site Policy

site固有のquotaや再閲覧猶予を扱う。

汎用rule DSLは作らず、必要なsiteだけ小さいPython Policyとして実装する。

Phase 5Aでは `SitePolicyRegistry` にManga ONEだけを登録する。未登録siteは
明示エラーとして停止する。Manga ONE Policyはsite-wideのlocal quotaを4枠とし、
09:00/21:00 JSTのhalf-open windowで`quota_started_at`を数える。active grant
（`access_granted_until > now`）はdirect扱いでslotを消費しない。利用者の手動消費や
外部clientの残量はCatalogから観測できないため、これはlocal eligibility estimateである。

### Crawl Request

Batchまたは手動CLIからCrawlerへ渡すsite-neutralな実行入力。

- `site`
- `url`
- `access_strategy = auto | direct | quota`
- optional `title / author / order / genre`

Catalog identityやquota ruleそのものは含めない。
### Shared Batch identity and local resource gate

Batch may call the optional scalar
`SiteAdapter.configure_target_identity(external_id, work_key)` before Runner
navigation. This lets a site adapter bind Catalog identity to target-local live
checks without giving Core Catalog access or site-specific identity rules.
Work-scoped local resource cooldown checks run before opening a consuming
candidate page; local skips do not count as site attempts or pacing events.

### Confirmed access grant persistence

`ConfirmedAccessGrant` is an immutable site-neutral event containing the exact
site/external identity, an aware observation time, a finite aware expiry later
than that observation, and its evidence kind. `SiteAdapter` exposes optional
`set_confirmed_access_grant_observer(callback | None)` and
`configure_existing_access_grant(expiry | None)` hooks. The Batch Executor
binds the observer to the already validated Catalog source, validates the
immutable event, and synchronously calls the Catalog grant-only API before
capture continues. The Catalog update changes only that source grant expiry
and its update timestamp; quota state, resource state, Items, and Artifacts
remain untouched. The Executor disables and clears the observer on every run
exit. Runner remains independent of Catalog. Existing-grant context is reset
for each run, including a `None` expiry.

## Hanayume Source identity maintenance

Hanayume Full Discovery may observe a site native identity proof that an old
episode URL now resolves to a new episode ID. The site adapter is responsible
for the bounded API proof; Core never merges by title, position, content ID,
or neighboring rows. A proven change is applied through the common Catalog
maintenance transaction, which retains the existing Item/Source IDs and all
historical CrawlRun, Artifact, quota, and ZIP state while updating the current
external ID and web target locator. Existing Catalog schema/version contracts
are unchanged. When proof is unavailable, the maintenance CLI provides the
same dry-run/token/apply path for explicit human confirmation.


## GUI live monitor and history (Phase 04)

The lower execution monitor and JobsPage are passive views over the existing
JobController and JobStore. They share the bounded fixed-path LogTailReader and
Qt-free result Presenter; controller/DB state remains authoritative. View
initialization and refresh failures are isolated from queue advancement and
safety operations, while controller/database failures remain fail-closed.
GUI submission catches controller-ownership/queue/worker-start exceptions at
the Qt action boundary and reports them in-window. The controller exposes a
RuntimeError-compatible ownership exception; it keeps the existing OS lease.
Initialization publishes store/controller only after successful reconciliation
and releases the lease if reconciliation fails. Registered-but-unstarted jobs
are identified explicitly and never retried automatically.
Events use bounded latest/keyset reads and metrics use authorized incremental
JSONL reads. Raw stdout/stderr remain separate, and the upper inventory layout
and execution controls retain their existing order and meaning.
- Work-deletion preview safety update (2026-11-14): the read-only planner treats a sealed management binding as a complete set, checks catalog-specific recovery markers before any Work classification, and binds plan tokens to root identity/volume, management logical state, status facts and the gate fingerprint. Existing destination operation directories, ambiguous/untracked artifacts, unsafe status paths, duplicate locators and uncertain worker states block. SQLite WAL/SHM sidecars are fail-closed before read-only open so preview cannot change SQLite read marks or source file metadata.
- Duplicate locator refinement (2026-11-14): exact same-Work/path/size/SHA/owner historical duplicates remain represented by every Artifact ID, warn, and nominate one primary move; shared or mismatched ownership/content remains blocking. Supervision-error markers and raw status-path traversal are blocking before canonical resolution.
- Work-deletion Apply (2026-11-14): the service path revalidates a fresh plan under admission→Catalog→Watchlist locks, writes a durable fsync manifest and verified standalone backup, performs no-clobber same-volume file moves with per-file hash checks, then executes exact Catalog graph deletion and lossless Watchlist target/archive CAS. Pre-commit exceptions restore files; commit uncertainty is observed as `RECOVERY_REQUIRED`. The CLI and GUI surfaces now use this same path.
- Work-deletion Stage 02 safety refinement (2026-11-14): destructive Apply is bound to a canonical same-instance preview cache and path/namespace token, persists Watchlist originals plus per-file intent/verification, reserves `active.json`, and carries strong file identity through rename and rollback. Ambiguous filesystem/database/YAML state never chooses rollback; final target and non-target invariants are checked before releasing the reservation.
- Work-deletion Stage 02 cutover refinement (2026-11-14): the namespace reservation is written before the manifest, and a previously present Watchlist that disappears after replacement is treated as `RECOVERY_REQUIRED`, never as DONE. File and parent-directory fsync barriers are best-effort; Windows/filesystem and physical-power-loss durability limits are explicit, with process-kill recovery deferred to Stage 03.
- Work-deletion locator compatibility (2026-11-14): relative Catalog Artifact locators and status `archive_path` values resolve from the established process CWD, matching archive audit/renumber and Batch behavior. Deletion does not reinterpret them relative to a custom Catalog parent; traversal and reparse checks still run before canonical resolution.
- Work-deletion operation namespace refinement (2026-11-14): the trash operation directory is exclusively created before any snapshot/manifest write. If an external actor wins that name race, Apply stops without touching the existing directory, manifest, marker, or source data.
- Work-deletion recovery/gate (2026-11-14): recovery is an explicit dry-run/apply service and CLI path backed by durable operation history, admission→Catalog→Watchlist locking, exact Catalog/Watchlist before/after fingerprints, and per-file size/SHA/strong-identity observations. Discovery, registration, Batch, and effective-Catalog enqueue recheck the read-only deletion gate after acquiring the Catalog lock; active/pending, malformed, unknown, or manifestless reservations fail closed. Catalog rows marked missing/deleted are still blocked when their recorded ZIP or status locator exists physically, so stale state cannot hide a later Batch collision. Process-kill recovery is isolated-tested; physical power-loss durability is not claimed. Independent Stage 03 review is BLOCKING-0 approved.
- Work-deletion move portability boundary (2026-11-14): destructive no-clobber rename is enabled only on Windows in this initial implementation, where the tested native rename semantics reject an existing destination. Other platforms fail closed before moving; no POSIX check-then-rename guarantee is claimed.
- Work-deletion recovery safety (2026-11-14): recovery dry-run treats SQLite WAL/header/sidecars and hot journals as unknown without creating locks or SQLite files; explicit apply may use SQLite's native hot-journal rollback under the Catalog lock. Recovery manifests require canonical Catalog/Watchlist/namespace bindings and verified backup facts. Catalog deletion compares the full non-target logical fingerprint inside the same transaction before COMMIT, and unknown Catalog tables/columns fail closed. These boundaries are covered by the isolated Stage 03 review-approved suite.
- Work-deletion GUI gate follow-up (2026-11-14): standalone Watchlist editor saves always use an effective Catalog admission/gate identity (`catalog_path` or isolated `catalog.sqlite` default); optional Catalog binding semantics for scope previews remain unchanged. Page, Watchlist, runtime, and worker paths are canonicalized at construction, so delayed workers cannot re-resolve them under a changed CWD. A pending deletion reservation blocks the save, and normal save resumes only after verified gate release. Manifest `active_marker` values are checked against the canonical Catalog namespace. GUI/work-deletion isolated coverage is 95 passing tests; Stage 03 independent review is BLOCKING-0 approved.
- Work-deletion Stage 04 surface (2026-11-14): direct CLI preview/apply JSON and the archive Work context-menu dialog both invoke the common service. CLI output includes authoritative title/site keys, graph and ZIP/byte counts, operation/manifest identifiers, blockers and warnings; blocked and recovery-required results are nonzero. The Qt dialog previews on a QRunnable, requires explicit confirmation, and applies only the cached canonical Plan; all paths are absolute at owner construction. Defaults are the existing isolated packaging roots (`output/Books`, `output/crawl-status`, `output/trash/work-deletion`). Independent Stage 04 review is BLOCKING-0 approved; real data and live sites remain out of scope. The affected isolated suite is 313 passed with 442 warnings; the full-suite attempt is recorded as incomplete because of a Windows async teardown timeout.

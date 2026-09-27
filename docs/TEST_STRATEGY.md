# Test Strategy

## 1. 目的とauthority

この文書は、Screenshot Crawlerにおける**テスト分類・テスト選択・実行範囲のauthority**である。

目的は、変更による回帰リスクに見合ったテストを選び、必要な安全網を維持しながら開発ループで不要なフルsuite実行を避けることである。

Core回帰、Browser Session回帰、Site Adapter前提崩壊、Discovery / Catalog / Batchの回帰を分けて検出する。実サイト確認済みの挙動を、根拠なく一般化したロジックで置換しない。

2026-09-27の実測・棚卸しは `note/test_suite_audit.md` に保存している。そこに記録された件数・所要時間は測定snapshotであり、この文書の恒久的な分類基準ではない。

### 基本原則

- **すべての変更で `pytest -q` を実行する必要はない。**
- 開発中は変更に直接対応するtargeted testsを優先する。
- 完了前は、変更した契約とその境界に応じて影響範囲を広げる。
- フルsuiteは、shared componentの広い変更、大規模refactor、複数領域変更、または影響範囲に確信が持てない場合の安全網として使う。
- test directory名だけで実行範囲を決めず、テストが実際に通る境界・依存関係で判断する。
- 外部実サイトを恒常的なpytest / CI authorityにしない。

## 2. Test taxonomy

テストは責務により次の4種類に分類する。実行時間の長短そのものは分類軸にしない。

### 2.1 Unit

実browser・外部サービスを必要とせず、単一コンポーネントまたは狭い契約をローカルで検証する。

SQLite、temporary filesystem、ZIP、Pillow等のローカルI/Oを使うだけではIntegration扱いにしない。

主な対象:

- PageState / models
- parser / naming / normalization
- fingerprint
- Runner guards / bounded timeout logic
- max_pages境界
- duplicate / same-content
- manifest / progress
- output directory safety
- packaging / manifest validation
- Adapter helper / pure selection logic
- Watchlist / Catalog / migration / reconciliation
- Batch Planner / Executorのlocal contract
- Site Policy
- CLI parser / orchestrationをfake dependencyで検証するもの
- CDP endpoint resolution
- global endpoint / site override precedence

### 2.2 Integration

実Chromium / Playwright Page / Locator / DOM、または複数コンポーネントの実際の境界を通して検証する。

外部実サイトへの接続は必要条件ではない。人工HTML、local viewer、route fixtureであっても、実browserを起動してDOM・capture・transitionを検証するものはIntegrationとする。

主な対象:

- Core Runner + local viewer
- Adapter + real DOM / Locator
- Browser-backed Discovery
- canvas / image signature等のbrowser runtime依存処理
- capture flow
- END / NEXT_CONTENT / LOADING transition
- Browser Session boundary

### 2.3 Research / Probe

`poc/`、probe、diagnostic experiment等、調査手段そのものの正しさを検証する。

Research / Probe testsは通常のproduction変更の完了条件には含めない。対象のPoC / probe / research helperを変更した場合、またはその調査結果に依存する作業を行う場合だけ実行する。

PoCで発見した挙動がproductionのsupported contractへ昇格した場合は、その契約をproduction側のUnitまたはIntegration testとして改めて表現する。PoC内部実装の全ケースを恒久production regressionとして残す必要はない。

### 2.4 Live verification

実サイト、実account、実viewer、実quota / ticket state等を使って確認する。

pytestの代替ではなく、人工fixtureでは保証できないsite-specific observationの確認である。

主な対象:

- 実DOM selector / button / reader control
- final content / END behavior
- 実サイトのloading / transition
- login / session共存
- quota / ticket / rental behavior
- real source capture

### 2.5 Slowは分類ではない

`slow` を第5の責務カテゴリとして扱わない。

Unitでもproductionの3秒delayをそのまま待てば遅くなり、Integrationでもfixture設計次第で高速にできる。遅さは分類ではなく改善対象として扱う。

## 3. 現行layoutに関する移行上の注意

現時点ではdirectory名と上記taxonomyが完全には一致していない。

特に、`tests/unit/` 内にも実Chromiumを起動するbrowser-backed testが存在し、`poc/` を直接importするresearch/probe testも存在する。詳細は `note/test_suite_audit.md` を参照する。

したがって分類整理が完了するまでは:

- `pytest tests/unit` を「高速なpure unit suite」とみなさない
- `tests/integration/` だけを全Integration testとみなさない
- browser / PoC依存をコード実体で確認してtest selectionする

Phase 2以降でdirectory配置をtaxonomyへ合わせる。

## 4. Codex test selection policy

### 4.1 開発中

変更中は最小のtargeted testを使う。

例:

```bash
pytest -q tests/unit/test_batch.py::test_new_quota_is_allocated_to_oldest_episode_first
pytest -q tests/unit/test_mangaone_discovery.py
```

小さな修正のたびにフルsuiteを実行しない。

### 4.2 実装完了前

完了前に、変更した契約と直接関係するtest file / groupまで範囲を広げる。

例:

```text
Batch Planner変更
→ plannerを直接検証するtests
→ 影響したSite Policy tests

Site Adapter pure helper変更
→ 当該adapterのpure tests

Site Adapter DOM/viewer変更
→ 当該adapter tests
→ relevant browser-backed integration

CrawlerRunner変更
→ Core Runner tests
→ local viewer integration
```

### 4.3 変更種別ごとの最低範囲

| 変更対象 | 最低限の完了時テスト |
|---|---|
| pure helper / parser / model | 対応するtargeted Unit |
| Site Policy | 当該site policy + 影響するPlanner/Executor Unit |
| Site Discovery pure logic | 当該site discovery Unit |
| Site Discovery DOM/browser | 当該discovery Unit + relevant Integration |
| Site Adapter pure logic | 当該adapter Unit |
| Site Adapter DOM/viewer/capture | 当該adapter Unit + relevant Integration |
| Batch Planner | Planner Unit + 関連Policy |
| Batch Executor | Executor Unit + 関連Policy / Catalog |
| CLI orchestration | 関連CLI Unit。実時間pacingは原則fake/override |
| Catalog schema / migration | Catalog / migration + 影響するDiscovery / Batch |
| Packaging / output | Packaging + 影響するBatch Executor |
| Core Runner | Core Unit + local viewer Integration |
| Browser Session共通層 | Browser Unit + relevant browser Integration |
| 複数site/shared contract | 影響する各Unit + relevant Integration |
| Research / Probe | 対象Research / Probe tests。production testsはproduction contractへの影響時のみ |
| 大規模refactor / 影響範囲不明 | broad affected tests + full suiteを強く推奨 |

この表は最低範囲であり、変更した契約が別レイヤーへ伝播する場合はその境界テストを追加する。

### 4.4 Full suiteを実行する条件

`pytest -q` は次の場合に実行する。

- shared Core / Runnerの広い変更
- shared Browser Sessionの大幅変更
- Catalog schemaや共通data modelの広い変更
- 複数siteへ影響する共通化・refactor
- 大規模なファイル移動・責務再編
- test selectionの影響範囲に確信が持てない
- release / milestone /明示的な全回帰確認

小さいsite-local fix、parser修正、単一policy修正などでは、関連testsが十分ならfull suiteを必須としない。

## 5. Test implementation policy

### 5.1 新しいテストを増やす基準

バグ修正・仕様変更のたびに必ずtest case数を1件増やす必要はない。

次の順で検討する。

1. 既存testの期待値変更で契約を表現できないか
2. 既存testへのcase追加 / parameterizeで表現できないか
3. 既存testでは別契約になり、独立した回帰保証が必要なら新規testを追加する

新規testは「何を壊したら失敗するか」が既存testと区別できることを目安にする。

### 5.2 UnitとIntegrationの重複

同じ機能をUnitとIntegrationの両方で確認してよい。ただし保証する層を分ける。

例:

```text
Unit:
terminal判定条件そのもの

Integration:
実DOMがterminal状態になったときAdapter + RunnerがENDへ到達
```

同じ内部条件を同じ方法で二重に検証しているだけなら統合・削減候補とする。

### 5.3 実時間wait / pacing

productionのdelay / timeout値そのものが検証対象でない限り、テストでproductionと同じ実時間を待たない。

例:

- `inter_candidate_delay_ms=3000` の存在を確認したい → 値またはsleep invocationを検証し、3秒実待機しない
- viewer timeout時のfailure contractを確認したい → 短いtest-specific timeoutを注入する
- pacing後に次candidateへ進むことを確認したい → fake sleep / dependency injectionを使う

実時間そのものがユーザー向け契約であり、wall-clock behaviorの検証が必要なケースだけ例外とする。

### 5.4 Browser fixtures

browser-backed testでは、test isolationを壊さない範囲で不必要なbrowser launch / context creationの重複を避ける。

fixture scopeを広げる場合は、cookie、storage、listener、route、page state等がtest間で漏れないことを確認する。

### 5.5 External site dependency

外部実サイトへの恒常的なCI依存は作らない。

実サイトの著作物・DOM snapshotを恒久fixtureへコピーしない。人工fixtureまたは必要最小限の非著作物データを使う。

## 6. Test execution reporting

Codexは最終報告で、実行したテストだけでなく、重要な未実行カテゴリと理由も明示する。

例:

```text
Tests run:
- PASS: tests/unit/test_batch.py
- PASS: tests/unit/test_magapoke_policy.py

Not run:
- Integration: browser/viewer behaviorに変更なし
- Research/Probe: poc/に変更なし
- Live verification: 実サイト挙動に変更なし
- Full suite: shared/core変更ではないため未実施
```

IntegrationがChromium unavailable等でskipされた場合は、pytest exit codeだけでなくskip件数と理由を報告する。

## 7. Browser Session Tests

共通Crawler Chrome関連では最低限次を確認する。

### Endpoint precedence

```text
--cdp-endpoint
> <SITE>_CDP_ENDPOINT
> CRAWLER_CDP_ENDPOINT
> default 9222
```

### Lifecycle

- CDP connectionから既存BrowserContextを取得できる
- Crawler用Pageを作れる
- crawl終了時にCrawler Pageだけcloseする
- remote Chrome process自体をcloseしない
- loginとcrawlが同じBrowser Session helperを利用できる

### Adapter boundary

- Adapterがendpoint/profile/Chrome launchを要求しない
- AdapterへPlaywright Pageを渡せば従来どおり動く
- access strategyのためにAdapterへCatalog/Site Policy依存を持ち込まない

Discovery Adapterがreal browserを必要とする場合も、browser/session lifecycleをAdapter自身に持たせない。

Raw CDP helperを追加する場合は、Playwright APIで代替できない理由をtest/docに残す。

## 8. Local Integration coverage

Playwright + 人工ローカルviewerを使うIntegrationでは主に以下を確認する。

- CONTENT → CONTENT → END
- AD skip
- NEXT_CONTENT
- LOADING → CONTENT
- unresolved LOADING timeout
- UNKNOWN stop
- same-content guard
- spread capture
- max_pages境界
- Manga ONEのimage-disappearance END heuristic
- Manga ONE chapter change
- site-specific capture / terminal behavior

Discoveryでは人工listing fixtureを使い、外部実サイトをCI authorityにしない。

Crawl Request拡張では、人工viewerまたはsite-specific fixtureで次を確認する。

- `auto` が既存entry behaviorを維持する
- `direct` がquota activation pathを選ばない
- `quota` がsite-specific quota entry pathへ伝わる
- Core自体にsite-specific quota selector/ifが入らない

## 9. Packaging tests

最低限:

- manifest記載artifactだけZIPへ入る
- manifest外の古いartifactはZIPへ入らない
- manifest記載ファイル欠落は失敗
- 無関係ファイルがあるsource directoryをrmtreeしない

Metadata override:

- explicit titleがAdapter titleより優先される
- explicit orderだけ指定し、author/genreはAdapter値を利用できる
- explicit値がNULL/空ならAdapterへfallbackする
- Adapter値もなければ既存packaging fallbackを使う
- metadata overrideでmanifest/source URLを変更しない

Batch統合では、packaging成功時だけCatalog itemをcompletedへ更新し、archive pathを保存することも確認する。

## 10. Live verification

Adapterの実サイト挙動を変更する場合は、可能な範囲で対象サイトを確認する。

最低観点:

1. 開始直後
2. 通常数ページ
3. spread / single transition
4. 広告前後（存在する場合）
5. 最終本文
6. 最終本文後
7. NEXT_CONTENT
8. 読み込みが遅いケース

Discovery Adapter追加・変更時:

- target作品だけを列挙する
- external ID / URL
- title / author / genre / kind / order（取得可能な範囲）
- free / owned / quota / paid表示
- 期間限定無料表示と終了日時
- latest側の順序
- fullで最終itemまで到達すること
- incrementalで既知領域へ到達できること

quota entry behaviorを持つSite Adapterでは、可能な範囲で:

- manual `auto`
- `direct`
- `quota`
- quota消費後grant期間中の再閲覧（grantを持つsiteのみ）
- requested strategyに合わないreader controlへfallbackしないこと

BookWalkerでは追加で:

- Watchlistの `/series/<id>/list/` だけをDiscovery scopeにする
- 同じseries listの商品が同じcanonical series titleを使う
- Discovery中にreaderをclickせず、まる読みtimerを開始しない
- owned / quota / paid / unknownのstrong-signal分類
- `subscription_reading` 単独をquota扱いしない
- existing quota/ownedをtrial/unknown観測だけでdowngradeしない
- existing paid/unknownはincrementalで再確認する
- run開始前からquota/ownedの既知sourceでstable boundary停止する
- 今回paid -> quotaになったsource自身では停止しない
- same external_id / different discovery_keyをscope conflictとして停止する
- local quotaは05:00 JST windowで1 quota book
- quota attempt失敗後も同windowでslotをrefundしない
- `access_granted_until` をdirect判定に使わない
- strict `quota` がtrial / owned / subscriptionへfallbackしない
- strict `direct` がtrial / maruyomi / subscriptionへfallbackしない

実サイトの著作物・DOM snapshotを恒久fixtureへコピーしない。

## 11. Browser Session migration smoke test

共通 `.chrome-crawler/` でBookWalker/Manga ONEそれぞれのlogin/crawlとsession共存を確認済みである。以後はこの確認項目をBrowser Session回帰の基準として維持する。

### 共通Chrome

- 同じCrawler Chrome processへ接続できる
- BookWalker login sessionが維持される
- Manga ONE login sessionが維持される
- 一方のloginが他方を壊さない
- Crawler Pageを閉じてもChromeと他tabは残る

### BookWalker

- 商品ページ→viewer
- single/spread capture
- final END

### Manga ONE

- chapter viewer
- spread order
- final image disappearance END

Browser Session移行のためにsite-specific viewer logicを変更しない。

## 12. Regression priority

優先度が高い失敗:

- 最終本文を保存せず終了
- viewer終端を認識できずtimeout
- 広告やnext contentを本文として保存
- 同一ページを大量保存
- 古いrun artifactを新ZIPへ混入
- user fileをcleanupで削除
- UNKNOWNなのに進行
- Coreへのsite-specific分岐混入
- AdapterへのCDP/profile管理混入
- Crawler終了時にremote Chromeを誤ってclose
- site-specific overrideがglobal defaultを壊す
- Watchlist外の作品をDiscoveryする
- incomplete full syncで既存sourceをunavailableにする
- incrementalで未観測過去sourceをunavailableにする
- cross-site duplicateを自動mergeする
- DiscoveryでItem completed statusやArtifact stateを上書きする
- paid/unknown sourceを自動crawlする
- quotaを誤って二重消費扱いする
- active grantなのに新規 `quota` strategyを選ぶ
- quota sourceだからという理由だけでCrawlerがquota ruleを再判定する
- metadata overrideが不足fieldを消す
- metadata overrideで実source URLを置換する
- crawl失敗をcompleted扱いする
- BookWalker quota/ownedをtrial観測だけでdowngradeする
- BookWalker quota requestがtrial readerへfallbackする
- BookWalker strict direct requestがmaruyomi/trialへfallbackする
- BookWalker quota失敗後に同じ05:00 windowで自動再試行する

## 13. Discovery Sync Tests

### Full sync

最低限:

- empty Catalogへ全sourceを追加
- 同じfullを再実行してsourceを重複作成しない
- 既存sourceのURL変更を更新
- free -> paid / paid -> freeを更新
- `free_until`変更を更新
- title/author/genre/order metadataを更新できる
- `complete=true` で未観測sourceを `available=false` にする
- `complete=false` では未観測sourceを変更しない
- sourceを物理削除しない
- completed statusとArtifact stateを維持する
- `discovery_key` が異なるsourceへmissing判定を波及させない

### Incremental sync

最低限:

- latest側の未知sourceを追加
- 複数の新規sourceを追加
- current generic known-streak policyに従って停止する
- unknown / new source観測でstreakが適切にresetされる
- site-specific stable-boundary policyを使うsiteではgeneric policyを適用しない
- 走査中に見たknown sourceのexternal stateをrefresh
- 未観測過去sourceをunavailableにしない

### Cross-site duplicate

- 別siteで同title/kind/order候補をwarningできる
- warningだけで自動mergeしない
- warningだけで自動completed化しない
- heuristic不一致で既存itemを書き換えない

## 14. Batch / Site Policy Tests

最低限:

- 期限が近いfreeを通常freeより優先
- freeをownedより優先
- ownedをquotaより優先
- paid / unknownを除外
- quota上限到達時にskip
- quota scopeがsite単位/作品単位等のPolicyに従う
- quota消費を定められたcommit timingで永続化する
- `access_granted_until` 内のretryでPolicyに従い追加quotaを消費しない
- grant期限後は再度quota eligibilityを評価
- quota source + active grantで `access_strategy=direct`
- quota source + no grant + eligibleで `access_strategy=quota`
- free/owned sourceで `access_strategy=direct`
- Batchがdaily limit/reset ruleをCrawl Requestへ含めない
- Catalog metadataをCrawl Requestのoptional output metadataへ入れられる
- crawl成功 + packaging成功でCrawlRun/Artifactを確定し、Itemをcompletedへ更新
- crawl失敗でpendingを維持
- `item_id / source_id / archive path` の対応が維持される
- Batchが既存Crawlerへsite-neutralなCrawl Requestを渡し、CrawlerRunnerへCatalog依存を追加しない

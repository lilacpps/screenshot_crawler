# AGENTS.md

このリポジトリでは、Codexは以下をauthorityとして実装する。

## Authority order

1. `docs/SPEC.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DISCOVERY_AND_BATCH.md`（Discovery / Catalog / Batch変更時）
4. `docs/ACCESS_CONTROL_AND_PACING.md`（shared runtime pacing / AccessGuard / metrics / access-resource selection / grant-only変更時）
5. `docs/MAGAPOKE_BATCH_ACCESS.md`（Magapoke固有のBatch / Work Ticket / Premium Ticket / resource rule変更時）
6. `docs/ACCESS_CONTROL_AND_PACING_PLAN.md`（上記shared access仕様の実装Phase・受け入れテスト）
7. `docs/DECISIONS.md`
8. `docs/TEST_STRATEGY.md`（テスト分類・選択・実行範囲）
9. `docs/CODEX_IMPLEMENTATION_GUIDE.md`
10. `docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md`（新規Site Adapterをmulti-agentで自律実装する場合）
11. 現在のコードとテスト
12. Site Adapter固有README / probe出力
13. `note/` の現行実装ノート

`note/` は詳細な現行実装スナップショットとして常に更新する。ただし、上位authorityと競合する場合は上位authorityを優先し、note側を修正する。

仕様と実装が競合した場合、黙って仕様を変更しない。差分を明示し、既存の実サイト確認済み挙動を壊さない最小修正を選ぶ。

## Browser Session policy

Real-site automationの標準設計は次とする。

```text
shared Crawler Chrome/profile
    ↑ CDP
Playwright Browser / Context / Page
    ↓
Core Runner
    ↓
Site Adapter
```

必須ルール:

- Real-site browserへの接続は原則CDP
- 接続後の通常操作はPlaywright `Page` / `Locator`
- 共通profile `.chrome-crawler/` をdefaultとする
- global endpoint `CRAWLER_CDP_ENDPOINT` をdefaultとする
- site-specific endpoint/profileは必要な場合だけoverride
- Site AdapterからChrome launch / profile選択 / endpoint解決 / `connect_over_cdp()` を行わない
- Raw CDP ProtocolはPlaywrightで代替できない場合だけ使う

shared profileでBookWalker/MANGA ONEのlogin・crawl・session共存と既存viewer behaviorをlive verification済みである。real-siteのlauncher/profileは共通構成を標準とし、site-specific endpoint/profileは例外overrideとしてのみ扱う。

## Implementation rules

- Python 3.12+ / Playwright Pythonを使用する。
- Coreにサイト固有selector、URL、サイト名による分岐を追加しない。
- サイト固有挙動は `site_adapters/<site>/` に置く。
- YAMLで複雑な条件分岐を表現する独自DSLを作らない。
- Patternは軽量な再利用部品に留め、深い継承階層を作らない。
- 1サイトだけで必要な処理を早期に共通化しない。
- UNKNOWN状態では無理に進行させない。
- retryには必ず上限を設ける。
- max_pages / same-content guardを外さない。
- 実装変更には対応するテストを追加・更新する。新規test caseの追加自体を目的にせず、既存testの拡張・parameterize・置換で十分ならそれを優先する。
- テスト分類・選択・実行範囲は `docs/TEST_STRATEGY.md` に従う。全変更でフル `pytest -q` を実行する必要はない。
- 外部実サイトへの恒常的なCI依存は作らない。
- fixtureには実サイトの著作物をそのまま保存しない。
- Discovery AdapterからCatalogへ直接writeしない。
- CrawlerRunnerへCatalog依存を持ち込まない。
- site横断itemの自動mergeを行わない。
- `source.access_mode` とCrawlerの `access_strategy` を混同しない。
- quota limit/reset/scope等のSite Policy ruleをCrawler Coreへ持ち込まない。
- `access_strategy` に応じたsite固有entry操作はSite Adapterに置く。
- output metadataはfield単位で `explicit Crawl Request > Adapter > packaging fallback` とする。
- metadata overrideでsource URLやmanifest URLを置換しない。
- generic Batch/Coreに `work_ticket` / `premium_ticket` など特定siteのresource名をハードコードしない。
- access resourceの候補・順序はSite Policy/integration、実際の利用可否・消費確認はlive site state / Site Adapterをauthorityとする。
- あるresourceのattempt中に別resourceへ暗黙fallbackしない。resource切替は明示的なpass orchestrationで行う。

## Multi-agent workflow for new Site Adapters

ユーザーが新規Site Adapterについてmulti-agent / 自律実装を明示的に依頼した場合は、`docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md` に従う。

基本役割:

- root orchestrator: GPT-6.1 Sol。結果を見ながら現在Phase・追加Probe・修正方針・次Phaseを決める。
- `site_adapter_worker`: GPT-5.6 Luna。Probe / PoC / production実装 / test / live verificationを担当する唯一のproduction writer。
- `site_adapter_reviewer`: GPT-6.1 Sol、read-only。各worker iteration後の品質ゲートを担当する。

必須ルール:

- rootは最初に全手順を固定して機械的に消化しない。実サイト観測・テスト・review結果に応じてPhaseを分割、追加、反復、差し替えしてよい。
- 各Phaseでrootは目的、既知事実、未確認事項、変更範囲、制約、受け入れ条件、必要なtest/live verificationをworkerへ明示する。
- worker完了後は必ずreviewerへreviewを委譲する。
- reviewerの`BLOCKING`が1件でも残る間は次Phaseへ進まない。workerによる追加Probe/修正後に再reviewする。
- 不明な実サイト挙動を推測でproduction実装へ落とさない。必要ならProbe/PoCへ戻る。
- production writeを行うsubagentは同時に1つだけとする。並列化は独立したread-heavy調査に限定する。
- reviewerはファイルを変更しない。追加testや実行確認が必要ならroot経由でworkerへ依頼する。
- 新規Site Adapterのproduction変更前にfeature branch上であることを確認する。未commitのユーザー変更を破棄・上書きしない。
- free-only scopeではticket / point / coin / paid resource等を消費しない。
- 実験用Catalogが指定されている場合、通常の`catalog.sqlite`へ暗黙fallbackしない。
- root sessionのモデルはrepository全体へ固定しない。multi-agent Site Adapter作業開始時にGPT-6.1 Solを選択する。

## Multi-agent workflow for existing BookWalker capture research

ユーザーが既存BookWalker adapterのsource-native capture / JPEG・PNG判定 / viewer provenanceについて
multi-agent / 自律調査・実装を依頼した場合は、
`docs/BOOKWALKER_SOURCE_NATIVE_CAPTURE_RUNBOOK.md` を基礎runbookとして使用し、個別stageは
`runbooks/bookwalker-source-native/README.md` の順序に従う。

基本原則は以下。

> **Research is lead-driven. Review is change-driven. Critic is risk-driven.**

通常の調査では次の2役だけをactiveにする。

- root/Lead: GPT-6.1 Sol。証拠十分性、A/B/C/D分類、次のbounded Probe、実装要否を判断する。
- `bookwalker_worker`: GPT-5.6 Luna。live調査、Probe、必要最小限のdiagnostic、実装、test、
  live verificationを担当する唯一のproduction writer / live-viewer operator。

`bookwalker_reviewer` は通常のResearch loopには入れない。production codeを変更した場合はmerge前に必須とし、
diagnosticをdurable production/test contractへ昇格させる場合やLeadが重要判断の独立確認を必要とした場合だけ使う。

`bookwalker_critic` はroutine gateにしない。既存proof/fail-closed gateを弱める、heuristic attributionを導入する、
観測範囲を超えて一般化する、大きなshared abstraction/refactorを行う等、silent wrong-artifact riskが高い設計判断でのみ使う。
Research開始時・終了時に機械的に呼ばない。

BookWalkerでは「JPEG化」を目的化せずsource-native formatをauthorityとする。sourceがPNGならPNGのままを正解とし、
dimension / filename / timing / visual similarityだけでJPEG candidateへ結びつけない。証拠不足ならD/fail-closedで終了してよい。
viewerは読書位置を永続化するため、live probeごとにactual page stateを確認し、必要なら明示的に巻き戻してから調査する。
複数agentが同時にviewerを操作してはならない。

## Note synchronization rule

仕様・実装・テスト・運用方法を変更した場合、**同じ変更の中で対応する `note/` も更新することを必須**とする。

更新先:

- Core / Runner / output / packaging / browser / diagnostics / resume等の共通変更 → `note/00_core.md`
- Discovery / Catalog / Batchの共通変更 → `note/00_core.md`（実装前は未実装であることも明記する）
- BookWalker固有変更 → `note/01_bookwalker.md`
- Manga ONE固有変更 → `note/02_mangaone.md`
- Magapoke固有変更 → `note/03_magapoke.md`
- 新規サイト追加 → 対応する `note/<nn>_<site>.md` を追加
- 共通変更が実サイト挙動にも影響する場合 → `00_core.md` と影響するsite noteの両方

計画段階のaccess-control仕様同期には `note/04_access_control_plan.md`、Magapoke固有の未実装計画同期には `note/03_magapoke_access_plan.md` を使用する。Catalog v6 / display position / archive naming / archive renumber / Item status拡張の採用済み未実装計画は `note/07_catalog_position_archive_plan.md` を使用する。これらは明示的に PLANNED / NOT YET IMPLEMENTED とし、現行実装スナップショットと混同しない。

noteには少なくとも、現在の挙動、主要な判定ロジック、設定/CLI、出力、既知の制約、実サイト確認状況を残す。

履歴だけを追記して古い仕様を残すのではなく、読めば現行仕様が分かる状態へ本文を更新する。古い判断を残す必要がある場合は `docs/DECISIONS.md` またはGit履歴を使う。

認証情報、Cookie、storage state、秘密情報はnoteへ書かない。

詳細は `note/README.md` を参照する。

## Before coding

1. `docs/CODEX_IMPLEMENTATION_GUIDE.md` を読む。
2. `docs/TEST_STRATEGY.md` を読み、変更する契約に対するtargeted / affected / integration / live verificationの必要範囲を決める。
3. 変更対象に対応する `note/` を読む。Catalog v6 / display position / archive naming / archive renumber / Item status拡張を変更する場合は `note/07_catalog_position_archive_plan.md` も読む。
4. Discovery / Catalog / Batchを変更する場合は `docs/DISCOVERY_AND_BATCH.md` を読む。
5. shared runtime pacing / AccessGuard / metrics / generic access-resource selection / grant-onlyを変更する場合は `docs/ACCESS_CONTROL_AND_PACING.md` と `docs/ACCESS_CONTROL_AND_PACING_PLAN.md` を読む。
6. Magapoke固有のWork Ticket / Premium Ticket / resource semanticsを変更する場合は `docs/MAGAPOKE_BATCH_ACCESS.md` を読む。
7. noteとコードが食い違う場合はcode/testsと上位authorityを確認し、作業内でnoteも同期する。
8. Browser関連変更では `docs/SPEC.md` のBrowser Session Modelを確認する。
9. 新規Site Adapterをmulti-agentで自律実装する場合は `docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md` を読む。

## After coding

`docs/TEST_STRATEGY.md` に従い、変更した契約に対して必要なテストを選択して実行する。

基本順序:

```text
targeted tests
→ 影響範囲のtests
→ 必要なbrowser-backed Integration
→ shared / large / uncertain changeではfull pytest
→ 必要な場合だけlive verification
```

小さいsite-local fixやparser / policy修正で関連testsが十分なら、フル `pytest -q` は必須ではない。逆にshared Core、共通data model、大規模refactor、複数領域変更、影響範囲が不明な変更ではfull suiteを実行する。

現在は `tests/unit/` にbrowser-backed test、production test群にResearch / Probe相当のtestが一部混在しているため、directory名だけでtest categoryを判断しない。

可能なら以下も実行する。

```bash
ruff check src tests
```

完了前に、変更内容に対応する `note/` が更新されていることを確認する。note更新が不要な変更なら、その理由を最終報告に書く。

最後に以下を報告する。

- 変更したファイル
- 更新したnote
- 仕様上の判断
- 実行したテストと結果
- 重要な未実行カテゴリ（Integration / Research / Live / full suite）と未実行理由
- skipped testがある場合は件数と理由
- 未解決事項・実サイト確認が必要な事項

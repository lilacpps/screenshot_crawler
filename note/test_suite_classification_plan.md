# Test Suite Classification Plan

調査日: 2026-09-28
対象: `screenshot_crawler` の Phase 2A 分類設計と Phase 2B 実施結果
位置づけ: **設計・移行計画資料。テスト方針の authority ではない。**
authority: [`docs/TEST_STRATEGY.md`](../docs/TEST_STRATEGY.md)

この資料は、pytest test fileを`Unit` / `Integration` / `Research / Probe`に分類した
Phase 2Aの設計と、Phase 2Bで実施した物理配置整理の結果を記録する。これは現時点の
調査・実装ノートであり、テスト方針のauthorityではない。

## 1. Executive Summary

### Phase 2A baseline（履歴）

- Phase 2A時点のmainで**785 cases**をcollectionした。
- 当時の内訳は`tests/unit/`が**43 files / 763 cases**、
  `tests/integration/`が**2 files / 22 cases**。Research directoryはまだなかった。
- 実測コマンドは、workspace rootをimport pathに明示した次のcollectionである。

  ```powershell
  $env:PYTHONPATH = (Get-Location).Path
  uv run pytest --collect-only -q
  ```

- `note/test_suite_audit.md` のフルpytest時間（約4分）は777/782-case時点の測定
  snapshotであり、現在のruntime baselineには使用しない。

### Phase 2A proposed classification（履歴）

| proposed category | cases | file shape | 根拠 |
|---|---:|---:|---|
| Unit | **611** | pure Unit 31 files + 混在8 filesのUnit部分 | 実Chromium・外部サイト・実DOMを必要としないローカル契約 |
| Integration | **128** | 現在の2 files + 混在8 filesのbrowser部分 | `Page` / `Locator` / real DOM / browser runtime / Core+Adapter境界 |
| Research / Probe | **46** | `poc/`直接依存の4 files | production contractではなくprobe / reconstruction / observation手段の検証 |
| **合計** | **785** | 既存45 filesを、移動4 + 分割8を経て53 files相当 | parametrize展開後 |

Phase 2Aでは、`tests/unit/`に残っている**8 mixed files / 106 browser cases**と、
同じくunit配下の**4 Research/Probe files / 46 cases**を整理対象とした。これは当時の
分類案であり、BookWalker Adapterのbrowser case数はPhase 2B実測で1 case増えた。

### Phase 2B progress (2026-09-28)

- **2B-1 completed**: Research / Probe 4 filesを`tests/research/`へ移動。
- **2B-2 completed**: `test_access_guard.py`、`test_mangaone_discovery.py`、
  `test_bookwalker_original_capture.py`をUnit / Integrationへ分割。
- **2B-3 completed**: browser-heavy mixed 5 filesをUnit / Integrationへ分割。
- 現在のcollectionは Unit 610 / Integration 129 / Research 46 / Total 785。
- `tests/unit/`は実Chromiumを起動せず、`tests/integration/`にreal Page / DOM boundary、
  `tests/research/`にpoc / probe testsを配置している。
- `pytest -q tests/unit tests/integration`はproduction regression、
  `pytest -q tests/research`はResearch / Probe regression、`pytest -q`はResearchを含む
  repository-wide regressionとして実行できる。
- 今回はfixture scope変更、browser起動回数削減、timeout短縮等の高速化を行っていない。

Phase 2B-3の計画値ではBookWalker Adapterを18 Unit / 25 Integrationとしていたが、
現行sourceをcollection case単位で実測すると17 Unit / 26 Integrationだった。他の4 filesは
計画値どおりであり、全体はtest追加・削除なしの785 casesを維持している。browser依存caseを
Unitへ残さず、parametrizeやassertionも変更しない条件ではこの差分を勝手に補正せず、Open
Questionとして記録する。

## 2. Current Test Inventory

表中の `DB` はSQLite/Catalog、`FS` はfilesystem/temp path、`IMG` は画像・codec・
canvas処理、`WAIT` はsleep/timeout/pollingまたはそれに近い待機を表す。`—` は、今回の
static scanでその依存を主対象として確認していないことを表し、処理が一切存在しない
という意味ではない。

`real Page` は実Chromiumを起動してPage/Locator/DOMを操作するもの、`fake Page` は
browser-shaped fakeを使うもの、`—` は該当なしである。

### 2.1 Existing integration files（Phase 2A baseline）

| path | cases | current | proposed | browser / Page | PoC direct | prod import | local concern | 主な対象 / 方針 |
|---|---:|---|---|---|---|---|---|---|
| `tests/integration/test_local_viewer_flows.py` | 19 | Integration | Integration | real Page | — | Yes | FS / IMG / WAIT | local viewerとCore RunnerのCONTENT / LOADING / END / NEXT_CONTENT / UNKNOWN、spread、same-content、max_pages。維持。 |
| `tests/integration/test_magapoke_local_viewer.py` | 3 | Integration | Integration | real Page | — | Yes | FS / IMG / WAIT | Magapoke + Core Runner、JPEG reconstruction / screenshot fallback、terminal card。維持。 |

### 2.2 Phase 2A unit directory inventory（履歴）

| path | cases | current | proposed | browser / Page | PoC direct | prod import | local concern | 主な対象 |
|---|---:|---|---|---|---|---|---|---|
| `tests/unit/test_access_guard.py` | 7 | Unit | **Unit + Integration** | real + fake Page | — | Yes | WAIT | AccessGuard / HTTP stopはUnit、captcha DOM判定1 caseはIntegration。 |
| `tests/unit/test_auth.py` | 12 | Unit | Unit | — | — | Yes | FS | auth state path / context選択。 |
| `tests/unit/test_batch.py` | 33 | Unit | Unit | — | — | Yes | DB / FS | BatchPlanner、quota、ordering、metadata。 |
| `tests/unit/test_batch_executor.py` | 34 | Unit | Unit | fake Page | — | Yes | DB / FS / WAIT | Executor、Catalog、fake adapter、packaging。 |
| `tests/unit/test_bookwalker_adapter.py` | 43 | Unit | **Unit + Integration** | real + fake Page | — | Yes | IMG / WAIT | pure parser / policyはUnit、entry DOM・capture signatureはIntegration。 |
| `tests/unit/test_bookwalker_batch.py` | 4 | Unit | Unit | fake Page | — | Yes | DB / FS | BookWalker quotaとBatch境界。 |
| `tests/unit/test_bookwalker_discovery.py` | 54 | Unit | **Unit + Integration** | real Page | — | Yes | DB / FS / WAIT | parser / inferenceはUnit、listing/product DOMとCatalog syncはIntegration。 |
| `tests/unit/test_bookwalker_native_capture.py` | 16 | Unit | Unit | fake Page | — | Yes | IMG | geometry / native capture helper。 |
| `tests/unit/test_bookwalker_native_source.py` | 7 | Unit | Unit | — | — | Yes | IMG | response / source bytes。 |
| `tests/unit/test_bookwalker_original_capture.py` | 13 | Unit | **Unit + Integration** | real + fake Page | — | Yes | IMG / WAIT | bytes/cache/listenerはUnit、canvas JSとbrowser image signatureはIntegration。 |
| `tests/unit/test_bookwalker_policy.py` | 12 | Unit | Unit | — | — | Yes | DB / FS | Site Policy / quota / grant判定。 |
| `tests/unit/test_bookwalker_reader_controls.py` | 12 | Unit | Unit | fake Page | — | Yes | WAIT | reader control分類・候補選択。 |
| `tests/unit/test_browser.py` | 9 | Unit | Unit | — | — | Yes | WAIT | BrowserSession lifecycle / cleanup semantics。 |
| `tests/unit/test_catalog.py` | 26 | Unit | Unit | — | — | Yes | DB / FS | Catalog schema / upsert / reconciliation。 |
| `tests/unit/test_catalog_backup.py` | 5 | Unit | Unit | — | — | Yes | DB / FS | SQLite backup / restore safety。 |
| `tests/unit/test_catalog_export.py` | 10 | Unit | Unit | — | — | Yes | DB / FS | Catalog export。 |
| `tests/unit/test_catalog_migrations.py` | 9 | Unit | Unit | — | — | Yes | DB / FS | SQLite migration / compatibility。 |
| `tests/unit/test_cli.py` | 63 | Unit | Unit | fake Page / fake session | — | Yes | DB / FS / WAIT | CLI parser、orchestration、output、metrics。 |
| `tests/unit/test_core_features.py` | 39 | Unit | Unit | fake Page | — | Yes | FS / IMG / WAIT | Runner state、retry、timeout、capture、same-content。 |
| `tests/unit/test_discovery.py` | 18 | Unit | Unit | fake Page | — | Yes | DB / FS / WAIT | generic DiscoveryService。 |
| `tests/unit/test_env.py` | 7 | Unit | Unit | — | — | Yes | FS | environment / endpoint resolution。 |
| `tests/unit/test_flatten_zip_archives.py` | 10 | Unit | Unit | — | — | Yes | FS | ZIP flatten / collision / filesystem safety。 |
| `tests/unit/test_jumpplus_adapter.py` | 39 | Unit | Unit | fake/browser-shaped | — | Yes | IMG / WAIT | Jump+ adapter parser / navigation / capture helper。 |
| `tests/unit/test_jumpplus_discovery.py` | 11 | Unit | Unit | fake Page | — | Yes | FS / WAIT | Jump+ discovery parser / listing / pagination。 |
| `tests/unit/test_jumpplus_discovery_probe.py` | 7 | Unit | **Research / Probe** | — | **Yes** | No direct production import | FS / WAIT | `poc.jumpplus_discovery_matrix` / `poc.jumpplus_discovery_probe`。 whole-file move候補。 |
| `tests/unit/test_jumpplus_policy.py` | 14 | Unit | Unit | — | — | Yes | DB / FS | Jump+ Site Policy / Catalog plan。 |
| `tests/unit/test_jumpplus_probe.py` | 11 | Unit | **Research / Probe** | — | **Yes** | No direct production import | FS / IMG / WAIT | `poc.jumpplus_probe` の identity / network / report。 whole-file move候補。 |
| `tests/unit/test_jumpplus_reconstruct.py` | 13 | Unit | **Research / Probe** | — | **Yes** | No direct production import | FS / IMG | `poc.jumpplus_reconstruct` の画像 reconstruction。 whole-file move候補。 |
| `tests/unit/test_launcher.py` | 4 | Unit | Unit | — | — | Yes | FS / WAIT | launcher command / profile / endpoint validation。 |
| `tests/unit/test_magapoke_adapter.py` | 76 | Unit | **Unit + Integration** | real + fake Page | — | Yes | IMG / WAIT | viewer DOM / entryはIntegration、policy / codec / safety helperはUnit。 |
| `tests/unit/test_magapoke_discovery.py` | 17 | Unit | **Unit + Integration** | real Page | — | Yes | DB / FS / WAIT | listing DOM / Catalog syncはIntegration、mapping / parserはUnit。 |
| `tests/unit/test_magapoke_policy.py` | 20 | Unit | Unit | — | — | Yes | DB / FS | quota / work ticket / premium ticket policy。 |
| `tests/unit/test_mangaone_adapter.py` | 25 | Unit | **Unit + Integration** | real Page | — | Yes | IMG / WAIT | quota entry / viewerはIntegration、URL・capture・retry helperはUnit。 |
| `tests/unit/test_mangaone_discovery.py` | 12 | Unit | **Unit + Integration** | real Page | — | Yes | DB / FS / WAIT | browser listing 1 caseはIntegration、parser / mappingはUnit。 |
| `tests/unit/test_mangaone_login.py` | 2 | Unit | Unit | fake Page | — | Yes | WAIT | login form interaction。人工fakeで契約を確認。 |
| `tests/unit/test_models.py` | 8 | Unit | Unit | — | — | Yes | — | model value semantics / RunConfig validation。 |
| `tests/unit/test_packaging.py` | 17 | Unit | Unit | — | — | Yes | FS | output packaging / manifest。 |
| `tests/unit/test_registry.py` | 1 | Unit | Unit | — | — | Yes | — | adapter registry。 |
| `tests/unit/test_restore_bookwalker_quota.py` | 2 | Unit | Unit | — | — | Yes + `scripts` | DB / FS | local repair utilityの小さな契約。Researchではなくutility Unit候補。 |
| `tests/unit/test_runtime_settings.py` | 10 | Unit | Unit | — | — | Yes | FS | runtime settings。 |
| `tests/unit/test_state.py` | 1 | Unit | Unit | — | — | Yes | — | state value / transition。 |
| `tests/unit/test_watchlist.py` | 15 | Unit | Unit | — | — | Yes | FS | watchlist load / validation。 |
| `tests/unit/test_zeblack_probe.py` | 15 | Unit | **Research / Probe** | — | **Yes** | No direct production import | FS / IMG / WAIT | `poc.zeblack_capture_probe` / `poc.zeblack_probe`。 whole-file move候補。 |

### 2.3 Inventoryの読み方

- Phase 2A時点の`tests/unit/` 43 filesのうち、8 filesは実Chromiumを起動するmixed fileであった。
- 4 filesは`poc/`を直接importするResearch/Probe候補である。
- したがって、unit配下の残りは **31 files / 470 cases** がfile単位でUnit維持候補、
  8 mixed fileのUnit部分は **141 cases** である。
- production importがあること自体はIntegrationの根拠ではない。fake Page、SQLite、
  filesystem、ZIP、Pillowだけなら、`docs/TEST_STRATEGY.md`上はUnitに留められる。

## 3. Mixed File Breakdown

以下のbrowser case数は、関数数ではなくparametrize展開後のcollection case数である。
これはPhase 2B後の実測値であり、`Unit cases` と`Integration cases`の合計は各fileの
元のcase数に一致する。BookWalker AdapterだけはPhase 2A計画値18/25から実測17/26へ
差分が生じた。

| file | Unit cases | Integration cases | browser portion | fixture / implementation observation | whole-file or split |
|---|---:|---:|---|---|---|
| `test_access_guard.py` | 6 | 1 | captcha providerのvisible DOM判定 | 1 testだけが`async_playwright()` / `chromium.launch()`を直接実行。runner / HTTP status / metricsはfake・local。 | split |
| `test_bookwalker_adapter.py` | 17 | 26 | strict entry control、delayed DOM、viewer URL、canvas / capture target | `browser_page` fixtureは実Chromium。fake pageのnavigation / parser testも同一fileにある。Phase 2A計画は18/25。 | split |
| `test_bookwalker_discovery.py` | 35 | 19 | series / product listing、control classification、full/incremental Catalog sync | `browser_page` fixtureで人工routeを使用。pure parser / inference / hookはfixture不要。 | split |
| `test_bookwalker_original_capture.py` | 9 | 4 | canvas JS、PNG/JPEG browser signature、draw trace | `browser_page` fixture。magic bytes、cache、fallback、listener policyはfake/local。 | split |
| `test_magapoke_adapter.py` | 33 | 43 | entry、viewer DOM、terminal card、premium/work control、canvas hook | `_new_page()`が35 source testの各所でPlaywrightを起動。単一shared fixtureではなく、browser部分の分離後も起動回数が大きいままになる点に注意。codec / mapping / fake retryはUnit。 | split |
| `test_magapoke_discovery.py` | 11 | 6 | listing DOM、multiple containers、Catalog sync / incomplete | `browser_page` fixtureで人工HTML routeを利用。access mapping / date parserはUnit。 | split |
| `test_mangaone_adapter.py` | 18 | 7 | quota entry、async button、viewer appearance、terminal boundary | `browser_page` fixture。URL parser、WebP/source capture、retry / fallbackはUnit。 | split |
| `test_mangaone_discovery.py` | 11 | 1 | chapter listing DOM / card mapping | `browser_page` fixtureを使う1 testのみ。parser / access / titleはUnit。 | split |

### 2.4 Current post-Phase 2B layout

Phase 2B完了後の実ファイル配置とcollectionは次のとおりである。以下はPhase 2Aの
分類案ではなく、2026-09-28に実行したcurrent collectionの結果である。

| current group | Unit | Integration | Research | 備考 |
|---|---:|---:|---:|---|
| existing pure Unit files | 470 | — | — | file単位でUnit維持 |
| small mixed files after split | 26 | 6 | — | AccessGuard 6/1、Manga ONE discovery 11/1、BookWalker original capture 9/4 |
| browser-heavy mixed files after split | 114 | 101 | — | BookWalker Adapter 17/26、Discovery 35/19、Magapoke Adapter 33/43、Discovery 11/6、Manga ONE Adapter 18/7 |
| existing Integration files | — | 22 | — | local viewer 2 files |
| Research / Probe files | — | — | 46 | `tests/research/` 4 files |
| **Total** | **610** | **129** | **46** | **785 cases** |

`tests/unit/`の実Chromium起動・`async_playwright()`・`chromium.launch()`はPhase 2B後の
対象範囲に残っていない。`Page`型注釈やfake browser-shaped objectの利用はUnitのままである。

### Mixed fileで特に分けるべき境界

- `async_playwright` / `chromium.launch`をtestまたはbrowser fixtureが実行するか。
- `Page` / `Locator` / `evaluate` / `route` / canvas runtimeの実挙動を契約に含めるか。
- fake Pageで同じsite adapterのpure helperを確認しているだけならUnitに残す。
- browserを使わないpure helperをIntegrationへ一緒に移すと、分類後の対象範囲が不必要に
  膨らむため、8 filesはwhole-file moveではなくtest関数単位のsplitが必要である。

## 4. Research / Probe Analysis

### 4.1 Direct `poc/` imports

次の4 filesが直接`poc`をimportしている。

| current path | cases | direct import | 内容 | 推奨 |
|---|---:|---|---|---|
| `tests/unit/test_jumpplus_discovery_probe.py` | 7 | `poc.jumpplus_discovery_matrix`, `poc.jumpplus_discovery_probe` | pagination / discovery observation matrix | `tests/research/`へwhole-file move |
| `tests/unit/test_jumpplus_probe.py` | 11 | `poc.jumpplus_probe` | identity / network / report probe | `tests/research/`へwhole-file move |
| `tests/unit/test_jumpplus_reconstruct.py` | 13 | `poc.jumpplus_reconstruct` | reconstruction algorithmの研究用検証 | `tests/research/`へwhole-file move |
| `tests/unit/test_zeblack_probe.py` | 15 | `poc.zeblack_capture_probe`, `poc.zeblack_probe` | capture / observation probe | `tests/research/`へwhole-file move |

これらは画像処理やparserを含むため、技術的にはUnitに似たケースもある。しかし、
assertの対象がproduction moduleのsupported contractではなく、`poc/`の調査実装そのもの
である点を優先してResearch/Probeとする。これは価値が低いという意味ではなく、通常の
production regression suiteと実行 cadenceを分ける候補という意味である。

### 4.2 `scripts` import

`tests/unit/test_restore_bookwalker_quota.py` は`poc`ではなく
`scripts.restore_bookwalker_quota`をimportしている。これは調査probeではなくlocal repair
utilityの小さな契約を確認しているため、現時点ではUnit候補として扱う。production
regressionとutility script testを将来分けるかはOpen Questionとする。

### 4.3 import pathの注意

現行の直接importはworkspace rootの`poc` / `scripts`を必要とする。今回の環境では、
import pathを明示しないpytest invocationでは5 filesがcollection errorになり、
workspace rootを`PYTHONPATH`に入れたcollectionでは785 casesを得た。これは今回修正
しないが、`pytest tests/research`を独立実行するPhase 2B acceptanceで確認すべき事項である。

## 5. Proposed Directory Layout

### 5.1 Phase 2B後の最終形

```text
tests/
  unit/
    31 file-level Unit files
    8 mixed filesに残したUnit tests
  integration/
    existing 2 files
    8 mixed filesから分離したbrowser tests
  research/
    test_jumpplus_discovery_probe.py
    test_jumpplus_probe.py
    test_jumpplus_reconstruct.py
    test_zeblack_probe.py
```

Phase 2Bでは、当面はflat layoutを採用した。site別のsubdirectoryは、Integrationや
Researchのfile数が増え、pathだけで対象範囲が明確になる規模になったときに再検討する。
現時点で`tests/integration/bookwalker/`等を新設する必要性は、分類だけからは確認できない。

### 5.2 Directoryだけで表現できないもの

- slow / browser-heavyは独立categoryではない。Integration内にも軽いDOM testと重い
  wait/canvas testがある。
- Research/Probeでもproduction adapterの変更に影響する観測結果があれば、必要な
  targeted testとして明示的に実行する余地がある。
- Live verificationはpytest directoryへ入れず、実サイト確認手順として扱う。

## 6. Import / Fixture Impact

### 6.1 Import impact

- production importの大部分は現状のまま維持できる。test fileのdirectory移動だけで
  `screenshot_crawler` importを変更する前提はない。
- `poc` / `scripts`はworkspace root依存があるため、isolated invocationとCI/IDEの
  Python pathをPhase 2Bで確認する必要がある。今回、import pathを補う変更は行わない。
- test module間のimportを前提とする構造は、移動対象4 filesについて個別に確認する。

### 6.2 Fixture impact

- `tests/conftest.py`はなく、`tests/fixtures/`もREADMEのみである。fixtureは各test
  file内に定義されている。
- そのため、mixed fileを分割するときは、browser fixtureをIntegration側へ、fake/local
  helperをUnit側へ複製または小さく再配置する必要がある。ただし、これはPhase 2Bの
  implementation taskであり、今回の設計では実施しない。
- `browser_page` fixtureはBookWalker / discovery / capture / Manga ONEでfunction-scoped
  のlocal fixtureとして使われている。`test_magapoke_adapter.py`は`_new_page()`を各
  browser testから呼ぶ構造で、directory移動だけではbrowser launch回数は減らない。
- fixture scope変更は今回の禁止事項であり、分類移行と高速化を同じ変更に混ぜない。

### 6.3 Pytest settings / markers

現在の`pyproject.toml`は`asyncio_mode = "auto"`と`testpaths = ["tests"]`のみで、
markerや除外設定はない。Phase 2Bの初期案ではdirectory commandで十分なため、markerを
追加しない方が変更面積は小さい。markerが必要になるのは、Researchの一部だけを頻繁に
除外したい等、directoryで表せない選択要件が実測で出た場合に限る。

## 7. Migration Steps / Result (Phase 2B)

Phase 2Bでは次の手順を実施した。test behavior、assertion、parameterize数、fixture
scope、pytest設定、production codeは変更していない。

1. **Inventory freeze**
   - 785 casesのbaseline collectionを保存した。
   - 4 Research filesのdirect importと、8 mixed filesのbrowser function listを固定する。
2. **Research whole-file move**
   - 4 filesを`tests/research/`へ移動し、`pytest -q tests/research`で46 casesを維持した。
3. **Mixed split: smallest boundary first**
   - `test_access_guard.py`、`test_mangaone_discovery.py`、
     `test_bookwalker_original_capture.py`をUnit / Integrationへ分けた。
   - Unit側のfake/local helperとIntegration側のreal browser fixtureの依存を分離する。
4. **Mixed split: adapter/discovery heavy files**
   - BookWalker adapter/discovery、Manga ONE adapter、Magapoke discovery、
     Magapoke adapterをtest function単位で分けた。
   - `test_magapoke_adapter.py`はbrowser launch helperの共有・scope変更を分類移行と
     同時に行わない。
5. **Import / fixture cleanup**
   - move後に壊れたrelative import、root import、fixture名衝突だけを修正する。
   - production code、test contract、fixture scopeは変更しない。
6. **Baseline comparison**
   - total 785 cases、Unit 610、Integration 129、Research 46をcollectionした。
   - Unit / Integration / Research / fullの各suiteを実行し、全てpassした。
   - BookWalker AdapterだけはPhase 2Aの18/25計画値と実測17/26に1 caseの差があり、
     test改変なしでは補正できないためOpen Questionとして残した。
7. **Separate optimization phase**
   - browser launch回数、実時間wait、fixture scope、画像処理時間の改善は、分類移行が
     安定した後の別Phaseで扱う。

## 8. Acceptance Tests for Phase 2B

Phase 2B完了時に次を実行した。Chromiumは利用可能で、Integrationのskipはなかった。

```powershell
pytest --collect-only -q tests/unit
pytest --collect-only -q tests/integration
pytest --collect-only -q tests/research

pytest -q tests/unit
pytest -q tests/integration
pytest -q tests/research
pytest -q
```

確認する項目:

- `tests/unit` に実Chromium起動testが残っていないこと。
- `tests/research` が4 files / 46 casesを収集すること。
- `tests/integration` が既存22 cases + browser-backed 107 casesを収集したこと。
- 全体collectionが785 casesから変化していないこと。
- `tests/unit` 610 passed、`tests/integration` 129 passed、`tests/research` 46 passed、
  full `pytest -q` 785 passedを確認したこと。
- `.venv`の標準invocationではResearch / scripts import errorは再現しなかったこと。

markersは初期移行の受け入れ条件に含めない。directory単位の明示実行で不足する場合だけ、
別途設計する。

### Phase 2B-3 runtime baseline (2026-09-28)

警告を抑制した実測（`pytest -q -p no:warnings`）は次のとおりである。これは高速化前の
baselineであり、fixture scope、browser起動回数、timeout / pacingは変更していない。

| suite | result | time |
|---|---|---:|
| `tests/unit` | 610 passed | 52.48s |
| `tests/integration` | 129 passed | 169.99s |
| `tests/research` | 46 passed | 0.46s |
| full (`--durations=30`) | 785 passed | 223.66s |
| full plain `pytest -q` | 785 passed / 2,774 warnings | 250.67s |

slowest 30（full、`--durations=30`）:

```text
10.09s  tests/integration/test_mangaone_adapter_browser.py::test_mangaone_quota_entry_fails_if_viewer_does_not_appear
6.60s   tests/integration/test_local_viewer_flows.py::test_runner_local_dom_same_identity_hits_same_content_guard
6.04s   tests/unit/test_cli.py::test_batch_run_replans_premium_after_work_pass_and_stops_at_zero_balance
6.04s   tests/unit/test_cli.py::test_grant_only_all_uses_policy_order_replans_and_shares_limit
6.04s   tests/unit/test_cli.py::test_batch_run_limit_spans_initial_and_premium_phases
4.47s   tests/integration/test_magapoke_local_viewer.py::test_magapoke_runner_stops_at_terminal_card_without_opening_next_episode
4.26s   tests/integration/test_local_viewer_flows.py::test_mangaone_graceful_end_and_chapter_change_are_distinct
3.56s   tests/integration/test_local_viewer_flows.py::test_mangaone_image_gap_becomes_end_after_grace_period
3.05s   tests/unit/test_cli.py::test_grant_only_all_moves_to_next_policy_pass_after_resource_exhaustion
3.03s   tests/unit/test_cli.py::test_batch_run_continues_after_work_ticket_unavailable
2.51s   tests/integration/test_local_viewer_flows.py::test_runner_local_dom_state_flows[steps0-2-end]
2.50s   tests/integration/test_local_viewer_flows.py::test_runner_local_dom_state_flows[steps1-2-end]
2.49s   tests/integration/test_local_viewer_flows.py::test_runner_local_dom_state_flows[steps3-2-end]
2.48s   tests/integration/test_local_viewer_flows.py::test_runner_local_dom_exact_max_pages_can_stop[end]
2.45s   tests/integration/test_local_viewer_flows.py::test_runner_local_dom_exact_max_pages_can_stop[next_content]
2.42s   tests/integration/test_local_viewer_flows.py::test_runner_local_dom_state_flows[steps2-2-next_content]
2.15s   tests/integration/test_bookwalker_discovery_browser.py::test_bookwalker_full_clean_exhaustion_reconciles_missing_source
2.11s   tests/integration/test_bookwalker_discovery_browser.py::test_bookwalker_full_reconciles_first_volume_after_later_release
2.10s   tests/integration/test_magapoke_local_viewer.py::test_magapoke_reconstructs_jpeg_and_falls_back_to_screenshot
1.64s   tests/integration/test_bookwalker_discovery_browser.py::test_bookwalker_incremental_stable_boundary_via_service[initial0-observed0]
1.49s   tests/integration/test_bookwalker_adapter_browser.py::test_bookwalker_strict_waits_for_transient_duplicate_to_settle
1.49s   tests/integration/test_bookwalker_adapter_browser.py::test_bookwalker_strict_waits_for_delayed_maruyomi
1.43s   tests/integration/test_mangaone_adapter_browser.py::test_mangaone_quota_entry_waits_for_async_button
1.41s   tests/unit/test_batch_executor.py::test_quota_state_remains_when_crawl_fails
1.39s   tests/integration/test_bookwalker_adapter_browser.py::test_bookwalker_strict_overlapping_scopes_count_same_element_once
1.37s   tests/integration/test_local_viewer_flows.py::test_runner_local_dom_saves_spread_parts_with_same_pixels
1.37s   tests/integration/test_bookwalker_adapter_browser.py::test_bookwalker_strict_uuid_comparison_is_case_insensitive
1.36s   tests/integration/test_bookwalker_adapter_browser.py::test_bookwalker_strict_direct_clicks_only_owned
1.35s   tests/integration/test_bookwalker_adapter_browser.py::test_bookwalker_strict_direct_allows_owned_without_control_uuid
1.34s   tests/integration/test_local_viewer_flows.py::test_mangaone_offscreen_terminal_marker_does_not_become_end
```

## 9. Risks / Open Questions

### Risks

- mixed fileの分割時に、fixture・helper・parametrizeの依存を誤って切ると、分類変更が
  test behavior変更に見える可能性がある。
- `test_magapoke_adapter.py`は1 file内のbrowser launchが多く、Integrationへ移すだけでは
  実行時間は改善しない。
- `tests/research/`をdirectory単位で選択できる一方、現在の`testpaths = ["tests"]`により
  Researchは`pytest -q`にも含まれる。probe変更時のtargeted executionは追加の選択肢であり、
  default full pytestからの除外ではない。
- `poc` / `scripts`のroot import pathは、IDE、PowerShell、CI、uv実行で挙動が異なる
  可能性がある。

### Open Questions

- Research/Probe 46 casesを毎回実行するか、probe変更時・site investigation時だけ実行
  するか。
- `test_restore_bookwalker_quota.py`のutility script testをUnitに残すか、将来
  `tests/tools`等の別categoryを設けるか。
- browser-backed Integrationをsite別subdirectoryへ分ける閾値。
- BookWalker Adapterの18 Unit / 25 IntegrationというPhase 2A計画値と、実際の
  browser-backed collectionで得た17 Unit / 26 Integrationの1 case差分を、次Phaseで
  どの分類表へ反映するか。現在はbrowser依存caseをUnitに残さない実測結果を優先している。
- full pytestの実行条件を、分類後の実測値（警告抑制219.34s、通常250.67s）を踏まえて
  どこに設定するか。
- 現在の実時間waitを契約として残すtestと、fake clock / timeout overrideでUnit化できる
  testの境界。

## 10. Change Record

- **2B-1 completed**: Research / Probe 4 filesを`tests/research/`へ移動し、46 casesを維持。
- **2B-2 completed**: browser部分が少ない3 filesをUnit / Integrationへ分割。
- **2B-3 completed**: browser-heavy mixed 5 filesをUnit / Integrationへ分割。
- collectionは785 casesで不変。実測内訳はUnit 610 / Integration 129 / Research 46。
- targeted / category / full pytestはpass。Chromium unavailableによるskipはなかった。
- test移動・分割以外のtest削除、統合、assertion変更、parameterize変更、fixture scope変更、
  marker、pytest設定、`scripts/run_tests.ps1`、production codeの変更は行っていない。
- Phase 3のbrowser launch削減、fixture共有、timeout / pacing短縮は未実施。
- 現在の作業treeにある`watchlist.yaml`の既存変更は、この資料作成の対象外として保持する。

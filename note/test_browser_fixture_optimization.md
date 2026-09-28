# Browser Fixture Optimization Assessment

Status: IMPLEMENTED THROUGH PHASE 3C-2; PHASE 3C-3 PENDING

調査日: 2026-09-28

この note は Phase 3C の browser fixture 最適化に向けた実測・安全性評価・移行案を
記録する設計資料である。fixture scope、test semantics、production code、pytest 設定は
この調査では変更していない。

Authority:

1. `AGENTS.md`
2. `docs/TEST_STRATEGY.md`
3. `docs/CODEX_IMPLEMENTATION_GUIDE.md`
4. `note/test_suite_classification_plan.md`
5. `note/00_core.md`
6. 現在の `tests/integration/` 実装
7. 各 Integration file の browser fixture / `_new_page()` helper

## Executive Summary

| 項目 | 実測・評価 |
|---|---|
| Current Integration runtime | 144.59s（129 passed、fixture phase 計測実行）。別の `--durations=50` 実行は 146.85s で、現環境の baseline は約 145s と扱う |
| Current Chromium launches | 129 回。全て test case ごとに 1 回 |
| Current Playwright starts/stops | 129 / 129 回 |
| Current context/page creation | `browser.new_page()` による implicit context + page が 129 / 129。さらに BookWalker original-capture の 1 test が explicit context + page を 3 回作成 |
| Estimated browser lifecycle cost | 1 case あたり、Playwright start 0.321s、Chromium launch 0.075s、Browser close 0.102s、Playwright stop 0.013s が中央値。start / close が launch 単体より大きい |
| Recommended optimization | Playwright は session、Browser はまず module、Context / Page は function。Page は共有しない |
| Estimated browser sharing savings | 約 60--65s。module Browser の予測は約 82s、session Browser の予測は約 80s |
| Expected runtime after optimization | まずは 80--85s の範囲を期待値とする。test body の wait、Windows の process variance、fixture cleanup を含む保証値ではない |

現行の大きなコストは Chromium launch 単体だけではなく、test ごとの Playwright start、Browser close、
Playwright stop を含む browser lifecycle の反復である。最も価値の高い対象は 43 case が各々
`_new_page()` を呼ぶ `test_magapoke_adapter_browser.py` である。

## Scope and Non-goals

今回行ったのは、現行 fixture の inventory、実測、state isolation の評価、Phase 3C の設計である。
次は今回の対象外である。

- session-scoped Chromium の実装
- module-scoped Chromium の実装
- shared BrowserContext / shared Page の実装
- `tests/integration/conftest.py` の追加
- fixture API、test semantics、assertion、parameterize の変更
- timeout / grace / pacing の変更
- production code、pytest marker、pytest configuration、pytest-xdist の変更
- test 削除・test 統合・Research / Probe の移動
- 実サイトへの live verification

作業ツリーに存在する Jump+ Research 追加（`tests/research/test_jumpplus_vertical_probe.py`、
`poc/jumpplus_vertical_j1.py`、`note/04_jumpplus.md`）はユーザー所有の対象外変更として触れていない。

## Current Test Baseline

現在の collection は次の通りである。

| suite | collected |
|---|---:|
| Unit | 610 |
| Integration | 129 |
| Research | 55 |
| Total | 794 |

既存の Phase 3B note にある 785 / 790 は過去時点の snapshot である。今回の fixture 調査対象は
Research の現在値ではなく、collection が 129 case で変わらない `tests/integration/` に限定した。

測定コマンド:

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run pytest --collect-only -q tests/integration
uv run pytest -q -p no:warnings tests/integration --durations=50
```

結果:

```text
129 tests collected
129 passed in 146.85s (0:02:26)
```

fixture phase の分離測定では同じ 129 case が 144.59s で完了した。pytest hook による phase 計測は
一時的な調査用で、repository に残していない。

## Current Fixture Inventory

`Browser.new_page()` は Playwright の convenience API であり、implicit BrowserContext と Page を
同時に作成する。従って browser launch 数だけでなく、context/page 作成数も test case 数に追随する。

| file | cases | browser launches | context strategy | page strategy | current scope |
|---|---:|---:|---|---|---|
| `test_access_guard_browser.py` | 1 | 1 | `browser.new_page()` の implicit context | test body で 1 page | test body 内の direct lifecycle |
| `test_bookwalker_adapter_browser.py` | 26 | 26 | `browser.new_page()` の implicit context | `browser_page` fixture で 1 page | function fixture |
| `test_bookwalker_discovery_browser.py` | 19 | 19 | `browser.new_page()` の implicit context | `browser_page` fixture で 1 page | function fixture |
| `test_bookwalker_original_capture_browser.py` | 4 | 4 | fixture の 4 implicit context + 追加 3 explicit context | fixture の 4 page + 追加 3 page | function fixture + 1 test 内 helper |
| `test_local_viewer_flows.py` | 19 | 19 | `browser.new_page()` の implicit context | `browser_page` fixture で 1 page | function fixture |
| `test_magapoke_adapter_browser.py` | 43 | 43 | `browser.new_page()` の implicit context | `_new_page()` で 1 page | test ごとの helper。fixture scope なし |
| `test_magapoke_discovery_browser.py` | 6 | 6 | `browser.new_page()` の implicit context | `browser_page` fixture で 1 page | function fixture |
| `test_magapoke_local_viewer.py` | 3 | 3 | `browser.new_page()` の implicit context | `browser_page` fixture で 1 page | function fixture |
| `test_mangaone_adapter_browser.py` | 7 | 7 | `browser.new_page()` の implicit context | `browser_page` fixture で 1 page | function fixture |
| `test_mangaone_discovery_browser.py` | 1 | 1 | `browser.new_page()` の implicit context | `browser_page` fixture で 1 page | function fixture |
| **Total** | **129** | **129** | **129 implicit + 3 explicit** | **129 implicit + 3 explicit** | **all per test** |

現行の `tests/integration/conftest.py` は存在しない。8 file は同型の `browser_page` fixture、
Magapoke Adapter は `_new_page()`、AccessGuard は test body の direct lifecycle を持つ。

## Setup / Call / Teardown Timing

下表は `pytest_runtest_setup` / `pytest_runtest_call` / `pytest_runtest_teardown` を一時的に wrap
して取得した file 別の合計値である。fixture setup / teardown は setup / teardown に含まれる。
Magapoke Adapter の `_new_page()` は test body から呼ばれるため、その browser lifecycle は call に
計上される。合計は pytest collection 等を除くため、実行時間と完全には一致しない。

| test/file | setup | call | teardown | dominant cost |
|---|---:|---:|---:|---|
| `test_access_guard_browser.py` | 0.001s | 1.289s | 0.000s | direct test-body browser lifecycle + CAPTCHA DOM |
| `test_bookwalker_adapter_browser.py` | 11.632s | 17.189s | 2.444s | per-test fixture lifecycle、strict entry wait |
| `test_bookwalker_discovery_browser.py` | 8.946s | 17.068s | 1.563s | per-test fixture lifecycle、listing / Catalog flow |
| `test_bookwalker_original_capture_browser.py` | 1.728s | 0.292s | 1.161s | fixture lifecycle。1 test の追加 context/page は call 内 |
| `test_local_viewer_flows.py` | 8.109s | 19.397s | 2.751s | fixture lifecycle + Runner wait / transition |
| `test_magapoke_adapter_browser.py` | 0.046s | 29.358s | 0.019s | `_new_page()` の start / launch / close が call 内 |
| `test_magapoke_discovery_browser.py` | 2.763s | 2.858s | 0.525s | per-test fixture lifecycle + listing expansion |
| `test_magapoke_local_viewer.py` | 1.203s | 5.029s | 0.360s | fixture lifecycle + reconstruction / terminal flow |
| `test_mangaone_adapter_browser.py` | 2.908s | 3.748s | 0.682s | fixture lifecycle + async entry / viewer wait |
| `test_mangaone_discovery_browser.py` | 0.439s | 0.662s | 0.048s | single fixture lifecycle + DOM mapping |
| **Total** | **37.775s** | **96.890s** | **9.553s** | measured phase subtotal 144.218s |

Magapoke Adapter の setup が 0.046s と小さく見えるのは高速化ではなく、fixture setup ではなく call
内で Playwright を起動しているためである。したがって duration output の call だけを見て fixture
cost を評価してはいけない。

## Browser Lifecycle Micro-benchmark

headless Chromium を同一環境で 5 回、各回で Playwright start から stop まで独立に測定した。
benchmark test は追加していない。値は中央値、括弧内は min--max である。

| phase | median | min--max |
|---|---:|---:|
| Playwright start | 0.3210s | 0.2882--0.3561s |
| Chromium launch | 0.0747s | 0.0660--0.0877s |
| new context | 0.0053s | 0.0047--0.0092s |
| new page | 0.0775s | 0.0668--0.0921s |
| Page/context close | 0.0072s | 0.0069--0.0122s |
| Browser close | 0.1016s | 0.0392--0.1435s |
| Playwright stop | 0.0134s | 0.0123--0.0155s |

現行 fixture は page/context を明示的に close せず `browser.close()` で browser ごと終了する。
推奨設計では test ごとに Page と Context を明示 close し、Browser close と Playwright stop は
owner scope の終了時だけ行う。

## Sharing Safety

Browser share は browser process の state を test 間で意図的に使うことではない。fresh Context と
fresh Page を保つ前提で「state leakage の観点では likely safe」と評価する。ただし共有 Browser の
crash は同じ scope の後続 test 全体に影響するため、完全な safe ではない。

Context share は、cookie / localStorage / sessionStorage / IndexedDB / permissions / service worker /
cache / context-level route / init script の reset 契約が現行 test にないため、全 file で risky とする。
Page share は URL、DOM、page route、listener、init script、JavaScript global、pending task が残るため、
全 file で unsafe とする。

| group / file | Browser share | Context share | Page share | reason |
|---|---|---|---|---|
| `test_access_guard_browser.py` | likely safe | risky | unsafe | `set_content()` と guard state を test-local に保つ必要がある |
| `test_bookwalker_adapter_browser.py` | likely safe | risky | unsafe | product/viewer route、entry state、listener / storage の境界 |
| `test_bookwalker_discovery_browser.py` | likely safe | risky | unsafe | listing route、pagination DOM、Catalog 対象の page state |
| `test_bookwalker_original_capture_browser.py` | likely safe | risky | unsafe | canvas trace、init script、追加 context の isolation |
| `test_local_viewer_flows.py` | likely safe | risky | unsafe | local viewer DOM、route、Runner の transition state |
| `test_magapoke_adapter_browser.py` | likely safe | risky | unsafe | canvas hook、route、viewer prefix / terminal DOM |
| `test_magapoke_discovery_browser.py` | likely safe | risky | unsafe | listing route、pagination、Catalog sync state |
| `test_magapoke_local_viewer.py` | likely safe | risky | unsafe | native reconstruction、terminal card、capture state |
| `test_mangaone_adapter_browser.py` | likely safe | risky | unsafe | quota entry、async button、viewer appearance state |
| `test_mangaone_discovery_browser.py` | likely safe | risky | unsafe | chapter listing route、card mapping、pagination DOM |

## Recommended Design

Phase 3C の初期設計は、次の境界を採用する。

```text
module-scoped:
    Playwright
    Browser

function-scoped:
    BrowserContext
    Page
```

最終的な低レベル fixture は次の責務だけを持つ想定である。

```text
playwright       start once / stop once
browser          launch once per integration module / close at module end
fresh_context    browser.new_context() / context.close()
fresh_page       context.new_page() / page.close()
```

`tests/integration/conftest.py` は最終形では yes とする。ただし共通化するのは lifecycle primitive
だけであり、site-specific route、HTML fixture、adapter preparation、capture helper は各 file に
残す。初回の Magapoke Adapter migration では module-local fixture で挙動を確認してから shared
conftest に抽出する方が安全である。

session-scoped Browser も理論上は可能だが、初回から全 Integration を一つの Browser crash 境界に
置かない。module-scoped Browser は 10 module で起動を共有するため、session-scoped との差は小さい
一方、失敗の blast radius と fixture failure の影響を抑えられる。

実装時の必須条件:

- shared Page は採用しない
- shared Context は採用しない
- test ごとに fresh Context / fresh Page を作る
- Browser close が Context / Page の cleanup を代替しないよう、Page と Context を順に close する
- Browser launch failure の skip / cleanup を shared fixture の owner scope で処理する
- BookWalker original-capture の追加 3 context/page は、必要な test-local context として明示 close する
- Magapoke `_new_page()` は Browser launch を担当しない helper に変え、fixture-provided Browser / Context / Page を使う
- route、listener、init script、storage、permissions の reset を暗黙に期待しない
- test count、assertion、test-specific timeout / grace、production default は変更しない

## Expected Benefit Model

micro-benchmark の中央値を使った概算である。現行の 129 case は各 case が Playwright start、
Chromium launch、Browser close、Playwright stop を繰り返す。提案後は Context / Page の creation と
close は test ごとに残し、owner scope の start / launch / close / stop だけを共有する。

| design | lifecycle owner | estimated saved lifecycle time | estimated Integration runtime |
|---|---|---:|---:|
| current | 129 test cases | -- | 約 145s |
| module Browser | Playwright 1 + Browser 10 | 約 63s | 約 82s |
| session Browser | Playwright 1 + Browser 1 | 約 65s | 約 80s |

これは lifecycle cost のモデルであり、adapter wait、fixture HTML、filesystem、Windows process
variance、Browser crash による再実行は含まない。判定基準は次とする。

- High value: browser lifecycle savings が 20--30s を超える file / group
- Medium value: 約 10--20s、または complexity / isolation risk と比較する必要があるもの
- Low value: 数秒未満で fixture migration risk の方が大きいもの

この基準では、43 case の Magapoke Adapter が最優先、26 case の BookWalker Adapter、19 case の
BookWalker Discovery / generic local viewer が次点である。1 case の AccessGuard と Manga ONE
Discovery は単独最適化の価値が低い。

## Migration Plan

### Phase 3C-1: Magapoke Adapter only

- `test_magapoke_adapter_browser.py` の `_new_page()` を module Browser + function Context / Page
  から呼べる構造へ置き換える設計を検証する
- 43 case の collection、pass、test order independence、cleanup failure を確認する
- browser lifecycle が call に埋め込まれなくなった後、setup / call / teardown を再測定する
- この段階では共通 `conftest.py` を先に広げず、site-local fixture で isolation を検証する

### Phase 3C-2: BookWalker browser tests

- `test_bookwalker_adapter_browser.py`、`test_bookwalker_discovery_browser.py`、
  `test_bookwalker_original_capture_browser.py` を移行する
- product/listing route、canvas trace、init script、追加 context/page の cleanup を確認する
- 3 file の local fixture で安定した低レベル lifecycle primitive を shared conftest に抽出する

### Phase 3C-3: Manga ONE / generic Integration and remaining files

- `test_mangaone_adapter_browser.py`、`test_mangaone_discovery_browser.py`、
  `test_local_viewer_flows.py`、`test_magapoke_local_viewer.py` を移行する
- `test_access_guard_browser.py` と `test_magapoke_discovery_browser.py` は最後に小さい対象として移行する
- shared conftest は browser / context / page の責務に限定し、site-specific helper は各 file に残す

### Phase 3C-4: Regression

- 各 migration group の targeted Integration
- `pytest --collect-only -q` で test count 不変を確認
- `pytest -q -p no:warnings tests/integration --durations=50`
- affected Unit / Integration と必要な full regression
- Windows / Playwright stability、test isolation、failure cleanup の確認

## Risks

| risk | evaluation / mitigation |
|---|---|
| test isolation | Context / Page を function scope に固定し、shared storage / route / listener reset を設計上要求しない |
| route / listener leakage | page/context を毎回 close。site-local helper の route 登録は fresh Page に限定 |
| init script / storage leakage | Context share を採用しない。BookWalker capture は extra context の close を明示 |
| context/page cleanup | fixture failure 時も `finally` で Page → Context の順に close。Browser close を代替にしない |
| browser crash | 初期 rollout は module Browser。session Browser は module rollout 後の判断にする |
| fixture setup failure | Browser owner fixture が起動失敗時に Playwright を stop し、後続 scope に壊れた object を渡さない |
| Windows / Playwright stability | module/session async fixture と pytest-asyncio event loop の組み合わせを 3C-1 で検証する |
| Magapoke helper semantics | `_new_page()` の API を一度に全 repository へ一般化せず、43 case の local boundary で確認する |
| false runtime attribution | Magapoke の call 内 lifecycle を setup と混同しない。移行前後で同じ phase hook を使う |

## Phase 3C-1 Result

Phase 3C-1 is complete for `tests/integration/test_magapoke_adapter_browser.py`.
Only the module-local fixture lifecycle in that file was changed. The test
assertions, parametrization, timeouts, fake HTML, routes, and production code
were not changed.

Before (direct target-file measurement on the current main baseline):

- cases: 43 passed
- Playwright starts: 43
- Chromium launches: 43
- target-file runtime: 29.15s
- Integration baseline from the Phase 3C measurement: 129 passed in 146.85s
  (fixture measurement 144.59s)

After:

- cases: 43 passed in 8.39s
- Playwright starts: 1
- Chromium launches: 1
- BrowserContexts: 43
- Pages: 43
- repeated target-file runs: 9.08s and 9.11s
- Integration: 129 passed in 121.34s
- full pytest: 801 passed in 152.09s, 2391 warnings

The `--setup-show` measurement confirmed one module-scoped Playwright fixture,
one module-scoped Browser fixture, and 43 function-scoped Context/Page fixture
invocations. Each test receives a fresh Context and Page; only Browser is
shared. No order dependency, browser crash, cleanup leak, or Chromium skip was
observed in the repeated and suite-level runs.

Because the repository uses function-scoped async test loops by default, the
target file explicitly uses the module loop scope for its async tests and
fixtures. No pytest configuration was changed. The first module-fixture trial
without aligned loop scope did not complete normally; the explicit local loop
scope resolved that ownership mismatch without introducing session scope.

The current repository-wide collection is 801 cases: Unit 610, Integration
129, Research 62. The Research count is reported as observed and was not
modified by this Phase.

Next: evaluate a separate BookWalker rollout (Phase 3C-2); no other
Integration file was changed in Phase 3C-1.

## Phase 3C-2 Result

Phase 3C-2 is complete for the three BookWalker browser-backed Integration
files. The lifecycle primitives are now in
`tests/integration/conftest.py`; they are module-scoped per test module rather
than session-scoped. Site-specific routes, HTML, Catalog fixtures, and capture
helpers remain in their original test files.

Current fixture architecture:

- module-scoped `integration_playwright`
- module-scoped `integration_browser`
- function-scoped `browser_context`
- function-scoped `browser_page`
- module-level `pytest.mark.asyncio(loop_scope="module")` for all three target
  files; no per-test async marker is needed

Before (direct measurements before the Phase 3C-2 change):

| file | cases | Playwright starts | Chromium launches | runtime |
|---|---:|---:|---:|---:|
| BookWalker Adapter | 26 | 26 | 26 | 32.30s |
| BookWalker Discovery | 19 | 19 | 19 | 27.11s |
| BookWalker Original Capture | 4 | 4 | 4 | 2.57s |

Original Capture also retained its test-local three extra Context/Page pairs.

After:

| file | cases | Playwright starts | Chromium launches | fixture Context/Page | runtime |
|---|---:|---:|---:|---:|---:|
| BookWalker Adapter | 26 | 1 | 1 | 26 / 26 | 18.50s |
| BookWalker Discovery | 19 | 1 | 1 | 19 / 19 | 17.55s |
| BookWalker Original Capture | 4 | 1 | 1 | 4 / 4 | 0.98s |

Original Capture still creates and closes the same three test-local extra
Context/Page pairs. The combined setup measurement reported three module
Playwright fixtures, three module Browser fixtures, and 49 function Context/Page
fixture invocations. The combined 49-case run was 37.76s; repeated runs were
36.74s and 36.37s.

Integration changed from the Phase 3C-1 reference of 129 passed in 121.34s to
129 passed in 90.79s in the first after run; the final verification run was
129 passed in 109.52s. The difference is runtime variance in unrelated
local-viewer/wait tests, while the repeated 49-case BookWalker run remained
36.40s and 36.33s. The final full suite was 810 passed in 133.80s with 2025
warnings. Final collection was Unit 618 / Integration 129 / Research 63 =
810. Unit and Research counts changed during the work because unrelated
user-owned changes appeared in the working tree; those paths were not modified
by this Phase.

Isolation and cleanup were verified through the repeated runs and
`--setup-show`: every test receives a fresh Context and Page, routes remain on
the fresh Page/Context, and no order dependency, loop ownership error, browser
crash, or Chromium skip was observed. All fixture owners use `finally` cleanup;
the Original Capture extra Page is explicitly closed before its Context.

The module-scoped Playwright/Browser arrangement is now the recommended
standard. Session-scoped Playwright/Browser remains an optional future
optimization only, pending separate loop-ownership and crash-blast-radius
evidence. Phase 3C-3, including Manga ONE, generic local viewer, Magapoke
local/discovery, and AccessGuard rollout, remains pending.

## Verification Status

実行済み:

- `uv run pytest --collect-only -q tests/integration`: 129 collected
- `uv run pytest -q -p no:warnings tests/integration --durations=50`: 129 passed in 146.85s
- fixture phase measurement: 129 passed in 144.59s、setup 37.775s / call 96.890s / teardown 9.553s
- headless browser lifecycle micro-benchmark: 5 samples、中央値を記録
- `uv run pytest --collect-only -q`: 794 collected（Unit 610 / Integration 129 / Research 55）

未実行・今回不要:

- fixture migration implementation: 今回は設計のみで、実装を開始していない
- full pytest execution: test / production behavior を変更していないため、Phase 3C 実装後に実行する
- `ruff check src tests`: Python source の変更がないため未実行
- Research / Probe runtime: 対象外。Jump+ Research 追加も変更していない
- Live verification: real-site behavior、login、quota、viewer session を変更していないため不要

Skipped tests: 0。Chromium は利用可能で、Integration 実行時に skip は発生しなかった。

## Final Decision Snapshot

```text
Current:
- Integration runtime: 90.79s / 109.52s observed for 129 passed after 3C-2
- BookWalker target: 3 module Playwright starts and 3 Chromium launches
- dominant remaining cost: test-body DOM waits and local-viewer transitions

Completed:
- Phase 3C-1: Magapoke Adapter local fixture proof
- Phase 3C-2: BookWalker browser tests + shared lifecycle primitive extraction

Recommended:
- Playwright scope: module
- Browser scope: module
- Context scope: function
- Page scope: function
- shared conftest: lifecycle primitives only
- session scope: optional future optimization, not current standard

Highest-value target:
- remaining Phase 3C-3 Integration files

Risks:
- cleanup, browser crash blast radius, async event-loop compatibility, route/listener/storage leakage

Pending:
- Phase 3C-3: Manga ONE / generic / remaining Integration

Changed:
- tests/integration/conftest.py
- three BookWalker browser test files
- note/test_browser_fixture_optimization.md and note/00_core.md

Not changed:
- test semantics
- shared Context/Page
- production code
- pytest configuration
- timeout / grace values
- non-BookWalker Integration semantics
```

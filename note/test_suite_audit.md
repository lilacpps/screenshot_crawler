# Test Suite Audit

調査日: 2026-09-27  
対象: `screenshot_crawler` の現行 pytest suite  
位置づけ: **現状調査資料。テスト方針の authority ではない。**

### 測定 snapshot の注意

フル pytest と inventory の主測定は、作業開始時に確認した **777 cases** の snapshot に
対して行った。調査中にユーザー側の変更と思われる `poc/zeblack_probe.py`、
`tests/unit/test_zeblack_probe.py`、`poc/zeblack_capture_probe.py` が追加・変更された。
調査終了時の read-only collection は **782 cases**（unit 760 / integration 22）だったが、
この後の状態に対するフル pytest の再計測は行っていない。以下では、実測時間は777-case
snapshot、現行 collection の差分は明示的に区別する。

この調査では、`AGENTS.md`、`docs/TEST_STRATEGY.md`、
`docs/CODEX_IMPLEMENTATION_GUIDE.md`、`pyproject.toml`、
`scripts/run_tests.ps1`、`tests/`、および実行対象の test code を確認した。
テスト削除・移動・再分類・設定変更・production code変更は行っていない。

## 1. Executive Summary

- 初回の measured snapshot は **777 test cases**（parametrize 展開後）。その内訳は
  `tests/unit/` が **43 files / 755 cases**、`tests/integration/` が **2 files / 22 cases**。
- 調査終了時の current collection は、ユーザー側変更を含めて **782 cases**
  （unit 760 / integration 22）。current の標準 `pytest -q` も実行し、
  **782 passed, 0 failed, 0 skipped、223.50s (3:43)** だった。
- 初回 snapshot の標準 run は **777 passed, 0 failed, 0 skipped、240.21s (4:00)**
  だった。いずれも xfailed/xpassed はなかった。
- Chromium が利用でき、integration と unit 配下の browser-backed test は skip
  されず実行された。したがって今回の計測は、少なくともこのローカル環境の
  browser 起動を含む負荷を反映している。
- 実行時間上位の主因は、テスト数そのものではなく次の bounded wait / pacing。
  - Manga ONE の viewer 未出現を確認するテスト: **10.10s**
  - CLI batch の既定 inter-candidate delay 3 秒を複数回通るテスト: **約6.02--6.07s**
  - local viewer の terminal / chapter-change grace period: **約3.55--4.47s**
- `tests/unit/` の名前に反して、実 Chromium を起動するファイルが **8 files** ある。
  さらに `poc/` を直接 import する unit file が **4 files / 40 cases** ある。
- `pyproject.toml` の pytest 設定は `testpaths = ["tests"]` のみで、marker や
  除外設定はない。`tests/integration/` も通常の `pytest` に含まれる。
- `scripts/run_tests.ps1` は `pytest -q` のみを実行するため、現状の標準完了確認は
  browser-backed unit と integration を含む約4分のフル suite である。

### 実測と推測の区別

上記の件数・時間・slow test・skip 状態は今回の pytest 実測値である。
「今後 integration へ移すべき」「research として扱うべき」といった分類は、
実行挙動と import / fixture の静的確認から得た **候補** であり、今回決定していない。

## 2. Current Test Inventory

### 2.1 現在の収集設定

`pyproject.toml` は次の設定である。

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

pytest の追加設定、marker、`addopts` はない。`tests/fixtures/` には README のみで、
fixture code はない。`poc/` は pytest の testpaths ではないが、下表の test file から
直接 import されるため、suite の実行時依存には入っている。

### 2.2 `tests/integration/`

| path | cases | 現在の category | browser / Chromium | PoC | 主な対象 |
|---|---:|---|---|---|---|
| `tests/integration/test_local_viewer_flows.py` | 19 | integration | **実 Chromium**。function-scoped fixture で launch | なし | Core Runner + 人工 local viewer、CONTENT / LOADING / END / NEXT_CONTENT / UNKNOWN、spread、same-content、max_pages、Manga ONE terminal / chapter change |
| `tests/integration/test_magapoke_local_viewer.py` | 3 | integration | **実 Chromium**。function-scoped fixture で launch | なし | Magapoke adapter + Core Runner、JPEG reconstruction / screenshot fallback、terminal card、次話遷移 |

両ファイルとも route で人工 HTML / data を供給しており、今回の pytest は外部実サイトへ
接続していない。`tests/` の integration README および `docs/TEST_STRATEGY.md` が想定する
「Chromium がなければ skip」の実装になっているが、今回の環境では Chromium が利用可能だった。

### 2.3 `tests/unit/` の全 file inventory

`cases` は pytest collection 結果の parametrize 展開後の数である。
`Chromium=Yes` は import だけではなく、`chromium.launch()` または同等の helper が
実際に呼ばれる file を示す。`Fake Page` は browser API 形状を持つだけで Chromium は起動しない。

| path | cases | 現在の category | Chromium | PoC | 主な対象 |
|---|---:|---|---|---|---|
| `tests/unit/test_access_guard.py` | 7 | unit | **Yes**（captcha DOM 1 test） | なし | HTTP 403/429、challenge、captcha、AccessGuard、batch stop、metrics |
| `tests/unit/test_auth.py` | 12 | unit | No（context fake / helper） | なし | auth state path、browser context 選択、saved state |
| `tests/unit/test_batch.py` | 33 | unit | No | なし | BatchPlanner、access resource、quota、ordering、metadata |
| `tests/unit/test_batch_executor.py` | 34 | unit | No | なし | BatchExecutor の実行・消費・失敗・packaging、fake adapter / Catalog |
| `tests/unit/test_bookwalker_adapter.py` | 43 | unit | **Yes** | なし | BookWalker strict direct/quota entry、DOM control、capture target、navigation、title |
| `tests/unit/test_bookwalker_batch.py` | 4 | unit | No | なし | BookWalker quota / BatchExecutor 境界 |
| `tests/unit/test_bookwalker_discovery.py` | 54 | unit | **Yes** | なし | BookWalker listing / product DOM、full/incremental discovery、Catalog reconciliation |
| `tests/unit/test_bookwalker_native_capture.py` | 16 | unit | No（fake page / capture helper） | なし | native canvas capture、geometry、fallback |
| `tests/unit/test_bookwalker_native_source.py` | 7 | unit | No | なし | native source response / image bytes |
| `tests/unit/test_bookwalker_original_capture.py` | 13 | unit | **Yes** | なし | original JPEG listener、canvas JS、browser image signature、fallback |
| `tests/unit/test_bookwalker_policy.py` | 12 | unit | No | なし | BookWalker Site Policy、quota / grant 判定 |
| `tests/unit/test_bookwalker_reader_controls.py` | 12 | unit | No | なし | reader control の分類・候補選択 |
| `tests/unit/test_browser.py` | 9 | unit | No（fake browser。cleanup hang は 0.01s に制限） | なし | BrowserSession lifecycle / close semantics |
| `tests/unit/test_catalog.py` | 26 | unit | No | なし | Catalog schema、upsert、reconciliation、identity |
| `tests/unit/test_catalog_backup.py` | 5 | unit | No | なし | SQLite backup / restore safety |
| `tests/unit/test_catalog_export.py` | 10 | unit | No | なし | Catalog CSV export |
| `tests/unit/test_catalog_migrations.py` | 9 | unit | No | なし | SQLite migration / schema compatibility |
| `tests/unit/test_cli.py` | 63 | unit | No（FakeSession / FakeExecutor） | なし | CLI parser、crawl/discover/batch orchestration、grant-only、output / metrics |
| `tests/unit/test_core_features.py` | 39 | unit | No（FakePage / FakeAdapter） | なし | CrawlerRunner state、retry、timeout、capture、same-content、cleanup |
| `tests/unit/test_discovery.py` | 18 | unit | No（FakePage） | なし | generic DiscoveryService、full/incremental、known streak、Catalog |
| `tests/unit/test_env.py` | 7 | unit | No | なし | environment / endpoint resolution |
| `tests/unit/test_flatten_zip_archives.py` | 10 | unit | No | なし | ZIP flatten、collision、filesystem safety |
| `tests/unit/test_jumpplus_adapter.py` | 37 | unit | No（browser-shaped fake） | なし | Jump+ adapter parser / navigation / capture helper |
| `tests/unit/test_jumpplus_discovery.py` | 11 | unit | No（fake page） | なし | Jump+ discovery parser / listing / pagination |
| `tests/unit/test_jumpplus_discovery_probe.py` | 7 | unit | No | **Yes** | `poc.jumpplus_discovery_matrix` / `poc.jumpplus_discovery_probe` |
| `tests/unit/test_jumpplus_policy.py` | 14 | unit | No | なし | Jump+ Site Policy / Catalog plan |
| `tests/unit/test_jumpplus_probe.py` | 11 | unit | No | **Yes** | `poc.jumpplus_probe` の identity / network / report |
| `tests/unit/test_jumpplus_reconstruct.py` | 13 | unit | No | **Yes** | `poc.jumpplus_reconstruct` の画像 reconstruction |
| `tests/unit/test_launcher.py` | 4 | unit | No | なし | launcher command / profile / endpoint validation |
| `tests/unit/test_magapoke_adapter.py` | 76 | unit | **Yes**（`_new_page()` call 35 箇所。残りは pure / fake / codec） | なし | Magapoke entry、viewer DOM、terminal、access resource、JPEG DCT / PNG reconstruction |
| `tests/unit/test_magapoke_discovery.py` | 17 | unit | **Yes**（browser fixture を使う discovery 6 source tests） | なし | Magapoke listing DOM、access mapping、Catalog sync / incomplete |
| `tests/unit/test_magapoke_policy.py` | 20 | unit | No | なし | Magapoke quota / work ticket / premium ticket policy |
| `tests/unit/test_mangaone_adapter.py` | 25 | unit | **Yes**（browser fixture 7 source tests） | なし | Manga ONE quota entry、viewer、END heuristic、native WebP / source capture |
| `tests/unit/test_mangaone_discovery.py` | 12 | unit | **Yes**（browser fixture 1 test） | なし | Manga ONE chapter listing / access mapping / Catalog |
| `tests/unit/test_mangaone_login.py` | 2 | unit | No（fake page） | なし | Manga ONE login form interaction |
| `tests/unit/test_models.py` | 8 | unit | No | なし | model value semantics、RunConfig validation |
| `tests/unit/test_packaging.py` | 17 | unit | No | なし | manifest、metadata merge、library tree、ZIP、cleanup safety |
| `tests/unit/test_registry.py` | 1 | unit | No | なし | adapter registry duplicate rejection |
| `tests/unit/test_restore_bookwalker_quota.py` | 2 | unit | No | なし | quota restore script、backup、SQLite state |
| `tests/unit/test_runtime_settings.py` | 10 | unit | No | なし | `crawler.yaml` parse / validation / defaults |
| `tests/unit/test_state.py` | 1 | unit | No | なし | PageState values |
| `tests/unit/test_watchlist.py` | 15 | unit | No | なし | watchlist YAML、add/enable/disable、duplicate / validation |
| `tests/unit/test_zeblack_probe.py` | 9 at measured snapshot; 14 currently | unit | No | **Yes** | `poc.zeblack_probe` の target guard / resource classification / report。現在は `poc.zeblack_capture_probe` も直接 import |

**measured snapshot の unit 合計: 43 files / 755 cases**。上表の `Chromium=Yes` は 8 files であり、
directory 名だけでは unit と browser integration-like behavior を分離できない。

### 2.4 SQLite / filesystem / image / wait の横断棚卸し

- **SQLite / Catalog**: `test_batch.py`、`test_batch_executor.py`、
  `test_bookwalker_batch.py`、`test_bookwalker_discovery.py`、
  `test_bookwalker_policy.py`、`test_catalog*.py` 4 files、`test_cli.py`、
  `test_discovery.py`、`test_jumpplus_policy.py`、`test_magapoke_discovery.py`、
  `test_magapoke_policy.py`、`test_mangaone_discovery.py`、
  `test_restore_bookwalker_quota.py` の **16 files** が、主に `tmp_path` 下の
  `catalog.sqlite` を使う。
- **filesystem / ZIP**: Catalog 系、batch / CLI、packaging、watchlist、runtime
  settings、probe report、`test_flatten_zip_archives.py` などが一時ディレクトリに
  write/read する。通常の本番 `catalog.sqlite` をテスト対象にはしていない。
- **画像 / codec**: `test_magapoke_adapter.py` は Pillow と jpeglib を使い、JPEG
  coefficient-domain reconstruction と PNG fallback を検証する。その他、
  BookWalker native/original capture、Manga ONE native capture、Magapoke integration、
  Jump+ reconstruction / probe に画像 bytes 処理がある。
- **実時間 sleep**: test code に直接ある `asyncio.sleep` は主に
  `test_browser.py`、`test_core_features.py`、`test_mangaone_adapter.py` にある。
  10 秒 sleep は cleanup timeout を検証するために 0.01--0.2 秒で cancel され、
  1 秒 sleep も timeout test 内で bounded である。`test_access_guard.py` の
  `fail_sleep` は monkeypatch 用の no-op であり実時間待機ではない。
- **production 側の実時間 sleep を間接的に踏む test**: `test_cli.py` の batch
  orchestration test は `src/screenshot_crawler/cli.py` の既定
  `inter_candidate_delay_ms = 3000` を monkeypatch せず実行する。今回の 6 秒級の
  slow test はこれが主因である。
- **polling / timeout**: browser-backed adapter は `page.wait_for_timeout()`、
  locator wait、DOM polling を使う。Playwright は fake ではなく実 browser を動かす
  file もあるため、設定された wait budget が wall-clock に現れる。
- `time.sleep` は test code では確認されなかった。

## 3. Runtime Measurement

### 3.1 標準フル pytest

実行条件: repository root、`.venv\Scripts\python.exe`（Python 3.14.6）、pytest 8.4.2、
通常の `pytest -q`。pytest 設定・warning filter の変更はしていない。

初回の measured snapshot（777 cases）:

```text
777 passed, 2747 warnings in 240.21s (0:04:00)
failed: 0
skipped: 0
xfailed: 0
xpassed: 0
```

調査中にユーザー側変更を検出した後の current state（782 cases）:

```text
782 passed, 2747 warnings in 223.50s (0:03:43)
failed: 0
skipped: 0
xfailed: 0
xpassed: 0
```

これは別 run なので、追加5 casesが suite を16.71秒短縮したという意味ではない。
browser / process / cache / host load の run-to-run variance を含む。slowest の個別値は
777-case snapshot の durations run で取得した。

Chromium unavailable による skip はなかった。したがって、Chromium をインストール
できない開発環境では、今回より短く見える一方、integration / browser-backed unit の
実負荷を表さない可能性がある。

### 3.2 durations 計測

遅い test を読みやすく回収するため、同じ collection を次の条件で再実行した。

```text
pytest -q -p no:warnings --durations=30 --durations-min=0.01
```

この計測は warning 出力を抑制しており、標準フル pytest の 240.21 秒と同一の
wall-clock baseline ではない。durations の phase は、上位 30 件がすべて `call` で、
上位30に `setup` / `teardown` は現れなかった。

| rank | duration | phase | test |
|---:|---:|---|---|
| 1 | 10.10s | call | `tests/unit/test_mangaone_adapter.py::test_mangaone_quota_entry_fails_if_viewer_does_not_appear` |
| 2 | 6.07s | call | `tests/unit/test_cli.py::test_grant_only_all_uses_policy_order_replans_and_shares_limit` |
| 3 | 6.04s | call | `tests/unit/test_cli.py::test_batch_run_replans_premium_after_work_pass_and_stops_at_zero_balance` |
| 4 | 6.02s | call | `tests/unit/test_cli.py::test_batch_run_limit_spans_initial_and_premium_phases` |
| 5 | 4.47s | call | `tests/integration/test_magapoke_local_viewer.py::test_magapoke_runner_stops_at_terminal_card_without_opening_next_episode` |
| 6 | 4.22s | call | `tests/integration/test_local_viewer_flows.py::test_mangaone_graceful_end_and_chapter_change_are_distinct` |
| 7 | 3.55s | call | `tests/integration/test_local_viewer_flows.py::test_mangaone_image_gap_becomes_end_after_grace_period` |
| 8 | 3.09s | call | `tests/unit/test_cli.py::test_batch_run_continues_after_work_ticket_unavailable` |
| 9 | 3.03s | call | `tests/unit/test_cli.py::test_grant_only_all_moves_to_next_policy_pass_after_resource_exhaustion` |
| 10 | 2.52s | call | `tests/integration/test_local_viewer_flows.py::test_runner_local_dom_state_flows[steps3-2-end]` |
| 11 | 2.52s | call | `tests/integration/test_local_viewer_flows.py::test_runner_local_dom_state_flows[steps1-2-end]` |
| 12 | 2.49s | call | `tests/integration/test_local_viewer_flows.py::test_runner_local_dom_state_flows[steps2-2-next_content]` |
| 13 | 2.49s | call | `tests/integration/test_local_viewer_flows.py::test_runner_local_dom_exact_max_pages_can_stop[next_content]` |
| 14 | 2.48s | call | `tests/integration/test_local_viewer_flows.py::test_runner_local_dom_state_flows[steps0-2-end]` |
| 15 | 2.47s | call | `tests/integration/test_local_viewer_flows.py::test_runner_local_dom_exact_max_pages_can_stop[end]` |
| 16 | 2.32s | call | `tests/unit/test_bookwalker_discovery.py::test_bookwalker_full_clean_exhaustion_reconciles_missing_source` |
| 17 | 2.21s | call | `tests/unit/test_bookwalker_discovery.py::test_bookwalker_full_reconciles_first_volume_after_later_release` |
| 18 | 2.17s | call | `tests/integration/test_magapoke_local_viewer.py::test_magapoke_reconstructs_jpeg_and_falls_back_to_screenshot` |
| 19 | 1.58s | call | `tests/integration/test_local_viewer_flows.py::test_runner_local_dom_same_identity_hits_same_content_guard` |
| 20 | 1.52s | call | `tests/unit/test_bookwalker_adapter.py::test_bookwalker_strict_waits_for_delayed_maruyomi` |
| 21 | 1.52s | call | `tests/unit/test_bookwalker_adapter.py::test_bookwalker_strict_waits_for_transient_duplicate_to_settle` |
| 22 | 1.52s | call | `tests/unit/test_bookwalker_discovery.py::test_bookwalker_incremental_stable_boundary_via_service[initial0-observed0]` |
| 23 | 1.44s | call | `tests/unit/test_bookwalker_adapter.py::test_bookwalker_strict_direct_clicks_only_owned` |
| 24 | 1.41s | call | `tests/unit/test_bookwalker_adapter.py::test_bookwalker_strict_overlapping_scopes_count_same_element_once` |
| 25 | 1.41s | call | `tests/unit/test_mangaone_adapter.py::test_mangaone_quota_entry_waits_for_async_button` |
| 26 | 1.40s | call | `tests/unit/test_bookwalker_adapter.py::test_bookwalker_strict_quota_clicks_only_maruyomi` |
| 27 | 1.40s | call | `tests/unit/test_bookwalker_adapter.py::test_bookwalker_strict_direct_clicks_purchased_owned_control` |
| 28 | 1.40s | call | `tests/unit/test_bookwalker_adapter.py::test_bookwalker_strict_direct_allows_owned_without_control_uuid` |
| 29 | 1.38s | call | `tests/integration/test_local_viewer_flows.py::test_runner_local_dom_saves_spread_parts_with_same_pixels` |
| 30 | 1.36s | call | `tests/unit/test_access_guard.py::test_visible_captcha_providers_stop_but_hidden_provider_does_not` |

`--durations=30` の run 自体は warning 抑制下で `777 passed in 219.95s` だった。
同様に warning 抑制下でディレクトリを分けて測ると、次の値になった。

| selection | cases | result | measured time |
|---|---:|---|---:|
| `pytest -q -p no:warnings tests/integration` | 22 | 22 passed | 52.27s |
| `pytest -q -p no:warnings tests/unit` | 755 | 755 passed | 177.82s |

これらは別プロセス・別 run の値なので、同一 run の厳密な加算値として扱わない。
ただし、unit suite 単体も約3分であり、`unit` という名前だけで高速 suite とみなせない。

### 3.3 setup / call / teardown の見え方

上位30はすべて `call` phase だった。これは「browser fixture の setup/teardown がない」
ことを意味しない。実際、browser fixture は scope 指定がなく function scope であり、
test case ごとに `async_playwright().start()`、`chromium.launch()`、page creation、
close を行う file がある。setup/teardown 個別の時間は上位30より下に分散している。

## 4. Bottleneck Analysis

### 4.1 Manga ONE の viewer 未出現 timeout

`test_mangaone_quota_entry_fails_if_viewer_does_not_appear` は、button をクリックした後に
viewer が出現しないケースを実 Chromium で検証する。test 側で quota entry wait は変更
しておらず、adapter の既定 `page_change_timeout_ms = 10_000` が locator wait に使われる。
そのため measured call time が **10.10s** になった。これは失敗を早く返せない偶発的な
遅さではなく、timeout contract を実時間で検証していることによる時間である。

### 4.2 CLI batch の inter-candidate pacing

`src/screenshot_crawler/runtime_settings.py` の既定値は
`DEFAULT_INTER_CANDIDATE_DELAY_MS = 3000`。`src/screenshot_crawler/cli.py` の
`_execute_batch_candidates()` は、後続 candidate があると
`asyncio.sleep(inter_candidate_delay_ms / 1000)` を行う。

slow な `test_cli.py` の batch / grant-only test は FakeSession / FakeExecutor を
使うため外部サイトや実 browser はないが、production CLI の pacing は実際に通る。
resource pass をまたぐ複数 candidate を用意しているため、3 秒 delay が2回程度入り、
**約6秒**になっている。これは unit が遅くなる主要因の一つで、browser 起動が原因ではない。

### 4.3 local viewer の DOM polling / grace period

- `test_mangaone_graceful_end_and_chapter_change_are_distinct`: **4.22s**
- `test_mangaone_image_gap_becomes_end_after_grace_period`: **3.55s**
- `test_magapoke_runner_stops_at_terminal_card_without_opening_next_episode`: **4.47s**

前者は Manga ONE の `end_grace_ms` / page-change wait と実 DOM transition を組み合わせ、
後者は Magapoke の viewer state / terminal card transition を実 browser で通る。
local viewer は人工 fixture だが、Core + Adapter + DOM + screenshot / capture の境界を
検証しているため、pure unit より遅いのは構造上自然である。

### 4.4 Browser / DOM integration-like tests が unit に混在

実 Chromium を launch する unit file は次の8本。

```text
tests/unit/test_access_guard.py
tests/unit/test_bookwalker_adapter.py
tests/unit/test_bookwalker_discovery.py
tests/unit/test_bookwalker_original_capture.py
tests/unit/test_magapoke_adapter.py
tests/unit/test_magapoke_discovery.py
tests/unit/test_mangaone_adapter.py
tests/unit/test_mangaone_discovery.py
```

各 fixture は原則 function scope であり、shared browser fixture ではない。
`test_magapoke_adapter.py` は `_new_page()` を35箇所の test path から呼ぶ。したがって
browser launch / page creation / JS DOM 操作 / close の累積が unit suite に入っている。
上位 duration の BookWalker / Manga ONE test も、DOM control の安定化・delayed control・
locator wait を実時間で確認している。

### 4.5 画像処理・SQLite・filesystem

Pillow / jpeglib の JPEG / PNG / WebP 処理、ZIP、SQLite、temp filesystem は suite 全体に
広く使われている。一方、今回の上位30では、個別の codec decode や SQLite init よりも、
明示的な wait / pacing と browser DOM transition の方が大きかった。
これは「codec / DB が軽い」と断定する結果ではなく、今回の top-duration で支配的では
なかったという意味である。

### 4.6 Warning output

標準 run では pytest-asyncio の event loop policy deprecation warning を中心に
**2747 warnings** が出た。warning 抑制下の full run は **219.95s** だったため、
今回の run 間比較では warning collection / report も数十秒規模の差に寄与している可能性が
ある。ただし warning 対応や pytest 設定変更は今回の scope 外であり、実装判断はしていない。

## 5. Classification Candidates

### 5.1 Unit として維持しやすい候補

次のような file / group は、実 browser / 外部サイトなしで契約を確認している。

- models / state / env / registry / reader control / parser / naming:
  `test_models.py`、`test_state.py`、`test_env.py`、`test_registry.py`、
  `test_bookwalker_reader_controls.py` など。
- Core state / guard / timeout / fingerprint / packaging helper:
  `test_core_features.py`、`test_browser.py`（fake browser）、
  `test_access_guard.py` のうち DOM captcha 以外、`test_packaging.py`。
- Catalog / Watchlist / Runtime settings:
  SQLite や YAML を `tmp_path` に閉じ込めた logic test。DB / filesystem を使っても
  外部サービス不要で、unit 相当の local component contract とみなせるものが多い。
- Batch / policy / executor:
  `test_batch.py`、`test_batch_executor.py`、各 site policy test の fake adapter / fake
  runner を使う部分。なお `test_cli.py` の default pacing は別途実時間を消費する。
- site-specific pure parser / policy / mapping:
  実 page を使わない `jumpplus_*`、BookWalker / Magapoke / Manga ONE の parser・policy
  ケース。

「SQLite / filesystem を使わないこと」を unit の必要条件にすると、Catalog / packaging
 の妥当な component test までこぼれるため、外部 browser / network / real-site boundary
 の有無で見る方が現状には合う。

### 5.2 Integration 相当なのに unit 配下にある候補

次の8 file は、少なくとも一部が実 Chromium + Playwright Page / Locator / DOM を使う。

- `tests/unit/test_access_guard.py`: captcha provider の visible / hidden DOM 判定 1 test。
- `tests/unit/test_bookwalker_adapter.py`: strict entry control、delayed DOM control、
  canvas capture target。
- `tests/unit/test_bookwalker_discovery.py`: listing / product HTML、pagination、
  product control と Catalog の境界。
- `tests/unit/test_bookwalker_original_capture.py`: browser canvas / image signature、
  original JPEG listener。
- `tests/unit/test_magapoke_adapter.py`: viewer DOM / entry / terminal と native capture。
  同じ file に pure JPEG reconstruction も混在する。
- `tests/unit/test_magapoke_discovery.py`: listing DOM と DiscoveryService / Catalog。
- `tests/unit/test_mangaone_adapter.py`: quota entry と viewer appearance、同じ file に
  parser / WebP bytes test も混在する。
- `tests/unit/test_mangaone_discovery.py`: chapter listing DOM と Catalog。

これらは実サイトへ接続しているわけではなく、route / `set_content()` / data URL を使う
local browser test である。それでも browser / DOM / adapter boundary の確認なので、
現在の `tests/unit/` という配置だけでは実行コストと意味が見えにくい。

### 5.3 Research / Probe 相当の候補

measured snapshot で `poc/` を直接 import するものは次の4 file / 40 cases。

- `tests/unit/test_jumpplus_discovery_probe.py` (7)
- `tests/unit/test_jumpplus_probe.py` (11)
- `tests/unit/test_jumpplus_reconstruct.py` (13)
- `tests/unit/test_zeblack_probe.py` (9 at measured snapshot; 14 currently)

調査中に `poc/zeblack_capture_probe.py` が追加され、`test_zeblack_probe.py` から直接
import される5 casesが増えたため、current collection ではこの probe group は
**45 cases** になっている。

これらは production package (`src/screenshot_crawler`) の契約ではなく、`poc/` の
probe / reconstruction / report implementation を直接検証している。PoC の結果を
production adapter の regression contract として残す価値があるか、または research / probe
suite として明示的に別実行するかは次 Phase の判断材料である。今回は削除・移動をしていない。

### 5.4 現在の integration として妥当なもの

`tests/integration/` の2 file は、人工 local viewer を実 Chromium で開き、Core Runner と
Adapter、DOM state、capture、END / NEXT_CONTENT、same-content / max-pages の境界を通して
いる。`docs/TEST_STRATEGY.md` の Integration Tests の説明と実装が一致している。

## 6. Possible Duplicate / Low-value Candidates

ここでは候補のみを挙げ、削除・parameterize・統合は行っていない。

| candidate | 観測した重なり | 判断保留の理由 |
|---|---|---|
| `test_mangaone_adapter.py` と `test_local_viewer_flows.py` | Manga ONE の quota / viewer、image disappearance、END / chapter transition をそれぞれ adapter 直下と Core+DOM で確認 | pure adapter contract と integrated runner contract の二層なら重複ではなく役割分担の可能性がある |
| `test_magapoke_adapter.py` と `test_magapoke_local_viewer.py` | JPEG reconstruction / screenshot fallback、terminal / next episode の挙動が両方に現れる | codec selection の unit と browser capture flow の integration で、同じ契約かは要整理 |
| `test_bookwalker_adapter.py` 内の strict entry matrix | direct / quota、owned / purchased / trial / subscription / generic、duplicate / delayed / UUID mismatch が多数の近接ケースで反復 | access strategy の安全性 matrix として意図的な可能性があり、単純な重複とは言えない |
| `test_batch.py`、`test_batch_executor.py`、`test_bookwalker_batch.py`、`test_cli.py` | resource pass、quota consumption、failure / replan / grant-only の同じ分岐を層ごとに確認 | Planner / Executor / CLI orchestration の責務境界を守るための重複かもしれない |
| generic `test_discovery.py` と各 site discovery test | full / incremental、known streak、Catalog sync / incomplete の類似契約 | site-specific DOM / identity / policy が異なるため、共通化できる範囲は未確認 |
| Jump+ / Zebrack probe test | probe の target guard、resource classification、report artifact の構造が似る | 同じ production contract ではなく、将来の probe test harness 候補という段階 |

低価値かどうかは、test count ではなく、どの層の契約を担っているか、失敗時にどの境界を
特定できるかを見て次 Phase で判断する必要がある。

## 7. Implications for Future Test Policy

### 7.1 想定されている運用案への材料

提示された次の方向性は、今回の計測結果と概ね整合する。

```text
変更中                  -> targeted tests
実装完了前              -> 影響範囲の unit tests
Core / shared component  -> unit suite 全体
browser / viewer        -> 関連 browser-backed integration
大きな shared 変更      -> unit + 必要な integration
実サイト挙動変更        -> 必要に応じて live verification
```

ただし、次の補足カテゴリが必要になる。

1. **browser-backed local tests**: path ではなく Playwright / Chromium の有無で選ぶ。
   現状は unit 配下にも8 fileあるため、`pytest tests/unit` を「browserなし」と扱えない。
2. **research / probe**: `poc/` direct import の4 file / 40 casesを production regression
   と同じ必須 suite とするか、明示的な research/probe suite とするかを決める。
3. **pacing / real-time contract tests**: batch の3秒 inter-candidate delay、timeout、
   grace period を含むテストは、unit の依存関係は軽くても wall-clock が重い。通常の
   targeted run と、pacing contract を確認する選択的な run を分けられるか検討する。
4. **DB / filesystem component tests**: SQLite / ZIP / output safety は unit 相当だが、
   Core / Catalog / packaging の shared change では影響範囲として拾う必要がある。

### 7.2 フル pytest を毎回実行する合理性

- 現状の標準 full pytest は約 **4分**で、全777件が passed する。
- unit suite だけでも warning 抑制下で **177.82s** あり、8 file の実 Chromium と多数の
  DOM / wait test を含む。
- よって、変更中の毎回の標準実行として full pytest を強制する合理性は低く、targeted
  test と影響範囲 test を先に選ぶ余地が大きい。
- 一方、Core / Runner / shared browser / Catalog / packaging など広い変更、または完了
  前の最終確認では、full suite の価値がある。今回の passed result は、現在のsuiteが
  4分で完走可能であることも示している。
- 実サイトの live verification は pytest の代替ではなく、人工 fixture で表現できない
  adapter / session / account 状態の確認として別枠に置くべきである。

### 7.3 今回の調査から追加で必要な判断

- `unit` と `integration` の境界を directory 名ではなく browser / external boundary /
  real-time wait / PoC dependency で表すか。
- browser fixture の共通化や timeout短縮を行うかは、分類を決めた後の別 Phase とする。
- warning 2747 件を test policy / dependency maintenance の課題として別途扱うか。

## 8. Open Questions

- browser fixture の setup / teardown が suite 全体で何秒を占めるかは、今回の
  `--durations=30` 上位結果だけでは確定できない。上位30はすべて call phase だったため、
  次 Phase で phase 別集計が必要。
- Chromium のバージョン、CPU、filesystem cache により browser test の秒数は変動する。
  今回の時間は Python 3.14.6 / pytest 8.4.2 / local Windows 環境の snapshot であり、
  CI baseline ではない。
- `poc/` の各 helper が今後も研究用なのか、production adapter の supported contract に
 昇格済みなのかは、実装方針だけでは決められない。
- `test_cli.py` の 3 秒 pacing を実時間で検証する必要があるテストと、orchestration の
  分岐だけを検証したいテストの境界は未整理である。
- `test_magapoke_adapter.py`、`test_mangaone_adapter.py`、
  `test_bookwalker_original_capture.py` のように pure helper と browser test が同一 file
  に混在する file は、file単位の選択だけでは過剰実行になる可能性がある。
- 現在の pytest standard output には多数の pytest-asyncio deprecation warning があるが、
  その扱いはテスト分類とは別の保守課題である。

## Measurement and change record

- 実行したもの: `pytest --collect-only -q`、標準 `pytest -q`（777-case snapshot と
  current 782-case state）、durations 付き full run、`tests/unit` /
  `tests/integration` の分割 run。
- production code: **変更なし**。
- test code: **変更なし**。
- pytest 設定: **変更なし**。
- test file の移動・削除・parameterize・統合: **なし**。
- 作成した資料: `note/test_suite_audit.md`。

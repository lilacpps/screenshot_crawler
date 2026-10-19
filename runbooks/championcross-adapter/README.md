# Champion Cross（チャンピオンクロス／チャンピオン＋）Site Adapter 実装 Runbook

**Status:** PLANNED（2026-10-20。実装・実サイトE2Eは未着手）
**Repository:** `lilacpps/screenshot_crawler` / `main`。このrunbookは計画のauthorityであり、実測・進捗・消費枚数は [PROGRESS.md](PROGRESS.md) に記録する。
**実装ブランチ:** 着手時の最新 `main` から `feat/championcross-adapter` を作る（既存同名ブランチがあれば確認し、勝手に上書きしない）。コードを `main` へ自動マージしない。
**サイトキー:** `championcross`。名称「チャンピオン＋」は呼称として扱い、`championplus` などの別siteキー・別Catalogを作らない。
**対象サイト:** https://championcross.jp/ / https://championcross.jp/tutorial

## 0. 最重要契約（実装中に緩めない）

1. **今回実装するのは「無料」と「待つと無料（`work_ticket`）」まで。** 「すぐ無料チケット」は、同じ話に「待つと無料」と併記されていても**別の、作品をまたいで使える資源**。マガポケの `premium_ticket` に相当する概念として扱い、今回は取得・消費・残高管理・フォールバックの全てを**対象外**とする。有料コイン、購入・レンタルも実装対象外。同一話への二つのアイコン表示を「曖昧な状態」と誤判定しない。
2. **quota/`work_ticket` を使う通常Batch・grant-onlyは、Catalog/DBに保存された「選定済みの対象話のURL」へ直接1回入場する。** その時点の各話の状態を調べるための作品一覧（`/series/*`）アクセス、別話の試し開き、順繰りのlive事前探索、横断的な事前権限収集を**一切しない**。DB内の情報だけで「作品ごとに1話」を選び、対象話で「待つと無料で読む」（実際のUI表記はread-only probeで厳密確認）に相当する**一意・正規・無料**のボタンを検証して、確認できれば消費を試行する。見つからなければその作品をSKIP/FAIL CLOSEDとし、同作品の別話へフォールバックしない。
3. **この制限は実装上の必須不変条件であり、最適化の提案ではない。** 「より確実に現在の状態を確認したい」ためにBatchの前に作品・各話を探索するResolver/Probe/Preflightを足してはならない。手動 `discover` は別コマンドなので通常の作品一覧列挙が許される。Batch内部からDiscoveryを暗黙実行しない。対象話のページで自然に発生する対象話に限った認証・権限応答を観測するのは可だが、追加の状態探索APIで候補を探し回らない。
4. **Work Ticketは作品単位で23時間の回復制限、使用した話の閲覧権限は話単位で最大72時間**という契約。実際の有効期限は同一対象話で観測した残時間から保守的に保存する。作品をまたいで使える「すぐ無料チケット」の回数や権利はここへ一切混入しない。
5. **実際の消費操作は1作品1候補・1試行。** 正の本人認証・対象work/episode・無料Work Ticketボタンを照合する。消費操作開始後はtimeout/キャンセル/通信エラーでも自動再クリックしない。事前の非消費UI操作または確認ダイアログが実在するなら、read-onlyで正確に検証してから最小の手順だけ許容し、**消費確定操作は1回、消費試行全体は再試行しない**。「すぐ無料」や有料のボタンへ切り替えない。
6. **消費の確定と画像取得の成功は独立。** 同一対象話に対する消費の正の証拠を得たら、後続Viewer/END/ZIP失敗でも消費と有効権限をCatalogに記録する。消費の成否が不明なら成功扱いしないし、自動で再試行しない。通常Batchは消費後の**同じPlaywright Page**で本文→END→ZIPを続行する。
7. **既存Chrome/CDP・AccessGuard・pacing・quota・Catalog・Batch・manifest/ZIPを使う。** 新サイトのために共通Coreや既存Hanayume/YoungAnimalを大規模リファクタリングしない。権利のない画像取得、CAPTCHA/MFA回避、403/429回避、認証情報/署名付きURL/漫画画像のgit登録は禁止。
8. **このrunbook自体は実サイトWork Ticket消費の許可ではない。** 実消費する段階でユーザーが対象話URLと上限枚数を明示的に承認するまでは、read-only probe、fixtureテスト、無料話・既存Grantの取得まで進め、未承認の消費を実行しない。未検証のチケット消費をPASS/DONEと記載しない。

## 1. 目的・範囲・再利用

### 1.1 目的

Watchlistの1作品URLを起点に、チャンピオンクロスの `Discovery (full/incremental) → Catalog → Batch plan → Batch run → Viewer Capture → END → ZIP → completed` を実装する。無料話は`direct`、正確に確認できた「待つと無料」未使用話は作品単位`quota/work_ticket`、手動またはBatchで使用済みかつ有効期限内の同じ話は**再消費せずdirect**として扱う。通常の作品単位Batch、`--limit`、`--grant-only work_ticket` に対応する。

### 1.2 アクセス種別

| 公式UI/認証・権限観測 | Catalog/Policy | Batch |
| --- | --- | --- |
| 無条件・正規の無料 | `free` | `direct` |
| 認証を必要とする無料（認証・権限を正に確認済み） | `free`（条件に沿って保持） | `direct` |
| 「待つと無料」未使用・対象episodeに正の証拠あり | `quota` + `work_ticket` | Catalog選定 → 対象episode直行 → 正規ボタン確認 → quota |
| 「待つと無料」使用済みで同じepisodeの有効な閲覧Grantあり | `quota` + 観測済み `access_granted_until` | `direct`・クリックなし |
| 「待つと無料」と「すぐ無料」が**併記**されている | 「待つと無料」の正の証拠で上記quota判定。もう一方は対象外 | `work_ticket` のみ使える |
| 「すぐ無料」しか確認できない | `unknown` / 不許可（既存Catalog型で表現） | SKIP。`premium_ticket` 的な資源を使用しない |
| 課金・コイン・購入・不明なレンタル | `paid` / `unknown` | SKIP |
| ID不一致、状態矛盾、既存Grantの正当性不明 | fail closed | 取得も消費もしない |

無料の条件、確実な有料判定、キャンペーン期間、二種のアイコンの具体的DOM/APIは本runbook時点で**未実測**。部分一致文字列やアイコン数だけで「quota使用可能」としない。

### 1.3 参考実装・authority

上位仕様: `AGENTS.md`、`docs/SPEC.md`、`docs/ARCHITECTURE.md`、`docs/DISCOVERY_AND_BATCH.md`、`docs/ACCESS_CONTROL_AND_PACING.md`、`docs/CAPTURE_STRATEGY.md`、`docs/SITE_ADAPTER_GUIDE.md`、`docs/TEST_STRATEGY.md`、`docs/CODEX_IMPLEMENTATION_GUIDE.md`、`docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md`。衝突した場合はLeadが原因と解決を明記し、上位仕様を黙って変更しない。

- `src/screenshot_crawler/site_adapters/younganimal/` と `src/screenshot_crawler/site_policies/younganimal.py`、`runbooks/younganimal-work-ticket/README.md`: 同基盤のDiscovery・safe ticket entry・same-Page Viewer・23h work resource・72h上限とは別の実測タイマー・grant-only。特に「1作品1候補」「消費をViewer/ZIP失敗から独立させる」実装を第一候補として調べる。
- `src/screenshot_crawler/site_adapters/hanayume/`、`src/screenshot_crawler/site_policies/hanayume.py`、`runbooks/hanayume-work-ticket/README.md`: 72h閲覧Grant、手動使用済みGrant同期、厳密なWork Ticket entry、先頭空白・見開き・初期Canvas安定とpost-encoding proof。
- `src/screenshot_crawler/batch/planner.py`、`batch/executor.py`、`batch/grants.py`、`cli.py`: 作品単位quota候補、`after_observed_consumption`、ローカルSKIP、`grant-only`、各Registry登録。現行APIを優先し、共通改修は既存契約で実現不能と確認した場合に限定する。
- 公式仕様参照: https://championcross.jp/tutorial （23h「待つと無料」、別資源「すぐ無料チケット」）と対象話の表示（72h閲覧）。サイトの現在のHTMLやログイン後動作は実サイトで改めて観測する。

## 2. Phase 01 — Repo差分・安全なRead-only実サイト調査

**担当:** Lead → Explorer → Reviewer。必要時だけImplementerが境界のあるread-only診断を作成。**チケット消費0件。**

1. main HEAD/既存site key/Registry/Planner/WorkTicket経路/Viewerの観測済み例を確認し、YoungAnimal、Hanayumeとの**実際の差分**を表にする。
2. 少数の公開episode URLを対象として、`https://championcross.jp/episodes/<id>` と作品`/series/<id>`の実形式、episode/work ID、canonical route、表示タイトル、一覧番号、もっと見る/範囲分割、総件数、順序、ラベル、二種類のアイコンを調べる。Discoveryでは正規の作品一覧移動を許す。
3. 認証状態を区別し、正規の無料・Work Ticket・「すぐ無料」・有料を**同じ話の複数選択肢として**識別する。`「待つと無料」で読む`等、実際の表示文言・ボタン属性・親スコープ・唯一性・可視/有効条件・有料兄弟との違い・確認モーダルの有無を、**対象episodeだけ**で確認する。
4. 前後の権限についてはサイトが自然に返すwork/episode boundのAPI/DOM/時間をread-onlyで観測。成功の正の証拠候補、手動Grantの認識、画面遅延や二重ボタン、読める状態の中央ゲート/ログイン状態を記録する。API名・フィールド名が他サイトと同じと決めつけない。
5. 無料話と期限内Grantなど**権利が既にある話**で、Viewer初回、spreads、ページ数・counter・physical wrappers、先頭空白、画像ソース/draw geometry、END/次話誤遷移を確認。サイズは固定値を流用しない。
6. 確認に使う候補の例（実行時点の公開・権利は未保証）: `https://championcross.jp/episodes/c1e8056b4e0e1`（Work Ticket操作表記の調査候補）、`https://championcross.jp/episodes/aaf4e3ea717b4`（2種アイコン表示の調査候補）。**ユーザーの消費許可リストではない。**

**Gate 01:** work/episode正規化、UIとnativeの対応、無料性、二種のチケット分離、Viewer形状、消費の正の証拠候補を「OBSERVED / INFERRED / UNKNOWN」でPROGRESSに記録する。特に「DB URL直行だけで本人認証と対象ボタンを検証できるか」を確認。Batchのためのseriesアクセスを足す案は**不採用**とする。正の証拠が不足ならその経路のみ未対応/fail closed。

## 3. Phase 02 — Full/Incremental Discovery・SitePolicy・Catalog

### 3.1 Discovery

- Watchlistの1作品に紐づくcanonical workとepisodeを検証し、正規のサイト固有Bounded Discoveryで一覧を**全範囲**検証後にCatalogへ同期。work ID、episode ID、URL、タイトル、表示位置、公開状態、出典、順序を保存する。
- Fullは一覧全体と利用可能性を反映。Incrementalは既知連続話の停止基準だけで**古い話の手動Grant更新を取りこぼさない**よう、既に取得済みの一覧/認証状態更新を安全に統合する。サイトが不完全なら中断し、消えた話を憶測でunavailableにしない。読了状態やzip命名は既存Catalog/Batch契約に従う。
- `「待つと無料」＋「すぐ無料」`の併記は合法。待つと無料の正の根拠で`quota`にする。全話unknownの一括quota化は禁止。過去のGrantだけで新規使用権を捏造しない。
- 手動Work Ticket使用済みは**episode単位**に`access_granted_until`と`access_granted_until_observed`を同期し、期限内`direct`。期限は観測可能なサイト時刻・残秒数から保守的に計算。矛盾/一時的な取得不能の観測だけで確実な未来Grantを消さず、明確な期限切れ・権利消失時はクリア。手動使用のwork cooldownは使用・回復時刻の**正の証拠がある場合に限り**同期し、72h期限から23h消費時刻を勝手に推定しない。

### 3.2 Policy / Planner

`ChampioncrossSitePolicy`は`work_ticket`に限り下記を実装する:

```python
site = "championcross"
quota_resource = "work_ticket"
quota_scope = "work"
quota_limit = 1
quota_commit_mode = "after_observed_consumption"
```

- `supported_access_resources` / `ordered_access_resource_passes` / `grant_only_supported_access_resources` は`("work_ticket",)`。`resource_state_scope("work_ticket") == "work"`。`defer_quota_access_to_grant_phase() == False` を原則とし、既存non-deferred構成に乗せる。
- `free`→`direct`、正の期限内episode Grant→`direct`、正の未使用Work Ticket候補→`quota`。`paid` / `unknown` / すぐ無料のみ→不許可。`grant-only`は対象の未使用Work Ticketのみ。
- 一つのworkに複数`quota`候補があっても**Catalogから最初の1件を決める**。その候補が現地で使えなければwork SKIPであり、**別のepisodeを試さない**。Batchの `--limit` / quota resource pass / stop-on-failure がこれを破らないかを検証する。
- `site, work_id, work_ticket`に記録した最終消費時刻から23時間未満は**ローカルSKIP**（長いユーザー設定は尊重、短縮は不可）。SKIP時はPage作成・goto・サイトHTTPが**0件**。別サイト・別作品・作品共通「すぐ無料」残高とは完全に分離する。
- episode閲覧Grant上限は72時間。生の残時間が観測できればrequest/観測時刻から保守的な期限を算出（丸め誤差を減算）、**上限72hを超過しない**。サイト由来の正の期限証拠がない場合は権利未確認のままとし、72h固定値を捏造してdirect化しない。tz-awareの時刻で判定する。

**Gate 02:** テストで「二種併記→`quota/work_ticket`のみ」「すぐ無料のみ→SKIP」「23h境界」「episode Grant期限境界」「別work/別site独立」「full/incremental手動Grant更新・失効」「1作品1候補」「site requestゼロのSKIP」「未知→失敗」を検証。

## 4. Phase 03 — Championcross Viewer/Native Capture/無料Direct Batch

- `ChampioncrossAdapter`を独立site adapterとして新設。`cli.py`の`_registry` / `_batch_adapter_registry` / `_discovery_registry` / `_batch_policy_registry`等、現在存在する4種類のRegistryへ追加。`site_policies/__init__.py`も更新。
- **BatchはCatalogが選んだ対象話URLへ直接移動する。** quotaだけでなく無料directでも既知identityを使い、不要なseries往復を作らない。手動URL Crawlの事前確認は別経路として扱ってよい。
- 原本JPEG/PNG/WebPを本文と1対1で立証できればバイト列を優先。できない場合は元source/canvasの描画時画素・幾何/identityを検証して元寸法の可逆WebP（VP8L）、同一検証済みPNG fallbackを利用。rendered fallbackは正当性・ページの完全性を証明できる場合のみ。元データを取得できないものを「原本」と表示しない。
- Hanayume/YoungAnimalのViewer codeから、先頭空白・spread・counter/wrapper数・ページ順序・巻き戻し・initial canvas quiet・native proof・post-encoding verifyを参考にする。ただしsite固有の観測証拠がないlayout/画像サイズを無条件に採用しない。
- 初回〜ENDの本文全ページを重複/欠損/左右逆転なく取り込み、広告・操作UI・無関係な次話を本文へ混入させない。終了成功だけZIP化しCatalog Itemをcompletedとする。失敗時の途中成果を完成済みとしない。

**Gate 03:** 公開無料話2例以上（可能なら別作品・異なるViewer layout）で`discover → batch plan → batch run → END → ZIP`を隔離データで確認。CRC、画像デコード、形式・寸法、順序、manifest・Catalog・成果物SHA/サイズ、画像画素とprovenance（検証できた範囲）を独立監査。**無料話実サイトE2EがPASSするまで、実チケット消費に進まない。**

## 5. Phase 04 — Work Ticket entryとsame-Page Batch

**対象操作はDB登録済みの一話に限定。二つのチケットが表示されていても「待つと無料」だけ。**

1. **Catalogのみ**でwork/episode/`SourceTarget.locator`を選び、ローカルcooldownと既存Grantを判定する。Batch内部で一覧ページへ移動・Discover・別話のliveアクセス可否確認・一括Resolver作成を行わない。
2. 対象work/episode/canonical URLの一致を確認。1つの既存CDP Pageで**DB保存のepisode URLへ直接goto**。入場前に対象話にスコープしたnetwork response observer / 必要なroute guardを設置し、**他話/seriesへの事前navigationは禁止**。ページ自身のRSC prefetchがあるなら既存Hanayume/YoungAnimalと同様に観測済み狭い形だけabortし、それを探索の代替にしない。
3. **到達したその話のページ上だけ**で本人認証・work/episode identity・native/access stateと、唯一の「待つと無料で読む」相当の正規無料ボタンを確認。二種のボタンがあれば`すぐ無料`を**明示的に拒否対象へ分離**し、消費用Locatorがそれに一致しないことを検証。目標ボタンがなくても別話・作品一覧・別リソースへ移動しない。
4. locatorは唯一・可視・enabled・上に重なりなし・同一DOM identity・親scope一致・無料条件を確認し、直前に再確認。実際に確認モーダルがある場合も最終確定ボタンの種類と対象IDを厳格照合。消費確定アクションは1回のみ、失敗/Timeout/Cancelで再実行禁止。サイト側が自発的に発行する正規の消費通信を観測する（自前の購入・checkout HTTPを組み立てない）。
5. サイトの**同じepisode/workに結びつく**成功応答と`hasAccess`等のgrant遷移（実サイトで証明できた組み合わせ）で消費を確定して`AccessConsumption`に直ちに保持。使用時刻・72h以下の観測有効期限とwork cooldownを、Viewer/ZIPとは独立してCatalogへ保存。positive proofなしは`unconfirmed`であり自動retry不可。
6. **通常Batch:** 操作後も**同一Page**・同一話のViewerへ接続し、追加`goto`/reload/別Page作成をせずCapture→END→ZIP。**`--grant-only work_ticket`:** 同じ消費判定だけで終了、保存画像=0、ZIP=0、Item pending、消費記録あり。Grant-only後の通常Batchは同話の期限内Grantをdirect使用できる。
7. 消費前にすでに有効な閲覧Grantがある場合は再クリックせずdirectに切り替えられるのは**通常Batchのみ**（positive proof必要）。Grant-onlyは「すでに有効」として消費せずSKIP。**対象話が不適格でも候補を切り替えない。**
8. 対象外の有料/`すぐ無料`/別話/ログイン導線、response不一致、403/429/CAPTCHA、未知の別サイト遷移はfail closed。クリック後の中断・画像取得失敗でも確認済み消費は保持し、未確認は未確認としてログに区別して残す。

**Gate 04（fixture/browser）:** unique button、二種併記、すぐ無料だけ、モーダル有無、未ログイン、duplicate/hidden/disabled/covered、paid、ID mismatch、ボタン差し替え、hydration遅延、click timeout、checkout応答失敗、消費成功→Viewer/ZIP失敗、cancelをテスト。特に**DB URL以外の初回navigation 0、series/他話へのBatch主導アクセス0、別話の事前状態照会0、same-work候補fallback 0、すぐ無料操作0、有料操作0、再消費試行0**をSpy/Network fixtureで証明する。

## 6. Phase 05 — 独立レビュー・実サイトE2E・完了判定

1. **テスト:** `ruff check src tests`、関連`pytest`と`git diff --check`。共通Batch/Policy変更時は全関連site policyテストを実施し、Hanayume/YoungAnimalのdirect、work_ticket、Grant、Capture、ComicDAYS/Zeblackのquotaと正常ZIPを回帰確認。全テストが実行不可の場合は理由を残す。
2. **隔離:** `output/championcross_experiment/`以下に専用Watchlist、Catalog、batch、library、metricsを指定。普段のDBやライブラリを触らない。共有ログイン済みChromeを操作するエージェントは1名のみ。Cookie等を保存/コミットしない。
3. **Free E2E:** Phase 03で実測した無料話を、通常CLIで複数対象検証。必要なら起動時に`--limit 1`を使用。Reader→END、本文画像、ZIP、Catalog状態を独立検証。
4. **手動既存Grant E2E:** 実際に期限内の閲覧権限があるなら`discover full` / `incremental`で反映し、`batch run`を対象話へ直行させ、**Work Ticket消費0・余計なseriesアクセス0**でEND/ZIPを確認。実在しなければFixture PASS、live NOT VERIFIEDと明記。
5. **実チケット消費（別途の明示許可が必要）:** 許可された対象話・枚数上限の範囲で、まず最少1件を通常Batchかgrant-onlyで検証。実際の1回操作の証拠、正のconsumption、work cooldown、episode grant、Viewer/ZIPまたはgrant-onlyの0画像/0ZIPを記録。追加の実消費は未検証事項に必要で、かつユーザーが許可した枚数内に限る。**許可がない場合は消費せず、未検証Gateを明記して完了扱いしない。**
6. **独立監査:** Reviewerは仕様不一致・quota候補探索・権利誤認・重複消費・タイマー・回帰を懐疑的に検査。TesterはCLI/Network/CDP trace、対象話URL、Catalog、zip member順、CRC、画像寸法・デコード・hash、使用枚数/時刻を確認。失敗箇所とテスト範囲をPROGRESSへ記録。

**最終受け入れ条件:** Full/Incrementalの一覧・Grant同期が正確、無料DirectがEND/ZIP、既存Grantは再消費しない、work単位23h SKIP時のサイトrequest 0、quota時は**DB対象episode URL以外を状態探索しない**、正規「待つと無料」の消費のみ、1work1candidate、使った後はsame-PageでEND/ZIP（grant-onlyなら0画像/0ZIP）、消費と取得結果を独立永続化、既存sitesの回帰なし、Reviewer/Tester証拠あり。**実消費未承認/実サイト未確認なら最終DONEではない。**

## 7. 変更範囲・開発運用

| 変更先 | 方針 |
| --- | --- |
| `src/screenshot_crawler/site_adapters/championcross/__init__.py` | Adapter/Discovery公開 |
| `.../championcross/discovery.py` | work/episode identity、full/incremental、free/quota/Grant観測 |
| `.../championcross/adapter.py` | target URL direct、Viewer、Work Ticket安全入口 |
| `.../championcross/native_capture.py` | 実際のViewerに必要な場合のみ。YoungAnimal等のコードを根拠なくコピーしない |
| `src/screenshot_crawler/site_policies/championcross.py` | 作品`work_ticket`、23h、話Grant、safe Policy |
| `src/screenshot_crawler/cli.py` / `site_policies/__init__.py` | Registryと`site`登録 |
| `tests/unit/test_championcross_*.py` / `tests/integration/test_championcross_*.py` | 上記GateのUnit、Browser fixture、負例、回帰 |
| `src/screenshot_crawler/site_adapters/championcross/README.md` / `note/`の空いているsite note / index | 仕様と実測を実装状態へ同期 |
| `runbooks/championcross-adapter/PROGRESS.md` | Phase状態、観測、テスト、レビュー、実消費ledger |

- `batch/planner.py`、`batch/executor.py`、`batch/grants.py`、`discovery/service.py`など共通部分は**原則変更しない**。既存契約でできないという再現テストと最小パッチ案をLeadが承認した場合のみ触り、既存全サイトへの回帰を必須化。
- 既存`Hanayume/YoungAnimal`のproduction codeを「コミチ共通化」の名目で大規模に変えない。独立Adapterをまず完成させ、明確に同一で試験容易な小さい部分だけ共有。
- 分担は`docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md`に従い、Lead（仕様・ゲート）、Explorer（read-only）、Implementer（唯一のproduction writer）、Reviewer（独立・read-only）、Tester（独立E2E）。共有Chromeは逐次利用、同時アクセス禁止。
- 実装中は1つのrunbookを通してPhaseを進める。調査だけ終えてタスクを打ち切らず、未確認箇所だけfail closedにして安全に進められる範囲を完成する。既存仕様との差異は`PROGRESS.md`に記載。最終的に`main`へ自動マージしない。

## 8. Codex開始時チェックリスト

- [ ] 最新`main`と`AGENTS.md`等authorityを読んで実装ブランチ作成、`PROGRESS.md`にbaseline記録。
- [ ] 2種チケットは**異なる資源**、今回は`work_ticket`のみという仕様を確認。
- [ ] Batch/Grant-onlyの**Catalog URL直接入場、シリーズ・他話事前探索なし**の負例テストを最初に計画。
- [ ] Phase 01 read-only観測でサイト固有ID/DOM/API/Viewerの根拠を収集。
- [ ] Phase 02/03でDiscovery・Policy・無料E2Eを完成、Reviewer Gateを通す。
- [ ] Phase 04でWork Ticket入口・消費永続化・grant-onlyを実装、Fixtureの負例を含むGateを通す。
- [ ] 承認された場合だけ最少枚数で実サイト消費し、消費有無・件数・対象ID・日時を記録。
- [ ] 全変更・テスト・Reviewer/Tester結果・未確認条件を`PROGRESS.md`に残す。

# ComicFUZ 日次チャージ（`work_ticket`）実装 Runbook

**Runbook contract:** 2026-11-23 JST。これは実装・検証の実行契約であり、各Phaseの完了状況と実サイト検証範囲は [PROGRESS.md](PROGRESS.md) が記録する。
**Baseline:** 実装開始時に `main` HEAD と差分を記録。既存の `runbooks/comicfuz-free/` と `note/13_comicfuz.md` を出発点とする。
**実装ブランチ:** 最新の `main` から `feat/comicfuz-work-ticket` を新規作成。ユーザーの明示指示がない限り `main` に自動マージしない。既存の未コミット変更は保持する。
**Authority:** `AGENTS.md` の順序（`docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/DISCOVERY_AND_BATCH.md`, `docs/ACCESS_CONTROL_AND_PACING.md`, 現行コード/テスト）を遵守。上位仕様との衝突は明示して最小修正。

## 1. 目的と確定した要求

既存 ComicFUZ の無料話 `direct` Discovery→Batch→Viewer→ZIP を維持したまま、「チャージ」のある話を `work_ticket` として通常 Batch と `--grant-only work_ticket` に追加する。Premium Ticket、コイン、メダル、有料購入は**一切使用・実装しない**。

| 項目 | 契約 |
| --- | --- |
| サイト | `comicfuz` |
| Resource | `work_ticket` のみ。 `supported_access_resources`, `ordered_access_resource_passes`, `grant_only_supported_access_resources` は `("work_ticket",)` |
| 消費単位 | 1作品で日ごと最大1枚。作品間は独立。1回の Batch plan では1作品の quota 候補は最大1話 |
| **回復** | **毎日 00:00 JST（`Asia/Tokyo`）に日次リセット**。消費から23h/24h経過ではない。サイトの実利用可否は現場のUI/APIが最終 authority |
| 使用日 | サイト上で**確定した消費の日時**を既存 `quota_resource_states.last_consumed_at`（`work_id,site,resource`）へ保存 |
| Grant | チケット使用で開放された当該**話**の `access_granted_until` は work の日次リセットとは別。観測可能なサイト由来の期限を採用し、未観測の「72時間」を無条件に埋めない |
| 通常 Batch | 作品ごとに適格な1話でチケットを最大1回使用、正の消費確認後に**同じ Playwright Page**から既存 Viewer→END→ZIP→Completed を継続 |
| Grant-only | 消費確認・DB永続化のみ。画像0、ZIP0、対象 Item は pending。後日、閲覧権限が有効なら通常 Batch が `direct` 取得できる |
| その他 | `--grant-only all` を使う場合もComicFUZのpassは `work_ticket` のみ。明示 `premium_ticket` は拒否 |

### Discovery の分類（ユーザー確認済み表示）

- 行に正確な「無料」表示がある → `access_mode=free`。
- 行にコインのマークがある → `access_mode=paid`（**閲覧・購入操作は禁止**）。
- 無料/コインその他の価格・権利マーカーが**何もない、完全に描画済みの正規話行** → `access_mode=quota`（チャージ候補）。
- 行の構造、非表示マーカー、未知アイコン、loading/hydration、複数または矛盾した印がある → `unknown` / Discovery fail-closed。**「無料マークがない」だけで一律にquotaにしない**。

「無料/コイン/無表示」の正規DOM構造とコインが img / svg / CSS 背景 / first-party metadata のどこにあるかは Phase 01 の読み取り専用調査で確定させる。既存の`#__NEXT_DATA__` chapter ID↔見出し完全照合、全行数、順序、`global_display_position`、スコープ・incremental の契約は変えない。匿名時とログイン時の差分を検証する。

## 2. 日次リセットの設計判断（23時間制と混同しない）

**DBスキーマは原則変更しない。** 既存 `CatalogService.record_quota_access_with_resource_state()` が source grant と作品単位 resource 消費を原子的に記録できる。共通 Executor の `resource_state_skip_reason()` / `grant_only_retry_at()` は SitePolicy hook を呼ぶため、時刻の判断だけ ComicFUZ 固有に実装する。

時間は全て timezone-aware とし、JSTに変換する（OSローカル時刻やUTC日付で比較しない）。考え方は以下。

~~~python
JST = ZoneInfo("Asia/Tokyo")

def next_reset(last_consumed_at):
    consumed_jst = last_consumed_at.astimezone(JST)
    next_day = consumed_jst.date() + timedelta(days=1)
    return datetime.combine(next_day, time.min, tzinfo=JST)

# resource == "work_ticket" かつ last_consumed_at がある場合
retry_at = next_reset(last_consumed_at)
skip = now.astimezone(JST) < retry_at
# skip なら "work_ticket_daily_reset" 等の明示 reason を返す
~~~

`ComicFuzSitePolicy.grant_only_skip_reason()` は上記ルールで判定し、`grant_only_retry_at()` は「**最終消費日の翌日 00:00 JST**」を返す。通常 Batch も既存 Executor の同じ local gate を通す。境界は厳密に `now < reset` が SKIP、`now == reset` はサイト再判定に進む。

| 確定した消費 | ローカル次回確認可能 |
| --- | --- |
| 2026-11-23 09:00 JST | 2026-11-24 00:00 JST |
| 2026-11-23 23:50 JST | 2026-11-24 00:00 JST |
| 2026-11-24 00:01 JST | 2026-11-25 00:00 JST |

- `runtime_settings.work_ticket_cooldown_hours` は他サイト用の**経過時間**設定。ComicFUZ の日付ルールには適用せず、23hが過ぎても同日ならSKIP、23h経たなくても翌日00:00ならサイトで再確認。共有設定の意味論を変えない。ここをテストで明示する。
- `grant_only_retry_at` は「ローカルで次に確認可能な時刻」の推定であり、**サイト上で利用可能である保証ではない**。0時直後にサイトの反映遅延があれば「利用不可」で終了し、誤クリックしない。
- `management/inventory.py` は既存 Policy hooks から次回時刻を取得する。期限超過の過去時刻を「次回」と誤表示しないこと、ComicFUZが23h表示にならないことをUI/モデルテストで確認し、必要な場合だけ最小修正。
- 手動でサイト上のチケットを使った場合、閲覧期限の観測だけから消費日時・使用日を逆算して work state を偽造しない。サイトが**その作品の回復時刻/当日の消費**を明確に示す場合のみ同期し、判別不能なら実サイトのチャージ利用可否判定に委ねる。
- 日付境界付近にクリック/応答がまたがった場合、正しい消費日がサイトから確証できなければ**二重使用を防ぐ保守的な日付**を採用し、未確定として自動リトライしない。実サイトで23:59頃の消費テストは不要（境界試験は合成時計で行う）。

## 3. 不変条件・禁止事項

1. **Batchの候補選定はCatalog-only。** Discovery済み `work_id:chapter_id` を使う。通常Batch/Grant-onlyの事前全作品一覧収集、別話サーフィン、コイン残高ページ巡回をしない。現行の無料 `direct` の厳密な一覧 preflight は維持する。有効episode grantはcanonical `/manga/viewer/<chapterId>` へ直行する。quotaはサイトが「チャージで読む」を対象row選択後にだけ表示するため、Lead承認済みの最小差分としてCatalog選定済みtargetに限った1回のwork page entry→exact row modal→charge controlを使う。quotaを既存「free一覧であることが必須」の条件に通さず、全話Discovery、別話探索、未観測deep linkの生成・直行はしない。
2. **作品ごと最大1候補・1試行。** `quota_scope="work"`, `quota_limit=1`, `quota_commit_mode="after_observed_consumption"` を使用。候補の並び順は既存 Catalog/Discovery を基準にし、1話が不適格でも別の話をliveで順次探索しない。作品Aが終わる前に作品Bへアクセスしない。
3. **チケット以外に触らない。** 正規の無料チャージである確証が必要。メダル/コイン/購入/有償操作、Premium、ログイン代行への暗黙フォールバックは禁止。旧unknown全件を安易にquota扱いしない。
4. **サイト操作は1回だけ。** ユーザーが確認した唯一の消費controlは対象話modalの「チャージで読む」。作品一覧でCatalogが選択した正確な1話だけを開き、正規の課金ゼロ `work_ticket` control、native identity、same-Page observerとdurable `attempting` を束縛してからクリックする。timeout/キャンセル後の再クリック・再gotoは禁止。対象行の選択だけでは消費しない。全話再Discovery、別話探索、未観測 `ticket=true` deep-link直行は禁止。
5. **正の消費証拠が必須。** 公開first-party clientは `/v1/web_manga_viewer_2` と `WebMangaViewer2Request/Response` を結合する。Exact main-frame same-Page POSTのHTTP 200、同じJST日内のrequest→response、exact work/chapter、前状態ticket available、responseのavailable false + charge-needed true + 正確な `0時に回復!` が揃った場合だけ `AccessConsumption(consumed=True, resource="work_ticket", consumed_at=request_started_at, access_granted_until=observed_future_expiry_or_None)` を確定する。Expiryはresponseと同operation fresh React stateの一致がある場合だけ設定し、固定期間を推測しない。表示できた/閲覧可能だっただけでは「今回1枚消費した」証拠としない。消費は確定したがexpiry/後続viewer確認が失敗した場合は、resource consumptionを保持しgrant expiryはNoneとする。時刻跨ぎ/証拠不足はunknownで自動再試行しない。
6. **失敗時の整合性。** チケット消費が確認されたら後段 Viewer/ZIP が失敗してもDBのresource stateとsource grantを保持。消費の成否が不明なら再試行せず「未確認」を報告し、可能性のある消費を安全に再実行できると見なさない。既存 `AccessAttemptObservation` / history guard と整合し、同作品の自動再試行を防ぐ最小実装・テストを行う。
7. **既存画像取得を壊さない。** `_classify_viewer_pages`、先頭1枚/見開き、source-native JPEG→safe PNG fallback、extraページ除外、安定待機、正のEND、ZIP CRC/Manifest/ページ順は維持。quotaは正規入場後**同じ Page**で既存 Viewer 初期化に接続。grant-onlyはページ画像の読み取り/ZIP/Completedをしない。
8. **共有環境と安全。** `AGENTS.md` のCDP共有Chrome、Playwright、AccessGuard、有限retry/pacing、403/429/CAPTCHA stopを維持。ライブ操作担当は一人だけ。認証情報、cookie、画像本文、署名URL、秘密、個人情報はcommitしない。

## 4. 実装フェーズとゲート

### Phase 01 — Repo差分調査、読み取り専用の実サイト観測

**目的:** チャージの正確なUI/消費トリガーと、無表示・無料・コイン表示のrow-local構造を立証する。実サイトでの不用意なチケット消費は禁止。

**起点・参考:** `site_adapters/comicfuz/{discovery.py,adapter.py,README.md}`、`site_policies/comicfuz.py`、`site_policies/{hanayume,younganimal,comicdays}.py`、`site_adapters/{hanayume,younganimal,comicdays}/adapter.py`、`batch/{planner,executor}.py`、`catalog/service.py`、`management/inventory.py`、`tests/unit/test_comicfuz_discovery.py` と既存 ComicFUZ browser tests。

- 作品一覧 `https://comic-fuz.com/manga/<workId>` の、無料/コイン/無表示の**実在する例**を一作品以上で観測。hydration、ID対応、CSS/画像/SVG、読み込み途中・ログイン時の差を確認。新しいマーカーの負の判定を検証。
- viewerの入口、チケット操作の唯一性、日次リセット表示、すでに開放済みの話の閲覧期限（表示があれば）、有償controlとの隔離をread-onlyで調査。チャージ可能な未使用viewerは**遷移だけで消費する可能性があるため、読み取り調査では開かない**。
- チケットの1枚上限・繰越有無、0時（JST）回復のサイト側の表示/動作、手動消費状態の検出可否は事実と未確認事項に分ける。ユーザーから「0時回復」「無表示がチャージ、コインが有料、無料は無料表示」の仕様が伝えられているが、検証対象の画面形状までは推測で確定しない。
- 新旧 ComicFUZ free-only の制約と、共通 `batch` / `grant-only` の実際の候補選択、現在のGUI/CLI次回時刻表示を確認。必要なproduction変更範囲を `PROGRESS.md` に書く。

**Gate 01:** 無副作用の表示分類の証拠、コインを押さない判断条件、消費前後の確認方法・有界retry、時刻基準を記録。クリック/有償アクセスの不明点が残るなら実チケット消費は禁止し、合成fixtureで実装可能な範囲だけ進む。Explorer/read-onlyレビューを行う。

### Phase 02 — Discovery・SitePolicy とCatalog-only plan

**変更候補:** `src/screenshot_crawler/site_adapters/comicfuz/discovery.py`、`src/screenshot_crawler/site_policies/comicfuz.py`、対象 tests、必要ならsite-local小helper。共有DB/Planner変更はまず行わない。

- `_snapshot` で`free`/coin `paid`/正規無表示 `quota` を完全に相互排他的に分類。未知/矛盾/未hydratedは失敗または `unknown`。global display position、`full`/bounded/`incremental`、既存 `external_id` の不変を保証する。
- 開放済み話の正規な期限をサイトから確認できる場合は `DiscoveredSource.access_granted_until` と `access_granted_until_observed` の既存契約に従って更新。正しく期限切れが観測できた場合のみ stale grant をクリアし、観測不能で既存grantを消さない。手動消費のwork日付を推測しない。
- `ComicFuzSitePolicy`: `work_ticket` resource methods、`resource_state_scope("work_ticket") == "work"`、日次リセットの `grant_only_skip_reason` と `grant_only_retry_at` を実装。 `defer_quota_access_to_grant_phase() == False` の通常同一Page経路を優先。
- `evaluate`: `free`→direct、期限内の`quota` grant→direct、未開放`quota`→`work_ticket` quota candidate（work scope/limit1/observed commit）、coin `paid`・unknown・unavailable→SKIP。 `premium_ticket` 明示は拒否。
- work A/B独立、同work複数quotaの1候補、既存 `--limit` / grant-only / `all` 選択・scope同期に不整合がないことを確認。必要な場合のみ最小限のsite-neutral変更を行い、CoreにComicFUZ名をハードコードしない。
- 必須時計テスト: 2026-11-23 09:00消費→23日23:59:59 SKIP/24日00:00:00可、23日23:50消費→24日00:00:00可、24日00:01消費→25日00:00までSKIP。UTC offset入力、日本時間とUTC日付のズレ、naive clock拒否、未来時刻の安全側、設定`cooldown_hours=23`でもルール不変。

**Gate 02:** ローカルSKIPがページ作成/サイト要求**0件**で働くこと、23hベースの他サイトPolicyが不変であること、source期限とwork日次回復が独立であることをUnit/統合テストで確認。実チケット不要。

### Phase 03 — ComicFUZのquota entry、grant-only、既存Viewer継続

**変更候補:** `src/screenshot_crawler/site_adapters/comicfuz/adapter.py`、必要時のみ`site_adapters/comicfuz/live_access.py`、関連 tests。画像取得部分の大規模変更禁止。

- `configure_run` で `auto/direct/quota` を正確に分岐、`configure_quota_resource` は `work_ticket` のみ許可。 `get_access_consumption`、`initialize_entry_only` を実装し、状態をrunごとに初期化。
- `resolve_initial_navigation_url` と `initialize` の「必ず作品一覧へ行き、freeであることを確認」という既存契約を、**無料directでは温存**、quota/有効grantのdirectでは選定済みエピソードへ直行できるよう最小分離。batchの途中に全話一覧preflightを差し挟まない。
- ユーザー確認に従い「チャージで読む」を唯一の消費triggerとする。副作用前にobserverとdurable attemptを設置し、対象`work_id:chapter_id`、正規work page/route、native identity、唯一の可視/有効/ゼロ価格ticket controlを確認する。直接未観測routeへgotoせず、Catalogで選んだ対象行の通常modalを通す。
- Correct first-party bindingは`WebMangaViewer2Request`と`WebMangaViewer2Response`。Requestの `deviceInfo=1`, `useTicket=2`, `consumePoint=3`, `chapterId=4` を厳密検査し、ticket POSTでは`useTicket=true`、Browser device、point free/paid zero、chapter exactを必須にする。Response native fieldsは`manga=11`, `chapterId=12`, `chapter groups=5`; Manga `mangaId=1`, `isTicketAvailable=12`, `isChargeNeeded=13`, `chargeStatus=18`; Chapter `chapterId=1`, `pointConsumption=5`, `endOfRentalPeriod=10`。旧 `/v1/manga_viewer` の似た名前messageを流用しない。
- quota成功後は同じPageから既存のmanifest/page readiness・Viewer/END/ZIPを実行。既存の`_validate_reader_identity`のfree前提を「正しく許可されたチケットの対象話」に限って置き換える。work/chapter/title/manifestの厳密な一致は維持。
- grant-onlyは同じ入場操作・消費確認までで停止。0画像/0ZIP、pending。後日該当episodeの有効grantを使うdirectではチケットクリック0回。期限不明なら勝手にdirect権限を付与しない。
- timeout、click後route不明、viewer遅延、課金controlへ切替、paidしかない、混合/重複control、未ログイン、消費結果不明時は二重操作なし。消費確認後capture/ZIP失敗でもresource stateは残す。

**Gate 03 implementation checkpoint (2026-11-24):** Controller and synthetic normal/entry-only paths are implemented; independent review PASS, BLOCKING=0. Focused tests cover native protobuf decoding, click/no-click, paid request pre-send abort, same-Page latch/duplicate prevention, date-boundary unknown, exact response/React state, expiry mismatch, confirmed consumption after downstream failure/sink error, AccessGuard and grant-only no-image-observer. A full synthetic normal Batch reaches positive END/ZIP, while grant-only persists the confirmed entry with no image observer or artifacts. Gate03 was synthetic/static only; no live charge has been clicked and no real ticket has been consumed. Phase04 listing preflight later revealed a real-runtime listing message nesting detail not represented in the original synthetic fixture; the adapter now binds the exact chapter through the same `webMangaViewerData` referenced by heading and Charge, and the synthetic fixture was updated. See `PROGRESS.md` for exact commands/results, Phase04 correction and evidence limits.

**Gate 03:** browser fixtureで無副作用のfree/paid/blank分類、quotaのクリック0/1、正の消費/不明、entry-only、同Page継続、identity drift、AccessGuard失敗、再試行阻止を検証。コイン購入操作0、重複消費0、通常Batchに余分な作品一覧visit0。

**Phase 04 B implementation status (2026-11-24):** Synthetic-only direct revalidation is implemented behind the existing normal Batch path. The old quota timestamp is a planning hint, not rental authority; the live selected Work row and exact zero-cost viewer response remain the authority. B can end a normal Batch at positive END and ZIP without recording a ticket use or source grant. Current live status remains stopped: Work3152 run4 and Work3342 run5 are unknown/potential uses, and Work3667 remains quarantined. No additional real ticket action was taken for B. Details and limitations are in `PROGRESS.md`.

### Phase 04 — 回帰試験、限定した実サイトE2E、独立監査

1. **静的/自動:** `ruff check src tests`, `git diff --check`、`docs/TEST_STRATEGY.md`に従ったComicFUZ/Policy/Batch Executor/CLI/管理画面の影響テスト。共有部変更時は関連する全サイトの回帰テスト。全pytestを常に必須とはしない。
2. **時刻境界:** 合成時計でJST 23:59:59→00:00:00の判定と、同日/翌日/別作品、settingsの23h上書き無効、ローカルskipのsite request 0、再起動後もwork stateが残ることを確認。実0時を待つ試験は不要。
3. **隔離実環境:** 既存の共有CDP/ログイン状態は使用可だが、実運用DB・Watchlist・output/libraryは変更せず隔離コピーで検証。サイト側の実チケットを使う**最初の操作前にユーザーの明示的許可と消費枚数上限を確認**。実操作は必要最少（目安: 異なる作品の grant-only 1枚 + 通常Batch 1枚）。同時に複数エージェントがブラウザを触らない。
4. **grant-only E2E:** `batch run --site comicfuz --grant-only work_ticket --limit 1`。消費1回、workのlast_consumed_at/sourceの期限（観測可能な場合）、Item pending、画像0/ZIP0を監査。同作品同日再実行はローカルSKIP（Page/HTTP0）、別workは独立。
5. **通常 Batch E2E:** `batch run --site comicfuz --limit 1`。別の未使用workでquota候補1話を開放→**そのPageから**先頭～END→ZIP/Completed、Manifest順、全ページデコード、CRC、hash/size、広告/extra除外を独立確認。既存 free/direct の同等試験も1例確認。可能なら既に手動で開放済みのepisodeを`direct`で再取得しクリック0回を証明する（追加消費不要）。
6. **失敗分岐・報告:** 「消費確認済みだが取得失敗」「消費未確認」「当日消費済み」「サイト側利用不可」「有料のためskip」を分けて記録。作業中断やサイト403/429に対するauto retry禁止。UI/CLI次回時刻、resource stateとsource grantの一致を検査。
7. **レビュー:** Explorerの観測、Implementerのproduction diff、独立ReviewerのBLOCKING、必要なら独立Testerのアーカイブ/DB/リクエスト監査を`PROGRESS.md`に記録。観測に使った実チケットのwork/chapter/現地時刻・枚数を記録（認証情報/画像は記録しない）。

**Gate 04 / Definition of Done:** ①無料/無表示quota/コインpaidを安定識別、②日次00:00 JSTルールを通常Batch/Grant-only/管理表示に反映、③同work同日最大1消費（クリック含む）・別work独立、④grant-only=0枚/ZIP0/pending、⑤通常Batch=同一Pageで正のEND/ZIP/Completed、⑥使用済みepisodeを再消費せずdirect可能（有効権限が観測された場合）、⑦有料操作0・不明時二重試行0、⑧旧無料機能と他サイトの回帰なし。すべての根拠・未解決事項・試験実績が`PROGRESS.md`に揃うまでDONEとしない。実チケット検証が承認されない場合は`synthetic verified / live pending`と明記。

## 5. 更新対象と差分境界

- Production候補: `src/screenshot_crawler/site_adapters/comicfuz/{discovery.py,adapter.py}`, `src/screenshot_crawler/site_policies/comicfuz.py`。必要性が明白な時だけ同サイト小helper。
- Tests: `tests/unit/test_comicfuz_discovery.py`, ComicFUZ adapter/policy/browser/Batch tests、`tests/unit/test_batch_executor.py`, `tests/unit/test_cli.py`、`tests/unit/test_gui_model.py`/management関連（既存テストをまず拡張）。
- Notes/docs: `note/13_comicfuz.md`, `src/screenshot_crawler/site_adapters/comicfuz/README.md`, 共通仕様へ影響した場合だけ対応 `docs/`、本runbookの `PROGRESS.md`。
- **原則変更禁止:** Catalog schema/migration、Core Runner、既存JPEG/PNG capture/role検証、他サイトpolicy、Premium/Coin/Medal処理。必要性が判明した場合は根拠を提出して最小差分をレビュー。
- コミット前に元のworktree/branch/未commit差分を確認し、他エージェントの変更を上書きしない。

## 6. Codexへの実行指示（Runbook起点）

`AGENTS.md`と本README、`runbooks/comicfuz-work-ticket/PROGRESS.md`を読み、最新`main`から専用branchで進める。Phase 01のread-only根拠と未確定事項を記録してから、Phase 02/03を最小差分で実装し、各Gateのテスト・独立レビューを通す。Phase04は合成テストを先に実施し、**実チケットを使用する前だけ**明示許可と上限を確認する。作業の途中結果・失敗・実消費枚数・SHAをPROGRESSに追記し、最終的に変更ファイル、テスト結果、残リスク、実サイト検証済み範囲を報告。0時リセットを23時間ルールへ置き換えたり、無表示を無条件にquotaとしたりしない。

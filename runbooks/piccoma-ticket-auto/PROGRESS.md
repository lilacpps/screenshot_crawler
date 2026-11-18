# Piccoma 3種チケット自動消費 — 進捗・証拠

**Status: 2026-11-19 Work/Binge grant-only revision complete; independent final review PASS / BLOCKING 0. Stage 02 live implementation and the 2026-11-18 default/grant revision remain historical.**
**更新日:** 2026-11-19
**契約:** [README.md](README.md)

## Current revision — grant-only Work and Binge resources (2026-11-19)

**Phase status:** complete; independent final review PASS / BLOCKING 0. No real-site/CDP action or additional ticket use was performed for this revision.

- Normal Batch remains unchanged: `piccoma_ticket_auto` chooses among the three observed free kinds using fresh native state. Grant-only now exposes `work_ticket` (waitfree / ¥0+) followed by `binge_ticket` (binge-free). `--grant-only all` uses the existing ordered resource passes and replans between them. Each pass is bound to its own kinds; no implicit fallback. Multiple episodes remain allowed, subject to live availability, selected targets and existing selected-attempt `--limit`.
- Grant-only confirms target access and persists the grant, then leaves the Item pending. It does not capture pages, package, create an Artifact or complete the Item. A fresh free/grant race remains a durable no-action skip; a fresh grant is persisted before skipping. The obsolete `piccoma_ticket_grant` alias is rejected, while existing Catalog grant/history data is retained.
- Queue compatibility is resource-aware. Normal Piccoma Batch and grant-only `all` / `binge_ticket` requests use the internal exact consent marker in `inputs-v2`; explicit grant-only `work_ticket` can remain v1/false. Old Piccoma `all` requests without the marker are rejected before execution. In mixed-site runs consent applies only to Piccoma; grant-only child CLI namespaces keep `allow_quota_access=False`.
- Targeted/affected validation: **274 distinct passed / 0 failed / 0 skipped**: 254 affected policy/CLI/input/worker/GUI/adapter tests in `work_all_revision/affected1.log`, plus 20 Discovery browser tests in `work_all_revision/discovery1.log`. The 254 selection ran the full `test_piccoma_policy.py`, `test_cli.py`, `test_execution_inputs.py`, `test_execution_worker.py`, `test_gui_execution_inputs.py`, plus the five focused Piccoma adapter nodes listed in `work_all_revision/current_validation.md`. The Work→Binge sequence goes through the real Planner, CLI candidate loop, BatchExecutor and Adapter entry with a synthetic SequenceRunner and reader setup stub; it is not a production CrawlerRunner E2E. A separate representative Work grant-only case uses the actual CrawlerRunner. No duplicate intermediate counts are added.
- First-run diagnostics are retained, not counted as passes: `first_policy_cli.log` recorded 39P/1F because an old test expected the now-supported `work_ticket` resource to be unsupported; validation then reached a secondary error from its uninitialized test Catalog. The test input was changed to the obsolete `piccoma_ticket_grant` alias; no Catalog initialization fix was made; `targeted1.log` recorded 117P/2F because two safe preflight no-action cases expected an access POST even though the resource was known ineligible before that request. The test fixture and assertions were corrected to match the approved fail-closed contract; the superseding affected selection passed. An early adapter collection error and transport fixture failures are also retained as `sequence1.log` and `transport1.log`; details are summarized in `current_validation.md`.
- `ruff check src tests` and `git diff --check` pass. The 2026-11-18 9473-case all-file suite is a prior-revision result only; this site/transport-local revision did not rerun the full suite. Its ticket ledger (4/4), positive live proofs and recovery E2E remain historical and are not new evidence for this revision.

## Previous revision — default normal Batch and restricted grant-only (historical, 2026-11-18)

**Phase status:** complete; final independent review passed with **BLOCKING 0**. The targeted/affected revision selection and final per-file full suite are green. Full-suite outcomes and interrupted-run accounting are recorded below and in ignored `default_and_grant_revision/final_regression_summary.json`.

- Normal Piccoma Batch now admits the three native free ticket kinds by default in candidate order. The public `--piccoma-auto-tickets` flag, GUI checkbox and extra Piccoma-only opt-in dialog were removed. The Run button tooltip explains that free tickets may be used; clicking it queues the job without an execution-confirmation dialog.
- `piccoma_ticket_auto` remains the normal-Batch logical resource. `piccoma_ticket_grant` is a separate grant-only resource that permits waitfree and ¥0+ only, processes multiple episodes subject to fresh stock / selected targets / existing `--limit`, and does not impose a per-Work one-episode limit. Binge-free is rejected before an affirmative action in grant-only.
- Grant-only confirms each target grant, persists it, and leaves the Item pending. It does not capture pages, package, create an Artifact or mark Item complete. A post-plan fresh free/active-grant race is a no-action skip; any fresh grant is persisted before skip, without opening the viewer or attempting a ticket.
- Existing same-Source unresolved-run guard, typed candidate-bound observer, native control/kind/debit checks, access guard, capture/native provenance and normal Batch END/ZIP remain in force. No Core site-name/resource branching or Catalog schema migration was introduced.
- Queue compatibility: GUI Piccoma normal-Batch requests sign the internal exact consent bit in `inputs-v2`; old Piccoma `inputs-v1` and false-bit `inputs-v2` requests are rejected before execution. Mixed-site batches carry the consent only in the Piccoma namespace. Normal multi-site `--limit` is a total crawl-slot cap; grant-only `--limit` caps selected grant attempts. The Worker passes remaining capacity between sites from `candidate_started` events. Deferred normal sites emit candidate starts in both preparation and capture phases, so this conservative accounting preserves the crawl-slot cap but can leave unused capacity; it does not guarantee filling the requested limit. Skips before candidate start and empty plans use no slot; a skip after candidate start does. A failure prevents later sites from starting.
- Synthetic sequential scenarios cover daily A1→A2 secondary→B1 daily, shared ¥0+ 1→0 cross-Work block→fresh refill, and binge Work stock 1→0→fresh UI reset plus account-stock-zero/work-stock-positive block. The last scenario uses normal Batch because grant-only prohibits binge.
- Focused/affected results: adapter fresh-free/fresh-grant race **2 passed**; consolidated affected selection **458 latest-per-node passed / 0 failed / 0 skipped** (the initial 457P/1F run's single stale CLI fake assertion was corrected, then the full `test_cli.py` file passed 114/114; overlapping reruns are not added). `ruff check src tests` and `git diff --check` pass. Exact selection, run accounting and the partial mapping of the first 300P/19F console result are recorded in ignored `output/piccoma_ticket_stage01/default_and_grant_revision/affected_checkpoint.md`; raw output of that initial run was not retained, so it is not represented as a complete 19-node map.
- This revision used **zero** real-site/CDP actions and **zero** additional tickets. Stage 02's 4/4 ticket ledger, live proofs, recovery E2E and 9453/9456 validation remain historical only and are not counted as evidence for this revision.
- Final full-suite result (Lead-owned): latest-per-file accounting is **201 files / 9473 passed / 0 failed / 0 skipped / 0 xfailed / 0 deselected**. Groups: Integration 3292, Research 171, Unit 6010. The raw full aggregate was 9403 passed / 1 failed with the interrupted ComicFUZ file excluded; that file stopped after 55 dots with no case outcomes, and those partial dots are not counted. Whole-file rechecks passed ComicDays 65/65 (31.08s) and ComicFUZ 69/69 (157.34s); these replace their initial per-file outcomes and are not added twice. The initial ComicDays timeout and ComicFUZ stall causes are unknown and did not reproduce in these rechecks; they are not attributed to a baseline defect or a code fix. Combined source/test hash remained `62d5d75b9242e95c1a13aaf7246cde87d232a2b60de053784ca92ad2f30ea3f0`. Independent evidence audit passed with **BLOCKING 0** after verifying all 201 logs, the exact ComicDays/ComicFUZ rerun node sets, hash and latest-per-file count. Evidence: ignored `default_and_grant_revision/final_regression_summary.json`, full raw logs and recheck records. No Piccoma source/test edits were made during the suite.

## 現時点の基準

- Stage 01 の記録は下記に履歴として保持。2026-11-18にユーザーからStage 02実装、必要な実サイト確認、 ticket消費の明示許可を受けた。
- B1/B2/B3とexternal-tracking compatibility sliceの独立code reviewはすべてPASS / BLOCKING 0。live ledgerとテストの最終集計はStage 02最終節に記録する。
- live consumption ledger: 待てば¥0 **2回**、¥0+ **1回**、爆読み **1回**（上限4回、種類別最大2/1/1）。**4/4を使用済み。追加ticket操作はしない。**
- paid/ギフト/広告/時短/ポイント/コインの消費は0。各live試行でaffirmativeは1回。結果不明後の再クリックはしていない。

## Stage 01 — Repo / live read-only Probe

**Status:** 調査終了 / **Gate S1 HOLD**。実サイト証拠の不足を明示して停止する。機能完成・消費経路PASSという意味ではない。

### 実施範囲・再現情報

- 実施日: **2026-11-18 JST**。主なlive観測は06:22〜06:29頃。
- HEAD: `7f9f6852aa36b53bdb7fd4161646d5b48f5af0af`。開始時はcleanな **detached HEAD**。調査と文書更新だけを行い、実装用branchは作成していない。実装指示を受けた将来のStage 02で最新mainから専用branchを作る。
- Lead/root: 実ブラウザの唯一のoperator、証拠の整理と本書・note更新。`site_adapter_explorer`: 独立したコード調査と隔離Catalogの順序再現。`site_adapter_reviewer`: 文書・証拠・設計判断のread-only品質ゲート。
- 既存 `http://127.0.0.1:9222` に共通 `BrowserSession` でCDP接続。新規Pageだけを作成・終了し、remote Chromeや既存タブは閉じていない。Chromeの新規起動・profile選択/設定変更、CrawlerによるCookie/storage stateの取得・exportはしていない。案内表示のサイトJSには表示済みCookieの更新があり、通常のサイト状態更新まで不変とは主張しない。
- ログインは作品ページの `_init_.login === true`、`PCM-stt_login`、一覧のログアウトlinkで確認。認証情報そのものは取得していない。
- ProbeはGET/HEADのみ許可し、viewer・一覧/作品ページ以外へのdocument navigationと非GETを遮断。**話行・読む・購入・時短・広告・ギフト・消費確認ボタンは一切押していない**。操作したのはサイトJSから説明表示だけと確認できた `.js_freeplusModal` / `.js_bingefreeModal` の案内linkのみ。課金/解放APIの直接呼出しなし。
- ローカル再現scriptと非秘密のメタデータはgitignore対象 `output/piccoma_ticket_stage01/` に隔離。`probe_listing.py`、`probe_details.py`、`probe_guides.py`、`listing-*.json`、`home-*.json`、`guide-*.json`。作品画像・Cookie・認証header・token・URL queryは保存していない。サイトの自然なscript responseをローカルで読んだが、repoのfixtureには追加しない。
- 通常Catalog / Watchlist / libraryへwriteしていない。`watchlist.yaml` の既存対象11191・13565・4230、およびユーザーが明示した23222を使用。28600の作品ページも補助確認したが、代表サンプルの全件集計には含めない。

### 確定事項: 既存実装と非消費live観測

**コードの現状（この調査では変更していない）**

| 契約 | HEADで確認した内容 |
| --- | --- |
| Discovery | `discovery.py:46-57,143-171` は厳密な `{waitfree}` / `{waitfree, zeroPlus}` / `{waitfree, bingefree}` のみquota。三重バッジ、未知・矛盾するバッジはunknown。実際の券種・枚数はSourceに保存しない |
| Policy | `site_policies/piccoma.py:16-39` はfreeと期限内の手動grantだけdirect。未解放quotaは`no_active_manual_grant`、表示上pending。paid/unknownは対象外。resource宣言なし |
| Adapter | `adapter.py:372-394,417-527` はauto/directのみ。全一覧の対象行をfresh確認し、free/active manual grantに限りcanonical viewerへ。`/web/viewer/s/` はfresh grant＋同一product/episode時だけ許可。quota activationなし |
| 手動grant | `waitfreeRead`＋`閲覧期限 残りN時間`だけを観測時刻＋`N-1`時間の保守的期限として扱う。72時間の固定加算で入場させない。今回の4一覧には該当行がなく、live再検証はしていない |
| GUI/CLI/Worker | `cli.py:455-509`、`management/execution.py:126-149`、`gui/main_window.py:1173-1275`、`gui/execution_dialog.py:54-56`、`execution_worker.py:47-65,441-470` にPiccoma用opt-inなし。追加するならrequest/検証・fingerprint/確認表示/worker/CLI/実行Policyまで明示伝播が必要 |

**行のidentity・バッジ・分類**

全一覧はHTTP 200、同一productのcanonical、`#js_episodeList` の `PCM-list_asc` class、`a[data-product_id][data-episode_id]` を確認した。保存した全行のproductは一致し、episode IDの重複はない。container数そのものはProbeで数えておらず、単一containerのlive証明とはしない。以下の件数は当日スナップショットであり定数ではない。

| product / 一覧URLのID | 全行 | free | waitfree＋zeroPlus | waitfree＋bingefree | point | 代表episode |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 23222 | 156 | 3 | 122 | 0 | 31 | `896200` = 添付の第2話 騎士団試験 (2)。未解放の2バッジ。free=`896196`、point=`5684737` |
| 11191 | 411 | 5 | 0 | 364 | 42 | `1317630` = 未解放の2バッジ。free=`1317625`、point=`6182144` |
| 13565 | 323 | 3 | 0 | 320 | 0 | `662558` = 未解放の2バッジ、free=`662546` |
| 4230 | 320 | 3 | 0 | 317 | 0 | `882428` = 未解放の2バッジ、free=`882423` |

- 一覧URLは `https://piccoma.com/web/product/{product}/episodes`。代表話のcanonical URLは `https://piccoma.com/web/viewer/{product}/{episode}` と導出できるが、**本Probeでは開いていない**。
- ステータスscopeは各対象行内の `.PCM-epList_status` とその子孫。`PCM-epList_status_waitfree`、`PCM-epList_status_zeroPlus`、`PCM-epList_status_bingefree` は画像アイコンなので可視テキストが空でも存在する。
- 対象行のhrefは`#`、`data-user_access="require"`。freeにも同じ値があり、これだけで有料/未解放/無料を区別できない。DOM indexは現在の一覧内位置であり、episode IDの代わりにしない。
- point行23222は現在21、取消価格73、11191は現在18、取消価格60。還元文言や取消価格で無料扱いしない。既存 `.js_point` による現在価格分類を維持する。
- ユーザーの画像説明と一致し、**話ごとの複数アイコンは利用対象券種を示す**。その券の現在残数・チャージ状態・grantを示す証拠とは分ける。添付2枚目と同じ見出しの行のIDは今回同定しておらず、11191の別の明確な対象行を代表にした。

**作品ページでの券・チャージ表示**

今回 `/episodes` は全行を表示するがチャージ/残数欄がなく、`/web/product/{product}` はチャージ/残数を持つ一方でプレビュー行は **5行だけ** だった。後者だけで対象話の適格性を決めない。両documentのproduct一致と、全一覧の対象行を束縛する設計が必要。

| 券種 | 観測した表示・非秘密field | 判定できた範囲 |
| --- | --- | --- |
| 待てば¥0 | `#js_freeChargeBar.PCM-chargeBar_waitfree` の文字列`チャージ完了`、`data-server_time` / `data-charge_time` / `data-charge_duration`、子`.PCM-chargeBar_bar`の幅100%。23222/11191/13565/4230で完了、durationは82800秒 | 作品ごとの現在のチャージ表示を確認。チャージ中への遷移・回復は未観測。82800秒を固定の利用可否ruleにしない |
| ¥0+券 | 23222の `.PCM-freeplusStatusBar` は`6/6枚（回復済み）｜0枚（プレゼント）`。`_init_.product_home.product_id=23222`, `free_plus_product=true`, `free_plus_ticket=6` | 対象作品上で現在数と定期/プレゼント表示を確認。`.js_freeplusModal`から開いた`.bl_freeplusModal`は配布説明のみ、消費ボタンなし |
| 爆読み¥0券 | 11191/13565/4230の `.PCM-bingefreeStatusBar` は`30/30枚（1作品で使用可能）`。対応productの`bingefree_product=true`, `bingefree_ticket=100`, `bingefree_ticket_limit=30`。`.js_bingefreeModal`の`.bl_bingefreeModal`に保有100枚と週回復・作品制限の案内 | 共通保有数と作品の利用枠を別の表示から確認。今回の各作品では未使用30枠。週途中の消費・上限到達・リセットは未観測 |

重要な落とし穴:

- **対象外作品のresource fieldは0だった**。23222では`bingefree_product=false`かつ`bingefree_ticket=0`、11191では`free_plus_product=false`かつ`free_plus_ticket=0`。これをアカウント全体の残数ゼロと解釈してはいけない。対象flag・product・その場の表示を一致させる。
- 作品homeの`bingefree_ticket_limit=30`は説明文の上限にも使われる。同名の確認response field（後述）が「あとN枚」を表す可能性と混同せず、作品別の**現在残枠**は確認画面/その場の表示で別途証明する。
- 色は補助情報。完了中でもbar親のcomputed backgroundは灰色で、子のfillは100%だった。親のRGBだけ、画像色だけ、固定classだけで消費を許可しない。赤/ピンク→灰色の実遷移は未観測。
- 23222に¥0+提供期限2026-12-27 23:59、11191に爆読み対象区間と2026-11-22 23:59までの告知があった。現在の対象範囲を永続化して期限後も使用可能としない。

### 公式説明・読み込まれたサイトJSと、未確認の境界

公式説明を2026-11-18に再読した:

- [待てば¥0 FAQ](https://piccoma.com/web/faq_detail/115): チャージ1回で1話、通常23時間だがキャンペーンで変わる。
- [¥0+ FAQ](https://piccoma.com/web/faq_detail/195): アカウント共通、対象アイコンの話限定、定期配布とプレゼント分を区別。偶数時刻の配布は遅延し得る。
- [爆読みFAQ](https://piccoma.com/web/faq_detail/197): 待てば¥0を使ってチャージ中になった後に利用。アプリとも残数共通、週回復と作品別上限がある。
- [閲覧期限FAQ](https://piccoma.com/web/faq_detail/80): 閲覧期間中でもキャンペーン終了で有料へ戻る場合がある。

これはユーザー説明の「待てば¥0が最優先、その後は当該話に表示された爆読み/¥0+」と整合する。**¥0+と爆読みの相互優先順位は定めない**。今回両方が付く三重バッジは観測しておらず、既存分類もunknownである。

自然にロードされた `/static/web/js/product_home/pcm_web_product_home_v32.0.js` をpassiveに読んだ。ローカルUTF-8保存のSHA-256は `8990589758bf26a350c58397dff5da723bf802ef4fbabbc5a0bfff0b93d1d351`。以下は**配信JS内の分岐の確認**であり、該当response・確認画面が実際に出たというlive証拠ではない。

| JSの観測 | 実装に使える可能性 / 未確認 |
| --- | --- |
| `data-user_access=require`の行click → `POST /web/user/access`。入力は`product_id, episode_id, referrer_type, current_episode_id` | 通常UIが対象話の利用可否を問い合わせる候補。今回はPOSTを許可せず、行clickもしていない。server側が非消費であること、返却ID/URL・無料性のfieldは未確認。直接APIを呼ぶ実装にはしない |
| status `21000` / `WEB_WAITFREE_READABLE` → `.btn-waitfree` | 待てば¥0の券種別確認ボタンを生成するコード。実際の一意なvisible control・対象話表示・追加消費なしは未確認 |
| status `24000` / `WEB_FREE_PLUS_TICKET_READABLE` → `.btn-free-plus-ticket`、`data.free_plus_ticket`を枚数表示 | ¥0+の確認画面候補。現在数の型/欠落/競合・チャージ中で選ばれることは未確認 |
| status `25000` / `WEB_BINGEFREE_TICKET_READABLE` → `.btn-bingefree-ticket`、`data.bingefree_ticket`と`data.bingefree_ticket_limit`を表示 | 爆読みの保有数/「この作品であとN枚」の候補。server実response・0枠/枠消化後の挙動は未確認 |
| 券種statusから確認UIを作り、肯定操作で`data.redirect_url`または`data.url`へnavigation | 観測コードはserverが券種を選ぶ方式と整合し、3券を自由に選ぶradio/selectは未確認。**URLへ移る操作が消費境界の可能性**。GETであっても安全とは限らないため未操作。返却URLを生のまま保存しない |
| ギフト/SMS/再ログイン/有料/時短/広告には別status/分岐がある。statusによっては直接navigationもある | 未知statusや`status=0`を一律の無料券成功としない。説明モーダルと話の利用確認モーダルも別物 |

サイトJSの `field || 0` のUI fallbackをCrawlerのauthorityにしない。field欠落はUNKNOWN。上記ボタンclassは **selector候補** に留め、production selectorへ昇格させていない。

### 未確認事項・消費許可ゲート

次はすべて未確認であり、自動消費を許可する根拠にしない:

1. 対象行clickのPOSTがserver上でも純粋な検査であること。話ごとの実確認ダイアログ、無料性、返却identityと使用券種をクリック前に同時に束縛できること。
2. 待てば¥0が完了/チャージ中のときの実status切替、¥0+と爆読みの実選択。色が灰色の0枚・作品枠0・補充直後・週境界・他端末使用との競合。対象外作品でfield=0だったことは残数0のテストではない。
3. 実消費responseの枚数・券種・対象話grant・有効期限。正しいviewer URLと初頁ready、消費後Capture失敗/timeoutでも証拠を保存できること。**確認ボタンの存在、残数減少だけ、viewerが開けるだけでは当該券の消費を確定しない**。
4. 今回の代表4一覧にはactive manual grant、unknown、単独waitfreeの行がなく、これらは既存合成fixtureと過去noteの実証範囲に留まる。

将来の1試行は、opt-in＋fresh login＋厳密なproduct/episode/row一意性＋既知quotaバッジ＋当該resourceの正の残数/残枠/チャージ＋券種が明示された正規確認＋課金0＋一意なvisible操作、の**すべて**が揃った場合だけ消費へ進める。取得した券種をクリック前に固定し、その試行では高々1回。別券・ギフト・課金・広告・時短・認証・不明へ誘導されたら押さない。

成功判定は、対象IDに結びつく正の消費証拠とfreshな対象grantを収集し、同じ対象のcanonical/許可済み`/viewer/s/` identityおよび既存reader readyを別途確認する。timestamp/期限の推測やクリック成功だけを`AccessConsumption(True, ...)`へ変換しない。消費不明なら自動再クリック・別券切替を止め、pendingと不確実性を保持する。

**本調査の消費ledger: 待てば¥0=0、¥0+=0、爆読み¥0=0、その他資源=0。** 通常viewer入場0、本文capture0、ZIP作成0、話の利用確認click0。案内モーダル表示だけを実施。消費後検証の許可は得ていないため未実施。

### 実装方針（提案・未実装）とauthority上の判断

1. **1話ずつのsite-owned選択を維持する。** 対象全一覧の行と同じproductの残数/チャージをfreshに結び、native確認で実際の1券種を確定する。ユーザー/公式説明の待てば優先を尊重するが、候補バッジだけで消費券種を決めない。初期検査後の別券fallback、3券種別pass、作品別全話先読みは採用しない。
2. **論理resource案は条件付き。** `piccoma_ticket_auto`を1個のsite-owned選択意図としてPolicy/候補に載せ、`after_observed_consumption`を使用する。実券種`waitfree/zero_plus/binge_free`はclick前に固定し、attempt内に変更しない。`docs/ACCESS_CONTROL_AND_PACING.md:481-510`の明示resource規則との整合はこの束縛が前提。束縛・実消費証明ができなければ案を承認しない。単にresource名をまとめて暗黙fallbackを隠す使い方は禁止。
3. **Plannerの最小拡張が必要。** 現Piccomaの順序はbaseの`catalog`、Catalog Item `ORDER BY id`。Plannerは`quota_scope=work`でdirectをすべて前へ出すだけでなく、`site`でもquota同士をsortしてquota slotへ戻す（`planner.py:318-354,638-691`）。`quota_scope=site`だけでは元のID列を守れない。
   - 隔離fixtureの入力: Item ID順 `[1:quota02, 2:free03, 3:quota01]`、各`order_key=02,03,01`。全件directにした基準はID列`[1,2,3]`、仮の論理resource・site scope・上限なしでも出力は `[3:quota01, 2:free03, 1:quota02]`、work scopeでは`[2,3,1]`。単なる過去noteの推測ではなく、現コードで再現した。再現scriptは `python output/piccoma_ticket_stage01/piccoma_ordering_probe.py`、結果は同directoryの`piccoma_ordering_probe_result.json`。隔離した合成Watchlist keyを選択し、通常データ・実ブラウザを使っていない。
   - 採用方針は **既定を変えないsite-neutralなopt-inの順序契約**。Piccoma ticket modeでは選定済みの同一candidate ID列をdirect/quotaで分離sortせず維持し、`limit`/`selected_keys`/rerun/複数作品でテストする。`quota_limit=1`や定数のlocal残数上限は使わない。
   - 上位 `DISCOVERY_AND_BATCH.md:1847-1877` は現在のquota自然順を仕様化している。したがって将来の拡張時は、この限定opt-inの例外を上位仕様・テスト・Core noteにも明示同期する必要がある。今回は既存仕様を書き換えず、衝突点と最小提案を記録するだけ。
4. **記録は消費とCapture成否を分ける。** 現在の `AccessConsumption` は単一resource、時刻、期限等（`site_adapters/base.py:51-58`）。Executorはcandidateとのresource一致とaware timestampを必須とし、失敗後にも記録する（`executor.py:1348-1435`）。論理resourceは既存Source grant/消費時刻保存を流用し、Catalog schemaを先に増やさない。実券種・操作前の根拠・消費確認/不明は安全なper-attempt出力に必要。既存APIだけで失敗時もdurableに残せるかを詰め、必要なら最小のsite-neutral metadataを別途設計する。
5. **scopeの違うquotaをlocalに一枚と数えない。** 待てばは作品単位、¥0+はaccount共通、爆読みはaccount＋作品枠。現在の生残数をCatalogの固定上限や72時間grantから逆算しない。再試行のために必要な話単位grantと消費不明の記録を優先し、可否はその都度のlive状態で再確認する。
6. **既定OFFを実行まで伝播。** 将来の通常Piccoma `batch run`のみ明示opt-in。CLI誤site/`batch plan`/`grant-only`は拒否、GUIは既定OFFと「実券を消費し得る」確認を設け、request/fingerprint/worker/Policy/Adapterの各境界で検証する。既存direct、Coreのsite非依存、capture/source-native/lossless WebP/PNG fallback/END/ZIPの契約は維持する。

最小代替案は **現在のfree/手動grantのdirect運用を継続**し、消費経路をすべて無効に保つこと。実確認画面と消費証拠が不足する状態で、waitfreeだけ・画像がピンクの券だけを先に有効化しない。候補順を犠牲にする3-pass案も採用しない。

### 基準テスト・検証結果

production/testファイルの変更はなく、既存fixtureを基準検証した。全て外部サイト非依存・隔離Catalog。**最終検証はすべてtask-localの `$env:PYTHONPATH=(Resolve-Path -LiteralPath src).Path` を設定**し、packageと`batch.executor`の`__file__`がこのworktree内であることを確認した。

| 実行 | 結果 |
| --- | --- |
| `python -m pytest -q tests/unit/test_piccoma_policy.py tests/unit/test_piccoma_discovery.py tests/unit/test_batch.py tests/unit/test_batch_executor.py tests/unit/test_batch_selected_keys.py --basetemp="$env:TEMP\pc-s1-local-unit" --tb=short` | **270 passed / 0 skipped**, 919 warnings、74.41秒。分類・direct/manual grant・Planner・選択key・消費記録/失敗保存の既存契約 |
| `python -m pytest -q tests/integration/test_piccoma_adapter_browser.py -k 'auto_preflight or stale_nonfree or malformed_grant or manual_grant_redirect or wrong_composite or quota_strategy or batch_executor_captures or batch_failures' --basetemp="$env:TEMP\pc-s1-local-browser" --tb=short` | **20 passed / 334 deselected / 0 skipped**, 5 warnings、22.29秒。free/manual grant、期限/identity拒否、quota拒否、Batch→END/manifest/ZIP/Catalogと失敗時非更新を含む |
| 隔離Catalog順序Probe（worktreeの`src`をscript内でも固定） | 元のquota ID列がsortで入れ替わることを再現。結果の`planner_module_path`も当worktreeを確認。これは将来の順序保持の受け入れテストをPASSしたという意味ではない |
| ローカル3本のlive Probe scriptに`python -m py_compile` | **PASS**。import参照先をworktreeの`src`へ固定。補助scriptの変更後に再度live操作はしていない |
| `python -m ruff check src tests` | **PASS / All checks passed** |

最終的に選択した既存case **290件が通過**（270＋20）。skipped **0**、browser群の334件は選択外。warningは既存pytest-asyncioのevent-loop-policy非推奨警告。ログは`output/piccoma_ticket_stage01/local-unit-tests.log`と`local-browser-tests.log`。

初回検証の切り分けも残す: 共有venvのeditable installが親main checkoutをimportしていたため、初回のPolicy/Discovery108pass、Batch161pass/1fail、browser18pass/2failと短TEMPへの再試行は**最終HEAD検証に数えず**、上記290件を当worktreeで一括し直した。217個のapplication Python fileを比較すると、58個のbyte差（主に改行）があり、UTF-8の改行正規化後のtext差は対象外の`site_adapters/yanmaga/discovery.py`だけだった。liveで使用したBrowserSession/auth helperのtextは一致するため、表示観測のための追加live再操作は不要と判断した。比較の詳細は`source_provenance.json`。初回Batchの診断file未生成とbrowserの`.manifest.json.tmp`作成失敗は長いworkspace pathで起き、短いTEMP pathでは当worktreeの全対象が通過した。production修正はしていない。

Probeの時刻出力ではWindowsのtzdata欠落に一度遭遇し、ローカル診断だけ固定JST offsetに直して完了。アプリ依存関係の変更なし。初期の `work/` 診断はその後gitignore対象 `output/piccoma_ticket_stage01/` に移動した。`git diff --check`もPASS。

未実行: full pytest、全Piccoma native capture/browser/Discovery integration、GUI/CLI/Workerの広域回帰、既存Research suite。理由はStage 01が調査・文書のみでproduction contract変更がなく、今回はdirect/manual grant・分類・順序・消費記録の基準に絞ったため。**実消費後のLive/E2Eは追加許可がなく未実行**。券切れ・補充・週境界・新opt-inのfixtureは未実装であり、既存290件の成功で代替しない。

### 独立レビューとGate S1

- 独立 `site_adapter_reviewer` の最終判定: **Stage 01成果物はPASS / BLOCKING 0**。実diff、4一覧の件数/ID、案内表示、JS hash、順序Probe、worktree固定の270＋20テストログとauthorityをread-onlyで確認。import参照先・単一containerの過剰表現・Cookie状態の表現を修正して解消した。Reviewerの実ブラウザ操作・消費・file編集は0。これは下記Gate S1の消費経路を承認した判定ではない。
- 調査の結論: UIは対象券種と現在の資源状態を別に表示し、配信JSには券種別確認の分岐がある。1話単位方式の設計候補はあるが、**実確認画面・非消費検査境界・消費後の正の証拠はまだ揃わない**。
- **Gate S1 = HOLD（3種すべての消費経路を未承認）**。適格表示とPlanner対応方針は整理したが、「確定券種・安全な1回操作・正の消費成功判定」をliveで説明し切れない。Stage 02 **NOT STARTED**のまま停止する。

## Stage 02 — 実装 / テスト / GUI

**Status:** Stage 02 complete; final independent Reviewer Gate S2 PASS / BLOCKING 0. Full 201-file suite: 9453 passed; three later-added synthetic sequential cases passed separately (9456 unique validations).

### Stage 02A — live証拠と現在のGate

- 実行branch: `feat/piccoma-ticket-auto`。Stage 01の未commit `note/09_piccoma.md` / `PROGRESS.md` を保持したまま、rootがlocal mainから作成した専用branch上で継続。commitは行わない。
- 操作者: shared Crawler ChromeのCDPへ `BrowserSession` で接続し、所有Page 1枚だけを使用。cookie/storage export、Chrome起動、別タブ操作なし。診断script/evidenceはgitignore対象 `output/piccoma_ticket_stage01/` に隔離。
- Stage 02の総消費上限: **4回以下**。内訳上限は待てば¥0 **2回**、¥0+ **1回**、爆読み¥0 **1回**。有料/ギフト/広告/時短/ポイント/コインは0。各試行でaffirmative操作は1回のみ、結果不明時の再試行なし。
- 実消費済み（後続のStage 02 live proofを含む最終ledger）: 待てば¥0 **2回**（`23222:896200`, `11191:1317630`）、¥0+ **1回**（`23222:896199`）、爆読み¥0 **1回**（`11191:1317631`）。合計 **4/4**、種類別上限も到達。課金/購入操作は0。
- 保存した安全な証拠: `output/piccoma_ticket_stage01/stage02a_waitfree_live_evidence.json`, `stage02a_waitfree_11191_evidence.json`, `stage02a_zero_plus_confirmation.json`, `stage02a_binge_confirmation.json`。応答body/URL query/signed viewer URL/cookie/tokenは保存していない。
- 事前確認はログイン表示あり、row ID `23222:896200` が一意で `user_access=require`、waitfree+¥0+ icon。`/web/user/access` POSTは同一 product/episode IDをbody fieldsに含み、200 JSON status `21000`。1個だけのvisible modalは `待てば¥0` の確認で、enabled affirmative `.btn-waitfree` と `キャンセル` の2ボタン。
- 1回クリック後の正の証拠: 同一IDのfresh rowに `PCM-epList_status_waitfreeRead` と `閲覧期限 残り71時間`。dailyは `チャージ完了` から `あと22時間59分` へ変化。¥0+残数は `6/6枚` のまま。既存Direct adapter initializeは同一IDのreader readyと20ページを確認。事後にprobeがlisting-only access extractorをviewer上で呼んで `UnknownPageStateError` を得たが、初期化成功後の診断scriptの呼び順誤りであり、grantはfresh listing rowで独立に確認済み。
- ZeroPlus positive proof: exact target row `23222:896199`, one affirmative, one `attempting` + one `confirmed` event for kind `zero_plus`; fresh poststate shows same-target `waitfreeRead`, grant persisted, and balance 6/6->5/6. The normal Batch used `--max-pages 1` and stopped after one page with `MaxPagesExceededError`; the isolated default-off direct recovery is recorded below. The later isolated default-off direct recovery reached END and produced a clean ZIP without another ticket action; details below.
- binge live positive proof（取消のみの新preflightは履歴）: fresh homeはdaily残り19時間21分、作品枠30/30。`11191:1317631` のunique waitfree+binge row、eligibility POST/200/status25000、unique native modalの保有爆読み100枚/同作品30枚、`.btn-bingefree-ticket` を確認して事前probeではCancel。最終実行でaffirmativeは1回だけ。JSONLは同一sourceの`attempting`/`confirmed`各1件、post-stateで同一target `waitfreeRead` と作品枠 `30/30→29/30`。Account-wide残数のdeltaは未確認で主張しない。通常Batchは13ページでENDし、13件のWebP ZIPが作られ、`ZipFile.testzip()` は`None`。
- 新しい初期確認から、待てば¥0は作品ごとに別カウントであることを観測（23222はcharge中、11191はcharge完了）。従来の「accountごとに1日1枚」とする仮説は棄却。zeroPlusは別のaccount残数として表示。爆読みは作品別週上限表示を伴う。Site Policyはこの異なるscopeを合算しない。
- 現時点のlive Gate: 3券種すべてでnative flow、1回操作、same-target grantを実証。waitfreeは2回のdaily change、zeroPlusは6→5、bingeは作品枠30→29。total 4/4を使用済みで、これ以上のticket redemptionはしない。positive live proofはcaptureの全種完了を意味しない（zeroPlusは1ページcapで停止）。

### Stage 02B — 実装スライスと独立レビュー

- Policy / PlannerのB1 sliceは、候補ID列の保持と同一Sourceに残る全ての不確実な過去quota CrawlRunによる再消費holdを実装。新Catalog schemaなし。独立reviewは **BLOCKING 0**。
- Adapter / executorのB2 entry sliceはnative status 21000/24000/25000を1話ごとに扱い、fresh listing/home state、ログイン状態、1件のtarget-bound eligibility request/response、unique modalと同一ticket control、affirmative直前DOM再検証を要求。所有Page/popup treeの危険なnavigationとmutating requestを遮断し、未確認結果を再クリックしない。独立安全reviewは **BLOCKING 0**。
- Stage 02前半のread-only evidenceでは、23222:896200と11191:1317630のgrant rowとnormal viewport準備後のreader readinessを確認。消費前のproduct homeは23222 daily充電中/+0 6、11191 daily充電中/作品枠30/30、rendered binge account count 100。後続live poststateではbinge作品枠30→29を確認したが、account-wide 100→99は未確認であり主張しない。
- ticket flow fixtureで日次/¥0+/爆読みの正確な選択とpost-state、残数変化、unknown/modal改変/paid copy/購入redirect/mutating request/observer失敗/二重eligibilityを検査。route cleanup時にclosed owner Pageでpage unrouteが失敗してもContext routeを取り外す回帰を追加。
- CLIは `batch run --site piccoma --piccoma-auto-tickets` のみopt-in。通常はOFF、plan/他site/grant-onlyは拒否。GUIの `無料チケットを自動使用` はPiccoma-only通常Batchだけ表示し、同意確認は既定No。Workerはexact boolとinputs-v2 fingerprintを再検証し、旧inputs-v1/legacyは従来通りfalseのみ許可。
- attemptはnormal Batch metrics JSONLにcandidate identity・論理resource・具体kind・attempt状態を記録。capture失敗後も結果が残るようにする。`inputs-v1` fingerprintは変更しない。
- 最初の7-node regression run **7 passed / 0 skipped**。その後のaffected/full suite結果は下の最終集計を参照。`ruff check src tests` と `git diff --check` はPASS。
- 3券種のpositive post-consume proofと、追加消費なしのisolated direct-recovery E2Eは完了。種類別/総live budgetはすべて使い切った。
- B3独立code review最終判定: **PASS / BLOCKING 0**。対象61 tests / 0 skipに加え、reviewerがExecutor observerの4 in-process probeを独立実行し、valid JSONL persistence・wrong identity拒否・sink欠落/失敗でclick前停止・実行終了後のstale callback拒否を確認。独立probeはコードを変更していない。
- B3 reviewで追加probeしたobserver境界は `tests/unit/test_batch_executor.py::test_executor_scopes_and_persists_access_attempt_observer` とCLI metrics testで永続回帰化した。Valid/wrong identity、sink欠落/失敗のclick前停止、candidate終了後stale callback、JSONL保存をカバーする。
- B3後の調整: closed Pageの`page.unroute`失敗時にも所有Context routeをunrouteするようcleanup順序を修正し、回帰testを追加。GUIの明示同意文言を日本語へ。normal CLI Batchでplanner opt-in、executor flag、metrics sink→JSONL kind記録がつながるtestを追加。これらの変更後のfocused suiteは7 passed / 0 skipped、ruffとdiff checkも再度PASS。後続のaffected/full resultsは最終節に記録した。

### Stage 02B — 初回 opt-in 実装の判断履歴（superseded）

以下のdefault-OFF / CLI flag / GUI checkbox / grant-only非対応の判断はStage 02当時の履歴である。2026-11-18のdefault/grant revisionで置き換えられ、当時の置換先はこのファイル上部のWork/Binge revisionおよびRunbook README §5を参照。

- Opt-inはdefault OFF、通常Piccoma `batch run` のみ。`batch plan` / 他サイト / `grant-only` / 複数サイト混在では受け付けない。GUI側は実際のBatch開始画面にcheckboxと「無料ticketを消費し得る」明示確認を設置し、default OFFとする。
- Site Policy上は単一論理resource `piccoma_ticket_auto` を使う。native UIでクリック前に確定した実券種はmetrics/per-attempt evidenceに別記し、attempt内で別券へfallbackしない。free/active grant はFresh listing後にdirect。unknown/paid/gift/ad/time-saving/ambiguousは停止。
- Piccomaだけ、選定済み候補の元ID列をquota sort/direct-quota pool再配置で変えないsite-neutral opt-in ordering contractを追加。`quota_limit=1`やlocal quota枚数を設定しない。既定の他Policy orderingは変えない。
- uncertain/restarted quota attemptはCatalog `CrawlRun` をwrite-ahead sentinelとして扱う。Piccoma Policyは同一Sourceの全過去quota runを確認し、active grant/fresh discovery grantならdirectを許し、失敗/実行中/unknown runがあれば次回消費を保守的にhold。唯一の確定no-action errorは専用型で記録する。新Catalog schemaは増やさない。
- GUI request booleanはexact bool検証付き `inputs-v2` fingerprintに含める。既存 `inputs-v1` / legacy hashを変えず、旧versionでtrueまたは型不正を拒否する。Workerはaction/site/selectionを実行時にも検査する。
- Post-B3 broad affected regression passed 560 tests. Observer contracts are covered by Executor/CLI regression tests. Positive live proof for all three kinds and the zeroPlus direct-recovery E2E are complete; the final all-file pytest passed. Final independent Reviewer Gate S2 passed with BLOCKING 0; Stage 02 is complete.

### チェック項目

- [x] CLI・GUIで明示opt-in、既定OFF、誤site/誤actionで拒否（transport/GUI focused tests）
- [x] free / manual grant のdirect処理に回帰なし（isolated zeroPlus既存grant recovery + full suite）
- [x] quota対象話の厳密なfresh判定。3種それぞれ本人アカウントで利用可能か確認し、同一target grantとdaily/残数変化を記録
- [x] 1話ずつのcrawl順維持（candidate sequence fixture / B1 review、all-file suite）
- [x] 1試行・対象話・1券種・1回操作のsynthetic guard。UNKNOWN/有料/他resourceへ自動fallbackしない
- [x] 消費確定とCapture成功を別記録。zeroPlusのcapture上限失敗後もgrant/debitをmetrics/Catalogへ保持し、再消費せずdirect recoveryへ回す
- [x] Same-target viewer -> Capture/END/ZIP: binge captured 13 pages; zeroPlus completed 20 pages through default-off direct recovery using its existing grant.
- [ ] 残数0、作品上限、週境界、途中配布、同作品複数話、同時に複数券適用可のlive境界は未確認（既知の未検証範囲。固定のローカル残数をavailability authorityにしない）
- [x] Sequential synthetic transitions: per-work waitfree -> secondary -> independent daily; shared zero-plus 1 -> 0 cross-work block -> fresh refill retry; binge work 1 -> 0 block -> UI reset to 30 retry; account 0/work 30 block. Actual Planner/CLI candidate loop/BatchExecutor/Adapter.initialize; no live depletion/refill/weekly-boundary claim.
- [x] 既存Piccoma unit/browser integration + Batch/CLI/GUI/Worker affected tests（560 passed、external-tracker slice 14 passed、all 201 files 9453 passed in the full suite; 3 unique sequential cases later passed separately (9456 unique validations)）
- [x] 共有コード変更に対する他サイトの回帰（全201 test filesを実行）
- [x] `ruff check src tests` と `git diff --check`。full suiteも全件PASS
- [x] note/09_piccoma.md / Adapter README・共通noteとのStage 02同期
- [x] Final independent Reviewer Gate S2: PASS / BLOCKING 0; Stage 02 complete. B1/B2/B3 and compatibility reviews also passed. Live ledger is 4/4; the 201-file full suite passed.

### 実装結果（2026-11-18 最終検証）

- 実装branch: `feat/piccoma-ticket-auto`（未commit）
- 採用判断: 1つの論理resource `piccoma_ticket_auto`＋native live-selected concrete kind。B1はcandidate sequence保持とCrawlRun履歴guard、B2はstrict native confirmationとowned Page mutation/navigation guard、B3はCLI/GUI/Worker/fingerprint/metrics伝播。追加Catalog schemaなし。3券種positive live proofを確認したが、ticket actionは既定OFFのままとする。
- 変更コード: `src/screenshot_crawler/batch/{planner.py,executor.py,metrics.py}`, `src/screenshot_crawler/site_policies/{base.py,piccoma.py}`, `src/screenshot_crawler/site_adapters/{base.py,piccoma/adapter.py,piccoma/discovery.py,piccoma/live_access.py}`, `src/screenshot_crawler/{cli.py,execution_worker.py,gui/main_window.py,management/execution.py}`。
- Changed tests: `tests/unit/{test_batch_executor.py,test_cli.py,test_execution_inputs.py,test_piccoma_discovery.py,test_piccoma_live_access.py,test_piccoma_policy.py,test_runtime_settings.py}`, `tests/integration/{test_gui_execution_inputs.py,test_piccoma_adapter_browser.py,test_piccoma_discovery_browser.py}`.
- Changed docs/notes: this Progress file and Runbook README; `note/00_core.md`, `note/09_piccoma.md`, Site Adapter README; `docs/ARCHITECTURE.md`, `docs/DISCOVERY_AND_BATCH.md`, `docs/ACCESS_CONTROL_AND_PACING.md`, `docs/ACCESS_CONTROL_AND_PACING_PLAN.md`, `docs/GUI_README.md`, `docs/GUI_INVENTORY.md`.
- Fixture/transport: B3 reviewer selected61 passed / 0 skippedと4つのin-process observer probeをPASS。B3後focused CLI/GUI/cleanup suite 7 passed / 0 skipped。external-tracker compatibility slice 14 passed / 0 skipped。先行affected Piccoma/CLI/GUI/Worker suite 560 passed / 0 failed / 5 warnings。最終ruffもPASS。
- Live: 待てば¥0 2/2、¥0+ 1/1、爆読み1/1の計4/4。対象episodeは `23222:896200`, `11191:1317630`, `23222:896199`, `11191:1317631`。各ticketを一度だけクリックし、同一targetの`waitfreeRead` grant確認。daily charge変化、zeroPlus6→5、binge work slots30→29を確認。binge normal Batchは13 pages/END/valid ZIP。zeroPlusはmax_pages=1の意図した上限で停止した後もgrant/debitを維持。
- Final full pytest: 201 files, **9453 passed / 0 failed / 0 skipped / 0 xfailed / 0 deselected**. Group totals: Integration 53 files / 3283 passed; Research 21 files / 171 passed; Unit 127 files / 5999 passed. Three sequential synthetic cases then passed in a focused run, for 9456 distinct validations; the full suite itself remains 9453. 3 stale test expectations were corrected (Piccoma supported capability vs grant-only, Yanmaga `work_ticket`, and configured BookWalker page-turn delay 0); unchanged production/configuration was not modified. The affected files were rerun for a combined latest-per-file replacement of 154 passes, not added twice to the total.
- Binge account-wide balance 100→99 was not observed. Both live ZIPs passed CRC, member count, WebP decode and hash checks, but normal packaging removed the manifest, so per-page source-native provenance was not independently rechecked. No more ticket actions are allowed.
- Reviewer: B1/B2/B3, external compatibility, and final Stage 02 Gate S2 all PASS / BLOCKING 0.
- Stage 02 implementation, full suite, and final review: **PASS / BLOCKING 0**.

### Stage 02B — 最終互換性診断と回帰チェックポイント（2026-11-18）

- Historical ledger at the time of the Cancel-only compatibility diagnostic was waitfree 2, zeroPlus 0, binge 0 (2/4). The subsequent final live proof below brought the authorized total to 4/4.
- zeroPlusの通常Batch試行と、その後の別Catalogを使った明示的な調査試行は、どちらも対象話 `23222:896199` のクリック前に `UnknownPageStateError` で停止した。`access_attempt` eventはなく、CrawlRunの結果とSourceの `quota_started_at=NULL` / grant未変更から、affirmative操作未到達を確認した。元の失敗runは保持し、同一Sourceを再試行していない。根拠は `output/piccoma_ticket_stage01/zero-plus.sqlite` と `output/piccoma_ticket_stage01/trial-zero-plus-retry/catalog.sqlite`、および各metrics JSONL。最初の通常Batch metricsはリポジトリcwdの `output/metrics/20261118T102003716035+0900-piccoma-normal-cbda39ae1afd491e8317b611cb888341.jsonl` に出力された。2回目は隔離先 `output/piccoma_ticket_stage01/trial-zero-plus-retry/output/metrics/20261118T102848800436+0900-piccoma-normal-80c6abc93a374735a1ceb9bb9aaced0c.jsonl`。後者もticket attempt eventなし。誤った改行のみのenv fileは事前run setup失敗後に取り除き、サイト操作は起きていない。
- Leadが許可したbounded normal-Batch相当のCancel-only診断で、対象 `23222:896199` のnative row clickからmodalを出す前に、Piccoma外のanalytics POSTが2件先行する実順序を確認した。これらはguardにより送信前に遮断されたが、従来のguardは遮断した全mutating requestを `eligibility_invalid` として扱い、後続する正しい `/web/user/access` POSTを無効化していた。合成サイトfixtureでは異なる `current_episode_id` でも、厳密な `product_id` と `episode_id` が一致すれば、既存matcherが対象要求として受理していた。したがって観測されたcurrent episode値の不一致は**非因果**であり、matcher仕様変更はしていない。
- Sanitized live evidenceは `output/piccoma_ticket_stage01/trial-zero-plus-diagnostic/sanitized_live_diagnostic.json`。記録したのはorigin/path（query除去）、method/resource type、content type/byte count、allowlist済field名とtarget ID match boolean、response status/native statusだけ。request body、headers、Cookie、signed URLは保存していない。Cancelのみのためserver-side access確認/消費はない。
- 最小互換性修正では、Piccoma外のmutating requestと外部tracking subframe navigationは引き続き遮断する一方、これらの遮断をtarget eligibility判定の失敗として数えない。Piccoma first-partyの予期しない/誤った/重複mutating request、main-frame外部navigation、同一originの購入iframeなどは引き続きfatalかつfail-closed。外部host allowlistや遮断requestのfallbackは追加していない。
- 追加focused regressionは **14 passed / 0 failed / 0 skipped**、pytest-asyncio deprecation warning 5件、8.87秒。対象: `tests/unit/test_piccoma_live_access.py`; browser側のbinary POST body non-read、waitfree/zeroPlus/binge native entry、今回のnormal Core Batch経路で外部POST＋tracking iframe POSTを正しいtarget eligibilityより先に発生させるcase（1 ticket click、grant、END、ZIPまで）、unbound requestとsame-origin purchase POST拒否。`PYTHONPATH` はworktree `src`、pytest basetempは短い `$env:TEMP\pc2u`。
- 独立reviewへ渡すためproduction/test差分をfreezeした。レビュー対象は今回変更のPiccoma `adapter.py` / `live_access.py` と `test_piccoma_adapter_browser.py` / `test_piccoma_live_access.py`、既存B1-B3との差分全体。追加live redemptionsはこのreview/Lead gate完了まで保留。
- 上位Batch noteのpost-entry記述を同期し、Pageをviewerからnavigationさせず、bounded same-origin GETをdetached documentへparseしてhome stateを読む現行方式を明記した。

### Stage 02 — 最終live券種proofとdirect-recovery E2E（2026-11-18）

- Live ticket ledgerは **waitfree 2/2、zeroPlus 1/1、binge-free 1/1、総数4/4**。許可された消費枠をすべて使用済み。以後の確認はread-onlyまたは既存grantのdirect accessだけとし、ticket actionを追加しない。
- ¥0+の通常Batchはfresh isolated Catalog/Watchlist `output/piccoma_ticket_stage01/approved-final-live/zero-plus.sqlite` / `zero-plus-watchlist.yaml` で実行。keyは `stage02-zero-plus-23222-896199`、Source ID 1、external ID `23222:896199`。CLIに `--piccoma-auto-tickets --limit 1 --max-pages 1` を付けた。metrics `output/metrics/20261118T105112455238+0900-piccoma-normal-f10c5050bc7a4f1bb551f89d94b0d07d.jsonl` に同じsource/resourceの `attempting` と `confirmed`, kind `zero_plus` が各1件。Catalogには `quota_started_at=2026-11-18T10:51:16.969269+09:00` と期限 `2026-11-21T09:51:15.508968+09:00` を保存。CLIは1ページ後に指定上限で `MaxPagesExceededError` となり、1ページcapture後のZIPはない。再実行・再消費はしていない。
- ¥0+のfresh read-only poststate `output/piccoma_ticket_stage01/approved-final-live/zero-plus-poststate.json` は、logged-in、product/episode ID一致、一意な `waitfreeRead` row、有効grant期限、home product ID `23222`、残数 `5/6枚`、daily charge中を記録。クリック前のpreflightは同じ対象でstatus24000と保有6枚、Cancel-onlyだった。したがって現live証拠は1消費と6→5、同一話grantを束縛する。
- 爆読みは新しい隔離Catalog/Watchlist `output/piccoma_ticket_stage01/approved-final-live/binge.sqlite` / `binge-watchlist.yaml`、key `stage02-binge-11191-1317631`、Source ID 1でnormal Batchを実行。fresh preflight artifact `binge-preflight-cancel.json` はstatus25000、唯一のwaitfree+binge row、ログイン/home daily charge中、作品枠30/30、保有100、unique enabled `.btn-bingefree-ticket` とCancelを記録（affirmative 0、Cancel 1）。その後のCLI opt-in実行でaffirmativeは1回のみ。metrics `approved-final-live/output/metrics/20261118T105437227166+0900-piccoma-normal-c0f6149a8d4448d99b0c270ab3c6b781.jsonl` に同じsourceの `attempting` / `confirmed`, kind `binge_free` が各1件。
- 爆読みのfresh poststate `binge-poststate.json` は同じ `11191:1317631` の `waitfreeRead` row、ログイン状態、作品枠 `29/30枚` を記録。Catalog grant期限は `2026-11-21T08:54:40.286599+09:00`。Runはsucceeded / END / 13 pages。ZIP `approved-final-live/binge-library/manga/爆読み live proof/爆読み live proof-Episode 1317631.zip` は13 WebP memberで、`ZipFile.testzip()` は `None`。Account-wide binge残数の変化は未観測であり、100→99とは主張しない。
- waitfree live positive evidenceは従前の `stage02a_waitfree_live_evidence.json` と `stage02a_waitfree_11191_evidence.json`。対象 `23222:896200` / `11191:1317630` を各1回操作し、同一target `waitfreeRead` grantと各作品のdaily charge変化を確認済み。total ledgerはこの2件に今回のzeroPlus/binge各1件を加えた4。
- Independent zeroPlus recovery completed on a backup Catalog copy: `output/piccoma_ticket_stage01/independent_e2e/trial-zero-plus-recovery/independent_validation.json`. The plan selected 1 direct candidate / 0 quota candidates. Failed quota Run 1 remains unchanged; direct Run 2 reached END after 20 pages. `quota_started_at` and `access_granted_until` exactly match pre-recovery values, and metrics contain 0 access-attempt events. The ZIP has 20 ordered WebP members, all VP8L lossless at 1350x1920, CRC clean, SHA-256 `872ff2f21befa0bd5ebcecbf3880f23fb15991c6bbbc4756e6cf4e5f000b581e`. Binge audit reports all 13 members VP8L lossless at 1125x1600, CRC clean, SHA-256 `b259594a5e85844b1fa716f08e54d517c0e764e14f0c2c18b3e458dc86f31ffb`. Normal packaging removed run manifests, so native-source provenance was not independently proved for either ZIP.
- 外部tracingの互換性修正後focused regression: **14 passed / 0 failed / 0 skipped**。これにはsynthetic normal Core Batchのexternal POST＋tracking iframe POSTをvalid eligibilityより前に遮断しつつ、異なるcurrent_episode contextでも厳密target bodyを受理し、zeroPlus 1回→same-target grant→END→ZIPへ進むケースを含む。既存のunbound target / same-origin paid POST拒否と3 native kind testsも通過した。
- Direct-recovery E2Eは独立Testerのisolated copyでPASS。full-suiteの中断/代替実行と最終集計は次節に記録する。

### Post-full-suite sequential synthetic regression (2026-11-18)

- `tests/integration/test_piccoma_adapter_browser.py::test_piccoma_batch_rechecks_ticket_state_for_sequential_candidates`: **3 passed / 378 deselected / 5 existing deprecation warnings / 5.54s**. The test uses the production Planner, CLI candidate loop, BatchExecutor, and Piccoma adapter entry; only the reader capture loop is stubbed.
- Scenarios: per-work daily ticket followed by secondary ticket and another work's daily ticket; shared zero-plus depletion across works then a fresh refill retry; binge work stock depletion, fresh UI reset to 30 permitting retry, and account stock 0/work stock 30 blocking. Clicks are counted via a Python-exposed button-click binding and viewer GETs independently; exact listing/home paths and target IDs are asserted. No calendar reset logic is modeled.
- The all-201-file suite remains **9453 passed**; these are 3 new post-suite cases, for **9456 unique validated cases**. The affected ticket-helper slice passed **27 passed / 354 deselected**; its rerun is not added to the full-suite total. Exact commands and helper caller map: `output/piccoma_ticket_stage01/sequential_test_coverage.md`. The live daily/shared-stock/refill/weekly-reset boundaries on the real site remain unverified.

### Full pytest 実行記録（Lead管理、2026-11-18）

- 最初のmonolithic full run（root session `5958`）は約19分33秒後に中断された。直近10分以上 `ComicFUZ` integration fileで進捗せず、終了直前までの569 outcomesには `tests/integration/test_comicfuz_adapter_browser.py::test_comicfuz_runner_crawls_verified_spreads_to_positive_end` 1 failureがあった。tracebackはhang前に生成されず、この中断runは**成功にもskipにも数えない**。共有Chromeには触れず、Leadが所有するtest treeだけを停止した。
- 同じ遅い100msケースを独立fresh processで再実行したところ **2 passed / 0 skipped / 5 warnings, 2.53秒**。さらにComicFUZ全fileはfresh processで **69 passed / 0 skipped / 5 warnings, 143.20秒**。したがって当該failureがfeature回帰である根拠は確認されず、元runのsuite state/teardownを含む非決定的要因の可能性が残る。full run結果へは加算しない。
- Leadのper-file full pytestは全201 filesを完了。初回集計 **9448 passed / 5 failed / 0 skipped**。失敗は3ファイルの古い期待値だけだった: `test_piccoma_discovery_browser.py`はInventoryのsupported capabilityを空と誤期待（grant-only resourcesは空のまま）、`test_cli.py`は既存Yanmaga `work_ticket` capabilityを空と誤期待、`test_runtime_settings.py`は設定ファイルのBookWalker `page_turn_delay_ms: 0`に対して200を誤期待。production code/configは変更せず、該当する3テストファイルの期待値だけをHEADの契約へ同期した。
- 3ファイルの再実行は `20 + 114 + 20 = 154 passed / 0 failed / 0 skipped`。これは初回失敗fileの最新結果で置き換え、二重計上しない。全201 filesのlatest-per-file集計は **9453 passed / 0 failed / 0 skipped / 0 xfailed / 0 deselected**（Integration 53 files / 3283 passed、Research 21 files / 171 passed、Unit 127 files / 5999 passed）。証拠: `output/piccoma_ticket_stage01/full_final_summary.json`, `expectation_reruns.json`, `expectation_fixes.diff`。
- Full suite runnerはfile単位watchdogを600秒から1800秒へ上げて長時間Piccoma fileを完了した。既完了fileは保持して再実行せず、tracked production source hashは前後一致。途中のrunner再起動や初回mono runの結果は成功/skipとして加算していない。全体のfull suiteを再実行しない。

# Young Animal `work_ticket` 実装 Runbook

**Status:** COMPLETE (2026-10-19). Phases 01-04 passed independent review. The normal quota path was verified on `849948508c8bc` / work `71460b2b6686f`: one ticket entry continued on the same Page through Capture, END, ZIP, and Catalog completion. Seven ticket uses are recorded (five original plus two of three additional authorizations); `4ba85f4c9e538` remains unopened and unused. The full repository test suite was not run. See [PROGRESS.md](PROGRESS.md) for evidence, failures, and constraints.
**Baseline:** 着手時の `main` HEADを確認して記録する。`runbooks/younganimal-adapter/` の free/direct E2E完了実装、および `runbooks/hanayume-work-ticket/` の完了済み実装を参考にする。
**実装ブランチ:** `main` から新規 `feat/younganimal-work-ticket` を作り、既存 `feat/younganimal-adapter` / `feat/hanayume-work-ticket` を起点にしない。`main` へ自動マージしない。
**進捗・実測・消費数:** [PROGRESS.md](PROGRESS.md)。既存の Young Animal Adapter Runbook は歴史的記録として維持し、本機能の authority はこの新Runbookと上位仕様。
**最優先の制約:** Batch は Catalog 内の Discovery 済み episode URL に直接アクセス。作品ページを調べに行かず、**作品Aのチケット処理が終わるまで作品Bに触れない**。旧Zeblack式の全作品事前live巡回は禁止。

## 1. ゴール・要求・確定している契約

`younganimal` の Discovery済み作品で `work_ticket` を1作品1枚の単位で使用し、`batch run --site younganimal` から本文を取り込む。`batch run --site younganimal --grant-only work_ticket` ではチケットを消費・記録するだけにする。使用済みの話に閲覧権限が残っている場合は、チケットを再消費せず `direct` で取り込む。

| 項目 | 仕様 / 扱い |
| --- | --- |
| Resource | `work_ticket`。`site=younganimal` の作品単位resource state（他サイトとは共有しない） |
| 消費単位 | **1作品1枚**。同一作品では1回のBatchにつき候補1話のみ |
| 回復時間 | **23時間**。消費確定時刻から作品単位でローカルSKIP。より長い設定は尊重し、23時間未満には短縮しない |
| 起点 | Catalogにある canonical `https://younganimal.com/episodes/<episode_id>` に直接移動 |
| 消費操作 | 対象話内の唯一の正規「待つと無料で読む」を確認し、**最大1クリック** |
| 消費後 | サイトが開いた同一Playwright `Page` から1ページ目→既存Younganimal Capture/END/ZIPを継続。自前の再`goto`や別Pageでの再読込は禁止 |
| Grant-only | 同じ入場処理で使用確認・状態記録のみ。画像0、ZIP0、Item `pending` |
| 手動消費 | Discoveryが対象話の有効な閲覧権限を観測した場合、話単位の `access_granted_until` に同期。期限内は通常Batchが `direct` |
| 閲覧有効期間 | **チケット利用後の native `timeRemainingInSeconds` を実サイトで観測済み**。観測した request start と countdown から 1 秒を差し引いた保守的 expiry を記録する。正確な server recovery 仕様は未確定。固定 72h fallback は使わない。 |
| 候補の探索 | Catalogのみで選定。対象1話で不適格ならSKIP。作品内の別話を連続して探さない |
| 権限外 | 課金/ポイント/コイン/別のチケット/ログイン処理へフォールバックしない |

ユーザーは検証用のチケット数枚の使用を許可している。ただし必要最少枚数で段階的に検証し、何枚・どの作品/話・何時に使用したかを必ず記録する。未知の課金やログイン操作にはこの許可を拡張しない。

### Repository baseline at Phase 01 start (2026-10-18; historical)

The following describes the pre-implementation state, not the current adapter.
See the completion status and `PROGRESS.md` for the current implementation.

- At the start, Younganimal direct Batch for free and active-rental sources plus Viewer Capture/END/ZIP were implemented. The configured Batch adapter was direct-only and the central ticket gate rejected entry.
- At the start, Discovery traversed work listing ranges and joined `epListUser` rows with public rows. It classified exact free and active-rental labels but had no strict wait-free candidate classifier. An earlier survey found only 3 free rows among 925; unknown rows must not be treated as ticket candidates.
- At the start, the Younganimal policy excluded `quota` as `quota_not_supported`; it already preserved free and active-rental direct classification.
- `site_policies/hanayume.py`、`site_adapters/hanayume/adapter.py` / `discovery.py`、`runbooks/hanayume-work-ticket/`: 1作品1枚、23h cooldown、消費後同一Pageで続行、grant-only、手動使用済み話同期、安全な1回クリックの実装・検証例。
- `batch/planner.py`: `quota_scope="work"` + `quota_limit=1` の候補抑制あり。`batch/executor.py`: local cooldown SKIP、`after_observed_consumption` 記録、grant-only entry、失敗時の消費記録あり。`cli.py`: site resource pass / `--grant-only` / 逐次実行あり。まず既存フローに載せ、Core改修は必要性を証明した場合に限る。

## 2. 禁止事項と不変条件

Follow-up authorization (2026-10-18; final state 2026-10-19): the original five-use allowance was exhausted. The user separately authorized up to one additional use on each exact episode URL `dd9facaba1704`, `849948508c8bc`, and `4ba85f4c9e538`. DD9 and 849 were each handled as separate one-work Discovery/Batch candidates; both additional ticket uses were consumed, while `4ba85f4c9e538` remained unopened and unused. The fresh-quota 849 normal run passed same-Page Capture -> END -> ZIP and independent postflight. No blanket preflight or automatic retry is allowed; see `PROGRESS.md` for the per-attempt evidence.

1. **Batch/Grant-onlyで作品ページ (`/series/`)、作品一覧、別話を事前crawlしない。** Discoveryコマンドでの正規の作品一覧列挙は既存仕様のまま許すが、Batchの preflight/消費直前/作品選定に流用しない。
2. **1作品ずつ逐次完了。** work AのCatalog候補選択→ローカル判定→episode直行→クリックまたはSKIP→通常Capture/ZIPまたはgrant-only確認→close、の後に初めてwork Bへ。先に全作品のlive状態を集めるResolver、作品内全話の試行は禁止。
3. **消費対象を正確に拘束。** `work_id:episode_id`、canonical episode URL、画面内のwork link・見出し、controlのscope/唯一性・有効性・無料条件を照合。unknown / paid / login / duplicate / hidden / disabled / ID不一致 / DOM変化はfail closed。
4. **クリック最大1回。** `click` timeout、通信切断、キャンセルの後に自動再クリックしない。成否を確認するときは回数と時間を制限したread-only観測のみ。
5. **「消費確認」と「取得成功」は独立。** 正の消費証拠があれば `AccessConsumption` を確定し、Viewer/ZIP/ENDで失敗してもwork resource / source grantを可能な限り保存。未確認時は未確認として終了し、成功扱いも自動再試行もしない。
6. **期限は観測値から保守的に算出する。** Active ticket grant の有効期限は観測済みの native countdown に基づく。正確な server recovery 時刻と別の work countdown との関係は未確定。固定 72h fallback を使わず、手動 ticket の消費時刻を expiry のみから逆算しない。
7. **回帰防止。** free、active rental、初回空白、見開き、巻き戻し、native VP8L/PNG fallback、END/ZIP、既存Catalog状態を維持。サイト間resource/セッションは完全に分離。
8. 共有CDP Chromeを操作するエージェントは同時に1名。既存AccessGuard、有限timeout、サイト間pacing、403/429/CAPTCHA stopに従う。Cookie/画像/認証トークン/署名付きURLをコミットしない。実サイトの過度な反復アクセスは禁止。

## 3. 実装フェーズ

### Phase 01 — Repo差分と実サイトのread-only Probe、最少枚数の消費検証

**担当:** Explorer → Reviewer → 必要な最少1枚の実操作はLead管理下でTesterまたはImplementer。
**対象:** 既存のDiscovery済みworkとepisode URL。必要な対象はCatalogから選ぶ。実サイトに対象がない場合は安全に判定可能な範囲を記録し、架空の成功判定をしない。

- Hanayumeの `work_ticket` 各入口と Younganimal `EPISODE_SCOPE_SCRIPT` / `ENTRY_BLOCK_SCRIPT` / `initialize` の実際の差分を調査。
- 対象話URL **1件** を直接開き、hydrate後の正確な「待つと無料で読む」button、親scope、同一ページ内のpaid/rental/login controlとの差、実行可能状態をread-only観測する。既知の曖昧なアイコンや「今なら無料」だけで消費可能と判断しない。
- サイトが通常発生させるネットワークのうち、対象work+episodeを結びつけるaccess/grant/remaining/APIレスポンスをread-onlyで観測。API名・フィールド名をHanayumeと同一と仮定しない。ログイン中の本人アカウントであることのpositive evidenceを確認する。
- チケット回復23hと本文閲覧期間（未確認）の**違い**、手動消費した話の一覧表示、期限切れ、対象ページの閲覧権限・状態を調べる。可能な限り追加navigationなし、既存のDiscovery表示を活用する。
- Selector/identity/無料性/1回クリックの安全ゲートが確認できてから、必要なら1枚だけ実際に使う。サイト生成の消費リクエスト・対象話のgrant遷移・Viewer1ページ目ready・URL/ページ一致を検証。二度押し禁止。追加枚数は前回の結果と未検証項目に基づき最小限にする。
- 利用不可・ログイン不足・対象が有料・API/DOM不明なら消費せず未確認条件を明記する。

**Gate:** `PROGRESS.md` に（秘密を除く）DOM/APIセレクタ、ID対応、クリック成功の正の証拠、閲覧有効期間の根拠またはUNKNOWN、使用した枚数とwork/episode、制御画面の分岐を記録。Reviewerによる操作安全性の判定を得る。

### Phase 02 — Discovery / SitePolicy / Catalog-only candidate

**主な変更:** `src/screenshot_crawler/site_policies/younganimal.py`、`site_adapters/younganimal/discovery.py`、各テスト。一般化は必要最小限。

- `YounganimalSitePolicy` に `supported_access_resources`、`ordered_access_resource_passes`、`grant_only_supported_access_resources`、`resource_state_scope("work_ticket") == "work"`、`defer_quota_access_to_grant_phase() == False`、`grant_only_skip_reason`、`grant_only_retry_at` をHanayumeと同じ契約で追加。
- 確実にticket対象と分かった source だけ、`quota_resource="work_ticket"`、`quota_scope="work"`、`quota_limit=1`、`quota_commit_mode="after_observed_consumption"` でeligibleにする。freeはdirect、当該話のactive grantはdirect、他のpaid/unavailable/unknownはfail closed。既存の `paid + active rental` direct は維持。
- 作品内候補の優先順は既存Catalog/Discovery順を維持。Plannerの既存work quota limitを利用し、**同作品の別候補をlive探索するfallbackなし**。`--limit` や失敗後の候補移行がこの原則を破らないことをテスト。
- Discoveryの正確なrow-scopedバッジ/APIに基づき `unknown → quota` の条件を実装。判別不能なunknown全件をquotaにしない。画面内の正の信号が足りない場合、候補の限定方法をPhase01証拠で決め、漏れなく捕まえようとして無制限にepisodeを探し回らない。
- 手動使用済み話は**話単位**で期限を同期。既存の `レンタル中 閲覧期限...` を再利用できる場合はそのまま用い、タイマー丸めの下限を維持。未知の観測で正確な既存の `access_granted_until` を誤消去しないため、`access_granted_until_observed` を正しく設定する。正しく期限切れを観測した場合のみstale grantをクリアする。
- 23hは `site, work_id, work_ticket` をキーにCatalogへ保存された消費時刻で**ページ作成前にSKIP**。表示される次回確認時刻はローカル推定であってサイトでのリアルタイム保証ではない。手動消費のwork cooldownは、サイトから使用日時/回復時刻の正の証拠を得られる場合のみ同期。
- 既存 `incremental_stop_decision=CONTINUE` を維持し、古い話の手動grantをfull/incrementalともに反映。Discovery本来の作品一覧アクセス以外の追加事前巡回はしない。ソースがあいまいな場合に無期限grantを捏造しない。

**Gate:** free/active rental/direct維持、quota適格/unknown拒否、1作品1候補、別作品で独立23h、22:59:59 SKIP/23:00:00可、期限境界、手動grant、全件unknown、stale更新/保全、SKIP時のsite request **0** をUnitで検証。必要ならBrowser fixtureでDiscovery一覧を検証。

### Phase 03 — Younganimal Adapterの1回ticket entry / 同一Page Capture / grant-only

**主な変更:** `site_adapters/younganimal/adapter.py`。複雑なら同ディレクトリに小さな `live_access.py` を新設。`capture.py` / `native_capture.py` の大規模変更禁止。

- `configure_run` で `auto`（手動） / `direct` / `quota` を厳密に区別し、`configure_target_identity` と canonical URL束縛を維持。`configure_quota_resource`、`get_access_consumption`、`initialize_entry_only` を追加。
- Observer/route guardは対象話への`goto`前にセットし、対象話に閉じて一意・可視・有効な無料ticket controlがあることを判定する。課金/rental/login、複数control、別話への遷移、work不一致は**クリック前**に拒否。クリック直前にも再確認する。
- クリック開始をラッチしたら、失敗/timeout/キャンセル後に再試行しない。サイトが返す**同じwork/episodeの正の消費＋active grant証拠**で `AccessConsumption(consumed=True, resource="work_ticket", consumed_at=aware_datetime, access_granted_until=...)` を確定。期限が確証できなければ `None` とし、別サイトの72hを適用しない。検証可能な証拠が無い時は消費未確認・自動retryなし。
- **通常Batch:** サイトが開いた **同じPage** で既存 `_verify_episode_entry` / `_wait_for_viewer_ready` / 巻き戻し・Capture/END/ZIPに接続する。押下後に独自`page.goto`を追加しない。routeが変わる場合は同じepisode identityかを検証し、未観測の別話/series redirectは拒否する。
- **grant-only:** 同じticket entry処理で正の消費を確認して終了。0画像、0ZIP、Item pending。確認済みwork stateを保存する。画像が無いことをViewer失敗と誤判定しない。
- 消費確認は後続のViewer/Capture/ZIPとは独立して永続化する。クリック後のクラッシュ/中断/未知の通信結果では、二重消費を避ける失敗報告と運用手順を残す。異常時に次作品へ進めるかは既存Batchのfatal-stopルールに従い、権利不明のまま同じ作品を再試行しない。
- 既存 `ENTRY_BLOCK_SCRIPT` の無料directを保ちつつ、quota時だけ正当なticket gateを通す。paid gateの迂回・ブラウザ操作での権利捏造・画像取得ロジックの緩和は禁止。

**Gate:** synthetic Browserで有効1回click、遅延hydrate、未ログイン、missing/duplicate/hidden/disabled/paid、wrong work/episode、ボタン差し替え、click timeout、HTTP 403/429/CAPTCHA、post-clickのroute drift、クリック成功後Viewer/ZIP失敗、cancel時の消費記録を検証。paid click=0、二重click=0、Batchの `/series/` main-frame navigation=0、`grant-only` 成功でpages/ZIP=0を確認。

### Phase 04 — 検証 / 独立レビュー / 実サイトE2E

1. `ruff check src tests`、影響範囲の `pytest`、可能なら全 `pytest`、`git diff --check` を実行。Younganimal free/directの2つの既存layout profile、active rental、Hanayume work ticket、ComicDAYS/Zeblack work resource、共通Batchの回帰を確認。通らない既知テストは原因・対象・修正責任を切り分ける。
2. **隔離DB・Watchlist・output/library** と既存ログイン済み共有CDP Chromeの排他利用。最少1話で `batch run --site younganimal --grant-only work_ticket --limit 1` を実行。正の使用証拠、正しいwork cooldown、話のgrant、Item pending、画像/ZIPゼロを独立監査する。
3. 同じworkで再実行し **サイトアクセス0件** の23h SKIP、別workには影響しないことを確認。初回で実サイト使用したticketは消費枚数として記録する。
4. 別の未使用作品で `batch run --site younganimal --limit 1`。1回のticket使用後、**対象epの同じPageから**1ページ目→END→画像/ZIP（ページ順・CRC・デコード・native fallback）→Catalog completedまで検証。
5. 手動使用済みの話を `discover full` と `incremental` で同期し、通常Batchで**再消費0**のdirect取得を検証。実際の手動消費や期限観測が不可能な場合はfixture PASSとlive NOT VERIFIEDを区別。
6. Reviewerは実装と結果の独立レビュー。Testerはネットワーク監査（対象episode main navigation数、`/series/` navigation 0、ticket POST/click 0/1、他作品先読み0）、Work/Source DB、失敗ログ、ZIPを独立確認。結果と消費総数を `PROGRESS.md` に記録。

**完了条件:** Phase01の証拠に基づく仕様、Phase02/03の全安全ゲート、Phase04のライブ両モードと回帰テストがPASS。Viewerの既存仕様を破らず、自動サイト巡回や二重消費が無いことを証明できる。実サイトの仕様・有効期限が観測できず未完成なら、未検証の部分を完了扱いしない。

## 4. 変更範囲・担当と開発規則

| 範囲 | 方針 |
| --- | --- |
| `site_policies/younganimal.py` | work-scoped resourceと23h policy追加 |
| `site_adapters/younganimal/discovery.py` | ticket候補と手動grantを安全に分類、既存free/rental維持 |
| `site_adapters/younganimal/adapter.py` | 1回ticket entry、観測・記録、same-page Viewer/entry-only |
| `site_adapters/younganimal/live_access.py` | 追加するのはadapterに押し込むと複雑になる場合のみ |
| `tests/unit/test_younganimal_*.py` / `tests/integration/test_younganimal_adapter_browser.py` | 分岐・回帰・end-to-end fixture |
| `batch/planner.py` / `batch/executor.py` / `cli.py` | 既存機能を優先使用。変更が不可避なら汎用で小さく、他サイト回帰テスト必須 |
| `runbooks/younganimal-work-ticket/PROGRESS.md` | 実測、判断、実際の消費枚数、レビューチェックポイント |

**マルチエージェント:** Leadは仕様判断とゲート管理、Explorerは既存実装と実サイトread-only、Implementerは限定変更と単体テスト、Reviewerは問題・回帰・権利操作を独立検証、Testerはfixture/E2E・ネットワーク・DB・ZIPの独立監査。共有Chrome操作は常に排他的。`docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md` と `AGENTS.md` の上位ルールに従う。

**Codex初動:** このRunbookと `PROGRESS.md` を読み、`main` 最新から作業ブランチ作成→Phase01で差分・未確定点・安全な対象候補を調査→Reviewerゲートを通した最少ticket消費→Phase02/03を実装→Phase04で独立検証。Phaseが完了するたびに `PROGRESS.md` を更新し、コード・テスト・ドキュメントの変更と未検証点を明示する。目的・変更範囲を広げたり、旧サイトAdapterの共通化を自己目的化しない。

## 5. 最終受け入れチェックリスト

- [x] Discovery済み canonical episode URL以外にBatchの事前探索がない。作品ページnavigation、別作品先読み **0件**
  This check covers Batch's explicit candidate preflight/navigation only; it does not assert that every naturally generated non-main RSC request is absent. Incidental RSC observations and abort handling are recorded in `PROGRESS.md`; initiators and work identity are not established for all such requests.
- [x] 1作品1候補・最大1回ticket click、作品ごとの逐次完了
- [x] `work_ticket` のローカル23h SKIPがページ作成前に働き、再実行時site request **0件**
- [x] 有効期限内の手動・自動grantは同じ話のみdirect。再消費0、期限の捏造0
- [x] 対象不一致/paid/login/unknown/DOM driftでクリック0、自動二重クリック0
- [x] 消費確定後にCapture/ZIPが失敗してもwork/sourceの記録と失敗区別が残る
- [x] Normal Batch: one click -> same Page -> END -> valid ZIP -> Item completed (episode 849; independent review passed)
- [x] `--grant-only work_ticket`: 1クリック→消費確認・記録、pages=0、ZIP=0、Item pending
- [x] 既存free/rental/描画品質、Hanayume/ComicDAYS、共通Batchの回帰確認あり（検証範囲は下記）
- [x] 実サイトでチケット総消費数・証拠・観測時刻・独立レビュー結果を `PROGRESS.md` に記録

Regression-check scope: an earlier broad affected selection recorded 871 passes and 2 diagnostic-path failures. Both exact shortened-path reruns passed, suggesting path length as the cause (inference). The current seven-file Younganimal selection also passed 322 tests. This bounded evidence does not claim that the original broad run was all-green or that the full repository suite ran.

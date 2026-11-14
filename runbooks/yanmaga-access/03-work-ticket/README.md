# Stage 03 — 待つと無料（work_ticket）の通常Batch / grant-only

**Status:** NOT STARTED
**前提:** Stage01のサイト側チャージ・レンタル状態の証拠、Stage02の既存Grant直取得がPASS。未確認のセレクタ・回復時間・閲覧期限の実装は禁止。
**終了条件:** 同一workでの23h消費抑止、liveチャージ可否、確定した1回のチケット消費、通常Batchとgrant-only双方の成功/失敗の扱い。

## 1. Policy（既存仕組みを利用）

変更先：`src/screenshot_crawler/site_policies/yanmaga.py`。 `hanayume.py` / `younganimal.py` / `magapoke.py` を参照し、site共通化・新DB列はしない。

- `batch_ordering` はStage01で検証した順序を採用。既存のplanのwork quota分離を理解し、作品の順番を勝手に再配置しない。
- `supported_access_resources`, `ordered_access_resource_passes`, `grant_only_supported_access_resources` が `("work_ticket",)` を返す。`resource_state_scope("work_ticket") == "work"`。
- `free` は従来の `direct`（初回無料も含む）。`quota` は対象話の有効Grantがあれば `direct`、それ以外は `PolicyDecision(eligible=True, access_strategy="quota", consumes_quota=True, quota_resource="work_ticket", quota_scope="work", quota_limit=1, quota_commit_mode="after_observed_consumption")` とする。
- `paid` は新規支払い禁止。**初回無料や待つと無料で実際に得た同じ話の有効Grant**が既存DBで確認できる場合だけ `direct` を候補にして、site側Viewerでも正の検証を必須にする。
- `unknown`, `owned`, 他のmodeは勝手にquota/purchaseへ昇格しない。
- `grant_only_skip_reason` / `grant_only_retry_at` により、最後の**確定済み**同作品 `work_ticket` 消費から23時間以内はサイトへアクセスする前にローカルSKIP。`work_ticket_cooldown_hours` の設定があってもサイト既定の23hより短縮しない。naive/不正日時はfail-closed。
- `access_grant_until` はStage01の**サイト実測の閲覧権限有効期間**に基づいてのみ決定（23h回復と混同しない）。本人の正確な期限が取得できるならそれを優先。期限不明なら架空の一律有効期間を付与せず、サイトの可否に従う。
- `defer_quota_access_to_grant_phase` や独自resolverの追加は既存の簡単な同一話clickでは足りないと**実測で確認された場合だけ**。不要な汎用抽象化はしない。

## 2. Adapterのwork-ticket入場

`src/screenshot_crawler/site_adapters/yanmaga/adapter.py` の `configure_run` を `quota` に拡張し、`configure_quota_resource(page, "work_ticket")` を受ける。`get_access_consumption()`、`initialize_entry_only()` は既存共通Runnerの契約に合わせる。

1. 計画された対象話のsource/episode IDとサイトの入場状態をfreshに照合。**アカウントログイン・チケット利用可・無料操作の一意性・作品単位のチャージが完了していること**をサイト由来の正の証拠で確認する。
2. 同一話の閲覧権限が**既に有効ならクリックしない**。通常Batchはそのまま本文取得へ。grant-onlyは「既にGrantあり」として成功した消費に数えない。
3. 「待つと無料」だけが有効な場合、対象work/episodeとボタン/リソースを最後に再検証し、**1クリックのみ**。初回無料・コイン/ポイント・広告報酬・別作品への暗黙fallbackを禁止。
4. ボタンclickの返り値だけで確定しない。確認された同一話のサイトGrant変化と本文閲覧可能状態から `AccessConsumption(consumed=True, resource="work_ticket", consumed_at=aware日時, access_granted_until=検証済み期限)` をラッチ。結果が不明なら**二度押ししない**。確認待ちはbounded read-only polling。タイムアウトやキャンセル時も、可能なら同一話の消費事実を照合して記録。
5. 通常Batchでは**開放後の同じPage**で既存Yanmaga本文先頭→Capture→ENDへ。grant-onlyでは入口/権限の確認だけ行い、画像・Manifest・ZIPは作らない。Itemはpendingのまま。
6. 後段の画像取得/END/ZIPが失敗しても消費確認済みなら、既存 `BatchExecutor` の `after_observed_consumption` フローでSourceの `quota_started_at` と `access_granted_until`、work `quota_resource_states` を記録。**消費未確認**と**消費済み・後処理失敗**を別々に報告する。

サイトが読取用の認証表示/チャージ画面を出すだけで消費済みか不明な場合は、DBの使用履歴を作り上げない。最後に読める状態になっても、閲覧可能であることと「今回の新規チケット消費」は区別する。

## 3. Discoveryとの整合性

初回無料で失敗した話が再Discoverで `quota` になっても、既存Grantがまだ有効ならPolicyはdirect候補として再取得させる。`paid` に変化しても有効Grantがあれば同じ。逆にGrant失効後は待つと無料ならquota、ポイントのみならpaidで止める。

チケットを手動使用した場合、Discoveryが**正の閲覧期限**を観測できればepisode `access_granted_until` を更新する。作品チケットの最終消費日時は、サイトから正確に立証できる場合だけ `quota_resource_states` に反映する。閲覧終了時刻だけから使用日時を逆算して「23h経過」と決めつけない。

## 4. 必須テスト

- same workの2話に同一チケットを二重消費しない（通常Batch/同一run/別run/同じ作品の複数Discoveryキー）。異なるworkは独立。
- 23時間未満でSKIP、23時間以降は**サイト上でチャージ完了の正の確認がある場合のみ**click。JST/UTCと境界時刻。
- チャージ中、未ログイン、disabled、別resourceのみ、ポイントのみ、ラベル曖昧、複数CTA、他作品・他話に変化、403/429、CAPTCHA→消費なしでSKIP/STOP。
- クリックを1回だけ試みる。APIエラー/キャンセル/タイムアウト、消費未確認で自動再クリック0。事後に今回の消費が確認できれば画像失敗でもwork/source記録。
- すでにGrantあり→再消費0、direct captureのみ。grant-onlyでGrant済み→消費済み成功として誤記録しない。
- grant-onlyで `quota/work_ticket` を選び、初回無料 `free` は候補外。完了時ページ0・ZIP0・pending・work stateのみ消費確認に応じ更新。
- 通常quota runで同一話Viewer→全画像→positive END→ZIP/Completed、失敗でpendingと既存Artifact不変。
- `tests/unit/test_yanmaga_*.py`、`tests/integration/test_yanmaga_*browser.py`、`tests/unit/test_batch_*.py`、`tests/unit/test_cli.py` など該当する**実在ファイル名を確認**して選択実行。サイト共通のPlanner/Executor/Grant-only経路への回帰を重点検証。

**Gate:** 通常quotaのlive消費結果とgrant-onlyのlive消費結果を区別して記録する。同じ作品で23時間待つ必要がある場合、無理に実サイト権利を消費せず、別の適格作品またはモック試験を使い、未実証部分はNOT VERIFIEDと記載。Reviewer BLOCKING 0でStage04へ。

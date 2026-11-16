# Stage 03 — 待つと無料（work_ticket）の通常Batch / grant-only

**Status:** PASS with qualified composite live evidence and independent BLOCKING 0. Wait classification, Policy, exact entry, automatic ticket persistence, novel chapter 10 grant-only, and dual chapter 29 same-grant capture through positive END/ZIP/Completed were verified. The dual final run used the existing grant and made no ticket POST; the grant and work cooldown stayed unchanged. No more ticket action is authorized.
**前提:** Stage01/02 are accepted. Stage03 uses only the observed wait marker, charged indicator, exact episode rental form, and Rental History structure recorded in `PROGRESS.md`. Dual chapter 29 Run 10's postcondition was not confirmed inline; Root later applied one frozen exact-history observation to the Source grant and work cooldown using the observation-time anchor, not the precise POST time. Novel chapter 10 grant-only then verified automatic ticket confirmation and persistence. Dual same-grant attempts 3/4 were incomplete; attempt 5 completed capture through positive END/ZIP/Completed without a new submit. Stage03 is accepted with qualified composite evidence and independent BLOCKING 0. No further ticket submit is authorized; no unobserved selector or fixed expiry is assumed.
**終了条件:** 同一workでの23h消費抑止、liveチャージ可否、確定した1回のチケット消費、通常Batchとgrant-only双方の成功/失敗の扱い。

## 1. Policy（既存仕組みを利用）

変更先：`src/screenshot_crawler/site_policies/yanmaga.py`。 `hanayume.py` / `younganimal.py` / `magapoke.py` を参照し、site共通化・新DB列はしない。

- `batch_ordering` は既存のYanmaga順序を維持する。既存planのwork quota分離を使い、作品の順番を勝手に再配置しない。
- `supported_access_resources`, `ordered_access_resource_passes`, `grant_only_supported_access_resources` が `("work_ticket",)` を返す。`resource_state_scope("work_ticket") == "work"`。
- `free` は従来の `direct`（初回無料も含む）。`quota` は対象話の有効Grantがあれば `direct`、それ以外は `PolicyDecision(eligible=True, access_strategy="quota", consumes_quota=True, quota_resource="work_ticket", quota_scope="work", quota_limit=1, quota_commit_mode="after_observed_consumption")` とする。
- `paid` は新規支払い禁止。**初回無料や待つと無料で実際に得た同じ話の有効Grant**が既存DBで確認できる場合だけ `direct` を候補にして、site側Viewerでも正の検証を必須にする。
- `unknown`, `owned`, 他のmodeは勝手にquota/purchaseへ昇格しない。
- `grant_only_skip_reason` / `grant_only_retry_at` により、最後の**確定済み**同作品 `work_ticket` 消費から23時間以内はサイトへアクセスする前にローカルSKIP。`work_ticket_cooldown_hours` の設定があってもサイト既定の23hより短縮しない。naive/不正日時はfail-closed。
- `access_grant_until` は対象話のRental Historyで実測したカウントダウンから保守的下限を計算し、23hの作品チャージ回復と混同しない。wait/trusted-historyでは exact `残りH時間` または `残りD日` を明示上限72hまで扱う。D>=2は観測開始+(D-1)日-5秒の `site_day_countdown_lower_bound`、D=1とH=1はactiveのみでfinite expiryなし。通常のfirst-free履歴は最大23hの時間表記だけを使い、日の表記は受け付けない。72h固定で期限を作らない。
- `defer_quota_access_to_grant_phase` や独自resolverの追加は既存の簡単な同一話clickでは足りないと**実測で確認された場合だけ**。不要な汎用抽象化はしない。

## 2. Adapterのwork-ticket入場

`src/screenshot_crawler/site_adapters/yanmaga/adapter.py` のquota pathは、実測済みのwait rowとcharged表示を照合し、観測されたSource modalの同一話 `読む` formを使う。`get_access_consumption()`、`initialize_entry_only()` は既存共通Runnerの契約に合わせる。

1. 計画された対象話のsource/episode IDとサイトの入場状態をfreshに照合する。authenticated work listingの一意なwait画像marker、対象行、visible charged表示、および対象話がRental Historyに未掲載であることを確認する。History取得失敗・対象の重複・未対応collectionは入場を止める。
2. 同一話の閲覧権限が**既に有効ならクリックしない**。通常Batchはそのまま本文取得へ。grant-onlyは「既にGrantあり」として成功した消費に数えない。
3. Source GETだけではチケットを消費しない。fresh Source modalのwork/episode/title/3日間表示、同一話にbindされた `POST /rental/episodes/<episode-id>/by_free_waits` form、visible enabled exact `読む` buttonを再検証してから、通常Locator clickを最大1回行う。初回無料・コイン/ポイント・広告報酬・別作品への暗黙fallbackは禁止。
4. clickの返り値だけでは確定しない。既存の同話Viewer・work-ticket固有のexact完了notice `レンタルが完了しました`・body-access proofと、post-clickのexact active Rental Historyがすべて成立した場合だけ `AccessConsumption(consumed=True, resource="work_ticket", consumed_at=aware日時, access_granted_until=検証済み期限)` をラッチする。first-freeの `無料レンタルが完了しました` はwork-ticket noticeの代替にしない。Novel chapter 10 grant-onlyで、このticket notice/history/persistence経路が実サイトで1回確認された。Dual chapter 29 Run 10は当時postconditionをinlineで保存できず、後から凍結した正のHistory観測で一度だけ復旧記録した。結果不明なら**二度押ししない**。H=1またはD=1で消費は確認できてもexpiryが作れない場合は消費を記録してcapture前に失敗し、期限なしGrantで成功扱いにしない。
5. 通常Batchでは**開放後の同じPage**で既存Yanmaga本文先頭→Capture→ENDへ。grant-onlyでは入口/権限の確認だけ行い、画像・Manifest・ZIPは作らない。Itemはpendingのまま。
6. 後段の画像取得/END/ZIPが失敗しても消費確認済みなら、既存 `BatchExecutor` の `after_observed_consumption` フローでSourceの `quota_started_at` と、finite expiryが確認できた場合の `access_granted_until`、work `quota_resource_states` を記録する。**消費未確認**と**消費済み・後処理失敗**を別々に報告する。

サイトが読取用の認証表示/チャージ画面を出すだけで消費済みか不明な場合は、DBの使用履歴を作り上げない。Source modalの表示とPOST form確認は消費ではなく、クリック後の同一話post-stateでのみ「今回の新規チケット消費」を確定する。Dual chapter 29とNovel chapter 10の2回のnative ticket POSTが記録され、Novelでは自動保存が、Dualでは遅延したexact-history復旧記録が確認された。Dualの後続same-grant captureは別runで完了し、追加POSTは発生していない。Stage 03はqualified composite evidenceでPASS、独立BLOCKING 0。Stage 04は未開始。

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

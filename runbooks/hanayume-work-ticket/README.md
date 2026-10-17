# 花とゆめ＋ Work Ticket 実装 Runbook

**Status:** PLANNED（計画のみ。コード変更・実サイトでのチケット使用は未実施）  
**Baseline:** 2026-10-17 の `main`。既存の [Hanayume free-only Runbook](../hanayume-free/README.md) R9 PASS を起点とする。  
**実装ブランチ:** `main` から新しい `feat/hanayume-work-ticket` を作成し、main には自動マージしない。古い `feat/hanayume-adapter` を起点にしない。  
**進捗記録:** [PROGRESS.md](PROGRESS.md)。旧 free-only Runbook は完了履歴として維持する。

## 1. 目的と確定仕様

Discovery 済みの Catalog に対し、各話の canonical URL (`https://hanayume.com/episodes/<id>`) を**直接**開く。「待つと無料で読む」の明確なボタンをクリックして当該話の Viewer を開き、通常 Batch では**クリック後の同じページから**既存 free-only と同じ Capture → END → ZIP を実行する。`batch run --site hanayume --grant-only work_ticket` に対応する。

| 項目 | 仕様 |
| --- | --- |
| Resource 名 | `work_ticket` |
| 消費単位 | 作品につき1枚 |
| 消費後の回復時間 | **23時間**。消費確定時刻を work 単位に記録 |
| 当該話の閲覧有効期間 | **72時間**。別の話には適用しない |
| 閲覧期限表示 | 「2日＋23時間」等の残時間表示が見られる。これは回復23時間とは別 |
| 開始点 | Discovery / Catalog 済みの episode URL。Batch が Discovery しない |
| 通常 Batch | ticket のクリック後、遷移先の話の1ページ目からそのまま既存 Crawler を実行 |
| Grant-only | ticket 使用・成功確認・記録まで。**画像保存0、ZIP0、Item は pending** |
| 再実行 | **23時間未満は作品単位でサイトアクセス前にローカル SKIP**。次回確認可能時刻を出力 |
| 処理順 | **1作品ずつ逐次処理**。前作品を処理・終了してから次作品。先に全作品の live 状態を確認しない |
| 禁止 | Batch 中の `/series/` 作品ページ・作品一覧・全話リストの巡回、有償購入・コイン操作、別作品の先読み |

ComicDAYS の作品単位 Resource / Batch / grant-only の扱いを**第一参考**とする。必要に応じてゼブラックの候補グループ化部分を参考にしてよいが、ゼブラックの旧式「先に全作品の状態を巡回」は絶対に行わない。

72時間の閲覧 grant は source（episode）単位 `access_granted_until` に保存し、チケット消費時刻は Catalog の既存 work-scoped quota-resource state (`site, work_id, resource`) に保存する。サイト由来の正確な有効期限が得られれば優先し、得られなければ**確認済みの消費時刻＋72h**を適用。23h はあくまで同作品で新しい ticket を使えない期間。使用済み話が72h中ならチケットを使わず direct で読む。

## 2. 絶対に守る制約・安全条件

1. **Catalog-only 候補選定。** Batch 開始時は DB/Watchlist から作品・候補を選択するだけ。作品の状態のために作品ページを crawl したり、全作品の状態を先に収集したりしない。
2. **1作品1候補・1回の試行。** 作品Aの1話だけを直接開き、付与するか SKIP するか決める。作品内の別話を順番に調べる fallback はしない。作品Aの処理・close 完了後に初めて作品Bへ進む。全作品のまとめてアクセスは禁止。
3. **正確な UI をクリック。** work/episode identity と、唯一の「待つと無料で読む」control・無料であること・操作可能状態を、対象話ページ内だけで検証する。Paid / rental / login / unknown / duplicate / disabled は **fail-closed**。有料ボタンへは絶対にフォールバックしない。
4. **クリックは最大1回。** Playwright の timeout / click error / cancellation 後は追加クリックしない。必要なら bounded read-only polling で成否確認。正の証拠がない場合は消費**未確認**とし、成功とみなさない。
5. **消費記録は Viewer/ZIP 成功と独立。** サイト上で ticket 消費が確認できれば `AccessConsumption` をラッチし、続く viewer/capture/ZIP が失敗しても可能な限り確定消費を Catalog に記録する。レポートでは「消費済み／後処理失敗」と「消費未確認」を区別する。消費した可能性がある未確認状態で再試行を自動化しない。
6. **Viewer 継続。** 通常 Batch は押下後に開く同一 `Page` で既存 Hanayume Viewer を初期化して crawl する。別の Page に navigete して ticket 取得を分離しない。`grant-only` は同じ安全な入場処理を使い、内容は保存しない。
7. **既存機能に回帰を出さない。** free / authenticated `今なら無料` direct、manual preflight、同一話 identity、先頭見開き、巻き戻し、source-canvas・可逆WebP・PNG fallback、END、ZIP順序を維持。
8. AccessGuard、有限 timeout、サイト間の pacing、HTTP403/429 / CAPTCHA stop、共有 CDP Chrome を維持。共有 Chrome を同時に操作するエージェントは1名のみ。秘密・画像・署名付き URL を commit しない。

## 3. 既存実装の再利用ポイントと重要な判断

- `src/screenshot_crawler/site_policies/comicdays.py`: Work Ticket resource、work scope、ローカル23h skip、72h grant、`after_observed_consumption` を参照。
- `src/screenshot_crawler/site_adapters/comicdays/adapter.py`: `quota/work_ticket` の entry と通常 Viewer を**同一ページ内**で連結、`initialize_entry_only`、一度だけ click、消費確認・ラッチ。
- `src/screenshot_crawler/batch/executor.py`、`batch/grants.py`、`cli.py`: Catalog への work resource 状態保存、ローカル SKIP、grant-only 実行とレポートを再利用。
- `src/screenshot_crawler/site_adapters/hanayume/adapter.py`: 現行 Viewer / native capture は原則変更しない。チケット入場処理だけ前段に追加。
- `src/screenshot_crawler/site_adapters/hanayume/discovery.py`: 現行は `無料` と認証済み `今なら無料` を free、その他を unknown とする。調査で検証できたチケット系 badge を quota にする。ただし **既存 Catalog を使う要件**があるため、既存 unknown source の候補化方法は先に調べる。unknown を無条件に quota・使用可能と決めつけず、選んだ1話内の厳密な ticket control で安全を証明する。Batch から Discovery を再実行しない。

**設計選択:** 通常 Batch では ComicDAYS 型の**non-deferred quota execution**を第一候補にする。現行の deferred 付与→post-grant direct 再ナビゲーションは「クリック後そのページをそのままcrawl」と食い違うため、そのまま使わない。一方、同作品に複数 pending candidate がある時の「1作品1候補」を現行 Planner/CLI が保証するかを検証する。不十分なら、work 単位で最初の Catalog 候補だけを選ぶ薄い site-owned 層、または最小限の site-neutral grouping を追加し、Core の site 固有分岐や大きな抽象化を避ける。候補選定や cooldown SKIP にサイト通信を伴わせない。

## 4. 段階別実行契約

### Phase 01 — Repo / live read-only probe

**目的:** 現行 `HanayumeSitePolicy` / `HanayumeAdapter` / ComicDAYS 作品Batch / grant-only を比較し、最小変更範囲を確定。指定された次の5つは必要に応じて利用可（5枚使うことを目標にしない）。

- https://hanayume.com/episodes/49b7e11049871
- https://hanayume.com/episodes/9a2b14d706281
- https://hanayume.com/episodes/2469d6342bd0b
- https://hanayume.com/episodes/06994043345b1
- https://hanayume.com/episodes/1d10701c05629

各話へ直接アクセスし、対象 work/episode ID、button 固有属性・親スコープ・数・表示状態、paid control との差、UI hydration、チケット回復の表示、72h閲覧 grant の表示/絶対期限を**read-only** で観測。作品ページ・一覧ページには行かない。5話が異なる作品であるとは仮定しない。1話の安全性を確定した後、必要な**最少の ticket（まず1枚）**だけ使用して click 後の target、Viewer first-page readiness、サイトにおける消費の正の証拠を確認。click が不確実なら二度押し禁止。安全な control / identity / success 判定が立証できなければ実際の消費に進まない。

**Gate:** DOM/API の観測証拠、Catalog identity の一致、72h の有効期間と23hの回復表示の区別、消費確認方法を `PROGRESS.md` に記録。Explorer → Reviewer の安全確認。

### Phase 02 — Discovery / SitePolicy / work-scoped candidates

**変更候補:** `site_policies/hanayume.py`、`site_adapters/hanayume/discovery.py`、関連 tests。必要性が証明された場合に限り共通 Batch の最小変更。

- SitePolicyに `supported_access_resources()`、`ordered_access_resource_passes()`、`grant_only_supported_access_resources()`、`resource_state_scope("work_ticket")=="work"`、`grant_only_skip_reason()`、`grant_only_retry_at()`、`access_grant_until()` を追加。
- `quota` 候補は `quota_scope="work"`、`quota_resource="work_ticket"`、`quota_commit_mode="after_observed_consumption"`。`free` は direct、当該話の未期限切れの grant も direct。`paid` は不許可。
- 観測済みの ticket バッジを適切に quota 判定。現行の無料ラベル判定は変更しない。古い unknown の扱いは明示的・限定的な候補 selection とクリック直前の厳格判定で対応する。未確認の候補を無差別に大量リクエストしない。
- Catalog上で work ごとに**1話だけ**選定し、選定済みの work ごとの順序で処理。正の ticket 適格証拠がない場合は当該 work を SKIP（次の話への連続探索は禁止）。
- 過去に消費を確定した work は **now < last_consumed_at+23h** で必ずローカルSKIP。直近の source grant は72hを超えて direct にしない。時間は tz-aware、境界・別 work・再起動をテスト。
- **Gate:** 単体テストで23h境界（22:59:59 SKIP / 23:00:00 pass）、72h期限（71:59:59 direct / 72:00:00期限切れ）、同作品の複数話、旧 Catalog unknown、Catalog-only skip の site network 0件。

### Phase 03 — Ticket entry / Viewer continuation / grant-only

**変更候補:** `site_adapters/hanayume/adapter.py`、必要なら同ディレクトリに小さな `live_access.py`、関連 tests。

- `configure_run`、`configure_quota_resource`、`get_access_consumption`、`initialize_entry_only` を実装。quota entry を今の `initialize` の Viewer 初期化に最小限接続。
- 選んだ話の URL と Catalog work/episode を再照合。対象話内の唯一の ticket control を検証。Click 直前にフラグを立てて1回のみ操作。
- クリック後は site が開いた**同じページ**で 1ページ目の Viewer ready を待つ。閲覧解放と ticket 消費を**正の証拠**で確認して `AccessConsumption(consumed=True,resource="work_ticket",consumed_at=...)` を確定。曖昧ならクリック再試行しない。
- 通常 Batch はそのまま現行 Hanayume の初期化 → Native/PNG Capture → END → ZIP。`grant-only` は entry 確認だけで終了し、画像・ZIPを作らず Item pending。
- 通常 Batch / grant-only とも過去のローカル23h記録で**ブラウザアクセス前 SKIP**。消費確定後に Viewer または ZIP が失敗しても消費記録を保持。
- **Gate:** Fixture で unique, missing, duplicate, hidden, disabled, paid, identity mismatch, delayed hydrate, click timeout, click succeeded but post-processing failed, interruption の全分岐。paid click 0回、再クリック0回、`/series/` request 0件。

### Phase 04 — Integration / real site / independent verification

1. `ruff check src tests`、`pytest`、`git diff --check`。Hanayumeの既存 direct/free、ComicDAYS・Zeblack の quota 関連に回帰がないこと。共通Batchを触れた場合は全 site policy の既存テスト。
2. **隔離DB/Watchlist/output/library**、共有ログイン済みChromeで `batch run --site hanayume --grant-only work_ticket --limit 1`。消費確定、sourceの72h grant、workの23h state、画像0・ZIP0・Item pending を監査。同作品で再実行し、**ページアクセス0件で SKIP** になること。既存 Catalog は破壊しない。
3. 別の未消費作品で通常 `batch run --site hanayume --limit 1`。**ticket click 後の同一Page**で本文先頭・中間・最後・ENDまで確認し、ZIP CRC、ページ順、lossless WebPの品質と Catalog completed を独立チェック。無料話の direct control を別途検証。
4. 必要な場合だけ複数作品を逐次実行し、作品Aの処理終了前に作品Bへの live request が0であること、同作品 ticket は1回、作品別cooldownが独立であることを確認。ユーザー提示の5件を上限目安とし、余分にticketを消費しない。
5. Reporter に OK（消費確認）、SKIP（23h、利用不可）、NG（消費未確認）を区別して記録。click 後の中断・capture failure でも使用事実を失わない。秘密・画像・signed URLをコミットしない。

**Acceptance:** Batch由来の作品ページ／全作品事前アクセス0件、作品ごとのticket消費最大1回/23h、ローカルskip時のsite request0件、72h grantは話単位、通常Batchは同じPageからEND/ZIP、grant-onlyはZIP0/Item pending。Reviewer と独立 Tester の検証が完了し、`PROGRESS.md` にSHA・コマンド・根拠・残リスクを記録するまで DONE としない。

## 5. 作業体制と更新先

既存 `AGENTS.md`、`docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md` に従う。Leadが仕様・Gateを管理、Explorer が read-only 調査、Implementer が唯一の production writer、Reviewer がバグ/セキュリティ/回帰を懐疑的に確認し、必要時に Tester が実サイト成果物を独立検証する。重大な BLOCKING は次ステージへ持ち越さない。

変更後は `src/screenshot_crawler/site_adapters/hanayume/README.md`、`note/10_hanayume.md`、必要な仕様authorityを同期する。元の `runbooks/hanayume-free` を今回の作業履歴で上書きしない。実装未確認の成果を PASS と書かない。

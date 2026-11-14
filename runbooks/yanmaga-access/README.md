# ヤンマガWeb 初回無料・待つと無料 実装 Runbook

**Status:** PLANNED / NOT IMPLEMENTED（2026-11-15）。
**Scope:** 既存 `yanmaga` の通常無料取得を維持しながら、初回無料（capture-only）と待つと無料（capture / grant-only）を追加する。
**Base:** `main` の `runbooks/yanmaga-free/README.md` の正常完了版。既存画像取得経路・厳格なEND判定は保持。
**実装ブランチ:** 作業開始時の最新 `main` から `feat/yanmaga-access` を新規作成する。ユーザーの未コミット変更は保持し、`main` へ自動マージしない。既存ブランチがあれば衝突を確認し、勝手に上書きしない。
**実施記録:** [PROGRESS.md](PROGRESS.md)。各Stage後に観測・差分・テスト・レビュー・コミット・未解決点を更新する。

## 0. 着手時のauthorityと参照実装

優先順位は `AGENTS.md` に従う：`docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/DISCOVERY_AND_BATCH.md`, `docs/ACCESS_CONTROL_AND_PACING.md`, `docs/TEST_STRATEGY.md`, 現行コード・テスト・site README。既存の `runbooks/yanmaga-free/` は「通常無料を壊さない」回帰仕様の基線であり、今回のRunbookはその消費禁止スコープを**新たな選択的無料開放フローに限って**拡張する。

特に読むこと：
- `src/screenshot_crawler/site_adapters/yanmaga/{discovery.py,adapter.py,native_capture.py,README.md}`, `src/screenshot_crawler/site_policies/yanmaga.py`
- `src/screenshot_crawler/site_adapters/magapoke/{discovery.py,adapter.py}`（既存Viewer入場、既存Grantを再消費しない、消費後のラッチ）
- `src/screenshot_crawler/site_adapters/hanayume/{discovery.py,adapter.py}`, `site_policies/hanayume.py`（作品チケット、手動Grant観測、消費不明時の停止）
- `src/screenshot_crawler/site_adapters/younganimal/adapter.py`（work_ticket / entry-only の補助例）
- `src/screenshot_crawler/batch/{planner.py,executor.py,grants.py}`, `src/screenshot_crawler/site_policies/base.py`, `src/screenshot_crawler/catalog/{models.py,schema.py,service.py}`
- 既存の `runbooks/hanayume-work-ticket/`, `runbooks/younganimal-work-ticket/` と `runbooks/yanmaga-free/PROGRESS.md`

前提となる**現行コード上の事実（作業開始時に再確認）**：Catalog `sources.access_mode` は `owned/free/quota/paid/unknown` のCHECK、`access_granted_until` と作品単位 `quota_resource_states` は既存。Yanmagaの現行Policyは `free/direct` のみ、Discoveryは未ログインの赤字「無料」だけを `free`、初回無料・`.by_wait`・有料を `unknown` にしている。Yanmaga Adapterは未ログイン前提の全一覧preflight後にViewerへ入り、native WebP / PNG fallback / END / ZIPを検証している。**ログイン済みのDOM・チケット開放フローは未実測であり、これらの既存セレクタをそのまま流用できるとは決めつけない。**

## 1. ユーザーと確定した要件

| 実サイトで証明したアクセス状態 | DB `access_mode` | 通常Batchの扱い | grant-onlyの扱い |
| --- | --- | --- | --- |
| 無条件・通常無料 | `free` | `direct`、そのまま取得 | 対象外 |
| **初回無料**（対象エピソード1回限り） | **`free`** | **`direct`、取得直前に初回無料を開放し、そのViewerで取得** | **対象外：絶対に開放しない** |
| 待つと無料（作品チケット） | `quota` | `work_ticket` がサイト上で使用可能な場合だけ消費・取得 | `work_ticket` のみ消費・Grant確認、画像取得なし |
| 開放済みで閲覧権限が有効 | 表示を根拠に既存modeを保持・更新（`free/quota/paid`のいずれもあり得る） | 既存Grantが有効で対象話の閲覧が実際に確認できれば**再消費なしのdirect** | 再消費しない |
| コイン・ポイントのみ | `paid` | 新たな支払い禁止。**既存の有効な無償Grant**が明確にあればdirectの再取得だけ可 | 対象外 |
| 未判定・矛盾・認証切れ | `unknown` | スキップ。曖昧なクリック禁止 | スキップ |

- **DBスキーマ変更なし**：既存の `access_mode`, `access_granted_until`, `quota_started_at`, `quota_resource_states` を必要な範囲で使う。`first_free` 等のDB列や新しいmodeは増やさない。
- 初回無料の開放後も `access_mode=free` のままでよい。開放時に `quota` へ変更しない。初回無料の開放は**作品チケットの消費として記録しない**。
- 初回無料の開放成功後、画像取得・END・ZIPが失敗してもItemは `pending`。権限が残る間は追加クリックせず、再取得できるようにする。再Discoveryすると実サイト表示に従い `quota` や `paid` へ変わり得る。**失敗時に自動Discoveryが走るとは仮定しない**。
- 初回無料は原則「取得と同時に開放する」ので、別途grant-onlyで初回無料を一括消費する機能は作らない。
- 待つと無料の回復期間は**23時間**。作品単位チケットであることと有効閲覧期間（23時間の回復とは別）はStage 01で実サイト再確認。新しいチケット枚数や日次上限を推測で追加しない。
- 一覧に初回無料が優先表示される想定だが、**正の実サイト証拠**を優先し、両条件が同時に見える場合はその場で優先順位を推測せずStage 01で検証する。
- Paid/コイン/ポイント購入、広告視聴による強制取得、認証回避、DRM・アクセス制御回避は対象外。

## 2. 実装契約

### 2.1 分類と保存（DBを増やさない）

アダプター内部の観測型（例：`public_free/first_free/wait_free/active_grant/paid/unknown`）を使い、Catalogへの写像だけ `free/quota/paid/unknown` とする。内部型はdataclass/Enum等の単純なsite-owned値にし、共通Catalogのmodeを拡張しない。

**Discoveryは観測のみ**。全話リストの「もっと見る」、work+episode identity、canonical、完全性、並び、`global_display_position`、既存の未ログイン赤字無料の証拠を保持する。ログイン中のDOMと認証の正の根拠を新たに観測し、未ログイン用analytics telemetryをログイン済み判定の必須条件に流用しない。ログイン有無・マーカーの競合、初回無料と待つと無料、明確なポイントのみ、すでにレンタル中/開放済み、unknownを別々に検証する。HTML文字列部分一致や色だけでの判定禁止。

`access_granted_until` は正のサイト情報（絶対時刻または検証済み残時間の安全側下限）で同期する。期限不明で現在Viewerが開くこと自体を期限の証拠にしない。ローカルで推定する場合はサイトの既知の契約と安全側の時刻計算が明確なケースに限定し、推定値とサイト観測値を区別する。期限の実測がなければDBへ架空の値を書かず、**再実行時にLive Reader可否を判定できるようにする**。Discoveryによるmode変更でも、期限が未観測であれば既存の有効Grantを無条件に消さない（`CatalogService.refresh_discovered_source` の現行規則を確認）。失効が確実なら消去・無効扱いの要否を検討する。

### 2.2 captureのdirect（通常無料＋初回無料）

`YanmagaSitePolicy.evaluate` が `free` を `direct` とする構造は維持。対象話のfresh preflight→episode入場で、次の順に判定する。

1. **同じwork/episodeの有効Viewerが既に見える**：開放操作を行わず続行（繰り返し取得時も含む）。
2. **赤字の通常無料が一意で確認できる**：現行のdirect入場処理を維持。
3. **「初回無料」操作だけが一意に確認できる**：ログイン/対象話/無料操作ボタン/クリック直前状態を再検証し、最大1回だけ通常UIをクリック。Viewerの同一話identityと本文のアクセス可能状態を正に確認してから取得。
4. **待つと無料/ポイント/認証不足/矛盾/上限ゲート**：directでは代替消費しない。対象話をskip/fail-closedし、再Discoveryを促す。

クリックがタイムアウト/例外/取消された場合は2回目を押さず、有限のread-only照合で閲覧権限が付いたか判定。クリック後の成功/失敗を画像保存成否から推定しない。同一PageのViewer、native capture、PNG fallback、完全END、Manifest/ZIP/Completedを維持。**初回無料Grantの記録は成功した開放直後に行い、後続のキャプチャ失敗でも残す**。ただし直後にGrant記録できない／記録有無不明のケースでも、サイト側で閲覧可否を再検証できること。

### 2.3 quotaのwork_ticket（23時間）

`YanmagaSitePolicy` に `work_ticket` のsupport/ordered/grant-only/works scopeと、適正な`after_observed_consumption`を導入。`quota` の候補は作品単位（1作品1回の消費可能枠、同時に複数話に消費しない）。最後の**確定消費**時刻から23時間以内なら、通常Batchとgrant-onlyは作品単位でローカルSKIP。サイトがチャージ済みを表示しなければ、ローカル時間だけで押してはいけない。期限切れ・disabled・ログイン不可・別資源しかない場合はSKIPする。

Viewerが既に当該話で閲覧可能なら**新たなticketを消費せず**direct扱いで取得。チケットを消費する場合は対象エピソード・無料ボタンを1回だけクリックし、正しいViewer/サイト由来Grant変化を観測。`AccessConsumption` を消費確定後にラッチして、通常Batchの画像取得やZIPで失敗してもCatalogの`source` + 作品resourceへ記録する。消費不明なら再クリックを禁止し、`resource_consumed` を真と偽に誤分類しない。

**grant-onlyの対象は`work_ticket`のみ**。0画像・ZIPなし・Itemはpending。既存Grant済み話ではチケットを使わず、成功した消費として記録しない。

### 2.4 初回無料のGrantをDBに記録する際の注意

初回無料は `direct` であり、現在の `BatchExecutor._record_observed_resource_consumption` は `candidate.quota_resource` がある `quota` 向け。**初回無料の開放をquota経路へ流用すると、`work_ticket` の消費時刻/冷却期間を誤記録するリスクがある**。そのため、site-ownedの開放結果を既存の `access_granted_until` に反映する最小API/フックを必要時に追加する。Catalog更新は「対象Sourceのみ」「本人が同一話の権限を正に確認」「既存値を安全に保存」が前提。AdapterからCatalogへの直接write、RunnerへのCatalog依存、site名でのCore特別扱いは避ける。Stage 02で既存の安全な拡張点を先に探し、必要な時だけ小さな共通hookを追加する。

既存の有効Grantが残り `access_mode=quota` や `paid` に変わっても、期限内かつサイトで閲覧可能と証明できれば `direct` 再取得を認める。**有料のmode自体を「無料で閲覧できる権利」に読み替えてはいけない**。期限なしの曖昧な状態から支払いボタンへ進まない。

### 2.5 候補順と安全性

作品・話数のcrawl順を維持し、通常無料と初回無料を同じ`direct`として扱う。作品チケットは既存Plannerのwork quota分離・1作品1枠ルールに従う。`BatchPlanner` はwork quotaをdirect群の後に配置し得るので、**全候補で完全な交互順になると断言しない**。現行planの具体的順序をStage 01で検証して、既存の通常Batch運用に合わせる。必要ならsite-owned `batch_ordering` で最小変更し、全体Plannerの並べ替えには踏み込まない。次話への自動移動や他作品の先読みで追加資源を消費しない。

共通のAccessGuard、pacing、HTTP403/429、CAPTCHA/CHALLENGE停止、有限timeout/retry、output競合保護、success Artifact/Completedの原子性は保持。未知状態では明示理由でSKIP/失敗にし、成功扱いしない。

## 3. Stage契約と通過条件

| Stage | 実装内容 | 次StageへのGate |
| --- | --- | --- |
| [01 調査・Discovery](01-site-probe-discovery/README.md) | 読み取り専用実サイト調査、認証状態、マーカー/Grant、分類実装、plan順の監査 | 主要状態を正しく分類／不明はunknown／既存匿名無料・全件Discovery回帰なし。**消費操作0** |
| [02 初回無料](02-first-free-capture/README.md) | direct時の初回無料開放、既存Grant復旧、必要最小のGrant保存経路 | 無料開放1回→END/ZIP/Completed、失敗後再取得、grant-only除外、誤消費0 |
| [03 待つと無料](03-work-ticket/README.md) | work_ticket、23h cooldown、captureとgrant-only、実測消費記録 | 作品枠・チャージ・Grant・再試行安全性、消費/失敗の区別 |
| [04 統合E2E](04-e2e/README.md) | CLI end-to-end、独立監査、リグレッション | 3経路の実サイト/モック根拠、END/Manifest/ZIP/Catalog一致、Reviewer BLOCKING 0 |

Stage 01 は対象話・アカウント・表示が揃わなければ **PROBE BLOCKED/NOT VERIFIED** と記録する。根拠がないままクリックセレクタを仮実装しない。Stage 02/03では実際の無料権利を使う**都度**、対象作品/話と消費可能回数を事前に決め、専用環境で有界に検証する。最低限のサンプル消費で十分な根拠を取る。機能別レビューを挟み、レビューでBLOCKINGが残る次Stageへの進行は禁止。

## 4. 作業範囲、環境、報告

優先変更箇所：
- `src/screenshot_crawler/site_adapters/yanmaga/{discovery.py,adapter.py,README.md}`、必要な小さな補助コード
- `src/screenshot_crawler/site_policies/yanmaga.py` とsite固有テスト
- **根拠が揃った時のみ**Catalogの既存Grant記録・Batchの連結用最小hook
- `note/14_yanmaga.md`（現状に同期）、`runbooks/yanmaga-access/PROGRESS.md`
- 必要範囲のUnit/Browser Integration/E2Eテスト。共有CLI・Planner・Schema・画像Coreの無関係な変更は避ける。

実サイト操作：共有Crawler Chrome/CDP（Playwright Page/Locator）、専用 `output/yanmaga_access_experiment/` 以下のWatchlist/Catalog/Books/outputを使用。通常Catalog、他サイト作品、認証profile、既存ZIPを汚染しない。実ブラウザ操作者は同時に1名。Cookie/Token、署名URL、スクリーンショット本文、HTML全体、個人情報・機微な通信データをGitへ入れない。実測ノートは時刻・状態・要素名・匿名化したID・件数のみ保存。

Leadは各StageにExplorer（read-only調査）、Implementer（唯一のproduction writer）、Reviewer（変更diffの独立レビュー）、必要なTester（独立E2E）を割り当て、並列化は読み取り調査のみ。実際に使用可能なエージェント/モデルを確認し、利用不可なら人間が追える記録と同じGateを守って進める。

**Definition of Done:** 既存無条件無料に回帰なし。初回無料のcapture成功と失敗後の閲覧期限内再取得を実証。待つと無料の通常Batchとgrant-onlyの消費確認・作品cooldownと同一話Grantを実証。未知・有料・二重クリック・期限切れは安全にSKIP。正常END→ページ欠損なし→ZIP/Manifest/Artifact/Completed一致。テスト結果、実証できなかった条件、独立ReviewerのBLOCKING 0をPROGRESSへ記録。実サイトの権利消費ができない場合は **Unit PASS / Live NOT VERIFIED / Overall NOT DONE** を分けて報告し、成功したことにしない。

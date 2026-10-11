# Phase 05 — 「待つと無料」 state / waiting / Batch

Status: DOCUMENTATION / UNKNOWN-ONLY CLASSIFICATION; wait flow NOT IMPLEMENTED. Official documentation is not live state evidence. No waiting, grant, entitlement, or resource action has been performed.
Prereq: Phase 02までの作品一覧/ラベル契約、Phase 03/04で確立したViewer/Batch。
Next: [E2E](../06-e2e/README.md)。

## Goal
正規の`待つと無料`を、**未開始 / 待機中 / 閲覧可能 / 期限切れ**
の実態に従ってDiscoveryし、適正なタイミングで通常のBatchから取り込む。
サイトが提供する機能を実測するまでstate名や値を推測しない。

## Step 1 — Observational contract
- 正確なrow badge、CTA、account状態、target ID、timer/remaining、grantの始点/終点、
  待機scope（作品/話/ユーザー）、同時待機数、リセット条件、実際のViewer入口を調べる。
- 共通IDのHanayumeとYounganimalは**別セッション**。各siteのpositiveログイン証拠を確認。
- 「待つと無料」が現在見当たらない場合、数作品/別episode/認証状態をboundedにProbe。
  別機能（`今なら無料`/ticket/rental等）を同一視しない。
- 偶然読めるViewerや過去grantだけでは「未開始からfree」と分類しない。
- **待機開始が資源/チケット消費に該当するか**、最初のクリックやURL navigateだけで
  状態が変わるかを確認。観測目的のクリックは、別の安全契約を満たすまで禁止。

## Step 2 — Chosen implementation contract
Evidenceにより次の正規経路のうちsupportedなものを設計する:
- **現在readableな非消費direct**: verified current state、対象話一致、
  自動で待機開始をしないReader入場と保存。
- **無料待機の開始が必要**: 実サイトで**料金/チケット/ポイント等の消費が無い**
  通常の無料待機開始とpositively検証できた場合だけ、意図した一つのactionを
  site-local Adapterに追加し、操作1回・結果確認・二重開始防止・その後の
  再計画または後日ready判定を実装する。
  liveでの初回待機開始テストも**有界で、非有料・非チケットの対象1件**に限定。
  もしユーザーresourceを消費する、既存権利を破壊する、または実条件が不確かなら
  実操作を止め、必要な明示的判断を依頼する。
- **待機中**: 再クリック/連続消費せずpendingを維持。将来のBatchでreadyに変わればdirectで取得。
- **期限切れ**: 既存grantと実サイトのcurrent状態を照合し、不正なdirect保存や重複消費を防ぐ。

既存Catalog `access_mode`、`access_granted_until`、`SitePolicy`、
resource selection/consumptionの契約に合うと**実証できた場合のみ**利用。
「待つと無料」のための独自共有DSL、Comici ticket abstraction、
安易なschema migrationを作らない。
Catalogに表現できない本当に必要な状態だけ最小提案としてLeadが審査。
既存generic resourceの意図と一致しないときはsite-local orchestrationで対応する。

## Safety and test matrix
- チケット・コイン・ポイント・購入・別resourceへの暗黙fallbackは禁止。
- 行identity・現在の待機/閲覧状態と操作対象を二重確認。
  曖昧なCTA、個数不明、複数候補、URL drift、error response、課金表示なら停止。
- Unit: free/wait-not-started/waiting/ready/expired、誤分類、
  stale Catalog、再試行による二重開始防止、grant未確定の未完了維持。
- Browser integration: 正規の無消費wait開始（合成ページ）→待機中→ready→direct取得、
  不正ボタン/有料混在/条件変化/1回クリックだけを確認。
- Live: 権利消費を伴わない正規対象が見つかるなら、
  normal Batchからの対応可能な待機状態の取得を確認。
  途中の実時間待機を短縮/偽装しない。ready実例が無ければwaitingはNOT VERIFIED。
- Reviewer/TesterはResource/Grant記録、非free誤入場、
  有料/チケット操作ゼロ、completed Item / Artifactの正当性を独立確認。

Exit: supported free+waiting契約をREADME/note/PROGRESSに記載。
**freeだけ通ったことを「待つと無料を実装済」と言わない**。
待機対象や検証可能な状態が実サイトに無ければ、可能な範囲の
read-only分類と合成テストまで実装し、実際の欠落gateを分離して報告。

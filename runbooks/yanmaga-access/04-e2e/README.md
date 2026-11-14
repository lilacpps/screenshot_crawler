# Stage 04 — 統合E2E・回帰・独立レビュー

**Status:** NOT STARTED
**前提:** Stage01〜03の独立Reviewer BLOCKING 0。チケット操作の事前観測で正しい作品・話・リソースが証明されていること。既存 `runbooks/yanmaga-free/05-e2e/README.md` の出力監査方法を踏襲。

## 1. 実行隔離と準備

- 実装コードは `feat/yanmaga-access`。ベースは作業開始時の最新main。旧実装ブランチから進めない。
- 専用 `output/yanmaga_access_experiment/` のWatchlist/SQLite/output/Booksだけを使う。他サイトの状態、通常Catalog、既存ZIP、共有login profileを改変しない。
- 起動前に `python -m screenshot_crawler.cli --help`, `discover --help`, `batch --help`, `batch run --help` を確認し、CLI引数を実装時点に合わせる。下記は意図する通常フローであり、CLI対応・実行済みを主張しない。
- 共有CDP Chromeを操作するのは同時に1 agentだけ。最少の実サイト権利消費で検証を行う。クリック直前に同一作品/話/チャージ/無料を再確認。
- 本文画像、認証情報、Cookie、token、署名URL、サイト内部JSON全体はGitに残さず、匿名化されたテスト結果のみコミット。

## 2. E2Eシナリオ（独立Testerが確認）

### A. 従来の通常無料の非消費回帰

最新の赤字通常無料話を選び、`discover full → incremental → batch plan → batch run` で一切チケットを押さずに本文全ページ→END→Manifest/ZIP/Completed。匿名状態とログイン済み状態で可能な範囲を確認。すでに完了したArtifactのhash/Statusを再Discoverが壊さない。

### B. 初回無料をcaptureで使う

初回無料の未使用話を**明示的に1件**選び、`free/direct` としてplanされること、初回無料を正の根拠で**1回だけ**開放し、同じ話のViewerから全ページ→END→ZIP/Completedまで進むことを確認。`quota_resource_states` は変化せず、`quota_started_at` も誤記録されない。grant-onlyを実行してもこの話を開放しない。

### C. 初回無料後の失敗と復旧

実サイトでの必要な権利消費は1回で済むよう、1回の開放後に**後続capture/END/packagingの失敗だけをテストで注入**。Item pending、Sourceの確定Grant情報維持、二度押し0、再Discoverあり/なしの復旧を確認。初回無料が後から `quota` 又は `paid` 表示へ変わった場合にも、同一話の有効Grant期限中は`direct`で再取得できる。失効・権限不明はSKIP。意図的な画像破損や実サイトへの再請求で失敗を作らない。

### D. 待つと無料の通常Batch

初回無料と異なる適格なチケット対象話・作品を選ぶ。残り23hの回復が完了した状態のみ、1クリック・positive消費確認→同じ話のViewer→全ページ→END→ZIP/Completed。work-scoped最終消費時刻、Source Grant期限が保存される。消費後の別話は23h未満に再消費されない。本人が既に開放済みなら追加クリックなし。

### E. 待つと無料のgrant-only

別の適格作品等の独立資源を使用（同一workの23h制限を破らない）。`batch plan/run --site yanmaga --grant-only work_ticket`（実際のCLI syntaxはhelp確認）で、対象は`quota`のみ、1回のgrant確認とwork state記録、ページ/ZIP/Artifactなし、Item pending。初回無料・通常無料・ポイントのみは非対象。次の通常Batchで権限内なら画像取得できる。

### F. 消費状態の失敗モード

fixture/テストダブルを使い、クリックは実行されたがUI/ネットワークが曖昧、サイトエラー、ログアウト、作品/話drift、期限切れ、他資源のみ、ZIP失敗を再現。二度押し・ポイント操作0、確定消費だけ記録、未確定消費で再試行しない。実サイトへの必要ない試し押し禁止。

## 3. 成果物と状態の監査

1. 対象話のwork/episode ID、URL同一性、開放前/後状態、対象ボタンの一意性、消費回数、残りGrantとcooldownを匿名化して照合。
2. ページ1/中間/最終のpixel整合性・サイズ・形式、本文ページ数、重複、順序、見開き、Native WebP→fallback判定、広告・他話混入なし。実サイト本文は非コミット。
3. positive ENDが成立すること（単なるtimeoutはNG）、Manifest全pageとZIP member数/形式/順序、ZIP CRC、Artifact SHA-256/byte_size、Completed timestamp/成功CrawlRun。
4. 失敗したらItem pendingでsuccess Artifact・Completedなし。**消費済み/開放済み**の記録だけが成功した権利操作として保持される。
5. 再Discover後もSource ID、Work、display_position、Archive/Completedの履歴保持。アクセスタイプが`free→quota→paid`へ変わってもViewerの有効Grantの再取得が安全にできる。
6. `ruff check src tests` と `git diff --check`、変更に関係する単体/Browser Integration/Batch Planner/Executor/CLI/Catalog、既存通常無料と他のticket-siteの重要回帰テストを実行。重いfull suiteは `docs/TEST_STRATEGY.md` に基づき必要な範囲に限定。

## 4. 完了宣言

- 変更diffはLeadと独立Reviewerが照合し、**BLOCKING 0**。
- サイトの表示を前提にした実サイトE2EでA/B/D/Eの根拠を示す（利用可能な権利数の不足等なら個別にNOT VERIFIED）。C/Fは再現性のあるfixture/失敗注入で網羅。
- スキーマ/共通Coreの不要な変更が無いことを監査。site README、`note/14_yanmaga.md`、関連authorityを現行仕様に同期。
- `PROGRESS.md` に実測日時、テストコマンド/件数/失敗数/skips、消費資源の正の証拠、ZIP/DB状態、変更commit、未確認点を記載。
- **全条件を証明できなければDoneと言わない**。Unit PASS / Integration PASS / Live NOT VERIFIED / Overall NOT DONEを明示し、site障害や未提供のチャージに対する推測の成功判定を禁じる。

最終報告には実装ブランチのcommit/差分範囲と、ユーザーが自分の通常DBで実行する前に必要な操作（ログイン済みCDP、Discovery、plan確認、正常Batch、grant-only実行方法）を簡潔に載せる。mainへの自動mergeは禁止。

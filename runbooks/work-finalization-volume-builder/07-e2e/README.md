# Phase 7 — 統合・実作品検証
開始: Phase 0–6のcheckpoint。Leadが受入、Tester/Reviewerが独立検証。実運用への適用はユーザー判断。
- GUIのWork行→一覧→検索→参照抽出→自動境界→手動修正→plan→apply→完成品とmanifest検証。巻のみ、話のみ、複数site、話巻混在、Piccoma非掲載、曖昧な境界、途中巻、既存品再生成を人工ZIPでE2E。DB/Watchlist/入力/他Work不変。故障注入・並行job・古いplan・キャンセル・復旧待ちをPhase 3と整合確認。
- Phase 0の作品に加え、既存watchlistから合計30–50作品程度（可能な範囲、出版社/長短/取得元を分散）で読み取り専用メタデータ評価。実データの取得や変更は行わない。独立に確認した巻開始位置を正解として、作品特定率、巻境界取得率、境界自動照合率、誤自動確定数、未解決理由を分母付きで記録。正解を確認できない例は別集計し、目標値や未確認を実測と混同しない。誤自動確定があれば条件を狭めて再検証。実サイトが利用不能ならPARTIAL/BLOCKED、手動経路の成功と分ける。
- TEST_STRATEGYに沿いtargeted→affected（GUI、renumber/audit、Catalog、Watchlist、Piccoma、deletion/job）→必要なintegration→必要時full suite/live。ruff check src tests、git diff --check。未実行・skip・失敗を報告。ユーザー環境の設定・本番Catalog/Watchlist/ZIP変更なし。
- docs/SPEC.md、ARCHITECTURE.md、GUI_README.md、BOOK_NAMING_RULES.md等の必要部分、note/00_core.md・Piccoma noteを実装に同期。操作手順、出力・手動fallback・再生成・復旧、制約を記載。今回の生成完了をarchived/終了確定と混同しない。
出口: 親Runbookの最終受入と独立review BLOCKING-0、全checkpoint記録。実サイト未検証が残る場合は明示して完了範囲を限定。変更ファイル、テスト、計測、運用制約、次の終了処理に渡すmanifest契約を最終報告する。

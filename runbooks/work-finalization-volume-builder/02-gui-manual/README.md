# Phase 2 — 終了処理GUIと手動巻境界
開始: Phase 1の共通モデル・入力一覧。ImplementerがPySide6 UI/Service接続、Reviewerが状態管理を検証。
- MainWindowのWork行右クリック「作品の終了処理」。work_key/作品名を固定し、巻統合・完成品生成タブのみ実装。未実装機能を動作可能に見せない。
- 取得順ZIP一覧、巻の開始位置の追加/削除/変更、実巻番号の入力、既存巻の表示、プレビュー（開始/終了話、ZIP数、ページ数、未割当/欠損/衝突、処理種別）を用意。巻の間の番外編は前巻。先頭/末尾未確定範囲は明示割当または除外の承認が必要。巻のみはコピーplan。
- 保存/再読込はatomic JSON。work identityとsnapshotをbindし、renumber/recrawl/削除再登録等で古い境界が無効になる場合は通知。手動境界を保存して保持。未保存変更・古いplan・busy・エラーを表示し、生成はPhase 3まで無効。Workerは既存GUI方式。
受入/テスト: offscreen QtでWork選択、他Workへの切替、範囲・実巻番号編集、保存/再開、手動fallback、未解決/重複/欠損時の生成禁止、古いplan失効、キャンセル/閉じる。既存GUI archive/deletion回帰。BLOCKING-0でPhase 3へ。

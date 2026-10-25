# Stage 00 — 現行契約監査と境界設計

> Status: **COMPLETE / REVIEW APPROVED**。実行結果は [PROGRESS.md](../PROGRESS.md) を参照。以下は実行契約。実装は行わない。開始HEAD/branchと並行`gui-live-monitor`を確認。

## Objective / 入力
`AGENTS.md`、`docs/SPEC.md`、`docs/ARCHITECTURE.md`、`docs/BOUNDED_DISCOVERY.md`、`docs/DISCOVERY_AND_BATCH.md`、`docs/TEST_STRATEGY.md`、`watchlist/{models,service,fingerprints,reconcile}.py`、`discovery/{base,service,models}.py`、`catalog/{models,service}.py`、`gui/{main_window,model,details}.py`、Magapoke discovery、関連テストを照合する。

1. 現行Full・IncrementalがCatalogと`acquisition_enabled`を書き込むタイミング、proof invalidation、scope-syncの別apply、Batchのfail-closedを経路図にする。
2. 未登録除外・既存同key除外・他key所有除外・異site同work・複数scope境界のbefore/after表を作る。**同サイト他keyのSourceを奪わない**ことを明示。
3. Magapokeのlisting取得が本当に無副作用のread-only previewとして再利用可能か確認する。認証/CDP、DOM展開、real-site access、`capture_complete_listing_inventory` と `discovery_scope` の影響を調べる。他Adapterへ先に一般化しない。
4. プレビューと正式applyの差（未Catalog話、旧Full proofのfingerprint相違、archive position未知）を定義する。「予測」と「同期可能」の表示語彙を分ける。
5. GUI Live Monitorとの所有境界を決める。UI上部の既存状態、job/store、選択key/checkboxの用途を保持。
6. コメント付きYAMLの構造編集方針を決定。安全なsource-span patchとround-trip YAML libraryのトレードオフ（注釈/未知キー保持、依存増、差分、race）を検証し、**silent rewrite禁止**を固定。

## Deliverables / tests / exit
- 動作別matrix（legacy /連続/穴あき/空/他key/新話/証拠不在）、API/DTO案、preview no-writeのテスト方法。
- 実Catalog/Watchlist/ZIPを使わずsynthetic fixtureの最小セットを決める。
- 説明できない重要挙動があれば次Stageへ進まず調査し、`PROGRESS.md`に記録。Stage00はコードを書かず完了可。

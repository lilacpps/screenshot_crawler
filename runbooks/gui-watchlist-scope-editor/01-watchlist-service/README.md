# Stage 01 — Watchlistモデル・編集API

> Status: **COMPLETE / REVIEW APPROVED**。実行結果は [PROGRESS.md](../PROGRESS.md) を参照。以下は実行契約。Stage00の設計固定とHEAD再確認が前提。

## Objective / 変更範囲
対象: `watchlist/models.py`、`service.py`、`fingerprints.py`、関連Unit/CLI（必要なら）。**Catalog schemaやAdapterはこのStageで変えない**。

1. `DiscoveryScope.excluded_external_ids: tuple[str,...]` を追加。既存フィールド/legacy意味を維持し、`excluded_external_ids`のみのscopeを許可。空リストは正規化して未指定扱い。重複・空文字・非文字列は拒否。文字列はsite-native IDとして不必要な数値変換をしない。
2. `WatchlistService.update_target`、`update_work_archive_order`、`add`のscope指定、`preview_edit`相当の非書込み検証を設計。操作はkey単位、`archive_order`のみwork_key全体でatomic更新。`work_key/key/site`変更は初期GUIでは不可（別の所有権移管機能を生やさない）。
3. YAMLをparse→write→再parseしてtarget集合が完全一致すること、既存の関係ないデータ・コメント・未知キーを勝手に消さないこと。コメント付き構造編集を無変更拒否に留めるならGUI編集要件を満たさないため、Stage00で決めたlossless writerを実装。壊せない形は明示エラーにする。
4. 読込時/保存直前にファイルdigest等の期待versionを比較するoptimistic concurrencyと、atomic replace/flush/必要なファイル保護を実装。競合は再読込・再プレビュー要求。プロセス/Jobロックと永続書き込み順序を一致させる。
5. `target_scope_definition`、work/scope fingerprint、保存済configuration JSON復元の全経路で新除外集合を含める。旧設定と新設定の一意なcanonicalization、旧`configuration_json`を読めること。`enabled`/`label`変更だけでは不要なFull proofを破壊しない既存仕様を維持。
6. いずれの編集もここでは`ScopeReconciler.apply`、Discovery、ZIP renameを起動しない。

## Tests / acceptance
- 旧YAML/未指定/空リスト/`excluded_external_ids`のみ/境界付き/ID順序入替/日本語ラベル/コメント付き/未知キー保持のparse→update→read。構造編集後のbyte-level非対象span不変性を可能な限り検証。
- 増減・key重複・archive_order全キー検証、編集version競合、同時編集、invalid YAML・write失敗で元ファイル保持。
- 変更前後のfingerprint同値性（除外リスト順序違い）・差異（除外ID追加/削除）・旧configuration round-trip。
- `tests/unit/test_watchlist.py`等、CLI/GUI既存回帰。失敗時に部分書込なし。独立Reviewerで安全な永続化を確認してExit。

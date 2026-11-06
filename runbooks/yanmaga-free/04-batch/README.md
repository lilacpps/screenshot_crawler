# Phase 04 — Free-only SitePolicy と標準 Batch 統合

**Start:** Phase 02でCatalogの`free`が安全に識別でき、Phase 03のViewer/Capture/ENDが対象無料話で動作する。
**担当:** Lead → Implementer単独writer → Reviewer。共通Core変更は原則禁止。

## Goal / Change boundary

`src/screenshot_crawler/site_policies/yanmaga.py` と`site_policies/__init__.py`、`src/screenshot_crawler/cli.py`の既存4registry、Policy/CLI/Batchテストを実装。新サイト固有のfree-only Policyだけを設け、既存Planner/Executor/packaging/Artifact管理へ接続する。

## Policy contract

- site keyは`yanmaga`のみ。`source.site != yanmaga`、`available=false`、非`free`、不正な日時、期限が確認済みで切れた`free_until`は不許可。
- `available=true`、`access_mode=free`、実際に期限内なら `PolicyDecision(True, "direct", "free")`。期限がない公開freeは`free_until=NULL`のまま許可できるが、**NULLだけで無料だと推定しない**。
- `quota`/`paid`/`unknown`/`owned`は必ずSKIP。既存Grant/手動アンロックの有無をBatch候補昇格に使わない。`quota_resource`・`grant-only`・daily reset・resource/cost管理をv1に追加しない。
- Batch実行直前にAdapterが対象と同一episodeの現在の無条件公開freeをpositiveに再確認する。Catalog上でfreeでも当日は有料/不明だった場合、チケット/ポイントをクリックせずcandidateをSKIPする。状態不明のクラッシュや本体取得失敗はFAILED/pendingのままで、誤ってcompletedにならない。
- 成功は正しいbody→positive END→Manifest/ZIP/Artifactの検証完了後のみ`completed`。再Discoveryでcompletedを初期化せず、同じArchiveを二重作成しない。

## CLI wiring

現在の実装に合わせ以下へ`yanmaga`を登録:
1. `cli._registry`（manual）
2. `cli._discovery_registry`（full/incremental）
3. `cli._batch_adapter_registry`（run）
4. `cli._batch_policy_registry`（plan/run）

`site_policies/__init__.py`のimport/export、`watch add --site yanmaga`、`discover --key`、`batch plan --site yanmaga`、`batch run --site yanmaga`が実際のCLIでつながることを確認。`--limit 1`、`--catalog`、`--watchlist`、`--output-root`、`--library-dir`など既存引数を再利用し、新しい専用Batch commandを作らない。手動runとBatchでpreflightをすり抜ける経路がないこと。

## Tests / Review

- Unit: free/期限内/期限境界/失効/available=false/不正site/initial-free/ticket-free/paid/unknown/grant-only拒否。
- Planner: freeのsourceだけ`direct`、他はskip reason、複数work・completed itemを再選択しない、display position保持。
- Executor/browser Integration: fresh-freeでzip完成、preflight失効はskipで資源操作無し、unknown途中遷移・不正END・画像不整合・ZIP失敗はpending+no successful Artifact、既存Archive保持。
- CLI registry/Watchlist実装とNeighbor regressionは、変更した境界に従い`docs/TEST_STRATEGY.md`のtargeted+affectedを実行。
- Reviewer: access_resource導線ゼロ、別work誤選択なし、source URL/Manifest偽装なし、既存Catalog/他siteへの影響ゼロを確認。

**Gate:** 既存`batch plan/run`フローでfreeだけ選ばれ、1件の正常CaptureがZIP/Completedまで完了し、非freeや失効時に消費無しでskip、失敗時はpending、Reviewer BLOCKING 0。実サイトE2Eの最終独立監査はPhase 05で行う。

# Runbooks

This directory contains execution runbooks for bounded autonomous engineering work.

## Convention

Use one directory per workstream, then one ordered directory per substantial stage:

```text
runbooks/
  <workstream>/
    README.md
    01-<stage>/
      README.md
    02-<stage>/
      README.md
    03-<stage>/
      README.md
```

Rules:

- A runbook is an execution contract, not a general architecture document.
- Each stage should state starting evidence, objective, role assignment, constraints,
  acceptance criteria, tests/live verification, and exit conditions.
- Later runbooks may rely on earlier recorded evidence, but must identify the exact
  checkpoint they start from.
- Do not rewrite completed stage runbooks into current-state documentation. Current
  implementation truth belongs in `docs/` and `note/`.
- If a stage produces a durable specification or architecture decision, synchronize the
  relevant authority document separately.
- One workstream may end with "no production change required" when evidence does not
  justify implementation.

## Migration policy

Existing runbooks outside this directory do not need to move during an active work item.

Move them later in a dedicated documentation-only change after:

1. active branches depending on the old path are finished or updated;
2. all references in `AGENTS.md`, Codex prompts, and docs are known;
3. the move does not get mixed with production implementation.

This avoids noisy rename diffs and broken instructions during an in-progress investigation.

## Active workstreams

- [Piccoma free-only Site Adapter](piccoma-free/README.md) — five-role autonomous
  discovery/capture/direct-batch/E2E implementation contract (planned).
- [花とゆめ＋「無料」「今なら無料」Site Adapter](hanayume-free/README.md) —
  five-phase Discovery → source-faithful Capture → direct Batch → independent E2E contract (planned).

- [Young Animal Web — 無料・待つと無料 Site Adapter](younganimal-adapter/README.md) —
  independent-first implementation runbook: Discovery, original/native capture, free direct Batch, waiting-free and E2E.

- [ComicFUZ anonymous free-only Site Adapter](comicfuz-free/README.md) —
  logged-out public-free Discovery → Catalog → direct Batch → verified ZIP/E2E;
  charge/ticket/medal research and consumption deliberately deferred to a later phase.

- [花とゆめ＋ Work Ticket](hanayume-work-ticket/README.md) — 作品単位の23h回復、話単位の72h閲覧、direct episode entry、同一ページBatch、grant-only と安全な実サイト検証（planned）。

- [Work-key acquisition scope and cross-site archive ordering](work-key-archive-order/README.md) —
  既存discovery_scopeのCatalog取得担当フラグ同期、archive_orderによる複数key/サイト横断ZIP採番、
  grant-onlyを含むBatchフィルタ、安全な既存ZIP renumber（planned）。

- [Windows GUI — Inventory viewer P0/P1](gui-inventory-p1/README.md) —
  PySide6の閲覧専用Windows管理画面。サイト別/作品別ツリー、実Catalog v7の状態集計、
  話数/取得履歴の詳細、チェック選択。P1終了時にユーザーUIレビューで停止（planned）。

- [Windows GUI — P2 execution + P3 job management](gui-execution-p2-p3/README.md) —
  P1のチェック選択をDiscover/Batch/Grant-onlyへ安全に接続し、site別順次実行、
  事前確認、永続ジョブ履歴、進捗、協調停止・再実行を実装する計画。
  P2安全性レビューをゲートとし、P3完了後にユーザーUIレビューで停止（planned）。

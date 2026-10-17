# 花とゆめ Work Ticket — PROGRESS

**Status: NOT STARTED**（Runbook作成のみ。実装・チケット消費は未実施）  
Baseline: 2026-10-17 `main` / Hanayume free-only R9 PASS。

## チェックポイント
- [ ] Phase 01: Repo/Live read-only probe, safety review, 最少枚数での検証
- [ ] Phase 02: SitePolicy, Discovery candidate, work-scoped 23h cooldown, source-scoped 72h grant, **manual ticket grants in full/incremental Discovery and safe expiry refresh**, tests
- [ ] Phase 03: one-click entry, same-page normal Batch, grant-only, failure handling, tests
- [ ] Phase 04: integration, live E2E, separate Reviewer/Tester audit, docs sync

## 各段階で記録するもの
- Date / branch / source commit / result commit:
- Role (Explorer, Implementer, Reviewer, Tester):
- Observed DOM / ticket identity / proof, or remaining assumptions:
- Selected episode/work identifiers and **actual number of tickets spent**:
- Confirmed work cooldown timestamp and source grant expiry (auto vs manually consumed; absolute timestamp vs conservative countdown floor):
- Discovery full/incremental manual-used state, history/public row reconciliation, expired/unknown refresh semantics:
- Network audit: episodes vs `/series/` requests; site preflight count:
- Manual ticket -> Discovery -> batch direct (no second ticket click), Viewer first→END:
- Same-page automated ticket Viewer first→END, output hashes/ZIP/Item status:
- grant-only page count 0 / ZIP 0 / pending Item:
- Test commands and results / BLOCKING / next action:

**注意:** ユーザーは5話のチケットを必要に応じて利用してよいと許可しただけで、5枚の消費を義務づけていない。試験で消費が曖昧な場合は、再クリックせず正確に報告する。

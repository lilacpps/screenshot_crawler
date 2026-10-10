# Phase 04 — Free-only Site Policy / Batch integration

Status: NOT STARTED。前提: Phase 02 Discovery、Phase 03 Viewer/Captureの独立Review通過。
次段階: [E2E](../05-e2e/README.md)。

## 目的
既存Catalog/Planner/Executor/Runner/Packagerの標準経路で「無料」「今なら無料」両ラベル由来の
freeなsourceだけを**direct-only**実行対象にし、正常終了でのみZIPとcompleted Itemを作る。

## 実装契約
- 花とゆめ＋ Site Policy を最小限のregistryに追加。Catalog available=trueかつ
  access_mode=freeのcandidateだけをdirectへ。quota・paid・unknown・owned・
  grant・rental等は非対象。quota resource/消費/purchase/後続grant passを実装しない。
- Plannerはnative順序とwork-global positionを尊重。既存的な重複取込/skip/completed処理を維持。
- Execution前に対象site/作品/話のcanonical identityとfresh freeラベルを確認。
  失効・矛盾・redirectはcapture/ZIP/完了更新なしでfail closed。何らかのgrant状態が
  既にあることを理由に非freeを昇格させない。
- 標準BatchはCrawl Requestを作り、元のsource URL/metadata/読書順を壊さない。
  source-native jpeg/webp/pngとfallback PNG・lossless WebPをManifestが正しく識別し、
  完了したmemberだけPackagerがまとめる。
- Archive hash/size、Catalog item status=completed、succeeded END run、
  Artifact関係は**ZIP/packaging成功時のみ**更新。途中停止やchecksum failureはpending。
- existing Core/Batchにサイト名分岐を導入しない。必要な登録だけ差分追加。

## Test matrix
- Unit: 両freeラベル起源sourceのdirect採択（Phase 02 classification前提）、
  nonfree/unknown/expired/live mismatch skip、no quota mutations、stale Catalog、completed skip。
- Integration: local fixtureの完全なDiscovery→Catalog→Planner→Executor→Runner
  →Manifest→ZIP→completed経路、失敗時pending/no ZIP/no Artifact、
  external_id違い、redirect、未確定END、画像形式混在。
- CLI smoke: site registration、watch add / discover / batch plan / batch run が
  site keyと隔離パスで使用できる。
- Reviewerは権利消費・不適切な無料昇格・source衝突・誤完了・
  manifest範囲外ファイル混入・他サイト共通部への回帰を優先監査。

## Exit
normal Batch/isolated Catalogで既存統合テストを通過し、Reviewer BLOCKING 0。
実サイトをまだ使っていない場合は「live Batch NOT VERIFIED」とPROGRESSへ記録し、
Phase 05で独立検証する。全pytestは変更面積とdocs/TEST_STRATEGY.mdに従って判断する。


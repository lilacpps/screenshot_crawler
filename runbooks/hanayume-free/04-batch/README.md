# Phase 04 — Free-only Site Policy / Batch integration

Status: Direct-only Phase 04 integration and R3/R4/R5 corrections passed independent review. The final logged-in standard Batch E2E completed four authenticated/ordinary-free candidates with END and four verified ZIP artifacts; no quota or entitlement state changed. Final independent review PASS / BLOCKING 0.
次段階: [E2E](../05-e2e/README.md)。

## 目的
既存Catalog/Planner/Executor/Runner/Packagerの標準経路で、現在 `access_mode=free` として
確認されたsourceだけを**direct-only**実行対象にし、正常終了でのみZIPとcompleted Itemを作る。
The original logged-out baseline kept `今なら無料` as `unknown`; current runs may include it only when the fresh same-work listing proves the positive authentication markers.

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
- Unit: Phase 02でfreeに分類されたsourceのdirect採択（「今なら無料」はunknown）、
  nonfree/unknown/expired/live mismatch skip、no quota mutations、stale Catalog、completed skip。
- Integration: local fixtureの完全なDiscovery→Catalog→Planner→Executor→Runner
  →Manifest→ZIP→completed経路、失敗時pending/no ZIP/no Artifact、
  external_id違い、redirect、未確定END、画像形式混在。
- CLI smoke: site registration、watch add / discover / batch plan / batch run が
  site keyと隔離パスで使用できる。
- Reviewerは権利消費・不適切な無料昇格・source衝突・誤完了・
  manifest範囲外ファイル混入・他サイト共通部への回帰を優先監査。

## Historical Phase 04 local result (before the R3 authenticated-label extension)

The registered Hanayume policy admits only available `access_mode=free` with `direct`; the original logged-out Catalog kept `今なら無料` unknown. Current Discovery may classify that exact label as free only after the fresh same-work auth proof described above, and runtime repeats that preflight. The site adapter accepts Batch `direct` as the same no-entry free path used by manual `auto`; quota strategies and resources remain unsupported. A synthetic browser pipeline completed Discovery -> Catalog -> Planner -> Executor -> Runner -> Manifest/ZIP -> Catalog completed using the explicit test Catalog and temporary output paths. It also verified stale free-to-`今なら無料`, wrong work, UNKNOWN state, premature END, max-pages, and package failure remain pending with no Artifact. The run observed global-position archive prefix and skipped the completed Item on replanning. Independent Phase 04 review passed BLOCKING 0 (42 tests, 0 skipped; Ruff PASS). No live Batch was part of the Phase 04 local gate; the Phase 05 section below documents the later independent live run.

## Exit
normal Batch/isolated Catalogで既存統合テストを通過し、Reviewer BLOCKING 0。
実サイトをまだ使っていない場合は「live Batch NOT VERIFIED」とPROGRESSへ記録し、
Phase 05で独立検証する。全pytestは変更面積とdocs/TEST_STRATEGY.mdに従って判断する。

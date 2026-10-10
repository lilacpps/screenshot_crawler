# Piccoma性能・簡略化調査

調査日: 2026-10-10 JST。**Stage A/Bは独立Reviewer PASS。Stage Cのmanual interleaved比較、source-native出力一致、YAML200msのEND/ZIP/Catalog Batch、fresh per-page Manifest auditはPASS。Final Stage C Reviewer PASS / BLOCKING 0。WebP/PNG画像処理の追加最適化は未実装。** Stage C数値は[専用profile](PHASE07_PROFILE.md)、[Tester report](PHASE07_TESTER.md)、[measurements](PHASE07_MEASUREMENTS.json)に記録する。

最新のユーザー採用方針は [Phase 07 runbook](../../runbooks/piccoma-free/07-performance/README.md)。対象はJSON全field転送、`crawler.yaml` のPiccoma待機200ms、実装済みDPR許容の維持。Stage A/Bの実装は独立Reviewer PASS。Stage CはYAML200msのmanual/Batch経路を実測し、4本のinterleaved manual runで48対応画像byte一致/0 fallback、dedicated 24-page Batchのexplicit END/ZIP/Catalogと24/24 prepackage Manifest auditを確認した。Final Stage C Reviewer PASS / BLOCKING 0。0msは研究結果、method4/PNG等は別候補として保持し、今回の必須実装へ追加しない。

対象はユーザー指定の公開無料話 `28600/1910027`。source-native JPEG response binding、408タイルの正確な再描画、必要な白背景合成、可逆WebP、ページ・描画世代・完全性の検証を維持する。

## 基準と作業範囲

- 基準コミット: `69fccad`。Piccoma最新版 `c10eea4` は取り込み済み。`feat/piccoma-adapter` と基準コミット間で対象Adapter/Core Runner/runtime settingsの差分はない。
- 調査ブランチ: `research/piccoma-performance-20261010`。
- 既存取得成果物、通常Catalog/Watchlistには書き込まない。開始時のユーザー変更 `watchlist.yaml` と未追跡 `debug.log` を保持する。DPR微小差許容/前後一致、`crawler.yaml` の200ms待機、全6 snapshotのfull-trace JSON transportを実装し、対応tests/note/支持範囲文書を同期した。Stage A/B reviewはPASS。Stage C live evidenceもmanual画像一致、Batch END/ZIP/Catalog、per-page Manifest auditまでPASSした。Final Stage C Reviewer PASS / BLOCKING 0。画像codec/PNG経路は変更していない。
- 計測スクリプトと権利情報を含まない数値はこのディレクトリ、新規画像等はGit除外済みの専用 `output/piccoma_performance/` 以下に隔離する。画像・Cookie・署名URLをコミットしない。
- shared Crawler Chrome/profile → CDP → Playwrightを使用。fresh exact-free preflight、AccessGuard、bounded waits、既定pacingを通す。有料・待機無料・ticket等の操作は禁止。

## 調査契約

1. 現行フローと各検証の保証をコード・仕様・テストから整理する。
2. 初回ページと通常ページを分離し、同一条件の反復計測を行う。wall-clock、CPU、browser往復、同期ブロック、メモリについて測定範囲を明示する。
3. 同じ再構成済みRGBでWebP methodを比較し、VP8L・寸法・全RGB byte一致を確認する。
4. 改善案は実測と推定を分け、保証維持の条件・リスク・必要テストを示す。
5. Reviewerが完成した成果物を独立に懐疑的レビューする。未解決事項を成功扱いしない。

Lead: Sol; Explorer: `site_adapter_explorer` Luna (read-only); Tester: `site_adapter_tester` Luna (isolated measurement and sole live operator); Reviewer: `site_adapter_reviewer` Sol (read-only). Implementer: `site_adapter_implementer` Luna, the sole production writer for DPR tolerance and Stage A/B configuration/JSON changes.

## 成果物

- [FULL_PROFILE_PLAN.md](FULL_PROFILE_PLAN.md): ユーザーの追加依頼によるDPR最小修正と通常取得の全体再計測契約。

- [PROFILE.md](PROFILE.md): 計測方法・時間内訳・ボトルネック・限界。
- [INITIAL_PROFILE.md](INITIAL_PROFILE.md): DPR許容変更前の0ページ停止・metadata microbench・local benchmark記録。
- [SIMPLIFICATION.md](SIMPLIFICATION.md): 保証と検証の対応、重複・中間処理の削減案。
- [RECOMMENDATION.md](RECOMMENDATION.md): 優先順位・効果・リスク・受け入れテスト。
- [GENRE_FIX_PLAN.md](GENRE_FIX_PLAN.md): genre欠落→小説fallbackの原因、漫画の種別確認を前提にした修正計画。未実装。
- `TESTER.md` と数値JSON/計測スクリプト: 初期researchの再現手順と測定証拠。
- `REVIEW.md`: 独立レビュー結果。
- [PHASE07_PROFILE.md](PHASE07_PROFILE.md), [PHASE07_TESTER.md](PHASE07_TESTER.md), [PHASE07_MEASUREMENTS.json](PHASE07_MEASUREMENTS.json): Stage Cの同一200ms object/JSON比較とBatch artifact/Manifest evidence。

初期全体baselineはDPR許容修正後、method6/object返却/1,000msで12ページ×2run、**24 native WebP・fallback 0**。通常20cycle平均4.538秒で、固定pacing1.008秒。これは後続Phase 07の200ms object/JSON比較と条件が異なるため、因果差分に使わない。Stage Cの同条件比較は専用profileに記録する。

DPR変更の検証はUnit **60 passed**、browser Integration **56 passed**、再計測のinstrumented画素一致fixture **1 passed**、skip 0。DPRコードレビューと全体計測harnessの予備レビューはBLOCKING 0。最終統合レビューはREVIEWに記録する。初回0ページ停止はINITIAL_PROFILEとREVIEWの歴史的checkpointであり、現在の全体計測結果ではない。

追加調査では、ユーザー指定に従い既存shared ChromeのCDP接続環境で、reader/native snapshotを各12pair×2run比較した。native full object返却の中央値157〜201msに対し、**全fieldを保つJSON文字列返却＋Python復元は24〜26ms**、deep equalityは各run12/12一致。必要な検証を減らさず、転送表現を軽くする案を最優先へ変更した。paint走査自体は中央値約0.2msで、cache化は見送る。これは読取りmicrobenchmarkであり、geometry guardを変更した通常captureではない。追加checkpointも独立Reviewer **PASS / BLOCKING 0**。Ruff/compile PASS、数値成果物に画像・認証情報・署名URL無しを確認した。

上位authorityは既存AGENTS.mdと仕様文書。ここでの提案は採用済み仕様を変更しない。source-nativeからスクリーンショットへの変更、raw tiled JPEGの保存、非可逆圧縮、Free/END/Catalog/Batch/ZIPの仕様変更は対象外。

ユーザー回答反映: 約1%の容量増は許容。追加benchでは**method4**を次の推奨に変更（平均encode 0.938→0.483秒、容量+0.294%、48出力全RGB一致）。JSONは実装前microbenchで1回約0.15秒、1ページ6回の0.86〜0.99秒が事前の外挿予算。method変更は未実装。全field JSON返却は後続Stage Bで実装された。ここに記した「実装後効果は未検証」は当時の記述で、後続Stage Cは[PHASE07_PROFILE.md](PHASE07_PROFILE.md)に同一200ms条件の効果を測定した。待機0msの調査用live比較とPiccoma誤分類の修正計画も記録した。

初回research-only checkpointではnote更新無し。追加依頼によるDPR許容修正では `note/09_piccoma.md` を同期した。Stage A/B後とStage C後に同note、Adapter README、runbook、supporting research docsを同期し、Stage Cの検証済み範囲とFinal Reviewer PASS / BLOCKING 0を区別する。

追加の0ms liveも12ページ×2run、24native・fallback0、同ページbaselineと24/24出力byte一致。通常20cycle平均4.068秒・中央値3.742秒。描画安定待ちは維持し、pacing枠は約1秒減った。他工程も遅くなったため全体の観測短縮は平均0.470秒で、固定1秒短縮をそのまま全体効果とはしない。0msは調査専用overrideで、配布設定を0msへ変更していない。その後Stage Aで配布YAMLとmanual/Batch RunConfigへ200msを追加し、Stage Aの影響範囲testsは149 passed・0 skipped。この段階では実サイト200ms経路・連続性を未検証としたが、後続Stage Cでmanual/Batch/Manifestまで確認済み（Final Reviewer PASS / BLOCKING 0）。調査時の0ms/method4提案の後、ユーザーはYAML200ms＋JSONと既存DPR維持に範囲を絞って採用した。詳細はPhase 07/PHASE07_PROFILE/RECOMMENDATION。

最終独立Reviewer **PASS / BLOCKING 0**。0ms24出力のbaselineとの直接byte一致、両条件の排他的予算、method4、分類計画、計測限界を再確認した。最終Ruff/compileall/diff-checkもPASS。詳細は [REVIEW.md](REVIEW.md)。

Stage Cの4本interleaved manual runでは通常20cycle平均がobject 3.600739565秒→JSON 2.743414850秒、-0.857324715秒 / 23.8%。trace RPC合計は1.005563675→0.141548770秒、decodeは0.033611520秒追加。WebP method6 (0.508483810→0.510337605秒)、YAML pacing (0.208004275→0.208721775秒)、page-change wait (0.627919825→0.636617750秒)はほぼ不変。48/48 manual WebP bytes一致。別のBatch 24-page runはEND、ZIP/Catalog、per-page Manifest auditを通し、native evaluationとJSON decodeがそれぞれ144回一致した。これらのStage C evidenceはPASSで、Final Stage C Reviewer PASS / BLOCKING 0。Exact distributions/resource measures and scope are in [PHASE07_PROFILE.md](PHASE07_PROFILE.md) and [PHASE07_TESTER.md](PHASE07_TESTER.md).

Final independent review: [PHASE07_REVIEW.md](PHASE07_REVIEW.md). All stages PASS / BLOCKING 0. No further implementation or merge.

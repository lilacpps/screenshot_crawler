# P4 — 独立E2E、レビュー、最終判定

Status: PASS for the isolated episode 4.1 and first-episode 38-slot CLI Batch,
ZIP, and independent source/canvas audits (Tester and Reviewer BLOCKING=0;
NONBLOCKING=0). The separate 21-slot control and post-Discovery/Catalog
stability audit also passed. Final docs synchronization review passed (Reviewer BLOCKING=0, NONBLOCKING=0); Lead accepted closeout. The
prior repository-wide pytest run had one known baseline failure, reproduced at
`ceb3434`; it predates the 38-slot extension. Full Ruff passed. Other reader
variants and lifetime-position reconstruction remain unsupported. See
[PROGRESS](PROGRESS.md).
**目的**: Discovery→Catalog→Batch→全本文の完全性→ZIP/Completedを確認し、
再公開/期限変更/非公開履歴で実害のある不具合を残さない。

## P4 execution result (2026-10-12)

Tester completed a fresh isolated CLI run for `KC_004915_S:KC_0049150000400011_E`.
Full Discovery returned 53/53 complete; incremental returned five known Sources
and left the other 48 untouched. A normal Batch plan contained 53 pending Items;
in the isolated test Catalog, 52 non-target Items were marked skipped through
`CatalogService` so `batch run --limit 1` exercised the production CLI path for
the one exact target. The run captured 21 WebP pages, reached explicit END on
the same episode, created one ZIP Artifact, and marked one Item Completed.

An independent ZIP audit found 21 ordinally named, CRC-valid 836x1200 WebP
members. Each member matched both its corresponding P2 page file and the
independent normal-renderer live Blob bytes. The ZIP is 3,278,163 bytes with
SHA-256 `d64fd2a66c6982c3045a70940b36846cd7f12af4685551f9488174673099e6ff`.
Post-run incremental/full Discovery retained the Artifact and Completed state;
final isolated Catalog counts were 52 pending, 1 completed, 53 available/free
Sources, and 53 NULL positions. The actual Catalog's renumber dry-run proposed
no moves because positions are unknown; one separate synthetic fixture verified
apply/locator update while preserving ZIP bytes. No real archive was renamed.

The normal CLI removed temporary source output after packaging, so P4 validates
the ZIP, CrawlRun/status, Artifact, and Completed record; it does not claim a
retained manifest file. Exact CLI commands, isolated report paths, and audit
limits are recorded in [PROGRESS](PROGRESS.md). The independent Tester phase
passed; final P4 review and Lead acceptance passed for the bounded target scope.
The full-suite baseline failure and unsupported variants remain recorded above.

## First-episode 38-slot extension audit (2026-10-12)

Tester ran the normal isolated CLI Batch path for the first-episode target.
The 38 ordinal ZIP members were CRC-valid 835x1200 WebP and matched the
independent normal-renderer source Blob bytes and full-RGBA canvas audit exactly.
The source aggregate was 6,326,198 bytes; ZIP size was 6,328,964 bytes with
SHA-256 `7a98969ce7c2ee05c4ac93a0a593fa671451f7b5389f1fe74eeccad37c5365ea`.
The reader traversed 20 content slides with slot counts `[1, 2 x 18, 1]`, then
one ArrowLeft advance reached the empty slide 20 with the same episode identity
and explicit END `n=1,n=2`. All 38 ZIP members had exact ordinal bytes,
full-RGBA equality, and valid CRCs. Tester and independent Reviewer passed this
variant with BLOCKING=0. Sanitized evidence is under
`work/kadocomi/p4-first38-independent-20261012/`.

The 21-slot normal CLI control passed: the normal CLI produced 21 ordinal WebP
members with valid CRCs, matching the independent P2 page-file bytes and
836x1200 dimensions; CrawlRun succeeded at explicit END and produced its
Artifact/Completed state under the direct strategy with no quota resource. The
ZIP size was 3,278,163 bytes with SHA-256
`943c469041da7a2629eea810927694acea7cb5e6bdaf09b5441735edac089942`.
The final post-Discovery/Catalog stability audit preserved 53 original Sources
and external IDs, 53 available/free Sources (46 explicit deadlines, 7 NULL), all
NULL positions, 2 Completed Items, 51 pending Items, and both Artifacts. The
isolated Catalog backup integrity check returned `ok`. Actual-catalog
renumber dry-run selected 53 Sources with zero renames, 53 `no_position`, and
zero artifact collisions/errors. No fresh synthetic apply was run. Final
Final docs synchronization review passed (Reviewer BLOCKING=0, NONBLOCKING=0); Lead accepted closeout. The normal CLI removes temporary
source output after packaging, so this evidence covers the ZIP, run/status,
Artifact, and Completed state rather than a retained manifest.

## 必須確認マトリクス

| 分類 | 独立に確かめること |
| --- | --- |
| URL/identity | 作品、episode URL、redirect、別作品/volume混入、query/canonicalの整合 |
| 全件展開 | 「全XX話」展開、総数と非公開区間の意味、重複・途中切れ検出 |
| Full | clean complete時のみmissingをunavailable化し、Source/Item/Artifact/Completedを保存 |
| Incremental | 新規話/観測話更新とfree_until更新、早期停止、未観測履歴不変 |
| 配信期限 | 期限あり更新、期限なしNULLクリア、期限切れ時のBatch拒否 |
| 復活 | 同一episode ID再公開で既存Source再利用、現在観測freeへ状態更新 |
| 位置 | 全件順序・非公開gap・部分話、履歴Sourceとの衝突なし。不明な位置は捏造しない |
| キャプチャ | original byte保持またはnative/canvas pixel証明、全本文・spread・順序・解像度 |
| END | 最終本文直後の正常END、別話/広告/課金誘導非取得、途中失敗は未完了 |
| Batch | 期限/権利fresh check、Catalog候補、--limit、manifest、ZIP、Completed |
| 安全性 | 403/429/CAPTCHA、ログイン/チケット/ポイント・購入UI、上書き、無限retryなし |
| 回帰 | DiscoveryService、Catalog、Policy、Core capture/packaging、既存関連site |

## 実行手順

1. Reviewerがbranchのmaterial diffを実際の上位authority、P0証拠、
   受け入れ条件と突合。BLOCKING/NON-BLOCKING/VERIFIED分類。好みと実害を分離。
2. ImplementerがBLOCKINGを修正 → Reviewer再検証。自分のテストだけを合格根拠にしない。
3. Tester (独立) が専用Watchlist+Catalogを新規に用意し、
   少なくとも1話、可能なら期限/構造の異なる2話について実サイト `discover full`
   → `batch plan` → `batch run --limit 1` を実施。
   ZIPの実ページ数、先頭/中間/最後、左右、形式、寸法、源との一致を調べる。
4. 再Discovery（incremental/full）の差分ケースを合成fixtureで検証。
   時間経過による配信終了・再公開の実サイト検証は可能な時点で行い、
   fixture結果と未実施liveを混同しない。
5. Catalogバックアップ・Archive renumberのdry-runを試験用DB/outputで確認。
   `--apply`は安全なisolated fixtureに限る。本番運用DB/ZIPには勝手に実行しない。
6. target unit/local Playwright integration/関連Batch/Catalog tests、必要に応じ
   `pytest -q`と`ruff check src tests` を実施。skipをPASS扱いしない。
7. `site_adapters/kadocomi/README.md`、対応`note/`、`PROGRESS.md`に
   現行実装、実サイト日時、証拠、サポート対象外、将来課題を記す。
8. Leadが独立TesterとReviewerの結果を確認し、各Phase状態・最終判定を記録。

## 最終PASSの受け入れ条件

- 現在無条件無料と証明できた話で、少なくとも1つの完全なBatch→ZIP→Completed。
- 先頭から最後まで本文の欠落/重複/入替なし、ENDは明示/証明済み。
- 可読権限の誤判定や課金消費、重要なCatalog履歴破壊なし。
- 未観測Sourceの扱いがfull/incremental契約に一致。
- 再採番の安全策（誤った番号の強制更新をしない）が機能。
- 既存機能の回帰なし、Reviewer BLOCKING=0、必要な独立E2E確認済み。
- 原画像調査で、採用方式と不採用候補に根拠がある。
- 不可能なlive経時検証や高度な終了区間復元は、残制限として可視化してよい。
  **未確認のことをPASSと記載しない。**

## Leadの最終報告フォーマット

- 実装branch/commitと変更ファイル。
- supported URL/viewer/free判定とunsupportedな状態。
- Full/Incremental/復活/位置再採番の実装済み範囲。
- original/native/renderedの採用方式、根拠、画素検証。
- テストコマンド: PASS/FAIL/SKIPと理由、live E2E/画像監査の結果。
- BLOCKING 0の確認、未確認事項、修復・再実施が必要な場合の手順。
- ユーザーが判断する事項は最大3点に絞り、他の重要事項は省略せず説明する。

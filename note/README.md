# note/ maintenance rule

`note/` は、現在の実装を詳しく説明するための **current implementation snapshot** です。

過去の会話や作業履歴を保存する場所ではありません。各noteを読めば、「今のコードがどう動くか」「どのsignalを使うか」「どこまで実サイト確認済みか」「既知の制約は何か」が分かる状態を維持します。

ただし、実装前の採用済み仕様を current-state note に混ぜないため、access-control関連では明示的な計画noteを例外として使用します。計画noteは必ず **PLANNED / NOT YET IMPLEMENTED** と明記し、実装済み挙動と混同しません。

## Authority

noteのauthority順位は上位ではありません。

1. `docs/SPEC.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DISCOVERY_AND_BATCH.md`（Discovery / Catalog / Batch）
4. `docs/ACCESS_CONTROL_AND_PACING.md`（shared pacing / AccessGuard / metrics / access-resource / grant-only）
5. `docs/MAGAPOKE_BATCH_ACCESS.md`（Magapoke固有resource semantics）
6. `docs/ACCESS_CONTROL_AND_PACING_PLAN.md`（shared access実装Phase）
7. `docs/DECISIONS.md`
8. `docs/CODEX_IMPLEMENTATION_GUIDE.md`
9. code / tests
10. Site Adapter README / probe
11. `note/`

noteと上位authorityまたはcode/testsが食い違う場合、noteを現行状態へ修正します。

## File mapping

- `00_core.md`: Core / Runner / browser / output / packaging / diagnostics / resume /共通安全装置
- `01_bookwalker.md`: BookWalker固有の観測・Adapter・login・capture・終端
- `02_mangaone.md`: Manga ONE固有の観測・Adapter・login・capture・終端
- `03_magapoke.md`: Magapoke固有のviewer・scrambled JPEG tile再構成・PNG fallback・遷移・現行Batch/resource挙動
- `03_magapoke_access_plan.md`: Magapoke固有の採用済み未実装resource計画（PLANNED only）
- `04_access_control_plan.md`: shared access-control / pacing / metrics / resource selectionの採用済み未実装計画（PLANNED only）
- 新規site追加時: 対応番号のsite noteを追加

## Mandatory synchronization

仕様・実装・テスト・運用方法を変更した場合、**同じ変更の中で対応noteを更新することを必須**とします。

- Core共通変更 → `00_core.md`
- Site Adapter固有変更 → 対応site note
- Core変更が特定siteの挙動へ影響 → Core note + site note
- CLI/login/browser起動方法変更 → Core note + 影響site note
- output naming / packaging変更 → Core note + 影響site note
- shared access仕様の計画変更（未実装） → `04_access_control_plan.md`
- Magapoke固有access resource計画の変更（未実装） → `03_magapoke_access_plan.md`

実装が各Phaseでlandしたら、その実装済み内容は計画noteだけでなく `00_core.md` / 各site current-state noteにも反映します。

noteを更新しない場合は、「ユーザー向け文言のみ」「コメントのみ」など、現行挙動に影響しない理由を作業報告へ明記します。

## What to record

最低限、該当するものを記載します。

- 目的 / scope
- 現在の処理フロー
- 主要class / module / entry point
- PageState / identity / context / fingerprintの扱い
- capture target / spread order
- navigation / wait / retry / timeout
- END / NEXT_CONTENT / UNKNOWN判定
- login / CDP / profile / env
- output / manifest / progress / ZIP / cleanup
- safety guard
- tests
- live verification
- known limitations / 未確認事項

site noteでは、selectorやDOM signalのような実装上重要な詳細も残します。

## Current state, not append-only history

古い仕様を本文に残したまま「現在は違う」と末尾だけに追記しないでください。

実装が変わったら、古い説明を置換して本文全体を現行状態にします。過去の判断経緯を残す必要がある場合は、以下を使います。

- `docs/DECISIONS.md`
- Git commit history
- issue / PR

計画noteは履歴保管ではなく「採用済みだが未実装の現在計画」のみを保持し、計画変更時は本文を更新します。

## Secrets

以下はnoteへ記録しません。

- password
- Cookie
- storage state
- access token
- session secret
- 個人用認証情報

`.env` のキー名やダミー例は記載して構いませんが、実値は書きません。

## Completion check

変更作業の完了前に確認します。

1. code/testsとcurrent-state noteが一致している
2. 計画noteは未実装内容を実装済みと書いていない
3. 現行CLI例が実際に有効
4. 実サイト確認済みと未確認を区別している
5. 固定の古いtest件数を「現在値」として残していない
6. secretsを含まない

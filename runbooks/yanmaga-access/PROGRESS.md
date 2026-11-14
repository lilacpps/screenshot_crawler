# ヤンマガWeb アクセス拡張 — PROGRESS

**Status:** PLANNED / NOT STARTED
**Plan authored:** 2026-11-15
**Implementation branch:** \`feat/yanmaga-access\`（作業開始時の最新mainから作成。未作成）
**Base authority:** [README.md](README.md), \`runbooks/yanmaga-free/README.md\`, \`AGENTS.md\`
**注意:** 本ファイルは実装済み・実サイト確認済みを意味しない。旧 \`runbooks/yanmaga-free/PROGRESS.md\` は通常無料機能の既存検証履歴として維持する。

| Stage | 状態 | 証拠・結果 |
| --- | --- | --- |
| 01 Site probe / Discovery | NOT STARTED | ログイン状態・初回無料/待つと無料/レンタル/ポイント分類を実測する |
| 02 First-free capture | NOT STARTED | direct開放・失敗復旧・Grant記録とgrant-only非対象を検証する |
| 03 Work ticket | NOT STARTED | 23h cooldown・通常Batch・grant-only・確定消費保存を検証する |
| 04 E2E / final review | NOT STARTED | 画像・END・ZIP・Catalogと独立レビューを監査する |

## Stageごとの更新テンプレート

- **日時/commit/branch:** 
- **実サイトサンプル:** 匿名化work/episode、確認した画面状態、観測時刻。権利使用回数。秘匿情報は記録しない。
- **観測と推測:** DOM/APIの根拠、スクリーンに見える結果、確認できなかった点を明確に分離。
- **変更ファイルと仕様差分:** 
- **Unit/Integration:** 実行コマンド、pass/fail/skip、失敗の修正と再実行。
- **E2Eと成果物:** 入口の権限状態、クリック前後の証拠、本文ページ数、END、Manifest/ZIP整合性、Artifact/Completed。失敗時のpending/Grant状態。
- **独立Reviewer/Tester:** BLOCKING件数、残課題。
- **次StageへのGate:** PASS / BLOCKED / NOT VERIFIEDと理由。

## 未検証事項（実測まで断定しない）

1. ログイン済みの初回無料、待つと無料、チャージ中、レンタル中、ポイントのみ、同時表示の正確なDOM/API。
2. 初回無料開放時の画面遷移と閲覧期限の証拠、取得失敗時の再入場。
3. 作品単位の待つと無料のチャージ・回復表示と、開放後の閲覧有効期間。
4. 既存Yanmagaの匿名用Discovery証拠を維持しながら、ログイン時のアクセス分類を行う方法。
5. 初回無料のdirect開放成功を既存DB \`access_granted_until\` に確実に反映する最小の呼び出し経路。
6. 通常direct群と作品quota群の具体的な既存実行順。

未検証の実サイト挙動を前提にproductionへセレクタや期限計算を入れないこと。

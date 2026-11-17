# Piccoma 3種チケット自動消費 — 進捗・証拠

**Status: PLANNED / NOT IMPLEMENTED**
**更新日:** 2026-11-18
**契約:** [README.md](README.md)

## 現時点の基準

- Runbook本文のみ作成。Piccoma のチケット自動消費機能は未実装。
- 既存コード: Piccoma Discoveryは3種の候補バッジをquota扱い、PolicyとAdapterは無条件無料/手動解放済みだけをdirect Batch可能としている。
- 公式FAQ/イベント説明はREADMEにURLを記載。**ログイン済み実ブラウザでの券種選択・実消費の挙動は未検証**。
- このRunbook作成で実チケットを消費していない。ユーザーの追加の明示許可なく消費検証をしない。

## Stage 01 — Repo / live read-only Probe

**Status:** NOT STARTED

### 記録テンプレート

- HEAD SHA・作業ブランチ・実施日:
- 独立read-only調査担当 / 実ブラウザ操作担当（単独）:
- 現行Policy・Planner・GUI / Worker の順序・フラグ連携のテスト/証拠:
- 観測した product_id / episode_id（秘密・作品画像を記録しない）:
- 待てば¥0：作品ごとの表示、利用可否、選択/消費UI、確定事項/未確認事項:
- ¥0+券：アカウント残数、対象話、券種選択、確定事項/未確認事項:
- 爆読み¥0券：アカウント残数、作品ごと上限、対象話、確定事項/未確認事項:
- 複数券が適用可能なときのネイティブ優先順位:
- クリック前に証明できる対象話・券種・無料性・一意な操作:
- クリック後の権利付与を証明するレスポンス/DOM/URLとreader ready:
- ローカル記録（site-wide/作品ごと/話ごと）の必要性と、既存API流用可否:
- 資源別passではなく1話ずつ処理するための最小変更判断:
- **実消費: 0枚（無許可の場合）／別途許可を受けた場合のみ、許可された上限と実消費数を記載**:
- 残るUNKNOWN・ブロッカー・代替案:
- Reviewerによる安全性確認 / BLOCKING:

**Gate S1:** 未実施。実サイトのUI証拠と候補順維持の設計を確定できるまで、Stage 02での消費実装を有効にしない。

## Stage 02 — 実装 / テスト / GUI

**Status:** NOT STARTED

### チェック項目

- [ ] CLI・GUIで明示opt-in、既定OFF、誤site/誤actionで拒否
- [ ] free / manual grant のdirect処理に回帰なし
- [ ] quota対象話の厳密なfresh判定。3種それぞれ本人アカウントで利用可能か確認
- [ ] 1話ずつのcrawl順維持。free/3券種/複数作品の混在を含む
- [ ] 1試行・対象話・1券種・1回操作。UNKNOWN/有料/他resourceへ自動fallbackしない
- [ ] 消費確定とCapture成功を別記録。失敗/中断後に自動で二度押ししない
- [ ] 同じ対象話のviewer → 既存Capture/END/ZIP経路
- [ ] 残数0、作品上限、週境界、途中配布、同作品複数話、同時に複数券適用可のfixture
- [ ] 既存Piccoma unit/browser integration + Batch/CLI/GUI/Worker affected tests
- [ ] 共有コード変更がある場合、他サイトの回帰テスト
- [ ] ruff・対象テスト結果、必要に応じたfull suite
- [ ] note/09_piccoma.md / Adapter README・共通noteとの同期
- [ ] Reviewer BLOCKING 0、実サイトでの消費は別途許可された最少枚数だけ

### 実装結果（未記入）

- 実装ブランチ/commit:
- 採用した設計とRunbookとの差分:
- 変更ファイル:
- fixture テスト:
- 既存回帰テスト:
- 現地テスト（券種/対象/実消費枚数/ZIP/Source状態）:
- 未確認/未実施:
- Reviewerの判定:
- Stage 02最終判定:

# ComicFUZ `work_ticket` — PROGRESS

**Status:** PLANNED / implementation not started
**Runbook authored:** 2026-11-23 JST
**Execution contract:** [README.md](README.md)
**Implementation branch:** `feat/comicfuz-work-ticket`（着手時に最新`main`から作成）
**Runbook baseline:** 2026-11-23 の `main` 現行コードを確認して作成。実装時に最新SHAを記入すること。

## 既知の事実・ユーザー指定

- ComicFUZ の作品チケット（チャージ）は **毎日午前0時 JSTに回復**（ユーザー確認）。経過23時間ではない。
- 消費は作品ごと1枚。Premium Ticket、コイン、メダル、有料操作は実装しない。
- 話一覧の「無料」は`free`、コインマークは`paid`、何も表示されない正規行は`quota`候補。
- 現行のComicFUZ Discovery/Adapter/Policyはpublic-free `direct` のみ。無表示は`unknown`、quota/entry-only/日次消費管理は未実装。
- 共通Catalog `quota_resource_states` と Batch Executor の work-scope resource hooks を再利用する計画。現段階で schema 変更不要と見込む。
- サイトのUIによるチャージ開始操作・消費確認のnative証拠・話の閲覧期限・手動消費同期の方法は**未観測**。推測で確定しない。

## Phase checklist

| Phase | Status | Exit evidence |
| --- | --- | --- |
| 01 Read-only DOM/native 調査と仕様確定 | TODO | free/coin/無表示の exact row、消費トリガー、確認方法、日次回復の表示証拠、未確定点の整理 |
| 02 Discovery/Policy/日次skip | TODO | 合成時計のJST 00:00境界、work分離、site request 0、他サイト23h回帰なし |
| 03 Adapter/通常Batch/grant-only | TODO | 合成browserで消費最大1、正の証拠、同一Page、entry-only0画像、paid操作0 |
| 04 実サイト・独立検証 | TODO | 変更SHA、限定E2E、DB/ZIP/requests監査、レビュー、残リスク |

## 実装着手時に記入する項目

- `main` HEAD SHA / 専用worktree / 未コミット差分:
- Phase01に使った作品URL・chapter ID（公開IDのみ）とログイン/匿名差:
- 観測したDOM/first-partyフィールド名と条件（秘密・本文・署名URLを保存しない）:
- チケット消費操作が navigation / button / その他のどれか:
- 事前の副作用なし判定、消費の正の証拠、時刻の根拠:
- 閲覧grantの正確な終了時刻または安全な観測下限:
- 00:00 JST反映遅延・日跨ぎ時の扱い:
- 変更ファイル/commit SHA:
- Unit/browser/CLI/inventory regression の実行コマンドと結果:
- 実サイトで消費したチケット（作品ID、話ID、JST時刻、枚数、事前許可）:
- grant-onlyと通常BatchのDB監査、同Pageの証拠、ZIP/CRC/Manifest監査:
- 独立レビュー（blocking数）、残課題、Done/Live pending判定:

## 決定事項と変更時の扱い

**Decision 001:** Work resource stateは既存 `site,work_id,resource` キーと `last_consumed_at` を利用。ComicFUZ SitePolicyだけが「最終消費日の翌日00:00 JST」を算出する。他サイトの経過時間ルールは維持。変更する場合は根拠と回帰テストを残す。

**Decision 002:** 「無表示=quota」は**描画済み・完全照合済み・未知の価格/権利マーカーなし**に限る。隠れたコイン、遅延hydrate、未判定のアイコン/ラベルがある場合はfail closed。

**Decision 003:** 無料directの既存厳密preflightとJPEG/END/ZIP処理は維持。quota/有効grantは対象話直行の最小変更を検討し、別話へのfallbackやpremium/coin消費を禁止。

**Decision 004:** 実サイトの不可逆なチケット消費を伴うE2Eは、synthetic検証後、ユーザーから枚数上限を含む明示許可がある場合にのみ実施。許可を得られなければlive pendingと明記し、synthetic verifiedをDONEと偽らない。

# Stage 02 — Work候補、ローマ字ID、同一性・重複判定

> Status: COMPLETE。実装・検証は ../PROGRESS.md のStage 02 checkpoint。

## Objective

- URL解析結果からGUIに依存しないBatchRegistrationDraftを構築。複数URLの入力順、原文、解析エラー、選択状態、手動編集、source provenanceを保全する。
- 同一site + 検証済みwork identityの重複は1target候補へ折り畳む。異siteは作品名・既存Watchlistを参照して「候補」を提示するだけで確定mergeしない。
- Work単位の新規/既存紐付けをユーザー確定事項にする。既存のwork_keyを継承し、既存key/work_keyは変更しない。
- work_keyは読み→ローマ字のhuman-readable slug候補。ASCII英数字+underscoreに正規化。key=work_key + "_" + canonical_site。手動調整可。新work_key衝突、同Work同site複数keyの _2 等は明示候補、誤mergeしない。
- work_key編集後、未手動変更のkeyだけ自動追従。手動編集済みkeyは保持。読み/タイトルが不確実なら確定をブロックし入力を求める。
- Work状態は ready / needs_manual_confirmation / needs_scope / blocked（複数未完了理由を保持）。新規単一keyは無scope、正規URL/label/Work/ID確定と所有照合後にready。複数key/既存Workへサイト追加はscope確認を必須化。単一keyでも任意で詳細編集へ進める。
- 選択した準備完了候補のみ後の保存対象とし、除外候補は編集データを失わない。

## Constraints / tests

- Resolver/PlannerからCatalogやWatchlistへのwrite禁止。Watchlist既存情報はread-only snapshot。
- 作品タイトル一致はdisplay hintに限定。サイト横断エピソード名寄せ/Source移動/同一内容判断をしない。
- 同一siteの別登録（同一Workで複数key）が正当な場合、作品IDが同じでも既存keyを勝手に取り込まずoperator選択を要求。
- Unit tests: 同一URL/作品ID、異siteタイトル一致、同名別作品、既存Work候補、異作品slug衝突、_2、手動命名追従、改名禁止、bulk draft再試行時の維持。
- Stage完了時点でGUI/Watchlistへの実保存は不要。必要十分なモデルだけ作り、後続StageのUI過剰設計を避ける。

## Stage 00後の決定: 手動確認候補

- 厳格に安全性を検証できた正規Discovery URLなら、native work IDまたはtitleが未取得でも、unknownを維持して手動確認候補とする。URLがblockedなら手動確定しても登録不可。
- label入力、明示的な新規/既存Work選択、ローマ字work_key/keyの修正・確認を候補版に結び付ける。既存Workの場合は安定work_keyを継承する。
- 手動確認は作品IDの証明ではない。unknown identityの別URLを同一作品と自動統合しない。既存Sourceの所属や所有が曖昧ならblocked、確認操作で回避不可。正確なURL重複の検出はよい。
- Tests: 正規URL+unknown ID/title→手動label入力/明示確認→ready候補、不正URLの確認bypass拒否、同名別作品の自動merge拒否、既存owner不明はblock、再解析・編集後の確認証拠失効。

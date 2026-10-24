# Phase 02 — 既存上部GUIを維持した常設Monitor

## Starting evidence
- Phase01のログreaderとDiscover出力 parityが確認済みであること。
- 現行`gui/main_window.py:_build_ui()`: path行 / toolbar / 横splitter tree+detail / 実行ボタン行 / error label の順。`JobsPage`は別window。`_poll_jobs()`は500msごと。

## Objective
1. `gui/execution_monitor.py`に`ExecutionMonitor(QWidget)`を追加。見出し + action/state/current site/key/item + observed progress + ログ/サマリ/問題のみ（サマリ本体はPhase03）+ stdout/stderr切替/ファイルを開く。
2. メイン`MainWindow`へ追加。既存横splitterとaction行とerror labelを**元の並びのまま**上部のコンテナにまとめ、その下にMonitorを配置。垂直`QSplitter`で高さ調整（既定約220–250px、展開/折り畳み）。path行、toolbar、上部各WidgetのobjectName/動作/横比率・選択保持を変更しない。window縮小時にボタン列が欠けないか検証。
3. `MainWindow._start_execution()`で生成されたjob_idをmonitorへ設定。 `_poll_jobs()`成功・失敗・queue進行に合わせ表示更新（`queued`、`running`、`terminal`を区別）。ユーザーが履歴を選択中なら追従停止。終了Jobは結果確認まで残す。
4. `QPlainTextEdit`の追記表示。初回history tail読み込み後はreaderで増分のみ。スクロールがbottomの時だけautofollow、過去閲覧時はscroll value/viewport anchor維持、最下部に戻った時再追従。閉じたpaneは不要な再描画を避ける。
5. Monitorが表示できなくても`JobController`のworker実行・poll・stop・reconcileを妨げない。GUI初期化時にManagement DBへ不必要な書込を発生させない。

## Constraints
- main window上部のWidget構成・順番・ツリー表示・検索/絞り込み/checkbox・実行前Previewを変更しない（widget reparentのみ許可）。
- actionボタンや「ジョブ」の動作を変えない。monitorからworkerを直接起動しない。強制終了ボタンは増やさない。
- 狭い画面・折り畳み・高DPIで上部を優先し、monitor最低限見出しで縮小可にする。

## Tests
- Qt offscreen: 現行上部Widgetが同じ順序・同じ設定であり、既存HorizontalSplitterが残っていること。分割高さを変更しても選択・検索・detailが維持。
- fake stdout追記中、scroll bottomなら追従／上へ移動したら位置保持／最下部復帰で追従。大量追記・block limit超過・別job選択でも手動位置が飛ばない。
- 選択Job切替、queue/active/terminal、終了後history確認、起動時管理DBがないケース。
- 同時Qt load/reloadのUI responsiveness、既存`tests/integration/test_gui_smoke.py`回帰。実サイトアクセス/チケット消費禁止。

## Acceptance / Exit
- ユーザーは「ジョブ」を押さず通常画面で進捗ログを読める。既存上部GUIの配置・操作の変更なし。
- `PROGRESS.md`に画面キャプチャ、テスト、保留を記録しPhase03へ。

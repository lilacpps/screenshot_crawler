# Stage 05 — 最終プレビュー・原子的保存・Full導線・E2E

> Status: NOT STARTED。Stage 04のdraft-only検証完了が前提。

## Objective

- 選択されたready Workの設定を統合し、WatchlistService.preview_edit + Catalog照合で、登録キー、既存との差、追加/除外/維持、重複、scope/orderの影響、Full/Scope sync/renumber残作業をユーザーにプレビューする。
- 保存直前にWatchlist revision/Catalog fingerprintとjob lock、必要なread-only listing proof鮮度、全Key/Work uniqueness、同一site Source owner衝突を再検証。安全な正規Discovery URLかつID/title unknownの手動確認済み候補も許可し得るが、既存Source owner/Work所属が曖昧・古い/途中保存の可能性がある場合は全体をブロック。
- 最終選択集合を単一のatomic WatchlistService.apply_editで保存する。保存中、全ターゲットの旧状態とselected setを混在させない。部分チェックを外した候補は保存しない。
- 正常保存後にMainWindowへ明示的な変更Key集合とWatchlist revisionを通知し、既存Full Discovery確認ダイアログを一度表示する。No/CancelはWatchlist登録だけ成功、Fullは未実行と表示。Fullは独立job、失敗はkey別表示。
- scope-sync、renumber、Batchの自動起動はしない。Fullが必要でもCatalog状態の未同期を成功と見せない。

## Tests / exit

- end-to-end synthetic: 1URL→登録、multiURL→複数Work、異site同Work+scope、既存Workへの追加、選択Workのみ保存、ID手修正、一部blocked/未選択、Full yes/no/failure、GUI再読込。
- Race/atomic tests: concurrent Watchlist編集、Catalog更新、listing stale、キー重複、同site他key owner、新規/既存の混在、予期しない例外でWatchlistに部分書き込みなし。
- Affected suite: Watchlist/Catalog/WorkEditor/Discovery read-only preview/MainWindow/GUI/Batch acquisition-gate（変更範囲による）。shared広範囲変更でfull pytest、ruff check src tests。
- Browser-backed local Integration / 必要な限定Live verification。実サイト著作物を保存せず、実運用のWatchlist/Catalog/ZIPに触れない。
- 完了時はdocs/DISCOVERY_AND_BATCH.md、docs/GUI_README.md、note/00_core.mdと関係site noteを更新。変更ファイル、テスト/skip、未確認のサイト変換、操作手順をPROGRESSに記録。

## Stage 00後の決定: 手動登録と初期サイト範囲

- URL文字列が公式siteの現行Discovery用正規起点として厳格に検証されていれば、作品IDやtitleを自動取得できない候補も、ユーザーがlabel・Work・key/work_keyを明示確定し、Watchlist/Catalog所有照合に通るとき保存できる。`unknown`な作品IDを`verified`に昇格せず、既存SourceやWorkの自動merge/再所属を禁止。
- URLが不正・未対応・変換先不明、手動確認未完了、既存Source所有不明、既存key衝突・別Work混入、stale/不完全な詳細証拠はblocked。人の確認で安全検証を飛ばさない。
- Stage 05の先行完成は、安全な正規URLの新規単一key登録・Kadocomi pilotの登録と、現行4site（magapoke/jumpplus/zeblack/comicdays）の完全一覧previewによる複数key編集まで。未対応7siteでscopeが必要なWorkは理由付きblock。後続Stage 07で拡張。
- E2Eに追加: valid canonical URL+ID/title unknown→label手入力と明示確認→保存、invalid/unsupported URLのbypass拒否、unknown IDの自動同一Work判定なし、4siteの複数key詳細、7siteのpreview block、CAS/owner競合時all-or-nothing、Full Yes/No/失敗。

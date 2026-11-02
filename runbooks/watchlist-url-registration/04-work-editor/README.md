# Stage 04 — WorkEditorをdraft-only詳細設定として再利用

> Status: COMPLETE。実装・レビュー・検証は ../PROGRESS.md のStage 04 checkpoint。

## Objective

- 既存WorkEditorDialog / WorkDraft / ListingPreview / validate_work をできるだけ再利用し、draft-only利用時は対象Workの完全一覧取得・範囲・順序編集と検証結果を一括登録側へ返す。通常編集モードのsave/full動作は変えない。
- 複数key Work・既存Workへ追加: 全関係keyの既存discovery_scope、archive_order、archive_segments、existing Source ownershipを読み、変更の必要な箇所だけ編集。未設定の複数keyを全話対象として保存不可。
- read-only完全一覧に基づきsite-local identity/pos/selected stateを比較する。ユーザーが話の重複/範囲/完成順を指定し、別siteの内容一致を自動推測しない。
- Existing Workに追加する際、既存のstable identity・Source owner・ZIP履歴を変更しない。既存scope/order/segmentsは初期値として維持し、ユーザーが確認した明示変更だけ許す。採番差分/renumber要否は事前プレビューで警告し、暗黙のZIP renameはしない。
- WorkEditorを閉じると未保存のそのWork draftだけをcancelでき、他Workの候補は消えない。戻って再編集できる。TTL 300sの既存完全一覧は保存直前にfreshnessを再評価し、staleならWork単位で再取得。
- 詳細設定結果にはscope確認済みという事実と、元Watchlist revision / Catalog identity / listing digest等の検証証拠を保持。単なるGUIボタン押下を「有効な設定」と見なさない。

## Tests / exit

- 新規複数site、既存1siteへの追加、既存複数siteへの追加、archive_segments Work、複数非連続範囲、Source overlap、old/new listing mismatch、TTL stale、キャンセル/再編集。
- draft-onlyでWatchlist/Catalog/ZIPにwriteしないこと。通常WorkEditorの保存→Fullリクエスト回帰テスト。
- 既存scopeが未同期/不完全なら理由付きblockにする。scopeの誤拡張や別KeyのSource横取りは禁止。

## Stage 00後の決定: 初期詳細編集は4サイト

- 現行 `preview_complete_listing` 対応はmagapoke/jumpplus/zeblack/comicdaysの4サイトのみ。新規/既存複数key Workの詳細編集は4サイトと人工fixtureで先行検証する。
- 未対応7サイトが混在し、そのWorkで完全一覧に基づくscope/order/segmentsの確認が必要なら、Workごと理由付きblocked。通常Full Discoveryをread-only preview代わりに呼ばない。後続 [Stage 07](../07-listing-preview-coverage/README.md) に分離。
- 安全な正規URLの新規単一keyを手動登録する場合、完全一覧previewは必須ではない。ただしStage 02–05の手動確認・所有チェックは必要。
- Tests: 4サイトのread-only詳細editing/confirmation、7サイト未対応のblocking、既存scope/order/segments維持、通常WorkEditorモード回帰。

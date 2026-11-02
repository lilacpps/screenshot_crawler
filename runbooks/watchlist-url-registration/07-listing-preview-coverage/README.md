# Stage 07 — read-only完全一覧previewのサイト別拡張

> Status: NOT STARTED / DEFERRED。Stage 05までに既存4サイトで先行完成し、残り7サイトは後続段階で安全に追加する。

## Objective / scope

- 現行preview対応4サイト: magapoke, jumpplus, zeblack, comicdays。未対応7サイト: bookwalker, comicfuz, hanayume, kadocomi, mangaone, piccoma, younganimal。
- 既存Full Discoveryのcomplete inventoryと、GUIのread-only complete listing previewを混同しない。各siteのpreview_complete_listingでsite-native identity、行ID/順序/position、完全性、境界と除外を検証する。
- siteごとの安全なread-only一覧だけを用い、通常FullによるCatalog write、viewer/reader、チケット/point/購入/権利消費は用いない。過去全件が観測できないなら完全な一覧として扱わない。
- 1サイトずつ既存ListingPreviewService・WorkDraft・SelectionPlannerと連携し、複数keyのscope/archive_order/archive_segmentsをプレビュー・draft-only編集できるようにする。
- URL変換と作品title/IDのmetadata取得はStage 06で扱い、本Stageでは混在させない。ユーザーの利用頻度・実サイト観測可能性を踏まえて対応順を決める。

## Acceptance / tests

- site-native work identityと入力URL/対象keyが一意に結び付く。complete=trueの証拠なしでは保存可能としない。
- 既存range/excluded_external_ids、同site所有重複、archive順序、stale TTL、partial/pagination failureにfail-closed。
- site別Unit＋人工DOM/response Browser Integration＋既存Discovery/WorkEditor/Batch取得担当回帰。必要なら限定Live観測、サイト著作物をテストに保存しない。
- 未対応siteを含む複数key Workは引き続きblocked。安全な正規URLの単一key手動登録はStage 05の条件に従い継続。
- サイトごとにdocs、site note、PROGRESSの実装済み/未確認を更新。全7サイト完了をStage 05の完了条件にしない。

# Stage 06 — サイト別のURL変換拡張と検証

> Status: NOT STARTED。Stage 05のpilot vertical sliceを壊さず、サイト単位で進める。

## Objective

- Stage 00 matrixで「未確認」を明示したまま11siteへURL変換を段階追加。初期段階から全11siteの現行Discovery起点URLは受理検証済みであることが基本契約。
- 例: kadocomi episode→work（URL中のwork ID）、zeblack viewer→chapter/list（title identity）、younganimal/comicfuz episode→work（同一Work確認）、magapoke/jumpplus/comicdays/mangaone/hanayume/piccoma work/listing→episode/viewer（安全なsite-native linkを検証してから）、bookwalker product→series/list（seriesが複数・不明なら要選択/ブロック）。
- このリストは「実装可能と検証済み」の意味ではない。対応可否は現在のsite parserとLive/fixture証拠で決定。作品一覧ページ自体をDiscoveryに登録しない。
- 1siteずつformat, safe transform, title evidence, offline tests, optional bounded Live probe, notesを更新する。未知URLに一般的な「最初のepisodeをクリック」を行わない。
- リダイレクト、query、認証状態、episode公開終了、owner work mismatch、話一覧に1件もない、購入/課金誘導はfail-closed。サイト制御による負荷・rate limitを尊重する。

## Tests / exit

- site固有parser unit + synthetic browser/response integration + preview no-write + existing Discovery/Batch regression、必要時のみ実サイトLive（日時・URL shape・根拠・未対応を明記）。
- 動作確認できた形のみ「自動変換できます」とGUIに表示する。未実証のサイトは通常の起点URLを使えるまま維持し、改善予定を登録成功と偽らない。
- 共通modelの変更や大規模refactorは避け、site-localな拡張にとどめる。

## Stage 00後の決定: URL変換とpreviewの責務を分ける

- Stage 06で扱うのはサイト別URL変換と、非消費のsite-native work identity/title metadataの拡張のみ。安全な正規URLは確定しているがmetadataが取得不能な場合は、Stage 02–05の手動登録経路を妨げない。
- 残り7サイトのread-only完全話一覧previewとscope詳細設定は [Stage 07](../07-listing-preview-coverage/README.md) に分離する。Full DiscoveryやCatalogへの書込みでpreviewを代用しない。
- Stage 06の完了判定では「正規URL認識」「別形式変換」「作品ID/title取得」「完全一覧preview」を別のcapabilityとして報告する。

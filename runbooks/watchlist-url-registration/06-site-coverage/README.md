# Stage 06 — サイト別のURL変換拡張と検証

> Status: COMPLETE (2026-11-03). Only proved URL conversions/metadata are enabled. All eleven site boundaries: CAPABILITIES.md. Results: ../PROGRESS.md. Stage 07 not started.

## Execution contract (2026-11-03)

- Baseline: feature/watchlist-url-registration `09c040d`。運用YAML/locks/logの既存変更を保護し、入力やtest fixtureとして読まない。
- 順序: URLだけで確定できるZeblack変換 → 非消費の作品ページでmetadata/自然な同作品linkを有界観測 → 全11siteのcapability matrixを更新。各siteは独立に検証し、未確認を実装しない。
- Probeはshared CDPの専用Pageを一人で操作し、readerやepisodeを開かず、まず正確な作品/listing documentへの一回GETとredirect拒否・subresource遮断で調べる。保存する証拠はURL shape・title/identity/link等のmetadataのみ。Cookie/HTML本文/漫画画像を保存しない。
- 不明点: dynamic work-to-seed経路、作品所属の一意性、非消費title根拠。確認できない場合はunsupportedを残す。安全な正規起点の手動確認経路は維持する。
- 受入: 新変換のstrict URL/identity tests、人工DOM/responseのredirect/mismatch/auth/error/no-write Integration、変更site Discovery regressionと登録GUI/save回帰、ruff。共通resolver/modelを変更する場合は根拠と最小範囲を明示し、影響に応じfullも実施。
- checkpointごとに対応site note/core note、capability matrix、PROGRESSを同期する。Stage 07の完全一覧previewには入らない。

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

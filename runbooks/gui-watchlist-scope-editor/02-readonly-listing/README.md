# Stage 02 — 完全一覧の読み取り専用Preview

> Status: **COMPLETE / REVIEW APPROVED**。実行結果は [PROGRESS.md](../PROGRESS.md) を参照。以下は実行契約。Stage01/Stage00確定後。第一対応siteはMagapoke、他サイトはcapabilityが揃ってから。

## Objective / API
共通Coreからサイトの話一覧を**Catalog書込なし**で取得。通常`DiscoveryService.discover`をGUIプレビューへ呼ばない。

推奨の軽量DTO（名前は最終実装に合わせ調整可）:
- `ListingRow`: `external_id`, `url`, `site_position`, `display_title`, `access_observation`, `listing_identity`の参照
- `ListingPreview`: `site`, `target_key`, `target_url`, `listing_identity`, `rows`, `complete`, `observed_at`, `digest`, `blockers`
- 完全一覧のidentity/positionはsite-nativeで保証し、`Source.external_id`と一致。DOM順、話数文字列、URL連番、タイトル補正では境界を推測しない。access情報は観測した場合のみ表示（残quotaや取得成功可能性と混同しない）。

## Implementation
1. Magapokeの一覧load・全件展開・canonical order・ID/URL/話名/access観測を`site_adapters/magapoke/discovery.py`内のread-only listing helperへ抽出し、既存Full/Incrementalと共用。上位CoreにMagapoke専用分岐を持たせない。
2. Site Adapter optional capabilityとして`preview_complete_listing(page,target)`相当を追加する（既存`iter_records`の挙動・返却型を不必要に全面変更しない）。共通callerが明示的に「未対応/不完全」を判断する。
3. Shared CDP Browser Sessionを利用。`Page`はread-only listing観測専用で、新規Reader/Viewer遷移、`grant-only`、`quota`、購入、捕獲を行わない。実サイト/認証ありではログイン済状態の観測だけで権利を消費しないことを確認。bounded retry/timeout/件数上限とno-progress guard。
4. 一覧digestはlisting identity + ordered stable IDs + authoritative positions等から計算し、Site表示の変化や不完全を識別する。catalogにあるか・取得済かは別のread-only snapshotでjoinし、欠損は「Catalog未登録」と表示。
5. 一覧をGUI側に返してからチェック状態を変更しても、siteへ都度再アクセスしない。保存/適用には新鮮さ検証・再previewを別途行う。
6. 対応前サイトは「Catalog参考一覧（完全性不明）」だけ表示し、無根拠にチェック編集をcommitさせない。

## Tests / acceptance
- 合成Magapoke listing: 全話/追加展開/順序/特殊回・重複ID/途中欠落/別title混入/不正URL/timeout/DOM変化を含む。
- preview実行前後のCatalog/Watchlist/management/ZIPのhash/mtimeとJob差異が**ゼロ**、権利消費アクション未呼出し。
- 初期`DiscoveryService`が既存Full/Incremental結果を維持（同じparserの共有で回帰させない）。
- 実サイト確認は必要最小限の読み取りのみ・明示的作業判断で実施。成功根拠を`PROGRESS.md`へ記録。Reviewerで無副作用を確認してExit。

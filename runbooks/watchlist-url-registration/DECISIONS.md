# Watchlist URL一括登録 — Stage 00後の採用決定（2026-11-02）

> Status: ADOPTED DESIGN / Stage 01–05 IMPLEMENTED（2026-11-03）。Stage 06–07は未着手。Stage 00の静的監査記録は [RESEARCH.md](00-contract/RESEARCH.md)。上位authorityが優先。実行証拠は [PROGRESS.md](PROGRESS.md)。

## Decision A — 正規URLが安全なら、ID/title未取得でも手動登録可能

- 現行Discovery用の**正規起点URLを公式host/HTTPS/厳格parserで確定できる場合のみ**、native work IDやtitleが未取得でも候補として保持できる。URL未対応・危険・変換先不明・別作品へredirectはblockedで、確認操作で解除しない。
- URL状態 valid/converted/blocked と、作品identity verified/unknown、title observed/manual/unknown、登録準備 ready/needs_manual_confirmation/needs_scope/blockedを分ける。URL validは登録readyを意味しない。
- ユーザーがlabel、所属する新規/既存Work、読みやすいwork_key/keyを明示確定して登録を進める。確認はsite-native identityの証拠にならない。作品IDはunknownのままで保持し、推測値を捏造しない。
- 同名/別episodeを同じWorkに自動統合しない。既存Workへの所属を指定した場合でもWatchlist/CatalogのSource owner、既存identity、key重複を再検査。既存Sourceの所属が曖昧な場合はblocked、既存stable ID・履歴の変更や横取りは禁止。
- Stage 01は解析DTOのみ。手動確認の候補・UI・永続化はStage 02/03/05で実装する。

## Decision B — 完全一覧previewは4サイトで先行完成

- 現行のread-only preview対応: magapoke, jumpplus, zeblack, comicdays。これはFullのcomplete inventoryとは別のcapability。
- Stage 04/05の複数key・scope/order/segments詳細設定はこの4サイトで先行完成。未対応7siteの完全一覧が必要ならWorkごと理由付きblocked。新規単一keyなら正規URL/手動確認/所有チェックで登録可能。
- 残り7site: bookwalker, comicfuz, hanayume, kadocomi, mangaone, piccoma, younganimal。後続Stage 07でサイトごとにread-only previewを実装・検証する。
- Stage 06はURL形式変換と作品metadataに限定する。Stage 05は11siteの自動metadata取得や7siteの詳細編集まで完了したことを意味しない。

## 受け入れmatrix

| URL | identity/title | 操作 | 登録状態 |
|---|---|---|---|
| 安全な正規URL | verified/observed | 既存照合を確認 | 検証後ready |
| 安全な正規URL | unknown/unknown | label/Work/IDを明示確認 | 所有検証後ready、identity unknownを維持 |
| 不正・未対応・起点不明 | any | 手動確認しても | blocked |
| 安全な正規URL | any | 複数keyでpreview未対応site | blocked |
| 安全な正規URL | any | Source owner/既存所属が曖昧 | blocked |

## Stage別反映

- Stage 01: 11siteの現行正規URL厳格認識とKadocomi episode→work pilot、identity/title unknownとURL状態を分離、no-write。
- Stage 02: 手動確定の証拠と候補版保持、work/key命名、同一性・所有衝突の判別。
- Stage 03: label入力、明示確認、URLがvalidでも登録未準備の表示、下書き保持。
- Stage 04: 現行4site previewのみでdraft-only詳細編集。7site未対応時はblocked。
- Stage 05: 明示確認済み正規URLの保存前所有/CAS検証、選択Workのatomic保存、Full確認とE2E。
- Stage 06: URL変換・作品metadata拡張。Stage 07: 7siteのread-only complete listing previewを段階拡張。

この文書は設計判断であり、コード実装・テスト完了を示さない。

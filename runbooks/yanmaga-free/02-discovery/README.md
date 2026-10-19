# Phase 02 — Full / Incremental Discovery・Catalog同期

**Start:** Phase 01の承認済み証拠（work/episode identity、真正な通常無料marker、一覧展開/順序）を`PROGRESS.md`で参照。証拠が足りない識別子やセレクタを推測で追加しない。
**担当:** Lead契約 → Implementer単独writer → Reviewer独立diffチェック。

## Goal / Change boundary

`site_adapters/yanmaga/discovery.py` とexports、`cli.py`のDiscovery registry、必要なUnit/Browser Integrationを実装。既存の`DiscoveryAdapter` / `DiscoveredRecord` / `DiscoveryService` / Catalogを再利用。Adapterから直接Catalogへ書かない。共有Schema/Core/他siteは原則変更しない。

## Requirements

1. **Watchlist入力:** Phase 01で実測した正規作品URL（必要なら正規episode URLからworkを安全に解決）を受理。HTTPS / 許可host / path / work identityを厳密にvalidate。redirect、query、canonicalが別workなら中断。`work_key`はWatchlist由来のまま、勝手に他サイトと作品をmergeしない。
2. **安定identity:** 実サイトに固有なchapter/episode IDをCatalog `source.external_id`に保持。作品跨ぎ一意性が証明できないなら初めから`<work_id>:<episode_id>`にする。サイト由来のcanonical episode URLを`SourceTarget`に保存。話数や表示文字列をstable IDにしない。
3. **一覧完全取得:** 作品全体の掲載済み話を「もっと見る」等で最後まで展開し、必要ならpaginationをたどる。native total/境界/重複/ループ/読み込み後snapshot整合性を確認。**全件確証の前にrecordをyieldしない**（`DiscoveryService`は逐次Catalog反映するため）。対象作品の公開一覧がそもそも部分的なら、完全な`full`と申告しない。
4. **分類:** 各話のrow-localな正の無条件無料だけ`free`。初回無料/黄色チケット無料/ポイントのみは正確に識別可能なら`quota`/`paid`、不確実なら`unknown`。同話の価格ラベルと真正free markerは両立する可能性がある。曖昧・相反・ログイン/Grant依存は`unknown`。閲覧権利を試し開きして判定しない。
5. **日時:** 掲載日時/無料終了日時が正のnative/public表示で確認できる場合のみ`published_at` / `free_until`。現在観測した期限無しは古い`free_until`をクリアするが、権限種別不明を期限無しだけで`free`にしない。`access_checked_at` / `last_seen_at`は今回の観測時刻。期限切れの誤eligibleを防ぐ。
6. **順序:** 最新→古い順にrecordをemit（現行Discoveryのincrementalを満たす）。`global_display_position`は**作品全体**のoldest=1を根拠がある時のみ付与。最古/最新、番外編、同日更新・話数以外の宣伝回を落とさない。`order_label`は見た目の話名、`order_key`は信頼できる時だけ。
7. **full / incremental:** `full`は検証済みの全範囲が完全なときだけ既存Serviceの未観測ソース整理を許す。不完全時`DiscoveryIncompleteError`を起こし、未観測sourceをmass-unavailableにしない。`incremental`は最新から既知話の連続を検出して停止し、**実際に観測した話**のアクセス状態と期限を更新。未観測の古い話は触らない（古いキャンペーン無料化を拾うには周期的`full`が必要）。
8. **bounded:** work-native identity、global positions、範囲境界を実測で保証できる場合のみ`supports_bounded_discovery`を有効にする。範囲を001..Nへ再採番しない。根拠がない場合は明示的にunsupportedとし、嘘のglobal orderを作らない。
9. **再実行:** 再full/incrementalはSourceを二重作成せず、`free→unknown/paid`や`unknown→free`を観測に従い更新。既存Itemの`completed`とArtifact/CrawlRunは変更しない。`available`は掲載の有無であり`access_mode`とは別に扱う。

## Tests / Review

- Unit: URL正規化/host/redirect、work+episode衝突、無料・初回無料・黄色無料・ポイント・競合・70+無料、期限/時区、同一話の併記、order/特殊回。
- Browser Integration: 展開全件・見えないrow・pagination/変動件数・重複/ループ・途中通信失敗・ソートdrift・complete前yield無し・scope/global position・匿名証拠とDOM/APIの矛盾。
- Catalog: fresh full、repeat full、latest-first incremental、known streak、無料終了/復活、failed fullで既存sourceがunavailableにならない、Completed+Artifactの再Discovery保護。
- Reviewer: すべての`free`判定を確かな第一者signalへ遡れるか、誤freeが回帰で生じないか、異なるworkが混線しないか。

**Gate:** Phase 01で検証した公開作品についてfull/incrementalの正しいSource集合と分類が出て、誤free・不完全fullによる削除・position破壊がなく、関連テストPASS / Reviewer BLOCKING 0。実サイトで全件確認できない場合は`NOT VERIFIED`を明記して次Phaseでも無理に成功認定しない。

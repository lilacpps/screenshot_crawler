# Phase 4 — Piccoma巻境界取得
開始: Phase 0で実証された構造とPhase 3の手動経路。Implementerがsite-local reader、Reviewerが証拠/side effectを確認。
- 指定された正規作品URL/product IDから公開話一覧と巻一覧を取得。既存Discoveryの安全な一覧parser/previewを必要な範囲で再利用し、Catalog登録・scope同期・access付与はしない。既存DTOの破壊的変更は避ける。
- 実証された巻ID/表紙URL・ID等の結合で、実巻番号、開始話ID/表示名、位置、版、観測日時、一覧完全性、証拠を返す。表紙がない・同一表紙複数・不一致・途中配信・最新未収録は理由付き未解決。最後の巻の収録末尾も確認可能なら記録し、証拠がなければ不明とする。
- GUIでURL指定→取得→参照情報表示・保存。承認済み手動境界は変更しない。retry上限、アクセス制御・サイト条件遵守。
受入/テスト: sanitized人工fixtureで正常、昇降順、欠落巻、重複表紙、部分一覧、wrong product、版違い、最新未収録、通信失敗。通常公開画面でPhase 0の複数サンプルを再確認。未検証部分は自動確定不可。BLOCKING-0でPhase 5へ。

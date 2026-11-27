# Phase 0 — Piccoma実サイトProbe
開始: 親Runbook。Leadが契約、Explorerがread-only調査、必要なら単一Implementerが隔離probe、Reviewerが証拠確認。
目的: 作品検索と巻境界取得を通常公開ページの情報から実証する。既存 piccoma/discovery.py の全話一覧、registration observation、ListingPreviewを確認。
- 既存watchlistから出版社/長短/分割/完結・連載/途中配信の異なる約10作品（実際にアクセス可能なもの）を選ぶ。検索不一致・同名別版も含める。作品名、product ID、話/巻一覧URL、件数、順序、取得可否を記録。
- 検索画面の通常操作、正規URL、候補のtitle/author/publisher/版を観測。無結果と一時障害を区別。
- 話一覧の表紙がどの行に属するか、巻一覧の巻番号/表紙/ID、DOM属性/通常表示データによる結合を確認。昇順/降順、遅延ロード、ページング、未単行本化、巻の欠落、途中配信を検証。表紙の出現順だけを巻番号にしない。画像URL/ID照合を優先し、画像類似は候補に留める。OCRは初期実装外。
- 本文・購入・チケット操作なし。CDP/Playwrightは既存ライフサイクル、専用Pageのみ、単一operator。証拠はsanitized構造/ID/判定表にし、画像/認証情報をcommitしない。
受入: 検索/巻境界抽出の根拠・失敗条件と手動fallback契約をPROGRESSまたはRESEARCH.mdへ。観測なしのselector/URL/巻対応を実装しない。Reviewer確認後Phase 1へ。外部要因のBLOCKEDでも手動経路Phase 1–3は可、Phase 4–5は証拠を待つ。

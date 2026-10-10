# Phase 03 — Free Viewer / 高忠実度Capture

Status: NOT STARTED。前提: Phase 01のViewer画像/END調査、Phase 02のidentityとaccess判定。
次段階: [Batch](../04-batch/README.md)。

## 目的
現在「無料」/「今なら無料」の対象話を確実に正規Viewerで開き、
**元画像を可能な限り無変換で保存**して本文すべてを正しい順序で終了まで取得する。
サイト側の表示方式をまだ観測していないため、Capture MethodはProbe後に決定する。

## Viewer/アクセス契約
- 実行時のcanonical URL/target external_idと対象作品・話IDを厳密に比較。
- 直接入場前に同一一覧等で現在の「無料」「今なら無料」positive signalを
  fresh check。古いCatalogのfreeやログイン状態だけでは許可しない。
- 課金/チケット/待機/解放/login操作、別話への遷移はしない。
  必要な未対応CTAが出たらfail closed。auto/direct限定、quotaを拒否。
- サイトで観測された単画面/見開き、上部Viewer、再開/巻き戻しを正しく扱う。
  body index、page-change readiness、loading、広告、END/NEXT_CONTENTを
  明示的なbounded state/signalsで判定。固定sleepだけでcaptureしない。
- 最終本文を落とさず、最終本文後は次話の有料Viewerに入る前にEND。
  spreadは片側欠損不可、読書順を守る。same-content/max_pages/timeoutを残す。

## 画像取得の決定ゲート
優先順位は docs/CAPTURE_STRATEGY.md のauthorityどおり。

A. **Original image bytes**:
  Network response等から現在表示中のページと1対1で一致する元JPEG/WebP/PNGを
  Provenanceで証明できれば、そのバイト列をそのまま保存（再エンコード禁止）。
B. **JPEGの無劣化スクランブル復元**:
  画像responseがスクランブルJPEGなら、実際のdraw map・sourceID・全tile coverage・
  orientationとMCU境界を検証。Jump+/BookWalkerのjpeglib DCT係数入替方式が
  **実geometryで適合すると証明できる場合だけ**復元JPEGを保存。
  係数/量子化table・見た目・画像内容を厳密に比較する。
C. **Source-derived pixels**:
  Bが成立しなければ、正確なdraw trace/source pixel/mutation/transform/背景を
  再現し、既知良品のrendered RGBと同一であると証明する。
  証明済みpixelをlossless WebPで保存し、encode/decode pixel round-tripを検証。
  エンコード失敗時は同じ検証済みpixelをPNGで保持。
D. **Rendered fallback**:
  Provenanceが不明なら安定したCanvas/content Locator PNGを使う。
  スクリーンショットは最後の手段。Viewer UI/広告混入や不完全描画を防ぐ。

**Stop condition**: DCT不適合などの否定的証拠が出たら無制限に探索せず、
失敗理由を記録してC/DでE2Eへ進んでよい。Dが唯一の実装可能な方式なら
品質制約（解像度、同一ページ照合）を文書化し、見込みのないJPEG復元を作り込まない。
ただしA/B/Cを観測・検証せず最初からDを恒久の標準にしない。

## 実装・テスト範囲
- site固有adapter / capture補助、正当化された小さいpure helper、
  対応Unit/Browser integration、site README/note。Core/Packagerの
  出力形式仕様を無断で改変しない。
- Unit: canonical target mismatch、free→nonfree、forbidden control、同一ページ、
  検証不可能なsource、MCU不整合、WebP lossless証明失敗とPNG fallback。
- Integration: CONTENT→CONTENT→END、LOADING→CONTENT、UNKNOWN、
  spread/片側不完全、最終本文、巻き戻し、別話遷移防止、fallback正しい状態。
- Live: 同一作品の代表2〜3話で先頭/中間/最終、画像のサイズ・順序・品質・元body照合、
  終端、数ページ連続のnavigation安定性を確認。保存画像と基準表示を視覚・pixel両面で監査。
- 独立Reviewerは原画像帰属根拠、誤ったjpeg係数変換、ページ脱落/重複、
  UI混入、最終ページEND、再開処理と他Adapter回帰を確認。高リスクCaptureはTesterにも渡す。

## Exit
本番で採用するCaptureレベル、証明手段、観測した解像度/ページ数、fallback頻度、
テストPASS/FAIL/NOT VERIFIED、差分とReview BLOCKING 0をPROGRESS.mdへ記録。
未対応layoutやDCT不適合を「完全復元済」と表現しない。


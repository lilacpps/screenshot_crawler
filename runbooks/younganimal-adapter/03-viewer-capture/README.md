# Phase 03 — Viewer / original-image-first Capture

Status: BLOCKED / NOT IMPLEMENTED. Target body sequence, END, and source/native attribution remain unproven; live work stopped after HTTP 429 in Phase 02. No further live requests were made. Prereq: Phase 02 review and safely available live evidence.
Next: [free Batch](../04-free-batch/README.md)。

## Primary design
まずHanayumeの現行main `adapter.py`（R8/R9/R10）と
`native_capture.py`の対応ロジックを参照して、ヤングアニマルのObserved Viewerを実装。
**独立Adapter/独立native_captureでもよい**。
Hanayume専用URL、960x1540、`total-5`、画面上のCanvas実寸をコピーして定数化しない。

### Viewer state
- exact target source URL/work identity、current page counter、seek値、
  物理`#xCVPages`のwrapper数、body slot、spread片側/両側、初回状態、
  初回非本文intro、履歴からのresume/rewindを観測し、支持できるレイアウトだけ実装。
- Hanayumeの`mode-has-top-emptypage`とphysical-count variantを調査項目にする。
  **空白やPRに見えるからskipするのではなく**、siteによるmarker/状態と
  本文連続性の対応が正に証明できた場合だけ非本文として除外。
- 初期Canvasはloaded/renderedだけで即captureしない。
  必要ならHanayumeのgeneration/write/identityのbounded quiet waitを転用。
  逆にnative hookがない場合はrendererの安定性を別の有限signalで確認。
- ページ遷移は公開/正規のcontrolを使用、bounded timeout/同一内容防止。
  最終本文保存後のみEND。NEXT_CONTENTや有料の次話へ自動移動しない。
  対応外レイアウトや不完全見開きはfail closed。

### Capture method decision tree
**A. Exact original bytes** — HTTP responseやViewer sourceが1ページに1対1で対応するなら、
元JPEG/PNG/WebPバイトをそのまま保存。ページ同定を寸法/URL推測だけでしない。
**B. Lossless JPEG unscramble** — スクランブルJPEGなら実際のsource/destination
tile mapとMCU配置、DCT coefficient/quant tablesで可逆性を証明。
既存Jump+/BookWalker helperが適合しなければ無理にJPEGで復元しない。
**C. Source-native pixels** — 元のJPEG bitstreamが復元できなければ
Hanayumeの方式を参考にsource Canvas / mutable draw-time snapshotを正確に取得。
オリジナルの画素幅/高さで保存する（Display Canvasへの縮小ではない）。
exact target/slot/work、drawing context/transform/filter、
canvas generation/書込み状態を保存・検証し、Viewer描画結果とピクセル同値を証明。
検証済みRGBAをlossless WebP（VP8L、decode round-tripで全RGBA一致）へ。
encoder失敗・不適合なら元の検証済みPNG。
**D. Complete rendered Canvas** — source帰属が証明できなければbody canvas PNGへ。
同一spreadで片側だけ未確認なら丸ごとfallbackか停止。
generic Locator/UI screenshotへは無理に進まない。

### Fidelity and performance
- native hook内に重いPNG encoding/比重いhash/replayを入れない。
  mutable sourceの必要なコピーのみdraw時に取り、残りの検証/圧縮は選択後に遅延。
- WebPは**元のJPEGファイルの完全復元ではない**。ソース画素losslessと
  JPEGバイト完全維持をManifest/diagnosticsで区別。
- original bytes→DCT feasibility→draw-time source/clean Canvasの順で**有界に調査**し、
  DCT不適合が確認できたらC/Dの実装を進める。JPEG復元の研究によりE2Eが永久停止しないようにする。
- 同一ページで元画像/復元RGB・表示Canvas間の比較と代表ページの目視確認を行う。
  native captureがViewer navigationを不安定にしないかrendered-only controlと比較可能にする。

## Tests / exit
- URL/work違い、first-body欠落、空白lead-in誤skip、wrapper+1/等しい variant、
  unreadable/changed Canvas、wrong page/half、slow loading、resume、terminal premature、
  native proof/encoder/reset不正、WebP lossless、画像欠落と順序逆転をUnit/Browser Integrationで検証。
- Live無料2〜3話でfirst/middle/last/END、元画像候補のprovenance、
  source-native RGBA独立照合、fallback分布を確認。
- Reviewer BLOCKING 0 + 高リスクCaptureは独立Tester。
  native未証明でもDの安全な画素経路でE2E可能。ただし対応形式と品質限界を隠さない。

# 03 — 原画像 / source-native Capture を最大限追求する

Status: **NOT STARTED**。開始条件: Stage 00の画像経路仮説、Stage 02の安全なViewer baselineと正しいページ/END判定が確立済み。

## 目的（品質要件）

ユーザーの明示要望は「できる限り**原画像**を取得すること。簡単にPNGへ諦めず、できないときは**何を試し、なぜ無理だったか**後で説明できること」。

最低限のD描画PNGは基準画像・回帰用であり、A/B/Cの調査完了を意味しない。A→B→Cを**現物の配信形式/描画処理に照らして検証**し、成功が証明できる最上位方式を実装する。Aを選ぶために解像度を下げたりlossy変換したりしない。証拠がない「多分原画像」は禁止。

## 証拠クラス

| Class | 保存するもの | 必須の証拠 |
| --- | --- | --- |
| A ORIGINAL_BYTES | 該当ページ完成画像の元JPEG/WebP/PNGバイト列そのまま | response/DOM source一意IDと巻/ページ/表示slot対応、decoderとsize、crop/変形の不要性または表示への正確な対応、応答変化・preload誤混同の否定 |
| B LOSSLESS_RECONSTRUCTED | 元JPEGのDCT/MCU等を**無劣化**に配置して復元した出力、または証明済みlossless transform | 元符号化形式、全タイル・source→destination map、coverage、無重複/欠損、integer geometryやMCU/係数/量子化情報、復元→描画pixelの再現、巻/ページ対応 |
| C SOURCE_PIXELS_LOSSLESS | upstream source canvas/bitmapの**表示前source由来の完成ページピクセル**をlossless WebP/PNG保存 | 現在のsourceとrendererのID、draw/clip/scale/alpha/composite/transform、全領域再現、同一frame同期、独立したreader表示とのpixel-level整合、encode/decode roundtrip |
| D RENDERED_PNG | Viewerが**現在表示する本文だけ**のPNG | 対象巻/page/reader slot identity、現在のbacking dimensions、unobstructed+ready、before/after frame integrity、UI/広告混入なし |

Aは最も望ましいが、画像が元WebPならWebPを優先。BのJPEG無劣化復元は技術適合が証明されて初めて検討する。Cのlossless WebP/PNGは元符号化バイト列ではないので「原画像バイト取得成功」と書かない。Dを「native」と呼ばない。混在時は**ページ単位**でclassを記録し、見開きの片側だけが不成立なら不整合な混合保存を避ける。

## 03-A — 配信元・非加工ページ探査（A優先）

次を**それぞれ**調べ、最初に失敗しただけで次を飛ばさない。

1. 購入済みViewerの通常ネットワーク通信（document・first-party XHR/fetch・画像レスポンス）、`Content-Type`/magic bytes/寸法/bytesの分布。広告、サムネイル、試読、表紙、次巻先読みと本文を区別する。
2. 描画中のDOM `img` / `picture` / CSS background / `blob:` / Canvas sourceの実体と、Network候補への導線。Blob URL自体や読み込み順は永続IDではない。
3. 同一ページで配信される画像が「1ファイルで完成ページ」か、「連結された大画像」「分割画像」「タイルatlas」か、ピクセル操作前の中間Canvasかを分類。
4. source画像が現在表示している**この巻のこのページ**に一意に結びつくか、preloadやページ転換後の古いrequestを否定できるか。必要なら`drawImage`時のactual source identityとdestinationを少量・上限付きで記録。
5. 同一内容の低解像度配信用・高解像度配信用sourceが観測されたら、通常の許可されたReader経路で最大の高品質版を選び、crop/回転/合成で内容が欠けないことを確認。別の権限要求・隠しAPI・認証回避で高解像度版を探さない。
6. Aを採用したページでは元bytesのhash/format/dimensionsを記録し、再エンコードしないことをテストする。表示にscaleがある場合は**実際のscale/drawをreplayして由来を照合**する。単純なバイト一致が不可能でも、一意のsource/frame proofがあれば候補を棄却しない。

A不成立時に必ず「候補レスポンス数、形式、最大寸法、全ページを成さない理由、identity未証明ならその理由」を記録。**候補を観測できなかった**ことと「元画像は存在しない」は区別する。

## 03-B — 無劣化の再構成可能性（B）

実描画がタイル・断片・順番変更・元JPEGなどの場合の検討。まず実際のdraw操作を有限個だけtraceし、次を確定する。

- source座標・destination座標・rotation/scale/clip/alpha/composition・タイル重複・全領域coverage、viewer内の実順番。
- JPEGならsampling、MCU境界、tile source/destinationの8px等アラインメント、DCT coefficientsとquant tablesの保持可能性、lossless coefficient permutationの適用可否。
- WebP/PNGならJPEG DCT手法を流用せず、それぞれの符号化/画像配置で**無劣化**に復元できる経路が存在するか検証。
- edge strips・fractional scale・smoothing・複数段draw・色変換がある場合はその形を記録し、既存のBookWalker/Jump+/Piccoma実装へ単純に合わせるための丸めや補間をしない。
- 有望な形式だけ、既存のsite-local native-capture helperまたは最小限のPoCで試す。**元のencoded bytes/係数を保つ**ことを検証できない場合、その方式をBと称さない。

DCT不適合の具体的理由（例: 実測50pxタイルとMCU不整合）を示せば**その方式**は打ち切ってよい。ただしBの一方式が不適合でも、A/Cまで否定したことにはならない。暗号化/DRMや権利ゲートを迂回する復号・改変は実施しない。

## 03-C — source由来画素の取得（C）

A/Bが成立しなくても画面描画前の高解像度ピクセルを取得できる可能性を必ず検討する。

1. draw時のsource `ImageBitmap` / `HTMLImageElement` / `HTMLCanvasElement`（観測されたものに限る）のサイズ、write generation、rendererへの変換を確定し、後でmutable canvasを見て古い画像を誤結合しない。
2. 可能なら描画時にimmutable snapshotを取り、実際のdraw graphをscratch canvasへ再生。下流のtargetと**同じ現在ページ/frame**であること、全ピクセルまたは適切な再現性検査で一致することを証明。
3. 原解像度が表示より高いなら、source pixelsを最大解像度で保存するためのページ全領域・幾何証明を独立して持つ。**表示解像度で一致しただけでは、拡大していない高解像度sourceの全域が正しいとは証明しない**。
4. 既存の`lossless WebP` / PNG encoderを使う場合、RIFF/VP8Lなど符号化属性と全デコードピクセルのroundtripを確認。リサイズとlossy JPEG再圧縮をデフォルトにしない。
5. 別巻の画像、stale frame、後から再描画、readback/CORS失敗、未知composition、部分cropは `UNKNOWN`。正しいViewer proofが別途あればDへfallbackし、なければ収集失敗。

## 03-D — 最終Fallbackと検証レポート

A/B/Cすべてが実証できなかった**各対応layout**だけでDを使う。D自体も元サイズか、Viewport依存で縮小されたものかを記録し、書影や本文の欠損を認めない。

**必ず作る成果物:**

- `output/ebookjapan_experiment/phase03/source-native-evidence.json`（ignored）: sanitized、ページ本文や秘密情報なし。例: `work_id`(公開ID)、`volume_external_id`、`page_index`、`candidate_kind`、`source_format`、`source_size`、`render_size`、`draw_count`、`proof_status`、`failure_reason_code`、`capture_class`、`output_format`、`output_size`、`sha256`。
- `runbooks/ebookjapan-owned/PROGRESS.md` と `src/screenshot_crawler/site_adapters/ebookjapan/README.md`: A/B/C各方法の**試行有無**・成功/不成立/技術的に適用外・未実施の区別、実測値、次の条件。未実施を「不可能」と書かない。
- 第一/中間/最終・表紙/見開きのサンプルを両作品から選定（少なくとも別の巻・別のpage position）。レイアウトが異なる場合、class毎に検証。特定1ページの成功を全16巻へ一般化しない。

### 「諦めない」と「無限に追わない」の両立（終了ゲート）

- A: Network / DOM・Blob / upstream sourceという**独立した候補経路**を観測し、完成ページbytesの存在/不在、巻/page bindingがなぜ証明できないかを説明済み。
- B: source formatと実draw graphを取って、**適用可能な無劣化方法を列挙**し、少なくとも適合判定を実測。適合が見込める場合は小規模PoCまで試す。単一の既存アルゴリズムが失敗しただけでB全体を不可能扱いしない。
- C: source-derived pixelsのreadback/immutable snapshot/transform replay可能性と高解像度・pixel proofを実測。失敗したならsite/browser/formatの具体的ブロッカーを記録済み。
- 2作品・代表ページ・異なる描画profileの証拠が揃い、追加の試行で新しい判定に進める合理的な経路がない、または権利/技術上の明確なblockerがあるなら、その**観測範囲**でDを最終採用可能。
- その場合でもユーザーへ「原画像は絶対不可能」と一般化せず、「観測した版/環境ではA/B/Cがこの理由で不成立」と正確に説明。後日新しいソース経路が観測されたら再評価できるよう診断を残す。
- **独立Reviewerの画像由来・pixel/identity・権利境界レビューPASSが必須**。Explorerも独立にA/B/Cの未検討経路がないか反証する。

## Test / Live gate

Unit・fixture: source/target identity衝突、preload/stale frame、1枚対複数source、tile欠損/重複、MCU不整合、fractional transform、alpha、multiple canvas、overlay、readback blocked、WebP lossless invalid、encode/decode mismatch、half-spread fallback、page turn race、byte-preservation。

Live: ユーザーの購入済みページの代表箇所でsource候補から最終画像のformat/dimensions/pixel provenanceを検証。Dしか成立しなくても**A/B/C試行台帳の完成がStage03の合格条件**。証拠が取れないならこのStageは`BLOCKED / PARTIALLY VERIFIED`とし、完了と偽らない。

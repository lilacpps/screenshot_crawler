# 検証と画像処理の簡略化案

**Stage A/Bは独立Reviewer PASS。Stage Cのinterleaved manual comparison、source-native output equality、YAML200msのBatch END/ZIP/Catalogおよびfresh prepackage Manifest auditもPASS。Final Stage C Reviewer PASS / BLOCKING 0。** DPR微小差許容も実装済み。候補の行番号は調査時点のbaseline `69fccad` を指す。JSON実装前の値は[PROFILE.md](PROFILE.md)、同じ200ms条件の実装後計測は[PHASE07_PROFILE.md](PHASE07_PROFILE.md)と[PHASE07_MEASUREMENTS.json](PHASE07_MEASUREMENTS.json)に分離し、採用方針・検証状態は[RECOMMENDATION](RECOMMENDATION.md)を参照する。

## 現行source-nativeフロー

最新の採用範囲は [Phase 07](../../runbooks/piccoma-free/07-performance/README.md) に限定する。以下のPNG削減/snapshot統合等は候補比較として保持し、実装済みのJSON転送・YAML待機200ms・既存DPR維持に自動追加しない。

```text
fresh exact-free listing + canonical viewer identity
  → trace/response listenerをnavigation前に設置
  → p1への正規化、expected pageのloaded/geometry安定待ち
  → Runner state/context/identity確認
  → capture前reader構造・page ID・canvas確認
  → target trace baseline（guide非表示前）
  → 既知guideを検証して一時非表示
  → 全6 checkpointでfull native traceをJSON返却 → Python dict復元 → native trace/paint proof
  → exact URLの単一terminal JPEG response、load generation binding
  → byte budget/length/baseline JPEG/寸法検証
  → browser decoder + detached canvasで408 drawをそのままreplay
  → replay PNG出力
  → replay後target/source/paint再確認
  → Pillow RGBA白背景合成 → RGB PNG
  → fallback用PNG検証・再load
  → PNGを再decode → RGB → lossless WebP(method=6)
  → single VP8L + 寸法 + WebP decode全RGB byte一致
  → encode後target/source/paint再確認
  → adapter post reader/geometry + 出力format再検証
  → target generation再確認 + native target/source/paint再確認
  → guide復元・trace retire
  → AccessGuard、fingerprint、保存、manifest/progress更新
  → 固定pacing → next control → expected p(n+1)安定待ち
```

現行にはnative PNG encoding fallbackとCore PNG fallbackも存在する。本調査の速度評価はsource-native WebP成功経路を対象とし、fallbackを高速化成功には数えない。fallbackを増やす提案はしない。

## 何を保証する検証か

| 処理・位置 | 保証 | 分類と判断 |
|---|---|---|
| `adapter.py:393-473` initialize/listing | 現在の対象が個人権利に依存しないexact-free、canonical product/episode一致 | **必須**。初期化の1回。Catalogの過去freeを代用しない |
| `adapter.py:525-555,759-801` complete page list / detect | 完全な一意p1..pNとlast、supported layout、expected current、loaded/visible geometry | **必須だが取得・評価を統合可能**。同じfresh snapshotのpageIdsを使って評価する。話全体の永続cacheだけにしない |
| `adapter.py:565-616` body wait | expected IDの一意active、loaded、祖先visible、geometryを3回安定確認 | **必須**。固定pacingとは別目的。初期提案では3サンプル/100msを維持 |
| `adapter.py:815-848` capture前state/target | capture対象がexpected body page、単一canvas、native不可の場合もgeneration監視可能 | **必須だが同一観測の再利用が可能**。複数snapshotの不整合も避けられる。awaitを越えて無条件cacheしない |
| `native_capture.py:689-879` trace proof | 完全408 draw graph、fractional rect・context state、source ID/URL/load generation、寸法・coverage、hooks/overflow | **必須**。寸法/filename/見た目をbindingの代用にしない。draw履歴の不変部分のみgeneration付きcacheを検討可能 |
| `native_capture.py:883-958;521-585` white paint | opaque covering solid white、透明部分の見える背景、pseudo/sibling/text/clip/filter等 | **必須**。DOM走査負荷だけを理由に削除しない。paintはcanvas generationだけではcache無効化できない |
| `native_capture.py:1313-1358` response/body/JPEG | exact URL単一response、terminal200/image/jpeg、redirect無し、bounded length、観測baseline444形式・寸法 | **必須**。JPEG marker scanは形式契約であり、Pillow header確認だけと同義ではない。現在1ページ1回で、優先的削減対象にしない |
| `native_capture.py:1378-1409` replay後snapshot | browser replay中のtarget/source/paint変化を検出 | **現時点は維持**。後段検証と時間窓が異なる。削除するなら同等検出窓を新設する必要あり |
| `native_capture.py:978-994` composite | verified replay PNGの寸法/format、alphaを白へ正しく合成、RGB画素を確定 | **必須**。中間のRGB PNGエンコード自体は保証の本質ではなく削減可能 |
| `native_capture.py:1032-1045` fallback PNG verify/load | エンコーダ失敗時に返すPNGの整合性とdecode可能性 | **成功時に重複**。同じRGBから失敗時だけPNGを生成し、そのPNGを検証する案。生成エラーはfail-closed |
| `native_capture.py:997-1029` encode+roundtrip | single VP8L、expected dimensions、全RGB byte完全一致 | **必須**。method変更でも1回の完全decode/比較を残す。ヘッダ・サイズ・hashだけへ置換しない |
| `native_capture.py:1417-1448` encode後snapshot | 長い同期encode中にも動くブラウザのtarget/source/paint変化 | **必須**。thread化後も必須。encode前のproofを使い回さない |
| `adapter.py:957-1001` post reader + format | 同じpage/URL、canvas rect/loaded/祖先visible、method-MIME-extension一致、画像完全性 | reader/geometryは**必須**。既に完全decode・RGB一致を検証したimmutable native bytesの再decodeは**統合可能**。Core/native PNG経路の検証は別途維持 |
| `adapter.py:948-955; native_capture.py:1463-1488` adjacent final traces | target mutation、source変更、paint変更、hooks intactをadapter検証後にも検出 | **統合可能**。1回のfresh full snapshotを2つのbaselineへそれぞれ比較し、target異常停止/source-only fallbackの区別を維持 |
| `runner.py:376-467` AccessGuard/dedupe/persist | access停止、同じ取得の反復抑止、安全な保存・manifest authoritative | **必須**。今回の最適化対象外 |

「1回で十分」は同じimmutable bytesに対する画像検証に限る。ブラウザの可変状態を全体で1回しか調べない、という意味ではない。失敗時だけでよいのはfallback PNG生成などの補助処理であり、source provenanceや最終generation検証ではない。

## 画像処理をどこまで簡単にできるか

推奨する最小構造は次の通り。

```text
exact JPEG response + unchanged browser tile replay
  → replay PNG（当面維持）
  → decode once / RGBA白合成 / RGB object
  → lossless WebP(method候補)
  → VP8L・寸法・frame・RGB完全一致を1回検証
  → immutable verified result
  → fresh post-state / generation / source / paint checks
```

- **合成済みRGB PNGを省略**: `composite_replay_png_on_white` とencoder間でbounded RGB imageを内部受渡しする。確定したRGB byte列をreferenceとして保持し、同じPillow白合成・変換順を使う。色空間やalpha丸めを変更しない。通常成功時のPNG encodeと複数PNG decodeを避ける。
- **fallbackは遅延生成**: WebP失敗時だけ、保持した同じRGBからPNGを生成・検証する。現行と同じnative PNG fallback理由・metadataを維持。PNG生成自体の失敗は止める。
- **完全性検証を一元化**: site-local internal verified-resultを構築する時点で、immutable出力bytes、MIME/extension、VP8L構造、寸法、単一frame、全RGB一致をまとめて証明する。adapterは同じbytesに対する証明だけを受け入れ、任意CaptureResultの検証を省略しない。複雑な共通証明基盤は作らない。
- **browser replay PNGも除去する案は次段階**: RGBA直接転送は圧縮がなく、base64化なら約5.4MB/844×1200ページ。現状PNGより通信/コピー/メモリを増やす可能性がある。`getImageData`や別canvasへの白合成は色・alpha丸めの証明も必要。最初の変更では採用しない。
- **408 drawのstate設定一括化は低優先**: 現行validatorが全drawのstateを固定値に制限していても、対応関係とunsupported変化拒否を維持する必要がある。drawのfractional座標・50.01高さ・smoothingを丸めない。速度根拠がないうちに触らない。

## snapshot統合の安全な境界

1. `detect_state` 内の2回のreader snapshotを1回にし、その同じsnapshotからpage countとstateを判定する。状態観測が揃う利点もある。
2. capture前に同じfresh snapshotを使ってstate/page/geometry/target IDを評価する。target Locatorの一意性やtarget baselineは保持する。
3. **guide非表示前baselineと非表示後paint proofは同一にしない**。guide操作が入るため観測窓・paint条件が異なる。
4. adapter post validation後の隣接した2つのtraceを1つへ統合する場合、最後側の時点でfresh snapshotを取得し、outer target baselineとnative target/source/paint baseline・hooksを両方評価する。response countの最終再確認も保持する。後者だけを残すとnative capture開始前の変化を見逃す。unsafe target変更は停止、source-only変更は既存fallbackという区別を維持する。
5. traceの重いeventsを軽量generation/digestに置き換える構造案は、reset・retire・overflow・hook tamper・detached mutation・source same-URL reloadの全てを検出する設計が必要。generationだけに落とす案は不十分。
6. `paintSnapshot` の永続cacheや全page構造の初期化時だけの検証は見送る。CSS rule/CSSOM・animation・viewport・sibling/pseudoの変化はDOM MutationObserverだけでは完全に失効できない。

追加CDP計測でfull readerは平均約11ms/回、native full objectは平均167〜193ms/回だった。したがって同じ観測をまとめる候補はあるが、後者の大半は次の返却形式案で削減できる。JSON化後の隣接trace統合は約24〜28ms/回の候補となり、元のobject時間で効果を上乗せしない。paint走査自体はp1中央値約0.2msだったため、安全な失効条件を複雑に設計してcacheする優先度は低い。

### full trace JSON返却（Stage B実装・Reviewer PASS）

追加CDP計測では、同じsnapshotの計算時間に比べ、full objectをPlaywrightから返すwall時間が大きかった。Stage Bでは**全6 fresh checkpointで全fieldをJSON文字列返却し、Pythonで復元して現在のvalidatorへ渡す方式**を実装した。必要な検証はブラウザへ移管せず、408 draw記録・source情報・paint・hooks等を全て残す。Unit/browser testsで人工traceのdeep equality、target signature/validator結果、6 raw string経路、出力RGB一致を確認し、独立Reviewer PASSとなった。Stage Cは同一YAML200ms条件のobject/JSONを4回交互に12ページ計測し、48/48出力byte一致、fallback0、normal-cycle mean 3.601→2.743秒を確認した。Batch 24ページEND/ZIP/Catalogとper-page Manifest auditもPASS。詳細は[PHASE07_PROFILE.md](PHASE07_PROFILE.md)と[PHASE07_TESTER.md](PHASE07_TESTER.md)。Final Stage C Reviewer PASS / BLOCKING 0。

一般のJavaScript objectはJSONで可逆とはみなさない。実装はbrowser側でplain object/dense array/有限の対応値を直列化前に走査し、undefined/function/symbol/BigInt/NaN/Infinity/negative zero/sparse array/accessor/cycle/custom objectを拒否する。意図的なnullは保持する。PythonはJSON構文・duplicate keys・root schema/type・サイズを確認し、transport/parse errorはtarget continuity unknownとして安全停止する。新しい8 MiB (512 events × 16 KiB/event) / 131,072-node (512 × 256) 上限を越えたtraceは切り詰めずfail-closedにする。この上限のavailability影響とnegative zero拒否はreviewerが確認する項目。

実装前のmicrobenchmarkではfull object中央値157〜201msに対し、全field JSON返却＋Python復元は24〜26ms、2run×12pairの復元後deep equalityは全て一致した。これはsource response body/replayを行わないmetadata計測であり、実装後costの主張には使わない。実装後のlive effectは同一200ms条件のStage Cで実測済みで、結果は[PHASE07_PROFILE.md](PHASE07_PROFILE.md)に示す。

さらにcompactな後検証へ進む場合、numeric summaryやgenerationだけでは現行proofと同値にならない。初回のimmutable baselineを保持し、現在と同じtarget全draw/context/reset/retire/overflow、source URL/object/load generation、paint、hooks、response countの比較をfresh時点で実行し、比較結果だけ返す設計が必要。live参照の共有をbaselineに使わず、page/epoch変更時に破棄する。これはJSON返却案より設計・試験範囲が大きく、診断用compactの速さだけで採用しない。

## 通常live計測を阻むDPR比較

初回のCDP環境はDPR `1.0000000298023224` で、旧`adapter.py:689`の `[1904,1200,1]` 完全一致から外れた。ユーザーの追加指示により、現在は**有限数値かつ `abs(DPR-1)<=1e-7`** を受け入れる。bool/NaN/inf/非数値・許容外は拒否。他の1904×1200/Canvas/frame/可視性検証は維持した。この差の原因をChrome/OS・Piccomaいずれかへ断定しない。

これは速度改善ではなく、現在の共有CDPで標準取得を再評価するための障害除去。source-nativeの画素はsource/backing dimensionsとexact draw graphから再構成し、canvas/frame rect・inFrame・loaded/renderability・expected page・response/source/generation・paint・前後検証を維持する。実scale1.25/2を許容する変更ではない。Unit60件と人工browser Integration56件がPASSし、note/Adapter README/runbook支持範囲を同期した。独立DPRコードレビューはPASS/BLOCKING0。変更後liveの結果はPROFILEを参照する。

Reviewer指摘: exact 1判定はcapture前後でDPRが同じであることも暗黙に保証している。許容はsupported-mode認定だけに使い、**capture前後のraw viewport/DPRの一致を別途比較**する。観測値を1へ正規化せず、許容帯内でも観測間に変化があれば拒否するテストを追加する。観測間に変化して元へ戻る動きを連続監視できるという主張は置かず、現行と同じ検証時点・検出窓を維持する。

## 同期処理とページ遷移

Pillow composite/PNG/WebP/decode、JPEG marker scan、Python trace評価はasync関数内でも同期処理。特にWebP encode中はPython event loopが止まる一方、Chromeは動き続ける。したがってencode後のfresh検証を維持する必要がある。

CPU処理を `asyncio.to_thread` に移す案はAccessGuard responsiveness改善が主目的で、単独でwall-clock短縮を約束しない。thread取消でnative codecが即停止するわけではないため、同時1ジョブ・bounded memory・timeout時結果破棄・終了後fresh検証が必要。まずmethod変更/PNG削減で同期時間を短くし、残る問題に対して検討する。

thread化すると今まで同期処理に遅延させられていたRunner timeoutが適時発火しやすくなる。`runner.py:358-366` はcaptureの `PageChangeTimeoutError` をCore fallbackへ送るため、late result破棄だけで同等の安全性を主張できない。取消時のguide復元/trace retire、その後のCore fallbackのgeneration監視・metadata・AccessGuard停止を別途検証する。source-native最適化の通常成功経路と混ぜず、保証できなければこの提案は採用しない。

固定 `page_turn_delay_ms=1000` はshared pacingであり、描画準備待ちではない。authorityはoperatorによる0ms明示overrideを許す（`docs/ACCESS_CONTROL_AND_PACING.md:113-116`）。設定省略時の非0defaultは維持し、Piccoma限定の設定として評価する。save→manifest→設定delay→go_next→wait順を変えず、encode時間を差し引く処理も追加しない。100ms間隔・3観測の安定待ちは保持する（最初からreadyならsleepは2回で最低約200ms＋通信。300msの固定待機ではない）。0msにしてもexpected ID・loaded・geometry/style安定・timeout/UNKNOWN・URL/END・AccessGuardは残る。描画保証と、要求頻度増による403/429等の運用上の結果は別に確認する。

最新liveではfull trace6回が平均1.034秒、method6 encodeが0.572秒、replay RPCが0.486秒。408 draw自体は1.02ms、browser PNGは52.2msであり、タイルの描画再現を省く利点は小さい。JPEG取得/検証は計0.212秒だが現状1回の必須検証なので維持。PNG白合成・中間形式準備は計0.141秒で候補比較に留める。最新採用はPhase 07の検証回数を削らないJSON転送とYAML固定pacing200ms、既存DPR維持。method4/PNG等は今回の実装へ含めない。

## 推測を避けるための限界

同一episodeの実測は他作品・画像密度・Chrome/codec・CPUへの一般保証ではない。個別microbenchmarkの短縮を足し合わせてlive speedupとみなさない。画素一致が証明するのは保存RGBの可逆性であり、正しいresponse/pageを選んだことは別途provenance/状態検証で保証する。

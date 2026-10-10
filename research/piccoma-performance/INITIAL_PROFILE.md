# 初回調査・metadata microbenchの記録

この文書はDPR許容変更前の調査snapshot。現在の全体計測は[PROFILE.md](PROFILE.md)を参照する。以下の0ページ停止・未計測・仮予算は当時の状態であり、後続の通常取得結果へ上書きしない。

**調査のみ。本番コード・設定の最適化は未実装。** 対象 `28600/1910027`、基準 `69fccad`（Piccoma実装 `c10eea4` を含む）。計測日2026-10-10 JST。

## 環境と隔離

- CPU: AMD Ryzen 7 8840U / Radeon 780M、8 cores / 16 logical processors。
- Python 3.14.6、Pillow 12.3.0、libwebp 1.6.0、Chrome 153.0.8010.54。
- 既存shared Crawler ChromeへCDP接続。既存profile・タブ・Cookie・権利状態を変更しない。
- 通常shared contextと、DPR=1/1904×1200を明示した**隔離・非認証context**で試行したが、いずれもcanvas/viewport geometry guardで **0ページ・UNKNOWN停止**。Cookieは複製していない。
- 数値probeで `innerWidth/innerHeight=[1904,1200]`、canvas `[844,1200]`、canvas/frame rectとも画面内でnative寸法と一致することを確認。一方、JSのDPRは `1.0000000298023224` であり、`adapter.py:689` のviewport配列と `[1904,1200,1]` の厳密比較を満たさない。近傍DSF設定9点でも `0.9999999404` または `1.0000000298` に離散化し、exact 1を得られなかった。renderer起動引数の1.5だけを失敗理由とはしない。
- guardのshim/緩和や既存Chrome設定の変更は行わず、**今回のlive source-native取得は未計測（0ページ）**。追加で同じshared CDP環境の無料話p1を読み取り、reader/native snapshotを実測した。ページ全体の取得時間とは区別する。
- 標準 `CrawlerRunner + PiccomaAdapter` を使い、fresh exact-free preflight、source-native proof、1,000ms pacing、AccessGuardを維持する。Catalog/Batch/ZIPの性能試験ではない。
- 新規出力のみ `output/piccoma_performance/` に隔離。数値以外の画像・HTML・署名付きURL等は研究成果物へコピーしない。

## 計測の定義

関数の前後を `perf_counter` と `process_time` で測るin-process wrapperを使う。本番ファイルは変更しない。browser内の描画・PNG生成・paint DOM走査には、research-only init scriptへ `performance.now()` の読取りを追加する。描画引数・画素処理・proof値は変更しない。

- wrapperの親子spanは包含関係。`capture_page` とその内側のWebP encodeを足さない。
- browser JS時間はbrowser内のwall時間。Python `process_time` はPythonプロセスCPUのみで、Chrome CPUを含まない。
- async spanのCPUはその待機中に同プロセス内で動いた別taskを含み得る。CPUの厳密な関数exclusive帰属とはみなさない。
- 安定待ちは100ms間隔の3観測。readyならsleepは2回で最低約200ms＋RPC。固定300msではない。
- 初回ページと通常ページを分離する。初期化（listing/viewer navigation、resume grace）はページ時間と分ける。
- bounded `max_pages` で停止した場合はEND未確認。完全話・Catalog完成・ZIP成功の証明にしない。
- 画像の権利状態を変える操作は行わない。fallback画像はsource-native WebPの成功測定に含めない。

## コードから確定できる回数

通常native成功ページ、guideあり、loading retryなしの1サイクルでは次の通り。

| 処理 | 回数 | 根拠 |
|---|---:|---|
| full reader snapshot、transition waitより前 | 14 | Runner detect2 + identity3 + capture5 + go_next4 |
| transition stability reader snapshot | 最低3 | `adapter.py:565-616` |
| full native trace/paint snapshot | 6 | outer baseline1 + native before/after/final3 + adapter final2 |
| replay evaluate | 1 | 408 exact draws |
| guide hide/restore evaluate | 通常2 | guide存在時 |
| JavaScript evaluate合計 | 最低26 | 上記。target count/click、AccessGuard RPC等は別 |
| fixed pacing | 1回、設定1000ms | `runtime_settings.py:11,19; runner.py:111-115,465` |

trace snapshotは408 draw記録・source state・hooks・paintを返す。paintはcomputed style/ancestor/descendant/textを読む。回数の多さだけでは支配的な時間か判断できないため、以下の実測と合わせて読む。

## 実測結果

### 実サイトの9工程と未計測範囲

live captureは0ページで止まったため、「約5秒」の全体内訳は再現・確定できなかった。以下の未計測を0msと解釈しない。

| 工程 | 今回の証拠 | 限界 |
|---|---|---|
| 1. ページ送り前の固定待機 | 設定1000ms/turn、save→persist後に適用 | 実capture後のtimer実測は未到達。描画完了待ちとは別 |
| 2. next操作・描画完了待ち | コード上3安定観測、100ms間隔、最低約200ms＋通信 | 実サイトの遷移時間/prefetch影響は未計測 |
| 3. reader/canvas/trace取得・検証 | 追加CDP実測: full reader平均11ms、full native trace平均180ms。下記参照 | 同じp1の読取りmicrobench。successful capture全体/遷移中ではない |
| 4. 元JPEG response.bodyとJPEG検証 | exact response/body contractを確認 | live body読取り・decode・marker scan時間は未計測 |
| 5. 408タイルreplay | fractional draw/context state維持を確認 | real JPEGのbrowser decode/draw時間は未計測 |
| 6. replay PNGと白合成 | 下記ローカル白合成＋RGB PNG平均89ms | browser PNG生成/転送は未計測。入力はopaque RGBA surrogate |
| 7. lossless WebP encode | 同じRGBでmethod比較、下記表 | ローカルCPU実測。実サイト全ページの分布ではない |
| 8. WebP decode・RGB一致 | method6平均20ms、全method全byte一致 | ローカルopen→load→RGB比較。live中のCPU/RPC重複は未計測 |
| 9. final checks/save/manifest | 形式再decode平均18msをローカル実測 | live generation/source/paint・保存・manifestは未到達 |

### 追加CDP実測: DOM走査よりfull trace返却が重い

出典: [final run A](measurements/live-shadow-final-a.json)、[final run B](measurements/live-shadow-final-b.json)、[script](live_snapshot_shadow.py)。既存shared Chromeの9222へPlaywrightでCDP接続し、各runで新しい未認証contextを使った。fresh exact-free preflight通過後、標準RunnerはDPR guardで停止。その同じowned pageのp1で、初回warmupを除いて各variantを12回、2run測定した。通常ページ送り・body読取り・replay・画像保存は0。既存タブやprofile設定は変更していない。

readerは両側同じ`Page.evaluate`、nativeは両側同じ`Locator.evaluate`を使い、同じsnapshotを計算する。full object、診断用numeric compact、nativeのみfull JSON string返却を比較した。各側でsummary/JSON長の計算も揃える。**JSON案のwallは各rowのevaluate＋Python json.loadsの合計**から集計し、中央値同士を足していない。順序はfull→compact→JSON stringの固定反復、間隔100ms。順序の無作為化はしていない。

単位ms、各行n=24（12回×2run）:

| 対象・返却形式 | 平均wall | 中央値 | p90 | 最大 | JSON payload長 |
|---|---:|---:|---:|---:|---:|
| reader full object | 10.964 | 10.545 | 13.094 | 15.748 | 平均約13.1KB |
| reader numeric compact | 3.967 | 3.771 | 5.235 | 6.102 | 466B |
| native full object | 180.086 | 165.527 | 221.201 | 281.794 | A:391,028B / B:390,619B |
| native full JSON string＋json.loads | 25.948 | 24.363 | 29.423 | 49.645 | full objectと同じ全field/JSON長 |
| native numeric compact | 11.967 | 11.898 | 14.921 | 17.195 | 513B |

| run | native object 平均 / 中央値 / p90 / 最大 | full JSON＋loads 平均 / 中央値 / p90 / 最大 | 同じpairの平均差 |
|---|---|---|---:|
| A | 193.270 / 200.850 / 221.201 / 281.794ms | 27.656 / 26.289 / 30.895 / 49.645ms | 165.614ms |
| B | 166.902 / 157.252 / 189.317 / 248.695ms | 24.241 / 24.145 / 25.562 / 27.387ms | 142.661ms |

readerのbrowser snapshot中央値は約0.5〜0.6ms、nativeは約0.3〜0.4ms、paint走査は約0.2ms。nativeのsummary/JSON長計算は概ね1〜1.5ms。大きな差はDOM走査より**full object返却に伴うPlaywrightのserialization/transport/復元/scheduling等**にある。wall−browser JSを純通信時間とは呼ばない。JSON長はwire上の転送byte数でもない。readerのsummary timerはJSON長計算を含まず、その時間は残差側に入る。

各runでreader projection12/12、native projection12/12、**JSONから復元したfull objectのdeep equality12/12**、不安定pair0。408 draw、target/source/paint signatureの安定性、white paint validator、対応する単一200/JPEGレスポンスmetadataを確認した。JPEG bodyは読んでいないため、body完全性・replay画素・最終capture成功の証明ではない。numeric compactの一致は限定projectionだけで、full page IDs/全style/全draw/source proofを代用できない。

通常のfull trace6回へこの1状態の平均差を適用すると、JSON返却案は**約0.86〜0.99秒/ページの削減予算**になる。これは回数×microbench差の推定で、6回を含む通常captureのA/B実測ではない。source URL長・ページ内容・Chrome・PC・計測順で変わる。一方、JSON後に全6回をさらにcompact化しても、このsampleの平均差は約84msに留まる。proofをブラウザへ移管する大きな設計より、全fieldを保つJSON返却案を優先する根拠になる。

初回試行`live-shadow-a/b`にはPython/JS summary schema不一致とmatch件数の集計バグがあった。ReviewerとLeadが検出し、元データを残してscript修正後に上記finalを再計測した。旧データの一致件数は採用しない。JSONの非対応型をfail-closedにする将来契約は未実装で、観測したdeep equalityを全入力への保証に拡張しない。

### WebP method比較（同一RGB、4画像×3回/method）

出典: [raw CSV](measurements/local-webp-methods/webp_methods.csv)、[summary JSON](measurements/local-webp-methods/webp_methods.json)。既存の検証済みsource-native lossless WebPをread-onlyでデコードした同じRGBを各methodへ渡す。計36出力がsingle VP8L・寸法・全RGB byte一致を通った。画像やエンコード結果は研究ディレクトリへ保存しない。

単位は秒。p90はnearest-rank `ceil(0.9*n)-1`。encodeにはRGB bufferからImage生成も含む。verifyは別timer。

| method | encode平均 | 中央値 | p90 | 最大 | verify平均 / 中央値 / p90 / 最大 | 平均bytes | method6比のサイズ |
|---:|---:|---:|---:|---:|---|---:|---:|
| 0 | 0.190 | 0.208 | 0.238 | 0.283 | 0.024 / 0.024 / 0.026 / 0.036 | 936,699 | +14.33% |
| 3 | 0.444 | 0.457 | 0.570 | 0.769 | 0.020 / 0.018 / 0.030 / 0.032 | 824,211 | +0.60% |
| 6 | 0.817 | 0.971 | 1.187 | 1.293 | 0.020 / 0.019 / 0.031 / 0.032 | 819,327 | 基準 |

method6→3は**平均差0.373秒、中央値差0.515秒**（encode中央値約53%減）。method6→0は平均差0.627秒、中央値差0.764秒（約79%減）。これはこの4画像のcodec比較であり、ページ全体の削減率ではない。sample2ではmethod3中央値0.226秒に対しmethod6は0.215秒で、全画像が速くなる保証はない。method3でサイズが僅かに小さくなったsampleもあり、探索methodとサイズは単調とは限らない。

### 現行Python画像処理と直接RGB案（12画像×2回）

出典: [修正後raw CSV](measurements/local-pipeline-final/local_pipeline_pages.csv)、[summary JSON](measurements/local-pipeline-final/local_pipeline_summary.json)。過去の検証済みtarget episode p1..p12のRGBを使い、opaque RGBA PNGを作ってreplay PNGの**代用入力**とした。実サイトの半透明replay PNGではない。browser描画やprovenanceをこのbenchで証明し直したわけではない。

現行側はproductionの `composite_replay_png_on_white` → `encode_lossless_webp_or_png` → `capture_result_format_is_valid` をそのまま呼ぶ。直接RGB側は同じ白合成RGBをPNG化せずmethod6へ渡し、VP8L/全RGB一致を確認する。**両側とも最後の形式再検証を残す**ので、その削減効果は含まない。timer間のheartbeat用sleepは全て処理時間から除外する。

通常ページp2..p12、2run合計n=22、秒:

| 経路 / exclusive stage | 平均 | 中央値 | p90 | 最大 | Python CPU平均 |
|---|---:|---:|---:|---:|---:|
| 現行: PNG decode＋白合成＋RGB PNG encode | 0.0894 | 0.0844 | 0.1136 | 0.1191 | 0.0881 |
| 現行: fallback PNG入力検証＋method6＋VP8L/完全decode一致 | 0.6597 | 0.3966 | 1.2954 | 1.4593 | 0.6563 |
| 現行: adapterの最終形式再decode | 0.0183 | 0.0150 | 0.0276 | 0.0345 | 0.0170 |
| RGB案: replay代用PNG decode＋白合成＋RGB buffer | 0.0274 | 0.0267 | 0.0335 | 0.0373 | 0.0277 |
| RGB案: method6＋VP8L/完全decode一致 | 0.6012 | 0.3492 | 1.1546 | 1.2881 | 0.5994 |
| RGB案: 同じadapter最終形式再decode | 0.0184 | 0.0151 | 0.0288 | 0.0303 | 0.0170 |

これらは重複しない同期stage。同じページのstage合計を計算すると、現行通常ページ平均 **0.767秒**、RGB案 **0.647秒**。paired短縮の平均 **0.120秒**、中央値 **0.107秒**（平均合計の約15.7%）。PNG serializationとfallback用PNG入力検証の削減を合わせたprototype効果であり、PNG encode単独の効果ではない。

| run / 区分 | n | 現行画像処理合計 平均 / 中央値 / p90 / 最大 | RGB案 平均 / 中央値 / p90 / 最大 |
|---|---:|---|---|
| run1 / p1 | 1 | 1.415 / 1.415 / 1.415 / 1.415 | 1.498 / 1.498 / 1.498 / 1.498 |
| run2 / p1 | 1 | 1.230 / 1.230 / 1.230 / 1.230 | 1.198 / 1.198 / 1.198 / 1.198 |
| run1 / p2..p12 | 11 | 0.715 / 0.422 / 1.329 / 1.487 | 0.600 / 0.334 / 1.140 / 1.154 |
| run2 / p2..p12 | 11 | 0.820 / 0.530 / 1.441 / 1.590 | 0.693 / 0.412 / 1.217 / 1.356 |

p1は画像内容も異なり、この差からcold-startだけの費用は分離できない。run1のp1では直接RGB案の方が遅かった。normal平均もrun間に約0.10秒の差があり、0.12秒の改善値はこの固定試行順・小標本の観測として扱う。

### CPU、event loop、memory、計測負荷

- 上表の同期stageはCPU時間がwall時間に近く、Python processで概ね1core分のCPUを使う。全16 logical CPUに対する利用率ではない。Chrome/GPUのCPUは測っていない。
- ローカルheartbeatは50ms周期で、単発tickの遅れ最大 **1.425秒**。method6主体の同期処理がasync loopを長く止め得ることを確認した。browser access monitorの実際の停止遅延を測った値ではない。
- Windows working-set測定では、0ページで止まったgeometry probeのPython processは終了時49.64MiB/peak59.40MiB、instrumented人工fixture試験は終了時79.38MiB/peak130.07MiB。失敗runとpytestプロセスの値であり、成功liveページのpeak memoryは未計測。localbenchは12画像のRGB/PNGを事前保持し、productionの1ページ単位メモリ使用量を代表しない。RGBA/RGB bufferだけでも844×1200で約4.05MB/3.04MBあり、中間PNG除去はコピー/圧縮buffer削減に役立つ可能性があるが、production RSS削減量は未確定。
- full reader/native trace RPC回数はコードで数えた値。追加CDP計測ではnative full objectのPython CPU平均はrun A約78ms、B約73ms/回。JSON evaluate部分は約4〜7ms/回＋別のjson.loads CPUで、structured object復元負荷を減らす候補になった。Windows CPU時計は15.625ms程度の粒度で、単発の0msを無負荷とはみなさない。Chrome CPU/GPU・成功live全RPC数・メモリpeakは引き続き未計測。
- wrapperは時計/数値記録のみ、tracemallocや画像コピーによる計測はしない。localbenchは明示timer。instrumentation全体のunprofiled対照差は未計測で、無視できるとの定量保証は置かない。base `Image.Image.load` hookだけではcodec全decodeを測れないため、表のdecode値は明示open/load/RGB比較timerから採用した。
- 以前の非対称baseline（helper後の余分なdecodeをtimerに含む）は改善効果に使わない。最終判断には `local-pipeline-final` だけを使う。

上記CPU時間はWindowsの計測粒度も受けるため、数十ms以下のstageでCPUとwallの微小差を解釈しない。method固定順（0→3→6）とbaseline→direct固定順、warmup無し、少数サンプルという制約がある。

## 「約5秒」の説明と改善幅の解釈

確定しているのは1,000msのpacing設定、別目的の安定待ち、繰り返すDOM/trace取得、同期PNG/WebP処理である。追加liveのp1 full trace平均180msを6回に当てはめると約1.08秒、reader平均11msを最低17回なら約0.19秒の予算。ローカル通常画像処理平均約0.77秒、最小安定待ち約0.2秒と合わせても、異なる測定を足した概算約3.2秒であり5秒の再現ではない。元JPEG/body、browser replay/PNG、遷移、保存など未計測部分が残る。**5秒のend-to-end内訳と改善後のlive速度は未確定**。

全fieldを保つJSON返却案は約0.86〜0.99秒、method3は別4画像で約0.37秒、RGB案は別12画像で約0.12秒の削減を示唆する。単純合計約1.35〜1.49秒は**別測定の仮予算**で、5秒を仮基準にすれば約3.5〜3.7秒相当。ただし最適化実装・通常capture A/Bは行っていない。final trace回数削減をさらに現行full objectの時間で加算すると二重計上になる。まずJSON返却を単独評価し、その後codec/RGB案を分けて測る。pacing短縮はこの見積りに含めない。

### ページ移動の未計測範囲

ユーザー確認への回答: 「処理約2秒＋固定待機1秒＋未説明約2秒」は概算として近い。ただし処理約2秒も成功ページ1サイクルを測った内訳ではなく、p1 microbenchとlocal画像処理の積み上げ。さらに安定観測だけで最小約0.2秒＋RPCを要するため、概算残りは約1.8秒となるが、これを実測の残差とは呼ばない。

`go_next()` は状態確認後にPlaywrightの通常clickを行う（timeout 3秒は上限であって固定待機ではない）。その後、`_wait_for_body()` がexpected page ID・loaded・visible・同じ寸法/rect/viewport/祖先styleを100ms間隔で3回観測する。サイトの遷移animation、次ページ画像のfetch/decode/draw、clickのactionability待ち、追加pollは時間を使い得る。今回p2へ進んでいないため、それぞれの実時間は未計測。未説明時間にはこれらに加えsource body読取り、replay、browser PNG、保存等も含まれ得る。次の通常live計測ではclick開始/完了、expected ID初検出、loaded初検出、3安定観測完了を分け、固定pacingと重複計上しない。

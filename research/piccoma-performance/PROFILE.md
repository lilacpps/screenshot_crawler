# Piccoma全体性能計測（2026-10-10）

<a id="full-current-pipeline-live-profile-handoff-two-runs"></a>

採用後の実装範囲は [Phase 07](../../runbooks/piccoma-free/07-performance/README.md)（JSON・YAML待機200ms・既存DPR維持）。以下はStage B JSON実装前・1,000ms/研究用0msの歴史的測定記録で、200msまたはJSON実装後の測定結果ではない。この文書のcapture spansは旧object返却baselineとして読む。実装後の同一200ms object/JSON profileと現在の確認状態は[PHASE07_PROFILE.md](PHASE07_PROFILE.md)、[PHASE07_TESTER.md](PHASE07_TESTER.md)、[PHASE07_MEASUREMENTS.json](PHASE07_MEASUREMENTS.json)を参照する。Stage A/Bは独立Reviewer PASS。Stage Cのmanual/Batch/Manifest evidenceはPASSし、Final Stage C Reviewer PASS / BLOCKING 0。

DPR微小差を許容する最小修正後、指定無料話 `28600/1910027` を共有Chrome/CDP 9222で **12ページ×2run、計24ページ**取得した。全て `native_tile_replay_lossless_webp`、fallback 0、連続p1..p12。**このprofile run当時**はJSON転送・WebP method・PNG処理の本番最適化前で、baselineはmethod=6/full object返却/1,000ms pacing。method/PNGは現在も変更せず、Stage B JSONは後続実装・独立review済み。

通常ページ20完全cycleは **平均4.538秒、中央値4.151秒、p90 5.627秒、最大5.772秒**。約5秒という観測を再現する範囲で、未説明だった時間を工程へ分離できた。初回p1のcycleは5.571秒/5.398秒。bounded max_pages停止であり、今回ENDは未確認。以前の全話END確認と混同しない。

## 計測方法・証拠

- 環境: Ryzen 7 8840U、Python 3.14.6、Pillow 12.3.0/libwebp 1.6.0、Chrome 153.0.8010.54。
- 基準 `69fccad`＋DPR許容修正。viewport 1904×1200、DPRは有限数値で `abs(DPR-1)<=1e-7`、capture前後のraw viewport一致を要求。その他のgeometry/source/paint検証は維持。
- 既存shared Chromeの新規・未認証contextを各runで使用。fresh exact-free listing確認から標準Runner/Adapterへ入る。Cookieを複製せず、paid/ticket等を使用しない。
- 数値証拠: [full-profile.json](measurements/full-profile-current/full-profile.json)、[全span CSV](measurements/full-profile-current/full-profile.csv)、[重複のないcycle budget](measurements/full-profile-current/cycle-budget.json)。初回0ページ停止・metadata A/B・過去local benchmarkは[INITIAL_PROFILE.md](INITIAL_PROFILE.md)。
- 実行: `run_profile.ps1`、`profile_run_driver.py`、`profile_sitecustomize.py`。集計: `aggregate_full_profile.py`、`cycle_partitions.py`。画像は新規ignored outputだけで、数値成果物に画像/HTML/署名URL/認証情報を含めない。
- 1cycleはcapture_page開始→次capture_page開始。各run p1..p11の11完全cycle、p12は次capture開始が無いので除外。通常はp2..p11、2run合計n=20。取得済み画像は24枚だがcycle標本は22件。
- 初期化はcycle外。p1を通常分布へ混ぜない。p90はnearest-rank。以下の予算表は同じ20cycleを使い、親と子を二重加算しない。各行の中央値/p90/最大を足して全体とはしない。

## 全体の時間配分

秒、通常20cycle。実測Python spanの時間区間を分割した排他的内訳。平均列の合計が4.538秒になる。

| 工程 | 平均 | 中央値 | p90 | 最大 |
|---|---:|---:|---:|---:|
| capture_page（次表で分解） | 2.632 | 2.234 | 3.670 | 3.926 |
| ページ送り前の固定pacing | 1.008 | 1.008 | 1.013 | 1.015 |
| go_next（状態確認＋click） | 0.094 | 0.089 | 0.116 | 0.143 |
| wait_for_change（描画安定待ち） | 0.644 | 0.631 | 0.721 | 0.741 |
| Runner状態/context/identity/metadata | 0.070 | 0.068 | 0.081 | 0.096 |
| Runner AccessGuard確認 | 0.084 | 0.083 | 0.093 | 0.103 |
| 画像ファイル保存 | 0.0013 | 0.0014 | 0.0018 | 0.0018 |
| Manifest/progress更新 | 0.0032 | 0.0031 | 0.0038 | 0.0043 |
| その他のcycle gap | 0.0015 | 0.0014 | 0.0021 | 0.0022 |
| **cycle全体** | **4.538** | **4.151** | **5.627** | **5.772** |

遷移をgo_next開始→wait完了で各cycle内にまとめると平均0.738秒、中央値0.724秒、p90 0.806秒、最大0.826秒。固定1秒はこの外側。ページ移動には実際に約0.7秒を使っていた。

## capture_pageの内訳

秒、同じ20cycle。下表の平均合計は上表のcapture 2.632秒。親captureを再加算しない。

| 工程 | 平均 | 中央値 | p90 | 最大 |
|---|---:|---:|---:|---:|
| full native trace/paint取得6回の合計 | 1.034 | 1.037 | 1.082 | 1.202 |
| reader取得＋guide/locator等の操作 | 0.125 | 0.116 | 0.134 | 0.227 |
| 元JPEG response.body取得 | 0.093 | 0.077 | 0.146 | 0.154 |
| JPEG形式・marker・寸法の検証 | 0.119 | 0.094 | 0.183 | 0.191 |
| browser replay RPC（decode/408draw/PNGを含む） | 0.486 | 0.396 | 0.740 | 0.819 |
| replay PNG読込み・白合成・RGB PNG生成 | 0.093 | 0.085 | 0.118 | 0.123 |
| fallback PNG検証・PNG再読込み・codec準備 | 0.048 | 0.043 | 0.066 | 0.075 |
| lossless WebP method6エンコード | 0.572 | 0.318 | 1.198 | 1.442 |
| WebP decode/convert＋全RGB bytes比較準備 | 0.0245 | 0.0211 | 0.0354 | 0.0499 |
| 最終形式検証＋native比較のPython残余 | 0.0207 | 0.0179 | 0.0322 | 0.0348 |
| その他capture処理 | 0.0165 | 0.0167 | 0.0209 | 0.0277 |

source/target/paintの最終fresh確認もfull trace行に含む。最終native比較行へtrace時間を重ねていない。PNG/codec準備は中間形式とfallbackのための処理で、全てをWebP roundtripとは呼ばない。roundtripのconvertにはcodec decodeが包含され、codec decodeを再加算しない。

### 408タイル・PNG・replay通信の分離

下表はreplay RPCの内訳であり、上表へ追加しない。browserのperformance.nowを秒へ変換したduration。合成start/end時刻は実際のJS位置を表さないため、区間分割には使用していない。

| replay内の工程 | 平均 | 中央値 | p90 | 最大 |
|---|---:|---:|---:|---:|
| browser JPEG decode | 20.2ms | 15.9ms | 34.8ms | 36.1ms |
| **408 draw再現** | **1.02ms** | **1.05ms** | **1.30ms** | **1.50ms** |
| browser PNG生成 | 52.2ms | 42.6ms | 75.3ms | 96.4ms |
| replay RPC残余 | 412.6ms | 340.1ms | 642.4ms | 718.4ms |

残余はJPEG base64/描画specの引数転送、browser base64/Blob/Canvas準備、PNG data URL返却、Playwright変換・scheduling等を含む。純通信時間とは断定せず、各要素のexclusive測定は未実施。**408 draw自体の省略・state一括化は速度上の優先度が低い。**

## ページ移動は何を待っていたか

run2の通常p2..p11（n=10）は実Locator.click開始を基準に計測した。

- click呼出し自身: 平均37.8ms、中央値35.4ms。
- expected page ID/loaded状態の初観測: 平均62.3ms、中央値50.2ms。実際の変化時刻ではなく既存pollで最初に観測した時刻。
- 3回の同一signature安定観測: 平均672.4ms、中央値662.0ms（click開始基準）。
- loaded確認後にもrect/viewport/祖先styleを含むsignatureの安定待ちが続く。reset理由のcounterは無いため、animation/rect変化だけが原因とは断定できない。

run1はclick markerの識別不備でmilestoneがwait開始基準だった。run1/2のfirst-ID・loaded等は直接混ぜない。go_next/wait本体とcycleの計測は両run有効。今回は追加poll無しで既存reader観測を用いた。

固定pacing1秒、描画安定0.6秒、その他状態検証は別の目的。loadedだけで保存へ進める変更や3観測を1観測へ削る変更は採用しない。同じ条件を維持するreader/RPC統合は検討できる。

## 初回・ばらつき・CPU・メモリ

- p1 cycle: run1 5.571秒、run2 5.398秒。capture部分平均3.610秒、method6 encode平均1.140秒。画像内容と初回費用を分離できないので全てcold-startとは呼ばない。
- 通常capture CPU平均1.541秒/回、中央値1.234秒。全run Python CPUは22.234秒/22.063秒。async spanのCPUは同プロセスの他taskも含み得る。
- Python working-set peakは165.2/166.7MiB、終了時108.6/109.6MiB。JPEG・PNG・RGB/WebP等が共存する標準経路のプロセス値。
- 50ms heartbeatの最大遅れは1.443/1.628秒。同期codec/検証がevent loopを止めることをliveでも確認。Chrome CPU/GPU/RSSはshared他タブの活動が混ざるため未測定。
- run1 API counts: reader snapshot248、Page.evaluate260、Locator.evaluate108、Locator.count1753。full native traceは6回×12ページ=72回。`snapshot_native_trace`関数のcount24だけではhelper内のdirect snapshotを落とす。API呼出数はCDP wire往復数ではない。
- 計測は時計/数値記録、既存pollへのobserver、JS duration読取り。p1後に小さいnumeric progress JSONを1回書く。observer CPUは数値記録するが、unprofiled対照による全計測overheadは未測定。大きい画像copy/tracemallocは計測目的で追加しない。

## WebP method4の評価

同じ無料話の既存source-native p1/p13/p24のRGBをread-onlyで利用。各sample/methodに未集計warmup1回、0/3/4/6をbalanced orderで4回ずつ。各method n=12。**全48出力がsingle VP8L・全RGB byte一致**。出力画像は保存しない。[CSV](measurements/local-webp-method4/webp_methods.csv) / [JSON](measurements/local-webp-method4/webp_methods.json)。

| method | encode平均 | 中央値 | p90 | 最大 | 平均bytes |
|---:|---:|---:|---:|---:|---:|
| 0 | 0.236s | 0.206s | 0.320s | 0.454s | 1,052,250 |
| 3 | 0.514s | 0.586s | 0.648s | 0.671s | 940,149 |
| **4** | **0.483s** | **0.515s** | **0.589s** | **0.731s** | **940,149** |
| 6 | 0.938s | 1.162s | 1.323s | 1.613s | 937,396 |

method4はmethod6より平均0.454秒短く、合計容量は約+0.294%。method3と今回全sampleで容量が同じ、平均時間は約30ms短い。中央値サイズは681,864対682,062 bytes（4が198B小さい）だが、容量判断には合計/平均を使う。画像ごとに速度差は異なり、4が常に3より速いという保証はない。methodは圧縮探索の選択で、lossless/VP8L/RGB完全一致を維持する限り画素品質は同じ。**調査時には有力候補としたが、最新Phase 07の採用範囲には含めずmethod6を維持する。** benchmarkのencode timerはRGB `Image.frombytes`・save・context closeを含む。live表のWebP行はsaveのみなので境界も異なる。

この3画像と全体profileの通常20cycleは母集団が異なる。0.454秒を通常cycleからそのまま差し引いた値を実測速度とはしない。method4の本番設定はまだ変更していない。

## 判断と残る計測

主要因はfull trace反復返却（平均1.034秒）、固定pacing（1.008秒）、method6 encode（0.572秒で画像依存）、遷移（0.738秒）、replay RPC（0.486秒）。通常cycleの排他的gapは平均1.5msまで整理できた。replay RPC内部の約0.413秒は複数処理をまとめた残余として残る。

このbaseline時点では全field JSON返却→method4→中間RGB PNG削減、追加0ms調査時には0ms設定→method4→JSONを推奨した。最新のユーザー採用はPhase 07の**YAML200ms＋JSON、既存DPR維持**に限定する。JSON返却の以前のp1 A/Bでは1回平均143〜166msの差、通常は6回なので約0.86〜0.99秒の削減予算。**この文書に記録した取得は**全てobject返却で、当時の200ms/JSON速度は未測定だった。後続の同条件Stage C結果は[PHASE07_PROFILE.md](PHASE07_PROFILE.md)に記録する。method/PNG案との効果の単純加算やtrace回数削減との二重加算をしない。

DPR以外の本番最適化へ自動的に進まない。必要なsource/page/generation/white paint/RGB完全性/encode後のfresh検証を維持する。Catalog/Batch/ZIPの契約は変更していない。

## 固定待機0msの追加live比較

ユーザーの追加質問を受け、同じ話・method6/object返却・描画安定条件で、research専用 `PageTurnDelayMs=0` を12ページ×2run実行した。[数値JSON/CSV](measurements/full-profile-zero-delay/full-profile.json)、[排他的予算](measurements/full-profile-zero-delay/cycle-partitions.json)。本番crawler.yaml・共有defaultは変更していない。

**各run p1..p12連続、24/24 native lossless WebP、fallback0、AccessGuard停止/不整合無し。baseline run1の同ページと24/24 WebP bytesがSHA256一致**した。画像の再decode比較以前に全出力byteが同じだった。source/page/generation/white paint/全RGB一致/encode後検証、expected-ID/loaded/3回安定待ちはそのまま通る。max_pages停止でENDは未確認。

各条件の通常20完全cycle。秒。後から実行した別runとの比較で、ランダム化した因果実験ではない。

| 指標 | 1,000ms設定 | 0ms設定 |
|---|---:|---:|
| cycle平均 | 4.538 | 4.068 |
| cycle中央値 | 4.151 | 3.742 |
| cycle p90 | 5.627 | 5.143 |
| cycle最大 | 5.772 | 5.301 |
| pacing枠平均（Playwright往復・scheduling等も含む） | 1.008 | 0.0085 |
| capture平均 | 2.632 | 3.076 |
| go_next平均 | 0.094 | 0.115 |
| wait_for_change平均 | 0.644 | 0.666 |
| full trace6回平均（capture内） | 1.034 | 1.277 |
| WebP6 encode平均（capture内） | 0.572 | 0.649 |
| capture CPU平均 | 1.541 | 1.817 |

設定待機の枠は約0.999秒減ったが、0msのrunではcapture等も遅く、cycleの観測差は平均0.470秒・中央値0.409秒だった。原因を待機0によるもの/CPUやChrome負荷の変動のいずれかに断定しない。全run wallはbaseline59.989/59.413秒、0ms60.088/59.323秒でほぼ同じ。全runは初期化や初回・最後のpartial intervalを含むため、通常cycle短縮と同じではない。最適化後「必ず1秒短くなる」というend-to-end主張は置かない。

capture p1までの初期化は平均約3.93→4.54秒、p12 capture終了→Runner終了は約1.83→5.88秒に変動した。この最後のpartial区間は通常20cycleに含めない。zero run1のp12後の実go_next＋waitは約0.742秒で、その後Runner終了まで約5秒が未分離。`runner.py:497` のguard cleanupには5秒上限があるため調査候補だが、cleanup spanを独立計測していないので原因確定とはしない。最後の約5.9秒を描画待ちや毎ページの取得費用へ割り当てない。

結論は**今回の条件で0msでも描画・連続性・同一画素が保たれた**こと。固定待機は描画準備を保証する唯一の待ちではなく、描画待ちは残るため0ms採用候補にできる。短期2runから長時間アクセス負荷や将来の403/429不発まで保証しない。

research driverはdelayをRunConfigへexplicitに渡す。初回に生成したunused research YAMLにindent不具合があったが、そのファイルはdriverがloadせず、実行設定は0だった。script templateは修正・parse確認し、既存rawは上書きしない。instrumentation負荷の未測定、shared Chrome CPU/RSS未測定等の限界はbaselineと同じ。

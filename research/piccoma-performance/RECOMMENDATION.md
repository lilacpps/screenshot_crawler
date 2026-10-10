# 推奨する改善方針

**Stage A/B passed independent review.** Stage C interleaved manual comparison, source-native output equality, YAML200ms Batch END/ZIP/Catalog checks, and fresh prepackage per-page Manifest audit passed; final Stage C Reviewer passed with BLOCKING 0. DPR micro-tolerance/raw viewport equality are preserved. No additional WebP/PNG optimization was implemented. Preimplementation estimates remain in [PROFILE.md](PROFILE.md); actual same-200ms object/JSON results are in [PHASE07_PROFILE.md](PHASE07_PROFILE.md), [PHASE07_TESTER.md](PHASE07_TESTER.md), and [PHASE07_MEASUREMENTS.json](PHASE07_MEASUREMENTS.json). Guarantee mapping is in [SIMPLIFICATION.md](SIMPLIFICATION.md).

最新のユーザー採用方針（2026-10-10）は [Phase 07 runbook](../../runbooks/piccoma-free/07-performance/README.md): **JSON全field転送、crawler.yamlのPiccoma待機200ms、既存DPR許容維持**。Stage A/Bは独立Reviewer PASS。Stage Cの4本interleaved runでは通常20cycle mean 3.601秒 (object)→2.743秒 (JSON)、-0.857秒/23.8%。trace RPCは1.006→0.142秒/page、Python decodeは0.034秒/page追加。48/48のmanual WebP bytes一致し、専用Batch END/ZIP/Catalogおよび24-page manifest auditもPASS。Final Stage C Reviewer PASS / BLOCKING 0。画像処理は現行method6のまま。旧4.538秒/1,000ms値は異なるbaseline条件として記述し、200ms比較との差を因果評価に使わない。

## 優先順と変更の単位

1. **G: Piccoma YAML200msを既存経路へ設定する（Stage A実装済み・Reviewer PASS）。** root `crawler.yaml` に追加し、manual/BatchからRunConfigまでの既存loader経路をaffected testsで確認した（149 passed、0 skipped）。共通missing-file/site/field fallback1,000msと他サイトは維持。save→manifest→設定delay→go_next→expected-ID/loaded/3回描画安定も変えていない。Stage Cでactual CLI/Batchの200ms経路を確認した。
2. **K: full native traceをJSON文字列で返し、Pythonで復元する（Stage B実装・Reviewer PASS）。** 全6観測時点・全field・408 draw/source/paint/hooks/既存validatorを維持し、Pythonが同じdictを受ける。Browser側でunsupported valuesを直列化前に拒否し、Python側でも重複key、非有限値/negative zero、wrong-root/schema/type、サイズ超過をfail-closedにした。8 MiB/131,072-node上限を超えたtraceは切り詰めず拒否する。native/browser対象は139 passed、0 skipped。Stage Cでnormal-cycle平均0.857秒の短縮が測定され、48/48 corresponding WebP files were byte-identical with no fallback.
3. **Stage C live acceptance evidence: PASS; final Reviewer PASS / BLOCKING 0.** Interleaved manual comparison, per-page native/WebP/source/sequence checks, YAML200ms actual CLI path, dedicated Batch explicit END, ZIP/VP8L/Catalog Artifact checks, and fresh prepackage Manifest audit all passed. Audit retained URL/title/raw-manifest-free facts only and found 24/24 pages, 144 native evaluations, 144 JSON decodes. Final Reviewer sign-off is PASS / BLOCKING 0; Phase 07 is reviewed and complete.

DPRは実装済みの保護対象。WebP method4・中間PNG削減・snapshot/再decode統合・paint cache/thread化は調査候補として保持し、今回のrunbookから自動実装しない。

通常captureを再計測する前提として、DPR微小差許容を実装した。支持範囲認定とraw DPR/viewport前後一致を分け、他geometry・source・paint検証を維持する。速度改善自体ではない。詳細はSIMPLIFICATIONを参照。

## 調査候補ごとの評価（今回の新規採用はG/K）

| ID / 分類 / 優先 | 対象・現状 | 改善内容 | 実測/期待効果 | 保証維持の根拠 | リスク・必要な検証 |
|---|---|---|---|---|---|
| K / 採用・実装・review済み / 高 | `native_capture.py:641,897,1502,1673,1705; adapter.py:869,977`、実装前baselineではfull traceをobjectで通常6回返す | 全6地点のfull traceをJSON stringで返しPythonでdict復元。fresh時点・内容・既存validatorを維持 | **Stage C actual same-200ms:** mean normal cycle 3.601→2.743s (-0.857s/-23.8%); trace RPC 1.006→0.142s/page, decode +0.034s; capture 2.497→1.632s. WebP method6/pacing/stability unchanged. Preimplementation microbench 0.86–0.99s remains estimate only | Unit/browser assertions and live 48/48 corresponding WebP byte equality; 24-page native Batch through END/ZIP/Catalog plus prepackage per-page Manifest audit; 24/24 entries, 144 evaluations/decodes | New fail-closed 8MiB and 131,072-node bounds; unsupported values and negative zero stop. Stage B reviewer PASS; final Stage C reviewer PASS / BLOCKING 0 |
| A / 低リスクで効果の高い変更 / 高 | `native_capture.py:997-1029`、ページ1回のlossless `method=6` | 同じRGBでmethod4 | 最新3画像×4反復: 平均0.938→0.483秒、中央値1.162→0.515秒、容量+0.294%。全体live通常20cycleのmethod6は平均0.572秒で、別母集団の短縮をそのまま適用しない | 圧縮探索だけの変更。lossless/VP8L/dimension/全RGB一致を保持、48出力で確認 | サイズと画像依存性。全対象ページの同一RGB、単一VP8L、寸法、色・alpha・encoder失敗、変更後のlive A/B |
| B / 構造の簡略化 / 中 | `native_capture.py:978-1045`、replay PNG→白合成RGB PNG→複数回PNG load | 内部でRGB受渡し、失敗時だけPNG生成 | 12画像×2回の通常22件で合計平均0.767→0.647秒（約0.120秒削減）。同じmethod6/最終形式検証。代用RGBA入力・固定順のprototype実測 | 同じPillow alpha_composite/convertで確定したRGBをencoderとroundtrip referenceの両方に使用 | alpha丸め・buffer lifetime・fallback例外。fractional partial-alpha、全RGB一致、失敗PNG、metadata reset、memory上限 |
| C / 構造の簡略化 / 低（Bと同時に検討） | `native_capture.py:1057-1095; adapter.py:957-1001`、native WebPが直後とadapterで再decode | 1回のauthoritative complete decode+RGB proof、immutable result内部契約 | 出力形式再検証の平均0.018秒が削減候補上限。単独効果は小さい | MIME/extension/frame/VP8L/dimension/完全性/RGBを1か所で全て証明し、同じimmutable bytesだけを扱う | 任意CaptureResultを誤信頼しない。lossy exact-RGB、truncated/wrong MIME/extension/size、native/Core PNGも拒否条件を維持 |
| D / 構造の簡略化 / 中 | `adapter.py:525,759,815,1050,1076`、通常14 reader取得+wait>=3 | まずdetect_stateのpage countを同一snapshotから評価。capture/next内も順に統合 | p1 full reader平均約11ms/回、返却のみcompactで約4ms。1回統合あたり約11msが仮予算。通常capture speedup未測定 | URL/expected ID/contiguous IDs/loaded/geometry/visibilityを同じfresh観測で評価 | stale cacheやTOCTOU。compactの有限projectionは全page IDs/祖先styleの代用不可。capture/next直前確認、page-list追加/欠落/重複、hidden ancestor、cursor jump、ENDを試験 |
| E / 構造の簡略化 / 低（K後） | `adapter.py:902-907,948; native_capture.py:1463`、adapter後2回のfull trace | 1回のfresh traceでouter baselineとnative proofをそれぞれ照合 | full trace6→5回。現行objectなら約167〜193ms/回、K後なら約24〜28ms/回の仮予算。両効果を二重加算しない | outer期間のtarget不変性とnative期間のsource/paint/hooks不変性、response countを両方判定 | native-beforeだけ照合するとouter期間を失う。同値dimension reset、detached reset、source same URL reload、hook tamper、post-encode mutation |
| F / 高リスク・速度効果未確認 / 低（当初見送り） | 同期Pillow処理 `native_capture.py:978-1045` | 単一threadへoffload | live heartbeat最大遅延1.443/1.628秒。応答性改善が目的、wall-clock短縮は保証しない | 結果をawait後、現行と同等のfresh page/target/source/paint照合を行う必要 | timeout取消でもthread継続、Runner Core fallback時点変更。late result破棄、メモリ/同時数上限、encode中page変化とAccessGuard停止 |
| G / YAML設定として採用・Stage A実装済み / 高 | `crawler.yaml` のPiccoma entryは200ms。generic `runtime_settings.py` とRunner伝播を使用 | manual/Batchのsite settingからRunConfigまでの伝播を維持 | 旧設定との差800ms/advanceは設定上の差。Stage C object/JSON両armのobserved pacingは0.2080/0.2087sで、他区間も含む全体cycleは別途profile済み | readiness/expected-ID/3安定/END/AccessGuard、save→manifest→設定delay→advanceを保持。共通fallbackと他サイト値は不変 | 200msのmanual/Batch live pathと連続取得、Batch END/manifest/artifact checks all PASS. 0ms短期試験は長期負荷を保証せず、wall短縮は純設定値差と同じとは限らない。設定省略は1,000ms |
| H / 高リスク・低効果として見送り | `native_capture.py:521-612`、各snapshotのwhite paint再走査 | paint全体cache、generationだけで有効性判定 | live p1 paint中央値約0.2ms、6回なら約1.2msの仮予算。現sampleで支配的でない | 現状案では保証できない | CSSOM/animation/pseudo/overlap/text/viewportはcanvas generation外。必要な失効証明がなく見送り |
| I / 高リスク・低効果/効果不明として見送り | `native_capture.py:640-679`、408 exact draws→PNG transfer | RGBA直接転送、browser内白合成、draw state一括化 | live draw408平均1.02ms、browser PNG52.2ms。replay RPC残余412.6msは引数/結果転送・変換・準備等を未分離。まず測る対象で、直接転送の効果は未証明 | 同じ画素・fractional argsを証明する追加設計が必要 | 転送量/コピー増、alpha/color roundoff、描画stateの変更。最初の改善に含めない |
| J / 高リスクとして見送り | replay/encode後の状態検証、`adapter.py:565-616` stability | post-encode検証削除、3sampleを1sample化 | 数値上の待ちを削れても誤取得リスクが増える | 現状案では既存保証を維持できない | encode中のpage切替/遅延draw/未描画保存。削除しない |
| L / 高リスク・K後の追加効果小として当初見送り | `native_capture.py:1230-1277` などのfull target/source/paint比較 | immutable baselineと同じ比較をbrowser側で行い結果だけ返す | compact診断平均12ms、K平均26ms。仮に6回全置換でも追加約84ms。診断projectionはproof同値でない | 全draw/context/reset/source/paint/hooks/response countの同値比較が必要。generationだけでは不足 | JS/Python判定乖離・baseline参照共有・epoch失効。Kで大半を減らせるため当初見送り |

## Stage Bで確定した保証とStage Cの証拠

Stage B site-local code and affected tests passed independent review. The Stage C runs below exercised the same image/provenance contract and retained the production output behavior.

- **品質とbinding**: 観測JPEGとsource object/load generationが一意に対応。408 fractional draw args、context state/smoothing、white paint proofを維持。raw JPEG保存やscreenshot置換を成功扱いしない。
- **転送**: 実装済みの全6 fresh full snapshot JSON経路はPython dictへ復元して既存validator/signatureへ渡す。Unit fixtureはfull fields/null, signature, validator結果の一致を比較し、browser fixtureは6 raw strings、JS lossy-value拒否、JSON corruption fail-closedを検証する。Stage Cでもunsupported値/欠落、size bound、malformed schema、hooks/overflow/reset/retire、signed URLの同一性、エンコード後fresh検証を維持する。文字列返却を理由にfull snapshotの取得時点を早めない。
- **画素と形式**: 現行reconstructed RGBと全byte一致。lossless単一VP8L、expected寸法、単一frame、MIME/extension整合。中間PNG削減ではpartial alpha/fractional seamを重点確認する。
- **encode中の変化**: delayed encoderの間にpage ID、target draw、同値width/height reset、detach/reset/reattach、source same-URL reload、paint/visibility、hook tamperを変え、安全停止または既存source-only fallback区別が維持されることを人工browser fixtureで確認する。thread化するならRunner timeout/AccessGuard取消→guide復元/trace retire→Core fallbackが作動するタイミングも変わるため、generation監視・metadata・late result破棄をその経路で独立に検証する。保証できなければthread化は採用しない。
- **連続性**: expected p(n+1)以外へ進まない。loading/duplicate/missing/hidden/unknown guideで誤保存しない。final pN保存後だけexplicit last/END。max_pages/same-content維持。
- **境界**: AccessGuard停止、save→manifest→pacing→advance、format/metadata reset、fallback PNG、ZIP membership、Catalog完成条件は変更しない。
- **性能**: 同じCPU/Chrome/viewport/episode/pacingで反復し、初回を分離。avg/median/p90/max、サイズ、event-loop lag、RSSを記録。関数内microbenchだけでlive高速化完了としない。

既存testを拡張/parameterizeする対象:

- `tests/unit/test_piccoma_native_capture.py`: fractional full grid、white backdrop、partial alpha、lossless roundtrip、encoder failure、payload/MIME/寸法不一致、lossy WebP拒否。
- `tests/integration/test_piccoma_adapter_browser.py`: encode後target変更、same-value reset、same-URL reload、visibility変更、trace overflow/eviction、incomplete readiness、cursor jump、contiguous pages→explicit END、fallback metadata reset。
- pacingを変える場合だけruntime settings / Runner pacing tests。共有契約を変えないsite-local変更ではfull suiteを一律必須にしないが、境界に影響するなら該当integration/packagingまで広げる。

## 判断済み事項と残る確認

JSON返却案は型/schemaのfail-closedを含む条件付きでユーザー採用され、Stage Bへ実装されて独立Reviewer PASS。負のゼロを拒否するため既存trace値として現れた際は安全側に停止する。待機は0ではなく、他サイトと同様のcrawler.yaml Piccoma entryで200msを採用し、Stage Aの独立ReviewerもPASS。method4の容量許容とbench結果は保持するが、今回の新規実装範囲には含めない。

ユーザー追加依頼によるDPRの狭い数値許容＋raw前後一致は実装・Unit60/Integration56・baseline24native liveを確認済み。1,000ms baselineの遷移は平均0.738秒。追加0msも24native、出力byte一致を確認し、別条件の測定としてPROFILEへ記録した。

Stage C evidence is now available in [PHASE07_PROFILE.md](PHASE07_PROFILE.md), [PHASE07_TESTER.md](PHASE07_TESTER.md), and [PHASE07_MEASUREMENTS.json](PHASE07_MEASUREMENTS.json). The four interleaved manual runs establish the tested same-condition comparison; the dedicated Batch and prepackage Manifest audit establish the reviewed output path through END. The final Stage C Reviewer gate passed with BLOCKING 0. Performance evidence does not authorize a codec or image-pipeline change.

## 追加の誤分類修正

Piccomaのgenre欠落が包装の「小説」fallbackに流れる原因と最小修正を [GENRE_FIX_PLAN.md](GENRE_FIX_PLAN.md) に整理した。確認済み漫画のDiscoveryとoutput metadataを補完し、explicit優先を維持する。既存の非NULL誤値や保存済みZIP移動は別対応。性能最適化と独立した高優先の不具合修正として計画するが、今回は実装しない。

## 期待する全体速度と未確定事項

歴史的な1,000ms/object baselineは通常20cycle平均4.538秒、中央値4.151秒。実装後の同条件測定では200ms/YAML object→JSONが3.601→2.743秒平均だった。JSONの約0.86〜0.99秒は以前のlive p1 A/Bからの外挿予算で、現在は0.857秒のnormal-cycle短縮を別比較で観測した。method4の平均0.454秒差は別の3画像benchmarkで、通常cycleから差し引けない。RGB直接受渡しの約0.120秒も代用RGBA prototypeの値。これらを単純に足した秒数を約束しない。Stage Cでtrace RPC, capture, encoder, pacing, stabilityを分けて計測した。Final integrated Reviewer PASS / BLOCKING 0。

Kのfull JSON返却はsource-native取得・408 draw・白合成・Python検証・post-encode fresh検証を維持するようStage Bへ実装・独立reviewした。実装後liveでJSONはnormal-cycle meanを0.857秒短縮し、decoderは0.034秒/pageだった。K後はEやcompact proof移管の追加効果が小さく、paint cacheは今回のlive値でも割に合わない。post-encode検証を削除する案は採用しない。

0msのcycle平均4.068秒・中央値3.742秒は研究時の別条件実測。最新の採用は **YAML200ms＋全field JSON** に絞り、大きい構造整理やcodec変更は行わない。Stage A/B reviewer PASS。設定待機800msとJSON約0.9秒の事前予算を単純に加えず、実装後の同条件測定はPhase 07 Stage C reportsを参照する。Manual outputs, Batch END/ZIP/Catalog, and per-page Manifest audit passed; final Stage C Reviewer review passed with BLOCKING 0.

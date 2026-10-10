# 独立レビュー結果

2026-10-10、既存 `site_adapter_reviewer`（Sol / high）の初回checkpoint評価: **PASS / BLOCKING 0**。追加CDP調査は末尾に分けて記載する。

Reviewerはread-onlyでコード、調査script、仕様、成果物を確認し、CSVを独立集計した。編集、benchmark/test実行、ブラウザ操作は行っていない。

## 発見・修正確認

| 指摘 | 対応・最終確認 |
|---|---|
| B1: baselineだけhelper終了後の独立decodeまでtimerに含み、直接RGB案と非対称 | helper境界でtimerを閉じ、両側に同じ最終形式検証を残した。修正後 `local-pipeline-final` を再計測。旧データは不採用と明記 |
| B2: adapterだけのnative-only gateではRunner timeout→Core fallbackの保存を止められない | research profilerでRunner Core captureを例外化し、保存前gateも追加。None/fallbackを成功に数えない |
| output pathのprefix比較にdirectory境界がない | separator境界を含む比較、既存root拒否を確認 |
| base Image.load hookではcodec全decodeを測れない | そのspanをdecode性能根拠に使わず、明示helper/open/load/RGB比較timerの結果を採用 |
| stability待ちを300ms固定と誤読し得る | 100ms間隔3観測、最小2sleep約200ms＋通信と明記 |
| thread化でtimeout→Core fallback時点まで変わる | 取消、guide復元/trace retire、fallback generation/metadataの独立検証を条件化。当初は見送り |
| 未計測paint/replay効果を測定済みと読める表現 | 成功liveの時間効果は未計測、将来実測が必要と修正 |

## VERIFIED

- method平均/サイズを独立集計し、method6平均0.8167483250秒、method3平均0.4437351417秒、平均bytes819326.5→824211が報告と一致。
- normal22件、各側66 exclusive stage rowsから合計し、現行平均0.7673832318秒、RGB案0.6469450182秒、差0.1204382136秒が報告と一致。
- method比較36出力は全て `rgb_exact=True`。品質主張はlocalの同じRGBに限定されている。
- source response binding/408 draw/白背景/VP8L・完全RGB一致/post-encode fresh検証を維持する条件、final trace統合時の両baseline/hooks/response countが明記されている。
- 実サイト0ページ、opaque RGBA代用入力、固定順、少数サンプル、CPU/RSSの範囲、未計測部分が区別されている。初回の約4.5秒はcodec/RGBだけの仮予算であり実測速度ではない。追加CDP調査後の現在の予算はPROFILE/RECOMMENDATIONを参照する。
- production code/tests/仕様/note/configの変更無し。既存ユーザーの `watchlist.yaml` と `debug.log` を保持。数値成果物に画像・Cookie・署名URLは見つからなかった。

## 残る制約

対応環境でのlive A/B、半透明replay入力による将来実装の画素検証は未実施。これらは最適化実装の完了条件であり、今回の調査を実装済み・live高速化済みと解釈しない。

## 初回checkpointの検証実績

- Unit: `tests/unit/test_piccoma_native_capture.py` **45 passed、0 skipped**。
- Research / browser Integration: instrumented synthetic native replay画素一致fixture **1 passed、0 skipped**。
- local benchmark: 12画像×2run、method比較4画像×3repeat×3method、VP8L/RGB一致。
- Ruff: `research/piccoma-performance src tests` **PASS**。`git diff --check` PASS。
- Live: fresh-free確認とgeometry probeのみ。**source-native capture 0ページ、性能未検証**。
- Full suite / full browser Integration / Catalog-Batch-ZIP E2E: 本番契約変更がなく今回の性能調査対象外のため未実行。
- note更新無し: 現行実装・採用済み仕様・production tests・通常運用を変更していないため。

## 追加CDP調査の独立レビュー

ユーザー追加要求により、既存shared Chrome 9222でreader/native snapshotをlive比較した。Reviewerはscript、数値JSON/CSV、統合文書をread-onlyで確認し、evaluate＋json.loadsを各rowで足して独立集計した。ブラウザ操作・benchmark再実行は行っていない。

| 指摘・確認 | 対応 |
|---|---|
| BLOCKING: 旧traceのPython/JS summary schemaが異なり実際のprojection一致は0 | `dimensions`/`present`の差を修正して2runを再計測。旧raw数値は保持し一致証拠として不採用。final各12/12一致 |
| JSON evalだけではPython loads時間を落とす | 各rowのevaluate＋loads合計を集計。中央値同士を足していない |
| 数値compactは全proofと同値でない | 限定projectionとして明記。最初の推奨を全field JSON返却へ変更 |
| wall−JSやJSON長の解釈 | 純RPC latency/wire byte数とせず、serialization/transport/復元/scheduling等を含むと明記 |
| 固定の呼出順と単一状態 | full→compact→JSON string固定、p1のみ、warmup分離。通常10〜20ページのspeedupへ一般化しない |
| JSON型変換がunsupported状態を正常化し得る | finite/schema/欠落/NaN/Infinity等をfail-closedにする将来条件を明記。観測deep equalityだけで全域保証を主張しない |
| KとEの効果の二重計上 | JSON後の隣接trace統合は1回約24〜28ms相当。変更前の約150〜200msをさらに足さない |
| DPR許容案で許容帯内の変化を見落とし得る | 支持範囲認定とraw viewport/DPR前後一致を分離。正規化せず観測変化を拒否する条件を追加 |

独立集計で確認したfinal結果:

- 各run reader/trace projection **12/12**、JSON復元後full deep equality **12/12**、不安定pair **0**。
- full object平均 **193.27ms / 166.90ms**、全field JSON＋loads平均 **27.66ms / 24.24ms**。
- JSON長 **391,028B / 390,619B**。全408 draw記録・source・paint等のfieldが観測上維持される。
- fresh-free後の標準RunnerはDPR guardで停止。body/replay/save **0**。追加の成果は読取りmicrobenchmarkであり、capture/画素品質/live全体速度の検証ではない。
- paint中央値約0.2ms、JSON化後のcompact追加候補効果は小さいため、paint cache/proof移管を当初見送る判断は妥当。

追加checkpointの最終評価: **PASS / BLOCKING 0**。Reviewerが最終文書とscript修正を確認した。不安定pairを含むrunは集計を拒否し、一致数/比較数/安定数の名称を整理。aggregatorはraw reportを再書込みせず派生JSON/CSVのみ出力し、実行前後のraw SHA256不変をTesterが確認した。Ruff/compile PASS、Leadの`ruff check research/piccoma-performance src tests`と`git diff --check`もPASS。

将来実装時にはJSON型契約、mutation fixture、通常capture live A/Bが必要。本番コード・既存取得成果物・通常Catalogは変更していない。noteは現行実装・採用済み仕様・通常運用に変更がないため未更新。

## DPR最小修正・全体再計測のレビュー（追加依頼後）

上記の「本番変更無し」「0ページ」は過去checkpointの記録。追加指示後はDPRだけproduction変更、noteも同期した。DPRコードgateと全体計測harness予備レビューはPASS/BLOCKING0。最終統合文書のgateは以下の最終欄へ追記する。

- DPRは有限builtin数値の1±1e-7だけを許容、bool/NaN/inf/実scaleを拒否。他geometry/source/paint条件を維持。raw viewportはcapture前後で完全一致を要求し、帯内の値の変化も拒否する。
- Unit60、browser Integration56、instrumented synthetic pixel-equality fixture1がPASS、skip0。scopeに応じた検証であり、full suite/Catalog-Batch-ZIP E2Eは未実行（DPR site-local最小変更で共有契約変更無し）。
- independent numeric recomputationは22完全cycle/通常20、各capture6trace、各run72traceを確認。全体平均4.538023095秒、capture groups平均2.632123400秒、区間分割の保存誤差0。異なるlabelの有意な同priority重複が無く、synthetic browser-JS timestampsを区間へ使用していない。
- method4平均0.483381秒対6平均0.937666秒、容量+0.2937%、48出力VP8L/RGB一致を独立再確認。bench timerにRGB Image構築が含まれる点をPROFILEへ追記し、live codec-only表と区別した。
- Reviewerが発見したrun2 RSS終了値の誤記を109.6MiBへ修正。PROFILEの既存link anchorを復旧し、runbookの20cycle母集団・median非加算を明示した。
- 0ms harnessも静的レビューPASS。CLI→driver第四引数→RunConfigへexplicit0、403/429/challenge/captcha停止True、native-only保存gate、fresh-free、expected-ID/3回安定、max_pages/same-contentを維持。unused research YAMLの一時indent不具合は修正し、既存rawは保持、実行に使ったRunConfig値と区別する。
- 分類修正計画はgenre欠落経路、NULL/非NULL、explicit優先、漫画の根拠条件を独立確認。種別live確認は未実施の設計条件で、サイト全作品漫画扱いは採用していない。

Ruff `research/piccoma-performance src tests`、research compileall、`git diff --check` はPASS。数値成果物へのURL/認証情報patternとresearch内の生画像/HARは0件。通常Catalog/既存取得成果物/ユーザーwatchlist/debug.logを保持する。DPR以外のJSON/WebP/PNG/pacing設定/分類本番変更は行っていない。

### 最終統合gate

`site_adapter_reviewer` Solの最終評価: **PASS / BLOCKING 0**。上記nit全修正を確認し、0msのraw configured_msが全12回/runで0、各run72trace/12native gate、access_checkを独立確認。baseline run1対zero run1/run2の同ページWebPを直接bytes比較し24/24完全一致を再確認した。

0ms通常20cycle平均4.068100490秒・中央値3.742401200秒、pacing平均0.008508905秒、capture平均3.076370930秒と排他的予算保存を独立再集計。初期化平均3.93→4.54秒、末尾1.83→5.88秒も再計算して一致。末尾約5秒を毎ページ描画待ちへ帰属しない記載、JSONの約0.9秒を外挿予算に限定した記載、全run時間はほぼ不変という制約を確認した。

現在の推奨順G（Piccoma限定0ms設定）→A（method4）→K（full JSON）、genre未設定経路と漫画種別live確認を前提とした修正計画もPASS。長期0ms運用、最適化後live A/B、分類種別のlive確認は将来条件であり、今回の調査完了を妨げない。Lead最終Ruff/compileall/diff-check PASS、数値JSON/CSV28ファイルの秘密情報pattern 0、生画像/HAR 0。

## ユーザー採用後のPhase 07 runbook文書gate

上記推奨は調査時点の記録。最新採用は [Phase 07](../../runbooks/piccoma-free/07-performance/README.md) のJSON全field転送＋配布crawler.yamlのPiccoma待機200ms、実装済みDPR維持。method4/PNG等は本Phaseへ追加しない。今回の追加作業はrunbookと関連研究文書・noteの計画同期のみで、コード/設定は変更していない。

Explorer Lunaは6snapshot経路と既存manual/Batch設定伝播をread-only確認。Reviewer Solの最終文書評価は **PASS / BLOCKING 0**。JSON変換前のunsupported値検出/必要null保持、後検証・描画安定・AccessGuard、200msは配布YAML値で欠落fallback1,000ms維持、DPR実装済みとJSON/設定未実装の区別を確認した。manual設定smokeと専用BatchのEND/ZIP/Catalog検証を分離するnitは修正済み。リンク/YAML例/diff-check PASS。pytest/Integration/liveは文書変更だけのため再実行無し。

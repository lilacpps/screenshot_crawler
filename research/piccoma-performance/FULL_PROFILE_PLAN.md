# 全体再計測の実行契約（2026-10-10）

ユーザーは全体再計測、WebP method4の比較、DPR微小差の許容を依頼した。先行調査の0ページ停止を解消するため、DPR判定だけを最小修正する。JSON返却・WebP method・PNG処理等の本番最適化は今回のbaselineに混ぜない。

## 既知と未知

- shared Chrome/CDP 9222で実DPR `1.0000000298023224`。full native trace返却は同じp1で平均約180ms。これらはmetadata microbenchの事実。
- 通常captureの約5秒の内訳、p2以降の遷移、JPEG body、replay/PNG、保存は未計測。DPR値の微小差の原因も未特定。
- source-native JPEG/408 exact draws/white composite/lossless WebP/全RGB一致を保ち、画像権利や通常Catalog/成果物を変更しない。

## 変更範囲と役割

- Implementer（Luna）だけがPiccoma Adapter・対応tests・note/支持範囲文書を書く。DPR有限数値・狭い絶対許容（1e-7）、raw viewport/DPR前後一致、他geometry検証維持。
- Tester（Luna）はresearch scripts/resultsのみ。shared CDPの唯一のlive operator。DPR修正の独立レビュー完了まで実サイトcaptureを実行しない。
- Reviewer（Sol）はread-onlyでDPR diff・testsと最終計測/推奨を独立評価。
- Lead（Sol）は契約と結果を統合。他者・ユーザーの変更を保持する。

## 受け入れ条件

1. exact1と観測した近傍値を許容し、bool/NaN/inf/許容外/real scale1.25・2を拒否。許容帯内でもcapture前後のraw値が違えば拒否。安定観測のraw署名は維持する。
2. targeted Unit＋関連人工browser Integration、Ruff、note同期、Reviewer PASS後にliveへ進む。
3. fresh exact-freeの指定話をowned uncredentialed CDP contextで12ページ×2run（目標）。1,000ms pacing/AccessGuard/max_pages/same-contentを維持し、通常Runner/Adapterでnative lossless WebPだけ保存。fallback/不整合/拒否時は停止。
4. 初期化、p1、通常p2..p12を分離。capture開始→次capture開始を1cycleとし、親子spanを足さない。最後の完全cycleがない場合は別記する。
5. 固定待機、go_next/click、expected ID/loaded/3安定観測、reader/trace、response body/JPEG検証、decode/408draw/browser PNG、白合成/RGB PNG、WebP encode/完全一致、final checks/save/manifestを区別。不明なgapを隠さない。
6. WebP method0/3/4/6を同一RGBで比較。単一VP8L/全RGB一致、時間・容量・画像別差を記録。method4への本番設定変更は計測に含めない。
7. 成功ページ数・連続ID・native方式・fallback0を確認。bounded max_pages停止はEND成功としない。生画像・HTML・URL・認証情報はGit成果物へ入れない。
8. 全体/工程のavg/median/p90/max、CPU/heartbeat/メモリ・browser通信回数を可能な範囲で記録し、計測負荷・未測定を明記。最終Reviewer PASS。

通常Catalog/Batch/ZIPは変更・更新しない。DPR以外の本番最適化へ自動的に進まない。

## 追加質問に対する0ms比較・分類修正計画

ユーザーは固定待機0msの実用性を質問し、Piccoma作品の小説誤分類も修正計画へ含めるよう依頼した。1,000ms baselineと混ぜず、research-onlyの `PageTurnDelayMs=0` で同じ12ページ×2runを計測する。本番crawler.yaml・shared defaultは変更しない。operator override以外の順序・source-native画像処理・3回描画安定・expected ID・AccessGuardは維持する。

0ms結果は連続p1..p12、24 native、fallback0、拒否/不整合無し、同ページbaselineとのbytes/RGBを確認する。max_pages非ENDと少数runの限界を明記し、後で行ったrunのwall差を純pacing因果効果としない。0msは長期のアクセス負荷保証ではない。

誤分類はread-onlyコード調査と [GENRE_FIX_PLAN.md](GENRE_FIX_PLAN.md) の計画のみ。対象漫画の種別根拠、Discovery/output metadata、explicit優先、既存Catalog誤値と包装時fallbackの区別、必要テストを整理する。Catalog/包装コードや既存成果物を修正する段階には進まない。

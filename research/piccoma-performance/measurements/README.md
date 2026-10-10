# 数値証拠の採否

最終判断に使うデータ:

- `full-profile-zero-delay/`: research専用explicit0msの12ページ×2run。24native/fallback0、同ページbaselineと24/24byte一致、max_pages非END。`cycle-partitions.json`は通常20完全cycleの排他的予算（baselineのcycle-budgetと同じ分割）。後に実行した別runでCPU等も変動している。
- `full-profile-current/full-profile.json/csv`: DPR微小差許容後の標準source-native 12ページ×2run、method6/object返却/1,000ms pacing。全24 native WebP・fallback 0、max_pages停止でEND未確認。
- `full-profile-current/cycle-budget.json`: 同じ通常20完全cycleの排他的予算。親子を二重加算しない。`cycle-partitions.json`は先行の詳細分割で、最終文書のgrouped値はcycle-budgetをauthorityとする。
- `local-webp-method4/`: 既存native RGB 3画像、0/3/4/6、各warmup除外後balanced order 4反復。48出力のVP8L/全RGB一致。method4平均0.483秒、method6平均0.938秒、合計容量+0.294%。全体profileとは異なる母集団。
- `local-webp-methods/`: 同一RGBでmethod0/3/6、4画像×3反復。
- `local-pipeline-final/`: Reviewer指摘修正後、12画像×2反復。baseline timerをproduction helper境界内に限定し、両側で同じ最終形式再検証を実行した。
- `fixture-timing.json`: 人工browser fixtureでの計測配線・RGB一致確認。実サイト性能値ではない。
- `live_geometry_failure.json`: isolated CDP contextの0ページ停止時geometryを数値のみ抽出した証拠。
- `live-shadow-final-a.json`, `live-shadow-final-b.json`, `live-shadow-final-summary.json/csv`: 既存shared CDP 9222で、fresh-free後のp1 reader/native snapshotを各12pair×2run。full object/compact/full JSON string比較。JSON案の性能比較は各rowのevaluate＋json.loads合計を採用。この過去checkpointの通常captureは0ページで、DPR修正後のfull-profile-currentと区別する。

追加CDP読取りmicrobenchmarkの旧試行:

- `live-shadow-a.json`, `live-shadow-b.json`, `live-shadow-summary.csv/json`: full/compactのwall・JSON長を測定した初回試行。trace summaryのPython/JS schemaに差があり、`full_compact_projection_matches=0`。`full_compact_projection_match_count`は誤ってstable件数を記録していたため、一致件数の証拠として使用禁止。修正後の再計測を最終判断に使う。元データは上書きせず保持する。

**不採用の旧データ（改善効果に使用禁止）**:

- `local-pipeline/`
- `local-pipeline-comparison/`

これらは比較設計の修正前の試行。baseline側の独立検証用追加decodeがtimerに入り、直接RGB案との比較が非対称だった。最終結果との混在を避け、PROFILE/RECOMMENDATIONは `local-pipeline-final` のみ参照する。旧試行はレビュー指摘の経緯を検証する数値として保持する。

どのデータにも画像byte、Cookie、署名付きURLを含めない。通常の成果物・Catalogは変更していない。

# Phase 05 — 正常CLIでの実サイトE2E・独立監査

**Start:** Phase 01-04の成果とReviewerの修正反映が揃っている。指定作品のChapter 1は2026-10-20の観測時点で赤字通常無料だったが、E2E時点で無料とは限らず、fresh listing gateが必要。
**担当:** Leadが1 operatorを予約、Testerがread-only site確認と隔離E2E/Artifact検証、Reviewerが実際のdiffを最終査読。ImplementerはTester実行中に共有Chromeを触らない。

## Isolated run — Windows PowerShell（登録後の想定コマンド）

実行前に`python -m screenshot_crawler.cli --help`と`watch add --help`で引数を再確認。専用Crawler Chromeは別途起動しておく。**以下は実装完了後に実行する例であり、実行済み記録ではない。**

```powershell
New-Item -ItemType Directory -Force output\yanmaga_experiment | Out-Null
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

.\.venv\Scripts\python.exe -m screenshot_crawler.cli watch add `
  --watchlist output\yanmaga_experiment\watchlist.yaml `
  --key yanmaga-usagi --work-key yanmaga-usagi `
  --site yanmaga --url "https://yanmaga.jp/comics/%E3%82%A6%E3%82%B5%E3%82%AE%E3%81%A8%E3%82%AB%E3%83%A1%E3%81%AE%E3%82%86%E3%82%8B%E5%B1%B1%E6%AD%A9" `
  --label "ウサギとカメのゆる山歩"

.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover `
  --key yanmaga-usagi --mode full `
  --watchlist output\yanmaga_experiment\watchlist.yaml `
  --catalog output\yanmaga_experiment\catalog.sqlite

.\.venv\Scripts\python.exe -m screenshot_crawler.cli discover `
  --key yanmaga-usagi --mode incremental `
  --watchlist output\yanmaga_experiment\watchlist.yaml `
  --catalog output\yanmaga_experiment\catalog.sqlite

.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch plan `
  --site yanmaga --catalog output\yanmaga_experiment\catalog.sqlite

.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run `
  --site yanmaga --catalog output\yanmaga_experiment\catalog.sqlite `
  --output-root output\yanmaga_experiment\batch `
  --library-dir output\yanmaga_experiment\library --limit 1
```

**PowerShellの行継続記号はバッククォート**。指定作品URLのDiscoveryはPhase 02でshared-CDPにより確認済み。Phase 05時点で通常free話がなくなった、または日次上限等で非消費閲覧できない場合は、権利使用に切り替えず別の公開free作品を採用する。

## Tester acceptance audit

1. **Discovery/Catalog:** work/episode identity、実サイト全公開list件数、並び、特殊回、true freeとinitial/ticket/paidの除外、`free_until`、現在時刻、`full`と`incremental`の停止点・位置を照合。全件保証不可ならscope限界と`full`未完了を記録。
2. **Policy:** `batch plan`が`available/free`のみ選び、`direct`のみ・`quota=0`。初回無料、黄色無料、ポイント、権利不明、失効、logged-in grantを実行対象にしない。テストでは非freeが入らないことを検証し、実サイトの有料話を試し開きしない。
3. **Capture:** first/middle/lastを人が目視し、全頁の形式/サイズ/順序/番号/重複/空白/見開き/他話混入を監査。ViewerのENDまでのsequence、source-native attributionの証拠範囲、fallback理由を記録。本文外の宣伝/next-episodeを混ぜない。
4. **Archive:** Manifestの全pageとZIP member（順番/件数/filename/format）の一致、ZIP CRC、画像デコード、各pageのhash、重複、Catalog Artifact SHA-256/byte_size/locator、`completed`と成功CrawlRunを照合。Packaging前に必要なManifest snapshotを隔離保管してから監査し、不在なら「Manifest比較済み」としない。
5. **Negative paths:** synthetic/localで無効free/redirect・他episode・部分list・描画タイムアウト・END不正・ZIP失敗に対しpending/no success Artifactを確認。現在無料だったものが実行時非無料になれば消費せずSKIPし、ZIPを作らない。
6. **Rediscovery:** 少なくとも成功対象を再`full`/`incremental`し、Source IDと`display_position`、Completed timestamp、Artifact hash/size/pathが保存されることを検証。再planで完了済みを候補に含めない。
7. **Change impact:** 対象Unit・Browser Integration・Planner/Policy・CLI、関連siteの回帰、`ruff check src tests`、`git diff --check`。shared Core/Schema変更時のみ広いSuiteを追加。実行件数・skipped・未実行カテゴリと理由を明記。

## Gates and final report

**PASS（全体Done）** は、現時点で無条件無料と独立に確認できる少なくとも1話に対し、通常CLIで`full/incremental → plan → run → positive END → Manifest/ZIP → Completed`が成立し、上記整合性監査PASS、独立Reviewer BLOCKING 0の場合だけ。可能なら異なるレイアウトの2話目。

実サイトに一時障害、無料対象不足、認証/DRM要件、Readerの不明状態などがある場合は **Unit PASS / Integration PASS / Live NOT VERIFIED（理由）/ Overall NOT DONE** に分ける。無料だけの実装を完了するために初回無料/チケット/ポイントを使わない。

`PROGRESS.md`へcommit/branch、変更パス、実サイトサンプル・観測日時、全件/無料/skip件数、Captureの画像数/形式/寸法/END、ZIP CRC/sha、Catalog/再Discovery、テスト結果/skips、独立Reviewer/Tester、未解決点を記録する。`note/<next>_yanmaga.md`とsite READMEを現行挙動に同期し、`main`へ自動マージしない。

# P3 — Free-only Site Policy、Batch、ZIP/Completed

Status: Direct-only Policy/CLI and local Catalog-to-ZIP integration passed
their independent gates. The later direct-entry change also passed the
bounded live Runner probe and focused Runner/Batch browser fixtures. The
normal CLI/ZIP evidence below predates direct entry; current scope and
validation are summarized in [PROGRESS](PROGRESS.md).
**目的**: 既存CLI `batch plan`/`batch run`からカドコミの現在無料で未取得の話を
安全に選択、全ページ保存、ZIP化、Completedにする。

## 変更範囲

既存の `SitePolicyRegistry` と現行の`PiccomaSitePolicy`/direct-onlyな他siteの実例を確認し、
`src/screenshot_crawler/site_policies/` の既存形式でカドコミPolicyを作成。
CLIとRegistryの最小接続。site `kadocomi` だけに属する変更。
Batch Executor / Core Runner / Catalog schemaの大規模改修禁止。

## Eligibility / state machine

- `Item.status=pending`、`Source.site=kadocomi`、`available=true`、
  `access_mode=free`、正しく解釈できる未来の`free_until`またはNULL
  （期限なし）、有効なcanonical web targetのみ候補。
- `free_until=NULL` means Discovery observed no deadline; it is not
  a permanent entitlement. Planner eligibility comes from the
  current Catalog Source and Kadocomi Policy. Capture does not repeat
  Discovery or open a work-list page; on the exact episode route it
  validates the main document response, same-page identity/metadata,
  visible gate/dialog state, and bounded native-reader readiness.
- `quota/paid/unknown/owned`の特別な利用、ログイン、チケット/コイン/ポイント消費、
  click-to-unlock、purchase、grant-only、自動購入は全て不許可。
  認証済sessionの可読状態はfree保証にならない。
- `direct`以外のaccess strategyはreject/unsupported。batch/手動crawlの
  entry policyで課金動線をクリックしない。正常に無料Viewerへ入った後の
  非消費ページ送りだけ行う。
- The exact Catalog locator and configured `work_id:episode_id` must
  agree. A redirect to another work/episode or an unsuccessful main
  document response is a failure; no work-list request or second
  navigation is part of the capture run.
- `manifest`が全ページを指し、END正常が確認されたときだけpackagingと
  `completed`更新。missing page、見開き片側、last transition失敗、
  読めない/期限切れでは完成扱いしない。
- Batchは既存の停止・pacing/AccessGuard/metrics/--limitのルールを使い、
  skip/failureは正確に診断。ディレクトリ、旧ZIP、ユーザーファイルを上書きしない。

## Catalog位置 / archiveについて

- `Source.display_position` が安全に確定した場合、既存Plannerの
  `artifact_prefix={position:03d}`と`metadata.order=order_label`を使う。
- 不確定ならpositionを作らない（既存naming fallbackを利用）。
  過去非公開Sourceとの`display_position`重複、archive stem衝突をチェック。
  過去ZIPに一致するパスがあっても上書きしない。
- Discovery内で旧ZIP名は変更しない。必要なときだけ既存
  `scripts/renumber_archives.py`をdry-run→明示applyする。
- `order_label`やepisode IDを使った手動の1始まりprefixを作らない。

## テスト / gate

- P1で作った現在無料&pendingだけplanに含まれる。
  completed、unavailable、paid/unknown、明示期限切れが候補に入らない。
- Discoveryではfreeだったのに実行時に終了/期限切れ、別話redirect、
  ambiguous gate、missing total、END未確認でZIP/Completedが生成されない。
- directの正常2〜3ページfixtureでは
  `Catalog → Planner → Executor → CrawlerRunner → Manifest → ZIP → Artifact/Completed`
  の実pathを利用する。既存資源が消費された記録を残さない。
- 書き込み/packaging失敗ではpendingのまま、旧成果物・他siteのデータ不変。
- `--limit 1`で専用Catalog/Watchlist/outputへのlive Batchを行い、
  ページ数・順序・画素・ZIP/manifest・ItemのCompletedを検査。
- 既存Piccoma/他direct-only Policy/Batchへの回帰がないことを対応testsで確認。
  Core変更の場合は影響範囲を広げる。Reviewer BLOCKING=0。
- PROGRESSに実行コマンド、どのエピソードを無料と検証したか、取得結果/残課題を記録。

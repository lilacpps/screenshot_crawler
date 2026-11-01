# Operational scripts

`scripts/` は通常運用・保守用。BookWalker専用の診断・Probe・画像形式比較・
timing分析は `poc/bookwalker/`、それらのtestは `tests/research/` にある。

## BookWalker local quota

repository rootで次を実行する。既定は変更内容の確認のみ。

```powershell
python scripts/restore_bookwalker_quota.py
python scripts/restore_bookwalker_quota.py --apply
```

別のCatalogは `--catalog path/to/catalog.sqlite` で指定する。
readerに入れなかった場合も、1冊取得後に残時間で次の冊を取得したい場合も、
当日05:00 JST〜翌05:00 JSTのlocal予約を解除し、次の1回を実行できる状態に戻す。
既に1枠空いていれば何も変更せず、許可を何回分も貯める機能はない。

自動backupは作らない。対象はcurrent windowの予約1件で、複数ある場合は停止する。
CrawlRun・Item status・Artifact・access modeは保持するが、対象Sourceの
`quota_started_at` / `access_granted_until`はNULLに戻る。Catalog job lock取得と
timestamp一致確認の後に更新するため、同時実行中や予約が変わった場合は停止する。
旧 `--crawl-run-id` / `--source-id` / `--external-id` / `--allow-expired` /
`--backup-dir` は廃止した。

これはCrawler側のlocal制限を戻す操作であり、サイト側の残り10分を増やすものではない。
残り時間の取得・表示は未実装。Batchは引き続き明示された「まる読み10分」の
入口だけを使用し、失敗時に自動で枠を戻さない。

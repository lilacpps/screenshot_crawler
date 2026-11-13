# Stage 01 — Read-only 削除プレビュー

**状態:** PLANNED / NOT STARTED。前提: Stage 00の承認済み所有/ジョブ/パス契約とfixture。実削除は実装しない。

## 目的

`WorkDeletionService.preview(work_key, ...)` を作成し、対象WorkとDB全依存・退避ファイルを一意に列挙する。GUI/CLIから共用できるQt非依存の immutable DTOを返す。previewは完全read-onlyで、trash/backupディレクトリも作成しない。

## 変更範囲の候補

- 追加: `src/screenshot_crawler/maintenance/work_deletion.py`（Plan、FileMove、Blocker、PreviewService）。
- Catalogの必要なread-only queryは `catalog/service.py` へ小さく追加する。`read_work_archive_references` のZIPだけに依存して全Artifactを見落とさない。
- テスト追加/拡張: `tests/unit/test_work_deletion.py`、必要に応じCatalog/Watchlist tests。

## 実装契約

1. `work_key`を完全一致で解決し、存在パターン（両方、Catalog-only、Watchlist-only、NotFound）を区別。複数site/key・disabled/archivedを必ず含める。
2. Catalogは単一read-only snapshotで Work→Item→Source/Target→Run/Artifact、quota/scope/discoveryを列挙。IDだけで関連付け、作品タイトルやディレクトリ名で所有推定しない。
3. 全Artifact locatorを検査。present filesのpath/実体/size/hash、同じパスを参照する**全Workの全Artifact**、ZIPと対応statusの内容一致を確認。zip以外のpresent Artifactがあれば削除計画で扱える種類かを判定し、曖昧ならblocker。
4. 移動対象のroot（library, crawl-status）/trashが許可パスに収まり、symlink/reparse/hardlink、相互alias、同名destination、cross-volume、権限/空き容量に重大な問題がないことを検査。防止できないraceはApply直前に再検証。
5. rootの他のファイルは触らない。既存ZIP/stemに同じ名前の未管理statusがあればブロック。失敗runの中間出力はIDで所有を証明できるものだけ列挙し、判定不能ならwarning/blockerを明示。
6. Planには work_id・owner keys・各DB行件数・ZIP数と合計byte・全move mapping、Watchlist revision、Catalog内容fingerprint、各移動元hashと強いID、job状態、plan tokenを含める。JSON表示できるDTOにするがファイル操作はなし。
7. 不明情報を黙って空扱いしない。`blockers`が1件でもあればapply不可。Warningは意図的に手動確認を要するものと、移動に無関係なものを区別。

## テスト・受け入れ

- [ ] プレビュー前後でCatalog/Watchlist/ZIP/status bytes、mtime、ファイル一覧、Management job状態、backup/trashが不変。
- [ ] 2サイトの同一Workに属する全Sourceと歴史的Artifactが漏れなく列挙される。同名別Workは対象にならない。
- [ ] Watchlist-only / Catalog-only / no such work / archived/disabled / pending-only の件数・結果が明確。
- [ ] 他Work locator alias、改ざん済みzip、status mismatch、非管理root、missing-present、symlink/reparse/hardlinkはblockingとして表示される。
- [ ] 非ZIP Artifact、外部output、historical runと失敗run残骸を無視しない。
- [ ] ロック/変更検出に使うrevisionとtokenが同一内容なら安定し、内容変更なら失効する。
- [ ] targeted tests、独立review、PROGRESS記録完了。Stage02へ進める。apply入口はまだ存在させない/無効。

**禁止:** DB DELETE、Watchlist保存、ZIP rename、GUIからの本番操作。

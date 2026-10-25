# Stage 03 — チェック選択/除外/Full/Scope同期を整合させる

> Status: **PLANNED**。Stage01/02とMagapoke read-only一覧の証拠が前提。

## Objective
一覧上の任意の**非空集合**を、サイト順序に基づく`from_url/through_url`＋`excluded_external_ids`へ写像。Catalogが旧状態のままでも保存前に候補差分を見せ、Full後には既存Reconcilerで厳密に適用可能にする。

## Pure planning
1. `SelectionPlanner`相当のsite-neutral pure helperを設計。site-native `listing_identity`・全話unique ID・位置・URL・checked setの一致を検証。選択集合が空ならblocked。
2. 外側の最初/最後の選択行をinclusive boundsとし、その間で未チェックのIDだけを`excluded_external_ids`へ入れる。全選択はscope不要、片端指定や既存user-entered boundaryを保持したい場合は**操作前に意味の差を表示**して意図しない新着範囲拡大を防ぐ。
3. 同site別keyの所有者、同workの複数キー、旧Catalog Source、新規未登録行を差分分類。未登録は**見込み**として表示、実source/Archiveの確定数へ含めない。
4. 有償/無料/既取得のmetadataと取得対象maskを独立に扱う。`enabled=false`はDiscovery実行不可という別状態。

## Full/Proof integration
1. Discovery Adapter側のbounded基本区間判定を維持し、site-neutral Core側でexcluded IDだけをCatalog upsert/refresh対象から除外する。**別keyのSourceをreparent/updateしない**。既存同keyで除外されたSourceと履歴は保持。
2. Complete-listing証拠の`in_scope`は基本区間内かつnot excludedに補正する。除外IDは同じcomplete listingにあり、要求境界内で、重複しないことを検証。in_scope未登録SourceはFullで作成済であることを証明。site-native位置、snapshot digest、`target_scope_fingerprint`で証拠を封印。
3. `Full`が完了しても`scope-sync --apply`完了とは見なさない。現行の部分`apply_discovery_acquisition_flags`動作で`acquisition_enabled`が変わり得ること、古いsync marker/差分がBatchを止めることを検証する。
4. Preview用に`ScopeReconciler`の純粋な分類規則を適度に分離し、**提案ターゲット＋read-only listing＋Catalog snapshot**から予測を計算。旧`preview()`を偽Watchlist/偽Catalogで直接呼び出さない。正式applyは既存の`ScopeReconciler.preview/apply`へ戻し、CAS/lock/fingerprintをそのまま用いる。
5. 対象範囲外/除外行は`acquisition_enabled=0`に最終同期し、normal Batch/explicit grant-only/deferred resolver/replanで候補にならないことを確認。欠落証拠ならfail closedし、1話だけでも勝手に例外通過させない。
6. `archive_order`は担当内Sourceの再採番を再計算。未確定position/既存ZIP衝突がある場合はブロッカーとし、`scripts/renumber_archives.py`へ明示的に渡すだけ（自動renameなし）。

## Tests / acceptance
- 140話→100（除外40）→140復帰、100話の中で2話だけ除外→再選択、1話のみ選択、片端、全選択、空選択拒否、新着話追加とsite一覧変化。
- 同site別keyの穴を除外したケース、owner衝突、Catalog未登録の除外行、過去に取得済みの除外行、他site同work。個別除外変更の`fingerprint`とFull証拠、scope-sync diffを検証。
- 除外した未取得話でチケット/Quota/Reader/Batchが**一度も起動しない**こと。別keyや対象内の既存動作が維持されること。
- 未検証URL/未知ID/逆順境界/Full partial/stale proof/異常digest/既存ZIP番号drift時にfail-closed。同期途中クラッシュ後の復旧状態。
- targeted`test_watchlist`/`test_scope_reconciler`/`test_discovery`/`test_batch_acquisition_scope`/`test_batch_naming`/`test_archive_renumber` + affected adapter/CLI tests + shared change full suite。Reviewerがブロッカーゼロを確認してExit。

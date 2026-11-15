# Stage 02 — 初回無料をfree/directで開放して取得

**Status:** NOT STARTED
**前提:** Stage01 のDiscovery分類、匿名無料の回帰テスト、実サイトの初回無料表示とログイン根拠がPASSしていること。**grant-onlyの初回無料対応は作らない**。
**終了条件:** 1話につき1回だけ安全に無料開放→既存Viewerで全本文取得。失敗しても24h等の正しい閲覧期限内なら再開放せず再取得できる。

## 1. Viewer入場の実装

`src/screenshot_crawler/site_adapters/yanmaga/adapter.py` の `configure_run` / `initialize` / work listing preflightを必要最小限拡張。

1. `free` candidateは従来どおり `access_strategy=direct`。必ずsourceのcanonical URL・work-slug/episode IDと実画面一致を確認する。fresh listingのtarget 1行だけを使い、全件リストの裏で勝手に別話を消費しない。
2. 対象話が**すでにViewerを閲覧可能**と証明できれば、1回も開放ボタンを押さずに既存captureへ。
3. 現在の無条件無料なら従来のpreflightとViewer遷移を使う。
4. 現在の初回無料なら、本人ログイン済み、同一話の初回無料UIが唯一で有効、ポイント/チケット/会員登録誘導等と競合しないことを検証。**最後のawaitの後に対象ID・ボタンが変化していないことを再確認してクリックは最大1回**。認証を勝手に開始・変更しない。
5. クリック後はbounded read-onlyのアクセス状態確認。同一episodeのViewer正常本文、関連するサイト由来Grant証拠、ボタン表示の変化等、Stage01/02 Probeで有効性を確認した複数シグナルを用いる。クリック成功の戻り値だけでは消費確定としない。通信中断/timeoutでも再クリック禁止。
6. 観測済みの正しいViewerから**そのPageのまま**既存のrewind/native WebP/pixel proof/PNG fallback/positive ENDへ接続する。初回無料以外のボタンを代わりに押さない。
7. 途中でサイト状態が `quota` や `paid` に変わった場合、**directは新たなquota/paid操作へfallbackせず**Refresh/Discoveryを促してSKIP。キャプチャ成功まで本人の開放を待ち続ける無限pollは禁止。

## 2. 既存Grantの記録と再取得

**重要な現行コード契約:** `BatchExecutor._record_observed_resource_consumption` はquota candidateの `AccessConsumption` を記録する仕組みであり、初回無料の `free/direct` の記録先ではない。これを安易に使うと `quota_started_at` とwork ticket cooldownの誤記録になる。

実装順序：
- まず既存のCatalog/Executorの拡張可能点を確認。最小のsite-neutral `direct grant confirmed` という**追加の観測結果**を安全にRunner/Batchへ受け渡す方法を検討する。AdapterのCatalog直書き、RunnerへのCatalog依存は禁止。
- 本当に必要な場合だけ `CatalogService` に「site/sourceが一致・確定した期限を `access_granted_until` へ保存」する最小APIと、それを呼ぶBatch executor側の最小hookを足す。schema/既存モード/他サイトの意味を変更しない。
- サイトが確定したGrant期限を返すなら保存。表示上の期限が不明でも、サイト仕様を実サイトで確認して保守的な下限が計算できる場合にのみ記録する。曖昧ならNULLのままにし、再実行時の**サイト閲覧可否**を正とする。推定の `now + 24h` を無条件に記録しない。ただし、`quota/paid`へ再分類後に`access_granted_until=NULL`のままでは**既存Plannerがdirect候補にしない**。この状態での「再取得可能」は、Discoveryが同一話の現在Grantを正に証明して適切なdirect候補にできる等の経路を実装・検証した場合に限る。そうした経路が無ければStage02は未完了として扱う。
- **開放確定直後に記録**：END/ZIPが失敗しても `access_granted_until` は残り、Itemはpending。開放のみを「Crawl成功」「Completed」にしない。
- 再Discoverで `access_mode` が `quota` や `paid` に変わっても、有効Grantが存在する間はPolicyが `direct` を返し、実際に同一話をViewerで再確認して再取得。既存Grantの期限が切れればdirectを不許可にする。Grant期限不明でも、候補の安全な入口から同じ話のViewer権限を再確認できる仕様を検証し、可能なら同一runの再実行を回復させる。
- 再Discoverが行われることは**自動的に仮定しない**。再Discoverせず `free` candidateが残った場合も、実サイトで閲覧可能なら再取得し、閲覧不可/他resourceに変化したら追加消費なしで停止。

初回無料には `work_ticket` の資源使用カウントを発生させず、`quota_resource_states` に書かない。`AccessConsumption(resource="work_ticket")` を初回無料で立てない。診断上は初回無料開放確認済み・不明・未実行を区別できる非機微な状態を記録する。

## 3. grant-only除外

`batch plan/run --grant-only work_ticket` とsitePolicyのresource passが選ぶのは `quota` 候補だけ。`free`（初回無料を含む）はgrant-onlyで一切クリックしない。将来 resource を追加してもこの不変条件を維持。CLI test、Planner/Executor testで計画と実行両方に「初回無料は対象外」をアサート。

## 4. テスト・検証Gate

- 通常赤字freeは**従来DOM・匿名状態**で従来どおり非消費E2E可能。
- 初回無料が一意に見える時だけ、exact episodeにつき最大1クリック。成功後の正しいViewer、全ページ、END、ZIP/Completedを検証。
- 一度開放した後に画像取得/END/ZIPで失敗→pending、Grantが残る→再Discoverあり/なしで同じ話を再消費せず取得。後続ページ等の重複消費0。
- 期限切れかサイト上で権利不在→クリックせずSKIP、別種類の資源を消費しない。期限の時刻処理（JST/UTC、残り時間）を検証。
- クリックtimeout、例外、取消、リダイレクト、別話ID、DOM不明、複数CTA、ログアウト、paid only、同時表示矛盾→二度押し0、不要な有料操作0、Completedなし。
- 確定期限のDB永続化と、Catalog更新失敗/重複/実行中断時の失敗表示を検証。`free` から `quota/paid` へ変更されても有効Grantは正しく扱い、期限のないpaid自動取得は不可。
- 既存 `tests/unit/test_yanmaga_adapter.py`、`tests/integration/test_yanmaga_adapter_browser.py`、`tests/unit/test_yanmaga_discovery.py` と関連Policy/Executor/Catalogの選択テストを実行。`ruff check`、`git diff --check`。

**Gate:** サンプルで初回無料を実際に1回使ったかどうか明示。サイトの権利を消費できない状況ではLive NOT VERIFIEDとする。独立Reviewer BLOCKING 0の後にStage03へ。

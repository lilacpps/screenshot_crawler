# 01 — URL登録・購入済みFull Discovery

Status: **NOT STARTED**。開始条件: [00](../00-site-probe/README.md) の所有表示、全巻一覧、安定ID/順序が観測され、`PROGRESS.md` に記録済み。

## 目的 / 変更範囲

- `src/screenshot_crawler/site_adapters/ebookjapan/discovery.py` とサイト初期化を新設。
- `cli.py` のDiscovery Registry、URL登録Resolver経由のCLI/GUI選択候補に `ebookjapan` を接続。登録のUIを別機構として再実装しない。
- 対象URLは公式の `https://ebookjapan.yahoo.co.jp/books/all/<positive-id>/` を厳格に扱う。query、fragment、異なるhost、別作品へのredirect、曖昧なURLは拒否。表記の正規化範囲はP0で実証した形のみ。
- 既存 `WatchlistTarget` を使う。`key` は `<work_key>_ebookjapan` を推奨するが、CLI/GUIでユーザーが編集できる。`archive_order` は既存欄を維持。`discovery_scope` を求めず、`supports_bounded_discovery=False`（scope付きTargetは明示エラー）。
- 作品メタデータは安全な一覧情報から取得。`external_id` は巻固有の安定IDを使用し、閲覧用Source URLは公式の該当巻にbindする。単一`/books/all/<id>/` を全Sourceの閲覧URLに流用しない。

## Full Discoveryアルゴリズム

1. pageの作品ID、title、認証状態、表示ソートを確定。全巻リストの展開（存在すればページネーションやload more）を **上限付き** で完了する。読み込み失敗・不一致は `DiscoveryIncompleteError`。
2. 全カードを最後まで取得し、全件数・ID一意性・同一作品との紐づき・安定DOM snapshots・視覚順・新旧順を検証。「2列」は現在ユーザーが観測した表示形態であり、固定CSSレイアウト前提でコードを壊さない。
3. 全カードについて3値分類 `owned / explicitly_not_owned / unknown`。`owned` はカード自身の明示的な「購入済み」証拠が必要。未知が1件でもあるときは、未購入と見なしてスキップせず**Fullを不完全にして中止**。期限付きレンタル/試し読みはownedではない。
4. 全件の順番を `oldest=1` のglobal positionに正規化し、巻番号（1、2…や別冊/特装）と一意IDの矛盾を検査。単に文字列の末尾やIDの大小だけで順序確定しない。
5. 結果を**すべてバッファ**し、ownedのみの`DiscoveredRecord`を組み立てる。`access_mode=owned`、`available=True`、`kind=book`、`global_display_position`、任意`order_key/order_label`を含む。メタデータ取得途中で失敗したら1件もyieldしない。
6. `CompleteListingInventory` に**全カードの安定external_id/global position**と`selected_external_ids=owned集合`を渡す。`capture_complete_listing_inventory` または同等既存hookを利用。全件の権利観測が証明されない限りcomplete inventoryは発行しない。
7. Fullが成立したときだけyield。`incremental` 入力は、Catalogに触る前に明示`DiscoveryIncompleteError`で拒否する。Owned 0件はログイン・完全一覧・無所有が証明できたときだけ許容し、ユーザーの2作品では申告件数と異なればLive gate不合格。
8. 通常の再Fullでは既存`Source/Item`をIDで更新し、`completed`/Artifactを保持。今回ownedから外れた既知Sourceはサービス既存処理で`available=False`となるが履歴/ZIPを削除しない。後から購入した巻は新規pending。

## 重要なトランザクションリスク

`DiscoveryService` はレコードを逐次Catalogにupsertする。全カード確認→全selected record事前bufferというAdapter契約で、ネットワーク中断・権利判断不明による**途中yield**を防ぐ。それでもService側のDB制約違反や後処理失敗で一部upsertが残る場合がある。既存の`job_lock`とCatalog整合・incomplete evidenceの失効が働くことを検証し、必要なら最小限の共通原子性修正を**別途Lead判断**する。試しにCoreをリファクタしない。

## テスト / 受け入れ条件

- Unit: URL完全一致/偽host/query/redirect、カードのowned・未購入・未知、カード外共通バッジを誤採用しない、duplicate IDs、途中一覧、並び方向、欠番、別冊、タイトル末尾数字なし、loadedの一時的欠落、incremental拒否、scope拒否、全件事前buffer。
- Browser fixture: 2列表示とDOM順が違う、lazy load、複数カードに異なる購入状態、ログアウト、ownership表示遅延、一覧zero/partial、後から巻を買い足す、前回ownedの剥奪。
- Service integration: Full→Full不変なら`completed`維持、追加巻のみpending、失敗Fullでは以前のownedが誤ってunavailableにならない。`CompleteListingInventory` の全巻positionsと所有選択マスクを監査。
- 実サイト: `エンジェル伝説` owned正確に10巻1件、`ムダヅモ` owned全16件で1〜16巻の安定ID・順番一致。どちらも未購入巻をCatalogへ新規登録しない。
- GUI: 作品URL貼付→安全な正規URLとして解析→work/key調整→保存→Full Discoverが動く。scope設定画面に誘導しない。

**Exit**: Reviewer `BLOCKING=0`、上記Live/Unit/Integrationの結果と未実行理由を`PROGRESS.md`に記録。Verifierが閲覧に必要な巻固有URL/IDを確定できなければ先へ進めない。

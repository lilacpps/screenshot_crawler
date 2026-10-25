# Windows GUI — Watchlist管理・話数チェックによるDiscovery Scope編集 Runbook

> **PLANNED / DOCUMENTATION ONLY — 2026-10-25**
>
> 対象: `lilacpps/screenshot_crawler` の既存 PySide6 GUI / Watchlist / Catalog v7 / Discovery / Scope Reconciler。現時点では設計・実装契約のみで、実装・実サイト検証・本番データ更新は行っていない。
>
> Authority: `AGENTS.md` → `docs/SPEC.md` → `docs/ARCHITECTURE.md` → `docs/DISCOVERY_AND_BATCH.md` / `docs/BOUNDED_DISCOVERY.md` → `docs/DECISIONS.md` → `docs/TEST_STRATEGY.md` → code/tests。実装時に相違があれば文書だけを根拠に挙動を変更しない。
>
> 独立した `runbooks/gui-live-monitor/` と並行開発になり得る。`gui/main_window.py` の同一箇所を無調整で編集しないこと。既存Inventory / Discover・Batch・Grant-only / Jobと上部レイアウトを維持する。

## 0. ゴール・要求・対象外

**目的**: Watchlistをサイト別・作品別に確認/編集し、各作品の**全話一覧（Discovery情報）を右ペインに表示**してチェック操作で「取得対象」を指定する。保存前に、実際に適用すると何が対象内/外になり、採番や同期にどう影響するかを可視化する。採用案は **B: 既存の連続`from_url`/`through_url` ＋ `excluded_external_ids`**。

必須:
1. サイト→作品→key / 作品→サイト→key切替、検索、未Discover・disabled・stale表示。既存GUIの閲覧・実行・選択集合を壊さない。
2. Watchlist `label`、`enabled`、`url`、`discovery_scope` の安全な編集、key追加。`archive_order`はwork_key単位で全keyを一括順序編集。
3. Site Adapterに基づく読み取り専用の完全話数一覧。各行にサイト順序、話名、安定ID、URL、Catalog有無、現行/編集後の対象内外、取得済/未取得（判明する場合）、利用区分（判明する場合）を表示。不明は不明のまま。
4. 連続選択・飛び飛び選択をチェックボックスで指定し、設定候補と**実際の差分**をプレビュー。範囲変更前に必ず確認。
5. プレビューは `watchlist.yaml` / Catalog / ZIP / 実quota / ticket / grantを**一切変更しない**。閲覧だけで権利を消費する操作、reader起動、購入・Captureは禁止。
6. 明示保存とFull Discovery・Scope同期は区別し、反映未完了・要再確認を成功と誤表示しない。既存Source・Item・run・Artifact・ZIPを削除/勝手にrenameしない。
7. 未確認境界、不完全一覧、キー競合、既存key所属の再割当、古いfingerprint/プレビューではfail-closed。

初期段階の対象外: ブラウザ拡張/ブックマークレット（後続workstream）、サイト横断Item名寄せ、自動ZIP renumber、DB schema移行、チケット消費ルール変更、話別のresource/policy指定、任意条件DSL。

## 1. 現状確認済みの根拠（2026-10-25 main）

- `src/screenshot_crawler/watchlist/models.py`: `DiscoveryScope(from_url,through_url)`。`WatchlistTarget`に `key,work_key,site,url,label,enabled,discovery_scope,archive_order`。
- `watchlist/service.py`: parse/validate/list/get/add/remove/enable/disable、atomic replace。**コメント付きYAMLはenabled値だけのパッチを許し、scope/order/追加等の構造変更を安全側で拒否**。編集API追加と保存方式の整備が必要。
- `docs/BOUNDED_DISCOVERY.md`: 対象境界はサイトのcanonical discovery orderで**両端を含む**。片端のみも可。境界のparse・同一listing所属・順序をAdapterで厳密検証。scopeは最大1連続区間。
- `discovery/base.py`: `iter_records`と `complete_listing_inventory`（site-native identity, position, in_scope）。`discovery/service.py`は通常DiscoveryでCatalogを更新する。**そのままGUIプレビューへ流用不可**。
- `watchlist/reconcile.py`: `ScopeReconciler.preview/apply`、完全Full証拠とfingerprintによるwork単位fail-closed。`catalog/service.py`の `apply_discovery_acquisition_flags` はFull完了時にも一部`acquisition_enabled`を書き得るが、これは`scope-sync`完了の証明ではない。
- `gui/main_window.py`、`gui/model.py`、`gui/details.py`: 既存サイト別/作品別Inventoryツリー、キー選択・詳細・ジョブ実行。`management/models.py`のInventorySnapshotにWatchlistTarget/同期状況あり。
- `runbooks/work-key-archive-order/PROGRESS.md`: Catalog v7/境界/保存順/厳密同期の実装済契約。scopeの140→100→140回復テスト、複数site、未同期の停止が既存の重要回帰。

## 2. 採用するデータ契約

### 2.1 YAML（互換拡張。Catalog migrationなしを原則）

```yaml
targets:
  - key: sample-magapoke
    work_key: sample-work
    site: magapoke
    url: https://pocket.shonenmagazine.com/title/00002/episode/481
    enabled: true
    label: サンプル
    discovery_scope:
      from_url: https://pocket.shonenmagazine.com/title/00002/episode/500
      through_url: https://pocket.shonenmagazine.com/title/00002/episode/481
      excluded_external_ids:
        - "490"
        - "485"
```

`excluded_external_ids` は **site-native `Source.external_id`** の文字列配列で、URL・話数表示名・配列indexではない。上例のIDは構造説明用で実在話の正しさを示さない。`from_url/through_url` の意味は従来どおりで、除外指定はその**内側だけ**で有効。境界・順序・ID一致は一覧証拠で検証する。

- 古いYAMLは意味も出力も維持。無指定/空配列は既存と同義。シリアライズ時は除外IDを安定ソート/重複拒否し、同じ集合の順序違いでfingerprintを変えない。
- `excluded_external_ids` のみも許可（全体を候補とし一部を除外）。scope構造は空にしない。全選択時はscope省略可能。
- 1件以上の**明示的に取得対象とする話**が必要。「全部チェック解除」は初期版で適用不可（`enabled=false` と全話取得対象外は意味が違う）。UIで理由を表示する。将来専用`exclude_all`等を追加する場合は別仕様として決定。
- 未知ID、別作品・別listingのID、範囲外ID、重複IDは黙って無視しない。候補作成/Full証拠/同期ではfail-closed。site-native IDが変更された場合は再取得・再確認を促す。
- 現在の1キー=単一連続基本範囲を維持。飛び飛び選択は「最初と最後の選択話を両端（canonical order）にし、間の非選択IDを除外」として表現。新着話の扱いは既存片端/両端境界の意味に従う。将来の新着話まで固定除外する保証はしない。
- `work_key`は異サイトの作品を束ねるが、Site-native Sourceは自動名寄せ・所属key移動しない。同一サイト複数key間の対象重複は事前検証でブロックする。
- `archive_order`は同じwork_keyの全keyに設定するか全未指定。個別checkbox/除外変更は番号を動かし得るが自動改名しない。

### 2.2 「取得対象」と「Discovery記録」を分ける

チェックは **Batch/Grant-only等が扱う取得担当の選択**（`acquisition_enabled`）であり、`access_mode`、`Item.status`、`enabled`（Discovery起動の可否）や権利条件と無関係。未取得・取得済・有料でも選択状態は独立。

- 全話一覧はAdapterの読み取り専用listingから表示する（Catalog未登録の話も表示可能）。
- Full Discoveryは基本区間のうち**チェック対象だけをCatalogへ新規upsert/refresh**する方針。除外行が既に同一keyのCatalogにあるなら履歴を残して最終的に`acquisition_enabled=0`。未登録の除外行は作成必須ではない。除外行が**別keyのSource**なら触らない。
- Adapterの完全一覧証拠には区間外も含む全話のsite-native位置を残し、in_scope maskは「基本区間 **かつ** 除外されていない」を示す。`ScopeReconciler`が既存Catalog全行を分類できることを維持。
- 既存のFull正常完了→証拠→フラグ更新→明示`scope-sync`の二段契約を維持。中間状態は「保存済/未同期」と見せ、Batchは既存のfingerprint/同期ゲートで止める。

## 3. GUI画面契約

- 既存「作品管理（実行・閲覧）」はそのまま。別の「Watchlist管理」画面/タブに編集導線を置く。`gui-live-monitor`の上部レイアウトや実行モニターとは独立する（統合時はコンフリクト解消）。
- 左: サイト別/作品別のツリー、key検索・絞り込み、Watchlist only / Catalog only / 未Discover / stale 表示。中央: 選択keyの基本設定、enabled、scope境界、work単位archive順序、追加/編集。右: 全話一覧（チェック、話名、site-native位置、URL、現行対象内外、更新予定、Catalog状態）。
- Qt描画は大量話の遅延を避け、`QAbstractTableModel`/proxy等のモデルで表示。全話一括選択/区間選択/複数選択を提供。編集dirty状態、キャンセル/元に戻す、未保存時の選択切替確認。
- 色だけで差を示さず、対象/対象外/変更なし/追加/除外/不明を明示。現行Catalog対象と提案の差を別列にし、`enabled`と話選択を混同しない。
- プレビューは「取得対象に追加N/除外N/維持N/未登録N/分類不能N」「各話 before→after」「対象内でも有償等によりBatch実行対象とは限らない」「archive order/ZIP採番差分（確定できなければ不明）」「必要なFull・scope-sync・renumber」を表示。
- 実行対象不明/Full一覧不完全/他key所有/旧プレビューは適用不可。`scope-sync`と`renumber`のブロッカーをUIへ保持・表示。プレビュー時点の値を無条件で実適用保証しない。

## 4. Read-only previewと反映フロー

```text
既存Watchlist + read-only Catalog snapshot
             + site-native complete listing (read-only, no Catalog writes)
                       ↓
             scope checkbox編集（メモリ内）
                       ↓
       正規化/候補YAML + 変更前後の予測 + blocker
                       ↓
       [設定を保存] 明示確認 / 変更競合を再チェック
                       ↓
       Watchlistのみ安全にatomic更新
                       ↓
       [Full Discovery] 別の明示ジョブ（必要ならガイド）
                       ↓
       [Scope同期プレビュー] 厳密な現在証拠・Catalogで再評価
                       ↓
       [同期を適用] 別の明示確認・再検証
                       ↓
       [ZIP再採番プレビュー] 必要時のみ（自動rename禁止）
```

- **一覧取得は通常の`DiscoveryService.discover`を呼ばない**。アダプタ側の既存listing parseを再利用する`read-only complete listing` service / DTOを追加する。初期はMagapokeで実装・検証、対応していないサイトでは既存Catalogの参考表示のみ（完全/確定扱い禁止）。
- Previewでは候補Watchlistをメモリ上で評価するpure helperを用意し、既存`ScopeReconciler`の判定規則を重複実装しない。`ScopeReconciler.preview()`は現行Watchlistと永続化済Full証拠に結び付くため、そのまま仮設定に呼ぶだけでは不十分。Pure planning部分を再利用・抽出する。
- 未登録の新話、異サイト関係、stale/欠損のCatalogや証拠がある場合、番号や正確な`acquisition_enabled`反映件数を**推測で確定表示しない**。一覧からの予測と正式scope-sync結果を区別する。
- List previewにはtimestamp、site/listing identity、一覧digest、対象key/URL、Watchlist content SHA、Catalog revision/snapshot identityを結び付ける（実装でtoken構造選択）。保存/実行前に有効性を再検証。既存ジョブのCatalog lockと競合する書込では待機/停止を明示。外部YAML編集を上書きしない。
- 可能なら「Full → Scope同期」の誘導を画面内で提供するが**単一ボタンで暗黙の自動同期/renameは禁止**。Fullで実際の証拠が異なれば再プレビューを必須にする。最終的な`ScopeReconciler.apply`のrevision checkを緩めない。
- 保存・Full・同期が途中停止/失敗したときは別々に完了状態を表示し、復旧を案内。Catalog、YAML、ZIPを擬似的に1 transactionと主張しない。

## 5. フェーズ・実装ゲート

| Stage | 実行契約 | Exit |
|---|---|---|
| [00 契約監査](00-contract/README.md) | 現行schema/adapter/GUI/Job契約、複数key所有と変更時の中間状態を確認 | 設計差異/リスクとテストfixtureが確定 |
| [01 YAMLモデル/編集API](01-watchlist-service/README.md) | `excluded_external_ids`、canonicalization、atomic edit/CAS、コメント保護、work単位archive並替 | 新旧YAML互換・競合拒否 |
| [02 Read-only listing](02-readonly-listing/README.md) | 初期Magapoke・site-neutral DTO、無書込完全一覧、GUIで一覧表示可能 | no-writeと不完全一覧gate検証 |
| [03 Scope selection / Planner](03-scope-planning/README.md) | 除外mask、Full、Reconciler/fingerprint、preview/apply、Batchまでの一致 | 意図外crawl/重複owner/未同期ゼロ |
| [04 GUI統合/E2E](04-gui-integration/README.md) | タブ・チェック・preview・保存/反映フロー・archive順序・ジョブ連携 | Windows/Qt + isolated Catalog E2E/Reviewer承認 |

後続: URL貼付からのkey登録・ブラウザ起点登録は別workstreamとして、Stage01の追加APIを再利用。初期StageにChrome拡張を含めない。

## 6. 共通の回帰観点 / 許容しない挙動

1. 未指定scope/legacy YAML/既存連続範囲のFull/Incremental/Batch/Grant-onlyが従来どおり。
2. 一覧100話、1〜100選択、1〜100中の50/75話除外、境界変更100→80→100、同一話で両端、片端、all included、空選択拒否。
3. 有料/無料/待つと無料/取得済/未取得混在時も選択maskはアクセス可否と独立。除外話はnormal Batchだけでなくexplicit grant-only/deferred resolver/replanで利用・消費されない。
4. 同じwork_keyの異サイト複数keyと、**同サイト複数keyの所有者境界**。除外話が別keyのSourceならreparent/refreshしない。scope重複はブロック。
5. 過去のZIP/Item/Source/Run/Artifactと担当外履歴の不変性。`archive_order`採番差分の可視化と未確定時の停止。自動rename/削除なし。
6. stale/invalid/duplicate/unknown excluded IDs、listing欠落、position重複、変更中のサイト一覧、失敗/partial Full、コメント付きYAML、競合保存、ロック、GUIジョブ並走。UNKNOWNをOK扱いしない。
7. Preview no-writeは実ファイルhash/mtime・DB contents・job state・outputを検証。ブラウザ操作はreader/チケット使用なし、外部アクセスの副作用がないことをAdapter単位で証明。
8. 対応Adapter未実装のサイトはread-only Catalog参考表示に限定し、完全一覧に基づく保存・applyを不可にする。機能の存在を誇張しない。

テスト選定は`docs/TEST_STRATEGY.md`。共有Model/Discovery/Batch/Reconciler変更なので affected Unit + browser-backed synthetic integration + GUI smoke を先行、共通変更統合時はfull suite、`ruff check src tests`。実サイトの読取確認は明示許可/既存CDP/profileの安全制約に従う。購入/reader/capture/quota/ticket消費は検証で行わない。

## 7. 引き継ぎ/記録

- Stage開始時にHEAD、既存枝、未commit差分、gui-live-monitorの状態を確認。ユーザーの変更を破棄しない。feature branchで実装し、単一production writerと独立Reviewerを置く。
- 各Stageの完了条件・テスト名・結果・未実行カテゴリ・review blockerを[PROGRESS.md](PROGRESS.md)へ記録。予定を実装済と記載しない。
- 仕様変更時は`docs/BOUNDED_DISCOVERY.md`、`docs/DISCOVERY_AND_BATCH.md`、`docs/DECISIONS.md`、`docs/GUI_README.md`を必要範囲で同期。Core/Discovery/Batchは`note/00_core.md`、Magapoke挙動が変わる場合は`note/03_magapoke.md`も同じ変更で更新。runbookはauthorityを自動的に上書きしない。
- 各Stage終了時に独立レビューを実施し、BLOCKINGを解消してから次へ。必要証拠不足なら当該Stageで止める。

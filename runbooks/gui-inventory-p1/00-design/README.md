# P0 — Windows GUI / Inventory設計固定

> **Status: COMPLETE — decisions in docs/GUI_INVENTORY.md and ../PROGRESS.md**
>
> **Prerequisite:** [workstream README](../README.md)。本Stage完了後はP1へ進み、P1末尾でユーザーのUIレビューを待つ。

## 1. Objective

Catalog v7/Watchlist/SitePolicyの実際のデータ契約を読み、閲覧GUIが「正しい数値・安全なread-only動作・一貫した選択操作」を提供できる仕様に固定する。**P0単体ではGUIを完成させず、曖昧な分類をUIへ埋め込まない。**

## 2. Starting evidence / 必読

- `src/screenshot_crawler/catalog/models.py`、`schema.py`、`service.py`：Work→Item→Source、状態、Scope同期証拠、Artifact/CrawlRun、読み取り専用API。
- `src/screenshot_crawler/watchlist/models.py`、`service.py`、`reconcile.py`、`fingerprints.py`：keyとwork_keyの関係、archive_order、同期一致性、未管理。
- `src/screenshot_crawler/site_policies/base.py` と主要site policy（MangaONE、BookWalker、Magapoke、Zeblack、Comic DAYS、Hanayume、YoungAnimal、Jump+、Piccoma、Kadocomi）：direct/quota、active grant、paid、有効期限、scopeがsite/workか。
- `src/screenshot_crawler/batch/planner.py`：Policyでの選択ルール、acquisition_enabled、サイト共通quota、deferred resource、grant-onlyでの差分。
- `docs/TEST_STRATEGY.md` と `AGENTS.md` / `note/00_core.md` の変更ルール。
- `runbooks/work-key-archive-order/PROGRESS.md`：既存実装の範囲と既知の2件の全suite failure（今回のP0で再評価）。

## 3. 具体的な作業

### P0.1 — データとアクセス分類の棚卸し

主要siteを最低1つずつ、可能な限りsynthetic fixtureで含める。各siteのPolicyによって次の質問に答えられる表を作成する。

- `pending/assigned/source.available/access_mode/free_until/access_granted_until` に対し「直取候補」「Quota対象残」「有償」「Unavailable」「Unknown」がどう判定されるか。
- 作品単位ticket（work_ticket）とサイト共通quota（MangaONE/BookWalker）で「候補話数」と「利用枠」をどう分けるか。
- Magapokeのwork_ticket/premium_ticket等、同一Sourceを複数Resourceで扱える場合でも「話数件数」を二重加算しない条件。
- Site Policyの`evaluate`だけで出せない結果（live resolverで決まる対象数、grant-only実消費可能量）は何か。**不明のまま表示する**。
- `completed/external/skipped/pending` の区別。`acquisition_enabled=0` の既存Artifact/Runは対象外の履歴として残す。
- サイト横断WorkのItemは自動mergeしない。画面の総数が「サイトからの取得対象の総数」でありコンテンツの重複排除済み話数でないことを明示する。

### P0.2 — 集計DTOと不変条件

Qt非依存の案をコードまたは文書で固定する（命名は適宜調整可能）:

```python
@dataclass(frozen=True)
class InventoryCounts:
    total_assigned: int
    completed: int
    external: int
    skipped: int
    direct_candidates: int
    quota_pool: int
    paid: int
    unavailable: int
    unknown: int
    out_of_scope: int  # total_assignedには含めない

@dataclass(frozen=True)
class KeyInventory:
    key: str
    work_key: str
    site: str
    label: str
    enabled_for_discovery: bool
    archive_order: int | None
    counts: InventoryCounts | None
    sync_status: str
    diagnostics: tuple[str, ...]

@dataclass(frozen=True)
class InventorySnapshot:
    # site/work/key treeの共通source。
    # 実際にはworks, site summaries, items, source factsを不変DTOで保持。
    loaded_at: datetime
    keys: tuple[KeyInventory, ...]
```

- 内訳 invariant: `total_assigned=completed+external+skipped+direct_candidates+quota_pool+paid+unavailable+unknown`（すべてItem IDのdedupe後）。分類不能なものは`unknown`へ保留し、理由を診断に付ける。
- keyの`counts`が算定不能なら`None`または`unknown flag`（0に偽装しない）。
- オーナーのないSource、Watchlistのみのkey、Work内の複数サイト、同一Itemに複数Sourceがあるsyntheticケースで整合性検証。
- `sync_status`の値は少なくとも synced/stale/missing_work/unmanaged/unknown/error を画面へマップ可能にする。
- item statusとSource accessは別もの。Source別の裏付けとItem集計の代表判定を明確に文書化。Itemに複数の有効Sourceがあるときは、Policyで単一候補に決定できなければ`unknown/ambiguous`として表示、都合よく合算しない。
- site共通枠の値は`site_summary.resource_state`に分離。個別Workにサイト全体の枠を無条件に再掲しない。
- site及びWorkの合計は同じkey基底データから生成し、フィルタ中でも表示母集団（全件/表示中）をラベルで区別する。

### P0.3 — read-only reader設計

現行`CatalogService.list_crawl_runs`と`list_artifacts`は通常のSQLite接続を使用するのでGUIから直接呼ばない。必要な集計を新設の`CatalogInventoryReader`等で読み出す設計を採用。`mode=ro`、存在確認、schema v7 validation、`BEGIN`下で整合スナップショットを取得し、絶対にDDL/DML/自動migrationしない。

- Watchlist YAMLの誤入力/未存在、Catalogの未存在/古いschema/SQLite破損に対するUIエラーを定義する。
- Scope同期: `ScopeReconciler.preview`によるread-only情報参照を可能な限り再利用。ただし全WorkごとのN+1 DB accessが性能問題になるなら既存のsync fingerprintsをSnapshotへbulk loadし、一致性判定を共通pure helperへ切り出す。**P1のためにScope適用機能を呼ばない。**
- WorkごとのScope previewを無理に重いlive/probeへ拡張しない。変化途中のDBはGUI reloadで取り直す。
- Item/Artifact/Run/QuotaResourceStateの表示に使用するフィールドと出典を`README`あるいは専用の表へ明示。
- 時刻はタイムゾーン付きデータをJST表示に正規化。無い値は—。timestampが不正なら診断表示し、GUI全体を落とさない。

### P0.4 — Qt画面デザインとInteraction契約

`../README.md`にある画面を基準とし、Windows 1400x850pxでのワイヤーフレームをP1の基準にする。

```text
[作品管理] [サイト別|作品別] [検索] [フィルタ] [再読込]
╔═══════════════════════════════════════╦═══════════════════════╗
║ ツリー (Site→Work→Key / Work→Site→Key) ║ 詳細 (Site/Work/Key) ║
║ チェック / 展開 / 統計列             ║ 概要・話数・実行履歴  ║
╚═══════════════════════════════════════╩═══════════════════════╝
[選択中 N key] [Discover — disabled] [Batch — disabled] [Grant-only — disabled]
```

UI内部状態:
- `view_mode: site|work`
- `expanded_nodes: set[stable_node_id]`
- `selected_keys: set[str]`
- `focused_node_id: str|None`
- `search_query`と`filters`
- `inventory_snapshot`

チェック集合と詳細表示focusを絶対に混同しない。Work/site parent checkboxの部分選択、フィルタ非表示のkeyに対する操作、ビュー切替/再読込/ソート時のselection安定をテスト契約とする。

### P0.5 — ファイル構成とテスト選定

候補（既存構造に整合し必要に応じて調整可）:
- `src/screenshot_crawler/management/inventory.py`：Qt非依存集計
- `src/screenshot_crawler/management/catalog_reader.py`：read-only DB snapshot
- `src/screenshot_crawler/gui/main.py`：entrypoint
- `src/screenshot_crawler/gui/model.py`：`QAbstractItemModel`
- `src/screenshot_crawler/gui/detail.py`：右ペイン
- `src/screenshot_crawler/gui/window.py`：MainWindow
- `tests/unit/test_inventory.py`、`tests/unit/test_gui_model.py`、`tests/integration/test_gui_smoke.py`等。

依存は`pyproject.toml`で`[project.optional-dependencies] gui = ["PySide6..."]`を追加するだけにする。Poetry/npm/electron/FastAPI/JS frontendを新規導入しない。

## 4. Role / Phase gate

- Implementer: 調査に基づく決定を文書化し、簡易pure classification prototype/fixtureの作成は可。ユーザー承認前にP2コードを作らない。
- Reviewer: UI上で事実と推定が混ざっていないか、site別/Work別の総数とquotaの二重加算、未同期扱い、read-only違反を優先確認。
- Tester: 合成データでの分類/ツリー投影/選択仕様の独立検証。

**Exit conditions（P1へ進む前）**:
1. 値の出典と分類表が明確。
2. Work/site/key/ItemのDTOと不変条件を記録。
3. read-only APIと想定クエリの方針が明確。
4. UIの操作/階層/フィルタ/selection規則が明確。
5. 具体的なP1のテストケースと視覚チェックが記録済み。
6. `PROGRESS.md`へP0の結果を記録。P0完了後P1へ進んでよいが、P1の先には進まない。

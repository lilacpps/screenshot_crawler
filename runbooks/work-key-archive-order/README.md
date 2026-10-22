# Work-key横断の取得範囲・ZIP採番 — 実装Runbook

> Status: **P0-P5 COMPLETE; 2026-10-22 site follow-ups reviewed**. The shared implementation and follow-up adapter coverage are complete. The final full suite completed with 4,991 passed and 2 failures; isolated rerun evidence and attribution are recorded in PROGRESS.md. Copy-only verification passed; operational rollout remains an operator task.
> Owner: Lead + Codex Implementer。進捗は同ディレクトリの PROGRESS.md で更新する。
> This runbook records the implemented contract and safe operational rollout. Copy-only P5 verification and final review are complete. No migration or renumbering was applied to the operational Catalog, Watchlist, or Books directory.

## 0. 目的と今回の決定

作品（work_key）の取得元を複数のWatchlist key / 複数サイトへ手動分割できるようにし、各keyが担当するSourceだけを、Watchlist指定順かつ各keyのサイト表示順で通し採番する。あとから取得元をゼブラックからBookWalkerへ変更する場合にも、過去のSourceやZIPを勝手に消さず、安全に取得担当範囲を変更できるようにする。

採用方針:
- 自動の作品・話数名寄せは **行わない**。同じwork_keyにサイト別Itemが存在してよい。
- Work=work_key（作品の管理単位）、Watchlist key=サイト上の取得範囲の管理単位。Sourceは最初のdiscovery_keyに所属し続ける。
- Watchlistの既存 discovery_scope を **Discovery対象範囲および取得担当範囲の正本** として使う。別の acquisition_scope は導入しない。
- Watchlistに optional な archive_order (正の整数) を追加し、同一work_keyのkey連結順を指定する。
- DBには sources.acquisition_enabled (0/1、既定1) を追加する。値はWatchlistから同期された派生データであり、ユーザーが独立の手動状態として編集しない。
- sources.display_position は従来のサイト全体の表示順（oldest=1）のまま維持し、NULLを取得担当外の意味に流用しない。
- BatchはSite PolicyとCatalogのフラグで候補を決める。毎回各Sourceの境界URLをWeb照合しない。
- ZIP番号だけは同一work_keyの **全key・全サイト** の位置を参照して計算する。現行の番号prefixはサイト固有display_positionをそのまま使っているため、統合方式への変更は明示的opt-inとする。
- GUIの実装は **今回の対象外**。将来のGUIから同じWatchlist編集・Scope同期・renumberプレビューを呼べるCLI / Serviceを整備する。

適用範囲: Catalog v6→v7、Watchlist、Discovery、Batch Planner / grant-onlyを含む候補選択、命名、既存ZIPのrenumber、unit/integration test、説明文書。Site Adapterのviewer/capture/購入操作の変更は対象外。

## 1. 現行コードの観察（実装前の事実）

- src/screenshot_crawler/catalog/schema.py: Catalog v6には works、items、sources、source_targets、crawl_runs、artifacts、quota_resource_states。sourcesにdisplay_position/discovery_keyはあるがacquisition_enabledはない。
- src/screenshot_crawler/discovery/service.py: 新しいSourceはItem/Source/Targetを作成、既知Sourceは同一(site, external_id)で更新。別discovery_keyへの所属変更は拒否。bounded fullは範囲外Sourceを削除・unavailable化しない。
- docs/BOUNDED_DISCOVERY.md: discovery_scope.from_url / through_url はsite-native URL境界、newest-firstのinclusive範囲。各Adapterが検証し、bounded Sourceにはサイト全体でのglobal_display_positionを与える。
- src/screenshot_crawler/batch/planner.py: 現在はsiteスナップショットを読んで pending とSite Policyで候補決定。scopeを参照せず、artifact_prefixはsources.display_positionから作る。
- src/screenshot_crawler/batch/naming.py + core/packaging.py: ZIP名のprefixとdisambiguatorを構成。zipファイルを既存パスへ暗黙上書きしない。
- scripts/renumber_archives.py + maintenance/archive_renumber.py: dry-run、衝突検査、ZIP/status JSON/Artifact locator更新、rollbackを実装済み。
- watchlist/service.py: YAMLのコメントはsafe_dumpでは保存されない。今回のCLIはコメントを含むWatchlistではenabledのscalarだけを保守的に更新し、追加・削除・archive_order変更など構造変更はファイルを書き換える前に拒否する。コメントレスの構造変更は再parseし、要求したtarget一覧と一致することを確認してからatomic replaceする。

変更開始前に必ず最新の code/tests と docs/SPEC.md、docs/ARCHITECTURE.md、docs/DISCOVERY_AND_BATCH.md、docs/BOUNDED_DISCOVERY.md、docs/ACCESS_CONTROL_AND_PACING.md、docs/TEST_STRATEGY.md、note/00_core.md、note/07_catalog_position_archive_plan.md を再確認する。既存ドキュメントとこの計画に矛盾があれば黙って変更せず、差分を明示して整合を取る。

## 2. 用語・責務とデータ契約

| 項目 | Authority | 意味 |
|---|---|---|
| work_key | Watchlist / works | 作品を人手でまとめるID。異サイトのItemを自動mergeしない |
| key | Watchlist targets.key / sources.discovery_key | 取得範囲を識別するID。Sourceの所属は不変 |
| site | Watchlist / sources | サイトID |
| discovery_scope | Watchlist | そのkeyで走査・取得担当するsite-native inclusive範囲。省略時は全範囲 |
| archive_order | Watchlist | 同一work_key内でkeyを連結するための相対順位 |
| display_position | Catalog Source | site-native complete listingにおける位置。不変の話数IDではなく更新され得る |
| acquisition_enabled | Catalog Source、新規 | 現在のWatchlist scopeによる取得担当範囲内なら1、外なら0 |
| item.status | Catalog Item | pending/completed/skipped/externalの従来意味を維持 |
| source.available/access_mode | Catalog Source | サイトでの可用性/無料・quota・有償等。担当範囲と独立 |
| archive_position | 派生値（非永続化） | opt-inしたwork_keyの取得担当Source全体で001からの連番 |

### 2.1 Watchlist書式

~~~yaml
targets:
  - key: sample-zeblack
    work_key: sample
    site: zeblack
    url: https://example.invalid/zeblack-series
    enabled: true
    archive_order: 10
    discovery_scope:
      from_url: https://example.invalid/zeblack-chapter-100

  - key: sample-bookwalker
    work_key: sample
    site: bookwalker
    url: https://example.invalid/bookwalker-series
    enabled: true
    archive_order: 20
    discovery_scope:
      from_url: https://example.invalid/bookwalker-volume-15
      through_url: https://example.invalid/bookwalker-volume-14
~~~

上記URLは概念例、実サイトURLではない。境界の向き・site-native識別・inclusive判定は既存docs/BOUNDED_DISCOVERY.mdと各Adapterをauthorityとする。archive_orderは同一work_key内で重複禁止、boolean/0/負数/非整数禁止。値は10,20,30など間隔を空けてよい。

CLIで新しいkeyを追加する場合は `watch add --key ... --work-key ... --site ... --url ... --archive-order 10` を使う。work_keyの全keyに順序を追加・変更する場合、既存YAMLにコメントがあるとCLIの構造書き換えは安全側に拒否されるため、Watchlistを直接編集する。raw `#` 文字をURL fragmentや引用scalar内で使っている場合もコメント保持のため保守的に同じ扱いとなる。

**後方互換**:
- work_key配下の全targetにarchive_orderが **ない** 場合、既存のsite-native display_position命名を維持する。
- work_key配下の **全targetにarchive_orderがある** 場合のみ、新しいwork-key通し採番を使う。keyが1つでも明示的に指定すればopt-in可能。
- 一部だけ指定、同値重複、scope境界不整合、同一keyの重複は **エラー**。暗黙の配列順・推測順にfallbackしない。
- enabled:falseは「定期/一括Discoveryの対象外」を意味するだけ。既存Sourceのacquisition_enabledも採番資格も変更しない。
- 有償/無料/購入済み、item.status、source.available、発行日、grant残数によって番号を詰めない。scope内のSourceは **すべて** 採番母集団に含める。
- Watchlist keyが削除されたSource、またはCatalogで所属を解決できないSourceは「unmanaged / 要確認」。勝手に別keyへ移動せず、通常Batchから除外し、名前計画に黙って混ぜない。
- 異なるサイトの範囲が作品内容として重なることは自動検出・補正しない（人手でscope調整）。同じ(site, external_id)を異なるdiscovery_keyへ再所属させない。

### 2.2 DB最小拡張

Catalog v7 migration（バックアップと既存migrations.pyの明示migration導線を利用）:
1. sources.acquisition_enabled INTEGER NOT NULL DEFAULT 1 CHECK(IN (0,1)) を追加。
2. 小さな同期メタデータ表（例: acquisition_scope_sync、work_keyをキーに設定fingerprint・同期時刻・状態を持つ）を追加。列名は実装時に既存Catalog APIとの整合で確定してよいが、**設定変更・同期未完了をBatchが検知できる契約**は必須。
3. Item/Source/CrawlRun/Artifactの既存ID、履歴、quota state、display_positionは移行時に変更しない。自動的な全件reconcileや改名はmigrationに混ぜない。
4. migration直後は旧取得動作を突然変えない。同期状態が未初期化の作品は、明示bootstrap syncを要するものとして表示・実行ガードする。実Catalogの事前バックアップは必須。

同期fingerprintは正規化したwork_key内の全key・site・target URL・scope・archive_order・key集合（disabled含む）から決定的に計算する。target URLは同じlistingであることの根拠に関わるため含める。label等の表示用編集だけでは不要な再同期を発生させない。site/key/work_key不一致、境界未解決、途中更新があれば同期完了としない。

Scope sync proofは単なる `complete=true` やWatchlist fingerprintと分離する。成功したFull Discoveryから、`work_key / key / site / target URLまたはsite-native listing identity`、そのlisting全体のstable Source identityとglobal position、完全性を検証したinventory digestを保持する。既存bounded Discoveryは境界確認のためlisting全体を一時観測するが、Serviceが現在永続化するのはyieldされた範囲内のpositionだけである。そのため、yield範囲内の行や以前の `display_position` だけで未観測Sourceの範囲判定を完了してはならない。境界照合・complete inventoryを提供できないsiteはScope syncをfail closedにする。target URL/listing identityの変更、incomplete Discovery、または位置inventoryへ影響するCatalog mutationで証明を失効させる。

**重要**: filenameの通し番号は永続カラムにしない。現在のCatalogスナップショットとWatchlist順序から同じpure functionで計算し、新規Batchとrenumberが共有する。

## 3. Scope同期アルゴリズム（最重要）

### 3.1 更新前計画 / 完了反映

- scope編集時は新Watchlistの設定を読み、対象work_keyに属するCatalogの全Sourceを確認する。
- Scope判定はsite-native stable identityで境界を解決し、同一site/listingであることを確認したうえで、成功Fullの完全なinventoryに含まれるglobal `display_position` を使って比較する。URL文字列の大小比較、話数表記、漢数字の推定、Source IDの大小を境界の代用にしない。
- 範囲境界がCatalog/listing inventoryにない・位置がNULL・同一listingと証明できない・inventoryがincomplete・逆転している・重複所有が疑われる場合は **fail closed**。そのsiteにcomplete-listing proof hookがある場合は、必要なsiteのFull Discoveryで証拠を更新してから再同期する。hook未対応のsiteでは、bounded Discovery自体が動作してもscope/archive-order同期の証明にはならず、Fullの反復でも解決しない。Adapter/Service間にlisting全体identity-position inventoryを安全に渡すhookが実装されるまで同期しない。範囲外Sourceを新規Discovery/Item化しない。
- 管理操作は **preview/dry-run → apply**。差分としてSource ID/外部ID/key/old→new flag、担当外件数、ZIP採番/衝突への影響を提示する。
- applyでは1 work_key分を一つのSQLite transactionで更新。fingerprint記録も同一transactionとする。途中失敗で一部のフラグだけが有効にならない。
- GUIは後から同じpreview/apply APIを利用する。WatchlistとSQLiteの更新を物理的な1 transactionにできないため、途中クラッシュ時はfingerprint不一致としてBatchを **fail closed** させる。
- sourceのdiscovery_keyは変更しない。別keyへ移動しない。重複対象での新規Discoveryは既存どおりエラー。

### 3.2 新規Discover・再Discover

- 新しくDiscoverされたSourceは、そのkeyのscope内で確定したものとして acquisition_enabled=1 とする。旧Sourceは今回観測しなくても、必要なら同期処理でscope内/外を再評価する。
- A successful Full Discovery stores target/listing-bound complete inventory evidence only after iterator exhaustion and Catalog finalization. It does not apply Watchlist acquisition flags. A separate explicit `scope-sync --dry-run` / `--apply` operation commits the full work once all required key proofs are current. This avoids partial multi-key synchronization.
- Incremental Discoveryはcomplete listingの証拠ではない。新規確実なin-scope Sourceの登録・位置更新はよいが、「今回見つからなかった」ことを理由に既存Sourceを取得担当外にしない。scope変更時の全Source再判定をincrementalのknown-streak結果だけで確定しない。
- Discoveryがincomplete/exception/プロセスクラッシュなら同期成功マーカーを付けない。Incremental/partial Catalog mutationがscope eligibilityまたはposition inventoryへ影響する場合も古いFull proofを失効させる。更新途中に作られたSourceはBatchが見ないよう同期ゲートまたは保守的な初期フラグで守る。ジョブ排他も実装し、Discover/同期/Batch/renumberの同時変更を防ぐ。
- Watchlistを直接手編集したケースもサポートする。Batch開始時には **軽量なfingerprint照合だけ** 行い、scope未同期なら実行しない。各SourceのWeb照合をBatchに持ち込まない。
- Full/Incremental listing-position changes may cause historical ZIP names to differ from the current plan; Batch reports that drift as a maintenance warning. Renumber existing files only when you choose to align them. Batch still stops on a detected collision at the current candidate ZIP/status path and never overwrites a detected file.

### 3.3 Scopeがない、disabled、orphan

- scope省略のkeyは「そのkeyが担当する全Source」を対象。初期状態の既存Sourceを1にし、そこから自動で制限しない。
- disabled keyでも、以前にそのkeyで取得したSourceの割当と番号を保持。サイトでのDiscover実行有効化とは独立。
- Watchlist削除で所属不明となったSourceはCatalogから削除・status変更しない。新規Batchは実行禁止（保守的には所属keyなしのSourceをscope同期時に0へ）、GUIで将来「所属未解決」と表示できるようにする。
- 「担当外」SourceはCatalogへ保存したまま acquisition_enabled=0、Item.statusはpendingでも問題ない。CrawlRun、Artifact、grant時刻、access_mode、availableも変更しない。
- 担当外の取得済みZIPは **自動削除しない**。新しい名前と衝突した場合はpreflightでblockし、明示的な別処理で解消する。

## 4. Batch・grant-only統合

- BatchPlanner.plan(site=...)の候補構築で acquisition_enabled=0 をSite Policy評価・quota消費候補選択の前に除外。スキップ理由は `acquisition_disabled`。
- 通常Batch、明示 grant-only、deferred/live resolver、replan、追加resource passまで **同じ対象フィルタ** を適用する。quota消費/サイトアクセスの直前で選択集合が意図せず拡張しないこと。
- Site Policy / Core Runner / Adapterの既存resource/チケット消費ルールは変えない。購入・ポイント/コイン消費は新規導入しない。acquisition_enabledは購入可否を意味しない。
- Batch PLAN/RUNはCatalogだけで話単位の可否を判定。開始前のWatchlist読込は軽いfingerprint整合チェックと、opt-in採番用のkey順序情報の取得に限定。個々のURL境界を再解決しない。
- CLIの既存batch plan / runには--watchlistを明示的に通す導線を整える（現在planには引数なし）。誤ったwatchlist/catalogペアを使って進行しない。対象work_keyごとの不整合でfail closed。既存の明示Catalogテストとの互換性に注意。
- 実行前に対象work_keyの名前計画を固定（同時にCatalogが変わらないよう排他/再検証）。後続keyにずれを作る変更があれば衝突防止のため実行を保留する。

## 5. ZIP採番・renumberの厳密規則

### 5.1 pure naming plan

opt-inしたwork_keyについて:
1. すべてのWatchlist targetをarchive_order昇順で並べる（disabledも含む）。
2. keyごとにそのsite + discovery_keyに属する **acquisition_enabled=1の全Source** を取得する。
3. key内部でdisplay_position昇順。display_position=NULL、重複・不整合・非比較可能なlisting位置があれば、そのwork_keyの採番を停止。未知位置をItem ID・話数文字列・timestamp等で補完しない。
4. 連結した全Sourceに1,2,3...を付与し、既存の3桁以上ゼロ埋めprefixへ変換する。
5. pending/completed/skipped/external、paid、unavailable、期限切れ、未購入も、scope内であれば番号を **予約** する。
6. ファイル名の残り（title/order/author、long-title省略、disambiguator、ZIP/statusのdirectory policy）は現行ロジックを維持。
7. 未opt-in work_keyは既存site-native display_positionの命名を完全維持。partial archive_orderは設定エラー。

例: 同一work_keyのゼブラック第1～100話が有効、101～140話が担当外、BookWalker第14～15巻が有効なら、ZIP番号はゼブラック001～100、BookWalker101～102。ゼブラック101～140を予約しない。一方、マガポケの有償未取得話も担当範囲内なら番号に含める。

この番号は**配信話数や巻数ではなく作品内の並べ替え用序数**。異サイト間の話と巻の内容整合・欠落話の自動検出は本機能の対象外。

### 5.2 既存ZIPと再取得

- src/screenshot_crawler/batch/naming.pyの共通計画をBatchCandidate構築とmaintenance/archive_renumber.pyの両方から参照。別々に採番を再実装しない。
- 既存scripts/renumber_archives.pyを拡張し、--work-key単位の**全サイト**にわたるdry-run / applyに対応。
- Renameプレビューで old→new、件数、対象外の既存ZIP、collision、不明なposition、status JSON、Catalog Artifactsへの影響を表示。
- 対象外SourceのZIPは勝手に消去・rename・locator削除しない。既存パス占有を含む衝突ではapplyしない。
- Opt-in workはそのwork_key全体でatomicなpreflight policyを適用する。参加Sourceのposition/key/scope証拠が不明、対象外既存ZIPとの衝突、Artifact locator/Status JSON不整合、またはCatalog/Watchlist fingerprint差異が1件でもあれば、他の正常なrenameだけを部分適用せずwork全体のapplyを拒否する。
- 既存preflightのTEMP rename、rollback、status更新、Artifact locator更新を維持。手動で管理しているZIPや過去に複数Artifactがあるケースは曖昧性を拒否。異なるArchive同士の入れ替え/ずらしは対象全体をpreflightしなければならない。
- Old ZIP names, ordinal drift, and historical status/Artifact inconsistencies are visible maintenance warnings. They do not alone block a new Batch or trigger a rename/repair.
- A real file occupying the candidate ZIP or status path remains a hard stop. Check it before site access and again immediately before packaging; a collision detected at either check fails without overwriting that file, and post-crawl detection leaves the Item pending.
- Current scope/naming plan, candidate metadata/identity, access policy, and quota/ticket gates remain fail-closed. Use the separate strict renumber command when you choose to align old archives and Catalog locators; Batch never repairs them automatically.

## 6. CLI / API契約（実装時に命名調整可）

以下は現在利用できるCLIである。Scope Reconciler / archive renumber planはservice APIからも呼び出せるため、GUI integrationは同じvalidation結果を利用できる。

~~~powershell
# Workのscope変更をCatalogへ反映する前に影響を確認
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --work-key sample --dry-run --json

# 境界確認済みで問題なければ同期
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --work-key sample --apply --json

# 変更されたZIP番号を確認（既存CLIを拡張）
python scripts/renumber_archives.py --watchlist watchlist.yaml --catalog catalog.sqlite --work-key sample --status-dir output/crawl-status --dry-run --json

# 明示承認のうえ既存ZIPを改名
python scripts/renumber_archives.py --watchlist watchlist.yaml --catalog catalog.sqlite --work-key sample --status-dir output/crawl-status --apply --json
~~~

- dry-runはWatchlist・Catalog・ZIPに一切書き込まない。失敗事由を具体的に返す。
- applyは対象work_keyを明示要求。--all一括は段階導入時はpreview重視。
- 実行後はselected, enabled, excluded, unresolved, renamed, unchanged, collision等を機械可読な形式でも取得できるようにする（必要最小限のJSON summaryでよい）。
- Watchlist CLIの書き込みは、コメントを含むファイルでenabledのscalar変更のみを元テキスト上に反映し、それ以外の構造変更を拒否する。コメントレスの構造変更ではserialize後に再parseし、正規化したtargetsが要求された一覧と完全一致することを確認してからatomic replaceする。GUI用の高度なエディタは今回不要。

## 7. フェーズ契約・チェックポイント

### P0 — 既存実装確認と安全なテストデータ
**Objective**: 現行契約をテストで固定。
- 既存のschema v6、bounded/full/incremental、Batch (direct/quota/grant-only)、Package/renumberの呼び出し位置を確定。
- 複数key、異サイト、disabled key、paid rows、scope縮小、同一サイト重複keyのfixtureを作成。
- 仕様と矛盾する既存テストがあれば変更理由を記録。
**Exit**: Before/after behavior matrix作成、isolated SQLite/Watchlist/ZIPで再現可能、実Catalogを書き換えない。

### P1 — Watchlist model + Catalog v7
**Objective**: 新しい設定/派生フラグ・同期状態を持つ。
- archive_orderのload/write/validationと全keyのopt-in検証を追加。
- Catalog migration v6→v7にバックアップ・rollback・schema validation・index/constraintsを実装。
- Source model/serviceへacquisition_enabledを追加し、既存値を壊さない。
- fingerprint同期状態のスキーマ/API追加。
**Acceptance/tests**: 既存Watchlistが読める、archive_orderの不正・重複・部分指定は拒否、migrate冪等/backup/失敗rollback、既存run/artifact/positionの保持。
**Exit**: Catalog v7を専用テストDBで作成・移行可能。まだ本番DBへのapply禁止。

### P2 — Scope Reconciler / orphan扱い
**Objective**: Watchlistの取得方針をCatalogのフラグへ安全に反映。
- 候補範囲を既存Sourceのsite-native identity + 全体positionで解決し、dry-run差分を返す。
- scope変更時の成功Fullを前提に、対象外への0、再拡張時の1、新規Sourceの1、削除keyの未解決、disabledの非影響を確認。
- 全Sourceと同期fingerprintを一括commit。途中失敗/不完全Discoveryで適用せずゲートを無効にする。
- 同一siteのkey間移動はfail。DBのItem status/available/quota/run/artifactは変更しない。
**Acceptance/tests**: 1～140→1～100→1～140の再拡張でSource IDs/履歴不変、NULL position/未知境界/同一site重複でfail closed、incremental missingでfalse excludeしない。
**Exit**: legacy + scopedのreconcileが専用fixtureで検証済み。

#### P2 implementation contract and operational split

P2 adds the service API `ScopeReconciler.preview()` / `.apply()` and the CLI
`watch scope-sync --watchlist PATH --catalog PATH --work-key KEY
(--dry-run|--apply) [--json]`. Dry-run is read-only, including when the
Catalog path does not yet exist. Apply re-reads the Watchlist, revalidates the
preview under the stable per-Catalog job lock, and atomically commits the
complete Source-flag set with the sync marker.

A successful Full Discovery writes complete listing evidence only after
normal iterator exhaustion and Catalog finalization. It does **not** apply
Watchlist scope flags. Scope changes require a separate explicit preview and
apply after the required keys have fresh proof. This is a safety refinement to
the original combined Full-proof/sync wording: a multi-key work cannot be
partially synchronized merely because one key completed first. Position or
membership changes require fresh Full evidence and another explicit sync.

For compatibility, a first sync without discovery proof may bootstrap only a
work with no `discovery_scope` and no `archive_order`, when every existing
Source belongs to a current Watchlist key with matching site/work ownership;
all such Sources are enabled. Scoped or archive-ordered works require complete
Full proof. Removed keys retain their last site/URL binding in sync metadata:
re-adding the same key and URL is recognized, while changing a removed key's
URL requires new proof. Removed Sources remain in Catalog and are disabled.

Complete-listing hooks and bounded Discovery currently cover Zeblack,
BookWalker, Magapoke, Jump+, MANGA ONE, Piccoma, Hanayume, Younganimal,
ComicFUZ, Kadocomi, and Comic DAYS. Comic DAYS validates canonical episode
boundaries against its full Atom/readable-product listing. Kadocomi's native
history path is opt-in for scoped or archive-ordered targets; the legacy
unconfigured path remains public-only and does not infer positions. Its
observed native catalogue is not a guarantee that every episode ever published
is present: number gaps are not synthesized, and existing Catalog Sources
missing from a proof retain prior positions but block sync. On a supported
site, run successful Full Discovery, resolve boundary/position errors at the
source listing, then rerun dry-run and apply. An adapter without a complete
inventory hook remains blocked; repeated Full Discovery cannot resolve that
blocker. Do not manually edit `acquisition_enabled` or use Full as implicit
sync.

#### Site-wide Scope sync selector

`watch scope-sync` accepts exactly one of `--work-key KEY` and `--site SITE`.
The site selector uses current Watchlist targets (including `enabled: false`) to
select distinct work keys; Catalog-only Sources for removed Watchlist keys do
not select a Work. Each selected Work is still previewed and validated across
all of its sites and keys. Dry-run is a read-only aggregate preview. Apply
preflights the full selection before writing and then applies the existing
per-Work transaction under the shared Catalog job lock. It is not a site-wide
atomic transaction. `failure_stage` disambiguates `failed_work_key`: at
`preflight` it identifies a blocked Work that was not attempted; at `apply` it
identifies the attempted Work, whose transaction may have committed before an
exception; at `final_validation` it identifies the Work whose final gate failed
and may also appear in `applied_work_keys` if its apply call returned. Other
stages keep their own error context. `not_applied_work_keys` lists only
Work keys that were definitely unattempted. On any partial result,
review the JSON and run a new site dry-run before continuing. The final
Watchlist snapshot checks the selected site membership plus each selected
Work's complete key/scope/order fingerprint, including keys on other sites.

```powershell
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --site comicdays --dry-run --json
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --site comicdays --apply --json
```

### P3 — Batchの対象フィルタと同期ゲート
**Objective**: 元のチケット/選択セマンティクスを維持して担当外だけを除外。
- plan/run（normal/direct/quota/grant-only/deferred/replan/追加resource）で除外フィルタの一貫性を実装。
- setting fingerprint mismatchなら消費前に停止。Watchlistの境界照合はBatchに埋め込まない。
**Implemented**: CLI `batch plan` / `batch run` はWatchlistを読み、各Workのactive fingerprint・sync marker・現在Source flagsを照合する。Discovery証拠が更新されても、別途 `watch scope-sync --apply` が完了するまでBatchは拒否する。Plannerは担当外SourceをPolicy評価の前に候補外とし、quota履歴の集計には全Sourceを残す。Executorは通常実行とresolver入口でCatalog上のWork/Item/Source/Target identity、pending/available/current access mode、resource passの一致および同期snapshotを再検証する。grant-only allは全resourceをCDP接続前にpreflightし、候補がなければBrowser/Loginを開始しない。CLI run中はCatalog job lockを保持する。
**CLI**:
```powershell
python -m screenshot_crawler.cli batch plan --site mangaone --catalog catalog.sqlite --watchlist watchlist.yaml
python -m screenshot_crawler.cli batch run --site mangaone --catalog catalog.sqlite --watchlist watchlist.yaml
```
Watchlistを直接編集した後は、Batchの前に作品ごとにscope preview/applyを実行する。
```powershell
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --work-key my-work --dry-run --json
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --work-key my-work --apply --json
```
**Acceptance/tests**: 担当外のpaid/free/quotaが候補にならず、quota消費・ログインサイト操作も起きない。属するWorkの別サイトを自動mergeしない。既存Site Policyテストを回帰させない。skip reasonは`acquisition_disabled`。
**Exit**: synthetic normal/grant-only/deferred/replan/resource-passの候補拒否、同期stale・TOCTOU・forged resolver候補の拒否、empty grant-onlyのno-browserがtargeted testsで合格。P3 Reviewer **APPROVE / BLOCKING 0** 後、P4へ進んだ。

### P4 — opt-in通し採番と安全なrenumber — COMPLETE
**Objective**: 複数keyにまたがるZIPの並び順を統一。
- pure naming plan共通化、Batch新規ZIP命名と既存renumberを統一。
- known paid/expired/completed/disabledを採番母集団に保持。
- preflightで跨サイトのファイル名重複と非参加ファイル占有を検出し、fail/rollbackを維持。
**Acceptance/tests**: Cross-site numbering and legacy compatibility; out-of-scope paid sources do not consume ordinals, while in-scope paid sources reserve them. Existing ordinal drift is a maintenance warning. If you choose to align existing archives, use explicit whole-work renumber; a collision at the current candidate ZIP/status path remains a hard stop.
**Exit**: isolated ZIP/status/Artifactのdry-run / apply / collision / forced-failure rollback合格。P4 Reviewer **APPROVE / BLOCKING 0**。

**実装結果**: Batchとrenumberは同じwork-wide numbering planを使用する。既存ZIPのhash/size、status JSON、全WorkにまたがるArtifact locator alias、collision、Watchlist/sync状態をapply前に検証する。managed Workのrenumberは全site一括のみで、`--site` partial applyは拒否する。`--json`はold/new、excluded rows、blockers、summary/resultを単一JSON documentで返す。既存ZIP/status/Catalog更新の途中失敗ではrollbackを検証し、状態が不確かな場合は成功と報告せずrecovery detailsを返す。

**独立レビュー**: P4 Reviewer **APPROVE / BLOCKING 0**。全変更後のroot full-suite結果はPROGRESSに記録する。

### P5 — End-to-end と手動適用 — COPY-ONLY VERIFICATION
**Objective**: 既存実環境を壊さず導入。
- schema-neutral online backupとraw Watchlistを隔離seedにし、working copyだけをmigration・CLI検証に使用。
- synthetic fixtureでcross-site E2E、scope shrink/re-expand、renumber、status/Catalog locator整合、rollbackを確認。
- 実サイト確認・購入・quota/ticket消費は実施しない。scope proofを本番copy用に捏造しない。
- P5では本番Catalog migration/Scope apply/renumberを実施しない。運用適用は以下の手順に従い、operatorがpreviewを確認してから個別に実施する。
- docs/DISCOVERY_AND_BATCH.md、docs/BOUNDED_DISCOVERY.md、docs/BOOK_NAMING_RULES.md、docs/DECISIONS.md、note/00_core.md、note/07_catalog_position_archive_plan.md、必要なsite note、README/CLI helpを実装内容に合わせ更新。
**Acceptance/tests**: 複数サイトの一作品で期待通り採番、Catalog/ZIP/status locator整合、現行未opt-in siteの実行結果を維持。
**Exit**: synthetic E2E、rollback injection、migration-copy invariants、CLI read-only behaviorをPROGRESSに記録。全テスト結果はroot full-suite完了後に追記する。

#### 運用への適用手順（別途明示実行）

RenumberのArtifact locatorは旧ZIPパスの正本です。隔離status directoryだけでは十分ではありません。P5検証copyで `--apply` する場合は、必ず [COPY_VALIDATION.md](COPY_VALIDATION.md) の手順で全Artifact locatorとstatus JSONの `archive_path` を `COPY_ROOT` 内へremapし、symlink解決後の全参照がcopy root内にあることをapply直前にも検査してください。

1. Crawlerを停止し、運用Watchlist/Catalog/`output/Books`を変更しない保管先へコピーする。Catalogは `catalog backup --catalog <運用DB> --output <backup.sqlite>` 相当のSQLite online backupを使い、通常runtimeのDBを直接コピーしない。WatchlistとBooks/statusも同じ時点のcopyを保存する。
2. まずworking copyにmigrationを実行する: `python -m screenshot_crawler.cli catalog migrate --catalog <copy.sqlite> --backup-dir <copy-backups>`。Migration後にschema v7とbackupを確認し、既存7 tablesの既存columns/rows、Item status、Source IDs/positions、run/artifact/quota履歴が保持されていることを照合する。Migrationだけではscope syncもrenumberも行わない。
3. Watchlist copyの対象workのうち、必要なproof hookがあるsite/keyでsuccessful Full Discoveryを行う。Scoped / archive-ordered workでhook未対応のsiteは、Fullが成功しても必要なproofを作れずpreviewはblockしたままになる。未対応workはhook実装まで停止する。Full Discoveryはevidenceだけを更新し、取得担当flagsは変更しない。
4. `python -m screenshot_crawler.cli watch scope-sync --watchlist <copy-watchlist.yaml> --catalog <copy.sqlite> --work-key <work> --dry-run --json` を確認する。差分とarchive numbering impactが期待どおりの場合だけ、同じ引数に `--apply --json` を付ける。適用後はBatch planをcopyで検証する。
5. Archive-order renumber is optional maintenance, only when you choose to align existing ZIP names and Catalog history. Scope sync does not require it: when scope is synced and the current candidate/output-path checks pass, Batch can plan and run. If you choose renumbering, point Books and status paths at isolated copies, run `python scripts/renumber_archives.py --watchlist <copy-watchlist.yaml> --catalog <copy.sqlite> --work-key <work> --status-dir <copy-status> --dry-run --json`, review every blocker and planned move, and apply only on that copy after review. Excluded ZIPs are not deleted or overwritten.
6. Verify copied results, status files, Artifact locators, hashes, and restore steps. Operational rollout follows migration then scope sync; run renumber afterward only if you choose to align existing ZIPs. Take a separate backup and review a preview before each applied operation. Stop on ambiguous works and recover from migration backups or the renumber rollback report; do not guess at status or Catalog repairs.

`renumber_archives.py --json` returns one JSON document. An unmanaged legacy work may omit Watchlist for compatibility, while a managed work requires a matching Watchlist and synchronized snapshot. Explicit opt-out retains the legacy naming plan. If you choose to align existing ZIPs back to legacy names, review and apply a whole-work renumber; that optional maintenance is not a prerequisite for Batch when current candidate paths are free.

## 8. テスト観点（具体的な境界）

1. 1 work_keyで1 key（archive_orderなし/あり）、同work_keyで複数key、3 key (Jump+→Zeblack→Jump+)。
2. 本来同じ漫画でもサイトごとにItem別。名寄せなし、並び順だけ連結。
3. scopeなし、片側境界、両側境界、boundary不在、逆順、別シリーズ、global_display_position欠落。
4. 同一siteの別keyと外部ID重複のDiscoveryは拒否、Source再所属なし。
5. 以前登録済みの範囲外pending/purchased/failed/completedは保持して除外。復帰時に状態/履歴不変。
6. 有償話の扱い: マガポケ等で取得予定なら番号予約。ゼブラックで担当外にした有償話は番号を予約しない。
7. reserved positions: completed/skipped/external/unavailable/disabledを飛ばさない。新規話は後続keyをずらす。
8. 機械的な同期ゲート: Watchlist手編集/誤パス/同期前/クラッシュ/途中Full失敗/position変更後の旧名前を検出。
9. normal/deferred/grant-only/all-resources/single-work quotaでacquisition_enabledを一貫適用。
10. 既存ZIP（同名/非参加/既に除外済み）、Status JSON不一致、Artifact locator欠落、失敗時のrollback。
11. Watchlist YAMLのキー・scope・archive_orderのload/write保持、コメント消失を伴う操作は防止または明示警告。
12. full→bounded/full→unbounded/incremental→full変更後の出力、および無変更での既存動作の回帰。
13. 3-key synthetic workでZeblackの担当100 rows、BookWalkerの2 volumes、Magapokeのin-scope paid 2 rowsを扱う場合、BookWalkerが101/102、Magapokeが103/104となる。Zeblackのout-of-scope paid rowsは採番せず、合計は104。`example.invalid` fixtureはCatalog/Watchlist/ZIP構造専用であり、サイト境界parserの証拠には使わない。Adapter inventory hookは各siteのpure fake identity adapterで検証し、実site境界確認が必要なsiteのみ別途有界に調査する。
14. Catalog v7 migrationはdefault acquisition flagを設定してもsync/evidenceは未初期化のままとし、migrationのみでscope eligibilityやZIPを変更しない。
15. Comic DAYSのsuccessful Fullは、検証済みAtom/readable-product全listingを
    `comicdays-series:<id>` identityで証明し、canonical boundaryを同じlisting内で
    検証してからinclusive sliceを返す。latest-first orderをCore display positions
    `N..1`へ写し、archive_order下でpaid/completed rowも採番予約する。
    Incremental/partial Fullはproofを作らない。

想定の主なテストファイル: tests/unit/test_watchlist.py, test_catalog_migrations.py, test_catalog.py, test_discovery.py, test_batch.py, test_batch_executor.py, test_batch_naming.py, test_archive_renumber.py, test_cli.py と必要なbounded discovery integration。影響範囲が広いため、targeted/affected tests後にfull pytestとruffを推奨（docs/TEST_STRATEGY.mdに従い、実サイト実行は必要時のみ）。

## 9. 非目標 / 将来のGUI統合

- 同一サイトの異なるkey間で既存Sourceを自動移籍させない（衝突を検出して停止）。
- 作品内容の自動名寄せ・話と巻の換算・作品間のギャップ自動修復を行わない。
- 有料購入、課金、コイン、ポイント、チケット自動補充、ログイン状態の拡張を行わない。
- GUIは今回作らない。将来は「作品別/サイト別一覧」「キー・範囲編集」「対象外Source一覧」「Scope同期プレビュー・適用」「ZIP改名プレビュー」を共通Serviceの操作として追加する。
- 既存ライブラリ全体を起動時に自動改名・自動削除しない。

## 10. Implementer/Reviewer 作業規約

- LeadはPhaseごとに対象コミット/fixture/差分と受け入れテストを定義。Implementerは変更の少ない順に実装し、各Phaseの境界で証拠を残す。
- 実装はfeature branchで実施し、通常のwatchlist.yaml / catalog.sqlite / output/Booksをテスト対象にしない。作業者の未コミット変更は保持する。
- Reviewerは、誤採番（silent wrong ZIP）、scope外のquota消費、サイト横断の意図せぬmerge、同期漏れ、再取得時のファイル衝突を優先して独立確認する。
- productionコードに変更が入ったPhaseは必ずtargeted testsを実施。P4/P5では実際のZIP/status/Artifact一貫性をfixtureで確認。
- 各Phase完了時にPROGRESSを更新し、仕様変更・実装済/未実装・検証済/未検証を区別。runbook上の未実装例を現在使えるCLIとして説明しない。

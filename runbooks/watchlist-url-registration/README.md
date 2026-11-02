# Watchlist URL一括登録 — 実装Runbook

> Status: PLANNED / NOT IMPLEMENTED（2026-11-02）
> 対象: Windows PySide6 GUI、Watchlist、read-only URL解析、既存WorkEditor。Phase 00から順番に実施する。
> Authority: AGENTS.md → docs/SPEC.md / docs/ARCHITECTURE.md → docs/DISCOVERY_AND_BATCH.md / docs/BOUNDED_DISCOVERY.md → docs/TEST_STRATEGY.md → docs/DECISIONS.md → code/tests。Runbookは既存契約を上書きしない。
> Stage 00 COMPLETE。次は [Stage 01](01-url-resolver/README.md)。採用されたユーザー判断は [DECISIONS.md](DECISIONS.md)、進捗は [PROGRESS.md](PROGRESS.md)。

## Goal / ユーザー要求

- 1件・複数件のURLを同じGUIに貼り付け、サイトと作品を解析してWatchlistへ登録する。サイト別のDiscovery起点URLをユーザーに覚えさせない。
- 入力URLを厳格に検証し、サイト固有の確認済み規則でDiscovery用URLへ安全に変換する。正規Discovery URLそのものが不正・未対応・未確定ならブロック。安全な正規URLは確定しているが作品ID/titleが未取得の場合は、手動確認の候補として残す。
- 作品名(label)をサイトから取得し、読み・ローマ字化により人間が理解できるwork_key候補、work_key + "_" + siteのkey候補を生成する。最終確定前に編集可能にする。
- 既存Watchlistの同一作品/同一サイト登録を照合する。異サイトの同一作品はタイトル等から候補を提示しても、ユーザーが最終的にグループ化・既存Work紐付けを決定する。サイト横断で自動mergeしない。
- 新規の単一取得元Workは、scopeなし（全話対象）を標準に簡単登録可能。複数key/サイトの同一Work、または既存複数key Workへの追加は既存の話一覧比較・discovery_scope・archive_order/archives_segments編集を必須にする。単一取得元でも任意で詳細編集可能。
- URL解析 → 候補編集 → 複数Workの必要な詳細設定 → 最終プレビュー → 明示的一括保存。途中でWatchlist/Catalog/ZIPを変更しない。保存後に、変更keyのFull Discoveryの確認ダイアログへ既存導線で接続する。Fullは独立ジョブであり、保存成功とDiscovery成功を混同しない。
- 一括解析・詳細編集中にエラーや画面切替があっても、ほかの候補・手動修正を保全する。個々の候補を登録対象から外す/後回しにできる。

## Non-goals

- サイトトップ・カテゴリ一覧からの全作品探索（作品一覧Discovery）、定期Discovery、Batch自動実行。
- ローマ字/同タイトルだけによる異サイト自動統合、異サイトの話単位自動対応付け、既存key/work_keyの自動rename。
- Catalog/Watchlist schema migration、既存Source/Item/Artifact移動・削除・自動ZIP rename、SitePolicy/課金/チケット動作変更、ブラウザ拡張。
- URL Resolverを使って既存Discovery Adapterの厳格な入力検証を緩和すること。

## Fundamental boundaries

1. **URL input is untrusted**。認識済みの公式site allowlistだけを受理する。任意のhost、user-info、localhost/private network、外部短縮URLを一般的なHTTP clientでたどらない。redirect先もsiteごとに検証し、異サイト/異Work/曖昧な遷移を拒否する。意味あるquery/fragmentを安易に消さない。URL以外の閲覧者操作やログイン/reader/購入/ticket/grant/captureを起動しない。
2. **Resolver is read-only**。共通層でブラウザ/CDP接続やサイト固有selectorを直書きしない。必要なサイト観測は既存BrowserSession/CDPとサイト固有処理を利用する。外部HTTP requestが必要な実装はサイトの自然なページ遷移/レスポンスと権限・制約を精査し、Stage 00で設計を明示する。
3. **Watchlist key stability**。既存key/work_keyは変更禁止（明示リネーム機能は対象外）。新規keyは作品ローマ字候補を元に、最終確定後は不変。変換失敗・読みに不確実性があれば編集を要求し、意味不明なランダムIDを自動確定させない。
4. **URLの有効性と登録可否は別**。現行Discoveryの正規起点11サイトを厳格に検証し、不安全・未対応URL、変換先不明は確認操作でbypassできない。正規URLが確定できてもnative work ID/titleが未取得なら、identity unknownのまま人によるlabel・Work・IDの明示確認を許可。ただし保存前の所有/重複照合を必須とし、曖昧な既存Sourceの移動・自動Work統合は禁止。
5. **No silent acquisition changes**。同一Workで新たな取得元が増える場合は既存範囲/順序を保持し、完全一覧を用いた人の範囲・担当確認なしに全話を複数keyへ割り当てない。archive_segmentsを使うWorkも尊重し、archive_orderへ黙って縮退させない。既存WorkEditorのScoped Preview/Catalog guardを流用する。
6. **Save is one transaction boundary**。最終選択されたreadyな候補を1回のWatchlistService.apply_editで原子的に反映。version/CAS + Catalog snapshot/lock + fresh proof を再検証する。ブロック候補は一括保存対象から除外できるが、選択中の候補が一つでもブロックなら選択集合全体を保存しない。
7. **No hidden Full**。保存後に変更keyのFull Discovery実行を確認する。No/Cancelでは保存済みのまま終了し、Catalog未反映/未同期を明示。Fullが失敗しても保存をロールバックしたふりをしない。

## UI / data-flow contract

1. URL入力: 改行区切り。空行と文字列一致重複を整理し、元入力を保持。
2. 解析: per-URL status = valid / converted / blocked。site、input_url、discovery_url、site_work_identity（確定時）、title、evidence、blockersを提示。read-only。失敗行だけ再試行可能。
3. 候補編集: 同一site + 同一site-native work identity は重複候補として統合。同じラベルだけでは異siteを確定mergeしない。ユーザーが既存Workか新規Workかを選択し、work_keyとkey候補を修正。
4. グループ単位で status = ready / needs_scope / blocked。新規で単一取得元は原則ready。同一Workで複数keyならneeds_scope（既存の複数keyも含む）。任意で単一keyも詳細編集。
5. 詳細設定: 完全一覧の read-only preview で実際の各key/範囲/完成順を編集。キャンセルは当該Workの暫定編集のみ破棄。確定は一括登録のメモリ下書きへ返し、Watchlistへ保存しない。
6. 保存前プレビュー: 追加/既存の区別、全key、同一Workのgrouping、取得範囲・archive順序、現行Catalogへの影響（予測のみ）、未実行のFull/Scope sync/renumber注意事項を表示。対象Workを選択可能。
7. 明示的保存: Watchlistのみ一度に更新。必要ならFull用既存実行確認へ進む（1つの保存から複数keyが発生しても、選択集合・未実行・失敗を正確に扱う）。

## ID policy

- 新規work_key例: kusuriya_no_hitorigoto。日本語読みからローマ字候補を作り、a-z / 0-9 / underscoreの安全なslugに正規化。英字既存タイトルは過剰変換しない。連続underscoreと先頭/末尾underscoreは整理する。
- 新規key例: kusuriya_no_hitorigoto_magapoke。サイト名はDiscovery registryのcanonical keyを使う。標準はwork_key + "_" + site、同一Work/同一siteに追加keyが必要なら明示的に _2, _3 等の衝突回避候補を提示。
- 新規work_keyの衝突は別Workか既存Workへの所属かを明示確認。勝手に同じWorkへmergeしない。異なる新規Workの同一slugには _2 の候補を提示できる。
- work_key編集時は、ユーザーが未編集のkey候補だけ連動。手動編集済みkeyは自動上書きしない。既存Workに紐付けたときは既存work_keyを編集不可・継承。
- 読み仮名の一次証拠がなければ機械変換はsuggestionにとどめる。未確定・空・不正/衝突したIDでは保存不可。IDはCLIやYAMLから読める形式であり、乱数やhashのみをユーザー向けkeyにしない。

## Implementation map / stages

| Stage | Responsibility | Gate |
|---|---|---|
| 00 | [現行契約監査・URL対応matrix](00-contract/README.md) | read-only監査と設計判断、実装なし |
| 01 | [URL Resolver + pilot](01-url-resolver/README.md) | 全11サイトの現行起点検証 + 1サイトの安全な変換 |
| 02 | [登録候補・命名・重複判定](02-registration-service/README.md) | pure/fake testsで複数URLのdraft成立 |
| 03 | [URL貼付・候補編集GUI](03-gui/README.md) | read-only GUIで下書きが編集できる |
| 04 | [WorkEditor詳細設定のdraft連携](04-work-editor/README.md) | scoped Workの保存前検証が成立 |
| 05 | [原子的保存 + E2E](05-save-and-e2e/README.md) | 登録→プレビュー→保存→Full確認、既存回帰 |
| 06 | [他サイトURL変換・metadata拡張](06-site-coverage/README.md) | 実証した変換と作品metadataのみ拡張 |
| 07 | [完全一覧previewの段階拡張](07-listing-preview-coverage/README.md) | 初期4サイトで先行し、残り7サイトを順次対応 |

**Vertical slice:** Stage 01は少数siteで変換、Stage 02–05はそれを使ってGUIからの一気通貫を先に完成させる。Stage 06で11サイトに順次広げる。11サイトの「現在の起点URL」はStage 01でパーサ適合を試験し、別形式の変換を全サイトで保証するものではない。

## Acceptance / overall

- 1件/多数URLを貼り付け、正常・変換済み・修正必要を区別できる。
- 未サポートURL、違うサイト/作品、redirect、誤読タイトル、ID重複でsilent mis-registrationがない。
- 既存label/key/work_key、既存Workのscope/order/segments、Catalog・ZIP・取得履歴を破壊しない。
- 単一key/複数key/既存Work追加を通せる。複数keyの場合は詳細設定なしで保存できない。
- 一括保存はall-or-nothing for selected set。候補の部分選択と編集持続。競合・stale時はno-write。
- Browser GUI応答を妨げず、登録時のサイト操作で課金/閲覧権を消費しない。
- test selectionはdocs/TEST_STRATEGY.md。各実装Stageでtargeted → affected → 必要なIntegration/Liveの順。shared広範囲変更ではfull suiteを検討。必要に応じてruff check src tests。
- 実装Stageでdocs・noteを同一変更で更新。Stage完了時に変更範囲、実行したテスト/skip、Live検証状況、BLOCKER、次Stage可否をPROGRESS.mdへ記録。

## Starting evidence (auditにより更新可)

- watchlist/models.py、watchlist/service.py: stable key/work_key、revision CASとWatchlist一括編集API。
- gui/watchlist_editor.py: AddWatchlistKeyDialog はkey/work_key/site/url/label手入力。
- gui/work_editor.py と watchlist/work_edit.py: WorkDraftはWork単位、read-only ListingPreviewを使う範囲・archive editing、現行WorkEditorは自らsaveする。今回の一括保存ではdraft-only導線が必要。
- discovery/listing_service.py: Catalogへ書かない完全一覧preview。通常DiscoveryService.discoverはCatalogを書き得るのでURL解析に使わない。
- cli.py _discovery_registry(): bookwalker, comicdays, comicfuz, hanayume, jumpplus, kadocomi, magapoke, mangaone, piccoma, younganimal, zeblack の11 site。
- 2026-11-02時点のGitHubコード読取に基づく。実サイトの最新挙動・変換可否を確認済みとみなさない。

## Stage 00後の決定（2026-11-02）

- 手動登録: **安全な正規Discovery URLは確定済み**なら、作品IDまたは作品名が未取得でも、ユーザーによる作品名・Work・key/work_keyの明示確認と保存前の所有競合チェックを経て登録可能。native identity不明はunknownのまま保持し、手動確認をsite identityの証拠としない。
- 詳細編集: 完全一覧previewは現行4サイト（magapoke、jumpplus、zeblack、comicdays）で先行。残り7サイトで必要なscope詳細は理由付きblocked。Stage 07で順次拡張。
- Stage 01は11サイトの現行起点URL検証とKadocomiのURL変換pilot、identity/titleの証拠状態を返すところまで。手動確認UIと保存は後続Stage。
- 詳細は [DECISIONS.md](DECISIONS.md)。Stage 05の完成は全11サイトの作品名自動取得や全サイトscope編集の完成を意味しない。

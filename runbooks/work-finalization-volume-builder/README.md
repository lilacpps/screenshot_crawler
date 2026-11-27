# Work終了処理 — 巻統合・完成品生成 Runbook

> Status: **PLANNED / NOT YET IMPLEMENTED — 2026-11-27**
> 対象: Windows / PySide6、既存 Catalog・Watchlist・renumber、Piccomaの公開作品メタデータ。
> このRunbookの追加は計画のみ。進捗・証拠・レビューは [PROGRESS.md](PROGRESS.md) に記録する。

## 0. 目的と範囲

作品行の右クリック「作品の終了処理」から、正確な work_key 単位で保管用完成品を生成する。話ZIPは巻単位に統合、BookWalker/ebookjapan等の巻ZIPはバイト列を保持してコピーし、両者を一つの作品フォルダにまとめる。ピッコマの作品検索と巻境界情報を主力にし、得られない・曖昧な部分だけGUIで手動指定する。独立CLIは必須ではない。

今回の完了は**出力生成・検証**であって、作品の終了確定ではない。prepare_recrawl、再取得、Full Discovery、renumber実行、watchlistアーカイブ、欠損検査除外、元ZIP整理/削除は後続workstream。Catalog schema/status/Artifact、Watchlist、入力ZIP/status、取得権限、quotaを変更しない。外部DB、LLM、本文閲覧、表紙追加、広告除去、画像重複排除は対象外。

## 1. Authority / 進め方

AGENTS.md のauthority orderに従う。開始前に docs/SPEC.md、ARCHITECTURE.md、DISCOVERY_AND_BATCH.md、ACCESS_CONTROL_AND_PACING.md、DECISIONS.md、TEST_STRATEGY.md、CODEX_IMPLEMENTATION_GUIDE.md、GUI_README.md、BOOK_NAMING_RULES.md、note/00_core.md、note/07_catalog_position_archive_plan.md、note/09_piccoma.md（実際のファイル名を確認）、runbooks/work-key-archive-order/README.md、runbooks/work-deletion/README.md を確認。矛盾・最新実装との差はPROGRESSへ明記し、上位authorityを黙って変更しない。採用仕様は実装と同時に関連docs/noteに同期する。Runbookのみの追加は実装済みを意味しない。

feature branch（例 feat/work-finalization-volume-builder）、単一production writer、独立reviewer。ユーザーの未commit変更を保持。既存コードの小さな共通部品を再利用し、汎用provider frameworkや深い継承は作らない。各Phaseのtargeted testsとBLOCKING-0レビューを終えて次へ。Phase 0の外部要因で不成立でもPhase 1–3の手動経路は進めてよい。実サイトの未知を推測実装しない。ライブ調査は通常の公開一覧をCDP/Playwrightで読むだけ、権限/DRM回避・チケット/課金・本文閲覧禁止。サイト利用条件、レート制限、既存AccessGuardを守り、retry上限を設定。認証情報や実サイトの著作物をfixture/commitに残さない。実データの変更なし。試験は隔離Catalog/Watchlist/library/output、人工ZIPを使用。実運用コピーを使う場合は明示的に許可された読み取り元のみ、別出力に生成する。

## 2. 実行順序

| Phase | 契約 | 完了条件 |
| --- | --- | --- |
| 0 | [実サイトProbe](00-piccoma-probe/README.md) | 検索・巻境界の証拠と未解決点 |
| 1 | [入力・共通モデル](01-inventory/README.md) | 厳密なWork所有・順序・採用ZIPのプレビュー |
| 2 | [GUI・手動編集](02-gui-manual/README.md) | 保存/再開できる境界設定 |
| 3 | [完成品生成](03-export/README.md) | 手動経路で安全な作品単位出力 |
| 4 | [Piccoma巻境界](04-piccoma-boundaries/README.md) | 指定URLの読み取り専用取得 |
| 5 | [作品検索](05-piccoma-search/README.md) | URL自動探索・候補選択 |
| 6 | [自動照合](06-matching/README.md) | 巻開始話の対応・未解決の局所化 |
| 7 | [統合・検証](07-e2e/README.md) | GUI完結、回帰・実サイト評価 |

## 3. 共通契約

- work_key→work_id→Item/Source/成功Run/Artifactで入力所有を確定。タイトル/ファイル名globで収集しない。acquisition_enabled、archive_order/segments、現役Artifact、既存external coverageの意味を尊重。担当外・履歴は除外し、曖昧性は解決するまで生成不可。巻/話はItem.kindと確実な巻番号等から判断し、未知種別は明示確認。既存巻は別の巻に混入させない。
- 順序は既存採番計画とrenumber済み実ファイルを照合する。prefixは序数であり話数/巻数ではない。複数keyに一意な順序がない、採番がずれている場合は既存renumber等へ誘導し、自動修正しない。
- 巻番号付き開始位置（Item/Source ID）で連続区間を区切る。間に挟まる番外編/特典は区間の巻、境界直前の不明話は前巻。先頭境界より前、既刊末尾より後の未単行本化部分、境界話欠損、巻ZIPとの重複、参照範囲が不完全な場合は自動補完しない。手動で明示決定する。巻内で順序は変えない。既存巻・欠番・途中開始の実巻番号を保持。
- 採用範囲内の未取得や不完全巻を表示し、無断で完全扱いしない。破損・欠損のある採用入力は生成不可。未取得範囲を意図的に除外する場合はGUIで明示確認し記録。出力成功は市販単行本と同一・全話取得済みを意味しない。
- 参照情報と確定境界を別に保存し、再取得/改名でも可能な限り再利用。ID再利用・変更、scope/順序/Work identityの変化を検知し、古い承認は失効させる。GUI確認済みの手動境界は再検索で上書きしない。
- GUIの確認→plan→apply。applyで入力snapshot・出力衝突・排他を再確認。バックグラウンドWorkerで進捗/エラーを表示。将来の終了処理から同じServiceを直接呼べる。実行中の再取得/renumber/削除/同一出力への並行生成を防ぐ。既存CatalogJobLock・deletion gate・job admissionとの統合を確認する。
- 完成品は独立rootへ出力。初期値 output/Books-finalized、設定/GUIで変更可。既存 Books と同じ genre/title の作品フォルダ、BOOK_NAMING_RULES準拠（実巻番号、2桁/100巻以上3桁、作者、長いタイトル、安全なWindows名）、取得用prefixは除去。別work_keyや正規化名の衝突を拒否。入力rootと出力rootの重なりは禁止。
- 画像は復号・再エンコードしない。元の画像ファイルバイト列を維持、巻内通し番号、ZIP member順は既存packagingの規約に従う。既存巻ZIPはファイル全体のSHA-256一致。ZIP統合はページ順/枚数/各画像SHA-256/CRCで検証。
- 出力rootと同一filesystemの一時作品フォルダで全巻を生成・検証してから公開。完成品への直接書込み、既存品の無断上書き禁止。再生成時は明示承認後に旧完成品を退避し、新品公開失敗なら旧品を復旧。クラッシュ時の状態を記録し、復旧待ちには生成不可。物理電断までの保証は主張しない。

## 4. 保存・モジュール

初期配置案（既存path設定に合わせ調整可。変更はPROGRESSに記録）:
- output/management/volume_mapping/<safe-work-key>.json: schema_version、work identity、参照product/URL・版/観測日時・証拠digest・巻開始話/ID、確定境界・根拠/手動修正、未解決、入力順序snapshot。安全な一意ファイル名、atomic replace。
- output/management/finalization/<safe-work-key>.json: 操作ID、plan digest、入力Item/Source/Run/Artifact/locator/hash、各出力巻・ページ数・hash、未取得/除外の承認、生成日時・検証結果、出力先。公開と記録の不一致は復旧待ち。完成品フォルダに管理JSONは置かない。将来の終了確定の証拠用であって archived フラグではない。
- gui/work_finalization.py + gui/volume_builder.py: 既存MainWindowから起動、UI/Worker。今回だけのタブで十分。
- maintenance/volume_builder/: models, inventory, planner, matching, packaging, storage（必要最小限に整理可）。
- site_adapters/piccoma/volume_mapping.py, work_search.py: サイト固有の読み取り専用処理。
- tests/unit, tests/integration: 対応する契約を検証。

## 5. 最終受入

GUIで1作品を選ぶ→renumber済み入力を表示→Piccoma自動探索/巻境界抽出/照合→必要時だけ手動修正→プレビュー→完成品生成・検証、または全手動経路が成立。巻のみのWorkは検索不要。混在Workは統合+コピー。入力/他Work/Catalog/Watchlist変更なし。正常、失敗、キャンセル、再実行、既存出力、古いplan、同名別Workのテストが通る。Phase 7に実サイトの観測数・取得率・境界正解率と未確認を記録。フルsuiteの要否はTEST_STRATEGYで決め、未実行をPASSとしない。完了時にdocs/note、テスト結果、未解決、運用制約を報告する。

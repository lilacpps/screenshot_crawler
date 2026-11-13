# 花とゆめ＋ Catalog修復 Runbook

対象: Catalog v7 / Python 3.12+ / 既存PySide6作品管理GUI。
Stage 00/01と、後続のユーザー依頼によるStage 02 GUI/移行処理を実装。
Stage 03Aの履歴専用ZIP分離を追加。Stage 03の採番/不要ZIP削除は **PLANNED / NOT YET IMPLEMENTED**。
運用CatalogのStage 02はユーザー適用後のDB状態をread-only確認済み。履歴先のZIP locator15件も確認済み。
assistantによる本番Catalog/ZIP変更は実施していない。
運用への適用は具体的プレビューを確認した後の別の明示操作とする。
Stage 02はWatchlist、ZIP、チケット状態を変更しない。Stage 03AのZIP分離は別の明示preview/applyとする。

## 要求と安全条件

複数作品でFull済みの旧unavailableと新available（pending/completedの両方）を
読み取り専用で比較し、人間が1対1・1対多・多対1・候補複数・不明を検討する。
API identity、メタデータ推測、人間の対応指定、本文同一性を別の概念とする。
API identityが確定しても本文改訂はあり得る。候補生成からcompletedを自動伝播しない。
Stage 02では人間が採用した対応と方針に基づき旧取得を利用できる。技術的本文証明とは区別する。
取得/利用履歴と手動編集を持つItem/Source/SourceTarget、全CrawlRun、全Artifact、quota/resource state、ZIPを保持する。
ユーザー追加方針により、新旧pendingで新側を採用するとき、履歴/権利/手動編集/別Source/個別Targetのない
旧Item/Source/Targetは削除し、新pendingだけを残す。保護対象のある旧pendingは理由を表示して保管する。
削除IDをdry-run/tokenへ含め、verified backupとtransaction内再検証後に適用する。詳細はStage 02契約。
利用するZIPの存在・内容検証と、CatalogのZIP記録の存在を区別する。
unavailableは刷新世代を表す正式フィールドではなく公開終了等も含む。availableも
新IDである保証はなく、古いCatalog snapshotの可能性を常に示す。

## Stage 00 調査結果

### 現在の責務と再利用可能な機能

- `catalog/models.py`, `schema.py`: Work 1:N Item、Item 1:N Source。
  Source identityは(site, external_id)でunique、Targetは(source_id, backend, target_key)。
  RunはItem/Source/Targetを参照し、実行時identity/URL/access_strategyのsnapshotを保持する。
  ArtifactはItemと任意のRunを参照。ZIPはArtifact locatorの外部ファイルでありDB内の本文ではない。
  SourceをunavailableにしてもItem status、Run、Artifact、Targetは消えない。
- `discovery/service.py`: recordごとに新Item/Source/web-default Targetを作る。同identityは
  既存Itemを再利用する。全件正常終了のunbounded Fullだけが同site/keyのmissingを
  available=falseにする。bounded Fullは範囲外のmissingを一律unavailableにしない。
  DiscoveryはItemの手動タイトルをcanonical話名で上書きしない。
- `site_adapters/hanayume/discovery.py::resolve_identity_changes`: scopeなしの完全Full proof、
  missing最大16件。old/newのexact nonredirect HTTP200 APIとstrict parserの
  episode/summary/access/series/index一致、現在Full membership、1対1を要求。
  16超を一律に緩和せず、この経路は変更しない。
- `maintenance/source_identity.py`: planはread-only、WALを拒否。applyはjob lock +
  BEGIN IMMEDIATE + token再検証。旧Item/Sourceを残しexternal_idとweb/default URLを更新。
  donorはpendingかつ手動タイトル/note、Run、Artifact、grant、兄弟Source、特殊Targetの
  ないpristineだけ。new completedは拒否。旧running Runも拒否。証拠失効・scope stale化。
  **API identityだけで本文が同じとする今回の引き継ぎ条件には不足する**。
- `management/catalog_reader.py`: 既存v7をmode=ro/query_only/BEGINで一貫読取。
  WALを事前拒否し、migration/createなし。通常Inventoryは最新Run/Artifactのprojection。
  Stage 01では明示オプションで全履歴を読む（通常のprojectionは維持）。
- `watchlist/models.py`, `archive_order.py`: acquisition_enabledは現行取得担当。
  enabledはDiscoveryのON/OFFで別概念。scopeはnative URL境界/除外ID、
  archive_orderは作品内key順、archive_segmentsはnative ID境界の交互区間配置。
  segmentsとlegacy orderは混在不可。旧ID境界の置換は単純なURL変更では解決しない。
- `batch/planner.py`: 通常候補はpending Item、enabledな取得担当Source、available、
  Target、SitePolicy等で決定。Artifactがmissingでもcompletedをpendingに戻さない。
  repairの手動メモはBatchに入力されない。
- `batch/naming.py`, `maintenance/archive_renumber.py`, `scripts/renumber_archives.py`:
  全作品の担当flags、key順/segments、display_positionからZIP prefixを算出。
  同名collisionはdisambiguator、既存ファイル/ハッシュ/参照/statusのpreflight、
  apply lock、段階renameとrollbackを備える。今回呼ばない。番号は話数番号と別概念。
- `gui/main_window.py`, `work_editor.py`: Qt worker→immutable DTO→GUI threadで表示。
  Catalog/job/Watchlist saveは別の明示操作。新機能もworkerで読取/通信し、主画面から開く。

### Stage 00調査時に新規実装が必要だった機能

修復専用snapshot/candidate graph、全履歴比較、手動対応メモ、報告JSON、
通常Fullと独立したAPI解析（offset/件数/request上限/総時間/間隔/停止）、左右比較Dialog。
本文照合、取得済み同士の現行採用、履歴保存のまま担当解除、永続的な除外/世代の扱い、
Watchlist anchor移行、移行監査は既存SourceIdentityMaintenanceだけでは実現できない。

## Stage 01 実装契約

### フロー

1. Catalogのhanayume Sourceを持つWorkを一覧表示。Watchlistの無効/アーカイブ作品、
   Catalogだけに残る作品も含める。選択作品について一貫した全履歴snapshotを読む。
2. 左unavailable/右available。Item metadata/status/note、Source identity/URL/key、
   flags/position、Run全件、Artifact全件、scope/order/segmentsを確認する。
3. 同じCatalog Work、同native work ID、同じ非NULL key、strict episode URLの範囲で候補生成。
   話数ラベル・話数番号が一致し、その完全ラベルの対応が旧新の両方向で一意なら、
   最初に1対1推測として取り分ける（ユーザー確認後の2026-11-11方針）。丸数字のpartも
   完全ラベルの一部とし、scene4①/②/③同士を3対3にまとめない。手動titleや位置差は
   この優先判定を妨げない。話番号は先頭の `N.` を途中の `ACT.N` より優先して読み、
   `第N翼` も認識する。異なる既知話番号は近接位置だけで結ばない。
   `其ノ一`〜`其ノ九十九` の正規漢数字とその末尾の丸数字partにも対応する。
   百以上・数字の連記・未知suffixはこの形式の番号として推定しない。
   `#N` / `#N.M` とその丸数字partにも対応し、小数部分を保持して整数話と区別する。
   全角＃/数字/小数点はNFKCで正規化する。小数話も完全ラベル一致が一意なら1対1を優先する。
   `♭N` と丸数字partも認識するが、`♭-001` や `♭064 Side B` は通常話番号に解釈しない。
   先頭ゼロは保持し、別表記への暗黙の同一視は行わない。
   `episode.N` と丸数字partも認識する。NFKC/casefoldを適用し、先頭ゼロは保持する。
   `episode.EX` 等の特別表記を通常話番号へ寄せない。
   同ラベルが複数ある場合は一意とみなさず、件数上限をかける前に
   重複を確認する。残りだけを話数番号・近接順序・前後ラベル・ZIP記録などで推測し、
   各旧Source上位8辺をconnected componentへまとめる。候補複数は分割/統合確定と表示しない。
   API証拠と手動メモの優先度、本文未証明、completedを変更しない条件は維持する。
4. 希望時に専用API解析。共有CDP session、新規所有Pageだけを使う。Adapterは接続を所有しない。
   robots.txtとexact episode metadata GET以外を遮断。viewer/checkout/Batch/Grant-onlyは呼ばない。
   旧endpointと独立した新endpointがstrict identity/index一致し、同snapshotの現行候補に
   存在する場合だけAPI対応証拠とする。複数旧→同新は1対1に数えない。
5. 左右複数行を選んで手動対応/保留/再取得、グループ解除。補足メモは任意（空欄可）。
   選択した左右の行全体を1グループにし、下のリストの指定行を自動選択・スクロールする。
   成功・選択エラーは操作欄の近くにも表示する。
   旧側だけの保留、新側だけの再取得にも対応。グループの一部を対応指定しても、
   残りの候補を保持する。本文同一性を指定済みと誤認させない。Catalog/Batch/ZIPへの効果なし。
6. summaryと全根拠、設定、snapshot token付きJSONを新しいファイルにのみ保存可能。
   Stage 02のapply入力として無検証で信用しない。現段階はJSON再読込なし。

### アクセス上限

既定: 旧100件、最大200 API GET、180秒、開始間隔2秒、offset=0。
件数最大500、request最大1000、時間最大600秒、間隔最小0.5秒。
逐次、再試行なし、旧/新のrequest両方を同じ予算から引く。deadline/停止/401/403/429/
5xx/通信失敗は未確認として終了。他の未証明応答は不明として続行する。
各fetch5秒abort/外側6秒、body2MB上限。CDP接続は別途15秒以内。途中結果を保持し、
処理済offsetから続行できる。API再実行は同じsnapshot内のみで証拠を累積する。
通常Discoveryの16件制限、access pacing、AccessGuard、metrics契約は変更しない。

### データ不変条件と変更範囲

- Catalog/Watchlistは読み取り専用。WAL、破損、schema不一致は停止。
- CatalogServiceやmaintenance.applyは構築/呼出ししない。修復保存は新規JSONのみ。
- 全Artifact履歴を保持し、ZIP記録を本文・存在確認と混同しない。
- candidate/manualのIDは同snapshotから検証。他Work/site/key・不正URLを拒否。
- 手動指定とAPI証拠は異なる。手動の意図的な誤対応の本文判定は人間の責任であり、
  Stage 01では適用できない。API証拠の矛盾は詳細に残す。
- 主画面接続と専用Dialog、Qt非依存解析、site-local probeだけを追加。
  schema、Discovery、Batch、Core Runner、source identity apply、renumberを変更しない。
- ZIP画像previewはStage 01対象外。将来、安全なmember名・解凍量/画素数制限・
  symlink/path traversal拒否・worker decode・LRU等を設計してから追加する。

### 受け入れ条件とテスト計画

合成v7 DBでFull済みunavailable＋pending/completed、複数旧、1:N/N:1、タイトル/note、
scope/order/segments、複数Artifact/Runを確認。DB/Watchlist/既存ZIP byte不変を検証する。
他Work/key、malformed ID/URL、API不一致/foreign/index不一致/redirectを拒否。
16超の独立解析、request/time/件数/間隔/offset/停止、403/429、部分結果をfake Pageで検証。
Qtテストで実worker→表示、左右選択、手動編集/解除/保留/再取得、保存拒否、エラー回復を確認。
affected: Catalog reader/Inventory、既存GUI smoke/work editor、Hanayume identity、
SourceIdentityMaintenance、Batch planner/scope/naming、renumber。
既存Discovery/Batchを変更しないためFull後再発/途中apply失敗/transaction rollbackの
新しい適用契約はStage 02で実装・検証する。既存テストで現行契約の回帰を確認する。
実siteでは許可範囲のmetadata GETのみ。実Catalog/ZIPの書込、ticket消費は禁止。
結果/未実行カテゴリはPROGRESS.mdに記録する。

## Stage 02 — IMPLEMENTED / COPY VERIFICATION、運用applyは未実施

詳細な現行契約は [02-migration.md](02-migration.md)。保存報告を現在の作品graphと照合し、
人間による対応採用を確認してdry-runを生成する。GUIで旧/新/再取得/保留/履歴保管を変更できる。
単純1対1のpristine donorは既存SourceIdentityMaintenanceを一括transaction内で再利用。
その他の旧利用は旧ZIP参照をnoteへ残すexternal coverageとし、複雑なら新側を再取得してよい。
保留/未対応はapplyをblockし、対応無しは明示的な履歴保管とする。

保管Sourceは担当OFFと非現行履歴bindingへの移動を同時適用し、既存scope configuration historyへ
bindingを登録する。旧identityが空く場合はquotaなしの履歴aliasで予約する。通常Full/Scope Syncで
履歴を再有効化せず、履歴IDがsite上で再登場した場合は既存所有権guardで停止して再確認する。
旧IDを含むscope/segment anchorは自動置換せずblockする。Watchlistは変更しない。

Catalog/Watchlist lock、事前条件token、verified backup、BEGIN IMMEDIATE内再検証、
単一transaction、操作markerによる冪等性を実装。全Run/Artifact/quota履歴、ZIPを保持する。
合成Full→Scope Sync→Batch planと、実Catalog隔離コピーのapply/再apply/Batch planを確認済み。
実サイトへのFull再実行は未実施。結果と適用対象はPROGRESS.mdを参照する。

## Stage 03 — PLANNED / NOT YET IMPLEMENTED

追加依頼による履歴専用ZIP分離は [Stage 03A](03-history.md) に実装・検証契約を分離した。
Stage 02移行前の投影previewと、移行後の実Catalogに対する独立applyを提供する。
以下の採番/削除は引き続き未実装。

現行Watchlist/Catalogでrenumberのdry-runを行う。既存toolの参照/hash/status/collision
preflightとrollbackを再利用し、明示承認でのみapplyする。
不要ZIPは全Artifact（過去/別Item/別Work含む）、Run/status/manifest/別locatorとの参照と
実path/存在/サイズ/hashを検証し削除候補一覧だけを作る。未参照のみで削除しない。
削除は採番と分離し独立承認/バックアップ/復元手順を必須とする。

## 段階checkpoint

- S00: 上記調査・契約を記録（完了）。
- S01a: read-only snapshot/候補/手動メモ＋Unit。
- S01b: bounded site-local probe＋synthetic browser/Unit。
- S01c: GUI/JSON＋Qt integration、affected regression、note同期。
- S01d: 実Catalog read-onlyで起動し実作品の結果を表示。live metadata結果と未検証事項を記録。
- S02: GUI/移行処理とcopy検証を実装。本文未証明を明示した人間の採用判断、永続履歴bindingを採用。
- S03: 採番/不要ZIP候補は未実装。別Stageでのみ開始。

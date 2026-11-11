# Stage 03A — 履歴専用ZIPの分離

**IMPLEMENTED / SYNTHETIC APPLY VERIFIED / PRODUCTION PREVIEW ONLY**（2026-11-11）。
本番ZIPの移動、本番Catalogへのapplyは未実施。

ユーザーの追加依頼による限定拡張。採番修復と不要ZIP削除は引き続き未実装・別操作。
Stage 02のCatalog移行とファイル移動は別のpreview/applyにし、連動して自動実行しない。

## 要求と不変条件

- DBでは履歴Sourceの `acquisition_enabled=0`、非現行の履歴key、既存Item statusを維持する。
  completedだけでもBatch対象外。追加の担当OFFはpending履歴と明示的な退役を表す。
- 既定の履歴先は `output/Books-history/hanayume/<work_key>/artifact-<id>/<元ファイル名>`。
  ZIPの中身・名前・採番は変えず、Artifact.locatorだけを新しい実pathに更新する。
  Item/Source/Target/Run/quota、過去Runのsnapshot、Watchlistは変更しない。
- 同Itemに現行SourceがあるZIP（旧completedを現行IDへ引き継ぐ場合を含む）、
  現行external Itemの旧Artifact coverage参照、他Item/Workと共有するpathは移動しない。
  過去Artifactを含め全参照を調べ、同じ保管Item内で同pathを参照する全Artifactのlocatorを更新する。
- Stage 02適用前にも移行planを使った投影previewを出せるが、そのplanではファイルapplyできない。
  Stage 02適用後のCatalogから改めて実previewを作る。
- 全参照/Work/担当状態、存在・size/SHA-256・ZIP形式・path境界/リンク/移動先衝突を検証。
  不明・壊れたZIPはblockする。新規preview JSONは上書きせず保存する。
- 通常のDiscovery/Batch/Grant-only/採番処理は変更しない。チケット・実サイトアクセスなし。

## 適用と復旧

Catalog job lock、snapshot token再検証、verified backup、BEGIN IMMEDIATE内の再検証を行う。
同じfilesystem内でhardlinkの排他的作成＋元path解除により移動し、既存移動先を上書きしない。
hardlink不可のfilesystem/ネットワーク越し移動は拒否し、copy/deleteへ暗黙fallbackしない。
移動の前にbackup隣接のmanifestとCatalog隣接のrecovery journalを記録する。
ファイル移動後に全対象Artifact locatorをCAS更新する。
通常例外ではDB rollbackとfile復元を確認し、完了した場合だけ復旧済みと報告する。
DB commitの成否や復元結果が不明ならjournalを残して `RECOVERY_REQUIRED` とし、以後のapplyを止める。
process強制終了/電源断はDBとfilesystemの単一atomic commitではないため、journalとbackupを用いた
明示復旧が必要。自動再実行で解決済みと扱わない。正常適用済みplanの再applyはhash/DB/path検証後no-op。

### 強制終了時の明示復旧

1. 同Catalogを扱うworkerを停止し、journal/backup/manifestを保管する。以後のapplyはjournal検出で停止する。
2. manifestの全Artifact IDについて、DBのlocatorが全て旧pathか全て新pathかを読み取り専用で確認する。
   各ZIPの存在、size/SHA、旧/新path両方が存在する場合は同一fileかも確認する。
3. DBが全て旧pathなら、ZIPを旧pathへ復元する。旧pathが既存なら上書きしない。
   両pathが同一hardlinkの場合だけ、検証後に作成途中の新linkを解除できる。
4. DBが全て新pathで、新pathの全ZIPが検証済みなら移動は完了している。manifest完了状態を記録し、
   journalを解除する。別ファイルの旧pathが残っていても暗黙削除しない。
5. DBが混在、不明、hash不一致なら自動復旧しない。backupを丸ごと戻す前に、他の更新が入っていないかを
   確認し、ZIP配置とDB参照を個別に修復する。現時点ではこの明示復旧を自動化するGUI/helperはない。

過去のcrawl-status/packaging manifestは取得時snapshotとして変更しない。これらが現行出力名と衝突する場合の
整理はStage 03B以降の採番/衝突対処に残す。Artifact locatorが現在のファイル参照authorityとなる。

## 受け入れとテスト

現役/alias共有/coverage参照の除外、履歴ZIP移動、全Artifact locator更新、過去Run/quota/ZIP bytes保持、
誤Work/古いtoken/外部path/リンク/破損ZIP/衝突、途中失敗と復元、復元失敗journal、再applyをUnitで確認。
Qtで投影previewのapply禁止、実preview→明示apply、新規JSON保存を合成データで確認する。
実CatalogではStage 02後の隔離copyに対してread-only previewだけを行い、本番ZIPは動かさない。

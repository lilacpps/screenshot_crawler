# Phase 3 — 巻ZIP統合と完成品公開
開始: Phase 2の手動plan。Implementerがwriter、独立Reviewer/Testerが安全性・成果物を確認。
- planで各話ZIPを一回だけ採用。連続区間は既存巻をまたがない。巻番号衝突・未割当・採用入力欠損/破損・他Workとの共有/所有不明は停止。未取得範囲の明示除外はmanifestへ。実巻番号・命名・rootは親契約通り。
- ZIPは既存packagingのmember順序を確認し、順序が証明できない場合は停止。安全な相対member名、重複名、暗号化、symlink、予期しないmember、過大サイズ等をpreflight。画像をstreamで読み、通し番号の拡張子を維持してZIPへ。画像の再エンコード禁止。元ZIPを展開して任意pathに書かない。未知metadataを黙って捨てず、既存規約の既知非画像memberのみ理由付きで除外可能。
- 既存巻はbyte-for-byte copy。入力/出力rootの重複、Windows casefold/予約名/path長、symlink/reparse、同名別Work、容量不足を検査。別filesystem入力はコピー可、stageは出力と同一filesystem。
- apply直前にCatalog job lock、deletion admission/gate、既存job lifecycleの競合対策を確認。ロック中にplanのWork/source/Artifact/path identityと入力hashを再検証し、出力中の変化も検知。別プロセスの同じ出力を排他。GUI内のbusyだけに依存しない。
- 全巻を一時作品dirへ生成。CRC、画像数・順序・SHA-256、既存巻の全体SHA-256を検証後、作品dir単位で公開。manifestと公開の間のクラッシュを検出できる小さなjournal/operation stateを設ける。新規出力に競合が発生すれば停止。旧完成品の更新は明示承認・所有確認・旧品退避→新品公開→記録確定。失敗時復旧、復旧待ちを明示。見知らぬフォルダを削除/置換しない。再実行は同じplanかつ出力hash一致なら生成済み、不一致なら明示再生成。旧品退避の永久削除は対象外。
- GUIで進捗、出力先、結果、エラー、キャンセルを表示。終了確定/archivedにはしない。
受入/テスト: 人工ZIPで混在拡張子・ページ順・全hash、巻のみ/混在、欠損/壊れたCRC/危険member/重複、Windows名衝突、容量/書込エラー、キャンセル、publish/manifest失敗、強制終了後復旧、既存品維持、再実行、古いplan/並行job/他Work無変更。入力ZIP/status/DB/YAMLのbefore-afterを比較。手動GUI E2E成功、独立レビュー後Phase 4へ。実データ変更なし。

# Stage 02 実行契約（実装・隔離コピー検証済み、ユーザー適用後のDB状態確認済み）

ユーザーの2026-11-11の確認済み方針を採用する。旧completed→新pendingは旧を再利用、
新旧completedは新を採用、分割/統合も旧の全範囲を再利用できれば旧を利用できる。
不確かな場合は新側を再取得してよい。対応無しはGUIで明示して現行対象から外す。
物理的なZIP/履歴削除はStage 03の別操作であり、このStageでは行わない。

## 判断と表示

- GUIは「適用前（旧 / 新）」と「適用後（予定）の現行話」を分け、現行Item/Source IDと状態、
  残す/物理削除するDB行を表示する。選択行の説明には正確なItem/Source/Target ID、新URL、
  旧ID保管alias、採用ZIP、Run/Artifact保持を明示する。新規preview JSONにも `outcomes` /
  `after_summary` を保存する。aliasの新IDはtransaction時採番のため事前確約しない。
  方針変更・失敗時は古い結果を消して再previewを要求する。これは表示のみでapply処理は変えない。
- 報告JSONの候補を人間が採用することと、本文同一性の技術的証明を区別する。
  旧データの利用には「この対応を採用」の一括確認を必要とする。本文証明は追加しない。
- 自動方針は、新側の全件がcompletedなら新を維持、旧全件completed＋検証可能ZIPがあり
  新側が全件pendingなら旧を利用、それ以外は新側を維持/不足分再取得。
- 1対1で旧Itemに兄弟Sourceがなく、新donorがpristineなら既存SourceIdentityMaintenanceを
  同じ外側transaction内で利用する。旧Item/Source IDと履歴を保持し、履歴のないdonorだけ除去。
  現行Sourceの外部状態/表示位置は新側から採用、旧quota履歴は保持する。
- donorに履歴/手動編集がある場合は無理なmergeをしない。自動方針では新側へ回す。
  明示的な旧採用では、分割/統合と同様に旧Artifactの参照を現在Itemのnoteへ記録し、
  現在Itemをexternal（このItemのcapture以外の既存取得でカバー）とする。completedは作らない。
  全範囲分の旧取得がない場合は旧採用を拒否する。ZIPの切断/結合、Run再帰属はしない。
- 新pendingは通常Batchへ残す。明示「再取得」は新Itemをpendingに戻すが過去Run/Artifactは保持。
- 新旧pendingで新側を採用する場合、旧Item/Source/Targetに保護対象がなければ旧側を削除する。
  CrawlRun（失敗分も含む）/Artifact/利用・grant/owned権利、手動title/note、同Itemの別Source、
  個別Target設定があれば保管し、GUIへ理由を出す。複数旧の場合は個々に判定する。
  削除IDはplan/tokenと適用後previewに含め、新Itemへ監査markerを残す。操作IDは方針version 2を含む。
  alias採番後に履歴のない旧Target→Source→Itemを削除し、当該Work/siteのlisting証拠を無効化する。
  backup・事前/transaction内再検証・rollbackは既存と同じ。旧completed・ZIP・取得履歴は削除しない。
- 未対応の旧Sourceは暗黙削除せず保留でapplyを止める。GUIで対応、保留解除、履歴保管を指定。
  新側だけは新規取得候補（取得済みならそのまま）。他作品/site/keyの対応は拒否する。

## 永続的な履歴保管（schema v7の既存責務を利用）

旧取得の1対1継承では旧Item/Source IDを現行に維持し、履歴/編集のない新donorのItem/Source/Targetだけを
物理削除する。旧episode IDには同Itemの保管aliasを追加する。
それ以外の旧Sourceは削除せず、取得担当をOFFにし、Discovery keyを修復専用の非現行履歴bindingへ移す。
ただし上記の保護対象のない旧pendingは削除し、保管aliasを作らない。現行の新IDは維持する。
現行listingのFullを繰り返しても新pendingを重複作成しない。削除した旧IDそのものが再公開された場合は、
その旧IDを通常Discoveryが新規pendingとして登録できる（取得済みIDの履歴予約とは扱いが異なる）。
元のkey/URL/Source/Item/全履歴と操作IDは移行プレビュー・backup・Item note監査に残す。
履歴bindingは同じtransactionのacquisition_scope_sync.configuration_jsonへ非現行bindingとして
明示登録する。これは過去のsite listingの証明ではなく、maintenanceが作成した保管用binding。
既存ScopeReconcilerの「削除されたkeyの履歴Source」規則で担当OFFを維持する。
Watchlistを編集せず、schema/Core/Discovery/Batchにサイト固有分岐を追加しない。

Source identity変更で旧external_idが空く場合は、同旧Itemに履歴用alias Source/Targetを新設して
旧identityを予約する（quota timestampを複製しない）。旧IDが再登場してもpendingを自動新規作成しない。
現行listingのFullは通常成功し、履歴Sourceを再有効化しない。サイトが履歴IDを再度現行listingへ
戻した場合は既存のkey所有権guardでfail-closed停止し、改めて人間が対応を判断する。

旧IDを含むscope/segment境界・除外設定はこのStageで暗黙置換しない。該当する計画をblockする。
全Workの他サイト/key・手動title/note・チケット履歴は維持する。旧noteの本文は残したまま監査追記。
採番の整備と実ファイル変更はStage 03で扱う。

## 読込・dry-run・apply

1. JSONはサイズ上限、version、型、Work/Source/Item/Target/全履歴binding、所属、重複を検証する。
   同Workのsnapshotが変わっていれば再解析を要求する。無関係なWorkだけの更新は許容するが、
   apply tokenはプレビュー時の現Catalog全体とWatchlist revisionに結び付ける。
2. GUIでgroupごとに「自動方針/旧を利用/新を利用/新を再取得/保留/履歴保管」を変更できる。
   旧を利用しない一括方針も用意する。変更ごとにプレビューを再生成する。
3. 再利用ZIPのfilesystem/存在/サイズ/SHA-256/ZIP形式、成功Runとの対応をread-only検証。
   最新Artifactが使えない場合に古いZIPを暗黙代用しない。同Itemの旧Source alias群は
   取得単位を一重に扱い、最新Artifactの成功Runが採用した旧群に属することを確認する。
   new completedの欠落ZIPも警告し、プレビューで再取得を提案する。実ファイルは一切変更しない。
4. applyはCatalog job lockとWatchlist lockを保持し、最新プレビュー/tokenを再検証する。
   verified standalone Catalog backupを新規作成し、BEGIN IMMEDIATE内で再検証して全件単一transaction。
   Watchlistは書き込まないため跨ファイルtransactionは不要。
5. 履歴binding、identity変更、external/pending指定、監査note、scope stale化を同時commit。
   FK検証とZIP/Watchlistの最終再確認が失敗すれば全DB変更をrollbackする。backupは残す。
6. 操作IDは報告digest・承認方針・group選択に結び付ける。監査markerも同transactionで記録し、
   同じplanの再applyはno-op。markerの部分的存在は不整合として拒否する。
7. 運用Catalogでは今回dry-runまで。実applyの承認は具体的なプレビュー/backup方針の提示後に取る。

## 受け入れテスト

reportの偽造/破損/別Work/key/重複・古いbinding、正常1対1/両側completed/分割/統合/兄弟Source、
donor履歴、手動title/note、ZIP欠落/変化/誤hash、scope/order/segments、未対応/新側のみ、
BEGIN後の故障rollback、競合、backup失敗、冪等性、全Run/Artifact/quota不変、
Full再実行→ScopeReconciler→Batch planの重複なしを合成Catalogで検証する。
実Catalogコピーでもdry-run/applyとBatch planだけを確認し、site通信/Batch captureは行わない。

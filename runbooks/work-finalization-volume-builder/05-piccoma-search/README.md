# Phase 5 — Piccoma作品URL自動探索
開始: Phase 0の検索観測、Phase 4 reader。Implementerがsearch、Reviewerが誤同定・副作用を監査。
- 優先順: 保存済み参照URL（Work/版を再照合）、同一work_keyの登録済みPiccoma URL、作品名検索、保守的に正規化した作品名の再検索、GUI候補選択/URL入力、完全手動。検索なしで巻のみコピー可。
- 作品名/著者（得られる場合）/版/出版社等を確認。通常版と完全版/分冊/カラー/別作品は混ぜない。完全一致で一意かつ矛盾なしの候補を採用可、著者や版の証拠不足はGUI選択。曖昧一致の自動決定禁止。検索候補はURL/title/author/版/根拠を表示。
- 自動探索のURLはvolume mapping JSONへ保存、Watchlistに登録しない。no result、ambiguous、通信障害を分ける。再検索/refreshで手動確定情報を上書きしない。通常サイト内検索のみ、bounded retry、チケット/閲覧操作なし。
受入/テスト: cache、既存URL、exact、複数候補、版/作者不一致、no result、通信失敗、GUI手動fallback、無副作用。Phase 0の実サイトで検索結果を確認し、BLOCKING-0でPhase 6へ。

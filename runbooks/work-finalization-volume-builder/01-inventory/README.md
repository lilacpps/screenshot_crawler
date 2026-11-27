# Phase 1 — 入力一覧・共通モデル
開始: Phase 0 checkpoint（BLOCKED可）。Implementerが共通service、Reviewerが所有/順序を監査。
- Catalog/Watchlistの読み取りsnapshotをwork_keyで解決。Catalogの成功Runと現役filesystem Artifactを既存renumber/auditの選定規則と整合させる。source scope、external coverage、共有path、履歴、同名別Work、未取得、欠損を扱う。external coverageの実ファイル参照が証明できなければ手動確認/停止、黙って脱落させない。
- archive_order/segmentsおよび既存採番計画からwork-wide順序を決める。実ZIP prefixと照合し、異常はrenumberへ誘導。ZIP名だけでItemを決めない。入力行に実巻番号/話名/ID/位置/状態/パス/ページ数（確認済みか否か）を持つ。
- 種別 episode/volume/unknown を明示。既存巻の実番号はorder_key/label等の確実な根拠から取得し不明は手動。巻のみはPiccoma不要。
- 参照DTO、境界DTO、入力snapshot、plan DTOを定義。境界はIDと実巻番号、手動/自動/未解決を保持。DB schema変更なし。
受入/テスト: 単一/複数site、混在、巻のみ、同名別Work、担当外、履歴、external、欠損/複数Artifact、未知kind/位置、scope変更、採番ずれ。未解決を含むplanはapply不可。入力/DB/YAML変更なし。targeted testsと独立review完了でPhase 2へ。

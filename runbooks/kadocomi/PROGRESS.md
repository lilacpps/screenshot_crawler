# カドコミ Free-Only Adapter — Progress / evidence ledger

Status: **PLANNED** (2026-10-12)。現時点で実装・実サイトProbe・E2Eは未実施。
この文書は実装開始時からLeadが更新する。**実行したかのような成功記録を作らない。**

## Stage checkpoints

| Stage | 状態 | 根拠/残課題 |
| --- | --- | --- |
| P0 Site/Original research | NOT STARTED | 種URLのユーザー観察のみ。HTTP/DOM/Network/Viewerは要独立Probe |
| P1 Discovery | NOT STARTED | list展開、free分類、free_until、full/incremental、履歴を実装 |
| P1.5 Position | NOT STARTED | 履歴位置との衝突防止を最低条件。高度な再構成はbest-effort |
| P2 Viewer/Capture | NOT STARTED | 元画像候補・ピクセル帰属・ENDを証拠で確定 |
| P3 Free-only Batch | NOT STARTED | directだけを既存Planner/Executor/ZIPに統合 |
| P4 Independent E2E | NOT STARTED | fresh Catalog実サイト、独立画像監査、Reviewer BLOCKING=0 |

## Known observations (user-provided, NOT independently verified)

- 作品URL: https://comic-walker.com/detail/KC_004915_S?episodeType=first
- 「全XX話を表示」で話一覧を展開。
- 公開中の話に無料バッジがない場合があり、配信期限がある場合もある。
- 終了した話は「第XX話から第XX話は配信が終了しました」等で表現。
- 単行本や他の導線も混じりうる。
- 配信終了/再公開に伴い、途中話のID・位置・公開状態が変わる可能性がある。

上記の正確なDOM、ネットワーク、総話数、原画像形式、free判定はP0未確認。
現行コード・仕様からの既知事項は `README.md` と各P文書に分離して記載。

## Checkpoint template (phase完了時に追記)

```text
Phase:
Branch / commit / date:
Scope and evidence:
  OBSERVED:
  INFERRED:
  UNKNOWN / NOT VERIFIED:
Changed paths:
Test results (commands, PASS/FAIL/SKIP):
Live browser / source image audit:
Reviewer findings (BLOCKING/NON-BLOCKING/VERIFIED):
Decisions and tradeoffs:
Remaining risks / next step:
```

Local実サイト証拠は`work/kadocomi/`等の隔離・gitignored領域へ。
cookie、session token、署名付きURL、実画像そのもの、機密metadataはcommitしない。

# ヤンマガWeb free-only Adapter — evidence / progress ledger

**Date:** 2026-10-20（JST）
**Status:** PLANNED / CODE NOT STARTED / LIVE CDP NOT VERIFIED
**Branch:** `feat/yanmaga-adapter`
**Base:** `main` at `ddfcee7bf844a6215d51a8dbc043f589a92fa0ca`
**Site key:** `yanmaga`
**Scope:** 赤字の無条件公開「無料」だけ。初回無料・黄色の無料/チケット・ポイント・認証Grantは取得対象外。

## Phase gates

| Phase | State | Required evidence |
| --- | --- | --- |
| 01 Site Probe | NOT STARTED | browser/APIのwork・episode ID、全件list、free badge、Reader/画像/END、閲覧上限 |
| 02 Discovery | NOT STARTED | full/incremental・Catalog ID/順序・free/unknown更新、tests、review |
| 03 Viewer/Capture | NOT STARTED | 同一episodeのfree preflight・本文全頁・positive END・fallback、tests、review |
| 04 Free Batch | NOT STARTED | `direct`だけのPolicy・CLI/ZIP/Completed、否定ケース、tests、review |
| 05 E2E | NOT STARTED | 隔離標準CLI・Manifest/ZIP/Artifact監査・再Discovery、Reviewer BLOCKING 0 |

## 2026-10-20: 初期情報と未検証事項

**OBSERVED from public website/search rendering（ブラウザDOM/APIの実地Probeではない）:**
- https://yanmaga.jp/comics/MADE_IN_YAMATO の公開結果に「70 無料」と「初回無料」が話単位で混在し、「もっと見る」と「無料は1日で読める数に限りがあります。」が掲載。無料とポイント数字は同じ行に存在しうる。
- https://support.yanmaga.jp/hc/ja/articles/360050176114-利用に会員登録は必須ですか は無料連載マンガが会員登録なしで読めると案内。
- https://yanmaga.jp/columns/articles/7367 （2026-05-29）は初回無料が会員登録特典であると説明。

**UNKNOWN（Phase 01で正の証拠が必要）:**
- 赤字/黄色無料・初回無料の安定したDOM属性やsite-native分類・複数バッジ併記の判定。
- 「無料は1日で読める数に限り」が無条件赤字無料に適用されるか、個別episodeの非消費アクセスゲート。
- 作品slug / `?reading=...` / `/comics/<slug>/<id>` のID/URL/redirect/canonicalの対応。
- 全件一覧のAPI/展開/pagination、特殊回の存在とglobal display position確定方法。
- Reader初期位置、本文頁、見開き、広告/extra、END/next transition、画像native MIME・実寸・source attribution。
- live CDP・実サイト正常CLIを実施できるか、現在の公開freeサンプル。

**NOT DONE:** Branch planning docs only. サイトAdapter/Policy/CLI/tests/noteは未変更。CDP未接続、ticket/point消費なし、実サイトE2Eなし、pytest/ruff実行なし。`note/`は現行実装スナップショットなので計画追加だけでは改変せず、実装時にサイトnoteを新設する。

## Update instructions

各Phase終了時に、観測・推測・未知、ファイル変更、対象URL（認証情報を含めない）、テストの実数/skips/未実行理由、Review BLOCKING/NON-BLOCKING、次のGateを記載する。障害を隠してPASSにしない。Viewer画像、Cookie、セッション、署名URL、raw HTML/ネットワーク本文はGitへ保存しない。

# Young Animal Web Adapter — Progress

Date: 2026-10-11
Branch: `feat/younganimal-adapter`
Base: `main` @ `43d9218`
Status: **PLANNED — runbook created, production implementation NOT STARTED**

## Confirmed user preferences
- `younganimal` は花とゆめ＋と別サイト。
- 実装対象: **「無料」「待つと無料」**。チケットは将来。
- 両サイトのIDは共通、ログインは別。セッション・権利の共有は未実証。
- **完全に独立したsite adapterの実装を許容**。共通化の義務なし。
- Hanayumeの初期状態、Catalog直接Viewer入場、native source capture/WebPを積極的に参考にする。

## Research handoff
前回Probeは無料token候補2作品、Viewer初期表示1話、表示Canvas925x1329。
全件Discovery、厳密なbadgeと権利、待つと無料の状態、seek/END、JPEG/native pixelsは
未検証。2話目のgotoは30秒timeout、cleanupも中断した。
[Research evidence](https://github.com/lilacpps/screenshot_crawler/blob/research/younganimal-comici-compat/runbooks/younganimal-compat/EVIDENCE.md)。
最新mainのHanayume R8/R9/R10を別途基準にする。

## Phase status

| Phase | Status | Minimum proof before acceptance |
| --- | --- | --- |
| 01 Site Probe | NOT STARTED | 正確な無料badge、全件listing、画像/初期状態/待機の契約 |
| 02 Discovery | NOT STARTED | complete full/incremental/bounded＋分類とCatalog保全 |
| 03 Viewer/Capture | NOT STARTED | 継続ページ/END、original/native/Canvas帰属と画質 |
| 04 Free direct Batch | NOT STARTED | Catalog→1回Viewer→ZIP/END/complete |
| 05 Wait-free | NOT STARTED | 未開始/待機中/readyの正当なstate・非消費/限定操作 |
| 06 Independent E2E | NOT STARTED | 画像・権利・ZIP・Catalog/回帰の独立監査 |

## Checkpoint contract
各Phase後、以下を追記:
- Date, commit, changed paths, design decision:
- OBSERVED / INFERRED / UNKNOWN:
- Access states, click/consumption and source identity:
- Native JPEG/DCT/source canvas/rendered fallback evidence:
- Unit/Integration/live tests, pass/fail/skip/reasons:
- Reviewer BLOCKING/NON-BLOCKING/VERIFIED:
- Tester PASS/FAIL/NOT VERIFIED:
- Other-site regression and docs/note status:
- Next action, human decision needed (max 3):

重要: Free E2E成功後も`待つと無料`を調査・実装する。待機の実例不足や権利操作の
ブロッカーがあれば部分完成を正確に報告して分離。無実証の大きな共通化はしない。

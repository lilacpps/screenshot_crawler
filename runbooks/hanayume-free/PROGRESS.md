# 花とゆめ＋ Adapter — Progress / Evidence log

Updated: 2026-10-10 (plan only)
Branch: feat/hanayume-adapter
Implementation: **NOT STARTED**
Live site Probe: **NOT VERIFIED**
Reference seed: https://hanayume.com/episodes/8c6f15923caa0

| Phase | Status | Evidence / pending gate |
| --- | --- | --- |
| 01 Site Probe | NOT STARTED | full listing, free labels, ID, viewer/image/ENDを未観測 |
| 02 Discovery | NOT STARTED | full/incremental/bounded + 「無料」「今なら無料」分類を未実装 |
| 03 Viewer/Capture | NOT STARTED | source-original/JPEG DCT/source-derived/fallback未検証 |
| 04 Policy/Batch | NOT STARTED | direct-only policy/標準Batch未実装 |
| 05 Independent E2E | NOT STARTED | 2〜3話の実サイトZIP/manifest/Catalog監査未実施 |

## Scope / decisions confirmed by user
- Phase 1 target: **「無料」および「今なら無料」両表示の話をDiscoveryし、Batch Runで取り込む**。
- **配信期限は初期段階の進行上の制約としない**。ただしBatch入場時にlive無料状態を確認し、
  無料でなくなったものは取得しない。
- 原画像バイト列の保存を第一希望、スクランブルJPEGなら無劣化係数復元を検証。
  不能時は正しいsource-derived pixelsをlossless WebPなどで保存。
- 他サイトの実装方式を参考にするが、花とゆめ＋固有の事実はProbeで確定する。

## Unknowns / research questions
1. 作品全件の終了をどのDOM/レスポンスsignalで証明できるか。話数範囲expand/もっと見るの優劣。
2. 「今なら無料」と「無料」の正確なscope、矛盾表示、会員要件、非消費なViewer entry。
3. 安定作品/話IDとサイト間重複、作品全体の話順。
4. Viewerがrenderする画像のMIME/スクランブル/タイル幾何、DCT feasibility、END/復帰挙動。
5. 同一作品で両無料状態と2〜3話のlive exampleを用意できるか。

## Checkpoint template (append after each phase)
### Phase XX — YYYY-MM-DD / commit
- Scope & diff:
- OBSERVED facts (URLs stripped of signed query; no copyrighted body):
- INFERRED hypotheses:
- UNKNOWN/BLOCKED:
- Unit / browser integration / live / selected regression (pass, fail, skips):
- Reviewer BLOCKING / NON-BLOCKING / VERIFIED:
- Tester PASS / FAIL / NOT VERIFIED:
- Capture fidelity/provenance and fallback:
- User decisions needed (at most 3) / next action:

Do not mark a phase PASS without its required observations/tests/reviewer gate.


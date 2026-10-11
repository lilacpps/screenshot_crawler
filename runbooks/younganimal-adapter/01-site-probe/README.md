# Phase 01 — Evidence-first bounded site Probe

Status: **VERIFIED — Reviewer PASS / BLOCKING 0**。
Next: Continue [Discovery](../02-discovery/README.md) and
[Viewer Capture](../03-viewer-capture/README.md); bounded follow-up probes belong to those phases.

## Goal
前回の互換性研究が未確認で終わった重要情報を、**実装を進められる最小限**だけ再Probeする。
研究単独で終了しない。観測済み結果からすぐ実装に進める。

## Known / Unknown
- 追加Probeで確認: 対象episode `/episodes/55889b8a851cb` はwork
  `/series/aee4fa742b0fe` の行にあり、row内の
  `span.series-eplist-item-access-text.mode-free` がexact `無料`。
  同じ初期一覧にはexact `今なら無料` もあるが、待機状態とは未確認。
- Viewer初期状態は `#comici-viewer.mode-spread.mode-first-page.mode-top-pr-page`、
  `#xCVSeekBar` value 21 / min 1 / max 21 / step 2、22 physical wrappers。
  durable probe reportはvalue 11のmiddle candidateまで。先行実行のvalue 1 / `mode-last-page`
  はconsole summaryだけに残り、現在のprobe artifactには保存されていないため、終端は未確認扱い。
- 未確認: ログイン正例/匿名正例、全件一覧・loaderの展開、各body slot identity、
  last bodyと通常END遷移、`待つと無料`の正確な対象・待機状態、
  original JPEGの本文帰属、source/canvas pixel equality。
- 2話目の`domcontentloaded`が30秒timeout。原因は不明。cleanupも中断した。
  429/WAF・サイト不具合と決めつけない。
- Hanayumeの現行mainはR8/R9/R10まであり、旧research branchと異なる。
- 初期一覧は31 range links (`1-30`〜`901-925`) と`もっと見る`を持つが、
  DOMには10 episode rowsのみ。全件列挙はPhase 02で続ける。
- Probe結果・詳細は[PROGRESS.md](../PROGRESS.md#phase-01-checkpoint--bounded-live-probe-2026-10-11)。

## Steps / bounded observations

1. 現行Hanayumeの初期状態（空白1枚、物理wrapper数の差、first-canvas quiet wait）、
   Catalogからのdirect entry、native captureのsource/target proofをコードとテストで棚卸し。
2. 既存shared Chrome/CDPで各siteのsessionが独立していることを確認。
   Younganimalについて、site内部のログイン正例・匿名正例を得られないなら
   UNKNOWNと記録（ID共通だからログインと推測しない）。
3. ヤングアニマルの作品一覧で**対象行の正確なbadge文字列とDOM scope**を記録。
   まず無料話が存在する1作品、可能なら2作品。全件取得手段が範囲展開か
   「もっと見る」か、完全終了signalと全体順序を確認。
   前回候補`/series/8f24a114d125e` / `/episodes/dfb216e571e81`、
   `/series/295656ade266b` / `/episodes/d6713bdfba7b5`は**現在無料という保証なし**。
4. 権利消費のない正規の無料話を最初/中間/終端で観測。
   Viewer/counter/seek/DOM wrapper/初期空白/広告/見開き/ENDを記録。
   待機・チケット・課金ボタンを押さない。
5. Networkの元JPEGなどと、画面への描画元を識別する。
   MIME、sample count、元寸法、スクランブルmap/tile geometry、DCT MCU適合性、
   Canvas/source→target draw chain、表示RGBA比較可否を限定Probeで調べる。
   元JPEG同定が無理なら、Hanayumeの`drawImage`元Canvas取得方式が成立するか検討。
6. 「待つと無料」の実対象を探し、**押さずに確認できる**badge・待機CTA・
   待機中・解放済み画面のpositive signalを採集。
   見つからない場合は別作品から探し、進捗へ未確認と追加Probe対象を残す。
7. Reviewerがアクセス安全性、ID/作品scope、描画proofの不足、
   調査終了条件を確認。合格した範囲からPhase 02へ直進する。

## Constraints
- 1 operator、bounded navigation/retries/cleanup。前回のcleanup timeoutを繰り返さない
  （例外/キャンセル時でも所有Pageだけcloseする明示的な有限処理）。
- 機密URL query/cookie/account、ページ画像は無加工でtracked fileに保存しない。
- 通常Catalog/Watchlist、正常なChrome sessionを変更しない。
- 403/429/Challenge/CAPTCHA時は既存AccessGuardの規則で停止。
- 調査段階では権利取得、タイマー開始、待機開始、チケット/購入操作をしない。

## Exit gate
- 個々の実装判断（listing identity、free判定、開始ページ、capture方式）に足る
  OBSERVED evidenceと未確認点がPROGRESSに記録され、Reviewerに確認された。
- 全件一覧やViewer終端がこの段階で揃わなくても、
  その領域のProbeをPhase 02/03で続ける。**単なる調査報告書で作業を終えない**。
- 実サイト自体が利用不能なら外部blockerの理由と試行範囲を明示し、
  無根拠の本番Adapterを作らない。

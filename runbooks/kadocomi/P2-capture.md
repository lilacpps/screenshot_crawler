# P2 — Viewer、原本優先の画像取得、本文完全性

Status: The original episode 4.1, first-episode 38-slot, and Episode 79
native capture contracts passed their bounded live, local, and independent
gates. The direct-entry follow-up is implemented and its anonymous live
Episode 79 Runner probe passed with one episode document navigation, 20
native WebP pages, and explicit END. The direct-entry Adapter/test review
passed; prior P4 CLI/ZIP results predate this navigation change. See
[PROGRESS](PROGRESS.md) for the exact current test and live evidence.
**目的**: 無条件無料話を先頭から全本文ページ、正しい読書順で取り、終端を確実に検証する。

## 変更範囲と優先順位

基本 `src/screenshot_crawler/site_adapters/kadocomi/adapter.py`、
証明が必要な場合だけ`native_capture.py`等のsite-local helper、
テスト/`README.md`/`note/`。共有Coreは具体的blockerが無ければ変更禁止。

`docs/CAPTURE_STRATEGY.md`に従う:
1. **Original bytes**: そのページの元JPEG/PNG/WebPが完全に一意に識別できれば
   同じ形式/元のbyte列のまま保存（JPEGへ変換したりWebPへ再圧縮しない）。
2. **Source-native pixels/安全な再構成**: 元bytesを帰属できなくても、
   viewer drawに使われたソースピクセル・座標/分割/合成順を正確に証明できるなら
   本文ピクセルをnative解像度で再構成しlossless WebPを候補にする。
3. **Rendered content canvas**: nativeが不確実でも、完成した本文Canvasが
   有界に安定観測できるなら、その完成pixelをlossless WebPで保存する。
4. **Locator screenshot**: それしかない場合の最終fallback。
   UIや余白が混ざらない安全な範囲を検証。単に動けばよいという理由で選択しない。

どの方式でも、一意なページ帰属・pixel寸法・読書順・非本文排除が必須。
明確な画像ソースを見つけられていないことと、元bytesが復元不能なことを区別する。
native候補が失敗した根拠（source URL/response mapping、境界、clip、tile matrix、
拡大/縮小、alpha、合成、デコーダ差異など）を`PROGRESS.md`/site noteへ残す。
原本探しは十分に行うが、アクセス制御/DRM回避や無制限探索はしない。

## Viewer contract

- `RunConfig.source_url` remains the canonical Catalog episode URL. The
  adapter returns that exact URL for Runner's single initial main-document
  navigation; it does not navigate to the work page, reload, or issue a
  second document navigation.
- P1 Discovery/Catalog and the P3 Policy remain the free/availability
  authority. On the exact episode navigation, the site-local response
  observer requires a final HTTP 200 document response and rejects any
  redirect that changes configured work/episode identity. No additional
  HTTP request is made.
- Initialization waits a bounded time for one visible H1 matching the
  observed `【order】work` format, with `og:title` and `document.title`
  exactly equal to that H1 plus the verified Kadocomi suffix. Missing or
  ambiguous metadata, visible dialogs, and a non-settling reader fail closed.
- The exact work/episode URL and same-page metadata are rechecked for each
  capture. Preserve the verified first slide, native Blob provenance, full
  pixel equality, stable source mapping, slot order, page bounds, and END
  contracts below without fallback to screenshots.
- Page identity, transitions, loading, ads, spreads, terminal DOM, and output
  format remain bounded and fail-closed as described below.
- Capture observers do not encode or hash in the renderer hook and retain
  only bounded Blob references. See the native source evidence in `PROGRESS.md`.

## テスト（単体 → local Browser → live → 独立評価）

1. URL/work/episode mismatch、無料期限切れ、redirect to other episode、
   購入/ログイン/非対応dialogのfail-closed。
2. ページ先頭から進めて、counter・identity・同内容guard・bounded timeout・loading/
   spreadの両側・END/next contentをfixture確認。正常終了に全slotの証拠が必要。
3. RGB/RGBAやalphaを含むsyntheticデータで原本byte保持、
   native再構成/レンダリングとlossless WebP pixel一致、変換不可能時の
   安全なdownward fallback、画像形式とmanifestの整合。
4. 本文後の広告/購入UIを画像として取得しない。
5. 代表的な現在公開中エピソードでE2E: 先頭→最終画像まで全部の内容・順序/解像度を
   独立Testerが比較。可能なら異なるviewer構造でも検証。
6. 既存BookWalker/Comic DAYS/Piccoma等のCore側挙動を変更した場合は
   隣接の実装契約を直接検証し、full suiteの必要性をLeadが判断。

## Gate

- source-native原本調査は「何を調べ、なぜ採用/不採用」まで記録。
- 全本文の完成、ページ帰属、source→output pixel/byte根拠、ENDを確認。
- Reviewer BLOCKING=0。画像品質が不明な場合はfallback/unsupportedを明記。
- 未検証の画面variantを成功扱いしない。成果/ログをPROGRESSへ記録。

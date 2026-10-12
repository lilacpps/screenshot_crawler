# P2 — Viewer、原本優先の画像取得、本文完全性

Status: PASS for the observed episode 4.1 and first-episode 38-slot readers.
The Episode 79 strict trailing-recommendation extension is implemented and its
bounded live all-20-source/END proof and local Runner/Batch tests passed.
Independent code review passed (45 targeted tests, BLOCKING=0), and the normal
CLI Batch run produced a 20-member ZIP. The independent all-20 source/RGBA-to-ZIP
audit also passed. The prior 21/38 CLI, source/ZIP audits and review remain passed
(BLOCKING=0); opaque network-original bytes remain unclaimed. See
[PROGRESS](PROGRESS.md) for current status.
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

- `RunConfig.source_url` はCatalogのcanonicalエピソードURL。
  入口に別URLが必要なら既存の `resolve_initial_navigation_url` 相当のhookを検討し、
  Catalog/Manifestのauthorityを別URLへ置換しない。
- 初期遷移でwork ID/episode IDを再確認し、サイトの正のFREE根拠を
  **freshに**再確認する。既知の期限切れ・購読要求・個人session閲覧や
  gate不明な状態に対しては進入しない。別話に移ったら停止する。
- 初期位置は必ず先頭。既知の再開dialogがあれば要素/文言/操作を正確に証明した
  cancel/firstへの復帰のみ使用。未知のmodalや途中開始は停止。
- page ID/位置/total、前後変化、loading、広告、spread、終端DOM/状態を
  P0で確認し、`CONTENT/LOADING/END/NEXT_CONTENT/UNKNOWN`へ正しくマッピング。
- 見開きの左右欠落/反転、同一画像重複、途中のlazy canvas、白紙と実本文の誤判定、
  PRや単行本導線の混入を避ける。実サイトで検証済みの構造だけをサポート。
- 正しい最後の本文後にのみEND。END判定不能は正常完了にしない。
  先頭・中間・最終ページの実画素を独立監査可能にする。
- 画像取得補助はrendererに干渉しない。draw hookで重いencode/hash、
  全画像の長時間保持をしない。network観測はbounded、fallbackが既存頁移動を妨げない。
- `CaptureResult`のmime/file extension/manifestとの一致を保証。
  WebPのlosslessはbitstreamをdecoded pixel比較し、RGBA時はalpha/色管理の差も確認。
  Canvasで既に低解像度化されている場合は「lossless」でもoriginalの解像度ではない
  と記録。表示サイズから元のpixelを推定しない。

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

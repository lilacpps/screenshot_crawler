# Phase 03 — 無条件無料のReader / Capture / END

**Start:** Phase 01の公開freeとViewer観測、Phase 02のCatalog identityと対象URLを承認済み。調査未実施の画像/Reader実装を他サイトからコピーしない。
**担当:** Leadが許容shapeを定義 → Implementer単独writer → Reviewer → Captureは独立Testerによる検証を推奨。

## Goal / Change boundary

`site_adapters/yanmaga/adapter.py` と`access.py`、証拠に基づく`native_capture.py`（必要な場合のみ）、exports / テストを追加。既存CrawlerRunner、CaptureResult、AccessGuard、Manifest/Packagerを利用。新しいcore protocolや独自CDPは根拠なしに作らない。

## Requirements

1. **target-bound preflight:** `configure_target_identity`でCatalogのwork:episode identityとSource URLをbind（必要に応じて）。`resolve_initial_navigation_url`/`initialize`でReader入場より前に同一work・同一episodeの現在の公開free状態を検証。target local証拠が十分なら不要な全作品再列挙はしないが、作品公開一覧を確認する必要がある場合は**同一作品のread-only listing**だけ許可。別話を順に開いて無料可否を試さない。
2. **fail closed:** preflightで`free`消失、login/token/ticket/初回無料/ポイントの要求、work/episode/route不一致、リダイレクト矛盾、閲覧数制限でのアクセス不可が判明したらReaderを進めない。明確な権利不足は`AccessResourceUnavailableError`としてskip可能にし、状態不明や内部破損を「普通のskip」に隠さない。`auto`/`direct`以外のアクセス戦略は拒否。`auto`もquota fallbackしない。
3. **Reader初期位置:** 既読位置から再開しても本文先頭に安全に戻す。戻れない時はfailure。最初の本文・表紙/空白の扱いは実サイトで確定。カウンタのみを唯一のauthorityとしない。
4. **ページ単位の根拠:** DOMのページID、画像source/canvas、表示寸法、episode context、loading完了、physical wrapperの組合せで本文ページを確定。1頁/RTL見開き・先頭と最終の片側・遷移中のoverlapを考慮。途中の重複・欠落・左右逆順を検出してfail closed。
5. **画像品質:** 同じ表示本文と確実に結びついたnative JPEG/WebP/PNGが得られればバイト列優先。通常描画から合法的に得られるsource-native pixels/正しく検証した再構成を次点とし、Canvas/Locator・最後にscreenshotへfallback。スクランブルや暗号化をアクセス回避目的で解かない。再エンコードが必要なら原則lossless WebP/PNG。本文以外のサムネイル、低解像度タイル、広告を混ぜない。fallback理由と実際の方式をManifest/diagnosticsに示す。
6. **安全な遷移:** Playwrightの正規ページ操作だけで進行。`CONTENT`/`LOADING`/`AD`/`END`/`NEXT_CONTENT`/`UNKNOWN`の既存Core契約を守る。遷移はbounded wait/安定確認を使い、`max_pages`・same-content guard・AccessGuard/pacingを残す。未知のLayoutを都合よく`CONTENT`と見なさない。
7. **終端:** 最後の本文とtail（宣伝、次話リンク、広告など）を分ける。body全頁の観測とpositiveなENDもしくは安全なNEXT_CONTENTを確認する。Next Episodeへ自動進行して別話を保存しない。固定sleepや単なる画像消失で不確かな完了としない。
8. **機密・著作物:** response body/signed URLはbounded scopeで扱い、認証ヘッダ/Cookie/署名クエリはログに残さない。実際の漫画画像・raw DOMをfixtureにcommitしない。読めない頁を別サイトの元画像で補完しない。

## Observed Yanmaga profile and N2 capture result

The accepted implementation is limited to the observed anonymous red-free Chapter 1 reader
layout in `ウサギとカメのゆる山歩`. A complete original page response was not observed: the
first-party viewer draws a shuffled JPEG tile atlas into three canvases, then encodes each
segment as JPEG quality 0.9 before creating the body Blob. The adapter copies opaque sRGB
canvas pixels before that original encoding and binds the copy to a displayed segment only
through a unique exact JPEG-byte/Blob-byte/current-source match. It composes the three strips
in DOM paint order at native offsets 0, 532, and 1064, clips to the first-party logical page
bounds 1125×1600, and writes a single-frame lossless WebP only after exact decoded-pixel
round-trip verification. This is reconstructed pre-JPEG viewer pixels, not original bytes.

The supported nested structure is one `.pt-img` with three absolutely positioned, clipped
segment hosts and one image each. The measured source segments are 1127×536, 1127×536, and
1127×538; the 4-row overlap and final 2-row overrun are handled by the logical page clip, not
by guessing a stack. The outer wrapper permits only observed pure X translation and 0/2 CSS
px right padding; host pseudo paint, altered source, unsupported styles, missing/duplicate
segments, non-opaque output, or proof overflow demote the whole group to rendered locator PNG.
The menu, perimeter ownership, work/episode, sequence, spread, and positive-END guards remain
in force. No access state or navigation behavior is changed.

The live N2 Runner run completed all 36 Chapter 1 pages and positive END with all 36 pages
using native-pixel lossless WebP and no fallback. See `native-capture-research.md` and
`runbooks/yanmaga-free/PROGRESS.md` for the sanitized evidence and current verification gate.
The fresh ordinary Chapter 11 Batch E2E now verifies the current WebP output path: 20 ordered
native VP8L pages reached positive END, the ZIP matched the Manifest and passed CRC, and the
Artifact/Completed state was verified by Tester and Root. Independent reference capture completed all 60 segments for this 20-page Chapter 11 run; Pillow-composited RGBA references exactly match decoded ZIP pixels on all 20 pages. The QA-only observer initialization issue and lock fixture are documented in `../PROGRESS.md`. Detailed hashes and isolation paths are there as well.

### N4 bounded pixel retention

An ordinary Chapter 11 initialization exceeded the previous 96 MiB raw-pixel budget before
the first capture: 41 exact canvas/Blob candidates held 99,185,016 bytes, and the next
1127×536 segment would raise the total above the 100,663,296-byte limit. A separate normal
CLI metrics window found all 60 segment responses for the 20-page Chapter 11 before the
first PNG; their three RGBA source segments per page total 145,157,600 bytes. The 128 MiB
proposal was therefore rejected.

The accepted bounded fix uses a fixed 256 MiB (268,435,456 byte) raw-pixel cap, covering the
known 36-page profile's 261,283,680 bytes (about 249.2 MiB). This limits only retained pixel
arrays; it is neither preallocation nor total JavaScript/Chrome memory. The 192-candidate,
48-pending/async-task, 32 MiB encoded-character, 192-URL, and 1 MiB-per-segment bounds remain.
No compression in hooks, pacing changes, or shared Core changes were introduced.

The synthetic eager-60 regression verifies all candidates are uniquely Blob-bound before the
first page capture, confirms the 145,157,600-byte retention, lossless WebP first page, and
one-page pixel release. The exact-boundary test accepts the final candidate at the cap and
rejects a following candidate before copying pixels. A bounded isolated ordinary CLI run
with `--max-pages 1` measured 21 candidates / 50,805,160 bytes immediately before page 1,
then 43,547,280 bytes after releasing that page; page 1 was a 1125×1600 native WebP. The
command stopped at its one-page bound (exit 1) and is not evidence of END or ZIP success.
Its aggregate observer snapshot does not establish page IDs for all retained candidates.
The N4 material change passed independent review with BLOCKING 0. The fresh single-process
Chapter 11 WebP Batch/ZIP E2E and independent all-20-page RGBA reference equality passed.

## Tests / Review

- Unit: URL / identity / access guard / manual auto vs direct vs rejected quota / current freeからunknown・有料・期限切れへの変化 / 最初の頁・途中・最後 / 枠・タイムアウト。
- Playwright Integration: loading→content、連続頁、見開き、先頭復帰、片側最終、ad/extra、END / NEXT_CONTENT、異話遷移、重複・同一画像、拡大縮小時・画像差替の誤attribution、PNG/WebP/JPEG検証と不成立fallback。
- E2Eへ渡すevidence: 実URLの同一話証明、全body数、画像サイズ/形式、先頭・中・最後、実際に読まれたReaderのEND動作、画像原本を主張できる範囲、unsupported shapes。
- Reviewer: accidental resource click、silent wrong image/episode、欠落・重複、END誤判定、回帰を優先。PoCでは動いたが通常Runnerで落ちるtimingを評価。

**Gate:** 合意した無料Viewer形状についてローカル完走・否定ケースのfail-closed、少なくとも1件の実サイト無料Readerで先頭から最終本文までの観測証拠があり、Reviewer BLOCKING 0。ZIP/Completed最終判定はPhase 04-05。未観測layoutは明記して非対応。

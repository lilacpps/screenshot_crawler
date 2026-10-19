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

## Tests / Review

- Unit: URL / identity / access guard / manual auto vs direct vs rejected quota / current freeからunknown・有料・期限切れへの変化 / 最初の頁・途中・最後 / 枠・タイムアウト。
- Playwright Integration: loading→content、連続頁、見開き、先頭復帰、片側最終、ad/extra、END / NEXT_CONTENT、異話遷移、重複・同一画像、拡大縮小時・画像差替の誤attribution、PNG/WebP/JPEG検証と不成立fallback。
- E2Eへ渡すevidence: 実URLの同一話証明、全body数、画像サイズ/形式、先頭・中・最後、実際に読まれたReaderのEND動作、画像原本を主張できる範囲、unsupported shapes。
- Reviewer: accidental resource click、silent wrong image/episode、欠落・重複、END誤判定、回帰を優先。PoCでは動いたが通常Runnerで落ちるtimingを評価。

**Gate:** 合意した無料Viewer形状についてローカル完走・否定ケースのfail-closed、少なくとも1件の実サイト無料Readerで先頭から最終本文までの観測証拠があり、Reviewer BLOCKING 0。ZIP/Completed最終判定はPhase 04-05。未観測layoutは明記して非対応。

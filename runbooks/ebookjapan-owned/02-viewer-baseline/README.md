# 02 — Owned Viewer baseline / ページ完全性と安全な閲覧

Status: **ONE-WORK D BASELINE VERIFIED / ACCEPTED; LOCAL ENTRY + D CAPTURE/TRAVERSAL ACCEPTED** (2026-11-07 Asia/Tokyo). The manifest-retained Angel 10 CoreRunner run `core-run-angel10-20261107-215910-399914` reached native END after 287 ordered D pages and produced a completed isolated ZIP; audit passed 20 artifact checks and 9 visual samples. The current affected suite passes 115 tests (24 adapter unit + 91 local Chromium, 0 skipped), with independent review passing 37 browser + 4 geometry cases. Earlier page-285 failure and manifest-lost run remain historical. Stage 03 has three bounded Muda 1 metadata-only attempts; the latest recorded a canvas?bitmap?Offscreen epoch and WebP response graph but remained `UNHEALTHY_METADATA_ONLY` because two additional unidentified context-method descriptors mismatched outside the six critical keys; their drawing relevance is unknown. No response body or pixels were read. A/B/C and final source-native policy remain unproven; Stage 03 is incomplete.

## 目的 / 設計

`site_adapters/ebookjapan/adapter.py`（必要なら`access.py`）を実装し、**購入済み対象巻の正規Viewerを安全に開き、全本文とENDを再現できる**ことを検証する。ここではページと描画の正しいbaselineを確立する。D系PNGは研究用baselineであり、Stage 03の原画像研究をスキップした最終形式にしてはならない。

## 対象巻の入場チェック

- `configure_target_identity(external_id, work_key)` でCatalogの対象巻IDと作品を固定。`access_strategy=direct` を支持し、`quota` とresource/grant-onlyを拒否。`auto` は実際のOwned確認済みで安全な場合に限る。
- 入口では最新の**対象巻と同じ作品一覧／巻カードの所有状態**を再確認し、カードの閲覧ボタンだけから正式にViewerへ移る。DOM内の別巻・宣伝・試し読み・購入導線の`読む`は対象にしない。
- Readerの現在URL/DOM/サイト内部IDを、入口に固定した巻IDと再照合。新規タブが出る場合も同じBrowserContextとライフサイクルを使い、無関係な既存タブを閉じない。
- 権利消失・別アカウント・ログアウト・試し読みViewer・有償CTA・不正redirect・カバーのみは`AccessStopError`等で停止。自動ログイン、購入、課金、レンタル等へ進まない。

## Viewer stateと保存契約

1. 正式Viewerの構造をP0観測に基づいて解析。`CONTENT / LOADING / AD / END / NEXT_CONTENT / UNKNOWN`を区別。固定sleepのみでreadinessや終端を確定しない。
2. 前回の読書位置が復元されても、ページ番号・本文ID・描画が安定した**最初の本文**へ巻き戻す。戻せない場合は不完全のまま進めず停止。検証終了時の閲覧位置変更は可能な限り復旧。
3. 見開きならページの位置・右左を解釈し、**表紙1枚・本文右→左**の実読書順を保つ。複数ページを一括表示している場合、全体スクリーンショットを1ページと誤認しない。
4. 1つ前のフレームと描画fingerprint/ページID/ページカウンターを確認してから進める。ページ番号だけ更新して古いcanvas画像が残るtransitionを排除。重複ページ・空白ローディング・広告混入・欠落半ページを保存しない。
5. `get_capture_target(s)` / `capture_page()`で、現在の本文領域を検証したD系baselineを確保する。UI表示全体の撮影は、本文だけを切り出せるproven geometryがない場合には使わない。
6. ENDは本当の最終本文の後に、実観測に基づく根拠が揃ってから判定。次巻の自動開始・購入・おすすめクリックを行わない。`max_pages`とsame-content guardを維持する。
7. RunnerのManifestに対象巻ID/URL/順番が残ることを検査。本文が画面で欠けて見える場合は、読めたところだけを正常ZIPとして確定しない。

## 現在の実装スライス（未完了）

- `EbookJapanAdapter.initialize()` は `direct` のみ受け入れ、`auto` / `quota` とquota resourceを拒否する。
- 同じ正規シリーズ一覧のHTTP 200 main-document witnessと、対象カードのvisible `購入済み` /価格なし状態が3回安定するまでReader操作をしない。購入済みの静的witnessに対し、hydration中の一時price/cartは待機扱いにする。最大8秒で一致しない場合は停止する。
- 実際に押す直前に対象Product A-ID、カード内の読込ボタン、タイトル、購入済み表示を再確認する。購入済みカード内の観測済み一意 `読む` 操作だけを押す。
- Viewerは同一ページの正規 `/viewer/purchased/B.../` routeとカード同一タイトルを確認する。新規タブ・redirect・別タイトルは未対応でfail-closed。既知の読書案内modalは正確な説明文・一意`OK`・form control不在の場合だけ閉じる。
- native counter totalと実slot node総数を照合し、document/route/title/all slot references/orderと同一horizontal RTL spread layout nodeをpinする。既観測のnative range `End` を使って途中位置を1/Nへ戻し、自然なsame-size 3-argument full `drawImage` transferと完全なvisible partが揃うまで有界で待つ。
- Observer failure, metadata error/overflow, slot/layout/title/route drift, and unknown draw overload keep the frame unready. A canvas backing reset is rejected unless a new complete full draw is observed. The first toolbar-center action is allowed only at the observed entry viewport (1906×986) and cover rect (left 282.52, right 953, top 0, bottom 986, width 670.48, height 986, 1 CSS-pixel tolerance); the actual viewport/bounding box/center hit is read again immediately before click. Any other visible-toolbar geometry fails closed before action. Capture hides the toolbar before fitting the owned Page. A fitted cover center at fraction 0.25/0.5 was observed to advance into the spread. CSS-only fit may preserve an unchanged full-draw signature only when all pinned identities/backing dimensions and observer health match and CSS/backing geometry is 1:1; a redraw branch requires increased cumulative successfulDraws, positive current generation and complete ready state. The chosen full signature must remain unchanged over two animation frames. D capture then rejects clipping/off-viewport/transform/opacity/filter/mask/blend and intersecting visible painted DOM elements using bounded inventory, then returns repeated CSS-scale samples atomically. Normal advance binds the observed non-interactive left-edge hit and the last committed paint/geometry to the same fresh DOM sample, then requires the next contiguous frozen slot order. END requires full ordered slot coverage and one of two exact observed, scoped terminal profiles: Angel's dead-end structure/action partition or Mudazumo's `.book-last` shell/cell/action partition. Hidden/offscreen terminal roots alone remain LOADING while the profile activates; visible malformed, modal, unknown, or extra actions fail closed. A hidden native counter remains None; derived cover/spread shape is separate.
- The latest affected suite passes 115 tests (24 adapter unit + 91 local Chromium), 0 skipped; the independent Reviewer passed 37 browser and 4 geometry cases. The neutral CoreRunner flow captures a seven-slot cover plus three continuous spreads through exact END; identical page pixels remain distinct ordered manifest/ZIP entries. Failure cases produce no ZIP or completion status. Tests cover hide-before-fit and rejection of the former order, delayed natural resize drawing, both scoped END profiles, hidden-terminal LOADING transitions, same-sample navigation races, and terminal/action negatives. The Reviewer independently verified that a 10-pixel fresh-bbox drift rejects before click; this is separate probe evidence, not a named suite case. The accepted Angel 10 production baseline reached END after 287 ordered D pages and produced a retained-manifest ZIP, audited with 20 checks and 9 visual samples. The earlier 202212 failure remains historical; the prior IMG offender is unidentified. Stage 03 copied health verifier passed 64 checks and metadata harness passed 17 local self-checks. Three bounded Muda 1 metadata-only attempts occurred; the latest bound a canvas-to-ImageBitmap transfer/Offscreen epoch graph and WebP response graph but remained `UNHEALTHY_METADATA_ONLY` because two additional unidentified context-method descriptors mismatched outside the six critical keys; their drawing relevance is unknown. No response body or pixels were read; A/B/C remain unproven.

## Probe・確認の例

- エンジェル伝説10巻の先頭、普通の単ページ、普通の見開き、中間、最終本文、ENDを順次観測。
- ムダヅモ無き改革1巻でもReader構造の違いがないか確認する（別出版社・レイアウト差があり得る）。
- 横読み/縦読み・見開き/単ページの設定が異なる場合、**実際に観測したモードのみ対応**。可能ならユーザーの既存設定を変えず、安全なモードへ明示切替する。
- ローディングが長い、戻り復帰、途中reader移動、最終ページ直前のリトライで同じ画像を二重保存しないか確認。

## テスト / Exit

- Unit/Browser integration: 別巻への混線、所有権喪失、別URL、遅延表示、途中再開、1/Nに戻らない、描画は遅いがcounter先行、半分だけloadedの見開き、終端手前の広告、最終頁→END、NEXT_CONTENT、長時間/無限reader、bad response。
- 隔離`output/ebookjapan_experiment/phase02/`で少なくとも1巻のbaselineが、本人の正規Viewerと本文ページ順・画像の重複/欠落・ENDを一致させられる。Baselinesは本番Libraryへ移動しない。
- Reviewerは契約違反なしを確認。**原画像の取得方法はStage03で決める**。PNG baselineが完成してもここだけで「完成」としない。

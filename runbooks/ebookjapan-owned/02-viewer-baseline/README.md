# 02 — Owned Viewer baseline / ページ完全性と安全な閲覧

Status: **NOT STARTED**。開始条件: Stage 01 owned対象の巻固有Source ID/URLとP0の閲覧入口が確定済み。

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

## Probe・確認の例

- エンジェル伝説10巻の先頭、普通の単ページ、普通の見開き、中間、最終本文、ENDを順次観測。
- ムダヅモ無き改革1巻でもReader構造の違いがないか確認する（別出版社・レイアウト差があり得る）。
- 横読み/縦読み・見開き/単ページの設定が異なる場合、**実際に観測したモードのみ対応**。可能ならユーザーの既存設定を変えず、安全なモードへ明示切替する。
- ローディングが長い、戻り復帰、途中reader移動、最終ページ直前のリトライで同じ画像を二重保存しないか確認。

## テスト / Exit

- Unit/Browser integration: 別巻への混線、所有権喪失、別URL、遅延表示、途中再開、1/Nに戻らない、描画は遅いがcounter先行、半分だけloadedの見開き、終端手前の広告、最終頁→END、NEXT_CONTENT、長時間/無限reader、bad response。
- 隔離`output/ebookjapan_experiment/phase02/`で少なくとも1巻のbaselineが、本人の正規Viewerと本文ページ順・画像の重複/欠落・ENDを一致させられる。Baselinesは本番Libraryへ移動しない。
- Reviewerは契約違反なしを確認。**原画像の取得方法はStage03で決める**。PNG baselineが完成してもここだけで「完成」としない。

# ebookjapan — 購入済み書籍限定 Site Adapter 実装 Runbook

Status: **PLANNED / NOT IMPLEMENTED**（2026-11-06）。Runbook整備のみ。実サイトの購入済みDOM、Viewer、原画像配信経路は **未検証**。完成・成功を主張しない。

## 目的・完了定義

`screenshot_crawler` に `site=ebookjapan` を追加し、作品一覧URLのWatchlist登録 → **Full Discovery（購入済みのみ）** → Catalog → Batch Plan → Batch Run → 画像取得 → Manifest/ZIP → Item completed までを、既存のGUI/CLIで利用できるようにする。

ユーザー指定の実検証対象（実際の所有状況はユーザー申告。現時点でブラウザ確認は未実施）:

| 作品 / 正規入力URL | 購入済みの期待値 | E2E期待値 |
| --- | --- | --- |
| エンジェル伝説 `https://ebookjapan.yahoo.co.jp/books/all/134336/` | 10巻のみ | Discovery 1件、Batchは10巻のみ |
| ムダヅモ無き改革 `https://ebookjapan.yahoo.co.jp/books/all/115888/` | 全16巻 | Discovery 16件、Batchは1〜16巻を正しい順序で取得 |

`/books/all/<numeric-id>/` は **作品一覧の入力** であり、Sourceごとの安定した購入済み閲覧URLとは限らない。P0で各巻の公式IDと正規閲覧経路を確定し、推測でURLを生成しない。

**原画像優先は必須要件**。後述の証拠ゲートA→B→Cを検証せず、最初の描画PNGが動いたという理由だけで恒久的なDフォールバックを採用しない。A〜Cを試した結果と、不可・未証明の理由を実測付きで残す。原画像の取得可能性を保証するものではない。

## 基本契約（決定済み）

1. 既存の `shared Crawler Chrome / CDP / Playwright Page` を利用。Yahoo! JAPANへのログインはユーザーが通常のUIで行う。認証情報・Cookieを別保存しない。
2. 全巻一覧は **すべて列挙・検証** するが、`DiscoveredRecord` としてCatalogへ発行するのは、その巻固有の明確な「購入済み」証拠があるSourceのみ。Free、試し読み、読み放題、未購入、未知、レンタル、期限付き権限は対象外。自動購入・決済・権利消費なし。
3. 運用は **`full` のみ**。`incremental` は入力された場合に明示的に拒否する（無言でfullへ変更しない）。`discovery_scope`、quota、grant-only、チケット処理は実装しない。既存GUIの選択値は対象サイトで`full`になることを確認する。
4. Sourceの `access_mode=owned`、`available=True`、Batchの `access_strategy=direct`。Policyはowned以外をすべて不適格にする。Batch直前とViewer入口で、同一アカウントの現在の購入済み権限・巻IDを再検証する。Catalogの古い`owned`だけでは入場させない。
5. 各巻の `external_id` は公式の安定したproduct/book ID。`display_position` は **非購入巻も含む公式全巻一覧における oldest=1 の位置**。数字の大きさやURL連番では求めない。巻名・巻番号が取れる場合は`order_key` / `order_label`にも保持する。
6. 同一作品を異なるサイトと組み合わせる場合はユーザーが `work_key` を指定し、各Watchlist keyに `archive_order` を設定する。既存の通し採番・Scope sync・安全なrenumberを使用し、新規サイト側でZIP採番を実装しない。実行後の一括renumberを許容し、ZIPの自動改名・既存データ上書きは禁止。
7. 取得処理は既存Core/Runner・AccessGuard/pacing・max_pages・same-content・Manifest/ZIP・status/Artifactを利用。サイト固有ロジックはAdapter/Policyに限定する。必要性のないDB変更・共通抽象化・独自DSLを作らない。
8. 実サイトアクセスは、通常購入済みの閲覧UIと既存の権利の範囲だけで行う。DRM/アクセス制御の回避、秘密鍵/暗号鍵抽出、認証操作の迂回は実装しない。制限に当たった場合は停止し、限界を報告する。

## 重要な既存コード上の注意点

- `discovery/service.py` はFull完了後、今回観測されなかった既存Sourceを `available=False` とする。**未ログイン／不完全一覧／購入済みバッジ未ロードを0件成功扱いにしない**。最新の全件・全アクセス状態を取得・検証・バッファしてから最初の`yield`を行う。サービス側の逐次upsert中にエラーが起きた場合の部分更新リスクもテスト・診断で明示する。
- `discovery/base.py` の `CompleteListingInventory` は全巻ID/位置と選択集合を記録できる。未購入巻をCatalogのItemとして登録する必要はない。完全な全巻の身元と購入マスクをここに保持する。
- `archive_order.py` は同一`work_key`の全keyに正の`archive_order`が必要。対象となるSourceのみから連番を計算する。10巻しか購入していなければ、それ単独の通し番号は1になり得る（巻数10のメタデータとは独立）。新規購入で順番が変化したら後から既存renumberをdry-run→applyする。
- `cli.py` のViewer / Batch Adapter / Discovery / Policy registry、URL登録・GUIのサイト選択、対応するTests / `note/` を更新する。Scope/取得担当の既存動作を勝手に緩めない。

## ステージとゲート

| 順 | Runbook | Gate |
| --- | --- | --- |
| 00 | [実サイトProbe](00-site-probe/README.md) | 2作品の全巻・購入済み表示・Viewer・画像配信の基礎証拠 |
| 01 | [登録とFull Discovery](01-discovery/README.md) | 実環境で1件/16件、正しいID・位置、未購入0件登録、ログアウトfail-closed |
| 02 | [Viewer baseline](02-viewer-baseline/README.md) | 対象1冊の先頭→本文→ENDを、ページ欠損なく安全に検証 |
| 03 | [原画像・source-native取得研究と実装](03-source-native-capture/README.md) | **A/B/Cを実測で評価**、適用可能な最高忠実度経路を実装。非採用理由の台帳必須 |
| 04 | [Owned-only Batch/GUI統合](04-batch-integration/README.md) | `owned/direct`のみ、通常Batch/ZIP/状態更新、他サイト回帰なし |
| 05 | [E2E・独立評価](05-e2e/README.md) | 2作品、再Discovery、owned剥奪・ログアウト、archive_order、原画像監査、独立Tester/Reviewer PASS |

各Stageは実装・証拠・テストを [PROGRESS](PROGRESS.md) に記録してから次へ進む。P0で調査できなかった箇所は `UNKNOWN` のまま保持し、憶測で本番有効化しない。

## 原画像・忠実度の共通定義

- **A / Original bytes**: 配信されたJPEG/WebP/PNGのバイト列が、その巻のそのページに **一意に対応する完成ページ** だと証明できる場合に、バイト列を再圧縮・再エンコードせず保存。
- **B / Lossless reconstruction**: 元データがタイル等でも、観測されたsource→表示の対応と全領域coverageが証明でき、既存実績のある**無劣化**復元がその画像形式・幾何に適合する場合に限る。JPEGのDCT/MCU入替は候補であり自動適用しない。
- **C / Verified source-derived pixels**: draw時の高解像度source canvas/bitmapから、実際のtransform/clip/順序で正確に再構成し、選択された表示ページとの厳密なpixel/provenanceを証明したものをlossless WebP/PNGに保存。A/Bとは区別して記録する。
- **D / Rendered fallback**: 上記を検証しても成立しない場合、ビューアーUIを含まない現在の完全な本文領域をPNGで保存。本文領域や原画像への由来が不明なら無理に保存せずUNKNOWN/失敗とする。単なる画面スクリーンショットを原画像と呼ばない。

**忠実度 > 拡張子**。原配信がWebPならWebP、PNGならPNGを採用。JPEGに変換すること自体を成果にしない。原画像が証明できないケースの成功報告には「A/B/Cのどこまで試したか」「何が不適合か」「Dの実測解像度・制限」を必ず含める。

## Codex進行ルール

- `AGENTS.md` と `docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md` のLead→Explorer→Implementer→独立Reviewer、必要時Testerを使用する。production writerと共有ブラウザoperatorは同時に一人。
- **実装はfeature branch** で行い、稼働Catalog/Watchlist/Bookライブラリに触らない。検証は明示した隔離パスを用いる。正常なログイン済み共有profileは閲覧用としてのみ再利用する。
- Phaseごとに差分、テスト・skip数、実観測と仮説、保存形式・失敗理由、残リスクを記録。ReviewerのBLOCKINGがあれば修正・再評価してから次へ。
- 新規Adapterの実装に合わせて `src/screenshot_crawler/site_adapters/ebookjapan/README.md` と `note/15_ebookjapan.md`（最新note番号は作業時に確認）を更新。共通変更が必要になった場合だけ`note/00_core.md`等も同期する。
- 原画像調査を「時間がかかりそう」「他サイトで無理だった」という理由で省略しない。**具体的な否定的証拠または権利・技術上の実ブロッカーがある場合にのみ調査を絞る**。際限ない探索・無根拠な復元の実装も求めない。

## 完了時のユーザー向け報告に必須

1. Discoveryの実測件数、追加/既存/不明、2作品それぞれのE2E結果。
2. Batchの成功件数、画像ページ数・ページの完全性、ZIP/Manifest/Artifact照合、未完了件数。
3. 原画像方式の **A/B/C/D判定表**（試した方法、成功/不成立/未実行、実測値、阻害理由、最終出力形式と解像度、残る品質差）。原画像の全ページ成功を一部サンプルから一般化しない。
4. 対象の変更ファイル/テスト/独立Review結果、既知の未対応構造と回帰リスク。
5. 既存ZIP名のずれがあれば安全なrenumber手順（自動改名はしない）。

## 参照

- `AGENTS.md`、`docs/SPEC.md`、`docs/ARCHITECTURE.md`、`docs/DISCOVERY_AND_BATCH.md`、`docs/CAPTURE_STRATEGY.md`、`docs/ACCESS_CONTROL_AND_PACING.md`、`docs/SITE_ADAPTER_GUIDE.md`、`docs/TEST_STRATEGY.md`
- `docs/BOOKWALKER_SOURCE_NATIVE_CAPTURE_RUNBOOK.md`（証拠・画像由来の考え方を参考にする。実装丸写し禁止）
- `runbooks/hanayume-free/03-viewer-capture/README.md`、`runbooks/piccoma-free/03-viewer-capture/README.md`、`runbooks/younganimal-adapter/03-viewer-capture/README.md`（A/B/C/Dの成功・不成立の実例）
- ebookjapan公式: `https://ebookjapan.yahoo.co.jp/info/viewer-instruction/` / `https://ebookjapan.yahoo.co.jp/info/bookshelf-instruction/`（公開案内は補助資料。購入済みのDOMを証明しない）

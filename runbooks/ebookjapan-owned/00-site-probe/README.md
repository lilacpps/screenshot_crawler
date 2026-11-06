# 00 — 実サイトProbe（一覧・権利・Viewer・画像ソース）

Status: **NOT STARTED**。このStageで本番Adapter実装や運用Catalog更新をしない。

## 入力・既知／未知

- 対象: `https://ebookjapan.yahoo.co.jp/books/all/134336/`（エンジェル伝説、ユーザー申告：10巻のみ購入）、`https://ebookjapan.yahoo.co.jp/books/all/115888/`（ムダヅモ無き改革、ユーザー申告：全16巻購入）。
- 公開公式ヘルプはPCの見開き表示、画面端クリック、ページ数表示・スライダー・読む方向切替を説明。これは現行の**認証済み実DOM・画像形式の証明ではない**。
- 不明: account-marker、カードの「購入済み」DOM/表示条件、lazy load/並び順、巻固有ID、閲覧URL、Viewerページ構造、原画像response、終端挙動。
- 共有Crawler Chrome/Playwright。ログインできていなければ手動ログインを依頼して **BLOCKED** にする。認証自動突破は行わない。

## Probe 00-A — 作品一覧と所有判定（閲覧のみ）

1. 作品URLと最終canonical/redirect、作品見出し・シリーズID・巻数/一覧完了シグナルを記録。host、path、document状態を同時検証。
2. 「左→右、上→下」の2列視覚順とDOM列挙順を照合。サーバーやUIに並び順切替がある場合、`oldest=1`へ正規化するための実証可能な方法を選ぶ。巻番号・作品IDをURL数字から推測しない。
3. 「購入済み」をカード固有のDOM要素・リンク・属性に紐づける。作品共通バナー、非表示のボタン、試し読み、表紙alt、価格`0円`、カート中、無料公開などからownedと誤判定しない。
4. 未購入巻・購入済み巻を少なくとも各1枚、対象作品内の**実カード**で比較。全16巻のケースは「単一カードの判定」を全行に再適用し、全カード固有の同一性を確認。
5. 全表示・遅延読み込み・ページネーション・続きを見る・各巻のmetadata/IDと安定した全件カウントを検証。件数が変わる、途中しか読めない、idが重複、所有判定が曖昧なら不完全として停止。
6. ログアウト/期限切れ/アカウント切替を区別できる証拠を確認。ログイン済みの証拠がないまま「購入済み0件で成功」としない。

**安全制約**: Listing確認では`購入する`、`カート`、`試し読み開始`、`無料で読む`等を操作しない。通常の一覧表示・スクロール・正規の表示順切替のみ使用。

## Probe 00-B — Viewer構造（購入済み1冊から開始）

1. 最初にエンジェル伝説10巻のカードで、明示的なowned閲覧入口を観測。Click前に巻ID・カードID・権利とURLを固定し、閲覧時に巻IDが変わったら中断。
2. Readerの同一タブ/新規タブ挙動、頁番号の取り方、最初の本文、途中再開→先頭への安全な復帰、読書方向、見開きの左右順、ページロード状態を確認。
3. 先頭、通常中間、見開き、最終本文、終了画面をそれぞれ観測。最終ページを越える「次巻へ」「購入」操作は禁止。ENDは独立に観測できる証拠が必要。
4. `img`、CSS背景、`canvas`、Blob、画像request/response、配信形式/サイズ、描画操作等を**メタデータ中心**で観測。任意のsrcから対象巻の本文だと決めつけない。
5. Browser profile・書籍の読書位置を勝手にクリアしない。検証で変えた表示設定・読書位置を可能な限り正常に戻す。共有Pageは一人のoperatorが扱う。

## Probe 00-C — 原画像仮説の初期切り分け

後続[03](../03-source-native-capture/README.md)を省略する理由にはしない。まず以下を最初/中間/終端サンプルで確認する。

- Network: first-party配信のContent-Type/bytes/decoded dimensions、同一ページで複数候補があるか、low-res/thumbnail/trialとの混在。
- Browser: DOM `img.src` / Blob / `createImageBitmap` / Canvas drawの関係、source→表示の形（完全ページ/タイル/非等倍/クリッピング/合成）。
- Raw配信候補の解像度とViewer実表示/Canvas backing storeの解像度差。高解像度候補があれば単純に縮小画像を保存せず、後続の対応付けへ回す。
- HTTP 401/403/429、challenge、rights/DRMなど停止条件はAccessGuardに従い、強行リトライ・回避しない。

## 成果物

- `runbooks/ebookjapan-owned/PROGRESS.md` に OBSERVED / INFERRED / UNKNOWN を分けた結果、2作品のカード数・owned候補数・DOM順・公式巻ID・Viewer頁と画像資源の種類を記録。
- 再現可能な最小Probe（必要なら`poc/ebookjapan/`）。出力はignored `output/ebookjapan_experiment/phase00/` に隔離し、Cookie/署名付きURL/本文画像/HTML丸ごと/認証情報をコミットしない。保存済みのbody bytesを使った診断も必要最小限で一時ファイルを削除。
- 具体的な次ステージのselector/ID authority、fail-closed条件と未確認事項を記述。

## 受け入れ／終了条件

- 独立Reviewerが「ownedのカード固有証拠」「一覧の完全性と順番」「Viewerの同一巻ID」「安全な正規閲覧入口」を確認。
- 各作品のowned実数を申告期待値と比較し、不一致は理由を特定するまで`BLOCKED`。
- Viewerや画像配信がログイン/環境のため未調査なら「未検証」としてP02/P03を合格扱いにしない。

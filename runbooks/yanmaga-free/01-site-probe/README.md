# Phase 01 — Site Probe / 無料性とReaderのread-only実測

**Start:** RunbookはPLANNED。2026-10-20の公開サイト検索結果に`70 無料`・`初回無料`・「もっと見る」・「無料は1日に読める数に限りがある」が確認できるが、Playwright/CDPによるDOM/API/Viewer実測は未実施。
**担当:** Leadが境界を指定 → Explorer read-only調査。必要な診断コードだけImplementerが隔離出力に作成。Viewerを含む共有CDPのoperatorは一人。Reviewerが証拠十分性をチェック。

## Goal / Scope

ヤンマガWebの**無条件の赤字無料**のみを安全に識別・直接閲覧できる根拠を得て、full/incremental Discovery、Capture、Batchに使う最小のサイト固有契約を確定する。調査対象候補: https://yanmaga.jp/comics/MADE_IN_YAMATO 。実行時に公開無料が存在しなければ、別の公開free作品を選んで理由を記録（無料でない章を解放しない）。

## Read-only調査の順序

1. **Repo契約確認:** `AGENTS.md`、上位docs、既存`comicfuz`/`piccoma`/`kadocomi`/`younganimal`、実行CLI、Catalog v6、site policyを照合。shared Core/Catalog変更を必要とする事実があるか区別する。
2. **作品URL/話ID:** `/comics/<work_slug>`、実際の話リンク`/comics/<slug>/<id>`、`?reading=<id>`、canonical URL、内部APIのwork/episode IDがどう対応するか検証。`reading`を即stable episode IDと決めない。redirect、同作品照合、URL正規化、末尾query/fragmentの扱い、エピソードの永続ID・公開日・タイトルを記録。
3. **作品一覧と「もっと見る」:** 新着順/古い順、行数、リスト範囲・各章のリンク、無限追加か非表示行の展開か、総件数、pagination、重複、エラー後の部分リストを確認。必要なら作品冒頭と最新話の両端を調査し、番外編/単行本宣伝話/前後編の挿入を確認。
4. **権限分類:** 各話のrow-localな「赤字無料」「初回無料」「黄色無料/チケット」「ポイントのみ」について、表示文言、DOM class/属性/style、native APIフィールド、複数badgeの併記、値が一致するかを**同一episode identity**で照合。`70 無料`のようなポイント価格併記を無料性の反証にしない。badgeの色だけ・`無料`文字列だけで通さない。無料扱いの正の証拠と不一致時の`unknown`を表にする。
5. **無料数制限と認証:** サイト共通の「無料は1日で読める数に限りがあります」が赤字無料に関わるか、閲覧にゲート/権利/枠が必要か、匿名の赤字無料が本当に無消費で進められるかを、無料話だけで確認。既存shared profileがログイン済みなら権利依存と混同しないため公開状態証拠を別に求める。ログアウトやCookie削除でユーザーsessionを破壊しない。
6. **Readerと画像:** 正のpublic-freeの一話だけを開き、開始URL/reader内同話identity、履歴による巻戻し、1頁/見開きの表示・RTL順、loading、次ページ操作、本文/広告/extra、END/NEXT_CONTENT、native JPEG/WebP/PNG・tile/canvas・画像寸法/表示画素の対応を調査。sourceを同一pageへ帰属できない画像は「原本」と断定しない。
7. **安全な停止:** チケット/初回無料/ポイント/無料登録/レンタルの実行ボタンをクリックしない。入口が不明ならViewerを開かず未検証で止める。CAPTCHA/MFA/DRMの回避、403/429の迂回、大量巡回や著作物のRepo保存をしない。

## Output / Evidence

`PROGRESS.md`に次を`OBSERVED` / `INFERRED` / `UNKNOWN`で分けて記録:
- site host、work/episode URIの厳格な構文・ID正規化方針、snapshotの根拠
- 全件・pagination・並び/positionのauthorityとbounded可否
- 各Access状態に対する正のbadge/API/匿名Reader証拠、併記・曖昧時の停止、日次上限の影響
- Readerの最初/中間/最後、見開き・宣伝・END、Captureのprovenance候補とfallback
- 使用した無料sample URLと観測日、検証できない項目。Cookie/署名URL/ページ画像/生HTMLは記録・pushしない

## Exit gate

- 作品・話IDが安定して関連付けられ、少なくとも1件の通常freeについて**非消費で現在の公開話**と立証できる。
- full list/Reader/画像/ENDに実装可能な観測事実がある。未観測shapeはfail closedとする設計を示す。
- いかなる資源消費も起きていない。Reviewerが誤free、ID衝突、部分list誤完了、画像欠落の主要リスクを検査。
- FREEの正の根拠が得られないときはその機能を`BLOCKED/NOT VERIFIED`にし、確認できた情報だけに基づくUnit計画へ進む。初回無料やチケットを代替サンプルとして使わない。

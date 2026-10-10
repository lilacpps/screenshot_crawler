# Phase 01 — Repository / 花とゆめ＋ 実サイトProbe

Status: NOT STARTED。次段階: [Discovery](../02-discovery/README.md)。

## 目的・根拠
シード https://hanayume.com/episodes/8c6f15923caa0 から、
**作品全体の列挙方式と「無料」「今なら無料」の実条件**を確定する。
同じ作品の2〜3話（両種ラベルがあれば双方）を対象にViewerの最初・中間・終端を観測する。
未知のselector/URLパターンや画像形式を仮定してproductionに埋め込まない。

Explorerがread-only調査し、必要なbounded ProbeだけImplementerへ依頼。
Leadが一覧・access・captureの設計判断を確定する。
既存Jump+ / Comic DAYS / Magapoke / Piccomaの実装・テスト・runbookを先に参照する。

## 調査内容

1. seed URLの作品タイトル、作品ID、話ID、作品一覧へのリンク、canonical URL・redirect・一覧の上部Viewerの関係を特定。URL IDの一意性と作品スコープを観測。
2. 一覧の「もっと見る」を最後まで押す方式と、「...」から話数範囲を順に展開する方式を比較。
   DOM増分、順序、上限・停止signal、declare countとactual count、Lazy load、重複を測定。
   全件性を証明しやすい**1方式**を採用。単純な件数未変化や固定sleepだけを完了判定にしない。
3. 少なくとも「無料」「今なら無料」各状態に対応する実際の行表示、
   row identity、表示text/attributes/icons、他のaccess表示（paid/quota/owned/unknown）との競合を記録。
   候補行が本当に**追加の権利消費なしに**Viewerへ入れるか、通常の無料ページに限って検証。
   購入・チケット・ログイン・権利付与CTAをクリックしない。
4. Reader方式（img/canvas/CSS/その他）、body/spread、前後操作、ページidentity、
   loading、resume/rewind、広告、最終本文後のEND/NEXT_CONTENT、Viewerがページ上部にある場合のcontext切替を観測。
5. 画像responseのMIME、サイズ、1ページ/見開き/タイル、ページidentityとの対応、canvas draw/transform、
   source-original候補を観測。スクランブルなら実タイル幾何・MCU/係数置換適合性を判定するPoC要否を判断。
   Browser出力と画像比較するための小さな証拠だけ残す。
6. 別作品/別話・異なるラベルによるレイアウト差分をboundedに確認する。
   観測できないVariantはUNKNOWNとして記録。

## 制約
- 研究中に権利消費・購入・課金・自動ログイン・DRM回避をしない。
- shared Chromeの同時操作者は1名。Probeはsite負荷、取得件数、待機をboundedにする。
- ネットワークbodyや署名付きURL、session/cookie、著作物をrepoへcommitしない。
- 仮説と観測事実を混在させない。生のスクリーンショットやtokenは保護されたローカル出力のみ。

## 必須成果物/Exit gate
- PROGRESS.mdに **OBSERVED / INFERRED / UNKNOWN / BLOCKED** を分けた調査結果。
- 作品/話identity契約、正確な無料ラベルscope、列挙完全性/終端方式、全体話順、
  Readerのpage/END、元画像候補/スクランブル評価、サンプル2〜3話の正規URL。
- 両ラベルの直接無料閲覧が正当に可能か、無消費入場で確認。どちらか未検証なら理由と次Probeを指定。
- 確認した事実に基づきPhase 02/03の仕様変更点をLeadが明示。無根拠のproduction実装は不可。
- Probeテストは必要に応じて実行、実装がなければunit testのPASSを主張しない。


# P0 — サイト構造・無料状態・原画像の証拠収集

Status: NOT STARTED。入口は [README](README.md)、結果は [PROGRESS](PROGRESS.md)。
**目的**: 推測を実装契約にしないため、実サイトで観測可能な範囲の正の証拠を揃える。

## 対象/前提/担当

- Seed: `https://comic-walker.com/detail/KC_004915_S?episodeType=first`。
- URL内の `KC_004915_S` をwork ID候補とし、エピソードURL・canonical化・queryの要否は未確定。
- Explorer (read-only) を中心に調査。ブラウザ操作・計測が必要ならLeadの排他指示でImplementerが有界Probe。
- 共有Crawler Chrome/CDP + Playwrightを利用。通常profileを勝手に切替えない。
- 別の構造を持つ無料作品/話も可能なら1件観測。単一seedの仮説をサイト全体へ拡張しない。
- 調査用のスクリーンショット、DOM断片、Networkメタデータは外部共有しない隔離領域に保存。
  Cookie、token、署名付きURL、著作物の原画像や生本文をrepoへcommitしない。

## Probe A — 一覧と公開状態

1. 初期表示 → 「全XX話を表示」操作を**有界**で実行。DOM変化、件数、順序、
   API response/ページング/遅延描画、総XX話の意味を確認。
2. 全件リンクを列挙する**exactなスコープ**を特定。話タイトル/episode ID/作品ID、
   クエリ、サイト内遷移、重複、横の「単行本」やストア導線を区別する。
3. 「第XX話から第XX話は配信が終了しました」の表示が、
   個別ID、話数、部分話（その1、その2）、スロット数を一意に示すか確認。
   総数≠リンク数の場合、その内訳を説明可能か。無理なら欠落を推測しない。
4. 各話の掲載期限（タイムゾーン、日時精度、無表示時の意味）、
   `無料`バッジ欠如、公開中の正の根拠、配信終了の案内、他の導線
   （有料・ログイン・アプリ限定等）の例を採取。期限の有無のみをfree根拠にしない。
5. 表示数・件数・ネットワーク結果が途中で変化した場合、すべての結果を
   バッファ検証した後にDiscoveryへ渡す条件を決める。
6. 話の並びはoldest→newest / newest→oldest のどちらか、再公開・非公開で
   位置が変動するか、サイト上の**全件位置**が証明できるかを調べる。

## Probe B — Reader・原画像/ページの帰属

1. 現在公開中と証明できた話URLを、Catalogで利用する予定のURL形で直接開く。
   リダイレクト/クエリの必要性/同じepisodeへの帰属、再開ダイアログの有無を確認。
2. ReaderのDOM/Canvas/img、ページ数、ページID、spread・片側/白紙/PR・広告、
   ページ送り、loading、先頭復帰、最終本文、END/NEXT_CONTENTを観測。
3. Network image responseのcontent-type、実byte先頭、元画像pixel dimensions、
   対象ページとの一意の対応を確認。JPEG/PNG/WebP原本を直接保存できる可能性を
   **簡単に諦めず**検証。原本がcrop/tiling/permute/transform等を経由しているなら
   draw geometryと画素整合性を検査する（DRM/アクセス制御回避はしない）。
4. 本文Canvasとの元画像・再構成候補のpixel比較を行い、border/subpixel/拡大縮小/
   alpha/color mode/ソースrectangleを確認。元画像不一致を「取得不能」と混同しない。
5. source-native pixelsからの安全な再構成の可否を検証。
   原本/再構成が安全でない理由と、rendered content canvas fallbackの根拠を記録。
   fallbackでlossless WebPを使うなら、変換前とdecoded pixelを比較する。
6. Resource captureは有界・軽量。draw hook上で重いencode/hash/response body-readをせず、
   rendererに悪影響を及ぼさないことを観察。元画像候補のdebug保存は隔離する。
7. 公開状態の再確認をViewer前に行う方法（対象episodeの可読性・work/episode一致、
   不明や期限切れ時の安全停止）を具体化する。個人sessionが読めることだけで
   無条件freeとしない。

## 調査記録の書式

各項目について「OBSERVED（取得方法、日時、URL/IDのマスク済み根拠）」、
「INFERRED（なぜそう推測）」、「UNKNOWN/NOT VERIFIED」を分ける。
最低限: work/episode URL parser候補、展開操作、public chapter scope、
配信終了行、FREE判定根拠、total/listing整合、reader entry、
page identity/next/END、原画像候補別の採否・pixel証明、限界と追加Probe。

## Gate / テスト

- URL/DOM/networkのサイト依存定数はP0の**観測結果**を経てP1/P2へ移す。
- 課金・購入・チケット消費やloginは行わない。CAPTCHA/403/429/曖昧な導線は停止。
- P1開始には、仕事/話identity、公開話の判定、全件展開・終了案内の区別、
  不完全な一覧の検出方法についてLeadが承認できる証拠が必要。
- P2開始には、readerの確実な前後遷移/END/ページ帰属と、採用画像方式の証拠が必要。
- 調査で明らかに不明な点は追加の**bounded Probe**か対応範囲の縮小を選ぶ。
  曖昧な無料判定や不完全な本文を本番化しない。結果をPROGRESSに記録。

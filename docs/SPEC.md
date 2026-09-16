# Screenshot Crawler 仕様書 v1

## 1. 目的

特定のWebビューアにアクセスし、コンテンツを1ページずつ進めながら、本文ページだけをPNGとして保存する。

サイトごとに以下が異なることを前提とする。

- 本文の描画方式（img / canvas / CSS background / その他）
- 次ページ操作
- ページ変更検知
- 広告や中間画面
- 最終ページ後の挙動
- 次話・次章・次コンテンツへの遷移
- スクリーンショット対象領域

したがって完全自動判定はv1の目的にしない。共通エンジンとサイト別Adapterを分離し、新しいサイトは都度調査して必要な差分だけ実装する。

## 2. 技術

- Python 3.12+
- Playwright Python
- Chromium
- asyncio
- PNG出力
- Windowsを主対象とするが、OS依存実装は避ける

## 3. 入力

Crawler本体はURLを収集しない。入力URLは人手または別プログラムから渡される。

想定CLI:

```bash
python -m screenshot_crawler.cli crawl --site example --url "https://example.com/..."
```

新規サイト調査:

```bash
python -m screenshot_crawler.cli probe --url "https://example.com/..."
```

## 4. 画面状態

`PageState` は次の6状態を持つ。

- `CONTENT`: 保存対象の本文
- `AD`: 広告・保存対象外の中間画面
- `END`: 現在コンテンツの終了画面
- `NEXT_CONTENT`: 次話・次章・別コンテンツ
- `LOADING`: 描画途中
- `UNKNOWN`: 安全に判定できない

`UNKNOWN` では無理に進まず、diagnosticsを保存して停止する。

## 5. Coreの責務

Coreは以下を担当する。

- Playwright起動・終了
- Browser Context作成
- URLアクセス
- Site Adapterの呼び出し
- ページループ
- 保存連番
- PNG保存
- fingerprint計算
- 重複防止
- retry / timeout
- progress保存
- manifest保存
- diagnostics保存
- 無限ループ防止

Coreは以下を判断しない。

- どのDOMが本文か
- どこをクリックすると次に進むか
- 広告かどうか
- 最終ページかどうか
- 次話に移ったかどうか

これらはSite Adapterの責務とする。

## 6. Site Adapterの責務

各サイトは最低限、以下を提供する。

- 初期化
- 現在画面の状態判定
- 保存対象Locatorの特定
- 現在ページのidentity取得
- 現在コンテンツのcontext取得
- 次ページ操作
- ページ変更待ち

インターフェースは `src/screenshot_crawler/site_adapters/base.py` をauthorityとする。

## 7. ページIdentity

同一ページ判定に使う情報。利用可能なものを組み合わせる。

優先順位の目安:

1. page id / page number
2. img src
3. CSS background-image URL
4. canvas screenshot hash
5. capture target screenshot hash

fingerprintだけで最終ページとは判断しない。

## 8. Content Context

開始した作品・話・章を識別する。

例:

- work_id
- episode_id
- chapter_id
- title

開始時のcontextと明確に異なれば `NEXT_CONTENT` と判定できる。

特に以下の遷移で重要:

```text
本文最終ページ → 広告 → 次話1ページ目
```

## 9. スクリーンショット範囲

優先順位:

1. 本文画像Locator
2. 本文Canvas Locator
3. Viewer Locator
4. 明示clip領域

可能な限り `locator.screenshot()` を使い、URLごとの固定ピクセルサイズを第一選択にしない。

Viewportはサイト別に調整可能とする。

## 10. 広告

`AD` は保存しない。広告表示自体は終了条件ではない。

許容遷移:

```text
CONTENT → AD → CONTENT
CONTENT → AD → END
CONTENT → AD → NEXT_CONTENT
```

## 11. 終了条件

強い終了条件:

- `END`
- `NEXT_CONTENT`
- 明示的な終了DOM
- content contextの変更

補助条件:

- page number == total pages
- Next disabled
- Next消失

異常停止:

- `UNKNOWN`
- max_pages超過
- 同一identityが規定回数継続
- timeout
- Adapter前提崩壊

## 12. 保存形式

```text
output/<run_id>/
├─ page-0001.png
├─ page-0002.png
├─ ...
├─ manifest.json
└─ progress.json
```

保存連番とサイト上のページ番号は分離する。

## 13. Manifest

最低限:

```json
{
  "source_url": "...",
  "site": "example",
  "content_context": {},
  "pages": [
    {
      "sequence": 1,
      "page_number": 1,
      "file": "page-0001.png",
      "width": 1400,
      "height": 2000,
      "fingerprint": "..."
    }
  ]
}
```

## 14. 重複防止

CONTENT保存前にidentityまたはfingerprintを取得する。

同一ページと判断できる場合は重複保存しない。同一状態が連続した場合はカウンタを増やし、既定値3回で停止する。

## 15. Retry

一時的な描画・クリック失敗は既定3回までretryしてよい。

以下はretryで無理に突破しない。

- UNKNOWN
- context不整合
- 主要selector消失
- DOM大幅変更

## 16. Diagnostics

失敗時:

```text
diagnostics/<run_id>/
├─ screenshot.png
├─ page.html
├─ metadata.json
└─ error.txt
```

metadataには可能な範囲で以下を記録する。

- current URL
- title
- viewport
- detected state
- content context
- identity
- visible img候補
- canvas候補
- button候補
- background-image候補

## 17. Probe

新規サイト調査用。Crawler本体とは分離する。

目的:

- Codexがサイト差分を理解する材料を集める
- viewer候補、img、canvas、button、URL、DOM等を保存する
- 必要なら手動で1回ページ送りした前後を比較できるようにする

v1では「自動で正しい次ボタンを発見する」ことは要求しない。

## 18. Patterns

初期候補:

- ImageViewerPattern
- CanvasViewerPattern
- BackgroundImageViewerPattern
- GenericViewerPattern

Patternは必須のフレームワークではなく、Site Adapterから再利用する補助部品とする。

1サイトだけの特殊処理はPatternに昇格させずAdapterに置く。

## 19. 途中再開

progressに最低限以下を保存する。

- last_saved_sequence
- last_identity / fingerprint
- content_context

ページジャンプ機能があるサイトでは直接再開してよい。

ジャンプできないサイトでは、先頭から進み既取得identityを照合してスキップする方式を許容する。

## 20. v1非対象

- OCR
- PDF化
- AI画像分類
- CAPTCHA回避
- 完全自動selector探索
- GUI
- 複数サイト並列実行
- 独自DSL
- 複雑なPlugin Framework
- YAMLだけで全挙動を記述する仕組み

## 21. 受け入れ条件

### Core

- Site Adapterを差し替えて動かせる
- PNG連番保存
- manifest / progress生成
- diagnostics生成
- max_pagesで無限ループ防止
- retry / timeoutがある
- サイト固有selectorやURL判定がCoreに混ざらない

### Site Adapter

対象サイトについて:

- 本文だけ保存
- 広告を保存しない
- ページ順が正しい
- 重複保存しない
- 最終本文を取りこぼさない
- 次話を保存しない
- UNKNOWNでは停止

## 22. 実装完了の定義

「正常系だけ通る」では完了としない。

最低でも以下を確認する。

- 開始直後
- 通常ページ遷移
- 広告前後
- 最終ページ
- 最終ページ後
- 次話遷移
- ページ変更失敗
- UNKNOWN

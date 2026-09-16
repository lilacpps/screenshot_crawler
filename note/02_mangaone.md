# 02. Manga ONE対応の設計・実装記録

## 1. 目的

Manga ONEのWebビューアから、指定した話の本文ページだけを順番にPNG保存し、
話単位のZIPとして残す。

今回の対象では、次の要件を満たすことを目標にした。

- ログインなしで読める話を対象にする
- Full HD相当のビューア表示に切り替える
- 本文画像だけをLocator単位でキャプチャする
- 1枚表示と見開き表示を画面状態から判定する
- 見開きは右ページ、左ページの順に保存する
- 左側の操作で次の表示へ進む
- 冒頭や末尾の片側だけの表示を無理に見開きにしない
- 次話へ移動せず、現在の話だけで停止する
- 話数・前編/後編をファイル名に反映してZIP化する

対象URLの実行では、話単位のZIPが生成されることを確認した。

## 2. 対象サイトの調査結果

### 2.1 対象URL

通常話の確認には次のURLを使用した。

~~~text
https://manga-one.com/manga/2379/chapter/214131
~~~

前編の確認には次のURLを使用した。

~~~text
https://manga-one.com/manga/2379/chapter/358834?type=chapter&sort_type=desc&page=1&limit=10
~~~

前編URLのページタイトルは次の形式だった。

~~~text
獣王と薬草 第80話(前編) | マンガワン
~~~

### 2.2 本文の描画方式

本文はCanvasではなく、ビューア内の個別img要素として描画される。

~~~text
.viewer-container img[alt^="page_"]
~~~

画像のaltは次の形式で、ページ識別に利用できる。

~~~text
page_0
page_1
page_2
~~~

画像のsrcは実行中にBlob URLへ変換されるため、URLそのものを永続的なページID
には使わず、altと表示位置を使う。

### 2.3 Full HD表示

ビューア上の全画面ボタンを押すと、画像の表示高さがFull HDの1080pxになる。
Adapterのinitialize()で、最初の画像表示を待ってからこのボタンを押し、もう一度
画像の安定を待つ。

ブラウザContextは次の論理Viewportを使用する。

~~~text
width: 1920
height: 1080
device_scale_factor: 1
~~~

## 3. 表示判定とキャプチャ

### 3.1 1枚表示・見開き表示

表示中のpage_N画像を毎回調べ、Viewportと重なっている画像だけを取得する。

- 1枚だけ表示されている場合は1枚を保存
- 見開きの場合は2枚を保存
- 冒頭・末尾で片側しかない場合も1枚のまま保存

見開きの判定に、画面中央での固定分割や背景色による推測は使わない。

### 3.2 保存順

表示位置のx座標を使い、右側から左側へ並べ替える。

~~~text
画面右: page_1
画面左: page_2

保存順: page_1 → page_2
~~~

Coreには画面全体ではなく、各img Locatorを渡す。これにより、ビューアの
ヘッダーや操作UI、周囲の章一覧をキャプチャしない。

## 4. ページ送りと変更待ち

### 4.1 ページ送り

Manga ONEの右開きビューアでは、左側をクリックすると次の表示へ進む。

Adapterは次のように操作する。

1. .viewer-containerの左端付近をクリック
2. クリックできない場合は画面左側のマウス座標を使う

ブラウザの論理Viewportに対する相対位置で操作するため、物理モニターの解像度や
Windowsの表示倍率に依存しにくい。

### 4.2 ページ変更検知

固定時間のsleepだけではなく、次の情報を使って変更を待つ。

- 表示中のpage_Nラベル
- 各画像の表示位置とサイズ
- 画像の読み込み完了状態
- 表示画像の組み合わせが一定回数安定したこと

クリック後も同じidentityが残る場合は、最大2回までページ送りを再試行する。
タイムアウトには上限を設け、無限に待たない。

## 5. IdentityとContent Context

### 5.1 Page Identity

表示中のページラベルを右から左の順で連結する。

~~~text
page_0
page_1|page_2
page_3|page_4
~~~

page_numberには表示中の最大ページ番号に1を加えた値を入れる。
見開き画像の各PNGはCore側で個別fingerprintも計算される。

### 5.2 Content Context

URLのパスから次の値を取得する。

~~~text
/manga/{work_id}/chapter/{chapter_id}
~~~

例えば対象URLでは次のようになる。

~~~text
work_id: 2379
chapter_id: 214131
content_id: 214131
episode_id: 214131
~~~

開始時の話と異なる章URLへ遷移した場合はNEXT_CONTENTとして保存せず停止する。

ログインが必要な話については、現時点では認証を試みない。本文画像が安全に
取得できない場合は、無理に進めずエラー/diagnosticsへ進む。

## 6. 終端と宣伝ページ

### 6.1 終端判定

最終ページ後の操作で本文画像が消え、その状態が一定時間続いた場合にENDとする。
画像が残ったままページ変更も終端表示も確認できない場合は、タイムアウトとして
停止する。

### 6.2 宣伝ページ

話の最後に表示される宣伝ページは、本文ページと同じpage_N画像として配信される。
現時点では、DOMやページ番号だけから確実に区別できない。

そのため、Adapterでは宣伝ページを推測で削除せず、いったん話単位のZIPに含める。
後工程の統合処理で、作品・話ごとに次のような削除設定を適用する想定である。

~~~text
第80話-前編: 末尾2ページを削除
第80話-後編: 末尾3ページを削除
~~~

元の話単位ZIPを残しておけば、削除数を変更して再生成できる。

## 7. ファイル名とZIP

### 7.1 タイトルと話数の抽出

ページタイトルから、作品名・話数・前編/後編を分離する。

~~~text
獣王と薬草 第1話 | マンガワン
↓
タイトル: 獣王と薬草
順序情報: 第01話
~~~

~~~text
獣王と薬草 第80話(前編) | マンガワン
↓
タイトル: 獣王と薬草
順序情報: 第80話-前編
~~~

半角カッコと全角カッコの両方に対応する。

### 7.2 命名規則

~~~text
作品名-第01話.zip
作品名-第01話-前編.zip
作品名-第01話-後編.zip
~~~

話数は2桁以上のゼロ埋めとする。前編・後編は別ZIPとして保存し、話の統合や
話数から巻数への変換は行わない。

Manga ONE Adapterは汎用のorderメタデータを返す。既存のBookWalkerが使用する
volumeメタデータも後方互換のためCore側で受け付ける。

### 7.3 ZIPの保存先

正常終了後、既存のCore packaging処理がZIPを作成する。

~~~text
output/Books/漫画/<作品名>/<作品名>-<話数>.zip
~~~

例えば次のようになる。

~~~text
output/Books/漫画/獣王と薬草/獣王と薬草-第80話-前編.zip
~~~

ZIP内には本文PNGだけを次の形式で格納する。

~~~text
獣王と薬草-第80話-前編/
├─ page-0001.png
├─ page-0002.png
└─ ...
~~~

manifest.json、progress.json、diagnosticsは配布用ZIPには含めない。

## 8. 実装ファイル

~~~text
src/screenshot_crawler/site_adapters/mangaone/
├─ adapter.py
├─ config.yaml
├─ README.md
└─ __init__.py
~~~

関連する共通処理は次の通り。

- core/packaging.py: orderメタデータとZIP名の生成
- cli.py: mangaone AdapterのRegistry登録
- tests/unit/test_mangaone_adapter.py: URL、ページラベル、見開き順、話数名のテスト
- tests/unit/test_packaging.py: 話数を順序情報として使うテスト

## 9. 確認方法

実行コマンドは次の通り。

~~~powershell
uv run python -m screenshot_crawler.cli crawl --site mangaone --url "https://manga-one.com/manga/2379/chapter/358834?type=chapter&sort_type=desc&page=1&limit=10" --headed --output-dir output\crawl-mangaone-run --max-pages 1000
~~~

URLは実際に取得したい作品・章のURLへ置き換える。

実装時の短いLive smoke checkでは、次を確認した。

- 初期表示が1枚の場合に1枚だけ返る
- 左側操作後に見開き2枚へ変わる
- 見開きが右ページ、左ページの順になる
- 前編タイトルから第80話-前編を生成できる
- 初期状態がCONTENTになる

## 10. テスト結果

~~~text
pytest: 51 passed
ruff check src tests: pass
~~~

## 11. 未解決・今後の注意点

- 末尾の宣伝ページは、現在は本文と区別できないためZIPに残る。
- 宣伝ページの削除は、後工程の話統合/整理処理で末尾ページ数を指定して行う。
- 前編・後編の統合は後工程で行う。
- 話数から巻数への変換は後工程で行う。
- ログインが必要な章への認証対応は未実装である。
- Manga ONE側のクラス名や画像属性が変更された場合は再調査が必要になる。
- 実行前に同名ZIPが存在すると、既存のパッケージ処理は上書きせずエラーにする。

このノートには認証情報、Cookie、storage stateなどの秘密情報を記録しない。

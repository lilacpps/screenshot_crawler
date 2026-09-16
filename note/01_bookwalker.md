# 01. BookWalker対応の設計・実装記録

## 1. 目的

BookWalkerの電子書籍ビューアから、本文ページだけを順番にPNG保存する。

今回の対象では、次の要件を満たすことを目標にした。

- 商品ページから「試し読み」「読む」「10分まる読み」のいずれかでビューアへ移動する
- 本文以外の広告・終了画面・BookWalkerロゴを保存しない
- 見開き表示を左右のページに分割する
- 中央寄せの単ページ表示は不要な左右余白を保存しない
- ライトノベルの冒頭にある大きな単ページ画像にも対応する
- 最終ページを取りこぼさない
- 次話・次コンテンツへ移動した場合は保存せず停止する
- 同じページを重複保存しない
- 正常完了後は中間ファイルを整理し、ZIPを残す

対象商品の実確認では、59/59ページまで本文を保存できた。

## 2. 対象サイトの調査結果

### 2.1 商品ページからビューアへ移動する

入力URLは、直接ビューアURLだけでなく、次のようなBookWalker商品ページも受け付ける。

```text
https://bookwalker.jp/de<content-id>/
```

商品ページでは、以下の候補を調べる。

- `試し読み`
- `読む`
- `10分まる読み`
- `viewer.bookwalker.jp` を含むリンク
- `data-action-label`
- 現在の商品IDと一致する `data-uuid`

リンクの表示順だけには依存せず、ビューアURL、content ID、アクション名、表示文字列を使って候補をスコアリングする。

`target=_blank` の場合でも、ログイン自動化や認証回避はせず、既存のタブで通常のリンククリックとして開くために `target` 属性だけを取り除く。

### 2.2 本文の描画方式

本文は通常の `img` 要素ではなく、主にCanvasへ描画されている。

使用する本文Canvasは次のDOMを優先する。

```text
#renderer .currentScreen canvas:not(.dummy)
```

Canvas自体には、ビューアのUIや描画領域が含まれる場合がある。そのため、画面全体のスクリーンショットは使用せず、CanvasのPNGバッファを取得する。

### 2.3 Canvas内のページ領域

Canvasの中央で単純に二分すると、単ページ表示や作品ごとに異なる余白に対応できない。そのため、ページ初期化前に `CanvasRenderingContext2D.drawImage` を監視するスクリプトを登録した。

描画時の次の情報を記録する。

- 描画先の `x`
- 描画先の `y`
- 描画先の `width`
- 描画先の `height`
- 対象CanvasのID

現在のCanvas上で最も大きい有効な描画矩形をページ領域として扱う。過去ページの描画が残る場合は、他の矩形に完全に含まれる小さい矩形を除外する。

この矩形を一時Canvasへコピーし、CoreのLocator単位PNG取得に渡す。

これにより、次の表示に対応する。

- 中央に1ページだけ表示される表紙・挿絵
- 横長の単ページ
- 2ページの見開き
- ブラウザ左右の余白を除いた本文領域

描画矩形が取得できない場合だけ、限定的なフォールバックとしてCanvasの横幅と高さを比較し、十分に横長なら中央分割する。

## 3. 表示サイズと見開き

専用Chromeは次のサイズで起動する。

```text
window-size: 1920,1080
```

物理モニターの解像度には依存しない。4Kモニターを150%表示で使っていても、BookWalkerへ渡す論理的な表示領域をFull HD相当にする。

実際の環境では、ブラウザの論理viewportはおおむね次の値になった。

```text
innerWidth: 1906
innerHeight: 987
devicePixelRatio: 1.5
```

本文が見開きの場合は、BookWalkerの読み順に合わせて右ページ、左ページの順に保存する。manifestには見開きの `part` と `parts` も記録する。

## 4. ページ送り

BookWalkerのデスクトップビューアでは、左側の操作領域で次ページへ進む。

優先操作は次の通り。

1. `#viewport1` の左端付近をクリックする
2. クリックできない場合は `ArrowLeft` を送る

画面全体の中央クリックやマウス座標の固定値には依存しない。これにより、Windowsの表示倍率によるマウス座標ずれを避ける。

ページ変更は固定sleepだけで判定せず、次の変化を待つ。

- `#pageSliderCounter` のページ番号
- URLの `cid`
- Canvasの簡易fingerprint
- ローディング表示の消失
- Canvasの描画安定

冒頭の画像や表紙では、最初の左操作がページ番号変更に使われないことがある。そのため、同一ページのままの場合に限り、最大2回までページ送り操作を再試行する。

## 5. 状態判定

Coreの状態機械へ、BookWalker固有のDOM判定結果を渡す。

### CONTENT

本文Canvasが表示され、ローディング中ではない状態。

この状態では、以下を行う。

1. content identityを取得
2. 同一ページ・同一fingerprintでないことを確認
3. 本文のcapture targetを取得
4. PNGを保存
5. manifestとprogressを更新
6. 次ページ操作
7. 変更待ち

### AD

次の明示的なDOMが見える場合だけ広告と判定する。

```text
[data-ad]
.ad
#ad
#advertisement
```

広告と断定できない画面を、色や平均輝度だけで広告扱いにはしない。

### END

次のいずれかで終了と判定する。

- `#endOfBook` が表示される
- 最終ページから次操作を行った後、ページカウンターが `N/N` のまま変化しない

BookWalkerでは、最終ページ後にロゴCanvasを出す場合がある。このロゴ画面にも `59/59` が残ることがあるため、最終ページからの次操作後は、同じ `N/N` を本文として再取得しない。

最終ページ本体は、最終ページへ到達した時点で先に保存する。その後のロゴ画面だけをENDとして除外する。

### NEXT_CONTENT

次の情報で別コンテンツへの移動を検知する。

- URLの `cid` が初期値から変わる
- `#eobNext` が表示される
- content contextの強いIDが変わる

NEXT_CONTENTになった画面は保存せず、正常停止する。

### LOADING

`#loaderStatusDialog` が表示されている間は待つ。ただし、Runnerのretry回数とタイムアウトに上限を設け、無限待機はしない。

### UNKNOWN

本文・広告・終了・次コンテンツのどれとも安全に判定できない場合は、無理にページ送りをしない。diagnosticsを保存して異常終了する。

## 6. 重複保存防止と安全装置

Core側で次のguardを使う。

- `max_pages`: 既定値1000
- `max_same_content`: 同一内容の連続回数上限
- Canvas PNG bytesのSHA-256 fingerprint
- ページ変更timeout
- loading retry上限

見開きの各ページは個別のPNG fingerprintを記録する。同じfingerprintの画像しか得られない場合は、同じ内容を保存し続けず停止する。

## 7. 商品情報と命名

商品ページから、ビューアへ移動する前に次の情報を取得する。

- メインタイトル
- 著者欄
- 商品IDに一致するシリーズカードのタイトル
- シリーズ冊数
- カテゴリ

`【期間限定】` や `【電子特別版】` などのBookWalker向けキャンペーン表示はタイトルから除去する。

タイトル末尾の数字は巻数候補として扱う。

```text
作品名4【電子特別版】
↓
作品名 / 第04巻
```

命名は `docs/BOOK_NAMING_RULES.md` に合わせる。

- 通常は2桁ゼロ埋め: `第01巻`
- 100巻以上のシリーズは3桁: `第001巻`
- 著者が複数いる場合は `・` で連結
- Windowsで使えない文字は除去
- ジャンルはファイル名に含めずフォルダで分類

## 8. ZIPと中間ファイル

正常完了すると、既定では次の場所に保存する。

```text
output/Books/<ジャンル>/<作品名>/<作品名>-<巻数>-<著者>.zip
```

ZIP内は次の構造にする。

```text
<ZIP拡張子を除いたファイル名>/
├─page-0001.png
├─page-0002.png
└─...
```

`manifest.json` と `progress.json` はZIPへ含めない。成果物として必要なのは本文PNGだけであり、実行管理情報を配布用ZIPへ混ぜないためである。

正常完了した中間crawlフォルダは削除する。

完了の確認用に、次のstatus JSONを残す。

```text
output/crawl-status/<ZIP名>.json
```

statusには次を記録する。

- `status: completed`
- 作成したZIPのパス
- PNGページ数
- 元のcrawlフォルダ
- crawlフォルダを削除できたか

失敗した場合は、crawlフォルダを削除しない。Runnerが保存するdiagnosticsを使って、次を確認できる。

```text
screenshot.png
page.html
metadata.json
error.txt
```

## 9. 認証とブラウザ起動

ログインは、サイト固有のSite Adapterに実装したCLIコマンドで自動化する。
認証情報と起点URLは`.env`に保存し、サイト名を接頭辞にして複数サイトの設定を区別する。

BookWalkerの設定例:

```env
BOOKWALKER_URL=https://bookwalker.jp/st3/
BOOKWALKER_EMAIL=<メールアドレス>
BOOKWALKER_PASSWORD=<パスワード>
BOOKWALKER_CDP_ENDPOINT=http://127.0.0.1:9222
```

`.env`は`.gitignore`で除外し、認証情報をリポジトリやノートへ保存しない。

BookWalkerの実確認では、通常利用ブラウザと分離した専用ChromeをCDP付きで起動し、ユーザーが必要な操作を行った状態で接続する方式を使った。

```powershell
.\scripts\start_bookwalker_chrome.ps1
```

専用Chrome起動後、次のコマンドで既存Chromeへ接続し、BookWalkerのログイン画面を操作する。

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli login --site bookwalker
```

`--env-file`の既定値は`.env`である。別ファイルを使う場合だけ明示的に指定する。

ログインコマンドは、次の操作を行う。

1. CDP接続済みChromeの既存ContextとPageを取得する
2. `.env`の`BOOKWALKER_URL`へ移動する
3. 右上のログインボタンをクリックする
4. `j_username`へメールアドレス、`j_password`へパスワードを入力する
5. ログインボタンをクリックする
6. URL遷移後にログインフォームが消えたことを確認する

BookWalker側でCAPTCHA、MFA、入力エラーが表示された場合は、無理に再試行せず停止する。
ログイン成功後は、そのまま次のように既存Chromeへ接続してCrawlerを実行する。

```powershell
uv run python -m screenshot_crawler.cli crawl `
  --site bookwalker `
  --cdp-endpoint http://127.0.0.1:9222 `
  --url "https://bookwalker.jp/de<content-id>/" `
  --output-dir output/crawl-bookwalker-run `
  --max-pages 1000
```

`--diagnostics-dir` を指定しなくても、異常時にはoutput-dir配下へdiagnosticsが作られる。

正常完了時はビューアのタブだけを閉じ、CDP接続先のChrome本体は閉じない。

## 10. 実サイトで確認したこと

対象商品で次を確認した。

- 商品ページから試し読み用ビューアへ移動できる
- Canvas描画から本文領域を取り出せる
- 単ページと見開きを判定できる
- 見開きを右ページ、左ページの順に分割できる
- 左側操作でページを進められる
- 冒頭の画像ページを保存できる
- ページ変更をページカウンターと描画安定性で待てる
- 59ページ分を保存できる
- 最終ページ後のBookWalkerロゴを保存しない
- 最終ページ後に正常終了できる
- 59枚のPNGをZIP化できる
- ZIPにmanifest/progressを含めない
- 正常完了後に中間crawlフォルダを削除できる
- CDPで起動済みの専用Chromeへ接続できる
- `.env`のBookWalker設定を読み込める
- 商品ページのログインボタン、メールアドレス欄、パスワード欄、ログインボタンを順に操作できる
- ログイン送信後に`https://bookwalker.jp/st3/`へ戻ることを確認できる

## 11. 未解決・今後の注意点

- BookWalkerの商品ページのDOMクラスやビューア仕様が変更された場合、商品情報抽出やCanvas判定の再調査が必要になる。
- すべての作品形式で同じCanvas描画矩形が得られるとは限らない。矩形が取れない場合はフォールバック分割になるため、未知作品では少数ページで確認する。
- 100巻以上の判定は、シリーズ見出しの冊数がDOMから取得できることを前提にしている。
- 直接ビューアURLから開始した場合、商品ページ由来の著者情報が得られないため、ZIP名の著者部分が省略されることがある。
- 実行前に既存の同名ZIPがあると上書きせずエラーにする。

## 12. 新しいチャットへ引き継ぐ場合

新しいチャットでは、前の会話で確認したCDP接続先やリポジトリの前提が引き継がれないことがある。その場合は、次の内容を最初に伝える。

```text
このリポジトリで作業してください。

リポジトリ:
C:\Users\kensu\projects\screenshot_crawler_starter

BookWalker操作用の専用ChromeはCDPで起動済みです。
接続先は次です。

http://127.0.0.1:9222

通常のブラウザ操作機能ではなく、リポジトリ内のPlaywright Pythonコードから
connect_over_cdp("http://127.0.0.1:9222")
で既存Chromeへ接続してください。

まず以下を確認してください。

1. http://127.0.0.1:9222/json/version に接続できるか
2. Playwrightで既存BrowserContextとPageを取得できるか
3. 現在開いているタブのURLを確認する

BookWalkerのログイン自動化を確認する場合は、`.env`を用意したうえで次を実行します。

.\.venv\Scripts\python.exe -m screenshot_crawler.cli login --site bookwalker

ログイン自動化がCAPTCHAやMFAで停止した場合は、ユーザーがChrome上で必要な操作を手動で完了し、その後Crawlerを実行します。
```

あわせて、作業開始前に次のファイルを読む。

```text
AGENTS.md
docs/SPEC.md
docs/ARCHITECTURE.md
docs/DECISIONS.md
docs/CODEX_IMPLEMENTATION_GUIDE.md
docs/SITE_ADAPTER_GUIDE.md
docs/TEST_STRATEGY.md
docs/BOOK_NAMING_RULES.md
note/01_bookwalker.md
```

専用Chromeをまだ起動していない場合は、リポジトリ直下のPowerShellで次を実行する。

```powershell
.\scripts\start_bookwalker_chrome.ps1
```

このノートは、認証情報、Cookie、storage stateの内容などの秘密情報を記録しない。

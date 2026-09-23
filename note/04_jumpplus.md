# Jump+ J0 probe 現行観測ノート

## Scope

少年ジャンプ＋（Jump+）のproduction Site Adapter / Discovery / Site
Policy / Batchは未実装。これはviewer構造を調査するためのread-only J0
probeの現行スナップショットである。ポイント、購入、レンタル、チケット、
ログイン状態変更、次episodeへの遷移は行わない。

対象は次のepisode URLのみ。

```text
https://shonenjumpplus.com/episode/13932016480029111789
```

## Probe entry point

実装は `poc/jumpplus_probe.py`。shared Crawler Chromeへ既存の
`BrowserSession` / `resolve_cdp_endpoint()`でCDP接続し、probe自身はChrome
launch、profile選択、CDP接続処理を所有しない。

```powershell
.\.venv\Scripts\python.exe poc\jumpplus_probe.py `
  --url "https://shonenjumpplus.com/episode/13932016480029111789" `
  --output-dir "output\jumpplus_probe" --steps 3
```

`--steps`は最大5に制限される。対象episodeのhostまたは`/episode/<id>`が
変わった場合は自動操作を停止する。

## Live verification (2026-09-23)

指定URLでshared Crawler Chromeへ1回実行済み。結果は
`output/jumpplus_probe/summary.md` と `report.json` に保存した。

- 初期ページのviewportは`1302x986`のCSS viewport、devicePixelRatioは1.5。
- 初期DOMには`section.viewer.js-viewer`、
  `div.image-container.js-viewer-content.is-spread`、4個のvisible canvas、
  `img.page-image.js-page-image`が観測された。ページ全体にはviewer以外の
  imgも含まれるため、visible img総数だけを本文ページ数とは扱わない。
- `drawImage`はinit scriptを`goto()`前に注入してmetadataのみを記録した。
  初期状態では`HTMLImageElement`から764x1200 canvasへの9引数drawが確認され、
  変換はidentity、`source-over`、filter `none`、globalAlpha 1だった。
  createImageBitmapは未観測。drawImage hook内でencode、base64、hash、network
  access、全画像copyは行わない。
- 本文候補のresponseは
  `https://cdn-ak-img.shonenjumpplus.com/public/page/2/...` のJPEGで、
  10件を元byteのまま保存した。いずれも実ピクセルは764x1200。保存先は
  `output/jumpplus_probe/network_images/`。
- viewerのsource URLは`blob:https://shonenjumpplus.com/...`としてdraw時に
  観測された。CDN responseとの一対一対応はJ0では検証済みとしない。
- 初期state後、DOMの`page-navigation-forward` /
  `js-slide-forward`を明示的にクリックして3回遷移した。URLは全stateで
  対象episodeのまま、bounded DOM/image/canvas stability waitは成功した。
  `state_000`から`state_003`を保存した。次episodeリンクはDOMに存在したが、
  クリックしていない。
- DOM・script・JSON候補、`/episode/<id>` links、access関連表示を保存した。
  無料に相当する表示は観測したが、free/paid分類ロジックは実装していない。
- END / NEXT_CONTENTの専用signal、page count/current page/total pageはJ0で
  最終判定していない。

## Output contract

`initial/`には`page.html`、`dom.json`、`network.json`、`draw_calls.json`,
`scripts.json`、`links.json`、`screenshot.png`を保存する。`state_000`以降は
DOM summary、new network events、new draw calls、scripts/links、screenshotを
保存する。network body取得失敗は記録してprobe全体を失敗させない。本文候補
bodyの保存数は最大20件（今回の実行は10件）。

## Capture status

- original bytes: `possible`。本文候補の元JPEG responseは保存できたが、visible
  pageとの厳密な対応付けは未確認。
- source-native: `possible`。drawImageのsource/destination geometryは得られたが、
  blob sourceとresponseの帰属・最終ページ対応は未確認。
- rendered canvas: `confirmed`。visible canvasの存在とgeometryを観測したが、
  J0のdraw hookはcanvas pixel encodeを行わない。
- screenshot: `confirmed`。viewport screenshotを各stateに保存した。

scramble、tile、canvas再構成の有無はJ0では確定しない。production capture方式を
このノートから決定してはならない。

## Next investigation

J1では、保存したJPEGの内容と各stateのdrawImage geometryを、同じvisible
canvas/screenshotと比較する。特に次を確認する。

1. CDN JPEGがvisible page一枚と一対一に対応するか。
2. blob化の前後で同じsource bytesを追跡できるか。
3. `is-spread`がDOMレイアウト上のspreadを意味する範囲と、readerのreading order。
4. viewer state内のcurrent/total pageとEND/NEXT_CONTENT signal。

不明なものは`unknown / not observed`として扱い、production adapterへの実装は
この確認後に別途行う。

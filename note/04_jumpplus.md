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

## J1 Capture PoC (2026-09-23)

`--j1 --steps 3`で再実行し、`output/jumpplus_probe/j1/`へ比較結果を保存した。

- `state_000`〜`state_003`の4 stateを取得した。各stateで8、10、12、14枚の
  `764x1200` canvasを観測した。
- 本文候補JPEGは16件保存され、全件`cdn-ak-img.shonenjumpplus.com`の
  `/public/page/` response、JPEG、764x1200だった。URL、response timestamp、
  byte length、raw SHA-256、decoded RGB pixel SHA-256、format、dimensions、pathを
  `candidate_images.json`へ保存した。
- canvasのraw `toDataURL("image/png")`は、対象canvasが
  `SecurityError: Tainted canvases may not be exported`となり利用できなかった。
  比較用にはstate安定後のPlaywright locator screenshotをfallbackとして保存した。
  これはraw canvas exportではなく、composited rendered canvasの観測である。
- drawImageでは、764x1200全体を描くcallに加えて、同じsourceから184x296の
  部分rectを多数描き、destinationへ配置するcallを観測した。transformはidentity、
  compositeはsource-over、filterなし、alpha 1だった。
- draw hookでHTMLImageElementをsource ID付きで軽量に保持し、state安定後にsource
  pixelを取得した。4 stateで合計76件のsource PNGを保存し、各sourceについて
  dimensionsとdecoded RGB pixel SHA-256を記録した。hook内ではencode/hashを行っていない。
- 4 stateの全captured canvasについて、16件のJPEG候補とのRGB pixel比較を行った。
  `exact_unique_match`は0件で、全て`no_exact_match`だった。
- CDN JPEGとblob sourceは、候補JPEGが同じstateに保存されていた38件で
  `exact_unique_match`、残り38件は候補未観測のため`ambiguous / unproven`だった。
  blob sourceとrendered canvasは比較可能な38件が全て`no_exact_match`だった。
- canvasのgeometry分類は44件すべて`tiled`。`is-spread`を全stateで観測し、canvasの
  screen x/y位置を`comparison.json` / `equivalence.json`へ保存した。reading orderは未確定。
- 保存JPEG候補を目視確認すると、輸送JPEG側はタイル状に配置が崩れている一方、
  rendered canvas側は漫画ページとして再構成されていた。partial sourceRectと
  no exact matchが複数stateで一致するため、J1では**tile/reconstructionを観測済み**
  と判断する。J1の範囲ではCDN JPEGをそのままLevel 1 original bytesとして保存する
  根拠は得られなかった。

比較詳細は各`j1/state_*/comparison.json`、全体結果は
`j1/comparison_report.json`、人間向け結論は`j1/summary.md`にある。

## Output contract

`initial/`には`page.html`、`dom.json`、`network.json`、`draw_calls.json`,
`scripts.json`、`links.json`、`screenshot.png`を保存する。`state_000`以降は
DOM summary、new network events、new draw calls、scripts/links、screenshotを
保存する。network body取得失敗は記録してprobe全体を失敗させない。本文候補
bodyの保存数は最大20件（今回の実行は16件）。J1比較結果は各stateの
`comparison.json` / `equivalence.json`、`equivalence_summary.md`にも保存する。

## Capture status (J1更新)

- original bytes: `rejected for observed candidates`。元JPEG responseは保存できたが、
  全J1 canvasとexact matchせず、tile/reconstructionが観測された。
- source-native: `transport source confirmed, direct page output rejected`。blob sourceの
  pixelは取得でき、観測可能な一部でCDN JPEGとexactだったが、rendered canvasとは一致しなかった。
- rendered canvas: `confirmed via screenshot fallback`。raw canvas exportはtainted
  canvasで拒否されたため、安定後のlocator screenshotを比較材料にした。
- screenshot: `confirmed`。viewport screenshotを各stateに保存した。

production capture方式はまだ実装していない。J1の推奨は`rendered canvas required`、
または観測済みtile mappingによる別途検証済みの再構成である。CDN JPEGの直接保存は
採用しない。

## Next investigation

追加調査を行う場合は、保存したJPEGのtile mappingとdrawImage geometryを使って、
lossless reconstructionがrendered canvasと一致するかを確認する。特に次を確認する。

1. CDN JPEGがvisible page一枚と一対一に対応するか。
2. blob化の前後で同じsource bytesを追跡できるか。
3. `is-spread`がDOMレイアウト上のspreadを意味する範囲と、readerのreading order。
4. viewer state内のcurrent/total pageとEND/NEXT_CONTENT signal。

不明なものは`unknown / not observed`として扱い、production adapterへの実装は
この確認後に別途行う。

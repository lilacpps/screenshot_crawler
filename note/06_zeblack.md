# Zebrack Z0 viewer probe 現行観測ノート

## Scope

これはゼブラック（Zebrack）の新規Site Adapter開発前に行う、対象chapter限定の
read-only viewer probe記録である。Production Site Adapter、Discovery、Site Policy、
Batch、access resource消費、login automationは未実装である。Z0では観測できた事実と
未確認事項を分離し、毎日無料・ポイント・コイン・レンタル等のresource semanticsを
決めていない。

## 対象URL / identity

対象は次のURLだけである。

```text
https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer
```

`title_id=118286`、`chapter_id=9265713`。probeはhostと
`/title/{title_id}/chapter/{chapter_id}/viewer`を検証し、query/hashだけの変化は
同一chapterとして記録する。別title、別chapter、別path、別hostへ遷移した場合は
自動操作を停止する。今回の実行では全stateで対象URLのままだった。

## Probe entry point / Browser Session

実装は `poc/zeblack_probe.py`。既存のshared Crawler Chromeへ
`BrowserSession` と `resolve_cdp_endpoint()`でCDP接続し、probe自身はChrome launch、
profile作成、storage state管理、loginを行わない。接続後の操作はPlaywrightのPage/
Locator/keyboardを使用した。

```powershell
.\.venv\Scripts\python.exe poc\zeblack_probe.py `
  --url "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer" `
  --output-dir "output\zeblack_probe" --steps 3
```

`--steps`は0〜3にbounded clampされる。response body候補は最大20件である。
初期artifactは `output/zeblack_probe/initial/`、state artifactは `state_000`〜である。

## Live verification (2026-09-27)

shared Crawler Chromeで対象URLを実行済み。3回の通常ページ送りを行い、
`initial`、`state_000`、`state_001`、`state_002`、`state_003`を保存した。

- viewportは`1906x986` CSS pixels、devicePixelRatioは`1.5`だった。
- titleは「「真の実力はギリギリまで隠していようと思う」1話 を漫画アプリで読む | ゼブラック」だった。
- final URLはtarget URLと同一で、chapter外遷移はなかった。
- 無料、毎日無料、待てば無料、ポイント、コイン、購入、レンタル、閲覧期限、残り時間、
  次回無料時刻、利用可能、利用済み等のaccess表示は、viewerのvisible textからは観測しなかった。
  これはaccessが存在しないという意味ではなく、今回の対象URL/stateでnot observedという意味である。

## Viewer structure

本文候補はcanvasではなく`img`で描画されていた。

- 初期stateではvisible DOM `img`が12件、うち`alt=page_0`〜のpage-like imageが3件、
  in-viewportは`page_0`の1件だった。recommendation等の本文外imgも同じDOMに存在した。
- page-like imageは`blob:` URL、natural sizeは`760x1080`、初期表示サイズは概ね
  `693.84x986` CSS pixelsだった。
- viewer-like DOMには`viewer` wrapper、slide container、spread-like element、
  page container、page imageが含まれた。実際のclass/id/data-* attribute、rendered x/y、
  width/heightは各`dom.json`と`viewerTree`に保存している。CSS module hashは観測値として
  artifactに残すが、production selectorとして採用していない。
- canvasは初期および3回のnavigation後もvisibleには観測されなかった。
- CSS `background-image`候補は観測されなかった。
- cross-origin広告iframeも存在したため、frame URLを記録したが、広告frameの操作は行っていない。

したがって今回のchapterについては「page-like `img` + `blob:` sourceが観測された、canvas/
backgroundはnot observed」が確認事実である。本文が常に同じ構造であることや、他chapterへ
一般化することはまだ確認していない。

## Network observation

navigation前からrequest/responseを記録し、`initial/network.json`と各stateのnetwork deltaに
URL、method、resource type、status、content-type、content-length、timestamp、frame URL等を保存した。

本文候補として次の二種類が観測された。

1. `asset.zebrack-comic.com` の対象title/chapter/page系JPEG response。content-typeは
   `image/jpeg`だったが、保存した元bytesはPillowでJPEGとしてdecodeできなかった。
2. `blob:https://zebrack-comic.shueisha.co.jp/...` のresponse/body候補。Playwright上の
   content-typeは`text/plain`だったが、保存bytesはJPEGとしてdecodeでき、代表的に
   `760x1080`だった。

Z0ではasset responseとblob bodyをURLや時刻、byte lengthだけで一対一対応と確定していない。
asset側bodyがそのままページ画像でない可能性、blob生成前後に変換がある可能性は残すが、
scramble、暗号化、tile permutation、reconstructionの方式は未確定である。保存bodyは
diagnostic candidateであり、production captureには使っていない。

実行時は最大20件のimage-classified candidate bodyを保存し、各候補にsource URL、content-type、
byte size、encoded SHA-256、format、dimensions、decode error、相対pathを記録した。
network全体にはJSON/fetch/xhr/script等も保存している。network artifact内のsigned queryは
運用上の秘密情報としてnoteには転記していない。

## Canvas / drawImage observation

`page.add_init_script()`でnavigation前にmetadata-only hookを注入した。対象は
`CanvasRenderingContext2D.drawImage()`、`OffscreenCanvasRenderingContext2D.drawImage()`、
`createImageBitmap()`である。hookはsource type/URL/dimensions、sourceRect、destinationRect、
canvas identity、transform、globalCompositeOperation、filter、globalAlpha、sequenceだけを
boundedに記録する。

今回の実行では以下はすべてnot observedだった。

- `drawImage()` call
- `OffscreenCanvasRenderingContext2D.drawImage()` call
- `createImageBitmap()` event
- canvas mutation

従ってgeometry分類は`unknown`であり、full-frame copy、tiled、cropped、scaledのいずれも
このchapterについて結論していない。hook内でPNG/JPEG encode、base64化、hash計算、network
access、全canvas pixel copyは行っていない。

## Navigation / page-change signal

初期DOMには本文page-forward buttonが明示的には見つからず、`< 次の話`はnext-content候補
として拒否した。viewer wrapperが1件だけあり、img/canvas contentを持ち、access/next-content
語を含まないことを再確認した上で、keyboard `ArrowLeft`をpage navigationとして観測した。
click直前のDOM candidateについてtext、aria-label、title、class、href、visibility、selector
を再検証し、hrefがある場合はtarget identityも検証する。今回の3回はすべて次を満たした。

```text
changed = true
stable = true
URL     = target chapterのまま
method  = keyboard / ArrowLeft
```

固定sleepだけではなく、visible img/canvas/page-text metadataのfingerprintが変化し、続けて
2回同一fingerprintになることをbounded waitで確認した。初期ページカウンタ候補は`1 / 25`、
navigation後は順に`2 / 25`、`4 / 25`、`6 / 25`だった。これはviewerが表示するcounter
候補として記録しており、production page number authorityとはしていない。

## Spread / reading order

初期stateはpage-like imgが1件viewport内だった。後続stateでは2件が同時にviewport内に入り、
spread-like classとpage containerが確認できた。観測したin-viewport geometryは、例えば
state_001で`page_2`が左側（x約259）、`page_1`が右側（x約953）、state_002で`page_4`が
左側、`page_3`が右側だった。初期の単ページから最初の送りでpage-like image集合が
`[page_0]`から`[page_1,page_2]`へ変化し、その後の送りでは`[page_1,page_2]`、
`[page_3,page_4]`、`[page_5,page_6]`のように2枚単位の変化が観測された。

これはspread-like表示とx/y配置の事実を示すが、意味上のreading orderをZ0でproduction確定
していない。DOM上の`page_N` labelとscreen geometryの対応はartifactで確認できる。

## Identity / END / NEXT_CONTENT candidates

URL identityは全stateでtitle/chapter targetと一致した。document title、visible heading/meta、
data-*、page alt、page counter、chapter/title link候補を保存した。

初期DOMで`< 次の話`というbuttonは観測したが、next chapter/next storyの可能性があるため
クリックしていない。chapter末尾へは進んでいないため、END screen、completion state、final
page後の遷移、next chapter IDは未確認である。`1 / 25`等のcounter候補はEND判定のproduction
実装には使わない。

## Capture candidates

Z0のassessmentは次のとおり。

| method | status | 根拠 |
| --- | --- | --- |
| original response bytes | possible | asset image responseとblob body候補の元bytesを保存できたが、visible pageとの一対一対応は未証明 |
| source-native | possible | page-like imgのblob source、natural dimensions、DOM sizeを観測したが、production用の安全なsource attributionは未確認 |
| native reconstruction | unknown | drawImage/canvas mappingが未観測で、再構成実装は未作成 |
| canvas | rejected for this run | visible canvas/drawImageはnot observed |
| locator screenshot | possible | page-like img locator候補とviewport screenshotは取得できたが、本文のみlocator screenshotは未保存 |

Z0ではcapture方式を決め打ちせず、production Site Adapterへ変更を入れていない。

## Next investigation (Z1)

次のZ1では、同じtarget chapter内で以下だけを追加確認する。

1. asset response元bytesとblob bodyの対応を、同一state・page alt・byte length・decode結果・
   必要なら安全なpixel比較で検証する。暗号化/scramble/tile reconstructionと推測しない。
2. blob sourceがそのまま表示page bytesなのか、blob生成前に復号/変換されるのかを確認する。
3. spreadのpage_Nとx/yから、productionで許せるreading orderとcapture単位を明示的に検証する。
4. page counterの意味、current/totalの安定性、END/NEXT_CONTENT signalをchapter末尾へ行かずに
   script/DOM/networkから追加観測する。
5. free/毎日無料/paid等がviewer内に表示される別安全な状態があるかを確認する。ただし
   resource消費、購入、レンタル、広告視聴、ログインは行わない。

## Known limitations

- 対象はこの1 title/chapterだけで、他chapter・別title・別access stateは未確認。
- CSS module class hashはlive observation artifactであり、production selectorのauthorityではない。
- cross-origin frameの内部viewer構造は調査していない。
- response body保存は最大20件で、network responseの全body保存ではない。
- Z0 artifactの画像候補は実サイト著作物を含み得るため、fixtureやCI入力として扱わない。


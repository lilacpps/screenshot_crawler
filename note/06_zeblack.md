# Zebrack Z0/Z1 viewer probe 現行観測ノート

## Scope

これはゼブラック（Zebrack）の新規Site Adapter開発前に行う、対象chapter限定の
read-only viewer probe記録である。Production Site Adapter、Discovery、Site Policy、
Batch、access resource消費、login automationは未実装である。Z0/Z1では観測できた事実と
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

Z1は通常Z0と分離した明示的opt-inである。

```powershell
.\.venv\Scripts\python.exe poc\zeblack_probe.py `
  --url "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer" `
  --output-dir "output\zeblack_probe" --steps 3 --z1
```

Z1 artifactは `output/zeblack_probe/z1/` に保存し、`report.json`、
`comparison.json`、`summary.md`、`pages/page_NNN.jpg`、各stateの`z1.json`を含む。

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

## Z1 live verification (2026-09-27)

shared Crawler Chromeで上記targetだけを`--z1 --steps 3`で実行した。initialを
`state_000`として、`state_001`〜`state_003`へArrowLeftでbounded navigationした。
全3回が`changed_and_stable`で、全stateのURLはtarget chapterのままだった。access、
ticket、購入、ポイント、コイン、広告、login、next chapter controlは操作していない。

### Visible page image attribution

Z1は全`img`から厳密な`alt=page_N`を抽出し、visibility、inViewport、natural size、
rendered x/y/width/height、`src`、`currentSrc`、document.imagesのDOM orderを保存した。
本文候補として採用したのは、exactな`page_N`、natural sizeが非zero、visible、viewport内で、
source URLが`blob:`であるものだけである。viewer/class hashは補助metadataであり、唯一の
authorityにはしていない。本文外画像をpage画像として推測していない。

今回のstable stateは次のpage集合だった。

```text
state_000: page_0
state_001: page_1 (x=953, 右), page_2 (x=259, 左)
state_002: page_3 (x=953, 右), page_4 (x=259, 左)
state_003: page_5 (x=953, 右), page_6 (x=259, 左)
```

各pageのnatural dimensionsは`760x1080`、表示サイズはおよそ`693.84x986` CSS pixels
だった。DOM orderはscreen左右順と同一とは限らないため、x/yからlogical orderを推測しない。

### Blob retrieval and encoded JPEG

各current stateでvisible imgのblob URLを完全一致で記録し、まず同じPage内の
`fetch(blobUrl)`を試行した。しかし今回の実サイトでは、表示中のimgが描画を継続していても、
後発の`fetch(blob:)`は全7件で`TypeError: Failed to fetch`になった。state遷移後の
lifetime checkも2件（page_0 after state_001、page_1 after state_002）を行い、両方とも
fetch不可だった。従って、後から同じblob URLを取得できるとは仮定しない。

Z0から継続している同一Playwright Pageのresponse listenerが、blob URLのresponse bodyを
load時にbounded保存していたため、Z1は`blob_url`の完全一致が確認できる場合だけ、その
既取得bodyをfallbackとして比較した。外部HTTP clientでblob URLを取得せず、別URL、asset
URL、byte順推測へのfallbackも行っていない。今回の7件は全て
`bytes_source=playwright_blob_response_body`で取得できた。

7件すべてで次を確認した。

- detected format: `JPEG`
- dimensions: `760x1080`
- JPEG decode success: true
- encoded bytesは再encodeせず`pages/page_000.jpg`〜`page_006.jpg`へ保存

### Pixel equivalence

各blob response bodyをPillowでRGB decodeし、SHA-256を計算した。同じstable stateの
visible `HTMLImageElement`をnatural size`760x1080`の一時canvasへ描画し、CSS表示サイズや
viewport/device scaleを入れず、RGBAからRGBだけを取り出してSHA-256を計算した。

`page_0`〜`page_6`の7/7で、decoded JPEG RGB hashとvisible img RGB hashが完全一致した。
canvas read時のSecurityErrorは発生せず、mismatch、inconclusive、unavailableは0件だった。

判定は次のとおりである。

```text
blob JPEG direct capture: confirmed
pages: 7
exact_pixel_match: 7
mismatch: 0
inconclusive: 0
unavailable: 0
```

これは今回の対象chapter・対象state・対象page集合でのlive verificationであり、他chapterや
別access stateへの一般化ではない。

Z1 verdictの集約はfail-closedである。`confirmed`は、今回の検証対象として採用した全pageが
`exact_pixel_match`で、minimum page数、stable ordering、spread、gapなしをすべて満たす場合
だけにする。1件でも`unavailable`または`inconclusive`があれば全体を`inconclusive`とし、
1件でも明確なpixel/dimension `mismatch`があれば`rejected`とする。empty、duplicate index、
malformed index、ambiguous ordering、non-monotonic transitionもconfirmedにしない。

`exact_pixel_match`には、JPEG decode dimensions、HTMLImageElementのnatural dimensions、
canvas read時の`img_pixel_dimensions`の3者一致と、decoded RGB hash / HTMLImageElement RGB
hashの一致をすべて要求する。dimensionsまたはhash等の必要metadata欠落はexactと推測せず、
`inconclusive`として扱う。

### Page_N attribution / spread / reading order

`page_N`の観測indexは`[0,1,2,3,4,5,6]`で、欠落・malformed alt・duplicate indexは
なかった。state間のpage集合は単調に進み、spread内の左右両pageを別々のblob URL、JPEG
bytes、pixel hashとして検証できた。page counter候補は既存DOM artifactで
`1 / 25`、`2 / 25`、`4 / 25`、`6 / 25`だった。

したがって、このbounded runでは次が安定した。

```text
logical page order candidate = numeric page_N ascending
```

screen左右位置、DOM order、page counterは対応証拠として保存するが、logical page orderの
authority候補は`page_N`の数値順である。missing、duplicate、non-monotonic transitionが
出た場合はconfirmedにしない実装にしている。

### Asset responseとの関係

同じstateの`asset.zebrack-comic.com` image response候補はtimestamp、URL、content-type、
content-length、body保存結果としてartifactに記録した。今回もasset側の`image/jpeg`
response bytesはJPEG decode不能だった。一方、exact blob URLのresponse bodyはJPEG decode
可能でvisible imgとpixel exact matchした。

asset responseとblob生成の一対一生成時刻・変換過程は観測できていないため、asset bodyから
blob bodyへのmapping、暗号化、scramble、tile permutation、compression方式は推測していない。
同一stateに存在することは記録したが、asset transport bytesをcapture sourceとして採用していない。

### Capture strategy conclusion

今回のZ1証明により、このchapterについては次をZeblack固有の最上位capture候補としてよい。

```text
visible HTMLImageElement
  -> exact blob URL / blob response bytes in the same browser context
  -> encoded JPEG bytes
  -> unchanged .jpg save
```

`CAPTURE_STRATEGY.md`のshared hierarchy自体は変更していない。用語上は、visible pageに
一対一対応しdecode pixelsもexact matchしたencoded source bytesなので、Level 1 original
bytesに相当するdirect-source候補として扱える。ただし、client側のblob生成過程やasset
transportの原形式までoriginalと断定するものではない。重要なのは、PoCがJPEG bytesを
再encodeせず保存できたことである。

Production Site Adapterはまだ実装していない。productionでは、blob URLのlifetimeに依存せず、
stable stateで必要なbytesを即時に確保する必要がある。fetch(blob:)が失敗する実サイト状態を
踏まえ、response body listener等の同一browser context内の取得経路を、別Phaseでproduction
設計として明示検討する。

## Capture candidates

Z0のassessmentは次のとおり。

| method | status | 根拠 |
| --- | --- | --- |
| original / direct blob response bytes | confirmed for this Z1 run | 7ページでJPEG decode、natural dimensions一致、visible img native RGBとのexact matchを確認。production Adapterは未実装 |
| source-native | possible but not selected | encoded blob bytesが直接使えるため、source pixelの再materializeは不要。別chapterへの一般化は未確認 |
| native reconstruction | unknown | drawImage/canvas mappingが未観測で、再構成実装は未作成 |
| canvas | rejected for this run | visible canvas/drawImageはnot observed |
| locator screenshot | possible | page-like img locator候補とviewport screenshotは取得できたが、本文のみlocator screenshotは未保存 |

Z1ではdirect blob response bytesを対象chapter限定でconfirmedとしたが、production Site Adapter
へは変更を入れていない。

## Next phase

次Phaseでは、Z1の境界を越えない範囲で次を検討する。

1. production Adapterへ入れる前に、同じsafe capture契約をsite-specific実装として分離し、
   current stable stateで即時取得・bounded memory・all-or-none spreadを設計する。
2. 別chapterで同じ`page_N`/blob response/pixel exact条件が成立するかを、access操作なしで確認する。
3. END/NEXT_CONTENT、別access state、loginは別phaseのread-only調査とし、Z1のdirect capture
   結論へ混ぜない。
4. asset transport bytesの復号・scramble・tile解析は、blob direct captureが利用できる限り行わない。

## Z2 live verification (2026-09-29)

This section supersedes the preceding pre-Z2 statement that chapter-end behavior had not yet been observed. The older text is retained only as the Z0/Z1 investigation history; the current terminal understanding is the one below.

The research-only Z2 probe was run against the same target chapter using the shared Crawler Chrome and bounded `ArrowLeft` navigation (`13` successful advances; hard cap `100`). No next-chapter, access, purchase, ticket, point, coin, advertisement, or login control was clicked. The target host/title/chapter/viewer identity stayed unchanged for every before/after operation.

Observed page progression was:

```text
state_000: page_0, page_1, page_2       counter 1 / 26
state_001: page_1, page_2, page_3, page_4 counter 2 / 26
state_002: page_3, page_4, page_5, page_6 counter 4 / 26
...
state_011: page_19, page_20, page_21, page_22, page_23 counter 22 / 26
state_012: page_21, page_22, page_23 counter 24 / 26
state_013: page_23 (not in viewport) counter 26 / 26
```

The final content state was `state_012`: `page_23` was the only in-viewport `page_N` image and the counter was `24 / 26`. One further `ArrowLeft` transition produced `state_013`, where no `page_N` image was in the viewport and the counter remained visible as `26 / 26`. The terminal screenshot showed the end-of-viewer UI, including `次の話を読む` with `2話`, comment/favorite controls, and recommendation content. This is a NEXT_CONTENT candidate, not a click or an observed next-chapter navigation.

The earlier partial Z1 artifact recorded a `1 / 25` counter, while this full Z2 run recorded `1 / 26` through `26 / 26`. That discrepancy was not resolved in this probe; the denominator is therefore evidence only and must not be treated as a standalone total-page authority.

The first terminal transition was therefore the advance from `24 / 26` to `26 / 26`. The URL remained the target viewer URL; no automatic chapter change was observed. A next-content DOM button was observed without an `href`; no next-chapter identity was obtained from a clickable chapter link. Recommendation links were recorded as recommendation evidence only and were not treated as next-chapter authority.

The Z2 report classification is:

```text
Zeblack terminal behavior: next_content_confirmed
```

The classifier is fail-closed: it does not treat a page counter or a no-change result alone as END. It requires current-chapter identity, stable transition evidence, disappearance of in-viewport page content, and explicit terminal evidence. `end_confirmed` was not observed in this run; the observed terminal signal was NEXT_CONTENT. This probe does not implement production PageState or click the next-content control.

Production Adapter recommendation: retain `page_N` numeric tracking for content order, treat `26 / 26` as supporting evidence only, and classify the terminal state as `NEXT_CONTENT` only after the same current-chapter guard and explicit visible `次の話を読む`-type evidence. Keep the next-content action non-clicking. Behavior for other chapters, access states, login states, and a separate explicit END UI remains unknown.

## Known limitations

- 対象はこの1 title/chapterだけで、他chapter・別title・別access stateは未確認。
- CSS module class hashはlive observation artifactであり、production selectorのauthorityではない。
- cross-origin frameの内部viewer構造は調査していない。
- response body保存は最大20件で、network responseの全body保存ではない。
- Z0 artifactの画像候補は実サイト著作物を含み得るため、fixtureやCI入力として扱わない。

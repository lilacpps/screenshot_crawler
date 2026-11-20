# 14. YanmagaWeb (`yanmaga.jp`) 現行実装ノート

## 日表示のgrant期限と他サイトとの整合（2026-11-21）

妹は知っている第10話（Item 50769 / Source 51076）は、実サイトの正確な同話Rental Historyが
active・残り1日であった一方、旧計算の`(D-1)日`ではD=1が期限なしとなりunknownに留まった。
この1日控除は日表示の丸めを未確認のまま置いた保守的仮定で、ヤンマガでその丸め方を
実測した根拠はなかった。現行cardには正確な終了日時のattribute/time/scriptは確認できない。
マガポケの表示残り時間→既存grant field、はなゆめの表示期間−1時間の実装を参照し、
ユーザー指定に従って日表示を`観測開始 + D日 - 1時間 - 5秒`へ変更した。

`access_granted_until`は日表示の場合には取得可否の目安であり、正確な終了日時や証明済みの
lower boundではない。evidenceも`site_day_countdown_estimate`として時間表示と区別する。
D=1..3はそれぞれ約23/47/71時間となり、既知quotaの期限がまだ未来でも、fresh有限観測で
更新する。以前のfree/paidのtrusted-grant保存契約は維持する。期限内の候補は既存Policyでdirect。
保存期限が未来でもSource entry前にexact active Rental Historyを再確認し、不在/失効なら入場しない。
Discoveryがcomplete inactiveを確認したら期限をclearし、既知quotaはquotaへ戻す。
チケットへの暗黙fallback、消費の推測、既存quota履歴の書換えは行わない。
H時間の既存lower-bound計算・H=1の契約、first-freeのhour-only証明、共有の
`ConfirmedAccessGrant`証明型・Core/Policy、他サイトの実装は変更しない。

ignored証拠は`output/yi10/`。初回の`current-evidence.json`はactive days=1で有限期限なし、
`history-attributes.json`は正確な期限metadataがないことを記録する。宣伝popupがMoreを遮った
最初の手動probeは失敗したが、productionと同じinnermost close selectorで×を1回押し、
`listing-evidence.json`でpopup非表示・同話のbadgeなし一覧を確認した。
調査中に実サイト表示が残り1日から残り23時間へ変わったことを`post-estimate-history.json`で確認。
したがって現在の実サイト更新は23時間表示の経路であり、変更後のD=1計算は人工browser testで検証する。
standalone backupと隔離CLI Full（98件complete/exhausted）でunknown→quota・future grant・
追加消費なしのdirect判定を確認した。別途fresh backupを作成した通常CLI Fullも98件complete/
exhaustedで成功し、free 6 / quota 90 / paid 2 / unknown 0となった。
Source 51076の保存期限は11月22日03:41 JST（現在の残り23時間表示からの下限）へ更新された。
既存有効grantでの実サイトdirect確認は本文1枚を保存し、max_pages=1で意図的に停止。
全話完走/ZIP成功は主張しない。前後話・first-party non-GETの試行は0、チケット消費なし。
`reader-check-report.json`、`day-estimate-audit.json`が結果で、WorkのItem status、Run/Artifact、
quota_started_atは通常反映前と一致する。正確な終了日時が公開されないという制約は残り、
日表示の期限だけで入場許可は出さず、直前のlive active proofを維持する。

テストはD=1/2/3の1時間控除、既存quotaのfuture期限更新、失効時clear、未知/重複履歴の拒否を
含むDiscovery/Policy UnitとDiscovery/Rental History browser Integrationが258件成功、skip 0。
Adapterのhistory/existing-grant/day-grant/grant-only選択は33件成功（231 deselected）、skip 0。
日数1/2の新規消費確定後のdeadline保存と、期限が未来でも実サイトinactiveならSourceへ入らない
hour/day両方の境界を確認した。targeted 12件も成功。既存asyncio deprecation warningのみ。
`ruff check src tests`、変更ファイルの`git diff --check`は成功。
full pytest、他サイトIntegration、既存Research suiteはYanmaga局所変更のため未実行。
マガポケ・はなゆめは参照のみで、実装を変更していない。

## 再レンタルの再確認・閲覧期限更新・quota復帰（2026-11-20）

パラレルパラダイス第10話（Item 50004 / Source 50311）はCatalog上の旧期限が
11月19日05:16 JSTで切れ、一覧もbadgeなしのためunknownだった。しかし、現行の実サイトでは
後続のレンタル履歴ページにexact targetの「残り6時間」があり、閲覧可能だった。
修正前のpositive-only `fetch_rental_history_countdowns()`は先頭ページだけを見て`absent`とし、
全ページを扱う既存`fetch_rental_history_observations()`はactive 6時間を正しく返した。
古い期限だけを原因とした説明では不十分で、現在の権利の取りこぼしが実際の原因だった。

現在はpositive-onlyのdirect-entry確認もnative Moreがあれば既存の有界GET/Turbo pagingを行う。
native collection、index/offset、全URLの一意性、stream形、fresh response headers、
50ページ/1000行/4MiB等の上限は維持する。画像・話・Viewerへ遷移して権利を得る処理ではない。
Moreなしの従来positive-only card proofは維持する。
Discoveryはcomplete active/inactive observationsを使用し、期限切れ/未保存の古いgrantがあっても
exact active rentalの有限期限を取り込み、quota Sourceと期限付きdirect判定へ更新する。
完全な履歴で対象の不在/期限切れを確認した場合は、`access_granted_until_observed=true`とnullを
明示して旧grantを消す。既知quota Sourceが一覧上unknownであればquota分類を維持する。
過去のfree/paid/unknownをinactive根拠だけでquotaへ変えず、実際のticket利用可否・消費確認は
従来のlive wait-marker/entry proofを要求する。unknown/partial/重複履歴では期限切れを推測しない。
新しいCLI/設定・Catalog schema・共通Policy/Coreの変更はなく、Item status/Run/Artifact/
quota_started_at/Work resource stateは更新しない。

証拠はignored `output/yr10/`。`history.json`に修正前positive-onlyとcomplete APIの比較を保存。
通常Catalogのstandalone backupを作成し、隔離Catalogの50311だけを実際の旧unknown/旧期限へ
戻した入力で通常CLI Full Discoveryを検証した。348件complete/exhausted、free 7 / quota 339 /
paid 2 / unknown 0、Source 50311はquotaと11月21日03:38 JSTまでの保守的な有限grantへ回復した。
これは読取時の残り時間から計算した下限で、実際の正確な終了時刻ではない。
別の実サイトdirect確認では保存済み有効grantを使用し、本文1枚の保存まで到達、
max_pages=1で意図的に終了した。完走/ZIP成功の主張ではない。新しいresource消費・前後話アクセスは0。
通常Catalogも再Discovery済みで、同Sourceはquotaと11月21日03:32 JSTまでのgrantへ更新されている。
この作業で通常Catalogへ直接SQLを書いたり、旧quota消費履歴を消したりはしていない。

テストはDiscovery/Policy Unit + Discovery/Rental History browser Integrationが249件成功、
追加したinactive/unknown/重複履歴と既知quota/paid/unknownの境界を含むDiscovery Unit全67件も成功。
Adapter入口のhistory/existing-grant選択は27件成功（233 deselected）。全実行でskip 0。
targeted 68件も成功。既存のpytest-asyncio/Python deprecation warningのみ残る。
`ruff check src tests`と今回変更ファイルの`git diff --check`は成功。
full pytest・他サイトIntegration・既存Research suiteはYanmaga局所のmetadata/権利確認変更のため未実行。
第10話の実サイトは上記read-only history、通常Discovery CLIの隔離検証、direct本文1枚で確認した。
全話capture/packagingはこの変更の検証範囲に含めない。`stale-live-audit.json`はunknown/旧期限からの
再取得分類、grant更新、追加消費なしとItem status/Run/Artifact/quota履歴の不変を確認している。
残り1時間等で安全な有限下限が得られない場合の既存の保留契約は維持する。
期限切れ後のquota復帰と再レンタルの状態遷移は人工browser/Policy境界で確認済み。

## パラレルパラダイス345話：1127幅profileと先頭確認（2026-11-20）

Item 49668 / Source 49975の通常Batch保存途中Manifestは、全保存ページで
`unsupported_native_geometry`によるPNGだった。前節のbuffer overflowとは異なる。
実サイトの隔離probeでpage 1のlogical box 1267.875×1800 CSS px、倍率1.125、
source segment 1129×536 / 1129×536 / 1129×538、Y位置0/598.5/1197 CSS pxを確認した。
論理ページは1127×1600で、既存1125×1600 / segment幅1127の固定profileに適合しなかった。
observerも幅1129のcanvasを対象外としており、candidate数は0だった。

現在は明示的な二つのprofileだけを許可する。logical widthは1125または1127、height=1600、
CSS倍率1.125、logical boxの許容差0.03 CSS px、segment幅はlogical width+2を要求する。
segment高さ536/536/538、native Y offset 0/532/1064、末尾crop、opaque/style/ownership、
exact byte binding、画素履歴、最終group proofは従来どおり。未知の幅、縦横比、混在profileは拒否。
observer、browser compositor、Pythonのlossless WebP encoder、Adapterの最終寸法検査を
同じ対応幅へ更新した。上限、navigation timing、他サイト・共通Core・Catalogの契約は変えない。

最初のprobeではcounter 1/19で`前の話を読みますか？`が表示され、menu hiddenを証明できず
保存0枚で停止した。ユーザー確認とnative「キャンセル」の実操作で、この表示が先頭位置であり、
キャンセル後も同じ話・同じcounterのまま通常captureできることを確認した。
初期化中、保存前のcounter 1かつ既知menu表示時に限り、単一のvisible `#wrap-popup`、
direct `#popup-header`のexact文言、direct footer配下の単一enabled/visible
`button#popup-cancel-btn`のexact `キャンセル`を検証し、一度だけクリックする。
2秒以内のpopup非表示とroute/counter/total不変を確認し、その後も既存menu非表示・全周ownership・
本文安定性を要求する。「読む」リンクは辿らない。不明/重複popupや再出現はfail-closed。
metadataに`previous_episode_prompt_cancelled`を追加。新しいCLI/設定はない。

証拠・QA scriptはignored `output/yp345/`。`baseline/`は確認popupで停止した初回、
`baseline2/`はQAによるCancel後の2ページPNGと実測layout（max_pages=2で意図的停止）。
`fixed/`は最終Adapter寸法guardの更新前に止まった途中runであり、完了証拠ではない。
最終の`fixed-final/`はQAによるCancel代行なしのproduction Adapterで全19ページを保存し、
positive ENDに到達した。全19枚が1127×1600 native pre-JPEG lossless WebP、PNG 0枚。
最初のMetadataで`previous_episode_prompt_cancelled=true`、最終ページで完全な19枚sequence、
native counter、同話route、隠れたmenuとfresh immediate-next signup cardのEND証明を確認した。
57 segmentのcanvas copy / exact binding、曖昧候補・miss・read failure・overflowは0。
各ページで、選択されたbound observerのimmutable pre-JPEG配列を別QA compositorで合成した
referenceと保存WebPのRGBA全byteが一致した。これは同じobserver配列の合成結果の検証であり、
observerのprovenanceを別の独立observerで証明したという主張ではない。
`native-checks.json`、`report.json`、`audit.json`に結果を保存した。
19枚のVP8L/opaque decode、1127×1600、unique hash、Manifest順序/identity/hash、
調査用ZIPのCRC/全member/hashが一致。ZIP SHA-256は
`0f41ba551f8a0971b4b9e0ca0c17882772de703d315342fda0d52e5308320cb0`。
ZIPは`fixed-final/parallel-paradise-345-verified.zip`。
通常Catalogのinterrupted/running履歴や既存ZIPは変更しない。

テストは幅1125/1127のencoder・native・再生成・decoded経路（pixel collision、binding欠落、
非JPEG、buffer上限）、既知popupのCancel・不明文言/誤button/重複buttonの拒否を含むtargeted
23件が成功。Unit全11件も成功。全幅を任意に受け入れる変更や判定の迂回は行っていない。
完了時のaffected selection（同Unit + Adapter browser Integration、
`-k 'native or decoded or capture or previous_episode_prompt'`）は93件成功、178件deselected、
skip 0（311.94秒）。既存のpytest-asyncio/Python deprecation warning 5件のみ。
`ruff check src tests`と今回の6ファイルの`git diff --check`は成功。
full pytest、他サイトIntegration、既存Research suiteはsite-local capture/初期化変更のため未実行。
実サイトは当該無料公開話の共有CDP隔離runで確認済み。通常CatalogへのBatch書込み、
既存ZIPの置換、前後話への遷移や新しい権利消費は実施していない。

## 長い話のcapture buffer上限とdecoded-source経路（2026-11-20）

通常Catalog Item 50361 / Source 50668、サタノファニ第1話（62ページ）の
Run 26990のZIPはWebP 1〜35、PNG 36〜62だった。既存ZIPにはManifestが含まれず、
当時のobserver内部イベントは保存されていない。共有CDPの同じ無料公開話への隔離probeで、
同じ36ページ目から`capture_buffer_overflow`になることを再現した。
36ページ目前の累積encoded保持量は33,535,112 bytes（上限33,554,432 bytes）、
totalCandidates=123、raw pixels=43,547,280 bytes、pending/inFlight=0、
hook conflict・ambiguity・read failureなし。次のJPEG payloadを追加すると
32 MiBのencoded上限を超える。raw-pixel上限256 MiBやcandidate上限192ではない。
encoded counterは`seenPayloads`のpayload key保持も含む累積budgetなので、
capture済みページのpixel解放後にも減らない。単純なcounter減算は保持量を過小評価する。

現在は`segment_source_not_exactly_bound`に加え、`capture_buffer_overflow`でも
既存のdecoded-source経路をvisible group全体で試す。Observerの上限・停止状態は維持し、
pre-JPEG証明には使わない。decoded経路だけが当該buffer overflowを許可し、
表示中の実img、bounded JPEG Blob、元解像度、opaque sRGB、geometry/style、
最終atomic group proofとlossless WebP round-tripを従来どおり検証する。
hook conflict・他種overflow・不明source/styleではこの例外を認めない。
decode経路不成立は引き続きPNG、本文identity変化は停止する。
metadataは`decoded_viewer_segment_lossless_webp` / `pre_jpeg_pixels_used=false`、
元の`fallback_reason=capture_buffer_overflow`を残す。新しい設定/CLIはない。

調査出力とQA scriptはignored `output/yanmaga-satanofani-investigation/`。
`baseline/observations.json`と`baseline/capture/manifest.json`が修正前証拠。
baselineは38ページの上限で意図的に停止しEND/packagingは行っていない。
通常Catalog・既存ZIPは変更せず、ZIP hashの一致も確認している。

修正後の隔離`CrawlerRunner`は全62ページ、PNGなし、positive ENDに到達。
この再訪は初期reading position/先読みによりraw-pixel上限へ先に到達し、
page 1時点で110 candidate / 266,116,256 raw bytes / 29,885,660 encodedだった。
capture前のcap到達でも同じ例外経路が働き、全62枚がdecoded-source WebPとなった。
元の35/27境界が常に再現するとは限らず、native pre-JPEG画素を全62枚回収したという意味ではない。
各ページで別の直接DOM-image合成referenceとの全RGBA一致を確認し、全62枚の
1125×1600、opaque single-frame VP8L、unique fingerprint、Manifest順序/identity/hashを検証した。
調査用`fixed/satanofani-chapter-01-verified.zip`はManifestの62ファイルだけを含み、
CRC・順序・hashが一致。SHA-256は
`ee6c9d8cf12fd1312060ca72ab82015fc4afb99b0a08a2e6ecdf8cfc8f7199f1`。
`fixed/decoded-checks.json`、`fixed/report.json`、`fixed/audit.json`が検証結果。
通常Item completed、2 Run、2 Artifactと既存ZIP hashは変わっていない。

テストは修正前に追加したencoded-buffer上限の既存browser case拡張が期待どおり失敗し、
修正後はdecoded画素一致・native pixel上限のtargeted 5件が成功。
`tests/unit/test_yanmaga_adapter.py`全10件も成功。
同Unitと`tests/integration/test_yanmaga_adapter_browser.py`の
`-k 'native or decoded or capture'`では78件成功、178件deselected。
残るgrant-onlyの1件は調査用長いbasetempで`entry_trace.json`の絶対pathが262文字となり
ファイル保存検査で失敗した。同一testを短い`output/ysfgrant`へ変更して再実行し1件成功。
production codeの追加変更は不要だった。全実行でskipは0。
`ruff check src tests`、今回の5ファイルの`git diff --check`は成功。
全worktreeのdiff checkには既存ユーザー変更の`watchlist.yaml:1856`の末尾空白が残る。
既存pytest-asyncio/Pythonのdeprecation warningのみ継続。
全体pytest、他サイトIntegration、既存Research suiteはsite-local capture変更のため未実行。
実サイトは当該無料公開話の共有CDP隔離runで確認済み。通常Catalog/ZIPを再取得版へ置換する
操作は行っておらず、既存Archiveの`FALLBACK_INCLUDED`判定自体は残る。

## リンクのない公開予定行を含む一覧（2026-11-19）

妹は知っている第95話（Item 50683 / Source 50990）は、Viewer前の作品一覧preflightで
`Yanmaga episode URL does not match its work`となり保存0枚で停止していた。
metricsの403/429/5xxは0。末尾の第98話が、リンクも本文title要素もない
`div.mod-episode-link.mod-episode-nopublic`の公開予定行だったため。
保存DOMとshared-CDPの作品一覧GETで、同一作品の`data-original-url`、
`data-episode-title`、`次回公開予定：`と`2026/11/24(火)`のnative構造を再確認した。

現在は単一の末尾公開予定行だけをsite-localな`unpublished=True`で保持する。
既知のLI/div/body/text/p/span/time構造と表示、リンク・button/form/input/role control・
無料/価格/wait/modal markerがないこと、`data-is-free=false`、
`data-modal=registration`、非空title、同一作品のstrict話URL/一意IDを検証。
日付は既知の日本語書式・実在する暦日・正しい曜日を要求し、日付から公開済みや
アクセス可能とは推測しない。不正/重複/途中の予定行、通常行のURL欠落はfail-closed。

予定行は内部snapshotの順序、安定性、重複検出、Moreのoffset、直後話/最新話判定に
残すが、Discovery recordをemitせずCatalogのItem/Source/targetには登録しない。
レンタル履歴照会からも既存grant候補を含めて除外し、hidden URLへは遷移しない。
既存公開話のdisplay positionはnativeのまま。公開後に通常行へ変わった時だけ通常の
分類・Discoveryへ入る。CLI/設定・Core/Policy・Catalog schemaに変更なし。

修正後のlive Fullで内部99行（公開予定1行）から公開済み98件を取得した。
該当第95話はpublic-freeでfirst-freeではないことを確認し、通常Catalogのread-only
backupと専用出力でRunnerを実行。本文index 1..20を保存しcounter `20/20`でEND、
全20画像のmanifest SHA-256一致を確認した。first-free observerは付けず、
first-free未試行・first-party non-GET試行0。通常Catalog/Watchlistと元の失敗出力は
変更していない。証拠は`.tmp/yanmaga-unpublished/probe.json`、
`discovery-result.json`、`live-result.json`、`live-capture/`。
通常11候補Batch全体は再実行していない。

検証はDiscovery Unit＋人工browser全体154件と、Adapter identity/Runner/Batch-ZIP/
失敗時pending維持のaffected 8件が全PASS、skip 0。公開予定行の正常/不正構造、
別作品URL・欠落・日付/曜日・リンク/無料badge混在・非表示・重複・途中配置、
More展開、incremental、公開後の通常登録、履歴候補からの除外を確認した。
`ruff check src tests`と本変更5ファイルの`git diff --check`もPASS。
site-localな一覧metadata処理のみの変更のためfull pytest、独立Research suite、
native encoder内部testは未実行。該当話の未解決failureはない。

## 評価カードと作者フォローの併設終了（2026-11-19）

サタノファニ第345話「戦争」（Item 50014 / Source 50321）は本文20枚を保存後、
counter `20/20`の終了判定で`go_next` timeoutになった。metricsの403/429/5xxは0。
保存診断では評価カード自体・本文全保存・非遮蔽は成立していたが、併設された
作者フォローlinkを評価カードbranchの「作者linkなし」条件が拒否していた。
独立の作者branchもnative X profile URLの`?s=20`を拒否していた。
保存DOMとshared-CDPの専用Pageでこの構成を再確認した。

現在は最終本文併置の評価カードに、単一のexact作者linkを許可する。
既知のhierarchy内で評価button群の直後の同一parentのsiblingであること、
exact label/class、loadedな既知2画像、表示・非遮蔽を検証する。
HTTPS `x.com`の単一profile path、credentials/port/fragmentなしを維持し、
queryは「なし」または実観測の完全一致`?s=20`だけを受け入れる。
重複・非表示・不正query・外部origin・未知asset/label・位置違いは拒否する。
評価form/shareの同一話identity、全本文index連続保存、最終本文とrentalの表示・
周辺非遮蔽、menu非表示、未知gate拒否は維持。独立作者branchの最新一覧row条件も
維持し、評価branchは従来の同一話form/share proofを使う。リンクは操作しない。
terminal-onlyの評価card単独許可、timeout延長、CLI/設定/Core変更はない。

通常Catalogのread-only backupへ既存grant/observerを隔離したRunnerで、該当話の
`max_pages=20`のまま本文20枚保存→positive END、counter `20/20`を確認した。
全20枚のSHA-256は元の失敗runと一致。first-free未試行、first-party non-GET試行0。
通常Catalog/Watchlist・元の失敗出力を変更していない。証拠は
`.tmp/yanmaga-engagement-author/probe.json`、`live-result.json`、`live-capture-v2/`。
通常50件Batch全体の再実行は行っていない。

検証はtargeted browser 28件、Adapter Unit 10件、既存終端/1ページ/terminal-only/
counter先行/menu/Runner/Batch連携のaffected browser 108件が全PASS、skip 0。
作者linkの同一parent内の順序違いもfixtureを強化して1件再確認しPASS。
`ruff check src tests`と変更4ファイルの`git diff --check`もPASS。
site-localの終端条件修正のためfull pytest、独立Research suite、変更していない
native encoder内部testsは未実行。CLI/設定の追加や未解決の該当話failureはない。

## 1ページ作品のメニュー非表示と終了（2026-11-19）

パラレルパラダイス「【会員限定無料】ヤンマガカバーガール風イラスト」
（Item 49770 / Source 50077）は本文counter 1/1・既知の初期menu表示中で停止し、
保存0枚だった。既存のmenu cleanupが「2ページ目へ進めて1ページ目へ戻す」方式で、
1枚だけの本文を明示拒否していたため。今回のmetricsも403/429/5xxは各0。

配信済みparent/custom_parent JavaScriptのkeyCode 68のmenu toggleと、shared-CDPの
専用Pageで`d`キー1回→menu非表示・counter 1/1不変を確認した。1ページかつ
既知のmenu/header/controller/transparent overlayでのみ、このnative keyを1回使う。
同一Viewer route・current=total=1を保ち、menuがdisplay:none・zero dimensions、
本文のcenter/perimeter非遮蔽、画像geometry・安定readを満たすまでbounded waitする。
非表示済みなら押さず、閉じない/identity変更/未知overlayでは停止。CSSや内部関数は
操作しない。2ページ以上の既存roundtripは維持する。

本文1枚保存後のnative ArrowLeft 1回で`-/1`、本文wrapperが右viewport外、
右半分1272×1800のrental cardになることも確認した。private terminal modeにN=1を
追加し、全保存index=[1]の後だけこのterminal turnを許可する。通常counter parser、
terminal-onlyでのidentity/capture禁止、max_pages・same-content guardは維持する。
単に1枚保存しただけではENDにせず、既存のstrict layoutとpositive card proofが必要。
N=2のdash layoutは未確認のため未対応。

今回の終端は「第244話」のready wait cardだった。単一`#js-btn-rental`配下の
`form.ga-viewer-rental-free-wait`、same-origin POST `/viewer/rental`、一意のhidden
20英数字`jdcn`/`rental_type=free_rental_if_wait`、exact label
`「待つと無料....！」で読む`、同じcodeのloaded thumbnail、必要point表示なしを検証する。
カード全体/title/controlの表示と非遮蔽、freshな同一作品一覧の一意の直後row/titleと
wait marker（public-free/first-free/red/restrictedとの競合なし）も必須。
既存point-rentalの共通form/thumbnail検証を保持し、paid/ready-waitの条件を分ける。
カードをclick/submitせず、チケット利用可否・消費やPolicyの判断は変更しない。
diagnosticsに`ready_wait_rental_exact`を追加。CLI/設定・Core・capture形式は変更なし。

変更後の同一作品を、通常Catalogのread-only backupに既存grant/observerを隔離し、
shared-CDPの専用PageでRunner確認。`max_pages=1`のまま1枚保存→positive END、
counter `-/1`、全保存index=[1]、exact terminal layout/ready-wait proofを確認した。
1125×1600のnative pre-JPEG lossless WebPをhash検証し、画像の目視でも本文1枚だけで
reader menu/終端cardが混入しないことを確認。first-party non-GET試行0、first-free
未試行。通常Catalog/Watchlist・元の失敗出力は変更していない。証拠は
`.tmp/yanmaga-single-page/probe.json`、`live-result.json`、`live-capture-v2/`。
人工browserでは1枚・menu表示/非表示/閉じない・不正カードと、ready-wait formの
label/type/action/thumbnail/重複/次話marker/title不一致を検証する。
targeted browser 15件、Adapter Unit 10件、既存menu/終端/Runner/既存grant/Batch-ZIP
連携のaffected browser 108件は全PASS、合計133件、skip 0。
`ruff check src tests`と本変更4ファイルの`git diff --check`もPASS。
site-local修正のためfull pytestと独立Research suite、変更していないencoder内部testは
未実行。実サイト確認は該当1話の隔離Runnerのみで、通常50件Batch全体は未再実行。

## 偶数ページ数のterminal-only終了画面（2026-11-18）

「アカデミー最強のモブヒーラー」第2話②（Item 49662 / Source 49969）の
22:02 Batchは本文26ページを保存済みだったが、最後の25/26見開きからnative
`-/26`へ送った後に`Yanmaga reader did not advance within the bounded wait`で停止。
20:09の同話失敗runにも同じDOMが残っていた。403/429/5xxは各0。
原因はprivate terminal snapshotとlayout検証に残っていた「Nは奇数」という限定。
`-/26`をsnapshotにできず、実際には移動済みの終了画面を変化待ちが認識しなかった。

shared-CDPの専用Pageで、native counter 1/26→3/26→…→25/26→-/26と、
右半分の1272×1800 rental、本文wrapper全てが右viewport外、loadedな最終26 wrapper、
同一話の評価controlと「第3話①」の次話/read cardを再観測した。
奇数限定を除き、既知N（現在は1または3以上、上限MAX_BODY_PAGES）、native caption一意性/ancestry、
同一route/total、本文保存index 1..N、最終wrapperの3画像geometry、本文非表示、
rentalの全体表示と周辺非遮蔽、menu非表示、access gate不在を維持する。
次話/read titleとfreshな同一作品一覧の直後rowとの一致も従来どおり必須。
`-/N`を本文identityや画像にせず、通常counter parserは変更しない。
評価card単独のENDは従来どおり最終本文併置layoutだけであり、今回のENDは
既存next/read branchで成立した。追加key操作・timeout延長・権利fallbackはない。

変更後の同一話を、通常Catalogのread-only SQLite backupからidentity/既存grantを
渡した隔離Runner出力で確認。`max_pages=26`のまま本文26枚→positive END、
counter `-/26`、`terminal_only_layout_exact=true`、保存index 1..26を検証した。
全26画像のSHA-256は元の失敗runの26画像と一致。first-party non-GET試行0、
`first_free_release_state=not_attempted`。grant observerの書込み先は隔離copyのみ。
通常Catalog/Watchlist・元の失敗出力は変更していない。証拠は
`.tmp/yanmaga-even-terminal/live-probe.json`、`live-result.json`、`live-capture-v2/`。
人工browserは既存3ページのtestを4ページにもparameterizeし、rewind/全本文保存/
exact max-pages/END、counter先行、誤total/不明caption/重複/遮蔽/本文残留/未保存を検証。
targeted browser 28件、Adapter Unit 10件、既存終端/Runner/ページ送り/menu/
既存grant/Batch-ZIP連携のaffected browser 78件は全PASS、合計116件、skip 0。
`ruff check src tests`と本変更4ファイルの`git diff --check`もPASS。
shared Core/encoder/Research契約の変更がないためfull pytestと独立Research suite、
変更範囲外のnative-capture内部testは未実行。通常56件Batch全体は再実行していない。

## 最終本文の評価カードによるEND（2026-11-18）

通常Batchの「アカデミー最強のモブヒーラー」第10話①（Item 49648 / Source
49955）は本文16ページを保存した後、未対応の評価カードで終了判定を満たせず、
`go_next` の外側timeoutで停止していた。metricsの403/429/5xxは各0。
保存済み診断DOMとshared-CDPの再観測で、次話title/reader/rental/author CTAを
持たない「お気に入り・いいね・シェア」のnative cardを確認した。

Adapterは既存の全本文index連続保存・最終counter・同一Viewer route・menu非表示・
最終本文の可視/周辺非遮蔽に加え、単一`#rental`の全体表示と周辺非遮蔽を要求する。
既知の`#js-rental-box > #js-modal-content > .wrapper-rental-button`の内部で、
既知assetのloadedな`like-note`画像、一意の評価3control、spacer/like-wrapper順序、
exact label/classを検証する。favorite/likeはnative formのsame-origin POST先、
一意のhidden `jdcn`と現在URLの`cid`一致、shareはTwitter intentと同一話Source URLを
要求する。検証済み作者linkの併設は上記条件で許可する。他の終端CTA/titleとの混在、
欠落・重複・identity不一致・hidden/遮蔽・
semantic access gateは従来どおり停止。評価controlはclick/submitしない。
この追加ENDは観測済みの最終本文併置layoutに限定し、`-/N`専用画面には適用しない。
snapshot安定判定とdiagnosticsにも`engagement_card_exact`の根拠を含める。
CLI/設定・capture形式・共通Core・Catalog/Batchの契約変更はない。

変更後の同一話をshared-CDPの新規専用Pageと隔離出力でRunner検証し、16画像を保存して
positive ENDに到達した。`engagement_card_exact=true`、全本文index保存済み、
`first_free_release_state=not_attempted`、first-party non-GET試行0を確認した。
16画像すべてのSHA-256は元の失敗runで保存済みの本文画像と一致した。
通常Catalog/Watchlistと元の失敗出力は変更していない。証拠は
`.tmp/yanmaga-engagement-fix/live-result.json`と同directoryの`live-capture/`。
人工browserでは正常カードとform/話ID/label/画像/構造/表示/混在の異常を検証する。
対応するAdapter Unit＋browser Integrationは216件PASS、skip 0。
`ruff check src tests`と本変更4ファイルの`git diff --check`もPASS。
shared Core/Researchの変更がないためfull pytestと独立Research suiteは未実行。
実サイトは該当1話のRunner確認のみで、通常70件Batch全体とCatalog完了更新は未実行。

## Discovery中の作品紹介ポップアップ（2026-11-18）

`YanmagaDiscoveryAdapter.iter_records()` は専用Pageへ一時的なPlaywright
`add_locator_handler()` を登録する。サイトの `body.is-open-popup` と表示中の
`.js-popup-close` が揃った場合だけ、同じclassを持つ背景を除いた最内側の
close controlを通常clickする。並び替え・「もっと見る」のactionability待機中に
遅れて表示された場合も対象。非表示時は追加の表示待ちをしない。
通常の登録・レンタルmodalの `is-open-modal` / `.js-modal-close` は対象外。

click前に現在URLが対象作品のcanonical/検証済みsort URLであること、closeが
一意であることを確認する。閉じた状態への遷移とURL非変更を確認し、最大3回まで。
close click・消失待ちはそれぞれ最大2秒（短いaction timeout時はその半分）。
曖昧、閉じない、再表示上限等の失敗はDiscovery incompleteとし、行をemitしない。
callback内の失敗は保持してDiscovery側から伝播し、Pageの後続操作へ漏らさない。
操作不要の短い一覧でも閉じるため、初期表示後・sort後・最終snapshot前にも即時確認する。
成功・失敗ともhandlerとtelemetry listenerを解除する。access分類・Catalog同期・
expansion/row上限は従来どおり。CLI/設定追加なし。

shared-CDPで作品一覧DOMとサイトが配信したJavaScriptを確認した。popup用の
`is-open-popup` / `.js-popup-close` と通常modalの別系統を確認できたが、
間欠的な作品紹介そのものは今回の作品ページ確認では再現せず、実ポップアップの
close成功は未確認。変更後Adapterで双星のアポクリファの全57件を列挙でき、
終了後のhandler残留0、話/Viewer/non-GET request各0を確認した。Catalog書込みなし。
旧QAで見えた `DIV.mod-modal-close.js-modal-close` は、閉じた
親modal（opacity=0）にも存在し得るため、ボタンの存在だけを開状態としない。
人工browserのDiscoveryで表示なし・hidden・開始時・sort遷移後・More直前・
click待機中の遅延表示・操作不要の一覧・閉じない・close重複・再表示上限と
handler後処理を検証する。

## Work Ticket前のレンタル履歴ページ送り・期限切れ（2026-11-17）

通常Catalogのアポクリファ第28話（Item 49616 / Source 49923）は、11月17日の
実行ログで `quota/work_ticket` まで選択されていたが、消費前の
`Yanmaga wait target history status is unknown` で停止していた。
原因はレンタル履歴31件の先頭20件に「もっと見る」があり、旧parserが
paginationを未対応扱いしていたこと。後続11件には同じ話の `期限切れ` cardも
存在し、この終了表示も旧parserのactive countdown契約ではunknownになっていた。

`rental_history.py` のcomplete-collection観測は、native linkで実在確認した
same-origin `GET /api/mypage/rentals?offset=N` だけを追跡する。
`#content_more_button` の既知DIV/A/BUTTON構造、Turbo属性・label/class、offset＝
累積行数を要求する。応答はfreshな200、exact URL、Turbo-stream MIME、既存の
Date/Age/private cache条件を満たし、`content_card_list` へのappendと
`content_more_button` のreplaceという2 streamだけをdetached DOMへ合成する。
実DOM・scriptは実行せず、重複話URL、連続data-index、1応答20行、最大50追加page／
1,000行／全fetch合計4MiB、native More消失までを検証する。不明・partialはunknown。
positive-only countdown取得は従来の単一履歴documentの範囲を維持する。

完全履歴内のexact targetが不在、またはnative `レンタル期間` と `期限切れ` の
既知class（gray背景・black文字）／pair・ancestry・非hiddenを満たす1 cardだけが
ある場合は「現在のactive rentalなし」として `RentalHistoryObservation.countdown=None`。
activeとexpiredの重複、未知class/text、hidden、取得失敗は消費許可にしない。
チケット候補には従来どおりfreshなwait row、認証、チャージ完了、exact modalが必要。
Policyの順序・cooldown・消費確認／persist条件は変更しない。

shared-CDPのread-only確認で31件を完了し、第28話の期限切れを検証した。
通常Adapterのquota/work_ticket初期化も実行し、履歴とcharged preflightを通過して
Source遷移直前へ到達したことを確認して診断hookで停止。Source／Viewerへのrequest、
チケットPOST・権利消費、通常Catalogへの書込みは0。実際の再消費とcapture/ZIPは
今回未実施。人工browserは複数page、active／expired／absent、異常応答・boundを検証する。

## GUIのURLから一括登録（2026-11-17）

`YanmagaDiscoveryAdapter.registration_hosts` と `resolve_registration_url()` により、
GUIの「Watchlist：URLから一括登録」で `https://yanmaga.jp/comics/作品名` を受理する。
Watchlistの `https://yanmaga.jp/comics/双星のアポクリファ` と同じ形式を使い、
既存 `parse_yanmaga_work_url()` が受理したslugを `yanmaga-work:<slug>` の同一site
作品identityとする。保存URLは日本語を含むliteralの作品URL。作品名はURLから推測せず、
既存GUIでlabel・所属Work・IDを人が確認してからpreview・一括保存する。
登録解析はnetwork、Discovery、話/viewerへのアクセスを行わず、metadata取得checkboxを
有効にしてもこのsiteではブラウザを開かない。通常のDiscovery・Capture・Batchは変更しない。

共通URL guardは従来どおりpercent escapeを拒否するため、日本語は `%E3...` 形式ではなく
Watchlist同様にそのまま貼り付ける。話URL、viewer、`/episodes`、末尾slash、query、
fragmentは登録対象外。完全一覧previewや複数keyの詳細編集能力は追加していない。
テストは `test_registration_resolver.py` と `test_gui_url_registration.py` で、公式URL・
不正URL拒否、保存前の再検証、metadata checkbox両状態のGUI解析→確認→preview→保存、
Catalog非変更・Full要求signalを隔離Watchlist/Catalogで検証する。今回の変更の実サイト
確認は未実施（URL解析のみの追加で、DOMや実サイトアクセス挙動は変更しない）。

## Terminal-only reader position (odd/even; 2026-11-17, updated 2026-11-18)

Chapter 15 (Item 49631 / Source 49938) failed in normal Runs 25364 and 25427
after all 15 body pages had already been saved as native WebP. After the final
14/15 spread, the viewer's next turn displayed only the next-episode rental
card. Its exact native `#menu_seekbar > #menu_slidercaption_base >
#menu_slidercaption` changed to `-/15`; the last body moved beyond the right
viewport edge and the rental occupied x=1280, y=0, width=1272, height=1800.
The old positive-number counter parser returned no snapshot, so change-wait
timed out instead of recognizing the terminal position. This was neither a
grant failure nor a missing captured page.

The ordinary public body-counter parser remains unchanged: `-/N` and N+1/N
are not body counters. A separate private snapshot mode recognizes only the
unique native caption/ancestry with exact `-/N`, N=1 or N>=3 of either parity, and the existing
page-total bound. It uses an internal terminal position N+1, never a body
identity or capture target. General total/duplicate/route/viewport/menu/gate
checks still apply. The layout must have zero visible body wrappers, one loaded
final N wrapper with the verified three-segment geometry and full height,
all retained bodies beyond the right viewport edge, and the exact native
rental slot above. The whole rental must be presented and own its center and
eight inset perimeter points.

END additionally requires the already captured sequence to be exactly 1..N
and an existing proven terminal-card branch. For a next/read card, the unique
normalized title must also match the unique immediately following same-work
listing row; signup/wait/point/latest-author retain their existing stronger
bindings. No click or next-episode navigation is performed. A terminal-only
screen at initialization may be rewound through the existing bounded normal
ArrowRight path, but cannot become END without all body pages being saved.
Exact max-pages=N still permits final END, without a fabricated N+1 image.

The dash counter also precedes the actual slide animation. Change-wait first
waits for the same terminal layout/control signature to stabilize, then applies
the positive-END predicate within the original deadline. It never presses a
second key or spends the same budget on two successive stabilization waits.
Transient body-visible/card-offscreen frames remain pending; malformed,
obstructed, wrong-title, incomplete-sequence or unsupported layouts do not end.
Diagnostics retain raw `native_counter="-/N"`, expose `terminal_only` and
`terminal_only_layout_exact`, and set `native_counter_complete=false` for this
mode rather than pretending the UI reports N/N. Existing complete body-count
and sequence fields remain separate.

The synthetic three- and four-page viewers start on this terminal position, rewind,
capture all body pages, and test both next/read and point cards. They
also cover delayed layout, bad/wrong-total/foreign/duplicate caption, wrong title,
missing control/final wrapper, edge obstruction, wrong card size, visible body,
and premature terminal entry. The historical odd-only targeted group passed 14 tests with 0
skipped, including explicit refusal to supply a body identity at `-/N`.
The first live implementation exposed the counter-before-animation race and
failed closed after saving all 15 pages; its isolated evidence is retained
under `output/yanmaga-png-investigation/fixed-odd15-final/`. That incomplete
attempt is not a successful crawl or Artifact verification.

The final post-stabilization live check used a fresh isolated Catalog backup,
the exact normal Planner candidate, real `BatchExecutor`, shared CDP Page, and
normal packager. It completed Chapter 15 with 15 pre-JPEG WebP pages, zero PNG,
positive END, ZIP, Completed, and one Artifact in that copy. The final UI had
`-/15`, no visible body, a fully presented exact rental slot, and the proven
next/read card. The previous stored grant was preserved exactly. Source GET=1,
Viewer GET=1, other-episode/non-GET requests=0; quota/Work-resource state and
the normal pending Catalog were unchanged. Evidence:
`output/yanmaga-png-investigation/fixed-odd15-stable/` (`report.json`,
`reader-trace.json`, genuine Manifest, Catalog, archive, and `audit.json`).
`odd15_audit.py` independently verified the 15 ordered Manifest members,
fingerprints, unique VP8L/opaque 1125×1600 decodes, ZIP CRC, real Artifact and
Completed state, and absence of a terminal-card/fake page-16 entry. Archive
SHA-256 is `c86179f88aa54abbccb67ffa6937fa6230ffffa9bca5216ff1fc944c479ad7b1`;
the convenient exact copy is `fixed-odd15-stable/chapter-15-fixed.zip`.

Adapter Unit/browser regression passed 198 tests with 0 skipped (477.07 seconds;
23 existing asyncio/Python deprecation warnings). After the final bounded
terminal-stabilization adjustment, all 14 affected odd-terminal cases passed
again with 0 skipped, including counter-before-animation and no terminal body
identity. Ordinary parser checks explicitly reject dash and N+1/N as body
counters. `ruff check src tests` and changed-files diff checks passed. Full
repository pytest and unrelated-site/Discovery suites were not rerun for this
site-local counter/layout/END change; shared Core, Catalog, resource policy,
capture format, and browser lifecycle code are unchanged. Other terminal
layouts and two-page dash states remain unsupported.

## Chapter 17 existing-rental recovery and delayed layout (2026-11-16)

The reported normal Run 25360 (Item 49628 / Source 49935, Chapter 17) stopped
in listing preflight with zero saved pages and no Source or Viewer entry.
Catalog still classified the Source as `free` from the 14:21 observation and
had no stored grant. An earlier 17:35 attempt had reached the requested Viewer
but failed first-free notice/finite-grant confirmation before persistence.
The later listing was markerless with a rental countdown. A metadata-only live
probe confirmed an authenticated exact active Rental History card (`残り21時間`)
and a finite conservative hour bound. Internal full Discovery already emitted
`quota` plus `access_granted_until_observed=true` for that exact row; the Adapter
had ignored that fresh evidence because its separate Catalog-grant input was
empty. The original entry's precise consumption time remains unproven.

For direct/auto capture only, the current Adapter can recover this exact state:
authenticated, markerless raw-unknown row; no public/first-free/wait/red or
restricted marker; internal Discovery's explicitly observed future grant;
and a fresh second Rental History observation for exactly the requested ID.
The second proof must be active with aware, future, finite hourly evidence and
an observation no later than now. It retains the earlier of the Discovery and
second bounds. After the existing live listing/URL/login/row pre-entry check,
the existing synchronous `ConfirmedAccessGrant` observer must save that bound
before Source GET or capture. Missing/duplicate/foreign/inactive/unbounded,
expired/malformed, future-observed or conflicting evidence, missing observer,
row drift, and persistence failure stop before Source entry. A still-future
Catalog grant keeps the old path and is not extended or reported again.

Only the source grant/timestamp is persisted through the existing site-neutral
observer. No access-mode rewrite, inferred use time, quota start, Work cooldown,
resource attempt, or fixed 24/72-hour lifetime is introduced. Day-only evidence
is intentionally outside this automatic recovery path because the current
observer's supported countdown category is hourly; normal full Discovery can
still import a validated day bound for the existing trusted-Catalog-grant path.
The quota/work-ticket attempt path never silently switches to recovery.
`history_grant_recovery_state` records `not_attempted`, `candidate`,
`reconfirmed`, or `persisted` in site-owned capture/failure metadata.

The first isolated Batch check saved the recovered grant before its one Source
GET, then failed after page 1 with `page turn did not reveal a new body page`.
A second bounded same-grant check completed all 14 pages; its numeric reader
trace proved that every turn's counter could lead the old visible frame by
several reads. The wait loop had treated even a still-stable old captured frame
as an immediate failure. It now continues observing the same turn inside the
original deadline until an advanced, stable uncaptured body is proven. No
second key press, forced identity, skipped page, or timeout extension is used.
If the layout never arrives it times out. Page-total, route, geometry, gate,
sequence, max-pages, and same-content protections remain. Diagnostics now also
include `native_counter`, `visible_body_indices`, and `captured_body_indices`.

Final verification used a fresh isolated SQLite backup and Watchlist copy,
selected the exact normal Planner direct candidate, and ran the real
`BatchExecutor` with its normal grant observer and packager. Chapter 17 reached
positive END, 14 pre-JPEG WebP pages, ZIP, Completed, and one Artifact in that
copy. A route observer independently checked the grant was already durable
before Source entry. Source GET=1, Viewer GET=1, other-episode/non-GET requests=0;
quota and Work-resource state were unchanged. The normal Catalog remains
pending with no grant and was not written by these checks; its next Batch run
will perform the same verified recovery automatically.

Evidence is under ignored `output/yanmaga-png-investigation/`:
`access17-preflight.json` is the metadata-only probe; `fixed-access17/` is the
grant-persisted/page-turn-failed check; `fixed-access17-retry/` is the successful
pre-wait-fix check with `reader-trace.json`; and `fixed-access17-final/` is the
post-fix real Batch verification with its genuine Manifest, ZIP, Catalog,
reader trace, and report. Final archive SHA-256:
`6ed9db258fdea0df7994356b5799b952bbc87ee85af52ac181b91629d043bbcc`.
The genuine Manifest's ordered members and all fingerprints matched the ZIP,
which passed CRC. Each run was limited to the one exact existing rental; no
ticket/point action or next-episode entry was performed.

Final verification: the complete Adapter Unit and browser Integration files
passed **185 tests, 0 skipped** in 426.24 seconds (23 existing asyncio/Python
deprecation warnings). Targeted recovery/layout checks passed 17; the earlier
affected access/grant group passed 45. Cases cover exact finite evidence,
min-bound persistence before capture, missing/duplicate/wrong-target evidence,
inactive/unbounded/day-only/future-observed/expired/malformed bounds, missing
observer, write failure, pre-entry DOM drift, delayed layout without extra key
presses, and bounded timeout if layout never arrives. `ruff check src tests`
and changed-files diff checks passed. The final offline audit also verified
all 14 unique VP8L/opaque 1125×1600 images, Manifest identities/fingerprints,
and the isolated Catalog's real Completed/Artifact state. It is
`fixed-access17-final/audit.json`; a convenient exact copy of the archive is
`fixed-access17-final/chapter-17-fixed.zip`. Full repository pytest and
unrelated-site/Discovery suites were not rerun because the changes are
Yanmaga Adapter entry/wait logic and existing-observer use only. No shared
Catalog schema, Batch, resource rule, or Core code changed.

## Chapter 29 point-rental END and decoded-segment recovery (2026-11-16)

The normal Batch failures for Item 49615 / Source 49922, Runs 25265 and 25266,
saved all 14 body pages of `第２９話 調和` before timing out in `go_next`.
The saved diagnostics prove a complete counter/sequence, correct route, hidden
menu, unobstructed final body and rental card/title. The next Chapter 30 card
instead had the observed point-rental CTA `レンタルして読む`; none of the
previous next/read, signup, countdown, or latest-author branches accepted it.
One failed run had all 14 WebP pages, while the other had 13 WebP plus one PNG,
so the END failure was independent of the last page's file format.

The current point-card branch requires all existing complete-body, route,
ownership, semantic-gate, and stable-END checks. It additionally requires one
presented exact `a#js-btn-rental.mod-button--orange.rental.content`, its direct
native `form#form-rental.ga-viewer-rental-point`, POST to same-origin HTTPS
`/viewer/rental` without credentials/query/fragment, one hidden 20-alphanumeric
`jdcn`, one hidden `rental_type=point_rental`, and positive displayed point cost.
The observed CDN thumbnail path must contain that exact code. The unique
normalized title must match the unique immediately following row of the fresh
same-work listing. Other terminal controls conflict. Point-code identity and
button geometry participate in the stable snapshot signature. The form and
button are observed only; no submission, point use, or next-episode entry is
performed. Diagnostics expose the point-card count, presentation, exact-shape,
and following-row proof booleans, without hidden form/account/token values.

An isolated same-grant capture first verified the END correction with 13 WebP
and one PNG. The separate bounded PNG trace identified the remaining cause:
the regenerated middle segment of page 14 had exactly the same JPEG payload
as its predecessor, but 1,151 RGBA channels differed by one. The predecessor
was retained and valid; this was an actual pre-JPEG pixel collision, not missing
history or a memory cap. The strict pre-JPEG matcher correctly rejected it and
remains unchanged for this case; no tolerance or newest-candidate guess is used.

When the pre-JPEG attempt reports `segment_source_not_exactly_bound` or
`capture_buffer_overflow`,
the adapter now tries the actual currently selected DOM image objects for the
whole visible group. It reuses the complete geometry/style/ownership proof,
validates each Blob as a bounded static JPEG (Content-Length and body size at
most 1 MiB, JPEG MIME and signature), and reads opaque sRGB pixels at intrinsic
segment dimensions. These are composited at the existing offsets/crop into
1125×1600 and encoded as lossless WebP with exact RGBA round-trip verification.
Only current browser-owned Blob URLs are read; this adds no server request.
Actual image-object identities, immutable source URLs, geometry, and styles are
revalidated through composition, encoding, and the final atomic spread check.
Unknown/changed sources, non-JPEGs, or failed proof still use the safe PNG path
or stop on changed body identity. No JPEG-image tolerance is added to pre-JPEG
attribution, and all existing observer/transfer/page/retry caps remain.

The lower source level is explicit: `capture_method=decoded_viewer_segment_lossless_webp`,
`capture_provenance=decoded_visible_image_composition`,
`source_native_bytes_used=false`, `source_native_pixels_used=true`, and
`pre_jpeg_pixels_used=false`. A successful pre-JPEG capture sets the last flag
true. The group retains the original native `fallback_reason`; a failed decoded
attempt also records `decoded_failure_reason`. Both successful pixel paths use
intrinsic dimensions, never a resized Locator screenshot. Decoded JPEG pixels
are not claimed to be the earlier pre-JPEG pixels or original server-page bytes.

The final same-grant shared-CDP `CrawlerRunner` verification reached positive
END with 14 WebP pages and zero PNG: 13 pre-JPEG pages and one decoded-source
page. Page 14's decoded WebP matched every RGBA byte of an independent direct
DOM-image reference composition. All 14 files passed ordered Manifest hashes,
unique fingerprints, VP8L/opaque decoding and dimensions; the exact-members ZIP
passed CRC and every fingerprint. ZIP SHA-256:
`caa6e5d6156e57f600597538e5ccde95366da2fe0600e7b0b1550bc38dc905a1`.
One exact Source GET and one exact Viewer GET were used, with zero other-episode
or first-party non-GET requests. The stored grant and null quota start were
unchanged. This isolated verification did not rewrite normal failed runs,
mark the normal pending Item completed, or create a normal Artifact.

Evidence is under ignored `output/yanmaga-png-investigation/`:
`fixed-point29/` is the END-only 13-WebP/1-PNG run;
`point29-png-diagnostic/observations.json` records the exact collision;
`fixed-point29-final/` contains the genuine Manifest, `decoded-reference-audit.json`,
`audit.json`, and `chapter-29-fixed.zip`. The QA wrapper's native-attempt log
still reports the page-14 native failure; the final Manifest and report record
the successful decoded-source result. `audit_point29_final.py` is the offline
artifact/Catalog audit. The observation does not guarantee other point-card
layouts or that every unavailable source can avoid the retained PNG fallback.

Verification: `tests/unit/test_yanmaga_adapter.py` and the entire
`tests/integration/test_yanmaga_adapter_browser.py` passed **169 tests, 0
skipped** (406.75 seconds; 23 existing asyncio/Python deprecation warnings).
Coverage includes normal/native/decoded capture, exact all-pixel references,
whole-spread selection, non-JPEG rejection, image/style drift, menu/gate/END,
point-card positive and malformed/hidden/conflicting cases, resource entry,
and Batch success/failure packaging contracts. `ruff check src tests` and the
changed-files diff check passed. Full repository pytest and unrelated-site
Integration/Discovery tests were not rerun because this changes only Yanmaga's
capture and END contracts. No normal-Catalog Batch or extra paid/ticket action
was performed; same-episode live verification and its offline audit are above.

## Native capture: regenerated-segment PNG fallback (2026-11-16)

The production observer now accepts a regenerated segment only with one fresh
exact-byte candidate and a still-bound immediately preceding same-payload
candidate with complete validated pixel history. After asynchronous Blob
reading, dimensions and every immutable RGBA byte must be equal. A successful
comparison carries that history forward; released history, any intervening
rejected copy, differing RGBA despite identical JPEG, or multiple fresh matches
still reject pre-JPEG attribution. The decoded-source path above may then be
used after its independent proof. A later rejected Blob preserves earlier proven bindings.
Full pixel comparisons run outside viewer hooks, no additional pixel copies
are retained for history, and all existing caps and source/style/spread proof
checks remain. Observer stats add `regeneratedBlobBindings`.

The normal Catalog's latest Yanmaga Run 25261 completed `双星のアポクリファ`
`第５３話 帰路へ` (episode `b7ae4530792bea5b258f31967418f513`) with 16
pages. Its existing archive contains WebP pages 1–9 and PNG pages 10–16;
its SHA-256 remains the Catalog Artifact's
`955509d9128388c9cb32f591e25b69c93eb370eaf0f52ebacc6429920db39bac`.
The original observer events were not logged, so that run's exact internal
event sequence cannot be established retrospectively.

Two fresh shared-CDP, isolated `CrawlerRunner` runs of the same public-free
episode reproduced `segment_source_not_exactly_bound`: both reached positive
END with 16 pages, WebP 1–13 and rendered PNG 14–16. Production capture code
was unchanged. A QA-only instrumented observer logged bounded candidate,
exact-byte Blob match, URL binding, and release events. Blob URLs were replaced
by document-local numeric IDs in these logs; no source pixels or JPEG payloads
were exported into the event log. Each run made one exact Source GET and one
exact Viewer GET, with zero other-episode or first-party non-GET requests.
The normal Catalog, its Artifact, and its archive were not rewritten.

The observer initially copied and bound 48 segments. During navigation the
viewer generated nine more segments, with JPEG payloads equal to existing
bound candidates. The pre-fix `matchBlobParts()` searched both pending and
already bound candidates; the duplicate triggered its ambiguity branch,
removed the previous `byUrl` entry, and released both candidates. The new Blob
was marked invalid and not bound. The later DOM images for pages 14–16 used the new URL IDs,
so preserving only the previous bindings would not recover those pages.
Capture then waits up to the existing 750 ms bound and falls back for the
whole visible group. Neither run had pixel-buffer overflow, hook conflict,
Blob read failure, or outstanding reads at the failed captures. The exact
viewer-internal reason for regenerating these segments was not instrumented.

The second diagnostic compared the immutable pre-JPEG RGBA arrays: all nine
duplicate pairs were dimension-equal and byte-for-byte pixel-equal. This is
evidence for the observed regeneration, not a general JPEG-to-RGBA equivalence
rule. Two offline synthetic browser cases independently reproduced the old
binding's removal: one used identical pixels, while the other changed one
source channel by one and still produced identical JPEG bytes. Consequently,
accepting repeated JPEG bytes alone cannot safely recover native pixels.
The current pre-JPEG correction uses the exact pixel-history proof above rather
than accepting JPEG equality alone. Missing/released history remains a pre-JPEG
limitation; decoded-source proof is now attempted before the safe PNG fallback.

A fresh post-fix shared-CDP `CrawlerRunner` recapture of the same Chapter 53
reached positive END with all 16 pages native 1125×1600 WebP and zero fallback.
The unmodified production observer reported 57 copies, 57 exact bindings,
nine regenerated bindings, and zero ambiguity/miss/read-failure/overflow/hook
conflict. One exact Source GET and one exact Viewer GET occurred; other-episode
and first-party non-GET requests were zero. The isolated
`fixed/chapter-53-fixed.zip` has SHA-256
`410f21db7a0fc615b2ed53992bada4811193470cc8e3a5b0e61791dd33a4d12f`.
All 16 files passed unique-hash, Manifest identity/order, VP8L/opaque decode,
dimensions, and ZIP CRC/member/fingerprint checks. The old normal archive's
hash and the completed Catalog Item were independently rechecked unchanged.

Evidence and QA scripts are under ignored
`output/yanmaga-png-investigation/`: `summary.json`, `probe.py`, `synthetic.py`,
`audit.py`, and each run's `observations.json`, `report.json`, and genuine
`capture/manifest.json`. `baseline/` stopped during listing preflight because
the initial QA request allowlist incorrectly blocked `/episodes`; the corrected
`baseline2/` and `attribution/` runs are the successful recaptures. The isolated
`attribution/chapter-53-diagnostic.zip` preserves the final recapture's exact
16 Manifest files. Its SHA-256 is
`e05cebe51a6c066767804e12060814ffba5729b64c7c95f9cad48648d2fb5c3d`.
The post-fix output, `fixed/audit.json`, and `audit_fixed.py` are in the same
ignored investigation directory. `probe.py fixed` selects the production
observer without the prior QA observer-script instrumentation.

Verification: both offline synthetic causal assertions passed; all 32 recaptured
files passed Manifest hash, image decoding, MIME, dimensions, and sequential
group-identity checks; the diagnostic ZIP passed CRC, exact member order, and
all 16 Manifest fingerprints. Post-fix affected native Unit/browser Integration
passed 34 tests (0 skipped, 115 deselected), including two regeneration rounds,
exact native output, preserved old bindings, pixel-collision rejection,
released/rejected history, and simultaneous fresh-candidate ambiguity. The
final rejection-history assertions were rerun with the encoder and existing
Batch recrawl-sidecar boundary: 6 passed, 0 skipped, 249 deselected. Recrawl
Unit tests passed 105 with 0 skipped. `ruff check scripts/prepare_recrawl.py
src tests` passed. The initial targeted group passed 7 with 0 skipped; its
pytest cache permission warning was avoided in the later checks by disabling
the cache provider. Existing asyncio deprecation warnings remain. The full
suite and unrelated site Integration were not rerun for this site-local
capture fix and explicit recrawl-policy entry. The earlier offline synthetic
probes are pre-fix causal evidence, not current-production expectations. The
instrumentation and request routing can affect timing, so a fixed PNG boundary
is not guaranteed, and original-run attribution remains qualified as above.

### Recrawl preparation

`scripts/prepare_recrawl.py` explicitly supports Yanmaga with WebP preferred
and PNG fallback at every position; JPEG is unexpected. The existing
classification and backup/apply services are reused. The normal-Catalog
dry-run below reported Item 49591 as `FALLBACK_INCLUDED`, preferred 9 / fallback
7, with one recrawl candidate and no unexpected/ambiguous/missing archive.
No `--apply` was performed. Apply-policy Unit coverage verifies unchanged ZIP
bytes after backup, Source and CrawlRun preservation, and Item-to-pending.

```powershell
.venv/Scripts/python.exe scripts/prepare_recrawl.py --site yanmaga --item-id 49591 --show-all
```

The default is read-only scanning; an explicit `--apply` moves the old archive
to the configured backup tree and returns the Item to pending. It does not
start capture, reset rights, or change the site's live access semantics.

## Existing-unknown Rental History recovery (2026-11-16)

Authenticated full Discovery joins unknown/point-only rows and same-work trusted
grant targets to one complete bounded native Rental History observation. Fresh verified
absence/expiry explicitly clears the stored direct grant; an otherwise unknown
previously known quota row retains quota after this proof. No prior free/paid/
unknown row is promoted by inactive history. Partial/ambiguous history cannot
clear a grant. The positive-only direct-entry helper also follows native More.
An exact active card with a fresh finite countdown promotes an unknown/point-only row to
`quota` and stores the conservative observed expiry; it does not infer
`quota_started_at` or a cooldown. Active history without a finite bound,
missing/duplicate evidence, and identity mismatches do not promote a row, and
`owned` rows are excluded. For otherwise unknown free/paid rows, a still-valid trusted grant preserves its existing
mode and expiry when active. Known quota rows refresh from fresh finite history. The join
does not enter a Source or Viewer or consume a right.

Root's normal-Catalog full Discovery repair changed only the three exact
`work-dual` rows for chapters 26, 27, and 29 from `unknown`/no grant to
`quota`/finite grant. The standard run preserved Source/Item identities,
Completed state, Artifacts, acquisition flags, and work state; its direct plan
did not consume a resource. Source, Viewer, and rental POST counts were zero.
Evidence: `output/yanmaga_access_experiment/followup-active/normal-repair-v1/report.json`.
The isolated validation run and normal-Catalog repair both used the updated
full Discovery path. Focused tests passed 96 with 0 skipped and 126 deselected;
the full suite was not rerun.

## Stage 02 current implementation (2026-11-16; capture and post-capture audit verified, PASS / BLOCKING 0)

The C sort and canonical/og corrections and BODY pre-live review passed
independent review with BLOCKING 0. A metadata-only probe verified the Rental
History helper for the already opened alias `episode-ff-probe-01`: H=17 at
2026-11-15T08:11:29.019643Z produced
`site_countdown_lower_bound=2026-11-16T00:11:24.019643Z` as GET start plus
(H - 1) hours minus 5 seconds. This lower bound is not an absolute expiry or a
fixed 24-hour lifetime. That probe used zero additional rights. A separate
metadata-only check planned one direct candidate, `episode-ff-capture-01` at
position 31, without rights; it differs from the earlier position-32 episode.
The preparation Catalog contained 1 Work, 57 Items, 57 Sources, and 57
SourceTargets. The selected target IDs were Work 1 / Item 27 / Source 27 /
Target 27; these are identifiers, not row totals.

C1 used one additional first-free entry on position 31. It confirmed the exact
Viewer and completion notice, then synchronously stored the finite countdown
lower-bound grant before pixel-readiness work. After readiness and rewind, the
intentional `capture_page` failure occurred before the first content page was
saved. C2 retried without rerunning the external Catalog DiscoveryService; the
Adapter did perform its fresh internal listing preflight and preserved the same
future-aware grant. Both runs used one Source GET and one Viewer GET; C2 used no
new first-free right. Each run had zero other-episode and first-party non-GET
requests. At the C1/C2 checkpoint, the Item was pending, both CrawlRuns had failed after
readiness and rewind but before a content page was saved, and no Artifact,
quota start, or Work resource state had been created. Research plus C1 account for two confirmed first-
free uses; the additional allowance is now exhausted. Ticket, point, coin, and
paid actions remain zero.

The adapter permits a normal public-episode GET only for a fresh exact
first-free candidate after rechecking the authenticated work identity, row,
marker, and queryless public URL. Because this GET may grant access
automatically, it requires the exact Viewer, visible body wrapper and counter,
no known gate, the exact first-free notice `無料レンタルが完了しました`, and
fresh finite same-target Rental History evidence. The site-neutral grant is saved synchronously before pixel
readiness. Unknown evidence, route drift, or persistence failure does not
trigger another entry. Trusted existing grants require a still-future Catalog
bound and fresh active evidence for the exact target.

C1 and C2 verify grant persistence and preservation through intentional
capture-hook failures after readiness/rewind but before the first saved content
page. Post-C2 v4 metadata Discovery and the one-candidate direct plan were
independently audited. C3 stopped before Source entry on an incorrect QA
request budget. C4 ran once and failed in the normal CLI after one Source
and one Viewer request; no genuine Manifest page progress or ZIP was saved.
The C4 failure does not establish a site failure. Its diagnostics are
preserved. C5 ran once and failed before content capture because the body did
not stabilize. The Item remained pending, the existing grant was preserved,
and no Artifact was created. C6 used the existing grant and verified one Source
302 to exact Viewer 200 chain and one content-info XHR, but the body still did
not stabilize. The run failed with page_count null; the Item stayed pending,
the grant stayed unchanged, and no Artifact was created. No additional right
was used. C7 then saved 13 native WebP pages and reached reader counter 14/14,
but did not establish END or create an Artifact. Inspection identified the
false stop: the broad modal-class gate matched a nonsemantic inline rental card
inside the unique `#rental` auxiliary. The adapter now exempts only the observed
static class/id shapes inside `#rental`. Semantic dialogs and existing body
ownership, viewport, menu, pixel, page-count, and positive-END checks remain
unchanged. Synthetic browser coverage confirms that this inline card permits
the final body page and END, while a semantic dialog in the same card still
fails closed. The adapter Unit file passed 10 tests, the adapter browser file
passed 106 tests, and independent review reported 8 pass / 0 skip and BLOCKING
0. C8 then completed the same target through the ordinary CLI using the
existing future-aware grant and passive request observation. Run 8 succeeded
with 14 pages and positive END; Item 27 completed and one Artifact was present.
The genuine 14-page Manifest matches the ZIP exactly, and Root's artifact audit
passed. The ZIP contains 13 native WebP pages and one safe PNG fallback for the
last page (`segment_source_not_exactly_bound`). An independent visual check
confirmed the final page is chapter 27's ending page (`第27話 完`). C8 used one Source GET and
one Viewer GET, no other episode or non-GET request, and no new first-free
right; the saved grant was unchanged, with quota and work-resource state empty.

The passive watcher did not produce its auxiliary watch-result marker, so its
standard audit command could not run. Root directly audited the genuine
Manifest and ZIP successfully; no marker was fabricated and no retry was made.
Post-capture metadata checks then ran against the completed target. Full
Discovery exited 0 with 57 observed/known rows, `complete=true`, and
`stopped_reason=exhausted`; the before/after Catalog comparison passed. The
incremental CLI also exited 0 without error and observed 5 known rows, 0 new,
then stopped with `known_streak`. Its `complete` value is null, so incremental
completion was not evaluated and is not claimed. The incremental report did not
install the Source/Viewer request observer; those request counts are unknown.
The Catalog retained Source 27 as the only enabled source, Source 28 disabled,
Item 27 completed, the existing Artifact and grant unchanged, and quota state
zero. The post-full plan contained zero candidates because Item 27 was already
completed. The bounded work-intro popup observation found a visible
`DIV.mod-modal-close.js-modal-close`, but its one click did not confirm popup
disappearance; the listing remained at 57 rows with no More control, so no
further popup action was attempted. The ignored QA popup helper, including this
observed DIV shape, has only passed compile checks and has not been live tested.
The Stage 02 final independent review accepted the implementation with BLOCKING 0.

Post-C2 v4 full/incremental metadata Discovery completed with rights 0,
Source/Viewer/non-GET/fatal requests 0, and an independently audited exact
one-candidate direct plan. The report is
`output/yanmaga_access_experiment/stage02/metadata-only-v4-refresh-report.json`
(SHA-256 `0b62fbb74622ef25e30f4f38d64ebc0c30d112365b894a56cc99dc29b85a100b`).
Full Discovery was complete/exhausted with 57 observed rows; incremental had
complete=null/known_streak with five observed rows and did not yield the
target, while both snapshots contained 57 rows with the same authenticated
identity and position-31 ordering. Fresh history plus the trusted grant
preserved Catalog free mode and the future bound; the target flag was reapplied
after each run. Root's read-only Catalog audit confirmed the unchanged grant,
pending Item, IDs Work 1 / Item 27 / Source 27 / Target 27, zero Artifacts and
quota/resource state, two CrawlRuns, and one direct non-quota plan. No capture
was attempted. The v3 raw result remains unavailable, so its QA stop's
underlying production outcome is unknown.

C8 verified image capture, positive END, ZIP, and Completed for the selected
existing-grant target. The post-capture audit is recorded above: full Discovery
was complete/exhausted; incremental stopped at `known_streak` with
`complete=null` (not evaluated); and incremental Source/Viewer counts are unknown
because its request observer was not installed. Root directly audited the genuine
Manifest, ZIP, Catalog, and Artifact. The independent final review accepted Stage
02 with BLOCKING 0. Stage 03 has since implemented the observed wait-marker
classification, `work_ticket` Policy and one-shot modal entry. Run 10's postcondition
did not latch inline; Root later verified the exact native notice, Viewer, and
active history from retained evidence and recorded one use from a frozen exact-
history observation. Its timestamp is an observation anchor, not the precise
POST time. Same-grant attempts 3 and 4 exposed and fixed inline-card gate and END
recognition issues. Attempt 5 then completed the same target with 14 pages and
positive END; Root audited the genuine Manifest and ZIP, and the grant and work
cooldown remained unchanged. Post-capture full/incremental Discovery has also
completed. Stage 03 is accepted with qualified composite live evidence and
independent BLOCKING 0. Stage 04 has started. Its existing-grant work-novel
chapter-10 capture completed with 18 WebP pages and positive END; the grant was
unchanged. The work-dual chapter-51 public-free capture completed with 16 WebP
pages and positive END, with grant/quota state unchanged. Both ZIPs and
Completed states passed Root's artifact audits. Independent Tester audits of
both A6/A7 ZIPs, Manifests, Catalog state, and first/middle/final pages passed.
The affected scope passed 261 tests with 0 skips and 305 deselections. The final
Reviewer gate passed with independent BLOCKING 0; the full-suite run was controlled-stopped and
is not a full pass.

## Stage 03 current implementation (2026-11-16; qualified PASS, independent BLOCKING 0)

Authenticated Discovery classifies the exact image-only
`span.mod-episode-free_browse` marker as `quota` when bound to a unique
authenticated row/source without conflicting access markers. The image has no
text node; `data-is-free="true"` alone is not evidence. Metadata Discovery
verified 22 such rows among 57 in `work-dual` and 29 among 37 in `work-novel`;
two `work-dual` rows remain unknown. The visible exact
`.episode-free-time.charged` / `チャージ完了` is required before a ticket action.

Yanmaga Policy supports one work-scoped `work_ticket` pass, limit one,
after-observed-consumption persistence, grant-only, and the existing 23-hour
local cooldown. A trusted future Catalog grant plus fresh active same-target
Rental History remains direct without extending its stored expiry. Separately,
Discovery may import a fresh finite grant for an exact active Rental History
card when the current row is raw `unknown`; it does not infer a cooldown or
import an `owned` row.
The shared `entry_only` path writes no page Manifest or Progress state, image,
ZIP, or completed Item; failure diagnostics are metadata-only. Normal capture
output is unchanged. Yanmaga's `prepare_entry_only_page()` skips its
capture-only native pixel observer for the fresh Batch-owned Page; it does not
generalize reuse behavior for a Page that already has that observer.

Read-only Source GETs for `work-dual` chapter 29 and `work-novel` chapter 10
showed the exact episode-bound modal, three-day period, and normal same-origin
POST form at `/rental/episodes/<episode-id>/by_free_waits`. The first-free
notice remains exact `無料レンタルが完了しました`; ticket success uses the distinct
exact `レンタルが完了しました`. The work-ticket path does not accept a generic
notice or the first-free notice.

Dual chapter 29 Run 10 emitted one native ticket POST, but the then-current
production postcondition did not latch or persist it. Root later verified the
exact notice, Viewer, and active history from retained evidence and applied one
frozen exact-history observation to Source 25 and work cooldown state. The
observation at `2026-11-16T00:23:46.090627Z` showed `残り2日`, producing lower bound
`2026-11-17T00:23:41.090627Z`; this anchor is not the precise POST time. The
applied record is `stage03/dual/late-confirmation-applied.json`; reapplication
is rejected. Same-grant attempts 3 and 4 were incomplete: attempt 3 saved 13
pages before a reader-gate timeout; attempt 4 saved 14 body pages but did not
establish END. Root's saved page showed the next-chapter point/rental metadata inside the unique
`#rental` auxiliary. The site-local gate now excludes only the observed
`.episode-modal-point`, `dl.episode-modal-point--posession`,
`dl.episode-modal-point--necessary`, and `.episode-modal-short` nodes there;
semantic dialogs and all body/END checks remain gates. Attempt 5 then completed
all 14 pages with positive END and no new ticket POST. Root audited the genuine
Manifest and ZIP. The existing grant and work cooldown were unchanged. The
Stage 03 full/incremental post-capture metadata refresh also completed with zero
Source, Viewer, and native rental POST activity. Its audit confirmed the target
and completed Item/Artifact state remained unchanged. No second ticket submit
is authorized.

Novel chapter 10 grant-only run succeeded with `stop_reason=entry_confirmed`,
zero pages, pending Item 26, and no Artifact. It emitted one native ticket POST;
Source=3 and Viewer=2 are request totals whose route types were not recorded.
The updated automatic notice/history proof and persistence succeeded. The
Source grant expiry is `2026-11-17T09:35:11.467066+09:00`; quota start and work
last-consumed time are `2026-11-16T09:35:16.467066+09:00`. The report is
`stage03/novel/grant_only-report.json`. These are the two Stage 03 ticket uses;
no more ticket action is authorized.

Wait and trusted-history parsing accepts exact `残りH時間` or `残りD日` within the
explicit 72-hour bound. D=1..3 uses observation start plus D days minus one hour
and five seconds with evidence `site_day_countdown_estimate`; fresh active
history remains required before entry. H=1 has no finite expiry. No fixed 72-hour
grant is created. Ordinary first-free remains capped at 23 hours and rejects
day notation.

Focused synthetic verification: Rental History browser tests 37; wait-ticket /
rental-form browser selection 18; first-free adapter regression 15; adapter and
policy unit files 41. Six initial first-free failures were caused by a fixed
November 15 test grant that had expired; the test fixture now uses a fresh
relative timestamp and all selected tests pass. Independent review of the
notice/day/late-record code passed BLOCKING 0. Five focused browser cases cover
the observed terminal countdown branch, and the Yanmaga adapter unit file passed
10 tests. Attempt 5 completed 14 pages with positive END and an audited genuine
Manifest/ZIP; the existing grant and work cooldown remained unchanged. The
post-capture full/incremental metadata refresh also preserved the target,
grant, and artifacts with zero Source, Viewer, and native rental POST activity.
Stage 03 is accepted with qualified composite evidence and independent BLOCKING
0. Stage 04 A6/A7 captures completed: work-novel chapter 10 used its existing
grant for 18 WebP pages; work-dual chapter 51 used public-free access for 16
WebP pages. Both reached positive END, ZIP, and Completed with no new right and
unchanged grant/quota state. Pre/post full/incremental Discovery preserved
Catalog state without Source, Viewer, or native rental POST. Independent Tester
audits passed. The affected scope passed 261 tests with 0 skips and 305
deselections. The final Reviewer gate passed with independent BLOCKING 0; the full-suite run was
controlled-stopped and is not a full pass.

## Latest-listed terminal follow-up (2026-11-16)

The normal Catalog still contains the original failed chapter-53 item and its
saved output. A separate isolated Catalog/output copy was used to verify the
new latest-listed END branch. On that copy, Source 49898 / Item 49591 completed
Run 25261 with 16 pages and `stop_reason=end`; the final UI had the observed
author-follow card and matched the unique last row of the complete fresh
listing. The run used one Source GET and one Viewer GET, with no other episode
request or ticket POST. Root audited the genuine 16-page Manifest and ZIP
(SHA-256 `61f770a67145554065ea67f9ccec243abc91f6f8030451845eb314adb90e53f4`).
The isolated run did not modify the user's normal Catalog or overwrite the
original failed output. Focused verification passed 30 relevant adapter browser
tests and 10 adapter unit tests; no full-suite rerun was performed.

## Discovery target pacing (2026-11-13)

CLI/GUI Discover uses shared `discovery_inter_target_delay_ms` (3000 ms in
the root YAML) after this target closes, only before another target starts.
The first/single/final target adds no delay; site changes retain the previous
site setting. Existing listing-page waits remain independent. See
[shared runtime details](00_core.md#phase-1-runtime-settings--pacing).
Synthetic CLI/worker ordering is verified; live timing is unverified.

## Stage 02 Discovery sort identity correction (accepted sub-gate)

The initial C implementation assumed canonical and og:url remained unqueried
after selecting the oldest-first control. A bounded, read-only production
Yanmaga Discovery uses `YanmagaDiscoveryAdapter` with the standard
`DiscoveryService`; the adapter does not write Catalog directly. The optional
`configure_source_snapshots(target, snapshots)` hook receives an immutable
tuple filtered to the same site and exact Discovery key. Discovery rechecks
the full listing after asynchronous Rental History proof and emits no rows on
identity or content drift.

Shared Batch adds a site-neutral immutable `ConfirmedAccessGrant` observer.
The Executor binds it to the validated Catalog source and synchronously
calls the grant-only Catalog API before capture continues. That API updates
only the source grant expiry and timestamp. The schema is unchanged; other
site adapters retain default no-op hooks, and Runner remains Catalog-free.

### Historical main integration baseline (2026-11-06; pre-Stage 02)

At the original integration checkpoint, Batch required an explicit
Watchlist and synchronized acquisition scope. The split Yanmaga Unit,
Viewer, Discovery, CLI, registry, and common Planner/Executor selection
passed 407 tests with 0 skips, and the historical full Ruff and independent
review checks passed. Those counts describe that earlier baseline, not the
current Stage 02 implementation. The Stage 02 affected tests and final full
suite status are recorded in `runbooks/yanmaga-access/PROGRESS.md`.

## URL・Identity

- HTTPS / exact host `yanmaga.jp` / canonical work path
  `/comics/<slug>` を要求する。query、fragment、認証情報、foreign host、
  foreign redirect、canonical/`og:url` の不一致を拒否する。
- Episode identity は作品slugと32桁小文字hex IDの組
  `<decoded-work-slug>:<episode-id>`。Catalogのweb targetは作品slugを保持する
  公開URL `/comics/<slug>/<episode-id>`。
- `discovery_scope` は未対応。`supports_bounded_discovery=False`、
  `allow_inferred_display_positions=False`。

## Listing・順序

`.detailv2-episodes` 内の `.mod-episode-item` 全件を検証する。行ごとに
一つのanchor、同じwork slugのepisode URL、表示中のrow、非空の
`.mod-episode-title` を確認する。`もっと見る` の
`.mod-episode-more-button` だけを通常clickで展開する。limit/offset/sort/path
とrow挿入位置を検証し、追加IDが既存IDと重複せず既存順序が保たれること、
一覧が安定すること、他の有効なpaginationがないことを確認する。
`data-limit` がない場合は実サイトで確認した150行pageを上限とする。
明示limitは1〜150の正規整数のみとし、空文字・不正値は欠落扱いにしない。
継続buttonが残る場合、次offsetは前offset＋追加行数と一致しなければならない。
最大100回/5,000行までで、未知のcontrol・重複・partial・driftは
`DiscoveryIncompleteError`。全レコードをbufferしてからyieldする。

2026-11-17のサタノファニで、欠落limitを整数化していた旧実装の
`Yanmaga continuation range is invalid` を再現。native clickで
10→160→310→348行、offset 5→155→305、最後は明示limit=38、button消失を確認した。
修正後の通常DiscoveryService＋専用Catalogでもfull complete=true、348 Sources、
display positions 1〜348を確認。作品一覧のみを操作し、話/viewerや権利消費は行っていない。
人工browser回帰は同じ3段階展開と、過大追加・offset drift・進捗なしの
0件yield／既存Catalog維持を検証する。

Work pages are not assumed to be oldest-first by default DOM order. When the
observed sort controls are present, Discovery validates and selects the exact
oldest-first same-work URL. The resulting complete DOM order supplies
global_display_position; records are yielded latest-first. Without sort
controls, the existing oldest-first fixture contract remains. Order and
missing rows are never inferred from IDs, dates, or titles. A complete public
listing snapshot does not invent unpublished or future backend rows. The exact
native upcoming row described above is internal metadata only and never proves
readability or creates an acquisition target.

## Viewer・Capture

`YanmagaAdapter` binds the configured `<decoded-work-slug>:<episode-id>` to
the original Catalog `source_url` and freshly validates the exact requested
source. The normal public-free path still requires the exact visible red-free
marker. Stage 02 also permits one public-episode GET for a fresh authenticated
exact first-free row; that route may grant access automatically. The adapter
requires the exact Viewer, the exact first-free completion notice, and finite
target-bound Rental History evidence before synchronously persisting the
grant. A trusted stored
grant can authorize direct retry only when its Catalog expiry is still future
and a fresh same-target countdown is active. The markerless existing-rental
recovery above also permits a newly observed finite hourly grant to be
reconfirmed and durably saved through the Batch observer before entry.
Unknown, conflicting, expired,
or unsupported states fail closed. The Stage 03 wait path requires a unique
image-only marker, fresh charged state, verified no-target Rental History, and
the exact source modal/form before one normal `読む` click. The wait path
requires the distinct exact work-ticket completion notice. Novel chapter 10
grant-only verified the exact post-click Viewer, notice, active history, and
automatic persistence. Dual chapter 29 Run 10 required later frozen-history
recovery; its same-grant capture succeeded in a separate run. `direct`, `auto`,
and the bounded `work_ticket` strategy are supported; daily-limit scope remains
unverified.

実navigationではpublic episode URLが同じslug/episode IDを持つ
`/viewer/comics/<slug>/<episode-id>` にredirectした。Viewer URLには一度、
`cid` query field一つ（値は20文字のASCII英数字）が付いた形も観測した。
episode identityはstrict pathから判定し、no-queryまたはこの単一query形だけを
許可する。duplicate/additional/malformed query、credential、fragment、別host/slug/
episodeは拒否する。Adapter所有metadataには`cid`値を含めず、Manifestのsource URLは
元のpublic episode `source_url` のままにする。Generic Core failure diagnosticsは現在URLを
記録するため、このopaque query値が診断artifactに入る場合がある。ignored diagnosticは
sensitive扱いとし、commitしない。

### 観測済みsource pipelineとcapture方式

完全なページ画像を含むupstream配信は確認できなかった。対応upstream JPEGは
shuffleされたtile atlasで、viewerがatlasの矩形をcanvasへ複数回`drawImage`し、
3つのsegment canvasをJPEG quality 0.9で再encodeしてからbody imageのBlobを作る。
したがってatlasやJPEG segment bytesはページ原本ではなく、すでにlossyなtransport
imageである。

Observerはstrictなtop-level Yanmaga viewer documentにだけinstallし、確認済みの
`toDataURL('image/jpeg',0.9)`直前に限定サイズ・色空間のcanvas RGBAをcopyする。
JPEG payload、Blob bytes、body image `blob:` sourceに一意なfresh candidateをexact byte
matchで結びつける。同payload再生成時には下記の画素履歴証明も必須とする。
曖昧match、hook conflict、source drift、非opaque画素、
上限超過、未確認style/layoutはnative groupを拒否する。hookは元のviewer呼び出しの
引数・戻り値・例外を保ち、owned hookだけをcleanup時に復元する。
同じJPEG payloadの再生成では、一意なfresh candidateと直前の同payload candidateの
検証履歴・未解放のRGBA全byte一致をBlob非同期read後に確認する。履歴欠落・衝突・複数fresh
候補は拒否し、既存の検証済みbindingは保持する。第53話は修正後16ページ全WebP・ENDを
確認済み。詳細な判定とlive evidenceは本note冒頭を参照。

確認済みのnested DOMは`#content-pN > .pt-img > 3 absolute clipped segment host > img`
である。logical `.pt-img` boxは倍率1.125・0.03 CSS pxの許容差で、明示的な1125×1600または
1127×1600のprofile一つと一致する必要がある。source segment幅はそれぞれ1127または1129、
高さは536/536/538、native Y offsetは0、532、1064。DOM順に重ねて選択profileのboundsへclipすることで4-row
overlapと最終segment下の2-row overrunを処理する。wrapperのright paddingは0または2 CSS px
の観測形だけ許可し、viewer gutterは出力へ含めない。wrapperはpure horizontal translation
だけ許可する。segment host `::after`はcomputed styleが正確なempty content・fully transparent
で、border/shadow/filter/backdrop-filter/transform/blend/mask等のpaintがない観測形のみ許可し、
style proofはcapture後・spread全体でも再検証する。

再構成画素をsingle-frame lossless WebP (`VP8L`)へencodeし、opaque RGBA、1125×1600または1127×1600
dimensions、Pillow decode後のpixel equalityを確認する。Manifestは`image/webp` / `.webp`
を記録し、metadataは`source_native_bytes_used=false`、
`source_native_pixels_used=true`とする。source/geometry/style/group proofまたはencode検証が
不成立なら理由を記録する。`segment_source_not_exactly_bound`または`capture_buffer_overflow`では、表示中の実img参照から
上記decoded-source pathをgroup全体で試す。こちらも証明できなければrendered locator PNGへ
fail-closed fallbackする。decoded経路はJPEG decode後の画素でありpre-JPEG画素とは区別する。
Fallbackは検証viewport 2560×1800で1266/1268×1800であり、source-native bytesとは呼ばない。

Readerはnative counter `1/36`、direct `#content-pN` wrappers、見開き時の連続2ページ表示。
初期位置が末尾でもbounded normal keyboard turnでpage 1へ戻す。capture前にはfirst page menuを
通常keyboard 1→2→1で隠し、stable hidden-menuと8-point perimeter proofを要求する。全body indexの
順次capture、route/counter/index/source/styleの安定性も必須。
先頭で既知の前話確認が表示された場合は、本note冒頭の厳密な確認とCancelを先に行う。

positive ENDは全body indexのcapture完了、同じepisode route、stable final counter/body wrapperに加え、
別領域の単一`#rental` cardがviewport内に全体表示され、visibleで他elementに覆われていないことを要求する。
奇数・偶数とも最後の見開きを送った後のnative `-/N` は、冒頭のterminal-only専用検証で扱う。
通常の本文counterやcapture identityにはせず、全本文保存済み・右側へ退避した最終wrapper・
既知のslotに安定表示された正しい次話card・全周の遮蔽なしを要求する。
既存のnext/read・signup・waitと新しいpoint-rental終端では一意のtitleが表示される必要がある。
signup・wait・point-rentalではさらにfresh listingの対応rowと一致することを確認する。
card内controlはexact `次の話を読む`一つとsignupなし、またはvalid-nextなしでexact
`無料登録して読む` signup control一つのどちらか。signup URLはsame-origin HTTPS
`/customers/sign-up`、credentials/fragmentなし、唯一のraw query fieldは
`forward=<32 lowercase hex episode ID>`。tokenはfresh same-work listingのunique immediate next row IDと一致し、
表示titleもnormalized exact matchする。tokenをURLとして解釈・遷移せず、CTAを操作しない。
これらのcontrolが無い場合は、unique immediate next listing rowがexact wait markerとして
分類され、表示titleと一致するときに限り、unique visible `.aspect-ratio-2-27.mt-wait >
div.episode-modal-wait.content` blockを代替終端として受け入れる。blockのdirect childは
`img.icon-clock`（観測済みclock asset）と`span`の順で、表示文言は`あとH:MMで無料`
（Hは0〜23、分は00〜59）に一致する必要がある。countdownや他controlは操作しない。
これは終端cardの一種として本文全page capture、route、ownership、semantic-gate、安定性検査を
置き換えない。完全なfresh listingで対象話が一意な最後のrowの場合は、例外として、同じ
`#rental`配下にある観測済みauthor-follow cardを終端証拠にできる。対象話のtitle、next/read、signup、wait markerは存在してはいけない。
一意の`a.author-info`、正確な表示文言`作者をフォローして次の更新を待つ！`、観測済みX/arrow画像、HTTPS `x.com`リンクと既知祖先構造を要求する。リンクは観測だけで、押さない。
このbranchでもbody/route/ownership/access-gate/ENDの他検証はすべて維持する。
観測済みpoint-rental cardも冒頭の厳密なform/thumbnail/title/表示検証で終端にできる。
`レンタルして読む`やformは押さず、ポイントを使用しない。他の終端controlとの競合は拒否する。
Unknown layout、page gap/duplicate、spread片側欠落、未知auxiliary/access gate、source/style drift、
終端不明はfail-closed。next arrowは診断のみ。

## Access behavior: current Discovery evidence

The login observer is attached before work-page navigation. It accepts only
main-frame telemetry while the current page and frame identify the requested
work document, resets on main-frame navigation, caps matching events at 64, and
detaches on every exit. It retains the exact `ep.is_logged_in` state only; it
does not retain complete request URLs.

Anonymous proof requires a visible sign-in link, no visible sign-out or exact
same-origin `/mypage` link, current work-document identity, no telemetry
overflow, and consistent explicit `ep.is_logged_in=false` values.

Authenticated proof requires a visible same-origin `/mypage` anchor whose exact
path is `/mypage` and which has no credentials, query, or fragment; no visible
sign-in link; current work-document identity; and no telemetry overflow.
Analytics is supporting evidence only: it may be absent, but any observed state
must be `true`. Visible, query/hash/userinfo, foreign-host, trailing-slash, and
hidden link cases are covered by browser fixtures.

A public-free row requires one visible `.mod-episode-point--free` element with
exact text `無料`, exact class name, computed color `rgb(220, 0, 0)`, and
no `.by_wait` or `.js-modal` marker, first-free label, or conflicting native
free badge. It is accepted only on a verified anonymous or authenticated work
document.

A first-free row requires authenticated proof, exactly one total
`.mod-episode-point--free` marker and one first-free marker, exact text
`初回無料`, and the exact class-token set
`{mod-episode-point--free, by_first_time}`. Wait/modal markers, a red-public
marker, or another conflicting native free badge leaves the row unknown. A
numeric normal point badge may coexist. Only these observed public-free and
first-free states map to `access_mode=free`. A verified wait row maps to `quota`.
Point-only rows map to `paid` under the rule below; unsupported access states
remain `unknown` and every row remains `available=True`.

ポイントのみの行は、検証済みanonymous/authenticated作品一覧で、
`data-is-free="false"`、最内側のpoint badgeが一つだけあり、可視・exact class
`mod-episode-point--normal` または `mod-episode-point`・正のASCII整数価格である場合に
`paid` とする。価格を包むnative icon wrapperは重複価格に数えない。無料・初回無料・
wait markerや矛盾する無料表示があればこの判定を適用しない。0、不正値、hidden、
重複、未知class、未検証login状態は `unknown`。無料・wait・有効な有限Rental History
grantの判定を優先し、point表示からgrant消失を推測しない。既存Sourceへの反映には
通常のFull Discoveryを使い、Item status等は変更しない。既存free/quota行がpoint-onlyの
観測で `paid` に変わる場合も保存済みgrant期限は維持し、既存の有効grant Policyを使う。
CLI/設定追加はない。
有効grantのない `paid` はSite PolicyによりBatch対象外となる。保存grantなしの場合の
skip reasonを `paid` に揃え、Inventoryでは有償件数として集計する。
不正/期限切れgrantの既存reasonと、有効grantによるdirect判定は維持する。

2026-11-18のshared-CDP一覧確認では、妹は知っている第96/97話に70ポイント、
パラレルパラダイス第345/346/347話に90ポイントの上記native badgeと
`data-is-free="false"` を確認した。話/Viewerやポイント操作には入っていない。
変更後の通常DiscoveryServiceを隔離Catalog backupへ実行し、Fullを98行
（free 6 / quota 90 / paid 2）と348行（free 7 / quota 338 / paid 3）で完走、
既存5 Sourceが `unknown → paid`、unknown 0であることを確認した。
Source identity、Item状態、保存grant、Artifact、Run、Work resource stateは維持され、
話/Viewer/non-GET request各0。通常Catalogへの書込みはない。証拠は
`.tmp/yanmaga-point-paid-live-20261118/report.json`。
Discovery/Policy/Adapter UnitとDiscovery browser Integrationは2回の実行で計179件成功、
skip 0。Policyのreason変更後、Policy/Inventory/GUI modelの95件も成功、skip 0。
隔離live CatalogをInventoryServiceとGUI status projectionで検証し、両作品の
paid件数2/3、unknown 0、status「候補あり」を確認した。
`ruff check src tests --no-cache` と変更対象の `git diff --check` は成功。
site-local分類変更のためViewer/capture Integration、Research、full pytestは未実施。

Yanmaga sends `free_until=None` on each refresh because no free-expiry value was
observed; under the existing Catalog refresh contract this clears a stale
free-expiry value. A public listing does not assert a new grant expiry, so
`access_granted_until_observed=False` and Catalog preserves an existing grant.
For otherwise unknown free/paid rows, fresh exact-target Rental History evidence retains a previous mode only while
its trusted stored expiry remains future; it does not extend that expiry. For
unknown/point-only rows, a fresh exact active card with a finite countdown imports a
new `quota` classification and observed expiry. Missing, duplicate, mismatched,
or active-without-finite-expiry evidence leaves the raw classification
unchanged; `owned` is excluded. The general Catalog contract still treats an
explicitly observed null as authoritative. Lead's isolated regression run
confirmed preservation and clear behavior.
Known quota additionally remains quota after complete exact-target inactive
history proof, and that proof explicitly clears its old grant. Incomplete
history is not inactive proof. This is the underlying ticket category; actual
availability and consumption still require the live entry checks.

The Stage 01 authenticated sample had no wait marker classification and kept
those rows unknown at that checkpoint. Stage 03 added the observed image marker
and charged-state requirement for ticket use; the later authenticated Rental
History join above recovers exact active rentals with finite bounds. Discovery
still opens no episode or access CTA. Point-only paid classification is supported
as described above; daily-limit scope remains unverified.

Live evidence on 2026-11-15 JST: `work-dual` returned 57 rows after the
Discovery change: 27 first-free, 8 public-free, 22 unknown. The authenticated
shared-profile page had five visible exact `/mypage` links, no sign-in/out
labels, current work identity, and consistent true telemetry. The temporary
empty-context comparison had no `/mypage` link, two sign-in links, and false
telemetry. The wife-list continuation had no `data-limit`; this was unsupported
at the Stage 01 checkpoint. The current 150-row pagination contract is described
in Listing・順序 above. Refer to
`runbooks/yanmaga-access/PROGRESS.md` and its isolated stage01 evidence files.

## 実サイト確認・テスト・既知の制約

Browser Integrationは、成功時とfailure時のobserver listener cleanupに加え、hidden row、foreign episode/canonical、
continuation sort drift、unsupported paging、no-progress、continuation fetch failureについて、recordをyieldせず
既存Catalogをunavailable化しないことを検証する。fetch/no-progressとhidden rowの待機はテスト内で短縮する。

指定作『ウサギとカメのゆる山歩』をshared Crawler Chrome/CDPとPlaywrightで
Discoveryした。native continuationを通常clickで展開後、13 unique rows、
continuation control消失、安定snapshotを確認。fullは13件完了、incrementalは
共通serviceのknown streak 5件で停止。current Catalog snapshotでは5件が`free`、
8件が`unknown`、global positionsは1〜13。Discoveryのlive検証では話を開かず、
チケット/ポイント/Grantを消費していない。これは現在のpublic listingの観測であり、
全バックエンド話数を証明しない。

対象Unit/Browser Integrationは `tests/unit/test_yanmaga_discovery.py` と
`tests/integration/test_yanmaga_discovery_browser.py`。URL/host、marker、
anonymous proof、展開・順序、full/repeat/incremental、stale expiryの消去、
incomplete fullの既存Catalog保護、Completed/Artifact保持、重複失敗を検証する。


### Phase 03 Viewer/Capture (N2/N4 accepted; Chapter 11 WebP Batch E2E passed)

N1の初回Runnerはrendered locator PNG fallbackを36ページ保存した。この出力は現在方式ではなく、
安全なcapture proofが成立しないときに使用するfallback pathの履歴として残す。
N2ではfresh shared-CDP normal `CrawlerRunner`を対象Chapter 1へ実行し、`stop_state=end`、
36 body indices、36 Manifest pages、36 filesを完了。全36が`native_pre_jpeg_lossless_webp`、
`image/webp`、1125×1600で、fallback reasonは0。別のoffline auditで36ファイルすべてを
Manifest SHA-256 fingerprintに照合し、36 unique hashes、single VP8L frame、decode success、alpha255を確認した。
Page 1/18/36を前回rendered PNG controlと目視比較し、本文全体・順序・cropが揃い、reader UI/広告/終端cardが
混入していないことを確認した。この比較はvisual/geometry確認でありpixel identityではない。
WebP encoderは各pageでcomposed RGBAとの厳密なdecode round-trip equalityを別途確認する。

Live output/evidence: `output/yanmaga_experiment/native-live-full-webp-20261020/`
(sanitized summary and offline audit). Complete original page responseは観測せず、保存形式は
viewer canvasのJPEG再encode前RGBAからのlossless再構成である。No ticket/point/quota/grant/next action。
The current Yanmaga Unit + browser Integration selection passed 76 tests, 0 skipped, with 23 existing pytest-asyncio/Python 3.14 deprecation warnings. Full `ruff check src tests` passed. N2 capture and N4 retention-cap changes were accepted by the independent Reviewer with BLOCKING 0. The normal Chapter 11 WebP Batch/ZIP E2E and exact all-20-page RGBA reference comparison passed; details are in the N4 and Phase 05 sections of `runbooks/yanmaga-free/PROGRESS.md`.

#### N4 bounded raw-pixel retention

An ordinary Chapter 11 preload reached the previous 96 MiB raw-pixel cap before first capture.
Separate first-party evidence showed 60 segment responses before first PNG and 145,157,600 raw
bytes for the known 20-page chapter, so 128 MiB was insufficient. The accepted fixed cap is
256 MiB (268,435,456 bytes) in both the Python helper and browser observer. The known 36-page
profile uses 261,283,680 bytes (about 249.2 MiB). This limits retained pixel arrays only; it is
not a preallocation or a limit on all JavaScript heap/Chrome RSS. Other finite bounds are unchanged.

The eager-60 browser regression verifies exact candidate binding, retained-byte accounting before
first capture, native WebP for page 1, and one-page release. A numeric test covers the exact cap
boundary without allocating a cap-sized buffer. A bounded isolated ordinary CLI probe observed
21 bound candidates / 50,805,160 raw bytes before capture, then 43,547,280 bytes after releasing
page 1; it saved one native 1125×1600 WebP and intentionally exited at `--max-pages 1`, without
reaching END or packaging. No page-ID association is inferred for the other retained candidates.

### Phase 04 Batch, extended by Stages 02 and 03

`YanmagaSitePolicy` admits an available, correctly identified `free` source
when its observed `free_until` is absent or still future. An available
`quota` or `paid` source is direct only with a valid exact episode identity and
a timezone-aware future `access_granted_until`. Without that grant, a validated
wait-free `quota` source uses one work-scoped `work_ticket` pass with
after-observed-consumption persistence. The resource supports grant-only while
ordinary free and first-free rows remain excluded from that pass. Malformed,
expired, or missing grants do not become direct; the Planner's existing
fail-closed behavior remains.

The capture adapter preserves three direct-entry cases: the public red-free
row, the fresh authenticated first-free row with one bounded source entry
and finite grant proof, and a trusted stored grant revalidated by fresh
same-target active Rental History evidence. A work-ticket candidate requires
the exact authenticated wait row and charged signal, verified absence of an
active rental (target absent or exact expired card) in the complete supported
Rental History collection, and the observed same-episode
modal with its exact native POST form. Only its visible enabled `読む` button
may be clicked, once. The source modal and pre-click history shapes were
observed read-only. Run 10 made one normal click and emitted one native POST,
but its automatic postcondition did not latch or persist the use. Root later
verified the exact notice, Viewer, and active history read-only and applied the
frozen history observation once to Source/work state; its anchor is not the
precise POST time. The same-grant direct retry is described in the current
Stage 03 section above. No second click is authorized. Unknown access, paid-only without a trusted grant, identity drift,
or a visible gate does not authorize entry. Normal image, END, and packaging
checks remain strict.
A bounded Stage 02 C1 CLI run used one additional first-free entry on the
separate candidate `episode-ff-capture-01` (position 31; the earlier research
release was position 32). It confirmed the first-free access and synchronously
stored the native countdown's conservative lower-bound grant before an
intentional `capture_page` failure after readiness/rewind but before the first
saved content page. Source GET=1, Viewer GET=1, other episodes=0, first-party
non-GET=0. The Item remained pending, one CrawlRun failed with
`page_count=null`, and no page file, Artifact, quota start, or Work resource
state was created. This does not verify successful capture, END, ZIP, or
Completed state; the countdown lower bound is not the site's absolute expiry.
The separate C2 retry without an external Catalog DiscoveryService run has also
completed: the Adapter still performed its fresh internal listing preflight. It
used one Source GET, one Viewer GET, and the capture hook after readiness/rewind
but before the first saved content page, with no new first-free use, other-
episode attempt, or first-party non-GET request. The same future-aware native-
countdown lower-bound grant remained unchanged; the Item stayed pending, two
CrawlRuns failed before a content page was saved, and no Artifact or
quota/resource state was created. This does not verify successful capture, END,
ZIP, or Completed state.
Research plus C1 consumed two first-free uses in total; C2 consumed none, and the
additional allowance is exhausted. Ticket/point/paid actions remain zero.
Post-C2 full/incremental metadata Discovery and direct-plan validation are
complete and independently audited. The later C8 ordinary capture with the same
grant also completed successfully. Post-capture full Discovery and incremental
results, plus the Stage 02 PASS / BLOCKING 0 gate, are in the current-state
section above. The v3 QA stop's raw result is missing, so its underlying
production outcome remains unknown. Evidence is in the ignored Stage 02 reports documented by
`runbooks/yanmaga-access/PROGRESS.md`.

The earlier synthetic Batch Integration verified the normal public-free
path through Catalog planning, capture, ZIP CRC, Artifact, CrawlRun, and
Completed state. The separate Phase 05 live CLI evidence below is limited
to the observed Chapter 11 case and is historical site evidence.

### Phase 05 isolated real-site CLI (historical PNG E2E and current WebP E2E PASS)

Tester used an isolated Watchlist, Catalog, archive/output, and library under
`output/yanmaga_experiment/phase05-independent-token/`. Full Discovery completed 13 rows;
incremental observed five known rows; the initial plan contained five `free/direct` candidates,
eight `unknown` skips, and quota 0. Normal Planner order selected Item/Source 2, Chapter 11
(`aac67662e0d47437726ee7034126a8ea`); selection and access state were not manually changed.

The ordinary `batch run --limit 1` exited 0 with `stop_reason=end`. CrawlRun 1 succeeded with
20 pages. The ZIP contains exactly 20 ordered Manifest pages; CRC passed, each payload matched
the Manifest fingerprint, all PNGs decoded, and all 20 payload hashes were distinct. Eleven
images are 1266×1800 and nine are 1268×1800. Tester and Root independently audited the archive.
First/middle/last images show manga body pages without reader chrome; the final image has no
terminal card. ZIP SHA-256 is `e0f3fc218937699e957c5854633f70291d22069ca83284235f13029291d5cc88`,
size 53,755,787 bytes. The Artifact is `archive`/`zip`, state `present`, and matches the on-disk
ZIP; Item 2 is `completed`.

A repeated full Discovery (13) and incremental Discovery (5) preserved all Source/Item IDs and
display positions, Item `completed_at`, and Artifact. The final plan contains four direct
candidates, eight unknown skips, and one completed skip. No ticket, point, grant, login,
purchase, quota operation, signup CTA, or next-episode action was used. Ordinary CLI metrics
defaults remained enabled. The unique task metrics file was emitted to the CLI's default
`output/metrics` location, then moved by exact path into isolated QA; the Watchlist, Catalog,
archive, and capture output used dedicated paths throughout.

The Watchlist explicitly supplied label `yanmaga-usagi`; the archive path used fallback genre
`小説`. These explicit/fallback metadata values do not assert the site's displayed work title.
The successful capture in this E2E was rendered locator PNG output, not source-native bytes; it
predates N2 and does not verify the current WebP Batch packaging path. N2's 36-page Chapter 1
Runner traversal is separately verified above. The E2E proves only this observed Chapter 11
candidate/layout. The daily-free notice's scope remains unknown,
missing or conflicting anonymous analytics remains `unknown`, and other reader layouts are
unsupported.

Earlier failed attempts remain historical: the first reached the signup boundary after 20 pages
before a positive END contract existed; one subsequent attempt failed before capture on the
measured 2px p2/p3 wrapper overlap; another reached the end after 20 pages but failed closed
because the signup CTA's `forward` query was not yet recognized. The final strict predicate now
requires a same-origin HTTPS `/customers/sign-up` URL with no credentials/fragment and exactly
one raw 32-lowercase-hex `forward` value matching the unique immediate next row in the fresh
same-work listing and the normalized rental title. The token is compared only; it is never
interpreted as a URL or navigated. The CTA is never activated.

Historical Phase 05 combined tests: **209 passed, 0 skipped**, with 423 existing pytest-asyncio/Python 3.14
deprecation warnings (148.67s). `ruff check src tests` and `git diff --check` passed. Full
`pytest -q` and the standalone Research suite were not run because changes were site-local plus
registries and did not alter shared Core, schema, or Probe contracts. The independent Reviewer
accepted the current N2/N4 implementation with BLOCKING 0. The implementation commit recorded above predates the
N2/N4 follow-up. Detailed sanitized audit is in the ignored
`output/yanmaga_experiment/phase05-independent-token/qa/tester-report.md`.

### Current Chapter 11 native-WebP E2E

The first fresh ordinary CLI attempt in `output/yanmaga_experiment/nv-e2e3/` returned a
complete=false Discovery result with zero observed/new/known records; the isolated Catalog
contained only its Watchlist Work and no Items, Sources, Runs, or Artifacts. A single direct
normal CDP adapter diagnostic then completed with 13 rows, no continuation, HTTP 200 for the
work document and native episode-list request, and explicit anonymous telemetry `false` with
no overflow. It did not identify why the first CLI attempt was incomplete. The subsequent
unmodified ordinary CLI retry completed successfully; no production code was changed for this
transient/unreproduced result.

The successful isolated run returned full Discovery 13 and incremental Discovery 5. Its initial
plan contained five `free/direct` candidates, eight `unknown` skips, and quota 0; normal Planner
order chose Item/Source 2, Chapter 11 (`aac67662e0d47437726ee7034126a8ea`). Normal
`batch run --limit 1` exited 0 with positive END and 20 pages. All 20 Manifest entries are
1125×1600 native-pixel lossless WebP (`VP8L`), with unique payload hashes and no fallback. The
ZIP contains exactly those ordered pages, passes CRC and Manifest hash checks, and is 18,830,115
bytes with SHA-256 `8d32c1ba953e2093e4c42945ce8bd1c2ff940884d2c343f6b68dc5ba6d4232b5`. The
Manifest snapshot SHA-256 is `e4d0bdec2c96606023a10c085dd100d8c952b5a598f9e6343f50ea7da2d68daa`.
The Artifact is present and matches the ZIP; Item 2 is completed. Repeated full/incremental
Discovery preserved Source/Item IDs, positions, completion time, and Artifact; the final plan
had four direct candidates, eight unknown skips, and one completed skip.

Tester audit: `output/yanmaga_experiment/nv-e2e3/q/primary/archive-audit.json`;
Root's independent archive audit: `output/yanmaga_experiment/nv-e2e3/q/primary/root-independent-audit.json`.
Both passed. Tester visually checked first/middle/last body pages; Root's all-page contact sheet
and ZIP audit found body pages without reader UI or terminal-card contamination.
Independent reference capture obtained 60 segments for all 20 pages with no overflow, send failures, or scan errors. Pillow-composited references exactly match decoded WebP pixels. Tester audit: `output/yanmaga_experiment/nv-e2e3/q/tester-report.md`, `output/yanmaga_experiment/nv-refcontrol4/q/primary-vs-reference-audit.json`, and `output/yanmaga_experiment/nv-refcontrol4/q/assembly-report.json`; Root's independent comparison is `output/yanmaga_experiment/nv-e2e3/q/primary/root-independent-pixel-equality.json`.
No next-episode/signup action or ticket, point, quota, grant, login, or purchase operation occurred.

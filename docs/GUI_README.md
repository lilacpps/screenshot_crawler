# Windows 作品管理GUI（P2・選択実行 / P3・ジョブ管理 / Watchlist編集）

Python 3.12以上とPySide6を使うローカルアプリです。Catalog v7とWatchlistを表示し、
チェックしたWatchlist keyだけを実行対象に
Discover / Batch Run / Grant-onlyできます。通常の実行は詳細確認画面を出さずジョブへ登録します。
Grant-onlyでは操作欄に権利・チケット・Quotaを消費する可能性を明示します。

## インストール・起動

リポジトリのルートで実行します。既存CLIだけを利用する場合、gui extraは不要です。

```powershell
python -m pip install -e ".[gui,dev]"
screenshot-crawler-gui --catalog catalog.sqlite --watchlist watchlist.yaml --runtime crawler.yaml
```

## トップ画面でDiscoveryのON/OFFを切り替える

一覧の「Discovery」列で、Watchlist項目のスイッチをクリックするか、セルを選んで
Spaceキーを押すと即保存します。確認画面や保存ボタンはありません。
ONにしてもDiscoveryは開始しません。「実行対象」のチェックと実行ボタンで開始します。
OFFはDiscovery対象から外す設定です。登録済みの話のBatch取得は停止しません。
作品・サイト行の「有効N／全M件」は、検索で隠れた項目も含む集計で、一括変更はできません。

保存中は「保存中」と表示し、他のスイッチ・編集・入力パス変更・ジョブ開始・GUI終了を
一時的に止めます。実行中または終了未確認のジョブ、古い一覧、編集画面の未保存変更や
処理中操作がある場合も切り替えできません。未保存変更は先に保存または破棄してください。
保存後は一覧と開いている未編集の管理画面へ反映し、以前の変更プレビューは無効になります。
実行チェック、検索、並べ替え、フォーカス、展開状態、スクロール位置は保持します。

外部編集との競合や書き込み失敗は上書きせず、再読込を案内します。
「保存済み・表示更新失敗」と表示された場合、設定は保存されています。再読込してください。
待機中ジョブはWatchlist全体の版に結び付くため、この変更で実行が停止する場合があります。
ジョブ履歴から最新状態で再計画してください。Catalogや既存ZIPは変更しません。

## Watchlist管理・話数選択

### 新規登録・範囲・置換（作品単位）

ツールバーの「新規登録・範囲・置換」で作品編集画面を開きます。
上部の検索ボックスへ作品名またはwork_keyの一部を入力すると、一致する候補を表示します。
候補をクリック、または上下キーとEnterで選ぶと、その作品へ切り替わります。
英字の大文字・小文字は区別しません。入力するだけでは編集中の作品は変わりません。
「新しい作品」はwork_keyを入力し、「既存作品へサイト追加」は選択作品のwork_keyと
ラベルを引き継ぎます。未保存のまま複数サイトを追加できます。

1. 作品を選び、必要なサイトを追加して「両サイトの全話一覧を取得」を押します。
2. 各サイトの古い順の一覧から「この話から」「この話まで」を指定します。
   「最古から」「新着も含める」で境界を開放できます。
3. 途中の置換は元一覧の行をShiftで連続選択し「別サイトの話に置換」を押します。
   置換先のkeyと開始・終了を指定します。「新規サイトを追加…」も選べます。
   サイト間の話名対応は自分で確認します。置換元と先の話数が違っても指定できます。
4. 「完成後の並び」でサイト別の区間を確認します。上／下への移動、区間の範囲変更・
   削除ができます。1話だけの置換や複数箇所の置換にも対応します。
5. 「変更プレビュー」で担当数・維持・担当外・未登録と予測順序を確認し、
   「Watchlistに保存」を押します。新規話の番号・ZIP名の最終確定はFull後です。
6. 保存後の「Full Discoveryを実行しますか？」でYesを選ぶと、そのまま既存ジョブへ
   登録します。Noなら設定だけ保存します。メイン画面の実行チェックは変更しません。
   Fullの進捗・サイト別の成功／失敗は、メイン画面の実行モニターまたは「ジョブ」で確認します。

マガポケ／Comic DAYS／ゼブラック／少年ジャンプ＋の一覧と範囲・除外に対応します。
マガポケの従来のチェック式編集は下記の「Watchlist管理」でも利用できます。
新規登録にも既存の有効なCatalog v7を使用し、
保存前のDiscoveryやWork/Source仮登録は不要です。保存時点でCatalog・ZIPは変更しません。
Full失敗時も設定は保存済みのままで、自動再試行しません。無効keyは自動有効化しません。

Discoveryなどのジョブ実行中は編集できませんが、「×」またはEscで編集画面を閉じられます。
ジョブはそのまま継続し、未保存の変更がある場合は破棄確認を表示します。
この画面自身の一覧取得・プレビュー・保存処理中は、処理完了まで閉じられません。

Watchlist保存では、追加項目を対象keyの末尾、区切りの空行や次作品の見出しコメントより前へ
挿入します。既存の作品間の空行・コメント・改行形式を保持します。

範囲の外側の変更はFull成功まで以前のCatalog担当フラグが有効です。穴の除外は保存後
すぐ既存のBatch安全判定で拒否されます。既存の取得済み状態は別サイトへ引き継ぎません。
既存ZIPの削除・上書き・改名は行いません。番号変更後の整理は別のaudit/renumber操作です。

### プラネテスのPHASE24・25だけをComic DAYSへ置換する例

1. 作品検索で「プラネテス」を選び、「既存作品へサイト追加」を押します。
2. keyを`planetes-comicdays`、siteを`comicdays`、URLを
   `https://comic-days.com/episode/13932016480029865789`にします。
   work_key=`planetes`とラベルは引き継ぎ、有効にして追加します。
3. 「両サイトの全話一覧を取得」を押します。追加したComic DAYS側は、そのまま置換操作へ進みます。
4. マガポケの最下部3行のうち、PHASE24「咆える犬」とPHASE25「光の速さで45分」を
   Shiftで連続選択し、「別サイトの話に置換」を押します。PHASE26は選びません。
5. 置換先をComic DAYS、開始をPHASE24、終了をPHASE25にして確定します。
6. 完成後の並びが「マガポケPHASE1〜23 → Comic DAYS PHASE24〜25 → マガポケPHASE26」
   であることを確認し、「変更プレビュー」→「Watchlistに保存」→Full確認でYesと進めます。

両サイトの一覧件数は異なるため、行番号ではなく話名で両側を選びます。
既存の取得状態・ZIPは移動せず、実際の取得はFull完了後にBatchから行います。

### 従来のkey単位編集

ツールバーの「Watchlist管理」から専用ウィンドウを開きます。既定は作品→サイト→keyのツリーで、
検索・状態フィルタ、key一覧、選択keyの編集フォームを使います。key一覧は参照用で、
編集はフォームから行います。label・enabledの変更と新規key登録はローカルで行えます。
編集中の話数チェックは、実行画面のkeyチェックとは別に保持します。
上の作品／keyペインと下の編集領域の境界を上下へドラッグすると、作品ペインの高さを変更できます。
上のkey一覧と下の話一覧は、選択した同一作品に属する全サイト／keyを表示します。
話一覧にsite・key・取得状態・話名の出典を併記し、編集中key以外は参照専用です。
未Discoveryのkeyも「未Discover / 一覧未取得」の行として残します。

「作品内の話名・全話一覧を一時取得（読取専用）」は共通Crawler Chromeへ接続し、Adapterの完全一覧
機能だけを呼び出します。対応サイトはMagapoke・Comic DAYS・ゼブラック・少年ジャンプ＋です。未対応サイトは接続前に停止し、
Catalogの参照一覧を表示します。URL・scope・archive_orderの変更保存には、対応する完全一覧と
Catalogに結び付いたプレビューが必要です。label・enabledだけの編集は一覧非対応でも可能です。
作品内のkeyを順番に読み取り、一時取得した話名をtitle列に表示します。取得した一覧はウィンドウ内だけで
保持し、WatchlistやCatalogへ保存しません。Catalog参照ではDiscoveryが保存する`order_label`を優先します。
positionはサイト上の並び順で、実際の「第何話」とは区別します。話名不明は未確認のままです。

話数は個別チェック、全選択／全解除、サイト上のpositionによる範囲選択で指定できます。
編集中keyの行を右クリックし「開始 from_url に設定」「終了 through_url に設定」で境界を入力できます。
別keyの行では「このkeyを編集」で切り替えられ、未保存変更があれば破棄確認します。URLコピーも利用できます。
非空の選択を連続範囲＋内側の`excluded_external_ids`へ変換します。「変更プレビュー」で
追加・維持・除外・未Catalog・不明、取得担当、Catalog反映前後、archive番号の差分と
既存ZIPの現在名／予測名・改名の必要性を確認します。詳細は下部テキストをスクロールして確認できます。
プレビューはWatchlist・Catalog・ZIP・管理DBを書き換えず、ticketやquotaを消費しません。

「保存」はWatchlistのlock・ハッシュCAS・atomic replaceで基本項目と範囲・作品内の順序を
まとめて保存します。空選択、重複担当、不完全／古い一覧、Catalogの変更、未確定の採番は停止します。
明示archive_orderの作品で未登録話の番号を予測できない場合も停止し、番号を捏造しません。
通常のブロック形式YAMLのコメント・未知キー・CRLFを保持し、安全に修正できない複雑な構文は停止します。

穴の除外は保存後すぐにBatch／Grant-onlyで拒否されます。除外IDの所属が証明できないkeyも停止します。
外側の境界変更は、Full／Scope適用まで以前のCatalog担当フラグが有効です。
「Full Discovery」はまず同一作品の話名を一時取得し、明示keyだけを既存の実行前確認へ送ります。
確認をキャンセルしても一時取得した話名はウィンドウ内に残ります。実行画面の選択は変更しません。
一時取得の非対応・失敗はCatalog参照へ戻し、停止理由を表示します。実行確認へは進めますが、
取得中のWatchlist変更や実行Job開始を検出した場合はFull確認も停止します。
新規keyも最新Inventoryを再読込して確認します。Full完了だけでwork全体のScope同期済みとは扱いません。
「Scope preview」「Scope apply」は別操作で、適用前に差分を確認し、Catalog job lockとrevisionを再検証します。
既存ZIPは保存・Full・Scope適用では改名しません。必要な改名は既存のmaintenance機能で別途行います。

未保存編集の切替・再読込・終了には破棄確認があります。非同期処理中、実行Job中、path切替時の
不安全な変更を止め、Catalog再読込で以前のプレビューを無効化します。
小さい画面では編集領域をスクロールできます。1,000行の合成一覧をWindows/DPR 1.5で描画し、
980×700と1400×1000の論理サイズを確認しています。実サイトの確認や権利消費は行っていません。

この作業環境の既存`.venv`にはインストール済みです。直接起動できます。

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.gui --catalog catalog.sqlite --watchlist watchlist.yaml
```

管理DBの保存先を変える場合は`--management path\to\management.sqlite`を追加します。

pipのないuv環境では `uv pip install --python .venv/Scripts/python.exe -e ".[gui,dev]"`
を使えます。起動引数を省略するとルートのcatalog.sqlite/watchlist.yaml/crawler.yamlを
参照します。存在しないCatalogや旧スキーマを自動作成・移行しません。

## 合成データでレビュー

生成ツールだけが、明示指定した**新しいディレクトリ**にサンプルを作成します。
実行のたびに未使用の出力先を指定してください。GUIからは呼び出しません。

```powershell
.\.venv\Scripts\python.exe tools/gui_sample.py --output .tmp/gui-review
.\.venv\Scripts\python.exe -m screenshot_crawler.gui --catalog .tmp/gui-review/sample.sqlite --watchlist .tmp/gui-review/sample-watchlist.yaml --runtime .tmp/gui-review/sample-runtime.yaml
```

同じ作品に4サイト、取得済・外部取得・skipped・未取得、無効key、担当外Source、
未Discover、未管理、Scope未同期を含みます。実在する作品・認証情報・個人情報は
含みません。Artifactのパスは説明用で、対応するZIPは作成しません。

## 操作と値の読み方

- サイト別と作品別を切り替えます。チェックはWatchlist key単位で保持します。
  詳細表示用の行クリックとは独立しています。親チェックは検索で隠れたkeyも含みます。
- 検索・状態フィルタ・列ソート・階層の展開と折りたたみを利用できます。
  右ペインとの境界はドラッグで調整できます。
- サイト、作品、keyを選ぶと詳細が変わり、keyの話数行を選ぶとItemの直近CrawlRunと
  Artifact/保存先を確認できます。保存先の存在確認・ZIPの展開は行いません。
- 「取得済」はcompletedのみです。externalとskippedは別内訳です。
  対象総数は担当内Sourceを持つItem数、担当外はSource数です。
- 「直取候補」「Quota対象残」はCatalogと既存Site Policyによるローカル判定です。
  Quotaの対象話数とサイト共通の残枠は別です。実サイトの現在の取得可否を保証しません。
- `—`は未確認・算定不能、`~`は未同期などの診断がある暫定集計です。
  未Discover・Scope未同期・未管理は正常な0件に置き換えません。
- 完全Inventory証拠の日時とアクセス観測日時は別です。再試行時刻は既存Policyと
  消費記録・設定に根拠がある場合だけ表示します。値は再読込時に更新されます。
- WatchlistのDiscovery無効とSourceの担当外は別概念です。無効keyもチェックできます。

## 選択実行

keyを1つ以上チェックすると下部のDiscover、Batch Run、Grant-onlyが有効になります。
検索・表示モード・フォーカスを変えても選択集合はkey単位で保持されます。
ボタンを押すと詳細確認画面を出さず、選択したkeyでジョブを登録します。
候補数・Quota・スキップ理由の事前計算と表示は行いません。実行結果はモニターとジョブ履歴で確認します。
空選択はサイト全件として扱いません。Watchlist保存後だけは、対象keyと警告を示す
「Full Discoveryを実行しますか？」のYes/No確認を一度表示します。
下部の最大件数は0（無制限）または候補数の上限を指定できます。Grant-onlyのResourceは
選択中のサイトごとに表示されるセレクタで`all`またはサイト対応Resourceを選びます。
key追加や再読込でもサイト別の指定値を保持します。以前のResourceが未対応になった場合は
旧値を表示してジョブ登録を停止し、利用者が対応Resourceを明示的に選び直すまで実行しません。
多数サイトのResource欄は横スクロールできます。

独立したJobとして管理DBへ登録し、専用workerプロセスが既存CLIの共通処理を呼びます。
起動時のInventory再構築、Catalog全体のハッシュ計算、GUI独自の候補計算は省略します。
複数サイトは順番に処理し、workerがCatalog job lock下で選択key・サイト・Resourceと、
Watchlist・runtime・環境設定・接続先・実行オプションのfingerprintを検証します。
待機中に設定が変わった場合は停止します。先行ジョブによるCatalogの更新だけでは停止せず、
最新Catalogを使って共通CLIが候補を計算します。範囲・権利・Quota・採番・保存先衝突の
安全検査は従来どおり実行時に行います。新方式導入前の待機ジョブは従来の厳密な計画検証を続けます。

CLIからは次のようにkeyを繰り返し指定できます。

```powershell
screenshot-crawler batch plan --site mangaone --key series-a --key series-b
screenshot-crawler batch run --site mangaone --key series-a --key series-b
screenshot-crawler batch run --site magapoke --key series-a --grant-only all
```

`--key`を省略した従来の`--site`全件動作は維持されます。

## ジョブキューと履歴（P3）

「ジョブ」を開くと、`output/management/management.sqlite` と
`output/management/logs/<job_id>/` の履歴を表示します。確認済みJobはキューへ入り、
サイトTaskは1つずつ実行されます。候補・skip・失敗・Resource消費状態はworkerの構造化
`events.jsonl`から取り込み、metrics writerが実際に作成したファイルパスとstdout/stderrログも
Task詳細から確認できます。履歴詳細には実行モード・最大件数・サイト別Resourceと、イベントごとの
site/key/item/source、Resource消費のyes/no/unknownも表示されます。候補0件のTaskは`no_candidates`として表示され、取得成功件数0と
サイト接続・消費成功を混同しません。
イベントの末尾が未完成でも次回pollで無視して再読込します。

実行中は「停止要求」で協調停止を依頼します。候補間やサイト境界で停止し、処理中の
Resource消費を強制中断しません。
メイン画面右上の赤い「緊急停止」は、確認なしで実行中workerを強制終了します。
画面をスクロールしてもボタンは上部に残り、実行中だけ有効になります。
待機ジョブの自動開始も止めます。待機ジョブ自体は取消せず、履歴から明示的に開始できます。
共有Chromeは終了しません。停止したジョブの状態は`interrupted`、
消費状態は不明として自動再試行しません。GUI再起動時にqueued Jobは自動実行せず、
前回workerの同一性を確認できない実行中Jobも再接続・再実行しません。
再起動後に残ったqueued Jobは自動開始せず、履歴画面の「選択ジョブを開始」で明示的に開始します。
workerはPIDだけでなくtoken・OS開始identity・heartbeatを記録します。heartbeatが欠落・古い場合は
「要確認」として二重起動を許可せず、実行結果を成功へ補正しません。
緊急停止が失敗した場合は停止未確認と表示し、実行中ならボタンから再試行できます。
子workerの終了を確認できない場合は、新規実行を停止したままにします。
ジョブ画面の「強制終了（非常）」は、従来どおり確認付きの別経路として利用できます。
終了済みJobの「最新状態で再計画」は現在の選択と設定で新しいJobを作成します。
古い候補をそのまま再利用しません。

管理DBはschema v1です。未知のschemaや破損DBを自動移行・上書きしません。
バックアップはアプリとworkerの終了後に管理DBと同じ場所の`logs/`を保存してください。
標準配置では`output/management/`全体を保存します。プログラムからは既存ファイルを
上書きしない`JobStore.backup_to()`も利用できます。

## P2/P3の制約

実行要求の作成は設定を読み取るだけです。実行開始後は既存のCrawler、Chrome/CDP、Catalog job lock、
Site Policyに従ってworkerを動かします。management DBはCatalogとは別に管理されます。
Rename and scheduler remain outside the P2/P3 execution contract. Watchlist編集
and Scope apply are provided by the separate Watchlist management section above.

直近履歴はItemごとの最大Run ID、ArtifactはItem/種別/形式/backendごとの最新記録です。
過去のrunning記録を現在実行中とは判断しません。物理ファイル検証はしません。
異サイト間の同じ内容の話数を自動統合しません。未同期時の派生archive位置は不明です。

WAL形式のCatalogはP1ではエラーにします。SQLiteはread-only接続でも`-shm`を
更新し得るため、完全な非変更を優先しています。運用側で明示的に作成した一貫した
通常journal形式のバックアップを選んでください。GUIはcheckpointやjournal変更を
行いません。通常のCatalogServiceはWAL設定を要求していません。

設計は[GUI_INVENTORY.md](GUI_INVENTORY.md)、P2/P3の測定・テスト・独立レビュー結果は
[P2/P3 PROGRESS](../runbooks/gui-execution-p2-p3/PROGRESS.md)を参照してください。
10万SourceのWindows非同期読込の測定は[性能結果](gui-performance.json)にあります。
初期ロード約3.9秒、表示切替約53ms、検索約32msでした。ロード中には最大約0.58秒の
タイマー遅延があり、大量データの初期処理に短い待ちが生じます。

## レビュー画面

サンプルで生成した画面です。PNGは認証情報を含みません。

- [サイト別](gui-screenshots/site.png)
- [作品別](gui-screenshots/work.png)
- [作品詳細](gui-screenshots/work-detail.png)
- [話数詳細](gui-screenshots/item-detail.png)
- [P2 選択実行](gui-screenshots/p2-execution.png)
- [旧P2 実行前確認（現行の通常起動では省略）](gui-screenshots/p2-confirmation.png)
- [旧P2 Grant-only確認（現行は操作欄に注意表示）](gui-screenshots/p2-grant-confirmation.png)
- [P3 ジョブ履歴](gui-screenshots/p3-jobs.png)
- [P3 中断・要確認](gui-screenshots/p3-interrupted.png)

P2/P3画面のWindowsキャプチャは、認証情報・実サイト接続・worker起動を含まない
合成データ専用ツールで再生成できます。出力先は毎回新しいディレクトリを指定します。

```powershell
.\.venv\Scripts\python.exe tools/gui_execution_screenshots.py --sample-output .tmp/gui-execution-screenshots --screenshots docs/gui-screenshots
```

このツールはInventory、確認ダイアログ、Jobs画面をネイティブWindowsウィジェットとして
保存します。実際のworker実行確認は、別途隔離Catalogを使うテストで行います。

Windows上でGUIを起動し、一覧の列幅、情報量、詳細レイアウト、チェック操作をご確認ください。

## Live execution monitor and job history (Phase 04)

The lower execution monitor and the Jobs history page share the same
`JobStore`, `JobController`, bounded fixed-path `LogTailReader`, and immutable
`JobResultPresenter`. The existing upper path/toolbar/tree/detail/action/error
layout and control meanings remain unchanged. The upper content now lives in
a scrollable viewport, so the user can enlarge the lower monitor without
squeezing the existing form/table minimums. A real vertical splitter drag can
reserve at least 400px for the monitor at 1400x850; resize, polling, and
follow preserve the selected ratio, and collapse/expand restores the prior
expanded size. History list/detail selection and scroll state are independent
from monitor job/stream selection; unchanged rows are not rebuilt, and changed
summary/detail text preserves a manual scroll anchor. Latest-event SQL keeps
terminal context beyond the old first-500 window.

The monitor exposes bounded stdout/stderr logs, omission metadata, structured
Discover/Batch/Grant summaries, and structured problems. Child execution uses
UTF-8 only at the child boundary; parent CLI encoding is unchanged. View
initialization/refresh failures are isolated from queue and safety state
handling, while controller/database failures remain fail-closed.

Phase 04 evidence is synthetic/offscreen plus native Windows captures under
`gui-screenshots/phase4-live-monitor-*.png` and
`gui-screenshots/phase4-live-monitor.actual.json`. Earlier native captures
record the pre-follow-up 980x600 request as actual 980x628; the follow-up
targeted geometry tests validate the scrollable 980x600 viewport behavior.
The report also records actual 1400x850 and history 1150x850 captures, with
worker/browser startup disabled. Root's follow-up native helper records
Windows/DPR 1.5, actual 980x600, a 230px monitor, a 326px upper viewport,
bounded header widths, a collapsed tree, Japanese log text, and no startup
QSplitter warning. Stress fixtures cover 50,000 Events and
50,000 log lines over
5 MiB, timer responsiveness, bounded rendering, manual anchor/follow, history,
rerun, and input-hash preservation. No operational Catalog, Watchlist, Books,
quota, ticket, real site, or CDP access was used.

Reproduce the synthetic captures with:

```powershell
.\.venv\Scripts\python.exe tools/gui_live_monitor_phase4_screenshots.py `
  --sample-output .tmp/glm-phase4-content-inputs `
  --screenshots .tmp/glm-phase4-content-shots
```

# BookWalker quota 自動resume / 590秒停止 Runbook

> **IMPLEMENTED / OWNED READER + SYNTHETIC QUOTA VERIFIED — 2026-11-20**
>
> 通常のBookWalker quota取得に、途中巻の自動resumeとreader滞在時間の制限を追加する。
> 専用resumeコマンド・run-id指定は不要。実サイト検証は購入済み作品だけを使い、
> まる読みの実quotaは消費しない。進捗・証拠・未確認事項は [PROGRESS.md](PROGRESS.md)。
>
> 利用者の実装開始指示に従いP1の位置調査とP2–P4の実装・受け入れ検証を完了した。
> 実quota・実失効・本番590秒実待機とnative全巻E2Eは未検証。
> 回帰テストの既知の設定不一致1件と、証拠・検証上の制限はPROGRESSを参照する。

## 1. Authorityと現行実装との差分

- [AGENTS.md](../../AGENTS.md) のauthority順に従う。本書は上位仕様を上書きしない。
- 主な参照先は [SPEC](../../docs/SPEC.md)、[ARCHITECTURE](../../docs/ARCHITECTURE.md)、
  [DISCOVERY_AND_BATCH](../../docs/DISCOVERY_AND_BATCH.md)、
  [DECISIONS](../../docs/DECISIONS.md)、[TEST_STRATEGY](../../docs/TEST_STRATEGY.md)、
  [CODEX_IMPLEMENTATION_GUIDE](../../docs/CODEX_IMPLEMENTATION_GUIDE.md)、
  [Core note](../../note/00_core.md)、[BookWalker note](../../note/01_bookwalker.md)。
- 共通deadline / metrics / AccessGuardに触れる場合は
  [ACCESS_CONTROL_AND_PACING](../../docs/ACCESS_CONTROL_AND_PACING.md) と
  [その実装計画](../../docs/ACCESS_CONTROL_AND_PACING_PLAN.md) も確認する。
- 開始時はresume未実装で、非空run directoryを拒否し、通常のBookWalker初期化は先頭へ戻していた。
  SPEC §19、ARCHITECTURE §14、DECISIONS D-009の明示resume方針と、
  DISCOVERY_AND_BATCH §10.4のresume非対応を、本書の限定例外へ変更した。
  production変更前に計画として同期し、実装後は該当上位仕様とnoteの本文も更新する。
- BookWalkerの05:00 JST区切りsite-wide capacity=1、entry前のlocal quota記録、
  同windowの自動refund／再試行禁止、source-local grantを仮定しない契約は維持する。
- source-native capture / JPEG・PNG判定の変更は対象外。既存のcapture proofと終端判定を弱めない。

## 2. 採用する利用者向け仕様

### 2.1 通常実行と対象範囲

- 本番の自動resume・590秒制限は、BookWalkerの `access_strategy=quota` にだけ適用する。
  `source.access_mode` と混同しない。通常の `direct` / `auto`、他site、grant-onlyは対象外。
- CLIとGUIの通常Batchから同じ処理を使う。利用者にrun-idの検索・指定を要求しない。
- Watchlist選択・除外・取得無効化・Source availability等の既存条件を適用した後、
  **quota仮割り当て前に、有効な途中巻を新規巻より優先**する。replanでも同じ条件を保持する。
  選択外の途中巻を勝手に追加しない。quota残数は選択範囲だけで再計算しない。
- 上位の実行履歴／ジョブ再試行を、同じ実行内での自動再入場やquota再消費へ変えない。

| 対象巻の状態 | 通常実行の動作 |
|---|---|
| 再開ファイルなし | 新しい取得ディレクトリで先頭から開始 |
| 検証済みの再開ファイル・途中データあり | strict quota entry後、位置を照合して続行 |
| 再開ファイルの破損、別書籍、画像欠落等 | readerを開く前に可能な検証を行い、理由とパスを表示して停止 |
| quota枠なし | readerを開かず、途中データを保持 |
| 終端確認済み・ローカル完了処理だけ未完了 | reader／quotaを使わずZIP化・Catalog完了処理を再試行 |
| Catalog完了記録済み・再開ファイルだけ残存 | 同一取得との対応を照合して残存情報を整理 |

### 2.2 再開ファイルと削除

保存先はCatalogファイルごとの隣接namespaceとする。

```text
catalog.sqlite
catalog.sqlite.resume/
  bookwalker/
    <書籍CID>.json
```

- 再開ファイルは、書籍から継続する取得を探す唯一の入口。
  schema version、Catalogとのbinding、Item/Source/target identity、CID、取得ID、
  manifestの保存先・対応を持つ。IDの再利用や同名Catalog／別Catalogの混同を拒否する。
- manifestは保存済み画像と確定済み表示単位の正本。
  再開ファイルは参照を中心とし、ページ一覧・最終位置を別々の正本として二重管理しない。
  `progress.json` はmanifestから再構築可能な補助情報とする。
- 実行を停止した状態で再開ファイルを削除すると、次回は新規取得する。
  過去CrawlRunやdirectory走査からファイルを自動復活させない。
- 削除しても旧途中画像・実行履歴・quota履歴は消さない。旧出力を上書きせず別directoryを作る。
  completed Itemの再取得指定や当日quotaの復元を兼ねない。
- 通常ログ／GUIに新規・再開・保存済み枚数・再開ファイルの場所・停止理由を表示する。
  再開ファイルのパスや内部IDを利用者が入力する操作は増やさない。

### 2.3 保存単位と再開位置

```text
見開き／単ページを取得
  → その表示に属する全画像の保存
  → manifestの表示単位を確定
  → 再開参照を必要に応じて更新
  → 次へ進む
```

- 見開きはall-or-noneで確定する。画像の保存連番とviewer counterを区別する。
  書籍CID、現在位置／総数、表示単位とpartの順序、必要な表示条件、ファイルSHA-256を記録する。
- 再開時だけ通常の `Home` 巻き戻しを省く。復元された位置を無条件には信用しない。
- 最終保存済み表示に復元された場合は照合後に次へ進む。
  次の未保存表示に復元された場合は、観測済みの遷移契約で連続性を確認してそこから保存する。
  「次」をcounterの単純な `+1`、画像連番、時刻、見た目の類似だけから決めない。
- それ以外の復元位置は、P1で確認した手段と上限内でだけ補正する。
  補正不能、CID／総数不整合、stale描画は停止する。保存時と表示寸法が異なる場合は次の
  source-native見開き照合だけを使う。
  cross-sessionの一時canvas ID一致や小さなsignatureだけを書籍・ページ照合の証明にしない。
- P1の観測に基づく初期対応: 保存済み境界へ最大8回の前後キー操作で合わせ、
  counterだけ先行した状態を避けるためcanvas identity/content versionとsignatureの変化を待つ。
  既に境界にいる場合も一度隣接表示を経て戻し、安定したframe joinを確認してから通常の次操作を行う。
  同じcounterでもcapture分割数・解像度・codecが変わった実測があるため、
  同じ表示寸法での再開は、既存の有界位置復元とframe joinを使う。
  保存済みartifactを再取得結果で置換・mergeせず、各回の既存capture proofを維持する。
- 表示寸法が異なる場合、最後の確定groupはsource-nativeの2枚で、各SHA-256は保存済み
  manifest内で一意であることを要求する。新しい寸法を位置復元と照合中に固定し、境界を
  描き直してから既存capture hookで見開きを取得する。両方のSHA-256が読み順で一致するか、
  各partの寸法・復号後のRGBAが読み順で完全一致し、同じframeに留まる場合だけ次の送りを許可する。
  復号比較では保存ファイルのSHA-256をmanifestと再照合し、各画像を最大16 MiB・800万画素の
  単一フレームJPEG／PNG／WebPに限る。色プロファイルや回転の扱いが明確でない画像、
  高精度PNG、復号後に同一の2枚も拒否する。
  2枚の一致後に同一CID・総数・位置・寸法でcanvas置換またはcontent version増加を確認した場合は、
  照合結果を破棄し、隣の表示を経由して一度だけ境界を描き直し、2枚とも再取得して照合する。
  往復は従来の最大8操作に含み、初回照合時に開始したpage-change timeoutを共有する。
  位置・寸法の変化、描画更新の証拠不足、2回目の変動、または左右の不一致は停止する。
  最初の送りと入力再試行の直前も照合したframeを再確認する。次が本文なら同じ本・総数・新しい
  寸法のままcounterが前進したことを確認する。照合結果は追記に使わず、保存済み
  groupは保持する。単ページ、rendered fallback、片側差分、順序逆転、重複hashでは停止する。
  照合には既存のpage-change timeoutと全体の590秒制限が適用される。
- manifestへの確定後・再開参照更新前の中断は、取得IDとmanifestの対応を検証して回復する。
  manifest未登録画像は自動採用しない。必要なら未確定取得として扱い、既存画像を無条件に消さない。
- 累計保存数への `max_pages`、same-content guard、既存のcapture proofを維持する。
  証拠不足の旧途中出力を自動移行しない。初期対象は新形式で記録した取得とする。

### 2.4 590秒制限と例外時の取り直し

- 計時開始は **strictなまる読みボタンを押す直前**。monotonic clockを使う。
  reader遷移、login redirect、読み込み、位置照合／補正も含み、同一attempt内でリセットしない。
- **590秒を、取得を終了して専用readerタブを閉じる時刻の目安**とする。
  580秒での停止準備など、二段階の時間制限は追加しない。
- checkpointは毎表示の保存時に確定済みである。期限到達時は新規capture／advanceを止め、
  確定済み情報を保全して専用タブを速やかに閉じる。終了のために新しい見開きを取りに行かない。
  処理中の表示が安全に確定できる場合の扱いはP3で有界に実装する。
- 通常の終了処理は残り約10秒で終わる想定。正確な600秒内終了やサーバー残時間は保証しない。
  複雑な残秒推定や、例外をすべて救済する汎用復旧機構は作らない。
- 例外的に整合性・終了位置を保証できなければ、その取得を継続不能として明示的に無効化し、
  **次の通常実行では新しい取得として先頭から取り直す**。同じ実行内では再入場しない。
  旧manifestに無効化理由を残し、再開参照を安全に解除する。旧出力・履歴・quotaは保持する。
- 上の自動無効化は、実行中に把握した継続不能な取得の処置。
  読み込み時に見つかった任意の破損JSONや不明な出力を「情報なし」として黙って取り直さない。
  どの障害を無効化／保存継続／停止にするかはP2/P3の分類表とテストで固定する。
- 別端末や同日中の先行利用で590秒より前に切れる場合もある。
  同windowのquota自動refundをせず、整合性が証明できるcheckpointのみ継続候補にする。
- 予防停止は `quota_time_budget` 等の明示的な理由を残す。正常ENDに偽装せず、
  Itemをcompletedにせず、途中ZIPを完成品として公開しない。

### 2.5 タブを閉じた後の完了処理

- 書籍全体の取得の連続性と既存の正常終端判定を確認し、終端確認済みであることを永続化する。
  復元位置からENDが見えただけでは完成にしない。
- **readerタブを閉じてからZIP化・Catalog更新を行う。これらは590秒に含めない。**
- 利用者向けの「ZIP化待ち」Item statusは追加しない。
  manifestの内部段階として終端確認済み／完了処理済みの対応を保持する。
- ZIP成功後のCatalog更新失敗、Catalog成功後の再開ファイル削除失敗も考慮し、
  自分の取得が作ったarchiveのhash・対応を検証して再試行する。無関係な同名ZIPを上書きしない。
- 完了記録後に再開参照を解除する。cleanupは既存の安全規則と整合させ、無関係ファイルを削除しない。

## 3. 責務・保存・排他

- BookWalker integration / Site Policy側: 対象判定、再開参照の解決、途中巻の優先、quota契約。
- BookWalker Adapter側: strict entry、計時開始のsite固有地点、巻き戻し省略、位置照合・補正。
- Core / ProgressStore側: site-neutralな検証済み既存manifestの読み込み・追記と、
  必要最小限の期限中断。CoreへBookWalker名・selector・quota ruleを持ち込まない。
- Batch側: 各attemptで新規CrawlRunを作り、取得IDと関連付ける。失敗履歴を成功へ書き換えない。
  終端確認済みのローカル完了処理はquota eligibilityとは別に判断できるようにする。
- schema追加・汎用resume frameworkは先に決め打ちせず、最小の表現を選ぶ。
  必要になればmigration・依存テスト・上位仕様を同じ変更で扱う。
- 既存Catalog job lockとWork削除gateの下で参照を再検証する。
  previewはread-only、executeはreader／quota接触前にbinding・出力・対象条件を再確認する。
  安全な相対パス／正規化済み管理root・symlink等を検証し、再開JSONで任意の場所へ書き込ませない。
- 共通Chrome/profileへCDPで接続し、通常操作はPlaywright Page/Locator。
  operatorとwriterは各1人。既存タブやremote Chromeを閉じない。
  本件は新規Adapterやsource-native研究ではなく、専用multi-agent編成を前提にしない。

## 4. 実サイト検証契約：購入済み作品だけを使用

購入済みreaderで、通常の予防停止・再入場・再開と同じ処理を検証する。
サーバーの10分切れを意図的に発生させることは受け入れ条件にしない。

| 検証対象 | 方法と証拠の限界 |
|---|---|
| 復元位置・前後移動・描画安定 | 現在のlive状態で購入済みと確認した商品からstrict direct entry |
| 保存→終了→再開→完成 | 本番と同じ保存・再開・中断部品に検証用条件を注入し、owned readerで有界に実行 |
| 計時とreader close、close後のZIP化 | 短縮タイマーで実機確認、fake clockで本番590秒値と順序を検証 |
| quota専用の適用条件・local quota記録・優先順 | synthetic Unit / browser-backed Integrationで検証 |
| 実まる読みcontrol click後のviewer固有差・実残時間・実際の失効 | この計画では実quotaを使わず、未検証として最終報告 |

- Catalogの過去のowned分類だけでは権利の証明にしない。
  liveで購入済み入口が一意に確認できなければ停止し、trial／まる読み／読み放題へfallbackしない。
- ownedをquotaに書き換えたり、本番strict entryを緩めたりして代用しない。
  通常のowned/directにresume・タイマーを有効化する公開CLI／GUIは追加しない。
  test-only driverから同じproduction部品へ条件・短縮時間を注入し、driverの役割を証拠に残す。
- 専用のCatalog・Watchlist・出力を用い、本番Catalog・ZIPは更新しない。
  既存実データの読取りが必要でもread-onlyにし、隔離資源が無ければ本番へfallbackしない。
- probeごとにactual CID/counter・総数・表示条件・開始／終了位置を記録する。
  dedicated Pageだけを操作し、元の読書位置を記録して可能な範囲で復元する。
  歴史的に同じ巻で成功したことを、今回の位置復元成功の証拠にしない。
- fixtureへ著作物を保存しない。調査画像が必要なら隔離出力だけに置き、
  durableな記録は数値・hash・sanitized metadata中心とする。認証・署名付きURLは記録しない。
- 最終結果は「購入済みreaderでのresume検証」と「quotaのsynthetic契約検証」を区別する。
  実quotaのlive E2E成功と表現しない。未検証範囲を記録するだけのためにquotaテストを追加しない。

## 5. Phaseとexit条件

段階ごとの目的、既知事実／未知、変更範囲、テスト、結果をPROGRESSへ記録する。
P1で位置移動の根拠が揃う前に、推測でP3のproduction挙動を実装しない。

| Phase | 目的・変更範囲 | 必須の検証／exit条件 |
|---|---|---|
| P0 計画・契約 | 本書、進捗、対応noteへの未実装リンク。上位仕様との差分を明示 | 利用者合意の反映、購入済み限定の検証範囲、P1の有界probe契約を確定。上位仕様の同期先を列挙 |
| P1 購入済み位置調査 | 隔離probeのみ。初期復元、保存直後／advance後のclose、再入場、前後移動、見開きと描画遷移 | CID/counter/安定frameの前後証拠。最後の保存済み／次の未保存／他位置の識別と補正の上限を確定。タブcleanupと読書位置復元を記録 |
| P2 永続化 | 上位仕様の計画同期後、再開参照・manifest・検証・attempt関連付けを実装 | 見開き途中・参照更新途中の中断、参照削除、破損／別Catalog／危険path、継続不能の無効化、max_pages累計をUnitで検証 |
| P3 再開・590秒 | 調査済みの位置照合と有界補正、再開時のHome省略、期限と専用Page close | 復元位置各case、stale描画、計時開始・非reset、停止中断とcloseをUnit＋local viewer Integrationで確認。ownedの短縮timer実機検証 |
| P4 通常Batch/GUI・完成 | 優先順・read-only plan／execute再検証・表示・終端→close→ZIP→Catalog→cleanup | quota割当より前の優先、selection/replan、direct/auto/他site回帰、ローカル完了再試行、ownedの中断→再開→ZIP E2E。docs/note同期と検証範囲の最終記録 |

- P1開始時にprobe対象・上限・終了／復元条件をPROGRESSへ具体化する。
  1つの代表購入済み作品から始め、別の表示形式が必要な場合だけ対象を増やす。
- P4のreaderを使うE2Eも購入済みのみ。quota候補選択と権利取得はsyntheticで別途検証する。
- production変更後は差分と根拠をレビューし、blockingな問題を解消して次へ進む。
  独立レビューを実施した場合だけその旨を記録し、実施していないレビューをPASSとしない。

## 6. テスト選択・最終報告

- docs/TEST_STRATEGY.mdに従い、既存testの拡張・parameterizeを優先する。
- targeted → affected（Core / Progress / BookWalker / Batch / Packaging / CLI/GUI境界）
  → 必要なbrowser-backed Integration → shared/cross-site変更のfull suite → owned live検証。
  Core/data modelを広く変更する場合はfull suiteを実行する。各小変更での反復は不要。
- 590秒を毎回実待機せず、fake monotonic clock・短い注入deadlineを使う。
  外部サイトへのCI依存は追加しない。Research helper変更時はそのhelperの検証も選ぶ。
- `ruff check src tests`、`git diff --check`を実施可能な範囲で行う。
- Phase終了時は変更ファイル、上位仕様／note更新、設計判断、テスト結果、skip件数と理由、
  未実行のIntegration / Research / Live / full suiteと理由、残課題を記録する。
- 実装完了後はCore noteとBookWalker noteの本文を現行動作へ更新する。
  計画リンクの追加だけで実装後のnote同期を済ませない。

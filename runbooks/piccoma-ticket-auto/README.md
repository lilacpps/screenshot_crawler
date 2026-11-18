# ピッコマ 3種チケット自動消費 — 実装 Runbook

**Status: Stage 02 live implementation and 2026-11-18 default/grant revision are historical. The 2026-11-19 Work/Binge grant-only revision is implemented and synthetic-verified; independent final review is pending. No new live site, CDP, or ticket action was used in this revision.**
**対象:** 既存 `screenshot_crawler` の Piccoma Adapter に、`待てば¥0` / `¥0+券` / `爆読み¥0券` の利用可能な範囲での自動解放を追加する。
**進捗:** [PROGRESS.md](PROGRESS.md) に観測・消費・テスト・未確認事項を記録する。
**現在:** 通常BatchはPiccoma専用flagなしで3券種を利用する。Grant-onlyは `work_ticket`（待てば¥0 / ¥0+）の後に `binge_ticket`（爆読み）を明示的に試し、`all` はこの2 passを順番に再計画する。資源ごとの券種から暗黙fallbackしない。Grant-onlyは複数話を解放でき、Capture / packaging / Item completionは行わない。旧 `piccoma_ticket_grant` は未対応として拒否する。旧CLI flag、GUI checkbox、追加 opt-in prompt はない。worker queueはv2 internal consent bitで古いPiccoma requestの黙った権限拡張を拒否する。今回のrevisionは実サイト接続・追加ticket消費なし。Stage 02の4回のlive proofと以前の9473件full suiteは履歴であり、今回の検証数と混同しない。詳細は [PROGRESS.md](PROGRESS.md) を参照。
**実装ブランチ:** 実装着手時の最新 `main` から専用 feature branch を作る。履歴のある旧 `feat/piccoma-adapter` / `research/piccoma-performance-20261010` を起点にせず、未コミット変更を破棄しない。`main` への自動マージはしない。

## 0. Authority と現行実装（確認済み）

`AGENTS.md` の authority order を最優先とし、`docs/SPEC.md`、`docs/ARCHITECTURE.md`、`docs/DISCOVERY_AND_BATCH.md`、`docs/ACCESS_CONTROL_AND_PACING.md`、`docs/TEST_STRATEGY.md`、`docs/CODEX_IMPLEMENTATION_GUIDE.md`、`note/09_piccoma.md` と現行テストを読む。無料・手動解放の既存履歴は `runbooks/piccoma-free/README.md`、実行方式の参考は `runbooks/hanayume-work-ticket/README.md` / `runbooks/younganimal-work-ticket/README.md`。上位仕様と衝突した場合は黙って変更せず、差分と採用判断を記録する。

**Stage 01開始前の基準状態:**
- `site_adapters/piccoma/discovery.py` は、単独の `waitfree`、`waitfree+zeroPlus`、`waitfree+bingefree` バッジを `access_mode=quota` として識別。無条件 `¥0` は `free`、ポイント価格の確証がある話は `paid`。チケット種別・所持枚数は Catalog に格納していない。
- 解放済み話は `waitfreeRead` と `閲覧期限 残りN時間` の保守的な期限を記録。`PiccomaSitePolicy` は `free` と有効な手動解放だけ `direct` 許可。quota は `pending_quota` 表示のみ。
- `PiccomaAdapter.initialize()` は対象の `/web/product/{product}/episodes` 一覧を再確認し、free/active grant なら canonical viewer に移る。現在は `auto/direct` のみ。未解放話を解放する操作はない。
- 共通 `BatchExecutor` は `after_observed_consumption`、`AccessConsumption`、失敗時の消費記録に対応する。一方 `BatchCandidate.quota_resource` は単一リソース名、`_record_observed_resource_consumption` は candidate と adapter の resource 一致を要求する。`BatchPlanner` と CLI の resource pass は候補を再配置しうるので、「複数 pass を足すだけ」は目的の順序を保証しない。

以上は設計の出発点であり、実装時に HEAD で再確認すること。**この Runbook の追加自体は機能の実装・チケット消費を意味しない。**

## 1. 目的・要求・受け入れ境界

Piccomaの通常 Batch は既存の **crawl候補順** を保ち、各話を順番に処理する。無条件無料/既に解放済みは券を消費せず取得。未解放のチケット対象話では、ログイン中の実サイトで利用可能な3種のいずれかを確認して、通常UIで対象1話の権利だけを1回取得し、正のgrant確認後は既存 Capture → END → ZIP へ進む。使えなければ pending のまま次の候補へ進む。通常Batchは既定でこの動作を行う。

Grant-onlyは `work_ticket`（待てば¥0 / ¥0+）と `binge_ticket`（爆読み）を別々のlogical resourceとして使う。`--grant-only all` は Work pass の後に再計画して Binge pass を行う。各passで指定された券種だけを使い、残数・対象・選択・既存 `--limit` の範囲で複数話を逐次解放する。券種間の暗黙fallbackはしない。各話のgrant確認後に次候補へ進み、Capture / packaging / Item completionを行わない。`piccoma_ticket_grant` は未対応として拒否する。

| 項目 | MVP契約 |
| --- | --- |
| 対象 | 既存 Watchlist / Discovery / Catalog が管理する piccoma の対象話。別作品/別話の自動探索、対象外話の追加は禁止 |
| 順序 | 通常 Batch の同一選択範囲における候補順を維持。無料/既解放/券を混ぜても resource ごとに並べ替えない |
| 資源 | 待てば¥0（作品ごと）、¥0+券（アカウント共通）、爆読み¥0券（アカウント共通＋作品ごとの週制限） |
| 消費 | 画面の正の証拠で対象話・使用する券種・課金0・残数/適格性・操作箇所を束縛。クリック前の read-only 検証後、当該試行は高々1操作 |
| 消費後 | 対象話の解放と同じ ID の viewer entry を確認し、できる限り同じ Page から Capture。既存 Piccoma source-native / lossless WebP / PNG fallback / END / ZIP 契約を変更しない |
| 実行許可 | 通常Batchは3券種を利用可能なとき自動使用。GUIにPiccoma専用checkboxや追加opt-in確認はない。Grant-onlyは専用resourceでwaitfree/¥0+だけを使用 |
| スキップ | 利用不可/不明/paid/課金操作/別の券種へ誘導/ログイン・challenge は安全に拒否。未消費と確認できた不適格は pending で次候補へ。消費不明の試行は自動再クリックしない |
| 有効期間 | 読める期限と券の次回回復・配布・週上限は**別物**。期限は実サイトで正に観測した値を保守的に記録。機械的な72時間加算だけで direct を許可しない |
| 実装範囲外 | 有料ポイント/コイン/決済、ギフト券、時短アイテム、動画・広告視聴による解放、アクセス制御/DRM回避、CAPTCHA対処、並列チケット消費。Grant-onlyでの爆読み利用 |

### 公式仕様として参照するが、実装判定の authority は live state

- 待てば¥0: 「チャージ完了」で1話、通常23時間で回復。キャンペーンで変動する（https://piccoma.com/web/faq_detail/115）。
- ¥0+券: 対象アイコンの話に利用。アカウント共通、定期配布は偶数時刻に1枚、定期配布分の保有上限6枚。イベント配布分は別扱い（https://piccoma.com/web/faq_detail/195）。
- 爆読み¥0券: 対象アイコンの話に利用、毎週月曜0時頃に100枚回復、1作品あたり週30枚まで。待てば¥0チャージが先に使われる（https://piccoma.com/web/faq_detail/197、https://jp.piccoma.com/web/event_detail/22429）。
- 取得後の閲覧期限は原則72時間だが、キャンペーン終了等で途中から有料へ戻る例がある（https://piccoma.com/web/faq_detail/80）。**キャッシュした72時間だけでアクセス保証しない。**
- これらの定数を残数・可否の authority にしない。サイトが自動的に券種を決める場合、観測で実際の券種と追加消費がないことを確認できなければ操作しない。券の消費優先順位は仮定で上書きしない。

## 2. 設計選択（Stage 01の証拠で確定した履歴）

**推奨: 1話ごとの site-owned 自動リソース選択。** 標準 `batch run` の候補列を保ったまま、当該話の一覧・入場UIから実際の残数、対象アイコン、作品制限を読み、候補になる券種を確定して1回解放し、同じ話を取得する。作品Aの全話を完了させてから作品Bに行くような独自のグルーピングはしない（順序は既存のプランに従う）。一括の全作品先読みは行わない。

**先に調べる重要な互換性問題:**
1. `PiccomaSitePolicy` を opt-in でのみ quota eligible にできるか。選定時点で具体券種が未確定でも計画できるか。`access_mode=quota` を3種に対応させるが `unknown` / `paid` を quota に昇格させない。
2. 現在の Planner は `quota_scope="work"` の候補を direct の後ろに配置し、quota候補のソートもする。**quotaを後回しにしないこと**が必須。プラン生成/実行を混ぜたときの同一ID・同一順序をまずテストで示し、不足する場合に site-neutral な最小拡張だけ加える。`quota_limit=1` を安易に指定すると、同作品で ¥0+券/爆読み券を複数消費する要求を満たせないので禁止。
3. 共有 `AccessConsumption.resource` は単一名で candidate と一致する必要がある。実装案は `piccoma_ticket_auto` を **論理的な1リソース** として計画・消費報告し、実際に使った券種（`waitfree` / `zero_plus` / `binge_free`）は site-owned の安全な per-attempt 記録に分ける。正の消費証拠があるときだけ既存 `after_observed_consumption` で Source の grant/消費時刻を記録する。失敗時にも券種と消費有無が判別できるよう、必要なら最小の site-neutral optional metadata 拡張を検討する。既存 Catalog schema を先に変更しない。
4. 共通設計の **「resource attempt 中に別resourceへ暗黙 fallback しない」** に従う。使用券種はクリック前に確定し、試行開始後に他券を押し直さない。最初のread-only検証でどれも利用できない場合だけ pending skip。券種の明示選択が実UIに存在しない場合は native priority を尊重し、無断の複数消費や別資源への自動切替をしない。
5. 既存 `PiccomaAdapter` は一覧ページを preflight に使うため、他サイトの「話URLへ直行」パターンをコピーしない。対象行を厳密に同定し、必要な場合はその場の正規UIで付与→同一Pageの正規 viewer に遷移。`/web/viewer/s/` の既存許可条件とリダイレクト identity gate を維持。
6. GUI と CLI の同一セマンティクス: ON時は確認画面に **実際に無料券を消費し得る**ことを表示。CLIの新フラグ（例 `--piccoma-auto-tickets`）は piccoma の通常 `batch run` のみに有効。無効な site・`batch plan`・`--grant-only` への誤適用を拒否し、GUIの execution_worker にも opt-in を明示的に伝播させる。既定OFF、ほかのサイトに副作用なし。

**判断ゲート:** Stage 01 終了時にこの方式が実装できるかを証拠つきで `PROGRESS.md` に記録。画面/通信から実際の券種が確定できない、共通候補順を守れない等の阻害要因があれば、危険なフォールバックで埋めず、最小代替案とトレードオフを提示してStage 02を止める。

## 3. Stage 01 — Repo確認・実サイトの非消費 Probe

**目的:** 3種の消費UI・残数/作品上限・実際の優先順位・解放確認方法を、観測証拠に基づいて確定する。**Stage 01のデフォルトはread-only。Runbook作成の依頼は実チケット消費の許可ではない。** 実際の券消費を伴うlive検証は、対象話・券種・最大枚数について別途ユーザーが明示許可した場合だけ行う。

1. 現行 HEAD、`AGENTS.md`、当該Policy/Adapter/Discovery/CLI/GUI/Worker/Tests を比較。既存の direct/manual-grant と Catalog の選定順を fixture で再現し、基準テストを記録する。
2. 既存共有CDPのログイン済みブラウザを単独使用。既存 Watchlist/Catalog の対象から、3種のバッジと未解放/解放済み/有料/UNKNOWNを代表する最小の話を選ぶ。作品ID+話ID・URL・一覧行のscopeを一致させ、**実際の消費を誘発しない一覧/案内画面だけ** read-only観測。
3. 各券について: 現在数の表示源、チャージ・配布・週上限の表示、どの話に使えるか、ログイン確認、表示の安定性、native actionの確認ダイアログ、券種が明示されるタイミング、課金ボタン/別券/広告との違いを調査する。ブラウザが通常生成した通信を passive に確認するのは可。生Cookie/トークン/署名付きURLは保存しない。
4. 「待てば¥0→¥0+→爆読み」といった固定優先を実装せず、UIがユーザーに選択を提供するか、サイトが消費順を決めるかを確認する。複数券アイコン・共通¥0+残数・爆読み同作品週上限・途中で券切れ・途中補充・手動解放済み話を重点観測する。
5. **別途許可が出た場合のみ**、まず代表の1話・1枚まで安全ゲートを確定したうえで、対象コントロールを最大1回操作し、使用した券種、対象話grant、閲覧期限、URL一致、初頁readyを確認する。追加消費は新たな許可が必要。クリックtimeout/通信断直後に二度押ししない。
6. 画面だけでは消費種別が特定できない、1クリックで未知の複数資源を消費する、実サイトが認証・年齢確認・CAPTCHA・課金へ誘導する等の場合は消費しない。UNKNOWN の内容と必要な次の観測だけを記録する。

**成果物:** `PROGRESS.md` の Stage 01 セクションに、確定/未確定の区別、実際の DOM・非秘密のAPIフィールド/ID照合、selector候補、優先順位、券残数のauthority、クリックの必要条件、消費結果の正の証拠、実消費枚数（無許可なら0）を記録。

**Gate S1:** 3種ごとに「適格判定・確定券種・1回操作・成功判定・不明時停止」を説明でき、Planner順序問題の対応方針が確定。独立Reviewerに安全性と変更範囲を確認してもらう。必要な実サイト証拠がなければStage 02 の当該券種を無効のまま保持し、「実装済み」と報告しない。

## 4. Stage 02 — 初回の opt-in 実装・ライブ証拠（履歴）

**実装状況:** Gate S1の証拠に基づく3券種を実装し、各券種のpositive live post-stateを確認済み。共有変更はPlanner順序保持、Executor attempt persistence、CLI/GUI/Worker opt-in transportに限定し、B1/B2/B3と互換性レビューはBLOCKING 0。全201 test filesは9453 passed / 0 failed / 0 skipped in the 201-file full suite; 3 later sequential synthetic cases also passed (9456 distinct validations; no full rerun)。Final Stage 02 Reviewer Gate: PASS / BLOCKING 0.

この節のdefault-OFF opt-in、`--piccoma-auto-tickets`、GUI checkbox、およびGrant-only非対応は当初のStage 02を記録した履歴であり、現行契約ではない。現行契約は次の節を参照する。

**変更候補:**
- `src/screenshot_crawler/site_adapters/piccoma/discovery.py`: 既知のrow-scopedバッジ分類は保持。必要なら read-only の種別判定を新設。Catalog の既存 `quota` 表現を維持し、別resource を持つためだけにDB migrationを増やさない。
- `src/screenshot_crawler/site_policies/piccoma.py`: opt-in 時のみ明確な quota 話を consuming candidate とする。`quota_resource=piccoma_ticket_auto`、`quota_commit_mode=after_observed_consumption` を使用。`free`/有効manual grantは引き続き `direct`。既定OFF。
- `src/screenshot_crawler/site_adapters/piccoma/adapter.py`（必要なら小さな `live_access.py`）: opt-in quota のみ、対象一覧rowと券種・残数を再確認して**クリック前に明示選択**。1回の正規UI操作、消費結果の正の観測、同じ対象話のviewer開通確認。`get_access_consumption()` を正の確認後だけ返し、Viewerの既存readiness/native captureへ合流。状態リセット/取消/失敗時の証拠も保持。
- `src/screenshot_crawler/batch/planner.py` / `src/screenshot_crawler/cli.py`: 現行の混在候補順維持ができない場合だけ site-neutral な候補順/当該1話の live resource 選択を実現する最小変更を行う。**resource別3-passの実装はしない**。同作品の2話目以降も余剰券で続行可能にする。
- `src/screenshot_crawler/gui/` / `src/screenshot_crawler/execution_worker.py`: サイト Piccoma の通常 Batch に限り既定OFFのチェックと消費注意を用意。フラグを実際の実行まで伝播。CLIにも同等の明示opt-in。対象外サイトに見せない。
- `note/09_piccoma.md`、`src/screenshot_crawler/site_adapters/piccoma/README.md`: 実装後の現行仕様・制限・検証状況へ同期。共通契約を変更した場合だけ `note/00_core.md` 等も同期。`runbooks/piccoma-free/` の歴史的検証内容を上書きしない。

**実行アルゴリズム（概念）:**
1. 既存 plan の順番に `Item pending` の対象を取る。非消費 direct は従来通り。opt-in でない quota は候補に入れない。
2. opt-in quota は対象作品・話の一覧rowを fresh に確認。paid/unknown/他資源・残数不明なら操作しない。サイトで実際に許される券種を特定し、対象話に限定した1回操作を実行する。
3. 消費の正の証拠を一度得たら `AccessConsumption` を確定し、後続Captureが失敗しても消費と話単位 grant を保存する。券種（3種のどれか）と消費確認/不明を安全なper-attempt診断に残す。実行中の残数は都度live再確認し、ローカル時刻計算だけで消費許可しない。
4. 解放された対象viewerの identity/readiness を再確認し、従来 Capture→END→ZIP を実行。成功時だけ `completed`。消費前スキップなら `pending`、消費後失敗なら `pending` + 消費記録。
5. 既に消費された可能性がある試行は、自動で別券や同じ券を再実行しない。手動確認や後のDiscoveryで当該話の正規grantを確認できたときに `direct` を選ぶ。
6. 通常のアクセス安全停止（403/429/challenge/CAPTCHA、リダイレクト、ページ不明、時間切れ）を維持。サイトを横断した券の使い回しや自動再試行はしない。

### 最低限必要なテスト

| ケース | 合格条件 |
| --- | --- |
| 既定OFF / 別サイト / GUI・CLI | 従来の無料・手動解放directのみ。クリック0、既存のBatch plan/GUI統計が回帰しない。ONが実実行へ届く |
| 無条件無料・期限内grant | 追加券消費0、既存のCapture/END/ZIP、期限切れ後はfresh検査 |
| 待てば¥0 | 作品Aで消費後、Aの次話ではチャージ中なら別の利用可能な券を確認。作品Bのチャージは独立 |
| ¥0+券 | 別作品をまたぐ共通残数、0枚/1枚/複数枚、実行途中の配布・0枚化、対象外話 |
| 爆読み¥0券 | 共通残数、作品別週30枚上限、週境界、対象アイコン、待てば¥0との自然優先関係 |
| 混在した順序 | free/grant/3券種が混じる複数作品・複数話の plan と実実行の候補順が一致。quotaだけを後ろに動かさない。`--limit` / selected_keys / rerun も検証 |
| 一意性・有料遮断 | ID不一致、別作品/別話、二重ボタン、DOM変化、paid/ギフト/広告/時短、UNKNOWNは消費0 |
| 消費結果 | 1クリックにつき正の証拠があれば記録1回。成功/失敗/timeout/中断/応答不明時に二重消費なし。消費後Capture失敗でも source grant/時刻/種別を追跡できる |
| 回帰 | 既存Piccoma Discovery full/incremental、manual unlock保守的期限、viewer/s、native WebP/PNG fallback、END、manifest/ZIP、Catalog Item状態、AccessGuard |

テストは **合成 HTML / Playwright browser fixture + 隔離Catalog** を基本とする。外部サイトに依存する恒常的CIは追加しない。実サイトの著作物や秘密をfixtureに入れない。`tests/unit/test_piccoma_*`、`tests/integration/test_piccoma_*` と Batch/CLI/GUI/Worker の影響範囲を拡張し、`docs/TEST_STRATEGY.md` に従い targeted → affected → browser-backed → 必要なら full suite。共有Planner/Executor等を変えた場合は影響を受ける他サイトのBatchテストも必須。`ruff check src tests` を実行する。

**Gate S2:** 3券種のfixture、live positive proof、default-off direct recovery、全201 test filesの回帰確認は完了。Final Gate S2: PASS / BLOCKING 0. Stage 02 is complete.既知の未確認事項（binge account-wide残数delta、normal packaging後のmanifest/source-native provenance、枯渇・週境界等のlive境界）は成功と見なさず `PROGRESS.md` に記録する。消費枚数・消費後grant・ZIP/manifest・Catalog状態は観測できた範囲だけ報告する。

## 5. 現行 default Batch / Grant-only 契約（post-Stage 02 revision）

- 通常 `batch run` はavailableなPiccoma quota話でsite-nativeに利用可能なwaitfree / ¥0+ / binge-freeを使う。専用CLI flag、GUI checkbox、追加opt-in promptはない。候補順序を保ち、各候補のfresh UI stateで種類を選ぶ。
- Grant-only は `work_ticket`（waitfree / ¥0+）と `binge_ticket`（binge-free）を順番に選択できる。`all` は Work の後に Catalog を再計画して Binge を試す。Binge pass では waitfree / ¥0+ に切り替えず、未知状態なら後続passを停止する。Stock、選択対象、既存 `--limit` を尊重し、Workごとの1話上限を追加しない。旧 `piccoma_ticket_grant` は受け付けない。
- Grant-onlyはtarget grant確認とdurable Catalog/metrics記録で終了する。Capture、package/ZIP、Artifact作成、Item completionは行わず、Itemはpendingのままにする。
- Plan後にfree/active grantへ変わったGrant-only候補は、追加ticket操作とviewer entryなしでno-action skipする。fresh grantはskip前にpersistする。
- GUI queueでは通常Piccoma Batchと Grant-only の `all` / `binge_ticket` にinternal signed consent bitを含む`inputs-v2`を使う。明示的な `work_ticket` は従来どおり `inputs-v1` / falseでよい。旧Piccoma `all` requestや未対応aliasは実行前に拒否し、保存済みjobがupgrade後にbinge券を黙って使うことを防ぐ。mixed-site runではbitをPiccoma namespaceだけに適用し、grant-only子CLIにはquota accessを渡さない。
- 通常multi-site Batchの `--limit` は全site合計のcrawl slot上限であり、`--grant-only` はselected grant attemptの上限である。Workerは`candidate_started`を使って残数を保守的にsite間へ渡す。deferred siteでは準備grantとcaptureの各phaseがcandidate startを出すため、通常Batchはslot上限を超えない一方、上限まで候補を埋めないことがある。候補開始前のlocal skip/empty planは枠を使わず、開始後のno-action/unavailableもcandidate start済みなら枠を使う。failureは後続siteを開始しない。
- Same-Source unresolved quota history guard、candidate-bound attempt/grant observer、native row/modal/control/debit proof、AccessGuard、normal Batch Capture → END → ZIP は維持する。未確認/ambiguous状態はfail-closed。今回のrevisionでは追加ticket/CDP/live actionは行わない。

このrevisionの合成browser sequence、targeted/affected results、全repository suiteの最新結果とレビューは `PROGRESS.md` に更新する。Stage 02の旧4 ticket uses、direct-recovery E2E、9456 historical validationは新revisionの証拠に加算しない。

## 6. 実装時の停止条件と報告形式

- **停止:** 身元/対象話/券種/課金0/一意な操作/消費結果を正に証明できないとき、あるいはサイトが別券・課金・ログイン・CAPTCHAへ誘導するとき。UNKNOWNを「残数なし」「無料」と解釈しない。
- **リソース消費上限:** 実サイト操作は別途許可された対象話と枚数のみ。無許可なら0枚。自動テストのため実券を消費しない。実際に使った券種/件数を試行ごとに記録。
- **プライバシー:** Cookie、認証ヘッダー、token、署名付きURL、作品画像をレポジトリにコミットしない。ローカル diagnostics でも認証情報は redact する。
- **完了報告:** 変更ファイル、当初想定との設計差分、確認済み券種/未確認券種、消費実績、順序検証結果、テスト結果と未実施項目、既知の制限、独立ReviewerのBLOCKING数を明示。機能未実装/未検証を PASS と言い換えない。

**Codexへの実行単位:** 現在のdefault Batch / Grant-only契約に対する変更は、上位authority・この節・`PROGRESS.md` の最新phaseを確認し、Stage 02のhistorical opt-in契約を現行仕様として再導入しない。

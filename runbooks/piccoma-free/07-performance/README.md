# Phase 07: PiccomaのJSON転送と待機200ms

作成日: 2026-10-10 JST。Stage A/Bは独立Reviewer PASS。Stage Cのinterleaved manual性能比較、source-native出力一致、YAML200ms BatchのEND/ZIP/Catalog、fresh Batch Manifest監査はPASS。Final Stage C Reviewer PASS / BLOCKING 0。既存DPR微小差許容は維持する。数値と境界は[Stage C profile](../../../research/piccoma-performance/PHASE07_PROFILE.md)、[Tester report](../../../research/piccoma-performance/PHASE07_TESTER.md)、[numeric measurements](../../../research/piccoma-performance/PHASE07_MEASUREMENTS.json)を参照。

計画文書gate: Explorer Lunaが現行6snapshotと既存設定伝播をread-only確認し、Reviewer Solが計画を独立確認して **PASS / BLOCKING 0**。Stage A/Bの実装差分も独立Reviewer **PASS / BLOCKING 0**。Stage Aでは `crawler.yaml` のPiccoma 200ms設定とmanual/Batch RunConfig伝播をUnitで確認した。Stage Cではshared Chrome/CDP経由で同じYAML200ms条件を使い、4回のinterleaved manual比較、専用Batch、独立prepackage manifest auditを検証した。48/48のmanual画像byte一致、24ページBatch explicit END/ZIP/Catalog完了、24/24 manifest entry一致を確認済み。Final Stage C Reviewer PASS / BLOCKING 0。

## 採用した範囲

ユーザーが採用した変更は次の3点。「待機削減」「待機短縮」は同じ変更として扱う。

| 項目 | 最終方針 | 開始時の状態 |
|---|---|---|
| native traceの転送 | 全fieldをJSON文字列で返し、Pythonで復元して既存validatorへ渡す | Stage B実装・独立Reviewer PASS。通常6回/pageのcheckpointを維持 |
| ページ送り前の固定待機 | 他サイトと同じ `crawler.yaml` の `sites.piccoma.page_turn_delay_ms: 200` | Piccoma項目無し。共通fallbackの1,000msを使用 |
| DPR微小差 | 有限数値、`abs(DPR-1)<=1e-7`。capture前後のraw viewport完全一致を維持 | 実装済み、Unit60/Integration56・bounded live確認済み |

今回の新規実装対象はJSON転送とYAML設定だけ。WebP method変更、中間PNG削減、snapshot回数削減、paint cache、thread化、描画安定条件の短縮は追加しない。WebPは現行method6/可逆性/全RGB一致を維持する。小説誤分類は別の [修正計画](../../../research/piccoma-performance/GENRE_FIX_PLAN.md) を保持し、本Phaseの性能変更と混ぜない。

## Authorityと役割

AGENTS.md、docs/SPEC.md、docs/ARCHITECTURE.md、docs/ACCESS_CONTROL_AND_PACING.md、docs/ACCESS_CONTROL_AND_PACING_PLAN.md、docs/TEST_STRATEGY.md、docs/CODEX_IMPLEMENTATION_GUIDE.md、[親runbook](../README.md) の順序・境界を守る。このrunbookは上位仕様を上書きしない。

- Lead: Sol。範囲、証拠、段階の受け入れ判断、結果統合。
- Explorer: Luna/read-only。実装時に不足した事実だけ調査。
- Implementer: Luna。唯一のproduction writer。コード・tests・設定・note同期を担当。
- Reviewer: Sol/read-only。各material diffと最終結果を独立確認し、BLOCKING解消後だけ次へ進む。
- Tester: Luna。必要なlive比較・成果物確認。実ブラウザoperatorは同時に1人だけ。

既存feature branchと作業差分を確認し、ユーザーの `watchlist.yaml`、`debug.log`、未commit DPR変更を保持する。古い `feat/piccoma-adapter` へ無条件に切り替えない。調査ブランチは `research/piccoma-performance-20261010`、調査基準は `69fccad`＋DPR変更。実装開始時の実HEAD/branch/dirty状態を記録する。

## 既知の証拠と未検証

[旧baseline PROFILE](../../../research/piccoma-performance/PROFILE.md)、[Phase 07 Stage C profile](../../../research/piccoma-performance/PHASE07_PROFILE.md)、[Tester report](../../../research/piccoma-performance/PHASE07_TESTER.md)、[numeric measurements](../../../research/piccoma-performance/PHASE07_MEASUREMENTS.json)、[REVIEW](../../../research/piccoma-performance/REVIEW.md) を根拠にする。別母集団の研究数値を単純差分で因果評価しない。

- 標準method6/object返却/1,000msの12ページ×2run、24native/fallback0。通常20完全cycleは平均4.538秒・中央値4.151秒。trace6回は平均1.034秒、固定pacing枠1.008秒、遷移0.738秒、WebP encode0.572秒。
- 同じp1の全field JSON A/Bは24/24 deep equality。1回平均143〜166ms短縮、6回で約0.86〜0.99秒の**外挿予算**。最適化後live全体速度ではない。
- 0ms調査overrideも24native/fallback0、同ページbaselineと24/24出力byte一致。通常cycle中央値3.742秒。ただしCPU/RPC/初期化/終了処理も変動し、run全体時間はほぼ不変。0ms結果を200msの測定結果に置き換えない。
- Stage Cの4 manual runsは同じYAML200ms条件でinterleaved object/JSONを比較した。normal-cycle平均は3.601→2.743秒（-0.857秒、-23.8%）、全48対応WebPがbyte一致し、source-native/fallback0。JSON trace RPCは1.006→0.142秒/ページ、Python decodeは0.034秒/page追加。Batch 24 pages reached explicit END and passed ZIP/Catalog checks. 詳細なspan・ばらつき・資源計測と測定限界は上記Stage C profileを参照。
- Fresh prepackage auditは24/24 entriesでPASSした。通常Batchのpackagingは画像出力を削除しmanifestをZIPへ格納しないため、このauditを最終ZIPにmanifestが内包される証明と誤認しない。Final Stage C Reviewer PASS / BLOCKING 0。過去の39ページ検証はPhase 07の代用にしない。
- 最後のpartial区間の約5秒残余は原因未確定。今回の性能Phaseへcleanup修正を追加しない。

## 維持する取得・安全契約

```text
ブラウザが受信した一意の元JPEG response
  → source object/load generationと実canvas描画のbinding
  → 408 drawのfractional座標・context stateをそのままreplay
  → replay PNG → 検証済み白背景合成 → 同じRGB
  → 可逆WebP(method6) → VP8L/寸法/全RGB完全一致
  → fresh page/target/source/paint/hooks/response countの後検証
  → save → manifest/progress → 設定delay → go_next → 描画安定待ち
```

ページID/URL、描画世代、Canvas reset/detach、source reload、white paint、hooks/overflow/retire、完全性、encode中の変化を引き続き検出する。Free判定、page list、expected p(n+1)、3回同一signature安定、END、max_pages/same-content、AccessGuard、既存fallbackの条件・metadataを変更しない。native-onlyは性能評価の成功条件であり、本番の既存fallbackを削除する指示ではない。

## Stage A: DPR現状確認と待機設定

目的: 実装済みDPRを再実装せず保護し、既存設定経路でPiccomaを200msにする。

1. 現行DPR diffが有限builtin数値1±1e-7、bool/NaN/inf/実scale拒否、raw viewport前後一致を満たすことを確認。normalizationや許容範囲拡大を行わない。
2. root `crawler.yaml` の既存 `sites` に、次のPiccoma項目を追加する。他サイトの値は維持する。

   ```yaml
   piccoma:
     page_turn_delay_ms: 200
     inter_candidate_delay_ms: 3000
     stop_on_http_403: true
     stop_on_http_429: true
     stop_on_challenge: true
     stop_on_captcha: true
   ```

3. 「Piccomaの既定200ms」は**配布するcrawler.yamlの設定値**を意味する。共通 `DEFAULT_PAGE_TURN_DELAY_MS=1000`、設定ファイル/site/field省略時の共通fallbackは変更しない。追加のsite名分岐やAdapter内sleep・YAML読取りを作らない。
4. manual CLIは既存loader→site settings→RunConfig、Batchは既存loader→Executor→RunConfig経由で同じ200msを受け取る。見かけのYAMLだけでなく、解決されたrun inputをtestsで確認する。
5. 固定待機はsave/progress後・初回go_next前に1回だけ、page-change timeout外に置く。AD/adapter retry/loadingへ追加せず、inter-candidate delayは3,000msのまま。

許可する変更: `crawler.yaml`、設定伝播の対応tests、Piccoma note/README/runbook。既存generic経路で足りるためshared runtime/Core/Batch実装は原則変更不要。足りない場合は原因・必要差分をLeadへ報告して範囲を再定義する。

検証: 既存runtime testsをPiccoma200msで拡張/parameterizeし、YAMLロード、manual/Batchへの伝播、非負整数/0override、欠落fallback、他サイト不変を確認。pacing順序は既存testを再利用。DPR正常近傍値と帯内変化拒否の既存testを確認する。Reviewer PASSをStage A完了条件とする。

### Stage A implementation checkpoint (2026-10-10)

- 作業開始時のbranch/HEAD: `research/piccoma-performance-20261010` / `69fccad509fa19f6b2143d3826abba4fc43b7cf8`。ユーザー編集の `watchlist.yaml`、`debug.log`、既存のPiccoma DPR差分を保持。
- `crawler.yaml` にPiccomaの200ms/3000ms/stop flagsを追加。共通runtime/Core/Batchのproduction code、WebP、JSON転送、描画安定条件には変更なし。
- manual CLIは一時YAMLを通してPiccomaの `RunConfig.page_turn_delay_ms == 200` を確認。Batchは同じruntime loaderと既存 `BatchExecutor -> RunConfig` 境界で200msを確認。配布 `crawler.yaml` 解決、欠落時1000ms、明示0、Magapoke/Manga ONE/BookWalkerの既存値も確認。
- focused results: runtime/manual/Batch settings selection **14 passed**; Runner save→delay→go_next / timeout boundary **2 passed**; DPR geometry and capture mutation selections **17 passed**. Total **33 passed, 0 skipped**. The complete affected settings/CLI/Batch test files then passed **149 passed, 0 skipped** (this broader run includes the focused settings/manual/Batch cases); existing pytest-asyncio deprecation warnings only. `ruff check src tests` and `git diff --check` passed.
- Stage A implementation passed independent review: **PASS / BLOCKING 0**. No shared browser or live site was operated during Stage A. Stage B subsequently passed its independent review; Stage C evidence follows below.
- Stage B comparison baseline: `output/piccoma_performance/phase07_20261010b_dpr_object_baseline/` (ignored local copy of current `src/screenshot_crawler` and `crawler.yaml`; file hashes recorded in `baseline_manifest.json`). It contains the dirty DPR-tolerant adapter and distributed 200ms setting, but still returns object snapshots. Files are read-only. No source images, auth state, cookies, or signed URLs were copied.

## Stage B: full traceのJSON転送

目的: 検証内容・観測時点・回数を維持したまま、object転送の費用を削減する。

1. `native_capture.py` の同じfull snapshotを返す**全経路**を対象とする。現行はnative materializationのbefore/replay後/encode後、`validate_native_capture_still_current()`、`snapshot_native_trace()`を使うAdapter baseline/target recheckの計6回/page。外側helper2回だけを変更して完了にしない。
2. browserでsnapshotをfreshに取得し、対応するJSON型として安全に直列化する。Pythonは復元後のdictを既存validator/signature比較へ渡す。全408 events/sourceStates/paint/hooks/generation等を保持する。
3. site-localの小さいhelperへ転送・復元をまとめてよい。既存bounded evaluate/timeoutと、各callerのtarget unsafe/source-only unavailableの区別を維持する。compact proof、digest、generationだけのsummary、snapshot cacheへ置換しない。
4. 対応型・異常時の扱いをコードとtestsで定める。NaN/Infinityのnull化、undefined/functionの欠落、array穴のnull化、非対応object/cycle等を正常な値として通さない。browser側の直列化前チェックを使い、undefined/nonfiniteがnullへ変わった後のPython検証だけに頼らない。negative zero等の表現差は、既存validator/signature/描画結果に同じ意味を持つことを確認するか拒否する。
5. malformed JSON、復元後の非dict、不正schema/型、欠落/曖昧値、巨大payloadは成功扱いしない。追加のsize boundは既存retained/events上限・支持対象から根拠を持たせ、観測した約391KBだけを固定の正常上限にしない。既存の必要なnullは保持する。
6. encode後snapshotを前へ移動しない。同期encode中にもブラウザは動くため、fresh後検証を残す。JSONエラーでtarget不変性が証明不能になった場合にCore fallbackへ無条件に進まない。
7. URLはJSONでも元の文字列のまま比較する。丸め、URL正規化、署名queryの削除、ログ/manifestへのfull trace出力を行わない。

許可する変更: Piccoma `native_capture.py`、必要なAdapter callsite、対応Unit/browser Integration、note/README。replayのJPEG/PNG転送、画像codec/白合成、汎用Coreのevaluateは変更しない。

検証: 人工snapshotの全field/型とsignature・validator結果をobject経路と比較。unsupported値・nullable/missing・malformed/サイズ異常、hooks tamper/overflow/retire、source same-URL reload、same-value canvas reset、encode中page/paint/source/viewport変更の既存testsを拡張/再利用する。画素fixtureで同じRGBを確認する。fallback PNG/Core metadata・安全停止条件を維持。Reviewer PASSをStage B完了条件とする。

### Stage B implementation checkpoint (2026-10-10)

`capture_native_tile_replay()` のbefore/replay後/encode後、`validate_native_capture_still_current()`、Adapterのbaseline/target recheckという**全6 checkpoint**が、同じ `SNAPSHOT_JSON_EXPRESSION` を通してfresh full traceをJSON文字列で返す。呼び出し回数・順序・timeoutとencode後のfresh検証は変えていない。Pythonでdictへ復元し、既存の `validate_tile_trace()`、target/source signature、paint検証へ同じ全fieldを渡す。source URLと署名queryは文字列としてそのまま保つ。

Browser側はJSON直列化前にsnapshot構造を走査する。plain object、dense array、null/bool/string/finite numberのみ受け付け、undefined/function/symbol/BigInt、NaN/Infinity、negative zero、sparse/custom array/object、accessor、cycleを拒否する。意図的なnullは保持する。negative zeroは既存traceで使われる座標値の同値性を仮定せず、transport failureとしてfail-closedにする。新しいtransport上限は512 target events × 16 KiB/event = 8 MiB、走査上限は512 × 256 nodes。超過時はtraceを省略・切り詰めず失敗する。Python側もUTF-8サイズ、JSON構文、重複key、定数/negative zero、root schema/typeを確認する。snapshot transport/parseの失敗はtarget continuity unknownとして扱い、internal/outer/final-currentのいずれでもCore fallbackへ進めない。snapshot自体の有効なnullや、既存validatorが扱うsource-only unsupported理由の意味は維持する。

検証: `uv run pytest -q tests/unit/test_piccoma_native_capture.py tests/integration/test_piccoma_adapter_browser.py` は **139 passed, 0 skipped**（5件は既存pytest-asyncio deprecation warning）。Unitで人工full traceの全field/null、signatureと既存validatorの結果一致、不正schema/重複key/NaN/negative-zero/サイズを確認。Browser fixtureで6回すべてraw string返却、null保持、escaped/non-BMP/lone-surrogate文字列、unsupported JS値/8MiB超過を確認。replay後・encode後・Adapter target recheck・最終recheckの各JSON破損とJS直列化例外でfail-closedし、Core fallbackが呼ばれないことを確認。source-native WebPと描画RGB完全一致、および既存DPR変更検出testを含む。`uv run ruff check src tests` と `git diff --check` もPASS。Stage B independent Reviewer: **PASS / BLOCKING 0**。Stage B時点ではlive比較未実施（後続Stage Cで実施）。

## Stage C: 実装後の独立live・性能確認

1. shared Crawler Chrome/profileへ標準BrowserSession/CDPで接続する。新規専用Page/Contextのみを操作し、Chromeや他タブを閉じない。現在のexact-freeを確認して指定話を使用する。権利不明・paid/wait/ticketでは停止。
2. 専用 `output/piccoma_performance/phase07_<unique>/` 以下の新規非空拒否出力を使う。Batchは専用Catalog/Watchlist/libraryを明示し、通常Catalogへfallbackしない。画像/認証情報/署名URLはGit成果物へ含めない。
3. **manual CLIと通常Batchの本物の設定ロード経路**を確認する。research driverの `RunConfig(page_turn_delay_ms=200)` 直書きだけではYAML伝播のlive証拠にしない。repoの設定をロードするか、実装済みPiccoma項目を使った専用YAMLを作り、resolved200msを記録する。
4. 効果を分離する比較は、同一method6で「object＋YAML200ms」と「JSON＋YAML200ms」を同条件・12ページ×2runずつ（可能なら順序を交互に）計測する。旧object版は隔離checkout等で保持し、現branchの編集を巻き戻さない。対照が実行不能なら理由を記録し、JSON後の全体速度を旧1,000msとの差だけで因果評価しない。
5. p1を分離し、capture開始→次capture開始の完全cycleと最後のpartialを区別する。avg/median/p90/max、capture、trace6回、設定pacing、go_next/wait、WebP、CPU/heartbeat/RSS、初期化/終了残余を記録。親子の二重加算・異なる母集団の統計混在をしない。
6. native WebP/fallback0、連続page ID/順序/枚数、同条件object対JSONの全ページ出力byte一致（異なるならRGB完全一致を別確認し理由調査）を確認する。source/provenance/paint/後検証は既存コードとtestsでも監査する。fallback・不整合・AccessGuard停止を高速化成功に数えない。
7. 設定経路と画像/順序の最終回帰確認として、現在無料の対象話で**専用Batchを少なくとも1話ENDまで**実行する。最終本文→explicit END、manifest、ZIP member/CRC、専用Catalog完了を独立確認。manualは手順3の短い設定/capture smokeで確認し、Catalog更新は要求しない。別作品が現在無料なら追加smokeを検討する。max_pagesで切った性能runをEND成功にしない。
8. 権利・サイト状態・環境の理由でliveが不可能ならNOT VERIFIEDとし、実装済み/確認済みの状態を分ける。品質・連続性が不一致なら停止して最小修正→Reviewer再確認。速度目標のために検証を削らない。

Stage Cの証拠は新規研究結果へ保存し、2026-10-10の既存rawを上書きしない。Testerの独立成果物確認とReviewer BLOCKING0で完了する。

### Stage C implementation and live checkpoint (2026-10-10)

- Interleaved manual arms used a read-only object baseline and the reviewed JSON implementation, with identical explicit YAML SHA, `page_turn_delay_ms=200`, and stop flags. Four stock CLI runs each saved p1..p12, preserved expected `MaxPagesExceededError` at `max_pages`, used six fresh snapshots/page, and recorded native JPEG source / white backdrop / lossless WebP / fallback0. All 48 corresponding WebP files were byte-identical (and RGB/dimensions matched).
- Across 20 normal capture-start cycles per arm, object mean was 3.600739565s and JSON mean 2.743414850s: observed -0.857324715s (23.8%). Six trace RPCs were 1.005563675→0.141548770s/page; JSON decode added 0.033611520s. Capture was 2.496769345→1.631985335s. WebP method6 encode 0.508483810→0.510337605s, YAML pacing 0.208004275→0.208721775s, and page-change wait 0.627919825→0.636617750s. Method6 and stability checks were unchanged. Earlier 4.538s mean used a different 1,000ms/object baseline and is descriptive, not a pure causal comparison to this 200ms pair.
- A dedicated current-free actual Batch run processed 24 pages through explicit END with successful Catalog Run, Artifact hash/size match, 24 ordered ZIP WebP members, CRC/VP8L validation, and first 12 members byte-matching manual JSON run 1. Normal packaging deleted the temporary per-page output; the initial artifact audit therefore did not retain an independently inspected Batch manifest.
- The opt-in research-only prepackage audit hook passed independent review and one fresh dedicated 24-page Batch rerun audited every per-page manifest entry before packaging: `audit_passed=true`, p1..p24, all native/JPEG-source/verified-white/lossless-WebP, no fallback, consistent source identity, 144 native evaluations and 144 JSON decodes. It retained only allowlisted URL-free manifest facts (no URLs, titles, or raw manifest). The rerun's CLI exit was 0; the dedicated Catalog Run succeeded with explicit END, 24 pages, direct access, and quota=0; source removal after packaging was true. Its 24 ordered ZIP members passed CRC and VP8L validation, matched Catalog Artifact SHA/size, and were byte-identical to the prior Batch output; the first 12 also matched manual JSON run 1. Stage C evidence gates are PASS; final Stage C Reviewer verdict is PASS / BLOCKING 0. No source images, credentials, signed URLs, Catalog/Watchlist, or normal outputs were written to research files.
- Detailed numbers, p90/max, CPU/RSS/heartbeat, exact audit scope, and instrumentation limits: [PHASE07_PROFILE.md](../../../research/piccoma-performance/PHASE07_PROFILE.md), [PHASE07_TESTER.md](../../../research/piccoma-performance/PHASE07_TESTER.md), [PHASE07_MEASUREMENTS.json](../../../research/piccoma-performance/PHASE07_MEASUREMENTS.json). The history-only, old object/1,000ms and 0ms measurements remain in [PROFILE.md](../../../research/piccoma-performance/PROFILE.md).

## テストの選択と最終成果物

`docs/TEST_STRATEGY.md`に従いtargeted→affected→必要なIntegration/liveの順。候補は `tests/unit/test_runtime_settings.py`、既存CLI/Batch伝播・Runner pacing tests、`tests/unit/test_piccoma_native_capture.py`、`tests/integration/test_piccoma_adapter_browser.py`。人工browserで境界を確認し、外部サイトへ依存するCIは作らない。小さいsite-local/config変更でfull pytestを一律必須にはしないが、shared差分や影響不明が生じた場合は範囲を広げる。`ruff check src tests`、`git diff --check`を実行する。

完了時に以下を報告・同期する。

- 実装範囲、actual HEAD/branch、JSON全6経路、YAML resolved200ms、共通fallback不変。
- DPR既存契約、source-native/白合成/可逆性/完全一致/encode後検証の維持根拠。
- testsの件数/skip理由、Reviewer結果、実サイトページ数/END/成果物一致、性能実測と限界。
- `note/09_piccoma.md`、Adapter README、親runbook/PROGRESS、研究文書の採用済み/実装済み状態。共有契約に変更が出た場合だけ `note/00_core.md` も同期する。
- 未検証を成功とせず、通常Catalog/ユーザー成果物を保持。自動merge/追加最適化へ進まない。

Final independent review: [PHASE07_REVIEW.md](../../../research/piccoma-performance/PHASE07_REVIEW.md). Stage A/B/C complete: PASS / BLOCKING 0.

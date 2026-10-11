# 花とゆめ＋ Site Adapter — 「無料」「今なら無料」対応 Runbook

Status: Phases 01-05 and the R8 implementation passed independent code review. The R8 post-fix standard CLI E2E passed for the observed leading-empty episode and an ordinary-layout control; independent artifact audit also passed. Final documentation review: PASS / BLOCKING 0. The original four-candidate E2E remains the separate 134-page independent source-RGBA proof. The two R8 cases verified 23 960x1540 VP8L WebP pages, END, ZIPs, Catalog completion, and no entitlement mutation; they did not independently verify source-canvas RGBA equality or persist capture_mode.
Branch: feat/hanayume-adapter。
進捗と観測のauthority: [PROGRESS.md](PROGRESS.md)。この文書は実行契約。Phase 03-Bのlocal review gateとlive evidence gateは分けて記録し、overall Phase 03のPASSを先取りしない。

## 1. Purpose and current scope

The Hanayume adapter discovers episodes from a Watchlist seed, captures the clean viewer body, and supports direct-only Batch runs using the existing Catalog and Runner. The original Phases 01-05 established the logged-out `無料` rendered-PNG baseline. A later user instruction authorized a logged-in pilot and eligibility for exact `今なら無料` rows when a fresh same-work series listing proves the observed authenticated account markers.

The final listing snapshot contained 296 unique episodes: 3 exact `無料` rows and 293 exact `今なら無料` rows. With the current attempt's verified same-work series auth, all 296 were classified `access_mode=free`; the standard inclusive Watchlist scope selected four records. The logged-out baseline had kept the latter rows `unknown`. The final live Batch completed the selected `今なら無料` and `無料` records without entitlement actions. The fresh auth result remains attempt-local; missing or ambiguous auth still leaves `今なら無料` unknown and ineligible.

The earlier logged-out live Batch run completed three `無料` episodes (122 rendered-canvas PNG pages); it is historical fallback evidence. The final logged-in E2E supersedes it for current acceptance: four candidates, 134 original-canvas lossless-WebP pages, four END runs, and four verified ZIPs.

Current gate: R8 implementation review PASS / BLOCKING 0, two standard CLI E2E cases PASS, and independent artifact audit PASS / BLOCKING 0. The target-specific run verified the exact flagged slot-1 lead-in and captured the 11 actual body slots without creating a blank page. Artifact format/dimensions and packaging passed; independent source-canvas RGBA equality for these 23 pages is unverified. Final documentation review: PASS / BLOCKING 0. Other layouts/native dimensions may use the existing whole-spread rendered-PNG fallback; original JPEG bytes/DCT recovery and universal entry-overlay detection are not claimed.
## 2. 実装の基準

上位authority: AGENTS.md、docs/SPEC.md、docs/ARCHITECTURE.md、
docs/DISCOVERY_AND_BATCH.md、docs/ACCESS_CONTROL_AND_PACING.md、
docs/DECISIONS.md、docs/CAPTURE_STRATEGY.md、docs/SITE_ADAPTER_GUIDE.md、
docs/TEST_STRATEGY.md、docs/CODEX_IMPLEMENTATION_GUIDE.md、
docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md。競合時は上位文書と既存コードを確認する。

参考実装はJump+（話数範囲展開、無料状態、JPEG/DCT復元）、Magapoke（もっと見る、タイル復元）、
Comic DAYS（無料アクセス、canvas/native）、Piccoma（完全リスト、free-only Batch、lossless WebP、独立E2E）。
**UI類似だけで流用可と決めない**。既存の拡張ポイントを優先し、Coreのサイト固有分岐、Catalog schema変更、DSL/過剰抽象化を避ける。

観測シード: https://hanayume.com/episodes/8c6f15923caa0
At the start of Phase 01 this URL was only a probe entry; its work ID, order, access labels, and image format were not yet verified. Phases 01-05 later verified this seed and the supported scope: 296 unique ordered rows, 3 exact `無料` and 293 exact `今なら無料`; the final authenticated attempt classified all rows as free and the standard inclusive scope selected four E2E candidates.
同一作品のサイトから現在読める2〜3話を選び、異なる話順/ラベル/終端を含むように実サイト確認する。
適切な例がなければ不足を明示し、別の現在無料作品で補完する。

## 3. Free-only and authenticated listing rules

- One exact row-scoped `無料` badge maps to `access_mode=free`, regardless of account markers. One exact `今なら無料` badge maps to `free` only when the current Discovery or Batch attempt proves authentication on the exact canonical same-work series route. Logged-out, absent, duplicate, or ambiguous auth markers leave `今なら無料` as `unknown`. Authentication is not stored in Catalog or reused across attempts.
- The positive authentication proof is the observed unique `#xHeader.h`, one `data-e2e=hUserMenu` link with a nested `hUserIcon`, one `signoutBtn` within `.h-usermenu`, and no login anchor. Episode/range pages normally use `#xHeader.ep-h` and need not contain these account markers.
- Discovery preserves both exact row labels as site-local classifications while Catalog stores only `access_mode`; no schema extension is used. Duplicate, conflicting, missing, or unsupported row labels remain unknown/fail closed. Every range remains subject to the full same-work identity, route, count, uniqueness, and buffering checks.
- Batch requires fresh exact work/episode identity and current exact row label; only `今なら無料` also requires fresh authenticated series proof. A login or paid-entry gate and unknown state stop without clicking. Page-wide upsell/resource copy alone is not an access decision. No ticket, coin, quota, purchase, rental, or entitlement is consumed or treated as free.
- The site policy remains direct-only and declares no resource or grant-only passes. A Catalog `free` value is not sufficient by itself to override a changed current listing or failed fresh preflight.
## 4. Discovery / Capture設計の共通判断

### 全話列挙

候補A: 一覧下部の「もっと見る」をbounded反復。
候補B: 上部の「...」等を利用して話数範囲を順次expand。
Phase 01で、全件性・観測可能な終了signal・DOM安定性・操作回数を比較して**原則1方式のみ**採用する。
範囲を複数expandする場合も、隠れた話・重複・順序崩れを監査。全行をバッファし、identity一意性、
対象作品一致、話順と全体件数（宣言値があれば）を検証してからyieldする。
途中失敗を成功扱いにして既存sourceをunavailableにしない。
full/incrementalとも列挙の完全性を保証し、bounded rangeでも**作品全体の順番**を保つ。
話数表示だけをprimary keyにしない（分割話・番外編・同名話を許容）。
site IDが作品スコープなら作品IDと複合external_idにする。

### 画質と安全な取得優先順位

docs/CAPTURE_STRATEGY.mdに従い次を順に調査する。

1. Viewerの現在本文に一意に対応する元JPEG/WebP/PNG **response bytesを無変換保存**。
2. スクランブルJPEGの場合、source/ページidentityと完全なタイル置換が証明でき、
   MCU配置・DCT係数操作の条件が揃う場合だけJump+/BookWalkerの**無劣化JPEG復元**を検証。
   DCT解析で実際の幾何条件を確認し、同名関数があるという理由だけで転用しない。
3. JPEG係数操作が成立しない場合、正確な元画像由来pixel再構成（描画trace、source矩形、
   変換・背景・アルファ等の完全な帰属証明）。再現結果を基準renderと比較し、
   妥当なら**検証済みlossless WebP**、エンコードや完全一致検証失敗時はPNG。
4. 根拠不十分なら安定した本文CanvasのPNG、その次に本文Locator Screenshot PNG。

lossless WebPは**再構成後のpixelsの無劣化**であり、元JPEGバイト列の復元ではない。
元JPEG/WebP/PNGがそのまま正しいページであれば再エンコードしない。
変換画像・スクリーンショットをsource-originalと称さない。
読書順・見開き・先頭/最後・白背景・縮尺・DPR・描画完了・余白/UI混入を検証し、
不完全な片側ページや広告は保存しない。
高優先captureを証明できず、堅牢な低優先captureで本文を正しく保存できるときは
E2Eまで到達を優先してよい。ただしnative可能性のProbe結果・未対応条件を明記し、画質劣化を黙認しない。

## 5. 実行フェーズ・ゲート

R2 document-start source-canvas capture and strict lossless WebP validation passed the final live run: 134/134 native pages, 0 rendered fallbacks. R3 authenticated `今なら無料` classification, R4 public-root validation, and R5 bounded readiness are included in the same verified four-candidate Batch E2E. The earlier 122-page rendered-PNG run remains historical baseline evidence.

1. [01 — Site/Repo Probe](01-site-probe/README.md): 全件一覧、2種の表示状態、ログアウト可能な閲覧、viewer、原画像候補、終端を証拠付き確認。
2. [02 — Discovery](02-discovery/README.md): exact `無料` / `今なら無料` row classification; the latter is free only with fresh verified account markers on the canonical same-work series route, otherwise unknown; complete ordering and independent Review.
3. [03 — Viewer/Capture](03-viewer-capture/README.md): live free preflight、安定したpage/END、原画像優先capture、比較テスト、独立Review。
4. [04 — Policy/Batch](04-batch/README.md): direct-only Policy、Planner/Executor/ZIP/Catalog統合、独立Review。
5. [05 — Independent E2E](05-e2e/README.md): 2〜3話の実パイプライン、画像・状態の独立監査、最終Review。

後半で重大なcapture問題が発見された場合、LeadはPhase 03に戻って修正/Review後にPhase 05を再実行する。
先行Phaseが未証明なら次のPhaseで成功を捏造しない。

## 6. 役割・作業ルール

- Lead/root: gpt-6.1-sol / xhigh。Phase契約・整合性・設計/ゲート・進捗管理。
- Explorer: site_adapter_explorer / gpt-6-luna / xhigh。既存実装と実サイトの独立調査、read-only。
- Implementer: site_adapter_implementer / gpt-6-luna / xhigh。唯一のproduction writer。PoC、実装、テスト、README/note同期。
- Reviewer: site_adapter_reviewer / gpt-6.1-sol / high。変更差分・access/identity/画質/回帰の独立read-only Review。
- Tester: site_adapter_tester / gpt-6-luna / high。必要時の独立実サイトE2Eと成果物監査。production編集禁止。

AGENTS.mdとdocs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.mdの既存role設定を利用。
並列化はread-only独立調査に限り、**production writerは1名、shared Chrome操作者も同時に1名**。
Review後のBLOCKINGは修正・再Reviewするまで次へ進めない。
ユーザーへの確認は真に判断が必要な最大3点に整理しつつ、観測事実・危険・未検証点は省略しない。

## 7. 作業場所・変更可能範囲

実装ブランチ: feat/hanayume-adapter。mainへ自動mergeしない。
実装の主体は src/screenshot_crawler/site_adapters/hanayume/ と関連tests、
必要最低限のsite registry / CLI registration / policy wiring / docs / note。
既存Core/Batch/他Adapter変更は既存extensionで不可能なことを証明した場合だけLead承認。

隔離する実行データ（必ず実際のCLIで明示指定）:
- output/hanayume_experiment/watchlist.yaml
- output/hanayume_experiment/catalog.sqlite
- output/hanayume_experiment/batch/
- output/hanayume_experiment/library/
- 秘密を除去したevidence（ignored、cleanup対象とは分離）

既存Crawler Chromeと共有profileへPlaywright/CDP接続する。AdapterはChrome起動・CDP接続・profile解決をしない。
通常Catalog/Watchlist/outputへの暗黙fallbackは禁止。既存利用者の未commit変更・ブラウザsessionを破壊しない。
cookie、署名付きURL、token、購入画面、原画像、著作物fixtureや生の機密ログをcommitしない。
すべてのtimeout/retry/クリック回数/pacingは有限でAccessGuard/max_pages/same-content guardを維持する。

## 8. Current exit gates

Current verification: the earlier four-candidate logged-in E2E independently proved exact source-canvas RGBA for 134 pages. R8 implementation review and independent artifact audit both passed, and two fresh standard CLI E2E cases passed: the top-empty target completed 11 body pages, and an ordinary-layout control completed 12. All 23 members were 960x1540 VP8L WebP; the two ZIPs and completed isolated Catalog records passed independent checks. Source-canvas RGBA equality for these latest 23 pages was not independently measured, and capture_mode was not persisted. No full pytest rerun was performed for this site-local change; the affected selection, Ruff, and diff checks passed. Final documentation review: PASS / BLOCKING 0.
## 9. Codex起動時

最初に本READMEとPROGRESS.md・Phase 01を読み、上位authorityと現行main差分を確認する。
Phaseごとに目的/観測/未確定/変更範囲/受け入れ条件/テストをLeadが提示し、
Probe→Implementer→Reviewer→必要ならTester→PROGRESS更新の順に実行する。
最終報告は「実装したもの」「テストしたもの」「未確認のもの」を厳密に分ける。

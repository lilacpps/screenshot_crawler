# 花とゆめ＋ Site Adapter — 「無料」「今なら無料」対応 Runbook

Status: Phases 01-05 PASS / BLOCKING 0 within the user-authorized logged-out `無料` scope. Final independent Reviewer passed (42 fresh tests, 0 skipped; Ruff, diff, and SQLite/ZIP/PNG artifact audits passed). The Tester completed three episodes, 122 body pages, and three ZIP Artifacts with 9/9 visual samples passing. `今なら無料` remains `unknown` and authenticated non-consuming access is unverified under the no-login instruction. The full pytest run predates the latest site-only geometry correction; the independent post-fix affected selection passed.
Branch: feat/hanayume-adapter。
進捗と観測のauthority: [PROGRESS.md](PROGRESS.md)。この文書は実行契約。Phase 03-Bのlocal review gateとlive evidence gateは分けて記録し、overall Phase 03のPASSを先取りしない。

## 1. 目的と第一段階のスコープ

花とゆめ＋（hanayume.com）の作品内エピソードをWatchlistの1話URLから発見し、
一覧に出る「無料」「今なら無料」を別々の表示状態としてDiscoveryへ取り込む。
この実行ではユーザー指示「ログインせず、検証可能な範囲で進める」に従い、
現在ログアウトで直接閲覧を確認できた「無料」だけをdirect-only Batch候補にする。
「今なら無料」は登録/ログインが必要というViewer表示を観測したためDiscoveryには残すが、
認証された状態の非消費閲覧は未確認としてBatch対象外にする。

Watchlist → full/incremental/可能ならsite-native bounded Discovery
→ Catalog → Batch Plan（direct-only）→ Batch Run → Crawl → Manifest/ZIP → Catalog completed。

- Discoveryは行の正確な表示を別々に判定する。「無料」は `access_mode=free`、「今なら無料」は `access_mode=unknown` とし、raw labelはCatalogへ保存しない。free eligibilityは表示だけで決めず、Viewerの非消費入場を確認した状態だけをBatch候補にする。現在のrun scopeではログアウトで確認した「無料」のみ対象。
- **配信期限を開発優先度・終了条件・固定の除外条件にしない**。ただし、実行時に無料でなくなった話は自動取得せずfail closed。もしサイトが終了日時を明示するなら既存モデルで保持可能か調査し、あくまで補助情報とする。
- 作品横断の全サイト検索やquota/課金の自動取得は対象外。別作品にも再利用できるsite adapterとする。
- 初期版はサイトで正規に利用できる無料閲覧を対象とし、アクセス制御・DRMの回避はしない。

**Phase 01で確認済み**: 10個の話数範囲ページで296/296件の一意IDを観測。「もっと見る」は55行で増分が止まっても表示されたため完了判定に使わない。「今なら無料」はログイン/登録要求の画面を表示し、ログアウト状態での閲覧は確認できなかった。
**Phase 03/05 evidence:** for the three logged-out `無料` samples, counters were 37/45/55 and the viewer had 38/46/56 `#xCVPages` slots. In these samples, slot 0 was promotion; slots 1 through N−5 were structural body candidate wrappers, many unloaded placeholders without a canvas; slot N−4 was book information, then two promotion slots, followed by good/last terminal UI. At N−4 the final body canvas was visible; at terminal N/N there was no body canvas. All were in `mode-spread`; no single-page control was established. This is sample evidence, not a universal rule. One first-page source replay from 16 complete tiles into a 960×1540 scratch canvas and the exact 828×1329 visible scale matched pixels exactly. A third-sample scratch-to-visible canvas relationship remains unresolved, so no all-page source-native claim is justified. The final three-sample live Batch E2E captured 32/40/50 body pages (122 total) as clean rendered body-canvas PNGs at 828×1329; all same-run RGBA comparisons matched, all three ZIPs passed Manifest order/count/CRC/hash checks, and first/middle/last visual checks passed for each episode. DCT is rejected only for the measured 240×385 tile geometry, whose 385px height is unaligned to MCU-8. The earlier HTTP 429 and one-page timeout are historical failures superseded by the later PASS; see [PROGRESS.md](PROGRESS.md). Phase 02 live Discovery verified same-work identity, all ten ranges, and all 296 rows for the seed work; the final Batch test reused that Catalog and did not rerun Discovery.

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
このURLは調査入口であり、対応する作品ID・話順・無料状態・画像種別をまだ確認したものではない。
同一作品のサイトから現在読める2〜3話を選び、異なる話順/ラベル/終端を含むように実サイト確認する。
適切な例がなければ不足を明示し、別の現在無料作品で補完する。

## 3. free-only契約

- 現在のログアウト実行では、同じ行の唯一の正確な「無料」badgeだけをfreeにする。複数badge、欠落、矛盾、未対応ラベルはunknownにする。「今なら無料」はDiscoveryで検出・区別するが、Catalog上はunknownであり、Batch候補にしない。
- 「無料」3話はログアウト状態の正規Viewerで表示された。「今なら無料」の認証済み非消費閲覧可否は未検証。ユーザーのno-login指示により、ログイン、登録、権利付与、購入操作は行わず、この範囲を広げない。
- 将来「今なら無料」をBatch対象へ含めるには、ログイン済み利用者についても同一話の現在の権利・Viewer入口・無消費性を示す追加の非消費証拠が必要。raw labelをCatalog schemaへ黙って追加しない。
- 有料、quota、レンタル、待てば無料、会員特典/購入済み、表示矛盾、unknownは**Batch非対象**。これらを無条件freeへ昇格させない。
- Catalogがfreeでも、**各Batch入場直前にliveサイトで同じ作品/話identityと現在の対象無料ラベルを再確認**。不一致、無料終了、未知のダイアログ、課金CTAは停止/skip。別エピソードへ暗黙移動しない。
- Site Policyはdirect-only、quota resource/消費記録/後続grant passなし。auto/directも同じ安全な無料入場に限定し、quotaは明示拒否。
- full Discoveryでラベル変更を観測したら次のBatchは新しい状態に従う。既存completed ItemやArtifactをDiscoveryで巻き戻さない。

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

1. [01 — Site/Repo Probe](01-site-probe/README.md): 全件一覧、2種の表示状態、ログアウト可能な閲覧、viewer、原画像候補、終端を証拠付き確認。
2. [02 — Discovery](02-discovery/README.md): 「無料」/「今なら無料」の診断分類（後者はunknown）、全話同期、global order、full/incremental/bounded、独立Review。
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

## 8. 最終受け入れ条件

- 1話URLから対象作品全体を漏れなく正しく列挙し、全体順序をCatalogへ保持。
- 「無料」と「今なら無料」それぞれの正確な表示状態を**独立にDiscoveryテスト**する。Catalogには現在の `access_mode` のみを保存し、raw labelは診断値とする。Batch候補にするのは同一identityの現在状態を無消費で直接閲覧できると確認したものだけ。
  このrunではログアウトで確認した「無料」のみBatch対象。「今なら無料」は登録要求を確認したためunknown/ineligibleとして残し、誤って取得しない。
- Batch直前に毎回identityと無料ラベルを再確認し、条件変化を安全に扱う。
- 2〜3話のログアウト状態「無料」例を標準Discovery→Batch→ZIPで検証する。「今なら無料」の認証済み非消費確認は、ユーザーの「ログインせず」指示によりこのrunの受け入れ条件から除外し、未検証として残す。
- 本文の欠落・重複・ページ順序逆転・画像品質の不当な劣化・広告/次話混入なし。
  Native復元には厳密なprovenance/pixel照合、fallbackには正しいMethod記録。
- 最終本文後のENDが観測され、Manifest/ZIP CRC/各member hash、Artifact、
  Catalog completed/Succeeded Runを整合検証。失敗話はpendingのまま。
- Relevant Unit/Integration/Live試験、独立Reviewer BLOCKING 0、独立Tester結果、未検証点をPROGRESS.mdに明示。
  実サイトで条件を満たす例が見つからなければその項目はNOT VERIFIEDとし、部分成功を完成扱いしない。

## 9. Codex起動時

最初に本READMEとPROGRESS.md・Phase 01を読み、上位authorityと現行main差分を確認する。
Phaseごとに目的/観測/未確定/変更範囲/受け入れ条件/テストをLeadが提示し、
Probe→Implementer→Reviewer→必要ならTester→PROGRESS更新の順に実行する。
最終報告は「実装したもの」「テストしたもの」「未確認のもの」を厳密に分ける。


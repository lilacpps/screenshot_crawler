# 花とゆめ＋ Site Adapter — 「無料」「今なら無料」対応 Runbook

Status: PLANNED / 実サイト未調査・実装未着手（2026-10-10）。
Branch: feat/hanayume-adapter。
進捗と観測のauthority: [PROGRESS.md](PROGRESS.md)。この文書は実行契約であり、実装完了を意味しない。

## 1. 目的と第一段階のスコープ

花とゆめ＋（hanayume.com）の作品内エピソードをWatchlistの1話URLから発見し、
**表示が「無料」または「今なら無料」の話**を既存の通常のdirect-only Batch Runで取り込み、
本文を正しい読書順でManifest/ZIPに保存する。

Watchlist → full/incremental/可能ならsite-native bounded Discovery
→ Catalog → Batch Plan（direct-only）→ Batch Run → Crawl → Manifest/ZIP → Catalog completed。

- 「無料」も「今なら無料」も初期版の**同等な採用対象**。両者を生の表示状態として区別して観測・テストし、現行Catalogには検証済みの両方をfreeとして表現する方針（既存schema優先）。
- **配信期限を開発優先度・終了条件・固定の除外条件にしない**。ただし、実行時に無料でなくなった話は自動取得せずfail closed。もしサイトが終了日時を明示するなら既存モデルで保持可能か調査し、あくまで補助情報とする。
- 作品横断の全サイト検索やquota/課金の自動取得は対象外。別作品にも再利用できるsite adapterとする。
- 初期版はサイトで正規に利用できる無料閲覧を対象とし、アクセス制御・DRMの回避はしない。

**重要な未検証事項**: 一覧のexpand構造、安定した作品/話identity、「今なら無料」の実際の閲覧条件、Viewer実体と原画像構成、END挙動。画面観測前にselectorやAPI形式を確定しない。

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

- Discoveryのpositive signalは、対象行に対応するサイト固有の正確な **「無料」/「今なら無料」** 表示と、その表示のscope・矛盾のなさ。単にViewerが読めた／ログイン済／以前開いたことがあるだけではfreeとしない。
- 対象となる両表示について、Viewer入場時に購入・ポイント・コイン・チケット・待機消費・新たな権利開放を必要としないことをPhase 01で検証する。正規セッションでの単純閲覧は可能だが、ログイン自動化や利用権付与操作は初期版対象外。
- 「今なら無料」が条件付き・権利消費型であると判明した場合、証拠に基づいてそのサブタイプをunknown/unsupportedへ保留し、Leadが範囲を明示的に再設計する。ラベルだけで危険な遷移を自動化しない。
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

1. [01 — Site/Repo Probe](01-site-probe/README.md): 全件一覧、2種のfree表示、viewer、原画像候補、終端を証拠付き確認。
2. [02 — Discovery](02-discovery/README.md): 両無料ラベル分類、全話同期、global order、full/incremental/bounded、独立Review。
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
- 「無料」と「今なら無料」それぞれを、**独立のpositive signalとしてテスト**し、検証済みであればどちらもdirect候補。
  非対象状態や矛盾は誤って取得しない。
- Batch直前に毎回identityと無料ラベルを再確認し、条件変化を安全に扱う。
- 2〜3話（両ラベルのlive例が存在するなら双方を含む）を標準Discovery→Batch→ZIPで検証。
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


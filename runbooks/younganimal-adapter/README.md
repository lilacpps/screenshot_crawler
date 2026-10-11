# Young Animal Web — 無料・待つと無料 Site Adapter 実装 Runbook

Status: IN PROGRESS (2026-10-11). Phase 01 verified. Phase 02 partial Discovery implementation/tests/docs are Reviewer VERIFIED (BLOCKING 0) and local checks pass; full target live Discovery remains incomplete on HTTP 429, and the corrected code was not live-tested. Phases 03-04 are not implemented; Phase 05 is documentation/unknown-only with waiting not implemented; Phase 06 local audit passes but live E2E is incomplete.
Execution branch: `feat/younganimal-adapter` (base: `main` @ `43d9218`)
Authority for observations and actual completion: [PROGRESS.md](PROGRESS.md)

Current phase gate: 01 VERIFIED; 02 partial Discovery REVIEWER VERIFIED (BLOCKING 0), LOCAL PASS, full live Discovery INCOMPLETE (HTTP 429; corrected code not live); 03-04 NOT IMPLEMENTED; 05 documentation/unknown-only, wait flow NOT IMPLEMENTED; 06 local Tester audit PASS, live E2E INCOMPLETE. No post-429 live request was made and no human approval is pending; the HTTP 429 is an external blocker.
Future authorized live Discovery entry after the HTTP 429 stop clears: `https://younganimal.com/series/aee4fa742b0fe` (the observed target work listing; the adapter accepts canonical `/series/<work-id>` URLs, not an ID allowlist).

## 1. 目的と最終的な受け入れ範囲

ヤングアニマルWebの作品をWatchlistへ登録し、作品内の各話をDiscoveryしたうえで、
**「無料」および「待つと無料」** のうち**現在正規に閲覧可能な状態**の話を、
既存の `Discovery → Catalog → Batch Plan → Batch Run → Crawl → Manifest/ZIP`
で取り込めるSite Adapterを実装する。

- サイトキーは **`younganimal`**。`hanayume` とWatchlist、Catalog source identity、Policy、セッション・resource stateを混同しない。
- **初期目標は「無料」の標準Batch→ZIPを実サイトで完成**。次に「待つと無料」の実状態を確認して必要な待機・解放・閲覧の実装を加える。**freeだけの成功を全体完成としない**。
- 「待つと無料」の待機開始が無料か、別の権利/資源を消費するかは未確認。未解放、待機中、現在閲覧可能、期限切れ等を実測し、それぞれを安全に分類・処理する。サイトが正当に提供する無償の待機開始が確認できれば、その狭い契約で実装可能。チケット・コイン・ポイント等の消費を伴う場合、勝手に動かさず別の明示承認・設計を要する。
- **チケットの獲得・利用は今回の実装対象外**。共通ID/白泉社だからといって権利・残高・タイマーがサイト間で共有されるとは仮定しない。ログインは別、IDは共通（ユーザー情報）。
- 配信期限による開発優先づけはしないが、実行時のアクセス資格や期限切れは実測し、権利がない話を取得しない。

### 変更対象と設計自由度

**ヤングアニマル専用の独立Adapterを作ることをデフォルトとしてよい。**
Hanayume/Comiciの共通化は義務ではない。複製のほうが分かりやすく回帰リスクが低ければ、
サイト固有の `discovery.py`、`adapter.py`、`native_capture.py`、`policy.py` を独立させる。
**2サイト共通であることが実証でき、共有によって実装や保守が明確に簡単になる小さな処理だけ**共有する。
共通化のためにHanayumeやCoreを大規模リファクタリングしない。

## 2. Authority / 参考実装

上位authority:
`AGENTS.md`、`docs/SPEC.md`、`docs/ARCHITECTURE.md`、
`docs/DISCOVERY_AND_BATCH.md`、`docs/ACCESS_CONTROL_AND_PACING.md`、
`docs/CAPTURE_STRATEGY.md`、`docs/SITE_ADAPTER_GUIDE.md`、
`docs/TEST_STRATEGY.md`、`docs/CODEX_IMPLEMENTATION_GUIDE.md`、
`docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md`。
runbookは上位仕様に優先しない。衝突を発見したらLeadが明示する。

- `src/screenshot_crawler/site_adapters/hanayume/` およびそのテストとsite README / `note/10_hanayume.md`
- Hanayume R8: `mode-has-top-emptypage` + 厳密な空白先頭判定、物理body slot再マッピング
- Hanayume wrapper variant: counterと`#xCVPages`物理wrapper数の不一致
- Hanayume R9: Catalogで対象を選んだBatchは**対象話のcanonical URLへ直接移動**し、不要なseries一覧往復を省略。手動Crawlは別のfresh preflight。
- Hanayume R10: 初回Canvasでgeneration/write/identityが静止する有界待機と、native post-encoding検証失敗時の詳細diagnostics
- Hanayume `native_capture.py`: full-frame source canvasのdraw-time snapshot、renderer pixel proof、元サイズのlossless WebP、PNG fallback。これは**特定レイアウトでの証明**であり、Younganimalに元寸法960x1540や同一のタイル幾何を強制しない。
- Jump+ / BookWalkerのDCT係数ベースJPEG無劣化復元、Magapokeのtile再構成、Piccomaのsource-derived pixel + lossless WebPも参照。

前回の[Younganimal互換性調査](https://github.com/lilacpps/screenshot_crawler/blob/research/younganimal-comici-compat/runbooks/younganimal-compat/COMPARISON.md)、
[Evidence](https://github.com/lilacpps/screenshot_crawler/blob/research/younganimal-comici-compat/runbooks/younganimal-compat/EVIDENCE.md)、
[提案計画](https://github.com/lilacpps/screenshot_crawler/blob/research/younganimal-comici-compat/runbooks/younganimal-compat/IMPLEMENTATION_PLAN.md)
は参考資料。研究ブランチの資料をProduction側へ丸ごと取り込む必要はない。
前回Probeは「無料」の部分一致候補2作品とViewer初期表示1話にとどまり、
exact label、全件Discovery、END、native pixels、「待つと無料」状態は**未検証**。
2話目`page.goto` timeoutの原因も未確定。**これらを欠けたまま使える仕様だと断定しない。**

## 3. 作業フェーズ（最後まで自律実行する）

1. [01 — 追加Probeと契約確定](01-site-probe/README.md):
   少数の実サイト操作で2つのaccessラベル、listing、Viewer/Canvas geometry、END、
   待機状態を観測し、観測できた部分から次Phaseへ進む。
2. [02 — Discovery](02-discovery/README.md):
   完全な作品話数一覧、全体話順、正確なラベル分類、full/incremental/bounded、Catalog同期。
3. [03 — Viewer / Image Capture](03-viewer-capture/README.md):
   初回/空白/spread/terminal、元JPEG→無劣化JPEG復元→元Canvas→lossless WebP/PNGの証拠順で実装。
4. [04 — 「無料」direct Batch](04-free-batch/README.md):
   Hanayume同様、Catalog-selected candidateの**1回の直接Viewer移動**を標準にし、free direct Batch→ZIPを完成。
5. [05 — 「待つと無料」](05-wait-free/README.md):
   正確なstate/access/resource契約を実測し、確認できた無償の正常閲覧/待機動作を追加。
   権利消費不明・チケット要求時はその経路のみfail closed。
6. [06 — 独立E2Eと最終Gate](06-e2e/README.md):
   free / wait-freeそれぞれのsupported stateで標準経路を確認し、画質・成果物・Catalog・resource stateを独立監査。

**進め方**: Phase 01を別の「調査で打ち切るタスク」にせず、得られた確実な事実からPhase 02〜04を自律的に実装する。
必要な未知が残ればその箇所で小さなProbeを追加し、根拠を揃えて続ける。
Phase 05も同様に先へ進める。人間に確認すべき権利消費/契約変更が本当に必要になった場合だけ停止し、
**すでに安全に完成できた機能・テスト・ドキュメント・コミットを残して報告**する。
有効な対象話が不在・サイトが応答しない場合は外部blockerと未検証内容を明記し、成功扱いしない。

## 4. Access / Site Policy基本規則

- `無料` は**正確なrow-scoped positive signal**とその正当なアクセス条件を検証してfreeに分類する。
  substring / Viewerがたまたま読める / 過去のgrantのみを証拠にしない。
- `待つと無料` は「現在閲覧できるか」「待機開始が必要か」「待機中か」「期限切れか」を**別状態**で観測する。
  待機前を無条件free/directにしない。既存Catalog / SitePolicy / resource・grant契約で表せる場合だけ採用。
  仮定でshared schemaを拡張しない。
- **通常の`無料` BatchはCatalogから直接URLへ1回入場**できる最小実装を選ぶ。
  Hanayume R9にならい、毎回のseries一覧へ往復することは必須にしない。
  source identityとViewerの閲覧可能状態・bodyの正当性・ENDは厳格に確認。
  現在のサイトがentryに権利消費を伴うことが判明したら**直接入場を停止**し、site-localな安全入口を検討する。
- 手動Crawlや待機開始/解放操作、サイトで異なる権利の入口は、個別のfresh access判定を実装。
- 未確認または変化した権利、購入・チケット・コイン・ポイント・待機resourceの不正な代用、
  予期しないconfirm/modal/next-episodeはfail closed。チケットの暗黙fallbackなし。
- `AccessGuard`、pacing、max_pages、same-content、finite retries、quota state
  とartifactの成功時更新を維持。既存ユーザーデータに触れない。

## 5. Captureの優先順位と品質

1. **原JPEG/WebP/PNGバイト列**: Viewerが使用する現在本文と1対1で対応することを実証できれば再圧縮なしで保存。
2. **JPEGスクランブル無劣化復元**: exact draw/tile map、MCU、DCT係数配置、量子化テーブルの
   可逆変換が証明された場合のみ既存Jump+/BookWalker方式を利用。
3. **source-native pixels**: 完全なdrawing/transform/source provenanceのもとで
   元Canvas/sourceの描画時画素を保持。元画像のnative寸法を維持し、
   正確なpixel復元と表示との対応を検証。
   **検証済みpixelsをlossless WebPへ**（VP8L＋復号後RGBA完全一致）。
   WebPエンコードや検証に失敗したら同じ検証済みPNG。
4. **rendered body canvas PNG**: nativeが証明できない場合の正しいfallback。
   キャプチャ中にCanvasが変わった場合や不完全spreadは停止。
   Browser chrome / 全画面Screenshotは最後の手段で、安易にsource-originalと呼ばない。

Hanayumeのコードを使う場合も**元画像寸法、draw geometry、page identity、font/UI混入**
をYounganimalで再検証。DCT復元が成立しないと確認できたら延々と追わず、
正しい元Canvas/pixel経路でfree E2Eを成立させる。

## 6. 役割 / 安全な作業範囲

- Lead / root: `gpt-6.1-sol` / `xhigh`。証拠・設計・scope・Phaseゲートと進捗管理。
- Explorer: `site_adapter_explorer` (`gpt-6-luna` / `xhigh`): 調査・リスク抽出（read-only）。
- Implementer: `site_adapter_implementer` (`gpt-6-luna` / `xhigh`): 唯一のProduction writer、Probe/コード/テスト/note更新。
- Reviewer: `site_adapter_reviewer` (`gpt-6.1-sol` / `high`): 独立、read-only、BLOCKING是正確認。
- Tester: `site_adapter_tester` (`gpt-6-luna` / `high`): リスクの高いlive E2E/画質/ZIP独立監査（production編集禁止）。

同時にProductionを書き換える担当は1名、共有Chromeのoperatorも1名。
個別PhaseでReviewer BLOCKING 0を得て次へ進む。実ブラウザに基づく決定を
Explorerができなければ、Implementerに少数の有界Probeを依頼する。
役割の儀式的並列化は不要。

変更候補: `src/screenshot_crawler/site_adapters/younganimal/`、
`src/screenshot_crawler/site_policies/younganimal.py`、
`src/screenshot_crawler/cli.py`の既存4registry、`src/screenshot_crawler/site_policies/__init__.py`、
対象test、`src/screenshot_crawler/site_adapters/younganimal/README.md`、
新しい`note/<nn>_younganimal.md`、本runbookのPROGRESSと必要な上位docs。
**既存Hanayume本体・shared Coreを変更する場合は、必要性・影響・回帰テストを先に示す**。

Research/live出力: `output/younganimal_experiment/{watchlist.yaml,catalog.sqlite,batch,library,diagnostics}`。
すべて明示パスを使用し、通常`catalog.sqlite`や`watchlist.yaml`へfallbackしない。
browser profile、Cookie、署名付きURL、著作物画像、認証情報、raw HTML/Network bodyはcommitしない。

## 7. 最終受け入れと成果報告

- 「無料」: exact分類→完全Discovery→free direct-only Batch→本文全ページ→END→ZIP→Catalog completed。
- 「待つと無料」: 待機前/待機中/閲覧可能を正しく扱い、実装した正当な経路でBatch/ZIP到達。
  実証できない状態はUNKNOWN・skipとし、**全体完成扱いにしない**。
- Work/episode identity、作品全体の順序、native/canvasにおけるページ欠落・重複・逆転・広告混入なし。
- Nativeであればprovenance・RGBA一致、WebPならlossless、fallback理由を正確に記録。
- ZIP CRC/member/Manifest/hash、Catalog item/run/artifact、失敗時pending、権利/リソースの変更を監査。
- relevant Unit/Integration、2〜3話（可能なら別作品）実サイトE2E、Reviewer BLOCKING 0。
- README・note・runbookを実際の実装状態へ同期。最後に実装済み・未実装・未検証、
  変更パス、テストと未実行理由、確認事項最大3点を報告。
- **mainへ自動マージしない。作業ブランチにコード・テスト・runbookをコミット。**

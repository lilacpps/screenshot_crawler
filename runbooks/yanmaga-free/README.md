# ヤンマガWeb（yanmaga.jp）通常無料のみ Site Adapter 実装 Runbook

**Status:** IN PROGRESS（Phases 02–04 accepted; Phase 05 ordinary CLI E2E passed for the observed Chapter 11 candidate; final independent Reviewer accepted with BLOCKING 0. Root commit/push handoff remains; Phase 01 daily-limit scope is unknown.）
**Repository:** `lilacpps/screenshot_crawler`
**実装ブランチ:** `feat/yanmaga-adapter`（`main` の `ddfcee7` から計画ファイルを作成。コードはこのブランチで実装し、`main` へ自動マージしない）
**サイトキー:** `yanmaga`
**優先対象作品:** https://yanmaga.jp/comics/%E3%82%A6%E3%82%B5%E3%82%AE%E3%81%A8%E3%82%AB%E3%83%A1%E3%81%AE%E3%82%86%E3%82%8B%E5%B1%B1%E6%AD%A9 （Chapter 1 の無条件赤字無料は2026-10-20の観測結果であり、再実行時もfresh checkが必要）
**進捗:** [PROGRESS.md](PROGRESS.md)。各フェーズは実行契約であり、観測・実行結果はPROGRESSに分けて記録する。

## 1. 目的・スコープ

Watchlistの作品URLを起点として、ヤンマガWebで **「赤字の『無料』」として示される、本当に無条件で読める公開話だけ** を `Discovery (full / incremental) → Catalog → batch plan → batch run → Viewer → Manifest / ZIP → Completed` の既存CLIフローで扱えるようにする。

今回のv1では **無条件の無料公開話だけ** に対応する。初回無料、黄色の「無料」（チケットを要する閲覧）、待つと無料、会員特典、ポイント利用、有料レンタル、購入、ログイン、既存Grantの利用・引継ぎ、アプリ限定コンテンツは**取得対象外**。無料扱いを証明できない話は`unknown`に倒す。ユーザーの認証・残高・チケット・閲覧権限を使って「無料」と分類しない。

公式サポートは無料連載マンガが会員登録なしで閲覧できると案内している。一方、公式作品ページには「※無料は1日で読める数に限りがあります。」と表示される場合がある。**この注意書きが通常の赤字無料に適用されるか、ログイン不要の無料話に追加ゲートがあるかはPhase 01で必ず実測する。** もし対象話に正規のリソース消費・解除・新規閲覧枠が必要ならv1の`free`とはしない。件数上限や再設定時刻を推測して実装しない。

### Access classification（v1）

| 公開ページの表示 / 事実 | Catalog `access_mode` | Batch |
| --- | --- | --- |
| 赤字の「無料」かつ**同じ話**の無条件・現在・公開状態を正の証拠で確認 | `free` | `direct` |
| 「初回無料」（登録・権利・日次枠などが必要） | `quota`（内部分類が正に確認できる場合のみ）または`unknown` | SKIP |
| 黄色の「無料」・チケット等が必要 | `quota`（チケットの正の根拠がある場合のみ）または`unknown` | SKIP |
| ポイント/課金でのみ読める | `paid`（根拠が明確な場合のみ）または`unknown` | SKIP |
| バッジが競合・色/DOM/APIが不明・権利依存・掲載消失 | `unknown` または実測`available=false` | SKIP |

**重要：**「70 無料」などポイント数と`無料`が同じ行に並ぶ実例がある。数値があるという理由だけで`paid`にしない、逆に文字列の`無料`だけで`free`にもしない。表示色の人間による説明を実装の唯一のauthorityにせず、DOM/APIの**行に紐づく意味、対象話ID、正規の公開閲覧可否**をセットで検証する。初回無料とチケット無料は将来別々の資源になりうるので解析上は区別するが、v1のCatalogを改造するための追加フィールド・スキーマ移行は行わない。信頼できなければ一律`unknown`でよい。

### v1でしないこと

- チケット残量、回復時刻、初回無料の日次枠、閲覧期限、クーポン、ポイント数の管理・消費。
- 確認/購入/無料登録/レンタル/ポイント/チケットのアクション（`auto`の暗黙fallbackも含む）。
- 認証済みプロフィールの個別権利を通常無料の根拠にすること、アクセス制御/DRM/CAPTCHA/MFA/403/429の回避。
- ヤンマガ以外のsite改造、汎用Access Resource DSL、Core/Catalogスキーマの先行リファクタリング。
- 無料話の取得を理由に全話ダウンロードを約束すること。十分な正の証拠がない話は取得しない。

## 2. Authority・実装戦略

実装前に `AGENTS.md`、`docs/SPEC.md`、`docs/ARCHITECTURE.md`、`docs/DISCOVERY_AND_BATCH.md`、`docs/ACCESS_CONTROL_AND_PACING.md`、`docs/CAPTURE_STRATEGY.md`、`docs/TEST_STRATEGY.md`、`docs/CODEX_IMPLEMENTATION_GUIDE.md`、`docs/SITE_ADAPTER_GUIDE.md`、`docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md`、実装コードとtestを読む。上位authorityが優先であり、runbookだけを理由にshared contractを変更しない。

参考実装（**構造の参考であり、同じサイト技術の証拠ではない**）:
1. `site_adapters/comicfuz/` と `site_policies/comicfuz.py`: 公開free行を厳格に認証し、Batchでfresh preflightしてからReaderに入るdirect-only flow。
2. `site_adapters/piccoma/`: 同じ話に複数access markerがある場合の安全な分類、画像取得とReader整合性。
3. `site_adapters/kadocomi/`: full/incremental、無料期限の更新、表示位置と全話リストの検証。
4. `site_adapters/younganimal/`: 作品・話ID境界、一覧展開・画像の完全性・失敗時停止。
5. `discovery/service.py`、`batch/planner.py`、`batch/executor.py`、`core`、`cli.py`: 既存共通フローのまま使う。

既存shared Crawler ChromeへCDPで接続し、操作はPlaywright `Page` / `Locator` を使う。AdapterはChrome起動・profile/CDP設定を担当しない。ヤンマガ固有の解析・状態遷移は `src/screenshot_crawler/site_adapters/yanmaga/` に閉じ込める。Policyは `src/screenshot_crawler/site_policies/yanmaga.py`。UI/API、画像配信、URLのstable identity、Viewer形式は **未実測** であり、他サイトと同じ前提を導入しない。

### 複数agentの運用

`docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md`に従う。
- Lead/root: `gpt-6.1-sol` / `xhigh`。判断・フェーズ契約・進捗/レビューゲート・サインオフ。
- Explorer: `site_adapter_explorer` / `gpt-6-luna` / `xhigh`。read-onlyの調査、根拠/不明点の分離。
- Implementer: `site_adapter_implementer` / `gpt-6-luna` / `xhigh`。唯一のproduction writer、実装・テスト・note。
- Reviewer: `site_adapter_reviewer` / `gpt-6.1-sol` / `high`。変更差分・仕様不一致・バグ・回帰・セキュリティを独立審査。
- Tester: `site_adapter_tester` / `gpt-6-luna` / `high`。必要な独立E2E・画像/Manifest/ZIP監査、production書換え禁止。

実行開始時にagent modelと設定が利用可能か確認し、未対応なら勝手に置換しない。共有Chrome/CDPのoperatorは同時に一人だけ。Leadは各Phaseごとに変更許容範囲、着手可能な根拠、禁止事項、テスト、受け入れ条件、checkpointを明示する。ReviewerのBLOCKING 0を確認して次へ進む。

## 3. 破ってはいけない実装契約

1. **無料性の正の根拠。** 各話に紐づく赤字無料の真正なDOM/API/公開状態を確認。`無料`の部分文字列、外側の作品「初回無料」バッジ、ボタンの色だけ、点数の有無、偶然Viewerが開くこと、既に読めるGrantは十分な証拠ではない。競合・欠損時は`unknown`/SKIP。
2. **消費ゼロ。** `quota`/`paid`/`owned`/`unknown`をReader取得対象にしない。Ticket/初回無料/ポイントボタン・確認ダイアログをクリックせず、UIが誤った消費操作へ進む場合はその前に停止する。`direct`のみ。
3. **Batch再検証。** Catalog時点の`free`は古くなりうる。Reader入場前に同じ作品/話の現在の無条件無料を検証し、不成立なら対象話だけスキップ。検証のために別話を開いて権利を探さない。読み取り専用の作品一覧preflightは現サイトの構造上必要なら許容するが、全話Viewer探査や自動Discovery再実行は行わない。
4. **Identity。** HTTPS hostと正規work URL/episode URL、redirect、canonical、work slug/IDとepisode ID、読者画面の話IDを厳格に照合。`?reading=...`や`/comics/<slug>/<id>`の役割はPhase 01で確認し、URL値を未検証のIDに流用しない。`source.external_id`は少なくともwork内で一意、跨作品衝突を安全に避ける。話数文字列はidentityにしない。
5. **順序・完全性。** 「もっと見る」等をすべて展開/ページングし、重複・終端・件数と順序を検証してからrecordsをyieldする。部分fullが完走したことにして欠落話を`available=false`に一括変更しない。位置を採番するなら作品全体の古い順1基準で、途中の番外編・前後編も保持する。範囲Discoveryはglobal positionが立証できる場合だけ。
6. **時刻。** 明示的な無料期限が観測された場合にだけ`free_until`に保存し、expiredをBatchから除外する。観測した期限無しを保存する場合は古い期限を正しくクリアする。時刻・タイムゾーン・無料期限・日次上限を捏造しない。`available`と`access_mode`は別概念。
7. **画像の忠実性。** 正規に表示できる本文に限定。対応する原本配信バイト（JPEG/WebP/PNG）をpage-boundで証明できるなら優先。次に再構成が正規の表示を超えないと確認できる描画画素、Canvas/Locator、最後にScreenshot。取得元の真偽、dimensions、ページ順、lossless再エンコード、fallback理由を検証。「原本」とは出版社マスター画像の保証ではない。著作権保護・権限制御を回避しない。
8. **Viewer lifecycle。** 先頭への巻戻し、lazy-loading、単頁/見開き（RTL）、広告/宣伝の排除、same-content、識別子drift、最終本文→END/NEXT_CONTENTをpositiveに検証。固定sleepだけでENDを推測しない。ページ欠損・重複・他話混入・未証明ENDは失敗。
9. **状態保護。** 正常END、Manifest/ZIP成立後だけArtifactとCompleted更新。失敗はpending、保存済み成果物は壊さない。再DiscoveryでもCompleted/Artifact履歴を維持。`max_pages`/`max_same_content`/bounded retry/AccessGuard/pacingを維持する。
10. **作業隔離。** `feat/yanmaga-adapter`を使用。実サイト検証は専用`output/yanmaga_experiment/`以下のWatchlist/SQLite/output/library、他の既存ファイルを上書きしない。Cookie、認証情報、署名URL、漫画本文画像、機微な生ログ、元HTML/ネットワーク本文をGitにコミットしない。site terms・アクセス負荷制限を守る。

## 4. 実行フェーズとゲート

| Phase | 実行契約 | レビューゲート |
| --- | --- | --- |
| [01 Site Probe](01-site-probe/README.md) | work/episode identity、無料バッジ、一覧展開、通常無料の制約、Reader/画像/ENDの非消費確認 | FREE判定・Readerへ安全に入れる正の証拠 |
| [02 Discovery](02-discovery/README.md) | full/incremental、scope/position、Catalog、期限・アクセス同期 | 不完全一覧・誤free・ID衝突を起こさない |
| [03 Viewer/Capture](03-viewer-capture/README.md) | 同じ話のfresh無料preflight、ページ順、source-native優先、END | 欠落・重複・有料操作・他話混入なし |
| [04 Free Batch](04-batch/README.md) | direct-only Policy、CLI registries、既存Batch/ZIP/Completed | `free`以外は候補外、失敗はpending |
| [05 E2E](05-e2e/README.md) | 独立したCLI E2E、画像/Manifest/ZIP/Catalog再監査 | Reviewer BLOCKING 0 + live証拠またはNOT VERIFIED |

Phase 01で対応可能な無料話の根拠が得られたら、Phase 02-05まで自律的に進める。フェーズごとに研究だけして終了せず、真の外部blockerだけ`BLOCKED/NOT VERIFIED`として報告する。今回対象外の資源機能が分からないことはv1のblockerではない。

## 5. 変更範囲・成果物

想定ファイル:
- `src/screenshot_crawler/site_adapters/yanmaga/{__init__.py,discovery.py,adapter.py,access.py,README.md}`、必要性が観測された場合だけ`native_capture.py`など小さなhelper。
- `src/screenshot_crawler/site_policies/yanmaga.py`、`site_policies/__init__.py`、`src/screenshot_crawler/cli.py`（標準の4つのregistryを登録）。
- 必要な`tests/unit/test_yanmaga_*.py`、`tests/integration/test_yanmaga_*.py`、関連CLI/Planner/Executor tests。
- `note/<next>_yanmaga.md`（現状の最大番号が13なら`note/14_yanmaga.md`）。現行実装ノートはPhase 02-04の実装と同じ変更で更新する。共通処理を変更した場合に限り`note/00_core.md`と関連authorityを同期。
- `runbooks/yanmaga-free/PROGRESS.md`、実測済みの根拠/制約/テスト結果を記録。必要な`research/`はサニタイズ済みの非著作物だけ。
- `config.yaml`や新たな独自APIクライアント/汎用DSLは必要性が確認された場合だけ。

**Definition of Done:** 既存通常CLIで少なくとも1件の本当に無条件無料の公開話を、full/incremental Discovery→Catalog→free-only Batch plan→Batch run→全本文Capture→positive END→Manifest/ZIP→Completedへ到達し、独立Testerが内容・順序・ZIP/Artifact整合性を確認。非無料を不正に実行せず、再Discoveryで完了履歴を保護し、Reviewer BLOCKING 0。可能なら異なるレイアウトの2件目を追加検証。正常にlive検証できない場合は、Unit/Integration PASSを全体Doneに昇格しない。

## 6. 参考一次情報（2026-10-20に公開ページ/検索結果で確認した範囲）

- https://yanmaga.jp/comics/MADE_IN_YAMATO — 同じ作品に`70 無料`と`初回無料`が混在し、「もっと見る」と`無料は1日で読める数に限りがあります`の注意書きが存在する（HTML/DOM/API構造は未実測）。
- https://support.yanmaga.jp/hc/ja/articles/360050176114-利用に会員登録は必須ですか — 無料連載漫画は会員登録なしで楽しめるという案内。
- https://yanmaga.jp/columns/articles/7367 — 2026-05-29の公式使い方。初回無料は会員登録の特典として説明される。

これらは無料方式の**存在**の根拠であって、現在のバッジCSS/API、作品ID、Reader実装、ページ寸法、画像形式や実サイトE2Eを証明したものではない。実装のauthorityはPhase 01のサニタイズ済み実測証拠。

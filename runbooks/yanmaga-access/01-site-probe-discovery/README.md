# Stage 01 — 非消費Site Probe / Discoveryの分類拡張

**Status:** NOT STARTED
**前提:** [全体Runbook](../README.md) の確定要件を読む。既存の `runbooks/yanmaga-free/` の正常取得・厳格な一覧照合を基線とする。
**終了条件:** 初回無料・通常無料・待つと無料・コイン/ポイントのみ・既存Grant/不明状態を根拠付き分類し、**本Stageで資源消費0回**。

## 1. 実サイトProbe（まずread-only）

共有Crawler Chrome/CDPのログイン済みと匿名（別profileか安全な既存手段）で、代表作品と代表エピソードを選定。**作品一覧だけから可能な範囲を調べ、チケット/初回無料/有料の開放ボタンは押さない。** アカウント状態を変えるおそれがあるエピソード遷移は実施前に安全性を判断。専用 `output/yanmaga_access_experiment/stage01/` へ匿名化したDOMの最小スナップショット・結果だけ保存し、HTML/通信本文・Cookie・作品画像をGitに保存しない。

最低限確認する観測項目：
1. 会員ログインを**正に確認できる**表示/サイト発行状態。匿名版の `ep.is_logged_in=false` の検証と両立できるか。ログインしたと推測するだけのCookie存在は証拠不足。
2. 作品ページの `.detailv2-episodes` / `.mod-episode-item` と「もっと見る」の保持、IDと順序、`data-is-free` や `js-modal` 等の実態。表示とAPIが矛盾した例も採る。
3. 未使用初回無料の行バッジ、ボタン位置、対象話のURL、表示優先度。初回無料と待つと無料が同一行に同時存在したら、実際に優先される操作を証明できるまで `unknown`。
4. 待つと無料のチャージ完了／チャージ中、作品ごと管理なのか、残時間/閲覧期限のUIまたは第一者情報。回復23hと閲覧権限の有効時間を区別。
5. ポイント/コインのみ、有料/購入CTA、利用済みの初回無料が再表示されない状態、レンタル中などの閲覧可能状態。操作でこれらの変化を**本Stageでは引き起こさない**。
6. 赤字通常無料がログイン済みでも正しく判定できるか。従来の匿名正の証拠と衝突しないこと。
7. 現行 `BatchPlanner` の通常direct候補とquota候補の作品・話数順。旧 `batch_ordering=catalog` のまま期待順が得られるか、`display_position` が必要かをplan fixtureで証明。

結果は `PROGRESS.md` に「観測日時、対象URLの匿名化したID、UI/DOM/第一者アクセス証拠、未確認」を分けて記録。見つからなかった分類は推測で埋めない。テストfixtureは実画面の本文なし・契約に必要な最小DOMに再構成する。

## 2. Discovery実装

実装箇所は `src/screenshot_crawler/site_adapters/yanmaga/discovery.py` とsite専用の必要最小helper。

- **内部観測分類**を作る：例 `public_free` / `first_free` / `wait_free` / `active_grant` / `paid` / `unknown`。DBの列を増やさず、写像は `public_free,first_free→free`、`wait_free→quota`、`paid→paid`。active_grantはサイト表示・直前Catalog状態・Grant期限の根拠を見てsite-ownedの`reconcile_access_mode`等で処理し、根拠不足ならunknown。
- 検証済みの**作品・話IDの完全性、順序、リスト全件確認**を壊さない。既存の匿名赤字 `free` 判定は残し、ログイン時の別の正の証拠を追加する。認証が不確かなら全件freeへ誤分類しない。
- `待つと無料` は回復待ちでもアクセス方式としては `quota`。現時点で使用可能かはBatch直前のlive条件とwork resource stateに委ねる。
- **数値ポイント表示だけ**でpaidにしてはいけない。無条件無料にも数値のキャンペーンバッジが共存する既存実測があるため、唯一の有料CTA/価格種別と無料代替不可を確実に確認して初めてpaid。
- `free_until` は公開無料終了時刻が正に観測できる場合に限る。初回無料の閲覧期限を `free_until` に混ぜない。開放済み閲覧期限は既存 `access_granted_until` の契約で記録できるときだけ保存。`access_granted_until_observed` フラグによる更新・未観測時保持を理解して使用。
- `full` は不完全な一覧で既存アイテムをunavailableにしない。`incremental` と再DiscoverでSource identity、display_position、完成済みArtifact、Work関連付けを維持する。
- Discovery中の初回無料開放/チケット消費/ポイント操作/ログインの自動実行は禁止。

## 3. 必須テスト

`tests/unit/test_yanmaga_discovery.py`、`tests/integration/test_yanmaga_discovery_browser.py` と必要なCatalog/CLI/Policy関連テストを拡張する。観測に応じfixtureを作り、次を網羅。

- 未ログイン赤字無料の従来判定、登録UI、analytics不明・矛盾・subframe・溢れ・古い通信でunknown。
- ログイン済み初回無料=free、通常無料=free、待つと無料=quota、チャージ中=quota、コインのみ=paid、重複/複数モード/矛盾=unknown。
- 同時表示の表示優先度が未実測ならunknown維持。後で観測されれば根拠付きfixtureへ更新。
- grant有効・失効・残時間不明・既存Source mode変更、古いGrantの不正延長なし。
- 全件読み取り、一意ID、順序、続きを開く操作、空・部分リストのfail-closed、full/incremental差分、Completed/Artifact保存。
- 本Stageで消費系UIのクリック・POSTが起きないことをbrowser fixture/spyで検証。
- Planの作品内話順、direct→quota群の相対順をサンプルCatalogでアサート。もし所望のcrawl順と異なる場合は方針を明記し、必要なsite-owned修正のみ行う。

**Gate:** Reviewer BLOCKING 0、Unit/Browser PASS、実サイトで確認できた分類だけproduction有効化。未確認のログイン/バッジ/優先ルールはunknownに残す。`PROGRESS.md` 更新後にStage02へ進む。

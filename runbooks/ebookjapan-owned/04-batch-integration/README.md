# 04 — Owned-only Site Policy / Batch / GUI Integration

Status: **STAGE 04 END+ZIP VERIFIED / STRICT AND INDEPENDENT AUDITS PASSED / REVIEWER B0 ACCEPTED; conditional C capture is now wired to the existing Runner path**. Run 4 remains the accepted 287-page D baseline ZIP with retained manifest. The new public capture path emits C only after complete per-part source ROI proof; the actual-site v5 pilot accepted one Muda 2 cover, while full17 and full Stage 05 E2E remain incomplete. Unsupported or unproven parts use a complete fresh D spread; fatal rights, route, layout, reset, access-guard, and internal failures are not hidden. See `PROGRESS.md` for the pilot evidence and current limits.

## 目的と実装範囲

- `src/screenshot_crawler/site_policies/ebookjapan.py` に小さな `EbookJapanSitePolicy` を追加。
- `src/screenshot_crawler/cli.py` の `_registry()`、`_batch_adapter_registry()`、`_discovery_registry()`、`_batch_policy_registry()` 等、既存の確定した登録経路を使う。
- GUIのサイト選択／URL登録／Full Discover／Batch Plan／Batch Runが`site=ebookjapan`を通ることを確認。新しい専用画面を作らない。GUIの一般既定がincrementalの場合に限りebookjapanでFullを明示し、利用者がincrementalを選べないようにするか理由付きで拒否。
- `site_adapters/ebookjapan/README.md` と最新`note/15_ebookjapan.md`（実際の最新番号に応じ調整）へ運用と取得方式・制限を記載。

## Policy

`EbookJapanSitePolicy` is registered in the CLI Batch policy registry, and the Reader adapter is registered for manual Crawl and Batch. It plans only available owned sources as `direct` with no quota consumption; the adapter revalidates ownership before Reader entry. The current public capture path conditionally emits verified source ROI C for every spread part, using the same Runner and packaging contract; one actual Muda 2 cover pilot passed, but Stage 05 full17 capture remains pending. Unsupported source proof falls back atomically to fresh D. Stage 04 run 4 remains the accepted 287-page D run with strict END and ZIP. Strict audit passed 11 checks, and independent current-ZIP audit plus Reviewer B0 (`6facc89`) were accepted. Repeat Full preserved identities, history, ZIP, and status hash/mtime; repeat Batch created no new runs or artifacts, made no HTTP request, and left the Catalog SHA unchanged. Actual GUI validation on isolated clone `gui/r11` used the real MainWindow/Controller/worker without fakes; it succeeded with 1 skipped, 0 started, 0 HTTP. Tests: 162 passed, 0 skipped (158 warnings); independent validation 35 passed, 0 skipped; Ruff passed. See `PROGRESS.md` for SHAs, audits, and the three earlier failures.

`EbookJapanSitePolicy.site = "ebookjapan"`。

| Source状態 | Batch決定 |
| --- | --- |
| `available=True`、`access_mode=owned`、正の整数`display_position` | `eligible=True, access_strategy=direct, consumes_quota=False` |
| `available=True`、`access_mode=owned`、位置がNULL/不正 | `owned_display_position_invalid`。Full Discoveryで位置が修復されるまで候補外 |
| `available=False` | `unavailable` |
| `paid/free/quota/unknown/rental/grant` その他 | `eligible=False`。silent fallbackしない |
| quota/resource | `available_quota=None`、消費なし、grant-only利用不可 |

`EbookJapanSitePolicy.batch_ordering()`は`display_position`を明示opt-inする。Batch Planは既存Work順と各Work内の初出discovery-key順を保ち、各key block内を正の整数位置昇順に安定sortする。NULL keyも1つのgroupとして初出位置を保ち、位置不明はgroup末尾。`selected_keys`は従来どおり先に適用される。Source IDや`archive_order`から巻順を推測せず、`archive_order`はZIP naming専用である。

`SitePolicy` はCatalogの適格性だけを決める。これが購入済みの**現在の権利確認**を代替してはならない。`BatchExecutor` から通常の`configure_target_identity`と`initialize`/direct-owned入口で同じ巻IDのowned状態を再確認する。

- 登録済みの古いSourceが未購入/権利失効となっていたらBatch候補でも画像へ進まず、安全に失敗しpending/履歴保持。
- 売買・試読・ポイント・クーポン・レンタルCTAをクリックしない。
- 既存のAccessGuard、HTTP throttling、same-content・retry上限、StopOnFirstFailureの動作を維持。
- Manifestの巻URLと実際のViewer IDが食い違うならzip化しない。

## archive_order / renumber（今回の決定）

- Book / Sourceの `order_key`、公式全巻内の `display_position` を正しく保持。未購入巻はCatalogに持ち込まない。
- 単一作品単一キーでは従来の並びと命名、複数サイト/キーで`archive_order`を明示した`work_key`は既存の `build_work_archive_position_plan` を使用。**全キーに重複しない正のarchive_orderが必要**。
- Batch ZIP名が将来の追加購入や統合により変わっても、既存ZIPを自動リネームしない。対象の新規ZIP名が衝突したら事前にstop。必要に応じて `scripts/renumber_archives.py` でdry-run→内容/衝突確認→明示apply。
- 作品間の同一巻・話の自動名寄せ、重複削除、他サイト取得範囲の自動書換えをしない。
- 作品のうち10巻だけOwnedなら、表示順は10というglobal positionでも、統合後のアーカイブ通し番号は1等になり得る。**巻番号とZIP prefixを混同しない**。

## 孤立テストコマンドの形（実行パスはStage 04で確定）

`output/ebookjapan_experiment/` 以下だけで、別Catalog/Watchlist/ZIP libraryを利用:

```powershell
python -m screenshot_crawler.cli watch add --watchlist output/ebookjapan_experiment/watchlist.yaml --key angel-densetsu_ebookjapan --work-key angel-densetsu --site ebookjapan --url "https://ebookjapan.yahoo.co.jp/books/all/134336/" --label "エンジェル伝説"
python -m screenshot_crawler.cli discover --key angel-densetsu_ebookjapan --mode full --watchlist output/ebookjapan_experiment/watchlist.yaml --catalog output/ebookjapan_experiment/catalog.sqlite
python -m screenshot_crawler.cli batch plan --site ebookjapan --catalog output/ebookjapan_experiment/catalog.sqlite --watchlist output/ebookjapan_experiment/watchlist.yaml
python -m screenshot_crawler.cli batch run --site ebookjapan --catalog output/ebookjapan_experiment/catalog.sqlite --watchlist output/ebookjapan_experiment/watchlist.yaml --output-root output/ebookjapan_experiment/batch --library-dir output/ebookjapan_experiment/library --limit 1
```

コマンドは現行CLIの実引数と認証済み共有Chromeを再確認すること。2作品のテストは`--limit 1`から段階的に広げ、稼働Catalogを暗黙に使わない。公式ログインは通常Browser UIで行う。

## テスト / Exit

- Unit: `owned/direct`のみ、available false、quota/resource拒否、stale owned、free表示の誤通過、unknown未購入、無資格Viewer開始禁止。
- Browser/Integration: 単一owned→Core Runner→完全Manifest→ZIP、失敗時のpending、再Batchのcompleted除外、元画像class A/B/C/Dの記録とfallback、一部失敗時のStopOnFirstFailure。
- Naming: 単独10巻の`order_label=10巻`と位置の区別、archive_order統合と複数キーの部分指定拒否、追加購入後のprefix drift warning、renumberは明示操作のみ。
- GUI: 正規入力作品URLでURL登録、作品/サイトの表示、full選択、候補確認、通常Batch実行モニター/結果表示。既存サイトのUIが崩れない。
- Reviewer `BLOCKING=0`、関連test・integration・live結果を`PROGRESS.md`に記録。原画像のClass記録と権利再確認が抜けた状態では完了不可。

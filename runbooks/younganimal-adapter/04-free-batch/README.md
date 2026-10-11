# Phase 04 — 「無料」 direct-only Site Policy / Batch

Status: BLOCKED / NOT IMPLEMENTED. Requires accepted complete Discovery and Phase 03 Viewer/Capture proof; neither gate is complete.
Next: [Wait-free](../05-wait-free/README.md) + [E2E](../06-e2e/README.md)。

## Objective
`無料`を完全Discovery→Catalog→direct-only Batch→Crawl→Manifest/ZIP
まで動作させる。Hanayume R9の簡略化を基本方針とする。

## Exact entry / state
- Site Policyはcurrent Catalogで`available=true`かつ`access_mode=free`の
  sourceをdirect eligibleとし、paid/unknown/waiting/quota/grant/ownedは含めない。
  実サイトでのaccess-state解釈はDiscoveryの観測結果と別。
- **Configured Batchの初回navigateはCatalogのcanonical target episode URL**。
  Work IDはsource external_idから照合し、他話/他作品へredirectしたら停止。
  **毎回series一覧へ往復しない**。URLが正規の直接Viewer入口であること、
  表示権利が新たな消費を伴わないことを実サイトで確認してから採用。
- Manual CrawlはCatalogの確認済み対象を持たないため、
  fresh正規listing/target access preflightを行う独立経路にする。
  `待つと無料`はこのfree pathへ混ぜない。
- Batch直前/Viewer入場の権利が無い場合、チケット・待機・購入への操作へ
  自動フォールバックしない。停止・pending・診断記録。
  過去の`free`を無条件に信用して解放/消費を行うわけではない。
- 標準Executor/Runner/Packager/manifest authorityは変更しない。
  Catalog completed/ArtifactはZIP成功後のみ。
  quota/resourceはfree direct実行で消費・更新しない。

## Files / tests
- `site_policies/younganimal.py`と登録、`cli.py`の四つのregistry、
  site module/README、対応Policy/CLI/Batch/Browser integration tests。
- Unit: free select、nonfree除外、Catalog identity conflict、stale Viewerで停止、
  site間干渉なし、grant/resource mutation 0。
- Integration: synthetic standard Batch（3ページ/END、失敗→pending/no ZIP、
  missing half、redirect、malformed source、Manifest/ZIP整合）。
- Live: 1〜2話で指定Catalogから**series一覧なしで1回の直接Viewer入場**を
  計測し、全本文→END→ZIPを独立監査。
  もしYounganimalの安全なdirect入場が成立しないなら
  site-localな最小preflightへ切り替え、理由/追加network costをPROGRESSへ記録。

Exit: independent Reviewer BLOCKING 0、free E2Eが成功した範囲を明記。
**全体終了ではなくPhase 05へ自律的に進む**。

# Piccomaの小説誤分類修正計画

**PLANNED / NOT IMPLEMENTED。** ユーザー追加依頼の修正計画。本調査では分類コード・通常Catalog・既存ZIP/出力ディレクトリを変更しない。画像取得の性能変更と別の小さい変更として扱う。

## 原因をコードで確認した範囲

1. `site_adapters/piccoma/discovery.py:206` の `DiscoveredItem` は `kind="episode"` を設定するが `genre` を設定しない。episodeは話単位の種類であり、漫画/小説の分類ではない。
2. `discovery/service.py:180` は観測されたgenreを `Catalog.fill_work_metadata` に渡す。入力がNoneなので未知のWork genreを補完できない。
3. `site_adapters/piccoma/adapter.py:1178` の `get_output_metadata()` はtitleだけを返す。手動取得でもgenreが未指定のままになる。
4. BatchはCatalogから既知metadataを渡す（`batch/planner.py:224`、`batch/naming.py`）。Core packagingの `archive_stem()`（`core/packaging.py:58`）はgenre欠落を「小説」で補完する。

したがって**genre未設定の漫画が包装時に小説フォルダへ入る経路**は確認できた。通常Catalogを開いて個々の作品の誤値や既存ファイル位置を実査したものではない。Work自体に「小説」が保存されている場合と、genreがNULLで包装時だけ小説になる場合は区別する。

## 最小修正の設計

- 対応する**漫画であると確認した対象**について、Piccoma Discoveryが `genre="漫画"` を返す。既存のDiscoveryService経由で未知Work metadataを補完する。AdapterからCatalogへ直接writeしない。
- 同じ対応対象について、Piccoma Adapterのoutput metadataにも `genre="漫画"` を返す。手動取得・Catalog genre欠落時の包装を修正する。
- Piccomaというサイト名だけで全作品を漫画に一括変換しない。現在の支持対象の漫画限定条件をauthority/実サイトの種別表示で確認する。漫画限定の根拠が足りなければ、product上の種別を明示的に取得し、小説/不明を区別する。画像canvasが存在するだけを漫画判定の根拠にしない。未確認の種別推定を本番化しない。
- 現行Discovery selector・人工browser fixtureには漫画/小説の種別markerが無く、全対応対象が漫画という契約は現行コードだけでは証明できなかった。**実装前に種別表示のbounded live確認とmarker付きfixtureを追加する**。単に全recordへ定数を足す修正だけでは完了にしない。
- field単位の **explicit Crawl Request > Adapter > packaging fallback** は維持する。Core packagingの小説fallbackや共通BatchへPiccoma分岐を追加しない。
- `Catalog.fill_work_metadata` は既知の値を上書きしない契約を維持する。既存の非NULL誤値は修正対象一覧のdry-runで確認後、明示的なmetadata訂正として別に扱う。再Discoveryだけで全て直ると説明しない。
- 既存ZIP/フォルダの移動・再包装は自動実行しない。必要なら対象・衝突・Catalog参照への影響を確認した独立した移行計画を作る。

## 必要な検証と受け入れ条件

| 境界 | 必要な検証 |
|---|---|
| Piccoma Discovery | 既存 `tests/unit/test_piccoma_discovery.py` を拡張し、確認済み漫画recordのgenre、既存ID/アクセス判定/順序が同じこと。小説/不明を漫画へ誤変換しない |
| Catalog補完 | 一時CatalogでNULL genreの補完、再Discoveryの冪等性、既知explicit genre非上書き、Work/source identity維持 |
| Adapter metadata | 既存 `tests/integration/test_piccoma_adapter_browser.py` で手動取得metadataの漫画genreとtitle、画像capture契約が不変 |
| 包装・Batch | `tests/unit/test_packaging.py` と既存Batch metadata/namingテストでmanual/Batchの漫画パス、explicit優先、他サイトfallback、ZIP membership不変 |
| Live確認 | 対象漫画のproduct種別とfree-onlyを確認。専用Catalog/出力で確認し、通常Catalogや成果物を使わない |

Reviewerによる独立確認、`note/09_piccoma.md` の同期を実装完了条件とする。共有metadata契約を変更する必要が生じた場合だけ `note/00_core.md` と該当authorityを追加確認する。

優先度は高（誤分類の修正）。method4/pacing/JSONの性能計測から独立させ、画像品質の変更を混ぜない。

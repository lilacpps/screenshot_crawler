# Phase 02 — Younganimal full/incremental Discovery

Status: NOT STARTED。Prereq: Phase 01の一覧/identity/無料badgeの実測。
Next: [Viewer/Capture](../03-viewer-capture/README.md)。

## Goal and scope
Watchlistに入力した1話URLからその作品の**全エピソード**を列挙し、
完全性を検証して`DiscoveryService`経由でCatalogへ保存する。
`site: younganimal`、work-scopedなsource identity、native whole-work orderを採用。
「無料」「待つと無料」は**raw labelを区別して分類**し、未確認は`unknown`。
待機前の`待つと無料`を`free`にしない。

## Implementation
- `site_adapters/younganimal/discovery.py`と`access.py`、registration、
  Unit/Playwright fixtures。既存Hanayumeのstrict URL、range enumeration、
  public/history root検証、last-page full bufferingの方式を参考にするが、
  正規URL・DOM ancestry・range/current marker・access labelはYounganimal実測値。
- 同一話IDが異なる作品内で利用されても衝突しないように安定したwork:episode
  external_idを使う（実測でglobal uniqueが証明されてもwork contextは保持）。
- 作品一覧の選んだpublic root以外のhistory/recommendation/access copyを混ぜない。
  重複/矛盾/未知scopeはfail closed。episodeタイトル、作者、全体表示番号は
  観測可能なもののみ採用。
- 全件列挙をboundedに完了し、行数・範囲・唯一性・target含有・orderingを検証してからyield。
  **不完全なfullの結果で既存sourceをunavailableにしない**。
- full/incrementalはサイトの完全集合を前提に、inclusive boundedを
  適用しても**作品全体に対するposition**を保持。
- `無料`の厳密なラベルと正規の閲覧条件を確認し`free`へ。
  `待つと無料`は実測された状態に応じ将来`quota`等の候補だが、
  Phase 05で確定するまでは`unknown`として保存可能。ラベルがないことを「待機済み」と推定しない。
  raw badgeは必要ならsite-local diagnosticsで保持し、Catalog schema変更を先取りしない。

## Tests
- Unit: URL/domain厳密性、canonical redirectとwork mismatch、分割話/同名、
  duplicate/missing rows、range異常、全体position、
  free exact positive / waiting unknown / conflicting badge / auth未知。
- Integration: real Playwright synthetic listing、full/incremental/bounded、loading、
  同一episodeのhistory/related copies、incomplete→Catalog保全。
- Live: 1作品の全range（最古/最新/件数/ID uniqueness）、可能なら別作品、
  現在無料の話と待機表示のcandidateをsample確認、schema/completeの監査。
- Reviewer: 実装差分/データ欠落・誤分類・誤ったposition・他サイト回帰を優先。

Exit: Explorer/Lead evidence + targeted tests、Reviewer BLOCKING 0。
未確認の「待つと無料」はPhase 05へ持ち越し、free Viewerの実装を止めない。

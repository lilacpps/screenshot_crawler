# Stage 00 — 現行契約監査・URL形式matrix / 設計確定

> Status: COMPLETE（2026-11-02、静的監査のみ）。**Stage 01以降は未着手**。production code・実Watchlist/Catalog変更禁止。
> Prerequisite: main READMEを読み、branch/HEAD、既存作業差分を記録する。

成果物: [RESEARCH.md](RESEARCH.md)。11サイトmatrix、現行WorkEditor/保存契約、
採用するResolver連携・pilot・下書き/命名設計、Stage別受入条件と未検証事項を記録した。
新Resolverの実サイト検証は全サイト未実施。7サイトの完全一覧preview未対応を
詳細編集のblockerとして区別し、Stage 01の静的実装を妨げるblockerはないと判断した。

## Objective

1. AGENTS.md、docs/SPEC.md、docs/ARCHITECTURE.md、docs/DISCOVERY_AND_BATCH.md、docs/BOUNDED_DISCOVERY.md、docs/TEST_STRATEGY.md、docs/CODEX_IMPLEMENTATION_GUIDE.md、GUI_README、関連notesと現コード/テストを照合。
2. URL入力の11-site matrixを作る。各siteについて (a) 現行Discovery targetで厳格に受理されるpath/host/query、(b) ユーザーが貼りそうな作品/エピソード/一覧/reader URL、(c) URLだけでwork ID/targetを変換できるか、(d) page/CDP観測が必要か、(e) work-title取得の根拠、(f) unsupported理由・案内文、(g) 既存parse helper・テスト、(h) Live実証の有無を記載。推測をVERIFIEDとしない。
3. 特に次の非対称性を確認: bookwalkerのseries listとproduct、zeblackのchapter/list、kadocomiのwork、younganimal/comicfuzのwork、mangaone/magapoke/jumpplus/comicdays/hanayume/piccomaのepisode/viewer。サイトごとに必要な起点URLはソースとテストで確定する。
4. 現行WorkEditorのWorkDraft/ListPreview/validate_work/preview_edit/save_editとMainWindowのFull連携をトレース。新規・既存Workのscope/ordering、archive_segments、Catalog guard、preview TTL、CAS/fingerprint、existing source所有の変更リスクを記述。
5. UI選択/戻る/再試行/取消/保存の状態図と、共通DTO/責務の最小案を提示。登録前のURL解決とサイト完全一覧取得を分離し、read-only安全境界を明確化。
6. ローマ字変換について候補ライブラリ、読みの曖昧さ、ASCII英語タイトル、collision、依存追加有無を検討。後から人が理解できるkey/work_keyを必須とする。
7. 登録上のセキュリティ上限を確認: allowlisted HTTPS、redirect、hostのなりすまし、外部画像/リンク、認証と権利消費、timeout/件数上限。GUI threadでサイトアクセスを行わない。
8. 新規URL Resolverのpilotを1サイト選定（URL identityからworkへ確定変換でき、既存parserとfixtureで検証可能なものを推奨）。他サイトへの横展開順を提案。

## Required outputs

- 本Runbookと整合する設計メモ: matrix、責務/DTO、画面状態遷移、リスク/未確定、Pilot根拠、各Stageの受入条件・必要テスト。計画ファイルとしてこのStage内に追記または別のRESEARCH.mdを作成し、リンク。
- PROGRESS.mdを更新。実コードと仕様の矛盾・実サイト未検証箇所を明示。
- Stage 01へ進む条件: 既存Discoveryに無理な変更をしないpilotと安全なResolver interfaceが説明できること。

## Hard restrictions / exit

- このStageでGUI/Resolver/Adapterのproduction実装を始めない。Live siteへのアクセスが必要なら必要性と限定Probeを提案し、承認と適切な実行環境がない限り実施しない。
- 既存の運用Watchlist/Catalog/ZIP/Chrome profileを変更せず、課金/閲覧権を消費しない。
- コード変更がなければpytestは必須でない。relevant parser・GUI・Watchlistテストの存在と、Stage 01で実行すべきtargeted群を列挙する。
- 不明点を推測で埋めず、BLOCKERなら次Stageへ進まない。完成した分析と未解決の境界を報告する。

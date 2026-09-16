# Design Decisions

## D-001 Pythonを採用

### 決定
Python 3.12+ + Playwright Pythonを使用する。

### 理由
必要なPlaywright機能を満たし、利用者の習熟度を優先する。

---

## D-002 万能自動判定をv1で目指さない

### 決定
新規サイトはprobeしてSite Adapterを追加する。

### 理由
終了挙動・広告・次コンテンツ遷移がサイトごとに異なり、完全自動化は誤取得リスクが高い。

---

## D-003 CoreとSite Adapterを分離

### 決定
サイト固有ルールをCoreに入れない。

### 理由
サイト追加・修正ごとの回帰を抑える。

---

## D-004 設定ファイルだけで全挙動を表現しない

### 決定
設定ファイルは必要な単純データに限定し、複雑なロジックはPython Adapterに置く。未使用configをauthority扱いしない。

### 理由
独自DSL化と二重authorityを避ける。

---

## D-005 UNKNOWNでは停止

### 決定
不明状態で自動継続しない。

### 理由
別コンテンツ・広告・意図しない画面を大量保存するリスクを抑える。

---

## D-006 Locator / content bufferを優先

### 決定
固定screen cropより本文Locatorを優先する。Canvasでraw PNGを取得できる場合はcontent bufferを利用する。

### 理由
viewer UI混入と画面環境依存を減らす。

---

## D-007 Patternは補助部品

### 決定
Patternを重い継承frameworkにしない。

### 理由
例外が多い領域で抽象化を先行させない。

---

## D-008 Real-site crawlはCDP接続を標準とする

### 決定
現行BookWalker/Manga ONEのcrawl/loginは専用profileで起動した通常ChromeへCDP接続する。

### 理由
login/sessionと通常browser viewer behaviorを維持しやすい。

---

## D-009 Resumeはv1.1では未実装

### 決定
既存の非空run directoryは拒否し、暗黙resumeやmanifest/progress上書きを行わない。

### 理由
不完全なresumeより既存成果物保護を優先する。

---

## D-010 保存dedupeはcapture fingerprintをauthorityとする

### 決定
現行RunnerではSHA-256 capture fingerprintを保存重複判定に使う。ContentIdentityはchange detectionと記録に利用する。

### 理由
実サイトで動作していたBookWalker/Manga ONEの遷移挙動を維持する。identity優先へ変更する場合は実viewerの連続spread等を先に確認する。

---

## D-011 Manifestをpackaging authorityとする

### 決定
ZIP対象はdirectory globではなくmanifest `pages[].file` とする。新規runは非空directoryを拒否し、無関係ファイルを含むsource directoryは丸ごとcleanupしない。

### 理由
古いPNG混入とuser file削除を防ぐ。

---

## D-012 Site固有の終端ヒューリスティックを許容する

### 決定
END判定に全サイト共通の「明示END DOM必須」ルールを置かない。実観測が安定している場合はboundedなsite-specific heuristicをAdapterに置く。

### 理由
Manga ONEでは最終advance後のpage image消失が実動作上の終端signalであり、未確認generic selectorへの置換の方が回帰リスクが高い。

---

## D-013 `note/` を現行実装スナップショットとして同期する

### 決定
仕様・実装・テスト・運用方法を変更した場合、同じ変更の中で対応する `note/` を更新する。

- Core共通変更は `note/00_core.md`
- Site固有変更は対応するsite note
- 共通変更がsite挙動へ影響する場合は両方

noteは履歴ログではなく「現在どう動くか」を詳しく説明する場所とする。履歴はGitと `docs/DECISIONS.md` に残す。

noteはauthority orderではcode/testsより下に置き、上位authorityと競合した場合はnoteを修正する。

### 理由
実装詳細をチャットや過去コミットだけに依存せず、次回作業時に現在の前提・既知の実サイト挙動・運用方法を素早く復元できるようにするため。

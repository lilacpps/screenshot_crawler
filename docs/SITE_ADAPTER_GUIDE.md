# Site Adapter Guide

## 1. 新規サイトで最初に確認するもの

1. 本文は `img` / `canvas` / CSS background / その他のどれか
2. 1画面に1ページかspreadか
3. page number / page idがあるか
4. content / work / episode / chapter IDがURLやDOMにあるか
5. 次ページ操作はbutton / click area / key / swipeのどれか
6. loading中に何が変わるか
7. 広告時に何が変わるか
8. 最終本文後に何が起きるか
9. 次コンテンツへ自動遷移するか
10. 実際に安定して観測できるsignalは何か

## 2. Browser SessionはAdapterの外側

新規siteを追加するとき、専用Chrome launcher/profileを最初から作らない。

標準:

```text
shared Crawler Chrome/profile
    ↑ CDP
Playwright Page
    ↓
Site Adapter
```

AdapterはPlaywright `Page` / `Locator` を受け取り、site固有logicだけを持つ。

Adapterから以下を行わない。

- Chrome launch
- profile directory選択
- CDP endpoint解決
- `connect_over_cdp()`
- BrowserContext lifecycle管理

site-specific endpoint/profileが本当に必要かは、共通Crawler Chromeで問題が確認されてから判断する。

## 3. Playwrightを標準操作APIとする

CDP接続後も通常のbrowser操作はPlaywrightで行う。

- `page.goto()`
- `page.locator()`
- `locator.click()`
- keyboard / mouse
- `wait_for_*`
- `evaluate()`
- screenshot / canvas capture

Raw CDP ProtocolはPlaywrightで実現できない機能に限る。必要ならCore/Browser Session側helperへ隔離し、Adapterへ低レベルprotocol操作を広げない。

## 4. Capture

本文そのものを取得できるtargetを優先する。

```text
img Locator
→ canvas Locator / raw canvas PNG
→ viewer Locator
→ 明示clip
```

spreadならAdapterが複数targetを読書順で返してよい。

## 5. Identityとページ変更

Identity候補:

- page number / page id
- img src
- content-specific DOM id
- background-image URL
- canvas/capture fingerprint

固定sleepだけに依存せず、bounded waitで安定を確認する。

ただし現行Coreの保存dedupeはcapture fingerprint authorityであり、Adapter identityは主にchange detection / manifest / context補助に使われる。

## 6. 終了判定

最終ページ後はサイトごとに異なる。

```text
最終本文 → END screen
最終本文 → 広告 → END
最終本文 → 広告 → NEXT_CONTENT
最終本文 → NEXT_CONTENT
最終本文 → page images disappear
```

開始時ContentContextを保持し、strong contextが変われば `NEXT_CONTENT` とするのは強いsignal。

ENDについて「明示DOMが必須」と一般化しない。実サイトで安定して確認済みのbounded heuristicはAdapterに置いてよい。

既存AdapterのENDロジックを変更する前にsite README / site noteのlive observationsを読む。

## 7. Authentication

Browser Sessionとlogin DOM logicを分ける。

共通層:

- Chrome profile
- CDP connection
- Page作成

site固有層:

- login URL
- email/password field
- submit
- success/failure判定

login後のsessionはChrome profileへ保存させる。site別storage-state JSONを標準にしない。

CAPTCHA / MFAを自動突破しない。

## 8. README / noteに残すこと

- Viewer type
- Capture target
- Spread / order
- Navigation
- Page change detection
- Content identity
- Content context
- Ad detection
- End detection
- NEXT_CONTENT
- Login DOM logic（存在する場合）
- Browser Sessionでsite-specific overrideが必要か
- Known limitations
- Live verification / Last verified

site固有overrideがない場合、「共通Crawler Chromeを利用」とだけ記載し、launcher/profileの重複説明を増やさない。

## 9. config.yamlとPython

`config.yaml` は必須ではない。

設定ファイル向き:

- 実際にloaderが読み込む単純selector
- viewport
- timeout
- 単純な文字列・数値

Python向き:

- 複合条件
- 状態遷移
- 特殊click
- 複数signalの優先順位
- SPA固有判定

**使われていないYAMLをPython実装と並べて二重authorityにしない。** 現行real adaptersではPython実装がauthority。

## 10. Patternへ昇格する条件

以下を満たす場合だけ検討する。

- 2サイト以上でほぼ同じ処理
- site-specific値を素直な引数にできる
- Coreに入れるほど普遍ではない

1サイトだけの都合ならAdapterに置く。

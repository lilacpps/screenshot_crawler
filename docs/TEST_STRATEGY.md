# Test Strategy

## 1. 目的

Webサイト依存コードは壊れやすい。Coreの回帰とSite Adapterの前提崩壊を分けて検出する。

## 2. Unit Tests

対象:

- PageState
- ContentIdentity比較
- fingerprint
- duplicate guard
- manifest/progress serialization
- max_pages
- retry counter
- Adapter registry

ネットワークや実ブラウザを不要にする。

## 3. Integration Tests

Playwrightを使い、ローカルfixture HTMLで以下を再現する。

- img viewer
- canvas相当
- 広告画面
- END
- NEXT_CONTENT
- 同一ページから変化しないケース

外部サイトに常時依存するCIテストはv1では避ける。

## 4. Site Adapter確認

実サイトで新規Adapterを作る際は最低限:

1. 開始直後
2. 通常3〜5ページ
3. 広告前後
4. 最終本文
5. 最終本文後
6. 次話遷移
7. 読み込みが遅いケース

## 5. 重要な失敗

以下は優先度高:

- 最終本文を保存せず終了
- 広告を本文として保存
- 次話を保存
- 同一ページを大量保存
- UNKNOWNなのに進行
- Coreにサイト固有分岐が混入

## 6. Fixture方針

`tests/fixtures/` にサイトからコピーした実コンテンツを安易に保存しない。

必要なら最小限の人工HTMLを作り、挙動だけ再現する。

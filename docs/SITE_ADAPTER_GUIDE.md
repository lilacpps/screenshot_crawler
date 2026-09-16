# Site Adapter Guide

## 1. 新規サイトで最初に見るもの

DOMをいきなり書き換える前に、以下を確認する。

1. 本文は `<img>` か
2. `<canvas>` か
3. CSS `background-image` か
4. Viewer全体しか取れないか
5. ページ番号表示があるか
6. episode/chapter/content IDがDOMまたはURLにあるか
7. 次ページ操作はbutton / click area / key / swipeのどれか
8. 広告時に何が変わるか
9. 最終ページ後に何が表示されるか
10. 次話へ自動遷移するか

## 2. 判定優先順位

### CONTENT判定

DOMの意味情報を優先する。

```text
content id / episode id
→ page number
→ known selector
→ img src
→ background-image
→ canvas fingerprint
→ screenshot fingerprint
```

背景色だけの判定は最後の手段。

### ページ変更判定

固定sleepだけに依存しない。

優先:

- page number変化
- src変化
- background-image変化
- content/page id変化
- canvas/capture fingerprint変化

## 3. 最終ページ

「Next disabled」だけを唯一の条件にしない。

サイトによって:

```text
最終本文 → 終了画面
最終本文 → 広告 → 終了画面
最終本文 → 広告 → 次話
最終本文 → 次話
```

があり得る。

開始時 `ContentContext` を保持し、現在contextが変わったら `NEXT_CONTENT` とするのが強い。

## 4. READMEに残すこと

各Site AdapterのREADMEには最低限以下を書く。

- Viewer type
- Capture target
- Navigation
- Page change detection
- Content identity
- Content context
- Ad detection
- End detection
- 次話遷移
- Known limitations
- Last verified

## 5. config.yamlとPythonの境界

YAML向き:

- selector
- viewport
- timeout
- max_pages override
- 単純な文字列・数値

Python向き:

- 複合条件
- 状態遷移
- 特殊クリック
- 複数selectorの優先順位
- SPA固有判定

## 6. Patternへ昇格する条件

以下を満たす場合だけ検討する。

- 2サイト以上でほぼ同じ処理
- サイト固有selectorを引数化できる
- Coreに入れるほど普遍ではない

1サイトだけの都合ならAdapterに置く。

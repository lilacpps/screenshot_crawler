# note/ maintenance rule

`note/` は、現在の実装を詳しく説明するための **current implementation snapshot** です。

過去の会話や作業履歴を保存する場所ではありません。各noteを読めば、「今のコードがどう動くか」「どのsignalを使うか」「どこまで実サイト確認済みか」「既知の制約は何か」が分かる状態を維持します。

## Authority

noteのauthority順位は上位ではありません。

1. `docs/SPEC.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DECISIONS.md`
4. `docs/CODEX_IMPLEMENTATION_GUIDE.md`
5. code / tests
6. Site Adapter README / probe
7. `note/`

noteと上位authorityまたはcode/testsが食い違う場合、noteを現行状態へ修正します。

## File mapping

- `00_core.md`: Core / Runner / browser / output / packaging / diagnostics / resume /共通安全装置
- `01_bookwalker.md`: BookWalker固有の観測・Adapter・login・capture・終端
- `02_mangaone.md`: Manga ONE固有の観測・Adapter・login・capture・終端
- 新規site追加時: `03_xxx.md` のように対応noteを追加

## Mandatory synchronization

仕様・実装・テスト・運用方法を変更した場合、**同じ変更の中で対応noteを更新することを必須**とします。

- Core共通変更 → `00_core.md`
- Site Adapter固有変更 → 対応site note
- Core変更が特定siteの挙動へ影響 → Core note + site note
- CLI/login/browser起動方法変更 → Core note + 影響site note
- output naming / packaging変更 → Core note + 影響site note

noteを更新しない場合は、「ユーザー向け文言のみ」「コメントのみ」など、現行挙動に影響しない理由を作業報告へ明記します。

## What to record

最低限、該当するものを記載します。

- 目的 / scope
- 現在の処理フロー
- 主要class / module / entry point
- PageState / identity / context / fingerprintの扱い
- capture target / spread order
- navigation / wait / retry / timeout
- END / NEXT_CONTENT / UNKNOWN判定
- login / CDP / profile / env
- output / manifest / progress / ZIP / cleanup
- safety guard
- tests
- live verification
- known limitations / 未確認事項

site noteでは、selectorやDOM signalのような実装上重要な詳細も残します。

## Current state, not append-only history

古い仕様を本文に残したまま「現在は違う」と末尾だけに追記しないでください。

実装が変わったら、古い説明を置換して本文全体を現行状態にします。過去の判断経緯を残す必要がある場合は、以下を使います。

- `docs/DECISIONS.md`
- Git commit history
- issue / PR

## Secrets

以下はnoteへ記録しません。

- password
- Cookie
- storage state
- access token
- session secret
- 個人用認証情報

`.env` のキー名やダミー例は記載して構いませんが、実値は書きません。

## Completion check

変更作業の完了前に確認します。

1. code/testsとnoteが一致している
2. 現行CLI例が実際に有効
3. 実サイト確認済みと未確認を区別している
4. 固定の古いtest件数を「現在値」として残していない
5. secretsを含まない

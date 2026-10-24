# Phase 03 — Action別の信頼できる進捗・終了サマリ

## Starting evidence
- Phase01でDiscoverの観測値がEventへ出る。Phase02で常設Monitorにjob_idを選択できる。
- 既存 `batch/metrics.py` は`batch_summary`と `grant_result`、 `jobs.py` はTask/Eventとjob terminal stateを保持。

## Objective
1. Qtなしの`JobResultPresenter`（名前は実装者裁量）を追加。入力は`JobStore`のJob/Task/Eventsと、`metrics_started`/`batch_finished`が示す正当なmetricsファイル。表示用 immutable DTOを返し、GUI/履歴で共用する。
2. 共通: action/mode, state, site/task別 result, observed attempts, duration, success/failure/skip/unknownとcritical warnings。現在処理中のsite/key/itemを構造化Eventから、欠落は不明とする。job stateを集計だけで成功へ上書きしない。
3. Discover: 対象key成功/失敗/未実行/disabled skip、観測話数・新規・既知・complete/stopped_reason、warning一覧、途中停止の値の部分性を表示。複数サイト/keysで確定分だけ集計し、完了が観測されないtargetは不明/未実行として扱う。
4. Batch: site別`batch_summary`の開始/完了/失敗/計画スキップ/実行スキップ・elapsed・stop_reasonとmetrics path。job_tasks counters（進行表示用）とmetrics counters（結果用）を重複加算しない。候補0件正常終了の意味を保持し、成果物件数とattempt数を混同しない。
5. Grant-only: `grant_result`のwork label × resource、試行/未実行/使用確認/unknown、理由をゼブラック型の作品別表で表示。`resource_consumed: true|false|null`をそのまま扱い、真でも後処理失敗は別警告。レポートがない直接grant経路は`grant_confirmed`等の観測事実からのみ最小限表示、coverage不足なら「情報なし」と明示。
6. `問題のみ`: 原因・site/key/item/source/resourceと、失敗/blocked/warning/消費不明を表示。unknownは再実行や非消費と同一視しない。
7. 数量不明のlive deferred/replanは割合表示しない。finish event欠落・Metrics partial JSONLは確定サマリを偽造しない。

## Constraints
- Log raw textの解析で数値を計算しない。新規イベントは最小限で、Management DB schema変更を避ける。Metricsは既存レコード形式を優先。
- DB/metricsが読み取れない時も既存ジョブのterminal stateを変えず「集計不可」を出す。安全性の異常をゼロ件やsuccessへ変換しない。
- 作品ごとの新たな名寄せ・サイト別クローラ改修は禁止。

## Tests
- CLI-Discover parity、多site一部失敗、disabled、途中incomplete、warnings、candidate startedだがfinish欠落。
- Batch: no_candidates、planned skipとexecution skipが混ざる、multi-site success+failed、missing/partial metrics、後段未実行、long metrics、HTTP countersと重複なし。
- Grant: true/false/unknown、work×resource複数、work ticket後処理失敗、duplicate`grant_result`、replan、not_started、同一workの別Resource、非自明なunknown。
- Worker interruption/crash、cancel/force stopで結果が安全側、Qt-free reducer testsとQt表示テスト。

## Acceptance / Exit
- Action別にCUIより情報不足にならず、サイト/作品レベルの結果と次に確認すべき異常が明確。すべての数値にobserved sourceがある。
- `PROGRESS.md`へ失敗/中断ケースのエビデンスを書いたらPhase04へ。

# BookWalker research scripts

BookWalker専用の診断・Probe・圧縮比較・capture timing分析を置く。
通常運用のscriptは `scripts/`、調査手段自体のtestは
`tests/research/test_*bookwalker*.py` に置く。

repository rootから、例えば次のように実行する。

```powershell
python poc/bookwalker/probe_bookwalker_jpeg_delivery.py --help
python poc/bookwalker/analyze_bookwalker_capture_timing.py --help
```

`diagnose_*` はviewer/sourceの診断、`probe_*` はdelivery/変換の調査、
`poc_*` はローカル成果物からの再構成実験、`benchmark_*` は画像形式の比較、
`analyze_*` は保存済みtimingの集計に使う。各scriptの `--help` とdocstringを
参照する。live probeはshared browserで同時に一つだけ操作し、
`runbooks/bookwalker-source-native/README.md` の対象stageの制約に従う。
ファイルの移動に伴う実サイト操作やcapture policyの変更は行っていない。

`scripts/restore_bookwalker_quota.py` は調査用ではなく、当日のlocal quotaを
1枠戻す運用scriptとして残している。

# 6. トラブルと保守

## 症状 → 原因 → 直し方

| 症状 | 原因 | 直し方 |
|---|---|---|
| `unknown producer` | `producer_id` が登録されていない(アダプタが import されていない) | `ingest/run_scan.py` で、アダプタのモジュールを import しているか確認 |
| `target path does not exist` | フォルダが無い・ファイルを渡した | 存在するディレクトリを渡す |
| `no successful scan_run found` | 成功したスキャンがまだ無い | 先に `run_scan` を成功させる(失敗した回は `failed` で残る) |
| GUI で **403**「このHostでは…」 | `127.0.0.1`・`localhost` 以外の名前で開いている | `INSIGHT_ALLOWED_HOSTS` に足す |
| GUI の POST が 403(Origin) | 別のポート・別のサイトのページから送っている | 同じ URL(Host・ポート)で開く |
| CI が終了コード `2` で落ちる | **fail の不具合があった**、または**実行時エラー**(両方とも `2`) | `stderr` の `error:` を見る。区別が要るなら、下の既知の問題 3 |
| 前に直した不具合が、また open | 再発(同じ行が open に戻る) | 仕様。`first_seen` は最初のまま([学習資料 3](03-internals.md)) |
| 他の入力の不具合が、解消にならない | 仕様(再評価していないものは閉じない) | その入力を、もう一度スキャンして `run_checks` |
| ルールを直したのに反映されない | YAML の構文・必須キー(`rule_id`・`module`)の誤り | GUI の保存時のエラー、または `python -m rules.run_checks` のエラーを見る |
| スキャンの進みが消えた | ジョブの状態は**メモリ**(再起動で消える) | 結果は DB に残っている(`/runs/<id>`) |

## 既知の問題(コードは変えていない。直すときの手がかり)

講義の作成中に、コードを読んで・動かして見つけたものです。

### 1. 不具合の並びが、重大度順にならない

`fetch_defect_records` は `ORDER BY severity DESC` で、重大度が**文字列**(`'fail'`・`'warn'`・`'info'`)なので、辞書順(`warn` > `info` > `fail`)に並び、**fail が最後**になります。

```python
# 実行できる
from core import db

conn = db.connect(":memory:")
run_id = db.start_scan_run(conn, "fs_scan", "demo", "2026-11-01T00:00:00+00:00")
for asset, severity in [("a.png", "info"), ("b.png", "warn"), ("c.png", "fail")]:
    db.upsert_defect_record(conn, asset, "naming", severity, "m", None, run_id)

print("今の並び     :", [row["severity"] for row in db.fetch_defect_records(conn)])
rank = {"fail": 0, "warn": 1, "info": 2}
print("あるべき並び :", sorted((row["severity"] for row in db.fetch_defect_records(conn)), key=rank.get))
```

```text
# 出力
今の並び     : ['warn', 'info', 'fail']
あるべき並び : ['fail', 'warn', 'info']
```

**直す案**: SQL を `ORDER BY CASE severity WHEN 'fail' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END, asset_id` にする(または `SEVERITY_RANK` で並べ替える)。画面の一覧・CSV・Webhook の文面に影響する。

### 2. ルール YAML の `module` を検査しない(任意のモジュールを import できる)

GUI の編集(`/rules/<file>/edit`)の検査は「YAML として読める・`rule_id` と `module` がある」だけ。エンジンは `module` を `importlib.import_module` する。GUI は**認証なし**。`params.pattern` も `re.compile` されるので、ReDoS の余地がある。**直す案**: `module` を `rules.` で始まるものに限る(保存時と読み込み時の**両方**)。パターンの長さの上限。(講義[第 2 回](../lecture/02-rules.md))

### 3. 終了コード `2` が、fail 検出と実行時エラーの両方

CI で、不具合による失敗と、ツールの故障を区別できない。**直す案**: 実行時エラーは別の終了コード(`3` など)にする。

### 4. `--fail-on info` は、info だけのとき `0`

`max_rank == 0` の扱いのため。意図通りかは未確認。

### 5. 再発すると、履歴が書き換わる

同じ行が open に戻り、`resolved_run_id` が `NULL` になる。`open_defect_count_over_time` は、直っていた期間も open と数える。**直す案**: 開閉の区間を持つ表(`defect_events`)。

### 6. その他の制約

- `defect_records` は `UNIQUE(asset_id, rule_id)`: **入力(producer)が違っても、同じ `asset_id` は 1 行**にまとまる。
- 孤立アセットの判定は**名前の文字列照合**(Unity の GUID 参照は見えない)。
- 前回との差は、**サイズと更新日時だけ**(中身の変更は検出しない)。
- z スコアは、n ≤ 4 では外れ値を検出できず、外れ値が複数あるとマスキングされる(IQR を選ぶ)。
- `check_results.value` は TEXT(数値集計は、読み出して `float()`)。
- GUI は、**スキャン対象のパスを、フォームから受け取る**(存在するディレクトリなら、どこでも走査できる)。ローカル専用の前提。

## 定期の保守

| いつ | 何を |
|---|---|
| 毎回の変更 | `pytest -q` と `python tools/check_docs.py` |
| 月 1 回 | 依存の更新(`Flask`・`openpyxl`・`PyYAML`)→ テスト |
| 月 1 回 | `insight.db` の**大きさ**(追記専用なので、増え続ける。古いスキャンを消す仕組みは**無い**) |
| ルールを変えたとき | しきい値・正規表現を、固定の入力でテストしてから、本番のスキャンへ |
| CI | Webhook の URL(シークレット)の有効期限・送信先の変更 |
| 関数を直したとき | `python tools/check_docs.py --update` で、文書の引用・出力を作り直し、**説明が合っているか**を読む |

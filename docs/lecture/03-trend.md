# 第 3 回 集計: 外れ値・分布・前回との差・推移

> 所要時間の目安: 3.5 時間 / 前提: 第 0〜2 回・平均と標準偏差の知識

## この回のゴール

- **パーセンタイル**(`_percentile`)を、線形補間で計算できる。
- **外れ値**を 2 つの方法(**z スコア**・**IQR**)で見つける仕組みと、それぞれの**癖と限界**を説明できる。
- 前回のスキャンとの**差**(追加・変更・削除)を、集合の演算で求める仕組みを説明できる。
- **時系列の推移**(「その時点で未解消だった件数」)の意味と、**再発があると狂う**限界を説明できる。

## 1. 集計は、「SELECT して、値を返す」だけ

`trend/aggregations.py` の関数は、**DB から読んで、ふつうの値(辞書・リスト)を返すだけ**です。描画(グラフ)・新しいテーブルの作成は、**しません**。

- 単体でテストしやすい(DB の接続だけあればよい)。
- CLI・Excel・HTML・GUI が、**同じ関数**を使い回せる(**計算と表示の分離**)。

## 2. パーセンタイル(線形補間)

```python
# 引用: trend/aggregations.py::_percentile
def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)
```

並べた値の「**p%の位置**」にある値です。位置 `k = (件数 − 1) × p/100` が**小数**なら、隣り合う 2 つの値の間を**直線で補間**します(`f` = 下の整数・`c` = 上の整数)。

```python
# 実行できる
from trend.aggregations import _percentile

values = [10, 20, 30, 40, 50]
for pct in (0, 25, 50, 75, 90, 100):
    print(f"p{pct:<3} = {_percentile(values, pct)}")
print("空のとき       :", _percentile([], 50))
print("1 件のとき     :", _percentile([7], 90))
print("偶数件の中央値 :", _percentile([1, 2, 3, 4], 50), "(2 と 3 の間 = 2.5)")
```

```text
# 出力
p0   = 10.0
p25  = 20.0
p50  = 30.0
p75  = 40.0
p90  = 46.0
p100 = 50
空のとき       : 0.0
1 件のとき     : 7
偶数件の中央値 : 2.5 (2 と 3 の間 = 2.5)
```

## 3. 外れ値: 2 つの方法

「平均より**とても重い**アセット」を見つけたい(例: 異様に大きいテクスチャ)。

| 方法 | 基準 | 強み | 弱み |
|---|---|---|---|
| **z スコア** | 平均から、標準偏差の**何倍**離れているか(`|z| ≥ しきい値`、既定 2.0) | 単純・直感的 | **外れ値が平均・標準偏差を引っ張る**。**件数が少ないと、検出できない** |
| **IQR** | 四分位範囲(Q3 − Q1)の**何倍**、四分位の外側か | 外れ値に**強い**(中央に近い値で決まる) | 分布が極端に歪んだ(ロングテール)と、多くを外れ値にする |

```python
# 引用: trend/aggregations.py::_outlier_indices
def _outlier_indices(values: list[float], method: str, threshold: float) -> set[int]:
    """values中で外れ値と判定されるインデックスの集合を返す(z-score または IQR)。
    outliers()とtexture_size_points()の両方がこの1箇所の判定ロジックだけに依存する。
    """
    n = len(values)
    if n == 0:
        return set()
    mean = sum(values) / n

    if method == "zscore":
        variance = sum((v - mean) ** 2 for v in values) / n
        stdev = variance**0.5
        if stdev == 0:
            return set()
        return {i for i, v in enumerate(values) if abs((v - mean) / stdev) >= threshold}

    if method == "iqr":
        sorted_values = sorted(values)
        q1 = _percentile(sorted_values, 25)
        q3 = _percentile(sorted_values, 75)
        iqr = q3 - q1
        lower, upper = q1 - threshold * iqr, q3 + threshold * iqr
        return {i for i, v in enumerate(values) if v < lower or v > upper}

    raise ValueError(f"unknown outlier method: {method}")
```

**z スコアの落とし穴**: n 件のデータで、**z スコアの最大値は `√(n − 1)`** です(数学的な上限)。しきい値 2.0 なら、**n ≤ 4 では、どんな値でも外れ値にならない**。小さいサンプルでは、z スコアは**検出できない**ことがあります。

```python
# 実行できる
from trend.aggregations import _outlier_indices

print("z スコア(しきい値 2.0): 最大の z は √(n−1) まで")
for n in (4, 5, 8):
    values = [1.0] * (n - 1) + [1000.0]          # 1 つだけ極端に大きい
    print(f"  n={n}: 外れ値の番号 = {sorted(_outlier_indices(values, 'zscore', 2.0))}   (√(n−1) = {(n - 1) ** 0.5:.2f})")

# 外れ値が 2 つあると、標準偏差が膨らんで、片方が見逃される(マスキング)
values = [10, 11, 9, 10, 12, 10, 11, 9, 500, 600]
print("2 つの巨大な値(z スコア):", sorted(_outlier_indices(values, "zscore", 2.0)))
print("2 つの巨大な値(IQR)     :", sorted(_outlier_indices(values, "iqr", 1.5)))
```

```text
# 出力
z スコア(しきい値 2.0): 最大の z は √(n−1) まで
  n=4: 外れ値の番号 = []   (√(n−1) = 1.73)
  n=5: 外れ値の番号 = [4]   (√(n−1) = 2.00)
  n=8: 外れ値の番号 = [7]   (√(n−1) = 2.65)
2 つの巨大な値(z スコア): [9]
2 つの巨大な値(IQR)     : [8, 9]
```

**マスキング**: 巨大な値が 2 つ(500 と 600)あると、それ自身が**標準偏差を押し上げ**、z スコアが小さく見えて、**小さいほう(500、番号 8)が外れ値にならない**。IQR は、**四分位**(中央の 50%)で決まるので、極端な値に引っ張られず、**両方を検出できる**。

```python
# 実行できる
from core import db
from core.schema import AssetRecord, CheckResult
from trend.aggregations import outliers

conn = db.connect(":memory:")
run_id = db.start_scan_run(conn, "fs_scan", "demo", "2026-11-01T00:00:00+00:00")
sizes = {"a.png": 120, "b.png": 130, "c.png": 125, "d.png": 118, "e.png": 122, "f.png": 128, "huge.png": 4000}
db.insert_asset_records(conn, run_id, [
    AssetRecord(asset_id=name, asset_type="texture", source_producer="fs_scan", collected_at="t", size_bytes=None, extension=".png",
                last_modified=None, checks={"size_kb": CheckResult(status="info", value=kb)})
    for name, kb in sizes.items()
])
for method, threshold in (("zscore", 2.0), ("iqr", 1.5)):
    found = outliers(conn, run_id, "size_kb", method=method, threshold=threshold)
    print(method, "→", [(o["asset_id"], o["value"]) for o in found])
```

```text
# 出力
zscore → [('huge.png', 4000.0)]
iqr → [('huge.png', 4000.0)]
```

注意: `check_results.value` は**文字列**で保存されている(第 0 回)ので、`outliers` は**読み出して `float()` に直し**、直せないもの(`None`・文字)は**黙って飛ばします**(`except (TypeError, ValueError): continue`)。

## 4. 前回との差(集合の演算)

```python
# 引用: trend/aggregations.py::diff_against_previous
def diff_against_previous(db: sqlite3.Connection, scan_run_id: int) -> dict:
    """新規/変更/削除アセットを直前(同一producer)のscan_runと比較して返す。

    比較対象がない(初回scan)場合は previous_scan_run_id=None かつ全カウント0。
    """
    run_row = db.execute(
        "SELECT source_producer FROM scan_runs WHERE scan_run_id = ?", (scan_run_id,)
    ).fetchone()
    empty = {
        "previous_scan_run_id": None,
        "added_ids": [],
        "changed_ids": [],
        "removed_ids": [],
    }
    if run_row is None:
        return empty

    prev_row = db.execute(
        """
        SELECT scan_run_id FROM scan_runs
        WHERE source_producer = ? AND scan_run_id < ? AND status = 'success'
        ORDER BY scan_run_id DESC LIMIT 1
        """,
        (run_row["source_producer"], scan_run_id),
    ).fetchone()
    if prev_row is None:
        return empty
    previous_scan_run_id = prev_row["scan_run_id"]

    def _snapshot(run_id: int) -> dict[str, tuple]:
        rows = db.execute(
            "SELECT asset_id, size_bytes, last_modified FROM asset_records WHERE scan_run_id = ?",
            (run_id,),
        ).fetchall()
        return {r["asset_id"]: (r["size_bytes"], r["last_modified"]) for r in rows}

    current = _snapshot(scan_run_id)
    previous = _snapshot(previous_scan_run_id)

    added_ids = sorted(set(current) - set(previous))
    removed_ids = sorted(set(previous) - set(current))
    changed_ids = sorted(a for a in (set(current) & set(previous)) if current[a] != previous[a])

    return {
        "previous_scan_run_id": previous_scan_run_id,
        "added_ids": added_ids,
        "changed_ids": changed_ids,
        "removed_ids": removed_ids,
    }
```

1. **同じ入力(producer)**の、**直前の成功したスキャン**を探す(別の入力のスキャンと比べない。失敗した回は除く)。
2. それぞれのスキャンを、`{asset_id: (サイズ, 更新日時)}` の**辞書**にする。
3. **追加** = 今にあって、前に無い。**削除** = 前にあって、今に無い。**変更** = 両方にあって、(サイズ, 更新日時)が**違う**。→ **集合の差・積**(`set(current) - set(previous)` など)。

初回(比べる前回が無い)は、すべて空。

```python
# 実行できる
from core import db
from core.schema import AssetRecord
from trend.aggregations import diff_against_previous

conn = db.connect(":memory:")


def scan(producer, files):
    run_id = db.start_scan_run(conn, producer, "demo", "2026-11-01T00:00:00+00:00")
    db.insert_asset_records(conn, run_id, [
        AssetRecord(asset_id=name, asset_type="texture", source_producer=producer, collected_at="t", size_bytes=size,
                    extension=".png", last_modified=mtime) for name, (size, mtime) in files.items()])
    db.finish_scan_run(conn, run_id, "2026-11-01T00:01:00+00:00", "success")
    return run_id


first = scan("fs_scan", {"a.png": (100, "m1"), "b.png": (200, "m1"), "c.png": (300, "m1")})
other = scan("lqa", {"z.png": (1, "m1")})                                    # 別の入力のスキャン
second = scan("fs_scan", {"a.png": (100, "m1"), "b.png": (250, "m2"), "d.png": (50, "m2")})

print("初回        :", diff_against_previous(conn, first))
print("2 回目(fs_scan):", diff_against_previous(conn, second))
```

```text
# 出力
初回        : {'previous_scan_run_id': None, 'added_ids': [], 'changed_ids': [], 'removed_ids': []}
2 回目(fs_scan): {'previous_scan_run_id': 1, 'added_ids': ['d.png'], 'changed_ids': ['b.png'], 'removed_ids': ['c.png']}
```

`lqa` のスキャンが間にあっても、`fs_scan` の前回(`first`)と比べています。`b.png` は**サイズも更新日時も変わった**ので「変更」、`c.png` は「削除」、`d.png` は「追加」。

> **限界**: 変更の判定は、(サイズ, 更新日時)の**違い**だけ。**中身が変わったが、サイズも日時も同じ**ファイルは、検出できません(ハッシュは見ていない)。

## 5. 時系列の推移と、再発の限界

`open_defect_count_over_time` は、**各スキャンの時点で、まだ解消されていなかった**不具合の数を返します。条件: `first_seen_run_id ≤ その回` かつ (`resolved_run_id` が `NULL` または `> その回`)。

「新規に見つけた数」(単調に増える)でなく、**その時点で実際に残っていた数**なので、**品質の推移**として意味があります。

**限界**: 第 2 回のとおり、**再発した不具合は、同じ行が open に戻り**、`resolved_run_id` が `NULL` に戻ります。すると、**直っていた期間**も「ずっと open だった」ことになります。

```python
# 実行できる
from core import db
from trend.aggregations import open_defect_count_over_time

conn = db.connect(":memory:")
runs = [db.start_scan_run(conn, "fs_scan", "demo", f"2026-11-0{i}T00:00:00+00:00") for i in (1, 2, 3, 4)]
for run_id in runs:
    db.finish_scan_run(conn, run_id, "t", "success")

db.upsert_defect_record(conn, "rock.png", "naming", "warn", "m", None, runs[0])    # 回 1 で見つかる
db.mark_defect_resolved(conn, db.fetch_defect_records(conn)[0]["defect_record_id"], runs[2])   # 回 3 で直る
print("直った時点(回 3 まで):", open_defect_count_over_time(conn))

db.upsert_defect_record(conn, "rock.png", "naming", "warn", "m", None, runs[3])    # 回 4 で再発
print("再発した後           :", open_defect_count_over_time(conn), "← 回 3 は直っていたのに、1 に戻る")
```

```text
# 出力
直った時点(回 3 まで): {'1': 1, '2': 1, '3': 0, '4': 0}
再発した後           : {'1': 1, '2': 1, '3': 1, '4': 1} ← 回 3 は直っていたのに、1 に戻る
```

**直る案**: 不具合の**期間**を、別の表(`defect_events`: 開いた回・閉じた回)に**履歴として**残し、推移はそこから数える。いまの `defect_records` は「現在の状態」の表なので、**過去の状態の再現**には向きません。

## 確認問題

1. 線形補間のパーセンタイルで、`[1, 2, 3, 4]` の p50 が 2.5 になるのは、なぜですか。
2. n = 4 のデータで、z スコア(しきい値 2.0)が、外れ値を 1 つも見つけられないのは、なぜですか。
3. 外れ値が 2 つあるとき、z スコアが片方を見逃し、IQR が両方を見つけられるのは、なぜですか。
4. 前回との差で、「別の入力のスキャン」と比べないのは、なぜですか。
5. 再発のある不具合で、`open_defect_count_over_time` が正確でなくなるのは、なぜですか。

## 解答

1. 位置 `k = (4−1) × 0.5 = 1.5`。値 `[1, 2, 3, 4]` の位置 1(=2)と 2(=3)の**中間**を、線形補間で取る → 2.5。
2. n 件での |z| の最大は `√(n−1)`。n = 4 なら約 1.73 で、しきい値 2.0 に届かない。
3. 巨大な値が、**平均と標準偏差を押し上げて**、自分(と、もう 1 つの外れ値)の z スコアを小さくする(マスキング)。IQR は四分位で決まり、極端な値に引っ張られない。
4. 入力ごとに、アセットの `asset_id`・見る範囲が違う。別の入力と比べると、**全部が「追加・削除」**に見えてしまう。
5. 再発で `resolved_run_id` が `NULL` に戻り、**直っていた期間も open だった**と数えられる。履歴(開閉の区間)を持たないため。

## まとめ

- 集計は「**SELECT して値を返す**」純粋な関数。表示から分離。
- パーセンタイルは**線形補間**。外れ値は **z スコア**(少数・マスキングに弱い)と **IQR**(強い)。
- 前回との差は、同じ入力の直前の成功回との**集合の差・積**(中身の変更は見ない)。
- 推移は「その時点で未解消の件数」。**再発があると、過去が書き換わる**(履歴の表が要る)。
- 次の回は、出力(CI のゲート・マニフェスト・GUI)とテスト・総合演習。

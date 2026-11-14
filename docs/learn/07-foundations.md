# 7. 基礎の補強(言語・設計思想・アルゴリズム・用語)

講義と学習資料の**前提になっている知識**を、ここで補います。「Python・SQL・正規表現・統計の基本」を、**このツールのコードで実際に使われている形**で、動かして確かめます。

## 1. 言語の基礎: ADIS で使う Python

### 1.1 デコレーターで「登録」する(プラグイン)

`@register` は、**クラスを定義した瞬間に、表(`ADAPTER_REGISTRY`)へ入れる**書き方。**新しい取り込み元を足すとき、新しいファイルを 1 つ置くだけ**で済み、既存のコードを直さない(`ingest/adapters/registry.py`)。

```python
# 実行できる
from typing import Protocol


class SourceAdapter(Protocol):
    producer_id: str

    def scan(self, target: str) -> list[str]: ...


REGISTRY: dict[str, SourceAdapter] = {}


def register(adapter_cls):
    instance = adapter_cls()
    REGISTRY[instance.producer_id] = instance        # クラスを作った時点で、表に入る
    return adapter_cls


@register
class FsScan:
    producer_id = "fs_scan"

    def scan(self, target):
        return [f"{target}/a.png", f"{target}/b.fbx"]


@register
class UnityAsset:
    producer_id = "unity"

    def scan(self, target):
        return [f"{target}/Hero.prefab"]


for producer_id, adapter in REGISTRY.items():
    print(producer_id, "→", adapter.scan("Assets"))
```

```text
# 出力
fs_scan → ['Assets/a.png', 'Assets/b.fbx']
unity → ['Assets/Hero.prefab']
```

### 1.2 辞書・集合・内包表記

`dict`(キーから値)・`set`(重複なし)・内包表記は、**集計の道具**。

```python
# 実行できる
from collections import Counter, defaultdict

assets = [("texture", "ok"), ("texture", "fail"), ("model", "ok"), ("texture", "fail"), ("model", "fail")]

by_type = defaultdict(list)
for kind, result in assets:
    by_type[kind].append(result)                    # キーが無ければ、空のリストを作って足す
print({kind: Counter(results) for kind, results in by_type.items()})

failed_kinds = {kind for kind, result in assets if result == "fail"}      # 集合内包: 重複なし
print(sorted(failed_kinds))
```

```text
# 出力
{'texture': Counter({'fail': 2, 'ok': 1}), 'model': Counter({'ok': 1, 'fail': 1})}
['model', 'texture']
```

### 1.3 正規表現(`re`)と YAML

ルール(命名規則)は、**YAML ファイル**に書き、中の `pattern` が**正規表現**。**コードを変えずに、規則を足せる**(データとして持つ)。**`yaml.safe_load` を使う**(`yaml.load` は、任意のコードを実行されうる)。

```python
# 実行できる
import re

import yaml

source = """
rule_id: coding_convention
applies_to: [script]
severity: warn
params:
  pattern: "^[A-Z][A-Za-z0-9]+$"
"""
rule = yaml.safe_load(source)                 # 辞書になる
print(rule["rule_id"], rule["applies_to"], rule["severity"])

pattern = re.compile(rule["params"]["pattern"])
for name in ["PlayerController", "playerController", "Player_Controller", "A1"]:
    print(f"{name:20s}", "合格" if pattern.fullmatch(name) else "違反")
```

```text
# 出力
coding_convention ['script'] warn
PlayerController     合格
playerController     違反
Player_Controller    違反
A1                   合格
```

- `^`…`$` で**全体**に一致させる。`[A-Z]` は大文字 1 文字、`[A-Za-z0-9]+` は英数字の 1 文字以上。**書き方が緩いと、違反を見逃す**(テストで、合格と違反の両方の例を確かめる)。

### 1.4 SQL(`sqlite3`)の集計

```python
# 実行できる
import sqlite3

db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE results (scan_run_id INTEGER, asset_type TEXT, check_id TEXT, value REAL)")
db.executemany(
    "INSERT INTO results VALUES (?, ?, ?, ?)",
    [(1, "texture", "resolution_px", v) for v in (512, 1024, 1024, 2048)] + [(2, "texture", "resolution_px", v) for v in (1024, 4096)],
)
for run, avg, n in db.execute(
    "SELECT scan_run_id, AVG(value), COUNT(*) FROM results WHERE asset_type = 'texture' AND check_id = ? GROUP BY scan_run_id ORDER BY scan_run_id",
    ("resolution_px",),
):
    print(f"スキャン {run}: 平均 {avg:.0f} px  件数 {n}")
```

```text
# 出力
スキャン 1: 平均 1152 px  件数 4
スキャン 2: 平均 2560 px  件数 2
```

## 2. 設計思想

| 原則 | 意味 | ADIS のどこに出るか | 破るとどうなるか |
|---|---|---|---|
| **データとコードを分ける** | 規則は YAML、判定は関数 | `rules/definitions/*.yaml` と `rules/*.py` | 規則を足すたびに、コードを直す |
| **プラグインで足す** | 新しい取り込み元は、新しいファイルだけ | `@register`・`ADAPTER_REGISTRY` | 既存コードの変更で、壊れる範囲が広がる |
| **共通の形に直してから使う** | 取り込み元ごとの違いを、入口で吸収 | `core/schema.py`(`AssetRecord`) | 後ろの処理が、取り込み元ごとに分岐する |
| **判定ロジックを 1 か所に** | 同じ判定を、複数の場所に書かない | `_outlier_indices`(2 つの関数が共有) | 場所ごとに、判定が食い違う |
| **継続して測る(履歴を残す)** | 1 回の点検でなく、推移を見る | スキャンごとの結果を DB に保存・差分 | 悪化に気づけない |
| **安全に読む** | 外部のファイルは、危険なものとして読む | `yaml.safe_load`・検証(`validate_definition_source`) | 任意コードの実行・壊れた規則の混入 |

## 3. 関数・アルゴリズム

| 名前 | 場所 | 何をする | 計算量・注意 |
|---|---|---|---|
| **z-score による外れ値** | `trend/aggregations.py` | `|値 − 平均| / 標準偏差 ≥ しきい値` | O(n)。**外れ値自身が平均・標準偏差を動かす**(隠れる) |
| **IQR による外れ値** | 同上 | 四分位数 Q1・Q3 から、`Q1 − k·IQR` 〜 `Q3 + k·IQR` の外 | O(n log n)(ソート)。**極端な値に強い** |
| **パーセンタイル(線形補間)** | `_percentile` | ソート済みの列の `pct` 位置を、隣との補間で求める | O(1)(ソート済みなら) |
| **ヒストグラム(ビン分け)** | `texture_resolution_histogram` | 値を、区間ごとに数える | O(n) |
| **参照の走査(孤立アセット)** | `orphan_and_individual_fix.py` | どこからも参照されていない物を探す(集合の差) | 参照の総数に比例 |

```python
# 実行できる
from trend.aggregations import _outlier_indices, _percentile

values = [10, 11, 9, 10, 12, 10, 11, 100]           # 100 だけが、飛び離れている
print("z-score(しきい値 2):", sorted(_outlier_indices(values, "zscore", 2.0)))
print("IQR(k=1.5):", sorted(_outlier_indices(values, "iqr", 1.5)))

# z-score の弱点: 外れ値が多いと、標準偏差が膨らんで、隠れる
masked = [10] * 8 + [500, 500]                       # 外れ値が 2 つ(20%)
print("外れ値が複数: z-score(しきい値 3):", sorted(_outlier_indices(masked, "zscore", 3.0)), " IQR(k=1.5):", sorted(_outlier_indices(masked, "iqr", 1.5)))

ordered = sorted(values)
print("中央値(50%):", _percentile(ordered, 50), " 75%:", _percentile(ordered, 75))
```

```text
# 出力
z-score(しきい値 2): [7]
IQR(k=1.5): [7]
外れ値が複数: z-score(しきい値 3): []  IQR(k=1.5): [8, 9]
中央値(50%): 10.5  75%: 11.25
```

- **z-score は「正規分布に近い」データ向き**。**少数の極端な値がある**データは、IQR の方が頑健。**どちらを使うか**は、データの形で決め、しきい値を**設定に出す**(コードに埋め込まない)。

## 4. IT・エンタメの用語の補強

| 用語 | 意味 | ADIS での出番 |
|---|---|---|
| **アセット** | ゲーム・映像で使う素材(テクスチャ・モデル・音・マテリアル・プレハブ) | 点検の対象 |
| **LOD(Level of Detail)** | 遠い物を、粗いモデルに切り替えること | `lod_missing`(LOD が無い) |
| **テクスチャ解像度 / ミップマップ** | 画像の細かさ / 縮小版を重ねて持つ仕組み | `resolution_px` の分布 |
| **マテリアル / シェーダー** | 見た目の定義 / その計算プログラム | `unused_material` |
| **プレハブ / 個別の上書き(override)** | 部品の雛形 / 雛形から個別に変えた設定 | `individual_overrides` |
| **孤立(orphan)アセット** | どこからも使われていない素材 | `orphan_and_individual_fix` |
| **命名規則 / コーディング規則** | 名前・書き方の決まり | `naming_convention` |
| **Unity** | ゲームエンジン。`.meta` と `.prefab` などのファイル構造を持つ | `unity_asset_adapter` |
| **取り込み(ingest)/ アダプタ** | 外のデータを共通の形に直す入口 | `ingest/` |
| **外れ値(outlier)/ 分布 / 四分位数** | 他と飛び離れた値 / 値の散らばり / 4 等分の境目 | `trend/` |
| **スキャン実行(scan run)/ 推移** | 1 回の点検 / 回ごとの変化 | DB の `scan_run_id` |
| **YAML** | 人が読み書きしやすい設定の書式 | ルール定義 |

## 確認問題

1. デコレーター `@register` で、取り込み元を足すとき、既存のコードを直さなくてよいのは、なぜですか。
2. 規則を YAML に置く(コードに書かない)利点は何ですか。
3. z-score で外れ値が見つからない一方、IQR で見つかるのは、どんなデータですか。
4. `yaml.safe_load` を使うのは、なぜですか。

## 解答

1. クラスを定義した時点で、自動で表に登録されるので、呼ぶ側は表を引くだけで済むから。
2. 規則を、コードを変えずに足し・直せる(データとして持つ)。人が読み書きしやすい。
3. 極端な外れ値が多いデータ(標準偏差が膨らむため、z-score では隠れる)。
4. `yaml.load` は、データに仕込まれたコードを実行されうるが、`safe_load` は通常のデータ型だけを読むから。

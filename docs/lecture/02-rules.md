# 第 2 回 YAML で書くルールと、不具合のライフサイクル

> 所要時間の目安: 3.5 時間 / 前提: 第 0〜1 回・正規表現の基本

## この回のゴール

- ルールを **YAML(データ)**で書き、**Python のコードを変えずに**足せる仕組み(動的 import)を説明できる。
- ルールの関数 `evaluate(context, rule_def)` の約束と、1 つのルールを読んで書ける。
- 不具合が、**「新規・継続・解消・再発」**をどう表すか(`first_seen`・`last_seen`・`resolved`)を説明できる。
- **解消の判定を、再評価したアセットだけに限る**理由(偽の「直った」を出さない)を説明できる。
- YAML から**任意のモジュールを import できてしまう**危険を、動かして確かめ、直し方を言える。

## 1. ルールは、データと関数の組

| もの | どこに | 何を決めるか |
|---|---|---|
| **ルールの定義(YAML)** | `rules/definitions/*.yaml` | `rule_id`・**どのモジュールを使うか**(`module`)・対象の種類(`applies_to`)・重大度・**しきい値(`params`)**・メッセージ |
| **ルールの関数** | `rules/*.py` | `evaluate(context, rule_def)` → 不具合のリスト |

```yaml
# rules/definitions/naming_convention.yaml
rule_id: naming_convention
module: rules.naming_convention
applies_to: [texture, model, material]
severity: warn
params:
  pattern: "^(T_|SM_|M_)[A-Za-z0-9_]+$"
message: "命名規則(接頭辞 T_/SM_/M_)に違反しています"
```

**重大度・しきい値・正規表現は、YAML に**あり、Python にはありません。ルールを**足す**には、(関数が既存で足りるなら)**YAML を 1 つ足すだけ**。たとえば「コーディング規約(クラス名は UpperCamelCase)」は、**同じ `naming_convention` モジュール**を、`applies_to: [script]` と別の正規表現で使い回しています。

## 2. エンジン

```python
# 引用: rules/engine.py::run_all_rules
def run_all_rules(
    context: RuleContext, definitions_dir: Path = DEFINITIONS_DIR
) -> list[DefectRecord]:
    defects: list[DefectRecord] = []
    for rule_def in load_rule_definitions(definitions_dir):
        module = importlib.import_module(rule_def["module"])
        defects.extend(module.evaluate(context, rule_def))
    return defects
```

**動的 import**(`importlib.import_module`): YAML の `module` の文字列から、**実行時にモジュールを取り込み**、その `evaluate` を呼ぶ。エンジンは、**どんなルールが有るかを知りません**。「ルールを足してもエンジンは変わらない」(開放閉鎖の原則)。

`RuleContext` は、ルールに渡す**入力**: どのスキャンか・対象フォルダ・アセットの一覧(各アセットは、種類・拡張子・**検査結果の辞書** `checks`)。ルールは**読み取り専用**で、DB を書きません(書くのは `run_checks` だけ)。

## 3. ルールを 1 つ読む

```python
# 引用: rules/naming_convention.py::evaluate
def evaluate(context: RuleContext, rule_def: dict) -> list[DefectRecord]:
    pattern = re.compile(rule_def["params"]["pattern"])
    applies_to = set(rule_def.get("applies_to", []))
    severity = rule_def.get("severity", "warn")
    message = rule_def.get("message", "naming convention violation")

    defects: list[DefectRecord] = []
    for asset in context.asset_records:
        if applies_to and asset.asset_type not in applies_to:
            continue
        basename = Path(asset.asset_id).stem
        if not pattern.match(basename):
            defects.append(
                DefectRecord(
                    asset_id=asset.asset_id,
                    rule_id=rule_def["rule_id"],
                    severity=severity,
                    message=message,
                    suggested_fix=None,
                    first_seen_run_id=context.scan_run_id,
                    last_seen_run_id=context.scan_run_id,
                )
            )
    return defects
```

- `applies_to` に**無い種類**は飛ばす(空なら全部)。
- **ファイル名の語幹**(`Path(...).stem`)に、正規表現が `match` するか(**先頭から**照合)。合わなければ、不具合を 1 件。
- **正規表現は YAML から**(`params.pattern`)。

```python
# 実行できる
from rules.engine import AssetView, RuleContext
from rules.naming_convention import evaluate

rule_def = {
    "rule_id": "naming_convention", "applies_to": ["texture", "model"], "severity": "warn",
    "params": {"pattern": r"^(T_|SM_)[A-Za-z0-9_]+$"}, "message": "命名規則に違反しています",
}
assets = [
    AssetView(1, "Props/T_Rock.png", "texture", ".png"),
    AssetView(2, "Props/rock.png", "texture", ".png"),            # 接頭辞が無い
    AssetView(3, "Props/SM_Tree.fbx", "model", ".fbx"),
    AssetView(4, "Props/tree final.fbx", "model", ".fbx"),        # 空白がある
    AssetView(5, "Audio/bgm_main.wav", "audio_bank", ".wav"),     # 対象の種類ではない
]
for defect in evaluate(RuleContext(scan_run_id=1, target_path=".", asset_records=assets), rule_def):
    print(f"{defect.severity:5} {defect.asset_id:20} {defect.rule_id}")
```

```text
# 出力
warn  Props/rock.png       naming_convention
warn  Props/tree final.fbx naming_convention
```

## 4. 不具合のライフサイクル

不具合は、**「アセット × ルール」で 1 行**(`UNIQUE(asset_id, rule_id)`)。1 行が、**時間を通した経過**を表します。

| 列 | 意味 |
|---|---|
| `first_seen_run_id` | **最初に**見つけたスキャン |
| `last_seen_run_id` | **最後に**見たスキャン(続いている限り、更新される) |
| `resolved_run_id` | **直った**スキャン(`NULL` = まだ open) |

```python
# 引用: core/db.py::upsert_defect_record
def upsert_defect_record(
    conn: sqlite3.Connection,
    asset_id: str,
    rule_id: str,
    severity: str,
    message: str,
    suggested_fix: str | None,
    scan_run_id: int,
) -> None:
    existing = conn.execute(
        "SELECT defect_record_id, first_seen_run_id FROM defect_records WHERE asset_id = ? AND rule_id = ?",
        (asset_id, rule_id),
    ).fetchone()
    if existing:
        # Re-detecting a defect always reopens it (resolved_run_id -> NULL),
        # covering the case where something was fixed and later regressed.
        conn.execute(
            """
            UPDATE defect_records
            SET severity = ?, message = ?, suggested_fix = ?, last_seen_run_id = ?, resolved_run_id = NULL
            WHERE defect_record_id = ?
            """,
            (
                severity,
                message,
                suggested_fix,
                scan_run_id,
                existing["defect_record_id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO defect_records
                (asset_id, rule_id, severity, message, suggested_fix, first_seen_run_id, last_seen_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                rule_id,
                severity,
                message,
                suggested_fix,
                scan_run_id,
                scan_run_id,
            ),
        )
```

- 既にある(`asset_id`・`rule_id`)なら、**`last_seen` を更新**し、**`resolved` を `NULL` に戻す**(**再発**: 直った後でまた壊れても、同じ行が再び open になる)。
- 無ければ、**新規**(`first_seen = last_seen`)。

### 解消の判定: 再評価した所だけ

`run_checks` は、ルールを評価して不具合を upsert した後で、**直ったものを閉じます**。ここに、大事な制限があります。

> **解消にするのは、「このスキャンで再評価したアセット」(と、削除が確認されたアセット)の不具合だけ**。

1 つのスキャンは、**1 つの入力**(`fs_scan` など)の**スナップショット**です。別の入力(`lqa`・`unity_asset`)のアセットの不具合は、**このスキャンで、そもそも見ていません**。見ていないものを「出なくなった = 直った」と閉じると、**偽の「直った」**になります。

```python
# 実行できる
import tempfile
from pathlib import Path

from core import db
from ingest.run_scan import run_scan
from rules.run_checks import run_checks

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    root, db_path = Path(tmp) / "assets", str(Path(tmp) / "insight.db")
    (root / "Props").mkdir(parents=True)
    (root / "Props" / "rock.png").write_bytes(b"x" * 10)         # 命名規則に違反
    (root / "Props" / "T_Tree.png").write_bytes(b"x" * 10)

    def naming_defects():
        with db.open_db(db_path) as conn:
            return [(d["asset_id"].split("/")[-1], d["first_seen_run_id"], d["last_seen_run_id"], d["resolved_run_id"])
                    for d in db.fetch_defect_records(conn, include_resolved=True) if d["rule_id"] == "naming_convention"]

    run1 = run_scan(db_path, "fs_scan", str(root), None)
    run_checks(db_path, str(root), run1)
    print("1 回目(rock.png が違反):", naming_defects())

    run2 = run_scan(db_path, "fs_scan", str(root), None)          # 何も直さずに、もう一度
    run_checks(db_path, str(root), run2)
    print("2 回目(そのまま)       :", naming_defects(), "← last_seen だけ進む")

    (root / "Props" / "rock.png").rename(root / "Props" / "T_Rock.png")   # 直す
    run3 = run_scan(db_path, "fs_scan", str(root), None)
    run_checks(db_path, str(root), run3)
    print("3 回目(名前を直した)   :", naming_defects(), "← resolved に run", run3)

    (root / "Props" / "T_Rock.png").rename(root / "Props" / "rock.png")   # また壊す
    run4 = run_scan(db_path, "fs_scan", str(root), None)
    run_checks(db_path, str(root), run4)
    print("4 回目(また壊した)     :", naming_defects(), "← 再発: 同じ行が open に戻る")
```

```text
# 出力
1 回目(rock.png が違反): [('rock.png', 1, 1, None)]
2 回目(そのまま)       : [('rock.png', 1, 2, None)] ← last_seen だけ進む
3 回目(名前を直した)   : [('rock.png', 1, 2, 3)] ← resolved に run 3
4 回目(また壊した)     : [('rock.png', 1, 4, None)] ← 再発: 同じ行が open に戻る
```

1 行(`rock.png`)の `last_seen` が進み、**直ると `resolved` が入り**、**再発すると `NULL` に戻ります**。ただし、再発後の `first_seen` は**最初のまま**(1)なので、「いつから壊れているか」は、**最初の発生**を指します(「いまの壊れ方がいつ始まったか」ではない。→ 学習資料の「既知の問題」)。

## 5. 他のルールの例

| ルール | 何をするか |
|---|---|
| `lod_missing` | モデルの検査 `lod_group_configured` が、**無い**か**失敗**している |
| `unused_material` | シーン・プレハブから参照されていない Material |
| `orphan_and_individual_fix` | ①**個別の指摘**(YAML の `overrides:` に書いた、アセットごとの一言。**スキャンに無くても出す**)②**孤立アセット**(`.unity`・`.prefab`・`.mat` の中に、**ファイル名が一度も現れない**) |

孤立の判定は、**名前の文字列照合**です(`[\w.\-]+\.(?:mat|fbx|png|...)` の正規表現)。Unity が GUID で参照するアセットは、**名前が現れない**ので、実際には使われていても孤立と判定される可能性があります(精度の限界。→ 学習資料)。

## 6. 危険: YAML の `module` は、何でも import できる

エンジンは、YAML の `module` の**文字列をそのまま** `import_module` します。そして、GUI には**ルールの YAML を編集する画面**(`/rules/<file>/edit`)があります。編集の**検査**は、「YAML として読める」「`rule_id` と `module` のキーがある」**だけ**で、`module` の**値は検査しません**。

```python
# 実行できる
from rules.definition_editor import validate_definition_source
from rules.engine import DEFINITIONS_DIR, RuleContext, run_all_rules
import tempfile
from pathlib import Path

# 編集の検査は、「module が rules. で始まるか」を見ない
parsed = validate_definition_source("rule_id: x\nmodule: json\n")
print("検査を通った:", parsed)

with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "x.yaml").write_text("rule_id: x\nmodule: json\n", encoding="utf-8")
    try:
        run_all_rules(RuleContext(scan_run_id=1, target_path=".", asset_records=[]), definitions_dir=Path(tmp))
    except AttributeError as exc:
        print("json モジュールは import され、evaluate が無くて失敗:", str(exc)[:60])
```

```text
# 出力
検査を通った: {'rule_id': 'x', 'module': 'json'}
json モジュールは import され、evaluate が無くて失敗: module 'json' has no attribute 'evaluate'
```

`json` は無害ですが、**import は、そのモジュールのトップレベルのコードを実行する**行為です。`sys.path` から import できる**どのモジュール**でも、指定できてしまいます。さらに、`params.pattern` は**そのまま `re.compile`** されるので、悪意あるパターン(**ReDoS**: 照合が極端に遅くなる)も入れられます。

| 守り | 内容 |
|---|---|
| **許可リスト** | `module` が `rules.` で**始まる**もの(または、既知のルールの名前だけ)に限る。検査は、**保存の前**(`validate_definition_source`)と、**読み込みの時**(エンジン)の両方で |
| **編集を絞る** | GUI は**ローカル専用**(Host・Origin の検査だけで、**認証なし**)。ルールの編集を、人を限る(認証・役割)か、GUI から外して、ファイルをリポジトリで管理する |
| **パターンの検査** | 正規表現の長さの上限・コンパイルの試行・時間制限 |

> これは、**この文書を作る途中で、コードを読んで見つけた**問題で、コードは変えていません(学習資料の「既知の問題」に記録)。ローカルの単独利用では、リスクは小さいが、**他の人が GUI を触れる環境**に置くなら、直す。

## 確認問題

1. ルールを足すのに、エンジンのコードを変えなくてよいのは、なぜですか。
2. 重大度・しきい値・正規表現を、YAML に置く利点は。
3. 不具合が、「直った後にまた壊れた」とき、`defect_records` はどうなりますか。
4. 「解消」にするのを、「再評価したアセット」に限るのは、なぜですか。
5. YAML の `module` を、検査しないと、何が危ないですか。

## 解答

1. エンジンは、YAML の `module` から**動的に import** して `evaluate` を呼ぶだけで、個別のルールを知らない。
2. **コードを変えずに**調整できる(運用の人が、レビューつきで直せる)。ルールの意図(しきい値)が、**データとして読める**。
3. **同じ行**の `resolved_run_id` が `NULL` に戻り、`last_seen` が進む(再発)。`first_seen` は最初のまま。
4. 1 つのスキャンは、**1 つの入力のスナップショット**。見ていないアセットの不具合を「出なくなった」で閉じると、**偽の「直った」**になる。
5. YAML を編集できる人が、**任意のモジュール**(import できるもの)を実行させられる(import はコードを実行する)。正規表現の ReDoS も、同じ入口から入る。

## まとめ

- ルールは **YAML(定義)+ `evaluate` 関数**。エンジンは動的 import で呼ぶだけ。足すときに、エンジンは変わらない。
- 不具合は「アセット × ルール」の 1 行で、`first_seen`・`last_seen`・`resolved` が**経過**を表す。再発は同じ行が再び open に。
- 解消は、**再評価したアセットだけ**(偽の「直った」を出さない)。
- **YAML の `module` を許可リストで絞る**必要がある(いまは、絞っていない)。
- 次の回は、**集計**(外れ値・分布・前回との差・推移)。

# 第 4 回 出力・GUI・テストと総合演習

> 所要時間の目安: 半日 / 前提: 第 0〜3 回

## この回のゴール

- **CI のゲート**(終了コード 0 / 1 / 2)の判定と、`--fail-on` の意味を説明できる。
- **マニフェスト**(`report_manifest.json`)が、**描画に依らない中間形式**である理由を説明できる。
- GUI の**スキャンの起動**(バックグラウンドのジョブ)と、**Host・Origin の検査**を説明できる。
- 新しいルールを足して、テストまで書ける。

## 1. CI のゲート(終了コード)

CI(自動ビルド)に組み込むと、**不具合があればビルドを落とせます**。

```python
# 引用: output/cli_adapter.py::evaluate_exit_code
def evaluate_exit_code(defect_rows: list, fail_on: str = "warn") -> int:
    threshold = SEVERITY_RANK.get(fail_on, 1)
    max_rank = 0
    for row in defect_rows:
        rank = SEVERITY_RANK.get(row["severity"], 0)
        max_rank = max(max_rank, rank)

    if max_rank == 0 or max_rank < threshold:
        return 0
    return 2 if max_rank >= SEVERITY_RANK["fail"] else 1
```

| 終了コード | 意味 |
|---|---|
| `0` | `--fail-on` 以上の不具合なし |
| `1` | **warn** 以上の不具合あり(`fail` ではない) |
| `2` | **fail** の不具合あり、または**実行時エラー**(成功したスキャンが無い等) |

- **重大度の順位**は `SEVERITY_RANK = {"info": 0, "warn": 1, "fail": 2}`(**1 か所**に定義し、CLI・Webhook の通知の判定が同じものを使う)。
- `--fail-on warn`(既定): warn 以上があれば、非ゼロ。`--fail-on fail`: **fail があるときだけ**非ゼロ(warn は許す)。
- **知らない重大度**(辞書に無い)は、`rank = 0` として扱う。

```python
# 実行できる
from output.cli_adapter import evaluate_exit_code


def rows(*severities):
    return [{"severity": s} for s in severities]


cases = {
    "不具合なし": rows(),
    "info だけ": rows("info", "info"),
    "warn が 1 件": rows("info", "warn"),
    "fail が 1 件": rows("warn", "fail"),
    "知らない重大度": rows("critical"),
}
for label, defects in cases.items():
    print(f"{label:12} --fail-on warn → {evaluate_exit_code(defects, 'warn')}   --fail-on fail → {evaluate_exit_code(defects, 'fail')}   --fail-on info → {evaluate_exit_code(defects, 'info')}")
```

```text
# 出力
不具合なし        --fail-on warn → 0   --fail-on fail → 0   --fail-on info → 0
info だけ      --fail-on warn → 0   --fail-on fail → 0   --fail-on info → 0
warn が 1 件   --fail-on warn → 1   --fail-on fail → 0   --fail-on info → 1
fail が 1 件   --fail-on warn → 2   --fail-on fail → 2   --fail-on info → 2
知らない重大度      --fail-on warn → 0   --fail-on fail → 0   --fail-on info → 0
```

注目: **`warn` だけのとき、`--fail-on fail` では 0**(通る)。`--fail-on info` は、`info` があっても `1` ではなく `0` です — 順位 0(`info`)の不具合は `max_rank == 0` として扱われる(下の「既知の問題」)。

## 2. マニフェスト: 描画に依らない中間形式

Excel・NDJSON・静的 HTML・GUI の**どれにも描画できる**ように、集計の結果を、**1 つの JSON(`report_manifest.json`)**にまとめます。

```text
{ manifest_version, scan_run_id, generated_at,
  sections: [ {section_id, type, title, data}, ... ] }
```

- **`ReportManifestBuilder`** だけが、この JSON を作る(各集計は、JSON を書かない)。
- 各セクションは `type`(`diff_summary`・`bar_chart`・`table`・`dot_chart` など)と `data`。**描画側は、`type` ごとの描き方**だけを知っていればよい。
- **新しい出力形式**を足すとき(例: PDF)は、**マニフェストを読んで描くだけ**。集計は変わらない。
- **id リストの上限**(`DIFF_ID_PREVIEW_LIMIT = 50`): 全件再スキャンで、「追加」が全アセットになっても、JSON が**膨らまない**。**件数は、常に正確**(上限は、一覧だけ)。

## 3. 操作 GUI(`webapp/`)

Flask の**ローカル**の操作画面です。

| 画面 | 役割 |
|---|---|
| `/` | ダッシュボード(スキャンの履歴・重大度ごとの件数) |
| `POST /scan` | **スキャンの起動**(入力・対象フォルダ・`since`・検知を続けて実行) |
| `/jobs/<id>`・`/jobs/<id>/status.json` | **ジョブの進み** |
| `/runs/<id>`・`export.xlsx`・`export.ndjson`・`static-report`・`notify` | 1 回分の詳細・各形式の出力・Webhook |
| `/defects`・`/defects/export.csv`・`/trend` | 不具合の一覧・CSV・推移 |
| `/rules`・`/rules/<file>/edit` | ルールの一覧・**編集** |

**スキャンは遅い**(大きなプロジェクトでは、数分)ので、リクエストの中で待たず、**別スレッド**(`threading.Thread`、`daemon=True`)で動かし、画面は**ジョブの ID**を持って、**ポーリング**で進みを見ます(`JobStore`)。

- ジョブの状態は**メモリだけ**(再起動で消える)。スキャンの結果そのものは、**DB にコミット済み**なので失われない(表示だけが消える)。
- **追跡する数に上限**(`MAX_TRACKED_JOBS = 50`)。古いものから捨てる(長く動かしても、メモリが増え続けない)。
- 例外は、**ジョブの `error` に入れて**、画面で見せる(スレッドの中の例外は、外に出ないので、自分で拾う)。

**Host・Origin の検査**(`webapp/security.py`): 認証のないローカル GUI に、別サイトのページが POST(スキャンの起動・ルールの編集)できないように、Host の許可リストと、変更操作の Origin を検査します(DNS rebinding・CSRF 対策)。**認証そのものはありません**(`secret_key` は、`flash` メッセージの署名だけに使う、起動ごとの乱数)。

## 4. テスト

```bash
.venv/Scripts/python -m pytest -q          # 全部(文書の検査を含む)
```

| ファイル | 確かめるもの |
|---|---|
| `test_ingest.py` | アダプタ・`since`・失敗の履歴 |
| `test_rules.py` | 各ルール・不具合のライフサイクル・解消の判定 |
| `test_trend.py` | パーセンタイル・外れ値・前回との差・推移 |
| `test_output.py`・`test_webhook_notify.py` | 終了コード・マニフェスト・Excel・NDJSON・Webhook |
| `test_webapp.py`・`test_webapp_security.py`・`test_definition_editor.py` | GUI・Host/Origin・ルールの編集の検査 |
| `test_docs.py` | この文書の検査 |

**型**: DB は `:memory:` か `tmp_path`。ファイルは `tmp_path` に作る。GUI は Flask の `test_client()`。**ネットワーク(Webhook)は偽物**に。

## 5. 総合演習: 新しいルール「テクスチャが大きすぎる」を足す

**課題**: テクスチャの**幅**(`texture_width` の検査値)が、しきい値(YAML の `params.max_width`)を**超える**ものを、不具合にします。

1. `rules/texture_too_large.py` に `evaluate(context, rule_def)` を書く。
2. `rules/definitions/texture_too_large.yaml` に、定義を書く(`module: rules.texture_too_large`・`params: {max_width: 2048}`)。
3. **テスト**を書く。

```python
# 実行できる
from rules.engine import AssetView, RuleContext
from rules.schema import DefectRecord


def evaluate(context: RuleContext, rule_def: dict) -> list[DefectRecord]:
    """演習: texture_width が params.max_width を超えるテクスチャを、不具合にする。"""
    limit = float(rule_def["params"]["max_width"])
    check_id = rule_def["params"].get("check_id", "texture_width")
    defects = []
    for asset in context.asset_records:
        if asset.asset_type != "texture":
            continue
        check = asset.checks.get(check_id)
        if check is None:                       # 検査が無い = 判断できない(不具合にはしない)
            continue
        try:
            width = float(check["value"])
        except (TypeError, ValueError):
            continue                            # 値が数値でない
        if width > limit:
            defects.append(DefectRecord(
                asset_id=asset.asset_id, rule_id=rule_def["rule_id"], severity=rule_def.get("severity", "warn"),
                message=f"幅 {int(width)}px が上限 {int(limit)}px を超えています", suggested_fix=f"{int(limit)}px 以下に縮小する",
                first_seen_run_id=context.scan_run_id, last_seen_run_id=context.scan_run_id))
    return defects


rule_def = {"rule_id": "texture_too_large", "severity": "warn", "params": {"max_width": 2048}}
assets = [
    AssetView(1, "T_Small.png", "texture", ".png", {"texture_width": {"status": "info", "value": "1024"}}),
    AssetView(2, "T_Big.png", "texture", ".png", {"texture_width": {"status": "info", "value": "4096"}}),
    AssetView(3, "T_Edge.png", "texture", ".png", {"texture_width": {"status": "info", "value": "2048"}}),   # ちょうど上限
    AssetView(4, "T_Unknown.png", "texture", ".png", {}),                                                    # 検査が無い
    AssetView(5, "T_Broken.png", "texture", ".png", {"texture_width": {"status": "info", "value": "?"}}),    # 数値でない
    AssetView(6, "SM_Rock.fbx", "model", ".fbx", {"texture_width": {"status": "info", "value": "9999"}}),    # 対象の種類ではない
]
for d in evaluate(RuleContext(scan_run_id=1, target_path=".", asset_records=assets), rule_def):
    print(d.asset_id, "→", d.message, "/", d.suggested_fix)
```

```text
# 出力
T_Big.png → 幅 4096px が上限 2048px を超えています / 2048px 以下に縮小する
```

**設計の判断**(3 つ): ①**ちょうど上限**は許す(`>`)。②検査が**無い**・値が**数値でない**ときは、**不具合にしない**(判断できないものを、決めつけない。ただし、それを**別のルール**で拾う手もある)。③検査値は**文字列**で入っているので、`float()` に直す。

### 自分で拡張する課題

1. 上のルールを、`rules/` に置き、YAML を足して、`python -m rules.run_checks` で動かす。**テスト**(`test_rules.py` の形)も足す。
2. `evaluate_exit_code` で、`--fail-on info` が `info` だけのとき `0` になるのは意図通りか。直すなら、どこをどう変えるか(テストも)。
3. 第 2 回の「`module` の許可リスト」を、`validate_definition_source` に足す(`rules.` で始まらなければ `RuleDefinitionError`)。テストも。

## 確認問題

1. `--fail-on fail` で、warn だけのとき、終了コードは何ですか。なぜ、そうしますか。
2. マニフェストを、描画に依らない中間形式にする利点は。
3. スキャンを、別スレッドのジョブにするのは、なぜですか。ジョブの状態が再起動で消えても、スキャンの結果は失われないのは、なぜですか。
4. 総合演習のルールで、「検査が無いテクスチャ」を、不具合にしないのは、なぜですか。

## 解答

1. **0**(通る)。CI で「warn は許すが、fail は許さない」という段階的な基準を、`--fail-on` で選べるようにする。
2. 出力の形式(Excel・HTML・NDJSON・GUI)を**足しても、集計は変わらない**。描画側は、マニフェストを読んで描くだけ。
3. 大きなプロジェクトでは、スキャンに数分かかり、リクエストの中で待つと、**画面が固まり**、ブラウザ・プロキシの**時間切れ**になる。結果は、スキャンの途中で DB にコミットされているので、メモリのジョブの表示が消えても、データは残る。
4. **判断できない**ものを、不具合と決めつけない(誤検知を増やさない)。「検査が走っていない」は、別の問題で、別のルールで拾うほうが、意図が明確。

## まとめ

- CI のゲートは、**終了コード 0 / 1 / 2** と `--fail-on`。重大度の順位は 1 か所。
- 出力は、**マニフェスト**(描画に依らない中間形式)から、各形式へ。
- GUI は、**別スレッドのジョブ**で重いスキャンを回し、Host・Origin を検査する(認証は無い)。
- 新しいルールは、**関数 + YAML + テスト**。判断できないものは、決めつけない。
- ここから先は、[学習資料](../learn/index.md)(保守・拡張の実務編)へ。

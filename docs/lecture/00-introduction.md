# 第 0 回 アセット品質を「継続的に」見る(全体の見取り図)

> 所要時間の目安: 1.5 時間 / 前提: Python の基本・SQL の `SELECT` / `INSERT`

## この回のゴール

- ゲームアセットの品質を**継続的に**見る意味と、このツールの設計(**単一のパイプライン・単一のデータモデル**)を説明できる。
- パイプライン(取り込み → 不具合検知 → 集計 → 出力)の各段と、4 つのテーブルの役割が分かる。
- **追記専用**(append-only)のテーブルが、なぜ履歴の集計に向くかを説明できる。
- インメモリの DB に、スキャンの結果を入れて、読み出せる。

## 1. 解きたい問題

ゲームのアセット(テクスチャ・モデル・マテリアル・スクリプト…)は、増え続けます。命名規則の違反・LOD(遠くで使う軽いモデル)の設定漏れ・参照されていない孤立アセット・巨大すぎるテクスチャ。**気づいたときには、数千個**になっています。

**一度だけ点検する**のでは足りません。**毎週・毎日**、同じ基準で点検し、**増えているのか・減っているのか**、**いつから**かを見たい。このツールは、そのための**点検・記録・集計・報告**を、ひとつにまとめています。

## 2. 設計: 単一のパイプライン・単一のデータモデル

![AssetDataInsightSuite の構成](../diagrams/architecture.svg)

| 段 | 場所 | 役割 |
|---|---|---|
| **取り込み**(ingest) | `ingest/` | アセットを集めて、**共通の形**(`AssetRecord`)にそろえる。入力: `.lqa` のサイドカー・ファイルシステム・Unity アセット |
| **不具合検知**(rules) | `rules/` | **YAML で書いたルール**を評価して、不具合(`DefectRecord`)を出す |
| **集計**(trend) | `trend/` | 外れ値・分布・前回との差・時系列の推移 |
| **出力**(output) | `output/` | CLI(CI のゲート)・Excel・NDJSON・静的 HTML・Webhook |
| **GUI** | `webapp/` | Flask の操作画面(スキャンの起動・不具合・推移・ルールの編集) |

すべての段が、**1 つの SQLite ファイル `insight.db`** を、**唯一の真実の源**として読み書きします。

> **「共通の形」にそろえる**のが要です。入力が `.lqa` でも Unity でも、`AssetRecord` になれば、**ルールも集計も出力も、入力の種類を知らなくてよい**。新しい入力を足すときは、**取り込みだけ**を書けばよい。

## 3. 4 つのテーブル

| テーブル | 1 行が表すもの | 書き方 |
|---|---|---|
| `scan_runs` | **スキャン 1 回**(いつ・どの入力・成功したか) | **追記専用**(過去の行は更新・削除しない) |
| `asset_records` | **その回に見たアセット 1 つ**(種類・サイズ・更新日時) | 追記専用 |
| `check_results` | アセット 1 つに対する**検査 1 件**(`lod_group_configured` など) | 追記専用 |
| `defect_records` | **不具合 1 件**(アセット × ルールで 1 行。最初に見た回・最後に見た回・解消した回) | **更新あり**(下) |

**追記専用が履歴に向く理由**: 過去のスキャンの行が**変わらない**ので、「第 3 回のときの状態」と「第 7 回のときの状態」を、**いつでも正確に比べられる**。集計の SQL が、過去の `scan_run_id` を安全に `JOIN` できる。

唯一、`defect_records` だけは**更新**します。「同じ不具合が、続いているのか・直ったのか」を、**1 行の `first_seen`・`last_seen`・`resolved` で表す**ためです(第 3 回)。

## 4. 触ってみる: メモリの DB に記録する

```python
# 実行できる
from core import db
from core.schema import AssetRecord, CheckResult

conn = db.connect(":memory:")          # ディスクに書かない、使い捨ての DB
run_id = db.start_scan_run(conn, "fs_scan", "demo", "2026-11-01T00:00:00+00:00")

records = [
    AssetRecord(asset_id="Assets/Props/T_Rock.png", asset_type="texture", source_producer="fs_scan",
                collected_at="2026-11-01T00:00:00+00:00", size_bytes=4096, extension=".png",
                last_modified="2026-10-30T12:00:00+00:00",
                checks={"texture_width": CheckResult(status="info", value=2048)}),
    AssetRecord(asset_id="Assets/Props/rock_model.fbx", asset_type="model", source_producer="fs_scan",
                collected_at="2026-11-01T00:00:00+00:00", size_bytes=90000, extension=".fbx",
                last_modified="2026-10-29T09:00:00+00:00",
                checks={"lod_group_configured": CheckResult(status="fail", message="LODGroup が無い")}),
]
db.insert_asset_records(conn, run_id, records)
db.finish_scan_run(conn, run_id, "2026-11-01T00:05:00+00:00", "success")

print("スキャン:", [(r["scan_run_id"], r["source_producer"], r["status"]) for r in conn.execute("SELECT * FROM scan_runs")])
print("アセット:", [(r["asset_id"].split("/")[-1], r["asset_type"], r["size_bytes"]) for r in db.fetch_asset_records(conn, run_id)])
for row in db.fetch_asset_records(conn, run_id):
    checks = db.fetch_check_results(conn, run_id, row["asset_record_id"])
    print(" ", row["asset_id"].split("/")[-1], "→", [(c["check_id"], c["status"], c["value"]) for c in checks])
print("最新の成功したスキャン:", db.latest_scan_run_id(conn))
```

```text
# 出力
スキャン: [(1, 'fs_scan', 'success')]
アセット: [('T_Rock.png', 'texture', 4096), ('rock_model.fbx', 'model', 90000)]
  T_Rock.png → [('texture_width', 'info', '2048')]
  rock_model.fbx → [('lod_group_configured', 'fail', None)]
最新の成功したスキャン: 1
```

注目: `texture_width` の値 `2048` が、**文字列として**保存されます(`check_results.value` は `TEXT`)。数値として集計するときは、**読み出して `float()` に直す**必要があります(第 3 回)。

## 確認問題

1. 「継続的に」見る価値は、一度きりの点検と比べて、何ですか。
2. 入力が違っても、ルール・集計・出力を変えずに済むのは、なぜですか。
3. `scan_runs` などを追記専用にする利点は。
4. `defect_records` だけが、更新を許すのは、なぜですか。

## 解答

1. **増減の傾向**と、**いつから**を知れること。点検の基準を**固定**して、時間で比べられる。
2. すべての入力が、**共通の形(`AssetRecord`)**にそろえられるから。後ろの段は、共通の形だけを知っている。
3. 過去のスキャンの行が**変わらない**ので、集計が過去を**正確に**参照できる(履歴の信頼性)。
4. 不具合は、「**続いている・直った・再発した**」という**状態**を持つ。1 行の `first_seen`・`last_seen`・`resolved` で、その経過を表す。

## まとめ

- 目的は、アセット品質の**継続的な**可視化。**単一のパイプライン・単一のデータモデル**(`insight.db`)で作る。
- 入力を**共通の形**にそろえるので、ルール・集計・出力は、入力を知らない。
- テーブルは**追記専用**(履歴の信頼性)。ただし `defect_records` は、不具合の**状態**を持つので更新する。
- 次の回は、取り込み(アダプタのプラグイン)と DB への書き込み。

# 第 1 回 取り込み: アダプタのプラグインと、失敗の記録

> 所要時間の目安: 3 時間 / 前提: 第 0 回・`Protocol` と デコレータの基本

## この回のゴール

- **アダプタ**(入力ごとの取り込み)が、`Protocol` と**登録(`@register`)**で、**追加しやすい**作りになっていることを説明できる。
- ファイルシステムのスキャンの流れ(`rglob`・相対パス・`since` による差分)を説明できる。
- 取り込みの**失敗が、履歴に残る**ようにする工夫(**明示のコミット**)を説明できる。
- 自分のアダプタを書いて、登録して動かせる。

## 1. アダプタの約束(`Protocol`)

```python
# 引用: ingest/adapters/registry.py::SourceAdapter
class SourceAdapter(Protocol):
    producer_id: str

    def scan(self, target_path: str, since: str | None = None) -> list[AssetRecord]: ...
```

アダプタは、**`producer_id`(名前)と `scan(target_path, since)`** を持てばよい。継承は要りません(`Protocol` = 構造的な型付け)。

```python
# 引用: ingest/adapters/registry.py::register
def register(adapter_cls: type[SourceAdapter]) -> type[SourceAdapter]:
    instance = adapter_cls()
    ADAPTER_REGISTRY[instance.producer_id] = instance
    return adapter_cls
```

**`@register` デコレータ**が、クラスを**インスタンスにして、辞書に登録**します。新しい入力を足すには、`ingest/adapters/` に**ファイルを 1 つ足して `@register` を付ける**だけ。既存のコードは**変えません**(プラグイン方式)。

## 2. ファイルシステムのスキャン

`FsScanAdapter`(`producer_id = "fs_scan"`)の流れ:

1. 対象フォルダの下を、`rglob("*")` で**再帰的に**たどる(`sorted` で**順序を固定**: 実行ごとに同じ並びになる)。
2. ファイルだけを対象に。**スキップする接尾辞**(`.meta` など)を除く。
3. **`since`**(ISO 8601 の日時)を渡すと、**それより後に更新されたファイルだけ**(`st_mtime > since`): 差分のスキャン。
4. `asset_id` は**対象フォルダからの相対パス**(`as_posix()` で、区切りを `/` にそろえる)。**同じファイルは、いつも同じ `asset_id`**(安定したキー)。
5. 拡張子から**種類**を決める(`_classify`: `.png` → texture など)。

```python
# 実行できる
import os
import tempfile
from pathlib import Path

from ingest.adapters.fs_scan_adapter import FsScanAdapter

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "Props").mkdir()
    (root / "Props" / "T_Rock.png").write_bytes(b"x" * 100)
    (root / "Props" / "SM_Rock.fbx").write_bytes(b"y" * 250)
    (root / "Props" / "SM_Rock.fbx.meta").write_text("meta", encoding="utf-8")   # スキップされるはず
    (root / "Notes.txt").write_text("memo", encoding="utf-8")
    os.utime(root / "Notes.txt", (1_000_000_000, 1_000_000_000))                 # ずっと前の更新日時

    adapter = FsScanAdapter()
    records = adapter.scan(str(root))
    for r in records:
        print(f"{r.asset_id:18} 種類={r.asset_type:9} サイズ={r.size_bytes:4} 拡張子={r.extension}")

    recent = adapter.scan(str(root), since="2020-01-01T00:00:00Z")
    print("since=2020 以降の更新:", [r.asset_id for r in recent])
```

```text
# 出力
Notes.txt          種類=unknown   サイズ=   4 拡張子=.txt
Props/SM_Rock.fbx  種類=model     サイズ= 250 拡張子=.fbx
Props/T_Rock.png   種類=texture   サイズ= 100 拡張子=.png
since=2020 以降の更新: ['Props/SM_Rock.fbx', 'Props/T_Rock.png']
```

注目: `.meta` は含まれず、`Notes.txt`(2001 年の更新日時)は `since=2020` で**除かれ**ます。

## 3. 自分のアダプタを足す

```python
# 実行できる
import tempfile
from pathlib import Path

from core.schema import AssetRecord, CheckResult
from ingest.adapters.registry import ADAPTER_REGISTRY, register


@register
class ReadmeAdapter:
    """演習用: フォルダの中の README だけを、文書(doc)として 1 件ずつ記録する。"""

    producer_id = "readme_demo"

    def scan(self, target_path, since=None):
        records = []
        for path in sorted(Path(target_path).rglob("README*")):
            records.append(AssetRecord(
                asset_id=path.relative_to(target_path).as_posix(), asset_type="doc", source_producer=self.producer_id,
                collected_at="2026-11-01T00:00:00+00:00", size_bytes=path.stat().st_size, extension=path.suffix.lower(),
                last_modified=None, checks={"has_text": CheckResult(status="pass" if path.stat().st_size else "fail")},
            ))
        return records


print("登録された:", "readme_demo" in ADAPTER_REGISTRY)
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "README.md").write_text("# hello", encoding="utf-8")
    (Path(tmp) / "sub").mkdir()
    (Path(tmp) / "sub" / "README.txt").write_text("", encoding="utf-8")
    for r in ADAPTER_REGISTRY["readme_demo"].scan(tmp):
        print(r.asset_id, r.asset_type, r.checks["has_text"].status)
```

```text
# 出力
登録された: True
README.md doc pass
sub/README.txt doc fail
```

このアダプタを、**`run_scan` から使う**には、`ingest/run_scan.py` が `ingest.adapters` を import して登録を済ませている必要があります(新しいファイルは、`__init__` か `run_scan.py` で import する)。**登録は import の副作用**なので、import されないと、辞書に載りません。

## 4. 失敗も、履歴に残す

```python
# 引用: ingest/run_scan.py::run_scan
def run_scan(
    db_path: str, producer_id: str, target_path: str, since: str | None
) -> int:
    adapter = ADAPTER_REGISTRY.get(producer_id)
    if adapter is None:
        raise SystemExit(
            f"unknown producer: {producer_id} (known: {sorted(ADAPTER_REGISTRY)})"
        )
    if not Path(target_path).is_dir():
        raise SystemExit(
            f"target path does not exist or is not a directory: {target_path}"
        )

    started_at = datetime.now(timezone.utc).isoformat()
    with db_module.open_db(db_path) as conn:
        scan_run_id = db_module.start_scan_run(
            conn, producer_id, TOOL_VERSION, started_at
        )
        try:
            records = adapter.scan(target_path, since)
            db_module.insert_asset_records(conn, scan_run_id, records)
        except Exception:
            # `open_db` only commits on a clean exit from the `with` block, so an
            # exception propagating past it would roll back this UPDATE too and
            # silently discard the "failed" status (and the scan_run row itself).
            # Commit explicitly here so the failure is actually persisted as history.
            db_module.finish_scan_run(
                conn, scan_run_id, datetime.now(timezone.utc).isoformat(), "failed"
            )
            conn.commit()
            raise
        db_module.finish_scan_run(
            conn, scan_run_id, datetime.now(timezone.utc).isoformat(), "success"
        )
    return scan_run_id
```

注目するのは、`except Exception:` の中です。

- `open_db` は、**`with` ブロックを正常に抜けたときだけ**コミットします。例外がそのまま外へ出ると、**ロールバック**され、`scan_runs` の行そのものが**消えます**。
- それでは「**失敗したスキャンがあった**」という事実が、履歴に残らない。そこで、例外の中で `finish_scan_run(..., "failed")` を書き、**明示的にコミット**してから、例外を**再送出**(`raise`)する。
- 失敗した回は、`status = 'failed'`。集計は `status = 'success'` だけを見る(`latest_scan_run_id`・`diff_against_previous`)ので、**壊れたデータを混ぜない**。

```python
# 実行できる
import tempfile
from pathlib import Path

from core import db
from ingest import run_scan as run_scan_module
from ingest.adapters.registry import ADAPTER_REGISTRY, register


@register
class ExplodingAdapter:
    producer_id = "exploding_demo"

    def scan(self, target_path, since=None):
        raise RuntimeError("スキャン中に壊れた")


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    db_path = str(Path(tmp) / "insight.db")
    try:
        run_scan_module.run_scan(db_path, "exploding_demo", tmp, None)
    except RuntimeError as exc:
        print("例外は呼び出し元へ:", exc)

    with db.open_db(db_path) as conn:
        rows = conn.execute("SELECT source_producer, status FROM scan_runs").fetchall()
        print("履歴に残った:", [(r["source_producer"], r["status"]) for r in rows])
        print("最新の成功したスキャン:", db.latest_scan_run_id(conn))
```

```text
# 出力
例外は呼び出し元へ: スキャン中に壊れた
履歴に残った: [('exploding_demo', 'failed')]
最新の成功したスキャン: None
```

## 確認問題

1. `Protocol` と `@register` で、新しい入力を足すとき、既存のコードを変えずに済むのは、なぜですか。
2. `asset_id` を、対象フォルダからの相対パス(`/` 区切り)にする理由は。
3. `since` の差分のスキャンで、何を取り込みますか。注意点は。
4. 失敗したスキャンを、履歴に残すために、何をしていますか。
5. 失敗した回を、集計から除くのは、なぜですか。

## 解答

1. アダプタは、`producer_id` と `scan` を持つだけでよく(`Protocol`)、`@register` が自動で辞書に載せる。他の段は、辞書を介して使うだけで、個別のアダプタを知らない。
2. **マシンが違っても、同じファイルは同じ `asset_id`** になる(絶対パスやバックスラッシュだと、環境で変わる)。前回との比較・不具合の追跡に、安定したキーが要る。
3. 更新日時が `since` **より後**のファイルだけ。注意: 削除されたファイルは、スキャンに**出てこない**ので、「消えた」ことは、前回との比較(`diff_against_previous`)で知る。
4. 例外の中で、`failed` を書き、**明示的にコミット**してから再送出する(`open_db` は、例外ではロールバックするため)。
5. 途中で壊れた回は、**中途半端なデータ**を含むかもしれない。壊れたデータを、傾向に混ぜない。

## まとめ

- 取り込みは、`Protocol` + `@register` の**プラグイン**。共通の形(`AssetRecord`)にそろえる。
- `asset_id` は、**相対パス**の安定したキー。`since` で差分のスキャン(削除は、前回との比較で知る)。
- 失敗も `failed` として**履歴に残す**(明示のコミット)。集計は成功した回だけを見る。
- 次の回は、**YAML で書くルール**と、不具合のライフサイクル。

# 5. テストの書き方と実行

## 実行

```bash
uv venv .venv
uv pip install -e ".[dev]" --python .venv
.venv/Scripts/python -m pytest -q          # 全部(文書の検査を含む)
.venv/Scripts/python -m pytest tests/test_rules.py -q
.venv/Scripts/python -m pytest -k "resolved" -q
```

`pyproject.toml` の `pythonpath = ["."]` で、ルートの `core`・`ingest`・`rules`・`trend`・`output`・`webapp` を import できます。

## テストの置き場所と、何を確かめるか

| ファイル | 確かめるもの |
|---|---|
| `test_ingest.py` | アダプタ・`since`・失敗が履歴に残ること |
| `test_rules.py` | 各ルール・不具合のライフサイクル・**解消は再評価した所だけ** |
| `test_trend.py` | パーセンタイル・外れ値・前回との差・推移 |
| `test_output.py` | 終了コード・マニフェスト・Excel・NDJSON・静的 HTML |
| `test_webhook_notify.py` | メッセージの組み立て・閾値・**送信の失敗**(偽の送信先) |
| `test_webapp.py`・`test_webapp_security.py` | GUI(`test_client`)・Host・Origin・ジョブ・ルール編集 |
| `test_definition_editor.py` | ルール定義の読み書き・検査(パスのたどり) |
| `test_docs.py` | 文書の検査(下) |

## よく使う型

1. **DB は `:memory:` か一時ファイル**。`db.connect(":memory:")` で使い捨ての DB。
2. **固定の入力**: `tests/fixtures/fs_scan_sample`・`lqa_sample`。または一時フォルダにファイルを作る。
3. **履歴は手で作る**: `start_scan_run`・`insert_asset_records`・`finish_scan_run` で、複数回のスキャンを作り、前回との差・推移を確かめる。
4. **外部は偽物**: Webhook は `urllib` を差し替える。
5. **GUI は Flask の `test_client()`**: DB は一時ファイルを `create_app(db_path)` に渡す。
6. **異常系と「しないこと」**: 壊れた YAML・必須キーの欠落・存在しないフォルダ・パスのたどり(`../`)・他のサイトからの POST。

## 新しい機能のテストを書く手順

1. **失敗するテストを先に**。2. 実装して通す。3. **境界**(ちょうど・1 つ手前)と、**判断できない入力**。4. 履歴が絡むなら、**再発・解消・失敗した回**のケース。

## 文書の検査

```bash
python tools/check_docs.py             # 検査(標準ライブラリだけ)
python tools/check_docs.py --update    # 引用の更新・実行例の出力の作り直し
python tools/check_mermaid.py          # Mermaid が描画できるか(mmdc が要る)
python tools/make_diagrams.py          # 構成図(SVG)を作り直す
```

`tests/test_docs.py` は、同じ検査を pytest で行います(引用がソースと一致・実行例が 2 回動いて出力が一致・講義の標準の節・リンク・Mermaid の標準行)。

> **実行例を書くコツ**: 出力は決まった値だけに。一時フォルダのパス・時刻・`set` の順をそのまま `print` しない。

## 確かめていないこと(正直に)

- 実ブラウザでの GUI の見え方・操作は、この文書の検査では**確かめていません**。
- 実際の Unity プロジェクト(大規模)での**スキャンの時間・メモリ**は未測定。
- `.github/workflows/insight-scan.yml` を、本物の GitHub Actions で走らせた結果は、ここでは確かめていません。

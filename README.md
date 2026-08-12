# AssetDataInsightSuite

ゲームアセットの品質を継続的に可視化するための単一パイプライン・単一データモデルのツール群。
設計の詳細は [AssetDataInsightSuite_DESIGN.md](AssetDataInsightSuite_DESIGN.md) を参照。

取り込み(`.lqa` / fs_scan / Unity asset)→ 不具合検知(YAML駆動ルール)→ トレンド集計 → 出力(CLI / Excel / NDJSON / 静的HTML)を、
`insight.db` (SQLite) 上の3テーブル (`scan_runs` / `asset_records` / `check_results`) + `defect_records` を唯一のソースオブトゥルースとして一貫実装している。

## セットアップ

```bash
uv venv .venv
uv pip install -e ".[dev]" --python .venv
```

## 使い方

```bash
# 1. 取り込み(いずれか、または --producer all)
python -m ingest.run_scan --producer fs_scan --target <SCAN_TARGET_DIR> --db insight.db

# 2. 不具合検知(rules/definitions/*.yaml を読み込んで評価)
python -m rules.run_checks --target <SCAN_TARGET_DIR> --db insight.db

# 3-a. CIゲート用CLI(exit code: 0=defectなし / 1=warn以上 / 2=fail検出 or 実行時エラー)
python -m output.cli_adapter --db insight.db --fail-on warn --manifest-out report_manifest.json

# 3-b. Excelレポート
python -m output.excel_adapter --db insight.db --out report.xlsx

# 3-c. Elasticsearch _bulk 互換NDJSON
python -m output.ndjson_export --db insight.db --out checks.ndjson

# 3-d. オフライン静的HTMLレポート(Kibanaが無いチーム向けフォールバック)
python -m output.static_html_adapter --db insight.db --out-dir reports
```

CIでの定期実行は [.github/workflows/insight-scan.yml](.github/workflows/insight-scan.yml) を参照。

## 操作用GUI

上記CLIを1画面から操作できるローカルWebダッシュボード(Flask)。スキャン実行・履歴閲覧・Defect一覧・トレンドを提供する。
ローカル/単一ユーザー利用が前提で、認証機能は無い(既定で `127.0.0.1` のみ待受)。

```bash
python -m webapp.app --db insight.db --port 5000
```

起動後 `http://127.0.0.1:5000` を開く。

- **Dashboard** — producer/target pathを指定してスキャン実行(取り込み+ルールチェック)、スキャン履歴一覧
- **run詳細** — `report_manifest.json` の内容をそのまま表示。Excel/NDJSONダウンロード、静的HTMLレポート再生成もここから
- **Defects** — 検出中の`defect_records`一覧、severityで絞り込み
- **Trend** — scan_runごとの新規defect検出件数の推移

GUIは既存の `ingest` / `rules` / `output` モジュールを直接呼び出すだけで、独自の集計・判定ロジックは持たない。

## テスト

```bash
python -m pytest
```

## ディレクトリ構成

- `core/` — 正準スキーマ(`AssetRecord`/`CheckResult`)と SQLite 層
- `ingest/adapters/` — `.lqa` / fs_scan / Unity asset の各取り込みアダプタ(プラグイン登録方式)
- `rules/` — YAML駆動の不具合検知ルールエンジン
- `trend/` — トレンド集計関数(SQLのみ、描画とは分離)
- `output/` — `report_manifest.json` を唯一の中間形式とする CLI / Excel / NDJSON / 静的HTML 出力アダプタ
- `tests/` — pytest スイートと固定フィクスチャ

静的HTMLレポート(`output/static_html_adapter.py`)は `AssetDataInsightSuite_UI_DESIGN.md`(Revolutデザイン分析)のトークン
(2モードキャンバス・pill型バッジ・rounded-lg カード)に基づいてスタイリングされている。

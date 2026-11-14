# 2. コードの読み方(どこに何があるか)

## ファイルの地図

| 場所 | 行数の目安 | 役割 | 読む順 |
|---|---|---|---|
| `core/schema.py` | 40 | `AssetRecord`・`CheckResult`(**共通の形**) | ① |
| `core/db.py` | 290 | SQLite のスキーマ・追記・**不具合の upsert と解消**・列の追加 | ② |
| `ingest/adapters/registry.py` | 30 | `SourceAdapter`(Protocol)・`@register` | ③ |
| `ingest/adapters/*_adapter.py` | 80〜150 | `lqa`・`fs_scan`・`unity_asset` | |
| `ingest/run_scan.py` | 80 | スキャン 1 回(失敗も履歴に残す) | ④ |
| `rules/engine.py` | 90 | YAML の読み込み・**動的 import**・`RuleContext` | ⑤ |
| `rules/*.py` | 60〜90 | 各ルール(`naming_convention`・`lod_missing`・`unused_material`・`orphan_and_individual_fix`) | |
| `rules/run_checks.py` | 90 | ルールの実行・upsert・**解消の判定** | ⑥ |
| `rules/definition_editor.py` | 70 | GUI のルール編集(検査はキーの有無だけ) | |
| `trend/aggregations.py` | 360 | パーセンタイル・外れ値・前回との差・推移 | ⑦ |
| `output/report_manifest.py` | 115 | マニフェストを作る(**唯一の生成元**) | ⑧ |
| `output/*.py` | 70〜310 | CLI・Excel・NDJSON・静的 HTML・Webhook | |
| `webapp/app.py` | 385 | Flask(ルート・ジョブ・ルール編集) | |
| `webapp/jobs.py`・`security.py` | 95・80 | 別スレッドのジョブ・Host/Origin の検査 | |

**読み方**: ①②(データの形)→ ③④(取り込み)→ ⑤⑥(ルールと解消)→ ⑦⑧(集計と出力)。GUI は最後。

## 設計書・設定

| 場所 | 内容 |
|---|---|
| `AssetDataInsightSuite_DESIGN.md` | 設計書(Phase 0〜6) |
| `AssetDataInsightSuite_UI_DESIGN.md` | UI のデザイントークン |
| `IMPROVEMENT_DESIGN_2026-10.md`・`IMPROVEMENT_PLAN_2026-10.md` | 2026-10 の改善の設計と計画 |
| `.github/workflows/insight-scan.yml` | CI での定期実行(`INSIGHT_WEBHOOK_URL` があれば通知) |
| `tests/fixtures/` | `fs_scan_sample`・`lqa_sample`(固定の入力) |

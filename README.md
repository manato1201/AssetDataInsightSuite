# AssetDataInsightSuite

ゲームアセットの品質を**継続的に**可視化する、単一パイプライン・単一データモデルのツール群です。取り込み(`.lqa` / fs_scan / Unity)→ 不具合検知(YAML 駆動ルール)→ トレンド集計 → 出力(CLI / Excel / NDJSON / 静的 HTML / Webhook / GUI)を、`insight.db`(SQLite)を唯一の真実の源として実装しています。設計は [AssetDataInsightSuite_DESIGN.md](AssetDataInsightSuite_DESIGN.md)。

![構成図](docs/diagrams/architecture.svg)

## 状態

| 項目 | 内容 |
|---|---|
| テスト | `.venv/Scripts/python -m pytest -q`(文書の検査を含む) |
| GUI | Flask のローカル専用。**認証なし**(Host・Origin の検査のみ) |
| 既知の問題 | [docs/learn/06-troubleshooting-maintenance.md](docs/learn/06-troubleshooting-maintenance.md)(不具合の並び・ルール YAML の `module` 未検証 ほか) |
| 学習資料 | 講義 5 回 + 保守・拡張の学習資料 7 本(全体像・コードの読み方・内側・拡張・テスト・トラブル・用語集) |

## クイックスタート

```bash
uv venv .venv
uv pip install -e ".[dev]" --python .venv
python -m ingest.run_scan --producer fs_scan --target <DIR> --db insight.db      # 1. 取り込み
python -m rules.run_checks --target <DIR> --db insight.db                        # 2. 不具合検知
python -m output.cli_adapter --db insight.db --fail-on warn                      # 3. CI ゲート(終了コード 0 / 1 / 2)
python -m webapp.app --db insight.db --port 5000                                 # GUI: http://127.0.0.1:5000
```

Excel・NDJSON・静的 HTML・Webhook・GUI の操作手順・環境変数は [詳細](docs/reference/setup-and-operations.md)。

## ドキュメント

| 読みたいもの | 場所 |
|---|---|
| 全体の地図 | [docs/index.md](docs/index.md) |
| **基礎から学ぶ**(講義 5 回・実行できる例つき) | [docs/lecture/](docs/lecture/index.md) |
| 保守・拡張(学習資料) | [docs/learn/](docs/learn/index.md) |
| セットアップ・GUI・動作確認の**詳細**(旧 README) | [docs/reference/setup-and-operations.md](docs/reference/setup-and-operations.md) |
| 図と技術解説(Mermaid) | [docs/TECHNICAL_GUIDE.md](docs/TECHNICAL_GUIDE.md)・[HTML 版](docs/technical_guide.html) |

## 限界(正直に)

- GUI は**認証なし**で、ルールの YAML を編集できます。他の人が触れる環境には置かないでください(`module` を `rules.` に限る検査がまだありません)。
- 前回との差は**サイズと更新日時だけ**を見ます。孤立アセットの判定は**名前の照合**です(GUID 参照は見えません)。

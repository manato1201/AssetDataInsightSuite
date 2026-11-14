# AssetDataInsightSuite 学習資料(保守・拡張の実務編)

このフォルダは、**このツールを直す・足す人**のための資料です。基礎から順に学ぶ講義は [../lecture/index.md](../lecture/index.md)(第 0〜4 回)。既存の技術解説は [../TECHNICAL_GUIDE.md](../TECHNICAL_GUIDE.md)(Mermaid の構成図・ER 図・シーケンス図)にあります。

| # | 資料 | いつ読むか |
|---|---|---|
| 1 | [全体像](01-overview.md) | 何がどう動いているか・データの置き場所・環境変数・API |
| 2 | [コードの読み方](02-code-tour.md) | どのファイルから読むか |
| 3 | [内側のしくみ](03-internals.md) | 不具合の解消の判定・マニフェスト・Webhook・GUI のジョブ・CI |
| 4 | [拡張のレシピ](04-extend.md) | 入力・ルール・出力・集計を**足したい** |
| 5 | [テストの書き方と実行](05-testing.md) | テストを回す・足す・文書の検査 |
| 6 | [トラブルと保守](06-troubleshooting-maintenance.md) | 動かない・**既知の問題**・定期の保守 |
| 7 | [基礎の補強](07-foundations.md) | デコレーター・辞書・正規表現・YAML・SQL・外れ値・設計思想・IT 用語を**補強したい** |
| – | [用語集](glossary.md) | 分からない言葉が出た |

## 最初の 15 分

1. [README](../../README.md) の手順で、`.venv` を作り、`pytest -q` を通す。
2. `tests/fixtures/fs_scan_sample` を対象に、CLI を 3 つ(取り込み → 検知 → ゲート)順に実行する(旧 README の「CLI だけで一気通貫」)。
3. [構成図](../diagrams/architecture.svg)を見ながら、[全体像](01-overview.md)を読む。

## 目的別の近道

| やりたいこと | 読む場所 |
|---|---|
| 新しい入力(別のツールの出力)を取り込む | [4 拡張](04-extend.md) レシピ 1・講義[第 1 回](../lecture/01-ingest.md) |
| ルールを足す・しきい値を変える | [4 拡張](04-extend.md) レシピ 2・講義[第 2 回](../lecture/02-rules.md) |
| 集計・出力を足す | [4 拡張](04-extend.md) レシピ 3・4 |
| CI で落とす基準を変える | [3 内側](03-internals.md)「CI のゲート」 |
| 不具合の並びがおかしい・ルールの編集が心配 | [6 トラブル](06-troubleshooting-maintenance.md)「既知の問題」 |

# 用語集

| 用語 | 意味 |
|---|---|
| **アセット** | ゲームの素材(テクスチャ・モデル・マテリアル・スクリプト・音)。`asset_id` は、対象フォルダからの相対パス |
| **producer(入力)** | アセットの集め方。`lqa`・`fs_scan`・`unity_asset` |
| **アダプタ(SourceAdapter)** | producer ごとの取り込み。`producer_id` と `scan()` を持つ。`@register` で登録 |
| **AssetRecord / CheckResult** | 取り込みの**共通の形**と、その検査 1 件 |
| **scan_run** | スキャン 1 回。status は running / success / failed |
| **追記専用(append-only)** | 過去の行を更新・削除しない。履歴の信頼性を保つ |
| **insight.db** | 唯一の真実の源(SQLite) |
| **ルール** | YAML(定義)+ `evaluate` 関数。エンジンは動的 import で呼ぶ |
| **動的 import** | 実行時に、文字列のモジュール名から `import` すること(`importlib.import_module`) |
| **DefectRecord / defect_records** | 不具合。「アセット × ルール」で 1 行 |
| **first_seen / last_seen / resolved** | 最初に見た回・最後に見た回・直った回 |
| **再発** | 直った不具合が、また出る(同じ行が open に戻る) |
| **偽の「直った」** | 見ていない(再評価していない)アセットの不具合を、出ないからと閉じてしまうこと |
| **重大度(severity)** | `info` < `warn` < `fail`(`SEVERITY_RANK`) |
| **トレンド集計** | 外れ値・分布・前回との差・時系列の推移。値を返すだけの関数 |
| **パーセンタイル(線形補間)** | 並べた値の p% の位置の値 |
| **z スコア / IQR** | 外れ値の 2 つの判定。z は平均・標準偏差、IQR は四分位 |
| **マスキング** | 外れ値が複数あると、平均・標準偏差が膨らみ、どれも外れ値に見えなくなること |
| **マニフェスト(report_manifest.json)** | 描画に依らない中間形式。出力はすべてここを経由 |
| **CI ゲート** | 不具合があれば、ビルドを落とす。終了コード 0 / 1 / 2 と `--fail-on` |
| **Webhook** | 結果を Slack などへ送る。`{"text": ...}` を POST |
| **ジョブ** | GUI の、別スレッドで動くスキャン。状態はメモリ |
| **Host の許可リスト / Origin の一致** | DNS rebinding・CSRF から、認証のないローカルの GUI を守る検査 |
| **ReDoS** | 悪意ある正規表現で、照合が極端に遅くなる攻撃 |
| **LOD** | 距離に応じた簡略モデル(LODGroup) |
| **孤立アセット** | シーン・プレハブ・マテリアルのどこからも、名前が参照されていないアセット |

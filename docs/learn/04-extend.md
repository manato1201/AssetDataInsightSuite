# 4. 拡張のレシピ

どれも「**データ(設定)→ 関数 → テスト**」の順で、小さく進めます。共通の形(`AssetRecord`)と、唯一の源(`insight.db`)は**変えない**のが原則です。

## レシピ 1: 新しい入力(アダプタ)を足す

講義[第 1 回](../lecture/01-ingest.md)の `ReadmeAdapter` が完成形です。

1. `ingest/adapters/<name>_adapter.py` に、`producer_id` と `scan(target_path, since)` を持つクラスを書き、`@register` を付ける。
2. `scan` が返す `AssetRecord` の `asset_id` は、**対象フォルダからの相対パス(`/` 区切り)**にする(マシンが違っても同じ ID)。
3. **`ingest/run_scan.py` が import する場所**に、新しいモジュールを足す(登録は import の副作用なので、import されないと辞書に載らない)。
4. 検査値(`checks`)は、`CheckResult(status, value, threshold, message)`。`value` は文字列で保存される。
5. **テスト**: 一時フォルダにファイルを作り、`scan` の結果(`asset_id`・種類・`since` の差分)を確かめる(`test_ingest.py` の形)。

## レシピ 2: 新しいルールを足す

講義[第 4 回](../lecture/04-output-testing-capstone.md)の「テクスチャが大きすぎる」が完成形です。

1. `rules/<name>.py` に `evaluate(context, rule_def) -> list[DefectRecord]`(`rule_def` の `params` から、しきい値・正規表現を読む)。
2. `rules/definitions/<name>.yaml`(`rule_id`・`module: rules.<name>`・`applies_to`・`severity`・`params`・`message`)。**エンジンは変えない**。
3. **判断できないものは、不具合にしない**(検査が無い・値が数値でない)。別のルールで拾う手もある。
4. **テスト**: 境界(ちょうど・1 つ手前)・対象外の種類・欠けた検査。
5. **YAML の `module`**: 今は検査が無い(任意のモジュールを import できる)。**`rules.` で始まるものだけ**を許すよう、`validate_definition_source` とエンジンの両方に検査を足すことを勧める([6 トラブル](06-troubleshooting-maintenance.md))。

## レシピ 3: 新しい集計を足す

1. `trend/aggregations.py` に、`(db, scan_run_id, ...)` を受けて**値(辞書・リスト)を返す**関数を足す(描画・書き込みはしない)。
2. `output/report_manifest.py` の `build_manifest` に、`builder.add_section(section_id, type, title, data)` を足す。
3. 新しい `type` なら、描画側(`static_html_adapter.py`・`excel_adapter.py`・`cli_adapter.py` の `section["type"]` の分岐)にも足す。
4. **履歴を使う集計**は、`status = 'success'` のスキャンだけを見る(`_recent_successful_run_ids`)。**テスト**: 履歴を作って問い合わせる(`test_trend.py` の形)。

## レシピ 4: 新しい出力を足す

マニフェストを**読んで**描くだけにする(集計を再計算しない)。`output/<name>.py` に `main()` を書き、`--db`・`--out` を受ける。外部へ送るもの(Webhook・チャット)は、**送信の失敗で CI を落とさない**(例外を捕まえ、`stderr` に出す)。秘密(URL・トークン)は**環境変数**で渡し、リポジトリに書かない。

## レシピ 5: GUI にルートを足す

`webapp/app.py` の `create_app` に `@app.route(...)` を足す。**状態を変える操作**(POST)は、Host・Origin の検査(`install_request_guard`)の内側に入る。**認証は無い**ので、危険な操作(ファイルを書く・任意のパスを読む)は足さない。パスを受け取るときは、**存在するディレクトリか**を確かめる(`/scan` と同じ)。

## 変更の前に

- **共通の形・追記専用のテーブル**を崩さない。
- 変更したら `pytest -q` と `python tools/check_docs.py`([5 テスト](05-testing.md))を通す。

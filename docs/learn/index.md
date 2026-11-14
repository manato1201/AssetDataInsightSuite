# AssetDataInsightSuite 学習資料(未完成・既知の問題のみ)

保守・拡張の実務編は**未作成**です。基礎は [講義](../lecture/index.md)(第 0〜4 回)、既存の技術解説は [TECHNICAL_GUIDE.md](../TECHNICAL_GUIDE.md) を参照してください。

## 既知の問題(講義の作成中にコードを読んで・動かして見つけたもの。コードは変えていない)

1. **不具合の並びが、重大度順にならない**: `fetch_defect_records` の `ORDER BY severity DESC` は文字列の順なので、`warn` → `info` → `fail` になり、**fail が最後**に来る(動かして確認済み)。重大度の順位(`SEVERITY_RANK`)で並べ替える必要がある。
2. **ルール YAML の `module` を検査しない**: GUI の編集(`/rules/<file>/edit`)は「YAML として読める・`rule_id` と `module` がある」だけを検査し、エンジンは `module` を `importlib.import_module` する。**任意のモジュールを import できる**。`params.pattern` も `re.compile` されるので ReDoS の余地がある。GUI は認証なし(Host・Origin の検査のみ)。直す案: `module` を `rules.` で始まるものに限る(保存時と読み込み時の両方)。
3. **`--fail-on info` は、info だけのとき 0 を返す**(`max_rank == 0` の扱い)。意図通りかは未確認。
4. **再発すると履歴が書き換わる**: 同じ行が open に戻り `resolved_run_id` が `NULL` になるため、`open_defect_count_over_time` は、直っていた期間も open と数える。`first_seen` も最初のまま。開閉の区間を持つ表が要る。
5. **`defect_records` は `UNIQUE(asset_id, rule_id)`**: 入力(producer)が違っても、同じ `asset_id` は 1 行にまとまる。
6. **孤立アセットの判定は名前の文字列照合**: Unity が GUID で参照するアセットは、使われていても孤立と判定されうる。
7. **前回との差は、サイズと更新日時だけ**を見る(中身の変更は検出しない)。
8. **z スコアは、n ≤ 4 では外れ値を検出できず**(最大値 √(n−1))、外れ値が複数あるとマスキングされる。
9. `check_results.value` は TEXT。数値集計では `float()` に直し、直せないものは黙って飛ばす。

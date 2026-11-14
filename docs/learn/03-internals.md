# 3. 内側のしくみ

講義(第 1〜4 回)の補足として、**書き込みの流れ・解消の判定・マニフェスト・Webhook・ジョブ・CI** の中身を説明します。

## 1. スキャンの書き込み(`run_scan`)

1. `scan_runs` に `status='running'` の行を作る。
2. アダプタの `scan()` で `AssetRecord` のリストを作り、`insert_asset_records` で `asset_records` と `check_results` に書く。
3. 成功なら `finish_scan_run(..., 'success')`。**例外なら**、`failed` を書いて**明示的にコミット**してから再送出(`open_db` は例外でロールバックするため)。

**検査値は TEXT**で保存される(`str(value)`)。数値として使うときは読み出して `float()` に直す(`outliers`・`texture_resolution_histogram` は、直せないものを**黙って飛ばす**)。

## 2. 不具合の upsert と解消(`run_checks`)

- ルールを全部走らせ、返った `DefectRecord` を `upsert_defect_record`: 既にある(`asset_id`・`rule_id`)なら `last_seen` を進め、`resolved` を `NULL` に戻す(**再発**)。無ければ新規。
- **解消**: 「直前に open で、今回出なくなった」不具合を閉じる。ただし対象は、**今回再評価したアセット**(今回のスキャンに載ったもの)と、**削除が確認されたアセット**(同じ入力の前回との差の `removed_ids`)だけ。他の入力のアセットは、**見ていない**ので閉じない(偽の「直った」を出さない)。

## 3. マニフェスト(`report_manifest.json`)

`ReportManifestBuilder` が、`{manifest_version, scan_run_id, generated_at, sections:[{section_id, type, title, data}]}` を作ります。`build_manifest` が、集計関数を呼んで、セクションを足す唯一の場所です(`scan_diff`・サイズ分布・ドットチャート・`defect_summary` ほか)。

- 差分の id リストは `DIFF_ID_PREVIEW_LIMIT = 50` で切る。**件数は常に正確**。
- 描画側は `type`(`diff_summary`・`bar_chart`・`table`・`dot_chart`)ごとの描き方だけを持つ。

## 4. CI のゲート(終了コード)

`evaluate_exit_code(defect_rows, fail_on)`: 最大の重大度の順位(`SEVERITY_RANK`)と、`--fail-on` の順位を比べる。`0` = 基準未満、`1` = warn、`2` = fail。**実行時の例外も `2`** を返す(fail 検出と区別できない。[6 トラブル](06-troubleshooting-maintenance.md))。CI では、`--fail-on fail` にして、warn は通すのが現実的。

## 5. Webhook(`webhook_notify`)

`{"text": "..."}` を POST するだけ(Slack・Mattermost 互換。Teams は Power Automate の「HTTP 要求の受信」で受ける)。本文は、**fail の不具合の先頭 10 件**と件数、詳細へのリンク。`notify_if_needed` が、閾値(`--fail-on`)以上があるときだけ送る。**送信の失敗は CI を失敗させない**。

## 6. GUI のジョブ(`webapp/jobs.py`)

`POST /scan` は、別スレッド(`daemon=True`)で `run_scan`(と、任意で `run_checks`)を走らせ、すぐ `job_id` のページへ移ります。進みは `/jobs/<id>/status.json` のポーリング。状態は**メモリ**(`MAX_TRACKED_JOBS = 50`・古いものから捨てる)。例外は `job.error` に入れて画面に出す。

## 7. GUI の守り

`webapp/security.py`: **Host の許可リスト**(DNS rebinding)と、変更操作の **Origin の一致**(CSRF)。**認証ではない**(ユーザー・役割・監査は無い)。`POST /scan`(指定ディレクトリを走査)・`POST /rules/<file>/edit`(ルールの書き換え)・`POST /runs/<id>/notify`(Webhook)が、保護の対象。複数人で使うなら、認証と役割が要る(姉妹のツール群の `hub/auth.py` と同じ型を移せる)。

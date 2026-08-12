# AssetDataInsightSuite 設計書

**設計指標: データ品質の継続的可視化(defect検知とtrend把握を単一パイプライン・単一データモデルで)**
作成日: 2026-08-11 / 想定規模: 中規模(取り込みアダプタ3種+検知+集計+出力アダプタ3種+CI連携)

---

## Phase 0: コンセプト・要件定義

### 目的
CEDEC講演資料に触発された新規ツール構想のうち、ユーザー原案item3(解析ツール)・item4(データ不備検出ツール)・item5(データ傾向確認ツール)・item6(3,4,5を定期実行するCI)を対象とする。item3の目的は文字通り「不備検知+傾向確認」であり、これはitem4・item5そのものである。加えてitem6は「3,4,5を定期実行するCI」と明言している。つまり4項目は目的別の4本の別ツールではなく、**単一パイプライン(取り込み→検知→集計→定期実行)の4断面**である。本書はこれを1つのデータモデル・1つのパイプラインとして統合設計する。

| 元アイデア | 内容 | 本書での位置づけ |
|---|---|---|
| item3 | 解析ツール(不備検知+傾向確認) | Suite全体の目的そのもの |
| item4 | データ不備検出(命名規則違反/コーディング規則違反/個別修正箇所/Material未使用/LOD未設定/エラー一覧化) | Phase 2: 不具合検知モジュール |
| item5 | データ傾向確認(テクスチャ解像度分布/LOD・フェード設定状況/設定ばらつきと平均より重いデータ/サイズ・拡張子・更新日分布の可視化) | Phase 3: トレンド分析モジュール |
| item6 | 3,4,5を定期実行するCI、Kibana/CSSアニメーションで可視化 | Phase 5: CI定期実行+Kibana連携 |

### 要求機能
- 不備検知: 命名規則違反、コーディング規則違反、個別修正箇所、Material未使用、LOD未設定、エラー一覧化
- 傾向確認: テクスチャ解像度分布、LOD/フェード設定カバレッジ、設定ばらつきと平均より重いデータの特定、サイズ・拡張子・更新日分布の可視化
- Phase 2〜3を定期的にCI実行し、履歴として蓄積
- Kibana連携(または軽量フォールバックとしての静的HTML+CSSアニメーション)
- CLI(CIゲート用)とExcel(人間向けレポート)の2出力

### 入力契約と正準スキーマ
入力契約の一次リファレンス実装として、`LoreDesktopAndWebSystem\IMPROVEMENT_PLAN.md` Phase 6で確定済みの`.lqa`(Lore Quality Analysis)サイドカー形式を**名指しで**引用する。`.lqa`は`{base_dir}/lqa/{repo_slug}/{path}.lqa.json`に配置され、コミット/変更のたびに`records[]`へ追記されるバージョン付きレコードで、`checks: { [checkId]: result }`という可変マップ(固定structにしない)を持つ。ただし**本Suite自体はLore専用ツールではない**。`.lqa`はSuiteが受け付ける複数プロデューサーのうちの一つとして扱い、汎用設計を貫く。`.lqa`の可変マップ思想をそのまま内部正準スキーマへ昇格させる:
```python
# core/schema.py
from dataclasses import dataclass, field

@dataclass
class CheckResult:
    status: str                          # "pass" | "warn" | "fail" | "info"
    message: str | None = None
    value: float | str | None = None
    threshold: float | str | None = None

@dataclass
class AssetRecord:
    asset_id: str                        # プロデューサー内で安定な一意キー(正規化済み相対パスが基本)
    asset_type: str                      # "texture" | "model" | "material" | "audio_bank" | ...
    source_producer: str                 # "lqa" | "fs_scan" | "unity_asset" | ...
    collected_at: str                    # ISO8601、取り込み実行時刻
    size_bytes: int | None
    extension: str | None
    last_modified: str | None            # ISO8601
    checks: dict[str, CheckResult] = field(default_factory=dict)
```
`.lqa`の`records[]`はLore側が保持する独自の履歴(コミット単位)であり、Suite側の`scan_run`履歴(Phase 1)とは責務が異なる。Ingestion Normalizerは各`scan_run`ごとに`.lqa`の`records[]`から最新1件(または`since`以降の新規分)だけを`AssetRecord`へ写像し、`.lqa`自体の履歴管理には関与しない。

### 非機能要件
- **本番データに絶対に触れない**: Loreの「静的解析サブシステムは`lorehub.db`/`blobs/`に一切書き込まない」という分離原則を、Suite全体の原則に格上げする。全アダプタは読み取り専用で、対象プロジェクトへの書き込みAPIを一切呼ばない
- **CI冪等性**: 同一入力に対する再実行で`asset_records`/`check_results`の値が変化しない(`scan_runs`に新規行が増える点のみが差分)
- **増分スキャン対応**: `since`パラメータで前回`scan_run`以降の差分のみ処理できること。全件再走査をデフォルト挙動にしない

### 前提・制約
- 履歴は追記専用(over-write禁止)。`scan_runs`テーブルは常に新規行としてINSERTのみで運用し、過去行のUPDATEは行わない。Phase 3のtrend集計が複数の過去`scan_run_id`を跨いで参照する前提であり、過去データの上書きは不可逆にtrendを破壊する
- Suiteは分析専用ツールであり、対象プロジェクトのアセット・シーンファイルへの書き込み権限を要求しない。不備を検知しても是正は人間(またはCIゲートによる差し戻し)の仕事とし、Suiteが自動修正することはない

### アンチパターン(全フェーズ共通)
- item3/4/5/6を4つの別ツールとして作り始めない。1パイプライン・1データモデルが本書の核
- 初日から「全プロデューサー・全エンジン対応」に手を広げない。最大のリスクはスコープクリープであり、fs-scan+`.lqa`をMVPとしてから拡張する順序を厳守する
- `.lqa`をSuite専用の特別なフォーマットとして扱わない。あくまで複数プロデューサーの一つ
- `checks`/`CheckResult`を固定structにしない。新規チェック追加のたびにスキーマバージョンを上げる運用にもしない(`.lqa`と同じ拡張容易性の思想)

**検証チェックリスト:**
- [ ] item3〜6が「4つの独立ツール」ではなく「1パイプラインの4断面」として本書全体に一貫して反映されている
- [ ] `AssetRecord`/`CheckResult`が`.lqa`の`checks`可変マップ思想をそのまま継承している
- [ ] `.lqa`が「一次リファレンス実装」であり「Suite専用フォーマットではない」ことの両方が明記されている
- [ ] 「本番データ非接触」がLoreの分離原則からSuite全体原則への格上げとして明記されている

---

## Phase 1: 正規化取り込み層(Ingestion Normalizer)(最優先・全フェーズの基盤)

Phase 2〜5は全てこの層が生成する`AssetRecord`/`insight.db`の上に構築される。ここが不安定だと以降のフェーズ全てが意味を失う。

**実装内容:**
1. アダプタ3種を`ingest/adapters/`配下に実装する:
   - `ingest/adapters/lqa_adapter.py` — `.lqa`パーサ。`records[]`の最新エントリを`AssetRecord`へ写像し、`conversion_errors`は`check_id="conversion_error"`として`checks`マップに合流させる
   - `ingest/adapters/fs_scan_adapter.py` — 素朴なファイルシステムスキャン(拡張子/サイズ/mtime)。専用メタデータを持たない全プロデューサー共通のフォールバック
   - `ingest/adapters/unity_asset_adapter.py` — `.meta`ファイル・TextureImporter設定・LODGroupコンポーネントを解析
2. アダプタはプラグイン登録方式(レジストリ辞書)とし、将来のプロデューサー追加が`ingest/adapters/`の新規ファイル追加だけで完結するようにする:
   ```python
   # ingest/adapters/registry.py
   class SourceAdapter(Protocol):
       producer_id: str
       def scan(self, target_path: str, since: str | None) -> list[AssetRecord]: ...

   ADAPTER_REGISTRY: dict[str, SourceAdapter] = {}

   def register(adapter: SourceAdapter) -> SourceAdapter:
       ADAPTER_REGISTRY[adapter.producer_id] = adapter
       return adapter

   # ingest/adapters/lqa_adapter.py
   @register
   class LqaAdapter:
       producer_id = "lqa"
       def scan(self, target_path, since=None) -> list[AssetRecord]:
           ...  # {base_dir}/lqa/{repo_slug}/{path}.lqa.json を走査
   ```
3. ストレージは SQLite `insight.db`。`scan_runs`/`asset_records`/`check_results`の3テーブルで構成し、`scan_run_id`を`check_results`にも直接FKとして持たせることで、Phase 3のtrend集計が`asset_records`とのJOINなしに`GROUP BY scan_run_id`だけで書けるようにする:
   ```sql
   -- insight.db (SQLite)
   CREATE TABLE scan_runs (
       scan_run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
       started_at      TEXT NOT NULL,          -- ISO8601
       finished_at     TEXT,
       source_producer TEXT NOT NULL,          -- 'lqa' | 'fs_scan' | 'unity_asset'
       tool_version    TEXT NOT NULL,
       status          TEXT NOT NULL           -- 'running' | 'success' | 'failed'
   );
   CREATE TABLE asset_records (
       asset_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
       scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(scan_run_id),
       asset_id        TEXT NOT NULL,
       asset_type      TEXT NOT NULL,
       source_producer TEXT NOT NULL,
       size_bytes      INTEGER,
       extension       TEXT,
       last_modified   TEXT,
       collected_at    TEXT NOT NULL
   );
   CREATE TABLE check_results (
       check_result_id INTEGER PRIMARY KEY AUTOINCREMENT,
       asset_record_id INTEGER NOT NULL REFERENCES asset_records(asset_record_id),
       scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(scan_run_id),
       check_id        TEXT NOT NULL,          -- .lqaのchecksマップのキーがそのまま入る
       status          TEXT NOT NULL,          -- 'pass' | 'warn' | 'fail' | 'info'
       value           TEXT,
       threshold       TEXT,
       message         TEXT
   );
   -- asset_records(scan_run_id, asset_id) / check_results(scan_run_id, check_id) に複合インデックスを張る
   ```
4. `scan_runs`はINSERT専用(Phase 0の前提を実装レベルで担保)。`status='failed'`で終わったrunも削除・上書きせず残し、失敗自体を履歴として追跡できるようにする

**検証チェックリスト:**
- [ ] `.lqa`固定フィクスチャ・`fs_scan`固定フィクスチャの双方が`AssetRecord`へ正しく正規化される
- [ ] 同一入力への2回目の実行で`asset_records`/`check_results`の値が変化しない(冪等性)
- [ ] 未知の`checkId`を持つ`.lqa`を読み込んでもエラーにならない(可変マップの実証)
- [ ] `ADAPTER_REGISTRY`に新規アダプタを1ファイル追加するだけで登録され、既存コードの変更が不要である

---

## Phase 2: 不具合検知モジュール(item4対応・優先度: 高)

**実装内容:**
1. ルール群は全てYAML設定駆動とし、ルールIDや閾値のハードコードを禁止する。ルールモジュールは`rules/`配下:
   - `rules/naming_convention.py`(regexベース)
   - `rules/unused_material.py`(シーン/プレハブの参照グラフとのクロスチェック)
   - `rules/lod_missing.py`
   - `rules/orphan_and_individual_fix.py`(孤立アセット検知+個別修正箇所のオーバーライド)
2. YAML例(`unused_material`も同型 — `applies_to: [material]`, `params.reference_graph_source: scene_and_prefab`でシーン/プレハブ参照グラフとのクロスチェックを指定するのみで、regexエンジンとは別の評価関数を`module`が指すだけの違い):
   ```yaml
   # rules/definitions/naming_convention.yaml
   rule_id: naming_convention
   module: rules.naming_convention
   applies_to: [texture, model, material]
   severity: warn
   params:
     pattern: "^(T_|SM_|M_)[A-Za-z0-9_]+$"
   message: "命名規則(接頭辞 T_/SM_/M_)に違反しています"
   ```
   item4の「コーディング規則違反」は専用モジュールを新設せず、`naming_convention.py`と同じregexルールエンジンをスクリプトアセット(`.cs`等)の命名/ヘッダパターンへ適用する形で扱う。モジュールを増やすほど拡張性は上がらず保守コストだけが増える(アンチパターン参照)。
3. 「個別修正箇所」は汎用ルールでは拾えない一点物の指摘であるため、`rules/orphan_and_individual_fix.py`側にasset_id直接指定のオーバーライドリストを持たせる:
   ```yaml
   # rules/definitions/individual_overrides.yaml
   rule_id: individual_fix_required
   module: rules.orphan_and_individual_fix
   severity: warn
   overrides:
     - asset_id: "Assets/Characters/hero_rig.fbx"
       message: "テクスチャ参照が旧命名のまま。次回リギング更新時に個別対応"
       suggested_fix: "hero_rig_v2への差し替え待ち"
   ```
4. 検知結果は`DefectRecord`として`insight.db`に永続化する(`check_results`とは別テーブル、ルール評価結果専用):
   ```python
   # rules/schema.py
   @dataclass
   class DefectRecord:
       asset_id: str
       rule_id: str
       severity: str                  # "info" | "warn" | "fail"
       message: str
       suggested_fix: str | None
       first_seen_run_id: int         # scan_runs.scan_run_id
       last_seen_run_id: int          # scan_runs.scan_run_id
   ```
   同一`(asset_id, rule_id)`の組が既存であれば`last_seen_run_id`のみ更新し、存在しなければ`first_seen_run_id = last_seen_run_id = 今回のscan_run_id`で新規作成する。これがPhase 3の「いつから壊れているか」トレンドへの供給元になる。item4の「エラー一覧化」はPhase 2単体の出力ではなく、`DefectRecord`全件をPhase 4の`report_manifest.json`(`defect_summary`セクション)として一覧化する形で実現する。検知(Phase 2)と一覧化(Phase 4)の責務を分離する。

**検証チェックリスト:**
- [ ] 全ルールがYAML定義から読み込まれ、ルールIDや閾値がPythonコード中にハードコードされていない
- [ ] 同一defectを2回連続で検知した際、`first_seen_run_id`が変化せず`last_seen_run_id`のみ更新される
- [ ] `individual_overrides.yaml`のasset_id指定が汎用ルールと同じ`DefectRecord`形式で出力される
- [ ] `unused_material`が実際にシーン/プレハブ参照グラフとクロスチェックし、参照ゼロのマテリアルのみを検出する

---

## Phase 3: トレンド分析モジュール(item5対応・優先度: 中、Phase 1完了後はPhase 2と並行着手可能)

**集計対象:** テクスチャ解像度ヒストグラム、LOD/フェード設定カバレッジ率、設定ばらつき(z-score/IQRベースの外れ値検知で「平均より重いデータ」を特定)、サイズ分布、拡張子別集計、最終更新日分布。

**実装方針:** Phase 1のテーブルをそのまま時系列クエリするだけであり、**新規ストレージは作らない**。全テーブルに`scan_run_id`を持たせたPhase 1の設計上の帰結として、`WHERE scan_run_id = ?`や`GROUP BY scan_run_id`だけでtrendが取れる。集計ロジック(データを返す)とチャート描画を分離する。テスト可能性の確保と、Phase 4での再利用(CLI/Excel双方が同じ集計関数を呼ぶ)のためである:
```python
# trend/aggregations.py -- SQLを叩いてデータを返すのみ。描画は持たない
def texture_resolution_histogram(db, scan_run_id: int, bucket_edges: list[int]) -> dict[str, int]:
    """asset_type='texture'のcheck_id='resolution_px'をビン分けして返す"""

def lod_fade_coverage(db, scan_run_id: int) -> dict[str, float]:
    """asset_type='model'全体に対しlod_group_configured/fade_configuredがpassの比率"""

def outliers(db, scan_run_id: int, check_id: str, method: str = "zscore", threshold: float = 2.0) -> list[dict]:
    """value列の外れ値(z-score または IQR)を「平均より重いデータ」として返す"""

def size_distribution(db, scan_run_id: int) -> dict[str, int]: ...
def extension_breakdown(db, scan_run_id: int) -> dict[str, int]: ...
def last_modified_distribution(db, scan_run_id: int, bucket: str = "month") -> dict[str, int]: ...

# trend/charts.py -- aggregations.pyの戻り値のみを受け取って描画する。SQLは直接叩かない
def render_bar_chart(data: dict[str, int], title: str): ...
```

**検証チェックリスト:**
- [ ] 全集計関数が新規テーブルを作らず、Phase 1の3テーブルに対するSELECTのみで実装されている
- [ ] `outliers`のz-score/IQR両方式が既知の合成外れ値データセットで正しく検出する
- [ ] `aggregations.py`の関数群が単体テストのみ(DB接続以外の外部依存なし)で検証できる
- [ ] 同一`scan_run_id`に対する2回の集計呼び出しで完全に同一の結果を返す

---

## Phase 4: 出力アダプタ層(CLI/Excel/統一フォーマット)(実装コストは小、Phase 2・3の関数を呼ぶだけ)

**実装内容:**
1. CLIアダプタ(`output/cli_adapter.py`): CIゲート用にexit codeを使い分ける — `0`(defectなし)/ `1`(warn以上を検知)/ `2`(fail検出、または実行時エラー)
2. Excelアダプタ(`output/excel_adapter.py`): `openpyxl`を用い、Phase 3の集計関数とPhase 2の`DefectRecord`を直接呼び出してシートへ書き出す。独自の計算ロジックは一切持たない
3. 「統一出力フォーマット」= `report_manifest.json`。section/type/dataのレンダラー非依存な中間形式とし、CLI/Excel/Kibana/将来のHTMLは全員これを読むだけにする:
   ```json
   {
     "manifest_version": "1.0",
     "scan_run_id": 42,
     "generated_at": "2026-08-11T09:00:00Z",
     "sections": [
       { "section_id": "texture_resolution_histogram", "type": "bar_chart", "title": "テクスチャ解像度分布",
         "data": { "labels": ["256", "512", "1024", "2048", "4096+"], "values": [12, 48, 120, 30, 4] } },
       { "section_id": "defect_summary", "type": "table", "title": "不具合一覧(severity>=warn)",
         "data": { "columns": ["asset_id", "rule_id", "severity", "first_seen_run_id"],
                    "rows": [["Assets/Textures/rock_d.png", "naming_convention", "warn", 39]] } }
     ]
   }
   ```
4. `report_manifest.json`の`sections`配列は、LearningQt改善計画書の`manifest.json`(`videos/<id>/metadata.json`)における`pipeline`配列と同型のパターンとして直接引用する。`pipeline`配列は`ManifestWriter`(`engine/src/manifest/manifest_writer.h/.cpp`)が唯一のプロデューサーとなり、フェーズ完了ごとに`StageResult{stage, success, duration_sec, error_message}`相当のエントリを1件ずつ追記する設計であった。`report_manifest.json`の`sections`も同じく「唯一のプロデューサー」原則(`ManifestWriter`役を担う単一の`ReportManifestBuilder`のみが書き込み、Phase 2/3の各モジュールは直接JSONへ書き込まない)を踏襲し、集計・検知が完了するたびに1セクションを追記する

**検証チェックリスト:**
- [ ] CLIアダプタのexit codeが0/1/2の3値をseverityに応じて正しく返す
- [ ] Excelアダプタが独自の集計・判定ロジックを持たず、Phase 2/3の関数の戻り値をそのままシートへ転記していることをコードレビューで確認
- [ ] 同一`scan_run_id`に対しCLIとExcelが同じ集計値を出力する
- [ ] `report_manifest.json`への書き込みが単一の`ReportManifestBuilder`経由のみで、他モジュールからの直接書き込みがない

---

## Phase 5: CI定期実行+継続蓄積+Kibana連携(item6対応・優先度: 中〜低、MVP後の仕上げフェーズ)

**実装内容:**
1. GitHub Actions cronによる定期実行。Research-Collectorの`daily_collect.yml`(人手トリガーに依存しない無人実行の実例)を直接踏襲する:
   ```yaml
   # .github/workflows/insight-scan.yml
   on:
     schedule:
       - cron: "0 21 * * *"   # Research-Collectorのdaily_collect.ymlと同じUTC運用(21:00 UTC = AM6:00 JST)
     workflow_dispatch: {}
   jobs:
     scan:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - run: python -m ingest.run_scan --all-producers
         - run: python -m rules.run_checks
         - run: python -m output.cli_adapter --fail-on warn
   ```
2. 失敗通知は**Research-Collectorのラベル付きIssue自動作成+自動クローズパターンを直接引用**する。`daily_collect.yml` L68-100のIssue自動作成(既存open Issueをラベル検索してから新規作成する重複防止ガード込み)をそのまま踏襲し、labelは`insight-scan-failed`とする。復旧時の自動クローズは`refresh_auth.ps1` L45-53と同型のロジック(次回成功run内で`gh issue list --label insight-scan-failed --state open`を検索し、存在すれば`gh issue close`)をCIジョブ内のクローズステップとして実装する
3. Kibana連携は「Suiteそのものが ELK スタックを抱える」設計にはしない。`output/ndjson_export.py`がElasticsearch `_bulk` API互換のNDJSONを吐く**エクスポートアダプタ**としてスコープを絞る:
   ```python
   # output/ndjson_export.py
   def export_ndjson(db, scan_run_id: int, index_name: str = "asset-insight-checks"):
       for row in query_check_results(db, scan_run_id):
           yield json.dumps({"index": {"_index": index_name}})
           yield json.dumps({"scan_run_id": row.scan_run_id, "asset_id": row.asset_id,
                              "check_id": row.check_id, "status": row.status,
                              "value": row.value, "collected_at": row.collected_at})
   ```
   Kibana側のインデックス作成・ダッシュボード定義はチーム側の運用に委ね、Suiteはインフラを持たない
4. 「CSSアニメーション」要求は、Kibanaを立てられないチーム向けの軽量フォールバックとして明記する。`output/static_html_adapter.py`が`report_manifest.json`を読み、外部CDN依存もJSフレームワークもない静的HTML(棒グラフの`width`/`height`を`transition`で遷移させる程度のCSSアニメーション)を`reports/{scan_run_id}/index.html`に生成する

**検証チェックリスト:**
- [ ] `insight-scan.yml`が`workflow_dispatch`(手動実行)・`schedule`(定期実行)の両方で成功する
- [ ] CIジョブ失敗時に`insight-scan-failed`ラベルのIssueが自動作成され、同一失敗中は重複作成されない
- [ ] 次回run成功時に該当Issueが自動クローズされる
- [ ] `export_ndjson`の出力がElasticsearch `_bulk` API形式(action行+ソース行の交互構造)として妥当である
- [ ] `static_html_adapter.py`が外部ネットワーク接続なしでレポートを生成できる(オフライン動作の確認)

---

## Final Phase: 統合検証

- [ ] `.lqa`固定フィクスチャ1件・`fs_scan`固定フィクスチャ1件を取り込み、両方が正準`AssetRecord`スキーマに正規化されること
- [ ] 同一フィクスチャに対する2回目の実行が冪等であること(`scan_runs`に新規行は増えるが`asset_records`/`check_results`の値は変化しない)
- [ ] `AssetRecord`/`CheckResult`/`DefectRecord`/`report_manifest.json`の4スキーマが本書とコード内docstring双方に文書化されていること
- [ ] CLIアダプタとExcelアダプタが同一`scan_run_id`に対し同じ集計値を出す(`report_manifest.json`のスナップショット比較で検証)
- [ ] `workflow_dispatch`による手動実行、および週次cronによるスケジュール実行の双方が成功し、後者が既存履歴を破壊せず`scan_runs`に追記されること
- [ ] `ndjson_export.py`が出力するNDJSONがElasticsearch `_bulk` API形式として妥当であること

---

## 相互参照ドキュメント

- `LoreDesktopAndWebSystem\IMPROVEMENT_PLAN.md` Phase 6の`.lqa`形式(独自拡張子サイドカー、`checks`可変マップ)は、本書の入力契約における一次リファレンス実装である(Phase 0・Phase 1)
- `Research-Collector\IMPROVEMENT_PLAN.md`(実在・実装済み)の`daily_collect.yml`によるCI cron無人実行、および`daily_collect.yml`/`refresh_auth.ps1`によるラベル付きIssue自動作成+自動クローズパターンは、Phase 5のCI定期実行・失敗通知の直接の前例である
- LearningQt改善計画書の`manifest.json`/`ManifestWriter`(フェーズ完了ごとに1エントリを追記する設計)は、Phase 4の「統一マニフェスト」原則(`report_manifest.json`の`sections`配列)の引用元である
- Sound Middlewareのサウンドアセット(バンク/wavファイル)は、Phase 1のIngestion Normalizerに新規プロデューサーとして追加されうる候補である
- 本SuiteのCIジョブ(`insight-scan.yml`)自体が、別文書「ProfilingTool設計書」の計測対象になりうる
- 別文書「ToolOrchestrationHub設計書」が、Phase 5の障害通知(Issue自動作成)を将来的に吸収する可能性がある
- 別文書「VisualRegressionQATool設計書」のDB設計(CaptureInstruction→CapturedImage→DiffImage→EvaluationResultの追記専用チェーン)は、本書Phase 1の`scan_runs`追記専用パターンと設計思想が同系であり、両ツールでスキーマ設計の考え方を揃える

**優先度注記:** 手堅いエンジニアリング。新規性のリスクは低く、SQLite・YAML駆動ルール・openpyxl・GitHub Actions cronはいずれも実績のある技術である。最大のリスクは初日から「全プロデューサー・全エンジン対応」に手を広げるスコープクリープであり、fs-scan+`.lqa`をMVPとしてから拡張する順序を厳守する。Phase 1(正規化取り込み層)さえ安定させれば、Phase 2〜5は互いに疎結合(検知・集計・出力・CIがそれぞれ別のPhase 1の読み取りクライアントに過ぎない)であるため、着手順序の融通は利く。

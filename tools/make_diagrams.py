"""docs/diagrams/ の構成図(SVG)を作る。直すときは、ここを直して `python tools/make_diagrams.py` を実行する。

  architecture.svg   全体の構成(入力・取り込み・insight.db・ルール・集計・出力・GUI)

部品は tools/svgkit.py。座標は手で決める。決まり: ①矢印はカードの横(か上)から出入り(カードの下には文字がある)
②縦に渡るときは、カードの間のすき間を通る ③流れの説明は、図に詰めず、本文に書く。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from svgkit import Diagram  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "diagrams"


def architecture() -> Diagram:
    d = Diagram(1700, 1080, "AssetDataInsightSuite の構成",
                "入力(.lqa・ファイルシステム・Unity)を、アダプタが共通の形にそろえて insight.db に追記する。YAML のルールが不具合を検知して defect_records に書き、"
                "集計がトレンドを計算する。結果は、描画に依らない report_manifest.json にまとめ、CI のゲート・Excel・NDJSON・静的 HTML・Webhook に出す。GUI は同じ DB を読む。")
    d.text(40, 44, "AssetDataInsightSuite — 構成", cls="hd")
    d.text(40, 66, "青=主な流れ / 灰の破線=補助。唯一の真実の源は insight.db(SQLite)。取り込みだけが入力の種類を知っている", cls="note")

    d.group(40, 100, 250, 640, "SOURCES — 入力", color="gray")
    lqa = d.card(150, 190, "doc", ".lqa サイドカー", "producer: lqa")
    fs = d.card(150, 340, "folder", "ファイルシステム", "producer: fs_scan")
    uni = d.card(150, 490, "extension", "Unity アセット", "producer: unity_asset\n(.meta・シーン・プレハブ)")

    d.group(480, 100, 820, 640, "PIPELINE — insight.db を中心に", color="teal")
    ing = d.card(640, 340, "gear", "ingest/", "SourceAdapter(Protocol)\n@register のプラグイン")
    db = d.card(900, 340, "db", "insight.db", "scan_runs・asset_records\ncheck_results・defect_records")
    rules = d.card(1160, 190, "check", "rules/", "YAML + evaluate()\n解消は再評価した所だけ")
    trend = d.card(1160, 490, "chart", "trend/", "外れ値(z・IQR)・分布\n前回との差・推移")
    d.text(500, 722, "テーブルは追記専用(defect_records だけ、不具合の状態を更新する)。失敗したスキャンも status=failed で残す", cls="note")

    d.group(1360, 100, 300, 640, "OUTPUT — 出力", color="blue")
    man = d.card(1510, 340, "list", "report_manifest.json", "描画に依らない中間形式\n(型つきのセクション)")
    out = d.card(1510, 540, "terminal", "CLI・Excel・NDJSON", "静的 HTML・Webhook\nCI は終了コード 0 / 1 / 2")

    d.group(480, 790, 820, 250, "GUI — Flask(webapp/)・ローカル専用・認証なし", color="purple")
    d.card(640, 880, "terminal", "スキャンの起動", "別スレッドのジョブ\n進みはポーリング")
    d.card(900, 880, "list", "不具合・推移", "一覧・CSV・グラフ")
    d.card(1160, 880, "gear", "ルールの編集", "YAML を保存\n(module は未検証)")

    d.arrow([lqa.right, (540, 190), (540, 340), ing.left], "共通の形にそろえる", at=0)
    d.arrow([fs.right, ing.left], "", at=0)
    d.arrow([uni.right, (540, 490), (540, 340), ing.left], "", at=0)
    d.arrow([ing.right, db.left], "追記", at=0)
    d.arrow([db.right, (1040, 340), (1040, 190), rules.left], "読む / 不具合を書く", both=True, at=2, dy=-10)
    d.arrow([(1040, 340), (1040, 490), trend.left], "SELECT", at=1, dx=24, dy=0)
    d.arrow([trend.right, (1330, 490), (1330, 340), man.left], "集計の結果", at=1, dx=-34, dy=0)
    d.arrow([man.right, (1620, 340), (1620, 540), out.right], "描画", at=1, dx=-24, dy=0)
    return d


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "architecture.svg").write_text(architecture().svg(), encoding="utf-8")
    print("wrote", OUT / "architecture.svg")


if __name__ == "__main__":
    main()

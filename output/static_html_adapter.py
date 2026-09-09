"""Static HTML/CSS fallback adapter.

Kibana can't always be stood up by every team; this renders
`report_manifest.json` into a single self-contained `index.html` per
scan_run — no external CDN, no JS framework, works fully offline. Visual
language follows `AssetDataInsightSuite_UI_DESIGN.md` (Revolut design
analysis): a true-black storytelling hero band for the run summary, a white
catalogue band with feature-card-styled sections, pill badges for severity,
and CSS `transition`-driven bar growth in place of a charting library.
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path

from core import db as db_module
from output.report_manifest import build_manifest
from trend.charts import render_dot_chart_svg

_SEVERITY_COLOR = {
    "fail": "#e23b4a",
    "warn": "#ec7e00",
    "info": "#428619",
}

_STYLE = """
:root {
  color-scheme: dark light;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
  background: #ffffff;
  color: #191c1f;
}
.hero {
  background: #000000;
  color: #ffffff;
  padding: 64px 24px;
}
.hero-inner, .catalogue-inner {
  max-width: 1200px;
  margin: 0 auto;
}
.hero h1 {
  font-family: 'Aeonik Pro', 'Inter Display', 'Söhne', sans-serif;
  font-weight: 500;
  font-size: clamp(32px, 5vw, 64px);
  line-height: 1.05;
  letter-spacing: -0.02em;
  margin: 0 0 12px 0;
}
.hero .meta {
  color: rgba(255,255,255,0.72);
  font-size: 16px;
  margin-bottom: 24px;
}
.badge-row { display: flex; gap: 8px; flex-wrap: wrap; }
.badge {
  display: inline-flex;
  align-items: center;
  border-radius: 9999px;
  padding: 4px 12px;
  font-size: 13px;
  font-weight: 600;
}
.badge-primary { background: #494fdf; color: #ffffff; }
.badge-neutral { background: #16181a; color: #ffffff; border: 1px solid rgba(255,255,255,0.12); }
.catalogue {
  background: #f4f4f4;
  padding: 64px 24px 96px;
}
.section-title {
  font-family: 'Aeonik Pro', 'Inter Display', 'Söhne', sans-serif;
  font-weight: 500;
  font-size: 24px;
  letter-spacing: 0;
  margin: 0 0 16px 0;
  color: #191c1f;
}
.card {
  background: #ffffff;
  border: 1px solid #e2e2e7;
  border-radius: 20px;
  padding: 32px;
  margin-bottom: 24px;
}
.bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.bar-label { width: 120px; flex-shrink: 0; font-size: 14px; color: #505a63; text-align: right; }
.bar-track { flex: 1; background: #f4f4f4; border-radius: 8px; height: 22px; overflow: hidden; }
.bar-fill {
  height: 100%;
  background: #494fdf;
  border-radius: 8px;
  width: 0;
  animation: growBar 900ms ease-out forwards;
  animation-delay: 120ms;
}
.bar-value { width: 56px; flex-shrink: 0; font-size: 14px; font-weight: 600; color: #191c1f; }
@keyframes growBar { from { width: 0; } to { width: var(--bar-width); } }

.diff-row { display: flex; gap: 12px; flex-wrap: wrap; }
.diff-tile { flex: 1; min-width: 140px; border-radius: 12px; padding: 16px; background: #f4f4f4; }
.diff-tile .n { display: block; font-size: 28px; font-weight: 600; }
.diff-tile.added .n { color: #428619; }
.diff-tile.changed .n { color: #ec7e00; }
.diff-tile.removed .n { color: #e23b4a; }
.diff-tile .l { font-size: 13px; color: #505a63; }

.dot-chart circle { transition: r 0.3s ease-out; }
.dot-outlier { fill: var(--color-outlier, #e05252); }
.dot-normal { fill: var(--color-normal, #6b8fb5); }
.dot-mean-line { stroke: #c9c9cd; stroke-dasharray: 4 3; stroke-width: 1; }
.dot-chart circle:hover { r: 6; }
.dot-caption { color: #8d969e; font-size: 12px; margin: 8px 0 0 0; }

table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid #e2e2e7; }
th { color: #505a63; font-weight: 600; text-transform: uppercase; font-size: 12px; letter-spacing: 0.05em; }
.severity-pill {
  display: inline-block;
  border-radius: 9999px;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 600;
  color: #ffffff;
}
footer {
  background: #000000;
  color: rgba(255,255,255,0.72);
  padding: 32px 24px;
  font-size: 13px;
  text-align: center;
}
@media (max-width: 640px) {
  .bar-label { width: 80px; font-size: 12px; }
}
"""


def _render_bar_chart(section: dict) -> str:
    data = section["data"]
    labels = data["labels"]
    values = data["values"]
    max_value = max(values) if values and max(values) else 1
    rows = []
    for label, value in zip(labels, values):
        pct = (value / max_value * 100) if max_value else 0
        rows.append(
            f'<div class="bar-row">'
            f'<div class="bar-label">{escape(str(label))}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="--bar-width:{pct:.1f}%"></div></div>'
            f'<div class="bar-value">{value}</div>'
            f"</div>"
        )
    return (
        f'<div class="card"><h2 class="section-title">{escape(section["title"])}</h2>'
        + "".join(rows)
        + "</div>"
    )


def _render_table(section: dict) -> str:
    data = section["data"]
    columns = data["columns"]
    severity_col = columns.index("severity") if "severity" in columns else None

    header = "".join(f"<th>{escape(str(c))}</th>" for c in columns)
    body_rows = []
    for row in data["rows"]:
        cells = []
        for i, value in enumerate(row):
            if i == severity_col:
                color = _SEVERITY_COLOR.get(str(value), "#8d969e")
                cells.append(
                    f'<td><span class="severity-pill" style="background:{color}">{escape(str(value))}</span></td>'
                )
            else:
                cells.append(f"<td>{escape(str(value))}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    if not body_rows:
        body_rows.append(
            f'<tr><td colspan="{len(columns)}">検出された不具合はありません</td></tr>'
        )

    return (
        f'<div class="card"><h2 class="section-title">{escape(section["title"])}</h2>'
        f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def _render_diff_summary(section: dict) -> str:
    data = section["data"]
    if data["previous_scan_run_id"] is None:
        body = '<p style="color:#505a63;font-size:14px;margin:0;">前回scanがないため比較できません(初回scan)。</p>'
    else:
        body = (
            '<div class="diff-row">'
            f'<div class="diff-tile added"><span class="n">{data["added_count"]}</span><span class="l">新規</span></div>'
            f'<div class="diff-tile changed"><span class="n">{data["changed_count"]}</span><span class="l">変更</span></div>'
            f'<div class="diff-tile removed"><span class="n">{data["removed_count"]}</span><span class="l">削除</span></div>'
            "</div>"
            f'<p style="color:#8d969e;font-size:12px;margin-top:12px;">vs scan_run #{data["previous_scan_run_id"]}</p>'
        )
    return f'<div class="card"><h2 class="section-title">{escape(section["title"])}</h2>{body}</div>'


def _render_dot_chart(section: dict) -> str:
    data = section["data"]
    points = data.get("points", [])
    if not points:
        body = '<p style="color:#505a63;font-size:14px;margin:0;">テクスチャがありません。</p>'
    else:
        outlier_count = sum(1 for p in points if p.get("is_outlier"))
        svg = render_dot_chart_svg(data)
        body = (
            svg + f'<p class="dot-caption">平均 {data.get("mean", 0):,.0f} bytes '
            f"({escape(str(data.get('outlier_method', '')))}) &middot; "
            f"外れ値 {outlier_count}/{len(points)}件</p>"
        )
    return f'<div class="card"><h2 class="section-title">{escape(section["title"])}</h2>{body}</div>'


def render_html(manifest: dict) -> str:
    sections_html = []
    for section in manifest["sections"]:
        if section["type"] == "diff_summary":
            sections_html.append(_render_diff_summary(section))
        elif section["type"] == "bar_chart":
            sections_html.append(_render_bar_chart(section))
        elif section["type"] == "dot_chart":
            sections_html.append(_render_dot_chart(section))
        elif section["type"] == "table":
            sections_html.append(_render_table(section))

    defect_count = 0
    for section in manifest["sections"]:
        if section["section_id"] == "defect_summary":
            defect_count = len(section["data"]["rows"])

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AssetDataInsightSuite Report - scan_run #{manifest["scan_run_id"]}</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="hero">
  <div class="hero-inner">
    <h1>Asset Data Insight Report</h1>
    <div class="meta">scan_run_id #{manifest["scan_run_id"]} &middot; generated_at {escape(manifest["generated_at"])}</div>
    <div class="badge-row">
      <span class="badge badge-primary">defects: {defect_count}</span>
      <span class="badge badge-neutral">manifest v{escape(manifest["manifest_version"])}</span>
    </div>
  </div>
</div>
<div class="catalogue">
  <div class="catalogue-inner">
    {"".join(sections_html)}
  </div>
</div>
<footer>AssetDataInsightSuite &mdash; offline static report, no external network dependency.</footer>
</body>
</html>
"""


def generate(db_path: str, scan_run_id: int | None, out_dir: str = "reports") -> Path:
    with db_module.open_db(db_path) as conn:
        if scan_run_id is None:
            scan_run_id = db_module.latest_scan_run_id(conn)
            if scan_run_id is None:
                raise SystemExit("no successful scan_run found")
        builder = build_manifest(conn, scan_run_id)

    manifest = builder.build()
    report_dir = Path(out_dir) / str(scan_run_id)
    report_dir.mkdir(parents=True, exist_ok=True)

    (report_dir / "report_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (report_dir / "index.html").write_text(render_html(manifest), encoding="utf-8")
    return report_dir / "index.html"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate offline static HTML report")
    parser.add_argument("--db", default="insight.db")
    parser.add_argument("--scan-run-id", type=int, default=None)
    parser.add_argument("--out-dir", default="reports")
    args = parser.parse_args()

    out_path = generate(args.db, args.scan_run_id, args.out_dir)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

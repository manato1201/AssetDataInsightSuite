"""Local operating GUI for AssetDataInsightSuite.

A thin Flask layer over the existing pipeline modules — every route calls
straight into `ingest.run_scan`, `rules.engine`, `output.report_manifest`,
`output.excel_adapter`, `output.ndjson_export`, and `output.static_html_adapter`.
No aggregation or judgement logic lives here; the GUI only triggers and
displays what the pipeline already computes.

Intended for local, single-user use (`--host 127.0.0.1` by default) — there
is no authentication layer.
"""

from __future__ import annotations

import argparse
import os
from io import BytesIO
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from core import db as db_module

# Import for adapter-registration side-effects.
from ingest.adapters import fs_scan_adapter, lqa_adapter, unity_asset_adapter  # noqa: F401
from ingest.adapters.registry import ADAPTER_REGISTRY
from ingest.run_scan import run_scan
from output import excel_adapter, ndjson_export, static_html_adapter
from output.report_manifest import build_manifest
from rules.engine import build_context, run_all_rules

DEFAULT_DB_PATH = os.environ.get("INSIGHT_DB_PATH", "insight.db")


def create_app(db_path: str = DEFAULT_DB_PATH) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path
    app.secret_key = (
        "asset-data-insight-suite-local-gui"  # local single-user tool, no auth
    )
    app.jinja_env.globals["zip"] = zip

    def _fetch_run(conn, scan_run_id: int):
        row = conn.execute(
            "SELECT * FROM scan_runs WHERE scan_run_id = ?", (scan_run_id,)
        ).fetchone()
        if row is None:
            abort(404)
        return row

    @app.route("/")
    def dashboard():
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            runs = conn.execute(
                "SELECT * FROM scan_runs ORDER BY scan_run_id DESC LIMIT 20"
            ).fetchall()
            defects = db_module.fetch_defect_records(conn)

        severity_counts = {"fail": 0, "warn": 0, "info": 0}
        for d in defects:
            severity_counts[d["severity"]] = severity_counts.get(d["severity"], 0) + 1

        return render_template(
            "dashboard.html",
            runs=runs,
            producers=sorted(ADAPTER_REGISTRY),
            severity_counts=severity_counts,
            total_defects=len(defects),
        )

    @app.route("/scan", methods=["POST"])
    def trigger_scan():
        producer = request.form.get("producer", "all")
        target = request.form.get("target", "").strip()
        since = request.form.get("since") or None
        run_checks_after = request.form.get("run_checks") == "on"

        if not target or not Path(target).is_dir():
            flash(f"target path が存在しないディレクトリです: {target}", "error")
            return redirect(url_for("dashboard"))

        producers = sorted(ADAPTER_REGISTRY) if producer == "all" else [producer]
        last_scan_run_id = None
        try:
            for producer_id in producers:
                last_scan_run_id = run_scan(
                    app.config["DB_PATH"], producer_id, target, since
                )
                if run_checks_after:
                    with db_module.open_db(app.config["DB_PATH"]) as conn:
                        context = build_context(conn, last_scan_run_id, target)
                        for defect in run_all_rules(context):
                            db_module.upsert_defect_record(
                                conn,
                                defect.asset_id,
                                defect.rule_id,
                                defect.severity,
                                defect.message,
                                defect.suggested_fix,
                                last_scan_run_id,
                            )
        except Exception as exc:
            flash(f"スキャン中にエラーが発生しました: {exc}", "error")
            return redirect(url_for("dashboard"))

        flash("スキャンが完了しました", "success")
        return redirect(url_for("run_detail", scan_run_id=last_scan_run_id))

    @app.route("/runs/<int:scan_run_id>")
    def run_detail(scan_run_id: int):
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            run_row = _fetch_run(conn, scan_run_id)
            builder = build_manifest(conn, scan_run_id)
        return render_template("run_detail.html", run=run_row, manifest=builder.build())

    @app.route("/runs/<int:scan_run_id>/export.xlsx")
    def export_excel(scan_run_id: int):
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            _fetch_run(conn, scan_run_id)
            builder = build_manifest(conn, scan_run_id)

        buffer = BytesIO()
        excel_adapter.write_workbook(builder, buffer)
        buffer.seek(0)
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"report_{scan_run_id}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/runs/<int:scan_run_id>/export.ndjson")
    def export_ndjson_route(scan_run_id: int):
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            _fetch_run(conn, scan_run_id)
            lines = list(ndjson_export.export_ndjson(conn, scan_run_id))
        content = "\n".join(lines) + ("\n" if lines else "")
        return Response(
            content,
            mimetype="application/x-ndjson",
            headers={
                "Content-Disposition": f"attachment; filename=checks_{scan_run_id}.ndjson"
            },
        )

    @app.route("/runs/<int:scan_run_id>/static-report")
    def regenerate_static(scan_run_id: int):
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            _fetch_run(conn, scan_run_id)
        out_path = static_html_adapter.generate(
            app.config["DB_PATH"], scan_run_id, out_dir="reports"
        )
        flash(f"静的HTMLレポートを生成しました: {out_path}", "success")
        return redirect(url_for("run_detail", scan_run_id=scan_run_id))

    @app.route("/defects")
    def defects_view():
        severity_filter = request.args.get("severity") or None
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            rows = db_module.fetch_defect_records(conn)
        if severity_filter:
            rows = [r for r in rows if r["severity"] == severity_filter]
        return render_template(
            "defects.html", defects=rows, severity_filter=severity_filter
        )

    @app.route("/trend")
    def trend_view():
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            rows = conn.execute(
                """
                SELECT first_seen_run_id AS scan_run_id, COUNT(*) AS c
                FROM defect_records
                GROUP BY first_seen_run_id
                ORDER BY first_seen_run_id
                """
            ).fetchall()
        labels = [str(r["scan_run_id"]) for r in rows]
        values = [r["c"] for r in rows]
        return render_template("trend.html", labels=labels, values=values)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the AssetDataInsightSuite local operating GUI"
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app(args.db)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

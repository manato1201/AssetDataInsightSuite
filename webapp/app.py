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
import csv
import io
import os
import secrets
import threading
from io import BytesIO
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
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
from output import excel_adapter, ndjson_export, static_html_adapter, webhook_notify
from output.report_manifest import build_manifest
from rules.definition_editor import (
    RuleDefinitionError,
    list_definition_filenames,
    read_definition_source,
    write_definition_source,
)
from rules.engine import DEFINITIONS_DIR, load_rule_definitions
from rules.run_checks import run_checks
from trend import aggregations
from trend.charts import render_dot_chart_svg
from webapp.jobs import JobStore

DEFAULT_DB_PATH = os.environ.get("INSIGHT_DB_PATH", "insight.db")
DEFAULT_WEBHOOK_URL = os.environ.get("INSIGHT_WEBHOOK_URL") or None


def _filter_defects(rows: list, severity_filter: str | None, query: str) -> list:
    if severity_filter:
        rows = [r for r in rows if r["severity"] == severity_filter]
    if query:
        q = query.lower()
        rows = [
            r
            for r in rows
            if q in r["asset_id"].lower()
            or q in r["rule_id"].lower()
            or q in (r["message"] or "").lower()
        ]
    return rows


def _inject_dot_chart_svgs(manifest: dict) -> dict:
    """Pre-renders SVG markup for any dot_chart sections so the template can
    just drop it in with `| safe` — the beeswarm layout algorithm lives once
    in trend/charts.py, not duplicated in Jinja."""
    for section in manifest["sections"]:
        if section["type"] == "dot_chart":
            section["data"]["svg"] = render_dot_chart_svg(section["data"])
    return manifest


def create_app(
    db_path: str = DEFAULT_DB_PATH,
    definitions_dir: Path = DEFINITIONS_DIR,
    webhook_url: str | None = DEFAULT_WEBHOOK_URL,
) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path
    app.config["DEFINITIONS_DIR"] = definitions_dir
    app.config["WEBHOOK_URL"] = webhook_url
    app.secret_key = secrets.token_hex(32)  # flash-message signing only, no login/auth
    app.jinja_env.globals["zip"] = zip
    jobs = JobStore()

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
        job = jobs.create(producers, target, since, run_checks_after)
        thread = threading.Thread(
            target=jobs.run,
            args=(job, run_scan, run_checks, app.config["DB_PATH"]),
            daemon=True,
        )
        thread.start()
        return redirect(url_for("job_status_page", job_id=job.job_id))

    @app.route("/jobs/<job_id>")
    def job_status_page(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            abort(404)
        return render_template("job_status.html", job=job)

    @app.route("/jobs/<job_id>/status.json")
    def job_status_json(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            abort(404)
        return jsonify(job.to_dict())

    @app.route("/runs/<int:scan_run_id>")
    def run_detail(scan_run_id: int):
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            run_row = _fetch_run(conn, scan_run_id)
            builder = build_manifest(conn, scan_run_id)
        return render_template(
            "run_detail.html",
            run=run_row,
            manifest=_inject_dot_chart_svgs(builder.build()),
            webhook_configured=bool(app.config["WEBHOOK_URL"]),
        )

    @app.route("/runs/<int:scan_run_id>/notify", methods=["POST"])
    def notify_webhook(scan_run_id: int):
        webhook_url = app.config["WEBHOOK_URL"]
        if not webhook_url:
            flash("Webhook URLが設定されていません(INSIGHT_WEBHOOK_URL)", "error")
            return redirect(url_for("run_detail", scan_run_id=scan_run_id))

        with db_module.open_db(app.config["DB_PATH"]) as conn:
            _fetch_run(conn, scan_run_id)
        try:
            sent = webhook_notify.notify_if_needed(
                app.config["DB_PATH"],
                scan_run_id,
                webhook_url,
                fail_on="warn",
                base_url=request.url_root,
            )
        except Exception as exc:
            flash(f"通知の送信に失敗しました: {exc}", "error")
            return redirect(url_for("run_detail", scan_run_id=scan_run_id))

        flash(
            "通知を送信しました"
            if sent
            else "warn以上のdefectがないため通知は送信されませんでした",
            "success",
        )
        return redirect(url_for("run_detail", scan_run_id=scan_run_id))

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
        query = request.args.get("q", "").strip()
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            rows = db_module.fetch_defect_records(conn)
            resolved_rows = db_module.fetch_recently_resolved_defects(conn, limit=20)
        rows = _filter_defects(rows, severity_filter, query)
        return render_template(
            "defects.html",
            defects=rows,
            resolved_defects=resolved_rows,
            severity_filter=severity_filter,
            query=query,
        )

    @app.route("/defects/export.csv")
    def defects_export_csv():
        severity_filter = request.args.get("severity") or None
        query = request.args.get("q", "").strip()
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            rows = db_module.fetch_defect_records(conn)
        rows = _filter_defects(rows, severity_filter, query)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "asset_id",
                "rule_id",
                "severity",
                "message",
                "suggested_fix",
                "first_seen_run_id",
                "last_seen_run_id",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r["asset_id"],
                    r["rule_id"],
                    r["severity"],
                    r["message"],
                    r["suggested_fix"],
                    r["first_seen_run_id"],
                    r["last_seen_run_id"],
                ]
            )
        # BOM so Excel on Windows detects UTF-8 (defect messages are Japanese)
        csv_content = "﻿" + buffer.getvalue()
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=defects.csv"},
        )

    @app.route("/trend")
    def trend_view():
        with db_module.open_db(app.config["DB_PATH"]) as conn:
            open_defects = aggregations.open_defect_count_over_time(conn, limit=30)
            asset_counts = aggregations.asset_count_over_time(conn, limit=30)
            total_sizes = aggregations.total_size_over_time(conn, limit=30)
            new_defect_rows = conn.execute(
                """
                SELECT first_seen_run_id AS scan_run_id, COUNT(*) AS c
                FROM defect_records
                GROUP BY first_seen_run_id
                ORDER BY first_seen_run_id
                """
            ).fetchall()

        charts = [
            {"title": "オープンなdefect数の推移", "data": open_defects},
            {"title": "アセット数の推移", "data": asset_counts},
            {
                "title": "合計サイズ(MB)の推移",
                "data": {
                    k: round(v / (1024 * 1024), 2) for k, v in total_sizes.items()
                },
            },
            {
                "title": "新規検出defect数(run別)",
                "data": {str(r["scan_run_id"]): r["c"] for r in new_defect_rows},
            },
        ]
        return render_template("trend.html", charts=charts)

    @app.route("/rules")
    def rules_list():
        definitions_dir = app.config["DEFINITIONS_DIR"]
        definitions = []
        for filename, rule_def in zip(
            list_definition_filenames(definitions_dir),
            load_rule_definitions(definitions_dir),
        ):
            definitions.append({"filename": filename, **rule_def})
        return render_template("rules_list.html", definitions=definitions)

    @app.route("/rules/<filename>/edit", methods=["GET", "POST"])
    def rule_edit(filename: str):
        definitions_dir = app.config["DEFINITIONS_DIR"]
        if request.method == "POST":
            source = request.form.get("source", "")
            try:
                write_definition_source(filename, source, definitions_dir)
            except RuleDefinitionError as exc:
                flash(str(exc), "error")
                return render_template(
                    "rule_edit.html", filename=filename, source=source
                )
            flash(f"{filename} を保存しました", "success")
            return redirect(url_for("rules_list"))

        try:
            source = read_definition_source(filename, definitions_dir)
        except RuleDefinitionError:
            abort(404)
        return render_template("rule_edit.html", filename=filename, source=source)

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

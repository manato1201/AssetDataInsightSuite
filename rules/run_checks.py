"""CLI entrypoint: `python -m rules.run_checks --target PATH [--db insight.db] [--scan-run-id N]`.

Runs every YAML-defined rule against the given scan_run's asset records and
upserts the results into `defect_records`: an existing `(asset_id, rule_id)`
pair only has its `last_seen_run_id` bumped, a new one gets
`first_seen_run_id == last_seen_run_id == scan_run_id`.
"""

from __future__ import annotations

import argparse

from core import db as db_module
from rules.engine import build_context, run_all_rules


def run_checks(db_path: str, target_path: str, scan_run_id: int | None) -> int:
    with db_module.open_db(db_path) as conn:
        if scan_run_id is None:
            scan_run_id = db_module.latest_scan_run_id(conn)
            if scan_run_id is None:
                raise SystemExit(
                    "no successful scan_run found; run ingest.run_scan first"
                )

        context = build_context(conn, scan_run_id, target_path)
        defects = run_all_rules(context)
        for defect in defects:
            db_module.upsert_defect_record(
                conn,
                asset_id=defect.asset_id,
                rule_id=defect.rule_id,
                severity=defect.severity,
                message=defect.message,
                suggested_fix=defect.suggested_fix,
                scan_run_id=scan_run_id,
            )
    return scan_run_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run defect-detection rules against a scan_run"
    )
    parser.add_argument(
        "--target", required=True, help="Directory the scan_run was collected from"
    )
    parser.add_argument("--db", default="insight.db")
    parser.add_argument("--scan-run-id", type=int, default=None)
    args = parser.parse_args()

    scan_run_id = run_checks(args.db, args.target, args.scan_run_id)
    print(f"checked scan_run_id={scan_run_id}")


if __name__ == "__main__":
    main()

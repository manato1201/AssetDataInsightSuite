"""CLI output adapter — the CI gate.

Exit codes: `0` no defects at/above `--fail-on`, `1` warn-level defects
found, `2` fail-level defects found (or a runtime error). Only reads data
that Phase 2/3 already computed; no independent judgement logic lives here.
"""

from __future__ import annotations

import argparse
import sys

from core import db as db_module
from output.report_manifest import build_manifest

_SEVERITY_RANK = {"info": 0, "warn": 1, "fail": 2}


def evaluate_exit_code(defect_rows: list, fail_on: str = "warn") -> int:
    threshold = _SEVERITY_RANK.get(fail_on, 1)
    max_rank = 0
    for row in defect_rows:
        rank = _SEVERITY_RANK.get(row["severity"], 0)
        max_rank = max(max_rank, rank)

    if max_rank == 0 or max_rank < threshold:
        return 0
    return 2 if max_rank >= _SEVERITY_RANK["fail"] else 1


def run(
    db_path: str, scan_run_id: int | None, fail_on: str, manifest_path: str | None
) -> int:
    try:
        with db_module.open_db(db_path) as conn:
            if scan_run_id is None:
                scan_run_id = db_module.latest_scan_run_id(conn)
                if scan_run_id is None:
                    print("no successful scan_run found", file=sys.stderr)
                    return 2

            defect_rows = db_module.fetch_defect_records(conn)
            builder = build_manifest(conn, scan_run_id)
            if manifest_path:
                builder.write(manifest_path)

            for row in defect_rows:
                print(
                    f"[{row['severity']}] {row['asset_id']} :: {row['rule_id']} :: {row['message']}"
                )

            exit_code = evaluate_exit_code(defect_rows, fail_on)
            print(f"defects={len(defect_rows)} fail_on={fail_on} exit_code={exit_code}")
            return exit_code
    except Exception as exc:  # runtime error -> exit code 2
        print(f"error: {exc}", file=sys.stderr)
        return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="CI-gate CLI adapter")
    parser.add_argument("--db", default="insight.db")
    parser.add_argument("--scan-run-id", type=int, default=None)
    parser.add_argument("--fail-on", choices=["info", "warn", "fail"], default="warn")
    parser.add_argument("--manifest-out", default="report_manifest.json")
    args = parser.parse_args()

    sys.exit(run(args.db, args.scan_run_id, args.fail_on, args.manifest_out))


if __name__ == "__main__":
    main()

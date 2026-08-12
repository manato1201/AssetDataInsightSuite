"""Elasticsearch `_bulk`-compatible NDJSON export.

Scoped as an export adapter only — this Suite does not run or manage an
ELK stack. Kibana index creation / dashboards are the consuming team's
responsibility.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterator

from core import db as db_module


def query_check_results(db: sqlite3.Connection, scan_run_id: int) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT ar.asset_id, cr.check_id, cr.status, cr.value, ar.collected_at
        FROM check_results cr
        JOIN asset_records ar ON ar.asset_record_id = cr.asset_record_id
        WHERE cr.scan_run_id = ?
        """,
        (scan_run_id,),
    ).fetchall()


def export_ndjson(
    db: sqlite3.Connection, scan_run_id: int, index_name: str = "asset-insight-checks"
) -> Iterator[str]:
    for row in query_check_results(db, scan_run_id):
        yield json.dumps({"index": {"_index": index_name}})
        yield json.dumps(
            {
                "scan_run_id": scan_run_id,
                "asset_id": row["asset_id"],
                "check_id": row["check_id"],
                "status": row["status"],
                "value": row["value"],
                "collected_at": row["collected_at"],
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export check_results as Elasticsearch _bulk NDJSON"
    )
    parser.add_argument("--db", default="insight.db")
    parser.add_argument("--scan-run-id", type=int, default=None)
    parser.add_argument("--index-name", default="asset-insight-checks")
    parser.add_argument("--out", default="checks.ndjson")
    args = parser.parse_args()

    with db_module.open_db(args.db) as conn:
        scan_run_id = args.scan_run_id or db_module.latest_scan_run_id(conn)
        if scan_run_id is None:
            raise SystemExit("no successful scan_run found")
        lines = list(export_ndjson(conn, scan_run_id, args.index_name))

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {args.out} ({len(lines) // 2} documents)")


if __name__ == "__main__":
    main()

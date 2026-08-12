"""CLI entrypoint: `python -m ingest.run_scan --producer lqa --target PATH [--since ISO] [--db insight.db]`.

Importing the adapter modules registers them into `ADAPTER_REGISTRY`; this
module is the only place that needs to know the full producer list.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from core import db as db_module

# Import for registration side-effects.
from ingest.adapters import fs_scan_adapter, lqa_adapter, unity_asset_adapter  # noqa: F401
from ingest.adapters.registry import ADAPTER_REGISTRY

TOOL_VERSION = "0.1.0"


def run_scan(
    db_path: str, producer_id: str, target_path: str, since: str | None
) -> int:
    adapter = ADAPTER_REGISTRY.get(producer_id)
    if adapter is None:
        raise SystemExit(
            f"unknown producer: {producer_id} (known: {sorted(ADAPTER_REGISTRY)})"
        )

    started_at = datetime.now(timezone.utc).isoformat()
    with db_module.open_db(db_path) as conn:
        scan_run_id = db_module.start_scan_run(
            conn, producer_id, TOOL_VERSION, started_at
        )
        try:
            records = adapter.scan(target_path, since)
            db_module.insert_asset_records(conn, scan_run_id, records)
        except Exception:
            db_module.finish_scan_run(
                conn, scan_run_id, datetime.now(timezone.utc).isoformat(), "failed"
            )
            raise
        db_module.finish_scan_run(
            conn, scan_run_id, datetime.now(timezone.utc).isoformat(), "success"
        )
    return scan_run_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest asset data into insight.db")
    parser.add_argument(
        "--producer", required=True, choices=sorted(ADAPTER_REGISTRY) + ["all"]
    )
    parser.add_argument("--target", required=True, help="Directory to scan")
    parser.add_argument(
        "--since", default=None, help="ISO8601 timestamp; only ingest newer data"
    )
    parser.add_argument("--db", default="insight.db")
    args = parser.parse_args()

    producers = list(ADAPTER_REGISTRY) if args.producer == "all" else [args.producer]
    for producer_id in producers:
        scan_run_id = run_scan(args.db, producer_id, args.target, args.since)
        print(f"[{producer_id}] scan_run_id={scan_run_id}")


if __name__ == "__main__":
    main()

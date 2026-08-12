"""SQLite storage layer for insight.db.

Three append-only tables (`scan_runs`, `asset_records`, `check_results`) plus
`defect_records` for Phase 2 rule evaluation output. `scan_runs` is
INSERT-only: past rows are never UPDATEd or DELETEd, so Phase 3 trend
aggregation can safely join across historical scan_run_id values.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core.schema import AssetRecord

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scan_runs (
    scan_run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    source_producer TEXT NOT NULL,
    tool_version    TEXT NOT NULL,
    status          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_records (
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
CREATE INDEX IF NOT EXISTS idx_asset_records_run_asset
    ON asset_records(scan_run_id, asset_id);

CREATE TABLE IF NOT EXISTS check_results (
    check_result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_record_id INTEGER NOT NULL REFERENCES asset_records(asset_record_id),
    scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(scan_run_id),
    check_id        TEXT NOT NULL,
    status          TEXT NOT NULL,
    value           TEXT,
    threshold       TEXT,
    message         TEXT
);
CREATE INDEX IF NOT EXISTS idx_check_results_run_check
    ON check_results(scan_run_id, check_id);

CREATE TABLE IF NOT EXISTS defect_records (
    defect_record_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id          TEXT NOT NULL,
    rule_id           TEXT NOT NULL,
    severity          TEXT NOT NULL,
    message           TEXT NOT NULL,
    suggested_fix     TEXT,
    first_seen_run_id INTEGER NOT NULL REFERENCES scan_runs(scan_run_id),
    last_seen_run_id  INTEGER NOT NULL REFERENCES scan_runs(scan_run_id),
    UNIQUE(asset_id, rule_id)
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn


@contextmanager
def open_db(db_path: str | Path):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def start_scan_run(
    conn: sqlite3.Connection, source_producer: str, tool_version: str, started_at: str
) -> int:
    cur = conn.execute(
        "INSERT INTO scan_runs (started_at, source_producer, tool_version, status) VALUES (?, ?, ?, 'running')",
        (started_at, source_producer, tool_version),
    )
    return cur.lastrowid


def finish_scan_run(
    conn: sqlite3.Connection, scan_run_id: int, finished_at: str, status: str
) -> None:
    conn.execute(
        "UPDATE scan_runs SET finished_at = ?, status = ? WHERE scan_run_id = ?",
        (finished_at, status, scan_run_id),
    )


def insert_asset_records(
    conn: sqlite3.Connection, scan_run_id: int, records: list[AssetRecord]
) -> None:
    for record in records:
        cur = conn.execute(
            """
            INSERT INTO asset_records
                (scan_run_id, asset_id, asset_type, source_producer, size_bytes, extension, last_modified, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_run_id,
                record.asset_id,
                record.asset_type,
                record.source_producer,
                record.size_bytes,
                record.extension,
                record.last_modified,
                record.collected_at,
            ),
        )
        asset_record_id = cur.lastrowid
        for check_id, check in record.checks.items():
            conn.execute(
                """
                INSERT INTO check_results
                    (asset_record_id, scan_run_id, check_id, status, value, threshold, message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_record_id,
                    scan_run_id,
                    check_id,
                    check.status,
                    None if check.value is None else str(check.value),
                    None if check.threshold is None else str(check.threshold),
                    check.message,
                ),
            )


def latest_scan_run_id(
    conn: sqlite3.Connection, source_producer: str | None = None
) -> int | None:
    if source_producer:
        row = conn.execute(
            "SELECT scan_run_id FROM scan_runs WHERE source_producer = ? AND status = 'success' "
            "ORDER BY scan_run_id DESC LIMIT 1",
            (source_producer,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT scan_run_id FROM scan_runs WHERE status = 'success' ORDER BY scan_run_id DESC LIMIT 1"
        ).fetchone()
    return row["scan_run_id"] if row else None


def fetch_asset_records(
    conn: sqlite3.Connection, scan_run_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM asset_records WHERE scan_run_id = ?", (scan_run_id,)
    ).fetchall()


def fetch_check_results(
    conn: sqlite3.Connection, scan_run_id: int, asset_record_id: int | None = None
) -> list[sqlite3.Row]:
    if asset_record_id is not None:
        return conn.execute(
            "SELECT * FROM check_results WHERE scan_run_id = ? AND asset_record_id = ?",
            (scan_run_id, asset_record_id),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM check_results WHERE scan_run_id = ?", (scan_run_id,)
    ).fetchall()


def upsert_defect_record(
    conn: sqlite3.Connection,
    asset_id: str,
    rule_id: str,
    severity: str,
    message: str,
    suggested_fix: str | None,
    scan_run_id: int,
) -> None:
    existing = conn.execute(
        "SELECT defect_record_id, first_seen_run_id FROM defect_records WHERE asset_id = ? AND rule_id = ?",
        (asset_id, rule_id),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE defect_records
            SET severity = ?, message = ?, suggested_fix = ?, last_seen_run_id = ?
            WHERE defect_record_id = ?
            """,
            (
                severity,
                message,
                suggested_fix,
                scan_run_id,
                existing["defect_record_id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO defect_records
                (asset_id, rule_id, severity, message, suggested_fix, first_seen_run_id, last_seen_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                rule_id,
                severity,
                message,
                suggested_fix,
                scan_run_id,
                scan_run_id,
            ),
        )


def fetch_defect_records(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM defect_records ORDER BY severity DESC, asset_id"
    ).fetchall()

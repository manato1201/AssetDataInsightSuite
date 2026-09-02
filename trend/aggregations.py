"""Trend aggregation queries.

Every function here does a SELECT against Phase 1's three tables and
returns plain data — no chart rendering, no new tables. This keeps the
functions unit-testable against a bare DB connection and reusable by both
the CLI and Excel output adapters (Phase 4).
"""

from __future__ import annotations

import sqlite3


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def texture_resolution_histogram(
    db: sqlite3.Connection, scan_run_id: int, bucket_edges: list[int]
) -> dict[str, int]:
    """asset_type='texture'のcheck_id='resolution_px'をビン分けして返す"""
    rows = db.execute(
        """
        SELECT cr.value FROM check_results cr
        JOIN asset_records ar ON ar.asset_record_id = cr.asset_record_id
        WHERE cr.scan_run_id = ? AND ar.asset_type = 'texture' AND cr.check_id = 'resolution_px'
        """,
        (scan_run_id,),
    ).fetchall()

    edges = sorted(bucket_edges)
    labels = [str(e) for e in edges] + [f"{edges[-1]}+"]
    counts = {label: 0 for label in labels}

    for row in rows:
        try:
            value = float(row["value"])
        except (TypeError, ValueError):
            continue
        for edge, label in zip(edges, labels):
            if value <= edge:
                counts[label] += 1
                break
        else:
            counts[labels[-1]] += 1
    return counts


def lod_fade_coverage(db: sqlite3.Connection, scan_run_id: int) -> dict[str, float]:
    """asset_type='model'全体に対しlod_group_configured/fade_configuredがpassの比率"""
    total_row = db.execute(
        "SELECT COUNT(*) AS c FROM asset_records WHERE scan_run_id = ? AND asset_type = 'model'",
        (scan_run_id,),
    ).fetchone()
    total = total_row["c"]
    if total == 0:
        return {"lod_group_configured": 0.0, "fade_configured": 0.0}

    coverage: dict[str, float] = {}
    for check_id in ("lod_group_configured", "fade_configured"):
        passed_row = db.execute(
            """
            SELECT COUNT(*) AS c FROM check_results cr
            JOIN asset_records ar ON ar.asset_record_id = cr.asset_record_id
            WHERE cr.scan_run_id = ? AND ar.asset_type = 'model' AND cr.check_id = ? AND cr.status = 'pass'
            """,
            (scan_run_id, check_id),
        ).fetchone()
        coverage[check_id] = passed_row["c"] / total
    return coverage


def outliers(
    db: sqlite3.Connection,
    scan_run_id: int,
    check_id: str,
    method: str = "zscore",
    threshold: float = 2.0,
) -> list[dict]:
    """value列の外れ値(z-score または IQR)を「平均より重いデータ」として返す"""
    rows = db.execute(
        """
        SELECT ar.asset_id, cr.value FROM check_results cr
        JOIN asset_records ar ON ar.asset_record_id = cr.asset_record_id
        WHERE cr.scan_run_id = ? AND cr.check_id = ?
        """,
        (scan_run_id, check_id),
    ).fetchall()

    data: list[tuple[str, float]] = []
    for row in rows:
        try:
            data.append((row["asset_id"], float(row["value"])))
        except (TypeError, ValueError):
            continue
    if not data:
        return []

    values = [v for _, v in data]
    n = len(values)
    mean = sum(values) / n

    if method == "zscore":
        variance = sum((v - mean) ** 2 for v in values) / n
        stdev = variance**0.5
        if stdev == 0:
            return []
        result = [
            {"asset_id": asset_id, "value": v, "score": (v - mean) / stdev}
            for asset_id, v in data
            if abs((v - mean) / stdev) >= threshold
        ]
        return sorted(result, key=lambda r: -abs(r["score"]))

    if method == "iqr":
        sorted_values = sorted(values)
        q1 = _percentile(sorted_values, 25)
        q3 = _percentile(sorted_values, 75)
        iqr = q3 - q1
        lower, upper = q1 - threshold * iqr, q3 + threshold * iqr
        result = [
            {"asset_id": asset_id, "value": v, "bounds": [lower, upper]}
            for asset_id, v in data
            if v < lower or v > upper
        ]
        return sorted(result, key=lambda r: r["value"])

    raise ValueError(f"unknown outlier method: {method}")


def size_distribution(db: sqlite3.Connection, scan_run_id: int) -> dict[str, int]:
    rows = db.execute(
        "SELECT size_bytes FROM asset_records WHERE scan_run_id = ?", (scan_run_id,)
    ).fetchall()
    buckets = {
        "<100KB": 0,
        "100KB-1MB": 0,
        "1MB-10MB": 0,
        "10MB-100MB": 0,
        ">=100MB": 0,
    }
    for row in rows:
        kb = (row["size_bytes"] or 0) / 1024
        if kb < 100:
            buckets["<100KB"] += 1
        elif kb < 1024:
            buckets["100KB-1MB"] += 1
        elif kb < 10 * 1024:
            buckets["1MB-10MB"] += 1
        elif kb < 100 * 1024:
            buckets["10MB-100MB"] += 1
        else:
            buckets[">=100MB"] += 1
    return buckets


def extension_breakdown(db: sqlite3.Connection, scan_run_id: int) -> dict[str, int]:
    rows = db.execute(
        "SELECT extension, COUNT(*) AS c FROM asset_records WHERE scan_run_id = ? GROUP BY extension",
        (scan_run_id,),
    ).fetchall()
    return {(row["extension"] or "(none)"): row["c"] for row in rows}


def diff_against_previous(db: sqlite3.Connection, scan_run_id: int) -> dict:
    """新規/変更/削除アセットを直前(同一producer)のscan_runと比較して返す。

    比較対象がない(初回scan)場合は previous_scan_run_id=None かつ全カウント0。
    """
    run_row = db.execute(
        "SELECT source_producer FROM scan_runs WHERE scan_run_id = ?", (scan_run_id,)
    ).fetchone()
    empty = {
        "previous_scan_run_id": None,
        "added_ids": [],
        "changed_ids": [],
        "removed_ids": [],
    }
    if run_row is None:
        return empty

    prev_row = db.execute(
        """
        SELECT scan_run_id FROM scan_runs
        WHERE source_producer = ? AND scan_run_id < ? AND status = 'success'
        ORDER BY scan_run_id DESC LIMIT 1
        """,
        (run_row["source_producer"], scan_run_id),
    ).fetchone()
    if prev_row is None:
        return empty
    previous_scan_run_id = prev_row["scan_run_id"]

    def _snapshot(run_id: int) -> dict[str, tuple]:
        rows = db.execute(
            "SELECT asset_id, size_bytes, last_modified FROM asset_records WHERE scan_run_id = ?",
            (run_id,),
        ).fetchall()
        return {r["asset_id"]: (r["size_bytes"], r["last_modified"]) for r in rows}

    current = _snapshot(scan_run_id)
    previous = _snapshot(previous_scan_run_id)

    added_ids = sorted(set(current) - set(previous))
    removed_ids = sorted(set(previous) - set(current))
    changed_ids = sorted(a for a in (set(current) & set(previous)) if current[a] != previous[a])

    return {
        "previous_scan_run_id": previous_scan_run_id,
        "added_ids": added_ids,
        "changed_ids": changed_ids,
        "removed_ids": removed_ids,
    }


def last_modified_distribution(
    db: sqlite3.Connection, scan_run_id: int, bucket: str = "month"
) -> dict[str, int]:
    slice_len = {"year": 4, "month": 7, "day": 10}.get(bucket, 7)
    rows = db.execute(
        "SELECT last_modified FROM asset_records WHERE scan_run_id = ?", (scan_run_id,)
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        lm = row["last_modified"]
        if not lm:
            continue
        key = lm[:slice_len]
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))

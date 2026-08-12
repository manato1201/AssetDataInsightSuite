from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DefectRecord:
    asset_id: str
    rule_id: str
    severity: str  # "info" | "warn" | "fail"
    message: str
    suggested_fix: str | None
    first_seen_run_id: int  # scan_runs.scan_run_id
    last_seen_run_id: int  # scan_runs.scan_run_id

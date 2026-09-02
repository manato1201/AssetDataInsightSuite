from __future__ import annotations

from dataclasses import dataclass

# Shared severity ordering — the single source of truth for anything that
# needs to compare or threshold severities (CI exit codes, webhook
# notification gating, etc.).
SEVERITY_RANK = {"info": 0, "warn": 1, "fail": 2}


@dataclass
class DefectRecord:
    asset_id: str
    rule_id: str
    severity: str  # "info" | "warn" | "fail"
    message: str
    suggested_fix: str | None
    first_seen_run_id: int  # scan_runs.scan_run_id
    last_seen_run_id: int  # scan_runs.scan_run_id

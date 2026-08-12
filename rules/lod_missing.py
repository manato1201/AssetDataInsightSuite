"""Flags models whose `lod_group_configured` check is missing or failing."""

from __future__ import annotations

from rules.engine import RuleContext
from rules.schema import DefectRecord


def evaluate(context: RuleContext, rule_def: dict) -> list[DefectRecord]:
    applies_to = set(rule_def.get("applies_to", ["model"]))
    severity = rule_def.get("severity", "warn")
    message = rule_def.get("message", "LOD group is not configured")
    check_id = rule_def.get("params", {}).get("check_id", "lod_group_configured")

    defects: list[DefectRecord] = []
    for asset in context.asset_records:
        if asset.asset_type not in applies_to:
            continue
        check = asset.checks.get(check_id)
        if check is None or check["status"] == "fail":
            defects.append(
                DefectRecord(
                    asset_id=asset.asset_id,
                    rule_id=rule_def["rule_id"],
                    severity=severity,
                    message=message,
                    suggested_fix=None,
                    first_seen_run_id=context.scan_run_id,
                    last_seen_run_id=context.scan_run_id,
                )
            )
    return defects

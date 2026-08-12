"""Regex-based naming/coding convention rule.

Doubles as the "coding regulation violation" check from item4: pointing a
YAML definition's `applies_to` at `script` and its `params.pattern` at a
header/naming regex reuses this exact module instead of adding a new one.
"""

from __future__ import annotations

import re
from pathlib import Path

from rules.engine import RuleContext
from rules.schema import DefectRecord


def evaluate(context: RuleContext, rule_def: dict) -> list[DefectRecord]:
    pattern = re.compile(rule_def["params"]["pattern"])
    applies_to = set(rule_def.get("applies_to", []))
    severity = rule_def.get("severity", "warn")
    message = rule_def.get("message", "naming convention violation")

    defects: list[DefectRecord] = []
    for asset in context.asset_records:
        if applies_to and asset.asset_type not in applies_to:
            continue
        basename = Path(asset.asset_id).stem
        if not pattern.match(basename):
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

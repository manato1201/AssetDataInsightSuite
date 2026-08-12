"""Individual-fix overrides + generic orphan-asset detection.

"Individual fix" items are one-off, asset_id-specific call-outs that don't
fit a generic rule — they come from a static `overrides:` list in the YAML
definition (see `rules/definitions/individual_overrides.yaml`) and are
emitted unconditionally, regardless of whether the asset appears in the
current scan.

Orphan detection is generic: any texture/model asset whose basename never
appears inside a scene/prefab/material file is flagged. It only runs when
`params.detect_orphans: true` is set on the definition.
"""

from __future__ import annotations

import re
from pathlib import Path

from rules.engine import RuleContext
from rules.schema import DefectRecord

_REFERENCE_RE = re.compile(
    r"([\w.\-]+\.(?:mat|fbx|obj|png|jpg|jpeg|tga|prefab))", re.IGNORECASE
)


def _evaluate_overrides(context: RuleContext, rule_def: dict) -> list[DefectRecord]:
    severity = rule_def.get("severity", "warn")
    defects: list[DefectRecord] = []
    for override in rule_def.get("overrides", []):
        defects.append(
            DefectRecord(
                asset_id=override["asset_id"],
                rule_id=rule_def["rule_id"],
                severity=override.get("severity", severity),
                message=override.get("message", "individually flagged for manual fix"),
                suggested_fix=override.get("suggested_fix"),
                first_seen_run_id=context.scan_run_id,
                last_seen_run_id=context.scan_run_id,
            )
        )
    return defects


def _collect_all_references(target_path: str) -> set[str]:
    referenced: set[str] = set()
    root = Path(target_path)
    for pattern in ("*.unity", "*.prefab", "*.mat"):
        for source_file in root.rglob(pattern):
            try:
                text = source_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            referenced.update(m.lower() for m in _REFERENCE_RE.findall(text))
    return referenced


def _evaluate_orphans(context: RuleContext, rule_def: dict) -> list[DefectRecord]:
    applies_to = set(rule_def.get("applies_to", ["texture", "model", "material"]))
    severity = rule_def.get("orphan_severity", rule_def.get("severity", "info"))
    message = rule_def.get(
        "orphan_message",
        "Asset is not referenced anywhere in scanned scenes/prefabs/materials",
    )

    referenced = _collect_all_references(context.target_path)

    defects: list[DefectRecord] = []
    for asset in context.asset_records:
        if asset.asset_type not in applies_to:
            continue
        basename = Path(asset.asset_id).name.lower()
        if basename not in referenced:
            defects.append(
                DefectRecord(
                    asset_id=asset.asset_id,
                    rule_id="orphan_asset",
                    severity=severity,
                    message=message,
                    suggested_fix=None,
                    first_seen_run_id=context.scan_run_id,
                    last_seen_run_id=context.scan_run_id,
                )
            )
    return defects


def evaluate(context: RuleContext, rule_def: dict) -> list[DefectRecord]:
    defects = _evaluate_overrides(context, rule_def)
    if rule_def.get("params", {}).get("detect_orphans"):
        defects.extend(_evaluate_orphans(context, rule_def))
    return defects

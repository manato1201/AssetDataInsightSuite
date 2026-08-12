"""Cross-checks materials against the scene/prefab reference graph.

`params.reference_graph_source: scene_and_prefab` scans `.unity`/`.prefab`
files under the scan target for material filename references; any material
asset never mentioned there is reported as unused. This is the same
`DefectRecord` output shape as every other rule — only the evaluation
function differs from the regex engine in `naming_convention.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

from rules.engine import RuleContext
from rules.schema import DefectRecord

_MATERIAL_REF_RE = re.compile(r"([\w.\-]+\.mat)")


def _collect_referenced_material_names(target_path: str) -> set[str]:
    referenced: set[str] = set()
    root = Path(target_path)
    for pattern in ("*.unity", "*.prefab"):
        for scene_file in root.rglob(pattern):
            try:
                text = scene_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            referenced.update(_MATERIAL_REF_RE.findall(text))
    return referenced


def evaluate(context: RuleContext, rule_def: dict) -> list[DefectRecord]:
    applies_to = set(rule_def.get("applies_to", ["material"]))
    severity = rule_def.get("severity", "warn")
    message = rule_def.get(
        "message", "Material is not referenced by any scene or prefab"
    )

    referenced = _collect_referenced_material_names(context.target_path)

    defects: list[DefectRecord] = []
    for asset in context.asset_records:
        if asset.asset_type not in applies_to:
            continue
        basename = Path(asset.asset_id).name
        if basename not in referenced:
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

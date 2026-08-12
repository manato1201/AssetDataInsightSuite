"""YAML-driven rule engine.

Rule IDs, severities, and thresholds all live in `rules/definitions/*.yaml`
— never hardcoded in Python. Each definition names a `module` (e.g.
`rules.naming_convention`) that is imported dynamically and must expose an
`evaluate(context: RuleContext, rule_def: dict) -> list[DefectRecord]`
function. Adding a rule is: add a module (or reuse an existing one) + add a
YAML definition; the engine itself never changes.
"""

from __future__ import annotations

import importlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core import db as db_module
from rules.schema import DefectRecord

DEFINITIONS_DIR = Path(__file__).parent / "definitions"


@dataclass
class AssetView:
    asset_record_id: int
    asset_id: str
    asset_type: str
    extension: str | None
    checks: dict[str, dict] = field(default_factory=dict)


@dataclass
class RuleContext:
    scan_run_id: int
    target_path: str
    asset_records: list[AssetView]


def load_rule_definitions(definitions_dir: Path = DEFINITIONS_DIR) -> list[dict]:
    definitions = []
    for yaml_path in sorted(definitions_dir.glob("*.yaml")):
        with yaml_path.open(encoding="utf-8") as f:
            definitions.append(yaml.safe_load(f))
    return definitions


def build_context(
    conn: sqlite3.Connection, scan_run_id: int, target_path: str
) -> RuleContext:
    asset_rows = db_module.fetch_asset_records(conn, scan_run_id)
    asset_views: list[AssetView] = []
    for row in asset_rows:
        checks_rows = db_module.fetch_check_results(
            conn, scan_run_id, row["asset_record_id"]
        )
        checks = {
            c["check_id"]: {
                "status": c["status"],
                "value": c["value"],
                "threshold": c["threshold"],
                "message": c["message"],
            }
            for c in checks_rows
        }
        asset_views.append(
            AssetView(
                asset_record_id=row["asset_record_id"],
                asset_id=row["asset_id"],
                asset_type=row["asset_type"],
                extension=row["extension"],
                checks=checks,
            )
        )
    return RuleContext(
        scan_run_id=scan_run_id, target_path=target_path, asset_records=asset_views
    )


def run_all_rules(
    context: RuleContext, definitions_dir: Path = DEFINITIONS_DIR
) -> list[DefectRecord]:
    defects: list[DefectRecord] = []
    for rule_def in load_rule_definitions(definitions_dir):
        module = importlib.import_module(rule_def["module"])
        defects.extend(module.evaluate(context, rule_def))
    return defects

"""`report_manifest.json` — the single renderer-agnostic intermediate format.

`ReportManifestBuilder` is the sole producer of `report_manifest.json`,
mirroring the `ManifestWriter` pattern from LearningQt's `manifest.json`
(one entry appended per completed phase). Phase 2/3 modules never write
JSON themselves; `build_manifest` is the only place that calls into them and
feeds the results through the builder.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core import db as db_module
from trend import aggregations

MANIFEST_VERSION = "1.0"

DEFAULT_TEXTURE_BUCKETS = [256, 512, 1024, 2048, 4096]


class ReportManifestBuilder:
    def __init__(self, scan_run_id: int, manifest_version: str = MANIFEST_VERSION):
        self.scan_run_id = scan_run_id
        self.manifest_version = manifest_version
        self.generated_at = datetime.now(timezone.utc).isoformat()
        self.sections: list[dict] = []

    def add_section(self, section_id: str, type_: str, title: str, data: dict) -> None:
        self.sections.append({"section_id": section_id, "type": type_, "title": title, "data": data})

    def build(self) -> dict:
        return {
            "manifest_version": self.manifest_version,
            "scan_run_id": self.scan_run_id,
            "generated_at": self.generated_at,
            "sections": self.sections,
        }

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.build(), ensure_ascii=False, indent=2), encoding="utf-8")


def build_manifest(conn: sqlite3.Connection, scan_run_id: int) -> ReportManifestBuilder:
    builder = ReportManifestBuilder(scan_run_id)

    hist = aggregations.texture_resolution_histogram(conn, scan_run_id, DEFAULT_TEXTURE_BUCKETS)
    builder.add_section(
        "texture_resolution_histogram", "bar_chart", "テクスチャ解像度分布",
        {"labels": list(hist), "values": list(hist.values())},
    )

    coverage = aggregations.lod_fade_coverage(conn, scan_run_id)
    builder.add_section(
        "lod_fade_coverage", "bar_chart", "LOD/フェード設定カバレッジ",
        {"labels": list(coverage), "values": [round(v, 4) for v in coverage.values()]},
    )

    size_dist = aggregations.size_distribution(conn, scan_run_id)
    builder.add_section(
        "size_distribution", "bar_chart", "サイズ分布",
        {"labels": list(size_dist), "values": list(size_dist.values())},
    )

    ext_breakdown = aggregations.extension_breakdown(conn, scan_run_id)
    builder.add_section(
        "extension_breakdown", "bar_chart", "拡張子別集計",
        {"labels": list(ext_breakdown), "values": list(ext_breakdown.values())},
    )

    last_mod = aggregations.last_modified_distribution(conn, scan_run_id)
    builder.add_section(
        "last_modified_distribution", "bar_chart", "最終更新日分布",
        {"labels": list(last_mod), "values": list(last_mod.values())},
    )

    defects = db_module.fetch_defect_records(conn)
    rows = [
        [d["asset_id"], d["rule_id"], d["severity"], d["first_seen_run_id"]]
        for d in defects
        if d["severity"] in ("warn", "fail")
    ]
    builder.add_section(
        "defect_summary", "table", "不具合一覧(severity>=warn)",
        {"columns": ["asset_id", "rule_id", "severity", "first_seen_run_id"], "rows": rows},
    )

    return builder

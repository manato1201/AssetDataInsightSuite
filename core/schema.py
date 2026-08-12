"""Canonical in-memory schema shared by every ingestion producer.

`checks` is intentionally a free-form dict (not a fixed struct) so that new
check IDs can be introduced by any producer without a schema migration. This
mirrors the `.lqa` sidecar format's `checks` map, which is the reference
input contract (see AssetDataInsightSuite_DESIGN.md Phase 0).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CheckResult:
    status: str  # "pass" | "warn" | "fail" | "info"
    message: str | None = None
    value: float | str | None = None
    threshold: float | str | None = None


@dataclass
class AssetRecord:
    asset_id: str  # stable key within a producer, normally a normalized relative path
    asset_type: str  # "texture" | "model" | "material" | "audio_bank" | ...
    source_producer: str  # "lqa" | "fs_scan" | "unity_asset" | ...
    collected_at: str  # ISO8601, ingestion run timestamp
    size_bytes: int | None
    extension: str | None
    last_modified: str | None  # ISO8601
    checks: dict[str, CheckResult] = field(default_factory=dict)

"""`.lqa` (Lore Quality Analysis) sidecar adapter.

Reference format (see LoreDesktopAndWebSystem\\IMPROVEMENT_PLAN.md Phase 6):
`{base_dir}/lqa/{repo_slug}/{path}.lqa.json`, holding a versioned
`records[]` array. This adapter maps only the latest entry (or the latest
entry among those newer than `since`) per asset into a canonical
`AssetRecord` — it does not manage `.lqa`'s own commit-level history, that
remains the producer's responsibility.

`.lqa` is one producer among several, not a Suite-specific format: this
adapter contains all of the `.lqa`-specific parsing so the rest of the
pipeline never has to know the sidecar's shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.schema import AssetRecord, CheckResult
from ingest.adapters.registry import register


def _record_to_asset(
    asset_id: str, asset_type: str, record: dict, collected_at: str
) -> AssetRecord:
    checks: dict[str, CheckResult] = {}
    for check_id, raw in (record.get("checks") or {}).items():
        checks[check_id] = CheckResult(
            status=raw.get("status", "info"),
            message=raw.get("message"),
            value=raw.get("value"),
            threshold=raw.get("threshold"),
        )

    conversion_errors = record.get("conversion_errors") or []
    if conversion_errors:
        checks["conversion_error"] = CheckResult(
            status="fail",
            message="; ".join(str(e) for e in conversion_errors),
            value=len(conversion_errors),
        )

    return AssetRecord(
        asset_id=asset_id,
        asset_type=asset_type,
        source_producer="lqa",
        collected_at=collected_at,
        size_bytes=record.get("size_bytes"),
        extension=record.get("extension"),
        last_modified=record.get("last_modified"),
        checks=checks,
    )


@register
class LqaAdapter:
    producer_id = "lqa"

    def scan(self, target_path: str, since: str | None = None) -> list[AssetRecord]:
        results: list[AssetRecord] = []
        for lqa_file in sorted(Path(target_path).rglob("*.lqa.json")):
            try:
                data = json.loads(lqa_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            asset_id = data.get("asset_id") or lqa_file.stem.removesuffix(".lqa")
            asset_type = data.get("asset_type", "unknown")
            records = data.get("records") or []
            if since:
                records = [r for r in records if (r.get("committed_at") or "") > since]
            if not records:
                continue

            latest = records[-1]
            collected_at = latest.get("committed_at", latest.get("last_modified", ""))
            results.append(_record_to_asset(asset_id, asset_type, latest, collected_at))
        return results

"""Slack-compatible webhook notification adapter.

POSTs a plain `{"text": "..."}` payload — natively understood by Slack
incoming webhooks (and Mattermost/Rocket.Chat). Microsoft Teams retired its
old Office 365 Connector webhook format; point this at a Power Automate
"When an HTTP request is received" flow that forwards the `text` field
onward instead. This Suite does not manage the receiving side, matching the
scope of `output/ndjson_export.py` — the workflow/webhook itself is the
consuming team's responsibility.

Only reads data Phase 2 already computed (`defect_records` via
`report_manifest`); no independent judgement logic lives here beyond
picking the severity threshold to notify on.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

from core import db as db_module
from output.report_manifest import build_manifest
from rules.schema import SEVERITY_RANK

_MAX_LISTED_DEFECTS = 10


def build_message(manifest: dict, base_url: str | None = None) -> str:
    scan_run_id = manifest["scan_run_id"]
    defect_section = next(
        (s for s in manifest["sections"] if s["section_id"] == "defect_summary"), None
    )
    rows = defect_section["data"]["rows"] if defect_section else []
    fail_rows = [r for r in rows if r[2] == "fail"]
    warn_rows = [r for r in rows if r[2] == "warn"]

    lines = [
        f"*AssetDataInsightSuite* scan_run #{scan_run_id}: "
        f"fail={len(fail_rows)} warn={len(warn_rows)}"
    ]
    for row in fail_rows[:_MAX_LISTED_DEFECTS]:
        lines.append(f"  :red_circle: {row[0]} :: {row[1]}")
    if len(fail_rows) > _MAX_LISTED_DEFECTS:
        lines.append(f"  …ほか{len(fail_rows) - _MAX_LISTED_DEFECTS}件")
    if base_url:
        lines.append(f"詳細: {base_url.rstrip('/')}/runs/{scan_run_id}")
    return "\n".join(lines)


def send_webhook(webhook_url: str, text: str, timeout: float = 10.0) -> None:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted, user-supplied webhook URL)
        if resp.status >= 300:
            raise RuntimeError(f"webhook returned HTTP {resp.status}")


def notify_if_needed(
    db_path: str,
    scan_run_id: int | None,
    webhook_url: str,
    fail_on: str = "fail",
    base_url: str | None = None,
) -> bool:
    """Sends a notification if any open defect is at/above `fail_on` severity.
    Returns whether a notification was actually sent."""
    with db_module.open_db(db_path) as conn:
        if scan_run_id is None:
            scan_run_id = db_module.latest_scan_run_id(conn)
            if scan_run_id is None:
                return False
        defect_rows = db_module.fetch_defect_records(conn)
        builder = build_manifest(conn, scan_run_id)

    threshold = SEVERITY_RANK.get(fail_on, 2)
    if not any(SEVERITY_RANK.get(r["severity"], 0) >= threshold for r in defect_rows):
        return False

    send_webhook(webhook_url, build_message(builder.build(), base_url))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a Slack-compatible webhook notification for open defects"
    )
    parser.add_argument("--db", default="insight.db")
    parser.add_argument("--scan-run-id", type=int, default=None)
    parser.add_argument("--webhook-url", required=True)
    parser.add_argument("--fail-on", choices=["info", "warn", "fail"], default="fail")
    parser.add_argument(
        "--base-url",
        default=None,
        help="GUI base URL to link back to the run, e.g. http://localhost:5000",
    )
    args = parser.parse_args()

    sent = notify_if_needed(
        args.db, args.scan_run_id, args.webhook_url, args.fail_on, args.base_url
    )
    print("notification sent" if sent else "no notification needed (below threshold)")


if __name__ == "__main__":
    main()

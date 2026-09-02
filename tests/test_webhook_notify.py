from __future__ import annotations

import json

from core import db as db_module
from ingest.adapters import fs_scan_adapter  # noqa: F401
from ingest.run_scan import run_scan
from output import webhook_notify
from rules.engine import build_context, run_all_rules


def _seeded_scan(db_path, fs_scan_sample_dir):
    scan_run_id = run_scan(db_path, "fs_scan", str(fs_scan_sample_dir), since=None)
    with db_module.open_db(db_path) as conn:
        context = build_context(conn, scan_run_id, str(fs_scan_sample_dir))
        for d in run_all_rules(context):
            db_module.upsert_defect_record(
                conn,
                d.asset_id,
                d.rule_id,
                d.severity,
                d.message,
                d.suggested_fix,
                scan_run_id,
            )
    return scan_run_id


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_build_message_lists_fail_rows_and_run_link():
    manifest = {
        "scan_run_id": 7,
        "sections": [
            {
                "section_id": "defect_summary",
                "type": "table",
                "data": {
                    "columns": ["asset_id", "rule_id", "severity", "first_seen_run_id"],
                    "rows": [
                        ["Assets/a.png", "naming_convention", "fail", 7],
                        ["Assets/b.mat", "unused_material", "warn", 7],
                    ],
                },
            }
        ],
    }
    text = webhook_notify.build_message(manifest, base_url="http://localhost:5000")
    assert "fail=1 warn=1" in text
    assert "Assets/a.png" in text
    assert "Assets/b.mat" not in text  # only fail rows are individually listed
    assert "http://localhost:5000/runs/7" in text


def test_notify_if_needed_skips_when_below_threshold(
    db_path, fs_scan_sample_dir, monkeypatch
):
    scan_run_id = _seeded_scan(
        db_path, fs_scan_sample_dir
    )  # only warn/info defects, no fail

    called = []
    monkeypatch.setattr(
        webhook_notify, "send_webhook", lambda *a, **k: called.append(a)
    )

    sent = webhook_notify.notify_if_needed(
        db_path, scan_run_id, "https://example.invalid/webhook", fail_on="fail"
    )
    assert sent is False
    assert called == []


def test_notify_if_needed_sends_when_at_threshold(
    db_path, fs_scan_sample_dir, monkeypatch
):
    scan_run_id = _seeded_scan(db_path, fs_scan_sample_dir)

    called = []
    monkeypatch.setattr(
        webhook_notify,
        "send_webhook",
        lambda url, text, **k: called.append((url, text)),
    )

    sent = webhook_notify.notify_if_needed(
        db_path, scan_run_id, "https://example.invalid/webhook", fail_on="warn"
    )
    assert sent is True
    assert len(called) == 1
    assert called[0][0] == "https://example.invalid/webhook"


def test_send_webhook_posts_json_payload(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["content_type"] = req.get_header("Content-type")
        return _FakeResponse()

    monkeypatch.setattr(webhook_notify.urllib.request, "urlopen", fake_urlopen)

    webhook_notify.send_webhook("https://example.invalid/webhook", "hello world")

    assert captured["url"] == "https://example.invalid/webhook"
    assert captured["body"] == {"text": "hello world"}
    assert captured["content_type"] == "application/json"

from __future__ import annotations

import shutil
import time

from core import db as db_module
from ingest.adapters import fs_scan_adapter  # noqa: F401
from output import webhook_notify
from rules.engine import DEFINITIONS_DIR
from webapp.app import create_app


def _trigger_scan_and_wait(client, timeout=5.0, **form_data):
    """POSTs /scan (which now runs in a background thread) and polls the job
    status endpoint until it finishes, returning the final status dict."""
    resp = client.post("/scan", data=form_data)
    assert resp.status_code == 302
    status_url = resp.headers["Location"] + "/status.json"

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(status_url).get_json()
        if data["status"] != "running":
            return data
        time.sleep(0.02)
    raise TimeoutError(f"scan job did not finish within {timeout}s")


def test_dashboard_loads(db_path):
    client = create_app(db_path).test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "スキャンを実行".encode() in resp.data


def test_trigger_scan_runs_in_background_and_redirects_to_run_detail(
    db_path, fs_scan_sample_dir
):
    client = create_app(db_path).test_client()
    data = _trigger_scan_and_wait(
        client, producer="fs_scan", target=str(fs_scan_sample_dir), run_checks="on"
    )
    assert data["status"] == "success"
    assert data["scan_run_ids"] == [1]

    resp = client.get(f"/runs/{data['scan_run_ids'][0]}")
    assert resp.status_code == 200
    assert "scan_run #1".encode() in resp.data
    assert "不具合一覧".encode() in resp.data


def test_job_status_page_renders_while_and_after_running(db_path, fs_scan_sample_dir):
    client = create_app(db_path).test_client()
    resp = client.post(
        "/scan",
        data={"producer": "fs_scan", "target": str(fs_scan_sample_dir), "run_checks": "on"},
    )
    assert resp.status_code == 302
    job_page = client.get(resp.headers["Location"])
    assert job_page.status_code == 200
    assert "スキャン".encode() in job_page.data


def test_trigger_scan_with_all_producers_reports_multiple_scan_run_ids(
    db_path, fs_scan_sample_dir
):
    """producer='all' triggers multiple independent scan_runs; the job status
    must report every one of them, not just the last producer's."""
    client = create_app(db_path).test_client()
    data = _trigger_scan_and_wait(
        client, producer="all", target=str(fs_scan_sample_dir), run_checks="on"
    )
    assert data["status"] == "success"
    assert len(data["scan_run_ids"]) >= 2

    with db_module.open_db(db_path) as conn:
        producers = {
            r["source_producer"] for r in conn.execute("SELECT source_producer FROM scan_runs")
        }
    assert len(producers) >= 2


def test_trigger_scan_with_invalid_target_flashes_error_synchronously(db_path):
    """Target-path validation happens before the background job is even
    created, so this is still a synchronous redirect straight to the
    dashboard with a flashed error — never a job to poll."""
    client = create_app(db_path).test_client()
    resp = client.post(
        "/scan",
        data={"producer": "fs_scan", "target": "C:\\this\\path\\does\\not\\exist", "run_checks": "on"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "存在しない".encode() in resp.data


def test_job_status_404_for_unknown_job_id(db_path):
    client = create_app(db_path).test_client()
    resp = client.get("/jobs/does-not-exist")
    assert resp.status_code == 404
    resp = client.get("/jobs/does-not-exist/status.json")
    assert resp.status_code == 404


def test_defects_page_filters_by_severity(db_path, fs_scan_sample_dir):
    client = create_app(db_path).test_client()
    _trigger_scan_and_wait(
        client, producer="fs_scan", target=str(fs_scan_sample_dir), run_checks="on"
    )

    resp_all = client.get("/defects")
    assert resp_all.status_code == 200

    resp_warn = client.get("/defects?severity=warn")
    assert resp_warn.status_code == 200
    tbody = resp_warn.data.split(b"<tbody>")[1].split(b"</tbody>")[0]
    assert b"severity-warn" in tbody
    assert b"severity-info" not in tbody


def test_trend_page_loads_without_data(db_path):
    client = create_app(db_path).test_client()
    resp = client.get("/trend")
    assert resp.status_code == 200


def test_trend_page_shows_time_series_charts_after_scans(db_path, fs_scan_sample_dir):
    client = create_app(db_path).test_client()
    _trigger_scan_and_wait(
        client, producer="fs_scan", target=str(fs_scan_sample_dir), run_checks="on"
    )
    resp = client.get("/trend")
    assert resp.status_code == 200
    assert "オープンなdefect数の推移".encode() in resp.data
    assert "アセット数の推移".encode() in resp.data
    assert "合計サイズ(MB)の推移".encode() in resp.data


def test_export_excel_and_ndjson_download(db_path, fs_scan_sample_dir):
    client = create_app(db_path).test_client()
    data = _trigger_scan_and_wait(
        client, producer="fs_scan", target=str(fs_scan_sample_dir), run_checks="on"
    )
    scan_run_id = data["scan_run_ids"][0]

    excel_resp = client.get(f"/runs/{scan_run_id}/export.xlsx")
    assert excel_resp.status_code == 200
    assert excel_resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    ndjson_resp = client.get(f"/runs/{scan_run_id}/export.ndjson")
    assert ndjson_resp.status_code == 200
    assert ndjson_resp.mimetype == "application/x-ndjson"


def test_run_detail_404_for_unknown_scan_run(db_path):
    client = create_app(db_path).test_client()
    resp = client.get("/runs/999")
    assert resp.status_code == 404


def _client_with_scratch_definitions(db_path, tmp_path):
    """create_app(definitions_dir=...) points the rules editor at a throwaway
    copy so these tests never write to the real, checked-in rule YAML files."""
    definitions_dir = tmp_path / "definitions"
    shutil.copytree(DEFINITIONS_DIR, definitions_dir)
    return create_app(db_path, definitions_dir=definitions_dir).test_client(), definitions_dir


def test_rules_list_page_shows_all_definitions(db_path, tmp_path):
    client, _ = _client_with_scratch_definitions(db_path, tmp_path)
    resp = client.get("/rules")
    assert resp.status_code == 200
    assert b"naming_convention" in resp.data
    assert b"coding_convention" in resp.data


def test_rule_edit_get_shows_raw_yaml_source(db_path, tmp_path):
    client, _ = _client_with_scratch_definitions(db_path, tmp_path)
    resp = client.get("/rules/naming_convention.yaml/edit")
    assert resp.status_code == 200
    assert b"rule_id: naming_convention" in resp.data


def test_rule_edit_get_404_for_unknown_file(db_path, tmp_path):
    client, _ = _client_with_scratch_definitions(db_path, tmp_path)
    resp = client.get("/rules/does_not_exist.yaml/edit")
    assert resp.status_code == 404


def test_rule_edit_post_saves_valid_yaml(db_path, tmp_path):
    client, definitions_dir = _client_with_scratch_definitions(db_path, tmp_path)
    resp = client.post(
        "/rules/naming_convention.yaml/edit",
        data={"source": "rule_id: naming_convention\nmodule: rules.naming_convention\nseverity: fail\n"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    saved = (definitions_dir / "naming_convention.yaml").read_text(encoding="utf-8")
    assert "severity: fail" in saved


def test_rule_edit_post_rejects_invalid_yaml_and_keeps_file_unchanged(db_path, tmp_path):
    client, definitions_dir = _client_with_scratch_definitions(db_path, tmp_path)
    original = (definitions_dir / "naming_convention.yaml").read_text(encoding="utf-8")

    resp = client.post(
        "/rules/naming_convention.yaml/edit",
        data={"source": "not valid yaml: [\n"},
    )
    assert resp.status_code == 200  # re-renders the editor with the error, no redirect
    assert (definitions_dir / "naming_convention.yaml").read_text(encoding="utf-8") == original


def test_run_detail_hides_notify_button_when_webhook_not_configured(db_path, fs_scan_sample_dir):
    client = create_app(db_path, webhook_url=None).test_client()
    data = _trigger_scan_and_wait(
        client, producer="fs_scan", target=str(fs_scan_sample_dir), run_checks="on"
    )
    resp = client.get(f"/runs/{data['scan_run_ids'][0]}")
    assert "INSIGHT_WEBHOOK_URL".encode() in resp.data


def test_notify_without_webhook_configured_flashes_error(db_path, fs_scan_sample_dir):
    client = create_app(db_path, webhook_url=None).test_client()
    data = _trigger_scan_and_wait(
        client, producer="fs_scan", target=str(fs_scan_sample_dir), run_checks="on"
    )
    resp = client.post(
        f"/runs/{data['scan_run_ids'][0]}/notify", follow_redirects=True
    )
    assert resp.status_code == 200
    assert "設定されていません".encode() in resp.data


def test_notify_sends_when_webhook_configured(db_path, fs_scan_sample_dir, monkeypatch):
    sent = []
    monkeypatch.setattr(
        webhook_notify, "send_webhook", lambda url, text, **k: sent.append((url, text))
    )

    client = create_app(db_path, webhook_url="https://example.invalid/webhook").test_client()
    data = _trigger_scan_and_wait(
        client, producer="fs_scan", target=str(fs_scan_sample_dir), run_checks="on"
    )
    resp = client.post(
        f"/runs/{data['scan_run_ids'][0]}/notify", follow_redirects=True
    )
    assert resp.status_code == 200
    assert "送信しました".encode() in resp.data
    assert len(sent) == 1
    assert sent[0][0] == "https://example.invalid/webhook"

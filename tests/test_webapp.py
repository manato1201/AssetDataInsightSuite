from __future__ import annotations

from ingest.adapters import fs_scan_adapter  # noqa: F401
from webapp.app import create_app


def test_dashboard_loads(db_path):
    client = create_app(db_path).test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "スキャンを実行".encode() in resp.data


def test_trigger_scan_redirects_to_run_detail(db_path, fs_scan_sample_dir):
    client = create_app(db_path).test_client()
    resp = client.post(
        "/scan",
        data={"producer": "fs_scan", "target": str(fs_scan_sample_dir), "run_checks": "on"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "scan_run #1".encode() in resp.data
    assert "不具合一覧".encode() in resp.data


def test_trigger_scan_with_invalid_target_flashes_error(db_path):
    client = create_app(db_path).test_client()
    resp = client.post(
        "/scan",
        data={"producer": "fs_scan", "target": "C:\\this\\path\\does\\not\\exist", "run_checks": "on"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "存在しない".encode() in resp.data


def test_defects_page_filters_by_severity(db_path, fs_scan_sample_dir):
    client = create_app(db_path).test_client()
    client.post("/scan", data={"producer": "fs_scan", "target": str(fs_scan_sample_dir), "run_checks": "on"})

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


def test_export_excel_and_ndjson_download(db_path, fs_scan_sample_dir):
    client = create_app(db_path).test_client()
    client.post("/scan", data={"producer": "fs_scan", "target": str(fs_scan_sample_dir), "run_checks": "on"})

    excel_resp = client.get("/runs/1/export.xlsx")
    assert excel_resp.status_code == 200
    assert excel_resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    ndjson_resp = client.get("/runs/1/export.ndjson")
    assert ndjson_resp.status_code == 200
    assert ndjson_resp.mimetype == "application/x-ndjson"


def test_run_detail_404_for_unknown_scan_run(db_path):
    client = create_app(db_path).test_client()
    resp = client.get("/runs/999")
    assert resp.status_code == 404

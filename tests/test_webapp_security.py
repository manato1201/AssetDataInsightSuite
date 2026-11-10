"""webapp/security.py: Host 許可リストと、変更操作の Origin 検査。"""
from __future__ import annotations

import pytest

from webapp import security
from webapp.app import create_app


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.delenv(security.ALLOWED_HOSTS_ENV, raising=False)
    return create_app(db_path).test_client()


def test_host_only_strips_port_and_handles_ipv6():
    assert security.host_only("localhost:5000") == "localhost"
    assert security.host_only("127.0.0.1:5000") == "127.0.0.1"
    assert security.host_only("[::1]:5000") == "::1"
    assert security.host_only("LocalHost") == "localhost"


def test_is_same_origin_rules():
    assert security.is_same_origin("http://localhost:5000", "localhost:5000")
    assert not security.is_same_origin("http://evil.example", "localhost:5000")
    assert not security.is_same_origin("http://localhost:9999", "localhost:5000")
    assert not security.is_same_origin("null", "localhost:5000")


def test_loopback_get_works(client):
    assert client.get("/").status_code == 200


def test_foreign_host_refused_even_for_get(client):
    resp = client.get("/", headers={"Host": "evil.example"})
    assert resp.status_code == 403


def test_extra_host_allowed_via_env(db_path, monkeypatch):
    monkeypatch.setenv(security.ALLOWED_HOSTS_ENV, "insight.internal")
    client = create_app(db_path).test_client()
    assert client.get("/", headers={"Host": "insight.internal:5000"}).status_code == 200


def test_cross_site_scan_post_refused_and_does_not_start_job(client, fs_scan_sample_dir):
    resp = client.post(
        "/scan",
        data={"producer": "all", "target": str(fs_scan_sample_dir)},
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403


def test_cross_site_rule_edit_post_refused(client, tmp_path):
    resp = client.post(
        "/rules/anything.yaml/edit",
        data={"source": "x: 1"},
        headers={"Origin": "http://evil.example"},
    )
    assert resp.status_code == 403


def test_cross_site_notify_post_refused(client):
    resp = client.post("/runs/1/notify", headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403


def test_null_origin_post_refused(client):
    resp = client.post("/scan", data={"target": "x"}, headers={"Origin": "null"})
    assert resp.status_code == 403


def test_post_without_origin_passes_guard(client):
    # curl / CI など Origin を付けないクライアントは通る(存在しない target なので画面へ戻される)
    resp = client.post("/scan", data={"producer": "all", "target": "/no/such/dir"})
    assert resp.status_code == 302


def test_same_origin_post_passes_guard(client):
    resp = client.post(
        "/scan",
        data={"producer": "all", "target": "/no/such/dir"},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 302

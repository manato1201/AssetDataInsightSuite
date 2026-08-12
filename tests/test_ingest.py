from __future__ import annotations

from core import db as db_module
from ingest.adapters import fs_scan_adapter, lqa_adapter, unity_asset_adapter  # noqa: F401
from ingest.adapters.registry import ADAPTER_REGISTRY
from ingest.run_scan import run_scan


def test_registry_has_all_three_producers():
    assert {"lqa", "fs_scan", "unity_asset"}.issubset(ADAPTER_REGISTRY)


def test_lqa_adapter_normalizes_latest_record(lqa_sample_dir):
    adapter = ADAPTER_REGISTRY["lqa"]
    records = adapter.scan(str(lqa_sample_dir))
    by_id = {r.asset_id: r for r in records}

    rock = by_id["Assets/Textures/rock_d.png"]
    assert rock.checks["resolution_px"].value == 4096
    assert rock.checks["naming_convention"].status == "pass"


def test_lqa_adapter_conversion_errors_merge_into_checks(lqa_sample_dir):
    adapter = ADAPTER_REGISTRY["lqa"]
    records = adapter.scan(str(lqa_sample_dir))
    rock = next(r for r in records if r.asset_id == "Assets/Textures/rock_d.png")
    assert "conversion_error" in rock.checks
    assert rock.checks["conversion_error"].status == "fail"


def test_lqa_adapter_unknown_check_id_does_not_error(lqa_sample_dir):
    adapter = ADAPTER_REGISTRY["lqa"]
    records = adapter.scan(str(lqa_sample_dir))
    rock = next(r for r in records if r.asset_id == "Assets/Textures/rock_d.png")
    assert "future_unknown_check" in rock.checks
    assert rock.checks["future_unknown_check"].status == "warn"


def test_fs_scan_adapter_normalizes_fixture(fs_scan_sample_dir):
    adapter = ADAPTER_REGISTRY["fs_scan"]
    records = adapter.scan(str(fs_scan_sample_dir))
    asset_ids = {r.asset_id for r in records}
    assert "Assets/Textures/T_rock_d.png" in asset_ids
    assert "Assets/Materials/M_unused.mat" in asset_ids

    texture = next(r for r in records if r.asset_id == "Assets/Textures/T_rock_d.png")
    assert texture.asset_type == "texture"
    assert texture.size_bytes > 0
    assert texture.source_producer == "fs_scan"


def test_ingestion_is_idempotent(db_path, fs_scan_sample_dir):
    run_scan(db_path, "fs_scan", str(fs_scan_sample_dir), since=None)
    run_scan(db_path, "fs_scan", str(fs_scan_sample_dir), since=None)

    with db_module.open_db(db_path) as conn:
        run_ids = [
            r["scan_run_id"]
            for r in conn.execute(
                "SELECT scan_run_id FROM scan_runs ORDER BY scan_run_id"
            )
        ]
        assert len(run_ids) == 2

        def snapshot(scan_run_id):
            rows = db_module.fetch_asset_records(conn, scan_run_id)
            return {
                r["asset_id"]: (r["asset_type"], r["size_bytes"], r["extension"])
                for r in rows
            }

        first, second = snapshot(run_ids[0]), snapshot(run_ids[1])
        assert first == second

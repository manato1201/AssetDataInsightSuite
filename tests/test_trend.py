from __future__ import annotations

from core import db as db_module
from core.schema import AssetRecord, CheckResult
from trend import aggregations


def _seed_texture_records(db_path: str, sizes_and_res: list[tuple[int, int]]) -> int:
    with db_module.open_db(db_path) as conn:
        scan_run_id = db_module.start_scan_run(
            conn, "fs_scan", "0.1.0", "2026-08-01T00:00:00Z"
        )
        records = []
        for i, (size_bytes, resolution) in enumerate(sizes_and_res):
            records.append(
                AssetRecord(
                    asset_id=f"Assets/Textures/tex_{i}.png",
                    asset_type="texture",
                    source_producer="fs_scan",
                    collected_at="2026-08-01T00:00:00Z",
                    size_bytes=size_bytes,
                    extension=".png",
                    last_modified=f"2026-0{(i % 6) + 1}-01T00:00:00Z",
                    checks={
                        "resolution_px": CheckResult(status="info", value=resolution)
                    },
                )
            )
        db_module.insert_asset_records(conn, scan_run_id, records)
        db_module.finish_scan_run(conn, scan_run_id, "2026-08-01T00:05:00Z", "success")
    return scan_run_id


def test_outliers_zscore_and_iqr_on_check_values(db_path):
    with db_module.open_db(db_path) as conn:
        scan_run_id = db_module.start_scan_run(
            conn, "fs_scan", "0.1.0", "2026-08-01T00:00:00Z"
        )
        records = []
        values = [10, 11, 9, 10, 12, 11, 10, 500]  # 500 is the outlier
        for i, v in enumerate(values):
            records.append(
                AssetRecord(
                    asset_id=f"Assets/Models/m_{i}.fbx",
                    asset_type="model",
                    source_producer="fs_scan",
                    collected_at="2026-08-01T00:00:00Z",
                    size_bytes=1000,
                    extension=".fbx",
                    last_modified="2026-08-01T00:00:00Z",
                    checks={"draw_calls": CheckResult(status="info", value=v)},
                )
            )
        db_module.insert_asset_records(conn, scan_run_id, records)
        db_module.finish_scan_run(conn, scan_run_id, "2026-08-01T00:05:00Z", "success")

        zscore_result = aggregations.outliers(
            conn, scan_run_id, "draw_calls", method="zscore", threshold=1.5
        )
        assert any(r["asset_id"] == "Assets/Models/m_7.fbx" for r in zscore_result)

        iqr_result = aggregations.outliers(
            conn, scan_run_id, "draw_calls", method="iqr", threshold=1.5
        )
        assert any(r["asset_id"] == "Assets/Models/m_7.fbx" for r in iqr_result)


def test_aggregations_are_pure_and_repeatable(db_path):
    scan_run_id = _seed_texture_records(
        db_path, [(1000, 256), (2000, 1024), (3000, 4096)]
    )
    with db_module.open_db(db_path) as conn:
        first = aggregations.texture_resolution_histogram(
            conn, scan_run_id, [256, 512, 1024, 2048, 4096]
        )
        second = aggregations.texture_resolution_histogram(
            conn, scan_run_id, [256, 512, 1024, 2048, 4096]
        )
        assert first == second
        assert sum(first.values()) == 3


def test_size_distribution_buckets(db_path):
    scan_run_id = _seed_texture_records(
        db_path, [(50 * 1024, 256), (500 * 1024, 512), (5 * 1024 * 1024, 1024)]
    )
    with db_module.open_db(db_path) as conn:
        dist = aggregations.size_distribution(conn, scan_run_id)
        assert dist["<100KB"] == 1
        assert dist["100KB-1MB"] == 1
        assert dist["1MB-10MB"] == 1


def test_extension_breakdown(db_path):
    scan_run_id = _seed_texture_records(db_path, [(1000, 256), (2000, 512)])
    with db_module.open_db(db_path) as conn:
        breakdown = aggregations.extension_breakdown(conn, scan_run_id)
        assert breakdown[".png"] == 2


def test_diff_against_previous_has_no_baseline_on_first_scan(db_path):
    scan_run_id = _seed_texture_records(db_path, [(1000, 256)])
    with db_module.open_db(db_path) as conn:
        diff = aggregations.diff_against_previous(conn, scan_run_id)
    assert diff["previous_scan_run_id"] is None
    assert diff["added_ids"] == diff["changed_ids"] == diff["removed_ids"] == []


def test_diff_against_previous_detects_added_changed_removed(db_path):
    def _record(asset_id, size_bytes):
        return AssetRecord(
            asset_id=asset_id,
            asset_type="texture",
            source_producer="fs_scan",
            collected_at="2026-08-01T00:00:00Z",
            size_bytes=size_bytes,
            extension=".png",
            last_modified="2026-08-01T00:00:00Z",
            checks={},
        )

    with db_module.open_db(db_path) as conn:
        run1 = db_module.start_scan_run(
            conn, "fs_scan", "0.1.0", "2026-08-01T00:00:00Z"
        )
        db_module.insert_asset_records(
            conn,
            run1,
            [_record("a.png", 1000), _record("b.png", 2000), _record("c.png", 3000)],
        )
        db_module.finish_scan_run(conn, run1, "2026-08-01T00:05:00Z", "success")

        # a.png unchanged, b.png size changed, c.png removed, d.png newly added
        run2 = db_module.start_scan_run(
            conn, "fs_scan", "0.1.0", "2026-08-02T00:00:00Z"
        )
        db_module.insert_asset_records(
            conn,
            run2,
            [_record("a.png", 1000), _record("b.png", 9999), _record("d.png", 4000)],
        )
        db_module.finish_scan_run(conn, run2, "2026-08-02T00:05:00Z", "success")

        diff = aggregations.diff_against_previous(conn, run2)

    assert diff["previous_scan_run_id"] == run1
    assert diff["added_ids"] == ["d.png"]
    assert diff["changed_ids"] == ["b.png"]
    assert diff["removed_ids"] == ["c.png"]

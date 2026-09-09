from __future__ import annotations

from core import db as db_module
from core.schema import AssetRecord, CheckResult
from trend import aggregations
from trend.charts import render_dot_chart_svg


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


def test_asset_count_and_total_size_over_time(db_path):
    run1 = _seed_texture_records(db_path, [(1000, 256), (2000, 512)])
    run2 = _seed_texture_records(db_path, [(1000, 256), (2000, 512), (3000, 1024)])

    with db_module.open_db(db_path) as conn:
        asset_counts = aggregations.asset_count_over_time(conn, limit=10)
        total_sizes = aggregations.total_size_over_time(conn, limit=10)

    assert asset_counts[str(run1)] == 2
    assert asset_counts[str(run2)] == 3
    assert total_sizes[str(run1)] == 3000
    assert total_sizes[str(run2)] == 6000


def test_open_defect_count_over_time_reflects_resolution(db_path, tmp_path):
    from ingest.run_scan import run_scan
    from rules.run_checks import run_checks

    project = tmp_path / "project"
    (project / "Assets" / "Textures").mkdir(parents=True)
    bad = project / "Assets" / "Textures" / "bad_name.png"
    bad.write_bytes(b"x")

    run1 = run_scan(db_path, "fs_scan", str(project), since=None)
    run_checks(db_path, str(project), run1)

    bad.unlink()
    (project / "Assets" / "Textures" / "T_bad_name.png").write_bytes(b"x")
    run2 = run_scan(db_path, "fs_scan", str(project), since=None)
    run_checks(db_path, str(project), run2)

    with db_module.open_db(db_path) as conn:
        series = aggregations.open_defect_count_over_time(conn, limit=10)

    assert series[str(run1)] >= 1  # naming_convention was open at run1
    assert series[str(run2)] < series[str(run1)]  # resolved by run2


def test_texture_size_points_flags_the_same_outliers_as_outliers_zscore(db_path):
    # 8 normal-ish sizes around 1000 bytes, one clear outlier at 100000.
    sizes_and_res = [(1000 + i * 10, 256) for i in range(8)] + [(100000, 256)]
    scan_run_id = _seed_texture_records(db_path, sizes_and_res)

    with db_module.open_db(db_path) as conn:
        result = aggregations.texture_size_points(
            conn, scan_run_id, method="zscore", threshold=1.5
        )

    assert len(result["points"]) == 9
    outliers = [p for p in result["points"] if p["is_outlier"]]
    assert len(outliers) == 1
    assert outliers[0]["value"] == 100000
    assert result["mean"] == sum(v for v, _ in sizes_and_res) / len(sizes_and_res)
    assert result["outlier_method"] == "zscore"


def test_texture_size_points_empty_when_no_textures(db_path):
    with db_module.open_db(db_path) as conn:
        scan_run_id = db_module.start_scan_run(
            conn, "fs_scan", "0.1.0", "2026-08-01T00:00:00Z"
        )
        db_module.finish_scan_run(conn, scan_run_id, "2026-08-01T00:05:00Z", "success")
        result = aggregations.texture_size_points(conn, scan_run_id)

    assert result == {"points": [], "mean": 0.0, "outlier_method": "zscore"}


def test_render_dot_chart_svg_marks_outlier_points_with_a_distinct_class():
    data = {
        "points": [
            {"asset_id": "a.png", "value": 1000, "is_outlier": False},
            {"asset_id": "b.png", "value": 1010, "is_outlier": False},
            {"asset_id": "c.png", "value": 100000, "is_outlier": True},
        ],
        "mean": 34003.3,
        "outlier_method": "zscore",
    }
    svg = render_dot_chart_svg(data)
    assert svg.startswith("<svg")
    assert svg.count("<circle") == 3
    assert 'class="dot-outlier"' in svg
    assert svg.count('class="dot-normal"') == 2
    assert "dot-mean-line" in svg


def test_render_dot_chart_svg_handles_no_points():
    svg = render_dot_chart_svg({"points": [], "mean": 0, "outlier_method": "zscore"})
    assert svg.startswith("<svg")
    assert "<circle" not in svg

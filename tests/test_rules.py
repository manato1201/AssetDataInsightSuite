from __future__ import annotations

from core import db as db_module
from ingest.adapters import fs_scan_adapter  # noqa: F401
from ingest.run_scan import run_scan
from rules.engine import (
    DEFINITIONS_DIR,
    build_context,
    load_rule_definitions,
    run_all_rules,
)


def test_rule_definitions_are_loaded_from_yaml_not_hardcoded():
    definitions = load_rule_definitions(DEFINITIONS_DIR)
    rule_ids = {d["rule_id"] for d in definitions}
    assert rule_ids == {
        "naming_convention",
        "coding_convention",
        "lod_missing",
        "unused_material",
        "individual_fix_required",
    }
    for d in definitions:
        assert "module" in d


def _run_pipeline(db_path, target_dir):
    scan_run_id = run_scan(db_path, "fs_scan", str(target_dir), since=None)
    with db_module.open_db(db_path) as conn:
        context = build_context(conn, scan_run_id, str(target_dir))
        defects = run_all_rules(context)
    return scan_run_id, defects


def test_naming_convention_flags_only_bad_names(db_path, fs_scan_sample_dir):
    _, defects = _run_pipeline(db_path, fs_scan_sample_dir)
    naming_defects = {d.asset_id for d in defects if d.rule_id == "naming_convention"}
    assert "Assets/Textures/badly_named.png" in naming_defects
    assert "Assets/Textures/T_rock_d.png" not in naming_defects


def test_unused_material_flags_only_unreferenced_material(db_path, fs_scan_sample_dir):
    _, defects = _run_pipeline(db_path, fs_scan_sample_dir)
    unused = {d.asset_id for d in defects if d.rule_id == "unused_material"}
    assert unused == {"Assets/Materials/M_unused.mat"}


def test_individual_override_emits_defect_record(db_path, fs_scan_sample_dir):
    _, defects = _run_pipeline(db_path, fs_scan_sample_dir)
    override_defects = [d for d in defects if d.rule_id == "individual_fix_required"]
    assert any(d.asset_id == "Assets/Characters/hero_rig.fbx" for d in override_defects)
    hero = next(
        d for d in override_defects if d.asset_id == "Assets/Characters/hero_rig.fbx"
    )
    assert hero.suggested_fix == "hero_rig_v2への差し替え待ち"


def test_defect_first_seen_last_seen_upsert_semantics(db_path, fs_scan_sample_dir):
    scan_run_id_1, defects_1 = _run_pipeline(db_path, fs_scan_sample_dir)

    with db_module.open_db(db_path) as conn:
        for d in defects_1:
            db_module.upsert_defect_record(
                conn,
                d.asset_id,
                d.rule_id,
                d.severity,
                d.message,
                d.suggested_fix,
                scan_run_id_1,
            )

    scan_run_id_2 = run_scan(db_path, "fs_scan", str(fs_scan_sample_dir), since=None)
    with db_module.open_db(db_path) as conn:
        context = build_context(conn, scan_run_id_2, str(fs_scan_sample_dir))
        defects_2 = run_all_rules(context)
        for d in defects_2:
            db_module.upsert_defect_record(
                conn,
                d.asset_id,
                d.rule_id,
                d.severity,
                d.message,
                d.suggested_fix,
                scan_run_id_2,
            )

        row = conn.execute(
            "SELECT first_seen_run_id, last_seen_run_id FROM defect_records "
            "WHERE asset_id = 'Assets/Textures/badly_named.png' AND rule_id = 'naming_convention'"
        ).fetchone()
        assert row["first_seen_run_id"] == scan_run_id_1
        assert row["last_seen_run_id"] == scan_run_id_2

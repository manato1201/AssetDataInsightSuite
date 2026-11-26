"""運用 GUI のばねの動き(webapp/static/motion.js)の配線を確かめる。

動きそのものはブラウザで確認する。ここでは「どの画面に何が付いているか」と
「JS が無くても値が読めるか」「ばねの値が決めた数字のままか」だけを見る。
"""
from __future__ import annotations

import re
from pathlib import Path

from webapp.app import create_app

MOTION_JS = Path(__file__).resolve().parents[1] / "webapp" / "static" / "motion.js"


def test_dashboard_stat_values_count_up_but_render_final_value(db_path):
    html = create_app(db_path).test_client().get("/").get_data(as_text=True)
    assert "static/motion.js" in html
    counts = re.findall(r'<span class="stat-value" data-count="(\d+)">(\d+)</span>', html)
    assert len(counts) == 4
    # JS が動かなくても(または動きを減らす設定でも)最終の値がそのまま見える
    assert all(attr == text for attr, text in counts)


def test_rule_editor_has_yaml_drop_bound_to_the_textarea(db_path):
    client = create_app(db_path).test_client()
    html = client.get("/rules/lod_missing.yaml/edit").get_data(as_text=True)
    target = re.search(r'data-yaml-drop="([^"]+)"', html).group(1)
    assert f'id="{target}"' in html
    assert 'name="source"' in html
    assert 'accept=".yaml,.yml"' in html
    assert 'role="status"' in html


def test_yaml_drop_is_only_on_the_rule_editor(db_path):
    client = create_app(db_path).test_client()
    for path in ("/", "/rules", "/trend", "/defects"):
        assert "data-yaml-drop" not in client.get(path).get_data(as_text=True), path


def test_spring_values_match_the_reference_component():
    src = MOTION_JS.read_text(encoding="utf-8")
    expected = {
        "statCount": (160, 22),
        "zoneScale": (380, 16),
        "zoneHover": (300, 26),
        "coreScale": (420, 14),
        "upIcon": (420, 30),
        "flood": (260, 21),
        "check": (200, 26),
        "textRoll": (360, 30),
    }
    for name, (k, c) in expected.items():
        assert re.search(rf"{name}: \[{k}, {c}\]", src), name
    assert "prefers-reduced-motion: reduce" in src


def test_motion_js_reads_files_locally_only():
    """ファイルはブラウザの中で読むだけ。どこにも送らない。"""
    src = MOTION_JS.read_text(encoding="utf-8")
    for word in ("fetch(", "XMLHttpRequest", "sendBeacon", "FormData"):
        assert word not in src, word

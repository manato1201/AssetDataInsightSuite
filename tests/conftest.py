from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def lqa_sample_dir() -> Path:
    return FIXTURES_DIR / "lqa_sample"


@pytest.fixture
def fs_scan_sample_dir() -> Path:
    return FIXTURES_DIR / "fs_scan_sample"


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "insight.db")

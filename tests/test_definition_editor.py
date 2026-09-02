from __future__ import annotations

import shutil

import pytest

from rules.definition_editor import (
    RuleDefinitionError,
    list_definition_filenames,
    read_definition_source,
    write_definition_source,
)
from rules.engine import DEFINITIONS_DIR


@pytest.fixture
def definitions_copy(tmp_path):
    """A throwaway copy of rules/definitions/ so write tests never touch the
    real, checked-in rule YAML files."""
    dest = tmp_path / "definitions"
    shutil.copytree(DEFINITIONS_DIR, dest)
    return dest


def test_list_definition_filenames_returns_all_yaml_files(definitions_copy):
    filenames = list_definition_filenames(definitions_copy)
    assert "naming_convention.yaml" in filenames
    assert all(f.endswith(".yaml") for f in filenames)


def test_read_definition_source_returns_raw_text(definitions_copy):
    text = read_definition_source("naming_convention.yaml", definitions_copy)
    assert "rule_id: naming_convention" in text


def test_read_definition_source_rejects_unknown_file(definitions_copy):
    with pytest.raises(RuleDefinitionError):
        read_definition_source("does_not_exist.yaml", definitions_copy)


def test_write_definition_source_persists_valid_changes(definitions_copy):
    write_definition_source(
        "naming_convention.yaml",
        "rule_id: naming_convention\nmodule: rules.naming_convention\nseverity: fail\n",
        definitions_copy,
    )
    text = read_definition_source("naming_convention.yaml", definitions_copy)
    assert "severity: fail" in text


def test_write_definition_source_rejects_invalid_yaml(definitions_copy):
    original = read_definition_source("naming_convention.yaml", definitions_copy)
    with pytest.raises(RuleDefinitionError):
        write_definition_source(
            "naming_convention.yaml", "foo: [1, 2\n", definitions_copy
        )
    assert (
        read_definition_source("naming_convention.yaml", definitions_copy) == original
    )


def test_write_definition_source_rejects_missing_required_keys(definitions_copy):
    with pytest.raises(RuleDefinitionError):
        write_definition_source(
            "naming_convention.yaml", "severity: warn\n", definitions_copy
        )


def test_write_definition_source_rejects_non_mapping_yaml(definitions_copy):
    with pytest.raises(RuleDefinitionError):
        write_definition_source(
            "naming_convention.yaml", "- just\n- a\n- list\n", definitions_copy
        )


def test_write_definition_source_rejects_path_traversal(definitions_copy):
    with pytest.raises(RuleDefinitionError):
        write_definition_source(
            "../outside.yaml", "rule_id: x\nmodule: y\n", definitions_copy
        )
    assert not (definitions_copy.parent / "outside.yaml").exists()

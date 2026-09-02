"""Read/write access to `rules/definitions/*.yaml` for the GUI editor.

Kept separate from `rules/engine.py` (which only ever *evaluates* rules) so
the evaluation path has no file-write capability anywhere near it. Writes
are validated before touching disk: the YAML must parse, and must still
carry the `rule_id` and `module` keys the engine requires — an editor typo
should never be able to silently take down `rules.run_checks` for every
rule, since `load_rule_definitions()` reads every file in the directory.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from rules.engine import DEFINITIONS_DIR

_REQUIRED_KEYS = ("rule_id", "module")


class RuleDefinitionError(ValueError):
    pass


def list_definition_filenames(definitions_dir: Path = DEFINITIONS_DIR) -> list[str]:
    return sorted(p.name for p in definitions_dir.glob("*.yaml"))


def _resolve(filename: str, definitions_dir: Path) -> Path:
    # Reject path separators / traversal outright rather than relying only on
    # the resolved-path containment check below, which is a good backstop but
    # a worse first line of defense against `..` or absolute-path input.
    if "/" in filename or "\\" in filename or Path(filename).name != filename:
        raise RuleDefinitionError(f"invalid filename: {filename}")

    path = (definitions_dir / filename).resolve()
    if definitions_dir.resolve() not in path.parents:
        raise RuleDefinitionError(f"invalid filename: {filename}")
    if not path.is_file():
        raise RuleDefinitionError(f"no such rule definition: {filename}")
    return path


def read_definition_source(filename: str, definitions_dir: Path = DEFINITIONS_DIR) -> str:
    path = _resolve(filename, definitions_dir)
    return path.read_text(encoding="utf-8")


def validate_definition_source(text: str) -> dict:
    """Parses `text` and checks it has the keys the engine requires. Returns
    the parsed dict on success; raises RuleDefinitionError on any problem."""
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RuleDefinitionError(f"YAMLの構文エラー: {exc}") from exc

    if not isinstance(parsed, dict):
        raise RuleDefinitionError("ルール定義はYAMLのマップ(key: value)である必要があります")
    missing = [k for k in _REQUIRED_KEYS if k not in parsed]
    if missing:
        raise RuleDefinitionError(f"必須キーがありません: {', '.join(missing)}")
    return parsed


def write_definition_source(
    filename: str, text: str, definitions_dir: Path = DEFINITIONS_DIR
) -> None:
    path = _resolve(filename, definitions_dir)
    validate_definition_source(text)  # raises before anything touches disk
    path.write_text(text, encoding="utf-8")

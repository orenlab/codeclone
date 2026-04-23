from __future__ import annotations

import re
from pathlib import Path

import pytest

from codeclone.config.argparse_builder import build_parser
from codeclone.config.pyproject_loader import load_pyproject_config
from codeclone.config.resolver import collect_explicit_cli_dests, resolve_config
from codeclone.config.spec import PYPROJECT_OPTIONS, TESTABLE_CLI_OPTIONS, OptionSpec


def _option_id(option: OptionSpec) -> str:
    if option.flags:
        return f"{option.dest}:{option.flags[0]}"
    return f"{option.dest}:positional"


def _cli_sample(option: OptionSpec) -> tuple[tuple[str, ...], object]:
    if option.cli_kind == "positional":
        return (("sample-root",), "sample-root")
    if option.cli_kind == "bool_optional":
        return ((option.flags[0],), True)
    if option.cli_kind == "store_true":
        return ((option.flags[0],), True)
    if option.cli_kind == "store_false":
        return ((option.flags[0],), False)
    if option.value_type is int:
        return ((option.flags[0], "7"), 7)
    return ((option.flags[0], "sample-value"), "sample-value")


def _pyproject_sample(option: OptionSpec, root_path: Path) -> tuple[str, object]:
    config_spec = option.config_spec
    assert config_spec is not None
    expected_type = config_spec.expected_type

    if expected_type is bool:
        return ("true", True)
    if expected_type is int:
        return ("7", 7)
    if expected_type is str:
        raw_value = "reports/output.json" if option.path_value else "sample-value"
        expected = str(root_path / raw_value) if option.path_value else raw_value
        return (f'"{raw_value}"', expected)
    if expected_type is list:
        return ('["./tests/fixtures/golden_*"]', ("tests/fixtures/golden_*",))
    raise AssertionError(f"Unsupported sample type for {option.pyproject_key}")


def test_resolve_config_prefers_explicit_cli_values() -> None:
    parser = build_parser("2.0.0")
    argv = ["--min-loc", "11"]
    args = parser.parse_args(argv)

    resolved = resolve_config(
        args=args,
        config_values={"min_loc": 42, "max_cache_size_mb": 77},
        explicit_cli_dests=collect_explicit_cli_dests(parser, argv=argv),
    )

    assert resolved.values["min_loc"] == 11
    assert resolved.values["max_cache_size_mb"] == 77
    assert resolved.explicit_cli_dests == frozenset({"min_loc"})


def test_pyproject_option_count_matches_declared_specs() -> None:
    pyproject_keys = [option.pyproject_key for option in PYPROJECT_OPTIONS]
    assert all(key is not None for key in pyproject_keys)
    assert len(pyproject_keys) == len(set(pyproject_keys))


@pytest.mark.parametrize("option", TESTABLE_CLI_OPTIONS, ids=_option_id)
def test_option_specs_have_cli_parsing_coverage(option: OptionSpec) -> None:
    parser = build_parser("2.0.0")
    argv, expected = _cli_sample(option)
    args = parser.parse_args(list(argv))
    assert getattr(args, option.dest) == expected


@pytest.mark.parametrize(
    "option",
    [
        option
        for option in TESTABLE_CLI_OPTIONS
        if option.const is not None and option.flags
    ],
    ids=_option_id,
)
def test_option_specs_cover_cli_const_behaviour(option: OptionSpec) -> None:
    parser = build_parser("2.0.0")
    args = parser.parse_args([option.flags[0]])
    assert getattr(args, option.dest) == option.const


@pytest.mark.parametrize("option", PYPROJECT_OPTIONS, ids=_option_id)
def test_option_specs_have_pyproject_loading_coverage(
    option: OptionSpec,
    tmp_path: Path,
) -> None:
    pyproject_key = option.pyproject_key
    assert pyproject_key is not None
    raw_value, expected = _pyproject_sample(option, tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.codeclone]\n{pyproject_key} = {raw_value}\n",
        encoding="utf-8",
    )

    loaded = load_pyproject_config(tmp_path)
    assert loaded[pyproject_key] == expected


def test_config_defaults_doc_covers_exact_pyproject_key_set() -> None:
    text = Path("docs/book/04-config-and-defaults.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([a-z0-9_]+)`\s+\|", text, re.MULTILINE))
    declared = {
        option.pyproject_key
        for option in PYPROJECT_OPTIONS
        if option.pyproject_key is not None
    }

    assert documented == declared

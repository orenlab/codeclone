# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import codeclone.config.pyproject_loader as loader_mod
import codeclone.config.resolver as resolver_mod
import codeclone.config.spec as spec_mod
from codeclone.config.pyproject_loader import ConfigValidationError


def _write_pyproject(path: Path, content: str) -> None:
    path.write_text(content, "utf-8")


def test_collect_explicit_cli_dests_stops_on_double_dash() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-loc", dest="min_loc", type=int, default=20)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--json", dest="json_out")
    explicit = resolver_mod.collect_explicit_cli_dests(
        parser,
        argv=("--min-loc=10", "--quiet", "--", "--json", "report.json"),
    )
    assert explicit == {"min_loc", "quiet"}


def test_load_pyproject_config_missing_file_returns_empty(tmp_path: Path) -> None:
    assert loader_mod.load_pyproject_config(tmp_path) == {}


def test_load_pyproject_config_raises_on_loader_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject, "[tool]\n")

    def _raise_oserror(_path: Path) -> object:
        raise OSError("denied")

    monkeypatch.setattr(loader_mod, "_load_toml", _raise_oserror)
    with pytest.raises(
        ConfigValidationError,
        match=r"Cannot read pyproject\.toml",
    ):
        loader_mod.load_pyproject_config(tmp_path)

    def _raise_value_error(_path: Path) -> object:
        raise ValueError("broken")

    monkeypatch.setattr(loader_mod, "_load_toml", _raise_value_error)
    with pytest.raises(ConfigValidationError, match="Invalid TOML"):
        loader_mod.load_pyproject_config(tmp_path)


def test_load_pyproject_config_validates_tool_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject, "[tool]\n")

    monkeypatch.setattr(loader_mod, "_load_toml", lambda _path: [])
    with pytest.raises(ConfigValidationError, match="root must be object"):
        loader_mod.load_pyproject_config(tmp_path)

    monkeypatch.setattr(loader_mod, "_load_toml", lambda _path: {"tool": "bad"})
    with pytest.raises(ConfigValidationError, match="'tool' must be object"):
        loader_mod.load_pyproject_config(tmp_path)

    monkeypatch.setattr(
        loader_mod,
        "_load_toml",
        lambda _path: {"tool": {"codeclone": []}},
    )
    with pytest.raises(
        ConfigValidationError,
        match=r"'tool\.codeclone' must be object",
    ):
        loader_mod.load_pyproject_config(tmp_path)

    monkeypatch.setattr(loader_mod, "_load_toml", lambda _path: {"tool": {}})
    assert loader_mod.load_pyproject_config(tmp_path) == {}

    monkeypatch.setattr(loader_mod, "_load_toml", lambda _path: {"tool": None})
    assert loader_mod.load_pyproject_config(tmp_path) == {}

    monkeypatch.setattr(
        loader_mod,
        "_load_toml",
        lambda _path: {"tool": {"other": {}}},
    )
    assert loader_mod.load_pyproject_config(tmp_path) == {}


def test_load_pyproject_config_unknown_key_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write_pyproject(pyproject, "[tool]\n")
    monkeypatch.setattr(
        loader_mod,
        "_load_toml",
        lambda _path: {"tool": {"codeclone": {"unknown_option": 1}}},
    )
    with pytest.raises(ConfigValidationError, match="Unknown key\\(s\\)"):
        loader_mod.load_pyproject_config(tmp_path)


def test_load_pyproject_config_normalizes_relative_and_absolute_paths(
    tmp_path: Path,
) -> None:
    _write_pyproject(
        tmp_path / "pyproject.toml",
        """
[tool.codeclone]
min_loc = 5
cache_path = ".cache/codeclone/cache.json"
json_out = "/tmp/report.json"
md_out = "reports/report.md"
sarif_out = "reports/report.sarif"
""".strip(),
    )
    loaded = loader_mod.load_pyproject_config(tmp_path)
    assert loaded["min_loc"] == 5
    assert loaded["cache_path"] == str(tmp_path / ".cache/codeclone/cache.json")
    assert loaded["json_out"] == "/tmp/report.json"
    assert loaded["md_out"] == str(tmp_path / "reports/report.md")
    assert loaded["sarif_out"] == str(tmp_path / "reports/report.sarif")


def test_apply_pyproject_config_overrides_respects_explicit_cli_flags() -> None:
    args = argparse.Namespace(min_loc=10, quiet=False)
    resolver_mod.apply_pyproject_config_overrides(
        args=args,
        config_values={"min_loc": 42, "quiet": True},
        explicit_cli_dests={"quiet"},
    )
    assert args.min_loc == 42
    assert args.quiet is False


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("update_baseline", True, True),
        ("min_loc", 10, 10),
        ("baseline", "codeclone.baseline.json", "codeclone.baseline.json"),
        ("cache_path", None, None),
        (
            "golden_fixture_paths",
            ["tests/fixtures/golden_*", "tests/fixtures/golden_*"],
            ("tests/fixtures/golden_*",),
        ),
    ],
)
def test_validate_config_value_accepts_expected_types(
    key: str, value: object, expected: object
) -> None:
    assert loader_mod.validate_config_value(key=key, value=value) == expected


@pytest.mark.parametrize(
    ("key", "value", "error_fragment"),
    [
        ("min_loc", None, "expected int"),
        ("update_baseline", "yes", "expected bool"),
        ("min_loc", True, "expected int"),
        ("baseline", 1, "expected str"),
        (
            "golden_fixture_paths",
            "tests/fixtures/golden_*",
            "expected list\\[str\\]",
        ),
        (
            "golden_fixture_paths",
            ["tests/fixtures/golden_*", 1],
            "expected list\\[str\\]",
        ),
        ("golden_fixture_paths", ["pkg/*"], "must target tests/"),
    ],
)
def test_validate_config_value_rejects_invalid_types(
    key: str, value: object, error_fragment: str
) -> None:
    with pytest.raises(ConfigValidationError, match=error_fragment):
        loader_mod.validate_config_value(key=key, value=value)


def test_validate_config_value_unsupported_spec_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        loader_mod.CONFIG_KEY_SPECS,
        "_unsupported",
        spec_mod.ConfigKeySpec(tuple),
    )
    with pytest.raises(ConfigValidationError, match="Unsupported config key spec"):
        loader_mod.validate_config_value(key="_unsupported", value=("x",))


def test_normalize_path_config_value_behaviour(tmp_path: Path) -> None:
    assert (
        loader_mod.normalize_path_config_value(
            key="min_loc",
            value=10,
            root_path=tmp_path,
        )
        == 10
    )
    assert (
        loader_mod.normalize_path_config_value(
            key="cache_path",
            value=123,
            root_path=tmp_path,
        )
        == 123
    )
    assert loader_mod.normalize_path_config_value(
        key="cache_path",
        value="relative/cache.json",
        root_path=tmp_path,
    ) == str(tmp_path / "relative/cache.json")
    assert (
        loader_mod.normalize_path_config_value(
            key="cache_path",
            value="/tmp/absolute-cache.json",
            root_path=tmp_path,
        )
        == "/tmp/absolute-cache.json"
    )
    patterns = ("tests/fixtures/golden_*",)
    assert (
        loader_mod.normalize_path_config_value(
            key="golden_fixture_paths",
            value=patterns,
            root_path=tmp_path,
        )
        == patterns
    )


def test_load_pyproject_config_accepts_golden_fixture_paths(tmp_path: Path) -> None:
    _write_pyproject(
        tmp_path / "pyproject.toml",
        """
[tool.codeclone]
golden_fixture_paths = [
  "./tests/fixtures/golden_*",
  "tests/fixtures/golden_*",
]
""".strip(),
    )
    loaded = loader_mod.load_pyproject_config(tmp_path)
    assert loaded["golden_fixture_paths"] == ("tests/fixtures/golden_*",)


def test_load_toml_py310_missing_tomli_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml_path = tmp_path / "pyproject.toml"
    _write_pyproject(toml_path, "[tool]\n")
    monkeypatch.setattr(loader_mod, "sys", SimpleNamespace(version_info=(3, 10, 14)))

    def _raise_module_not_found(_name: str) -> object:
        raise ModuleNotFoundError("tomli")

    monkeypatch.setattr(
        loader_mod,
        "importlib",
        SimpleNamespace(import_module=_raise_module_not_found),
    )
    with pytest.raises(ConfigValidationError, match="requires dependency 'tomli'"):
        loader_mod._load_toml(toml_path)


def test_load_toml_py310_invalid_tomli_module_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml_path = tmp_path / "pyproject.toml"
    _write_pyproject(toml_path, "[tool]\n")
    monkeypatch.setattr(loader_mod, "sys", SimpleNamespace(version_info=(3, 10, 14)))
    monkeypatch.setattr(
        loader_mod,
        "importlib",
        SimpleNamespace(import_module=lambda _name: object()),
    )
    with pytest.raises(ConfigValidationError, match="missing callable 'load'"):
        loader_mod._load_toml(toml_path)


def test_load_toml_py310_uses_tomli_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml_path = tmp_path / "pyproject.toml"
    _write_pyproject(toml_path, "[tool]\n")
    monkeypatch.setattr(loader_mod, "sys", SimpleNamespace(version_info=(3, 10, 14)))

    class _FakeTomli:
        @staticmethod
        def load(file_obj: Any) -> dict[str, object]:
            payload = file_obj.read()
            assert isinstance(payload, bytes)
            return {"tool": {}}

    monkeypatch.setattr(
        loader_mod,
        "importlib",
        SimpleNamespace(import_module=lambda _name: _FakeTomli),
    )
    assert loader_mod._load_toml(toml_path) == {"tool": {}}

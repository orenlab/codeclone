# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Core behaviour that only one interpreter would otherwise ever execute.

Three sites in the analysis core are decided by the running interpreter:

* ``core.entrypoints._load_toml_payload`` and ``config.pyproject_loader``'s
  ``_load_toml`` both read TOML through the stdlib ``tomllib`` on 3.11+ and
  through the ``tomli`` backport below it. Each interpreter runs one body and
  never the other, so the unexercised one is reached by moving the version
  gate -- the idiom this repository already uses for the ``tomli`` side in
  ``test_core_branch_coverage.py`` and ``test_cli_config.py``.
* ``analysis.cfg.CFGBuilder`` models ``try``/``except*`` (``ast.TryStar``,
  3.11+) exactly like ``try``. That node type does not exist below 3.11, so a
  stand-in of the same name is bound as ``ast.TryStar`` behind the moved gate;
  real ``except*`` grammar stays covered by ``test_cfg.py`` on 3.11+.

Every stdlib-branch test also proves it reached that branch: the parser bound
as ``tomllib`` records its calls, and the ``except*`` stand-in only matches
behind the gate, so a gate left unmoved reddens on 3.10 instead of quietly
passing through the other body.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from textwrap import dedent
from types import ModuleType, SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from codeclone.analysis import cfg as cfg_mod
from codeclone.analysis.cfg import CFGBuilder
from codeclone.config import pyproject_loader as loader_mod
from codeclone.core import entrypoints as entrypoints_mod


def _stdlib_toml_parser() -> ModuleType:
    """The 3.11+ stdlib parser, or the identical backport this project already
    depends on below 3.11. Binding it as ``tomllib`` lets the 3.11+ body run a
    real parse on an older interpreter rather than a stubbed one."""

    name = "tomllib" if sys.version_info >= (3, 11) else "tomli"
    return importlib.import_module(name)


@pytest.fixture
def stdlib_toml_branch(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Put both version gates on their 3.11+ side and make ``tomllib``
    importable there, whatever interpreter is running.

    The bound ``tomllib`` wraps the real parser and records each call, so a
    test can tell the 3.11+ body ran rather than the ``tomli`` fallback.
    """

    parser = Mock(wraps=_stdlib_toml_parser())
    monkeypatch.setitem(sys.modules, "tomllib", cast(ModuleType, parser))
    monkeypatch.setattr(entrypoints_mod, "sys", SimpleNamespace(version_info=(3, 11)))
    monkeypatch.setattr(loader_mod, "sys", SimpleNamespace(version_info=(3, 11)))
    return parser


def test_entrypoint_loader_parses_a_project_table_on_the_stdlib_branch(
    tmp_path: Path, stdlib_toml_branch: Mock
) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text('[project.scripts]\ntool = "pkg.cli:main"\n', encoding="utf-8")

    assert entrypoints_mod._load_toml_payload(config) == {
        "project": {"scripts": {"tool": "pkg.cli:main"}}
    }
    stdlib_toml_branch.load.assert_called_once()


def test_entrypoint_loader_rejects_invalid_toml_on_the_stdlib_branch(
    tmp_path: Path, stdlib_toml_branch: Mock
) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text("[project", encoding="utf-8")

    assert entrypoints_mod._load_toml_payload(config) == {}
    stdlib_toml_branch.load.assert_called_once()


def test_entrypoint_loader_rejects_a_non_table_payload_on_the_stdlib_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parser answering with something other than a table is refused rather
    than passed on as project metadata."""

    parser = Mock()
    parser.load.return_value = ["not", "a", "table"]
    monkeypatch.setitem(sys.modules, "tomllib", cast(ModuleType, parser))
    monkeypatch.setattr(entrypoints_mod, "sys", SimpleNamespace(version_info=(3, 11)))
    config = tmp_path / "pyproject.toml"
    config.write_text("[project]\n", encoding="utf-8")

    assert entrypoints_mod._load_toml_payload(config) == {}
    parser.load.assert_called_once()


def test_config_loader_reads_pyproject_on_the_stdlib_branch(
    tmp_path: Path, stdlib_toml_branch: Mock
) -> None:
    """The repo config reader has the same gate as the entrypoint loader, and
    on 3.10 its stdlib body was never executed by any test."""

    config = tmp_path / "pyproject.toml"
    config.write_text("[tool.codeclone]\nmin_loc = 7\n", encoding="utf-8")

    assert loader_mod._load_toml(config) == {"tool": {"codeclone": {"min_loc": 7}}}
    stdlib_toml_branch.load.assert_called_once()


class TryStar(ast.stmt):
    """Stand-in for ``ast.TryStar`` (3.11+), with the fields the builder reads."""

    _fields = ("body", "handlers", "orelse", "finalbody")
    body: list[ast.stmt]
    handlers: list[ast.ExceptHandler]
    orelse: list[ast.stmt]
    finalbody: list[ast.stmt]


def _cfg_shape(func: ast.FunctionDef) -> list[tuple[int, list[int], list[str]]]:
    cfg = CFGBuilder().build(func.name, func)
    return [
        (
            block.id,
            sorted(successor.id for successor in block.successors),
            [ast.dump(statement) for statement in block.statements],
        )
        for block in sorted(cfg.blocks, key=lambda block: block.id)
    ]


def test_cfg_models_try_star_exactly_like_try(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    func = ast.parse(
        dedent(
            """
            def f():
                try:
                    x = 1
                except ValueError:
                    y = 2
                else:
                    z = 3
                finally:
                    w = 4
                return x
            """
        )
    ).body[0]
    assert isinstance(func, ast.FunctionDef)
    plain = _cfg_shape(func)
    statement = func.body[0]
    assert isinstance(statement, ast.Try)
    monkeypatch.setattr(ast, "TryStar", TryStar, raising=False)
    monkeypatch.setattr(cfg_mod, "sys", SimpleNamespace(version_info=(3, 11)))
    starred = TryStar()
    starred.body = statement.body
    starred.handlers = statement.handlers
    starred.orelse = statement.orelse
    starred.finalbody = statement.finalbody
    func.body[0] = starred

    assert _cfg_shape(func) == plain

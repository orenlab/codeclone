# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Hold the pyproject writer to the tomlkit types it actually handles.

``tomlkit`` is a mandatory dependency that ships ``py.typed``, so every value
this module moves is describable.  The module nevertheless reached it through a
lazy loader annotated ``Any`` and bound the results with ``cast``, and declared
``TOMLDocument = object`` outside ``TYPE_CHECKING`` so the surviving runtime
annotations named nothing.  Both ends had to be removed together: a loader that
returns ``Any`` leaves an annotated binding vacuous, which is the same silence a
cast buys, spelled differently.
"""

from __future__ import annotations

import ast
import typing
from collections.abc import Mapping
from pathlib import Path

import tomlkit
import tomlkit.items
import tomlkit.toml_document

from codeclone.config import pyproject_writer

_SUPPRESSION_NAMES = frozenset({"Any", "cast", "import_module"})
_PYPROJECT = """\
[project]
name = "probe"

[tool.codeclone]
min_loc = 6
"""


def _module_source() -> str:
    return Path(str(pyproject_writer.__file__)).read_text(encoding="utf-8")


def _resolved_hints(name: str) -> dict[str, object]:
    """Annotations of one module function as they resolve at runtime."""
    namespace = dict(vars(pyproject_writer))
    namespace.setdefault("Mapping", Mapping)
    return dict(
        typing.get_type_hints(getattr(pyproject_writer, name), globalns=namespace)
    )


def _annotated_functions() -> list[str]:
    """Every function this module defines, read off the module itself."""
    return sorted(
        name
        for name, value in vars(pyproject_writer).items()
        if callable(value)
        and getattr(value, "__module__", None) == pyproject_writer.__name__
        and getattr(value, "__annotations__", None)
    )


def test_the_module_carries_no_type_suppression() -> None:
    """``cast``, ``Any`` and a dynamic import are the same silence, spelled thrice.

    A cast suppresses the binding check on every interpreter; a loader annotated
    ``Any`` suppresses it one step earlier, so removing either alone buys
    nothing; ``importlib.import_module`` suppresses it in mypy specifically,
    which resolves a literal dynamic import to ``ModuleType`` and every member
    off it to ``Any``.
    """
    source = _module_source()
    found = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name | ast.Attribute)
    } & _SUPPRESSION_NAMES
    assert not found, f"type suppression is back in the module: {sorted(found)}"
    assert "type: ignore" not in source, "a type: ignore is back in the module"


def test_the_annotations_resolve_to_the_real_tomlkit_types() -> None:
    """The annotations must resolve to the vendor's classes, not to stand-ins.

    Declaring ``TOMLDocument = object`` outside ``TYPE_CHECKING`` keeps every
    annotation parseable and empties them at the same time, so the identity is
    read off the resolved annotation rather than off an importable name.
    """
    document_return = _resolved_hints("read_pyproject_document")["return"]
    table_return = _resolved_hints("_ensure_tool_codeclone_table")["return"]
    declared_table, _flag = typing.get_args(table_return)

    assert document_return is tomlkit.toml_document.TOMLDocument
    assert declared_table is tomlkit.items.Table


def test_no_function_in_the_module_declares_Any() -> None:
    """``Any`` anywhere in this module is a vendor boundary that stopped talking."""
    offenders: dict[str, dict[str, object]] = {}
    for name in _annotated_functions():
        hints = _resolved_hints(name)
        if any(
            hint is typing.Any or typing.Any in typing.get_args(hint)
            for hint in hints.values()
        ):
            offenders[name] = hints
    assert not offenders, f"functions still declaring Any: {sorted(offenders)}"


def test_the_declared_document_type_describes_the_parsed_document(
    tmp_path: Path,
) -> None:
    """The return annotation must be a real type the produced value satisfies.

    Both halves matter.  ``isinstance`` alone passes against ``object``, which is
    what the erased declaration resolved to; requiring a proper subtype of
    ``object`` is what makes the check say something.
    """
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    declared = _resolved_hints("read_pyproject_document")["return"]
    document = pyproject_writer.read_pyproject_document(tmp_path)

    assert isinstance(declared, type) and declared is not object, (
        f"read_pyproject_document declares {declared!r}, which describes nothing"
    )
    assert isinstance(document, declared)


def test_the_declared_table_type_describes_the_ensured_table(tmp_path: Path) -> None:
    """The same rule on the table edge, which the second cast used to cover."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    declared_return = _resolved_hints("_ensure_tool_codeclone_table")["return"]
    (declared_table, _flag) = typing.get_args(declared_return)
    document = pyproject_writer.read_pyproject_document(tmp_path)
    table, created = pyproject_writer._ensure_tool_codeclone_table(document)

    assert isinstance(declared_table, type) and declared_table is not object, (
        f"_ensure_tool_codeclone_table declares {declared_table!r}"
    )
    assert isinstance(table, declared_table)
    assert created is False

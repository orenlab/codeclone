# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Pin the LanceDB protocols against the LanceDB objects they describe.

A type checker only sees the real ``lancedb.DBConnection`` when lancedb's
``overrides`` dependency resolves, and lancedb requires it exclusively on
``python_full_version < '3.12'``.  On a 3.12+ environment that base class
degrades to an unresolved import, every structural check against the connection
passes vacuously, and one hook returns two different verdicts across the
supported interpreter range.  These pins read the installed signatures at
runtime, which are the same on every supported version, so they hold the
protocols to one shape regardless of which interpreter is checking.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from types import FunctionType, ModuleType

import pytest

from codeclone.memory.semantic.lancedb_backend import (
    LanceDbSemanticIndex,
    _LanceConnection,
)

_POSITIONAL_KINDS = frozenset(
    {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
)
_KEYWORD_REACHABLE_KINDS = frozenset(
    {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }
)


def _declared_methods(protocol: type) -> dict[str, FunctionType]:
    """Callable members the protocol itself declares, properties included."""
    declared: dict[str, FunctionType] = {}
    for name, value in vars(protocol).items():
        if name.startswith("_"):
            continue
        if isinstance(value, FunctionType):
            declared[name] = value
        elif isinstance(value, property) and isinstance(value.fget, FunctionType):
            declared[name] = value.fget
    return declared


def _positional_parameters(signature: inspect.Signature) -> list[inspect.Parameter]:
    """Positional slots after ``self``."""
    return [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in _POSITIONAL_KINDS
    ][1:]


def _keyword_reachable_names(signature: inspect.Signature) -> set[str]:
    return {
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind in _KEYWORD_REACHABLE_KINDS
    }


def _binding_mismatches(
    declared: inspect.Signature, installed: inspect.Signature
) -> list[str]:
    """Ways a call written against ``declared`` fails to bind on ``installed``.

    The rule is re-derived rather than written down as a literal: a positional
    slot binds by position, so the installed method must carry the same name in
    that slot unless the protocol made it positional-only; a keyword-only slot
    binds by name, so the installed method must accept that name.
    """
    problems: list[str] = []
    installed_positional = _positional_parameters(installed)
    installed_keywords = _keyword_reachable_names(installed)
    accepts_var_keyword = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in installed.parameters.values()
    )
    for index, parameter in enumerate(_positional_parameters(declared)):
        # A positional-only slot binds by position, so the installed name is free.
        names_must_agree = parameter.kind is not inspect.Parameter.POSITIONAL_ONLY
        if index >= len(installed_positional):
            problems.append(
                f"positional slot {index} ({parameter.name!r}) "
                "does not exist on the installed method"
            )
        elif names_must_agree and installed_positional[index].name != parameter.name:
            problems.append(
                f"positional slot {index} is {installed_positional[index].name!r} "
                f"on the installed object but {parameter.name!r} in the protocol"
            )
    for parameter in declared.parameters.values():
        binds_by_name = parameter.kind is inspect.Parameter.KEYWORD_ONLY
        accepted = parameter.name in installed_keywords or accepts_var_keyword
        if binds_by_name and not accepted:
            problems.append(
                f"keyword {parameter.name!r} is not accepted by the installed object"
            )
    return problems


def _writable_member_mismatches(protocol: type, installed: type) -> list[str]:
    """Bare annotations claim a writable member; read-only properties are not."""
    problems: list[str] = []
    for name in vars(protocol).get("__annotations__", {}):
        if name.startswith("_"):
            continue
        attribute = inspect.getattr_static(installed, name, None)
        if isinstance(attribute, property) and attribute.fset is None:
            problems.append(
                f"{name!r} is declared as a writable member but "
                f"{installed.__name__}.{name} is a read-only property"
            )
    return problems


def _resolve_return_type(function: FunctionType, owner: type) -> type | None:
    """Resolve a return annotation in the module that declared it."""
    annotation = inspect.signature(function).return_annotation
    if annotation is inspect.Signature.empty:
        return None
    if isinstance(annotation, type):
        return annotation
    if not isinstance(annotation, str):
        return None
    text = annotation.strip().strip("\"'")
    if text.rsplit(".", 1)[-1] == "Self":
        return owner
    resolved: object | None = sys.modules.get(function.__module__)
    for part in text.split("."):
        resolved = getattr(resolved, part, None)
        if resolved is None:
            return None
    return resolved if isinstance(resolved, type) else None


def _walk(
    protocol: type,
    installed: type,
    visited: set[tuple[str, str]],
    problems: dict[str, list[str]],
) -> None:
    """Compare a protocol with its installed counterpart, then follow returns."""
    key = (protocol.__name__, installed.__name__)
    if key in visited:
        return
    visited.add(key)
    writable = _writable_member_mismatches(protocol, installed)
    if writable:
        problems[protocol.__name__] = problems.get(protocol.__name__, []) + writable
    for name, declared in _declared_methods(protocol).items():
        installed_member = inspect.getattr_static(installed, name, None)
        if isinstance(installed_member, property):
            installed_member = installed_member.fget
        if installed_member is None:
            problems.setdefault(protocol.__name__, []).append(
                f"{installed.__name__} has no member {name!r}"
            )
            continue
        try:
            installed_signature = inspect.signature(installed_member)
        except (TypeError, ValueError):
            continue
        found = _binding_mismatches(inspect.signature(declared), installed_signature)
        if found:
            problems.setdefault(protocol.__name__, []).extend(
                f"{name}: {problem}" for problem in found
            )
        declared_return = _resolve_return_type(declared, protocol)
        if declared_return is None or not getattr(
            declared_return, "_is_protocol", False
        ):
            continue
        installed_return = _resolve_return_type(installed_member, installed)
        if installed_return is not None:
            _walk(declared_return, installed_return, visited, problems)


def _installed_connection_type() -> type:
    """The class ``lancedb.connect`` is annotated to return."""
    lancedb = pytest.importorskip("lancedb")
    resolved = _resolve_return_type(lancedb.connect, type(None))
    assert resolved is not None, "lancedb.connect has no resolvable return type"
    return resolved


def test_lance_protocols_bind_on_installed_lancedb() -> None:
    """Every protocol reachable from the connection must bind on the real API."""
    connection_type = _installed_connection_type()
    visited: set[tuple[str, str]] = set()
    problems: dict[str, list[str]] = {}
    _walk(_LanceConnection, connection_type, visited, problems)
    assert len(visited) > 1, f"the walk never left the entry protocol: {visited}"
    assert problems == {}, (
        f"LanceDB protocols do not bind on the installed API: {problems}"
    )


class _StubTable:
    """Just enough table for the create branch of the production path."""


class _RecordingConnection:
    """Connection double that accepts only the keyword calling convention."""

    def __init__(self) -> None:
        self.create_table_keywords: list[frozenset[str]] = []

    def open_table(self, name: str) -> object:
        raise ValueError(f"Table '{name}' was not found")

    def create_table(self, name: str, /, **keywords: object) -> object:
        del name
        self.create_table_keywords.append(frozenset(keywords))
        return _StubTable()

    def drop_table(self, name: str) -> None:
        del name


def _install_recording_lancedb(
    monkeypatch: pytest.MonkeyPatch, connection: _RecordingConnection
) -> None:
    lancedb_module = ModuleType("lancedb")
    lancedb_module.connect = lambda _path: connection  # type: ignore[attr-defined]

    pyarrow_module = ModuleType("pyarrow")
    pyarrow_module.schema = lambda fields: {"fields": fields}  # type: ignore[attr-defined]
    pyarrow_module.field = lambda name, _type: (name, _type)  # type: ignore[attr-defined]
    pyarrow_module.list_ = lambda _item, _size: object()  # type: ignore[attr-defined]
    pyarrow_module.string = lambda: object()  # type: ignore[attr-defined]
    pyarrow_module.int32 = lambda: object()  # type: ignore[attr-defined]
    pyarrow_module.float32 = lambda: object()  # type: ignore[attr-defined]

    original = importlib.import_module

    def _import(name: str, package: str | None = None) -> ModuleType:
        if name == "lancedb":
            return lancedb_module
        if name == "pyarrow":
            return pyarrow_module
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", _import)


def test_protocol_names_every_keyword_the_production_path_sends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The declared member must still name what production actually sends.

    The expected keyword set is observed by running the production create
    branch, not written down here, so a protocol widened into a catch-all stops
    naming those keywords and this pin fails.
    """
    connection = _RecordingConnection()
    _install_recording_lancedb(monkeypatch, connection)

    LanceDbSemanticIndex(path=tmp_path / "index.lance", dimension=4, create=True)

    assert connection.create_table_keywords, (
        "the production create branch never reached create_table"
    )
    declared = _keyword_reachable_names(
        inspect.signature(_LanceConnection.create_table)
    )
    for sent in connection.create_table_keywords:
        assert not sent - declared, (
            f"production sends {sorted(sent - declared)} as keywords, "
            "but _LanceConnection.create_table does not name them"
        )

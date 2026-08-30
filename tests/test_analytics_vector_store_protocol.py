# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Pin the analytics LanceDB protocols against the objects they describe.

A type checker sees the real ``lancedb.DBConnection`` only when lancedb's
``overrides`` dependency resolves, and lancedb requires it exclusively on
``python_full_version < '3.12'``.  On a 3.12+ environment the package is not
installed at all, the declared base class degrades to an unresolved import, and
every structural check against the connection passes vacuously.  This module
carried a second, heavier silencer on top of that one: the connection was bound
through ``cast``, which suppresses the check on *every* interpreter.

These pins read the installed signatures at runtime.  Those are the same on
every supported version, so the verdict does not move with the interpreter that
happens to be checking, and no cast can hide it.

The helpers are imported from the semantic-backend pin rather than copied: one
binding rule, one implementation.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import FunctionType

import pytest

from codeclone.analytics.store import vectors_lancedb
from codeclone.analytics.store.vectors_lancedb import (
    AnalyticsVectorStore,
    _ArrowField,
    _ArrowSchema,
    _ArrowType,
    _LanceConnection,
)
from tests.test_lancedb_connection_protocol import (
    _binding_mismatches,
    _declared_methods,
    _installed_connection_type,
    _keyword_reachable_names,
    _resolve_return_type,
    _writable_member_mismatches,
)

lancedb = pytest.importorskip("lancedb")
pyarrow = pytest.importorskip("pyarrow")

# Any dimension works; both sides of every assertion below derive from this one.
_PROBE_DIMENSION = 4
_SUPPRESSION_NAMES = frozenset({"Any", "cast"})


def _returns_none(function: FunctionType) -> bool:
    annotation = inspect.signature(function).return_annotation
    return str(annotation).strip("\"'") == "None"


def _member_problems(protocol: type, installed: type, name: str) -> list[str]:
    """Every way this one declared member misdescribes the installed object."""
    declared = _declared_methods(protocol)[name]
    member = inspect.getattr_static(installed, name, None)
    if isinstance(member, property):
        member = member.fget
    if member is None:
        return [f"{installed.__name__} has no member {name!r}"]
    problems = [
        problem
        for problem in _writable_member_mismatches(protocol, installed)
        if problem.startswith(f"{name!r}")
    ]
    try:
        installed_signature = inspect.signature(member)
    except (TypeError, ValueError):
        # A compiled descriptor carries no signature, so presence is all that
        # can be read here.  It was read above.
        return problems
    problems += _binding_mismatches(inspect.signature(declared), installed_signature)
    if _returns_none(declared) and not _returns_none(member):
        problems.append(
            f"declares return None, but {installed.__name__}.{name} returns "
            f"{str(inspect.signature(member).return_annotation)!r}"
        )
    return problems


def _collect(protocol: type, installed: type, pairs: list[tuple[type, type]]) -> None:
    """Pair a protocol with its installed counterpart, then follow returns."""
    if (protocol, installed) in pairs:
        return
    pairs.append((protocol, installed))
    for name, declared in _declared_methods(protocol).items():
        declared_return = _resolve_return_type(declared, protocol)
        member = inspect.getattr_static(installed, name, None)
        if isinstance(member, property):
            member = member.fget
        # Only a protocol return reached through an introspectable member
        # continues the chain; anything else ends it here.
        if (
            declared_return is None
            or not getattr(declared_return, "_is_protocol", False)
            or not isinstance(member, FunctionType)
        ):
            continue
        installed_return = _resolve_return_type(member, installed)
        if installed_return is not None:
            _collect(declared_return, installed_return, pairs)


def _protocol_pairs() -> list[tuple[type, type]]:
    """Every protocol this module declares, paired with what it describes."""
    pairs: list[tuple[type, type]] = []
    _collect(_LanceConnection, _installed_connection_type(), pairs)
    # PyArrow ships compiled members, so no return annotation leads out of
    # ``Schema.field``.  Seed that chain from the objects the production schema
    # builder actually produces.
    schema = vectors_lancedb._schema(pyarrow, _PROBE_DIMENSION)
    field = schema.field("vector")
    _collect(_ArrowSchema, type(schema), pairs)
    _collect(_ArrowField, type(field), pairs)
    _collect(_ArrowType, type(field.type), pairs)
    return pairs


_MEMBER_CASES = [
    (protocol, installed, name)
    for protocol, installed in _protocol_pairs()
    for name in sorted(_declared_methods(protocol))
]


@pytest.mark.parametrize(
    ("protocol", "installed", "member"),
    _MEMBER_CASES,
    ids=[f"{protocol.__name__}.{name}" for protocol, _, name in _MEMBER_CASES],
)
def test_declared_member_binds_on_the_installed_object(
    protocol: type, installed: type, member: str
) -> None:
    """One case per declared member, so a break names the member it broke."""
    problems = _member_problems(protocol, installed, member)
    assert problems == [], (
        f"{protocol.__name__}.{member} does not describe "
        f"{installed.__name__}.{member}: {problems}"
    )


def test_the_pairing_reaches_every_protocol_the_module_declares() -> None:
    """A pairing that stopped early would pin nothing past the entry protocol.

    The expected set is read off the module, not written down, so a protocol
    added later is unpinned loudly instead of silently.
    """
    declared = {
        name
        for name, value in vars(vectors_lancedb).items()
        if isinstance(value, type)
        and getattr(value, "_is_protocol", False)
        and value.__module__ == vectors_lancedb.__name__
    }
    reached = {protocol.__name__ for protocol, _ in _protocol_pairs()}
    assert declared == reached, f"protocols never paired: {sorted(declared - reached)}"


def test_the_binding_rule_rejects_a_shape_that_only_carries_the_names() -> None:
    """Name presence is all the silenced check saw; this rule reads signatures.

    Proves an input exists that reaches the rule and trips it — a rule nothing
    can fail is theatre.
    """

    class _NamesOnlyConnection:
        def open_table(self, table: str) -> None: ...

        def create_table(self, table: str, layout: object) -> None: ...

    problems = {
        name: _member_problems(_LanceConnection, _NamesOnlyConnection, name)
        for name in sorted(_declared_methods(_LanceConnection))
    }
    assert all(problems.values()), f"a wrong shape went unnoticed: {problems}"


def test_the_pin_holds_when_the_vendor_base_class_does_not_resolve() -> None:
    """The verdict must not move in the mode that silenced the original check.

    lancedb declares ``EnforceOverrides`` as the base of its connection and
    pulls the package that defines it only below 3.12, so above that the base a
    checker sees is an unresolved name.  Re-running the same rule against a
    class stripped of that base must produce the identical verdict.
    """
    connection_type = _installed_connection_type()
    namespace = {
        key: value
        for key, value in vars(connection_type).items()
        if key not in {"__dict__", "__weakref__"}
    }
    stripped = type("_ConnectionWithoutVendorBase", (object,), namespace)
    for name in sorted(_declared_methods(_LanceConnection)):
        assert _member_problems(_LanceConnection, stripped, name) == _member_problems(
            _LanceConnection, connection_type, name
        ), f"{name} changed verdict once the vendor base class was removed"


def test_the_arrow_chain_describes_the_access_the_store_performs() -> None:
    """The declared arrow chain must reach the value the store compares."""
    schema = vectors_lancedb._schema(pyarrow, _PROBE_DIMENSION)
    assert schema.field("vector").type.list_size == _PROBE_DIMENSION


def test_the_module_carries_no_type_suppression() -> None:
    """`cast` here is suppression by another name: it hid this exact defect.

    A cast silences the connection check on every interpreter, not only the one
    where the vendor base class fails to resolve.
    """
    source = Path(str(vectors_lancedb.__file__)).read_text(encoding="utf-8")
    found = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name | ast.Attribute)
    } & _SUPPRESSION_NAMES
    assert not found, f"type suppression is back in the module: {sorted(found)}"
    assert "type: ignore" not in source, "a type: ignore is back in the module"


def _connection_return_type() -> type | None:
    connect = vectors_lancedb._connect
    assert isinstance(connect, FunctionType), (
        "the connection edge must be a plain function this pin can introspect"
    )
    return _resolve_return_type(connect, type(None))


def test_the_connection_enters_the_module_through_the_protocol() -> None:
    """The declared return type is the edge a checker can actually verify.

    A helper annotated ``ModuleType`` erases the module identity, the connect
    call degrades to an unknown, and the binding is unchecked again — the same
    silence the cast bought, spelled differently.
    """
    assert _connection_return_type() is _LanceConnection


class _StubTable:
    """Just enough table for the create branch of the production path."""

    def __init__(self) -> None:
        self.schema = _StubSchema()


class _StubSchema:
    def field(self, _name: str) -> object:
        return _StubField()


class _StubField:
    list_size = _PROBE_DIMENSION

    @property
    def type(self) -> _StubField:
        return self


class _RecordingConnection:
    """Connection double that records how the store calls ``create_table``."""

    def __init__(self) -> None:
        self.create_table_keywords: list[frozenset[str]] = []

    def open_table(self, name: str) -> object:
        raise ValueError(f"Table '{name}' was not found")

    def create_table(self, name: str, /, **keywords: object) -> object:
        del name
        self.create_table_keywords.append(frozenset(keywords))
        return _StubTable()


def test_the_store_takes_its_connection_from_the_declared_edge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The checked edge must be the one production runs through.

    The expected keyword set is observed by running the create branch, not
    written down here, so a protocol widened into a catch-all stops naming
    those keywords and this pin fails.
    """
    connection = _RecordingConnection()
    monkeypatch.setattr(vectors_lancedb, "_connect", lambda _path: connection)

    store = AnalyticsVectorStore(path=tmp_path / "vectors", dimension=_PROBE_DIMENSION)

    used: object = store._conn
    assert used is connection
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

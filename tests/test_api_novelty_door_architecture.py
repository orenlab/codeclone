# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Structural AST pin: the ``api/novelty.py`` door delegates, never owns.

The door re-exports the clone novelty vocabulary by assignment
(``NAME = _findings.NAME``) and derives its value tuple from the owner.
Editing the door into a literal (``CLONE_NOVELTY_NEW = "new"``) produces
byte-identical runtime values today, so no runtime pin can go red -- and the
vocabulary silently freezes the next time the owner grows (`G2`, `H1`).

These tests therefore read the door's *source* -- ``ast`` over the file,
never an import of either ring -- and pin the shape of source authority
delegation:

* every ``__all__`` symbol except the derived values tuple is assigned as
  ``<NAME> = _findings.<NAME>``: attribute access on the owner module, the
  same name on both sides;
* the values tuple is derived mechanically over ``vars(_findings)``, never
  spelled as a literal container;
* no other string constant exists in the door at all, so the file cannot
  spell a vocabulary value: the only strings allowed are docstrings, the
  ``__all__`` name list, and the ``startswith`` scan prefix (a name prefix,
  not a value).

The checked symbol list is derived from the door's own ``__all__`` in the
same AST pass, so a fourth name added to the door lands under the form check
automatically (`H1`). Runtime behavior of the exports stays pinned by the
wave 22/32 consumers (``tests/test_cli_unit.py``,
``tests/test_audit_analysis_completed.py``); this module proves the
complementary fact that the door is not the owner of any value.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

_DOOR_PATH = Path(__file__).resolve().parents[1] / "codeclone" / "api" / "novelty.py"

#: The one ``__all__`` symbol the ruling allows to be derived instead of
#: delegated: the tuple of every vocabulary value, computed from the owner.
_DERIVED_TUPLE_SYMBOL = "CLONE_NOVELTY_VALUES"

#: The vocabulary owner the door must delegate to, as spelled in its import
#: (``from ..domain import findings as _findings``).
_OWNER_PACKAGE = "domain"
_OWNER_MODULE = "findings"


def _door_tree() -> ast.Module:
    """Parse the door's source; imports would measure runtime, not authority."""
    return ast.parse(_DOOR_PATH.read_text("utf-8"))


def _owner_alias(tree: ast.Module) -> str:
    """The local name the door binds the owner module to.

    Derived from the door's own import so the delegation check survives an
    alias rename; requiring exactly one owner import keeps a second
    vocabulary source from appearing silently.
    """
    aliases = [
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        if (node.module or "").split(".")[-1] == _OWNER_PACKAGE
        for alias in node.names
        if alias.name == _OWNER_MODULE
    ]
    assert aliases != [], (
        f"the door must import the vocabulary owner via 'from ..{_OWNER_PACKAGE} "
        f"import {_OWNER_MODULE}'; no such import found in {_DOOR_PATH.name}"
    )
    assert len(aliases) == 1, (
        f"the door binds the vocabulary owner more than once: {aliases}"
    )
    return aliases[0]


def _dunder_all_value(node: ast.AST) -> ast.expr | None:
    """The expression assigned to ``__all__`` when ``node`` assigns it."""
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "__all__"
    ):
        return node.value
    return None


def _docstring_constant(node: ast.AST) -> ast.Constant | None:
    """The string constant of a standalone expression: a doc, not a value."""
    if (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        return node.value
    return None


def _startswith_arguments(node: ast.AST) -> list[ast.expr]:
    """Arguments of a ``.startswith`` call: name prefixes, never values."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "startswith"
    ):
        return list(node.args)
    return []


def _exported_names(tree: ast.Module) -> list[str]:
    """The door's ``__all__`` entries, in declaration order.

    A missing or empty ``__all__`` fails loudly: every form check below
    iterates this list, and a pin over an empty scan is no pin (`H2`).
    """
    for node in tree.body:
        container = _dunder_all_value(node)
        if container is None:
            continue
        assert isinstance(container, ast.List | ast.Tuple), (
            "__all__ must be a literal list or tuple of names, found "
            f"{type(container).__name__}"
        )
        names: list[str] = []
        for element in container.elts:
            assert isinstance(element, ast.Constant) and isinstance(
                element.value, str
            ), f"__all__ holds a non-string entry: {ast.dump(element)}"
            names.append(element.value)
        assert names != [], "__all__ is empty; the door exports nothing to pin"
        return names
    raise AssertionError(f"{_DOOR_PATH.name} declares no __all__")


def _module_assignments(tree: ast.Module) -> dict[str, ast.expr]:
    """Top-level ``name = value`` bindings, annotated or plain."""
    bindings: dict[str, ast.expr] = {}
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and value is not None:
            bindings[target.id] = value
    return bindings


class _DoorFacts(NamedTuple):
    """One parse of the door, shared by the form checks below."""

    tree: ast.Module
    owner: str
    exported: list[str]
    bindings: dict[str, ast.expr]


def _door_facts() -> _DoorFacts:
    """Parse the door once and derive owner alias, ``__all__``, and bindings."""
    tree = _door_tree()
    return _DoorFacts(
        tree=tree,
        owner=_owner_alias(tree),
        exported=_exported_names(tree),
        bindings=_module_assignments(tree),
    )


def test_every_exported_symbol_is_delegated_to_the_owner() -> None:
    """Each ``__all__`` name, bar the derived tuple, reads ``NAME = _findings.NAME``.

    The offender report carries the observed source form because runtime
    bytes cannot distinguish it: ``CLONE_NOVELTY_NEW = "new"`` is the exact
    mutation this pin exists to catch. The checked set comes from ``__all__``
    in this same pass, so a new exported name is under the form check the
    moment it is exported.
    """
    facts = _door_facts()

    delegated = [name for name in facts.exported if name != _DERIVED_TUPLE_SYMBOL]
    assert delegated != [], "the door exports no delegated symbols; nothing to pin"

    offenders: list[str] = []
    for name in delegated:
        value = facts.bindings.get(name)
        if value is None:
            offenders.append(f"{name}: no top-level assignment in the door")
            continue
        is_delegation = (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == facts.owner
            and value.attr == name
        )
        if not is_delegation:
            offenders.append(f"{name} = {ast.unparse(value)}")

    assert offenders == [], (
        f"these door symbols are not delegated as '<NAME> = {facts.owner}.<NAME>' "
        f"(the door may not own a vocabulary value): {offenders}"
    )


def test_the_values_tuple_is_derived_from_the_owner_not_spelled() -> None:
    """``CLONE_NOVELTY_VALUES`` is computed over ``vars(_findings)``.

    A literal tuple holding today's correct values is exactly the frozen-door
    defect: it stays green until the owner grows a word, then silently keeps
    every consumer of the door on the old vocabulary.
    """
    facts = _door_facts()
    assert _DERIVED_TUPLE_SYMBOL in facts.exported, (
        f"{_DERIVED_TUPLE_SYMBOL} left the door's __all__; the derived-tuple "
        "pin has no subject"
    )

    value = facts.bindings.get(_DERIVED_TUPLE_SYMBOL)
    assert value is not None, (
        f"{_DERIVED_TUPLE_SYMBOL} has no top-level assignment in the door"
    )

    assert not isinstance(value, ast.Tuple | ast.List | ast.Set | ast.Constant), (
        f"{_DERIVED_TUPLE_SYMBOL} is spelled as a literal "
        f"({ast.unparse(value)}); it must be derived from the owner"
    )

    scans_owner = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "vars"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == facts.owner
        for node in ast.walk(value)
    )
    assert scans_owner, (
        f"{_DERIVED_TUPLE_SYMBOL} = {ast.unparse(value)} never scans "
        f"vars({facts.owner}); the tuple must be derived mechanically from the owner"
    )


def test_no_string_in_the_door_can_spell_a_vocabulary_value() -> None:
    """No string constant outside docstrings, ``__all__``, and the scan prefix.

    Whichever words the owner declares, a value literal in this file would be
    a second owner (`G2`). The rule is structural -- a closed list of allowed
    string positions -- so this test never has to import the owner to learn
    today's words, and a new word arriving tomorrow is already covered.
    """
    tree = _door_tree()

    allowed: set[int] = set()
    for node in ast.walk(tree):
        docstring = _docstring_constant(node)
        if docstring is not None:
            allowed.add(id(docstring))
        dunder_all = _dunder_all_value(node)
        if isinstance(dunder_all, ast.List | ast.Tuple):
            allowed.update(id(element) for element in dunder_all.elts)
        allowed.update(id(argument) for argument in _startswith_arguments(node))

    offenders = sorted(
        (
            (node.lineno, node.col_offset, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in allowed
        ),
    )
    assert offenders == [], (
        "the door spells string constants outside its allowed positions "
        "(docstrings, __all__ names, the startswith scan prefix); each one "
        f"could be a vocabulary value with a second owner: {offenders}"
    )

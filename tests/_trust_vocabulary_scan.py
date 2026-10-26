# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Find where a module spells the trust vocabulary AS a vocabulary.

A word search cannot tell a status set from a sentence that happens to use
the word, so this reads the syntax tree and counts only semantic uses of the
owned words (``codeclone.contracts.trust_vocabulary``):

* a set, tuple or list literal holding two or more of them -- a vocabulary
  fragment, however it is later used;
* a ``Literal[...]`` holding two or more of them;
* a class body assigning two or more of them -- an enum of statuses;
* a comparison between one of them and a trust field: a lane's ``reason``
  or a ``baseline_status`` (``x.reason``, ``row["reason"]``,
  ``row.get("reason")`` or a variable of that name);
* a module-level constant naming one of them (``X: Final = "compatible"``):
  a private copy of a word the owner already names.

A message, a log line or a single value handed to a constructor is none of
these, and is not counted.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

TRUST_FIELDS = frozenset({"reason", "baseline_status"})


def _owned(node: ast.expr, words: frozenset[str]) -> bool:
    return isinstance(node, ast.Constant) and node.value in words


def _owned_count(nodes: Iterable[ast.expr], words: frozenset[str]) -> int:
    return sum(1 for node in nodes if _owned(node, words))


def _reads_trust_field(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in TRUST_FIELDS
    if isinstance(node, ast.Attribute):
        return node.attr in TRUST_FIELDS
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value in TRUST_FIELDS
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
    ):
        key = node.args[0]
        return isinstance(key, ast.Constant) and key.value in TRUST_FIELDS
    return False


def _is_literal_subscript(node: ast.Subscript) -> bool:
    value = node.value
    name = value.attr if isinstance(value, ast.Attribute) else getattr(value, "id", "")
    return name == "Literal"


def _assigned(statement: ast.stmt) -> ast.expr | None:
    if isinstance(statement, (ast.Assign, ast.AnnAssign)):
        return statement.value
    return None


def _literal_uses(
    tree: ast.Module, words: frozenset[str]
) -> tuple[list[tuple[int, str]], set[int]]:
    """``Literal[...]`` vocabularies, and the slices they own: the tuple
    inside a ``Literal`` is that Literal, not a second collection."""

    uses: list[tuple[int, str]] = []
    slices: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_literal_subscript(node):
            slice_ = node.slice
            elements = slice_.elts if isinstance(slice_, ast.Tuple) else [slice_]
            slices.add(id(slice_))
            if _owned_count(elements, words) >= 2:
                uses.append((node.lineno, "literal"))
    return uses, slices


def _kind_of(
    node: ast.AST, words: frozenset[str], literal_slices: set[int]
) -> str | None:
    """The kind of semantic use ``node`` is, if it is one."""

    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        counted = id(node) not in literal_slices
        return "collection" if counted and _owned_count(node.elts, words) >= 2 else None
    if isinstance(node, ast.ClassDef):
        values = [value for value in map(_assigned, node.body) if value is not None]
        return "class" if _owned_count(values, words) >= 2 else None
    if isinstance(node, ast.Compare):
        operands = [node.left, *node.comparators]
        compares_a_word = any(_owned(operand, words) for operand in operands)
        reads_a_field = any(_reads_trust_field(operand) for operand in operands)
        return "comparison" if compares_a_word and reads_a_field else None
    return None


def semantic_uses(source: str, words: frozenset[str]) -> list[tuple[int, str]]:
    """``(line, kind)`` of every semantic use of ``words`` in ``source``."""

    tree = ast.parse(source)
    uses = [
        (statement.lineno, "constant")
        for statement in tree.body
        if (value := _assigned(statement)) is not None and _owned(value, words)
    ]
    literal_uses, literal_slices = _literal_uses(tree, words)
    uses.extend(literal_uses)
    for node in ast.walk(tree):
        kind = _kind_of(node, words, literal_slices)
        if kind is not None and isinstance(node, (ast.expr, ast.stmt)):
            uses.append((node.lineno, kind))
    return sorted(uses)

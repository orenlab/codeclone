# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every closed vocabulary the cache reader admits is the model's, not a copy.

The defect these pin (ruling 2026-10-13, invariant 1): the runtime-reachability
framework vocabulary had three hand-written spellings -- the model's
``Literal``, the wire decoder's set and the rehydration narrower's ``match``
ladder -- and the third was one member short. Two lists and an equality test
would only move the problem; the reader now derives each narrower from the
alias that declares it, and these two ratchets keep it that way:

* closure -- every narrower in the cache read path (a one-argument function of
  ``object`` returning a ``Literal`` or a ``TypeGuard`` of one) accepts exactly
  the members of its own declared alias and nothing else;
* no restatement -- no ``match`` ladder, membership test or literal collection
  in those modules spells two or more members of a model vocabulary by hand.
  A rule that legitimately names a SUBSET is declared below, and its members
  are held to its vocabulary.

Both detectors are shown to fire before their silence is read.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal, TypeGuard, Union, get_args, get_origin, get_type_hints

import pytest

import codeclone.contracts as contracts
import codeclone.models as models
from codeclone.utils.closed_vocabulary import narrow_to_vocabulary

#: The cache read path: bytes to wire rows, wire rows to model facts.
_READ_PATH_MODULES = (
    "codeclone.cache._validators",
    "codeclone.cache._wire_decode",
    "codeclone.cache._wire_helpers",
    "codeclone.cache.entries",
    "codeclone.core.discovery",
    "codeclone.core.discovery_cache",
)

#: Rules that spell members of a vocabulary on purpose -- a decision about
#: some members, not a decoder of all of them. Each entry is (module, name of
#: the binding or enclosing function) -> the alias whose members the spelling
#: must stay inside. A decoder never belongs here: it derives from its alias.
_DECLARED_RULES: dict[tuple[str, str], object] = {
    # The two resolutions under which a dependency legitimately has no target.
    ("codeclone.core.discovery_cache", "_module_dep_target_is_valid"): (
        models.DependencyResolution
    ),
    # The two lane-profile domains, of every digest domain the model declares.
    ("codeclone.cache._wire_decode", "_decode_profile_digest"): models.DigestDomain,
    # Each status's target rule; the status itself was already narrowed by
    # ``_as_relationship_resolution_status``.
    ("codeclone.cache._wire_decode", "_decode_wire_relationship_record"): (
        models.RelationshipResolutionStatus
    ),
}

_UNKNOWN = "\x00not-a-member"


def _vocabularies() -> dict[str, frozenset[str]]:
    """Every closed string vocabulary the model and the contracts declare."""

    found: dict[str, frozenset[str]] = {}
    for owner in (models, contracts):
        for name, value in sorted(vars(owner).items()):
            if get_origin(value) is not Literal:
                continue
            members = get_args(value)
            if len(members) > 1 and all(isinstance(m, str) for m in members):
                found[f"{owner.__name__}.{name}"] = frozenset(members)
    return found


def _literal_of(annotation: object) -> object | None:
    """The ``Literal`` a narrower's return annotation names, or ``None``."""

    origin = get_origin(annotation)
    members: list[object] = []
    if origin is TypeGuard:
        members = list(get_args(annotation))
    elif origin in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
    if len(members) == 1 and get_origin(members[0]) is Literal:
        return members[0]
    return None


def _narrowers() -> Iterator[tuple[str, Callable[[object], object], object]]:
    for module_name in _READ_PATH_MODULES:
        module = importlib.import_module(module_name)
        for name, function in sorted(vars(module).items()):
            if not inspect.isfunction(function):
                continue
            if function.__module__ != module_name:
                continue
            parameters = list(inspect.signature(function).parameters.values())
            # Read the spelled annotation first: resolving every function's
            # hints would trip on names a module imports for type checking
            # only, and a narrower is a one-argument function of ``object``.
            if len(parameters) != 1 or parameters[0].annotation not in (
                "object",
                object,
            ):
                continue
            # The model is the namespace of last resort for a name a module
            # imports only while type checking; anything still unresolved is
            # an error here, never a narrower quietly left out.
            hints = get_type_hints(function, localns=vars(models))
            literal = _literal_of(hints.get("return"))
            if literal is not None:
                yield f"{module_name}.{name}", function, literal


def test_every_cache_narrower_accepts_exactly_its_declared_vocabulary() -> None:
    narrowers = list(_narrowers())
    # The population has to contain the defect's own two narrowers, or the
    # closure below was read over a set that could not have shown it.
    unseen = {
        "codeclone.cache.entries._as_runtime_reachability_framework",
        "codeclone.core.discovery_cache._runtime_reachability_framework",
    } - {name for name, _function, _literal in narrowers}

    divergent: list[str] = []
    for name, narrower, literal in narrowers:
        members = get_args(literal)
        accepted = {m for m in members if narrower(m) in (m, True)}
        rejected_unknown = narrower(_UNKNOWN) in (None, False)
        rejected_non_text = narrower(None) in (None, False)
        if accepted != set(members) or not rejected_unknown or not rejected_non_text:
            divergent.append(
                f"{name}: missing {sorted(set(members) - accepted)}, "
                f"unknown refused={rejected_unknown}, "
                f"non-text refused={rejected_non_text}"
            )
    assert (sorted(unseen), divergent) == ([], [])


def _string_members(node: ast.AST) -> frozenset[str] | None:
    """The members of a literal string collection, or ``None`` if it is not one."""

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in {"frozenset", "set", "tuple"} and len(node.args) == 1:
            return _string_members(node.args[0])
        return None
    if not isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        return None
    values = [
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]
    if len(values) != len(node.elts):
        return None
    return frozenset(values)


def _equality_ladder(function: ast.AST) -> frozenset[str]:
    """Every string a function compares a value to with ``==`` or ``!=``.

    An ``if value == "a": ... if value == "b":`` ladder spells a vocabulary
    without ever building a collection, which is how a scan shaped like a set
    missed one owner of the live-root vocabulary before (test_architecture).
    """

    return frozenset(
        comparator.value
        for node in ast.walk(function)
        if isinstance(node, ast.Compare)
        and all(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
        for comparator in (node.left, *node.comparators)
        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str)
    )


def _match_spelling(node: ast.Match) -> frozenset[str]:
    """The string patterns of every case of one ``match``."""

    return frozenset(
        pattern.value.value
        for case in node.cases
        for pattern in ast.walk(case.pattern)
        if isinstance(pattern, ast.MatchValue)
        and isinstance(pattern.value, ast.Constant)
        and isinstance(pattern.value.value, str)
    )


def _membership_spellings(node: ast.Compare) -> Iterator[frozenset[str]]:
    """The literal right-hand side of every ``in`` / ``not in`` of a test."""

    for operator, comparator in zip(node.ops, node.comparators, strict=True):
        members = _string_members(comparator)
        if isinstance(operator, (ast.In, ast.NotIn)) and members:
            yield members


def _assignment_target(node: ast.Assign | ast.AnnAssign) -> str | None:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return next((t.id for t in targets if isinstance(t, ast.Name)), None)


def _function_owners(tree: ast.AST) -> dict[int, str]:
    """Each node's innermost-first enclosing function name, by node id."""

    owners: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                owners.setdefault(id(child), node.name)
    return owners


def _restatements(source: str) -> Iterator[tuple[int, str, frozenset[str]]]:
    """(line, owning name, spelled members) for every hand-written string set.

    A ``match`` contributes the string patterns of all its cases, a membership
    test its literal right-hand side, an assignment its literal value and a
    function the strings of its equality ladder. The owning name is the
    assignment target or the enclosing function, which is what a declared
    rule is keyed by.
    """

    tree = ast.parse(source)
    owners = _function_owners(tree)
    for node in ast.walk(tree):
        owner = owners.get(id(node), "<module>")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.lineno, node.name, _equality_ladder(node)
        elif isinstance(node, ast.Match):
            yield node.lineno, owner, _match_spelling(node)
        elif isinstance(node, ast.Compare):
            for spelled in _membership_spellings(node):
                yield node.lineno, owner, spelled
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            name = _assignment_target(node) or owner
            assigned = _string_members(node.value)
            if assigned and name != "__all__":
                yield node.lineno, name, assigned


def _vocabulary_copies(
    module_name: str, source: str, vocabularies: dict[str, frozenset[str]]
) -> list[str]:
    copies: list[str] = []
    for line, owner, spelled in _restatements(source):
        if len(spelled) < 2:
            continue
        restated = sorted(
            name for name, members in vocabularies.items() if spelled <= members
        )
        if not restated:
            continue
        declared = _DECLARED_RULES.get((module_name, owner))
        if declared is not None and spelled <= frozenset(get_args(declared)):
            continue
        copies.append(f"{module_name}:{line} ({owner}) restates {restated}")
    return copies


def test_the_restatement_detector_sees_a_hand_written_vocabulary() -> None:
    """Positive control: each construct the scan claims to catch is caught."""

    vocabularies = _vocabularies()
    assert "codeclone.models.RuntimeReachabilityFramework" in vocabularies
    ladder = (
        "def narrow(value):\n"
        "    match value:\n"
        '        case "fastapi":\n'
        '            return "fastapi"\n'
        '        case "flask":\n'
        '            return "flask"\n'
    )
    membership = 'def narrow(value):\n    return value in {"click", "typer"}\n'
    assignment = '_FRAMEWORKS = ("celery", "django")\n'
    equality = (
        "def narrow(value):\n"
        '    if value == "aiogram":\n'
        '        return "aiogram"\n'
        '    return "aiohttp" if value == "aiohttp" else None\n'
    )
    for source in (ladder, membership, assignment, equality):
        assert _vocabulary_copies("probe", source, vocabularies), source


@pytest.mark.parametrize("module_name", _READ_PATH_MODULES)
def test_the_cache_read_path_restates_no_model_vocabulary(module_name: str) -> None:
    module = importlib.import_module(module_name)
    source_file = inspect.getsourcefile(module)
    assert source_file is not None
    source = Path(source_file).read_text("utf-8")
    assert _vocabulary_copies(module_name, source, _vocabularies()) == []


def test_every_declared_rule_is_still_spelled_inside_its_vocabulary() -> None:
    """A declared exemption that matches nothing is a stale exemption."""

    vocabularies = _vocabularies()
    for (module_name, owner), alias in _DECLARED_RULES.items():
        module = importlib.import_module(module_name)
        source_file = inspect.getsourcefile(module)
        assert source_file is not None
        spelled = [
            members
            for _line, name, members in _restatements(
                Path(source_file).read_text("utf-8")
            )
            if name == owner and len(members) > 1
        ]
        assert spelled, (module_name, owner)
        assert all(members <= frozenset(get_args(alias)) for members in spelled)
        assert frozenset(get_args(alias)) in vocabularies.values()


class _EqualToEverything:
    """A value that claims to equal any string: not text, so not a member."""

    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = object.__hash__


class _TaggedText(str):
    """Text that equals a member without being the member object."""


def test_only_text_narrows_and_the_member_itself_comes_back() -> None:
    """The narrower answers with the vocabulary's own member, from text only.

    The member, not the input: a ``str`` subclass equal to a member narrows to
    the plain member, so nothing downstream ever carries a caller's object
    where a vocabulary value was promised.
    """

    vocabulary = ("alpha", "beta")
    narrowed = narrow_to_vocabulary(_TaggedText("beta"), vocabulary)
    assert narrowed == "beta"
    assert type(narrowed) is str
    assert narrow_to_vocabulary(_EqualToEverything(), vocabulary) is None
    assert narrow_to_vocabulary("gamma", vocabulary) is None


@pytest.mark.parametrize(
    "spelling", ["Pydantic", "PYDANTIC", " pydantic", "pydantic ", "pydantic\n"]
)
def test_only_the_exact_spelling_of_a_member_narrows(spelling: str) -> None:
    """A member's case and edges are part of the value; nothing is normalised.

    The wire stores the member exactly as the producer spelled it, so a
    reader that folded case or trimmed whitespace would admit a row no
    producer wrote and serve it as a fact.
    """

    frameworks = get_args(models.RuntimeReachabilityFramework)
    assert narrow_to_vocabulary("pydantic", frameworks) == "pydantic"
    assert narrow_to_vocabulary(spelling, frameworks) is None

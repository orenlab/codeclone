# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Structural pin: the fact root composes, it never owns (ruling, variant v).

``CanonicalFacts`` is the composition root over the three ratified tier
houses (§4 grammar): ``analysis`` / ``comparison`` / ``evaluation``.  The
maintainer form is hard: the root carries NO formulas, NO routing policy,
NO derived values, and NO proxy methods outward — a root forwarder would
rebuild the undifferentiated family bag one level up, in a place no
coupling measure watches.

A smuggled ``@property contracts`` would be byte-identical at runtime to
reading ``facts.analysis.contracts``, so no runtime pin can go red on it.
These pins therefore read the class's SOURCE — ``ast`` over ``model.py``,
per the ``test_api_novelty_door_architecture`` precedent — and pin the
shape of composition:

* the root class body is a docstring plus exactly three annotated fields,
  ``analysis`` / ``comparison`` / ``evaluation``, and nothing else — no
  ``def``, no decorator, no assignment beyond those three;
* every registry wire family lives in ``AnalysisFacts`` (``file_modules``
  deliberately excepted: the FILE-MODULE relation rides the model, a table
  and never a column, §2.3);
* the comparison and evaluation houses are BORN EMPTY — the current,
  legitimate state under the ratified grammar.  When their first family
  lands (with its own wire-revision bump), this pin is updated as part of
  that declared transition, never silently.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from codeclone.canonical import (
    AnalysisFacts,
    CanonicalFacts,
    ComparisonFacts,
    EvaluationFacts,
)
from codeclone.canonical.registry import wire_fact_family_order

_MODEL_PATH = (
    Path(__file__).resolve().parents[1] / "codeclone" / "canonical" / "model.py"
)

#: The one registry family that is deliberately NOT an AnalysisFacts field:
#: the FILE-MODULE relation is model-level identity state (a table, never a
#: column) and reaches the wire through the projection plan.
_PLAN_CARRIED_FAMILIES = frozenset({"file_modules"})

_HOUSE_FIELDS = ("analysis", "comparison", "evaluation")


def _class_def(name: str) -> ast.ClassDef:
    tree = ast.parse(_MODEL_PATH.read_text("utf-8"))
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    assert len(matches) == 1, f"expected exactly one class {name!r} in model.py"
    return matches[0]


def test_root_source_is_a_docstring_plus_three_house_fields_only() -> None:
    """The AST form of "the root owns nothing but composition"."""
    root = _class_def("CanonicalFacts")
    assert root.decorator_list, "the root must stay a dataclass"
    body = list(root.body)
    docstring = body[0]
    assert isinstance(docstring, ast.Expr) and isinstance(
        docstring.value, ast.Constant
    ), "the root must open with its docstring"
    members = body[1:]
    assert all(isinstance(node, ast.AnnAssign) for node in members), (
        "the root body may contain nothing but the three annotated house "
        f"fields; found {[type(node).__name__ for node in members]}"
    )
    names = [
        node.target.id
        for node in members
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    ]
    assert names == list(_HOUSE_FIELDS), names


def test_root_runtime_fields_are_exactly_the_three_houses() -> None:
    fields = [field.name for field in dataclasses.fields(CanonicalFacts)]
    assert fields == list(_HOUSE_FIELDS)
    empty = CanonicalFacts()
    assert isinstance(empty.analysis, AnalysisFacts)
    assert isinstance(empty.comparison, ComparisonFacts)
    assert isinstance(empty.evaluation, EvaluationFacts)


def test_every_registry_family_lives_in_the_analysis_house() -> None:
    """A family declared for the wire but housed anywhere else — on the
    root, or nowhere — is the smuggling this pin exists to catch."""
    analysis_fields = {field.name for field in dataclasses.fields(AnalysisFacts)}
    registry_families = set(wire_fact_family_order()) - _PLAN_CARRIED_FAMILIES
    assert analysis_fields == registry_families


def test_comparison_and_evaluation_houses_are_born_empty() -> None:
    """Zero families is the CURRENT ratified state, not an omission: the
    houses exist so the §4 grammar has typed homes, and their first
    resident arrives only with a declared wire-revision bump."""
    assert dataclasses.fields(ComparisonFacts) == ()
    assert dataclasses.fields(EvaluationFacts) == ()

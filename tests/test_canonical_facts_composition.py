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
    CanonicalModel,
    ComparisonFacts,
    EvaluationFacts,
    ViolationRow,
)
from codeclone.canonical import model as canonical_model
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


# ---------------------------------------------------------------------------
# A fact ROW requires every field; only a CONTAINER may default.
#
# The rule is the four-state law one level up. On a row, a default makes
# ABSENCE project to a value: a construction site that never mentions the
# field gets the default silently, and for an evidence tuple the default is
# empty -- which reads as "the producer had nothing to say" rather than
# "nobody asked". On a container it means the opposite and is correct: a
# family carrying no rows is itself a statement, and the composition root
# composes whatever it is handed.
#
# Measured, not assumed: this pin exists because ``ViolationRow.locations``
# was shipped WITHOUT a default and the delivery report claimed that as the
# guarantee -- while giving it one turned the whole suite green (8103
# passed, nothing red). The type stops the author, not the tree: mypy reds
# on a call site that omits an argument, and there is no such call site
# until someone writes the next one. A guarantee nothing executes is a
# comment.
# ---------------------------------------------------------------------------

#: The dataclasses a default legitimately belongs on. Declared as a SET and
#: compared for equality below, so the rule cannot be dodged by moving a row
#: into this list: growing it is a visible, reviewable edit.
_CONTAINER_TYPES = frozenset({AnalysisFacts, CanonicalFacts, CanonicalModel})

#: Floor on the enumerated row population. An enumeration that silently
#: returned nothing would satisfy every "no offenders" assertion below.
_MIN_ROW_TYPES = 18


def _model_dataclasses() -> tuple[type, ...]:
    """Every dataclass the model module itself declares."""
    return tuple(
        sorted(
            (
                value
                for value in vars(canonical_model).values()
                if isinstance(value, type)
                and dataclasses.is_dataclass(value)
                and value.__module__ == canonical_model.__name__
            ),
            key=lambda cls: cls.__name__,
        )
    )


def _defaulted_fields(cls: type) -> tuple[str, ...]:
    """Fields of ``cls`` a caller may omit. The one predicate, used by all
    the pins below AND by the control that proves it can see a default."""
    return tuple(
        field.name
        for field in dataclasses.fields(cls)
        if field.default is not dataclasses.MISSING
        or field.default_factory is not dataclasses.MISSING
    )


def test_the_default_detector_actually_sees_a_default() -> None:
    """The control. Without it every pin below passes on a broken predicate.

    Both spellings, because a detector that reads only one of them would
    leave the other free: ``= ()`` lands in ``default`` and
    ``field(default_factory=tuple)`` in ``default_factory``.
    """

    @dataclasses.dataclass(frozen=True)
    class _Probe:
        required: int
        defaulted: tuple[int, ...] = ()
        factoried: tuple[int, ...] = dataclasses.field(default_factory=tuple)

    assert _defaulted_fields(_Probe) == ("defaulted", "factoried")


def test_a_canonical_fact_row_requires_every_field() -> None:
    """No row type may let a caller omit a field."""

    rows = [cls for cls in _model_dataclasses() if cls not in _CONTAINER_TYPES]
    assert len(rows) >= _MIN_ROW_TYPES, (
        f"only {len(rows)} row types enumerated; the walk found nothing to "
        "check and every assertion here would be vacuous"
    )
    offenders = sorted(
        f"{cls.__name__}.{name}" for cls in rows for name in _defaulted_fields(cls)
    )
    assert offenders == [], (
        "a canonical fact row field gained a default; absence would project "
        f"to that value instead of being refused: {offenders}"
    )


def test_only_the_declared_containers_carry_defaults() -> None:
    """The same rule from the other side, so the exemption cannot grow.

    An equality rather than a subset: a new container appearing here is a
    declared transition, and a row promoted into the container list to
    escape the rule above is the same edit and equally visible.
    """

    defaulting = {cls for cls in _model_dataclasses() if _defaulted_fields(cls)}
    assert defaulting == set(_CONTAINER_TYPES), {
        "unexpected": sorted(cls.__name__ for cls in defaulting - _CONTAINER_TYPES),
        "no_longer_defaulting": sorted(
            cls.__name__ for cls in _CONTAINER_TYPES - defaulting
        ),
    }


def test_the_violation_evidence_column_has_no_default() -> None:
    """The field the rule was written for, named so the mutant is explicit.

    ``locations`` is an evidence tuple: its empty value is a real, publish-
    able fact, so a default would be indistinguishable from a measured
    empty at every site that forgot to pass it. Required is what makes the
    omission a refusal instead of a silent zero.
    """

    field = next(
        item for item in dataclasses.fields(ViolationRow) if item.name == "locations"
    )
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING
    assert "locations" not in _defaulted_fields(ViolationRow)

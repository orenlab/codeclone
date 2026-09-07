# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Binding authority (liveness policy v5, the same unreleased generation).

A qualified spelling has no liveness authority until the receiver binding is
proven. The reproduced counterexample, measured on the engine before this
correction:

    class Widget:
        def render(self, a, b): ...

    class Gadget:                       # the negative arm: same shape,
        def polish(self, a, b): ...     # never mentioned anywhere

    def paint(Widget, a, b):            # the PARAMETER shadows the class
        return Widget.render(a, b)

    candidates 5 - dead 4 - unresolved_internal 0
    DEAD: Gadget, Gadget.polish, Widget, paint
    LIVE: pkg._shadow:Widget.render     <- the defect

``Widget`` at that call site is a function parameter of unknown type. The
negative arm is what makes the reading causal rather than plausible: a class
of identical shape that nothing mentions stays dead, so the LIVE verdict came
from the receiver's SPELLING and nothing else.

The rule, and it is one rule for every arm that recovers an owner from a name:

    proven module ``alias.attr``  -> may be a strong witness
    proven class ``binding.attr`` -> may be a strong witness
    receiver is a parameter, an unresolved local, or an ambiguous binding
                                  -> NOT LIVE
                                  -> ``unresolved_internal``,
                                     reason ``ambiguous_internal_binding``

Not a new generation and not a new reason: the vocabulary already had the
word for a symbol whose only support is a name no binding settles, and this
is that case - the support was never a reference, only a coincidence.

Tightening is safe in THIS lane and only here. The attribute name of a
refused ``receiver.attr`` is already a bare-name signal, so the symbol lands
in the abstention rather than in the dead lane; a lane with no such backstop
(the framework-registration edges) would push a refused symbol to DEAD, which
is why it is not touched by this correction.

Both boundaries are pinned under DIFFERENT tests. Every refusal pin is paired
with the control that binds the same receiver for real and must keep its
witness, because a rule that refuses everything passes every refusal pin.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from codeclone.analysis._module_walk import (
    _collect_lexical_binding_facts,
    _LexicalScopeBuilder,
    _proven_receiver_binding,
    _ProvenBinding,
)
from codeclone.metrics.class_facts import collect_class_walk_facts
from codeclone.metrics.cohesion import _resolve_lcom4
from codeclone.models import binding_witness
from tests._liveness_report_helpers import (
    VERDICT_DEAD,
    VERDICT_LIVE,
    VERDICT_UNRESOLVED,
    analysis_report,
    dead_code_family_of,
    live_root_reason_by_qualname,
    liveness_verdict,
    unresolved_internal_by_qualname,
)

_SCOPE_ID = "9d4a1f26-7c58-4b0e-9a3d-2f6b0c1e84d7"

#: The abstention this correction is allowed to produce, and no other.
_AMBIGUOUS = "ambiguous_internal_binding"


def _source(body: str) -> str:
    return textwrap.dedent(body).lstrip()


# ---------------------------------------------------------------------------
# The unit-level oracle. One helper answers every arm, so one pin covers the
# decision and the report pins below cover the wiring.


def _binding_of(
    source: str, name: str, *, inside: str | None = None
) -> _ProvenBinding | None:
    """What ``name`` is proven to bind, resolved in the scope it is written in."""

    tree = ast.parse(_source(source))
    builder = _LexicalScopeBuilder()
    builder.build(tree)
    for scope, receiver, _attribute in builder.attribute_loads:
        if receiver == name and inside in (None, scope.path):
            return _proven_receiver_binding(receiver, scope)
    raise AssertionError(f"no attribute load on {name!r} in this source")


def test_a_receiver_the_enclosing_scope_bound_is_not_proven() -> None:
    """Every shape that rebinds the receiver refuses, and says so as ``None``.

    Parametrised over the five shadowing shapes rather than one, because a
    proof that consulted only ``ast.arg`` would pass a parameter pin and let
    a loop target through.
    """

    shapes = {
        "parameter": "def paint(Widget, a):\n    return Widget.render(a)\n",
        "local-assignment": (
            "def paint(opaque, a):\n"
            "    Widget = opaque()\n"
            "    return Widget.render(a)\n"
        ),
        "loop-target": (
            "def paint(items, a):\n"
            "    for Widget in items:\n"
            "        return Widget.render(a)\n"
            "    return None\n"
        ),
        "comprehension-target": (
            "def paint(items, a):\n    return [Widget.render(a) for Widget in items]\n"
        ),
        "walrus": (
            "def paint(opaque, a):\n"
            "    if (Widget := opaque()):\n"
            "        return Widget.render(a)\n"
            "    return None\n"
        ),
    }
    for shape, source in shapes.items():
        declaration = "class Widget:\n    def render(self, a):\n        return a\n\n\n"
        assert _binding_of(declaration + source, "Widget") is None, shape


def test_a_receiver_the_module_really_binds_is_proven() -> None:
    """The other boundary: a real class binding and a real module alias.

    Under a different test from the refusal above, so a proof stuck at
    "nothing is ever proven" cannot pass both.
    """

    class_bound = _binding_of(
        """
        class Widget:
            def render(self, a):
                return a


        def paint(a):
            return Widget.render(a)
        """,
        "Widget",
    )
    assert class_bound is not None
    assert (class_bound.kind, class_bound.path) == ("definition", "Widget")

    import_bound = _binding_of(
        """
        import json


        def dump(a):
            return json.dumps(a)
        """,
        "json",
    )
    assert import_bound is not None
    assert import_bound.kind == "import"


def test_a_name_bound_as_a_definition_and_as_something_else_is_ambiguous() -> None:
    """``class Widget`` plus ``Widget = _make()`` binds no single owner.

    The third receiver category of the law, and the one a parameter-only
    reading would miss entirely: nothing is shadowed here, the module itself
    binds the name twice.
    """

    assert (
        _binding_of(
            """
            class Widget:
                def render(self, a):
                    return a


            def _make(a):
                return a


            Widget = _make(1)


            def paint(a):
                return Widget.render(a)
            """,
            "Widget",
        )
        is None
    )


def test_the_lexical_pass_publishes_only_proven_pairs() -> None:
    """The facts the resolver reads carry the proven pairs and nothing else."""

    facts = _collect_lexical_binding_facts(
        ast.parse(
            _source(
                """
                import json


                class Widget:
                    def render(self, a):
                        return a


                def proven(a):
                    return Widget.render(json.dumps(a))


                def shadowed(Widget, json, a):
                    return Widget.render(json.dumps(a))
                """
            )
        ),
        settled_import_names=frozenset(),
    )
    assert ("Widget", "render") in facts.definition_bound_attributes
    assert ("json", "dumps") in facts.import_bound_attributes
    # One spelling, two sites: the pair is admitted because ONE site proved
    # it, which is the correct granularity - the proven site really does
    # reference the definition. What must never happen is a pair admitted
    # with no proven site at all.
    unproven = _collect_lexical_binding_facts(
        ast.parse(
            _source(
                """
                import json


                class Widget:
                    def render(self, a):
                        return a


                def shadowed(Widget, json, a):
                    return Widget.render(json.dumps(a))
                """
            )
        ),
        settled_import_names=frozenset(),
    )
    assert unproven.definition_bound_attributes == frozenset()
    assert unproven.import_bound_attributes == frozenset()


# ---------------------------------------------------------------------------
# The report layer: what a user actually reads, from a spawned run.

_SHADOWED_CLASS_TREE = {
    "pkg/__init__.py": "",
    "pkg/_shadow.py": _source(
        """
        class Widget:
            def render(self, a, b):
                return a + b


        class Gadget:
            def polish(self, a, b):
                return a - b


        def paint(Widget, a, b):
            return Widget.render(a, b)
        """
    ),
}

_BOUND_CLASS_TREE = {
    "pkg/__init__.py": "",
    "pkg/_shadow.py": _source(
        """
        class Widget:
            def render(self, a, b):
                return a + b


        class Gadget:
            def polish(self, a, b):
                return a - b


        def paint(a, b):
            return Widget.render(a, b)
        """
    ),
}


def test_a_parameter_spelling_a_class_no_longer_holds_its_method_live(
    tmp_path: Path,
) -> None:
    """The reproduced counterexample, with its negative arm.

    ``Widget.render`` abstains on the exact reason the vocabulary already
    owns, and carries the bare-name witness that names the coincidence.
    ``Gadget.polish`` - identical shape, never mentioned - stays DEAD, which
    is what proves the abstention was caused by the receiver and not by a
    lane that stopped reporting.
    """

    payload = analysis_report(
        tmp_path, _SHADOWED_CLASS_TREE, "shadowed-class", scope_id=_SCOPE_ID
    )
    assert liveness_verdict(payload, "pkg._shadow:Widget.render") == VERDICT_UNRESOLVED
    assert liveness_verdict(payload, "pkg._shadow:Gadget.polish") == VERDICT_DEAD
    assert liveness_verdict(payload, "pkg._shadow:paint") == VERDICT_DEAD
    row = unresolved_internal_by_qualname(dead_code_family_of(payload))[
        "pkg._shadow:Widget.render"
    ]
    assert row["reason"] == _AMBIGUOUS
    assert row["witness"] == binding_witness("render")


def test_a_class_the_scope_really_binds_still_holds_its_method_live(
    tmp_path: Path,
) -> None:
    """The positive control: remove the shadowing parameter, nothing else.

    The two trees differ in exactly one token - ``paint``'s first parameter -
    so a rule that refused every class receiver would red here while the
    refusal pin above stayed green.
    """

    payload = analysis_report(
        tmp_path, _BOUND_CLASS_TREE, "bound-class", scope_id=_SCOPE_ID
    )
    assert liveness_verdict(payload, "pkg._shadow:Widget.render") == VERDICT_LIVE
    assert liveness_verdict(payload, "pkg._shadow:Gadget.polish") == VERDICT_DEAD


def _alias_tree(parameters: str) -> dict[str, str]:
    return {
        "pkg/__init__.py": "",
        "pkg/_target.py": _source(
            """
            def handler(a):
                return a


            def ignored(a):
                return a
            """
        ),
        "pkg/_shadow.py": _source(
            f"""
            from pkg import _target


            def use({parameters}):
                return _target.handler(a)
            """
        ),
    }


def test_a_parameter_spelling_a_module_alias_no_longer_holds_its_attribute_live(
    tmp_path: Path,
) -> None:
    payload = analysis_report(
        tmp_path, _alias_tree("_target, a"), "shadowed-alias", scope_id=_SCOPE_ID
    )
    assert liveness_verdict(payload, "pkg._target:handler") == VERDICT_UNRESOLVED
    assert liveness_verdict(payload, "pkg._target:ignored") == VERDICT_DEAD
    row = unresolved_internal_by_qualname(dead_code_family_of(payload))[
        "pkg._target:handler"
    ]
    assert row["reason"] == _AMBIGUOUS


def test_a_module_alias_the_scope_really_binds_still_holds_its_attribute_live(
    tmp_path: Path,
) -> None:
    payload = analysis_report(
        tmp_path, _alias_tree("a"), "bound-alias", scope_id=_SCOPE_ID
    )
    assert liveness_verdict(payload, "pkg._target:handler") == VERDICT_LIVE
    assert liveness_verdict(payload, "pkg._target:ignored") == VERDICT_DEAD


def _symbol_tree(body: str) -> dict[str, str]:
    return {
        "pkg/__init__.py": "",
        "pkg/_target.py": _source(
            """
            def handler(a):
                return a


            def ignored(a):
                return a
            """
        ),
        # Built by concatenation, not by interpolating a multi-line body into
        # an indented template: dedent then finds no common prefix and the
        # module does not parse, which reads as "nothing references anything"
        # and passes a DEAD pin for the wrong reason. Measured here.
        "pkg/_shadow.py": f"from pkg._target import handler\n\n\n{_source(body)}",
    }


def test_a_parameter_spelling_an_imported_symbol_no_longer_holds_it_live(
    tmp_path: Path,
) -> None:
    """The bare-name arm of the same class: no receiver, the same defect.

    ``handler`` here is the parameter of ``use``; the import it shares a
    spelling with binds nothing at that load. The symbol falls to DEAD rather
    than to the abstention, and correctly so: the load was SETTLED as a local,
    so it is not a bare-name signal either - policy v5's own reading.
    """

    payload = analysis_report(
        tmp_path,
        _symbol_tree("def use(handler):\n    return handler\n"),
        "shadowed-symbol",
        scope_id=_SCOPE_ID,
    )
    # The consumer module is asserted MEASURED first. A tree that does not
    # parse reports no reference at all, and that reads exactly like a
    # correctly withdrawn one - it passed this pin for that reason once.
    assert liveness_verdict(payload, "pkg._shadow:use") == VERDICT_DEAD
    assert liveness_verdict(payload, "pkg._target:handler") == VERDICT_DEAD
    assert liveness_verdict(payload, "pkg._target:ignored") == VERDICT_DEAD


def test_an_import_the_module_itself_rebinds_abstains_rather_than_dying(
    tmp_path: Path,
) -> None:
    """``from x import y`` then ``y = wrap(y)``: no single owner, so abstain.

    The law's third receiver category, and the one place this correction
    could have gone the wrong way. Withdrawing the reference is right - the
    load does not provably reach the imported definition - but withdrawing
    the SIGNAL as well reported the definition DEAD while the module calls a
    wrapper around it. Measured: LIVE before the correction, DEAD after the
    first draft of it, and the abstention is the honest third answer.
    """

    payload = analysis_report(
        tmp_path,
        _symbol_tree(
            "def _wrap(fn):\n"
            "    return fn\n"
            "\n"
            "\n"
            "handler = _wrap(handler)\n"
            "\n"
            "\n"
            "def use(a):\n"
            "    return handler(a)\n"
        ),
        "rebound-symbol",
        scope_id=_SCOPE_ID,
    )
    assert liveness_verdict(payload, "pkg._shadow:use") == VERDICT_DEAD
    assert liveness_verdict(payload, "pkg._target:handler") == VERDICT_UNRESOLVED
    assert liveness_verdict(payload, "pkg._target:ignored") == VERDICT_DEAD
    row = unresolved_internal_by_qualname(dead_code_family_of(payload))[
        "pkg._target:handler"
    ]
    assert row["reason"] == _AMBIGUOUS


def test_an_imported_symbol_the_scope_really_binds_stays_live(tmp_path: Path) -> None:
    payload = analysis_report(
        tmp_path,
        _symbol_tree("def use(a):\n    return handler(a)\n"),
        "bound-symbol",
        scope_id=_SCOPE_ID,
    )
    assert liveness_verdict(payload, "pkg._shadow:use") == VERDICT_DEAD
    assert liveness_verdict(payload, "pkg._target:handler") == VERDICT_LIVE
    assert liveness_verdict(payload, "pkg._target:ignored") == VERDICT_DEAD


def _self_tree(entry: str) -> dict[str, str]:
    """One class whose entry method is the variable, and one that is never
    mentioned at all - the negative arm every dispatch pin is read against."""

    body = textwrap.indent(_source(entry), "    ")
    return {
        "pkg/__init__.py": "",
        "pkg/_shadow.py": (
            "class Widget:\n"
            f"{body}\n"
            "    def render(self, a):\n"
            "        return a\n"
            "\n"
            "\n"
            "class Gadget:\n"
            "    def polish(self, a):\n"
            "        return a\n"
        ),
    }


@pytest.mark.parametrize(
    ("name", "entry"),
    [
        pytest.param(
            "staticmethod-argument-named-self",
            "@staticmethod\ndef entry(self, a):\n    return self.render(a)\n",
            id="staticmethod-argument-named-self",
        ),
        pytest.param(
            "outer-method-not-a-receiver",
            "def entry(this, a):\n"
            "    def inner(self):\n"
            "        return self.render(a)\n"
            "    return inner\n",
            id="outer-method-first-parameter-is-not-self",
        ),
        # The containment case, reachable ONLY through a method whose own
        # receiver IS proven: the outer ``self`` is real, and the inner
        # function binds the name again. A fixture whose outer method already
        # fails the first-parameter test never reaches the traversal bound,
        # and pinned nothing about it - measured, by a mutation that survived.
        pytest.param(
            "nested-function-rebinds-a-real-receiver",
            "def entry(self, a):\n"
            "    def inner(self):\n"
            "        return self.render(a)\n"
            "    return inner\n",
            id="nested-function-rebinds-a-real-receiver",
        ),
        pytest.param(
            "method-that-rebinds-self",
            "def entry(self, a):\n    self = a\n    return self.render(a)\n",
            id="method-that-rebinds-self",
        ),
    ],
)
def test_a_receiver_only_spelled_self_does_not_dispatch(
    tmp_path: Path, name: str, entry: str
) -> None:
    """``self`` is a spelling; the receiver is the first parameter of a method.

    Three ways the spelling can mean something else, each a separate case of
    the table, and each one an object of unknown type at the call site.
    """

    payload = analysis_report(tmp_path, _self_tree(entry), name, scope_id=_SCOPE_ID)
    assert liveness_verdict(payload, "pkg._shadow:Widget.render") == VERDICT_UNRESOLVED
    assert liveness_verdict(payload, "pkg._shadow:Gadget.polish") == VERDICT_DEAD
    row = unresolved_internal_by_qualname(dead_code_family_of(payload))[
        "pkg._shadow:Widget.render"
    ]
    assert row["reason"] == _AMBIGUOUS


def test_an_ordinary_method_receiver_still_dispatches(tmp_path: Path) -> None:
    """The control: ``self`` really is this method's receiver, so row 1 holds."""

    payload = analysis_report(
        tmp_path,
        _self_tree("def entry(self, a):\n    return self.render(a)\n"),
        "bound-self",
        scope_id=_SCOPE_ID,
    )
    assert liveness_verdict(payload, "pkg._shadow:Widget.render") == VERDICT_LIVE
    assert liveness_verdict(payload, "pkg._shadow:Gadget.polish") == VERDICT_DEAD


def _decorator_tree(parameters: str) -> dict[str, str]:
    return {
        "pkg/__init__.py": "",
        "pkg/_shadow.py": _source(
            f"""
            import json


            def make({parameters}):
                @json.register
                def inner(a):
                    return a

                return inner


            def sibling(a):
                return a
            """
        ),
    }


_ROOTED = "pkg._shadow:make.<locals>.inner"


def test_a_parameter_spelling_an_external_alias_no_longer_roots_a_definition(
    tmp_path: Path,
) -> None:
    """The decorator arm reads a root name against a module-wide alias set.

    The verdict is NOT the pin here, and that is the point: ``inner`` is
    returned by ``make``, so the lexical binding lane holds it live either
    way. A sibling mechanism doing the work is exactly how this arm would
    stay green while broken, so the live-ROOT lane is probed alone.
    """

    payload = analysis_report(
        tmp_path, _decorator_tree("json, a"), "shadowed-decorator", scope_id=_SCOPE_ID
    )
    roots = live_root_reason_by_qualname(dead_code_family_of(payload))
    assert _ROOTED not in roots, roots
    assert liveness_verdict(payload, "pkg._shadow:sibling") == VERDICT_DEAD


def test_cohesion_still_reads_the_receiver_blind_lane(tmp_path: Path) -> None:
    """The score guard: LCOM's input is NOT narrowed by this correction.

    ``self_dispatched_calls`` is a second, receiver-proven projection built
    beside ``method_calls``; cohesion keeps reading the original. That is a
    deliberate boundary, not an oversight - LCOM is a user-facing score, and
    a change that moves one is accepted only through an independent
    benchmark, which this correction does not carry and does not need.

    The fixture is the one class where the two lanes disagree: a
    ``@staticmethod`` whose first argument is spelled ``self``. Liveness
    refuses it (pinned above); cohesion must still see the edge, or the two
    methods fall into separate components and the number moves.
    """

    class_node = next(
        node
        for node in ast.parse(
            _source(
                """
                class Widget:
                    @staticmethod
                    def entry(self, a):
                        self.counter = 1
                        return self.render(a)

                    def render(self, a):
                        self.counter = 2
                        return a
                """
            )
        ).body
        if isinstance(node, ast.ClassDef)
    )
    facts = collect_class_walk_facts(
        class_node,
        analyzed_method_names=frozenset({"entry", "render"}),
        imported_symbol_targets={},
        imported_module_targets={},
    )
    assert facts.method_calls["entry"] == {"render"}
    assert facts.self_dispatched_calls["entry"] == set()
    # ``(lcom4, methods, instance vars)``. One component: the call edge
    # from the receiver-blind lane is what joins the two methods.
    assert _resolve_lcom4(facts) == (1, 2, 2)


def test_an_external_alias_the_scope_really_binds_still_roots_a_definition(
    tmp_path: Path,
) -> None:
    payload = analysis_report(
        tmp_path, _decorator_tree("a"), "bound-decorator", scope_id=_SCOPE_ID
    )
    roots = live_root_reason_by_qualname(dead_code_family_of(payload))
    assert roots.get(_ROOTED) == "external_decorator", roots
    assert liveness_verdict(payload, "pkg._shadow:sibling") == VERDICT_DEAD

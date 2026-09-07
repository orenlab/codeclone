# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Criterion C, liveness policy v5: two defects of one causal nature.

C1  a bare-name coincidence may no longer emit LIVE
C2  nested definitions may no longer fall out of the candidate population

They are one work because C2 cannot be added correctly without proper
lexical binding, and C1 is exactly what strips the coarse name mechanism of
its false authority: adding nested definitions first would only have handed
the bare-name fallback more symbols to revive by ``helper == helper``.

Measured on this repository at 5f35a50f: 4515 symbols (26.3% of 17185
candidates) were live ONLY because ``local_name in referenced_names`` - a
spelling coincidence with no binding witness, 561 of them sharing that
spelling with another such symbol - and 1030 function-local functions plus
189 function-local classes produced zero symbols under every lane.

The ratified semantics, as executable rows:

    resolved binding evidence      -> LIVE
    bare-name sole support         -> UNRESOLVED (ambiguous_internal_binding),
                                      in BOTH worlds
    no internal support            -> the ordinary world-dependent evaluation,
                                      except that a function-local definition
                                      has no external namespace and is never
                                      unresolved on reachability grounds

Every report-level pin here spawns the CLI (``tests/_liveness_report_helpers``)
and is paired with a control that differs only in the mechanism the pin
names; every unit-level pin runs the real per-file walk. The nested
population has no presence witness in the complexity family - it must not
enter that family, or any family but dead_code - so a LIVE nested verdict is
always proven by its control: the same tree with the reference removed
reports the symbol dead, which is what shows it was measured at all.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import pytest

from codeclone.cache._wire_decode import _decode_wire_nested_definition
from codeclone.cache._wire_encode import _encode_nested_definitions
from codeclone.cache.entries import _nested_definition_dict_from_model
from codeclone.metrics.dead_code import (
    classify_liveness,
    find_suppressed_unused,
    resolve_reexport_hops,
)
from codeclone.models import (
    CacheFactsDict,
    DeadCandidate,
    ExternalReachability,
    LivenessVocabularyError,
    ModuleDep,
    NestedDefinition,
    UnresolvedInternalItem,
    binding_witness,
)
from tests._ast_metrics_helpers import build_test_module_registry, extract_file_metrics
from tests._liveness_report_helpers import (
    VERDICT_DEAD,
    VERDICT_LIVE,
    VERDICT_UNRESOLVED,
    analysis_report,
    dead_code_family,
    dead_code_family_of,
    dead_qualnames,
    live_root_reason_by_qualname,
    liveness_verdict,
    unresolved_by_qualname,
    unresolved_internal_by_qualname,
    unresolved_override_by_qualname,
)

_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f43"
_CLOSED = ("--dead-code-world", "closed")
_WORLDS = (("open", ()), ("closed", _CLOSED))


def _nested_verdict(family: dict[str, object], qualname: str) -> str:
    """The verdict of a symbol the complexity family never carries.

    LIVE is an absence here as everywhere; the callers pair every LIVE with
    the control that makes the same symbol appear in the dead lane.
    """

    if qualname in dead_qualnames(family):
        return VERDICT_DEAD
    if qualname in unresolved_internal_by_qualname(family) or (
        qualname in unresolved_by_qualname(family)
    ):
        return VERDICT_UNRESOLVED
    if qualname in unresolved_override_by_qualname(family):
        return "unresolved_override"
    return VERDICT_LIVE


def _summary(family: dict[str, object]) -> dict[str, object]:
    summary = family["summary"]
    assert isinstance(summary, dict)
    return summary


def _rows(family: dict[str, object], lane: str) -> list[dict[str, object]]:
    rows = family[lane]
    assert isinstance(rows, list)
    return [dict(row) for row in rows if isinstance(row, dict)]


# ---------------------------------------------------------------------------
# The nested population, end to end.
# ---------------------------------------------------------------------------

#: ``pkg.core`` is a PUBLIC module: its module-level ``public_twin`` is
#: externally reachable, which is what makes the nested rows' absence from
#: the reachability lane a statement about nesting and not about the module.
_NESTED_TREE = {
    "pkg/__init__.py": "",
    "pkg/core.py": """
def factory():
    def used_helper() -> int:
        return 1

    def unused_helper() -> int:
        return 2

    class Widget:
        def render(self) -> int:
            return self.paint()

        def paint(self) -> int:
            return 3

        def lonely(self) -> int:
            return 4

    return used_helper(), Widget()


def other():
    def unused_helper() -> int:
        return 5

    return 6


def public_twin() -> int:
    return 7
""",
    "pkg/entry.py": """
from .core import factory, other


def run():
    return factory(), other()
""",
}

_USED_HELPER = "pkg.core:factory.<locals>.used_helper"
_UNUSED_HELPER = "pkg.core:factory.<locals>.unused_helper"
_OTHER_UNUSED_HELPER = "pkg.core:other.<locals>.unused_helper"
_WIDGET = "pkg.core:factory.<locals>.Widget"
_WIDGET_RENDER = "pkg.core:factory.<locals>.Widget.render"
_WIDGET_PAINT = "pkg.core:factory.<locals>.Widget.paint"
_WIDGET_LONELY = "pkg.core:factory.<locals>.Widget.lonely"
_PUBLIC_TWIN = "pkg.core:public_twin"


@pytest.fixture(scope="module")
def nested_reports(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, dict[str, object]]:
    root = tmp_path_factory.mktemp("nested")
    return {
        world: analysis_report(
            root, _NESTED_TREE, f"nested-{world}", scope_id=_SCOPE_ID, cli_args=args
        )
        for world, args in _WORLDS
    }


def test_the_inventory_names_both_populations(
    nested_reports: dict[str, dict[str, object]],
) -> None:
    """Acceptance 1: module-level and nested definitions in one explicit inventory.

    The counters are the population the lane judged, on the wire, so a
    reader can tell "no nested finding" from "nested definitions were never
    counted". Seven nested rows: three functions, one class, three methods.
    """

    for world in ("open", "closed"):
        summary = _summary(dead_code_family_of(nested_reports[world]))
        assert summary["nested_candidates"] == 7
        # factory, other, public_twin, run - the module-level population.
        assert summary["candidates"] == 4


def test_two_nested_names_under_different_parents_are_two_symbols(
    nested_reports: dict[str, dict[str, object]],
) -> None:
    """Acceptance 2: identity distinguishes lexical owners.

    Both ``unused_helper`` definitions are dead, and they are two rows with
    two qualnames; a lane that collapsed them would carry one, and would hand
    the bare-name fallback exactly the collision C2 was not allowed to add.
    """

    for world in ("open", "closed"):
        family = dead_code_family_of(nested_reports[world])
        dead = dead_qualnames(family)
        assert {_UNUSED_HELPER, _OTHER_UNUSED_HELPER} <= dead
        by_qualname = {str(row["qualname"]): row for row in _rows(family, "items")}
        assert (
            by_qualname[_UNUSED_HELPER]["start_line"]
            != (by_qualname[_OTHER_UNUSED_HELPER]["start_line"])
        )


def test_a_referenced_nested_definition_is_live_and_its_unreferenced_sibling_dead(
    nested_reports: dict[str, dict[str, object]],
    tmp_path: Path,
) -> None:
    """Acceptance 3 and 4, with the causal control that proves measurement.

    ``used_helper`` is called by a bare name inside its parent, which the
    lexical chain binds to the nested definition (the ``lexical_binding_
    reference`` mechanism); ``Widget`` is instantiated; ``Widget.paint`` is
    dispatched on ``self``. All three are absent from every lane while their
    unreferenced siblings are dead in both worlds. The control removes the
    ONE call of ``used_helper`` and the symbol becomes dead - which is what
    proves it was measured, and that the call was the reason.
    """

    for world in ("open", "closed"):
        family = dead_code_family_of(nested_reports[world])
        assert _nested_verdict(family, _USED_HELPER) == VERDICT_LIVE
        assert _nested_verdict(family, _WIDGET) == VERDICT_LIVE
        assert _nested_verdict(family, _WIDGET_PAINT) == VERDICT_LIVE
        assert _nested_verdict(family, _UNUSED_HELPER) == VERDICT_DEAD
        assert _nested_verdict(family, _WIDGET_LONELY) == VERDICT_DEAD
        assert _nested_verdict(family, _WIDGET_RENDER) == VERDICT_DEAD

    without_call = dict(_NESTED_TREE)
    without_call["pkg/core.py"] = _NESTED_TREE["pkg/core.py"].replace(
        "return used_helper(), Widget()", "return 1, Widget()"
    )
    for world, args in _WORLDS:
        family = dead_code_family(
            tmp_path,
            without_call,
            f"no-call-{world}",
            scope_id=_SCOPE_ID,
            cli_args=args,
        )
        assert _nested_verdict(family, _USED_HELPER) == VERDICT_DEAD
        assert _nested_verdict(family, _WIDGET) == VERDICT_LIVE


def test_a_nested_definition_does_not_inherit_reachability_from_its_name(
    nested_reports: dict[str, dict[str, object]],
) -> None:
    """Acceptance 6: no external namespace can spell a closure.

    ``public_twin`` and ``unused_helper`` are both public-named and both
    unreferenced in a public module. The module-level one is externally
    reachable, so the open world abstains on it; the nested one is dead in
    the open world too, and never appears in the reachability lane.
    """

    open_family = dead_code_family_of(nested_reports["open"])
    closed_family = dead_code_family_of(nested_reports["closed"])
    assert liveness_verdict(nested_reports["open"], _PUBLIC_TWIN) == VERDICT_UNRESOLVED
    assert unresolved_by_qualname(open_family)[_PUBLIC_TWIN]["reason"] == (
        "externally_reachable"
    )
    assert liveness_verdict(nested_reports["closed"], _PUBLIC_TWIN) == VERDICT_DEAD
    for family in (open_family, closed_family):
        assert _nested_verdict(family, _UNUSED_HELPER) == VERDICT_DEAD
        assert not any(
            ".<locals>." in qualname for qualname in unresolved_by_qualname(family)
        )


def test_the_nested_population_enters_no_other_family(
    nested_reports: dict[str, dict[str, object]],
) -> None:
    """Scope discipline: exactly ONE consumer path.

    Complexity, coupling and cohesion must not silently gain a population.
    The nested rows are absent from every other family's items while present
    in the dead-code counters of the same report.
    """

    payload = nested_reports["closed"]
    families = payload["metrics"]["families"]  # type: ignore[index]
    assert isinstance(families, dict)
    for name in ("complexity", "coupling", "cohesion"):
        items = families[name]["items"]
        assert isinstance(items, list)
        assert not any(".<locals>." in str(item.get("qualname", "")) for item in items)
    assert _summary(families["dead_code"])["nested_candidates"] == 7


def test_warm_cache_equals_cold_for_the_nested_population(tmp_path: Path) -> None:
    """Acceptance 7: the nested rows ride the dependent cache lane whole."""

    cold = dead_code_family(tmp_path, _NESTED_TREE, "nested-warm", scope_id=_SCOPE_ID)
    warm = dead_code_family(
        tmp_path,
        _NESTED_TREE,
        "nested-warm",
        scope_id=_SCOPE_ID,
        expect_warm_cache=True,
    )
    for lane in ("items", "unresolved", "unresolved_internal", "unresolved_overrides"):
        assert warm[lane] == cold[lane], lane
    assert _summary(warm) == _summary(cold)
    assert _summary(cold)["nested_candidates"] == 7
    assert _UNUSED_HELPER in dead_qualnames(warm)


# ---------------------------------------------------------------------------
# The anti-evasion fixture: nesting must not hide a class from the lane.
# ---------------------------------------------------------------------------

#: The same structural entity twice: at module level, and inside a function.
#: Both modules are private, so reachability cannot separate them and the
#: only difference between the two verdict sets is the nesting.
_EVASION_TREE = {
    "pkg/__init__.py": "",
    "pkg/_flat.py": """
class Thing:
    def render(self) -> int:
        return 1
""",
    "pkg/_folded.py": """
def build():
    class Thing:
        def render(self) -> int:
            return 1

    return None
""",
}


def test_moving_a_class_inside_a_function_does_not_make_it_invisible(
    tmp_path: Path,
) -> None:
    """The governance regression: nesting is not a way out of jurisdiction.

    Measured on this repository at 5f35a50f, a function-local class and a
    function-local function produced zero symbols under every lane, and an
    agent independently found that nesting a class hides it from the health
    gate. Both twins are dead in both worlds now, and the nested one is
    counted in the population the lane judged.
    """

    for world, args in _WORLDS:
        family = dead_code_family(
            tmp_path,
            _EVASION_TREE,
            f"evasion-{world}",
            scope_id=_SCOPE_ID,
            cli_args=args,
        )
        dead = dead_qualnames(family)
        assert {"pkg._flat:Thing", "pkg._flat:Thing.render"} <= dead
        assert {
            "pkg._folded:build.<locals>.Thing",
            "pkg._folded:build.<locals>.Thing.render",
        } <= dead
        assert _summary(family)["nested_candidates"] == 2


# ---------------------------------------------------------------------------
# C1 at the report level, for the nested population too.
# ---------------------------------------------------------------------------

_COINCIDENCE_TREE = {
    "pkg/__init__.py": "",
    "pkg/_folded.py": """
def build():
    class Thing:
        def render(self) -> int:
            return 1

    return None
""",
    "pkg/use.py": """
from typing import Any


def touch(obj: Any) -> int:
    return obj.render()
""",
}

_FOLDED_RENDER = "pkg._folded:build.<locals>.Thing.render"


def test_a_bare_name_neither_revives_nor_kills_a_nested_method(tmp_path: Path) -> None:
    """Acceptance 5, both boundaries, on a nested symbol.

    ``obj.render()`` on a receiver of unknown type spells the method's name
    and proves nothing. The method is in the binding lane in both worlds -
    not dead (the load exists), not live (nothing binds it) - and its
    witness names the coincidence. The control removes the attribute call
    and the method is dead.
    """

    for world, args in _WORLDS:
        family = dead_code_family(
            tmp_path,
            _COINCIDENCE_TREE,
            f"coincidence-{world}",
            scope_id=_SCOPE_ID,
            cli_args=args,
        )
        assert _nested_verdict(family, _FOLDED_RENDER) == VERDICT_UNRESOLVED
        row = unresolved_internal_by_qualname(family)[_FOLDED_RENDER]
        assert row["reason"] == "ambiguous_internal_binding"
        assert row["local_name"] == "render"
        assert row["witness"] == "bare_name_reference:render"
        assert row["kind"] == "method"
        assert _summary(family)["unresolved_internal"] == 1

    without_load = dict(_COINCIDENCE_TREE)
    without_load["pkg/use.py"] = """
from typing import Any


def touch(obj: Any) -> int:
    return 0
"""
    for world, args in _WORLDS:
        family = dead_code_family(
            tmp_path,
            without_load,
            f"no-load-{world}",
            scope_id=_SCOPE_ID,
            cli_args=args,
        )
        assert _nested_verdict(family, _FOLDED_RENDER) == VERDICT_DEAD
        assert _summary(family)["unresolved_internal"] == 0


# ---------------------------------------------------------------------------
# The rules the module-level population gets, applied to the nested one.
# ---------------------------------------------------------------------------

_RULES_TREE = {
    "pkg/__init__.py": "",
    "pkg/_rules.py": """
from ext import register
from flask import Flask
from vendor import Base


def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "ok"

    def plain():
        return 1

    return app


def hooks():
    @register
    def hook():
        return 1

    def silenced():  # codeclone: ignore[dead-code]
        return 2

    return None


def adapters():
    class Impl(Base):
        def handle(self):
            return 1

        def __mangled(self):
            return 2

    return None
""",
}

_INDEX = "pkg._rules:create_app.<locals>.index"
_PLAIN = "pkg._rules:create_app.<locals>.plain"
_HOOK = "pkg._rules:hooks.<locals>.hook"
_SILENCED = "pkg._rules:hooks.<locals>.silenced"
_IMPL = "pkg._rules:adapters.<locals>.Impl"
_HANDLE = "pkg._rules:adapters.<locals>.Impl.handle"
_MANGLED = "pkg._rules:adapters.<locals>.Impl.__mangled"


@pytest.fixture(scope="module")
def rules_family(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    root = tmp_path_factory.mktemp("rules")
    return dead_code_family(
        root, _RULES_TREE, "rules", scope_id=_SCOPE_ID, cli_args=_CLOSED
    )


def test_a_nested_framework_route_is_a_runtime_edge(
    rules_family: dict[str, object],
) -> None:
    """A route registered inside an application factory is the commonest
    shape of a framework edge; the undecorated sibling is the control."""

    assert _nested_verdict(rules_family, _INDEX) == VERDICT_LIVE
    assert _nested_verdict(rules_family, _PLAIN) == VERDICT_DEAD


def test_a_nested_external_decorator_roots_the_symbol(
    rules_family: dict[str, object],
) -> None:
    """The external-decorator root rule, at any lexical depth, and named in
    the evidence lane exactly as a module-level root would be."""

    assert _nested_verdict(rules_family, _HOOK) == VERDICT_LIVE
    assert live_root_reason_by_qualname(rules_family)[_HOOK] == "external_decorator"


def test_a_directive_on_a_nested_definition_binds(
    rules_family: dict[str, object],
) -> None:
    """Local policy reaches the nested population: the directive silences the
    row, and the run still reports what it silenced."""

    assert _nested_verdict(rules_family, _SILENCED) == VERDICT_LIVE
    suppressed = rules_family["suppressed_items"]
    assert isinstance(suppressed, list)
    assert _SILENCED in {str(row["qualname"]) for row in suppressed}


def test_a_nested_method_under_an_opaque_base_abstains_under_rule_three(
    rules_family: dict[str, object],
) -> None:
    """Rule 3 governs a nested method exactly as its module-level twin: the
    owning class's base binds outside the root, so the public method
    abstains, while the name-mangled private one - which no external base
    can override under Python's identity rules - stays dead-eligible."""

    assert _nested_verdict(rules_family, _HANDLE) == "unresolved_override"
    row = unresolved_override_by_qualname(rules_family)[_HANDLE]
    assert row["class_qualname"] == _IMPL
    assert row["base_names"] == ["Base"]
    assert _nested_verdict(rules_family, _MANGLED) == VERDICT_DEAD


# ---------------------------------------------------------------------------
# The lexical resolver, at the unit level over the real walk.
# ---------------------------------------------------------------------------


def _facts(
    tmp_path: Path,
    source: str,
    *,
    extra: dict[str, str] | None = None,
) -> tuple[frozenset[str], frozenset[str], tuple[NestedDefinition, ...]]:
    """(referenced_qualnames, referenced_names, nested_definitions) of pkg/m.py."""

    tree = {"pkg/__init__.py": "", "pkg/m.py": source, **(extra or {})}
    for relative, text in tree.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.lstrip("\n"), encoding="utf-8")
    registry = build_test_module_registry(root=tmp_path)
    metrics = extract_file_metrics(
        source=(tmp_path / "pkg/m.py").read_text(encoding="utf-8"),
        filepath="pkg/m.py",
        module_registry=registry,
    )
    return (
        metrics.referenced_qualnames,
        metrics.referenced_names,
        metrics.nested_definitions,
    )


def test_a_same_module_call_binds_the_definition_and_is_not_a_signal(
    tmp_path: Path,
) -> None:
    qualnames, names, _nested = _facts(
        tmp_path,
        """
def helper():
    return 1


def run():
    return helper()
""",
    )
    assert "pkg.m:helper" in qualnames
    assert "helper" not in names


def test_a_parameter_settles_its_own_loads(tmp_path: Path) -> None:
    """A load bound to a parameter refers to the parameter, never to a
    definition spelled the same way; it is neither evidence nor a signal."""

    qualnames, names, _nested = _facts(
        tmp_path,
        """
def helper():
    return 1


def run(helper):
    return helper()
""",
    )
    assert "pkg.m:helper" not in qualnames
    assert "helper" not in names


def test_a_class_body_rebinding_does_not_settle_the_load_it_reads(
    tmp_path: Path,
) -> None:
    """``helper = helper`` in a class body reads the enclosing ``helper``
    before rebinding it: the flow hazard the resolver closes by never
    letting a non-definition class binding settle a load."""

    qualnames, names, _nested = _facts(
        tmp_path,
        """
def helper():
    return 1


class Holder:
    helper = helper
""",
    )
    assert "pkg.m:helper" in qualnames
    assert "helper" not in names


def test_an_unbound_name_and_an_attribute_stay_signals(tmp_path: Path) -> None:
    qualnames, names, _nested = _facts(
        tmp_path,
        """
def run(obj):
    return obj.close(), mystery()
""",
    )
    assert {"close", "mystery"} <= names
    assert not any(qualname.endswith(":mystery") for qualname in qualnames)


def test_a_self_reference_is_neither_evidence_nor_a_signal(tmp_path: Path) -> None:
    qualnames, names, _nested = _facts(
        tmp_path,
        """
def recursive(n):
    return recursive(n - 1)
""",
    )
    assert "pkg.m:recursive" not in qualnames
    assert "recursive" not in names


def test_a_decorator_is_evaluated_in_the_enclosing_scope(tmp_path: Path) -> None:
    """A parameter named like the decorator must not capture the decorator's
    load: the signature is read in the scope that defines the function."""

    qualnames, names, _nested = _facts(
        tmp_path,
        """
def deco(fn):
    return fn


@deco
def target(deco=None):
    return deco
""",
    )
    assert "pkg.m:deco" in qualnames
    assert "deco" not in names


def test_global_nonlocal_comprehension_lambda_walrus_match_and_except_settle(
    tmp_path: Path,
) -> None:
    qualnames, names, _nested = _facts(
        tmp_path,
        """
counter = 0


def bump():
    global counter
    counter = counter + 1


def outer():
    x = 1

    def inner():
        nonlocal x
        return x

    return inner


def comprehension(items):
    return [i for i in items if i], (lambda y: y)(1), {k: v for k, v in items}


def walrus(source):
    if (n := len(source)):
        return n
    return 0


def matcher(value):
    match value:
        case [first, *rest]:
            return first, rest
        case {"key": found, **others}:
            return found, others
        case _:
            return None


def catcher():
    try:
        return 1
    except ValueError as error:
        return error
""",
    )
    settled_names = (
        "counter",
        "x",
        "i",
        "y",
        "k",
        "v",
        "n",
        "first",
        "rest",
        "found",
        "others",
        "error",
        "items",
        "source",
        "value",
    )
    for settled in settled_names:
        assert settled not in names, settled
    assert not any(qualname.endswith(":inner") for qualname in qualnames)


def test_an_internal_import_settles_and_an_external_one_stays_a_signal(
    tmp_path: Path,
) -> None:
    """Import settlement follows the registry: a name bound by a from-import
    the registry placed inside the root is answered by the imported-symbol
    lane; a name bound by an import it could not place keeps the signal,
    because a script-style sibling module is 'external' to the registry
    too. A plain ``import`` binds a module object and is settled outright."""

    qualnames, names, _nested = _facts(
        tmp_path,
        """
import json
from pkg.other import known
from unknown_sibling import stray


def run():
    return known(), stray(), json.dumps({})
""",
        extra={"pkg/other.py": "def known():\n    return 1\n"},
    )
    assert "pkg.other:known" in qualnames
    assert "known" not in names
    assert "stray" in names
    assert "json" not in names
    assert "dumps" in names


def test_a_star_import_leaves_an_unbound_load_a_signal(tmp_path: Path) -> None:
    _qualnames, names, _nested = _facts(
        tmp_path,
        """
from pkg.other import *


def run():
    return carried()
""",
        extra={"pkg/other.py": "def carried():\n    return 1\n"},
    )
    assert "carried" in names


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 syntax")
def test_a_type_alias_statement_binds_its_name_and_reads_its_value(
    tmp_path: Path,
) -> None:
    qualnames, names, _nested = _facts(
        tmp_path,
        """
class Helper:
    pass


type Alias[T] = list[Helper] | T
""",
    )
    assert "pkg.m:Helper" in qualnames
    assert "Alias" not in names
    assert "T" not in names


@pytest.mark.skipif(sys.version_info < (3, 11), reason="except* syntax")
def test_an_except_star_handler_binds_its_name(tmp_path: Path) -> None:
    _qualnames, names, _nested = _facts(
        tmp_path,
        """
def run():
    try:
        return 1
    except* ValueError as group:
        return group
""",
    )
    assert "group" not in names


def test_nested_discovery_spells_every_lexical_boundary(tmp_path: Path) -> None:
    """Acceptance 1 at the unit level: the population contract's fields."""

    _qualnames, _names, nested = _facts(
        tmp_path,
        """
def outer():
    def inner():
        def deep():
            return 1

        return deep

    class Local:
        def method(self):
            return 1

        class Inner:
            pass

    return inner, Local
""",
    )
    rows = {row.lexical_path: row for row in nested}
    assert set(rows) == {
        "outer.<locals>.inner",
        "outer.<locals>.inner.<locals>.deep",
        "outer.<locals>.Local",
        "outer.<locals>.Local.method",
        "outer.<locals>.Local.Inner",
    }
    assert rows["outer.<locals>.inner"].kind == "function"
    assert rows["outer.<locals>.inner"].lexical_parent == "pkg.m:outer"
    assert rows["outer.<locals>.inner.<locals>.deep"].lexical_parent == (
        "pkg.m:outer.<locals>.inner"
    )
    assert rows["outer.<locals>.Local"].kind == "class"
    assert rows["outer.<locals>.Local.method"].kind == "method"
    assert rows["outer.<locals>.Local.method"].lexical_parent == (
        "pkg.m:outer.<locals>.Local"
    )
    assert rows["outer.<locals>.Local.Inner"].kind == "class"
    assert all(row.qualname == f"pkg.m:{row.lexical_path}" for row in nested)
    assert all(row.start_line < row.end_line or row.kind != "class" for row in nested)


def test_the_nested_population_takes_no_protocol_member_and_no_overload_stub(
    tmp_path: Path,
) -> None:
    _qualnames, _names, nested = _facts(
        tmp_path,
        """
from typing import Protocol, overload


def outer():
    class Shape(Protocol):
        def area(self) -> int: ...

    @overload
    def convert(value: int) -> int: ...

    @overload
    def convert(value: str) -> str: ...

    def convert(value):
        return value

    return Shape, convert
""",
    )
    paths = [row.lexical_path for row in nested]
    assert "outer.<locals>.Shape" not in paths
    assert "outer.<locals>.Shape.area" not in paths
    assert paths.count("outer.<locals>.convert") == 1


# ---------------------------------------------------------------------------
# The decision table, over hand-built facts.
# ---------------------------------------------------------------------------


def _candidate(
    qualname: str, *, kind: str = "function", star: bool = False
) -> DeadCandidate:
    module, _, local = qualname.partition(":")
    return DeadCandidate(
        qualname=qualname,
        local_name=local.rpartition(".")[2],
        filepath=f"{module.replace('.', '/')}.py",
        start_line=1,
        end_line=2,
        kind=kind,  # type: ignore[arg-type]
        star_import_bound=star,
    )


def _nested(
    qualname: str, *, kind: str = "function", **facts: object
) -> NestedDefinition:
    module, _, path = qualname.partition(":")
    parent = (
        path.rsplit(".<locals>.", 1)[0] if kind != "method" else path.rsplit(".", 1)[0]
    )
    return NestedDefinition(
        qualname=qualname,
        local_name=path.rpartition(".")[2],
        kind=kind,  # type: ignore[arg-type]
        lexical_parent=f"{module}:{parent}",
        lexical_path=path,
        filepath=f"{module.replace('.', '/')}.py",
        start_line=3,
        end_line=4,
        **facts,  # type: ignore[arg-type]
    )


def _dep(source: str, target: str, *names: str) -> ModuleDep:
    return ModuleDep(
        source=source,
        target=target,
        import_type="from_import",
        line=1,
        resolution="analyzed",
        requested_names=names,
    )


def test_a_bare_name_abstains_in_both_worlds_and_a_binding_holds_live() -> None:
    """The three ratified rows, over one candidate."""

    helper = _candidate("pkg._m:helper")
    for world in ("open", "closed"):
        coincidence = classify_liveness(
            definitions=(helper,),
            referenced_names=frozenset({"helper"}),
            world_contract=world,
        )
        assert [item.qualname for item in coincidence.unresolved_internal] == [
            "pkg._m:helper"
        ]
        assert coincidence.dead_items == ()
        bound = classify_liveness(
            definitions=(helper,),
            referenced_names=frozenset({"helper"}),
            referenced_qualnames=frozenset({"pkg._m:helper"}),
            world_contract=world,
        )
        assert bound.unresolved_internal == () and bound.dead_items == ()
        unsupported = classify_liveness(
            definitions=(helper,),
            referenced_names=frozenset(),
            world_contract=world,
        )
        assert [item.qualname for item in unsupported.dead_items] == ["pkg._m:helper"]
        assert unsupported.dead_items[0].confidence == "high"


def test_the_binding_abstention_row_names_its_witness_or_is_refused() -> None:
    """The door on the row: both boundaries."""

    item = UnresolvedInternalItem(
        qualname="pkg.m:helper",
        filepath="pkg/m.py",
        start_line=1,
        end_line=2,
        kind="function",
        local_name="helper",
        witness=binding_witness("helper"),
    )
    assert item.witness == "bare_name_reference:helper"
    assert item.reason == "ambiguous_internal_binding"
    for wrong in ("", "helper", "public_module:pkg.m", "bare_name_reference:other"):
        with pytest.raises(LivenessVocabularyError):
            UnresolvedInternalItem(
                qualname="pkg.m:helper",
                filepath="pkg/m.py",
                start_line=1,
                end_line=2,
                kind="function",
                local_name="helper",
                witness=wrong,
            )


def test_the_nested_row_refuses_a_path_without_a_function_boundary() -> None:
    with pytest.raises(ValueError, match="<locals>"):
        NestedDefinition(
            qualname="pkg.m:Outer.inner",
            local_name="inner",
            kind="method",
            lexical_parent="pkg.m:Outer",
            lexical_path="Outer.inner",
            filepath="pkg/m.py",
            start_line=1,
            end_line=2,
        )
    with pytest.raises(ValueError, match="does not spell"):
        NestedDefinition(
            qualname="pkg.m:inner",
            local_name="inner",
            kind="function",
            lexical_parent="pkg.m:outer",
            lexical_path="outer.<locals>.inner",
            filepath="pkg/m.py",
            start_line=1,
            end_line=2,
        )


def test_a_nested_row_is_judged_by_the_same_table() -> None:
    """Hand-built nested facts through every row of the table."""

    unreferenced = _nested("pkg.m:outer.<locals>.helper")
    referenced = _nested("pkg.m:outer.<locals>.used")
    coincidence = _nested("pkg.m:outer.<locals>.close")
    rooted = _nested("pkg.m:outer.<locals>.hook", live_root_reason="external_decorator")
    dispatched = _nested(
        "pkg.m:outer.<locals>.Impl.paint", kind="method", self_dispatched=True
    )
    governed = _nested(
        "pkg.m:outer.<locals>.Impl.handle",
        kind="method",
        owner_base_names=("Base",),
        owner_has_unresolved_external_base=True,
    )
    evidenced = _nested(
        "pkg.m:outer.<locals>.Impl.render",
        kind="method",
        owner_base_names=("Base",),
        owner_has_unresolved_external_base=True,
        decorator_evidenced=True,
    )
    silenced = _nested("pkg.m:outer.<locals>.quiet", suppressed_rules=("dead-code",))
    dunder = _nested("pkg.m:outer.<locals>.Impl.__len__", kind="method")
    result = classify_liveness(
        definitions=(),
        referenced_names=frozenset({"close"}),
        referenced_qualnames=frozenset({"pkg.m:outer.<locals>.used"}),
        world_contract="open",
        nested_definitions=(
            unreferenced,
            referenced,
            coincidence,
            rooted,
            dispatched,
            governed,
            evidenced,
            silenced,
            dunder,
        ),
    )
    assert [item.qualname for item in result.dead_items] == [
        "pkg.m:outer.<locals>.helper"
    ]
    assert [item.qualname for item in result.unresolved_internal] == [
        "pkg.m:outer.<locals>.close"
    ]
    assert [
        (item.qualname, item.class_qualname, item.base_names)
        for item in result.unresolved_overrides
    ] == [("pkg.m:outer.<locals>.Impl.handle", "pkg.m:outer.<locals>.Impl", ("Base",))]
    # Nested rows never reach the reachability lane, whatever the world.
    assert result.unresolved_reachability == ()
    # The directive is what the suppressed lane reports.
    suppressed = find_suppressed_unused(
        definitions=(),
        referenced_names=frozenset(),
        nested_definitions=(silenced,),
    )
    assert [item.qualname for item in suppressed] == ["pkg.m:outer.<locals>.quiet"]


def test_a_nested_row_ignores_a_reachability_row_spelled_for_it() -> None:
    """Acceptance 6 at the evaluator's own door.

    The pipeline never hands the exposure owner a nested definition, so at
    the report level the row below cannot exist; the evaluator is a public
    function, and a caller that manufactured one must still get DEAD: no
    external namespace can spell a closure, whatever a row claims.
    """

    row = _nested("pkg.m:outer.<locals>.helper")
    result = classify_liveness(
        definitions=(),
        referenced_names=frozenset(),
        world_contract="open",
        nested_definitions=(row,),
        external_reachability=(
            ExternalReachability(
                "pkg.m:outer.<locals>.helper", "reachable", "public_module:pkg.m"
            ),
        ),
    )
    assert [item.qualname for item in result.dead_items] == [
        "pkg.m:outer.<locals>.helper"
    ]
    assert result.unresolved_reachability == ()


def test_a_reexport_hop_reaches_the_definition_or_leaves_a_signal() -> None:
    hops = resolve_reexport_hops(
        referenced_qualnames=frozenset(
            {
                "pkg:helper",  # one hop
                "pkg:deep",  # two hops
                "pkg:carried",  # star hop
                "pkg:CONSTANT",  # no definition anywhere
                "pkg.cycle_a:looped",  # a cycle that never lands
                "pkg._impl:helper",  # already a definition
            }
        ),
        definition_qualnames=frozenset(
            {"pkg._impl:helper", "pkg._deep:deep", "pkg._star:carried"}
        ),
        star_bound_qualnames=frozenset({"pkg._star:carried"}),
        module_deps=(
            _dep("pkg", "pkg._impl", "helper"),
            _dep("pkg", "pkg._mid", "deep"),
            _dep("pkg._mid", "pkg._deep", "deep"),
            _dep("pkg", "pkg._star", "*"),
            _dep("pkg.cycle_a", "pkg.cycle_b", "looped"),
            _dep("pkg.cycle_b", "pkg.cycle_a", "looped"),
        ),
    )
    assert hops.resolved == frozenset(
        {"pkg._impl:helper", "pkg._deep:deep", "pkg._star:carried"}
    )
    assert hops.dangling_names == frozenset({"CONSTANT", "looped"})


def test_a_definition_reached_only_through_a_reexport_hop_is_live() -> None:
    """The measured shape: ``bootstrap`` called through the package facade."""

    definition = _candidate("pkg.runtime:bootstrap")
    reached = classify_liveness(
        definitions=(definition,),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset({"pkg:bootstrap"}),
        module_deps=(_dep("pkg", "pkg.runtime", "bootstrap"),),
    )
    assert reached.dead_items == () and reached.unresolved_internal == ()
    unreached = classify_liveness(
        definitions=(definition,),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset({"pkg:bootstrap"}),
        module_deps=(),
    )
    # Without the edge the import target dangles: the name is a signal and
    # the symbol abstains rather than dies.
    assert [item.qualname for item in unreached.unresolved_internal] == [
        "pkg.runtime:bootstrap"
    ]


# ---------------------------------------------------------------------------
# The cache wire.
# ---------------------------------------------------------------------------


def test_the_nested_row_round_trips_the_wire_whole() -> None:
    row = _nested(
        "pkg.m:outer.<locals>.Impl.handle",
        kind="method",
        suppressed_rules=("dead-code",),
        live_root_reason="external_decorator",
        owner_base_names=("Base", "Mixin"),
        owner_has_unresolved_external_base=True,
        decorator_evidenced=True,
        self_dispatched=False,
    )
    encoded = _nested_definition_dict_from_model(row, "pkg/m.py")
    wire: dict[str, object] = {}
    _encode_nested_definitions(_facts_dict([encoded]), wire)
    rows = wire["nd"]
    assert isinstance(rows, list) and len(rows) == 1
    decoded = _decode_wire_nested_definition(rows[0], "pkg/m.py")
    assert decoded == encoded
    assert decoded is not None
    assert decoded["owner_base_names"] == ["Base", "Mixin"]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda row: row[:12], id="short-row"),
        pytest.param(lambda row: [*row[:2], "import", *row[3:]], id="unknown-kind"),
        pytest.param(
            lambda row: [*row[:8], "export_root_x", *row[9:]], id="unknown-reason"
        ),
        pytest.param(lambda row: [*row[:10], 1, *row[11:]], id="non-bool-flag"),
        pytest.param(
            lambda row: [*row[:7], "dead-code", *row[8:]], id="rules-not-a-list"
        ),
    ],
)
def test_a_malformed_nested_row_is_refused(mutate: object) -> None:
    wire: dict[str, object] = {}
    encoded = _nested_definition_dict_from_model(
        _nested("pkg.m:outer.<locals>.helper"), "pkg/m.py"
    )
    _encode_nested_definitions(_facts_dict([encoded]), wire)
    rows = wire["nd"]
    assert isinstance(rows, list)
    assert callable(mutate)
    assert _decode_wire_nested_definition(mutate(list(rows[0])), "pkg/m.py") is None


def test_an_empty_nested_population_writes_no_key() -> None:
    wire: dict[str, object] = {}
    _encode_nested_definitions(_facts_dict([]), wire)
    assert "nd" not in wire


def _facts_dict(rows: list[object]) -> CacheFactsDict:
    """The one key the encoder reads, typed as the facts dict it expects."""

    return cast("CacheFactsDict", {"nested_definitions": rows})

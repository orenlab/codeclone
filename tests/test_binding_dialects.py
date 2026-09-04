# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Two import dialects the binding owner used to lose, resolved once for all.

Measured on f8113038 + the liveness-policy-v4 delivery: of thirty symbols this
repository reports dead, seven read ``reason=unreferenced`` with an EMPTY
witness list while carrying real static test references. The witness lane
agreed with an independent resolver on the other twenty-three and returned
zero on exactly these seven - a blindness, not an under-count. Both causes are
binding dialects, and neither is a property of the consumer:

* ``from <pkg> import <submodule> as <alias>`` followed by ``alias.name``.
  ``import pkg._mod as alias`` bound the module and resolved; the ``from``
  spelling of the SAME binding wrote only the symbol reading, so the dotted
  use resolved to nothing. Lost in both lanes.
* a function-local ``from <module> import <name>``. The module walk records
  it, so ``referenced_qualnames`` sees it; the relationship index walks module
  scope only, so the alias reached the resolver as an opaque local binding and
  the witness lane lost it.

``DEAD / unreferenced / []`` reads as "nothing in the known world needs this"
and invites deletion; ``DEAD / test_only_reference / [tests/...]`` forces the
right question. Both carry the same production verdict, and the human decision
after them is not the same - so the evidence has to be right, not only the
verdict.

The rule these pins state: ONE resolver, ONE answer. The consumer's role
(``origin_lane``) is read AFTER resolution and never during it, so a
production consumer and a test consumer of the same construction resolve to
the same qualname. A fix that made the seven look right by special-casing the
test lane would hide the defect instead of closing it.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from codeclone.analysis import _module_walk as module_walk_mod
from codeclone.qualnames import QualnameCollector
from tests._ast_metrics_helpers import module_registry_context
from tests._liveness_report_helpers import dead_code_family, dead_qualnames

if TYPE_CHECKING:
    from pathlib import Path

    from codeclone.models import FunctionRelationshipFacts

_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f3c"

#: The registry the in-process pins resolve against: ``pkg`` is a package and
#: ``pkg._mod`` is one of its modules. ``pkg.helper`` deliberately is NOT a
#: module, which is what makes the negative boundary below measurable.
_INVENTORY = ("pkg", "pkg._mod")

_CLOSED = ("--dead-code-world", "closed")

#: The aliased-submodule dialect: the binding whose ``import`` spelling always
#: worked, written the other way.
_ALIAS_SUBMODULE_SOURCE = """
from pkg import _mod as alias


def consume() -> object:
    return alias.by_alias()
"""

#: The same binding in the spelling that always resolved. Not decoration: it
#: is what makes the pin above a statement about the DIALECT rather than about
#: the module.
_IMPORT_ALIAS_SOURCE = """
import pkg._mod as alias


def consume() -> object:
    return alias.by_alias()
"""

#: The function-local dialect.
_LOCAL_IMPORT_SOURCE = """
def consume() -> object:
    from pkg._mod import by_local

    return by_local()
"""

#: The same import at module scope - the spelling the relationship index
#: already read.
_MODULE_IMPORT_SOURCE = """
from pkg._mod import by_local


def consume() -> object:
    return by_local()
"""

#: Both dialects at once: the aliased submodule import written INSIDE a body.
#: One owner answers both halves, so this needs no rule of its own - which is
#: exactly the claim it pins.
_LOCAL_ALIAS_SUBMODULE_SOURCE = """
def consume() -> object:
    from pkg import _mod as alias

    return alias.by_alias()
"""

#: The negative boundary of the first dialect: ``pkg.helper`` is not a module
#: in the registry, so ``helper`` is an ordinary imported symbol and
#: ``helper.by_alias`` names no module member. A resolver that reads every
#: ``from`` import as a submodule INVENTS ``pkg.helper:by_alias`` here.
_NOT_A_SUBMODULE_SOURCE = """
from pkg import helper


def consume() -> object:
    return helper.by_alias()
"""

#: The negative boundary of the second dialect: the local import is rebound in
#: the same scope, so what the call reaches is not the imported symbol.
_LOCAL_IMPORT_SHADOWED_SOURCE = """
def consume(flag: bool) -> object:
    from pkg._mod import by_local

    if flag:
        by_local = len

    return by_local()
"""


def _walk(source: str, *, module_name: str = "consumer") -> object:
    identity, registry = module_registry_context(
        filepath=f"{module_name.replace('.', '/')}.py",
        module_name=module_name,
        inventory_modules=_INVENTORY,
    )
    tree = ast.parse(source.lstrip())
    collector = QualnameCollector()
    collector.visit(tree)
    return module_walk_mod._collect_module_walk_data(
        tree=tree,
        source=identity,
        registry=registry,
        collector=collector,
        collect_referenced_names=True,
    )


def _relationships(
    source: str,
    *,
    origin_lane: str = "test",
    module_name: str = "consumer",
) -> tuple[FunctionRelationshipFacts, ...]:
    identity, registry = module_registry_context(
        filepath=f"{module_name.replace('.', '/')}.py",
        module_name=module_name,
        inventory_modules=_INVENTORY,
    )
    tree = ast.parse(source.lstrip())
    collector = QualnameCollector()
    collector.visit(tree)
    return module_walk_mod._collect_function_relationship_facts(
        tree=tree,
        source=identity,
        registry=registry,
        filepath=f"{module_name.replace('.', '/')}.py",
        collector=collector,
        origin_lane=origin_lane,  # type: ignore[arg-type]
    )


def _resolved_targets(facts: tuple[FunctionRelationshipFacts, ...]) -> set[str]:
    return {
        relationship.target_qualname
        for fact in facts
        for relationship in fact.relationships
        if relationship.target_qualname is not None
    }


def _resolution_rules(facts: tuple[FunctionRelationshipFacts, ...]) -> set[str]:
    return {
        relationship.resolution_rule or ""
        for fact in facts
        for relationship in fact.relationships
    }


# ---------------------------------------------------------------------------
# Dialect 1: ``from <pkg> import <submodule> as <alias>``.
# ---------------------------------------------------------------------------


def test_an_aliased_submodule_import_binds_a_module_in_the_qualname_lane() -> None:
    """The reference lane. ``alias`` denotes ``pkg._mod``, so ``alias.by_alias``
    is a use of ``pkg._mod:by_alias`` - the same use the ``import`` spelling of
    the identical binding has always recorded."""

    aliased = _walk(_ALIAS_SUBMODULE_SOURCE)
    plain = _walk(_IMPORT_ALIAS_SOURCE)

    assert "pkg._mod:by_alias" in aliased.referenced_qualnames  # type: ignore[attr-defined]
    # The spelling that already worked, as the control: one answer, two
    # spellings of one binding.
    assert "pkg._mod:by_alias" in plain.referenced_qualnames  # type: ignore[attr-defined]
    # The symbol reading of the same import survives: ``pkg`` really does bind
    # the name ``_mod``, and that fact is not replaced by the module reading.
    assert "pkg:_mod" in aliased.referenced_qualnames  # type: ignore[attr-defined]


def test_an_aliased_submodule_import_binds_a_module_in_the_witness_lane() -> None:
    """The witness lane, on the same construction. This is the half that
    decides whether a dead symbol is reported with its consumers named."""

    facts = _relationships(_ALIAS_SUBMODULE_SOURCE)

    assert _resolved_targets(facts) == {"pkg._mod:by_alias"}
    assert "imported_module_attribute" in _resolution_rules(facts)


def test_the_two_lanes_agree_on_the_aliased_submodule_dialect() -> None:
    """One resolver, one answer. The lanes are allowed to ask different
    questions; they are not allowed to disagree about what a name binds."""

    walk = _walk(_ALIAS_SUBMODULE_SOURCE)
    facts = _relationships(_ALIAS_SUBMODULE_SOURCE)
    resolved = _resolved_targets(facts)

    # Non-empty first: an empty set is a subset of everything, so agreement
    # asserted on its own would be green while both lanes resolved nothing.
    assert resolved == {"pkg._mod:by_alias"}
    assert resolved <= set(walk.referenced_qualnames)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Dialect 2: a function-local ``from <module> import <name>``.
# ---------------------------------------------------------------------------


def test_a_function_local_from_import_resolves_in_the_witness_lane() -> None:
    """The relationship index walks module scope only, so this binding used to
    reach the resolver as an opaque local name. The module walk has always
    recorded it, which is why only the witness lane lost the reference."""

    local = _relationships(_LOCAL_IMPORT_SOURCE)
    module_scope = _relationships(_MODULE_IMPORT_SOURCE)

    assert _resolved_targets(local) == {"pkg._mod:by_local"}
    assert _resolved_targets(module_scope) == {"pkg._mod:by_local"}
    assert "imported_symbol" in _resolution_rules(local)


def test_the_two_lanes_agree_on_the_function_local_dialect() -> None:
    walk = _walk(_LOCAL_IMPORT_SOURCE)
    facts = _relationships(_LOCAL_IMPORT_SOURCE)
    resolved = _resolved_targets(facts)

    assert "pkg._mod:by_local" in walk.referenced_qualnames  # type: ignore[attr-defined]
    assert resolved == {"pkg._mod:by_local"}
    assert resolved <= set(walk.referenced_qualnames)  # type: ignore[attr-defined]


def test_the_two_dialects_compose_without_a_rule_of_their_own() -> None:
    """An aliased submodule import written inside a function body. Neither
    dialect knows about the other; one binding owner answers both, which is
    what makes the fix a resolver change rather than two special cases."""

    facts = _relationships(_LOCAL_ALIAS_SUBMODULE_SOURCE)

    assert _resolved_targets(facts) == {"pkg._mod:by_alias"}
    assert "imported_module_attribute" in _resolution_rules(facts)


# ---------------------------------------------------------------------------
# The opposite boundary: a resolver that invents a reference is not a fix.
# ---------------------------------------------------------------------------


def test_a_from_import_of_a_non_module_binds_no_module() -> None:
    """``pkg.helper`` is not a module. Reading every ``from`` import as a
    submodule would manufacture ``pkg.helper:by_alias`` - a reference to a
    module that does not exist, which on a real tree can revive a symbol
    nothing binds. The registry decides, not the syntax."""

    walk = _walk(_NOT_A_SUBMODULE_SOURCE)
    facts = _relationships(_NOT_A_SUBMODULE_SOURCE)

    assert "pkg:helper" in walk.referenced_qualnames  # type: ignore[attr-defined]
    assert not [
        qualname
        for qualname in walk.referenced_qualnames  # type: ignore[attr-defined]
        if qualname.startswith("pkg.helper:")
    ]
    assert _resolved_targets(facts) == set()


def test_a_rebound_function_local_import_resolves_to_nothing() -> None:
    """The local import is not what the call reaches: the name is assigned
    again in the same scope. Resolving it anyway would name a consumer that
    does not exist."""

    facts = _relationships(_LOCAL_IMPORT_SHADOWED_SOURCE)

    assert _resolved_targets(facts) == set()


# ---------------------------------------------------------------------------
# Role independence: the consumer's lane is read after resolution.
# ---------------------------------------------------------------------------


def test_both_dialects_resolve_identically_for_production_and_test_consumers() -> None:
    """The ruling, executable. ``origin_lane`` is the ONLY field allowed to
    differ between a production consumer and a test consumer of the same
    source; a resolver that answered differently for a test would make the
    seven look right while staying blind."""

    for source in (
        _ALIAS_SUBMODULE_SOURCE,
        _LOCAL_IMPORT_SOURCE,
        _LOCAL_ALIAS_SUBMODULE_SOURCE,
        _NOT_A_SUBMODULE_SOURCE,
        _LOCAL_IMPORT_SHADOWED_SOURCE,
    ):
        production = _relationships(source, origin_lane="production")
        test = _relationships(source, origin_lane="test")

        assert [
            (fact.source_qualname, tuple(sorted(_resolved_targets((fact,)))))
            for fact in production
        ] == [
            (fact.source_qualname, tuple(sorted(_resolved_targets((fact,)))))
            for fact in test
        ], source
        assert {
            relationship.origin_lane
            for fact in production
            for relationship in fact.relationships
        } == {"production"}
        assert {
            relationship.origin_lane
            for fact in test
            for relationship in fact.relationships
        } == {"test"}


# ---------------------------------------------------------------------------
# The wire: what a user reads about a dead symbol's consumers.
# ---------------------------------------------------------------------------

#: One tree, four symbols, one run. ``by_alias`` and ``by_local`` are reached
#: only through the two dialects; ``by_plain`` is reached through the spelling
#: that always resolved (the control that the witness lane fires at all); and
#: ``_orphan`` is reached by nothing (the control that it does not fire for
#: everything, so a named witness is evidence rather than decoration).
_DIALECT_TREE = {
    "pkg/__init__.py": "",
    "pkg/_mod.py": """
def by_alias() -> int:
    return 1


def by_local() -> int:
    return 2


def by_plain() -> int:
    return 3


def _orphan() -> int:
    return 4
""",
    "tests/test_dialects.py": """
from pkg import _mod as alias
from pkg._mod import by_plain


def test_through_an_aliased_submodule() -> None:
    assert alias.by_alias() == 1


def test_through_a_function_local_import() -> None:
    from pkg._mod import by_local

    assert by_local() == 2


def test_through_a_module_scope_import() -> None:
    assert by_plain() == 3
""",
}


def test_both_dialects_name_their_test_consumers_on_the_wire(tmp_path: Path) -> None:
    """The defect as a user reads it. All four symbols are dead - production
    binds none of them - and that verdict is not what changed. What changed is
    the evidence: a symbol a test reaches is reported with the test that
    reaches it, whichever of the three spellings the test used, and a symbol
    nothing reaches keeps an empty witness list."""

    family = dead_code_family(
        tmp_path, _DIALECT_TREE, "dialects", scope_id=_SCOPE_ID, cli_args=_CLOSED
    )
    items = family["items"]
    assert isinstance(items, list)

    assert dead_qualnames(family) == {
        "pkg._mod:by_alias",
        "pkg._mod:by_local",
        "pkg._mod:by_plain",
        "pkg._mod:_orphan",
    }
    assert {
        str(item["qualname"]): (
            item["reason"],
            tuple(item["test_reference_sources"]),
        )
        for item in items
    } == {
        "pkg._mod:by_alias": (
            "test_only_reference",
            ("tests.test_dialects:test_through_an_aliased_submodule",),
        ),
        "pkg._mod:by_local": (
            "test_only_reference",
            ("tests.test_dialects:test_through_a_function_local_import",),
        ),
        "pkg._mod:by_plain": (
            "test_only_reference",
            ("tests.test_dialects:test_through_a_module_scope_import",),
        ),
        "pkg._mod:_orphan": ("unreferenced", ()),
    }

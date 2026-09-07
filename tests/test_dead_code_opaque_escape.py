# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Opaque internal escape (liveness policy v5, the same unreleased generation).

A proven false verdict of Definition Liveness, measured on this repository at
5f35a50f: eight resource handlers in ``codeclone/surfaces/mcp/server.py``
are decorated with a bare ``@resource(...)`` whose name binds to a
function-local ``def resource`` that hands the decorated function to
``mcp.resource(...)`` - a callable the analyzer cannot resolve to any
definition - and the lane reported them DEAD. The counterexample, as ratified:

    definition -> decorator application -> local higher-order registrar
               -> function value escapes -> opaque runtime callable
               -> actual runtime use exists

The rule does not prove such a symbol LIVE. It proves DEAD may no longer be
asserted:

    decorated definition
    + the innermost decorator lexically resolves to a local callable
    + the decorated value provably flows into an opaque callable
    + the analyzer cannot establish what that consumer does
    -------------------------------------------------------------
    DEAD is forbidden  ->  UNRESOLVED (``unresolved_internal``,
                           ``opaque_internal_escape``), in BOTH worlds

World-invariant because the uncertainty is inside the observed program: the
value left into opaque semantics, and no world contract can dissolve that.

The rule fires on PROVEN flow only. A registrar the analyzer cannot follow -
a conditional around the registration, two returns, a re-assigned parameter -
leaves the symbol DEAD, because "when in doubt, abstain" would erode the dead
lane under cover of safety. And a registrar that passes the value to a
consumer the analyzer CAN resolve - a same-module function, an internal
import - leaves it DEAD too, or "opaque" would be a blanket amnesty. Both
boundaries are pinned here under different tests, each beside the row it
must not be confused with.

Every report-level pin spawns the CLI (``tests/_liveness_report_helpers``);
every LIVE-or-abstained nested verdict is paired with the control that puts
the same symbol in the dead lane, which is what proves it was measured at
all: the nested population has no presence witness in the complexity family.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import cast

import pytest

from codeclone.cache._wire_decode import (
    _decode_wire_escape_witness,
    _decode_wire_nested_definition,
)
from codeclone.cache._wire_encode import (
    _encode_dead_candidates,
    _encode_nested_definitions,
)
from codeclone.cache.entries import (
    _dead_candidate_dict_from_model,
    _nested_definition_dict_from_model,
)
from codeclone.core.discovery_cache import (
    _dead_candidate_from_cache_row,
    _nested_definition_from_cache_row,
)
from codeclone.metrics.dead_code import classify_liveness
from codeclone.models import (
    MECHANISMS,
    CacheFactsDict,
    DeadCandidate,
    ExternalReachability,
    LivenessVocabularyError,
    NestedDefinition,
    UnresolvedInternalItem,
    binding_witness,
    escape_witness,
    validate_escape_witness,
)
from tests._ast_metrics_helpers import build_test_module_registry, extract_file_metrics
from tests._liveness_report_helpers import (
    VERDICT_DEAD,
    VERDICT_UNRESOLVED,
    analysis_report,
    dead_code_family_of,
    dead_qualnames,
    liveness_verdict,
    unresolved_by_qualname,
    unresolved_override_by_qualname,
)

_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f47"
_CLOSED = ("--dead-code-world", "closed")
_WORLDS = (("open", ()), ("closed", _CLOSED))

_LANE = "unresolved_internal"
_REASON = "opaque_internal_escape"

# ---------------------------------------------------------------------------
# The fixture tree. Every module is PRIVATE, so external reachability can
# separate nothing here and the two worlds may differ only through the rule.
# ---------------------------------------------------------------------------

#: The counterexample itself, nested (acceptance 1) and module-level
#: (acceptance 2), each beside a local decorator that passes the value
#: nowhere (acceptance 3, in the call form and in the bare form).
_ESCAPE_TREE = {
    "pkg/__init__.py": "",
    "pkg/_runtime.py": """
from typing import Any


def load() -> Any:
    return object()
""",
    "pkg/_nested.py": """
from ._runtime import load


def build_server():
    mcp = load()

    def resource(uri):
        decorator = mcp.resource(uri)

        def register(func):
            decorator(func)
            return func

        return register

    def marker(uri):
        def register(func):
            return func

        return register

    def tag(func):
        return func

    @resource("codeclone://escaped")
    def nested_escaped() -> str:
        return "escaped"

    @marker("codeclone://marked")
    def nested_marked_only() -> str:
        return "marked"

    @tag
    def nested_tagged_only() -> str:
        return "tagged"
""",
    "pkg/_module.py": """
from ._runtime import load

_mcp = load()


def resource(uri):
    decorator = _mcp.resource(uri)

    def register(func):
        decorator(func)
        return func

    return register


def marker(uri):
    def register(func):
        return func

    return register


@resource("codeclone://module")
def module_escaped() -> str:
    return "module"


@marker("codeclone://module-marked")
def module_marked_only() -> str:
    return "marked"
""",
    "pkg/entry.py": """
from ._nested import build_server


def run():
    return build_server()
""",
}

_NESTED_ESCAPED = "pkg._nested:build_server.<locals>.nested_escaped"
_NESTED_MARKED = "pkg._nested:build_server.<locals>.nested_marked_only"
_NESTED_TAGGED = "pkg._nested:build_server.<locals>.nested_tagged_only"
_MODULE_ESCAPED = "pkg._module:module_escaped"
_MODULE_MARKED = "pkg._module:module_marked_only"

_NESTED_WITNESS = (
    "@resource(...) -> local build_server.<locals>.resource"
    " -> parameter func -> opaque call mcp.resource(...)"
)
_MODULE_WITNESS = (
    "@resource(...) -> local resource -> parameter func"
    " -> opaque call _mcp.resource(...)"
)


def _rows(family: dict[str, object], lane: str) -> dict[str, dict[str, object]]:
    rows = family[lane]
    assert isinstance(rows, list)
    by_qualname: dict[str, dict[str, object]] = {}
    for row in rows:
        assert isinstance(row, dict)
        by_qualname[str(row["qualname"])] = dict(row)
    return by_qualname


def _nested_verdict(family: dict[str, object], qualname: str) -> str:
    """A nested symbol's verdict; LIVE is an absence, so callers pair it."""

    if qualname in dead_qualnames(family):
        return VERDICT_DEAD
    if qualname in _rows(family, _LANE) or qualname in unresolved_by_qualname(family):
        return VERDICT_UNRESOLVED
    if qualname in unresolved_override_by_qualname(family):
        return "unresolved_override"
    return "live"


def _summary(family: dict[str, object]) -> dict[str, object]:
    summary = family["summary"]
    assert isinstance(summary, dict)
    return summary


@pytest.fixture(scope="module")
def escape_reports(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, dict[str, object]]:
    root = tmp_path_factory.mktemp("escape")
    return {
        world: analysis_report(
            root, _ESCAPE_TREE, f"escape-{world}", scope_id=_SCOPE_ID, cli_args=args
        )
        for world, args in _WORLDS
    }


# ---------------------------------------------------------------------------
# Acceptance 1 and 2: the counterexample abstains, nested and module-level,
# in both worlds, with the proven flow as its witness.
# ---------------------------------------------------------------------------


def test_the_nested_counterexample_is_unresolved_internal_in_both_worlds(
    escape_reports: dict[str, dict[str, object]],
) -> None:
    """Acceptance 1: a real local registrar with proven flow into an opaque
    callable forbids DEAD. The verdict is read first, so a run that still
    calls the symbol dead reds on the verdict and not on a missing lane."""

    for world in ("open", "closed"):
        family = dead_code_family_of(escape_reports[world])
        assert _NESTED_ESCAPED not in dead_qualnames(family), world
        assert _nested_verdict(family, _NESTED_ESCAPED) == VERDICT_UNRESOLVED, world
        row = _rows(family, _LANE)[_NESTED_ESCAPED]
        assert {key: row[key] for key in ("reason", "local_name", "witness")} == {
            "reason": _REASON,
            "local_name": "nested_escaped",
            "witness": _NESTED_WITNESS,
        }
        # Its own lane: neither the world-dependent one nor rule 3.
        assert _NESTED_ESCAPED not in unresolved_by_qualname(family)
        assert _NESTED_ESCAPED not in unresolved_override_by_qualname(family)


def test_the_module_level_counterexample_gets_the_identical_verdict(
    escape_reports: dict[str, dict[str, object]],
) -> None:
    """Acceptance 2: the same pattern at module level - the same lane, the
    same reason, and a witness naming the module-level registrar."""

    for world in ("open", "closed"):
        payload = escape_reports[world]
        assert liveness_verdict(payload, _MODULE_ESCAPED) == VERDICT_UNRESOLVED, world
        family = dead_code_family_of(payload)
        row = _rows(family, _LANE)[_MODULE_ESCAPED]
        assert {key: row[key] for key in ("reason", "local_name", "witness")} == {
            "reason": _REASON,
            "local_name": "module_escaped",
            "witness": _MODULE_WITNESS,
        }
        assert _MODULE_ESCAPED not in unresolved_by_qualname(family)


def test_the_lane_is_world_invariant_row_for_row(
    escape_reports: dict[str, dict[str, object]],
) -> None:
    """open.unresolved_internal == closed.unresolved_internal, as rows."""

    open_family = dead_code_family_of(escape_reports["open"])
    closed_family = dead_code_family_of(escape_reports["closed"])
    open_rows, closed_rows = open_family[_LANE], closed_family[_LANE]
    assert isinstance(open_rows, list) and isinstance(closed_rows, list)
    assert open_rows == closed_rows
    assert _summary(open_family)[_LANE] == _summary(closed_family)[_LANE]
    assert _summary(open_family)[_LANE] == len(open_rows)


# ---------------------------------------------------------------------------
# Acceptance 3: a local decorator that passes the value nowhere does not fire.
# ---------------------------------------------------------------------------


def test_a_local_decorator_that_passes_the_value_nowhere_leaves_the_symbol_dead(
    escape_reports: dict[str, dict[str, object]],
) -> None:
    """The siblings of the counterexample that differ ONLY in the flow: the
    call-form registrar whose inner function returns the value untouched,
    and the bare-form identity decorator. Dead in both worlds, both lexical
    depths."""

    for world in ("open", "closed"):
        payload = escape_reports[world]
        family = dead_code_family_of(payload)
        assert _nested_verdict(family, _NESTED_MARKED) == VERDICT_DEAD, world
        assert _nested_verdict(family, _NESTED_TAGGED) == VERDICT_DEAD, world
        assert liveness_verdict(payload, _MODULE_MARKED) == VERDICT_DEAD, world
        assert not {_NESTED_MARKED, _NESTED_TAGGED, _MODULE_MARKED} & set(
            _rows(family, _LANE)
        )


# ---------------------------------------------------------------------------
# Acceptance 5: removing the escape flow kills the verdict.
# ---------------------------------------------------------------------------


def test_removing_the_one_flow_statement_collapses_the_symbol_onto_dead(
    tmp_path: Path,
) -> None:
    """The positive control on the rule's own causal path: the SAME tree with
    ``decorator(func)`` deleted from both registrars reports both symbols dead
    in both worlds. This is also the presence witness for the nested row."""

    without_flow = dict(_ESCAPE_TREE)
    without_flow["pkg/_nested.py"] = _ESCAPE_TREE["pkg/_nested.py"].replace(
        "            decorator(func)\n", ""
    )
    without_flow["pkg/_module.py"] = _ESCAPE_TREE["pkg/_module.py"].replace(
        "        decorator(func)\n", ""
    )
    assert without_flow["pkg/_nested.py"] != _ESCAPE_TREE["pkg/_nested.py"]
    assert without_flow["pkg/_module.py"] != _ESCAPE_TREE["pkg/_module.py"]
    for world, args in _WORLDS:
        payload = analysis_report(
            tmp_path,
            without_flow,
            f"no-flow-{world}",
            scope_id=_SCOPE_ID,
            cli_args=args,
        )
        family = dead_code_family_of(payload)
        assert _nested_verdict(family, _NESTED_ESCAPED) == VERDICT_DEAD, world
        assert liveness_verdict(payload, _MODULE_ESCAPED) == VERDICT_DEAD, world
        assert _rows(family, _LANE) == {}


# ---------------------------------------------------------------------------
# Acceptance 4: a same-named ``.resource()`` by coincidence does not fire.
# The rule keys on the BINDING of the decorator's name, never on the name.
# ---------------------------------------------------------------------------

_COINCIDENCE_TREE = {
    "pkg/__init__.py": "",
    "pkg/_runtime.py": _ESCAPE_TREE["pkg/_runtime.py"],
    "pkg/_coincidence.py": """
from typing import Any

from ._runtime import load

_mcp = load()


class Other:
    def resource(self, uri: str) -> Any:
        return uri


_other = Other()


def resource(uri):
    decorator = _mcp.resource(uri)

    def register(func):
        decorator(func)
        return func

    return register


@resource("codeclone://real")
def real_escaped() -> str:
    return "real"


@_other.resource("codeclone://coincidence")
def attribute_coincidence() -> str:
    return "coincidence"


def build(resource):
    @resource("codeclone://shadowed")
    def parameter_coincidence() -> str:
        return "shadowed"

    return None
""",
}

_ATTRIBUTE_COINCIDENCE = "pkg._coincidence:attribute_coincidence"
_PARAMETER_COINCIDENCE = "pkg._coincidence:build.<locals>.parameter_coincidence"
_REAL_ESCAPED = "pkg._coincidence:real_escaped"
_OTHER_RESOURCE = "pkg._coincidence:Other.resource"


def test_a_same_named_resource_by_coincidence_does_not_fire(tmp_path: Path) -> None:
    """The rule keys on the BINDING of the decorator's name, never on the name.

    One module holds a real escaping registrar ``resource`` and two symbols
    decorated through a same-spelled name that does NOT bind to it: an
    unrelated object's ``.resource`` method (the decorator's root is an
    attribute), and a PARAMETER spelled ``resource`` that shadows the
    registrar inside ``build``. Both stay dead in both worlds while the
    symbol decorated through the real binding abstains - the positive
    control that the registrar in this module is a working one, so the two
    dead verdicts are the binding's doing and not the module's.

    The unrelated method itself lands in the lane as a bare-name coincidence
    (``_other.resource(...)`` loads the name against an unknown receiver);
    read whole so the two reasons stay visibly distinct.
    """

    for world, args in _WORLDS:
        payload = analysis_report(
            tmp_path,
            _COINCIDENCE_TREE,
            f"coincidence-{world}",
            scope_id=_SCOPE_ID,
            cli_args=args,
        )
        family = dead_code_family_of(payload)
        assert liveness_verdict(payload, _ATTRIBUTE_COINCIDENCE) == VERDICT_DEAD, world
        assert _nested_verdict(family, _PARAMETER_COINCIDENCE) == VERDICT_DEAD, world
        assert liveness_verdict(payload, _REAL_ESCAPED) == VERDICT_UNRESOLVED, world
        rows = _rows(family, _LANE)
        assert {qualname: row["reason"] for qualname, row in rows.items()} == {
            _REAL_ESCAPED: _REASON,
            _OTHER_RESOURCE: "ambiguous_internal_binding",
        }, world


# ---------------------------------------------------------------------------
# Acceptance 8: absence of proof means the rule does NOT fire.
# ---------------------------------------------------------------------------

#: Three registrars deliberately too complex for the bounded proof: the
#: registration behind a conditional, a registrar with two returns, and a
#: parameter re-assigned before the registration. Each symbol stays DEAD.
_COMPLEX_TREE = {
    "pkg/__init__.py": "",
    "pkg/_runtime.py": _ESCAPE_TREE["pkg/_runtime.py"],
    "pkg/_complex.py": """
from ._runtime import load

_mcp = load()


def conditional(uri):
    decorator = _mcp.resource(uri)

    def register(func):
        if uri:
            decorator(func)
        return func

    return register


def two_returns(uri):
    decorator = _mcp.resource(uri)

    def register(func):
        decorator(func)
        return func

    def other(func):
        return func

    if uri:
        return other
    return register


def rebound(uri):
    decorator = _mcp.resource(uri)

    def register(func):
        func = _wrap(func)
        decorator(func)
        return func

    return register


def _wrap(func):
    return func


@conditional("codeclone://conditional")
def conditional_registration() -> str:
    return "conditional"


@two_returns("codeclone://two-returns")
def two_return_registrar() -> str:
    return "two"


@rebound("codeclone://rebound")
def rebound_parameter() -> str:
    return "rebound"
""",
}

_CONDITIONAL = "pkg._complex:conditional_registration"
_TWO_RETURNS = "pkg._complex:two_return_registrar"
_REBOUND = "pkg._complex:rebound_parameter"


@pytest.mark.parametrize(
    "qualname",
    [
        pytest.param(_CONDITIONAL, id="registration-behind-a-conditional"),
        pytest.param(_TWO_RETURNS, id="registrar-with-two-returns"),
        pytest.param(_REBOUND, id="parameter-reassigned-before-registration"),
    ],
)
def test_a_registrar_the_proof_cannot_follow_leaves_the_symbol_dead(
    tmp_path: Path, qualname: str
) -> None:
    for world, args in _WORLDS:
        payload = analysis_report(
            tmp_path,
            _COMPLEX_TREE,
            f"complex-{world}",
            scope_id=_SCOPE_ID,
            cli_args=args,
        )
        assert liveness_verdict(payload, qualname) == VERDICT_DEAD, world
        assert qualname not in _rows(dead_code_family_of(payload), _LANE)


# ---------------------------------------------------------------------------
# Acceptance 9: the opposite boundary - a consumer the analyzer CAN resolve.
# ---------------------------------------------------------------------------

_RESOLVABLE_TREE = {
    "pkg/__init__.py": "",
    "pkg/_registry.py": """
def store(func):
    return func
""",
    "pkg/_resolvable.py": """
from ._registry import store

_REGISTRY = []


def _keep(func):
    _REGISTRY.append(func)


def kept(uri):
    def register(func):
        _keep(func)
        return func

    return register


def stored(uri):
    def register(func):
        store(func)
        return func

    return register


@kept("codeclone://kept")
def local_consumer() -> str:
    return "kept"


@stored("codeclone://stored")
def imported_consumer() -> str:
    return "stored"
""",
}

_LOCAL_CONSUMER = "pkg._resolvable:local_consumer"
_IMPORTED_CONSUMER = "pkg._resolvable:imported_consumer"


@pytest.mark.parametrize(
    "qualname",
    [
        pytest.param(_LOCAL_CONSUMER, id="same-module-function-consumer"),
        pytest.param(_IMPORTED_CONSUMER, id="internal-import-consumer"),
    ],
)
def test_a_registrar_that_hands_the_value_to_a_resolvable_consumer_leaves_it_dead(
    tmp_path: Path, qualname: str
) -> None:
    """The registrar DOES pass the value on - to a same-module function, to
    an internal import - and the analyzer can see both. Not opaque, so not an
    amnesty: dead in both worlds."""

    for world, args in _WORLDS:
        payload = analysis_report(
            tmp_path,
            _RESOLVABLE_TREE,
            f"resolvable-{world}",
            scope_id=_SCOPE_ID,
            cli_args=args,
        )
        assert liveness_verdict(payload, qualname) == VERDICT_DEAD, world
        assert qualname not in _rows(dead_code_family_of(payload), _LANE)


# ---------------------------------------------------------------------------
# Acceptance 6: warm equals cold under the v5 dependent lane.
# ---------------------------------------------------------------------------


def test_warm_cache_equals_cold_for_the_escape_lane(tmp_path: Path) -> None:
    """The witness rides the dependent cache lane whole, for both populations:
    a warm run reads the module-level row's sidecar and the nested row's field
    and reaches the same verdicts, row for row."""

    cold = dead_code_family_of(
        analysis_report(tmp_path, _ESCAPE_TREE, "escape-warm", scope_id=_SCOPE_ID)
    )
    warm = dead_code_family_of(
        analysis_report(
            tmp_path,
            _ESCAPE_TREE,
            "escape-warm",
            scope_id=_SCOPE_ID,
            expect_warm_cache=True,
        )
    )
    for lane in ("items", "unresolved", _LANE, "unresolved_overrides"):
        assert warm[lane] == cold[lane], lane
    assert _summary(warm) == _summary(cold)
    assert set(_rows(warm, _LANE)) >= {_NESTED_ESCAPED, _MODULE_ESCAPED}


# ---------------------------------------------------------------------------
# The producer: the witness is a per-symbol fact of the walk, on both rows.
# ---------------------------------------------------------------------------


def _walk(root: Path, tree: dict[str, str]) -> dict[str, object]:
    """The real per-file walk over the tree; every module's metrics by path."""

    root.mkdir(parents=True, exist_ok=True)
    for name, source in tree.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.lstrip(), encoding="utf-8")
    registry = build_test_module_registry(root=root)
    return {
        name: extract_file_metrics(
            source=(root / name).read_text(encoding="utf-8"),
            filepath=name,
            module_registry=registry,
        )
        for name in tree
        if name.endswith(".py")
    }


def test_the_walk_carries_the_witness_on_both_populations(tmp_path: Path) -> None:
    """The witness is produced by the walk and rides the row: the nested
    ``NestedDefinition`` and the module-level ``DeadCandidate`` each carry
    exactly the proven flow, and the no-flow siblings carry nothing."""

    metrics = _walk(tmp_path / "walk", _ESCAPE_TREE)
    nested = metrics["pkg/_nested.py"]
    module = metrics["pkg/_module.py"]
    nested_rows = {row.qualname: row for row in nested.nested_definitions}  # type: ignore[attr-defined]
    assert nested_rows[_NESTED_ESCAPED].escape_witness == _NESTED_WITNESS
    assert nested_rows[_NESTED_MARKED].escape_witness is None
    assert nested_rows[_NESTED_TAGGED].escape_witness is None
    candidates = {row.qualname: row for row in module.dead_candidates}  # type: ignore[attr-defined]
    assert candidates[_MODULE_ESCAPED].escape_witness == _MODULE_WITNESS
    assert candidates[_MODULE_MARKED].escape_witness is None
    # The registrars themselves carry nothing: a witness is about the value
    # that was decorated, and nothing decorates them.
    assert candidates["pkg._module:resource"].escape_witness is None


def test_the_mechanism_names_the_walk_producer() -> None:
    spec = MECHANISMS["opaque_internal_escape"]
    assert spec.status == "active"
    assert spec.producer == (
        "codeclone.analysis._module_walk:_collect_opaque_escape_witnesses"
    )
    assert spec.witness_type == "abstention_record"


# ---------------------------------------------------------------------------
# The evaluator: where the escape row sits in the decision table.
# ---------------------------------------------------------------------------


def _candidate(qualname: str, *, witness: str | None = None) -> DeadCandidate:
    module, _, local = qualname.partition(":")
    return DeadCandidate(
        qualname=qualname,
        local_name=local.rpartition(".")[2],
        filepath=f"{module.replace('.', '/')}.py",
        start_line=1,
        end_line=2,
        kind="function",
        escape_witness=witness,
    )


_WITNESS = escape_witness("resource(...)", "resource", "func", "mcp.resource")


def test_the_escape_row_outranks_the_bare_name_coincidence() -> None:
    """A proven flow is the more specific fact: with both a witness and a
    bare-name load, the row says ``opaque_internal_escape``; with only the
    load, ``ambiguous_internal_binding``. Same lane either way."""

    with_flow = classify_liveness(
        definitions=(_candidate("pkg._m:handler", witness=_WITNESS),),
        referenced_names=frozenset({"handler"}),
    )
    assert [(item.reason, item.witness) for item in with_flow.unresolved_internal] == [
        ("opaque_internal_escape", _WITNESS)
    ]
    coincidence_only = classify_liveness(
        definitions=(_candidate("pkg._m:handler"),),
        referenced_names=frozenset({"handler"}),
    )
    assert [
        (item.reason, item.witness) for item in coincidence_only.unresolved_internal
    ] == [("ambiguous_internal_binding", binding_witness("handler"))]
    assert with_flow.dead_items == () and coincidence_only.dead_items == ()


def test_the_escape_row_outranks_external_reachability_under_the_open_world() -> None:
    """The lane is world-invariant, so an open-world external abstention may
    not displace it: a reachable public symbol with a witness is
    ``unresolved_internal`` under BOTH worlds, and its twin without the
    witness is ``unresolved`` under open and dead under closed."""

    reachable = (
        ExternalReachability(
            qualname="pkg.core:handler",
            state="reachable",
            witness="public_module:pkg.core",
        ),
    )
    for world in ("open", "closed"):
        with_flow = classify_liveness(
            definitions=(_candidate("pkg.core:handler", witness=_WITNESS),),
            referenced_names=frozenset(),
            external_reachability=reachable,
            world_contract=world,
        )
        assert [item.reason for item in with_flow.unresolved_internal] == [
            "opaque_internal_escape"
        ], world
        assert with_flow.unresolved_reachability == () and with_flow.dead_items == ()
    without_flow_open = classify_liveness(
        definitions=(_candidate("pkg.core:handler"),),
        referenced_names=frozenset(),
        external_reachability=reachable,
        world_contract="open",
    )
    assert [item.qualname for item in without_flow_open.unresolved_reachability] == [
        "pkg.core:handler"
    ]
    without_flow_closed = classify_liveness(
        definitions=(_candidate("pkg.core:handler"),),
        referenced_names=frozenset(),
        external_reachability=reachable,
        world_contract="closed",
    )
    assert [item.qualname for item in without_flow_closed.dead_items] == [
        "pkg.core:handler"
    ]


def test_a_live_root_or_a_resolved_reference_still_outranks_the_escape_row() -> None:
    """The escape forbids DEAD; it does not compete with LIVE evidence."""

    referenced = classify_liveness(
        definitions=(_candidate("pkg._m:handler", witness=_WITNESS),),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset({"pkg._m:handler"}),
    )
    assert referenced.unresolved_internal == () and referenced.dead_items == ()


# ---------------------------------------------------------------------------
# The door on the row, the wire, and the cache: the witness is refused, not
# repaired, wherever it is spelled through the wrong construct.
# ---------------------------------------------------------------------------


def test_the_escape_witness_door_refuses_a_name_or_a_broken_chain() -> None:
    assert validate_escape_witness(_WITNESS) == _WITNESS
    for wrong in (
        "",
        binding_witness("handler"),
        "@resource(...) -> local resource -> parameter func",
        "@resource(...) -> local resource -> parameter func"
        " -> opaque call mcp.resource",
        "@resource(...) -> local resource -> parameter"
        " -> opaque call mcp.resource(...)",
        "resource(...) -> local resource -> parameter func"
        " -> opaque call mcp.resource(...)",
        "@resource(...) -> local a b -> parameter func"
        " -> opaque call mcp.resource(...)",
        "@resource(...) -> local resource -> parameter func -> opaque call (...)",
    ):
        with pytest.raises(LivenessVocabularyError):
            validate_escape_witness(wrong)
        with pytest.raises(LivenessVocabularyError):
            _candidate("pkg._m:handler", witness=wrong)
    # A reason and a witness spelled through each other's construct: refused
    # in both directions, so a row can never claim a proven flow and show a
    # spelling coincidence, or the reverse.
    for reason, witness in (
        ("opaque_internal_escape", binding_witness("handler")),
        ("ambiguous_internal_binding", _WITNESS),
    ):
        with pytest.raises(LivenessVocabularyError):
            UnresolvedInternalItem(
                qualname="pkg._m:handler",
                filepath="pkg/_m.py",
                start_line=1,
                end_line=2,
                kind="function",
                local_name="handler",
                witness=witness,
                reason=reason,  # type: ignore[arg-type]
            )
    with pytest.raises(LivenessVocabularyError):
        NestedDefinition(
            qualname="pkg.m:outer.<locals>.handler",
            local_name="handler",
            kind="function",
            lexical_parent="pkg.m:outer",
            lexical_path="outer.<locals>.handler",
            filepath="pkg/m.py",
            start_line=3,
            end_line=4,
            escape_witness=binding_witness("handler"),
        )


def test_the_module_level_witness_rides_the_dc_sidecar_whole() -> None:
    encoded = _dead_candidate_dict_from_model(
        _candidate("pkg._m:handler", witness=_WITNESS), "pkg/_m.py"
    )
    bare = _dead_candidate_dict_from_model(_candidate("pkg._m:other"), "pkg/_m.py")
    assert encoded["escape_witness"] == _WITNESS
    assert "escape_witness" not in bare
    wire: dict[str, object] = {}
    _encode_dead_candidates(
        cast("CacheFactsDict", {"dead_candidates": [encoded, bare]}), wire
    )
    assert wire["ew"] == [["pkg._m:handler", _WITNESS]]
    assert _decode_wire_escape_witness(["pkg._m:handler", _WITNESS]) == (
        "pkg._m:handler",
        _WITNESS,
    )
    for malformed in (
        ["pkg._m:handler"],
        ["pkg._m:handler", ""],
        ["pkg._m:handler", binding_witness("handler")],
        ["", _WITNESS],
        [1, _WITNESS],
    ):
        assert _decode_wire_escape_witness(malformed) is None, malformed
    decoded = _dead_candidate_from_cache_row(encoded)
    assert decoded is not None and decoded.escape_witness == _WITNESS
    decoded_bare = _dead_candidate_from_cache_row(bare)
    assert decoded_bare is not None and decoded_bare.escape_witness is None


def test_the_nested_witness_rides_the_nd_row_whole_and_is_refused_broken() -> None:
    row = NestedDefinition(
        qualname="pkg.m:outer.<locals>.handler",
        local_name="handler",
        kind="function",
        lexical_parent="pkg.m:outer",
        lexical_path="outer.<locals>.handler",
        filepath="pkg/m.py",
        start_line=3,
        end_line=4,
        escape_witness=_WITNESS,
    )
    encoded = _nested_definition_dict_from_model(row, "pkg/m.py")
    assert encoded["escape_witness"] == _WITNESS
    wire: dict[str, object] = {}
    _encode_nested_definitions(
        cast("CacheFactsDict", {"nested_definitions": [encoded]}), wire
    )
    rows = wire["nd"]
    assert isinstance(rows, list) and len(rows[0]) == 14
    assert rows[0][13] == _WITNESS
    decoded = _decode_wire_nested_definition(rows[0], "pkg/m.py")
    assert decoded == encoded
    for broken in (
        [*rows[0][:13]],
        [*rows[0][:13], binding_witness("handler")],
        [*rows[0][:13], 7],
    ):
        assert _decode_wire_nested_definition(broken, "pkg/m.py") is None, broken
    assert _decode_wire_nested_definition([*rows[0][:13], ""], "pkg/m.py") == {
        **encoded,
        "escape_witness": "",
    }
    model = _nested_definition_from_cache_row(encoded)
    assert model is not None and model.escape_witness == _WITNESS
    unmarked = _nested_definition_from_cache_row({**encoded, "escape_witness": ""})
    assert unmarked is not None and unmarked.escape_witness is None


# ---------------------------------------------------------------------------
# The bound of the proof, arm by arm: every place the producer declines is
# reached by a real input, and every place it fires names the flow it proved.
# A guard no input reaches is theatre; this table is what keeps each one
# honest, and each row is a one-line mutation of the counterexample.
# ---------------------------------------------------------------------------

_REGISTRY_MODULE = "def store(func):\n    return func\n"


def _witness_of(root: Path, source: str, qualname: str) -> str | None:
    """The witness the real walk puts on ``qualname`` in ``pkg/m.py``."""

    metrics = _walk(
        root,
        {
            "pkg/__init__.py": "",
            "pkg/_registry.py": _REGISTRY_MODULE,
            "pkg/m.py": source,
        },
    )["pkg/m.py"]
    rows: dict[str, str | None] = {
        row.qualname: row.escape_witness
        for row in (*metrics.dead_candidates, *metrics.nested_definitions)  # type: ignore[attr-defined]
    }
    assert qualname in rows, sorted(rows)
    return rows[qualname]


_HANDLER = "pkg.m:handler"
_BARE = "@tag -> local tag -> parameter func -> opaque call {origin}(...)"


def _src(text: str) -> str:
    """One fixture module, written as an indented block for the table."""

    return textwrap.dedent(text).lstrip("\n")


_CALL = (
    "@resource(...) -> local resource -> parameter func -> opaque call {origin}(...)"
)

#: (id, source, qualname, expected witness or None)
_PROOF_TABLE: tuple[tuple[str, str, str, str | None], ...] = (
    (
        "external-import-consumer-fires",
        _src(
            """
        import vendor


        def tag(func):
            vendor.register(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _BARE.format(origin="vendor.register"),
    ),
    (
        "internal-import-consumer-declines",
        _src(
            """
        from ._registry import store


        def tag(func):
            store(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "import-the-registry-cannot-place-is-external-and-fires",
        _src(
            """
        from .missing import store


        def tag(func):
            store(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _BARE.format(origin="store"),
    ),
    (
        "relative-import-beyond-the-package-is-unplaced-and-declines",
        _src(
            """
        from ...beyond import store


        def tag(func):
            store(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "standard-library-consumer-is-outside-the-root-and-fires",
        _src(
            """
        import functools


        def tag(func):
            functools.lru_cache(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _BARE.format(origin="functools.lru_cache"),
    ),
    (
        "same-module-definition-consumer-declines",
        _src(
            """
        def _keep(func):
            return func


        def tag(func):
            _keep(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "ambiguous-binding-consumer-declines",
        _src(
            """
        def _keep(func):
            return func


        _keep = _keep


        def tag(func):
            _keep(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "unbound-builtin-consumer-declines",
        _src(
            """
        def tag(func):
            setattr(tag, 'last', func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "parameter-consumer-fires",
        _src(
            """
        def make(registry):
            def register(func):
                registry.add(func)
                return func

            return register


        @make(object())
        def handler():
            return 1
            """
        ),
        _HANDLER,
        ("@make(...) -> local make -> parameter func -> opaque call registry.add(...)"),
    ),
    (
        "call-result-alias-fires-and-names-the-call",
        _src(
            """
        import vendor


        def resource(uri):
            decorator = vendor.resource(uri)

            def register(func):
                decorator(func)
                return func

            return register


        @resource('x')
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _CALL.format(origin="vendor.resource"),
    ),
    (
        "annotated-assignment-alias-fires",
        _src(
            """
        import vendor


        def resource(uri):
            decorator: object = vendor.resource(uri)

            def register(func):
                decorator(func)
                return func

            return register


        @resource('x')
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _CALL.format(origin="vendor.resource"),
    ),
    (
        "keyword-argument-flow-fires",
        _src(
            """
        import vendor


        def tag(func):
            vendor.register(fn=func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _BARE.format(origin="vendor.register"),
    ),
    (
        "returned-consuming-call-fires",
        _src(
            """
        import vendor


        def tag(func):
            return vendor.register(func)


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _BARE.format(origin="vendor.register"),
    ),
    (
        "return-before-the-call-declines",
        _src(
            """
        import vendor


        def tag(func):
            return func
            vendor.register(func)


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "compound-statement-before-the-call-declines",
        _src(
            """
        import vendor


        def tag(func):
            with vendor.lock():
                pass
            vendor.register(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "value-nested-in-another-call-declines",
        _src(
            """
        import vendor


        def tag(func):
            vendor.register(vendor.wrap(func))
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "subscript-of-a-call-result-fires",
        _src(
            """
        def tag(func):
            handlers = make()
            handlers[0](func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _BARE.format(origin="make"),
    ),
    (
        "lambda-callee-declines",
        _src(
            """
        def tag(func):
            (lambda f: f)(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "alias-of-a-definition-declines",
        _src(
            """
        def _keep(func):
            return func


        def tag(func):
            handler_ = _keep
            handler_(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "alias-of-a-parameter-attribute-fires",
        _src(
            """
        def make(registry):
            def register(func):
                add = registry.add
                add(func)
                return func

            return register


        @make(object())
        def handler():
            return 1
            """
        ),
        _HANDLER,
        ("@make(...) -> local make -> parameter func -> opaque call registry.add(...)"),
    ),
    (
        "alias-chain-beyond-three-hops-declines",
        _src(
            """
        def make(registry):
            def register(func):
                a = registry.add
                b = a
                c = b
                d = c
                d(func)
                return func

            return register


        @make(object())
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "name-bound-twice-declines",
        _src(
            """
        import vendor


        def _keep(func):
            return func


        def tag(func):
            sink = _keep
            sink = vendor.register
            sink(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "name-bound-to-a-lambda-declines",
        _src(
            """
        def tag(func):
            sink = lambda f: f
            sink(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "name-bound-by-unpacking-declines",
        _src(
            """
        import vendor


        def tag(func):
            sink, other = vendor.pair()
            sink(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "global-declaration-reads-the-module-binding",
        _src(
            """
        _mcp = load()


        def load():
            return object()


        def resource(uri):
            def register(func):
                global _mcp
                _mcp.resource(uri)(func)
                return func

            return register


        @resource('x')
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _CALL.format(origin="load"),
    ),
    (
        "global-declaration-the-module-never-binds-declines",
        _src(
            """
        def tag(func):
            global vendor_hook
            vendor_hook(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "nonlocal-declaration-on-the-callee-declines",
        _src(
            """
        import vendor


        def resource(uri):
            decorator = vendor.resource(uri)

            def register(func):
                nonlocal decorator
                decorator(func)
                return func

            return register


        @resource('x')
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "nonlocal-rebinding-of-the-parameter-declines",
        _src(
            """
        import vendor


        def tag(func):
            def swap():
                nonlocal func
                func = None

            vendor.register(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "registrar-defined-twice-declines",
        _src(
            """
        import vendor


        def tag(func):
            vendor.register(func)
            return func


        def tag(func):
            vendor.register(func)
            return func


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "class-as-registrar-declines",
        _src(
            """
        import vendor


        class Tag:
            def __init__(self, func):
                vendor.register(func)


        @Tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "registrar-without-a-positional-parameter-declines",
        _src(
            """
        import vendor


        def tag(*funcs):
            vendor.register(*funcs)
            return funcs[0]


        @tag
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "call-form-registrar-returning-a-call-declines",
        _src(
            """
        import vendor


        def resource(uri):
            return vendor.resource(uri)


        @resource('x')
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "call-form-registrar-whose-returned-name-is-rebound-declines",
        _src(
            """
        import vendor


        def resource(uri):
            register = None

            def register(func):
                vendor.register(func)
                return func

            return register


        @resource('x')
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "call-form-registrar-returning-a-class-declines",
        _src(
            """
        import vendor


        def resource(uri):
            class register:
                def __init__(self, func):
                    vendor.register(func)

            return register


        @resource('x')
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "outer-decorator-is-not-the-receiver",
        _src(
            """
        import vendor


        def resource(uri):
            decorator = vendor.resource(uri)

            def register(func):
                decorator(func)
                return func

            return register


        @resource('x')
        @vendor.wrap
        def handler():
            return 1
            """
        ),
        _HANDLER,
        None,
    ),
    (
        "innermost-decorator-is-the-receiver",
        _src(
            """
        import vendor


        def resource(uri):
            decorator = vendor.resource(uri)

            def register(func):
                decorator(func)
                return func

            return register


        @vendor.wrap
        @resource('x')
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _CALL.format(origin="vendor.resource"),
    ),
    (
        "async-entry-and-positional-only-parameter-fire",
        _src(
            """
        import vendor


        def resource(uri):
            decorator = vendor.resource(uri)

            async def register(func, /):
                decorator(func)
                return func

            return register


        @resource('x')
        def handler():
            return 1
            """
        ),
        _HANDLER,
        _CALL.format(origin="vendor.resource"),
    ),
    (
        "class-scope-registrar-marks-the-method",
        _src(
            """
        import vendor


        class Handlers:
            def register(func):
                vendor.register(func)
                return func

            @register
            def handle(self):
                return 1
            """
        ),
        "pkg.m:Handlers.handle",
        (
            "@register -> local Handlers.register"
            " -> parameter func -> opaque call vendor.register(...)"
        ),
    ),
    (
        "class-scope-is-skipped-on-the-way-to-the-enclosing-parameter",
        _src(
            """
        def build(registry):
            class Handlers:
                def register(func):
                    registry.add(func)
                    return func

                @register
                def handle(self):
                    return 1

            return Handlers
            """
        ),
        "pkg.m:build.<locals>.Handlers.handle",
        (
            "@register -> local build.<locals>.Handlers.register"
            " -> parameter func -> opaque call registry.add(...)"
        ),
    ),
)


@pytest.mark.parametrize(
    ("source", "qualname", "expected"),
    [pytest.param(*row[1:], id=row[0]) for row in _PROOF_TABLE],
)
def test_the_proof_fires_exactly_where_it_can_follow_the_flow(
    tmp_path: Path, source: str, qualname: str, expected: str | None
) -> None:
    assert _witness_of(tmp_path, source, qualname) == expected


def test_the_proof_table_pairs_every_firing_shape_with_a_declining_one() -> None:
    """The table is two-sided by construction: rows that fire and rows that
    decline, so no single direction of error can pass it."""

    fired = [row[0] for row in _PROOF_TABLE if row[3] is not None]
    declined = [row[0] for row in _PROOF_TABLE if row[3] is None]
    assert len(fired) >= 10 and len(declined) >= 20
    assert len({row[0] for row in _PROOF_TABLE}) == len(_PROOF_TABLE)


# ---------------------------------------------------------------------------
# The dependent wire decoder applies the ``ew`` sidecar to the candidate row
# (in-process: the spawned-CLI warm run exercises it, but coverage is blind
# to a subprocess), and a malformed sidecar rejects the section.
# ---------------------------------------------------------------------------


def test_the_dependent_decoder_applies_the_ew_sidecar_to_its_candidate() -> None:
    from codeclone.cache._wire_decode import _decode_wire_file_sections

    row = ["pkg._m:handler", "handler", 1, 2, "function"]
    other = ["pkg._m:other", "other", 3, 4, "function"]
    sections = _decode_wire_file_sections(
        obj={"dc": [row, other], "ew": [["pkg._m:handler", _WITNESS]]},
        filepath="pkg/_m.py",
        materialized_clone_channels=(),
    )
    assert sections is not None
    candidates = {item["qualname"]: item for item in sections[5]}
    assert candidates["pkg._m:handler"]["escape_witness"] == _WITNESS
    assert "escape_witness" not in candidates["pkg._m:other"]
    # A sidecar naming no row is harmless; a malformed one rejects the section.
    orphan = _decode_wire_file_sections(
        obj={"dc": [row], "ew": [["pkg._m:missing", _WITNESS]]},
        filepath="pkg/_m.py",
        materialized_clone_channels=(),
    )
    assert orphan is not None and "escape_witness" not in orphan[5][0]
    malformed_sidecars: tuple[dict[str, object], ...] = (
        {"dc": [row], "ew": [["pkg._m:handler", binding_witness("handler")]]},
        {"dc": [row], "ew": "x"},
    )
    for malformed in malformed_sidecars:
        assert (
            _decode_wire_file_sections(
                obj=malformed, filepath="pkg/_m.py", materialized_clone_channels=()
            )
            is None
        ), malformed


def test_the_row_door_refuses_a_reason_outside_the_lane() -> None:
    with pytest.raises(LivenessVocabularyError, match="unknown internal abstention"):
        UnresolvedInternalItem(
            qualname="pkg._m:handler",
            filepath="pkg/_m.py",
            start_line=1,
            end_line=2,
            kind="function",
            local_name="handler",
            witness=_WITNESS,
            reason="opaque_external_escape",  # type: ignore[arg-type]
        )

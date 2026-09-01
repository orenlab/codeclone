# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Identity-domain laws of the frozen canonical model (F-3 SS2-SS3)."""

from __future__ import annotations

import random
from collections.abc import Callable

import pytest

from codeclone.canonical import (
    API_PARAMETER_KINDS,
    API_SYMBOL_KINDS,
    API_VISIBILITIES,
    DEPENDENCY_BINDINGS,
    IMPORT_TYPES,
    VIOLATION_KINDS,
    AnalysisFile,
    ApiParameterFact,
    ApiSymbolRow,
    CanonicalModelError,
    DependencyOccurrenceRow,
    DependencyRelationRow,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    FileLine,
    KnownModule,
    ModuleId,
    OpaqueDottedHead,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    RiskObservationRow,
    SymbolId,
    UnresolvedLocation,
    UnresolvedRoot,
    ViolationRow,
    canonical_key,
    derived_wire_columns,
    endpoint_key,
    head_tag,
    root_family,
    sparse_bool_wire_columns,
    wire_columns,
    wire_fact_family_order,
)
from codeclone.canonical.registry import FACT_FAMILY_FIELDS


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/abs/path.py",
        "pkg\\win.py",
        "./pkg/a.py",
        ".",
        "..",
        "pkg/../a.py",
        "pkg/./a.py",
        "pkg//a.py",
    ],
)
def test_file_path_law_rejects_non_canonical_paths(path: str) -> None:
    with pytest.raises(CanonicalModelError):
        FileId(path)


def test_file_path_law_preserves_case_and_unicode() -> None:
    assert FileId("Pkg/Ångström.py").path == "Pkg/Ångström.py"


def test_symbol_key_is_a_tuple_never_a_join() -> None:
    left = SymbolId(FileId("p/a.py"), "b.c")
    right = SymbolId(FileId("p/a.py.b"), "c")
    assert canonical_key(left) != canonical_key(right)
    assert canonical_key(left) == (b"p/a.py", b"b.c")


def test_same_text_under_different_head_variants_stays_distinct() -> None:
    known = OperationRoot(
        "canonical_operation",
        OperationTarget(KnownModule(ModuleId("x.y")), "Z"),
    )
    opaque = OperationRoot(
        "canonical_operation",
        OperationTarget(OpaqueDottedHead("x.y"), "Z"),
    )
    assert canonical_key(known) != canonical_key(opaque)
    assert head_tag(known.target.head) == "module"
    assert head_tag(opaque.target.head) == "opaque"


def test_effect_root_order_is_total_and_family_tag_first() -> None:
    roots: list[EffectRoot] = [
        UnresolvedRoot(),
        ProducerRoot(SymbolId(FileId("a.py"), "f")),
        EffectLabelRoot("artifact_write", "os.replace"),
        OperationRoot(
            "canonical_operation",
            OperationTarget(KnownModule(ModuleId("m")), "n"),
        ),
    ]
    ordered = sorted(roots, key=canonical_key)
    assert [root_family(r) for r in ordered] == [
        "effect",
        "operation",
        "producer",
        "unresolved",
    ]


def test_canonical_order_is_shuffle_stable_and_injective() -> None:
    files = [FileId(f"p/{i}.py") for i in range(9)]
    symbols = [SymbolId(f, q) for f in files[:4] for q in ("a", "a.b", "ab")]
    roots: list[EffectRoot] = [
        *(ProducerRoot(s) for s in symbols[:5]),
        EffectLabelRoot("field_write", "field_write"),
        EffectLabelRoot("serialize_field", "pathlib.Path.write_text"),
        UnresolvedRoot(),
        OperationRoot("pure_builtin", OperationTarget(AnalysisFile(files[5]), "cls")),
        OperationRoot(
            "canonical_operation", OperationTarget(OpaqueDottedHead("a.b"), "c")
        ),
    ]
    for domain in (files, symbols, roots):
        keys = [canonical_key(value) for value in domain]
        assert len(set(keys)) == len(domain)
        baseline = sorted(domain, key=canonical_key)
        for seed in (1, 7, 42):
            shuffled = list(domain)
            random.Random(seed).shuffle(shuffled)
            assert sorted(shuffled, key=canonical_key) == baseline


@pytest.mark.parametrize(
    "build",
    [
        lambda: OperationRoot(
            "not_a_kind", OperationTarget(OpaqueDottedHead("x"), "y")
        ),
        lambda: EffectLabelRoot("not_a_kind", "label"),
        lambda: EffectLabelRoot("artifact_write", ""),
        lambda: OperationTarget(KnownModule(ModuleId("pkg.a")), ""),
        lambda: OperationTarget(AnalysisFile(FileId("pkg/a.py")), ""),
        lambda: OpaqueDottedHead(""),
        lambda: ModuleId(""),
        lambda: SymbolId(FileId("a.py"), ""),
    ],
)
def test_closed_vocabularies_and_empty_values_are_refused(
    build: Callable[[], object],
) -> None:
    with pytest.raises(CanonicalModelError):
        build()


def test_colonless_opaque_target_is_admitted_and_distinct() -> None:
    """Measured on the frozen corpus (wave 2): 21 of 1 080 operation
    targets are one opaque dotted string with no ModuleKey colon.  They are
    representable — empty local name under an opaque head only — and stay
    distinct from every colon-split neighbour."""
    whole = OperationRoot(
        "canonical_operation", OperationTarget(OpaqueDottedHead("a.b.c"), "")
    )
    split = OperationRoot(
        "canonical_operation", OperationTarget(OpaqueDottedHead("a.b"), "c")
    )
    assert canonical_key(whole) != canonical_key(split)
    assert len({canonical_key(whole), canonical_key(split)}) == 2


def test_canonical_key_refuses_foreign_values() -> None:
    with pytest.raises(CanonicalModelError):
        canonical_key(object())


def test_endpoint_key_is_total_and_tag_first_across_the_union() -> None:
    """Same text under MODULE and FILE stays distinct, and the union order
    is (tag, domain bytes) — one construction for every ratified union."""
    module = ModuleId("pkg.a")
    file_endpoint = FileId("pkg.a")
    assert endpoint_key(module) != endpoint_key(file_endpoint)
    assert endpoint_key(module) == ("module", b"pkg.a")
    assert endpoint_key(file_endpoint) == ("file", b"pkg.a")
    assert endpoint_key(file_endpoint) < endpoint_key(module)  # "file" < "module"
    with pytest.raises(CanonicalModelError):
        endpoint_key(SymbolId(FileId("a.py"), "f"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "build",
    [
        lambda: DependencyRelationRow(ModuleId("a"), ModuleId("b"), "banana"),
        lambda: DependencyOccurrenceRow(
            DependencyRelationRow(ModuleId("a"), ModuleId("b"), "import"),
            1,
            "banana",
            False,
        ),
        lambda: DependencyOccurrenceRow(
            DependencyRelationRow(ModuleId("a"), ModuleId("b"), "import"),
            -1,
            "import_time",
            False,
        ),
        # F5: every closed vocabulary and both empty-as-value refusals
        lambda: ApiSymbolRow(SymbolId(FileId("a.py"), "f"), "banana", "name", (), None),
        lambda: ApiSymbolRow(
            SymbolId(FileId("a.py"), "f"), "function", "banana", (), None
        ),
        lambda: ApiSymbolRow(SymbolId(FileId("a.py"), "f"), "function", "name", (), ""),
        lambda: ApiParameterFact("value", "banana", False, None),
        lambda: ApiParameterFact("", "pos_or_kw", False, None),
        lambda: ApiParameterFact("value", "pos_or_kw", False, ""),
        # F1: the closed dimension vocabulary and both positive floors
        lambda: RiskObservationRow(SymbolId(FileId("a.py"), "f"), "cbo", 3, 10),
        lambda: RiskObservationRow(
            SymbolId(FileId("a.py"), "f"), "cyclomatic_complexity", 0, 10
        ),
        lambda: RiskObservationRow(
            SymbolId(FileId("a.py"), "f"), "cyclomatic_complexity", 3, 0
        ),
        # The evidence-line law, both variants and both ways it breaks: a
        # negative line, and the bool that ``isinstance(True, int)`` would
        # otherwise smuggle in as line 1.
        lambda: FileLine(FileId("a.py"), -1),
        lambda: FileLine(FileId("a.py"), True),
        lambda: UnresolvedLocation("vendor/x.py", -1),
        lambda: UnresolvedLocation("vendor/x.py", True),
        lambda: ViolationRow(
            contract_id="",
            kind="owner_bypass",
            sink_identity=SymbolId(FileId("a.py"), "f"),
            canonical_owner=SymbolId(FileId("a.py"), "f"),
            authority_status="shadow",
            effect_signature="sig",
            resolution_state="resolved",
            root_set=frozenset(),
            producer_set=frozenset(),
            suppressed=False,
            locations=(),
        ),
        lambda: ViolationRow(
            contract_id="c",
            kind="banana",
            sink_identity=SymbolId(FileId("a.py"), "f"),
            canonical_owner=SymbolId(FileId("a.py"), "f"),
            authority_status="shadow",
            effect_signature="sig",
            resolution_state="resolved",
            root_set=frozenset(),
            producer_set=frozenset(),
            suppressed=False,
            locations=(),
        ),
    ],
)
def test_new_family_vocabularies_and_bounds_are_refused(
    build: Callable[[], object],
) -> None:
    with pytest.raises(CanonicalModelError):
        build()


def test_fact_family_order_is_mechanical_not_a_manual_tail() -> None:
    order = wire_fact_family_order()
    assert order == tuple(sorted(FACT_FAMILY_FIELDS))
    assert list(order) == sorted(order)
    for family in order:
        columns = wire_columns(family)
        assert list(columns) == sorted(columns)
        assert columns, family


def test_registry_wire_columns_are_exactly_the_declared_wire_fields() -> None:
    """Every wire=True field is a wire column and nothing else is: stored
    facts come from the model, and a derived wire field must be a declared
    contract-derived public handle with one named formula owner — an
    undeclared derived field is not something a test catches, it is
    something that cannot be written."""
    for family, declarations in FACT_FAMILY_FIELDS.items():
        emitted = set(wire_columns(family))
        assert emitted == {d.field for d in declarations if d.wire}, family
        for declaration in declarations:
            if declaration.wire and not declaration.stored:
                assert declaration.field in set(derived_wire_columns(family))
                assert declaration.public_handle, (family, declaration.field)
                assert declaration.owner.endswith(".v1"), (family, declaration.field)
            if not declaration.wire:
                assert declaration.field not in emitted, (family, declaration.field)


def test_registry_declares_the_two_class_b_handles_and_their_owners() -> None:
    assert derived_wire_columns("candidates") == ("candidate_id",)
    assert derived_wire_columns("violations") == ("violation_id",)
    owners = {
        d.field: d.owner
        for family in ("candidates", "violations")
        for d in FACT_FAMILY_FIELDS[family]
        if not d.stored and d.wire
    }
    assert owners == {
        "candidate_id": "candidate_identity_contract.v1",
        "violation_id": "violation_identity_contract.v1",
    }


def test_registry_declares_the_record_families() -> None:
    """The record-shaped wire families: one record per analysis snapshot,
    no rows, no invented row keys — F9 ``run_scalars`` and the
    RULING-2026-08-31 §3 ``analysis_population`` singleton; every table
    family stays columnar."""
    from codeclone.canonical import RECORD_WIRE_FAMILIES, is_record_family

    assert frozenset({"analysis_population", "run_scalars"}) == RECORD_WIRE_FAMILIES
    assert is_record_family("run_scalars")
    assert is_record_family("analysis_population")
    assert not is_record_family("dependency_relations")
    assert not is_record_family("api_symbols")


def test_registry_declares_the_sparse_boolean_columns() -> None:
    assert sparse_bool_wire_columns("dependency_occurrences") == ("is_lazy",)
    assert sparse_bool_wire_columns("dependency_relations") == ()
    assert sparse_bool_wire_columns("violations") == ("suppressed",)
    assert sparse_bool_wire_columns("candidates") == ()


def test_fact_vocabularies_mirror_the_producer_literals() -> None:
    """The wire's closed dictionaries and the producer's Literal types are
    pinned against each other: drift on either side is loud (G2 — one
    signal, one place, one interpretation)."""
    from typing import get_args, get_type_hints

    from codeclone.models import (
        ApiParameterKind,
        ApiSymbolKind,
        ApiVisibility,
        AuthorityViolationKind,
        DependencyBinding,
        ModuleDep,
    )

    hints = get_type_hints(ModuleDep)
    assert get_args(hints["import_type"]) == IMPORT_TYPES
    assert get_args(DependencyBinding) == DEPENDENCY_BINDINGS
    assert get_args(AuthorityViolationKind) == VIOLATION_KINDS
    assert get_args(ApiSymbolKind) == API_SYMBOL_KINDS
    assert get_args(ApiVisibility) == API_VISIBILITIES
    assert get_args(ApiParameterKind) == API_PARAMETER_KINDS

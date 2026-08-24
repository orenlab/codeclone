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
    AnalysisFile,
    CanonicalModelError,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    KnownModule,
    ModuleId,
    OpaqueDottedHead,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    SymbolId,
    UnresolvedRoot,
    canonical_key,
    head_tag,
    root_family,
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
        lambda: OperationTarget(OpaqueDottedHead("x"), ""),
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


def test_canonical_key_refuses_foreign_values() -> None:
    with pytest.raises(CanonicalModelError):
        canonical_key(object())


def test_fact_family_order_is_mechanical_not_a_manual_tail() -> None:
    order = wire_fact_family_order()
    assert order == tuple(sorted(FACT_FAMILY_FIELDS))
    assert list(order) == sorted(order)
    for family in order:
        columns = wire_columns(family)
        assert list(columns) == sorted(columns)
        assert columns, family


def test_registry_never_emits_undeclared_or_unstored_fields() -> None:
    for family, declarations in FACT_FAMILY_FIELDS.items():
        emitted = set(wire_columns(family))
        for declaration in declarations:
            if not (declaration.stored and declaration.wire):
                assert declaration.field not in emitted, (family, declaration.field)

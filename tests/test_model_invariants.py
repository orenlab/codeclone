# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Refusal paths of the model layer's ``__post_init__`` invariants.

Every dataclass here fails closed: an instance that would carry an incoherent
fact must not come into existence at all, because once constructed it is
indistinguishable from a measured one. These tests pin the refusals themselves
-- not merely that construction can succeed -- so that a later relaxation of a
guard shows up as a failing test rather than as silently admitted bad state.
"""

from __future__ import annotations

import pytest

from codeclone.models import (
    ContractIRDocument,
    FileIdentity,
    FunctionContractIR,
    ImportObservation,
    ModuleInventoryEntry,
    ModuleInventoryIndex,
    ObservabilityConfig,
    PackagePrefix,
    PythonModuleIdentity,
    ResolvedSourceIdentity,
    StageCounterSnapshot,
    ThinIdentityTable,
    UnreachableStatementItem,
    derive_python_module_identity,
    python_module_mount_row,
)


def _identity(path: str = "pkg/mod.py") -> ResolvedSourceIdentity:
    return ResolvedSourceIdentity(
        file=FileIdentity(path=path),
        python_module=PythonModuleIdentity(
            module="pkg.mod",
            package="pkg",
            is_package=False,
            mount_path=".",
            origin="import_mount",
            node_kind="module_file",
        ),
    )


def test_python_module_identity_requires_a_module_name() -> None:
    """An identity with no module names nothing and must not be constructible."""

    with pytest.raises(ValueError, match="requires a module name"):
        PythonModuleIdentity(
            module="",
            package="",
            is_package=False,
            mount_path=".",
            origin="import_mount",
            node_kind="module_file",
        )


def test_thin_identity_table_rejects_null_module_carrying_a_mount() -> None:
    """A row with no module cannot also claim the mount that would name one."""

    with pytest.raises(ValueError, match="null-module identity cannot carry an import"):
        ThinIdentityTable(
            paths=("a.py", "b.py"),
            module_null=(1,),
            mount_exc=((1, "src", "pkg"),),
        )


@pytest.mark.parametrize("index", [-1, 2])
def test_thin_identity_table_rejects_indices_outside_the_row_range(index: int) -> None:
    """Exception indices address real rows; an out-of-range index is a defect."""

    with pytest.raises(ValueError, match="must be inside the row range"):
        ThinIdentityTable(paths=("a.py", "b.py"), module_null=(index,))


def test_module_inventory_entry_rejects_internality_contradicting_analyzed() -> None:
    """``analyzed`` and ``internality`` are one fact stated twice, never two."""

    with pytest.raises(ValueError, match="internality must match analyzed state"):
        ModuleInventoryEntry(
            identity=_identity(),
            analyzed=True,
            internality="known_internal_not_analyzed",
        )


@pytest.mark.parametrize(
    ("module", "mount_paths", "contributing_paths", "expected"),
    [
        ("", ("src",), ("src/pkg",), "requires a non-empty module"),
        ("pkg", ("b", "a"), ("src/pkg",), "mount paths must be sorted and unique"),
        ("pkg", ("src",), ("b", "a"), "contributing paths must be sorted and unique"),
    ],
)
def test_package_prefix_rejects_incoherent_rows(
    module: str,
    mount_paths: tuple[str, ...],
    contributing_paths: tuple[str, ...],
    expected: str,
) -> None:
    """A prefix names one package and carries canonically ordered path sets."""

    with pytest.raises(ValueError, match=expected):
        PackagePrefix(
            module=module,
            node_kind="namespace_package",
            mount_paths=mount_paths,
            contributing_paths=contributing_paths,
        )


def test_module_inventory_index_rejects_unsorted_keys() -> None:
    """The index is binary-searched, so unsorted keys would silently miss."""

    entry = ModuleInventoryEntry(
        identity=_identity(),
        analyzed=True,
        internality="analyzed",
    )
    with pytest.raises(ValueError, match="keys must be sorted and unique"):
        ModuleInventoryIndex(rows=(("b", entry), ("a", entry)))


@pytest.mark.parametrize(
    ("retention_days", "max_operations", "max_spans"),
    [(0, 1, 1), (1, 0, 1), (1, 1, 0)],
)
def test_observability_config_rejects_nonpositive_bounds(
    retention_days: int,
    max_operations: int,
    max_spans: int,
) -> None:
    """A zero cap is not "unbounded"; it is a bound nothing can satisfy."""

    with pytest.raises(ValueError, match="retention and caps must be positive"):
        ObservabilityConfig(
            enabled=True,
            retention_days=retention_days,
            max_operations_per_process=max_operations,
            max_spans_per_operation=max_spans,
        )


def test_stage_counter_snapshot_rejects_duplicate_keys() -> None:
    """Duplicate keys make the merged total depend on iteration order."""

    with pytest.raises(ValueError, match="keys must be unique"):
        StageCounterSnapshot((("files", 1), ("files", 2)))


def test_stage_counter_snapshot_normalizes_counter_order() -> None:
    """Construction sorts, so two orderings of the same counters are one value."""

    assert StageCounterSnapshot((("b", 2), ("a", 1))).counters == (("a", 1), ("b", 2))


@pytest.mark.parametrize(
    ("start_line", "end_line", "statement_count", "expected"),
    [
        (0, 4, 1, "never a fabricated one"),
        (5, 4, 1, "never a fabricated one"),
        (1, 4, 0, "at least one statement"),
    ],
)
def test_unreachable_statement_item_rejects_fabricated_regions(
    start_line: int,
    end_line: int,
    statement_count: int,
    expected: str,
) -> None:
    """A dead region reports a real span covering at least one statement."""

    with pytest.raises(ValueError, match=expected):
        UnreachableStatementItem(
            reason="after_terminator",
            start_line=start_line,
            end_line=end_line,
            statement_count=statement_count,
        )


def test_import_observation_rejects_unsorted_candidate_targets() -> None:
    """Candidate order is not information, so it is canonical or it is a bug."""

    with pytest.raises(ValueError, match="candidate targets must be sorted and unique"):
        ImportObservation(
            source=_identity(),
            syntax_kind="import",
            level=0,
            requested_module="pkg",
            requested_names=(),
            resolution="analyzed",
            candidate_targets=("b.py", "a.py"),
            resolved_target="a.py",
        )


@pytest.mark.parametrize(
    "signature",
    ["0" * 63, "0" * 65, "A" * 64, "g" * 64],
)
def test_function_contract_ir_rejects_non_hex_effect_signatures(
    signature: str,
) -> None:
    """The signature is a sha256 digest; anything else cannot be compared."""

    document = ContractIRDocument(
        inputs=(),
        guards=(),
        transformations=(),
        dependencies=(),
        output_facts=(),
        side_effects=(),
        failure_states=(),
        unresolved=False,
    )
    with pytest.raises(ValueError, match="64 lowercase hex characters"):
        FunctionContractIR(
            function="pkg.mod:f",
            document=document,
            wire="wire",
            effect_signature=signature,
            provenance_roots=(),
        )


def test_derive_module_identity_keeps_paths_outside_their_declared_mount() -> None:
    """A path that does not sit under the mount keeps its full stem.

    The mount prefix is stripped only when it actually prefixes the path; a
    non-matching mount must not silently truncate an unrelated path.
    """

    identity = derive_python_module_identity(
        "other/mod.py",
        mount_path="src",
        module_prefix="",
    )
    assert identity.module == "other.mod"


def test_mount_row_is_omitted_when_the_default_derivation_already_matches() -> None:
    """Root-mounted, unprefixed identities need no exception row at all."""

    identity = derive_python_module_identity("pkg/mod.py")
    assert python_module_mount_row("pkg/mod.py", identity) is None


def test_mount_row_survives_a_path_outside_its_declared_mount() -> None:
    """A non-matching mount leaves the stem whole, so no prefix is left over.

    ``other/mod.py`` does not sit under the ``src`` mount, so nothing is
    stripped and both stem segments are accounted for by ``pkg.mod`` itself.
    The row still carries the mount -- dropping it would lose the exception --
    but the prefix is empty rather than a guessed ``pkg``.
    """

    identity = PythonModuleIdentity(
        module="pkg.mod",
        package="pkg",
        is_package=False,
        mount_path="src",
        origin="import_mount",
        node_kind="module_file",
    )
    assert python_module_mount_row("other/mod.py", identity) == ("src", "")

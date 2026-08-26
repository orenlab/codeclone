# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Full-run ingest laws: the legacy document maps losslessly, or refuses.

Distinguishing fixture (§6.2): a module-headed and a path-headed symbol key
resolve to different files; every root family is present, including the
measured colon-less operation target; candidate producers arrive unsorted;
a dotted head outside the registry is opaque for an operation target and a
refusal for a symbol — the same spelling, two verdicts, decided by the
producer's registry, never by the shape of the string.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from codeclone.canonical import (
    AnalysisFile,
    CanonicalModelError,
    CloneGroupRow,
    CloneItemRow,
    DependencyCycleRow,
    EffectLabelRoot,
    FileId,
    KnownModule,
    LegacyIngestError,
    ModuleId,
    ModuleSymbol,
    OpaqueDottedHead,
    OpaqueEntity,
    OperationRoot,
    OperationTarget,
    RunScalars,
    SymbolId,
    UnresolvedRoot,
    canonical_model_from_legacy_document,
    decode_canonical_json,
    encode_canonical_json,
)

_MAKE = "pkg.mod:make"
_RUN = "scripts/tool.py:run"


def legacy_document() -> dict[str, Any]:
    roots_make = [
        "operation:canonical_operation:pkg.mod:Writer",
        "operation:canonical_operation:scripts/tool.py:W2",
        "operation:canonical_operation:ext.lib:Cls",
        "operation:canonical_operation:ext.pkg.attr_only",
        "effect:artifact_write:os.replace",
        "unresolved",
    ]
    roots_run = ["producer:scripts/tool.py:run"]
    return {
        "source_facts": {
            "analysis_scope": [
                {"path": "pkg/mod.py"},
                {"path": "pkg/other.py"},
                {"path": "pkg/third.py"},
                {"path": "scripts/tool.py"},
            ],
            "module_registry": {
                "entries_by_path": {
                    "rows": [
                        [
                            "pkg/mod.py",
                            {
                                "identity": {
                                    "file": {"path": "pkg/mod.py"},
                                    "python_module": {"module": "pkg.mod"},
                                }
                            },
                        ],
                        [
                            "pkg/other.py",
                            {
                                "identity": {
                                    "file": {"path": "pkg/other.py"},
                                    "python_module": {"module": "pkg.other"},
                                }
                            },
                        ],
                        [
                            "pkg/third.py",
                            {
                                "identity": {
                                    "file": {"path": "pkg/third.py"},
                                    "python_module": {"module": "pkg.third"},
                                }
                            },
                        ],
                        [
                            "scripts/tool.py",
                            {
                                "identity": {
                                    "file": {"path": "scripts/tool.py"},
                                    "python_module": None,
                                }
                            },
                        ],
                    ]
                }
            },
            "semantic": {
                "contract_ir": {
                    "contracts": [
                        {
                            "function": _MAKE,
                            "effect_signature": "sig-make",
                            "provenance_roots": roots_make,
                        },
                        {
                            "function": _RUN,
                            "effect_signature": "sig-run",
                            "provenance_roots": roots_run,
                        },
                    ]
                },
                "graph": {
                    "nodes": [
                        {
                            "function": _MAKE,
                            "effect_signature": "gsig-make",
                            "producer_root_ids": roots_make,
                            "output_facts": ["unresolved", "const:int:1", "unresolved"],
                            "resolution_state": "resolved",
                        },
                        {
                            "function": _RUN,
                            "effect_signature": "gsig-run",
                            "producer_root_ids": roots_run,
                            "output_facts": [],
                            "resolution_state": "unavailable",
                        },
                    ],
                    "edges": [{"source": _MAKE, "target": _RUN}],
                },
                "sinks": [
                    {"sink_identity": _MAKE, "authority_status": "unavailable"},
                    {"sink_identity": _RUN, "authority_status": "mixed"},
                ],
                "candidates": [
                    {
                        "candidate_id": "ignored-by-ingest",
                        "level": "exact_contract_ir",
                        "score": 5,
                        "shared_fact": "contract_ir:sig-make",
                        # Deliberately unsorted: ingest must not depend on order.
                        "producers": [_RUN, _MAKE],
                    }
                ],
                "violations": [
                    {
                        "violation_id": "ignored-by-ingest",
                        "contract_id": "governance.report_write",
                        "kind": "owner_bypass",
                        "sink_identity": _MAKE,
                        "canonical_owner": _RUN,
                        "authority_status": "shadow",
                        "producer_root_ids": roots_run,
                        "effect_signature": "asig",
                        "resolution_state": "resolved",
                        "producers": [_RUN, _MAKE],
                        "suppressed": False,
                        "locations": [],
                    }
                ],
            },
            "source_fact_families": {
                # F2 lane verbatim from the producer's shape: source carries
                # the file identity (module provenance rides beside it and is
                # not identity), qualname is bare, zero rows never appear.
                "coupling_cohesion_observations": [
                    {
                        "source": {
                            "file": {"path": "pkg/mod.py"},
                            "python_module": {"module": "pkg.mod"},
                        },
                        "qualname": "Writer",
                        "dimension": "cbo",
                        "numerator": 3,
                    },
                    {
                        "source": {
                            "file": {"path": "pkg/mod.py"},
                            "python_module": {"module": "pkg.mod"},
                        },
                        "qualname": "Writer",
                        "dimension": "lcom4",
                        "numerator": 1,
                    },
                    {
                        "source": {
                            "file": {"path": "scripts/tool.py"},
                            "python_module": None,
                        },
                        "qualname": "Runner",
                        "dimension": "methods",
                        "numerator": 2,
                    },
                ],
                # F5 lane verbatim from the producer's shape: owner carries
                # the file identity, the symbol is bare, digests ride the
                # producer's one ccapi1:sig identity, absence is None.
                "api_surface": [
                    {
                        "owner": {
                            "file": {"path": "pkg/mod.py"},
                            "python_module": {"module": "pkg.mod"},
                        },
                        "symbol": "make",
                        "symbol_kind": "function",
                        "visibility": "name",
                        "parameters": [
                            {
                                "name": "value",
                                "kind": "pos_or_kw",
                                "has_default": False,
                                "annotation_digest": {
                                    "domain": "ccapi1:sig",
                                    "algorithm": "sha256",
                                    "value": "aa" * 32,
                                },
                            },
                            {
                                "name": "extra",
                                "kind": "kw_only",
                                "has_default": True,
                                "annotation_digest": None,
                            },
                        ],
                        "returns_digest": {
                            "domain": "ccapi1:sig",
                            "algorithm": "sha256",
                            "value": "bb" * 32,
                        },
                    },
                    {
                        # the @overload sibling: same owner and symbol,
                        # different canonical signature variant
                        "owner": {
                            "file": {"path": "pkg/mod.py"},
                            "python_module": {"module": "pkg.mod"},
                        },
                        "symbol": "make",
                        "symbol_kind": "function",
                        "visibility": "name",
                        "parameters": [],
                        "returns_digest": None,
                    },
                    {
                        "owner": {
                            "file": {"path": "scripts/tool.py"},
                            "python_module": None,
                        },
                        "symbol": "Runner",
                        "symbol_kind": "class",
                        "visibility": "all",
                        "parameters": [],
                        "returns_digest": None,
                    },
                ],
                # F1 lane verbatim from the producer's shape (fork (b)):
                # the @overload pair shares source, qualname, dimension
                # AND numerator — only the declaration site tells the two
                # facts apart; the third row rides the module-less file.
                # F4 lane verbatim from the producer's shape: glued
                # head:local entities with MIXED heads (module, analyzed
                # path, and one head outside both — the opaque variant), a
                # span-suffixed unreachable row, a live root, and an
                # abstention.
                "dead_code": [
                    {
                        "entity": "pkg.mod:make",
                        "candidate_kind": "function",
                        "reference_count": 1,
                        "reachable": False,
                        "runtime_marker_count": 0,
                        "source_markers": [],
                        "observation_kind": "symbol",
                        "live_root_reason": "export_root",
                        "abstained": False,
                    },
                    {
                        "entity": "pkg.mod:make#12-15",
                        "candidate_kind": "function",
                        "reference_count": 0,
                        "reachable": False,
                        "runtime_marker_count": 0,
                        "source_markers": [["unreachable_reason", "after_terminator"]],
                        "observation_kind": "unreachable_statement",
                        "live_root_reason": None,
                        "abstained": False,
                    },
                    {
                        "entity": "scripts/tool.py:run",
                        "candidate_kind": "function",
                        "reference_count": 0,
                        "reachable": True,
                        "runtime_marker_count": 2,
                        "source_markers": [],
                        "observation_kind": "symbol",
                        "live_root_reason": None,
                        "abstained": False,
                    },
                    {
                        "entity": "ext.vendor:Shim.call",
                        "candidate_kind": "method",
                        "reference_count": 0,
                        "reachable": False,
                        "runtime_marker_count": 0,
                        "source_markers": [],
                        "observation_kind": "symbol",
                        "live_root_reason": None,
                        "abstained": True,
                    },
                ],
                "risk_observations": [
                    {
                        "source": {
                            "file": {"path": "pkg/mod.py"},
                            "python_module": {"module": "pkg.mod"},
                        },
                        "qualname": "make",
                        "dimension": "cyclomatic_complexity",
                        "numerator": 7,
                        "start_line": 10,
                    },
                    {
                        "source": {
                            "file": {"path": "pkg/mod.py"},
                            "python_module": {"module": "pkg.mod"},
                        },
                        "qualname": "make",
                        "dimension": "cyclomatic_complexity",
                        "numerator": 7,
                        "start_line": 40,
                    },
                    {
                        "source": {
                            "file": {"path": "scripts/tool.py"},
                            "python_module": None,
                        },
                        "qualname": "run",
                        "dimension": "nesting_depth",
                        "numerator": 2,
                        "start_line": 5,
                    },
                ],
            },
        },
        "metrics": {
            "families": {
                "dependencies": {
                    "items": [
                        {
                            "source": "pkg.mod",
                            "target": "pkg.other",
                            "import_type": "import",
                            "line": 3,
                            "binding": "import_time",
                            "is_lazy": False,
                        },
                        {
                            "source": "pkg.mod",
                            "target": "scripts/tool.py",
                            "import_type": "from_import",
                            "line": 2,
                            "binding": "type_checking",
                            "is_lazy": True,
                        },
                    ],
                    # F7 verbatim from the producer's shape: modules and the
                    # aligned registry member paths; one set per row, the
                    # kind classified once, two sets sharing a module.
                    "cycle_details": [
                        {
                            "modules": ["pkg.mod", "pkg.other"],
                            "kind": "import_cycle",
                            "member_paths": ["pkg/mod.py", "pkg/other.py"],
                        },
                        {
                            "modules": ["pkg.mod", "pkg.third"],
                            "kind": "deferred_cycle",
                            "member_paths": ["pkg/mod.py", "pkg/third.py"],
                        },
                    ],
                },
                "coupling": {
                    "items": [
                        {"coupled_classes": ["Token", "AccessToken"]},
                        {"coupled_classes": []},
                        {"coupled_classes": ["Token", "AccessToken"]},
                        {"coupled_classes": ["Token"]},
                    ]
                },
            }
        },
        # F8: the emitted clone population verbatim from the producer's
        # shape — item qualnames are glued ModuleKey heads, the block group
        # carries an intra-function pair, and the SUPPRESSED container sits
        # right beside the emitted buckets carrying a group that must NEVER
        # enter the family (§10: suppressed is a different population).
        "findings": {
            "groups": {
                "clones": {
                    "functions": [
                        {
                            "id": "clone:function:aa11|0-19",
                            "clone_kind": "function",
                            "novelty": "known",
                            "facts": {"group_key": "aa11|0-19", "group_arity": 2},
                            "items": [
                                {
                                    "relative_path": "pkg/mod.py",
                                    "qualname": "pkg.mod:make",
                                    "start_line": 4,
                                    "end_line": 16,
                                    "loc": 13,
                                },
                                {
                                    "relative_path": "scripts/tool.py",
                                    "qualname": "scripts/tool.py:run",
                                    "start_line": 19,
                                    "end_line": 31,
                                    "loc": 13,
                                },
                            ],
                        }
                    ],
                    "blocks": [
                        {
                            "id": "clone:block:bb22",
                            "clone_kind": "block",
                            "novelty": "known",
                            "facts": {"group_key": "bb22|bb22|bb22|bb22"},
                            "items": [
                                {
                                    "relative_path": "pkg/mod.py",
                                    "qualname": "pkg.mod:make",
                                    "start_line": 13,
                                    "end_line": 48,
                                    "size": 36,
                                },
                                {
                                    "relative_path": "pkg/mod.py",
                                    "qualname": "pkg.mod:make",
                                    "start_line": 53,
                                    "end_line": 67,
                                    "size": 15,
                                },
                                {
                                    "relative_path": "pkg/other.py",
                                    "qualname": "pkg.other:helper",
                                    "start_line": 9,
                                    "end_line": 41,
                                    "size": 33,
                                },
                            ],
                        }
                    ],
                    "segments": [],
                    "suppressed": {
                        "functions": [
                            {
                                "clone_kind": "function",
                                "facts": {"group_key": "ffff|20-39"},
                                "items": [
                                    {
                                        "relative_path": "pkg/mod.py",
                                        "qualname": "pkg.mod:make",
                                        "start_line": 70,
                                        "end_line": 90,
                                    },
                                    {
                                        "relative_path": "pkg/other.py",
                                        "qualname": "pkg.other:helper",
                                        "start_line": 70,
                                        "end_line": 90,
                                    },
                                ],
                            }
                        ],
                        "blocks": [],
                        "segments": [],
                    },
                }
            }
        },
        # F9: the document's inventory scalars verbatim (values pairwise
        # distinct so a cross-wired mapping cannot survive; the witness
        # list and file_registry beside them are deliberately not scalars).
        "inventory": {
            "files": {
                "total_found": 3,
                "analyzed": 2,
                "cached": 1,
                "skipped": 0,
                "source_io_skipped": 4,
                "unsupported_construct_skipped": 5,
                "unsupported_constructs": [],
            },
            "code": {
                "parsed_lines": 905,
                "functions": 41,
                "methods": 13,
                "classes": 7,
            },
            "file_registry": {"encoding": "relative_path", "items": []},
        },
    }


def test_ingest_builds_the_measured_families() -> None:
    model = canonical_model_from_legacy_document(legacy_document())
    facts = model.facts
    assert len(facts.analysis.contracts) == 2
    assert len(facts.analysis.graph_nodes) == 2
    assert len(facts.analysis.sink_roles) == 2
    assert len(facts.analysis.candidates) == 1
    assert len(facts.analysis.semantic_edges) == 1
    assert len(facts.analysis.dependency_relations) == 2
    assert len(facts.analysis.dependency_occurrences) == 2
    assert {o.relation for o in facts.analysis.dependency_occurrences} == set(
        facts.analysis.dependency_relations
    )
    assert len(facts.analysis.violations) == 1
    assert len(facts.analysis.coupling_cohesion_observations) == 3
    assert len(facts.analysis.api_symbols) == 3
    assert facts.analysis.run_scalars == RunScalars(
        classes=7,
        files_analyzed=2,
        files_cached=1,
        files_found=3,
        files_skipped=0,
        functions=41,
        methods=13,
        parsed_lines=905,
        source_io_skipped=4,
        unsupported_construct_skipped=5,
    )
    assert len(model.coupled_sets) == 2  # duplicates collapse, empty drops
    assert len(model.analyzed_files) == 4
    assert len(model.file_modules) == 3
    make = SymbolId(FileId("pkg/mod.py"), "make")
    run = SymbolId(FileId("scripts/tool.py"), "run")
    assert {row.function for row in facts.analysis.contracts} == {make, run}
    candidate = next(iter(facts.analysis.candidates))
    assert candidate.producer_set == frozenset({make, run})


def test_ingest_builds_the_cycle_family_rows() -> None:
    """F7: both producer kinds, MODULE-domain sets, overlapping but
    distinct — carried verbatim from the document's cycle_details rows."""
    model = canonical_model_from_legacy_document(legacy_document())
    rows = model.facts.analysis.dependency_cycles
    assert len(rows) == 2
    assert rows == frozenset(
        {
            DependencyCycleRow(
                "import_cycle",
                frozenset({ModuleId("pkg.mod"), ModuleId("pkg.other")}),
            ),
            DependencyCycleRow(
                "deferred_cycle",
                frozenset({ModuleId("pkg.mod"), ModuleId("pkg.third")}),
            ),
        }
    )


def test_ingest_builds_the_emitted_clone_groups_only() -> None:
    """F8: the emitted population verbatim — and NOT ONE row from the
    suppressed container sitting right beside it (§10: suppressed is a
    different population; mixing them is the known dialect root)."""
    model = canonical_model_from_legacy_document(legacy_document())
    make = SymbolId(FileId("pkg/mod.py"), "make")
    run = SymbolId(FileId("scripts/tool.py"), "run")
    helper = SymbolId(FileId("pkg/other.py"), "helper")
    assert model.facts.analysis.clone_groups == frozenset(
        {
            CloneGroupRow(
                "function",
                "aa11|0-19",
                frozenset({CloneItemRow(make, 4, 16), CloneItemRow(run, 19, 31)}),
            ),
            CloneGroupRow(
                "block",
                "bb22|bb22|bb22|bb22",
                frozenset(
                    {
                        CloneItemRow(make, 13, 48),
                        CloneItemRow(make, 53, 67),
                        CloneItemRow(helper, 9, 41),
                    }
                ),
            ),
        }
    )


def _function_clone_group(document: dict[str, Any]) -> dict[str, Any]:
    groups = document["findings"]["groups"]["clones"]["functions"]
    row: dict[str, Any] = groups[0]
    return row


def test_ingest_refuses_a_clone_kind_disagreeing_with_its_container() -> None:
    """The container name IS the population statement; a row disagreeing
    with its own bucket is a document at war with itself."""

    def swap(document: dict[str, Any]) -> None:
        _function_clone_group(document)["clone_kind"] = "block"

    with pytest.raises(LegacyIngestError, match="disagrees with its container"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_clone_item_path_disagreeing_with_identity() -> None:
    """relative_path is the item's second spelling of its own file; when it
    disagrees with the resolved glued qualname the document is refused,
    never silently repaired toward either spelling."""

    def swap(document: dict[str, Any]) -> None:
        _function_clone_group(document)["items"][0]["relative_path"] = "pkg/other.py"

    with pytest.raises(LegacyIngestError, match="disagrees with the item"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_duplicate_clone_items() -> None:
    """Arity and identity are different measurements: two byte-identical
    members would be silently absorbed by a set — refused loudly instead."""

    def swap(document: dict[str, Any]) -> None:
        items = _function_clone_group(document)["items"]
        items.append(dict(items[0]))

    with pytest.raises(LegacyIngestError, match="share one identity"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_clone_group_without_a_group_key() -> None:
    def swap(document: dict[str, Any]) -> None:
        del _function_clone_group(document)["facts"]["group_key"]

    with pytest.raises(LegacyIngestError, match="missing 'group_key'"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_document_missing_the_clone_container() -> None:
    def swap(document: dict[str, Any]) -> None:
        del document["findings"]["groups"]["clones"]["blocks"]

    with pytest.raises(LegacyIngestError, match="missing 'blocks'"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_maps_dead_entities_onto_the_tagged_union() -> None:
    """The §2 union executed against the document's own registry: a module
    head KEEPS its MODULE variant, an analyzed path is the FILE-headed
    SYMBOL, and a head outside both rides opaque — verbatim, no guessing."""
    model = canonical_model_from_legacy_document(legacy_document())
    assert len(model.facts.analysis.dead_code_observations) == 4
    entities = {row.entity for row in model.facts.analysis.dead_code_observations}
    assert entities == {
        ModuleSymbol(ModuleId("pkg.mod"), "make"),
        ModuleSymbol(ModuleId("pkg.mod"), "make#12-15"),
        SymbolId(FileId("scripts/tool.py"), "run"),
        OpaqueEntity("ext.vendor", "Shim.call"),
    }
    abstained = next(
        row
        for row in model.facts.analysis.dead_code_observations
        if row.entity == OpaqueEntity("ext.vendor", "Shim.call")
    )
    assert abstained.abstained is True
    assert abstained.live_root_reason is None


def _dead_lane_row(document: dict[str, Any]) -> dict[str, Any]:
    families = document["source_facts"]["source_fact_families"]
    row: dict[str, Any] = families["dead_code"][0]
    return row


def test_ingest_refuses_an_unglued_dead_entity() -> None:
    """A dead-code reference without the producer's ModuleKey colon does
    not parse under the grammar: refused, never guessed into a variant."""

    def swap(document: dict[str, Any]) -> None:
        _dead_lane_row(document)["entity"] = "just_a_name"

    with pytest.raises(LegacyIngestError, match="head:local"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_dead_entity_with_an_empty_local() -> None:
    def swap(document: dict[str, Any]) -> None:
        _dead_lane_row(document)["entity"] = "pkg.mod:"

    with pytest.raises(LegacyIngestError, match="head:local"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_dead_entity_with_a_second_colon() -> None:
    def swap(document: dict[str, Any]) -> None:
        _dead_lane_row(document)["entity"] = "pkg.mod:make:extra"

    with pytest.raises(LegacyIngestError, match="second ModuleKey colon"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_non_boolean_dead_flag() -> None:
    def swap(document: dict[str, Any]) -> None:
        _dead_lane_row(document)["reachable"] = "no"

    with pytest.raises(LegacyIngestError, match="booleans"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_malformed_dead_marker_pair() -> None:
    def swap(document: dict[str, Any]) -> None:
        _dead_lane_row(document)["source_markers"] = [["only-key"]]

    with pytest.raises(LegacyIngestError, match="pair"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_keeps_both_overload_risk_declarations() -> None:
    """F1: the @overload pair survives as TWO facts — equal in everything
    but the declaration site — plus the module-less third row."""
    model = canonical_model_from_legacy_document(legacy_document())
    rows = {
        (row.symbol.qualname, row.dimension, row.numerator, row.start_line)
        for row in model.facts.analysis.risk_observations
    }
    assert rows == {
        ("make", "cyclomatic_complexity", 7, 10),
        ("make", "cyclomatic_complexity", 7, 40),
        ("run", "nesting_depth", 2, 5),
    }


def test_ingest_reads_the_producer_root_grammar() -> None:
    model = canonical_model_from_legacy_document(legacy_document())
    contract = next(
        row
        for row in model.facts.analysis.contracts
        if row.function == SymbolId(FileId("pkg/mod.py"), "make")
    )
    assert contract.root_set == frozenset(
        {
            OperationRoot(
                "canonical_operation",
                OperationTarget(KnownModule(ModuleId("pkg.mod")), "Writer"),
            ),
            OperationRoot(
                "canonical_operation",
                OperationTarget(AnalysisFile(FileId("scripts/tool.py")), "W2"),
            ),
            OperationRoot(
                "canonical_operation",
                OperationTarget(OpaqueDottedHead("ext.lib"), "Cls"),
            ),
            OperationRoot(
                "canonical_operation",
                OperationTarget(OpaqueDottedHead("ext.pkg.attr_only"), ""),
            ),
            EffectLabelRoot("artifact_write", "os.replace"),
            UnresolvedRoot(),
        }
    )


def test_colonless_operation_target_is_one_opaque_head() -> None:
    """The measured class (21 of 1 080 corpus targets): no ModuleKey colon
    means the whole string is the opaque head and no local name is
    asserted — splitting at a dot would manufacture structure."""
    model = canonical_model_from_legacy_document(legacy_document())
    roots = {
        root
        for row in model.facts.analysis.contracts
        for root in row.root_set
        if isinstance(root, OperationRoot)
        and isinstance(root.target.head, OpaqueDottedHead)
    }
    assert (
        OperationRoot(
            "canonical_operation",
            OperationTarget(OpaqueDottedHead("ext.pkg.attr_only"), ""),
        )
        in roots
    )


def test_ingested_model_round_trips_through_the_wire() -> None:
    model = canonical_model_from_legacy_document(legacy_document())
    encoded = encode_canonical_json(model)
    assert decode_canonical_json(encoded) == model


def test_wire_candidate_handle_matches_the_producer_formula_verbatim() -> None:
    """Known-answer pin against the producer's own preimage: revision,
    level, shared fact, then the sorted ModuleKey-headed producer keys —
    the module head where the registry names one, the analysis path
    otherwise.  A swapped head resolution or an unsorted set turns this
    red."""
    model = canonical_model_from_legacy_document(legacy_document())
    encoded = encode_canonical_json(model)
    document = json.loads(encoded)
    wire_handles = document["facts"]["candidates"]["candidate_id"]
    preimage = "\x00".join(
        ["1", "exact_contract_ir", "contract_ir:sig-make", _MAKE, _RUN]
    )
    expected = hashlib.sha256(
        b"ccsem1:authority\x00" + preimage.encode("utf-8")
    ).hexdigest()
    assert wire_handles == [expected]


def _mutated(mutate: Callable[[dict[str, Any]], None]) -> Mapping[str, Any]:
    document = copy.deepcopy(legacy_document())
    mutate(document)
    return document


def test_ingest_refuses_an_unresolvable_symbol_head() -> None:
    def swap(document: dict[str, Any]) -> None:
        node = document["source_facts"]["semantic"]["graph"]["nodes"][0]
        node["function"] = "ghost.mod:make"

    with pytest.raises(LegacyIngestError, match="neither a registry module"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_modulekey_target_without_local_name() -> None:
    """The boundary next to the colon-less class: a colon with an empty
    local name is a grammar defect — collapsing ``ext.lib:`` into
    ``ext.lib`` would merge two distinct producer strings."""

    def swap(document: dict[str, Any]) -> None:
        contract = document["source_facts"]["semantic"]["contract_ir"]["contracts"][0]
        contract["provenance_roots"] = ["operation:canonical_operation:ext.lib:"]

    with pytest.raises(LegacyIngestError, match="no local name"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_an_unresolvable_dependency_endpoint() -> None:
    def swap(document: dict[str, Any]) -> None:
        item = document["metrics"]["families"]["dependencies"]["items"][0]
        item["target"] = "ghost.mod"

    with pytest.raises(LegacyIngestError, match="endpoint"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_an_unknown_root_family() -> None:
    def swap(document: dict[str, Any]) -> None:
        contract = document["source_facts"]["semantic"]["contract_ir"]["contracts"][0]
        contract["provenance_roots"] = ["mystery:token"]

    with pytest.raises(LegacyIngestError, match="unknown root family"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_document_missing_a_family() -> None:
    """Structural refusal class: a missing key is loud, never a default."""

    def swap(document: dict[str, Any]) -> None:
        del document["source_facts"]["semantic"]["sinks"]

    with pytest.raises(LegacyIngestError, match="missing 'sinks'"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_non_boolean_lazy_marker() -> None:
    def swap(document: dict[str, Any]) -> None:
        item = document["metrics"]["families"]["dependencies"]["items"][0]
        item["is_lazy"] = "no"

    with pytest.raises(LegacyIngestError, match="is_lazy"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_module_claiming_two_files() -> None:
    def swap(document: dict[str, Any]) -> None:
        rows = document["source_facts"]["module_registry"]["entries_by_path"]["rows"]
        rows.append(
            [
                "pkg/dup.py",
                {
                    "identity": {
                        "file": {"path": "pkg/dup.py"},
                        "python_module": {"module": "pkg.mod"},
                    }
                },
            ]
        )

    with pytest.raises(LegacyIngestError, match="two files"):
        canonical_model_from_legacy_document(_mutated(swap))


def _cycle_row(document: dict[str, Any]) -> dict[str, Any]:
    dependencies = document["metrics"]["families"]["dependencies"]
    row: dict[str, Any] = dependencies["cycle_details"][0]
    return row


def test_ingest_refuses_a_cycle_module_outside_the_registry() -> None:
    """MODULE-domain law: a cycle member that is not a registry module has
    no MODULE identity; the oracle refuses instead of minting one from a
    string."""

    def swap(document: dict[str, Any]) -> None:
        row = _cycle_row(document)
        row["modules"] = ["pkg.mod", "ghost.mod"]
        row["member_paths"] = ["pkg/mod.py", None]

    with pytest.raises(LegacyIngestError, match="not a registry module"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_misaligned_cycle_member_paths() -> None:
    def swap(document: dict[str, Any]) -> None:
        _cycle_row(document)["member_paths"] = ["pkg/mod.py"]

    with pytest.raises(LegacyIngestError, match="align"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_member_path_disagreeing_with_the_registry() -> None:
    """member_paths is the registry's own projection; a document whose row
    disagrees with its own registry is at war with itself — refused, never
    silently repaired (the projection is representation, not a fact to keep)."""

    def swap(document: dict[str, Any]) -> None:
        _cycle_row(document)["member_paths"] = ["pkg/other.py", "pkg/other.py"]

    with pytest.raises(LegacyIngestError, match="disagrees"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_cycle_naming_one_module_twice() -> None:
    """The row asserts a SET; a repeated member is a producer defect that a
    frozenset would silently absorb.  Three members with one repeat reach
    ONLY the arity guard: the collapsed set still clears the two-module
    floor, so a dropped guard would absorb the defect silently."""

    def swap(document: dict[str, Any]) -> None:
        row = _cycle_row(document)
        row["modules"] = ["pkg.mod", "pkg.mod", "pkg.other"]
        row["member_paths"] = ["pkg/mod.py", "pkg/mod.py", "pkg/other.py"]

    with pytest.raises(LegacyIngestError, match="twice"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_two_cycle_rows_over_one_module_set() -> None:
    """The corpus-pinned family law routed through normalization: a second
    row on the same set — even with the other kind — is refused."""

    def swap(document: dict[str, Any]) -> None:
        rows = document["metrics"]["families"]["dependencies"]["cycle_details"]
        rows.append(dict(rows[0], kind="deferred_cycle"))

    with pytest.raises(CanonicalModelError, match=r"dependency_cycles\.modules"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_an_unknown_cycle_kind() -> None:
    """The model law owns the vocabulary; ingest routes its refusal."""

    def swap(document: dict[str, Any]) -> None:
        _cycle_row(document)["kind"] = "banana"

    with pytest.raises(CanonicalModelError, match="cycle kind"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_document_missing_cycle_details() -> None:
    def swap(document: dict[str, Any]) -> None:
        del document["metrics"]["families"]["dependencies"]["cycle_details"]

    with pytest.raises(LegacyIngestError, match="missing 'cycle_details'"):
        canonical_model_from_legacy_document(_mutated(swap))


def _observation_row(document: dict[str, Any]) -> dict[str, Any]:
    families = document["source_facts"]["source_fact_families"]
    row: dict[str, Any] = families["coupling_cohesion_observations"][0]
    return row


def test_ingest_refuses_a_glued_observation_qualname() -> None:
    """The producer's lane law is executed, not narrated: a ModuleKey colon
    inside an F2 qualname is a dialect defect, never an identity."""

    def swap(document: dict[str, Any]) -> None:
        _observation_row(document)["qualname"] = "pkg.mod:Writer"

    with pytest.raises(LegacyIngestError, match="glued"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_an_unanalyzed_observation_source() -> None:
    def swap(document: dict[str, Any]) -> None:
        _observation_row(document)["source"]["file"]["path"] = "vendored/x.py"

    with pytest.raises(LegacyIngestError, match="not an analyzed path"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_non_integer_observation_numerator() -> None:
    def swap(document: dict[str, Any]) -> None:
        _observation_row(document)["numerator"] = True

    with pytest.raises(LegacyIngestError, match="numerator"):
        canonical_model_from_legacy_document(_mutated(swap))


def _api_row(document: dict[str, Any], position: int = 0) -> dict[str, Any]:
    families = document["source_facts"]["source_fact_families"]
    row: dict[str, Any] = families["api_surface"][position]
    return row


def test_ingest_maps_api_overloads_to_two_rows_on_one_symbol() -> None:
    """The F5 oracle keeps both @overload declarations: one FILE-headed
    SYMBOL, two canonical signature variants — nothing deduplicated."""
    model = canonical_model_from_legacy_document(legacy_document())
    make = SymbolId(FileId("pkg/mod.py"), "make")
    rows = [row for row in model.facts.analysis.api_symbols if row.symbol == make]
    assert len(rows) == 2
    long_row = next(row for row in rows if row.parameters)
    assert [p.name for p in long_row.parameters] == ["value", "extra"]
    assert long_row.parameters[0].annotation_digest == "aa" * 32
    assert long_row.parameters[1].annotation_digest is None
    assert long_row.returns_digest == "bb" * 32
    short_row = next(row for row in rows if not row.parameters)
    assert short_row.returns_digest is None
    runner = SymbolId(FileId("scripts/tool.py"), "Runner")
    assert any(row.symbol == runner for row in model.facts.analysis.api_symbols)


def test_ingest_refuses_a_glued_api_symbol() -> None:
    def swap(document: dict[str, Any]) -> None:
        _api_row(document)["symbol"] = "pkg.mod:make"

    with pytest.raises(LegacyIngestError, match="glued"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_an_unanalyzed_api_owner() -> None:
    def swap(document: dict[str, Any]) -> None:
        _api_row(document)["owner"]["file"]["path"] = "vendored/x.py"

    with pytest.raises(LegacyIngestError, match="not an analyzed"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_non_boolean_api_default_marker() -> None:
    def swap(document: dict[str, Any]) -> None:
        _api_row(document)["parameters"][0]["has_default"] = "no"

    with pytest.raises(LegacyIngestError, match="has_default"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_foreign_api_digest_identity() -> None:
    """A digest under another domain is a different fact — reading it as a
    signature would silently merge two identity spaces."""

    def swap(document: dict[str, Any]) -> None:
        _api_row(document)["returns_digest"]["domain"] = "ccsem1:other"

    with pytest.raises(LegacyIngestError, match="foreign digest identity"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_an_empty_api_digest_value() -> None:
    def swap(document: dict[str, Any]) -> None:
        _api_row(document)["parameters"][0]["annotation_digest"]["value"] = ""

    with pytest.raises(LegacyIngestError, match="digest value is empty"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_document_missing_an_inventory_scalar() -> None:
    def swap(document: dict[str, Any]) -> None:
        del document["inventory"]["files"]["total_found"]

    with pytest.raises(LegacyIngestError, match="missing 'total_found'"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_boolean_inventory_scalar() -> None:
    def swap(document: dict[str, Any]) -> None:
        document["inventory"]["code"]["classes"] = True

    with pytest.raises(LegacyIngestError, match="classes is not an integer"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_maps_observation_sources_to_file_headed_symbols() -> None:
    model = canonical_model_from_legacy_document(legacy_document())
    rows = model.facts.analysis.coupling_cohesion_observations
    writer = SymbolId(FileId("pkg/mod.py"), "Writer")
    runner = SymbolId(FileId("scripts/tool.py"), "Runner")
    assert {row.symbol for row in rows} == {writer, runner}
    assert {(row.dimension, row.numerator) for row in rows if row.symbol == writer} == {
        ("cbo", 3),
        ("lcom4", 1),
    }


def _risk_row(document: dict[str, Any]) -> dict[str, Any]:
    families = document["source_facts"]["source_fact_families"]
    row: dict[str, Any] = families["risk_observations"][0]
    return row


def test_ingest_refuses_a_risk_row_without_a_declaration_site() -> None:
    """F1: the site is a key component; a lane row that lost it cannot name
    its entity and is refused, never defaulted."""

    def swap(document: dict[str, Any]) -> None:
        _risk_row(document).pop("start_line")

    with pytest.raises(LegacyIngestError, match="start_line"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_non_integer_risk_declaration_site() -> None:
    def swap(document: dict[str, Any]) -> None:
        _risk_row(document)["start_line"] = True

    with pytest.raises(LegacyIngestError, match="start_line"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_an_unknown_risk_dimension() -> None:
    """The model law owns the vocabulary; ingest routes its refusal."""

    def swap(document: dict[str, Any]) -> None:
        _risk_row(document)["dimension"] = "cbo"

    with pytest.raises(CanonicalModelError, match="risk dimension"):
        canonical_model_from_legacy_document(_mutated(swap))


def test_ingest_refuses_a_glued_risk_qualname() -> None:
    def swap(document: dict[str, Any]) -> None:
        _risk_row(document)["qualname"] = "pkg.mod:make"

    with pytest.raises(LegacyIngestError, match="glued"):
        canonical_model_from_legacy_document(_mutated(swap))

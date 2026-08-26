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
    EffectLabelRoot,
    FileId,
    KnownModule,
    LegacyIngestError,
    ModuleId,
    OpaqueDottedHead,
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
                    ]
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
    assert len(model.analyzed_files) == 3
    assert len(model.file_modules) == 2
    make = SymbolId(FileId("pkg/mod.py"), "make")
    run = SymbolId(FileId("scripts/tool.py"), "run")
    assert {row.function for row in facts.analysis.contracts} == {make, run}
    candidate = next(iter(facts.analysis.candidates))
    assert candidate.producer_set == frozenset({make, run})


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

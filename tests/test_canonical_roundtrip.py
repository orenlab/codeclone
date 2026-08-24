# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Round-trip laws L1..L7 of the canonical model and its wire codec (F-3 §6).

The fixture follows the distinguishing-fixture law (§6.2): every collection
is non-empty and non-trivial, an empty root set lives next to non-empty
ones, a module-less file lives next to a moduled one, and values that would
collide under a separator join are present.  The wave-1.5 families keep the
law: dependency edges differ pairwise in exactly one producer-key component
(line, then import_type), a FILE endpoint lives next to MODULE endpoints,
lazy rows live next to eager ones, and the two violations share everything
except ``kind`` so their class-B handles must differ.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from codeclone.canonical import (
    AnalysisFile,
    CandidateRow,
    CanonicalFacts,
    CanonicalModel,
    CanonicalModelError,
    ContractRow,
    DependencyEdgeRow,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    FileModuleRelation,
    GraphNodeRow,
    KnownModule,
    ModuleId,
    OpaqueDottedHead,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    SemanticEdge,
    SinkRoleRow,
    SymbolId,
    UnresolvedRoot,
    ViolationRow,
    decode_canonical_json,
    encode_canonical_json,
    wire_fact_family_order,
)


def fixture_model(reverse_insertion: bool = False) -> CanonicalModel:
    """A distinguishing fixture; ``reverse_insertion`` probes order freedom."""
    fa = FileId("pkg/a.py")
    fb = FileId("tools/b.py")
    fc = FileId("pkg/a.py.d")  # separator-collision neighbour of pkg/a.py
    ma = ModuleId("pkg.a")
    sa = SymbolId(fa, "A.run")
    sb = SymbolId(fb, "helper")
    sc = SymbolId(fa, "A.stop")
    sd = SymbolId(fb, "zz")  # referenced by an edge only: no FUNCTION role
    se = SymbolId(fc, "run")
    roots_a: frozenset[EffectRoot] = frozenset({UnresolvedRoot(), ProducerRoot(sa)})
    roots_b: frozenset[EffectRoot] = frozenset(
        {
            OperationRoot(
                "canonical_operation",
                OperationTarget(KnownModule(ma), "Writer"),
            ),
            OperationRoot(
                "canonical_operation", OperationTarget(AnalysisFile(fb), "W2")
            ),
            OperationRoot(
                "canonical_operation",
                OperationTarget(OpaqueDottedHead("x.y"), "Z"),
            ),
            EffectLabelRoot("artifact_write", "os.replace"),
        }
    )
    contracts = [
        ContractRow(sa, "sig-a", roots_a),
        ContractRow(sb, "sig-b", roots_b),
        ContractRow(sc, "sig-c", frozenset()),  # empty ≠ absent (four states)
        ContractRow(se, "sig-e", roots_a),  # shares roots_a: interned once
    ]
    graph_nodes = [
        GraphNodeRow(
            sa,
            "gsig-a",
            roots_a,
            ("unresolved", "const:int:1", "unresolved"),  # order + repeats kept
            "resolved",
        ),
        GraphNodeRow(sb, "gsig-b", roots_b, (), "unavailable"),
    ]
    sink_roles = [SinkRoleRow(sa, "unavailable"), SinkRoleRow(sb, "mixed")]
    candidates = [
        CandidateRow("exact", "shared", frozenset({sa, sb})),
        CandidateRow("exact", "shared", frozenset({sa, sc})),  # tail decided by set
    ]
    edges = [SemanticEdge(sa, sb), SemanticEdge(sb, sc), SemanticEdge(sc, sd)]
    mh = ModuleId("tools.helper")
    dependency_edges = [
        DependencyEdgeRow(ma, mh, "import", 4, "import_time", False),
        # differs from the row above only in import_type (key component)
        DependencyEdgeRow(ma, mh, "from_import", 4, "deferred_function", False),
        # differs only in line (key component), and is lazy
        DependencyEdgeRow(ma, mh, "import", 9, "type_checking", True),
        # FILE endpoint as source (the measured module-less fallback), lazy
        DependencyEdgeRow(fb, ma, "from_import", 2, "lazy_syntax", True),
    ]
    violations = [
        ViolationRow(
            contract_id="governance.report_write",
            kind="owner_bypass",
            sink_identity=sa,
            canonical_owner=sc,
            authority_status="shadow",
            effect_signature="asig-a",
            resolution_state="resolved",
            root_set=roots_a,  # shared with contracts and graph nodes
            producer_set=frozenset({sa, sb}),
            suppressed=False,
        ),
        ViolationRow(
            contract_id="governance.report_write",
            kind="shadow_projection",  # only the kind differs: ids must differ
            sink_identity=sa,
            canonical_owner=sc,
            authority_status="shadow",
            effect_signature="asig-a",
            resolution_state="resolved",
            root_set=frozenset(),  # measured empty, not absent
            producer_set=frozenset({sa, sb}),
            suppressed=True,
        ),
    ]
    coupled = [frozenset({"Token", "AccessToken"}), frozenset({"Token"})]
    if reverse_insertion:
        contracts = list(reversed(contracts))
        graph_nodes = list(reversed(graph_nodes))
        sink_roles = list(reversed(sink_roles))
        candidates = list(reversed(candidates))
        edges = list(reversed(edges))
        dependency_edges = list(reversed(dependency_edges))
        violations = list(reversed(violations))
        coupled = list(reversed(coupled))
    return CanonicalModel(
        analyzed_files=frozenset({fa, fb}),
        file_modules=frozenset({FileModuleRelation(fa, ma)}),
        facts=CanonicalFacts(
            contracts=frozenset(contracts),
            graph_nodes=frozenset(graph_nodes),
            sink_roles=frozenset(sink_roles),
            candidates=frozenset(candidates),
            semantic_edges=frozenset(edges),
            dependency_edges=frozenset(dependency_edges),
            violations=frozenset(violations),
        ),
        coupled_sets=frozenset(coupled),
    )


def test_known_answer_bytes_pin_the_wire_revision_0_contract() -> None:
    """Known-answer pin: any silent movement of the byte contract — member
    order, escaping, float lexemes, the integrity domain — turns this red.

    The literal is a contract sentinel for wire revision "0" (still a
    DRAFT); refreshing it to make the test pass is forbidden (a change here
    IS a wire-contract change and needs its own review).  Wave 1.5 replaced
    the wave-1 literal (1594 bytes, sha256 4172612b…) deliberately: the
    draft gained the ``dependency_edges`` and ``violations`` families and
    the two class-B handle columns, so every document's bytes moved.
    """
    payload = encode_canonical_json(fixture_model())
    assert len(payload) == 2576
    assert (
        hashlib.sha256(payload).hexdigest()
        == "cfcf02bf680c6b941c6fde4b1f87646e9d5a4c9ca3092fbbd81aab305857d47a"
    )


def test_l1_normalize_is_idempotent() -> None:
    once = fixture_model().normalize()
    assert once.normalize() == once


def test_l2_decode_of_encode_is_the_normalized_model() -> None:
    model = fixture_model()
    assert decode_canonical_json(encode_canonical_json(model)) == model.normalize()


def test_l3_encoding_does_not_distinguish_normalization() -> None:
    model = fixture_model()
    assert encode_canonical_json(model) == encode_canonical_json(model.normalize())


def test_l4_l7_bytes_are_deterministic_and_insertion_order_free() -> None:
    first = encode_canonical_json(fixture_model())
    again = encode_canonical_json(fixture_model())
    reversed_build = encode_canonical_json(fixture_model(reverse_insertion=True))
    assert first == again
    assert first == reversed_build


def test_entity_counts_survive_the_round_trip() -> None:
    model = fixture_model().normalize()
    decoded = decode_canonical_json(encode_canonical_json(model))
    for field in ("files", "modules", "analyzed_files", "file_modules", "coupled_sets"):
        assert len(getattr(decoded, field)) == len(getattr(model, field)), field
    for field in (
        "contracts",
        "graph_nodes",
        "sink_roles",
        "candidates",
        "semantic_edges",
        "dependency_edges",
        "violations",
    ):
        assert len(getattr(decoded.facts, field)) == len(getattr(model.facts, field)), (
            field
        )


def test_empty_root_set_is_a_measured_value_not_an_absence() -> None:
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    empty_rows = [row for row in decoded.facts.contracts if row.root_set == frozenset()]
    assert len(empty_rows) == 1
    assert empty_rows[0].effect_signature == "sig-c"


def test_shared_root_set_is_interned_once_on_the_wire() -> None:
    document = json.loads(encode_canonical_json(fixture_model()))
    # roots_a is shared by two contracts and one graph node; roots_b by one
    # contract and one graph node; plus the empty set and no duplicates.
    assert document["sets"]["root_sets"] == sorted(document["sets"]["root_sets"])
    assert len(document["sets"]["root_sets"]) == 3
    assert [] in document["sets"]["root_sets"]


def test_wire_fact_families_come_from_the_registry_in_sorted_order() -> None:
    document = json.loads(encode_canonical_json(fixture_model()))
    assert list(document["facts"].keys()) == list(wire_fact_family_order())
    assert "dependency_edges" in document["facts"]
    assert "violations" in document["facts"]
    assert list(document.keys()) == [
        "format",
        "revisions",
        "values",
        "domains",
        "sets",
        "scope",
        "facts",
        "integrity",
    ]


def test_dependency_edge_key_components_and_payload_survive_the_round_trip() -> None:
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    edges = decoded.facts.dependency_edges
    assert len(edges) == 4
    # both producer-key components are load-bearing: rows differing only in
    # line, and only in import_type, coexist after the round trip
    ma, mh = ModuleId("pkg.a"), ModuleId("tools.helper")
    lines = {
        e.line
        for e in edges
        if (e.source, e.target, e.import_type) == (ma, mh, "import")
    }
    assert lines == {4, 9}
    import_types = {
        e.import_type for e in edges if (e.source, e.target, e.line) == (ma, mh, 4)
    }
    assert import_types == {"import", "from_import"}
    # payload survives: the FILE-endpoint row keeps its binding and marker
    file_row = next(e for e in edges if e.source == FileId("tools/b.py"))
    assert (file_row.binding, file_row.is_lazy) == ("lazy_syntax", True)
    assert {e.is_lazy for e in edges} == {True, False}


def test_dependency_edge_endpoints_ride_the_wire_as_tagged_pairs() -> None:
    document = json.loads(encode_canonical_json(fixture_model()))
    table = document["facts"]["dependency_edges"]
    assert table["source"][0][0] == "file"  # FILE sorts before MODULE by tag
    assert all(pair[0] in ("file", "module") for pair in table["source"])
    assert all(pair[0] == "module" for pair in table["target"])
    # sparse boolean: strictly increasing true positions
    assert table["is_lazy"] == sorted(table["is_lazy"])
    assert len(table["is_lazy"]) == 2


def test_tied_dependency_rows_are_ordered_by_line_on_the_wire() -> None:
    """Rows tied on (source, target, import_type) MUST order by line.

    Eight tied rows make a set-iteration coincidence practically
    impossible (§6.2): an encoder that drops ``line`` from its sort key
    leaks insertion/iteration order into the wire and this pin reds.
    """
    ma, mb = ModuleId("pkg.a"), ModuleId("pkg.b")
    model = CanonicalModel(
        facts=CanonicalFacts(
            dependency_edges=frozenset(
                DependencyEdgeRow(ma, mb, "import", line, "import_time", False)
                for line in (13, 5, 89, 2, 34, 21, 55, 8)
            )
        )
    )
    document = json.loads(encode_canonical_json(model))
    lines = document["facts"]["dependency_edges"]["line"]
    assert lines == sorted(lines)
    assert lines == [2, 5, 8, 13, 21, 34, 55, 89]


def test_sparse_boolean_column_is_omitted_when_no_row_is_true() -> None:
    model = fixture_model()
    eager = frozenset(
        DependencyEdgeRow(e.source, e.target, e.import_type, e.line, e.binding, False)
        for e in model.facts.dependency_edges
    )
    facts = CanonicalFacts(
        contracts=model.facts.contracts,
        graph_nodes=model.facts.graph_nodes,
        sink_roles=model.facts.sink_roles,
        candidates=model.facts.candidates,
        semantic_edges=model.facts.semantic_edges,
        dependency_edges=eager,
        violations=model.facts.violations,
    )
    stripped = CanonicalModel(
        analyzed_files=model.analyzed_files,
        file_modules=model.file_modules,
        facts=facts,
        coupled_sets=model.coupled_sets,
    )
    document = json.loads(encode_canonical_json(stripped))
    assert "is_lazy" not in document["facts"]["dependency_edges"]
    decoded = decode_canonical_json(encode_canonical_json(stripped))
    assert all(not e.is_lazy for e in decoded.facts.dependency_edges)


def test_output_facts_order_and_multiplicity_are_facts() -> None:
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    node = next(
        row for row in decoded.facts.graph_nodes if row.effect_signature == "gsig-a"
    )
    assert node.output_facts == ("unresolved", "const:int:1", "unresolved")


def test_model_refuses_two_facts_under_one_logical_key() -> None:
    fa = FileId("pkg/a.py")
    sa = SymbolId(fa, "A.run")
    model = CanonicalModel(
        facts=CanonicalFacts(
            contracts=frozenset(
                {
                    ContractRow(sa, "sig-1", frozenset()),
                    ContractRow(sa, "sig-2", frozenset()),
                }
            )
        )
    )
    with pytest.raises(CanonicalModelError, match="logical key"):
        model.normalize()


def test_model_refuses_a_producer_without_the_function_role() -> None:
    fa = FileId("pkg/a.py")
    sa = SymbolId(fa, "A.run")
    ghost = SymbolId(fa, "ghost")
    model = CanonicalModel(
        facts=CanonicalFacts(
            contracts=frozenset({ContractRow(sa, "sig", frozenset())}),
            candidates=frozenset(
                {CandidateRow("exact", "shared", frozenset({sa, ghost}))}
            ),
        )
    )
    with pytest.raises(CanonicalModelError, match="FUNCTION role"):
        model.normalize()


def test_model_refuses_two_edges_under_one_producer_key() -> None:
    """binding and is_lazy are payload, never key: two rows sharing the
    producer's (source, target, import_type, line) with different payload
    are refused loudly, not last-writer-silenced."""
    ma, mb = ModuleId("pkg.a"), ModuleId("pkg.b")
    model = CanonicalModel(
        facts=CanonicalFacts(
            dependency_edges=frozenset(
                {
                    DependencyEdgeRow(ma, mb, "import", 4, "import_time", False),
                    DependencyEdgeRow(ma, mb, "import", 4, "deferred_function", False),
                }
            )
        )
    )
    with pytest.raises(CanonicalModelError, match=r"dependency_edges\.producer_key"):
        model.normalize()


def test_edge_rows_differing_in_any_key_component_coexist() -> None:
    ma, mb = ModuleId("pkg.a"), ModuleId("pkg.b")
    model = CanonicalModel(
        facts=CanonicalFacts(
            dependency_edges=frozenset(
                {
                    DependencyEdgeRow(ma, mb, "import", 4, "import_time", False),
                    DependencyEdgeRow(ma, mb, "import", 9, "import_time", False),
                    DependencyEdgeRow(ma, mb, "from_import", 4, "import_time", False),
                }
            )
        )
    )
    assert len(model.normalize().facts.dependency_edges) == 3


def _violation(kind: str, *, status: str = "shadow") -> ViolationRow:
    fa = FileId("pkg/a.py")
    sa = SymbolId(fa, "A.run")
    return ViolationRow(
        contract_id="governance.report_write",
        kind=kind,
        sink_identity=sa,
        canonical_owner=sa,
        authority_status=status,
        effect_signature="asig",
        resolution_state="resolved",
        root_set=frozenset(),
        producer_set=frozenset({sa}),
        suppressed=False,
    )


def test_model_refuses_two_violations_under_one_natural_key() -> None:
    sa = SymbolId(FileId("pkg/a.py"), "A.run")
    model = CanonicalModel(
        facts=CanonicalFacts(
            contracts=frozenset({ContractRow(sa, "sig", frozenset())}),
            violations=frozenset(
                {
                    _violation("owner_bypass", status="shadow"),
                    _violation("owner_bypass", status="mixed"),
                }
            ),
        )
    )
    with pytest.raises(CanonicalModelError, match=r"violations\.natural_key"):
        model.normalize()


def test_violations_differing_only_in_kind_are_distinct_rows() -> None:
    sa = SymbolId(FileId("pkg/a.py"), "A.run")
    model = CanonicalModel(
        facts=CanonicalFacts(
            contracts=frozenset({ContractRow(sa, "sig", frozenset())}),
            violations=frozenset(
                {_violation("owner_bypass"), _violation("shadow_projection")}
            ),
        )
    )
    assert len(model.normalize().facts.violations) == 2


def test_model_refuses_a_violation_sink_without_the_function_role() -> None:
    sa = SymbolId(FileId("pkg/a.py"), "A.run")
    row = _violation("owner_bypass")
    model = CanonicalModel(
        facts=CanonicalFacts(
            contracts=frozenset({ContractRow(sa, "sig", frozenset())}),
            violations=frozenset(
                {
                    ViolationRow(
                        contract_id=row.contract_id,
                        kind=row.kind,
                        sink_identity=SymbolId(FileId("pkg/a.py"), "ghost"),
                        canonical_owner=row.canonical_owner,
                        authority_status=row.authority_status,
                        effect_signature=row.effect_signature,
                        resolution_state=row.resolution_state,
                        root_set=row.root_set,
                        producer_set=frozenset({sa}),
                        suppressed=False,
                    )
                }
            ),
        )
    )
    with pytest.raises(CanonicalModelError, match="violation sink"):
        model.normalize()

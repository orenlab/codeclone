# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Round-trip laws L1..L7 of the canonical model and its wire codec (F-3 §6).

The fixture follows the distinguishing-fixture law (§6.2): every collection
is non-empty and non-trivial, an empty root set lives next to non-empty
ones, a module-less file lives next to a moduled one, and values that would
collide under a separator join are present.  The ratified dependency split
(ruling 2026-08-24 §2) keeps the law: two occurrences of ONE relation differ
only in their evidence line (and in payload), two relations differ only in
``dependency_type``, a FILE endpoint lives next to MODULE endpoints, lazy
occurrences live next to eager ones, one relation carries no occurrence
evidence at all, and the two violations share everything except ``kind`` so
their class-B handles must differ.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from codeclone.canonical import (
    AnalysisFacts,
    AnalysisFile,
    CandidateRow,
    CanonicalFacts,
    CanonicalModel,
    CanonicalModelError,
    ContractRow,
    CouplingCohesionRow,
    DependencyOccurrenceRow,
    DependencyRelationRow,
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


def analysis_facts(**families: object) -> CanonicalFacts:
    """The one test spelling of a fact root: families live in the ANALYSIS
    house; the root stays pure composition (ruling variant v)."""
    return CanonicalFacts(analysis=AnalysisFacts(**families))  # type: ignore[arg-type]


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
    # The ratified split (ruling 2026-08-24 §2): the relation is the entity,
    # the occurrence is location evidence bound to it.  Two relations differ
    # only in dependency_type; one relation carries two occurrences that
    # differ only in line (with different payload — binding is occurrence
    # payload, never relation state); one relation has a FILE source (the
    # measured module-less fallback); and one relation carries no occurrence
    # evidence at all — evidence is optional, the entity stands on its own.
    rel_import = DependencyRelationRow(ma, mh, "import")
    rel_from = DependencyRelationRow(ma, mh, "from_import")
    rel_file = DependencyRelationRow(fb, ma, "from_import")
    rel_bare = DependencyRelationRow(mh, ma, "import")  # no occurrence
    dependency_relations = [rel_import, rel_from, rel_file, rel_bare]
    dependency_occurrences = [
        DependencyOccurrenceRow(rel_import, 4, "import_time", False),
        DependencyOccurrenceRow(rel_from, 4, "deferred_function", False),
        # same relation as the first row: differs only in line, and is lazy
        DependencyOccurrenceRow(rel_import, 9, "type_checking", True),
        DependencyOccurrenceRow(rel_file, 2, "lazy_syntax", True),
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
    coupling_cohesion = [
        # F2 (wave 4): two rows on one symbol differ only in dimension, two
        # rows share (dimension, numerator) across symbols, one row lives on
        # the module-less separator-collision file, and numerator 1 sits on
        # the family's floor boundary.
        CouplingCohesionRow(sa, "cbo", 3),
        CouplingCohesionRow(sa, "lcom4", 1),
        CouplingCohesionRow(sc, "cbo", 3),
        CouplingCohesionRow(sb, "instance_variables", 1),
        CouplingCohesionRow(se, "methods", 2),
    ]
    coupled = [frozenset({"Token", "AccessToken"}), frozenset({"Token"})]
    if reverse_insertion:
        contracts = list(reversed(contracts))
        graph_nodes = list(reversed(graph_nodes))
        sink_roles = list(reversed(sink_roles))
        candidates = list(reversed(candidates))
        edges = list(reversed(edges))
        dependency_relations = list(reversed(dependency_relations))
        dependency_occurrences = list(reversed(dependency_occurrences))
        violations = list(reversed(violations))
        coupling_cohesion = list(reversed(coupling_cohesion))
        coupled = list(reversed(coupled))
    return CanonicalModel(
        analyzed_files=frozenset({fa, fb}),
        file_modules=frozenset({FileModuleRelation(fa, ma)}),
        facts=analysis_facts(
            contracts=frozenset(contracts),
            graph_nodes=frozenset(graph_nodes),
            sink_roles=frozenset(sink_roles),
            candidates=frozenset(candidates),
            semantic_edges=frozenset(edges),
            dependency_relations=frozenset(dependency_relations),
            dependency_occurrences=frozenset(dependency_occurrences),
            violations=frozenset(violations),
            coupling_cohesion_observations=frozenset(coupling_cohesion),
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

    The three-house facts split (ruling variant v) deliberately did NOT
    move the wave-1.5 literal (2576 bytes, sha256 cfcf02bf…): the split is
    wire-neutral, proven byte-for-byte across the split commit.  Wave 4's F2
    family then replaced that literal deliberately (2721 bytes, sha256
    67da14d4…): the draft gained ``coupling_cohesion_observations``.

    The ratified dependency split (ruling 2026-08-24 §2) replaced the F2
    literal deliberately — ``dependency_edges`` was rebuilt into the
    ``dependency_relations`` + ``dependency_occurrences`` families, so every
    document's bytes moved — the one announced transition of this commit.
    """
    payload = encode_canonical_json(fixture_model())
    assert len(payload) == 2946
    assert (
        hashlib.sha256(payload).hexdigest()
        == "8cc76938dd6ec350c71a82e31e224da9c629708c1ae4734b0670bd1a3345408a"
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
        "dependency_relations",
        "dependency_occurrences",
        "violations",
        "coupling_cohesion_observations",
    ):
        assert len(getattr(decoded.facts.analysis, field)) == len(
            getattr(model.facts.analysis, field)
        ), field


def test_empty_root_set_is_a_measured_value_not_an_absence() -> None:
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    empty_rows = [
        row for row in decoded.facts.analysis.contracts if row.root_set == frozenset()
    ]
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
    assert "dependency_relations" in document["facts"]
    assert "dependency_occurrences" in document["facts"]
    assert "dependency_edges" not in document["facts"]  # rebuilt, not renamed
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


def test_occurrence_key_components_and_payload_survive_the_round_trip() -> None:
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    occurrences = decoded.facts.analysis.dependency_occurrences
    assert len(occurrences) == 4
    # the evidence line is a row-key component of the occurrence family
    # (never of the relation): two occurrences of ONE relation coexist
    ma, mh = ModuleId("pkg.a"), ModuleId("tools.helper")
    rel_import = DependencyRelationRow(ma, mh, "import")
    lines = {o.line for o in occurrences if o.relation == rel_import}
    assert lines == {4, 9}
    # relations differing only in dependency_type are distinct entities
    types = {
        o.relation.dependency_type
        for o in occurrences
        if (o.relation.source, o.relation.target, o.line) == (ma, mh, 4)
    }
    assert types == {"import", "from_import"}
    # payload survives: the FILE-source occurrence keeps binding and marker
    file_row = next(o for o in occurrences if o.relation.source == FileId("tools/b.py"))
    assert (file_row.binding, file_row.is_lazy) == ("lazy_syntax", True)
    assert {o.is_lazy for o in occurrences} == {True, False}


def test_relation_without_occurrence_evidence_is_representable() -> None:
    """Evidence is optional: the entity (the relation) stands on its own.
    The bare relation of the fixture must survive the round trip while
    carrying zero occurrences."""
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    facts = decoded.facts.analysis
    bare = DependencyRelationRow(ModuleId("tools.helper"), ModuleId("pkg.a"), "import")
    assert bare in facts.dependency_relations
    assert not any(o.relation == bare for o in facts.dependency_occurrences)


def test_dependency_endpoints_ride_the_wire_as_tagged_pairs() -> None:
    document = json.loads(encode_canonical_json(fixture_model()))
    relations = document["facts"]["dependency_relations"]
    occurrences = document["facts"]["dependency_occurrences"]
    for table in (relations, occurrences):
        assert table["source"][0][0] == "file"  # FILE sorts before MODULE
        assert all(pair[0] in ("file", "module") for pair in table["source"])
        assert all(pair[0] == "module" for pair in table["target"])
    # sparse boolean: strictly increasing true positions, occurrences only
    assert occurrences["is_lazy"] == sorted(occurrences["is_lazy"])
    assert len(occurrences["is_lazy"]) == 2
    assert "is_lazy" not in relations
    assert "line" not in relations  # location is evidence, never identity


def test_tied_occurrence_rows_are_ordered_by_line_on_the_wire() -> None:
    """Occurrences tied on their relation MUST order by line.

    Eight tied rows make a set-iteration coincidence practically
    impossible (§6.2): an encoder that drops ``line`` from its sort key
    leaks insertion/iteration order into the wire and this pin reds.
    """
    ma, mb = ModuleId("pkg.a"), ModuleId("pkg.b")
    relation = DependencyRelationRow(ma, mb, "import")
    model = CanonicalModel(
        facts=analysis_facts(
            dependency_relations=frozenset({relation}),
            dependency_occurrences=frozenset(
                DependencyOccurrenceRow(relation, line, "import_time", False)
                for line in (13, 5, 89, 2, 34, 21, 55, 8)
            ),
        )
    )
    document = json.loads(encode_canonical_json(model))
    lines = document["facts"]["dependency_occurrences"]["line"]
    assert lines == sorted(lines)
    assert lines == [2, 5, 8, 13, 21, 34, 55, 89]


def test_sparse_boolean_column_is_omitted_when_no_row_is_true() -> None:
    model = fixture_model()
    eager = frozenset(
        DependencyOccurrenceRow(o.relation, o.line, o.binding, False)
        for o in model.facts.analysis.dependency_occurrences
    )
    facts = analysis_facts(
        contracts=model.facts.analysis.contracts,
        graph_nodes=model.facts.analysis.graph_nodes,
        sink_roles=model.facts.analysis.sink_roles,
        candidates=model.facts.analysis.candidates,
        semantic_edges=model.facts.analysis.semantic_edges,
        dependency_relations=model.facts.analysis.dependency_relations,
        dependency_occurrences=eager,
        violations=model.facts.analysis.violations,
    )
    stripped = CanonicalModel(
        analyzed_files=model.analyzed_files,
        file_modules=model.file_modules,
        facts=facts,
        coupled_sets=model.coupled_sets,
    )
    document = json.loads(encode_canonical_json(stripped))
    assert "is_lazy" not in document["facts"]["dependency_occurrences"]
    decoded = decode_canonical_json(encode_canonical_json(stripped))
    assert all(not o.is_lazy for o in decoded.facts.analysis.dependency_occurrences)


def test_output_facts_order_and_multiplicity_are_facts() -> None:
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    node = next(
        row
        for row in decoded.facts.analysis.graph_nodes
        if row.effect_signature == "gsig-a"
    )
    assert node.output_facts == ("unresolved", "const:int:1", "unresolved")


def test_model_refuses_two_facts_under_one_logical_key() -> None:
    fa = FileId("pkg/a.py")
    sa = SymbolId(fa, "A.run")
    model = CanonicalModel(
        facts=analysis_facts(
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
        facts=analysis_facts(
            contracts=frozenset({ContractRow(sa, "sig", frozenset())}),
            candidates=frozenset(
                {CandidateRow("exact", "shared", frozenset({sa, ghost}))}
            ),
        )
    )
    with pytest.raises(CanonicalModelError, match="FUNCTION role"):
        model.normalize()


def test_model_refuses_two_occurrences_under_one_producer_key() -> None:
    """binding and is_lazy are payload, never key: two occurrences sharing
    the producer's (relation, line) with different payload are refused
    loudly, not last-writer-silenced."""
    ma, mb = ModuleId("pkg.a"), ModuleId("pkg.b")
    relation = DependencyRelationRow(ma, mb, "import")
    model = CanonicalModel(
        facts=analysis_facts(
            dependency_relations=frozenset({relation}),
            dependency_occurrences=frozenset(
                {
                    DependencyOccurrenceRow(relation, 4, "import_time", False),
                    DependencyOccurrenceRow(relation, 4, "deferred_function", False),
                }
            ),
        )
    )
    with pytest.raises(
        CanonicalModelError, match=r"dependency_occurrences\.producer_key"
    ):
        model.normalize()


def test_model_refuses_an_occurrence_without_its_relation() -> None:
    """The occurrence is evidence BOUND to a relation: an occurrence whose
    relation the model does not carry is a dangling evidence row, refused
    loudly — normalization never invents the missing entity."""
    ma, mb = ModuleId("pkg.a"), ModuleId("pkg.b")
    orphan = DependencyOccurrenceRow(
        DependencyRelationRow(ma, mb, "import"), 4, "import_time", False
    )
    model = CanonicalModel(
        facts=analysis_facts(dependency_occurrences=frozenset({orphan}))
    )
    with pytest.raises(CanonicalModelError, match="relation the model does not carry"):
        model.normalize()


def test_occurrence_rows_differing_in_any_key_component_coexist() -> None:
    ma, mb = ModuleId("pkg.a"), ModuleId("pkg.b")
    rel_import = DependencyRelationRow(ma, mb, "import")
    rel_from = DependencyRelationRow(ma, mb, "from_import")
    model = CanonicalModel(
        facts=analysis_facts(
            dependency_relations=frozenset({rel_import, rel_from}),
            dependency_occurrences=frozenset(
                {
                    DependencyOccurrenceRow(rel_import, 4, "import_time", False),
                    DependencyOccurrenceRow(rel_import, 9, "import_time", False),
                    DependencyOccurrenceRow(rel_from, 4, "import_time", False),
                }
            ),
        )
    )
    facts = model.normalize().facts.analysis
    assert len(facts.dependency_occurrences) == 3
    assert len(facts.dependency_relations) == 2


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
        facts=analysis_facts(
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
        facts=analysis_facts(
            contracts=frozenset({ContractRow(sa, "sig", frozenset())}),
            violations=frozenset(
                {_violation("owner_bypass"), _violation("shadow_projection")}
            ),
        )
    )
    assert len(model.normalize().facts.analysis.violations) == 2


def test_model_refuses_two_coupling_rows_under_one_logical_key() -> None:
    """F2 key law: (SYMBOL, dimension) names at most one observation."""
    sa = SymbolId(FileId("pkg/a.py"), "A")
    model = CanonicalModel(
        facts=analysis_facts(
            coupling_cohesion_observations=frozenset(
                {
                    CouplingCohesionRow(sa, "cbo", 3),
                    CouplingCohesionRow(sa, "cbo", 4),
                }
            )
        )
    )
    with pytest.raises(
        CanonicalModelError, match=r"coupling_cohesion_observations\.key"
    ):
        model.normalize()


def test_coupling_rows_differing_in_either_key_component_coexist() -> None:
    sa = SymbolId(FileId("pkg/a.py"), "A")
    sb = SymbolId(FileId("pkg/a.py"), "B")
    model = CanonicalModel(
        facts=analysis_facts(
            coupling_cohesion_observations=frozenset(
                {
                    CouplingCohesionRow(sa, "cbo", 3),
                    CouplingCohesionRow(sa, "lcom4", 3),
                    CouplingCohesionRow(sb, "cbo", 3),
                }
            )
        )
    )
    assert len(model.normalize().facts.analysis.coupling_cohesion_observations) == 3


def test_coupling_row_refuses_a_zero_numerator() -> None:
    """The producer never emits zero (absence means zero); a zero row would
    smuggle the forbidden third state into the family."""
    sa = SymbolId(FileId("pkg/a.py"), "A")
    with pytest.raises(CanonicalModelError, match="numerator"):
        CouplingCohesionRow(sa, "cbo", 0)


def test_coupling_row_refuses_an_unknown_dimension() -> None:
    sa = SymbolId(FileId("pkg/a.py"), "A")
    with pytest.raises(CanonicalModelError, match="dimension"):
        CouplingCohesionRow(sa, "banana", 1)


def test_coupling_row_refuses_a_boolean_numerator() -> None:
    sa = SymbolId(FileId("pkg/a.py"), "A")
    with pytest.raises(CanonicalModelError, match="numerator"):
        CouplingCohesionRow(sa, "cbo", True)


def test_tied_coupling_rows_are_ordered_by_dimension_on_the_wire() -> None:
    """Rows tied on the symbol MUST order by dimension bytes.

    Eight tied rows across two symbols make a set-iteration coincidence
    practically impossible (§6.2, the dependency-line precedent verbatim):
    an encoder that drops ``dimension`` from its sort key leaks iteration
    order into the wire and this pin reds.
    """
    sa = SymbolId(FileId("pkg/a.py"), "A")
    sb = SymbolId(FileId("pkg/a.py"), "B")
    model = CanonicalModel(
        facts=analysis_facts(
            coupling_cohesion_observations=frozenset(
                CouplingCohesionRow(symbol, dimension, 2)
                for symbol in (sa, sb)
                for dimension in ("cbo", "instance_variables", "lcom4", "methods")
            )
        )
    )
    document = json.loads(encode_canonical_json(model))
    table = document["facts"]["coupling_cohesion_observations"]
    assert table["dimension"] == [
        "cbo",
        "instance_variables",
        "lcom4",
        "methods",
        "cbo",
        "instance_variables",
        "lcom4",
        "methods",
    ]
    assert table["symbol"] == [0, 0, 0, 0, 1, 1, 1, 1]


def test_model_refuses_a_violation_sink_without_the_function_role() -> None:
    sa = SymbolId(FileId("pkg/a.py"), "A.run")
    row = _violation("owner_bypass")
    model = CanonicalModel(
        facts=analysis_facts(
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

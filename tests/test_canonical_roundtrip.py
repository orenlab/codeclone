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
    ApiParameterFact,
    ApiSymbolRow,
    CandidateRow,
    CanonicalFacts,
    CanonicalModel,
    CanonicalModelError,
    CloneGroupRow,
    CloneItemRow,
    ContractRow,
    CouplingCohesionRow,
    DeadCodeObservationRow,
    DependencyCycleRow,
    DependencyOccurrenceRow,
    DependencyRelationRow,
    EffectLabelRoot,
    EffectRoot,
    FileId,
    FileModuleRelation,
    GraphNodeRow,
    KnownModule,
    ModuleId,
    ModuleSymbol,
    OpaqueDottedHead,
    OpaqueEntity,
    OperationRoot,
    OperationTarget,
    ProducerRoot,
    RiskObservationRow,
    RunScalars,
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
    sy = SymbolId(fb, "clone_only")  # referenced only by a clone item
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
    # F7 (wave 4): one row per module set, kind classified once.  The two
    # rows share a module (their sets overlap without being equal), the
    # deferred 3-cycle carries a module referenced by NO other family (the
    # closure must admit it), and both producer kinds are present.
    mz = ModuleId("zz.top")
    dependency_cycles = [
        DependencyCycleRow("import_cycle", frozenset({ma, mh})),
        DependencyCycleRow("deferred_cycle", frozenset({ma, mh, mz})),
    ]
    # F8 (wave 4): the EMITTED population only.  The block group's three
    # items include an intra-function pair (one SYMBOL, two spans) — group
    # arity and item identity are different measurements; the segment group
    # shares its producer key STRING with the function group, so the kind
    # is proven to be a key component, not a display label.
    clone_groups = [
        CloneGroupRow(
            "function",
            "aa11|0-19",
            frozenset({CloneItemRow(sa, 4, 16), CloneItemRow(se, 19, 31)}),
        ),
        CloneGroupRow(
            "block",
            "bb22|bb22|bb22|bb22",
            frozenset(
                {
                    CloneItemRow(sb, 13, 48),
                    CloneItemRow(sb, 53, 67),  # intra-function pair
                    CloneItemRow(sc, 9, 41),
                }
            ),
        ),
        CloneGroupRow(
            "segment",
            "aa11|0-19",  # same producer key string as the function group
            # sy is referenced by NO other family: the closure must admit
            # a clone-only symbol into the SYMBOL domain on its own.
            frozenset({CloneItemRow(sa, 5, 9), CloneItemRow(sy, 7, 11)}),
        ),
    ]
    # F4 (wave 4, slice K3): the tagged entity union with every variant
    # populated.  One MODULE-headed entity carries BOTH observation kinds
    # (the kind is a key component); its module exists in no other family
    # (the closure must admit it); one FILE-headed row rides a symbol
    # referenced nowhere else; the opaque variant is contract-declared and
    # carried here even while corpus-unpopulated (unpopulated tags stay).
    md = ModuleId("dead.only")
    sz = SymbolId(fc, "dead_probe")  # referenced only by a dead-code row
    dead_code_observations = [
        DeadCodeObservationRow(
            entity=ModuleSymbol(md, "Exported.helper"),
            observation_kind="symbol",
            candidate_kind="method",
            reference_count=1,
            reachable=False,
            runtime_marker_count=0,
            source_markers=(),
            live_root_reason="export_root",
            abstained=False,
        ),
        DeadCodeObservationRow(
            entity=ModuleSymbol(md, "Exported.helper"),
            observation_kind="unreachable_statement",
            candidate_kind="function",
            reference_count=0,
            reachable=False,
            runtime_marker_count=0,
            source_markers=(("unreachable_reason", "after_terminator"),),
            live_root_reason=None,
            abstained=False,
        ),
        DeadCodeObservationRow(
            entity=sz,
            observation_kind="symbol",
            candidate_kind="function",
            reference_count=0,
            reachable=True,
            runtime_marker_count=3,
            source_markers=(("aa", "bb"), ("cc", "dd")),
            live_root_reason=None,
            abstained=False,
        ),
        DeadCodeObservationRow(
            entity=SymbolId(fa, "A.maybe"),
            observation_kind="symbol",
            candidate_kind="method",
            reference_count=0,
            reachable=False,
            runtime_marker_count=0,
            source_markers=(),
            live_root_reason=None,
            abstained=True,
        ),
        DeadCodeObservationRow(
            entity=OpaqueEntity("ext.vendor.mod", "Shim.call"),
            observation_kind="symbol",
            candidate_kind="import",
            reference_count=2,
            reachable=False,
            runtime_marker_count=0,
            source_markers=(),
            live_root_reason="external_decorator",
            abstained=False,
        ),
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
    api_symbols = [
        # F5 (wave 4): the measured @overload class verbatim — one SYMBOL,
        # two canonical signature variants; the bare (FILE, symbol) key
        # loses one of these two rows, the ratified key keeps both.
        ApiSymbolRow(
            sb,
            "function",
            "name",
            (ApiParameterFact("value", "pos_or_kw", False, "aa" * 32),),
            "bb" * 32,
        ),
        ApiSymbolRow(
            sb,
            "function",
            "name",
            (
                ApiParameterFact("value", "pos_or_kw", False, None),
                ApiParameterFact("extra", "kw_only", True, "cc" * 32),
            ),
            None,
        ),
        # a class on the module-less separator-collision file, no signature
        ApiSymbolRow(se, "class", "all", (), None),
        # a constant: a return digest with zero parameters
        ApiSymbolRow(sc, "constant", "all", (), "dd" * 32),
        # a method covering the remaining parameter kinds
        ApiSymbolRow(
            sa,
            "method",
            "name",
            (
                ApiParameterFact("self", "pos_only", False, None),
                ApiParameterFact("args", "vararg", False, None),
                ApiParameterFact("kw", "kwarg", False, None),
            ),
            None,
        ),
    ]
    risk_observations = [
        # F1 (fork (b)): the measured @overload class verbatim — one
        # (symbol, dimension) pair, two declaration sites with EQUAL
        # measures; the site-blind key loses one of these two rows, the
        # ratified key keeps both.
        RiskObservationRow(sa, "cyclomatic_complexity", 7, 10),
        RiskObservationRow(sa, "cyclomatic_complexity", 7, 40),
        # the same declaration's second dimension
        RiskObservationRow(sa, "nesting_depth", 2, 10),
        # a row on the module-less separator-collision file, with the
        # numerator and the site both on the family floor boundary (1/1)
        RiskObservationRow(se, "nesting_depth", 1, 1),
    ]
    # F9 (wave 4): ONE run-scalars record per analysis snapshot — never a
    # table, no invented entity key.  Values pairwise distinct so a
    # cross-wired producer mapping cannot survive, and one zero: zero is a
    # MEASURED value here (unlike the F2 floor).
    run_scalars = RunScalars(
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
    coupled = [frozenset({"Token", "AccessToken"}), frozenset({"Token"})]
    if reverse_insertion:
        contracts = list(reversed(contracts))
        graph_nodes = list(reversed(graph_nodes))
        sink_roles = list(reversed(sink_roles))
        candidates = list(reversed(candidates))
        edges = list(reversed(edges))
        dependency_relations = list(reversed(dependency_relations))
        dependency_occurrences = list(reversed(dependency_occurrences))
        dependency_cycles = list(reversed(dependency_cycles))
        clone_groups = list(reversed(clone_groups))
        dead_code_observations = list(reversed(dead_code_observations))
        violations = list(reversed(violations))
        coupling_cohesion = list(reversed(coupling_cohesion))
        api_symbols = list(reversed(api_symbols))
        risk_observations = list(reversed(risk_observations))
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
            dependency_cycles=frozenset(dependency_cycles),
            clone_groups=frozenset(clone_groups),
            dead_code_observations=frozenset(dead_code_observations),
            violations=frozenset(violations),
            coupling_cohesion_observations=frozenset(coupling_cohesion),
            api_symbols=frozenset(api_symbols),
            risk_observations=frozenset(risk_observations),
            run_scalars=run_scalars,
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
    literal deliberately (2946 bytes, sha256 8cc76938…): ``dependency_edges``
    was rebuilt into the ``dependency_relations`` + ``dependency_occurrences``
    families.  Wave 4's F5 family then replaced that literal deliberately
    (3906 bytes, sha256 4db95d8e…): the draft gained ``api_symbols`` with
    its contract-derived ``signature_variant`` column.  Wave 4's F9 family
    then replaced that literal deliberately (4107 bytes, sha256 3f4af32e…):
    the draft gained the ``run_scalars`` record member.  The F1
    ``risk_observations`` family (ruling 2026-08-26, fork (b)) then
    replaced the F9 literal deliberately: the draft gained the
    declaration-site keyed risk family (4290 bytes, sha256 873a0a42…).
    The F7 ``dependency_cycles`` family (slice 4, K1) then replaced the F1
    literal deliberately (4388 bytes, sha256 bdd06ad1…): the draft gained
    the module-set keyed cycle family.  The F8 ``clone_groups`` family
    (slice 4, K2) then replaced the K1 literal deliberately (4605 bytes,
    sha256 db810d3d…): the draft gained the emitted clone-group family.
    The F4 ``dead_code_observations`` family (slice 4, K3) then replaced
    the K2 literal deliberately: the draft gained the tagged-entity dead
    code family, so every document's bytes moved — the one announced
    transition of this commit.
    """
    payload = encode_canonical_json(fixture_model())
    assert len(payload) == 5219
    assert (
        hashlib.sha256(payload).hexdigest()
        == "073e3f58d1e1117b4c50705d211c0fe3af7e6dcc1a66a174d9cf3acead6f6297"
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
        "dependency_cycles",
        "clone_groups",
        "dead_code_observations",
        "violations",
        "coupling_cohesion_observations",
        "api_symbols",
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


def test_api_overload_variants_coexist_under_one_symbol() -> None:
    """The F5 raison d'être: the measured @overload class — one SYMBOL, two
    canonical signature variants — survives the round trip as TWO rows.
    The bare (FILE, symbol) key measured 10 140/10 143 loses them."""
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    sb = SymbolId(FileId("tools/b.py"), "helper")
    overloads = [row for row in decoded.facts.analysis.api_symbols if row.symbol == sb]
    assert len(overloads) == 2
    assert {row.returns_digest for row in overloads} == {"bb" * 32, None}


def test_model_refuses_two_api_symbols_under_one_signature_key() -> None:
    """(SYMBOL, canonical_signature_variant) names at most one fact:
    symbol_kind and visibility are payload, never key."""
    sa = SymbolId(FileId("pkg/a.py"), "A")
    signature = (ApiParameterFact("value", "pos_or_kw", False, None),)
    model = CanonicalModel(
        facts=analysis_facts(
            api_symbols=frozenset(
                {
                    ApiSymbolRow(sa, "function", "name", signature, None),
                    ApiSymbolRow(sa, "class", "all", signature, None),
                }
            )
        )
    )
    with pytest.raises(CanonicalModelError, match=r"api_symbols\.key"):
        model.normalize()


def test_api_symbols_differing_in_any_signature_component_coexist() -> None:
    """Every signature component moves the variant: parameter name, kind,
    default marker, annotation digest, and the return digest each separate
    two rows on one SYMBOL."""
    sa = SymbolId(FileId("pkg/a.py"), "A")
    base = ApiParameterFact("value", "pos_or_kw", False, None)
    rows = {
        ApiSymbolRow(sa, "function", "name", (base,), None),
        ApiSymbolRow(
            sa,
            "function",
            "name",
            (ApiParameterFact("other", "pos_or_kw", False, None),),
            None,
        ),
        ApiSymbolRow(
            sa,
            "function",
            "name",
            (ApiParameterFact("value", "kw_only", False, None),),
            None,
        ),
        ApiSymbolRow(
            sa,
            "function",
            "name",
            (ApiParameterFact("value", "pos_or_kw", True, None),),
            None,
        ),
        ApiSymbolRow(
            sa,
            "function",
            "name",
            (ApiParameterFact("value", "pos_or_kw", False, "ee" * 32),),
            None,
        ),
        ApiSymbolRow(sa, "function", "name", (base,), "ff" * 32),
    }
    model = CanonicalModel(facts=analysis_facts(api_symbols=frozenset(rows)))
    assert len(model.normalize().facts.analysis.api_symbols) == 6


def test_tied_api_symbol_rows_are_ordered_by_variant_on_the_wire() -> None:
    """Rows tied on the symbol MUST order by signature-variant bytes.

    Eight tied rows across one symbol make a set-iteration coincidence
    practically impossible (§6.2, the dependency-line precedent verbatim):
    an encoder that drops the variant from its sort key leaks iteration
    order into the wire and this pin reds.
    """
    sa = SymbolId(FileId("pkg/a.py"), "A")
    model = CanonicalModel(
        facts=analysis_facts(
            api_symbols=frozenset(
                ApiSymbolRow(
                    sa,
                    "function",
                    "name",
                    (ApiParameterFact(f"p{index}", "pos_or_kw", False, None),),
                    None,
                )
                for index in range(8)
            )
        )
    )
    document = json.loads(encode_canonical_json(model))
    table = document["facts"]["api_symbols"]
    assert table["symbol"] == [0] * 8
    variants = table["signature_variant"]
    assert len(set(variants)) == 8
    assert variants == sorted(variants)


def test_api_parameter_cell_omits_an_absent_annotation_on_the_wire() -> None:
    """The producer's own bijection (``_component_digest``): an absent
    annotation digest is a 3-element cell, a present one a 4-element cell —
    absence is never spelled as a value."""
    document = json.loads(encode_canonical_json(fixture_model()))
    table = document["facts"]["api_symbols"]
    cells = [cell for row in table["parameters"] for cell in row]
    assert {len(cell) for cell in cells} == {3, 4}
    assert all(cell[2] in (0, 1) for cell in cells)
    # returns_digest spells absence as the empty string, never as null
    assert "" in table["returns_digest"]
    assert any(value for value in table["returns_digest"])


def test_run_scalars_record_survives_the_round_trip() -> None:
    """F9: the ONE record per snapshot round-trips verbatim — every scalar,
    the measured zero included."""
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    record = decoded.facts.analysis.run_scalars
    assert record is not None
    assert record == RunScalars(
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


def test_absent_run_scalars_is_the_empty_member_never_a_zero_record() -> None:
    """A model carrying no run-scalars record encodes the EMPTY member and
    decodes back to None — absence is never spelled as an all-zero record
    (zero is a measured value in this family)."""
    model = CanonicalModel(
        facts=analysis_facts(
            contracts=frozenset(
                {ContractRow(SymbolId(FileId("pkg/a.py"), "f"), "sig", frozenset())}
            )
        )
    )
    document = json.loads(encode_canonical_json(model))
    assert document["facts"]["run_scalars"] == {}
    decoded = decode_canonical_json(encode_canonical_json(model))
    assert decoded.facts.analysis.run_scalars is None


def test_run_scalars_wire_member_is_one_record_object() -> None:
    """The wire member is a record object in canonical column order — not a
    columnar table: no rows, no invented entity key."""
    document = json.loads(encode_canonical_json(fixture_model()))
    member = document["facts"]["run_scalars"]
    assert isinstance(member, dict)
    assert list(member.keys()) == sorted(member.keys())
    assert all(isinstance(value, int) for value in member.values())
    assert member["files_skipped"] == 0  # measured zero rides the wire


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("files_found", -1), ("classes", True)],
)
def test_run_scalars_refuses_non_scalar_values(field_name: str, value: object) -> None:
    values: dict[str, object] = {
        "classes": 7,
        "files_analyzed": 2,
        "files_cached": 1,
        "files_found": 3,
        "files_skipped": 0,
        "functions": 41,
        "methods": 13,
        "parsed_lines": 905,
        "source_io_skipped": 4,
        "unsupported_construct_skipped": 5,
    }
    values[field_name] = value
    with pytest.raises(CanonicalModelError, match="run scalar"):
        RunScalars(**values)  # type: ignore[arg-type]


def test_model_refuses_two_cycle_kinds_on_one_module_set() -> None:
    """F7 family law (corpus-pinned): ONE row per module set, the kind
    classified exactly once.  Two rows disagreeing only in kind are a
    producer defect — a deferred back-edge over a pair that already carries
    an import-time cycle never births a second row."""
    ma, mb = ModuleId("pkg.a"), ModuleId("pkg.b")
    model = CanonicalModel(
        facts=analysis_facts(
            dependency_cycles=frozenset(
                {
                    DependencyCycleRow("import_cycle", frozenset({ma, mb})),
                    DependencyCycleRow("deferred_cycle", frozenset({ma, mb})),
                }
            )
        )
    )
    with pytest.raises(CanonicalModelError, match=r"dependency_cycles\.modules"):
        model.normalize()


def test_cycle_rows_differing_in_module_set_coexist() -> None:
    """The module SET names the entity: overlapping sets — even a strict
    subset next to its superset — are distinct cycles."""
    ma, mb, mc = ModuleId("pkg.a"), ModuleId("pkg.b"), ModuleId("pkg.c")
    model = CanonicalModel(
        facts=analysis_facts(
            dependency_cycles=frozenset(
                {
                    DependencyCycleRow("import_cycle", frozenset({ma, mb})),
                    DependencyCycleRow("import_cycle", frozenset({ma, mb, mc})),
                    DependencyCycleRow("deferred_cycle", frozenset({ma, mc})),
                }
            )
        )
    )
    normalized = model.normalize()
    assert len(normalized.facts.analysis.dependency_cycles) == 3
    # the closure admits every cycle member into the MODULE domain
    assert {ma, mb, mc} <= normalized.modules


def test_cycle_row_refuses_an_unknown_kind() -> None:
    with pytest.raises(CanonicalModelError, match="cycle kind"):
        DependencyCycleRow("banana", frozenset({ModuleId("a"), ModuleId("b")}))


def test_cycle_row_refuses_fewer_than_two_modules() -> None:
    """The producer's Tarjan floor (``len(component) > 1``): a cycle names
    at least two modules; a one-module row asserts a self-loop the producer
    never emits."""
    with pytest.raises(CanonicalModelError, match="at least two"):
        DependencyCycleRow("import_cycle", frozenset({ModuleId("pkg.a")}))


def test_cycle_rows_are_ordered_by_module_set_on_the_wire() -> None:
    """Wire row order is the module-set ordinal tuple — the entity key.

    The kind deliberately does NOT enter the sort key: one set carries one
    row, so kind can never be a tiebreaker; an encoder that sorts by kind
    first leaks the classification into row order and this pin reds.
    """
    ma, mb, mc, md = (ModuleId(f"pkg.{c}") for c in "abcd")
    # The middle row's kind sorts BEFORE the first row's kind while its
    # module set sorts after: a kind-first encoder reorders these rows and
    # the pin reds directly, not only through the byte sentinel.
    model = CanonicalModel(
        facts=analysis_facts(
            dependency_cycles=frozenset(
                {
                    DependencyCycleRow("import_cycle", frozenset({ma, mb})),
                    DependencyCycleRow("deferred_cycle", frozenset({ma, mc})),
                    DependencyCycleRow("import_cycle", frozenset({mc, md})),
                }
            )
        )
    )
    document = json.loads(encode_canonical_json(model))
    table = document["facts"]["dependency_cycles"]
    assert table["modules"] == [[0, 1], [0, 2], [2, 3]]
    assert table["kind"] == ["import_cycle", "deferred_cycle", "import_cycle"]


def test_cycle_member_paths_never_reach_the_wire() -> None:
    """``member_paths`` is the registry's FILE-MODULE projection — a table,
    never a column (§2.3), declared representation_projection: the wire
    member carries exactly the kind and the module set."""
    document = json.loads(encode_canonical_json(fixture_model()))
    table = document["facts"]["dependency_cycles"]
    assert list(table.keys()) == ["kind", "modules"]


def test_cycle_family_survives_the_round_trip() -> None:
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    ma, mh, mz = ModuleId("pkg.a"), ModuleId("tools.helper"), ModuleId("zz.top")
    assert decoded.facts.analysis.dependency_cycles == frozenset(
        {
            DependencyCycleRow("import_cycle", frozenset({ma, mh})),
            DependencyCycleRow("deferred_cycle", frozenset({ma, mh, mz})),
        }
    )
    # the closure-only module (no other family references it) survived
    assert mz in decoded.modules


def _clone_items(*spans: tuple[int, int]) -> frozenset[CloneItemRow]:
    sa = SymbolId(FileId("pkg/a.py"), "A.run")
    return frozenset(CloneItemRow(sa, start, end) for start, end in spans)


def test_model_refuses_two_clone_groups_under_one_key() -> None:
    """F8 key law: (clone_kind, producer group_key) names at most one
    group; two groups sharing the key with different members are a
    producer defect, refused loudly."""
    model = CanonicalModel(
        facts=analysis_facts(
            clone_groups=frozenset(
                {
                    CloneGroupRow("function", "k1", _clone_items((1, 5), (9, 13))),
                    CloneGroupRow("function", "k1", _clone_items((1, 5), (20, 24))),
                }
            )
        )
    )
    with pytest.raises(CanonicalModelError, match=r"clone_groups\.key"):
        model.normalize()


def test_clone_groups_sharing_a_key_string_across_kinds_coexist() -> None:
    """The kind is a KEY component: one producer key string under two clone
    kinds is two entities, never a collision."""
    model = CanonicalModel(
        facts=analysis_facts(
            clone_groups=frozenset(
                {
                    CloneGroupRow("function", "k1", _clone_items((1, 5), (9, 13))),
                    CloneGroupRow("segment", "k1", _clone_items((1, 5), (9, 13))),
                }
            )
        )
    )
    assert len(model.normalize().facts.analysis.clone_groups) == 2


def test_clone_group_refuses_an_unknown_kind() -> None:
    with pytest.raises(CanonicalModelError, match="clone kind"):
        CloneGroupRow("banana", "k1", _clone_items((1, 5), (9, 13)))


def test_clone_group_refuses_an_empty_group_key() -> None:
    with pytest.raises(CanonicalModelError, match="group key"):
        CloneGroupRow("function", "", _clone_items((1, 5), (9, 13)))


def test_clone_group_refuses_fewer_than_two_items() -> None:
    """A group of one is not a group: every producer tier emits groups of
    at least two occurrences — a single-item row asserts a grouping the
    detector never made."""
    with pytest.raises(CanonicalModelError, match="at least two"):
        CloneGroupRow("function", "k1", _clone_items((1, 5)))


def test_clone_item_refuses_degenerate_spans() -> None:
    sa = SymbolId(FileId("pkg/a.py"), "A.run")
    with pytest.raises(CanonicalModelError, match="start line"):
        CloneItemRow(sa, 0, 5)
    with pytest.raises(CanonicalModelError, match="end line"):
        CloneItemRow(sa, 5, 4)


def test_intra_function_pair_is_two_items_not_one() -> None:
    """The corpus-pinned measurement: group arity and item identity are
    different dimensions — one SYMBOL with two spans is two members."""
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    block = next(
        row for row in decoded.facts.analysis.clone_groups if row.clone_kind == "block"
    )
    assert len(block.items) == 3
    assert len({item.symbol for item in block.items}) == 2


def test_clone_groups_are_ordered_by_kind_then_key_on_the_wire() -> None:
    """Row order is the (clone_kind, group_key) byte key, and every item
    cell is sorted by (symbol ordinal, start, end) — an encoder that leaks
    set iteration order into either level reds here."""
    document = json.loads(encode_canonical_json(fixture_model()))
    table = document["facts"]["clone_groups"]
    assert table["clone_kind"] == ["block", "function", "segment"]
    assert table["group_key"] == ["bb22|bb22|bb22|bb22", "aa11|0-19", "aa11|0-19"]
    for cells in table["items"]:
        assert cells == sorted(cells)
    # the intra-function pair rides one symbol ordinal with two spans
    block_cells = table["items"][0]
    assert len(block_cells) == 3
    assert block_cells[1][0] == block_cells[2][0]


def test_tied_clone_groups_are_ordered_by_group_key_on_the_wire() -> None:
    """Rows tied on the kind MUST order by group_key bytes: an encoder
    that drops the key from its sort leaks set iteration order into the
    wire and this pin reds (the F2 tied-row precedent verbatim)."""
    model = CanonicalModel(
        facts=analysis_facts(
            clone_groups=frozenset(
                CloneGroupRow("function", key, _clone_items((1, 5), (9, 13)))
                for key in ("cc33", "aa11", "bb22", "ee55", "dd44")
            )
        )
    )
    document = json.loads(encode_canonical_json(model))
    table = document["facts"]["clone_groups"]
    assert table["group_key"] == ["aa11", "bb22", "cc33", "dd44", "ee55"]
    assert table["clone_kind"] == ["function"] * 5


def test_clone_only_symbol_enters_the_domain_through_the_closure() -> None:
    """A symbol referenced by nothing but a clone item still reaches the
    SYMBOL domain — a closure that skips the clone family reds here."""
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    clone_only = SymbolId(FileId("tools/b.py"), "clone_only")
    segment = next(
        row
        for row in decoded.facts.analysis.clone_groups
        if row.clone_kind == "segment"
    )
    assert clone_only in {item.symbol for item in segment.items}


def test_clone_family_survives_the_round_trip() -> None:
    model = fixture_model().normalize()
    decoded = decode_canonical_json(encode_canonical_json(model))
    assert decoded.facts.analysis.clone_groups == model.facts.analysis.clone_groups


def _dead_row(
    entity: object,
    observation_kind: str = "symbol",
    **overrides: object,
) -> DeadCodeObservationRow:
    values: dict[str, object] = {
        "entity": entity,
        "observation_kind": observation_kind,
        "candidate_kind": "function",
        "reference_count": 0,
        "reachable": False,
        "runtime_marker_count": 0,
        "source_markers": (),
        "live_root_reason": None,
        "abstained": False,
    }
    values.update(overrides)
    return DeadCodeObservationRow(**values)  # type: ignore[arg-type]


def test_model_refuses_two_dead_rows_under_one_entity_and_kind() -> None:
    """F4 key law: (entity, observation_kind) names at most one fact; two
    DIFFERING rows under one key are refused (the one measured
    byte-identical duplicate merges losslessly instead)."""
    entity = ModuleSymbol(ModuleId("pkg.m"), "f")
    model = CanonicalModel(
        facts=analysis_facts(
            dead_code_observations=frozenset(
                {
                    _dead_row(entity, reference_count=0),
                    _dead_row(entity, reference_count=1),
                }
            )
        )
    )
    with pytest.raises(CanonicalModelError, match=r"dead_code_observations\.key"):
        model.normalize()


def test_one_qualname_under_two_entity_variants_is_two_facts() -> None:
    """The union's raison d'etre: the VARIANT is identity — a MODULE-headed
    reference and the FILE-headed SYMBOL of the same qualname are two
    entities, never normalized into one."""
    model = CanonicalModel(
        facts=analysis_facts(
            dead_code_observations=frozenset(
                {
                    _dead_row(ModuleSymbol(ModuleId("pkg.m"), "helper")),
                    _dead_row(SymbolId(FileId("pkg/m.py"), "helper")),
                    _dead_row(OpaqueEntity("pkg.m", "helper")),
                }
            )
        )
    )
    assert len(model.normalize().facts.analysis.dead_code_observations) == 3


def test_same_entity_under_two_observation_kinds_is_two_facts() -> None:
    entity = ModuleSymbol(ModuleId("pkg.m"), "f")
    model = CanonicalModel(
        facts=analysis_facts(
            dead_code_observations=frozenset(
                {
                    _dead_row(entity, "symbol"),
                    _dead_row(entity, "unreachable_statement"),
                }
            )
        )
    )
    assert len(model.normalize().facts.analysis.dead_code_observations) == 2


def test_dead_row_refuses_vocabulary_and_contract_violations() -> None:
    entity = ModuleSymbol(ModuleId("pkg.m"), "f")
    with pytest.raises(CanonicalModelError, match="observation kind"):
        _dead_row(entity, "banana")
    with pytest.raises(CanonicalModelError, match="candidate kind"):
        _dead_row(entity, candidate_kind="banana")
    with pytest.raises(CanonicalModelError, match="non-negative"):
        _dead_row(entity, reference_count=-1)
    with pytest.raises(CanonicalModelError, match="sorted and unique"):
        _dead_row(entity, source_markers=(("b", "1"), ("a", "2")))
    with pytest.raises(CanonicalModelError, match="live root reason"):
        _dead_row(entity, live_root_reason="banana")
    with pytest.raises(CanonicalModelError, match="mutually exclusive"):
        _dead_row(entity, live_root_reason="export_root", abstained=True)


def test_dead_entities_ride_the_wire_as_tagged_slots() -> None:
    """The variant tag is EMITTED — module and opaque slots carry their
    head and qualname, the FILE variant interns through the SYMBOL domain,
    and absence of a live root is the empty string, never null."""
    document = json.loads(encode_canonical_json(fixture_model()))
    table = document["facts"]["dead_code_observations"]
    tags = [slot[0] for slot in table["entity"]]
    assert tags == ["module", "module", "opaque", "symbol", "symbol"]
    assert table["entity"][0] == ["module", 0, "Exported.helper"]
    assert table["entity"][2] == ["opaque", "ext.vendor.mod", "Shim.call"]
    assert table["observation_kind"][0] == "symbol"
    assert table["observation_kind"][1] == "unreachable_statement"
    assert table["live_root_reason"] == [
        "export_root",
        "",
        "external_decorator",
        "",
        "",
    ]
    assert table["abstained"] == [3]
    assert table["reachable"] == [4]
    assert table["source_markers"][1] == [["unreachable_reason", "after_terminator"]]


def test_tied_dead_rows_are_ordered_by_observation_kind_on_the_wire() -> None:
    """Rows tied on the entity MUST order by observation kind.

    Eight tied pairs make a set-iteration coincidence practically
    impossible (§6.2, the dependency-line precedent verbatim; measured
    during K3: with ONE tied pair the kind-blind encoder survived
    PYTHONHASHSEED=2) — an encoder that drops the kind from its sort key
    leaks iteration order into the wire and this pin reds."""
    entities = [ModuleSymbol(ModuleId(f"pkg.m{index}"), "f") for index in range(8)]
    model = CanonicalModel(
        facts=analysis_facts(
            dead_code_observations=frozenset(
                _dead_row(entity, kind)
                for entity in entities
                for kind in ("symbol", "unreachable_statement")
            )
        )
    )
    document = json.loads(encode_canonical_json(model))
    table = document["facts"]["dead_code_observations"]
    assert table["observation_kind"] == ["symbol", "unreachable_statement"] * 8


def test_dead_code_family_survives_the_round_trip() -> None:
    model = fixture_model().normalize()
    decoded = decode_canonical_json(encode_canonical_json(model))
    assert (
        decoded.facts.analysis.dead_code_observations
        == model.facts.analysis.dead_code_observations
    )
    # the dead-only module and the dead-only FILE symbol entered the domains
    assert ModuleId("dead.only") in decoded.modules


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


def test_model_refuses_two_risk_rows_under_one_declaration_key() -> None:
    """F1 key law: (SYMBOL, dimension, start_line) names at most one fact."""
    sa = SymbolId(FileId("pkg/a.py"), "A.run")
    model = CanonicalModel(
        facts=analysis_facts(
            risk_observations=frozenset(
                {
                    RiskObservationRow(sa, "cyclomatic_complexity", 3, 10),
                    RiskObservationRow(sa, "cyclomatic_complexity", 4, 10),
                }
            )
        )
    )
    with pytest.raises(CanonicalModelError, match=r"risk_observations\.key"):
        model.normalize()


def test_risk_rows_differing_only_in_declaration_site_coexist() -> None:
    """The F1 resolution itself: the measured @overload shape — equal in
    symbol, dimension AND numerator — is two facts under the ratified key,
    where the site-blind key had made deduplication indefensible."""
    sa = SymbolId(FileId("pkg/a.py"), "parse_args")
    model = CanonicalModel(
        facts=analysis_facts(
            risk_observations=frozenset(
                {
                    RiskObservationRow(sa, "cyclomatic_complexity", 7, 10),
                    RiskObservationRow(sa, "cyclomatic_complexity", 7, 40),
                }
            )
        )
    )
    assert len(model.normalize().facts.analysis.risk_observations) == 2


def test_tied_risk_rows_are_ordered_by_site_on_the_wire() -> None:
    """Rows tied on (symbol, dimension) MUST order by declaration site.

    An encoder that drops ``start_line`` from its sort key leaks set
    iteration order into the wire and this pin reds (the F2 tied-row
    precedent verbatim, one key component further down).
    """
    sa = SymbolId(FileId("pkg/a.py"), "parse_args")
    sites = (40, 10, 25, 90, 55, 70)
    model = CanonicalModel(
        facts=analysis_facts(
            risk_observations=frozenset(
                RiskObservationRow(sa, dimension, 2, site)
                for dimension in ("cyclomatic_complexity", "nesting_depth")
                for site in sites
            )
        )
    )
    document = json.loads(encode_canonical_json(model))
    table = document["facts"]["risk_observations"]
    assert table["start_line"] == sorted(sites) + sorted(sites)
    assert table["dimension"] == (["cyclomatic_complexity"] * 6 + ["nesting_depth"] * 6)
    assert table["symbol"] == [0] * 12

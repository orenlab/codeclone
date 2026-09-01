# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The sink and violation row projections, measured column by column.

The candidate wave closed its seven columns and left sixteen: nine on
``authority.sinks``, seven on ``authority.violations``.  This module is
where each one is settled -- not by declaring it derivable, but by
rebuilding the published row out of stored facts and comparing it with the
row the report path published, byte for byte through the product's own
serializer.

Fifteen close.  ``locations`` does not, and the difference is the S8.V.3
test the model docstrings already cite: derivability is a property of the
``(value, place)`` pair.  A sink's ``effect_signature`` is derivable HERE
because the producer reads it off the very entry it built the graph node
from, and that node is stored.  A violation's ``locations`` is not,
because its basis is ``FunctionContractSummary.events`` -- a stream this
subject carries no family for.

The value pins below are not redundant with the equality above.  Both
readings of a root string share one owner (``canonical.semantic_grammar``),
so a mutation inside that owner moves BOTH sides and a cross-reading
equality stays green: consistency is not correctness.  Each rendering rule
therefore keeps one literal pin on what it produced.
"""

from __future__ import annotations

from typing import cast

import orjson
import pytest

from codeclone.canonical.authority_projection import (
    VIOLATION_UNPROJECTED_COLUMNS,
    sink_projection_rows,
    violation_projection_rows,
)
from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.identity import (
    DOMAIN_TAG_FILE,
    LOCATION_TAG_UNRESOLVED,
    VIOLATION_KINDS,
    AnalysisFile,
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
    SymbolId,
    UnresolvedLocation,
    UnresolvedRoot,
    source_location_key,
)
from codeclone.canonical.model import (
    AnalysisFacts,
    CanonicalFacts,
    CanonicalModel,
    FileModuleRelation,
    SinkRoleRow,
    ViolationRow,
)
from codeclone.canonical.semantic_grammar import (
    build_identity_index,
    format_effect_root,
    format_root_set,
    format_source_location,
    parse_effect_root,
    parse_source_locations,
)

from ._projection_equivalence import ProjectionCorpus, build_corpus


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> ProjectionCorpus:
    base = tmp_path_factory.mktemp("authority-projection-rows")
    tree = base / "tree"
    tree.mkdir()
    return build_corpus(tree, store_path=base / "runs.sqlite3")


def _reported(corpus: ProjectionCorpus, kind: str) -> list[dict[str, object]]:
    metrics = cast("dict[str, object]", corpus.document["metrics"])
    families = cast("dict[str, object]", metrics["families"])
    family = cast("dict[str, object]", families["semantic_authority"])
    items = cast("list[dict[str, object]]", family["items"])
    return [dict(item) for item in items if item.get("item_kind") == kind]


# -- the acceptance: the published row, rebuilt -----------------------------


def test_the_sink_projection_rebuilds_the_whole_published_row(
    corpus: ProjectionCorpus,
) -> None:
    """Nine unrepresented columns, closed by comparison rather than claim."""

    reported = _reported(corpus, "sink")
    assert len(reported) > 1, "a one-row population settles no ordering"
    projected = list(sink_projection_rows(corpus.stored_model))
    assert len(projected) == len(reported)
    for report_row, rebuilt in zip(reported, projected, strict=True):
        assert set(rebuilt) == set(report_row)
        assert orjson.dumps(rebuilt) == orjson.dumps(
            {key: rebuilt[key] for key in report_row}
        ), "the rebuilt row disagrees with the builder's key order"
        assert orjson.dumps({key: rebuilt[key] for key in report_row}) == orjson.dumps(
            report_row
        )


def test_the_violation_projection_rebuilds_the_whole_published_row(
    corpus: ProjectionCorpus,
) -> None:
    """All seven close now, ``locations`` included -- byte for byte.

    The wave that measured this lane closed six columns and named the
    seventh: ``locations`` had no stored basis, so the lane stood
    ``partial`` on exactly one column over 26 violations carrying 58
    location evidence points.  The column is stored now, so the comparison
    below is the WHOLE published row and the exemption list is empty.
    """

    reported = _reported(corpus, "violation")
    assert len(reported) > 1, "a one-row population settles no ordering"
    projected = list(violation_projection_rows(corpus.stored_model))
    assert len(projected) == len(reported)
    for report_row, rebuilt in zip(reported, projected, strict=True):
        assert set(rebuilt) == set(report_row)
        assert orjson.dumps(rebuilt) == orjson.dumps(
            {key: rebuilt[key] for key in report_row}
        ), "the rebuilt row disagrees with the builder's key order"
        assert orjson.dumps({key: rebuilt[key] for key in report_row}) == orjson.dumps(
            report_row
        )


def test_no_violation_column_is_left_unprojected(
    corpus: ProjectionCorpus,
) -> None:
    """The exemption list is empty, and the corpus makes that non-vacuous.

    ``locations`` is asserted on the reported rows -- so the equality above
    is comparing a column that CARRIES a value on every row, which is what
    keeps the closed gap a measurement instead of a convenient empty.
    """

    assert VIOLATION_UNPROJECTED_COLUMNS == ()
    reported = _reported(corpus, "violation")
    assert reported, "an empty population makes the claim below vacuous"
    assert all(row["locations"] for row in reported), (
        "no violation carries a location; the equality would be inert"
    )
    kinds = {str(row["kind"]) for row in reported}
    assert kinds == set(VIOLATION_KINDS), (
        f"the corpus reaches {len(kinds)} of {len(VIOLATION_KINDS)} violation "
        "kinds; a kind nobody produces proves nothing about its locations"
    )


# -- both boundaries of the ordering claim ----------------------------------


def test_the_sink_order_is_rebuilt_rather_than_inherited(
    corpus: ProjectionCorpus,
) -> None:
    """Order is rebuilt, not inherited.

    The model stores its families as frozensets, so the projection has no
    incoming order to copy.  This pins that the order it emits is the
    document's, by comparing against the report rows themselves.
    """

    reported = [str(row["sink_identity"]) for row in _reported(corpus, "sink")]
    projected = [
        str(row["sink_identity"]) for row in sink_projection_rows(corpus.stored_model)
    ]
    assert projected == reported
    assert projected != sorted(projected, reverse=True), "a one-way order proves less"


#: How many violations tie in the model below.  Not two: the model stores
#: its families as frozensets, so a tail-less projection falls back to
#: ``frozenset`` iteration order -- which is right by luck once in ``N!``
#: and made the first shape of this pin survive its own mutant under 2 of
#: 8 hash seeds.  Six rows put that luck at 1/720 per seed, so the mutation
#: that removes the tail dies under every seed instead of most of them.
_TIE_WIDTH = 6


def _tying_violation_model() -> CanonicalModel:
    """A model whose violations all tie on every document-order term.

    The reachable input for the projection's order tail.  Same contract,
    same sink, same kind, same source kind, same producer count -- the
    document builder's key cannot separate them, and the producer's own
    order (which ends in the handle) is what decides.  The pipeline corpus
    measured 0 such ties across 143 violations, so the tail is proved
    reachable HERE, at the boundary the function takes its input from.
    """

    sink_file = FileId("pkg/sink.py")
    sink = SymbolId(sink_file, "sink")
    owner = SymbolId(FileId("pkg/owner.py"), "owner")
    producers = [
        SymbolId(FileId(f"pkg/p{index}.py"), f"p{index}") for index in range(_TIE_WIDTH)
    ]

    def _violation(producer: SymbolId) -> ViolationRow:
        return ViolationRow(
            contract_id="tie/v1",
            kind="owner_bypass",
            sink_identity=sink,
            canonical_owner=owner,
            authority_status="shadow",
            effect_signature="s",
            resolution_state="resolved",
            root_set=frozenset({UnresolvedRoot()}),
            producer_set=frozenset({producer}),
            suppressed=False,
            locations=(FileLine(sink_file, 4),),
        )

    files = [sink_file, owner.file, *(producer.file for producer in producers)]
    modules = {
        path.path: ModuleId(path.path.removesuffix(".py").replace("/", "."))
        for path in files
    }
    return CanonicalModel(
        files=frozenset(files),
        modules=frozenset(modules.values()),
        analyzed_files=frozenset(files),
        file_modules=frozenset(
            FileModuleRelation(file=path, module=modules[path.path]) for path in files
        ),
        facts=CanonicalFacts(
            analysis=AnalysisFacts(
                violations=frozenset(_violation(p) for p in producers)
            )
        ),
    )


def test_the_violation_order_tail_decides_a_tie_the_builder_cannot() -> None:
    """The tail is reached, and it is the handle that decides.

    Both rows agree on every term the document builder sorts by, so an
    order still exists only because the tail exists -- and the order it
    yields is the handles ascending, which is the producer's own order
    within such a group.
    """

    rows = list(violation_projection_rows(_tying_violation_model()))
    assert len(rows) == _TIE_WIDTH
    keys = {
        (
            row["contract_id"],
            row["sink_identity"],
            row["kind"],
            row["source_kind"],
            len(cast("list[str]", row["producers"])),
        )
        for row in rows
    }
    assert len(keys) == 1, "the tie the tail exists for did not occur"
    handles = [str(row["violation_id"]) for row in rows]
    assert len(set(handles)) == _TIE_WIDTH
    assert handles == sorted(handles)


def test_the_tie_is_ordered_by_the_handle_and_not_by_the_producer_name() -> None:
    """The other boundary: which discriminator actually decided.

    Ordering the same pair by producer name is a different permutation on
    this input, so a projection that had fallen back to the producer string
    would be visible here rather than hidden behind a coincidence.
    """

    rows = list(violation_projection_rows(_tying_violation_model()))
    by_handle = [str(row["violation_id"]) for row in rows]
    by_producer = [
        str(row["violation_id"])
        for row in sorted(
            rows, key=lambda row: str(cast("list[str]", row["producers"])[0])
        )
    ]
    assert by_handle != by_producer, (
        "handle order and producer order agree on this input; the pin is inert"
    )


# -- the refusal, and an input that reaches it ------------------------------


def test_a_sink_without_a_stored_graph_node_is_refused() -> None:
    """The guard, proved reachable.

    Three of the sink's nine columns come from the graph node of the same
    function.  A model carrying the SINK role and not the node cannot
    answer them, and inventing an empty signature would publish a fact the
    run never made -- so the projection refuses.
    """

    orphan_file = FileId("pkg/orphan.py")
    model = CanonicalModel(
        files=frozenset({orphan_file}),
        modules=frozenset({ModuleId("pkg.orphan")}),
        analyzed_files=frozenset({orphan_file}),
        file_modules=frozenset(
            {FileModuleRelation(file=orphan_file, module=ModuleId("pkg.orphan"))}
        ),
        facts=CanonicalFacts(
            analysis=AnalysisFacts(
                sink_roles=frozenset(
                    {
                        SinkRoleRow(
                            symbol=SymbolId(orphan_file, "orphan"),
                            authority_status="shadow",
                        )
                    }
                )
            )
        ),
    )
    with pytest.raises(CanonicalModelError, match="does not name"):
        sink_projection_rows(model)


def test_a_sink_whose_node_is_present_is_not_refused(
    corpus: ProjectionCorpus,
) -> None:
    """The guard's complement: the corpus reaches the accepting branch."""

    assert sink_projection_rows(corpus.stored_model)


# -- the grammar inverse, pinned by value -----------------------------------


_SYMBOL = SymbolId(FileId("pkg/a.py"), "Thing.method")
_LEGACY = {_SYMBOL: "pkg.a:Thing.method"}

#: One literal per root variant AND per operation-head variant.  A cross
#: reading cannot catch a mutation both readings share; a literal can.
_ROOT_VALUES: tuple[tuple[EffectRoot, str], ...] = (
    (UnresolvedRoot(), "unresolved"),
    (ProducerRoot(_SYMBOL), "producer:pkg.a:Thing.method"),
    (EffectLabelRoot("field_write", "field_write"), "effect:field_write:field_write"),
    (
        OperationRoot(
            "canonical_operation", OperationTarget(KnownModule(ModuleId("pkg.a")), "f")
        ),
        "operation:canonical_operation:pkg.a:f",
    ),
    (
        OperationRoot(
            "canonical_operation",
            OperationTarget(AnalysisFile(FileId("loose.py")), "f"),
        ),
        "operation:canonical_operation:loose.py:f",
    ),
    (
        OperationRoot(
            "canonical_operation",
            OperationTarget(OpaqueDottedHead("hashlib.sha256.hexdigest"), ""),
        ),
        "operation:canonical_operation:hashlib.sha256.hexdigest",
    ),
)


@pytest.mark.parametrize(("root", "text"), _ROOT_VALUES)
def test_the_root_renderer_produces_the_producers_own_spelling(
    root: EffectRoot, text: str
) -> None:
    """The value pin: what the rule produced, not that two readings agree."""

    assert format_effect_root(root, _LEGACY) == text


def test_the_rendered_root_reparses_to_the_root_it_came_from() -> None:
    """Round trip through the forward rule, over every variant at once.

    The renderer's obligation is not "a plausible string" but "the string
    this run's own grammar resolves back to this identity", and the head
    variants are resolved against the registry rather than the spelling.
    """

    index = build_identity_index(
        [("pkg/a.py", "pkg.a")], analyzed_paths=frozenset({"pkg/a.py", "loose.py"})
    )
    for root, text in _ROOT_VALUES:
        # The RENDERED string, not the literal beside it: re-parsing the
        # literal would pin the forward rule twice and leave the renderer
        # unmeasured -- measured, by a mutation that regrew the opaque
        # target's colon and survived this test in its first shape.
        rendered = format_effect_root(root, _LEGACY)
        assert rendered == text
        assert parse_effect_root(index, rendered, "pin") == root


def test_the_root_set_is_rendered_sorted() -> None:
    """The set has no order; the column does, and the owner supplies it."""

    roots = frozenset({root for root, _text in _ROOT_VALUES})
    rendered = format_root_set(roots, _LEGACY)
    assert rendered == sorted(rendered)
    assert set(rendered) == {text for _root, text in _ROOT_VALUES}


def test_the_corpus_roots_survive_the_round_trip(corpus: ProjectionCorpus) -> None:
    """The same claim on a population nobody hand-wrote.

    A pin over six authored variants can miss a spelling only a real run
    produces, so the corpus's own root sets are re-parsed too.
    """

    reported = _reported(corpus, "sink")
    projected = [dict(row) for row in sink_projection_rows(corpus.stored_model)]

    def _roots(rows: list[dict[str, object]]) -> set[str]:
        return {
            str(text)
            for row in rows
            for text in cast("list[str]", row["producer_root_ids"])
        }

    assert len(_roots(projected)) > 1
    assert _roots(projected) == _roots(reported)


# -- the evidence witness: three properties, three separable mutations ------
#
# ``locations`` is the one authority column that had to be CANONICALIZED
# rather than projected, so its three obligations are pinned one test each,
# and each test is written so that ONE mutation kills it and leaves the
# other two green. That separation is the point: three tests that all die
# to the same mutation measure one property three times, not three.

#: The run scope the location grammar is read against. ``pkg/a.py`` and
#: ``pkg/b.py`` are analyzed; ``vendor/x.py`` deliberately is not, so the
#: unresolved variant has a reachable input rather than a hypothetical one.
_LOCATION_INDEX = build_identity_index(
    [("pkg/a.py", "pkg.a"), ("pkg/b.py", "pkg.b")],
    analyzed_paths=frozenset({"pkg/a.py", "pkg/b.py"}),
)


def test_the_evidence_order_is_canonical_and_not_the_order_events_arrived() -> None:
    """Property 1 -- the order is the model's, never the producer's.

    Two sites in DIFFERENT files, offered in both orders: the tuple that
    comes out is the same tuple. Different files on purpose, and no corpus
    fixture on purpose: this pin must stay green under the mutations the
    other two properties own, or the three would measure one property three
    times instead of three properties once each.

    Mutation: drop the ``sorted`` from ``parse_source_locations`` and the
    two arrival orders stop agreeing here.
    """

    forward = parse_source_locations(
        _LOCATION_INDEX, [("pkg/a.py", 4), ("pkg/b.py", 2)]
    )
    reversed_arrival = parse_source_locations(
        _LOCATION_INDEX, [("pkg/b.py", 2), ("pkg/a.py", 4)]
    )
    assert forward == reversed_arrival
    assert forward == (FileLine(FileId("pkg/a.py"), 4), FileLine(FileId("pkg/b.py"), 2))
    keys = [source_location_key(item) for item in forward]
    assert keys == sorted(keys)


def test_two_sites_in_one_file_stay_two_evidence_points() -> None:
    """Property 2 -- multiplicity survives; a repeat is refused, not eaten.

    The input is already in canonical order, so property 1's mutation
    (dropping the sort) leaves this test green and the two stay separable.
    What this one is about is the LINE: two sites of one file are two
    evidence points, and a key blind to the line would fuse them.

    Mutation: drop ``location.line`` from ``source_location_key`` and the
    two same-file sites collide -- the tuple below stops being strictly
    increasing and ``ViolationRow`` refuses the row it should have carried.
    """

    sites = parse_source_locations(_LOCATION_INDEX, [("pkg/a.py", 4), ("pkg/a.py", 9)])
    assert sites == (FileLine(FileId("pkg/a.py"), 4), FileLine(FileId("pkg/a.py"), 9))
    row = _violation_with(sites)
    assert row.locations == sites
    assert [
        (item["relative_path"], item["start_line"])
        for item in cast(
            "list[dict[str, object]]",
            _projected_row(row)["locations"],
        )
    ] == [("pkg/a.py", 4), ("pkg/a.py", 9)]

    # The other half of the property: a genuine repeat is a REFUSAL. A
    # deduplicating model would return a shorter tuple and call it a fact.
    doubled = (*sites, sites[-1])
    with pytest.raises(CanonicalModelError, match="strictly increasing"):
        _violation_with(doubled)


def test_an_unplaceable_site_becomes_explicit_unresolved_and_is_never_dropped() -> None:
    """Property 3 -- the site the FILE domain refuses still counts.

    A dropped site leaves a SHORTER tuple, and on the last site an empty
    one -- and an empty tuple reads as "the producer had nothing to say",
    which is a different statement. So the length is asserted first and the
    variant second, and the projection is asked to render the string back.

    Mutation: make ``parse_source_locations`` skip a path outside
    ``analyzed_paths`` and the length assertion below fails, while
    properties 1 and 2 (whose paths are all analyzed) stay green.
    """

    sites = parse_source_locations(
        _LOCATION_INDEX, [("pkg/a.py", 4), ("vendor/x.py", 7)]
    )
    assert len(sites) == 2, "an unplaceable site was dropped instead of tagged"
    assert sites[1] == UnresolvedLocation("vendor/x.py", 7)
    # The complement, so the classification is a decision and not a
    # constant: the analyzed path in the same call took the other branch.
    assert sites[0] == FileLine(FileId("pkg/a.py"), 4)

    rendered = cast(
        "list[dict[str, object]]", _projected_row(_violation_with(sites))["locations"]
    )
    assert [item["relative_path"] for item in rendered] == [
        "pkg/a.py",
        "vendor/x.py",
    ], "the unresolved site's own string was not rendered back verbatim"

    # A path the FILE law itself refuses reaches the same variant rather
    # than a crash: ``..`` can never be a FILE identity.
    outside = parse_source_locations(_LOCATION_INDEX, [("vendor/pkg/../x.py", 1)])
    assert outside == (UnresolvedLocation("vendor/pkg/../x.py", 1),)


def test_a_mixed_row_orders_by_the_path_and_not_by_the_variant_tag() -> None:
    """Property 4 -- the tail-tag decision, held by measurement.

    ``source_location_key`` puts the variant tag LAST, unlike
    ``endpoint_key`` and ``dead_code_entity_key`` which lead with it. The
    justification is that both location variants address ONE namespace --
    the producer's own path string -- and the producer orders its evidence
    by that string (``semantics/authority._summary_locations`` sorts by
    ``(relative_path, start_line, qualname)``). A leading tag would split
    that namespace into two blocks the producer never separated.

    Reasoning is not measurement, and the corpus cannot supply the missing
    half: 0 of its 58 sites are unresolved, so no corpus row mixes the
    variants and both candidate keys agree on every row a real run produces.
    This is the input that separates them -- and it is chosen so the two
    orderings DISAGREE, which the second assertion proves rather than
    assumes.

    Mutation: lead ``source_location_key`` with the tag and this reds, while
    the three single-variant property pins stay green.

    Separability, measured rather than assumed. The sites are handed in
    already in the shipped key's order, so property 1's mutation (dropping
    the sort) is a no-op here and the two stay independent -- the first
    shape of this pin was offered them REVERSED and the separability battery
    caught it dying to p1 as well. It cannot be made independent of property
    3: a mixed row needs an unresolved site to exist at all, so a mutation
    that drops unplaceable sites necessarily reds this too. That dependency
    is intrinsic to the claim, and it is stated rather than engineered away.
    """

    # ``aaa.py`` is outside the run's scope and ``zzz.py`` is inside it, so
    # path order and tag order pull in opposite directions here.
    sites = [("aaa.py", 1), ("zzz.py", 1)]
    index = build_identity_index([], analyzed_paths=frozenset({"zzz.py"}))
    ordered = parse_source_locations(index, sites)
    assert {type(item) for item in ordered} == {FileLine, UnresolvedLocation}, (
        "the input must mix the variants or it settles nothing"
    )

    # The producer's key, spelled here instead of imported: the path first,
    # then the line. The qualname is constant across one violation's sites,
    # so those two terms are the whole of the order it yields.
    by_producer = [path for path, _line in sorted(sites, key=lambda site: site)]
    assert [format_source_location(item) for item in ordered] == by_producer

    # Both boundaries: a tag-first key is a DIFFERENT permutation on this
    # input, so the equality above cannot be satisfied by both rules and the
    # pin is not inert.
    tag_first = sorted(
        ordered,
        key=lambda item: (
            DOMAIN_TAG_FILE if isinstance(item, FileLine) else LOCATION_TAG_UNRESOLVED,
            format_source_location(item),
        ),
    )
    assert [format_source_location(item) for item in tag_first] != by_producer

    # And the same disagreement reaches the model: under a tag-first key the
    # canonical tuple would be non-increasing, which ``ViolationRow``
    # refuses -- so the decision is load-bearing, not cosmetic.
    assert _violation_with(ordered).locations == ordered
    with pytest.raises(CanonicalModelError, match="strictly increasing"):
        _violation_with(tuple(reversed(ordered)))


def test_the_corpus_reaches_every_shape_the_three_pins_assert(
    corpus: ProjectionCorpus,
) -> None:
    """The three pins above are hermetic; this is where they meet a run.

    Hand-built inputs prove a rule; they do not prove the rule is about
    anything. Each shape the pins assert is counted here on the population a
    real pipeline produced, so a pin that had become inert would be visible
    as a zero rather than as a still-green assertion.
    """

    violations = corpus.stored_model.facts.analysis.violations
    assert violations, "an empty violation population makes every count vacuous"
    for row in violations:
        keys = [source_location_key(item) for item in row.locations]
        assert keys == sorted(keys), "a stored row lost the canonical order"
    assert all(row.locations for row in violations), (
        "a corpus violation carries no site at all; the evidence column "
        "would be measuring an empty everywhere"
    )
    multiplicity = [row for row in violations if len(row.locations) > 1]
    assert multiplicity, "no corpus violation carries two sites (property 1)"
    same_file = [
        row
        for row in multiplicity
        if len({_location_path(item) for item in row.locations}) == 1
    ]
    assert same_file, (
        "no corpus violation carries two sites of ONE file; a line-blind key "
        "would survive this corpus and property 2 would be its only witness"
    )
    unresolved = [
        item
        for row in violations
        for item in row.locations
        if isinstance(item, UnresolvedLocation)
    ]
    assert unresolved == [], (
        "the pipeline corpus produced an unplaceable site; the variant is "
        "reachable there too and this expectation needs re-measuring"
    )


def _location_path(location: object) -> str:
    return format_source_location(cast("FileLine | UnresolvedLocation", location))


def _violation_with(sites: tuple[object, ...]) -> ViolationRow:
    """One violation carrying exactly these sites, and nothing else new."""

    sink = SymbolId(FileId("pkg/a.py"), "sink")
    return ViolationRow(
        contract_id="evidence/v1",
        kind="owner_bypass",
        sink_identity=sink,
        canonical_owner=SymbolId(FileId("pkg/b.py"), "owner"),
        authority_status="shadow",
        effect_signature="s",
        resolution_state="resolved",
        root_set=frozenset({UnresolvedRoot()}),
        producer_set=frozenset({sink}),
        suppressed=False,
        locations=cast("tuple[FileLine | UnresolvedLocation, ...]", sites),
    )


def _projected_row(row: ViolationRow) -> dict[str, object]:
    """The published row of a one-violation model, through the projection."""

    files = [FileId("pkg/a.py"), FileId("pkg/b.py")]
    modules = {"pkg/a.py": ModuleId("pkg.a"), "pkg/b.py": ModuleId("pkg.b")}
    model = CanonicalModel(
        files=frozenset(files),
        modules=frozenset(modules.values()),
        analyzed_files=frozenset(files),
        file_modules=frozenset(
            FileModuleRelation(file=path, module=modules[path.path]) for path in files
        ),
        facts=CanonicalFacts(analysis=AnalysisFacts(violations=frozenset({row}))),
    )
    (projected,) = violation_projection_rows(model)
    return projected

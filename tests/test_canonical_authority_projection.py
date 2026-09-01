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
    AnalysisFile,
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
    parse_effect_root,
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


def test_the_violation_projection_rebuilds_every_column_with_a_stored_basis(
    corpus: ProjectionCorpus,
) -> None:
    """Six of seven close; the seventh is named, not silently dropped."""

    reported = _reported(corpus, "violation")
    assert len(reported) > 1, "a one-row population settles no ordering"
    projected = list(violation_projection_rows(corpus.stored_model))
    assert len(projected) == len(reported)
    for report_row, rebuilt in zip(reported, projected, strict=True):
        assert set(report_row) - set(rebuilt) == set(VIOLATION_UNPROJECTED_COLUMNS)
        assert set(rebuilt) - set(report_row) == set()
        trimmed = {
            key: value
            for key, value in report_row.items()
            if key not in VIOLATION_UNPROJECTED_COLUMNS
        }
        assert orjson.dumps({key: rebuilt[key] for key in trimmed}) == orjson.dumps(
            trimmed
        )


def test_the_unprojected_column_is_the_one_with_no_stored_basis(
    corpus: ProjectionCorpus,
) -> None:
    """The exemption is a fact about the corpus, not a spelling.

    ``locations`` is asserted on the reported rows -- so the projection is
    omitting a column that carries a value, which is what makes the
    omission a measured gap instead of a convenient empty.
    """

    assert VIOLATION_UNPROJECTED_COLUMNS == ("locations",)
    reported = _reported(corpus, "violation")
    assert reported, "an empty population makes the claim below vacuous"
    assert all(row["locations"] for row in reported), (
        "no violation carries a location; the omission would be inert"
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

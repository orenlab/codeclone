# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Can the canonical run express what the MCP surface serves from RAM?

Three slices are held off the sealed report and served out of the parent's
memory — the unit index, the module imports and the per-function
relationship records.  Migrating a consumer off that memory and onto the
canonical run store is only an engineering decision if something can say
*no* and name what disagreed.  These are the three answers, measured
2026-09-03 at ``4512acf0``; each is written as the equivalence it has to
satisfy, and the two still unsatisfied are marked ``xfail(strict=True)``:

``unit_inventory``
    SATISFIED 2026-09-04, by the owner this pin named in advance.
    ``qualname``, ``path`` and ``start_line`` always had a canonical owner
    and agreed row for row; ``end_line`` had none, because of the row types
    reachable from ``AnalysisFacts`` exactly two declared an ``end_line`` at
    all and neither covered the unit population.  The ``unit_spans`` family
    (``UnitSpanRow``) is the third, and it is the declaration itself: on the
    serving corpus the reader answered 2 of 12 units before it was taught
    and 12 of 12 after, with no declaration stated twice differently.  The
    equivalence below carries no expected failure any more.

``module_imports``
    SATISFIED 2026-09-07, by canonical model revision 2.  Every served
    field was always expressible; the POPULATION was a strict subset,
    because the dependency lane ingests only internal source-bearing edges
    so that the gate and the SCC pass consume one graph.  The
    ``import_observations`` family is the second lane the marker's exit
    condition named: every import the walk observed, external and
    unresolved targets included, and the dependency lane is left exactly as
    it was — pinned below as a strict subset, because the sanction forbids
    widening it.

``relationship_facts``
    SATISFIED 2026-09-07, by canonical model revision 2.  The
    ``relationship_observations`` family carries all eight served fields
    and BOTH resolution states — the nullary target variant is the fact
    "the producer resolved nothing" — plus the multiplicity the producer
    emits (one record per expression, so ``f(g(), g())`` is two records),
    counted per observation and expanded on the way out.

**What the pins compare now.**  Each slice is read out of the store by the
PRODUCTION projection (``codeclone.canonical.serving``) — the one owner the
surface serves through — and compared with the live producer's own tuple
on the SAME execution: every field, in the producer's own order.  A pin
that rebuilt the projection for itself would stay green under a real
mutation of the one that serves.  Each pin states its population before it
compares (both target kinds, both resolution states), so it cannot pass on
an empty or one-sided slice.

**What a red here means.**  A regression: some canonical fact the served
slice needs stopped being stated, or stopped agreeing.  Never a gap to
restore, and never a reason to narrow the served slice to the store.
"""

from __future__ import annotations

import dataclasses
import typing
from collections import Counter
from collections.abc import Callable, Iterable, Mapping

import pytest

from codeclone.canonical import (
    AnalysisFacts,
    CanonicalModel,
    CloneItemRow,
    CohesionHotspotRow,
    ComplexityHotspotRow,
    CouplingHotspotRow,
    CoverageUnitRow,
    DeadSymbolGroupRow,
    DependencyEndpoint,
    DependencyOccurrenceRow,
    FileId,
    ModuleId,
    RunStore,
    SecuritySurfaceRow,
    ServedRunSlices,
    SymbolId,
    UnitSpanRow,
    UnreachableStatementRow,
    read_served_run_slices,
)
from codeclone.models import (
    ModuleDep,
    RelationshipRecord,
    RelationshipResolutionStatus,
)
from tests._served_run import ServedRunStoreProjection

#: ``(FILE path, local qualname, first line)`` — the one key both sides can
#: be stated in.  The producer glues a head onto its local name
#: (``pkg.wheel:turn``) and the canonical model never does, so comparing the
#: two spellings compares dialects rather than populations.  The first line
#: is part of the key and not payload: one name may be declared several
#: times in one file (``@overload`` families, a property and its setter),
#: and a symbol-only key silently collapses those declarations into one —
#: measured on the self-repository at ``4512acf0``, where 15 934 served
#: units collapse onto 15 853 symbol-only keys.
UnitKey = tuple[str, str, int]


@pytest.fixture(scope="session")
def canonical_run(
    served_run_store_projection: ServedRunStoreProjection,
) -> CanonicalModel:
    """The canonical row that same execution published, read back out."""
    with RunStore(served_run_store_projection.store_path) as store:
        return store.read_run(served_run_store_projection.store_run_id)


def _modules_by_path(model: CanonicalModel) -> dict[str, str]:
    """The run's own FILE→MODULE projection, never a path-to-dots guess."""
    return {row.file.path: row.module.module for row in model.file_modules}


def _paths_by_module(model: CanonicalModel) -> dict[str, str]:
    """The same projection, inverted: MODULE→FILE."""
    return {row.module.module: row.file.path for row in model.file_modules}


def _analyzed_paths(model: CanonicalModel) -> frozenset[str]:
    """Every FILE the run analyzed, mapped to a MODULE or not."""
    return frozenset(row.path for row in model.analyzed_files)


def _canonical_row_types() -> dict[str, type]:
    """Every dataclass reachable from :class:`AnalysisFacts`, by class name.

    Walked from the type annotations, so a family whose rows happen to be
    empty on one corpus is still enumerated.  This is the instrument the
    closing-line reader below is proved complete against.
    """
    found: dict[str, type] = {}

    def element_types(annotation: object) -> list[type]:
        types: list[type] = []
        stack: list[object] = [annotation]
        while stack:
            current = stack.pop()
            arguments = typing.get_args(current)
            if arguments:
                stack.extend(arguments)
            elif isinstance(current, type) and dataclasses.is_dataclass(current):
                types.append(current)
        return types

    def walk(row_type: type) -> None:
        if row_type.__name__ in found:
            return
        found[row_type.__name__] = row_type
        hints = typing.get_type_hints(row_type)
        for field in dataclasses.fields(row_type):
            for nested in element_types(hints.get(field.name, field.type)):
                walk(nested)

    for annotation in typing.get_type_hints(AnalysisFacts).values():
        for row_type in element_types(annotation):
            walk(row_type)
    return found


# -- 1. the unit index ------------------------------------------------------
#
# One served row: the producer's glued qualname, the repo-relative path, the
# first line and the closing line.  The closing line is ``int | None``
# because that is what the canonical model can offer for it — absence is a
# value here, not a skipped row, so the failure names the field.

UnitRow = tuple[str, str, int, int | None]


def _qualname_head(
    path: str,
    modules_by_path: Mapping[str, str],
    analyzed_paths: frozenset[str],
) -> str | None:
    """The head the producer glues onto a local name.

    A FILE the run mapped to a MODULE is headed by that module; a file it
    analyzed without one is headed by its own path.  That is the producer's
    own rule, read off its output — 81 of 15 934 served units on the
    self-repository at ``4512acf0`` live in files ``file_modules`` does not
    cover, and a module-only head cannot spell any of them.
    """
    module = modules_by_path.get(path)
    if module is not None:
        return module
    return path if path in analyzed_paths else None


def _project_unit_inventory(
    *,
    modules_by_path: Mapping[str, str],
    analyzed_paths: frozenset[str],
    units: Mapping[UnitKey, int | None],
) -> frozenset[UnitRow]:
    """Rebuild the served unit index out of canonical facts.

    Total by construction: it raises nothing and drops only a FILE the run
    neither mapped to a MODULE nor recorded as analyzed, so the only way its
    answer can differ from the served slice is a fact that differs.
    ``units`` maps each declaration the canonical model knows to the closing
    line it states for it, and that mapping is the one input the pin and its
    control disagree about.
    """
    rows: set[UnitRow] = set()
    for (path, qualname, first_line), closing_line in units.items():
        head = _qualname_head(path, modules_by_path, analyzed_paths)
        if head is None:
            continue
        rows.add((f"{head}:{qualname}", path, first_line, closing_line))
    return frozenset(rows)


def _declarations_the_canonical_run_states(
    model: CanonicalModel,
) -> frozenset[UnitKey]:
    """Every declaration the canonical model states a first line for.

    ``risk_observations`` is the owner: its ratified key carries the
    declaration site precisely so that several declarations of one name stay
    several facts.
    """
    return frozenset(
        (row.symbol.file.path, row.symbol.qualname, row.start_line)
        for row in model.facts.analysis.risk_observations
    )


#: How one taught family spells a declaration key and the closing line it
#: states, given the analysis fact house.
_ClosingLineReader = Callable[[AnalysisFacts], Iterable[tuple[UnitKey, int]]]

#: Every canonical family the closing-line reader consults, paired with the
#: row type it is made of.  The reader below iterates THIS table and nothing
#: else, and the completeness ratchet holds the table equal — in BOTH
#: directions — to the row types the MODEL declares an ``end_line`` on.  A
#: hand-written expected set could only say one of those two things: it stays
#: green for a reader that was widened on paper and never taught, and green
#: again for one that quietly stopped reading a family it already had.
_CLOSING_LINE_FAMILIES: tuple[tuple[type, _ClosingLineReader], ...] = (
    (
        SecuritySurfaceRow,
        lambda analysis: (
            ((row.file.path, row.qualname, row.start_line), row.end_line)
            for row in analysis.security_surfaces
            if row.qualname is not None
        ),
    ),
    (
        CloneItemRow,
        lambda analysis: (
            (
                (item.symbol.file.path, item.symbol.qualname, item.start_line),
                item.end_line,
            )
            for group in analysis.clone_groups
            for item in group.items
        ),
    ),
    (
        UnitSpanRow,
        lambda analysis: (
            ((row.symbol.file.path, row.symbol.qualname, row.start_line), row.end_line)
            for row in analysis.unit_spans
        ),
    ),
    # Canonical epoch E1 (2026-09-25): six more families state a closing
    # line.  Five of them ARE the declaration — a dead symbol, a design
    # hotspot of any of the three categories, a coverage unit — keyed by
    # the declaration site exactly as ``unit_spans`` is, so each answers
    # for the units it carries.  The sixth, an unreachable region, is a
    # span INSIDE a unit like a security surface: its start is a statement
    # line, never a declaration, so it answers no served unit.  None of the
    # six is populated on the serving corpus; each is driven ALONE on the
    # E1 corpus in ``test_run_store_producer_wiring`` (the reachability
    # witness the mutation law asks for), and the population test below
    # names them as the families this corpus is measured to leave empty.
    (DeadSymbolGroupRow, lambda analysis: _sites(analysis.dead_symbol_groups)),
    (
        UnreachableStatementRow,
        lambda analysis: _sites(analysis.unreachable_statement_groups),
    ),
    (ComplexityHotspotRow, lambda analysis: _sites(analysis.complexity_hotspots)),
    (CouplingHotspotRow, lambda analysis: _sites(analysis.coupling_hotspots)),
    (CohesionHotspotRow, lambda analysis: _sites(analysis.cohesion_hotspots)),
    (CoverageUnitRow, lambda analysis: _sites(analysis.coverage_units)),
)

#: The taught families the serving corpus is measured to leave EMPTY
#: (2026-09-25): every E1 row type — the corpus carries no dead symbol,
#: no unreachable region, no hotspot of any category and no coverage
#: report.  Named here so the population test can state the emptiness
#: instead of tolerating it, and so a family that starts carrying rows on
#: this corpus turns that test red and a human decides.
_E1_CLOSING_LINE_ROW_TYPES: frozenset[str] = frozenset(
    {
        "CohesionHotspotRow",
        "ComplexityHotspotRow",
        "CouplingHotspotRow",
        "CoverageUnitRow",
        "DeadSymbolGroupRow",
        "UnreachableStatementRow",
    }
)


_SiteRow = (
    DeadSymbolGroupRow
    | UnreachableStatementRow
    | ComplexityHotspotRow
    | CouplingHotspotRow
    | CohesionHotspotRow
    | CoverageUnitRow
)


def _sites(rows: Iterable[_SiteRow]) -> Iterable[tuple[UnitKey, int]]:
    """The declaration key and closing line one site-keyed E1 row states."""
    return (
        ((row.symbol.file.path, row.symbol.qualname, row.start_line), row.end_line)
        for row in rows
    )


def _closing_lines_the_canonical_run_states(
    model: CanonicalModel,
) -> dict[UnitKey, int]:
    """Every closing line ANY canonical family states, by declaration.

    Every family that declares an ``end_line`` is read, through
    ``_CLOSING_LINE_FAMILIES`` (three before canonical epoch E1, nine
    since), and the completeness ratchet below proves that table is
    neither short of the model nor ahead of it — so this reader can
    neither quietly miss a tenth family nor keep one in an expected set it
    no longer consults.

    The key carries the first line, so a family answers about a unit only
    when it states that unit's whole span.  That is what makes the join a
    measurement rather than a guess: a security surface is a statement
    *inside* a unit and its span starts elsewhere, so it does not answer —
    while a function clone member IS the unit and does, and a ``unit_spans``
    row IS the declaration, so it answers for every one.

    A key two families answer differently is dropped: one declaration with
    two closing lines is a disagreement, not a stated fact.  That rule is
    populated rather than hypothetical — measured on the serving corpus
    2026-09-04, the clone lane and the span lane both state the corpus's
    clone pair, and state it identically.
    """
    stated: dict[UnitKey, set[int]] = {}
    analysis = model.facts.analysis
    for _row_type, read in _CLOSING_LINE_FAMILIES:
        for key, end_line in read(analysis):
            stated.setdefault(key, set()).add(end_line)
    return {key: next(iter(lines)) for key, lines in stated.items() if len(lines) == 1}


def _units_the_canonical_run_offers(
    model: CanonicalModel,
) -> dict[UnitKey, int | None]:
    """Each canonical declaration, and the closing line the model has for it."""
    closing = _closing_lines_the_canonical_run_states(model)
    return {
        key: closing.get(key) for key in _declarations_the_canonical_run_states(model)
    }


def _served_unit_rows(served: ServedRunStoreProjection) -> frozenset[UnitRow]:
    return frozenset(
        (unit.qualname, unit.path, unit.start_line, unit.end_line)
        for unit in served.unit_inventory
    )


def _served_units(served: ServedRunStoreProjection) -> dict[UnitKey, int]:
    """The served declarations and their closing lines, keyed canonically.

    Used ONLY by the control, where it is the fabrication: it is what a
    canonical owner of the closing line would have to state.
    """
    return {
        (unit.path, unit.qualname.partition(":")[2], unit.start_line): unit.end_line
        for unit in served.unit_inventory
    }


def test_the_closing_line_reader_is_taught_every_row_type_that_declares_one() -> None:
    """The reachability witness for the equivalence below (Probe Validity §1).

    Read from the model DEFINITIONS, not from one run's populated families.
    A reader that asked ``SecuritySurfaceRow`` for a ``symbol`` attribute it
    does not have would find nothing on every corpus and be indistinguishable
    from "no family owns this" — that exact hollow reader is what produced an
    earlier "0 of 15 884" reading of this gap.

    Two assertions, and the second is the one with teeth.  The first
    enumerates the row types the model declares an ``end_line`` on, so a
    fourth turns this red and a human decides; the prescribed fix is to teach
    ``_CLOSING_LINE_FAMILIES``, never to widen the expected set alone.  The
    second is what makes "alone" impossible: it holds the taught table equal
    to that enumeration in both directions, so widening the literal without
    teaching the reader fails here, and dropping a family from the reader
    while the literal still names it fails here too.  ``UnitSpanRow`` entered
    both lines together on 2026-09-04; before that day the enumeration was
    two names long and this file said so.  The six E1 row types entered both
    lines together on 2026-09-25, each keyed by the declaration site the
    ``unit_spans`` family established.
    """
    row_types = _canonical_row_types()
    assert len(row_types) > 20, row_types.keys()
    declaring = {
        name
        for name, row_type in row_types.items()
        if "end_line" in {field.name for field in dataclasses.fields(row_type)}
    }
    assert declaring == {
        "CloneItemRow",
        "SecuritySurfaceRow",
        "UnitSpanRow",
        *_E1_CLOSING_LINE_ROW_TYPES,
    }
    assert declaring == {row_type.__name__ for row_type, _ in _CLOSING_LINE_FAMILIES}


def _closing_lines_by_family(
    model: CanonicalModel,
) -> dict[str, frozenset[tuple[UnitKey, int]]]:
    """What each taught family states, kept APART instead of merged.

    The reader merges; these two tests need the families separated, because a
    merged answer cannot say which family produced which part of it.
    """
    analysis = model.facts.analysis
    return {
        row_type.__name__: frozenset(read(analysis))
        for row_type, read in _CLOSING_LINE_FAMILIES
    }


def test_the_two_families_that_state_one_declaration_state_it_identically(
    canonical_run: CanonicalModel,
) -> None:
    """The disagreement rule's own witness: reachable, and currently silent.

    A clone member and a ``unit_spans`` row can both be the same declaration,
    and on this corpus both state the clone pair — so the rule that drops a
    key two families answer differently has a populated overlap to police
    rather than a hypothetical one.  Every overlapping declaration survives
    into the reader's answer, which is true only while the two lanes agree.

    Corrupt one span end and the key is dropped rather than asserted wrong;
    measured 2026-09-04 by mutating the producer, this test named the exact
    declaration and the unit projected a closing line of ``None`` instead of
    the corrupted number.  That is the whole point of dropping: the reader
    would rather say nothing than pick a winner between two stated facts.
    """
    per_family = _closing_lines_by_family(canonical_run)
    overlap = {key for key, _ in per_family["CloneItemRow"]} & {
        key for key, _ in per_family["UnitSpanRow"]
    }
    assert overlap, (
        "no declaration is stated by two families; the disagreement rule the "
        "reader applies would be unreachable on this corpus"
    )
    stated = _closing_lines_the_canonical_run_states(canonical_run)
    assert overlap <= set(stated), (
        f"two families state a different closing line for the same "
        f"declaration and the reader dropped it: "
        f"{sorted(overlap - set(stated))}"
    )


def test_every_taught_closing_line_family_answers_on_this_corpus(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    """Each taught family is populated here, and each plays a part of its own.

    Taught is not reached.  The ratchet above reads DEFINITIONS, so a family
    whose rows are empty on this input would leave the reader's answer
    identical with and without it and that ratchet could not tell — the
    aggregate would be green because a sibling family did all the work.  So
    every family in the table is driven ALONE and required to carry rows.

    Then each is required to do its own job, measured rather than assumed.  A
    security surface is a statement INSIDE a unit: it names the same file and
    the same qualname, its span starts somewhere else, and the closing line
    it states is its own — so it answers no declaration, which is the rule
    that keeps the join a measurement.  A clone member IS the hosting unit
    and states that unit's whole span.  A ``unit_spans`` row IS the
    declaration, and it is what carries the population: 2 of 12 served units
    were answered before that family was taught, 12 of 12 after (2026-09-04,
    this corpus).

    The disagreement rule has a test of its own next door, and separate is
    the point: every declaration two families state is also a served unit, so
    an assertion about it placed AFTER the population statement here could
    never be the one to fire — it would be a guard unreachable in every
    configuration, which is the hollow shape this project's mutation law
    names.  Two tests, two reds, neither shadowing the other.
    """
    per_family = _closing_lines_by_family(canonical_run)
    unpopulated = {name for name, rows in per_family.items() if not rows}
    # The E1 row types are the families this corpus is MEASURED to leave
    # empty, stated as such; their reachability is proved alone on the E1
    # corpus (``test_run_store_producer_wiring``).  Any other empty family,
    # or an E1 family that starts carrying rows here, is a red to decide.
    assert unpopulated == _E1_CLOSING_LINE_ROW_TYPES, (
        f"taught families carrying no row on this corpus: {sorted(unpopulated)}; "
        f"the reader's answer cannot distinguish them from families it never read"
    )
    stated = _closing_lines_the_canonical_run_states(canonical_run)
    served = _served_units(served_run_store_projection)
    assert stated, "no canonical family stated a closing line; the reader is dead"
    inside_a_unit = {
        key
        for key in stated
        if key not in served
        and any(
            unit[0] == key[0] and unit[1] == key[1] and unit[2] < key[2]
            for unit in served
        )
    }
    assert inside_a_unit, "the surface lane stated no span inside a unit"
    answering = {key for key in stated if key in served}
    assert answering == set(served), (
        "a served unit has no stated closing line; the span family is the "
        "owner of that fact and every served unit is one of its rows"
    )
    assert all(served[key] == stated[key] for key in answering)


def test_unit_inventory_is_reconstructible_from_the_canonical_run(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    """RATIFIED 2026-09-04: the served unit index IS expressible from the run.

    This carried ``xfail(strict=True)`` from 2026-09-03 until the
    ``unit_spans`` family landed, because the closing line had no canonical
    owner: the two families that declared one answered 2 of 12 units on this
    corpus and 0 of 15 934 on the self-repository at ``4512acf0``.  The
    marker's own exit condition named ``UnitSpanRow`` as the work that would
    flip it, and this is that flip — the expected failure is removed, not the
    comparison weakened.

    A red here is now a REGRESSION and never a gap to restore: some canonical
    fact the served slice needs stopped being stated, or stopped agreeing.
    The test beside it isolates every field but the closing line, so the two
    reds say different things.
    """
    projected = _project_unit_inventory(
        modules_by_path=_modules_by_path(canonical_run),
        analyzed_paths=_analyzed_paths(canonical_run),
        units=_units_the_canonical_run_offers(canonical_run),
    )
    assert projected == _served_unit_rows(served_run_store_projection)


def test_the_unit_projection_agrees_on_every_field_but_the_closing_line(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    """The same projection, with the closing line taken out of the question.

    This was the positive control while the pin above was an expected
    failure: it drove the identical projection with the closing line supplied
    by hand, so a scaffolding fault turned it RED instead of leaving the pin
    quietly xfailing forever.  The day a real owner landed the pin stopped
    needing a control, and what the test still measures is worth keeping on
    its own — it isolates the OTHER fields.  The declaration set, the glued
    head, the path and the first line are compared here with the closing line
    fabricated, so a red here is never about the span, and a red on the pin
    above while this stays green is about the span alone.
    """
    served = _served_unit_rows(served_run_store_projection)
    assert served, "the served slice is empty; the comparison would be hollow"
    declarations = _declarations_the_canonical_run_states(canonical_run)
    assert declarations, "the canonical run stated no declaration; nothing projected"
    supplied: dict[UnitKey, int | None] = dict(
        _served_units(served_run_store_projection)
    )
    assert set(supplied) == declarations, (
        "the canonical declaration set and the served one have diverged; the "
        "pin above no longer measures the closing line alone"
    )
    assert (
        _project_unit_inventory(
            modules_by_path=_modules_by_path(canonical_run),
            analyzed_paths=_analyzed_paths(canonical_run),
            units=supplied,
        )
        == served
    )


# -- 2. the module imports --------------------------------------------------
#
# RATIFIED 2026-09-07 (canonical model revision 2).  Two statements, both
# pinned: the ``import_observations`` family reproduces the served slice
# exactly, and the dependency lane the gate consumes stays the strict subset
# it always was -- the sanction that admitted the family forbids widening it.

DependencyRow = tuple[str, str, str, int]


def _endpoint_name(endpoint: DependencyEndpoint) -> str:
    """A dependency endpoint in the producer's own spelling."""
    return endpoint.module if isinstance(endpoint, ModuleId) else endpoint.path


def _dependency_lane_rows(
    occurrences: Iterable[DependencyOccurrenceRow],
) -> frozenset[DependencyRow]:
    """The dependency lane's occurrences in the served import row shape.

    Total: it raises nothing and drops nothing.  Kept for ONE statement --
    the subset relation below -- and never the serving projection, which
    lives in production.
    """
    return frozenset(
        (
            _endpoint_name(row.relation.source),
            _endpoint_name(row.relation.target),
            row.relation.dependency_type,
            row.line,
        )
        for row in occurrences
    )


def _served_import_rows(served: ServedRunStoreProjection) -> frozenset[DependencyRow]:
    return frozenset(
        (row.source, row.target, row.import_type, row.line)
        for row in served.module_imports
    )


@pytest.fixture(scope="session")
def store_served_slices(
    served_run_store_projection: ServedRunStoreProjection,
) -> ServedRunSlices:
    """The production projection's answer for the SAME execution.

    Read out of the store through the one owner the surface serves through
    (``codeclone.canonical.serving``), never a projection rebuilt here: a
    pin that rebuilt it would stay green under a real mutation of the one
    that serves.
    """
    with RunStore(served_run_store_projection.store_path, create=False) as store:
        return read_served_run_slices(
            store,
            served_run_store_projection.store_run_id,
            root=served_run_store_projection.root,
        )


def test_the_dependency_lane_stays_a_strict_subset_of_the_served_imports(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    """Sanction condition 1, executable: the gate's graph was NOT widened.

    ``dependency_occurrences`` still carries only the internal, source-bearing
    edges (5 of the 9 served rows on this corpus), and the rows it lacks are
    exactly the external ones.  A red here means the dependency lane grew to
    match the served slice -- the repair the sanction forbids -- or shrank.
    """
    served = _served_import_rows(served_run_store_projection)
    lane = _dependency_lane_rows(canonical_run.facts.analysis.dependency_occurrences)
    assert lane, "the canonical dependency lane carried no rows"
    assert lane < served, "the dependency lane is no longer a strict subset"
    by_row: dict[DependencyRow, ModuleDep] = {
        (dep.source, dep.target, dep.import_type, dep.line): dep
        for dep in served_run_store_projection.module_imports
    }
    assert {by_row[row].resolution for row in served - lane} == {"external"}


def test_module_imports_are_reconstructible_from_the_canonical_run(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
    store_served_slices: ServedRunSlices,
) -> None:
    """RATIFIED 2026-09-07: the served import slice IS expressible from the run.

    This carried ``xfail(strict=True)`` from 2026-09-03 until the
    ``import_observations`` family landed: the dependency lane omits every
    external import by design, so the store held 5 of the 9 served rows here
    and 6 238 of 10 953 on the self-repository.  The marker's own exit
    condition named a second lane, and this is that lane -- the expected
    failure is removed, not the comparison weakened.

    The comparison is the production projection against the LIVE producer's
    tuple: every field of every ``ModuleDep``, in the producer's own order.
    The population is stated before it is compared, so the pin cannot pass
    on an empty or one-sided slice: an internal and an external target must
    both be present.  The nullary variant is not populated on this corpus;
    ``test_run_store_serving`` drives it by fixture, and the self-repository
    measurement of 2026-09-07 carries 22 of them.

    A red here is a REGRESSION and never a gap to restore.
    """
    served = served_run_store_projection.module_imports
    assert served, "the served slice is empty; the comparison would be hollow"
    resolutions = Counter(dep.resolution for dep in served)
    assert resolutions["external"] and resolutions["analyzed"], resolutions
    stored = canonical_run.facts.analysis.import_observations
    assert len(stored) == len(served), "the family and the slice differ in size"
    assert store_served_slices.module_imports == served


# -- 3. the relationship records -------------------------------------------
#
# RATIFIED 2026-09-07 (canonical model revision 2): the
# ``relationship_observations`` family carries all eight served fields and
# BOTH resolution states, with the multiplicity the producer emits.


def _canonical_symbol(
    qualname: str,
    paths_by_module: Mapping[str, str],
    analyzed_paths: frozenset[str],
) -> SymbolId | None:
    """Undo the producer's glue, through the run's own projections.

    The inverse of :func:`_qualname_head`: a module head resolves through
    ``file_modules``, a path head through the analyzed set, and anything
    else — an import outside the tree — is not a canonical SYMBOL at all.
    Used for the population accounting only.
    """
    head, separator, local = qualname.partition(":")
    if not separator or not local:
        return None
    path = paths_by_module.get(head)
    if path is None:
        path = head if head in analyzed_paths else None
    if path is None:
        return None
    return SymbolId(file=FileId(path=path), qualname=local)


def _relationship_population(
    records: list[RelationshipRecord], canonical_run: CanonicalModel
) -> tuple[Counter[RelationshipResolutionStatus], list[str], list[str]]:
    """The population the comparison must contain before it can see anything:
    both resolution states, and resolved targets split into the run's own
    SYMBOLS and the heads outside it."""
    statuses = Counter(record.resolution_status for record in records)
    paths_by_module = _paths_by_module(canonical_run)
    analyzed = _analyzed_paths(canonical_run)
    resolved = [r.target_qualname for r in records if r.target_qualname is not None]
    internal = [t for t in resolved if _canonical_symbol(t, paths_by_module, analyzed)]
    external = [
        t for t in resolved if _canonical_symbol(t, paths_by_module, analyzed) is None
    ]
    return statuses, internal, external


def test_relationship_facts_are_reconstructible_from_the_canonical_run(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
    store_served_slices: ServedRunSlices,
) -> None:
    """RATIFIED 2026-09-07: the served relationship slice IS expressible.

    This carried ``xfail(strict=True)`` from 2026-09-03 until the
    ``relationship_observations`` family landed: the model had no
    relationship family at all — ``semantic_edges`` filled two of the eight
    served fields from another lane and could not say "unresolved", which
    is 8 of the 17 records here and 49 475 of 112 967 on the self-
    repository.  The marker's exit condition asked for all eight fields and
    both resolution states; this family carries them, and the expected
    failure is removed rather than the comparison weakened.

    The comparison is the production projection against the LIVE producer's
    tuple: every ``RelationshipRecord`` of every source, every field
    (``path`` and ``expression`` included), in the producer's own order,
    with multiplicity expanded.  The population is stated first: both
    resolution states, an internal SYMBOL target and an external opaque
    one, and the family's own target variants — a store that spelled an
    internal target as an opaque head would still serve the same glued
    string, so that mutation is caught here on the FAMILY rather than on
    the slice.  No record repeats on this corpus (the self-repository
    carries 1 342 repeated groups); ``test_run_store_serving`` drives the
    multiplicity by fixture.
    """
    served = served_run_store_projection.relationship_facts
    records = [record for facts in served for record in facts.relationships]
    assert records, "the served slice is empty; the comparison would be hollow"
    statuses, internal, external = _relationship_population(records, canonical_run)
    assert statuses["unresolved"] and statuses["resolved"], statuses
    assert internal and external, (internal, external)
    rows = canonical_run.facts.analysis.relationship_observations
    variants = Counter(type(row.target).__name__ for row in rows)
    assert variants["SymbolId"] == len(internal), variants
    assert variants["OpaqueEntity"] == len(external), variants
    assert variants["UnresolvedTarget"] == statuses["unresolved"], variants
    assert sum(row.occurrence_count for row in rows) == len(records)
    assert store_served_slices.relationship_facts == served


# -- 4. the unit index, through the production projection ------------------


def test_the_unit_index_is_served_by_the_production_projection(
    served_run_store_projection: ServedRunStoreProjection,
    store_served_slices: ServedRunSlices,
) -> None:
    """Section 1 proves the closing line has an owner; this proves the
    projection the surface serves through reproduces the whole index, row
    for row, in the surface's own order."""
    served = served_run_store_projection.unit_inventory
    assert served, "the served slice is empty; the comparison would be hollow"
    assert store_served_slices.unit_inventory == served

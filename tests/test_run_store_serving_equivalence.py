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
2026-09-03 at ``4512acf0``, each written as the equivalence it will one day
satisfy and marked ``xfail(strict=True)``:

``unit_inventory``
    ``qualname``, ``path`` and ``start_line`` all have a canonical owner and
    agree row for row.  ``end_line`` does not.  Of the canonical row types
    reachable from ``AnalysisFacts`` exactly two declare an ``end_line`` at
    all, and neither covers the unit population.

``module_imports``
    Every served field is expressible and every stored row reproduces a
    served row exactly.  The POPULATION is a strict subset: the canonical
    dependency lane ingests only internal source-bearing edges, so that the
    gate and the SCC pass consume one graph, and every external import is
    absent by design.

``relationship_facts``
    There is no relationship family.  ``semantic_edges`` is the only family
    carrying a relation at all — two of the eight served fields, a different
    lane's derivation, and no way at all to say "unresolved", which is
    roughly half of what the surface serves.

**What a red here means.**  When the gap a pin names is closed the pin
XPASSes and CI turns red.  That red says *the proof changed: remove the
expected failure and ratify the new capability*.  It never says *restore the
gap to make the suite green.*

**Why each pin has a control beside it.**  A strict ``xfail`` that fails for
a reason nobody chose — an import error, a fixture that never built a store
— keeps passing as ``xfail`` long after its defect is gone and then never
flips.  So each pin's projection is total (it raises nothing and drops only
a file the run never mapped to a module), and each has a positive control
that drives the SAME projection with the missing piece supplied by hand.
The control shares every helper with the pin, so scaffolding that stopped
short of the comparison turns the control RED instead of leaving the pin
quietly xfailing forever (Probe Validity Law, ``AGENTS.md`` §17).
"""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.canonical import (
    AnalysisFacts,
    CanonicalModel,
    DependencyEndpoint,
    DependencyOccurrenceRow,
    DependencyRelationRow,
    FileId,
    ModuleId,
    RunStore,
    SymbolId,
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


def _closing_lines_the_canonical_run_states(
    model: CanonicalModel,
) -> dict[UnitKey, int]:
    """Every closing line ANY canonical family states, by declaration.

    Both families that declare an ``end_line`` are read, and
    ``test_the_canonical_model_declares_a_closing_line_on_two_row_types``
    enumerates them from the model definitions so this reader cannot quietly
    miss a third.  The ``unit_spans`` family (``UnitSpanRow``) is the third
    that is coming, and that enumeration is what will say so.

    The key carries the first line, so a family answers about a unit only
    when it states that unit's whole span.  That is what makes the join a
    measurement rather than a guess: a security surface is a statement
    *inside* a unit and its span starts elsewhere, so it does not answer —
    while a function clone member IS the unit and does.

    A key two families answer differently is dropped: one declaration with
    two closing lines is a disagreement, not a stated fact.
    """
    stated: dict[UnitKey, set[int]] = {}
    analysis = model.facts.analysis
    for surface in analysis.security_surfaces:
        if surface.qualname is not None:
            key = (surface.file.path, surface.qualname, surface.start_line)
            stated.setdefault(key, set()).add(surface.end_line)
    for group in analysis.clone_groups:
        for item in group.items:
            key = (item.symbol.file.path, item.symbol.qualname, item.start_line)
            stated.setdefault(key, set()).add(item.end_line)
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


def test_the_canonical_model_declares_a_closing_line_on_two_row_types() -> None:
    """The reachability witness for the pin below (Probe Validity Law §1).

    Read from the model DEFINITIONS, not from one run's populated families.
    A reader that asked ``SecuritySurfaceRow`` for a ``symbol`` attribute it
    does not have would find nothing on every corpus and be indistinguishable
    from "no family owns this" — that exact hollow reader is what produced an
    earlier "0 of 15 884" reading of this gap.

    This is a ratchet on the reader's completeness: a new row type carrying a
    closing line turns it red, and the fix is to teach
    ``_closing_lines_the_canonical_run_states`` about it, never to widen the
    expected set.
    """
    row_types = _canonical_row_types()
    assert len(row_types) > 20, row_types.keys()
    declaring = {
        name
        for name, row_type in row_types.items()
        if "end_line" in {field.name for field in dataclasses.fields(row_type)}
    }
    assert declaring == {"CloneItemRow", "SecuritySurfaceRow"}


def test_the_closing_line_reader_reaches_both_families_that_declare_one(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    """Both families answer, and only one of them answers about a unit.

    This is what "no owner" means here, measured rather than assumed.  A
    clone member IS the hosting unit: it states that unit's whole span and
    the closing line agrees.  A security surface is a statement INSIDE a
    unit: it names the same file and the same qualname, its span starts
    somewhere else, and the closing line it states is its own.  A corpus
    carrying only one of the two cannot tell a dead reader from an honest
    absence, so this one carries both.
    """
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
    answering = {key for key in stated if key in served}
    assert answering, "the clone lane stated no unit span"
    assert inside_a_unit, "the surface lane stated no span inside a unit"
    assert all(served[key] == stated[key] for key in answering)
    assert len(answering) < len(served), (
        "every served unit now has a stated closing line; the pin below "
        "should XPASS and its expected failure should be removed"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "unit_inventory: the canonical model has no owner for a unit's "
        "closing line. Of the row types reachable from AnalysisFacts only "
        "CloneItemRow and SecuritySurfaceRow declare an end_line, and neither "
        "covers the unit population: on this corpus they answer for 2 of 12 "
        "units (the clone pair) and the remaining 10 project a closing line "
        "of None; measured on the self-repository at 4512acf0, 0 of 15 934, "
        "because that tree carries no emitted clone group at all. qualname, "
        "path and start_line already agree row for row. "
        "EXIT CONDITION: the unit_spans family -- UnitSpanRow(symbol, "
        "start_line, end_line), key (SYMBOL, start_line), namespace "
        "canonical_model: and deliberately not under the complexity metric "
        "-- is the work that flips this pin. When it lands, teach "
        "_closing_lines_the_canonical_run_states to read it, DELETE this "
        "marker and ratify the new capability. Never restore the gap to keep "
        "the suite green."
    ),
)
def test_unit_inventory_is_reconstructible_from_the_canonical_run(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    projected = _project_unit_inventory(
        modules_by_path=_modules_by_path(canonical_run),
        analyzed_paths=_analyzed_paths(canonical_run),
        units=_units_the_canonical_run_offers(canonical_run),
    )
    assert projected == _served_unit_rows(served_run_store_projection)


def test_unit_inventory_reconstructs_once_a_closing_line_owner_is_supplied(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    """Positive control: the same projection, handed the one missing fact.

    It perturbs the one input the pin measures and nothing else, so it
    proves three things at once — the pin's body reaches the comparison,
    every other served field already agrees exactly (the declaration set,
    the glued head, the path and the first line), and the pin will XPASS the
    day a real owner lands.
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

DependencyRow = tuple[str, str, str, int]


def _endpoint_name(endpoint: DependencyEndpoint) -> str:
    """A dependency endpoint in the producer's own spelling."""
    return endpoint.module if isinstance(endpoint, ModuleId) else endpoint.path


def _project_module_imports(
    occurrences: Iterable[DependencyOccurrenceRow],
) -> frozenset[DependencyRow]:
    """Rebuild the served import slice out of canonical occurrence rows.

    Total: it raises nothing and drops nothing.  ``occurrences`` is the one
    input the pin and its control disagree about.
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


def _occurrences_the_canonical_run_offers(
    model: CanonicalModel,
) -> tuple[DependencyOccurrenceRow, ...]:
    """Every import occurrence the canonical model can state today.

    ``dependency_occurrences`` is the whole of it.  The lane ingests only
    internal source-bearing edges, so that the gate and the SCC pass consume
    one graph; an import whose target is outside the analyzed tree has no
    row here by design, not by omission.
    """
    return tuple(model.facts.analysis.dependency_occurrences)


def _served_import_rows(
    served: ServedRunStoreProjection,
) -> frozenset[DependencyRow]:
    return frozenset(
        (row.source, row.target, row.import_type, row.line)
        for row in served.module_imports
    )


def _occurrences_stubbed_by_hand(
    missing: Iterable[DependencyRow],
) -> tuple[DependencyOccurrenceRow, ...]:
    """The external-target rows the canonical dependency lane omits.

    Fabricated in the canonical row type, not in the served one, so the
    control drives the same endpoint translation the pin does.

    A ``ModuleId`` refuses an empty name, which is not an obstacle here and
    is a finding on its own: 19 served import rows on the self-repository at
    ``4512acf0`` name an empty target, and no canonical identity can hold
    one.  The corpus deliberately carries none, so the fabrication stays a
    fabrication of the population and not of the vocabulary.
    """
    return tuple(
        DependencyOccurrenceRow(
            relation=DependencyRelationRow(
                source=ModuleId(module=source),
                target=ModuleId(module=target),
                dependency_type=import_type,
            ),
            line=line,
            binding="import_time",
            is_lazy=False,
        )
        for source, target, import_type, line in sorted(missing)
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "module_imports: every served field is expressible and every stored "
        "row reproduces a served row exactly, but the canonical population is "
        "a strict SUBSET. _dependency_rows ingests only internal "
        "source-bearing edges so that the gate and the SCC pass consume one "
        "graph, and every external import is therefore absent by design: the "
        "store carries 5 of the 9 served rows on this corpus and the 4 it "
        "does not are exactly the external ones. Measured on the "
        "self-repository at 4512acf0: 6 238 stored occurrences against 10 953 "
        "served rows -- 4 715 served-only, 0 store-only, 152 import names "
        "lost. "
        "EXIT CONDITION: give the canonical model a population that carries "
        "external import targets -- a second lane, or a widened one that does "
        "not disturb the graph the gate consumes -- then DELETE this marker "
        "and ratify the new capability. Never narrow the served slice to "
        "match the store."
    ),
)
def test_module_imports_are_reconstructible_from_the_canonical_run(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    projected = _project_module_imports(
        _occurrences_the_canonical_run_offers(canonical_run)
    )
    assert projected == _served_import_rows(served_run_store_projection)


def test_module_imports_reconstruct_once_the_population_is_widened(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    """Positive control: the same projection over a widened population.

    The load-bearing half is the subset assertion.  It is the claim that
    every row the store DOES carry comes back as a served row field for
    field, with no row the store invented — if any of the four fields
    disagreed, or if the store carried a row the surface does not, widening
    could not repair it.
    """
    served = _served_import_rows(served_run_store_projection)
    offered = _occurrences_the_canonical_run_offers(canonical_run)
    projected = _project_module_imports(offered)
    assert projected, "the canonical dependency lane carried no rows"
    assert projected < served, (
        "the store's import population is no longer a strict subset of the "
        "served one; the pin above no longer measures what it says"
    )
    widened = offered + _occurrences_stubbed_by_hand(served - projected)
    assert _project_module_imports(widened) == served


# -- 3. the relationship records -------------------------------------------

RelationshipRow = tuple[
    str | None,  # relation_kind
    str | None,  # resolution_status
    str | None,  # origin_lane
    str,  # source_qualname
    str | None,  # target_qualname
    str,  # path
    int | None,  # line
    str | None,  # resolution_rule
]


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalRelationship:
    """One relationship in the shape a canonical family would carry it.

    Identities are canonical: a SYMBOL is ``(FILE, local qualname)``, and a
    target outside the analyzed tree is an opaque dotted head, which is how
    the store's own grammar already spells one.  The producer's glued
    ``module:local`` dialect is this projection's OUTPUT, never its input —
    a row that arrived pre-glued would prove nothing about the bridge.
    """

    source: SymbolId
    target: SymbolId | None = None
    target_head: str | None = None
    relation_kind: str | None = None
    resolution_status: str | None = None
    origin_lane: str | None = None
    line: int | None = None
    resolution_rule: str | None = None


def _project_relationships(
    *,
    root: Path,
    modules_by_path: Mapping[str, str],
    analyzed_paths: frozenset[str],
    rows: Iterable[CanonicalRelationship],
) -> frozenset[RelationshipRow]:
    """Rebuild the served relationship slice out of canonical rows.

    Total: it raises nothing and drops only a source FILE the run neither
    mapped to a MODULE nor recorded as analyzed.  Heads are glued by the
    same rule the unit index uses — a module when the run mapped one, the
    file's own path otherwise — because it is one producer dialect and a
    second spelling of it here would be a second dialect.  ``rows`` is the
    one input the pin and its control disagree about.
    """
    projected: set[RelationshipRow] = set()
    for row in rows:
        source_head = _qualname_head(
            row.source.file.path, modules_by_path, analyzed_paths
        )
        if source_head is None:
            continue
        target = row.target_head
        if row.target is not None:
            target_head = _qualname_head(
                row.target.file.path, modules_by_path, analyzed_paths
            )
            target = (
                None if target_head is None else f"{target_head}:{row.target.qualname}"
            )
        projected.add(
            (
                row.relation_kind,
                row.resolution_status,
                row.origin_lane,
                f"{source_head}:{row.source.qualname}",
                target,
                str(root / row.source.file.path),
                row.line,
                row.resolution_rule,
            )
        )
    return frozenset(projected)


def _relationships_the_canonical_run_offers(
    model: CanonicalModel,
) -> tuple[CanonicalRelationship, ...]:
    """Every relationship the canonical model can state today.

    There is no relationship family.  ``semantic_edges`` is the only family
    carrying a relation at all, it fills two of the eight served fields, and
    its row shape has no way to say "unresolved" — an edge is there or it is
    not.
    """
    return tuple(
        CanonicalRelationship(source=edge.source, target=edge.target)
        for edge in model.facts.analysis.semantic_edges
    )


def _canonical_symbol(
    qualname: str,
    paths_by_module: Mapping[str, str],
    analyzed_paths: frozenset[str],
) -> SymbolId | None:
    """Undo the producer's glue, through the run's own projections.

    The inverse of :func:`_qualname_head`: a module head resolves through
    ``file_modules``, a path head through the analyzed set, and anything
    else — an import outside the tree — is not a canonical SYMBOL at all.
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


def _served_relationship_rows(
    served: ServedRunStoreProjection,
) -> frozenset[RelationshipRow]:
    return frozenset(
        (
            record.relation_kind,
            record.resolution_status,
            record.origin_lane,
            record.source_qualname,
            record.target_qualname,
            record.path,
            record.line,
            record.resolution_rule,
        )
        for facts in served.relationship_facts
        for record in facts.relationships
    )


def _relationships_stubbed_by_hand(
    served: ServedRunStoreProjection,
    model: CanonicalModel,
) -> tuple[CanonicalRelationship, ...]:
    """The relationship family the canonical model does not have.

    Fabricated, and deliberately not a copy: every identity is re-stated
    through the run's OWN ``file_modules`` projection, so the control drives
    the same MODULE↔FILE bridge the pin does.  A target the run analyzed
    becomes a canonical SYMBOL; a target outside it stays an opaque head,
    because that is the only thing the canonical model could hold for it.
    """
    paths_by_module = _paths_by_module(model)
    analyzed_paths = _analyzed_paths(model)
    rows: list[CanonicalRelationship] = []
    for facts in served.relationship_facts:
        for record in facts.relationships:
            source = _canonical_symbol(
                record.source_qualname, paths_by_module, analyzed_paths
            )
            assert source is not None, record.source_qualname
            target = (
                None
                if record.target_qualname is None
                else _canonical_symbol(
                    record.target_qualname, paths_by_module, analyzed_paths
                )
            )
            rows.append(
                CanonicalRelationship(
                    source=source,
                    target=target,
                    target_head=(
                        record.target_qualname
                        if record.target_qualname is not None and target is None
                        else None
                    ),
                    relation_kind=record.relation_kind,
                    resolution_status=record.resolution_status,
                    origin_lane=record.origin_lane,
                    line=record.line,
                    resolution_rule=record.resolution_rule,
                )
            )
    return tuple(rows)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "relationship_facts: the canonical model has no relationship family. "
        "semantic_edges is the only family carrying a relation -- 2 of the 8 "
        "served fields, a different lane's derivation, and no representation "
        "of an unresolved edge at all: 3 projected rows against 17 served "
        "records of which 8 are unresolved on this corpus, with not one row "
        "in common. Measured on the self-repository at 4512acf0: 22 713 "
        "projected rows against 99 700 distinct served rows (104 628 records, "
        "50 156 of them unresolved), again with none in common. "
        "relation_kind, resolution_status, "
        "origin_lane, line and resolution_rule have no owner in any family, "
        "and the internal CLASS targets these records name are not carried as "
        "canonical symbols either. "
        "EXIT CONDITION: give the canonical model a relationship family that "
        "carries all eight fields and BOTH resolution states, then DELETE "
        "this marker and ratify the new capability. Never drop the unresolved "
        "half to make the two sides agree."
    ),
)
def test_relationship_facts_are_reconstructible_from_the_canonical_run(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    projected = _project_relationships(
        root=served_run_store_projection.root,
        modules_by_path=_modules_by_path(canonical_run),
        analyzed_paths=_analyzed_paths(canonical_run),
        rows=_relationships_the_canonical_run_offers(canonical_run),
    )
    assert projected == _served_relationship_rows(served_run_store_projection)


def test_relationship_facts_reconstruct_once_the_family_is_stubbed(
    served_run_store_projection: ServedRunStoreProjection,
    canonical_run: CanonicalModel,
) -> None:
    """Positive control: the same projection over a stubbed family.

    What it proves is not that a copy equals itself.  The stub carries
    canonical identities only, so the projection has to rebuild every glued
    qualname and every absolute path from the run's own FILE↔MODULE
    projection — and it proves the canonical model already holds the
    identities such a family would need for its SOURCES.  It does not hold
    them for the internal CLASS targets, which is why those arrive as
    fabricated symbols and not as a lookup.
    """
    served = _served_relationship_rows(served_run_store_projection)
    assert served, "the served slice is empty; the comparison would be hollow"
    offered = _relationships_the_canonical_run_offers(canonical_run)
    assert offered, "semantic_edges carried no rows; nothing was projected"
    stubbed = _relationships_stubbed_by_hand(served_run_store_projection, canonical_run)
    # The population the stub has to carry, stated before it is compared: a
    # control that never saw an unresolved record would prove nothing about
    # the half of the slice the store cannot represent.
    assert any(row.target is None and row.target_head is None for row in stubbed)
    assert any(row.target is not None for row in stubbed)
    assert any(row.target_head is not None for row in stubbed)
    assert (
        _project_relationships(
            root=served_run_store_projection.root,
            modules_by_path=_modules_by_path(canonical_run),
            analyzed_paths=_analyzed_paths(canonical_run),
            rows=stubbed,
        )
        == served
    )

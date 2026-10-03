# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The served slices of ONE published run, read bounded out of the store.

The MCP surface serves three slices it never wrote into the sealed report
— the unit index, the module imports and the per-function relationship
records — and until canonical model revision 2 it could serve them from
one place only: the parent's memory.  This module is the other place.  It
reads the families those slices are expressible from
(:data:`~codeclone.canonical.store.FAMILY_UNIT_SPAN`,
:data:`~codeclone.canonical.store.FAMILY_IMPORT_OBSERVATION`,
:data:`~codeclone.canonical.store.FAMILY_RELATIONSHIP_OBSERVATION`, plus
the two identity families that glue a head back onto a local name) through
:meth:`RunStore.read_family` — never :meth:`RunStore.read_run`, which
materializes a whole model to answer one slice — and projects them into the
exact value types the surface already serves.

**One owner of the projection.**  The producer's serving dialect — a
``module:local`` glued qualname whose head is the file's module when the
run mapped one and the file's own path otherwise, an absolute source path
under the analysis root, the producer's own row orders — is spelled here
and nowhere else.  The equivalence pins call THIS projection and compare
its answer with the live producer's on the same execution; a pin that
rebuilt the projection for itself would stay green under a real mutation
of the one that serves.

**What is re-spelled, and how it is held.**  Two producer sort keys are
restated here because the canonical package may not import their owners
(``core/_types._module_dep_sort_key`` — ``core`` imports this package —
and ``analysis/_module_walk._relationship_record_sort_key``).  Each is a
pure function of the served value's public fields, and each is pinned
ORDER-SENSITIVELY against the live producer's own tuple on the serving
corpus and on the self-repository, so a drift on either side reddens the
measurement instead of hiding in a set comparison.

**The authority candidates** are read here too, for the one report section
the surface pages rather than slices (``check_authority`` with
``section="candidates"``).  Their projection is NOT spelled here: the
published row -- its class-B ``candidate_id`` and ``score``, the group
conclusions the stored authority graph settles, the document builder's key
and row order -- has one owner, ``canonical.authority_projection``, and
this module only hands it the four families it needs, read bounded.  What
this module adds is the witness the families cannot carry: whether the run
MEASURED them at all.

**The run summary** (``get_run_summary``, consumer migration C1) is the
third reading.  Its fields are owned by the three tier projections
(``summary_projection``, ``comparison_projection``,
``evaluation_projection``); this module only arranges their answers into the
blocks the surface publishes, in the surface's key order, so the surface
compares and never computes.  It is the one reading here that is NOT
bounded: the tier projections take a whole model, so the run is read with
:meth:`RunStore.read_run`, which also proves the run whole (membership,
scope receipt, identity) -- the cost is measured and stated in the C1 wave
report rather than hidden.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from codeclone.canonical.authority_projection import candidate_rows_from_families
from codeclone.canonical.comparison_projection import (
    baseline_state,
    metric_deltas,
    metrics_baseline_state,
    new_by_source_kind,
    new_clone_groups,
    novelty_counts,
)
from codeclone.canonical.comparison_rows import (
    NOVELTY_KNOWN,
    NOVELTY_NEW,
    NOVELTY_UNAVAILABLE,
)
from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.evaluation_projection import (
    CLONES_ONLY_MODE,
    diff_health_delta,
    health_payload,
)
from codeclone.canonical.identity import (
    FileId,
    ImportTarget,
    ModuleId,
    OpaqueDottedHead,
    RelationshipTarget,
    SymbolId,
    UnresolvedTarget,
)
from codeclone.canonical.model import (
    CanonicalModel,
    ImportObservationRow,
    RelationshipObservationRow,
    relationship_resolution_status,
)
from codeclone.canonical.store import (
    FAMILY_ANALYSIS_POPULATION,
    FAMILY_CANDIDATE,
    FAMILY_FILE_MODULE,
    FAMILY_GRAPH_NODE,
    FAMILY_IMPORT_OBSERVATION,
    FAMILY_RELATIONSHIP_OBSERVATION,
    FAMILY_SEMANTIC_EDGE,
    FAMILY_UNIT_SPAN,
    RunStore,
)
from codeclone.canonical.summary_projection import (
    analysis_mode,
    analysis_profile,
    coverage_join,
    dead_code,
    finding_counts,
    inventory,
    security_surfaces,
)
from codeclone.contracts.report_identity import PRODUCER_STATE_COMPLETE
from codeclone.models import (
    DependencyBinding,
    DependencyMechanism,
    DependencyResolution,
    FunctionRelationshipFacts,
    ImportSyntaxKind,
    ModuleDep,
    RelationshipKind,
    RelationshipOriginLane,
    RelationshipRecord,
    RelationshipResolutionStatus,
)


@dataclass(frozen=True, slots=True)
class ServedUnitLocation:
    """One row of the served unit index, in the surface's own field set."""

    qualname: str
    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedRunSlices:
    """The three off-report slices of one run, as the surface serves them.

    ``run_id`` names the store run the slices were read from; the two
    relationship and import slices are the very value types the record
    holds (``r2`` values), and the unit index is the surface's own row shape
    copied field for field.
    """

    run_id: str
    unit_inventory: tuple[ServedUnitLocation, ...]
    relationship_facts: tuple[FunctionRelationshipFacts, ...]
    module_imports: tuple[ModuleDep, ...]


class _Heads:
    """The producer's glue rule over one run's FILE-MODULE relation."""

    def __init__(self, modules_by_path: Mapping[str, str]):
        self._modules_by_path = modules_by_path

    def of(self, path: str) -> str:
        """The head the producer glues onto a local name of ``path``.

        The producer's own rule, verbatim (``_source_module_key``: the
        module when the file has a module identity, the file's path
        otherwise): a FILE the run mapped to a MODULE is headed by that
        module, and any other file by its own path — 54 of 11 445 served
        import sources and 81 of 15 934 served units @ f117a8ad live in
        files ``file_modules`` does not cover.  Total by construction, so
        the projection can never drop a row the store carries.
        """
        module = self._modules_by_path.get(path)
        return path if module is None else module

    def glued(self, symbol: SymbolId) -> str:
        return f"{self.of(symbol.file.path)}:{symbol.qualname}"


def _import_target_text(target: ImportTarget) -> str:
    """The served ``ModuleDep.target``: the producer's own spelling of the
    variant, and the empty string for the nullary one (what the producer
    writes when ``resolved_target`` is ``None``)."""
    if isinstance(target, ModuleId):
        return target.module
    if isinstance(target, FileId):
        return target.path
    if isinstance(target, OpaqueDottedHead):
        return target.text
    return ""


def _module_dep(row: ImportObservationRow, heads: _Heads) -> ModuleDep:
    source = row.source
    # The vocabularies were proven at the row (``__post_init__`` refuses an
    # unknown value), so narrowing them to the producer's Literal types here
    # asserts nothing the model did not already check.
    return ModuleDep(
        source=source.module if isinstance(source, ModuleId) else source.path,
        target=_import_target_text(row.target),
        import_type=cast("ImportSyntaxKind", row.dependency_type),
        line=row.line,
        resolution=cast("DependencyResolution", row.resolution),
        inventory_expansion=row.inventory_expansion,
        level=row.level,
        requested_module=row.requested_module,
        requested_names=row.requested_names,
        candidate_targets=row.candidate_targets,
        mechanism=cast("DependencyMechanism", row.mechanism),
        binding=cast("DependencyBinding", row.binding),
        is_lazy=row.is_lazy,
    )


def module_dep_order_key(dep: ModuleDep) -> tuple[str, str, str, int]:
    """The producer's served order (``core/_types._module_dep_sort_key``),
    restated for the reason the module docstring gives and pinned against
    the live producer order-sensitively."""
    return dep.source, dep.target, dep.import_type, dep.line


def relationship_record_order_key(
    record: RelationshipRecord,
) -> tuple[str, str, str, str, int, str, str]:
    """The producer's order of one function's records
    (``analysis/_module_walk._relationship_record_sort_key``), restated for
    the reason the module docstring gives and pinned against the live
    producer order-sensitively."""
    return (
        record.relation_kind,
        record.origin_lane,
        record.target_qualname or "",
        record.path,
        record.line,
        record.resolution_rule or "",
        record.expression or "",
    )


def _relationship_target_text(target: RelationshipTarget, heads: _Heads) -> str | None:
    if isinstance(target, UnresolvedTarget):
        return None
    if isinstance(target, SymbolId):
        return heads.glued(target)
    return f"{target.head}:{target.qualname}"


def _relationship_facts(
    rows: tuple[RelationshipObservationRow, ...], heads: _Heads, root: Path
) -> tuple[FunctionRelationshipFacts, ...]:
    """The served facts: one entry per source, records expanded by their
    multiplicity and ordered as the producer orders them."""
    by_source: dict[str, list[RelationshipRecord]] = {}
    for row in rows:
        source_qualname = heads.glued(row.source)
        status = relationship_resolution_status(row.target)
        record = RelationshipRecord(
            relation_kind=cast("RelationshipKind", row.relation_kind),
            resolution_status=cast("RelationshipResolutionStatus", status),
            origin_lane=cast("RelationshipOriginLane", row.origin_lane),
            source_qualname=source_qualname,
            target_qualname=_relationship_target_text(row.target, heads),
            path=str(root / row.source.file.path),
            line=row.line,
            expression=row.expression,
            resolution_rule=row.resolution_rule,
        )
        by_source.setdefault(source_qualname, []).extend(
            [record] * row.occurrence_count
        )
    return tuple(
        FunctionRelationshipFacts(
            source_qualname=source_qualname,
            relationships=tuple(sorted(records, key=relationship_record_order_key)),
        )
        for source_qualname, records in sorted(by_source.items())
    )


def read_served_run_slices(
    store: RunStore, run_id: str, *, root: Path
) -> ServedRunSlices:
    """Read one run's three served slices, bounded, and project them.

    Four family reads and no model: the identity glue (``file_module``) and
    the three slice families.  ``root`` is the analysis root the surface
    serves under — the relationship ``path`` is that root joined to the
    source file, which is the producer's own spelling of it.  A run the
    store does not hold refuses typed from the first read
    (``UnknownRunError``); nothing here answers about a different run than
    the one named.
    """
    heads = _Heads(
        {
            relation.file.path: relation.module.module
            for relation in store.read_family(run_id, FAMILY_FILE_MODULE)
        }
    )
    units = sorted(
        {
            ServedUnitLocation(
                qualname=heads.glued(span.symbol),
                path=span.symbol.file.path,
                start_line=span.start_line,
                end_line=span.end_line,
            )
            for span in store.read_family(run_id, FAMILY_UNIT_SPAN)
        },
        key=lambda unit: (unit.qualname, unit.path, unit.start_line, unit.end_line),
    )
    imports = sorted(
        (
            _module_dep(row, heads)
            for row in store.read_family(run_id, FAMILY_IMPORT_OBSERVATION)
        ),
        key=module_dep_order_key,
    )
    facts = _relationship_facts(
        store.read_family(run_id, FAMILY_RELATIONSHIP_OBSERVATION), heads, root
    )
    return ServedRunSlices(
        run_id=run_id,
        unit_inventory=tuple(units),
        relationship_facts=facts,
        module_imports=tuple(imports),
    )


#: The producer family whose execution state witnesses the six authority
#: families: the metric-registry name the analysis population records it
#: under (``core.canonical_snapshot.producer_execution_population``).
AUTHORITY_PRODUCER_FAMILY: Final = "semantic_authority"


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedAuthorityCandidates:
    """One run's authority candidates, as ``check_authority`` pages them.

    ``items`` are the published candidate rows -- every column, in the
    document builder's key order and candidate order -- and ``run_id``
    names the store run they were read from.
    """

    run_id: str
    items: tuple[Mapping[str, object], ...]


def _require_measured_authority(store: RunStore, run_id: str) -> None:
    """Refuse a candidate family the run never measured.

    A canonical row family carries no "absent" marker: a run whose semantic
    lane did not execute is published with six EMPTY authority families,
    and the only witness that tells that emptiness from a measured one is
    the run's execution population.  A read that skipped it would serve
    "no candidates" for a population nobody looked at -- absence of
    execution projected into a zero, which the population law forbids.
    Only ``complete`` is a measurement; every other state, and a run that
    carries no population record at all, is refused typed.
    """
    states = {
        family: state
        for population in store.read_family(run_id, FAMILY_ANALYSIS_POPULATION)
        for family, state in population.producer_states
    }
    state = states.get(AUTHORITY_PRODUCER_FAMILY, "unwitnessed")
    if state != PRODUCER_STATE_COMPLETE:
        raise CanonicalModelError(
            f"run {run_id[:12]} carries no measured authority candidate "
            f"population: producer {AUTHORITY_PRODUCER_FAMILY} is {state}"
        )


def read_served_authority_candidates(
    store: RunStore, run_id: str
) -> ServedAuthorityCandidates:
    """Read one run's candidate rows, bounded, and project them.

    The execution witness first, then the four families the one owner of
    the reconstruction needs (``canonical.authority_projection``): the
    candidate natural keys, the authority graph's nodes and edges that
    settle the group conclusions, and the FILE-MODULE relation that heads
    the producer keys.  Never :meth:`RunStore.read_run`.  A run the store
    does not hold refuses typed from the first read (``UnknownRunError``);
    a population that was not measured refuses as unexpressible.
    """
    _require_measured_authority(store, run_id)
    items = candidate_rows_from_families(
        candidates=store.read_family(run_id, FAMILY_CANDIDATE),
        graph_nodes=store.read_family(run_id, FAMILY_GRAPH_NODE),
        semantic_edges=store.read_family(run_id, FAMILY_SEMANTIC_EDGE),
        file_modules=store.read_family(run_id, FAMILY_FILE_MODULE),
    )
    return ServedAuthorityCandidates(run_id=run_id, items=items)


#: The surface's word for a block whose producers a clones-only run never
#: ran -- the same two keys ``evaluation_projection.health_payload`` answers
#: for ``health`` and the MCP helpers spell for ``security_surfaces``.
_METRICS_SKIPPED: Final[Mapping[str, object]] = {
    "available": False,
    "reason": "metrics_skipped",
}

#: The analysis half of the surface's ``security_surfaces`` block.  A run
#: whose metrics ran always states all four, zero when it holds no row.
SECURITY_SURFACE_COUNT_KEYS: Final[tuple[str, ...]] = (
    "items",
    "categories",
    "production",
    "tests",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedRunSummary:
    """The store-carried fields of one run's ``get_run_summary``.

    Each attribute is one top-level block of the surface's answer, in the
    surface's own key order and spelling; an empty mapping is the surface's
    absence (it omits the key).  What the store does NOT carry is absent
    here by construction, and named so it cannot rot:

    * ``baseline`` has no ``runtime_python_tag`` / ``interpreter_provenance``
      -- the interpreter that ran, execution (``comparison_projection``);
    * ``inventory`` always states the four counts: whether the surface
      shows ``functions`` / ``classes`` or an ``entity_counts`` refusal is
      the report's inventory scope, which turns on the cache split a run
      store keeps out of its rows (DET-01), so the surface keeps that branch;
    * ``security_surfaces`` has no ``report_only`` / ``note`` (presentation).

    Every other field of the answer -- identity, version, provenance,
    schema, cache, warnings, failures, drift, hints -- is not a store fact.
    """

    run_id: str
    mode: str
    baseline: Mapping[str, object]
    metrics_baseline: Mapping[str, object]
    inventory: Mapping[str, object]
    health: Mapping[str, object]
    findings: Mapping[str, object]
    diff: Mapping[str, object]
    analysis_profile: Mapping[str, int]
    dead_code: Mapping[str, object]
    coverage_join: Mapping[str, object]
    security_surfaces: Mapping[str, object]


def _findings_block(model: CanonicalModel) -> dict[str, object]:
    """``findings``: the counts over the projected finding universe, the
    family breakdown restricted to the families that hold a group (the
    surface builds it from the groups present), the tri-state novelty."""
    counts = finding_counts(model)
    novelty = novelty_counts(model)
    by_family = cast("Mapping[str, int]", counts["by_family"])
    return {
        "total": counts["total"],
        "new": novelty[NOVELTY_NEW],
        "known": novelty[NOVELTY_KNOWN],
        "unavailable": novelty[NOVELTY_UNAVAILABLE],
        "by_family": {family: count for family, count in by_family.items() if count},
        "production": counts["production"],
        "new_by_source_kind": new_by_source_kind(model),
    }


def _diff_block(model: CanonicalModel) -> dict[str, object]:
    """``diff``: the clone novelty under its availability, the stored health
    delta, and the six delta terms, in the surface's order."""
    facts = model.facts.comparison
    return {
        "new_clones": new_clone_groups(facts),
        "health_delta": diff_health_delta(model),
        **metric_deltas(facts),
    }


def _security_block(model: CanonicalModel, mode: str) -> dict[str, object]:
    if mode == CLONES_ONLY_MODE:
        return dict(_METRICS_SKIPPED)
    return {
        **dict.fromkeys(SECURITY_SURFACE_COUNT_KEYS, 0),
        **security_surfaces(model),
    }


def run_summary_from_model(model: CanonicalModel, *, run_id: str) -> ServedRunSummary:
    """Arrange one stored run's tier projections into the summary blocks."""
    mode = analysis_mode(model)
    facts = model.facts.comparison
    return ServedRunSummary(
        run_id=run_id,
        mode=mode,
        baseline=baseline_state(facts),
        metrics_baseline=metrics_baseline_state(facts),
        inventory=inventory(model),
        health=health_payload(model),
        findings=_findings_block(model),
        diff=_diff_block(model),
        analysis_profile=analysis_profile(model),
        dead_code=dead_code(model),
        coverage_join=coverage_join(model),
        security_surfaces=_security_block(model, mode),
    )


def read_served_run_summary(store: RunStore, run_id: str) -> ServedRunSummary:
    """Read one published run whole and arrange its summary blocks.

    :meth:`RunStore.read_run`, not a family read: the tier projections take
    a model (see the module docstring).  A run the store does not hold
    refuses typed (``UnknownRunError``), as every reading here does.
    """
    return run_summary_from_model(store.read_run(run_id), run_id=run_id)


__all__ = [
    "AUTHORITY_PRODUCER_FAMILY",
    "SECURITY_SURFACE_COUNT_KEYS",
    "ServedAuthorityCandidates",
    "ServedRunSlices",
    "ServedRunSummary",
    "ServedUnitLocation",
    "module_dep_order_key",
    "read_served_authority_candidates",
    "read_served_run_slices",
    "read_served_run_summary",
    "relationship_record_order_key",
    "run_summary_from_model",
]

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
compares and never computes.  The tier projections take a model, so the
run is read with :func:`~codeclone.canonical.store.read_named_families`:
the families the projections read, and no other -- every other family of
that model is a typed absence, so a projection reaching past the
declaration refuses instead of reading "empty".

**Every reading declares its families.**  Each of the three readings here
names the families it reads in one constant beside it
(:data:`SERVED_SLICE_FAMILIES`, :data:`SERVED_AUTHORITY_CANDIDATE_FAMILIES`,
:data:`RUN_SUMMARY_FAMILIES`), and each declaration is held equal to what
the reading actually reads -- complete, and with nothing it could do
without (``tests/test_run_summary_declared_families.py``).  A consumer
that moves onto the store next declares its own the same way.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast, get_args

from codeclone.canonical.authority_projection import candidate_rows_from_families
from codeclone.canonical.blast_radius_facts import BlastRadiusFacts
from codeclone.canonical.blast_radius_projection import blast_radius_facts_from_model
from codeclone.canonical.comparison_projection import (
    SUMMARY_DIFF_BLOCK,
    SUMMARY_HEALTH_BLOCK,
    answered_if_compared,
    baseline_state,
    group_novelty,
    metric_deltas,
    metrics_baseline_state,
    new_by_source_kind,
    new_clone_groups,
    novelty_counts,
    stored_comparison_state,
)
from codeclone.canonical.comparison_rows import (
    NOVELTY_KNOWN,
    NOVELTY_NEW,
    NOVELTY_UNAVAILABLE,
)
from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.evaluation_projection import (
    CLONES_ONLY_MODE,
    PRODUCTION_HOTSPOT,
    diff_health_delta,
    health_payload,
    health_score,
    selection,
    suggestion_total,
)
from codeclone.canonical.evaluation_rows import FindingEvaluationRow, finding_effort
from codeclone.canonical.finding_projection import (
    PROJECTED_FAMILIES,
    projected_finding_groups,
    projected_once,
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
    AnalysisFacts,
    CanonicalModel,
    ImportObservationRow,
    RelationshipObservationRow,
    relationship_resolution_status,
)
from codeclone.canonical.store import (
    FAMILY_ADOPTION_COUNT,
    FAMILY_ADOPTION_DELTA,
    FAMILY_ANALYSIS_POPULATION,
    FAMILY_API_SURFACE_DELTA,
    FAMILY_BASELINE_WITNESS,
    FAMILY_CANDIDATE,
    FAMILY_CLONE_GROUP,
    FAMILY_CLONE_NOVELTY,
    FAMILY_COHESION_HOTSPOT,
    FAMILY_COMPARISON_AVAILABILITY,
    FAMILY_COMPLEXITY_HOTSPOT,
    FAMILY_COMPLEXITY_NOVELTY,
    FAMILY_COUPLING_COHESION,
    FAMILY_COUPLING_HOTSPOT,
    FAMILY_COUPLING_NOVELTY,
    FAMILY_COVERAGE_JOIN,
    FAMILY_COVERAGE_UNIT,
    FAMILY_DEAD_CODE_SUMMARY,
    FAMILY_DEAD_SYMBOL_GROUP,
    FAMILY_DEAD_SYMBOL_NOVELTY,
    FAMILY_DEPENDENCY_CYCLE,
    FAMILY_DEPENDENCY_CYCLE_NOVELTY,
    FAMILY_DEPENDENCY_RELATION,
    FAMILY_DISABLED_CAPABILITY,
    FAMILY_FILE_MODULE,
    FAMILY_FINDING_EVALUATION,
    FAMILY_GRAPH_NODE,
    FAMILY_HEALTH_DELTA,
    FAMILY_HEALTH_RESULT,
    FAMILY_HOTLIST_SELECTION,
    FAMILY_IMPORT_OBSERVATION,
    FAMILY_LANE_TRUST,
    FAMILY_METRICS_BASELINE_WITNESS,
    FAMILY_OVERLOADED_MODULE,
    FAMILY_RELATIONSHIP_OBSERVATION,
    FAMILY_RISK_OBSERVATION,
    FAMILY_RUN_SCALAR,
    FAMILY_SECURITY_SURFACE,
    FAMILY_SEMANTIC_EDGE,
    FAMILY_STRUCTURAL_GROUP,
    FAMILY_SUPPRESSED_CLONE_GROUP,
    FAMILY_UNIT_RISK_RESULT,
    FAMILY_UNIT_SPAN,
    FAMILY_UNREACHABLE_STATEMENT_GROUP,
    FAMILY_VIOLATION,
    ReadWhen,
    RunStore,
    read_named_families,
)
from codeclone.canonical.summary_projection import (
    analysis_mode,
    analysis_profile,
    authority_counts,
    coverage_join,
    dead_code,
    design_maxima,
    dominant_source_kind,
    finding_counts,
    inventory,
    security_surfaces,
    source_kind_breakdown,
)
from codeclone.contracts import FAMILY_CLONES, ObservedPopulation
from codeclone.contracts.report_identity import PRODUCER_STATE_COMPLETE
from codeclone.domain.findings import FAMILY_CLONE
from codeclone.domain.source_scope import SOURCE_KIND_PRODUCTION
from codeclone.metrics.coverage_join import permille
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
from codeclone.report.gates.evaluator import GateState, with_comparison_inputs


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


#: The families :func:`read_served_run_slices` reads.
SERVED_SLICE_FAMILIES: Final = (
    FAMILY_FILE_MODULE,
    FAMILY_IMPORT_OBSERVATION,
    FAMILY_RELATIONSHIP_OBSERVATION,
    FAMILY_UNIT_SPAN,
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


#: The families :func:`read_served_authority_candidates` reads: the
#: execution witness, then the four the reconstruction needs.
SERVED_AUTHORITY_CANDIDATE_FAMILIES: Final = (
    FAMILY_ANALYSIS_POPULATION,
    FAMILY_CANDIDATE,
    FAMILY_FILE_MODULE,
    FAMILY_GRAPH_NODE,
    FAMILY_SEMANTIC_EDGE,
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
    """Arrange one stored run's tier projections into the summary blocks.

    The comparison fields of ``health`` and ``diff`` state a number only
    for a comparison the stored run made (ruling 2026-10-03, one owner:
    ``comparison_projection.answered_if_compared``).  The finding groups the
    blocks are counted over are projected once for the whole arrangement
    (``finding_projection.projected_once``)."""
    with projected_once():
        return _run_summary(model, run_id=run_id)


def _run_summary(model: CanonicalModel, *, run_id: str) -> ServedRunSummary:
    mode = analysis_mode(model)
    facts = model.facts.comparison
    state = stored_comparison_state(model)
    return ServedRunSummary(
        run_id=run_id,
        mode=mode,
        baseline=baseline_state(facts),
        metrics_baseline=metrics_baseline_state(facts),
        inventory=inventory(model),
        health=answered_if_compared(SUMMARY_HEALTH_BLOCK, health_payload(model), state),
        findings=_findings_block(model),
        diff=answered_if_compared(SUMMARY_DIFF_BLOCK, _diff_block(model), state),
        analysis_profile=analysis_profile(model),
        dead_code=dead_code(model),
        coverage_join=coverage_join(model),
        security_surfaces=_security_block(model, mode),
    )


#: The authority graph settles the conclusions of the violation rows and of
#: nothing else (``authority_projection.violation_projection_rows``): a
#: reading that needs it reads it when the run holds a violation row, and a
#: run that holds none -- the self-repository: 0 rows, against 49 361 graph
#: rows and 60-75 % of every store answer (serving-cost audit, 2026-10-05) --
#: never pays for it.
AUTHORITY_GRAPH_WHEN_VIOLATIONS: Final = ReadWhen(
    decider=FAMILY_VIOLATION, families=(FAMILY_GRAPH_NODE, FAMILY_SEMANTIC_EDGE)
)
#: The risk observations state the complexity of a coverage group's unit
#: (``finding_projection.coverage_group_skeletons``), which is the only use
#: the run summary and the blast radius have for them: they read them when
#: the run holds a coverage join.
RISK_WHEN_COVERAGE_JOIN: Final = ReadWhen(
    decider=FAMILY_COVERAGE_JOIN, families=(FAMILY_RISK_OBSERVATION,)
)

#: The families the run summary's projections read on every run -- every
#: one, and none they could do without -- and the conditions under which
#: they read three more (``tests/test_run_summary_declared_families.py``,
#: per branch of each condition).  Measured 2026-10-03 on the sixteen served
#: populations, flask and the self-repository (32 of the store's 56
#: families); the two comparison-state inputs (``disabled_capability``,
#: ``lane_trust``) are read on every run; the authority graph and the risk
#: observations moved behind their conditions 2026-10-05.
RUN_SUMMARY_FAMILIES: Final = (
    FAMILY_ADOPTION_DELTA,
    FAMILY_ANALYSIS_POPULATION,
    FAMILY_API_SURFACE_DELTA,
    FAMILY_BASELINE_WITNESS,
    FAMILY_CLONE_GROUP,
    FAMILY_CLONE_NOVELTY,
    FAMILY_COHESION_HOTSPOT,
    FAMILY_COMPARISON_AVAILABILITY,
    FAMILY_COMPLEXITY_HOTSPOT,
    FAMILY_COMPLEXITY_NOVELTY,
    FAMILY_COUPLING_HOTSPOT,
    FAMILY_COUPLING_NOVELTY,
    FAMILY_COVERAGE_JOIN,
    FAMILY_COVERAGE_UNIT,
    FAMILY_DEAD_CODE_SUMMARY,
    FAMILY_DEAD_SYMBOL_GROUP,
    FAMILY_DEAD_SYMBOL_NOVELTY,
    FAMILY_DEPENDENCY_CYCLE,
    FAMILY_DEPENDENCY_CYCLE_NOVELTY,
    FAMILY_DISABLED_CAPABILITY,
    FAMILY_FILE_MODULE,
    FAMILY_HEALTH_DELTA,
    FAMILY_HEALTH_RESULT,
    FAMILY_LANE_TRUST,
    FAMILY_METRICS_BASELINE_WITNESS,
    FAMILY_RUN_SCALAR,
    FAMILY_SECURITY_SURFACE,
    FAMILY_STRUCTURAL_GROUP,
    FAMILY_SUPPRESSED_CLONE_GROUP,
    FAMILY_UNREACHABLE_STATEMENT_GROUP,
    FAMILY_VIOLATION,
)
#: The run summary's read conditions, in the order they are decided.
RUN_SUMMARY_READ_WHEN: Final = (
    AUTHORITY_GRAPH_WHEN_VIOLATIONS,
    RISK_WHEN_COVERAGE_JOIN,
)


def read_served_run_summary(store: RunStore, run_id: str) -> ServedRunSummary:
    """Read the declared families of one published run and arrange its
    summary blocks.

    Bounded: :data:`RUN_SUMMARY_FAMILIES`, and the families of each of
    :data:`RUN_SUMMARY_READ_WHEN` whose condition the run's own rows meet,
    each row proven against its content address; a projection that reached
    past the declaration would refuse typed (``UnreadFamilyError``, a stored
    answer the projection cannot express), never read an empty family.  A
    run the store does not hold refuses typed (``UnknownRunError``), as
    every reading here does.
    """
    model = read_named_families(
        store, run_id, RUN_SUMMARY_FAMILIES, read_when=RUN_SUMMARY_READ_WHEN
    )
    return run_summary_from_model(model, run_id=run_id)


# -- the patch contract (consumer migration C6) -----------------------------
#
# ``check_patch_contract`` (and the verification ``finish_controlled_change``
# runs) reads, per run, the facts below and nothing else of the run: its
# health score, the per-symbol complexity / coupling / cohesion values, the
# budget's aggregates, the baseline status, its finding universe (id, kind,
# severity, paths) and the inputs of a gate evaluated under the BUDGET's
# request.  The verdicts -- the comparison of two runs, the gate under a
# strictness profile, the scope partition -- are the session's arithmetic
# over these facts (``evaluation_projection``: an answer under a request
# other than the run's own is not projected), so this reading carries the
# facts and the surface keeps computing.


#: The metric families the verifier reads per symbol, and the stored
#: dimension each one is: complexity off the risk lane, coupling and
#: cohesion off the class lane.
PATCH_METRIC_DIMENSIONS: Final[Mapping[str, str]] = {
    "complexity": "cyclomatic_complexity",
    "coupling": "cbo",
    "cohesion": "lcom4",
}
#: The clone kinds the budget's ``clone_groups`` and the gate's clone total
#: count (the surface's ``func_clones_count + block_clones_count``).
PATCH_CLONE_KINDS: Final[tuple[str, ...]] = ("function", "block")
#: The cycle kind the gate's import-cycle terms count.
_IMPORT_CYCLE: Final = "import_cycle"
#: The gate state's population when the run states none, as the document
#: reader defaults it (``report.gates.evaluator``).
_DEFAULT_POPULATION: Final = "complete_nonempty"


#: One measured declaration of one patch metric family: its
#: ``(path, glued qualname)`` key, its ``(start_line, end_line)`` span (``None``
#: where the store keeps none) and its value.
PatchMetricElement = tuple[tuple[str, str], tuple[int, int] | None, int]


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedPatchRun:
    """The facts one run lends the patch contract, read out of the store.

    ``metric_items`` maps each of :data:`PATCH_METRIC_DIMENSIONS` to the
    run's whole population of :data:`PatchMetricElement` elements, sorted:
    one element per measured declaration, so two declarations that share a
    key are two elements.  Nothing here maps a key to one value --
    which of two candidates a key names is the verifier's question, and its
    answer is that it names neither; ``findings`` maps each
    tracked family (the document's key) to its groups, each carrying the
    severity the run's evaluation stated; ``gate_state`` with ``lane_trust``
    and ``enabled_lanes`` is everything the one gate evaluator needs to
    answer under any request.  ``coverage_join_status`` is ``None`` for a
    run that was handed no coverage report.
    """

    run_id: str
    analysis_mode: str
    health_score: int | None
    metric_items: Mapping[str, tuple[PatchMetricElement, ...]]
    dependency_cycles: int
    clone_groups: int
    dead_code_high_confidence: int
    baseline_status: str
    findings: Mapping[str, tuple[Mapping[str, object], ...]]
    gate_state: GateState
    lane_trust: Mapping[str, str]
    enabled_lanes: tuple[str, ...]
    coverage_join_status: str | None
    coverage_invalid_reason: str | None


def _patch_metric_items(
    model: CanonicalModel, heads: _Heads
) -> dict[str, tuple[PatchMetricElement, ...]]:
    """Each metric family's per-declaration population, in the document's
    spelling, sorted.

    A risk row is one declaration (its key carries the start line), so two
    ``def _calc`` in one module are two complexity elements under one
    ``(path, symbol)``.  A dict comprehension here once kept whichever of
    them a ``frozenset`` yielded last: 1 or 4 by ``PYTHONHASHSEED`` on
    ``cxdup`` (measured 2026-10-19).  Its span is the declaration's own:
    the start line its risk row is keyed by and the end line of the unit
    span stored under the same ``(SYMBOL, start_line)`` -- ``None`` when no
    such unit span is stored, never a guessed end.  A class row is keyed by
    its symbol, so a class key holds one element here by the lane's own
    law, and the class lane stores no span: its elements carry ``None``.
    The class lane drops a zero row, so a dimension a MEASURED class (one
    the lane holds any row for) does not carry is its measured zero -- the
    rule ``summary_projection.design_maxima`` states for the maxima, applied
    per symbol so a coupling that rises from zero is a rise from zero.
    """
    facts = model.facts.analysis

    def key(symbol: SymbolId) -> tuple[str, str]:
        return symbol.file.path, heads.glued(symbol)

    measured = {key(row.symbol) for row in facts.coupling_cohesion_observations}
    items: dict[str, tuple[PatchMetricElement, ...]] = {
        "complexity": _complexity_elements(facts, key)
    }
    for family in ("coupling", "cohesion"):
        values = {
            key(row.symbol): row.numerator
            for row in facts.coupling_cohesion_observations
            if row.dimension == PATCH_METRIC_DIMENSIONS[family]
        }
        items[family] = tuple(
            (symbol, None, values.get(symbol, 0)) for symbol in sorted(measured)
        )
    return items


def _complexity_elements(
    facts: AnalysisFacts, key: Callable[[SymbolId], tuple[str, str]]
) -> tuple[PatchMetricElement, ...]:
    """One complexity element per risk row, sorted by key and start line,
    each with the span of the unit stored under its ``(SYMBOL, start_line)``."""
    ends = {(row.symbol, row.start_line): row.end_line for row in facts.unit_spans}
    rows = sorted(
        (
            row
            for row in facts.risk_observations
            if row.dimension == PATCH_METRIC_DIMENSIONS["complexity"]
        ),
        key=lambda row: (key(row.symbol), row.start_line),
    )
    return tuple(
        (
            key(row.symbol),
            _unit_span(row.start_line, ends.get((row.symbol, row.start_line))),
            row.numerator,
        )
        for row in rows
    )


def _unit_span(start_line: int, end_line: int | None) -> tuple[int, int] | None:
    return None if end_line is None else (start_line, end_line)


def _patch_findings(
    model: CanonicalModel,
) -> dict[str, tuple[Mapping[str, object], ...]]:
    """The projected groups of every tracked family, under the document's
    family key, each with the severity the run's evaluation stated."""
    groups = projected_finding_groups(model)
    severities = {
        row.finding_id: row.severity
        for row in model.facts.evaluation.finding_evaluation
    }
    return {
        (FAMILY_CLONES if family == FAMILY_CLONE else family): tuple(
            {**group, "severity": severities.get(str(group["id"]), "")}
            for group in groups[family]
        )
        for family in PROJECTED_FAMILIES
    }


def _adoption_permille(model: CanonicalModel, feature: str) -> int:
    rows = [
        row for row in model.facts.analysis.adoption_counts if row.feature == feature
    ]
    return permille(
        sum(row.numerator for row in rows), sum(row.denominator for row in rows)
    )


def _patch_gate_state(model: CanonicalModel) -> GateState:
    """The gate's input record off the stored rows -- every term the
    document reader (``report.gates.evaluator``) takes off a document, the
    clone counts the surface hands it, and the comparison inputs as the
    stored run's normalized comparison state (``stored_comparison_state``:
    ``None`` for a delta the run did not compare) -- so the one evaluator
    can answer under the budget's request."""
    facts = model.facts.analysis
    health = model.facts.evaluation.health_result
    maxima = design_maxima(facts)
    dead = dead_code(model)
    coverage = coverage_join(model)
    new_clones = new_clone_groups(model.facts.comparison)
    population = _DEFAULT_POPULATION if health is None else health.population
    state = GateState(
        health_population=cast(
            "ObservedPopulation",
            population
            if population in get_args(ObservedPopulation)
            else _DEFAULT_POPULATION,
        ),
        clone_new_count=0 if new_clones is None else new_clones,
        clone_total=sum(
            1 for row in facts.clone_groups if row.clone_kind in PATCH_CLONE_KINDS
        ),
        complexity_max=maxima["complexity_max"],
        coupling_max=maxima["coupling_max"],
        cohesion_max=maxima["cohesion_max"],
        dependency_cycles=len(facts.dependency_cycles),
        import_dependency_cycles=sum(
            1 for row in facts.dependency_cycles if row.kind == _IMPORT_CYCLE
        ),
        dead_high_confidence=int(cast("int", dead.get("high_confidence", 0))),
        dead_unreachable_statements=len(facts.unreachable_statement_groups),
        unresolved_external_override=int(
            cast("int", dead.get("unresolved_external_override", 0))
        ),
        health_score=0 if health is None or health.score is None else health.score,
        typing_param_permille=_adoption_permille(model, "typing.parameters"),
        docstring_permille=_adoption_permille(model, "docstrings.public_symbols"),
        coverage_join_status=str(coverage.get("status", "")),
        coverage_hotspots=int(cast("int", coverage.get("coverage_hotspots", 0))),
        authority_violations=authority_counts(facts)["violations"],
    )
    return with_comparison_inputs(state, stored_comparison_state(model).value)


def patch_run_from_model(model: CanonicalModel, *, run_id: str) -> ServedPatchRun:
    """Arrange one stored run's facts into what the patch contract reads;
    the finding groups are projected once for the whole arrangement."""
    with projected_once():
        return _patch_run(model, run_id=run_id)


def _patch_run(model: CanonicalModel, *, run_id: str) -> ServedPatchRun:
    heads = _Heads(
        {relation.file.path: relation.module.module for relation in model.file_modules}
    )
    items = _patch_metric_items(model, heads)
    findings = _patch_findings(model)
    dead = dead_code(model)
    coverage = model.facts.analysis.coverage_join
    lane_trust = {row.lane: row.status for row in model.facts.comparison.lane_trust}
    return ServedPatchRun(
        run_id=run_id,
        analysis_mode=analysis_mode(model),
        health_score=health_score(model),
        metric_items=items,
        dependency_cycles=len(model.facts.analysis.dependency_cycles),
        clone_groups=sum(
            1
            for row in model.facts.analysis.clone_groups
            if row.clone_kind in PATCH_CLONE_KINDS
        ),
        dead_code_high_confidence=int(cast("int", dead.get("high_confidence", 0))),
        baseline_status=str(baseline_state(model.facts.comparison).get("status", "")),
        findings=findings,
        gate_state=_patch_gate_state(model),
        lane_trust=dict(sorted(lane_trust.items())),
        # One trust row per enabled lane, by construction
        # (``report.document.builder._baseline_projection``).
        enabled_lanes=tuple(sorted(lane_trust)),
        coverage_join_status=None if coverage is None else coverage.status,
        coverage_invalid_reason=None if coverage is None else coverage.invalid_reason,
    )


#: The families :func:`read_served_patch_run` reads on every run -- every
#: one, and none it could do without -- and the condition under which it
#: reads the authority graph (``tests/test_patch_contract_declared_families
#: .py``, per branch).  Measured 2026-10-03 on the sixteen served
#: populations and the 25 runs of the patch-contract battery: 33 of the
#: store's 56 families; the graph moved behind its condition 2026-10-05.
#: The risk observations stay unconditional: the per-symbol complexity
#: index and the complexity maximum are read off them on every run.  The
#: disabled capabilities joined the unconditional families (2026-10-05)
#: when the gate's comparison inputs moved onto the stored comparison
#: state, which names a reason off them.  The unit spans joined them
#: (2026-10-20): a complexity element carries its declaration's end line,
#: which the positional narrowing of an ambiguous key compares.
PATCH_CONTRACT_FAMILIES: Final = (
    FAMILY_ADOPTION_COUNT,
    FAMILY_ADOPTION_DELTA,
    FAMILY_ANALYSIS_POPULATION,
    FAMILY_API_SURFACE_DELTA,
    FAMILY_BASELINE_WITNESS,
    FAMILY_CLONE_GROUP,
    FAMILY_CLONE_NOVELTY,
    FAMILY_COHESION_HOTSPOT,
    FAMILY_COMPARISON_AVAILABILITY,
    FAMILY_COMPLEXITY_HOTSPOT,
    FAMILY_COMPLEXITY_NOVELTY,
    FAMILY_COUPLING_COHESION,
    FAMILY_COUPLING_HOTSPOT,
    FAMILY_COUPLING_NOVELTY,
    FAMILY_COVERAGE_JOIN,
    FAMILY_COVERAGE_UNIT,
    FAMILY_DEAD_CODE_SUMMARY,
    FAMILY_DEAD_SYMBOL_GROUP,
    FAMILY_DEAD_SYMBOL_NOVELTY,
    FAMILY_DEPENDENCY_CYCLE,
    FAMILY_DEPENDENCY_CYCLE_NOVELTY,
    FAMILY_DISABLED_CAPABILITY,
    FAMILY_FILE_MODULE,
    FAMILY_FINDING_EVALUATION,
    FAMILY_HEALTH_DELTA,
    FAMILY_HEALTH_RESULT,
    FAMILY_LANE_TRUST,
    FAMILY_RISK_OBSERVATION,
    FAMILY_STRUCTURAL_GROUP,
    FAMILY_SUPPRESSED_CLONE_GROUP,
    FAMILY_UNIT_SPAN,
    FAMILY_UNREACHABLE_STATEMENT_GROUP,
    FAMILY_VIOLATION,
)
#: The patch contract's read condition.
PATCH_CONTRACT_READ_WHEN: Final = (AUTHORITY_GRAPH_WHEN_VIOLATIONS,)


def read_served_patch_run(store: RunStore, run_id: str) -> ServedPatchRun:
    """Read the declared families of one published run and arrange what
    the patch contract reads of it.  Bounded, as every reading here is:
    :data:`PATCH_CONTRACT_FAMILIES`, and the authority graph when the run
    holds a violation row (:data:`PATCH_CONTRACT_READ_WHEN`)."""
    model = read_named_families(
        store, run_id, PATCH_CONTRACT_FAMILIES, read_when=PATCH_CONTRACT_READ_WHEN
    )
    return patch_run_from_model(model, run_id=run_id)


#: The families :func:`read_served_blast_radius_facts` reads on every run --
#: every one, and none it could do without -- and the condition under which
#: it reads the risk observations (``tests/test_blast_radius_declared_families
#: .py``, per branch).  Measured 2026-10-03 the way the run summary's were
#: (every family, then each one taken away): 26 of the store's 56 on the
#: nineteen served populations of consumer migration C7, flask and the
#: self-repository.  Since 2026-10-05 the one owner of the known-debt paths
#: walks only the families a novelty row can name
#: (``comparison_projection.NOVELTY_BEARING_FAMILIES``), so the authority
#: families (``graph_node``, ``semantic_edge``, ``violation``) and the
#: structural groups are no longer read at all, and ``risk_observation`` is
#: read when the run joined a coverage report.
BLAST_RADIUS_FAMILIES: Final = (
    FAMILY_CLONE_GROUP,
    FAMILY_CLONE_NOVELTY,
    FAMILY_COHESION_HOTSPOT,
    FAMILY_COMPLEXITY_HOTSPOT,
    FAMILY_COMPLEXITY_NOVELTY,
    FAMILY_COUPLING_HOTSPOT,
    FAMILY_COUPLING_NOVELTY,
    FAMILY_COVERAGE_JOIN,
    FAMILY_COVERAGE_UNIT,
    FAMILY_DEAD_SYMBOL_GROUP,
    FAMILY_DEAD_SYMBOL_NOVELTY,
    FAMILY_DEPENDENCY_CYCLE,
    FAMILY_DEPENDENCY_CYCLE_NOVELTY,
    FAMILY_DEPENDENCY_RELATION,
    FAMILY_FILE_MODULE,
    FAMILY_IMPORT_OBSERVATION,
    FAMILY_OVERLOADED_MODULE,
    FAMILY_SECURITY_SURFACE,
    FAMILY_SUPPRESSED_CLONE_GROUP,
    FAMILY_UNIT_RISK_RESULT,
    FAMILY_UNREACHABLE_STATEMENT_GROUP,
)
#: The blast radius's read condition.
BLAST_RADIUS_READ_WHEN: Final = (RISK_WHEN_COVERAGE_JOIN,)


def read_served_blast_radius_facts(store: RunStore, run_id: str) -> BlastRadiusFacts:
    """Read the declared families of one published run and rebuild the facts
    its blast radius is computed from (consumer migration C7).

    Bounded: :data:`BLAST_RADIUS_FAMILIES`, and the risk observations when
    the run holds a coverage join (:data:`BLAST_RADIUS_READ_WHEN`), through
    :func:`~codeclone.canonical.store.read_named_families`; the facts are
    rebuilt by their one owner,
    :func:`~codeclone.canonical.blast_radius_projection.blast_radius_facts_from_model`.
    A run the store does not hold refuses typed (``UnknownRunError``), and a
    projection reaching past the declaration refuses (``UnreadFamilyError``).
    """
    model = read_named_families(
        store, run_id, BLAST_RADIUS_FAMILIES, read_when=BLAST_RADIUS_READ_WHEN
    )
    return blast_radius_facts_from_model(model)


__all__ = [
    "AUTHORITY_GRAPH_WHEN_VIOLATIONS",
    "AUTHORITY_PRODUCER_FAMILY",
    "BLAST_RADIUS_FAMILIES",
    "BLAST_RADIUS_READ_WHEN",
    "RISK_WHEN_COVERAGE_JOIN",
    "RUN_SUMMARY_FAMILIES",
    "RUN_SUMMARY_READ_WHEN",
    "SECURITY_SURFACE_COUNT_KEYS",
    "SERVED_AUTHORITY_CANDIDATE_FAMILIES",
    "SERVED_SLICE_FAMILIES",
    "ServedAuthorityCandidates",
    "ServedRunSlices",
    "ServedRunSummary",
    "ServedUnitLocation",
    "module_dep_order_key",
    "read_served_authority_candidates",
    "read_served_blast_radius_facts",
    "read_served_run_slices",
    "read_served_run_summary",
    "relationship_record_order_key",
    "run_summary_from_model",
]
__all__ += [
    "PATCH_CLONE_KINDS",
    "PATCH_CONTRACT_FAMILIES",
    "PATCH_CONTRACT_READ_WHEN",
    "PATCH_METRIC_DIMENSIONS",
    "PatchMetricElement",
    "ServedPatchRun",
    "patch_run_from_model",
    "read_served_patch_run",
]


# -- the production triage (consumer migration C2) ---------------------------
#
# ``get_production_triage`` states, beside the blocks it shares with the run
# summary (baseline, health, analysis profile, coverage join, security
# surfaces -- read here as the summary's own arrangement), the run's finding
# universe broken down by source kind, the document's production-hotspot
# selection and its suggestion selection.  The cards and the short ids the
# surface shows them under are its own presentation (``_session_finding_
# mixin``), so this reading hands it the analysis skeleton of every published
# finding, and each selected one the way the surface reads a finding -- the
# skeleton with its verdict and novelty word beside it -- and never a card.
#
# A suggestion the store states twice, and never as a row of its own: its
# source kind is the dominant kind of its finding's sites, and its effort is
# its finding's price read backwards (``evaluation_rows.finding_effort``).
# Its TEXT -- title, summary, steps -- no store row carries (the evaluation
# tier leaves remediation out by design), so it stays the memory's, and a run
# held without its payload is not answered from here.


#: The selection whose order is the document's ``derived.suggestions``.
TRIAGE_SUGGESTIONS: Final = "suggestions"


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedTriageSuggestion:
    """One suggestion of the run's selection, as the triage states it: the
    finding it names (canonical id), that finding's dominant source kind and
    the effort the finding was priced under."""

    finding_id: str
    source_kind: str
    effort: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedTriage:
    """The store-carried facts of one run's ``get_production_triage``.

    ``summary`` is the run summary's arrangement, read for the blocks the two
    answers share; ``findings`` and ``suggestions`` are the triage's two
    count blocks in the surface's key order.  ``universe`` is every published
    finding's analysis skeleton (the short ids and the spread every card is
    weighed against are taken over all of them); ``hotspots`` is the
    production-hotspot selection, ranked, each finding as the surface reads
    one -- the skeleton, the verdict's ``severity`` / ``confidence`` /
    ``priority`` / ``clone_type`` and the ``novelty`` word;
    ``production_suggestions`` is the suggestion selection's production
    part, ranked; ``efforts`` states the effort of every suggested finding
    and of nothing else -- a finding without a suggestion has none.

    No limit is applied here: the facts are a function of the run alone,
    kept by the door across questions, and the caller's limit cuts them.
    """

    run_id: str
    summary: ServedRunSummary
    findings: Mapping[str, object]
    suggestions: Mapping[str, object]
    universe: tuple[Mapping[str, object], ...]
    hotspots: tuple[Mapping[str, object], ...]
    production_suggestions: tuple[ServedTriageSuggestion, ...]
    efforts: Mapping[str, str]


def _selected(
    by_id: Mapping[str, Mapping[str, object]],
    verdicts: Mapping[str, FindingEvaluationRow],
    finding_id: str,
    selection_name: str,
) -> tuple[Mapping[str, object], FindingEvaluationRow]:
    """One finding a selection names, with the verdict on it -- or the
    refusal: a selection naming a finding the run publishes no group or no
    verdict for cannot be shown, and is never shown short of it."""
    group = by_id.get(finding_id)
    verdict = verdicts.get(finding_id)
    if group is None or verdict is None:
        raise CanonicalModelError(
            f"the {selection_name} selection names {finding_id!r}, a finding "
            "the run publishes no evaluated group for"
        )
    return group, verdict


def _shown_finding(
    group: Mapping[str, object], verdict: FindingEvaluationRow, novelty: str
) -> dict[str, object]:
    """One selected finding as the surface reads one: the skeleton, the
    run's verdict on it and its novelty word."""
    finding = {
        **group,
        "severity": verdict.severity,
        "confidence": verdict.confidence,
        "priority": verdict.priority,
    }
    if verdict.clone_type is not None:
        finding["clone_type"] = verdict.clone_type
    finding["novelty"] = novelty
    return finding


def _triage_suggestion(
    by_id: Mapping[str, Mapping[str, object]],
    verdicts: Mapping[str, FindingEvaluationRow],
    finding_id: str,
) -> ServedTriageSuggestion:
    finding, verdict = _selected(by_id, verdicts, finding_id, TRIAGE_SUGGESTIONS)
    return ServedTriageSuggestion(
        finding_id=finding_id,
        source_kind=dominant_source_kind(finding),
        effort=finding_effort(verdict.severity, verdict.priority),
    )


def _triage_findings_block(
    counts: Mapping[str, object], summary: ServedRunSummary
) -> dict[str, object]:
    """``findings``: the universe's total and source-kind breakdown, the new
    findings by source kind (the summary's), and the findings outside the
    production focus."""
    by_source_kind = cast("Mapping[str, int]", counts["by_source_kind"])
    total = cast("int", counts["total"])
    return {
        "total": total,
        "by_source_kind": dict(by_source_kind),
        "new_by_source_kind": summary.findings["new_by_source_kind"],
        "outside_focus": total - by_source_kind[SOURCE_KIND_PRODUCTION],
    }


def _triage_suggestions_block(
    total: int, suggested: tuple[ServedTriageSuggestion, ...]
) -> dict[str, object]:
    """``suggestions``: how many the run selected, by source kind, and how
    many fall outside the production focus."""
    by_source_kind = source_kind_breakdown(item.source_kind for item in suggested)
    return {
        "total": total,
        "by_source_kind": by_source_kind,
        "outside_focus": total - by_source_kind[SOURCE_KIND_PRODUCTION],
    }


def triage_from_model(model: CanonicalModel, *, run_id: str) -> ServedTriage:
    """Arrange one stored run's facts into what the production triage states;
    the finding groups are projected once for the whole arrangement."""
    with projected_once():
        return _triage(model, run_id=run_id)


def _triage(model: CanonicalModel, *, run_id: str) -> ServedTriage:
    groups = projected_finding_groups(model)
    evaluation = model.facts.evaluation
    verdicts = {row.finding_id: row for row in evaluation.finding_evaluation}
    universe = tuple(
        dict(group) for family in PROJECTED_FAMILIES for group in groups[family]
    )
    by_id = {str(group["id"]): group for group in universe}
    novelty = group_novelty(model)
    hotspots = tuple(
        _shown_finding(
            *_selected(by_id, verdicts, finding_id, PRODUCTION_HOTSPOT),
            novelty[finding_id],
        )
        for finding_id in selection(evaluation, PRODUCTION_HOTSPOT)
    )
    suggested = tuple(
        _triage_suggestion(by_id, verdicts, finding_id)
        for finding_id in selection(evaluation, TRIAGE_SUGGESTIONS)
    )
    summary = _run_summary(model, run_id=run_id)
    return ServedTriage(
        run_id=run_id,
        summary=summary,
        findings=_triage_findings_block(finding_counts(model), summary),
        suggestions=_triage_suggestions_block(suggestion_total(evaluation), suggested),
        universe=universe,
        hotspots=hotspots,
        production_suggestions=tuple(
            item for item in suggested if item.source_kind == SOURCE_KIND_PRODUCTION
        ),
        efforts={item.finding_id: item.effort for item in suggested},
    )


#: The families :func:`read_served_triage` reads on every run -- the run
#: summary's (:data:`RUN_SUMMARY_FAMILIES`), whose arrangement the triage
#: reads for the blocks the two share, and the two evaluation families its
#: verdicts and selections are rows of (``finding_evaluation``,
#: ``hotlist_selection``) -- and the summary's conditions
#: (``tests/test_production_triage_declared_families.py`` holds the
#: composition and each family, per branch).  Measured 2026-10-06 on the
#: twenty served populations: this read equals the whole read on every one.
TRIAGE_FAMILIES: Final = (
    FAMILY_ADOPTION_DELTA,
    FAMILY_ANALYSIS_POPULATION,
    FAMILY_API_SURFACE_DELTA,
    FAMILY_BASELINE_WITNESS,
    FAMILY_CLONE_GROUP,
    FAMILY_CLONE_NOVELTY,
    FAMILY_COHESION_HOTSPOT,
    FAMILY_COMPARISON_AVAILABILITY,
    FAMILY_COMPLEXITY_HOTSPOT,
    FAMILY_COMPLEXITY_NOVELTY,
    FAMILY_COUPLING_HOTSPOT,
    FAMILY_COUPLING_NOVELTY,
    FAMILY_COVERAGE_JOIN,
    FAMILY_COVERAGE_UNIT,
    FAMILY_DEAD_CODE_SUMMARY,
    FAMILY_DEAD_SYMBOL_GROUP,
    FAMILY_DEAD_SYMBOL_NOVELTY,
    FAMILY_DEPENDENCY_CYCLE,
    FAMILY_DEPENDENCY_CYCLE_NOVELTY,
    FAMILY_DISABLED_CAPABILITY,
    FAMILY_FILE_MODULE,
    FAMILY_FINDING_EVALUATION,
    FAMILY_HEALTH_DELTA,
    FAMILY_HEALTH_RESULT,
    FAMILY_HOTLIST_SELECTION,
    FAMILY_LANE_TRUST,
    FAMILY_METRICS_BASELINE_WITNESS,
    FAMILY_RUN_SCALAR,
    FAMILY_SECURITY_SURFACE,
    FAMILY_STRUCTURAL_GROUP,
    FAMILY_SUPPRESSED_CLONE_GROUP,
    FAMILY_UNREACHABLE_STATEMENT_GROUP,
    FAMILY_VIOLATION,
)
#: The production triage's read conditions: the run summary's.
TRIAGE_READ_WHEN: Final = RUN_SUMMARY_READ_WHEN


def read_served_triage(store: RunStore, run_id: str) -> ServedTriage:
    """Read the declared families of one published run and arrange what
    the production triage states of it (consumer migration C2).  Bounded,
    as every reading here is: :data:`TRIAGE_FAMILIES`, and the families of
    each of :data:`TRIAGE_READ_WHEN` whose condition the run meets."""
    model = read_named_families(
        store, run_id, TRIAGE_FAMILIES, read_when=TRIAGE_READ_WHEN
    )
    return triage_from_model(model, run_id=run_id)


__all__ += [
    "TRIAGE_FAMILIES",
    "TRIAGE_READ_WHEN",
    "TRIAGE_SUGGESTIONS",
    "ServedTriage",
    "ServedTriageSuggestion",
    "read_served_triage",
    "triage_from_model",
]

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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast, get_args

from codeclone.canonical.authority_projection import candidate_rows_from_families
from codeclone.canonical.blast_radius_facts import BlastRadiusFacts
from codeclone.canonical.blast_radius_projection import blast_radius_facts_from_model
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
    FindingNoveltyRow,
)
from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.evaluation_projection import (
    CLONES_ONLY_MODE,
    diff_health_delta,
    health_payload,
    health_score,
)
from codeclone.canonical.finding_projection import (
    PROJECTED_FAMILIES,
    projected_finding_groups,
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
    FAMILY_FILE_MODULE,
    FAMILY_FINDING_EVALUATION,
    FAMILY_GRAPH_NODE,
    FAMILY_HEALTH_DELTA,
    FAMILY_HEALTH_RESULT,
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
    finding_counts,
    inventory,
    security_surfaces,
)
from codeclone.contracts import FAMILY_CLONES, ObservedPopulation
from codeclone.contracts.report_identity import PRODUCER_STATE_COMPLETE
from codeclone.domain.findings import FAMILY_CLONE
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
from codeclone.report.gates.evaluator import GateState


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


#: The families the run summary's projections read -- every one, and none
#: they could do without (``tests/test_run_summary_declared_families.py``).
#: Measured 2026-10-03 on the sixteen served populations, flask and the
#: self-repository: 32 of the store's 56 families.
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
    FAMILY_FILE_MODULE,
    FAMILY_GRAPH_NODE,
    FAMILY_HEALTH_DELTA,
    FAMILY_HEALTH_RESULT,
    FAMILY_METRICS_BASELINE_WITNESS,
    FAMILY_RISK_OBSERVATION,
    FAMILY_RUN_SCALAR,
    FAMILY_SECURITY_SURFACE,
    FAMILY_SEMANTIC_EDGE,
    FAMILY_STRUCTURAL_GROUP,
    FAMILY_SUPPRESSED_CLONE_GROUP,
    FAMILY_UNREACHABLE_STATEMENT_GROUP,
    FAMILY_VIOLATION,
)


def read_served_run_summary(store: RunStore, run_id: str) -> ServedRunSummary:
    """Read the declared families of one published run and arrange its
    summary blocks.

    Bounded: :data:`RUN_SUMMARY_FAMILIES` only, each row proven against its
    content address; a projection that reached past the declaration would
    refuse typed (``UnreadFamilyError``, a stored answer the projection
    cannot express), never read an empty family.  A run the store does not
    hold refuses typed (``UnknownRunError``), as every reading here does.
    """
    model = read_named_families(store, run_id, RUN_SUMMARY_FAMILIES)
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedPatchRun:
    """The facts one run lends the patch contract, read out of the store.

    ``metric_items`` maps each of :data:`PATCH_METRIC_DIMENSIONS` to the
    run's ``(path, glued qualname) -> value`` index; ``findings`` maps each
    tracked family (the document's key) to its groups, each carrying the
    severity the run's evaluation stated; ``gate_state`` with ``lane_trust``
    and ``enabled_lanes`` is everything the one gate evaluator needs to
    answer under any request.  ``coverage_join_status`` is ``None`` for a
    run that was handed no coverage report.
    """

    run_id: str
    analysis_mode: str
    health_score: int | None
    metric_items: Mapping[str, Mapping[tuple[str, str], int]]
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
) -> dict[str, dict[tuple[str, str], int]]:
    """Each metric family's per-symbol index, in the document's spelling.

    The class lane drops a zero row, so a dimension a MEASURED class (one
    the lane holds any row for) does not carry is its measured zero -- the
    rule ``summary_projection.design_maxima`` states for the maxima, applied
    per symbol so a coupling that rises from zero is a rise from zero.
    """
    facts = model.facts.analysis

    def key(symbol: SymbolId) -> tuple[str, str]:
        return symbol.file.path, heads.glued(symbol)

    complexity = {
        key(row.symbol): row.numerator
        for row in facts.risk_observations
        if row.dimension == PATCH_METRIC_DIMENSIONS["complexity"]
    }
    measured = {key(row.symbol) for row in facts.coupling_cohesion_observations}
    items: dict[str, dict[tuple[str, str], int]] = {"complexity": complexity}
    for family in ("coupling", "cohesion"):
        values = {
            key(row.symbol): row.numerator
            for row in facts.coupling_cohesion_observations
            if row.dimension == PATCH_METRIC_DIMENSIONS[family]
        }
        items[family] = {symbol: values.get(symbol, 0) for symbol in measured}
    return items


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


def _new_ids(rows: Iterable[FindingNoveltyRow]) -> set[str]:
    return {row.finding_id for row in rows if row.novelty == NOVELTY_NEW}


def _adoption_permille(model: CanonicalModel, feature: str) -> int:
    rows = [
        row for row in model.facts.analysis.adoption_counts if row.feature == feature
    ]
    return permille(
        sum(row.numerator for row in rows), sum(row.denominator for row in rows)
    )


def _patch_gate_state(
    model: CanonicalModel, findings: Mapping[str, tuple[Mapping[str, object], ...]]
) -> GateState:
    """The gate's input record off the stored rows -- every term the
    document reader (``report.gates.evaluator``) takes off a document, the
    clone counts the surface hands it, the diff terms its metrics diff
    carries -- so the one evaluator can answer under the budget's request."""
    facts = model.facts.analysis
    comparison = model.facts.comparison
    health = model.facts.evaluation.health_result
    maxima = design_maxima(facts)
    dead = dead_code(model)
    coverage = coverage_join(model)
    deltas = metric_deltas(comparison)
    new_clones = new_clone_groups(comparison)
    new_cycles = _new_ids(comparison.dependency_cycle_novelty)
    cycle_kinds = {
        str(group["id"]): group["kind"]
        for group in findings["design"]
        if group.get("category") == "dependency"
    }
    population = _DEFAULT_POPULATION if health is None else health.population
    return GateState(
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
        api_breaking_changes=deltas["api_breaking_changes"],
        authority_violations=authority_counts(facts)["violations"],
        diff_new_high_risk_functions=len(_new_ids(comparison.complexity_novelty)),
        diff_new_high_coupling_classes=len(_new_ids(comparison.coupling_novelty)),
        diff_new_cycles=len(new_cycles),
        diff_new_import_cycles=sum(
            1
            for finding_id in new_cycles
            if cycle_kinds.get(finding_id) == _IMPORT_CYCLE
        ),
        diff_new_dead_code=len(_new_ids(comparison.dead_symbol_novelty)),
        diff_health_delta=diff_health_delta(model) or 0,
        diff_typing_param_permille_delta=deltas["typing_param_permille_delta"],
        diff_typing_return_permille_delta=deltas["typing_return_permille_delta"],
        diff_docstring_permille_delta=deltas["docstring_permille_delta"],
    )


def patch_run_from_model(model: CanonicalModel, *, run_id: str) -> ServedPatchRun:
    """Arrange one stored run's facts into what the patch contract reads."""
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
        gate_state=_patch_gate_state(model, findings),
        lane_trust=dict(sorted(lane_trust.items())),
        # One trust row per enabled lane, by construction
        # (``report.document.builder._baseline_projection``).
        enabled_lanes=tuple(sorted(lane_trust)),
        coverage_join_status=None if coverage is None else coverage.status,
        coverage_invalid_reason=None if coverage is None else coverage.invalid_reason,
    )


#: The families :func:`read_served_patch_run` reads -- every one, and none
#: it could do without (``tests/test_patch_contract_declared_families.py``).
#: Measured 2026-10-03 on the sixteen served populations and the 25 runs of
#: the patch-contract battery: 33 of the store's 56 families.
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
    FAMILY_FILE_MODULE,
    FAMILY_FINDING_EVALUATION,
    FAMILY_GRAPH_NODE,
    FAMILY_HEALTH_DELTA,
    FAMILY_HEALTH_RESULT,
    FAMILY_LANE_TRUST,
    FAMILY_RISK_OBSERVATION,
    FAMILY_SEMANTIC_EDGE,
    FAMILY_STRUCTURAL_GROUP,
    FAMILY_SUPPRESSED_CLONE_GROUP,
    FAMILY_UNREACHABLE_STATEMENT_GROUP,
    FAMILY_VIOLATION,
)


def read_served_patch_run(store: RunStore, run_id: str) -> ServedPatchRun:
    """Read the declared families of one published run and arrange what
    the patch contract reads of it.  Bounded, as every reading here is:
    :data:`PATCH_CONTRACT_FAMILIES` only."""
    model = read_named_families(store, run_id, PATCH_CONTRACT_FAMILIES)
    return patch_run_from_model(model, run_id=run_id)


#: The families :func:`read_served_blast_radius_facts` reads -- every one,
#: and none it could do without (``tests/test_blast_radius_declared_families
#: .py``).  Measured 2026-10-03 the way the run summary's were (every family,
#: then each one taken away): 26 of the store's 56 on the nineteen served
#: populations of consumer migration C7, flask and the self-repository.  The
#: authority families (``graph_node``, ``semantic_edge``, ``violation``) are
#: read because the one owner of the known-debt paths walks the whole
#: published finding universe; ``risk_observation`` is reached only by a run
#: that joined a coverage report.
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
    FAMILY_GRAPH_NODE,
    FAMILY_IMPORT_OBSERVATION,
    FAMILY_OVERLOADED_MODULE,
    FAMILY_RISK_OBSERVATION,
    FAMILY_SECURITY_SURFACE,
    FAMILY_SEMANTIC_EDGE,
    FAMILY_STRUCTURAL_GROUP,
    FAMILY_SUPPRESSED_CLONE_GROUP,
    FAMILY_UNIT_RISK_RESULT,
    FAMILY_UNREACHABLE_STATEMENT_GROUP,
    FAMILY_VIOLATION,
)


def read_served_blast_radius_facts(store: RunStore, run_id: str) -> BlastRadiusFacts:
    """Read the declared families of one published run and rebuild the facts
    its blast radius is computed from (consumer migration C7).

    Bounded: :data:`BLAST_RADIUS_FAMILIES` only, through
    :func:`~codeclone.canonical.store.read_named_families`; the facts are
    rebuilt by their one owner,
    :func:`~codeclone.canonical.blast_radius_projection.blast_radius_facts_from_model`.
    A run the store does not hold refuses typed (``UnknownRunError``), and a
    projection reaching past the declaration refuses (``UnreadFamilyError``).
    """
    model = read_named_families(store, run_id, BLAST_RADIUS_FAMILIES)
    return blast_radius_facts_from_model(model)


__all__ = [
    "AUTHORITY_PRODUCER_FAMILY",
    "BLAST_RADIUS_FAMILIES",
    "RUN_SUMMARY_FAMILIES",
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
    "PATCH_METRIC_DIMENSIONS",
    "ServedPatchRun",
    "patch_run_from_model",
    "read_served_patch_run",
]

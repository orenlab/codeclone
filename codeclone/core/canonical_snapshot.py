# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Producer-native canonical snapshot: the SECOND entrance to one model.

``canonical.ingest.canonical_model_from_legacy_document`` stays the TEST
ORACLE (ruling 2026-08-24 §6) — it reads a rendered report back and is not
a production path.  This module is the production path the ratified chain
names: ``producers -> normalized run snapshot -> RunStore``, built from
the live ``(discovery, processing, analysis)`` results with none of the
oracle's coercion of an already-serialized document.

**Placement, decided by the frozen edges and not by convenience.**  The
``codeclone.canonical`` package (r2) reaches outward only into
``contracts`` (r0), ``observability`` (r1) and ``utils.sqlite_store`` (r1);
a builder placed inside it would introduce ``canonical -> models/core`` and
close a cycle.  ``codeclone.core`` already imports
``canonical.authority_identity`` and already owns ``AnalysisResult``, so
the graph puts the builder here and the dependency stays one-way.

**Why this is not a fake-zero machine.**  A canonical row family carries no
"absent" marker — only ``run_scalars`` and ``analysis_population`` are
``| None`` — so a builder that silently omitted an executed family would
publish exactly the fifteen honest-looking zeros the hard law forbids.
This module therefore either expresses every family the run produced, or
REFUSES to build, typed and loudly.  The one family group it cannot
express today is the semantic-authority tier: its producer rows carry the
same glued identity strings the document does, and their canonical grammar
(root families, operation heads) exists only as private helpers of the
legacy oracle.  Re-spelling that grammar here would be a second
implementation of one identity law, so a run with the semantic lane ON is
refused rather than approximated.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple

# Reached through the OWNING submodules, never through the package door:
# ``codeclone.canonical.__init__`` re-exports the store AND the legacy
# ingest oracle, and importing the oracle from a production path would
# make the test oracle a production dependency (ruling 2026-08-24 §6).
from ..canonical.identity import FileId, ModuleId
from ..canonical.model import (
    AdoptionCountRow,
    AnalysisFacts,
    AnalysisPopulation,
    ApiParameterFact,
    ApiSymbolRow,
    CandidateRow,
    CanonicalFacts,
    CanonicalModel,
    CloneGroupRow,
    CloneItemRow,
    ContractRow,
    CouplingCohesionRow,
    DeadCodeObservationRow,
    DependencyCycleRow,
    DependencyOccurrenceRow,
    DependencyRelationRow,
    FileModuleRelation,
    GraphNodeRow,
    RiskObservationRow,
    RunScalars,
    SecuritySurfaceRow,
    SemanticEdge,
    SinkRoleRow,
    ViolationRow,
)
from ..canonical.semantic_grammar import (
    IdentityIndex,
    build_identity_index,
    parse_dead_code_entity,
    parse_endpoint,
    parse_lane_symbol,
    parse_root_set,
    parse_symbol,
    parse_symbol_set,
    surface_head,
)
from ..contracts import observed_population
from ..metrics.registry import METRIC_FAMILIES
from ..models import (
    CANONICAL_HEAD_TARGET,
    CANONICAL_PROFILE_HEAD_PREFIX,
    RUN_SNAPSHOT_PUBLICATION_DISABLED,
    RUN_SNAPSHOT_PUBLICATION_HEAD_CONFLICT,
    RUN_SNAPSHOT_PUBLICATION_HEAD_WITHHELD,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RUN_SNAPSHOT_PUBLICATION_REFUSED,
    AdoptionCount,
    ApiSymbolObservation,
    DeadCodeObservation,
    IntegerObservation,
    ModuleRegistryHandle,
    ObservationBundle,
    RiskObservation,
    RunSnapshotPublication,
    RunStoreConfig,
    SemanticAuthorityResult,
)
from ..observability import span
from ..paths.workspace import REL_RUN_STORE_DB_PATH
from ..utils.ci import is_ci_environment
from ..utils.coerce import as_int as _as_int
from ..utils.coerce import as_mapping as _as_mapping
from ..utils.coerce import as_sequence as _as_sequence
from ..utils.coerce import as_str as _as_str
from ._types import AnalysisResult, DiscoveryResult, ProcessingResult

#: The run-wide metrics switch as the report meta spells it.  Both
#: surfaces write it from the SAME argument (``args.skip_metrics`` in the
#: CLI, the request mode in MCP, which sets ``args.skip_metrics``), so this
#: one word is the structural witness of the switch.
CLONES_ONLY_MODE = "clones_only"

#: The store namespace of producer-published analysis snapshots.  Spelled
#: once, here, so no surface can partition the object store by accident.
RUN_SNAPSHOT_NAMESPACE = "codeclone.analysis"

#: Report-only producers whose own witness is a tri-state field rather than
#: a metric family: ``None`` means the producer was never invoked, ``()``
#: means it ran and measured nothing.  Named here because a producer whose
#: state cannot be read is a producer the population cannot witness.
NEAR_MISS_FAMILY = "near_miss"
RENAMED_STRUCTURE_FAMILY = "renamed_structure"

#: The producer states that mean "this family did not measure the whole
#: universe it was asked to measure" (ruling 2026-08-31, I2-D: *truncated*).
#: ``disabled`` and ``not_executed`` are deliberately NOT here, and the
#: exclusion is measured rather than assumed: on a live full run
#: ``coverage_join`` is ``not_executed`` on every run without
#: ``--coverage-xml`` and ``near_miss`` is ``disabled`` on every run
#: without its opt-in, so a predicate that treated either as inadmissible
#: would leave the canonical head unreachable by every ordinary run — a
#: guard no input can trip is theater.  The ruling names exactly three
#: inadmissible cases: partial, clones-only and truncated; the clones-only
#: one is carried by ``analysis_mode``, the other two by these states.
_TRUNCATING_STATES = frozenset({"truncated", "unavailable"})


class ProducerSnapshotUnavailable(RuntimeError):
    """The run carries producer output this builder cannot express.

    A typed refusal, never a partial model: a family this build omits
    would reach the store as a measured zero.
    """


# ---------------------------------------------------------------------------
# The rollout flag — resolved in the module that publishes
# ---------------------------------------------------------------------------
#
# Placement, argued rather than assumed.  The brief asked for
# ``codeclone/config/run_store.py`` on the shape of
# ``codeclone/config/observability.py``.  Measured: the frozen architecture
# guard forbids ``codeclone.core -> codeclone.config`` outright
# (``tests/test_architecture.py``), and the observability resolver reaches
# its consumer only through an allowlisted ``r1 -> r2`` exception that this
# wave may not grow.  The brief's actual REQUIREMENT is that the resolve
# point coincide with the write point so the three waterfalls cannot
# physically diverge on one flag — and a resolver in the publishing module
# satisfies that more strictly than a separate module does.  The FORM the
# brief specified is kept verbatim: environment only, default OFF,
# CI-neutral, one frozen disabled singleton.
#
# Environment and not a ``[tool.codeclone]`` key, also argued: ruling
# 2026-08-24 §6 makes T2 a TEMPORARY rollout that DISAPPEARS once GC, the
# identity bridge and direct producer wiring have landed, and a published
# pyproject key cannot be withdrawn without breaking the surface it was
# published on.  The environment path is already measured to reach all
# three waterfalls and carries no configuration-delivery ratchet.

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

#: The rollout switch.  One name, spelled once.
ENV_RUN_STORE_ENABLED = "CODECLONE_RUN_STORE_ENABLED"
#: Lifts the CI gate for a deliberate CI rollout probe; enables nothing.
ENV_RUN_STORE_FORCE = "CODECLONE_RUN_STORE_FORCE"
#: Overrides the repo-local database location.  A relative value resolves
#: against the analysis root, never against the process working directory:
#: the three waterfalls do not share one cwd.
ENV_RUN_STORE_PATH = "CODECLONE_RUN_STORE_PATH"

_DISABLED_RUN_STORE = RunStoreConfig(enabled=False)


def _env_flag(environ: Mapping[str, str], key: str) -> bool:
    return environ.get(key, "").strip().lower() in _TRUE


def resolve_run_store_config(
    *,
    root: Path,
    environ: Mapping[str, str] | None = None,
) -> RunStoreConfig:
    """Resolve the rollout state for one analysis root.

    Returns the frozen disabled config — the T1 default of ruling §6 is
    "no backend", and "no backend" is the ABSENCE of a representation,
    never a second truth about the run.

    CI is neutral for the same reason the observability resolver makes it
    neutral: a backend that starts writing a SQLite file inside every CI
    checkout because a shared profile exported a variable is a surprise,
    not a rollout.  ``FORCE`` lifts only the CI gate and enables nothing
    on its own.
    """

    env = environ if environ is not None else os.environ
    raw = env.get(ENV_RUN_STORE_ENABLED, "").strip().lower()
    if raw in _FALSE or raw not in _TRUE:
        return _DISABLED_RUN_STORE
    if is_ci_environment(env) and not _env_flag(env, ENV_RUN_STORE_FORCE):
        return _DISABLED_RUN_STORE
    override = env.get(ENV_RUN_STORE_PATH, "").strip()
    if override:
        candidate = Path(override).expanduser()
        path = candidate if candidate.is_absolute() else root / candidate
    else:
        path = root / REL_RUN_STORE_DB_PATH
    return RunStoreConfig(enabled=True, path=path)


# ---------------------------------------------------------------------------
# Identity resolution against the run's OWN module registry
# ---------------------------------------------------------------------------


def _identity_index(
    registry: ModuleRegistryHandle, analyzed_paths: frozenset[str]
) -> IdentityIndex:
    """Project a live registry handle into the shared grammar's index.

    Extraction only.  The conflict law over the pairs — a module claiming
    two files, a file claiming two modules — is the grammar owner's, and it
    is the SAME rule the legacy ingest oracle is refused by; that is the
    whole point of the 2026-08-31 transplant.
    """

    return build_identity_index(
        (
            (entry.identity.file.path, entry.identity.python_module.module)
            for _key, entry in registry.entries_by_path.rows
            if entry.identity.python_module is not None
        ),
        analyzed_paths=analyzed_paths,
    )


# ---------------------------------------------------------------------------
# The execution-population authority (RULING-2026-08-31 §3)
# ---------------------------------------------------------------------------


def _skippable_metric_families() -> tuple[str, ...]:
    """Metric families the run-wide metrics switch turns off.

    Read off the metric registry's own ``skippable_flag`` rather than
    restated here: that field is the structural edge from the
    ``skip_metrics`` configuration owner to the production decision, and a
    hand-kept list beside it would be a claim, not an enforcement witness.
    """

    return tuple(
        sorted(
            name
            for name, family in METRIC_FAMILIES.items()
            if family.skippable_flag == "skip_metrics"
        )
    )


def producer_state(*, executed: bool, disabled: bool, population: str) -> str:
    """Name ONE producer family's realized execution state.

    The decision table is total over its three inputs and every outcome is
    reachable:

    ==========  ========  ===================  ===============
    disabled    executed  file population      state
    ==========  ========  ===================  ===============
    yes         any       any                  disabled
    no          no        any                  not_executed
    no          yes       partial              truncated
    no          yes       unmeasured           unavailable
    no          yes       complete_*           complete
    ==========  ========  ===================  ===============

    The hard law is the last three rows read together: a zero count is
    admissible ONLY under ``complete``.  A run that read part of its
    universe says ``truncated`` and a run that read none of a non-empty
    universe says ``unavailable`` — neither ever projects to zero.
    """

    if disabled:
        return "disabled"
    if not executed:
        return "not_executed"
    if population == "partial":
        return "truncated"
    if population == "unmeasured":
        return "unavailable"
    return "complete"


def producer_execution_population(
    *,
    discovery: DiscoveryResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
) -> AnalysisPopulation:
    """Build the run-level population authority from the producers.

    The legacy oracle can only pronounce ``complete`` and
    ``not_executed``, because a rendered document never says WHY a family
    is missing.  The producer edge knows: it has the run-wide metrics
    switch, the per-producer declaration and the realized file population,
    so a clones-only run leaves here as fifteen ``disabled`` families
    rather than fifteen honest-looking zeros.
    """

    mode = _as_str(report_meta.get("analysis_mode")) or "full"
    metrics_disabled = mode == CLONES_ONLY_MODE
    declared = {
        _as_str(name)
        for name in _as_sequence(report_meta.get("metrics_computed"))
        if _as_str(name)
    }
    population = observed_population(
        files_found=discovery.files_found,
        files_analyzed_or_cached=analysis.files_analyzed_or_cached,
    )
    states: dict[str, str] = {}
    for family in _skippable_metric_families():
        states[family] = producer_state(
            executed=family in declared,
            disabled=metrics_disabled,
            population=population,
        )
    for family, produced in (
        (NEAR_MISS_FAMILY, analysis.near_miss_pairs),
        (RENAMED_STRUCTURE_FAMILY, analysis.renamed_structure_groups),
    ):
        states[family] = producer_state(
            executed=produced is not None,
            disabled=produced is None,
            population=population,
        )
    profile_value = _as_mapping(report_meta.get("analysis_profile"))
    profile = tuple(
        (str(name), _as_int(profile_value[name])) for name in sorted(profile_value)
    )
    return AnalysisPopulation(
        analysis_mode=mode,
        analysis_profile=profile,
        producer_states=tuple(sorted(states.items())),
    )


def population_is_admissible(population: AnalysisPopulation) -> bool:
    """Answer whether this realized profile may hold the canonical head.

    Ratified (2026-08-31, I2-D): a partial, clones-only or truncated
    analysis is stored as a snapshot and never replaces a complete
    measurement.  The predicate reads the population record itself rather
    than the switches behind it, so the stored fact and the head decision
    can never disagree.
    """

    if population.analysis_mode == CLONES_ONLY_MODE:
        return False
    return not any(
        state in _TRUNCATING_STATES for _family, state in population.producer_states
    )


def profile_head_target(population: AnalysisPopulation) -> str:
    """The head this realized profile publishes under.

    An admissible profile takes the reserved canonical name; every other
    profile takes its own ``profile:<digest>`` head, so a poorer
    measurement cannot displace a richer one merely by being newer —
    ``generation`` proves publication order and nothing about completeness.
    """

    if population_is_admissible(population):
        return CANONICAL_HEAD_TARGET
    preimage = "\n".join(
        (
            population.analysis_mode,
            *(f"{family}={state}" for family, state in population.producer_states),
        )
    )
    digest = sha256(preimage.encode("utf-8")).hexdigest()[:16]
    return f"{CANONICAL_PROFILE_HEAD_PREFIX}{digest}"


# ---------------------------------------------------------------------------
# Row families, straight off the producers
# ---------------------------------------------------------------------------


def _run_scalars(
    discovery: DiscoveryResult, processing: ProcessingResult
) -> RunScalars:
    return RunScalars(
        classes=processing.analyzed_classes + discovery.cached_classes,
        files_analyzed=processing.files_analyzed,
        files_cached=discovery.cache_hits,
        files_found=discovery.files_found,
        files_skipped=processing.files_skipped,
        functions=processing.analyzed_functions + discovery.cached_functions,
        methods=processing.analyzed_methods + discovery.cached_methods,
        parsed_lines=processing.analyzed_lines + discovery.cached_lines,
        source_io_skipped=len(processing.source_read_failures),
        unsupported_construct_skipped=len(processing.unsupported_construct_skips),
    )


def _coupling_cohesion_rows(
    rows: Sequence[IntegerObservation], index: IdentityIndex
) -> frozenset[CouplingCohesionRow]:
    return frozenset(
        CouplingCohesionRow(
            symbol=parse_lane_symbol(
                index, row.source.file.path, row.qualname, "coupling_cohesion"
            ),
            dimension=row.dimension,
            numerator=row.numerator,
        )
        for row in rows
    )


def _risk_rows(
    rows: Sequence[RiskObservation], index: IdentityIndex
) -> frozenset[RiskObservationRow]:
    return frozenset(
        RiskObservationRow(
            symbol=parse_lane_symbol(index, row.source.file.path, row.qualname, "risk"),
            dimension=row.dimension,
            numerator=row.numerator,
            start_line=row.start_line,
        )
        for row in rows
    )


def _adoption_rows(
    rows: Sequence[AdoptionCount], index: IdentityIndex
) -> frozenset[AdoptionCountRow]:
    return frozenset(
        AdoptionCountRow(
            scope=parse_endpoint(index, row.scope, "adoption_counts.scope"),
            feature=row.feature,
            numerator=row.numerator,
            denominator=row.denominator,
        )
        for row in rows
    )


def _api_symbol_rows(
    rows: Sequence[ApiSymbolObservation], index: IdentityIndex
) -> frozenset[ApiSymbolRow]:
    return frozenset(
        ApiSymbolRow(
            symbol=parse_lane_symbol(
                index, row.owner.file.path, row.symbol, "api_surface"
            ),
            symbol_kind=row.symbol_kind,
            visibility=row.visibility,
            parameters=tuple(
                ApiParameterFact(
                    name=parameter.name,
                    kind=parameter.kind,
                    has_default=parameter.has_default,
                    annotation_digest=(
                        None
                        if parameter.annotation_digest is None
                        else parameter.annotation_digest.value
                    ),
                )
                for parameter in row.parameters
            ),
            returns_digest=(
                None if row.returns_digest is None else row.returns_digest.value
            ),
        )
        for row in rows
    )


def _dead_code_rows(
    rows: Sequence[DeadCodeObservation], index: IdentityIndex
) -> frozenset[DeadCodeObservationRow]:
    return frozenset(
        DeadCodeObservationRow(
            entity=parse_dead_code_entity(index, row.entity),
            observation_kind=row.observation_kind,
            candidate_kind=row.candidate_kind,
            reference_count=row.reference_count,
            reachable=row.reachable,
            runtime_marker_count=row.runtime_marker_count,
            source_markers=row.source_markers,
            live_root_reason=row.live_root_reason,
            abstained=row.abstained,
        )
        for row in rows
    )


def _dependency_rows(
    payload: Mapping[str, object], index: IdentityIndex
) -> tuple[frozenset[DependencyRelationRow], frozenset[DependencyOccurrenceRow]]:
    """The ratified split: every producer row is one OCCURRENCE, and the
    relation is that row's own triple — projected, never guessed.

    The rows come from the dependency producer's OWN payload rather than
    from the import-observation lane, because the two are different
    populations: the graph producer keeps internal, source-bearing edges
    (``metrics/dependencies.py``), and re-deriving that filter here would
    be a second implementation of one selection law.
    """

    occurrences = frozenset(
        DependencyOccurrenceRow(
            relation=DependencyRelationRow(
                source=parse_endpoint(
                    index, _as_str(row.get("source")), "dependencies.source"
                ),
                target=parse_endpoint(
                    index, _as_str(row.get("target")), "dependencies.target"
                ),
                dependency_type=_as_str(row.get("import_type")),
            ),
            line=_as_int(row.get("line")),
            binding=_as_str(row.get("binding")),
            is_lazy=bool(row.get("is_lazy")),
        )
        for row in (
            _as_mapping(item)
            # ``edge_list`` is the producer's own name for this population;
            # the report document renames it to ``items`` on the way out, so
            # the oracle reads one spelling and the producer edge the other.
            for item in _as_sequence(
                _family_payload(payload, "dependencies").get("edge_list")
            )
        )
    )
    return (
        frozenset(occurrence.relation for occurrence in occurrences),
        occurrences,
    )


def _family_payload(payload: Mapping[str, object], family: str) -> Mapping[str, object]:
    return _as_mapping(payload.get(family))


def _dependency_cycle_rows(
    payload: Mapping[str, object], index: IdentityIndex
) -> frozenset[DependencyCycleRow]:
    """F7 from the producer's own ``cycle_details``.

    Every member resolves through the run's registry; a member that is not
    a registry module is a refusal, because a cycle set is a MODULE-domain
    fact and no identity is minted from a bare string.
    """

    rows: list[DependencyCycleRow] = []
    for row in (
        _as_mapping(item)
        for item in _as_sequence(
            _family_payload(payload, "dependencies").get("cycle_details")
        )
    ):
        members = [_as_str(name) for name in _as_sequence(row.get("modules"))]
        if len(members) != len(set(members)):
            raise ProducerSnapshotUnavailable(
                "a dependency cycle repeats a member; refusing to collapse it"
            )
        resolved: list[ModuleId] = []
        for name in members:
            endpoint = parse_endpoint(index, name, "dependency cycle member")
            if not isinstance(endpoint, ModuleId):
                raise ProducerSnapshotUnavailable(
                    f"dependency cycle member {name!r} is not a registry module"
                )
            resolved.append(endpoint)
        rows.append(DependencyCycleRow(_as_str(row.get("kind")), frozenset(resolved)))
    return frozenset(rows)


def _security_surface_rows(
    payload: Mapping[str, object], index: IdentityIndex
) -> frozenset[SecuritySurfaceRow]:
    """F10 from the producer's own security_surfaces rows.

    The row's declared ``module`` must be the registry's own projection of
    its path — a producer at war with the registry is refused, never
    repaired.
    """

    rows: list[SecuritySurfaceRow] = []
    for row in (
        _as_mapping(item)
        for item in _as_sequence(
            _family_payload(payload, "security_surfaces").get("items")
        )
    ):
        path = _as_str(row.get("filepath"))
        head = surface_head(index, path, "security surface")
        declared = _as_str(row.get("module"))
        if declared != head:
            raise ProducerSnapshotUnavailable(
                f"security surface module {declared!r} disagrees with the "
                f"registry projection {head!r} of {path!r}"
            )
        location_scope = _as_str(row.get("location_scope"))
        qualname_text = _as_str(row.get("qualname"))
        qualname: str | None
        if location_scope == "module":
            if qualname_text != head:
                raise ProducerSnapshotUnavailable(
                    f"module-scope surface qualname {qualname_text!r} is not "
                    f"its own head {head!r}"
                )
            qualname = None
        else:
            symbol = parse_symbol(index, qualname_text, "security surface qualname")
            if symbol.file.path != path:
                raise ProducerSnapshotUnavailable(
                    f"security surface qualname {qualname_text!r} disagrees "
                    f"with its own file {path!r}"
                )
            qualname = symbol.qualname
        rows.append(
            SecuritySurfaceRow(
                file=FileId(path),
                start_line=_as_int(row.get("start_line")),
                end_line=_as_int(row.get("end_line")),
                evidence_symbol=_as_str(row.get("evidence_symbol")),
                qualname=qualname,
                location_scope=location_scope,
                category=_as_str(row.get("category")),
                capability=_as_str(row.get("capability")),
                evidence_kind=_as_str(row.get("evidence_kind")),
                classification_mode=_as_str(row.get("classification_mode")),
                source_kind=_as_str(row.get("source_kind")),
            )
        )
    return frozenset(rows)


def _coupled_sets(payload: Mapping[str, object]) -> frozenset[frozenset[str]]:
    """The standalone coupled-class value sets.

    ``classes`` is the coupling producer's own name for this container;
    the report document renames it to ``items`` on the way out — the same
    producer/document spelling split as ``edge_list``/``items``, and the
    reason this builder reads the payload rather than the rendered shape.
    """

    return frozenset(
        labels
        for labels in (
            frozenset(
                _as_str(name)
                for name in _as_sequence(_as_mapping(item).get("coupled_classes"))
            )
            for item in _as_sequence(
                _family_payload(payload, "coupling").get("classes")
            )
        )
        if labels
    )


#: The emitted clone containers and their kinds.  ``suppressed`` is
#: deliberately absent: it is a DIFFERENT population (ruling 2026-08-24
#: §10), and this builder never reads it — the same boundary the oracle
#: keeps from the document side.
_CLONE_LANES: tuple[tuple[str, str], ...] = (
    ("function", "func_groups"),
    ("block", "block_groups_report"),
    ("segment", "segment_groups"),
)


def _clone_group_rows(
    analysis: AnalysisResult, index: IdentityIndex
) -> frozenset[CloneGroupRow]:
    rows: list[CloneGroupRow] = []
    for kind, attribute in _CLONE_LANES:
        groups: Mapping[str, Sequence[Mapping[str, object]]] = getattr(
            analysis, attribute
        )
        for group_key in sorted(groups):
            items = [
                CloneItemRow(
                    symbol=parse_symbol(
                        index, _as_str(item.get("qualname")), f"{kind} clone item"
                    ),
                    start_line=_as_int(item.get("start_line")),
                    end_line=_as_int(item.get("end_line")),
                )
                for item in groups[group_key]
            ]
            unique = frozenset(items)
            if len(unique) != len(items):
                raise ProducerSnapshotUnavailable(
                    f"{kind} clone group {group_key!r} carries two items under "
                    "one identity"
                )
            rows.append(
                CloneGroupRow(clone_kind=kind, group_key=group_key, items=unique)
            )
    return frozenset(rows)


class _SemanticFamilies(NamedTuple):
    """The six authority families, or six honest emptinesses."""

    contracts: frozenset[ContractRow]
    graph_nodes: frozenset[GraphNodeRow]
    sink_roles: frozenset[SinkRoleRow]
    candidates: frozenset[CandidateRow]
    semantic_edges: frozenset[SemanticEdge]
    violations: frozenset[ViolationRow]


_EMPTY_SEMANTIC = _SemanticFamilies(
    frozenset(), frozenset(), frozenset(), frozenset(), frozenset(), frozenset()
)


def _semantic_families(
    semantic: SemanticAuthorityResult | None, index: IdentityIndex
) -> _SemanticFamilies:
    """The authority tier, straight off its producer.

    ``None`` is the lane's own execution witness — the producer was never
    invoked — and six empty families beside a population that says
    ``semantic_authority: disabled`` is a measured statement, not a fake
    zero.  When the lane DID run, every row resolves through the shared
    grammar owner, so this path and the ingest oracle cannot end up
    disagreeing about one identity.
    """

    if semantic is None:
        return _EMPTY_SEMANTIC
    return _SemanticFamilies(
        contracts=frozenset(
            ContractRow(
                function=parse_symbol(index, row.function, "contract_ir.function"),
                effect_signature=row.effect_signature,
                root_set=parse_root_set(
                    index, row.provenance_roots, "contract_ir.provenance_roots"
                ),
            )
            for row in semantic.contract_ir.contracts
        ),
        graph_nodes=frozenset(
            GraphNodeRow(
                function=parse_symbol(index, node.function, "graph.nodes.function"),
                effect_signature=node.effect_signature,
                root_set=parse_root_set(
                    index, node.producer_root_ids, "graph.nodes.producer_root_ids"
                ),
                output_facts=node.output_facts,
                resolution_state=node.resolution_state,
            )
            for node in semantic.graph.nodes
        ),
        sink_roles=frozenset(
            SinkRoleRow(
                symbol=parse_symbol(index, sink.sink_identity, "sinks.sink_identity"),
                authority_status=sink.authority_status,
            )
            for sink in semantic.sinks
        ),
        candidates=frozenset(
            CandidateRow(
                level=candidate.level,
                shared_fact=candidate.shared_fact,
                producer_set=parse_symbol_set(
                    index, candidate.producers, "candidates.producers"
                ),
            )
            for candidate in semantic.candidates
        ),
        semantic_edges=frozenset(
            SemanticEdge(
                source=parse_symbol(index, edge.source, "graph.edges.source"),
                target=parse_symbol(index, edge.target, "graph.edges.target"),
            )
            for edge in semantic.graph.edges
        ),
        violations=frozenset(
            ViolationRow(
                contract_id=violation.contract_id,
                kind=violation.kind,
                sink_identity=parse_symbol(
                    index, violation.sink_identity, "violation.sink_identity"
                ),
                canonical_owner=parse_symbol(
                    index, violation.canonical_owner, "violation.canonical_owner"
                ),
                authority_status=violation.authority_status,
                effect_signature=violation.effect_signature,
                resolution_state=violation.resolution_state,
                root_set=parse_root_set(
                    index, violation.producer_root_ids, "violation.producer_root_ids"
                ),
                producer_set=parse_symbol_set(
                    index, violation.producers, "violation.producers"
                ),
                suppressed=violation.suppressed,
            )
            for violation in semantic.violations
        ),
    )


# ---------------------------------------------------------------------------
# The snapshot, and the one publication decision
# ---------------------------------------------------------------------------


def canonical_snapshot_from_producers(
    *,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
) -> CanonicalModel:
    """Build one normalized model straight from the run's producers.

    Total over the wave-4 family set, the six semantic-authority families
    included: their producer rows carry the same glued identity strings the
    report does, and since the 2026-08-31 transplant both readings resolve
    them through the ONE grammar owner
    (``codeclone.canonical.semantic_grammar``).  A semantic lane that never
    ran leaves the six families legitimately empty and says so through the
    population witness; an unresolvable spelling fails closed here and in
    the ingest oracle identically.
    """

    bundle: ObservationBundle = analysis.observation_bundle
    analyzed = frozenset(identity.path for identity in bundle.analysis_scope)
    index = _identity_index(bundle.registry, analyzed)
    semantic = _semantic_families(bundle.semantic, index)
    payload = analysis.metrics_payload or {}
    structural = bundle.structural
    relations, occurrences = _dependency_rows(payload, index)
    facts = AnalysisFacts(
        contracts=semantic.contracts,
        graph_nodes=semantic.graph_nodes,
        sink_roles=semantic.sink_roles,
        candidates=semantic.candidates,
        semantic_edges=semantic.semantic_edges,
        violations=semantic.violations,
        clone_groups=_clone_group_rows(analysis, index),
        dependency_relations=relations,
        dependency_occurrences=occurrences,
        dependency_cycles=_dependency_cycle_rows(payload, index),
        dead_code_observations=_dead_code_rows(structural.dead_code, index),
        coupling_cohesion_observations=_coupling_cohesion_rows(
            structural.coupling_cohesion_observations, index
        ),
        api_symbols=_api_symbol_rows(structural.api_surface, index),
        risk_observations=_risk_rows(structural.risk_observations, index),
        adoption_counts=_adoption_rows(structural.adoption_counts, index),
        security_surfaces=_security_surface_rows(payload, index),
        run_scalars=_run_scalars(discovery, processing),
        analysis_population=producer_execution_population(
            discovery=discovery,
            analysis=analysis,
            report_meta=report_meta,
        ),
    )
    files = frozenset(FileId(path) for path in analyzed)
    return CanonicalModel(
        files=files,
        modules=frozenset(ModuleId(name) for name in index.module_to_path),
        analyzed_files=files,
        file_modules=frozenset(
            FileModuleRelation(FileId(path), ModuleId(module))
            for path, module in index.path_to_module.items()
        ),
        facts=CanonicalFacts(analysis=facts),
        coupled_sets=_coupled_sets(payload),
    ).normalize()


def publish_run_snapshot(
    *,
    config: RunStoreConfig,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
    namespace: str = RUN_SNAPSHOT_NAMESPACE,
) -> RunSnapshotPublication:
    """Resolve, build and publish — or say, typed, why nothing was stored.

    Every path returns a witness.  A publication that skipped silently
    would be indistinguishable from a backend that was never wired, which
    is the exact confusion this rollout exists to avoid, and the skip is
    the DEFAULT path (the flag ships off).
    """

    with span(name="canonical.snapshot.publish") as publish_span:
        publish_span.set_counter("run_snapshot_publish_attempts", 1)
        if not config.enabled or config.path is None:
            publish_span.set_counter("run_snapshot_publish_disabled", 1)
            return RunSnapshotPublication(
                outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED, admissible=False
            )
        try:
            model = canonical_snapshot_from_producers(
                discovery=discovery,
                processing=processing,
                analysis=analysis,
                report_meta=report_meta,
            )
        except ProducerSnapshotUnavailable as refusal:
            # Anticipated: a rollout flag may not fail an analysis, and it
            # may not invent the families it cannot express either.
            publish_span.set_counter("run_snapshot_publish_refused", 1)
            return RunSnapshotPublication(
                outcome=RUN_SNAPSHOT_PUBLICATION_REFUSED,
                admissible=False,
                reason=str(refusal),
            )
        population = model.facts.analysis.analysis_population
        if population is None:  # pragma: no cover - the builder always writes it
            raise ProducerSnapshotUnavailable("the snapshot carries no population")
        admissible = population_is_admissible(population)
        target = profile_head_target(population)
        publish_span.set_counter(
            "run_snapshot_publish_inadmissible", 0 if admissible else 1
        )
        config.path.parent.mkdir(parents=True, exist_ok=True)
        # Imported at use, not at module scope: the store is opened only on
        # the enabled path, so a disabled rollout never touches sqlite.
        from ..canonical.store import RunStore

        with RunStore(config.path) as store:
            head = store.head(namespace=namespace, target=target)
            receipt = store.write_full_run(
                model,
                namespace=namespace,
                target=target,
                expected_generation=0 if head is None else head.generation,
            )
        if receipt.head_advanced:
            outcome = (
                RUN_SNAPSHOT_PUBLICATION_PUBLISHED
                if admissible
                else RUN_SNAPSHOT_PUBLICATION_HEAD_WITHHELD
            )
        else:
            outcome = RUN_SNAPSHOT_PUBLICATION_HEAD_CONFLICT
        publish_span.set_counter("run_snapshot_publish_stored", 1)
        return RunSnapshotPublication(
            outcome=outcome,
            admissible=admissible,
            target=target,
            run_id=receipt.run_id,
            generation=receipt.generation,
        )


__all__ = [
    "CLONES_ONLY_MODE",
    "ENV_RUN_STORE_ENABLED",
    "ENV_RUN_STORE_FORCE",
    "ENV_RUN_STORE_PATH",
    "RUN_SNAPSHOT_NAMESPACE",
    "ProducerSnapshotUnavailable",
    "canonical_snapshot_from_producers",
    "population_is_admissible",
    "producer_execution_population",
    "producer_state",
    "profile_head_target",
    "publish_run_snapshot",
    "resolve_run_store_config",
]

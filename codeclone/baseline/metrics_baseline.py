# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Read-only metrics projection from authenticated native v3 lanes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from ..contracts import (
    BASELINE_SCHEMA_VERSION,
    COHESION_RISK_MEDIUM_MAX,
    COMPLEXITY_RISK_LOW_MAX,
    COMPLEXITY_RISK_MEDIUM_MAX,
    COUPLING_RISK_LOW_MAX,
    COUPLING_RISK_MEDIUM_MAX,
)
from ..contracts.errors import BaselineValidationError
from ..domain.source_scope import SURFACE_KIND_PRODUCT_PUBLIC
from ..metrics._visibility import is_public_module_name
from ..metrics.api_surface import is_product_api_module
from ..metrics.dependencies import (
    build_import_graph,
    depth_profile,
    max_depth,
    runtime_cycle_facts,
)
from ..metrics.health import HealthInputs, compute_health
from ..models import (
    AdoptionColumnarPayload,
    AdoptionCount,
    AdoptionObservationPayload,
    ApiParamSpec,
    ApiSurfaceColumnarPayload,
    ApiSurfaceObservationPayload,
    ApiSurfaceSnapshot,
    BaselineContainerV3,
    CloneObservationPayload,
    ContainerReadFailure,
    ContainerReadSuccess,
    DeadCodeColumnarPayload,
    DeadCodeObservationPayload,
    DependencyColumnarPayload,
    DependencyObservationPayload,
    ImportOccurrenceObservation,
    IntegerColumnarPayload,
    IntegerObservationPayload,
    LaneTrust,
    MetricsDiff,
    MetricsSnapshot,
    ModuleApiSurface,
    ModuleDep,
    ModuleIdentityColumnarPayload,
    ModuleIdentityObservationPayload,
    ObservationLaneName,
    ProjectMetrics,
    PublicSymbol,
    RiskColumnarPayload,
    RiskObservationPayload,
    cycle_kind_counts,
)
from ..observations.projection import glued_observation_identity
from ..report.gates.evaluator import HEALTH_INPUT_LANES
from ._metrics_baseline_contract import (
    MAX_METRICS_BASELINE_SIZE_BYTES,
    MetricsBaselineStatus,
    coerce_metrics_baseline_status,
)
from .container import read_container_v3
from .container_trust import (
    map_container_read_failure,
    unavailable_container_lanes,
    unavailable_lanes_after_version_checks,
)
from .diff import diff_metrics
from .lanes import (
    decode_adoption_lane,
    decode_api_surface_lane,
    decode_dead_code_lane,
    decode_dependency_lane,
    decode_integer_lane,
    decode_module_identity_lane,
    decode_risk_lane,
    lane_payload_is_opaque,
)
from .trust import current_python_tag

#: Lane-trust reasons that mean "this artifact was produced by a different
#: version of the observation contract itself". Each is a declared version
#: moving, never a corrupted or foreign artifact: the operator must regenerate,
#: and no surface may present the difference as a finding about the analyzed
#: code. Deliberately narrow — integrity, scope and interpreter mismatches are
#: not contract drift, and ``required_contract`` (an identity contract such as
#: the fingerprint version) and ``runtime_lane_unknown`` (a lane this runtime
#: does not have at all) keep their own established statuses.
_METRICS_CONTRACT_REASONS: frozenset[str] = frozenset(
    {
        "algorithm_revision",
        "canonicalization_version",
        "descriptor_version",
        "payload_schema",
        "payload_schema_outdated",
    }
)


@dataclass(frozen=True, slots=True)
class MetricsBaselineSectionProbe:
    has_metrics_section: bool
    payload: dict[str, object] | None


def probe_metrics_baseline_section(path: Path) -> MetricsBaselineSectionProbe:
    if not path.exists():
        return MetricsBaselineSectionProbe(False, None)
    result = read_container_v3(path, limit_bytes=MAX_METRICS_BASELINE_SIZE_BYTES)
    if not isinstance(result, ContainerReadSuccess):
        return MetricsBaselineSectionProbe(True, None)
    names = set(result.container.lanes)
    return MetricsBaselineSectionProbe(
        bool(names - {"clones.functions", "clones.blocks", "module_identity"}),
        None,
    )


class MetricsBaseline:
    __slots__ = (
        "api_surface_payload_sha256",
        "api_surface_snapshot",
        "container",
        "created_at",
        "generator_name",
        "generator_version",
        "has_coverage_adoption_snapshot",
        "is_embedded_in_clone_baseline",
        "path",
        "payload_sha256",
        "python_tag",
        "schema_version",
        "snapshot",
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.container: BaselineContainerV3 | None = None
        self.generator_name: str | None = None
        self.generator_version: str | None = None
        self.schema_version: str | None = None
        self.python_tag: str | None = None
        self.created_at: str | None = None
        self.payload_sha256: str | None = None
        self.snapshot: MetricsSnapshot | None = None
        self.has_coverage_adoption_snapshot = False
        self.api_surface_payload_sha256: str | None = None
        self.api_surface_snapshot: ApiSurfaceSnapshot | None = None
        self.is_embedded_in_clone_baseline = True

    def load(self, *, max_size_bytes: int | None = None) -> None:
        result = read_container_v3(
            self.path,
            limit_bytes=(
                MAX_METRICS_BASELINE_SIZE_BYTES
                if max_size_bytes is None
                else max_size_bytes
            ),
        )
        if isinstance(result, ContainerReadFailure):
            raise BaselineValidationError(
                result.detail,
                status=map_container_read_failure(
                    result.reason,
                    too_large=MetricsBaselineStatus.TOO_LARGE,
                    invalid_json=MetricsBaselineStatus.INVALID_JSON,
                    integrity_failed=MetricsBaselineStatus.INTEGRITY_FAILED,
                    schema_mismatch=MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION,
                    invalid_type=MetricsBaselineStatus.INVALID_TYPE,
                ),
            )
        if not isinstance(result, ContainerReadSuccess):
            raise BaselineValidationError(
                "Metrics lanes are inspection-only.",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        container = result.container
        self.container = container
        self.generator_name = container.meta.generator.name
        self.generator_version = container.meta.generator.version
        self.schema_version = container.meta.container_version
        self.python_tag = container.meta.python_tag
        self.created_at = container.meta.created_at
        self.payload_sha256 = container.meta.root_digest.value
        self.api_surface_snapshot = _api_surface_snapshot(container)
        self.has_coverage_adoption_snapshot = "adoption_counts" in container.lanes

    def verify_compatibility(
        self,
        *,
        runtime_python_tag: str,
        baseline_scope_id: UUID,
    ) -> None:
        unavailable = unavailable_container_lanes(
            self.container,
            python_tag=runtime_python_tag,
            baseline_scope_id=baseline_scope_id,
            missing_message="Metrics baseline container is missing.",
            missing_status=MetricsBaselineStatus.MISSING_FIELDS,
            root_message="Metrics baseline root digest mismatch.",
            integrity_status=MetricsBaselineStatus.INTEGRITY_FAILED,
        )
        if unavailable:
            reasons = ", ".join(f"{item.name}:{item.reason}" for item in unavailable)
            if any(item.reason == "baseline_scope_id" for item in unavailable):
                status = MetricsBaselineStatus.MISMATCH_SCOPE_ID
            elif all(item.reason in _METRICS_CONTRACT_REASONS for item in unavailable):
                status = MetricsBaselineStatus.INCOMPATIBLE_METRICS_CONTRACT
            else:
                status = MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION
            raise BaselineValidationError(
                f"Metrics baseline lane compatibility failed: {reasons}",
                status=status,
            )
        if self.schema_version != BASELINE_SCHEMA_VERSION:
            raise BaselineValidationError(
                "Metrics baseline schema mismatch.",
                status=MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION,
            )
        # No interpreter-tag check follows. This method was the harder of the two
        # tag sites: the lane projection merely degraded lanes, while this raised
        # outright, so a metrics baseline from another interpreter took the whole
        # run down even when the clone lanes were comparable. The tag is
        # provenance and is reported as such; it is not a compatibility term
        # (see ``baseline.container_trust._lane_trust`` for the measurement).

    def unavailable_lanes(
        self,
        *,
        runtime_python_tag: str,
        baseline_scope_id: UUID,
    ) -> tuple[LaneTrust, ...]:
        """Report untrusted lanes instead of condemning the whole container.

        The clone-lane twin of this method carries the full rationale; the
        contract is identical. ``verify_compatibility`` is left alone.

        The whole-container version checks below no longer include the
        interpreter tag. This was a third tag site, distinct from the lane
        projection and from ``verify_compatibility``, and it was asymmetric: the
        clone twin's ``version_checks`` never carried a tag term, so the two
        halves of one container disagreed about whether the tag was a
        compatibility question at all. Both now agree that it is not.
        """

        return unavailable_lanes_after_version_checks(
            self.container,
            python_tag=runtime_python_tag,
            baseline_scope_id=baseline_scope_id,
            missing_message="Metrics baseline container is missing.",
            missing_status=MetricsBaselineStatus.MISSING_FIELDS,
            root_message="Metrics baseline root digest mismatch.",
            integrity_status=MetricsBaselineStatus.INTEGRITY_FAILED,
            version_checks=(
                (
                    self.schema_version,
                    BASELINE_SCHEMA_VERSION,
                    "Metrics baseline schema mismatch.",
                    MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION,
                ),
            ),
        )

    def diff(self, current: ProjectMetrics) -> MetricsDiff:
        container = self.container
        if container is None:
            baseline_snapshot = None
        else:
            baseline_snapshot = _snapshot(container)
            self.snapshot = baseline_snapshot
        baseline_api, current_api = _gating_api_surfaces(
            baseline=self.api_surface_snapshot,
            current=current.api_surface,
        )
        return diff_metrics(
            baseline_snapshot=baseline_snapshot,
            current_snapshot=_current_snapshot(current),
            baseline_api_surface=baseline_api,
            current_api_surface=current_api,
        )


def _lane_payload(
    container: BaselineContainerV3,
    name: ObservationLaneName,
) -> object | None:
    """Return one lane as typed rows, decoding the columnar wire on the way."""

    try:
        payload = container.lanes[name].payload
    except KeyError:
        return None
    if isinstance(payload, IntegerColumnarPayload):
        return decode_integer_lane(payload)
    if isinstance(payload, RiskColumnarPayload):
        return decode_risk_lane(payload)
    if isinstance(payload, DeadCodeColumnarPayload):
        return decode_dead_code_lane(payload)
    if isinstance(payload, AdoptionColumnarPayload):
        return decode_adoption_lane(payload)
    if isinstance(payload, DependencyColumnarPayload):
        return decode_dependency_lane(payload)
    if isinstance(payload, ModuleIdentityColumnarPayload):
        return decode_module_identity_lane(payload)
    if isinstance(payload, ApiSurfaceColumnarPayload):
        return decode_api_surface_lane(payload)
    return payload


def _integer_lane(
    container: BaselineContainerV3,
    name: ObservationLaneName,
) -> tuple[tuple[tuple[str, str, int], ...], int]:
    """Return the lane rows plus the entity population they were observed from."""

    payload = _lane_payload(container, name)
    if not isinstance(payload, (IntegerObservationPayload, RiskObservationPayload)):
        return (), 0
    rows = tuple(
        (item.qualname, item.dimension, item.numerator) for item in payload.observations
    )
    return rows, payload.entity_population


def _entity_identity_rows(
    container: BaselineContainerV3,
    name: ObservationLaneName,
) -> tuple[tuple[str, str, int], ...]:
    """Return lane rows named the way a run names its entities.

    ``_integer_lane`` above yields the stored halves: the lane keeps the source
    identity apart from the bare qualname, and nothing the container hands out
    may glue them. Comparing rows against a run is a different question and
    needs the producer's identity back, so the join lives here -- the one place
    where lane rows meet run identities -- and nowhere in the decode path.

    Without it the comparison silently reads two different things and reports
    every entity the baseline already knows as new.

    This is the coupling/cohesion half: class symbols are declared once per
    name, so the triple is the whole key.  Risk rows carry a declaration
    site and are keyed by :func:`_risk_entity_identity_rows` instead.
    """

    payload = _lane_payload(container, name)
    if not isinstance(payload, IntegerObservationPayload):
        return ()
    return tuple(
        (
            glued_observation_identity(item.source, item.qualname),
            item.dimension,
            item.numerator,
        )
        for item in payload.observations
    )


def _risk_entity_identity_rows(
    container: BaselineContainerV3,
) -> tuple[tuple[str, str, int, int], ...]:
    """The risk half of the identity join, keyed with the declaration site.

    F1 (ruling 2026-08-26): two declarations sharing one qualname —
    ``@overload`` groups, property/setter pairs — are different entities,
    and a site-blind row key makes their rows byte-identical, so any keyed
    consumer collapses two facts into one.  ``start_line`` completes the
    row key here, in the baseline-reader join; the GLUED IDENTITY SPELLING
    deliberately does not change — the report vocabulary is untouched
    (lane-contract migration, not a report-schema change).
    """

    payload = _lane_payload(container, "risk_observations")
    if not isinstance(payload, RiskObservationPayload):
        return ()
    return tuple(
        (
            glued_observation_identity(item.source, item.qualname),
            item.dimension,
            item.numerator,
            item.start_line,
        )
        for item in payload.observations
    )


def _health_evidence_is_readable(container: BaselineContainerV3) -> bool:
    """Whether every lane the stored health number is derived from decoded.

    Reads ``HEALTH_INPUT_LANES`` -- the versioned manifest this repository
    already publishes as ``contracts.evaluation.health_input_lanes`` and that
    the gate-to-lane matrix already keys on -- instead of restating the set
    here, so the report's answer and the gate's answer cannot become two
    semantics for one fact (`G2`).

    Without this, the ``isinstance`` guards in ``_snapshot`` below turn an
    opaque lane into zero observations. Zero observations is a different fact,
    and a flattering one: the lane's dimension then scores as clean, the stored
    health reads better or worse than it was, and the delta measured against it
    is fabricated. An opaque lane is authentic and unreadable, never empty
    (`G4`, `RP2`, `B8`).
    """

    for name in HEALTH_INPUT_LANES:
        try:
            lane = container.lanes[name]
        except KeyError:
            return False
        if lane_payload_is_opaque(lane):
            return False
    return True


def _average(values: tuple[int, ...], population: int) -> float:
    """Average over the observed population: absence is zero, so sums are complete."""

    return sum(values) / population if population else 0.0


def _permille(rows: tuple[tuple[int, int], ...]) -> int:
    numerator = sum(item[0] for item in rows)
    denominator = sum(item[1] for item in rows)
    return round(numerator * 1000 / denominator) if denominator else 0


def _snapshot(container: BaselineContainerV3) -> MetricsSnapshot:
    risk_rows, risk_population = _integer_lane(container, "risk_observations")
    class_rows, class_population = _integer_lane(
        container, "coupling_cohesion_observations"
    )
    # Values are read from the stored rows; the three sets below name entities
    # that a run's own sets are differenced against, so they read the rejoined
    # identity instead.  Risk rows arrive keyed with their declaration site
    # (F1): two @overload declarations of one qualname are two facts here,
    # never one byte-identical row, while the glued identity string each
    # contributes stays the report's unchanged vocabulary.
    risk_identity_rows = _risk_entity_identity_rows(container)
    class_identity_rows = _entity_identity_rows(
        container, "coupling_cohesion_observations"
    )
    complexities = tuple(
        value for _qualname, dim, value in risk_rows if dim == "cyclomatic_complexity"
    )
    coupling = tuple(value for _qualname, dim, value in class_rows if dim == "cbo")
    cohesion = tuple(value for _qualname, dim, value in class_rows if dim == "lcom4")
    high_risk = tuple(
        sorted(
            identity
            for identity, dim, value, _site in risk_identity_rows
            if dim == "cyclomatic_complexity" and value > COMPLEXITY_RISK_MEDIUM_MAX
        )
    )
    high_coupling = tuple(
        sorted(
            identity
            for identity, dim, value in class_identity_rows
            if dim == "cbo" and value > COUPLING_RISK_MEDIUM_MAX
        )
    )
    low_cohesion = tuple(
        sorted(
            identity
            for identity, dim, value in class_identity_rows
            if dim == "lcom4" and value > COHESION_RISK_MEDIUM_MAX
        )
    )

    dependency_payload = _lane_payload(container, "dependencies")
    modules: tuple[str, ...] = ()
    dependency_edges: tuple[ModuleDep, ...] = ()
    if isinstance(dependency_payload, DependencyObservationPayload):
        modules = tuple(
            sorted(
                {
                    module
                    for item in dependency_payload.observations
                    for module in (
                        (
                            item.source.python_module.module
                            if item.source.python_module
                            else ""
                        ),
                        item.resolved_target or "",
                    )
                    if module
                }
            )
        )
        dependency_edges = tuple(
            _import_dependency(item)
            for item in dependency_payload.observations
            if item.source.python_module is not None
            and item.resolved_target is not None
        )
    graph = build_import_graph(modules=modules, deps=dependency_edges)
    # Same owner as the live path, so a baseline and a fresh run classify the
    # same repository identically. The lane has carried each row's binding
    # since payload_schema "6"; reading it here is what makes the stored kinds
    # survive across runs instead of every reconstructed cycle reading as
    # critical.
    cycle_facts = runtime_cycle_facts(modules=modules, deps=dependency_edges)
    cycle_counts = cycle_kind_counts(
        cycles=tuple(fact.modules for fact in cycle_facts),
        details=cycle_facts,
    )
    depth_avg, depth_p95 = depth_profile(graph)
    graph_depth = max_depth(graph)

    dead_payload = _lane_payload(container, "dead_code")
    dead = (
        tuple(item.entity for item in dead_payload.candidates)
        if isinstance(dead_payload, DeadCodeObservationPayload)
        else ()
    )
    # The baseline half of the permille refusal. An adoption lane that is
    # missing or arrived authentic-but-unreadable is not an empty one: reading
    # it as zero observations manufactured 0‰ for every adoption dimension,
    # and the diff then subtracted that fabricated zero (`B5`, `RP2`, `G4`).
    # A readable lane with no rows stays a measurement — nothing to count is
    # a fact, not a failure to observe.
    adoption = _lane_payload(container, "adoption_counts")
    if isinstance(adoption, AdoptionObservationPayload):
        adoption_readable = True
        adoption_rows: tuple[AdoptionCount, ...] = adoption.counts
    else:
        adoption_readable = False
        adoption_rows = ()
    typing_params = tuple(
        (item.numerator, item.denominator)
        for item in adoption_rows
        if item.feature == "typing.parameters"
    )
    typing_returns = tuple(
        (item.numerator, item.denominator)
        for item in adoption_rows
        if item.feature == "typing.returns"
    )
    docstrings = tuple(
        (item.numerator, item.denominator)
        for item in adoption_rows
        if item.feature == "docstrings.public_symbols"
    )

    module_payload = _lane_payload(container, "module_identity")
    analyzed_files = (
        sum(item.analyzed for item in module_payload.module_registry)
        if isinstance(module_payload, ModuleIdentityObservationPayload)
        else 0
    )
    function_clones = _lane_payload(container, "clones.functions")
    block_clones = _lane_payload(container, "clones.blocks")
    health = compute_health(
        HealthInputs(
            files_found=analyzed_files,
            files_analyzed_or_cached=analyzed_files,
            function_clone_groups=(
                len(function_clones.items)
                if isinstance(function_clones, CloneObservationPayload)
                else 0
            ),
            block_clone_groups=(
                len(block_clones.items)
                if isinstance(block_clones, CloneObservationPayload)
                else 0
            ),
            complexity_avg=_average(complexities, risk_population),
            complexity_max=max(complexities, default=0),
            high_risk_functions=len(high_risk),
            elevated_complexity_functions=sum(
                value > COMPLEXITY_RISK_LOW_MAX for value in complexities
            ),
            complexity_function_population=risk_population,
            coupling_avg=_average(coupling, class_population),
            coupling_max=max(coupling, default=0),
            high_risk_classes=len(high_coupling),
            elevated_coupling_classes=sum(
                value > COUPLING_RISK_LOW_MAX for value in coupling
            ),
            coupling_class_population=class_population,
            cohesion_avg=_average(cohesion, class_population),
            low_cohesion_classes=len(low_cohesion),
            import_dependency_cycles=cycle_counts.import_cycles,
            deferred_dependency_cycles=cycle_counts.deferred_cycles,
            dependency_max_depth=graph_depth,
            dependency_avg_depth=depth_avg,
            dependency_p95_depth=depth_p95,
            dead_code_items=len(dead),
        )
    )
    # The snapshot must carry the absence rather than a plausible integer:
    # ``health_delta`` is measured against this field, and a zero here becomes a
    # comparison the run never made (`B8`, `G4`).
    #
    # Only the lane predicate is consulted, deliberately. Adding
    # ``population_carries_score(health.population)`` beside it was tried and
    # removed: no admissible container can reach it. Both constructions were
    # attempted against ``read_container_v3`` -- an empty identity table, and a
    # registry whose every row is ``known_internal_not_analyzed`` -- and both are
    # refused upstream as ``inconsistent_container`` ("analysis scope digest does
    # not match module_identity"). ``files_found`` and ``files_analyzed_or_cached``
    # are also the same counter here, so the population of a *readable* container
    # is always ``complete_nonempty``. A guard nothing can be shown to reach is
    # theater (`H2`); the reachable cause of a scoreless baseline health is the
    # opaque lane, and that is what this reads.
    health_measured = _health_evidence_is_readable(container)
    return MetricsSnapshot(
        max_complexity=max(complexities, default=0),
        high_risk_functions=high_risk,
        max_coupling=max(coupling, default=0),
        high_coupling_classes=high_coupling,
        max_cohesion=max(cohesion, default=0),
        low_cohesion_classes=low_cohesion,
        dependency_cycles=cycle_facts,
        dependency_max_depth=graph_depth,
        dead_code_items=tuple(sorted(dead)),
        health_score=health.total if health_measured else None,
        health_grade=health.grade if health_measured else None,
        typing_param_permille=(_permille(typing_params) if adoption_readable else None),
        typing_return_permille=(
            _permille(typing_returns) if adoption_readable else None
        ),
        docstring_permille=_permille(docstrings) if adoption_readable else None,
        typing_any_count=0,
    )


def _import_dependency(item: ImportOccurrenceObservation) -> ModuleDep:
    if item.source.python_module is None or item.resolved_target is None:
        raise ValueError("dependency observation is not graph-resolvable")
    return ModuleDep(
        source=item.source.python_module.module,
        target=item.resolved_target,
        import_type=item.syntax_kind,
        line=0,
        resolution=item.resolution,
        inventory_expansion=item.inventory_expansion,
        level=item.level,
        requested_module=item.requested_module,
        requested_names=item.requested_names,
        candidate_targets=item.candidate_targets,
        # Carried, not defaulted. ``ModuleDep`` defaults binding to
        # ``import_time``, so omitting these silently rewrote every stored
        # deferred, lazy, and typing edge into an eager one — which made every
        # reconstructed cycle read as critical and hid TYPE_CHECKING-only
        # cycles inside the baseline's cycle set.
        mechanism=item.mechanism,
        binding=item.binding,
        is_lazy=item.is_lazy,
    )


def _gating_api_surfaces(
    *,
    baseline: ApiSurfaceSnapshot | None,
    current: ApiSurfaceSnapshot | None,
) -> tuple[ApiSurfaceSnapshot | None, ApiSurfaceSnapshot | None]:
    """Narrow both sides of the api comparison to the gating surface.

    ``api_breaking_changes`` is a verdict about the project's published
    contract, and it was being computed over every module the run collected —
    a repository's own ``scripts/`` tree, a distributed package's private
    modules, everything importable. This is where the owner's verdict becomes
    the gate's population, and it is done to BOTH sides together: narrowing
    only the current one would report each dropped module's stored symbols as
    ``removed``, which is the same false-teardown mechanism an unmaterialized
    cache row produced.

    A stored module the current run has no row for at all is kept. Its absence
    is the ordinary reason a public symbol disappears — a deleted module — and
    withholding that from the gate would trade a false positive for a false
    negative. Only a module the run classified, and classified as non-gating,
    is dropped from both sides.

    The kinds come from the run, never from the container: what a project ships
    is a property of the checkout being analysed, and the baseline predates any
    answer to it.

    The join is the MODULE IDENTITY, not the file path, and that is measured
    rather than stylistic: a run carries absolute runtime paths while the
    container stores repository-relative ones, so a path join matches nothing
    and every narrowed module falls through the "the run never classified it"
    branch. Measured on this repository with a path join: 183 breaking changes
    instead of 51, of which 138 were ``benchmarks``, ``scripts`` and ``plugins``
    modules reported as removed on an untouched tree — the exact false teardown
    this function exists to prevent, produced by the function itself.
    ``compare_api_surfaces`` already keys on ``module:qualname``, so module
    identity is the join the rest of the lane uses.
    """

    if current is None:
        return baseline, current
    gating = {
        module.module
        for module in current.modules
        if module.surface_kind == SURFACE_KIND_PRODUCT_PUBLIC
    }
    classified = {module.module for module in current.modules}
    narrowed_current = ApiSurfaceSnapshot(
        modules=tuple(module for module in current.modules if module.module in gating)
    )
    if baseline is None:
        return None, narrowed_current
    narrowed_baseline = ApiSurfaceSnapshot(
        modules=tuple(
            module
            for module in baseline.modules
            if module.module in gating or module.module not in classified
        )
    )
    return narrowed_baseline, narrowed_current


def _api_surface_snapshot(container: BaselineContainerV3) -> ApiSurfaceSnapshot | None:
    """Rebuild the stored api surface the way a run names its symbols.

    The api half of the identity join (`F5`, ruling 2026-08-26).  The lane
    keeps the source identity apart from the bare symbol and nothing the
    container hands out may glue them, but ``compare_api_surfaces`` keys on
    the producer's ``module:qualname``, so the join lives here — the one
    place where lane rows meet run identities — and nowhere in the decode
    path.  The report vocabulary is deliberately untouched: this is a
    lane-contract migration, not a report-schema change.

    The same place carries the track split's compatibility bridge.  A
    baseline published before the split still holds a row per public symbol
    of the repository's own test tree; a run no longer produces any of them,
    so handing them to ``compare_api_surfaces`` unchanged would report every
    one as removed from the public API surface on an untouched repository.
    They are dropped on the way out instead, which lets an old baseline
    degrade quietly on this lane until its owner regenerates it.  The
    verdict comes from the same owner the run uses, minus the run's module
    registry, which the container does not carry: registry-free the owner is
    strictly the more cautious of the two, so the bridge can drop a stored
    ``testing`` subpackage of a distributed package that a fresh run would
    keep — never the other way round.
    """

    payload = _lane_payload(container, "api_surface")
    if not isinstance(payload, ApiSurfaceObservationPayload):
        return None
    rows: dict[tuple[str, str], list[PublicSymbol]] = {}
    for item in payload.symbols:
        module = item.owner.python_module
        # One refusal, three reasons, because they are one question: is this
        # stored row something a run still produces? The privacy term is the
        # newer half. A baseline published while ``include_private_modules``
        # was inert still holds a row per public-named symbol of every private
        # module declaring ``__all__``; a run collects none of them, so passing
        # them through would report each as removed from the public API.
        # Unconditional, and that is the safe direction: a run that DOES ask
        # for private modules keeps more than this bridge, which can only turn
        # a stored symbol into ``added``, never into ``removed``.
        if (
            module is None
            or not is_product_api_module(item.owner.file.path)
            or not is_public_module_name(module.module)
        ):
            continue
        key = (module.module, item.owner.file.path)
        rows.setdefault(key, []).append(
            PublicSymbol(
                qualname=glued_observation_identity(item.owner, item.symbol),
                kind=item.symbol_kind,
                start_line=0,
                end_line=0,
                params=tuple(
                    ApiParamSpec(
                        name=parameter.name,
                        kind=parameter.kind,
                        has_default=parameter.has_default,
                        annotation_hash=(
                            parameter.annotation_digest.value
                            if parameter.annotation_digest
                            else ""
                        ),
                    )
                    for parameter in item.parameters
                ),
                returns_hash=(item.returns_digest.value if item.returns_digest else ""),
                exported_via=item.visibility,
            )
        )
    return ApiSurfaceSnapshot(
        modules=tuple(
            ModuleApiSurface(
                module=module,
                filepath=filepath,
                symbols=tuple(
                    sorted(symbols, key=lambda item: (item.qualname, item.kind))
                ),
            )
            for (module, filepath), symbols in sorted(rows.items())
        )
    )


def _current_snapshot(current: ProjectMetrics) -> MetricsSnapshot:
    from ._metrics_baseline_payload import snapshot_from_project_metrics

    return snapshot_from_project_metrics(current)


__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "MAX_METRICS_BASELINE_SIZE_BYTES",
    "MetricsBaseline",
    "MetricsBaselineSectionProbe",
    "MetricsBaselineStatus",
    "coerce_metrics_baseline_status",
    "current_python_tag",
    "probe_metrics_baseline_section",
]

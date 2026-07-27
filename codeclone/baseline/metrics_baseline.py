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
    COMPLEXITY_RISK_MEDIUM_MAX,
    COUPLING_RISK_MEDIUM_MAX,
)
from ..contracts.errors import BaselineValidationError
from ..metrics.dependencies import (
    build_import_graph,
    depth_profile,
    find_cycles,
    max_depth,
)
from ..metrics.health import HealthInputs, compute_health
from ..models import (
    AdoptionColumnarPayload,
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
    ImportObservation,
    IntegerColumnarPayload,
    IntegerObservationPayload,
    MetricsDiff,
    MetricsSnapshot,
    ModuleApiSurface,
    ModuleDep,
    ModuleIdentityColumnarPayload,
    ModuleIdentityObservationPayload,
    ObservationLaneName,
    ProjectMetrics,
    PublicSymbol,
)
from ._metrics_baseline_contract import (
    MAX_METRICS_BASELINE_SIZE_BYTES,
    MetricsBaselineStatus,
    coerce_metrics_baseline_status,
)
from .container import read_container_v3
from .container_trust import map_container_read_failure, unavailable_container_lanes
from .diff import diff_metrics
from .lanes import (
    decode_adoption_lane,
    decode_api_surface_lane,
    decode_dead_code_lane,
    decode_dependency_lane,
    decode_integer_lane,
    decode_module_identity_lane,
)
from .trust import current_python_tag


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
            elif any(item.reason == "python_tag" for item in unavailable):
                status = MetricsBaselineStatus.MISMATCH_PYTHON_VERSION
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
        if self.python_tag != runtime_python_tag:
            raise BaselineValidationError(
                "Metrics baseline Python tag mismatch.",
                status=MetricsBaselineStatus.MISMATCH_PYTHON_VERSION,
            )

    def diff(self, current: ProjectMetrics) -> MetricsDiff:
        container = self.container
        if container is None:
            baseline_snapshot = None
        else:
            baseline_snapshot = _snapshot(container)
            self.snapshot = baseline_snapshot
        return diff_metrics(
            baseline_snapshot=baseline_snapshot,
            current_snapshot=_current_snapshot(current),
            baseline_api_surface=self.api_surface_snapshot,
            current_api_surface=current.api_surface,
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
    if not isinstance(payload, IntegerObservationPayload):
        return (), 0
    rows = tuple(
        (item.qualname, item.dimension, item.numerator) for item in payload.observations
    )
    return rows, payload.entity_population


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
    complexities = tuple(
        value for _qualname, dim, value in risk_rows if dim == "cyclomatic_complexity"
    )
    coupling = tuple(value for _qualname, dim, value in class_rows if dim == "cbo")
    cohesion = tuple(value for _qualname, dim, value in class_rows if dim == "lcom4")
    high_risk = tuple(
        sorted(
            qualname
            for qualname, dim, value in risk_rows
            if dim == "cyclomatic_complexity" and value > COMPLEXITY_RISK_MEDIUM_MAX
        )
    )
    high_coupling = tuple(
        sorted(
            qualname
            for qualname, dim, value in class_rows
            if dim == "cbo" and value > COUPLING_RISK_MEDIUM_MAX
        )
    )
    low_cohesion = tuple(
        sorted(
            qualname
            for qualname, dim, value in class_rows
            if dim == "lcom4" and value > COHESION_RISK_MEDIUM_MAX
        )
    )

    dependency_payload = _lane_payload(container, "dependencies")
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
        graph = build_import_graph(
            modules=modules,
            deps=tuple(
                _import_dependency(item)
                for item in dependency_payload.observations
                if item.source.python_module is not None
                and item.resolved_target is not None
            ),
        )
    else:
        graph = {}
    cycles = find_cycles(graph)
    depth_avg, depth_p95 = depth_profile(graph)
    graph_depth = max_depth(graph)

    dead_payload = _lane_payload(container, "dead_code")
    dead = (
        tuple(item.entity for item in dead_payload.candidates)
        if isinstance(dead_payload, DeadCodeObservationPayload)
        else ()
    )
    adoption = _lane_payload(container, "adoption_counts")
    adoption_rows = (
        adoption.counts if isinstance(adoption, AdoptionObservationPayload) else ()
    )
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
            coupling_avg=_average(coupling, class_population),
            coupling_max=max(coupling, default=0),
            high_risk_classes=len(high_coupling),
            cohesion_avg=_average(cohesion, class_population),
            low_cohesion_classes=len(low_cohesion),
            dependency_cycles=len(cycles),
            dependency_max_depth=graph_depth,
            dependency_avg_depth=depth_avg,
            dependency_p95_depth=depth_p95,
            dead_code_items=len(dead),
        )
    )
    return MetricsSnapshot(
        max_complexity=max(complexities, default=0),
        high_risk_functions=high_risk,
        max_coupling=max(coupling, default=0),
        high_coupling_classes=high_coupling,
        max_cohesion=max(cohesion, default=0),
        low_cohesion_classes=low_cohesion,
        dependency_cycles=cycles,
        dependency_max_depth=graph_depth,
        dead_code_items=tuple(sorted(dead)),
        health_score=health.total,
        health_grade=health.grade,
        typing_param_permille=_permille(typing_params),
        typing_return_permille=_permille(typing_returns),
        docstring_permille=_permille(docstrings),
        typing_any_count=0,
    )


def _import_dependency(item: ImportObservation) -> ModuleDep:
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
    )


def _api_surface_snapshot(container: BaselineContainerV3) -> ApiSurfaceSnapshot | None:
    payload = _lane_payload(container, "api_surface")
    if not isinstance(payload, ApiSurfaceObservationPayload):
        return None
    rows: dict[tuple[str, str], list[PublicSymbol]] = {}
    for item in payload.symbols:
        module = item.owner.python_module
        if module is None:
            continue
        key = (module.module, item.owner.file.path)
        rows.setdefault(key, []).append(
            PublicSymbol(
                qualname=item.symbol,
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

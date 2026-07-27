# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

import codeclone.baseline.container_trust as container_trust_mod
import codeclone.baseline.metrics_baseline as metrics_mod
from codeclone.baseline.container import build_container, read_container_v3
from codeclone.baseline.container_digest import canonical_container_bytes
from codeclone.baseline.metrics_baseline import (
    MetricsBaseline,
    MetricsBaselineStatus,
    probe_metrics_baseline_section,
)
from codeclone.contracts.errors import BaselineValidationError
from codeclone.models import (
    ApiSurfaceObservationPayload,
    ApiSymbolObservation,
    ClassMetrics,
    ContainerInspectionResult,
    DeadItem,
    DigestObject,
    FileIdentity,
    HealthScore,
    ImportObservation,
    LaneTrust,
    ObservationBundle,
    ObservationContract,
    ProjectMetrics,
    ResolvedSourceIdentity,
    TrustVector,
)
from codeclone.observations.contracts import build_observation_contract
from codeclone.observations.projection import build_observation_bundle
from tests._ast_metrics_helpers import module_registry_context
from tests.test_baseline import _write_container

_SCOPE_ID = UUID("018f4b8e-5a5f-7d35-9c21-4af5d18df420")


def _bundle() -> ObservationBundle:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        function_clone_keys=(f"{'a' * 64}|0-19",),
        block_clone_keys=("|".join(("b" * 64,) * 4),),
    )


def _unknown_lane_inspection() -> ContainerInspectionResult:
    return ContainerInspectionResult(
        root_digest=DigestObject(
            domain="codeclone.baseline.root.v1",
            algorithm="sha256",
            value="a" * 64,
        ),
        unknown_optional_lanes=("future",),
    )


def _project_metrics() -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=3.2,
        complexity_max=50,
        high_risk_functions=("pkg.mod:hot",),
        coupling_avg=2.0,
        coupling_max=10,
        high_risk_classes=("pkg.mod:Service",),
        cohesion_avg=1.8,
        cohesion_max=4,
        low_cohesion_classes=("pkg.mod:Service",),
        dependency_modules=2,
        dependency_edges=2,
        dependency_edge_list=(),
        dependency_cycles=(("pkg.a", "pkg.b"),),
        dependency_max_depth=6,
        dependency_longest_chains=(("pkg.a", "pkg.b"),),
        dead_code=(
            DeadItem(
                qualname="pkg.mod:unused",
                filepath="pkg/mod.py",
                start_line=1,
                end_line=2,
                kind="function",
                confidence="high",
            ),
        ),
        health=HealthScore(total=70, grade="C", dimensions={"health": 70}),
        typing_param_total=4,
        typing_param_annotated=3,
        typing_return_total=2,
        typing_return_annotated=2,
        typing_any_count=1,
        docstring_public_total=3,
        docstring_public_documented=2,
    )


def test_coerce_metrics_baseline_status_is_typed() -> None:
    assert metrics_mod.coerce_metrics_baseline_status("ok") is MetricsBaselineStatus.OK
    assert (
        metrics_mod.coerce_metrics_baseline_status("future")
        is MetricsBaselineStatus.INVALID_TYPE
    )
    assert (
        metrics_mod.coerce_metrics_baseline_status(None)
        is MetricsBaselineStatus.INVALID_TYPE
    )


def test_probe_reports_native_metrics_lanes_without_returning_legacy_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = probe_metrics_baseline_section(tmp_path / "missing.json")
    assert missing.has_metrics_section is False
    assert missing.payload is None

    path = _write_container(tmp_path, monkeypatch)
    probe = probe_metrics_baseline_section(path)
    assert probe.has_metrics_section is True
    assert probe.payload is None

    path.write_text("not-json", "utf-8")
    invalid = probe_metrics_baseline_section(path)
    assert invalid.has_metrics_section is True
    assert invalid.payload is None


def test_metrics_baseline_loads_only_native_v3_and_verifies_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_container(tmp_path, monkeypatch)
    baseline = MetricsBaseline(path)
    baseline.load()

    assert baseline.container is not None
    assert baseline.schema_version == "3.0"
    assert baseline.python_tag == "cp314"
    assert baseline.is_embedded_in_clone_baseline is True
    baseline.verify_compatibility(
        runtime_python_tag="cp314",
        baseline_scope_id=_SCOPE_ID,
    )

    with pytest.raises(BaselineValidationError) as scope_error:
        baseline.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=UUID("019f7fa1-8866-7242-b0bf-0ff282cafbcb"),
        )
    assert scope_error.value.status == MetricsBaselineStatus.MISMATCH_SCOPE_ID


def test_metrics_baseline_rejects_invalid_and_incompatible_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", "utf-8")
    with pytest.raises(BaselineValidationError) as invalid_error:
        MetricsBaseline(invalid).load()
    assert invalid_error.value.status == MetricsBaselineStatus.INVALID_JSON

    unsupported = tmp_path / "unsupported.json"
    unsupported.write_text("{}", "utf-8")
    with pytest.raises(BaselineValidationError) as unsupported_error:
        MetricsBaseline(unsupported).load()
    assert (
        unsupported_error.value.status == MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION
    )

    oversize = tmp_path / "oversize.json"
    oversize.write_text("{}", "utf-8")
    with pytest.raises(BaselineValidationError) as oversize_error:
        MetricsBaseline(oversize).load(max_size_bytes=1)
    assert oversize_error.value.status == MetricsBaselineStatus.TOO_LARGE

    path = _write_container(tmp_path, monkeypatch)
    baseline = MetricsBaseline(path)
    baseline.load()
    baseline.schema_version = "future"
    with pytest.raises(BaselineValidationError):
        baseline.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    baseline.schema_version = "3.0"
    with pytest.raises(BaselineValidationError):
        baseline.verify_compatibility(
            runtime_python_tag="cp313",
            baseline_scope_id=_SCOPE_ID,
        )

    empty = MetricsBaseline(tmp_path / "missing.json")
    with pytest.raises(BaselineValidationError):
        empty.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )


def test_metrics_diff_uses_lane_projection_and_current_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_container(tmp_path, monkeypatch)
    baseline = MetricsBaseline(path)
    baseline.load()

    diff = baseline.diff(_project_metrics())

    assert diff.new_high_risk_functions == ("pkg.mod:hot",)
    assert diff.new_high_coupling_classes == ("pkg.mod:Service",)
    assert diff.new_cycles == (("pkg.a", "pkg.b"),)
    assert diff.new_dead_code == ("pkg.mod:unused",)
    assert diff.typing_param_permille_delta == 750
    assert diff.typing_return_permille_delta == 1000


def test_snapshot_from_project_metrics_is_deterministic() -> None:
    project = _project_metrics()
    snapshot = metrics_mod._current_snapshot(project)
    duplicate = replace(
        project,
        high_risk_functions=("pkg.mod:hot", "pkg.mod:hot"),
    )

    assert metrics_mod._current_snapshot(duplicate) == snapshot
    assert snapshot.typing_param_permille == 750
    assert snapshot.docstring_permille == 667


def test_metrics_baseline_compares_lane_descriptors_to_current_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = MetricsBaseline(_write_container(tmp_path, monkeypatch))
    baseline.load()

    def _changed_runtime_contract(
        *,
        collect_metrics: bool,
        collect_dependencies: bool,
        collect_dead_code: bool,
        collect_api_surface: bool,
        collect_semantic_authority: bool,
    ) -> ObservationContract:
        contract = build_observation_contract(
            collect_metrics=collect_metrics,
            collect_dependencies=collect_dependencies,
            collect_dead_code=collect_dead_code,
            collect_api_surface=collect_api_surface,
            collect_semantic_authority=collect_semantic_authority,
        )
        descriptors = tuple(
            replace(item, payload_schema="future")
            if item.name == "risk_observations"
            else item
            for item in contract.descriptors
        )
        return replace(contract, descriptors=descriptors)

    monkeypatch.setattr(
        "codeclone.baseline.container_trust.build_observation_contract",
        _changed_runtime_contract,
    )

    with pytest.raises(BaselineValidationError) as error:
        baseline.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert error.value.status == MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION


def test_metrics_baseline_unloaded_inspection_and_root_states_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unloaded = MetricsBaseline(tmp_path / "missing.json")
    with pytest.raises(BaselineValidationError) as missing:
        unloaded.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert missing.value.status == MetricsBaselineStatus.MISSING_FIELDS

    inspection = _unknown_lane_inspection()
    monkeypatch.setattr(
        "codeclone.baseline.metrics_baseline.read_container_v3",
        lambda *_args, **_kwargs: inspection,
    )
    path = tmp_path / "inspection.json"
    path.write_text("{}", "utf-8")
    with pytest.raises(BaselineValidationError) as inspection_error:
        MetricsBaseline(path).load()
    assert inspection_error.value.status == MetricsBaselineStatus.INVALID_TYPE

    monkeypatch.setattr(
        "codeclone.baseline.metrics_baseline.read_container_v3",
        read_container_v3,
    )
    baseline = MetricsBaseline(_write_container(tmp_path, monkeypatch))
    baseline.load()
    monkeypatch.setattr(
        container_trust_mod,
        "evaluate_lane_trust",
        lambda *_args, **_kwargs: TrustVector(root_verified=False, lanes=()),
    )
    with pytest.raises(BaselineValidationError) as root_error:
        baseline.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert root_error.value.status == MetricsBaselineStatus.INTEGRITY_FAILED


def test_metrics_baseline_fallback_projections_remain_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = MetricsBaseline(tmp_path / "missing.json")
    diff = empty.diff(_project_metrics())
    assert diff.new_high_risk_functions == ("pkg.mod:hot",)

    container = build_container(_bundle(), _SCOPE_ID)
    assert metrics_mod._integer_lane(container, "dependencies") == ((), 0)
    assert (
        container_trust_mod.map_container_read_failure(
            "lane_digest_mismatch",
            too_large=MetricsBaselineStatus.TOO_LARGE,
            invalid_json=MetricsBaselineStatus.INVALID_JSON,
            integrity_failed=MetricsBaselineStatus.INTEGRITY_FAILED,
            schema_mismatch=MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION,
            invalid_type=MetricsBaselineStatus.INVALID_TYPE,
        )
        is MetricsBaselineStatus.INTEGRITY_FAILED
    )
    assert (
        container_trust_mod.map_container_read_failure(
            "future",
            too_large=MetricsBaselineStatus.TOO_LARGE,
            invalid_json=MetricsBaselineStatus.INVALID_JSON,
            integrity_failed=MetricsBaselineStatus.INTEGRITY_FAILED,
            schema_mismatch=MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION,
            invalid_type=MetricsBaselineStatus.INVALID_TYPE,
        )
        is MetricsBaselineStatus.INVALID_TYPE
    )

    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    limited_bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        collect_dependencies=False,
        collect_api_surface=False,
    )
    limited_path = tmp_path / "limited.json"
    limited_path.write_bytes(
        canonical_container_bytes(build_container(limited_bundle, _SCOPE_ID))
    )
    limited = MetricsBaseline(limited_path)
    limited.load()
    assert limited.api_surface_snapshot is None
    limited_diff = limited.diff(_project_metrics())
    assert limited_diff.new_cycles == (("pkg.a", "pkg.b"),)

    unresolved = ImportObservation(
        source=ResolvedSourceIdentity(
            file=FileIdentity(path="pkg/mod.py"),
            python_module=None,
        ),
        syntax_kind="from_import",
        level=1,
        requested_module=None,
        requested_names=("name",),
        resolution="unresolved_relative",
        candidate_targets=(),
        resolved_target=None,
    )
    with pytest.raises(ValueError, match="not graph-resolvable"):
        metrics_mod._import_dependency(unresolved)

    resolved = ImportObservation(
        source=registry.entries_by_module["pkg.mod"].identity,
        syntax_kind="import",
        level=0,
        requested_module="pkg.other",
        requested_names=(),
        resolution="external",
        candidate_targets=(),
        resolved_target="pkg.other",
    )
    dependency = metrics_mod._import_dependency(resolved)
    assert dependency.source == "pkg.mod"
    assert dependency.target == "pkg.other"

    api_payload = ApiSurfaceObservationPayload(
        symbols=(
            ApiSymbolObservation(
                owner=ResolvedSourceIdentity(
                    file=FileIdentity(path="pkg/no_module.py"),
                    python_module=None,
                ),
                symbol="public_name",
                symbol_kind="constant",
                visibility="name",
                parameters=(),
                returns_digest=None,
            ),
        )
    )
    api_container = replace(
        container,
        lanes=replace(
            container.lanes,
            rows=tuple(
                (name, replace(lane, payload=api_payload))
                if name == "api_surface"
                else (name, lane)
                for name, lane in container.lanes.rows
            ),
        ),
    )
    api_snapshot = metrics_mod._api_surface_snapshot(api_container)
    assert api_snapshot is not None
    assert api_snapshot.modules == ()


def test_metrics_baseline_required_contract_reason_is_schema_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = MetricsBaseline(_write_container(tmp_path, monkeypatch))
    baseline.load()
    monkeypatch.setattr(
        container_trust_mod,
        "evaluate_lane_trust",
        lambda *_args, **_kwargs: TrustVector(
            root_verified=True,
            lanes=(
                LaneTrust(
                    name="risk_observations",
                    status="unavailable",
                    reason="required_contract",
                ),
            ),
        ),
    )
    with pytest.raises(BaselineValidationError) as error:
        baseline.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert error.value.status == MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION

    baseline.python_tag = "future"
    monkeypatch.setattr(
        container_trust_mod,
        "evaluate_lane_trust",
        lambda *_args, **_kwargs: TrustVector(root_verified=True, lanes=()),
    )
    with pytest.raises(BaselineValidationError) as python_error:
        baseline.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert python_error.value.status == MetricsBaselineStatus.MISMATCH_PYTHON_VERSION


def _class_metric(qualname: str, *, cbo: int, lcom4: int, methods: int) -> ClassMetrics:
    return ClassMetrics(
        qualname=qualname,
        filepath="pkg/mod.py",
        start_line=1,
        end_line=9,
        cbo=cbo,
        lcom4=lcom4,
        method_count=methods,
        instance_var_count=0,
        risk_coupling="low",
        risk_cohesion="low",
    )


def test_lane_averages_over_entity_population_equal_the_pre_39u_row_averages() -> None:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    units = (
        {
            "filepath": "pkg/mod.py",
            "qualname": "pkg.mod:flat",
            "cyclomatic_complexity": 3,
            "nesting_depth": 0,
        },
        {
            "filepath": "pkg/mod.py",
            "qualname": "pkg.mod:deep",
            "cyclomatic_complexity": 7,
            "nesting_depth": 2,
        },
    )
    class_metrics = (
        _class_metric("pkg.mod:Lonely", cbo=0, lcom4=1, methods=0),
        _class_metric("pkg.mod:Coupled", cbo=4, lcom4=3, methods=2),
    )
    container = build_container(
        build_observation_bundle(
            scan_root=Path("."),
            module_registry=registry,
            units=units,
            class_metrics=class_metrics,
        ),
        _SCOPE_ID,
    )

    risk_rows, risk_population = metrics_mod._integer_lane(
        container, "risk_observations"
    )
    class_rows, class_population = metrics_mod._integer_lane(
        container, "coupling_cohesion_observations"
    )
    rows = risk_rows + class_rows

    # The population is the observed entity count, never the surviving-row count.
    assert (risk_population, class_population) == (len(units), len(class_metrics))
    # Absence-is-zero: no row observes nothing, and the zero-valued ones are gone.
    assert all(value for _qualname, _dimension, value in rows)
    assert len(risk_rows) == 3
    assert len(class_rows) == 4
    # Identity is structured: the consumer reads bare qualnames, never glued strings.
    assert {qualname for qualname, _dimension, _value in rows} == {
        "flat",
        "deep",
        "Lonely",
        "Coupled",
    }

    for dimension, population, pre_39u_values in (
        ("cyclomatic_complexity", risk_population, (3, 7)),
        ("nesting_depth", risk_population, (0, 2)),
        ("cbo", class_population, (0, 4)),
        ("lcom4", class_population, (1, 3)),
    ):
        surviving = tuple(value for _qualname, name, value in rows if name == dimension)
        assert metrics_mod._average(surviving, population) == sum(pre_39u_values) / len(
            pre_39u_values
        )

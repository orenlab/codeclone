# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import UUID

import pytest

import codeclone.baseline.container as container_mod
import codeclone.baseline.container_trust as container_trust_mod
import codeclone.baseline.metrics_baseline as metrics_mod
from codeclone.baseline.container import build_container, read_container_v3
from codeclone.baseline.container_digest import canonical_container_bytes
from codeclone.baseline.diff import diff_metrics
from codeclone.baseline.metrics_baseline import (
    MetricsBaseline,
    MetricsBaselineStatus,
    probe_metrics_baseline_section,
)
from codeclone.contracts import (
    COMPLEXITY_RISK_MEDIUM_MAX,
    COUPLING_RISK_MEDIUM_MAX,
    METRICS_BASELINE_SCHEMA_VERSION,
)
from codeclone.contracts.errors import BaselineValidationError
from codeclone.metrics.api_surface import compare_api_surfaces
from codeclone.models import (
    ApiParamSpec,
    ApiSurfaceObservationPayload,
    ApiSurfaceSnapshot,
    ApiSymbolObservation,
    BaselineContainerV3,
    BaselineLaneIndex,
    ClassMetrics,
    ContainerInspectionResult,
    DeadItem,
    DigestObject,
    FileIdentity,
    HealthScore,
    ImportOccurrenceObservation,
    LaneTrust,
    ModuleApiSurface,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    ObservationBundle,
    ObservationContract,
    ObservationLaneDescriptor,
    ProjectMetrics,
    PublicSymbol,
    PythonModuleIdentity,
    ResolvedSourceIdentity,
    RiskColumnarPayload,
    RiskObservationPayload,
    TrustVector,
)

if TYPE_CHECKING:
    from codeclone.contracts import HealthPopulation
from codeclone.observations.contracts import build_observation_contract
from codeclone.observations.lanes import _encode_api_surface_lane
from codeclone.observations.projection import build_observation_bundle
from tests._ast_metrics_helpers import module_registry_context
from tests.test_baseline import _write_container

_SCOPE_ID = UUID("018f4b8e-5a5f-7d35-9c21-4af5d18df420")

#: The two lanes that carry per-entity design metrics and share one revision.
_DESIGN_METRIC_LANES = frozenset(
    {"coupling_cohesion_observations", "risk_observations"}
)


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
    # The interpreter-tag stanza that used to follow here was removed with the
    # behaviour it asserted; the positive contract now lives in
    # ``test_metrics_baseline_accepts_a_foreign_interpreter_tag``.

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


def _refusal_project_metrics(population: str) -> ProjectMetrics:
    """A current run that observed nothing: the adoption counters are empty
    and the population owner says the run carries no verdict."""

    return replace(
        _project_metrics(),
        health=HealthScore(
            total=0,
            grade="F",
            dimensions={},
            population=cast("HealthPopulation", population),
        ),
        typing_param_total=0,
        typing_param_annotated=0,
        typing_return_total=0,
        typing_return_annotated=0,
        docstring_public_total=0,
        docstring_public_documented=0,
    )


@pytest.mark.parametrize("population", ["unmeasured", "complete_empty"])
def test_current_snapshot_withholds_permilles_when_population_carries_no_score(
    population: str,
) -> None:
    """A refusal run must not convert its permilles into measured zeros.

    Wave 14 taught the current half to carry the health refusal as ``None``;
    the permille fields beside it still read ``int``, so an empty or unread
    current run published 0 and the diff subtracted a whole good baseline
    from it — a fabricated -1000 regression (`G4`, `B8`).
    """

    snapshot = metrics_mod._current_snapshot(_refusal_project_metrics(population))

    assert snapshot.health_score is None
    assert snapshot.typing_param_permille is None
    assert snapshot.typing_return_permille is None
    assert snapshot.docstring_permille is None


def test_current_snapshot_keeps_permilles_for_a_partial_population() -> None:
    """The opposite boundary: a truncated run measured something real.

    ``partial`` carries a score by the population owner's own table; painting
    ``None`` over it would be the same defect wearing the other sign.
    """

    project = replace(
        _project_metrics(),
        health=HealthScore(
            total=70,
            grade="C",
            dimensions={"health": 70},
            population="partial",
        ),
    )

    snapshot = metrics_mod._current_snapshot(project)

    assert snapshot.typing_param_permille == 750
    assert snapshot.typing_return_permille == 1000
    assert snapshot.docstring_permille == 667


def _bundle_with_adoption() -> ObservationBundle:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        typing_modules=(
            ModuleTypingCoverage(
                module="pkg.mod",
                filepath="pkg/mod.py",
                callable_count=2,
                params_total=4,
                params_annotated=4,
                returns_total=2,
                returns_annotated=2,
                any_annotation_count=0,
            ),
        ),
        docstring_modules=(
            ModuleDocstringCoverage(
                module="pkg.mod",
                filepath="pkg/mod.py",
                public_symbol_total=3,
                public_symbol_documented=3,
            ),
        ),
    )


def _container_with_adoption(monkeypatch: pytest.MonkeyPatch) -> BaselineContainerV3:
    monkeypatch.setattr(container_mod, "current_python_tag", lambda: "cp314")
    monkeypatch.setattr(container_mod, "_utc_now_z", lambda: "2026-07-20T00:00:00Z")
    return build_container(_bundle_with_adoption(), _SCOPE_ID)


def _with_opaque_adoption_lane(
    container: BaselineContainerV3,
) -> BaselineContainerV3:
    """The adoption lane as the reader leaves it when it cannot decode it.

    ``lane_payload_is_opaque`` defines the opaque shape as a raw ``dict`` —
    this forgery reproduces exactly that reader state, not a convenient one.
    """

    lane = replace(container.lanes["adoption_counts"], payload={"counts": []})
    return replace(
        container,
        lanes=BaselineLaneIndex(
            rows=tuple(
                (key, lane if key == "adoption_counts" else existing)
                for key, existing in container.lanes.rows
            )
        ),
    )


def test_baseline_snapshot_reads_permilles_from_a_readable_adoption_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = metrics_mod._snapshot(_container_with_adoption(monkeypatch))

    assert snapshot.typing_param_permille == 1000
    assert snapshot.typing_return_permille == 1000
    assert snapshot.docstring_permille == 1000


def test_baseline_snapshot_withholds_permilles_when_adoption_lane_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The baseline half of the same refusal: an opaque or absent lane is not
    an empty one (`B5`, `RP2`).

    Wave 7 taught this half to withhold ``health_score`` over unreadable
    evidence; the permilles beside it kept reading an opaque adoption lane as
    zero observations — a flattering, fabricated measurement.
    """

    opaque = _with_opaque_adoption_lane(_container_with_adoption(monkeypatch))
    snapshot = metrics_mod._snapshot(opaque)

    assert snapshot.typing_param_permille is None
    assert snapshot.typing_return_permille is None
    assert snapshot.docstring_permille is None

    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    without_metrics = build_container(
        build_observation_bundle(
            scan_root=Path("."),
            module_registry=registry,
            collect_metrics=False,
        ),
        _SCOPE_ID,
    )
    missing = metrics_mod._snapshot(without_metrics)

    assert missing.typing_param_permille is None
    assert missing.typing_return_permille is None
    assert missing.docstring_permille is None


def test_diff_withholds_permille_deltas_for_a_refusal_current_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subtraction must not run against an absent half.

    Before this wave the refusal current run read 0‰ against a fully typed
    baseline and every permille delta published -1000: the refusal itself
    became a measured regression (`B8`, `G4`).
    """

    baseline_snapshot = metrics_mod._snapshot(_container_with_adoption(monkeypatch))
    current_snapshot = metrics_mod._current_snapshot(
        _refusal_project_metrics("complete_empty")
    )

    diff = diff_metrics(
        baseline_snapshot=baseline_snapshot,
        current_snapshot=current_snapshot,
        baseline_api_surface=None,
        current_api_surface=None,
    )

    assert diff.typing_param_permille_delta == 0
    assert diff.typing_return_permille_delta == 0
    assert diff.docstring_permille_delta == 0


def test_diff_keeps_real_permille_deltas_for_a_measured_current_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opposite boundary: a real regression on a measured run survives."""

    baseline_snapshot = metrics_mod._snapshot(_container_with_adoption(monkeypatch))
    current_snapshot = metrics_mod._current_snapshot(_project_metrics())

    diff = diff_metrics(
        baseline_snapshot=baseline_snapshot,
        current_snapshot=current_snapshot,
        baseline_api_surface=None,
        current_api_surface=None,
    )

    assert diff.typing_param_permille_delta == -250
    assert diff.typing_return_permille_delta == 0
    assert diff.docstring_permille_delta == -333


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
    assert error.value.status == MetricsBaselineStatus.INCOMPATIBLE_METRICS_CONTRACT


@pytest.mark.parametrize(
    "field_name",
    ["algorithm_revision", "payload_schema", "descriptor_version"],
)
def test_stale_metrics_baseline_presents_as_incompatible_metrics_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
) -> None:
    """A metrics contract bump must never read as a regression in user code.

    39Y item 3 bumps the design-metric lanes' ``algorithm_revision`` because CBO
    and the risk bands changed meaning, so every baseline written before that
    bump is stale by construction. The operator has to be told the contract
    moved -- typed, so surfaces can say "regenerate" instead of presenting
    metric deltas the user's code did not cause.
    """

    baseline = MetricsBaseline(_write_container(tmp_path, monkeypatch))
    baseline.load()

    def _stale_runtime_contract(
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

        def _stale(item: ObservationLaneDescriptor) -> ObservationLaneDescriptor:
            # Named fields rather than ``**{field_name: ...}``: the descriptor
            # carries a Literal-typed lane name and a tuple-typed field, so
            # dynamic kwargs erase exactly the types this contract relies on.
            if field_name == "algorithm_revision":
                return replace(item, algorithm_revision="stale")
            if field_name == "payload_schema":
                return replace(item, payload_schema="stale")
            return replace(item, descriptor_version="stale")

        descriptors = tuple(
            _stale(item) if item.name in _DESIGN_METRIC_LANES else item
            for item in contract.descriptors
        )
        return replace(contract, descriptors=descriptors)

    monkeypatch.setattr(
        "codeclone.baseline.container_trust.build_observation_contract",
        _stale_runtime_contract,
    )

    with pytest.raises(BaselineValidationError) as error:
        baseline.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )

    assert error.value.status == MetricsBaselineStatus.INCOMPATIBLE_METRICS_CONTRACT
    # An untrusted baseline projects no snapshot, so nothing downstream can
    # turn a contract bump into new-finding claims.
    assert baseline.snapshot is None


def test_incompatible_metrics_contract_does_not_swallow_scope_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scope mismatch keeps its own status instead of reading as contract drift."""

    baseline = MetricsBaseline(_write_container(tmp_path, monkeypatch))
    baseline.load()

    with pytest.raises(BaselineValidationError) as scope_error:
        baseline.verify_compatibility(
            runtime_python_tag="cp314",
            baseline_scope_id=UUID("018f4b8e-5a5f-7d35-9c21-000000000000"),
        )
    assert scope_error.value.status == MetricsBaselineStatus.MISMATCH_SCOPE_ID


def test_metrics_baseline_accepts_a_foreign_interpreter_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The harder of the two tag sites, pinned on both of its methods.

    The lane projection merely degraded lanes; this half *raised*, so a metrics
    baseline stamped by another interpreter took the whole run down even when
    every clone lane was comparable. Two methods carried a tag term -- the strict
    ``verify_compatibility`` and, separately, the ``version_checks`` tuple inside
    ``unavailable_lanes``, which the clone twin never had. Both are exercised
    here, because fixing only one leaves a run that passes the gate it asks and
    fails the gate it does not.
    """

    baseline = MetricsBaseline(_write_container(tmp_path, monkeypatch))
    baseline.load()

    baseline.verify_compatibility(
        runtime_python_tag="cp313",
        baseline_scope_id=_SCOPE_ID,
    )
    assert (
        baseline.unavailable_lanes(
            runtime_python_tag="cp313",
            baseline_scope_id=_SCOPE_ID,
        )
        == ()
    )


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

    unresolved = ImportOccurrenceObservation(
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
        line=4,
    )
    with pytest.raises(ValueError, match="not graph-resolvable"):
        metrics_mod._import_dependency(unresolved)

    resolved = ImportOccurrenceObservation(
        source=registry.entries_by_module["pkg.mod"].identity,
        syntax_kind="import",
        level=0,
        requested_module="pkg.other",
        requested_names=(),
        resolution="external",
        candidate_targets=(),
        resolved_target="pkg.other",
        line=9,
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
                (
                    name,
                    replace(
                        lane, payload=_encode_api_surface_lane(api_payload.symbols)
                    ),
                )
                if name == "api_surface"
                else (name, lane)
                for name, lane in container.lanes.rows
            ),
        ),
    )
    api_snapshot = metrics_mod._api_surface_snapshot(api_container)
    assert api_snapshot is not None
    assert api_snapshot.modules == ()


def test_the_bridge_drops_a_stored_private_module_from_the_api_snapshot() -> None:
    """A baseline written while the privacy guard was inert still holds them.

    ``include_private_modules=False`` was inert for any module declaring
    ``__all__``, so a container published before the fix carries a row per
    public-named symbol of every private module. A run no longer collects any
    of them, so handing them over unchanged would report each as removed from
    the public API on an untouched tree. The bridge drops them, and it must do
    so unconditionally: that direction can only ever turn a stored symbol into
    ``added``, never into ``removed``.

    Both directions are here from one payload, so an over-eager drop fails as
    loudly as an absent one.
    """

    container = build_container(_bundle(), _SCOPE_ID)
    payload = ApiSurfaceObservationPayload(
        symbols=tuple(
            ApiSymbolObservation(
                owner=ResolvedSourceIdentity(
                    file=FileIdentity(path=path),
                    python_module=PythonModuleIdentity(
                        module=module,
                        package=module.rsplit(".", 1)[0],
                        is_package=False,
                        mount_path=path,
                        origin="import_mount",
                        node_kind="module_file",
                    ),
                ),
                symbol="public_name",
                symbol_kind="constant",
                visibility="all",
                parameters=(),
                returns_digest=None,
            )
            for module, path in (
                ("pkg._internal", "pkg/_internal.py"),
                ("pkg.public", "pkg/public.py"),
            )
        )
    )
    api_container = replace(
        container,
        lanes=replace(
            container.lanes,
            rows=tuple(
                (name, replace(lane, payload=_encode_api_surface_lane(payload.symbols)))
                if name == "api_surface"
                else (name, lane)
                for name, lane in container.lanes.rows
            ),
        ),
    )
    snapshot = metrics_mod._api_surface_snapshot(api_container)
    assert snapshot is not None
    assert [module.module for module in snapshot.modules] == ["pkg.public"]


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

    # With every lane compatible, a stored tag that matches no interpreter at all
    # is still not a refusal: the tag is provenance, and this method's remaining
    # whole-container term is the schema version.
    baseline.python_tag = "future"
    monkeypatch.setattr(
        container_trust_mod,
        "evaluate_lane_trust",
        lambda *_args, **_kwargs: TrustVector(root_verified=True, lanes=()),
    )
    baseline.verify_compatibility(
        runtime_python_tag="cp314",
        baseline_scope_id=_SCOPE_ID,
    )


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
            "start_line": 1,
            "end_line": 4,
        },
        {
            "filepath": "pkg/mod.py",
            "qualname": "pkg.mod:deep",
            "cyclomatic_complexity": 7,
            "nesting_depth": 2,
            "start_line": 6,
            "end_line": 14,
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


def test_consumers_receive_decoded_rows_never_columns() -> None:
    """The decode boundary is invisible: consumers still get typed row models."""

    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    units = (
        {
            "filepath": "pkg/mod.py",
            "qualname": "pkg.mod:run",
            "cyclomatic_complexity": 4,
            "nesting_depth": 2,
            "start_line": 3,
            "end_line": 9,
        },
    )
    class_metrics = (_class_metric("pkg.mod:Thing", cbo=3, lcom4=2, methods=1),)
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        units=units,
        class_metrics=class_metrics,
    )
    container = build_container(bundle, _SCOPE_ID)

    # The stored lane is columnar; what the consumer reads is not.
    assert isinstance(container.lanes["risk_observations"].payload, RiskColumnarPayload)
    risk_payload = metrics_mod._lane_payload(container, "risk_observations")
    assert isinstance(risk_payload, RiskObservationPayload)
    assert sorted(risk_payload.observations, key=repr) == sorted(
        bundle.structural.risk_observations, key=repr
    )

    rows, population = metrics_mod._integer_lane(container, "risk_observations")
    assert population == len(units)
    assert ("run", "cyclomatic_complexity", 4) in rows
    assert ("run", "nesting_depth", 2) in rows

    class_rows, class_population = metrics_mod._integer_lane(
        container, "coupling_cohesion_observations"
    )
    assert class_population == len(class_metrics)
    assert ("Thing", "cbo", 3) in class_rows


def test_metrics_baseline_schema_version_is_provenance_not_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stamp is reported, never enforced — pinned so the comment stays true.

    ``METRICS_BASELINE_SCHEMA_VERSION`` reads like a compatibility gate, and a
    comment once claimed 1.2 values "must not be diffed" against current ones.
    Nothing branches on it: comparability is decided by the per-lane
    ``algorithm_revision`` / ``payload_schema`` pair and then by
    ``BASELINE_SCHEMA_VERSION``. Wiring a second gate for the same decision
    would create two authorities for one question, so the constant stays a
    provenance stamp and this test keeps that statement honest — if someone
    later makes it authoritative, the first assertion fails and the comment,
    the consumers and this test have to be revisited together.
    """

    baseline = MetricsBaseline(_write_container(tmp_path, monkeypatch))
    baseline.load()

    # Moving the stamp alone changes no verdict: the artifact stays compatible.
    monkeypatch.setattr(
        "codeclone.baseline.metrics_baseline.METRICS_BASELINE_SCHEMA_VERSION",
        "9.9",
        raising=False,
    )
    # The fixture container is written with a pinned ``cp314`` tag, so the
    # runtime tag is held to the same value here, as every sibling test does.
    # Reading it from the live interpreter instead made this test pass only on
    # 3.14 and fail every other leg of the CI matrix on a lane-compatibility
    # mismatch that has nothing to do with the schema stamp under test.
    baseline.verify_compatibility(
        runtime_python_tag="cp314",
        baseline_scope_id=_SCOPE_ID,
    )

    # The constant reaches exactly one surface, and it is a report line.
    assert METRICS_BASELINE_SCHEMA_VERSION == "1.3"


def _high_risk_bundle() -> ObservationBundle:
    """A bundle whose design-metric lanes actually carry high-risk entities.

    Every other bundle in this module leaves those lanes empty, which is the
    reason the round trip below went unguarded for so long: an empty baseline
    set matches an empty current set no matter how the two are spelled.
    """

    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        units=(
            {
                "qualname": "pkg.mod:hot",
                "filepath": "pkg/mod.py",
                "cyclomatic_complexity": COMPLEXITY_RISK_MEDIUM_MAX + 5,
                "nesting_depth": 3,
                "start_line": 12,
                "end_line": 40,
            },
        ),
        class_metrics=(
            _class_metric(
                "pkg.mod:Service",
                cbo=COUPLING_RISK_MEDIUM_MAX + 3,
                lcom4=1,
                methods=2,
            ),
        ),
    )


def test_published_high_risk_entities_read_as_known_on_the_next_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entity that is in the baseline must not be reported as new.

    The lane splits the producer-glued ``module:qualname`` into a source
    identity and a bare qualname, so a reader that compares only the bare half
    can never match the glued identity a run carries. Every known high-risk
    entity would then be reported as new on every run, for as long as the sets
    stay non-empty -- the novelty signal inverted into noise.

    The second entity in each set is genuinely absent from the baseline and
    pins the other direction: reconciling the two spellings must not collapse
    into matching everything.
    """

    baseline = _published_baseline(tmp_path, monkeypatch, _high_risk_bundle())

    diff = baseline.diff(
        replace(
            _project_metrics(),
            high_risk_functions=("pkg.mod:hot", "pkg.mod:fresh"),
            high_risk_classes=("pkg.mod:Service", "pkg.mod:Fresh"),
        )
    )

    assert diff.new_high_risk_functions == ("pkg.mod:fresh",)
    assert diff.new_high_coupling_classes == ("pkg.mod:Fresh",)


def test_baseline_reader_keeps_overload_declarations_distinct() -> None:
    """F1 K2: the baseline reader keys risk rows with the declaration site.

    Distinguishing input — the ruling's own defect shape: two declarations
    of one qualname with different start_lines and EQUAL measures.  The K1
    wire carries all four facts (2 declarations x 2 dimensions); the
    reader's row key must keep them distinct all the way to the comparison,
    where a site-blind key made the pairs byte-identical (measured red:
    ``len(set(rows)) == 2``).  The glued identity SPELLING deliberately
    stays the same — the report vocabulary does not move.
    """

    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    container = build_container(
        build_observation_bundle(
            scan_root=Path("."),
            module_registry=registry,
            units=(
                {
                    "filepath": "pkg/mod.py",
                    "qualname": "pkg.mod:parse_args",
                    "cyclomatic_complexity": 7,
                    "nesting_depth": 2,
                    "start_line": 10,
                    "end_line": 20,
                },
                {
                    "filepath": "pkg/mod.py",
                    "qualname": "pkg.mod:parse_args",
                    "cyclomatic_complexity": 7,
                    "nesting_depth": 2,
                    "start_line": 40,
                    "end_line": 60,
                },
            ),
        ),
        _SCOPE_ID,
    )

    rows = metrics_mod._risk_entity_identity_rows(container)
    assert len(rows) == 4
    # Both declarations reach the comparison separately: every row is a
    # distinct fact under set(), keyed by its declaration site.
    assert len(set(rows)) == 4
    assert {row[0] for row in rows} == {"pkg.mod:parse_args"}
    assert {row[3] for row in rows} == {10, 40}
    # The value reader beside it still sees all four surviving rows.
    value_rows, population = metrics_mod._integer_lane(container, "risk_observations")
    assert population == 2
    assert len(value_rows) == 4


def _published_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bundle: ObservationBundle,
) -> MetricsBaseline:
    """Publish one bundle as a container on disk and load it back.

    Stated once: every suite below that needs a baseline it can read has the
    same five steps, and three copies of them were a block clone.
    """

    monkeypatch.setattr(container_mod, "current_python_tag", lambda: "cp314")
    monkeypatch.setattr(container_mod, "_utc_now_z", lambda: "2026-07-20T00:00:00Z")
    path = tmp_path / "baseline.json"
    path.write_bytes(canonical_container_bytes(build_container(bundle, _SCOPE_ID)))
    baseline = MetricsBaseline(path)
    baseline.load()
    return baseline


# ---------------------------------------------------------------------------
# F5: the baseline reader's identity join (ruling 2026-08-26).
# ---------------------------------------------------------------------------

#: The producer's own public surface for the fixture module.  Stated once so
#: the stored half and the run half of the comparison below cannot drift into
#: two different fixtures — the drift would hide the very defect this pins.
_API_MODULES = (
    ModuleApiSurface(
        module="pkg.mod",
        filepath="pkg/mod.py",
        symbols=(
            PublicSymbol(
                qualname="pkg.mod:run",
                kind="function",
                start_line=1,
                end_line=2,
                params=(
                    ApiParamSpec(
                        name="left",
                        kind="pos_or_kw",
                        has_default=False,
                        annotation_hash="1" * 64,
                    ),
                ),
                returns_hash="2" * 64,
                exported_via="all",
            ),
        ),
    ),
)


def _api_bundle(
    api_modules: tuple[ModuleApiSurface, ...] = _API_MODULES,
    inventory_modules: tuple[str, ...] = (),
) -> ObservationBundle:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        inventory_modules=inventory_modules,
    )[1]
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        api_modules=api_modules,
    )


def _stored_api_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    api_modules: tuple[ModuleApiSurface, ...] = _API_MODULES,
    inventory_modules: tuple[str, ...] = (),
) -> ApiSurfaceSnapshot:
    """Publish the fixture bundle, read it back through the public loader."""

    baseline = _published_baseline(
        tmp_path,
        monkeypatch,
        _api_bundle(api_modules, inventory_modules),
    )
    stored = baseline.api_surface_snapshot
    assert stored is not None
    return stored


def test_stored_api_surface_is_named_the_way_the_producer_names_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F5, half one: the reader rejoins the producer's identity spelling.

    The lane stores the source identity apart from the BARE symbol, and the
    report vocabulary is the glued ``module:qualname``, so the join lives in
    the reader.  This measures the spelling alone; the consequence of losing
    it is measured separately below, so neither pin can mask the other.
    """

    stored = _stored_api_snapshot(tmp_path, monkeypatch)
    assert [
        symbol.qualname for module in stored.modules for symbol in module.symbols
    ] == ["pkg.mod:run"]


def test_stored_api_surface_compares_clean_against_the_run_that_named_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F5, half two: the consequence, driven through the real comparison.

    ``compare_api_surfaces`` keys on the producer's glued qualname, so a
    reader that hands it the bare half compares two vocabularies and reports
    every symbol the baseline already knows as removed AND added on an
    unchanged repository.  This pin never inspects the spelling — it asserts
    only the comparison outcome, both sides of it, so it dies on the harm
    rather than on the spelling that causes it.
    """

    stored = _stored_api_snapshot(tmp_path, monkeypatch)
    # One assertion over BOTH outcome fields: written as two statements the
    # first failure would hide whether the second still had teeth.
    assert compare_api_surfaces(
        baseline=stored,
        current=ApiSurfaceSnapshot(modules=_API_MODULES),
        strict_types=True,
    ) == ((), ())


def test_stored_api_surface_drops_a_legacy_test_track_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A baseline published before the track split must degrade, not scream.

    Every ``tests.*`` symbol an old container carries is a symbol the run can
    no longer produce, so a reader that hands them to ``compare_api_surfaces``
    reports each of them as removed from the public API surface on an
    unchanged repository. The reader drops them instead, and the run's own
    product symbol still survives the same decode — measured together so a
    filter that swallowed everything could not pass.
    """

    legacy = ModuleApiSurface(
        module="tests.test_thing",
        filepath="tests/test_thing.py",
        symbols=(
            PublicSymbol(
                qualname="tests.test_thing:test_thing",
                kind="function",
                start_line=1,
                end_line=2,
                params=(),
                returns_hash="3" * 64,
                exported_via="name",
            ),
        ),
    )
    stored = _stored_api_snapshot(
        tmp_path,
        monkeypatch,
        api_modules=(*_API_MODULES, legacy),
        inventory_modules=("tests.test_thing",),
    )
    assert [module.module for module in stored.modules] == ["pkg.mod"]
    assert compare_api_surfaces(
        baseline=stored,
        current=ApiSurfaceSnapshot(modules=_API_MODULES),
        strict_types=True,
    ) == ((), ())

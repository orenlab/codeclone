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

import codeclone.baseline.container as container_mod
import codeclone.baseline.container_trust as container_trust_mod
from codeclone.baseline import (
    Baseline,
    BaselineStatus,
    coerce_baseline_status,
)
from codeclone.baseline.container import build_container, read_container_v3
from codeclone.baseline.container_digest import canonical_container_bytes
from codeclone.contracts.errors import BaselineValidationError
from codeclone.models import (
    BaselineLaneIndex,
    ContainerInspectionResult,
    ContainerReadSuccess,
    DigestObject,
    IntegerObservationPayload,
    LaneTrust,
    ObservationBundle,
    ObservationContract,
    TrustVector,
)
from codeclone.observations.contracts import build_observation_contract
from codeclone.observations.projection import build_observation_bundle
from tests._ast_metrics_helpers import module_registry_context

_SCOPE_ID = UUID("018f4b8e-5a5f-7d35-9c21-4af5d18df420")
_FUNCTION_ID = f"{'a' * 64}|0-19"
_BLOCK_ID = "|".join(("b" * 64,) * 4)


def _bundle() -> ObservationBundle:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        function_clone_keys=(_FUNCTION_ID,),
        block_clone_keys=(_BLOCK_ID,),
    )


def _write_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    monkeypatch.setattr(container_mod, "current_python_tag", lambda: "cp314")
    monkeypatch.setattr(
        container_mod,
        "_utc_now_z",
        lambda: "2026-07-20T00:00:00Z",
    )
    path = tmp_path / "baseline.json"
    path.write_bytes(canonical_container_bytes(build_container(_bundle(), _SCOPE_ID)))
    return path


def _assert_load_status(path: Path, expected: BaselineStatus) -> None:
    with pytest.raises(BaselineValidationError) as error:
        Baseline(path).load()
    assert error.value.status == expected


def test_baseline_loads_native_clone_lanes_and_verifies_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_container(tmp_path, monkeypatch)
    baseline = Baseline(path)
    baseline.load()

    assert baseline.functions == {_FUNCTION_ID}
    assert baseline.blocks == {_BLOCK_ID}
    assert baseline.schema_version == "3.0"
    assert baseline.fingerprint_version == "2"
    assert baseline.python_tag == "cp314"
    baseline.verify_compatibility(
        current_python_tag="cp314",
        baseline_scope_id=_SCOPE_ID,
    )


def test_baseline_diff_projects_known_and_new_clone_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = Baseline(_write_container(tmp_path, monkeypatch))
    baseline.load()
    new_function = f"{'c' * 64}|20-39"
    new_block = "|".join(("d" * 64,) * 4)

    functions, blocks = baseline.diff(
        {_FUNCTION_ID: [], new_function: []},
        {_BLOCK_ID: [], new_block: []},
    )

    assert functions == {new_function}
    assert blocks == {new_block}


def test_baseline_missing_and_invalid_inputs_are_typed(tmp_path: Path) -> None:
    missing = Baseline(tmp_path / "missing.json")
    missing.load()
    with pytest.raises(BaselineValidationError) as missing_error:
        missing.verify_compatibility(
            current_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert missing_error.value.status == BaselineStatus.MISSING_FIELDS

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("not-json", "utf-8")
    with pytest.raises(BaselineValidationError) as invalid_error:
        Baseline(invalid_path).load()
    assert invalid_error.value.status == BaselineStatus.INVALID_JSON

    oversize_path = tmp_path / "oversize.json"
    oversize_path.write_text("{}", "utf-8")
    with pytest.raises(BaselineValidationError) as oversize_error:
        Baseline(oversize_path).load(max_size_bytes=1)
    assert oversize_error.value.status == BaselineStatus.TOO_LARGE


def test_baseline_scope_and_runtime_mismatches_are_untrusted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = Baseline(_write_container(tmp_path, monkeypatch))
    baseline.load()

    with pytest.raises(BaselineValidationError) as scope_error:
        baseline.verify_compatibility(
            current_python_tag="cp314",
            baseline_scope_id=UUID("019f7fa1-8866-7242-b0bf-0ff282cafbcb"),
        )
    assert scope_error.value.status == BaselineStatus.MISMATCH_SCOPE_ID

    with pytest.raises(BaselineValidationError) as python_error:
        baseline.verify_compatibility(
            current_python_tag="cp313",
            baseline_scope_id=_SCOPE_ID,
        )
    assert python_error.value.status == BaselineStatus.MISMATCH_PYTHON_VERSION


def test_baseline_schema_and_fingerprint_guards_remain_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = Baseline(_write_container(tmp_path, monkeypatch))
    baseline.load()
    baseline.schema_version = "future"
    with pytest.raises(BaselineValidationError) as schema_error:
        baseline.verify_compatibility(
            current_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert schema_error.value.status == BaselineStatus.MISMATCH_SCHEMA_VERSION

    baseline.schema_version = "3.0"
    baseline.fingerprint_version = "future"
    with pytest.raises(BaselineValidationError) as fingerprint_error:
        baseline.verify_compatibility(
            current_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert fingerprint_error.value.status == BaselineStatus.MISMATCH_FINGERPRINT_VERSION


def test_baseline_compares_persisted_lane_descriptors_to_current_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = Baseline(_write_container(tmp_path, monkeypatch))
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
            if item.name == "clones.functions"
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
            current_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert error.value.status == BaselineStatus.MISMATCH_SCHEMA_VERSION


def test_baseline_unloaded_and_inspection_only_states_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unloaded = Baseline(tmp_path / "missing.json")
    with pytest.raises(BaselineValidationError) as missing:
        unloaded.verify_compatibility(
            current_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert missing.value.status == BaselineStatus.MISSING_FIELDS

    inspection = ContainerInspectionResult(
        root_digest=DigestObject(
            domain="codeclone.baseline.root.v1",
            algorithm="sha256",
            value="a" * 64,
        ),
        unknown_optional_lanes=("future",),
    )
    monkeypatch.setattr(
        "codeclone.baseline.clone_baseline.read_container_v3",
        lambda *_args, **_kwargs: inspection,
    )
    path = tmp_path / "inspection.json"
    path.write_text("{}", "utf-8")
    _assert_load_status(path, BaselineStatus.INVALID_TYPE)


def test_baseline_rejects_wrong_clone_payload_and_unverified_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = build_container(_bundle(), _SCOPE_ID)
    function_lane = container.lanes["clones.functions"]
    wrong_function_lane = replace(
        function_lane,
        payload=IntegerObservationPayload(observations=(), entity_population=0),
    )
    wrong_lanes = BaselineLaneIndex(
        rows=tuple(
            (name, wrong_function_lane if name == "clones.functions" else lane)
            for name, lane in container.lanes.rows
        )
    )
    wrong_container = replace(container, lanes=wrong_lanes)
    monkeypatch.setattr(
        "codeclone.baseline.clone_baseline.read_container_v3",
        lambda *_args, **_kwargs: ContainerReadSuccess(container=wrong_container),
    )
    path = tmp_path / "wrong.json"
    path.write_text("{}", "utf-8")
    _assert_load_status(path, BaselineStatus.INVALID_TYPE)

    monkeypatch.setattr(
        "codeclone.baseline.clone_baseline.read_container_v3",
        read_container_v3,
    )
    baseline = Baseline(_write_container(tmp_path, monkeypatch))
    baseline.load()
    monkeypatch.setattr(
        container_trust_mod,
        "evaluate_lane_trust",
        lambda *_args, **_kwargs: TrustVector(root_verified=False, lanes=()),
    )
    with pytest.raises(BaselineValidationError) as root_error:
        baseline.verify_compatibility(
            current_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert root_error.value.status == BaselineStatus.INTEGRITY_FAILED


def test_baseline_required_contract_and_status_fallbacks_are_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = Baseline(_write_container(tmp_path, monkeypatch))
    baseline.load()
    monkeypatch.setattr(
        container_trust_mod,
        "evaluate_lane_trust",
        lambda *_args, **_kwargs: TrustVector(
            root_verified=True,
            lanes=(
                LaneTrust(
                    name="clones.functions",
                    status="unavailable",
                    reason="required_contract",
                ),
            ),
        ),
    )
    with pytest.raises(BaselineValidationError) as contract_error:
        baseline.verify_compatibility(
            current_python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
        )
    assert contract_error.value.status == BaselineStatus.MISMATCH_FINGERPRINT_VERSION
    assert (
        container_trust_mod.map_container_read_failure(
            "future",
            too_large=BaselineStatus.TOO_LARGE,
            invalid_json=BaselineStatus.INVALID_JSON,
            integrity_failed=BaselineStatus.INTEGRITY_FAILED,
            schema_mismatch=BaselineStatus.MISMATCH_SCHEMA_VERSION,
            invalid_type=BaselineStatus.INVALID_TYPE,
        )
        is BaselineStatus.INVALID_TYPE
    )
    assert coerce_baseline_status("future") is BaselineStatus.INVALID_TYPE
    assert coerce_baseline_status(None) is BaselineStatus.INVALID_TYPE

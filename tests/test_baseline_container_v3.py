# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from uuid import UUID

import orjson
import pytest

import codeclone.baseline.container as container_mod
from codeclone.baseline.container import (
    build_container,
    read_container_v3,
    read_container_v3_bytes,
)
from codeclone.baseline.container_digest import (
    canonical_container_bytes,
    compute_analysis_scope_digest,
    compute_input_root_digest,
    compute_lane_digest,
    compute_lane_digest_components,
    compute_root_digest,
)
from codeclone.baseline.container_trust import evaluate_lane_trust
from codeclone.baseline.lanes import (
    BaselineLaneValidationError,
    decode_module_identity_lane,
    descriptor_from_input,
    lane_from_input,
    lane_payload_is_opaque,
    payload_from_input,
    validate_descriptor,
)
from codeclone.contracts import BASELINE_FINGERPRINT_VERSION
from codeclone.models import (
    BaselineContainerV3,
    BaselineContainerV3Input,
    BaselineLane,
    BaselineLaneIndex,
    BaselineLaneInput,
    BaselinePublishLock,
    CloneObservationPayload,
    ContainerInspectionResult,
    ContainerReadFailure,
    ContainerReadSuccess,
    ContractIndex,
    DigestObject,
    EpochTransitionEvidence,
    EpochTransitionEvidenceInput,
    ModuleIdentityColumnarPayload,
    ObservabilityConfig,
    ObservationBundle,
    ObservationContractInput,
    ObservationLaneDescriptorInput,
    ObservationLaneName,
    RuntimeContracts,
    StructuralObservationFacts,
)
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.observations.lanes import build_observation_lanes
from codeclone.observations.projection import build_observation_bundle
from codeclone.report.gates.evaluator import (
    GateState,
    MetricGateConfig,
    evaluate_gate_state,
)
from tests._ast_metrics_helpers import module_registry_context

_SCOPE_ID = UUID("018f4b8e-5a5f-7d35-9c21-4af5d18df420")
_FIXTURES = Path(__file__).parent / "fixtures" / "baseline_v3"
_DUPLICATE_KEYS_FIXTURE = _FIXTURES / "duplicate_keys.txt"
_INVALID_JSON_FIXTURE = _FIXTURES / "invalid_json.txt"
_LANE_NAMES: tuple[ObservationLaneName, ...] = (
    "adoption_counts",
    "api_surface",
    "clones.blocks",
    "clones.functions",
    "coupling_cohesion_observations",
    "dead_code",
    "dependencies",
    "module_identity",
    "risk_observations",
    "semantic_authority",
)


def _bundle() -> ObservationBundle:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
        known_internal_modules=("pkg.hidden",),
    )[1]
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        function_clone_keys=(f"{'a' * 64}|0-19",),
        block_clone_keys=("|".join(("b" * 64,) * 4),),
    )


def _container(monkeypatch: pytest.MonkeyPatch) -> BaselineContainerV3:
    monkeypatch.setattr(container_mod, "current_python_tag", lambda: "cp314")
    monkeypatch.setattr(
        container_mod,
        "_utc_now_z",
        lambda: "2026-07-20T00:00:00Z",
    )
    return build_container(_bundle(), _SCOPE_ID)


def _object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise AssertionError("expected a string-keyed JSON object")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise AssertionError("expected a JSON array")
    return list(value)


def _object_str(value: object) -> str:
    if not isinstance(value, str):
        raise AssertionError("expected a JSON string")
    return value


def _wire(value: object) -> object:
    result: object = orjson.loads(orjson.dumps(value, option=orjson.OPT_SORT_KEYS))
    return result


def _document(container: BaselineContainerV3) -> dict[str, object]:
    return _object_dict(orjson.loads(canonical_container_bytes(container)))


def _replace_lane(
    container: BaselineContainerV3,
    name: str,
    lane: BaselineLane,
) -> BaselineContainerV3:
    rows = tuple(
        (key, lane if key == name else existing)
        for key, existing in container.lanes.rows
    )
    return replace(container, lanes=BaselineLaneIndex(rows=rows))


def _different_digest(value: DigestObject, fill: str) -> DigestObject:
    return replace(value, value=fill * 64)


def _authenticated_document(document: dict[str, object]) -> bytes:
    parsed = BaselineContainerV3Input.model_validate_json(orjson.dumps(document))
    meta = _object_dict(document["meta"])
    meta["root_digest"] = _wire(compute_input_root_digest(parsed))
    document["meta"] = meta
    return orjson.dumps(document, option=orjson.OPT_SORT_KEYS)


def _rehash_lane(document: dict[str, object], name: str) -> None:
    lanes = _object_dict(document["lanes"])
    lane = _object_dict(lanes[name])
    required = lane["required"]
    if not isinstance(required, bool):
        raise AssertionError("lane required flag must be boolean")
    descriptor = ObservationLaneDescriptorInput.model_validate_json(
        orjson.dumps(lane["descriptor"])
    )
    lane["digest"] = _wire(
        compute_lane_digest_components(
            name=name,
            required=required,
            descriptor=descriptor,
            payload=lane["payload"],
        )
    )
    lanes[name] = lane
    document["lanes"] = lanes


def _write_and_read(
    tmp_path: Path,
    *,
    name: str,
    document: dict[str, object],
    authenticate: bool = True,
) -> object:
    target = tmp_path / name
    raw = (
        _authenticated_document(document)
        if authenticate
        else orjson.dumps(document, option=orjson.OPT_SORT_KEYS)
    )
    target.write_bytes(raw)
    return read_container_v3(target, limit_bytes=target.stat().st_size)


def _set_lane_fields(
    document: dict[str, object],
    name: str,
    fields: dict[str, object],
) -> None:
    lanes = _object_dict(document["lanes"])
    lane = _object_dict(lanes[name])
    lane.update(fields)
    lanes[name] = lane
    document["lanes"] = lanes


def _set_nested_fields(
    document: dict[str, object],
    outer_name: str,
    inner_name: str,
    fields: dict[str, object],
) -> None:
    outer = _object_dict(document[outer_name])
    inner = _object_dict(outer[inner_name])
    inner.update(fields)
    outer[inner_name] = inner
    document[outer_name] = outer


def _set_lane_nested_fields(
    document: dict[str, object],
    lane_name: str,
    inner_name: str,
    fields: dict[str, object],
) -> None:
    lanes = _object_dict(document["lanes"])
    lane = _object_dict(lanes[lane_name])
    inner = _object_dict(lane[inner_name])
    inner.update(fields)
    lane[inner_name] = inner
    lanes[lane_name] = lane
    document["lanes"] = lanes


def _set_object_field(
    document: dict[str, object],
    object_name: str,
    field_name: str,
    value: object,
) -> None:
    item = _object_dict(document[object_name])
    item[field_name] = value
    document[object_name] = item


def _remove_lane(document: dict[str, object], name: str) -> None:
    lanes = _object_dict(document["lanes"])
    del lanes[name]
    document["lanes"] = lanes


def _stat_with_size(result: os.stat_result, size: int) -> os.stat_result:
    """Return ``result`` with only its size replaced.

    Simulations here change what a stat REPORTS, never what the path is, so
    every other field - the mode above all - is carried through unchanged.
    """

    fields = tuple(result)
    return os.stat_result((*fields[:6], size, *fields[7:10]))


def _assert_read_failure(value: object, reason: str) -> ContainerReadFailure:
    assert isinstance(value, ContainerReadFailure)
    assert value.reason == reason
    return value


def _unknown_lane_document(
    container: BaselineContainerV3,
    *,
    required: bool,
) -> bytes:
    document = _document(container)
    future_name = "future.optional"
    descriptor = ObservationLaneDescriptorInput(
        name=future_name,
        descriptor_version="1",
        payload_schema="1",
        algorithm_revision="1",
        canonicalization_version="1",
        required_contracts=(),
    )
    payload: dict[str, object] = {"items": []}
    digest = compute_lane_digest_components(
        name=future_name,
        required=required,
        descriptor=descriptor,
        payload=payload,
    )
    lanes = _object_dict(document["lanes"])
    lanes[future_name] = {
        "required": required,
        "descriptor": descriptor.model_dump(mode="json"),
        "observation_digest": _wire(container.source.observation_digest),
        "digest": _wire(digest),
        "payload": payload,
    }
    document["lanes"] = lanes
    contract = _object_dict(document["observation_contract"])
    enabled = _object_list(contract["enabled_lanes"])
    enabled.append(future_name)
    contract["enabled_lanes"] = sorted(_object_str(item) for item in enabled)
    descriptors = _object_list(contract["descriptors"])
    descriptors.append(descriptor.model_dump(mode="json"))
    descriptors.sort(key=lambda item: _object_str(_object_dict(item)["name"]))
    contract["descriptors"] = descriptors
    document["observation_contract"] = contract
    return _authenticated_document(document)


def test_build_container_has_native_digest_tree_and_golden_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(monkeypatch)
    module_lane = container.lanes["module_identity"]
    assert isinstance(module_lane.payload, ModuleIdentityColumnarPayload)

    assert module_lane.required
    assert container.source.module_identity_manifest_digest is (
        module_lane.payload.manifest_digest
    )
    assert container.source.module_registry_digest is (
        module_lane.payload.registry_digest
    )
    assert compute_root_digest(container) == container.meta.root_digest
    assert all(
        compute_lane_digest(lane) == lane.digest for _name, lane in container.lanes.rows
    )

    raw = canonical_container_bytes(container)
    parsed = BaselineContainerV3Input.model_validate_json(raw)
    original_lane = container.lanes["adoption_counts"]
    parsed_lane = parsed.lanes["adoption_counts"]
    assert (
        compute_lane_digest_components(
            name="adoption_counts",
            required=parsed_lane.required,
            descriptor=parsed_lane.descriptor,
            payload=parsed_lane.payload,
        )
        == original_lane.digest
    )
    expected = _object_dict(
        orjson.loads((_FIXTURES / "expected_digests.json").read_bytes())
    )
    assert container.meta.root_digest.value == expected["root"]
    assert b"payload_sha256" not in raw
    assert b'"trust"' not in raw
    assert b"legacy_v2" not in raw


@pytest.mark.parametrize("lane_name", _LANE_NAMES)
def test_lane_digest_matches_golden(
    monkeypatch: pytest.MonkeyPatch,
    lane_name: ObservationLaneName,
) -> None:
    container = _container(monkeypatch)
    actual_lanes = {name: lane.digest.value for name, lane in container.lanes.rows}
    expected = _object_dict(
        orjson.loads((_FIXTURES / "expected_digests.json").read_bytes())
    )
    expected_lanes = _object_dict(expected["lanes"])

    assert actual_lanes.get(lane_name) == expected_lanes.get(lane_name)


def test_container_is_hash_seed_and_process_deterministic() -> None:
    script = """
import codeclone.baseline.container as container_mod
from codeclone.baseline.container import build_container
from codeclone.baseline.container_digest import canonical_container_bytes
from tests.test_baseline_container_v3 import _SCOPE_ID, _bundle

container_mod.current_python_tag = lambda: "cp314"
container_mod._utc_now_z = lambda: "2026-07-20T00:00:00Z"
print(canonical_container_bytes(build_container(_bundle(), _SCOPE_ID)).hex())
"""
    outputs: list[str] = []
    root = Path(__file__).resolve().parents[1]
    for seed in ("1", "997"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            (sys.executable, "-c", script),
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(completed.stdout)

    assert outputs[0] == outputs[1]


def test_root_excludes_presentation_and_binds_contract_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(monkeypatch)
    presentation = replace(
        container,
        meta=replace(
            container.meta,
            generator=replace(container.meta.generator, version="999.0"),
            created_at="2099-01-01T00:00:00Z",
            project_label="renamed",
        ),
    )
    assert compute_root_digest(presentation) == container.meta.root_digest

    changed_source = replace(
        container,
        source=replace(
            container.source,
            observation_digest=DigestObject(
                domain="codeclone.source-observations.v1",
                algorithm="sha256",
                value="f" * 64,
            ),
        ),
    )
    changed_transition = replace(
        container,
        transition=EpochTransitionEvidence(
            kind="baseline_epoch_transition",
            from_schema="2.1",
            from_fingerprint="2",
            to_schema="3.0",
            to_fingerprint="2",
            imported_lanes=(),
            regenerated_lanes=container.observation_contract.enabled_lanes,
            source_legacy_digest=DigestObject(
                domain="codeclone.baseline.legacy-evidence.v1",
                algorithm="sha256",
                value="9" * 64,
            ),
        ),
    )
    assert compute_root_digest(changed_source) != container.meta.root_digest
    assert compute_root_digest(changed_transition) != container.meta.root_digest

    changed_contracts = replace(
        container,
        contracts=replace(
            container.contracts,
            rows=tuple(sorted((*container.contracts.rows, ("FUTURE_CONTRACT", "1")))),
        ),
    )
    assert compute_root_digest(changed_contracts) != container.meta.root_digest

    document = _document(container)
    document["format"] = "future-baseline"
    parsed = BaselineContainerV3Input.model_validate_json(orjson.dumps(document))
    assert compute_input_root_digest(parsed) != container.meta.root_digest


def test_builder_cross_field_consistency_rejects_divergent_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(monkeypatch)
    module_lane = container.lanes["module_identity"]
    clone_lane = container.lanes["clones.functions"]

    wrong_payload_lane = replace(module_lane, payload=clone_lane.payload)
    wrong_payload = _replace_lane(container, "module_identity", wrong_payload_lane)

    wrong_manifest = replace(
        container,
        source=replace(
            container.source,
            module_identity_manifest_digest=_different_digest(
                container.source.module_identity_manifest_digest,
                "1",
            ),
        ),
    )
    wrong_registry = replace(
        container,
        source=replace(
            container.source,
            module_registry_digest=_different_digest(
                container.source.module_registry_digest,
                "2",
            ),
        ),
    )
    wrong_scope = replace(
        container,
        source=replace(
            container.source,
            analysis_scope_digest=_different_digest(
                container.source.analysis_scope_digest,
                "3",
            ),
        ),
    )
    wrong_observation_lane = replace(
        clone_lane,
        observation_digest=_different_digest(clone_lane.observation_digest, "4"),
    )
    wrong_observation = _replace_lane(
        container,
        "clones.functions",
        wrong_observation_lane,
    )
    changed_descriptor = replace(
        clone_lane.descriptor,
        algorithm_revision="future",
    )
    wrong_contract = replace(
        container.observation_contract,
        descriptors=tuple(
            changed_descriptor if item.name == "clones.functions" else item
            for item in container.observation_contract.descriptors
        ),
    )
    wrong_descriptors = replace(container, observation_contract=wrong_contract)
    wrong_contract_index = replace(
        container,
        contracts=replace(
            container.contracts,
            rows=tuple(
                (key, "future") if key == "BASELINE_FINGERPRINT_VERSION" else row
                for row in container.contracts.rows
                for key in (row[0],)
            ),
        ),
    )

    for candidate in (
        wrong_payload,
        wrong_manifest,
        wrong_registry,
        wrong_scope,
        wrong_observation,
        wrong_descriptors,
        wrong_contract_index,
    ):
        with pytest.raises(ValueError):
            container_mod._validate_container_consistency(candidate)


def test_builder_rejects_scope_and_contract_conflicts_and_has_dev_version_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def package_missing(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(
        container_mod,
        "version",
        package_missing,
    )
    assert container_mod._package_version() == "dev"
    assert container_mod._utc_now_z().endswith("Z")

    bundle = _bundle()
    with pytest.raises(ValueError, match="observation scope"):
        build_container(replace(bundle, analysis_scope=()), _SCOPE_ID)

    conflicting_descriptor = replace(
        bundle.contract.descriptors[0],
        required_contracts=(("OBSERVATION_DIGEST_VERSION", "future"),),
    )
    conflicting_contract = replace(
        bundle.contract,
        descriptors=(
            conflicting_descriptor,
            *bundle.contract.descriptors[1:],
        ),
    )
    with pytest.raises(ValueError, match="conflicting container contract"):
        build_container(replace(bundle, contract=conflicting_contract), _SCOPE_ID)

    lanes = build_observation_lanes(bundle)
    clone_payload = next(
        lane.payload for lane in lanes if lane.descriptor.name == "clones.functions"
    )
    wrong_module_lanes = tuple(
        replace(lane, payload=clone_payload)
        if lane.descriptor.name == "module_identity"
        else lane
        for lane in lanes
    )
    monkeypatch.setattr(
        "codeclone.baseline.container.build_observation_lanes",
        lambda _bundle: wrong_module_lanes,
    )
    with pytest.raises(ValueError, match="wrong payload type"):
        build_container(bundle, _SCOPE_ID)

    unknown_contract = ObservationContractInput(
        observation_digest_version="1",
        enabled_lanes=("future",),
        descriptors=(),
    )
    with pytest.raises(BaselineLaneValidationError, match="unknown lane"):
        container_mod._contract_from_input(unknown_contract)


def test_required_flag_is_authenticated_by_lane_and_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container = _container(monkeypatch)
    lane = container.lanes["clones.functions"]
    flipped = replace(lane, required=not lane.required)
    changed = _replace_lane(container, "clones.functions", flipped)

    assert compute_lane_digest(flipped) != lane.digest
    assert compute_root_digest(changed) != container.meta.root_digest

    document = _document(container)
    _set_lane_fields(document, "clones.functions", {"required": False})
    target = tmp_path / "required-flip.json"
    target.write_bytes(orjson.dumps(document, option=orjson.OPT_SORT_KEYS))

    result = read_container_v3(target, limit_bytes=target.stat().st_size)
    _assert_read_failure(result, "lane_digest_mismatch")


def test_round_trip_duplicate_invalid_and_size_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container = _container(monkeypatch)
    target = tmp_path / "baseline.json"
    raw = canonical_container_bytes(container)
    target.write_bytes(raw)

    result = read_container_v3(target, limit_bytes=len(raw))
    assert isinstance(result, ContainerReadSuccess)
    assert result.container == container

    too_large = read_container_v3(target, limit_bytes=len(raw) - 1)
    _assert_read_failure(too_large, "too_large")
    buffered_too_large = read_container_v3_bytes(raw, limit_bytes=len(raw) - 1)
    _assert_read_failure(buffered_too_large, "too_large")

    duplicate = read_container_v3(
        _DUPLICATE_KEYS_FIXTURE,
        limit_bytes=1024,
    )
    invalid = read_container_v3(
        _INVALID_JSON_FIXTURE,
        limit_bytes=1024,
    )
    _assert_read_failure(duplicate, "invalid_json")
    _assert_read_failure(invalid, "invalid_json")


def test_private_conversion_rejects_noncanonical_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = canonical_container_bytes(_container(monkeypatch))
    value = BaselineContainerV3Input.model_validate_json(raw)
    wrong_format = value.model_copy(update={"format": "other"})

    result = container_mod._container_from_input(wrong_format)

    _assert_read_failure(result, "unsupported_format")


def test_reader_unreadable_unicode_and_authentication_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = read_container_v3(tmp_path / "missing.json", limit_bytes=1024)
    directory = read_container_v3(tmp_path, limit_bytes=1024)
    zero_limit = read_container_v3(tmp_path / "missing.json", limit_bytes=0)
    _assert_read_failure(missing, "unreadable")
    _assert_read_failure(directory, "unreadable")
    _assert_read_failure(zero_limit, "too_large")

    unicode_path = tmp_path / "unicode.json"
    unicode_path.write_bytes(b"\xff")
    unicode = read_container_v3(unicode_path, limit_bytes=1)
    _assert_read_failure(unicode, "invalid_json")

    growth_path = tmp_path / "growth.json"
    growth_path.write_bytes(b"{}")
    original_stat = Path.stat

    def stale_stat(
        path: Path,
        *,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        result = original_stat(path, follow_symlinks=follow_symlinks)
        if path == growth_path:
            # Only the SIZE goes stale. The mode still describes a regular
            # file, because that is what a stale stat of a growing file looks
            # like; zeroing the whole record would simulate something that
            # cannot happen and would exercise the not-a-regular-file branch
            # instead of the growth guard this pins.
            return _stat_with_size(result, 0)
        return result

    monkeypatch.setattr(Path, "stat", stale_stat)
    growth = read_container_v3(growth_path, limit_bytes=1)
    monkeypatch.setattr(Path, "stat", original_stat)
    _assert_read_failure(growth, "too_large")

    container = _container(monkeypatch)
    root_document = _document(container)
    _set_nested_fields(
        root_document,
        "meta",
        "root_digest",
        {"value": "0" * 64},
    )
    root_result = _write_and_read(
        tmp_path,
        name="root-mismatch.json",
        document=root_document,
        authenticate=False,
    )
    _assert_read_failure(root_result, "root_digest_mismatch")

    wrong_root_domain = _document(container)
    _set_nested_fields(
        wrong_root_domain,
        "meta",
        "root_digest",
        {"domain": "codeclone.baseline.lane.v1"},
    )

    wrong_lane_domain = _document(container)
    _set_lane_nested_fields(
        wrong_lane_domain,
        "clones.functions",
        "digest",
        {"domain": "codeclone.baseline.root.v1"},
    )

    wrong_observation_domain = _document(container)
    _set_lane_nested_fields(
        wrong_observation_domain,
        "clones.functions",
        "observation_digest",
        {"domain": "ccmi2:manifest"},
    )

    for index, document in enumerate(
        (wrong_root_domain, wrong_lane_domain, wrong_observation_domain)
    ):
        result = _write_and_read(
            tmp_path,
            name=f"wrong-domain-{index}.json",
            document=document,
            authenticate=False,
        )
        _assert_read_failure(result, "invalid_container")


def test_reader_rejects_authenticated_lane_set_inconsistencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container = _container(monkeypatch)

    duplicate_enabled = _document(container)
    contract = _object_dict(duplicate_enabled["observation_contract"])
    enabled = _object_list(contract["enabled_lanes"])
    enabled.append(str(enabled[-1]))
    _set_object_field(
        duplicate_enabled,
        "observation_contract",
        "enabled_lanes",
        enabled,
    )

    missing_lane = _document(container)
    _remove_lane(missing_lane, "api_surface")

    descriptor_names = _document(container)
    contract = _object_dict(descriptor_names["observation_contract"])
    descriptors = _object_list(contract["descriptors"])
    contract["descriptors"] = list(reversed(descriptors))
    descriptor_names["observation_contract"] = contract

    descriptor_mismatch = _document(container)
    contract = _object_dict(descriptor_mismatch["observation_contract"])
    descriptors = _object_list(contract["descriptors"])
    first = _object_dict(descriptors[0])
    first["algorithm_revision"] = "future"
    descriptors[0] = first
    contract["descriptors"] = descriptors
    descriptor_mismatch["observation_contract"] = contract

    optional_module_identity = _document(container)
    _set_lane_fields(optional_module_identity, "module_identity", {"required": False})
    _rehash_lane(optional_module_identity, "module_identity")

    for index, document in enumerate(
        (
            duplicate_enabled,
            missing_lane,
            descriptor_names,
            descriptor_mismatch,
            optional_module_identity,
        )
    ):
        result = _write_and_read(
            tmp_path,
            name=f"lane-set-{index}.json",
            document=document,
        )
        _assert_read_failure(result, "inconsistent_container")


def test_future_major_malformed_type_and_descriptor_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container = _container(monkeypatch)

    future_document = _document(container)
    future_meta = _object_dict(future_document["meta"])
    future_meta["container_version"] = "4.0"
    future_document["meta"] = future_meta
    future_path = tmp_path / "future-major.json"
    future_path.write_bytes(_authenticated_document(future_document))
    future = read_container_v3(
        future_path,
        limit_bytes=future_path.stat().st_size,
    )
    _assert_read_failure(future, "unsupported_format")

    malformed_document = _document(container)
    malformed_document["contracts"] = []
    malformed_path = tmp_path / "malformed-type.json"
    malformed_path.write_bytes(
        orjson.dumps(malformed_document, option=orjson.OPT_SORT_KEYS)
    )
    malformed = read_container_v3(
        malformed_path,
        limit_bytes=malformed_path.stat().st_size,
    )
    _assert_read_failure(malformed, "invalid_container")

    descriptor_document = _document(container)
    lanes = _object_dict(descriptor_document["lanes"])
    api_lane = _object_dict(lanes["api_surface"])
    api_descriptor = _object_dict(api_lane["descriptor"])
    api_descriptor["payload_schema"] = "99"
    api_lane["descriptor"] = api_descriptor
    parsed_descriptor = ObservationLaneDescriptorInput.model_validate_json(
        orjson.dumps(api_descriptor)
    )
    api_lane["digest"] = _wire(
        compute_lane_digest_components(
            name="api_surface",
            required=bool(api_lane["required"]),
            descriptor=parsed_descriptor,
            payload=api_lane["payload"],
        )
    )
    lanes["api_surface"] = api_lane
    descriptor_document["lanes"] = lanes
    contract = _object_dict(descriptor_document["observation_contract"])
    descriptors = _object_list(contract["descriptors"])
    contract["descriptors"] = [
        api_descriptor if _object_dict(item)["name"] == "api_surface" else item
        for item in descriptors
    ]
    descriptor_document["observation_contract"] = contract
    descriptor_path = tmp_path / "outdated-descriptor.json"
    descriptor_path.write_bytes(_authenticated_document(descriptor_document))
    descriptor_result = read_container_v3(
        descriptor_path,
        limit_bytes=descriptor_path.stat().st_size,
    )
    # An artifact is read against its own recorded descriptors: a lane whose
    # payload schema is not the current one is opaque, not a read failure.
    assert isinstance(descriptor_result, ContainerReadSuccess)
    outdated = descriptor_result.container.lanes["api_surface"]
    assert lane_payload_is_opaque(outdated)
    assert all(
        not lane_payload_is_opaque(lane)
        for name, lane in descriptor_result.container.lanes.items()
        if name != "api_surface"
    )


def test_transition_wire_accepts_historic_and_live_target_fingerprints() -> None:
    """Both pre-fix and live ``to_fingerprint`` evidence must stay readable.

    Containers migrated before the fix carry ``to_fingerprint: "2"`` — the
    repository's own baseline is one — while future migrations record the
    live ``BASELINE_FINGERPRINT_VERSION``. The wire model accepts both;
    empty evidence stays rejected at the runtime boundary.
    """

    def _payload(to_fingerprint: str) -> bytes:
        return orjson.dumps(
            {
                "kind": "baseline_epoch_transition",
                "from_schema": "2.1",
                "from_fingerprint": "2",
                "to_schema": "3.0",
                "to_fingerprint": to_fingerprint,
                "imported_lanes": [],
                "regenerated_lanes": ["clones.functions"],
                "source_legacy_digest": {
                    "domain": "codeclone.baseline.legacy-evidence.v1",
                    "algorithm": "sha256",
                    "value": "9" * 64,
                },
            }
        )

    for target in ("2", BASELINE_FINGERPRINT_VERSION):
        parsed = EpochTransitionEvidenceInput.model_validate_json(_payload(target))
        runtime = container_mod._transition_from_input(parsed)
        assert runtime is not None
        assert runtime.to_fingerprint == target

    empty = EpochTransitionEvidenceInput.model_validate_json(_payload(""))
    with pytest.raises(ValueError, match="target fingerprint must be non-empty"):
        container_mod._transition_from_input(empty)


def test_reader_handles_transition_and_rejects_format_and_generator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container = _container(monkeypatch)
    transition = replace(
        container,
        transition=EpochTransitionEvidence(
            kind="baseline_epoch_transition",
            from_schema="2.1",
            from_fingerprint="2",
            to_schema="3.0",
            to_fingerprint="2",
            imported_lanes=(),
            regenerated_lanes=container.observation_contract.enabled_lanes,
            source_legacy_digest=DigestObject(
                domain="codeclone.baseline.legacy-evidence.v1",
                algorithm="sha256",
                value="9" * 64,
            ),
        ),
    )
    transition = replace(
        transition,
        meta=replace(
            transition.meta,
            root_digest=compute_root_digest(transition),
        ),
    )
    target = tmp_path / "transition.json"
    target.write_bytes(canonical_container_bytes(transition))
    result = read_container_v3(target, limit_bytes=target.stat().st_size)
    assert isinstance(result, ContainerReadSuccess)
    assert result.container.transition == transition.transition

    transition_input = BaselineContainerV3Input.model_validate_json(
        canonical_container_bytes(transition)
    ).transition
    assert transition_input is not None
    future_transition = transition_input.model_copy(
        update={"regenerated_lanes": ("future",)}
    )
    with pytest.raises(BaselineLaneValidationError, match="unknown regenerated"):
        container_mod._transition_from_input(future_transition)

    wrong_format = _document(container)
    wrong_format["format"] = "future-baseline"
    wrong_generator = _document(container)
    _set_nested_fields(
        wrong_generator,
        "meta",
        "generator",
        {"name": "other"},
    )

    for index, document in enumerate((wrong_format, wrong_generator)):
        unsupported = _write_and_read(
            tmp_path,
            name=f"unsupported-{index}.json",
            document=document,
        )
        _assert_read_failure(unsupported, "unsupported_format")


@pytest.mark.parametrize("required", (False, True))
def test_unknown_lane_is_fail_closed_or_inspection_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    required: bool,
) -> None:
    target = tmp_path / "unknown.json"
    target.write_bytes(
        _unknown_lane_document(_container(monkeypatch), required=required)
    )

    result = read_container_v3(target, limit_bytes=target.stat().st_size)

    if required:
        _assert_read_failure(result, "unknown_required_lane")
    else:
        assert isinstance(result, ContainerInspectionResult)
        assert result.unknown_optional_lanes == ("future.optional",)
        assert not result.rewrite_allowed


def test_mixed_observation_digest_fails_after_valid_authentication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container = _container(monkeypatch)
    document = _document(container)
    _set_lane_fields(
        document,
        "clones.functions",
        {
            "observation_digest": _wire(
                DigestObject(
                    domain="codeclone.source-observations.v1",
                    algorithm="sha256",
                    value="e" * 64,
                )
            )
        },
    )
    target = tmp_path / "mixed.json"
    target.write_bytes(_authenticated_document(document))

    result = read_container_v3(target, limit_bytes=target.stat().st_size)
    _assert_read_failure(result, "inconsistent_container")


def test_authenticated_fp_v1_clone_payload_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container = _container(monkeypatch)
    document = _document(container)
    _set_lane_fields(
        document,
        "clones.functions",
        {"payload": {"items": [f"{'a' * 32}|0-19"]}},
    )
    lanes = _object_dict(document["lanes"])
    lane = _object_dict(lanes["clones.functions"])
    descriptor = ObservationLaneDescriptorInput.model_validate_json(
        orjson.dumps(lane["descriptor"])
    )
    lane["digest"] = _wire(
        compute_lane_digest_components(
            name="clones.functions",
            required=True,
            descriptor=descriptor,
            payload=lane["payload"],
        )
    )
    _set_lane_fields(document, "clones.functions", {"digest": lane["digest"]})
    target = tmp_path / "fp-v1.json"
    target.write_bytes(_authenticated_document(document))

    result = read_container_v3(target, limit_bytes=target.stat().st_size)
    _assert_read_failure(result, "inconsistent_container")


def test_lane_validator_rejects_closed_schema_and_clone_shape_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(monkeypatch)
    function_lane = container.lanes["clones.functions"]

    unknown_descriptor = ObservationLaneDescriptorInput(
        name="future",
        descriptor_version="1",
        payload_schema="1",
        algorithm_revision="1",
        canonicalization_version="1",
        required_contracts=(),
    )
    with pytest.raises(BaselineLaneValidationError):
        descriptor_from_input(unknown_descriptor)
    with pytest.raises(BaselineLaneValidationError):
        validate_descriptor(
            replace(function_lane.descriptor, descriptor_version="future")
        )

    invalid_payloads: tuple[tuple[ObservationLaneName, object], ...] = (
        ("clones.functions", {"items": ["not-a-fingerprint"]}),
        ("clones.functions", {"items": [f"{'a' * 64}|bad+"]}),
        ("clones.functions", {"items": [f"{'a' * 64}|bad-range"]}),
        ("clones.blocks", {"items": ["bad|block"]}),
        (
            "clones.functions",
            {"items": [f"{'a' * 64}|0-19", f"{'a' * 64}|0-19"]},
        ),
        (
            "clones.functions",
            {"items": [f"{'a' * 64}|0-19"], "alias": True},
        ),
        ("module_identity", {}),
        ("semantic_authority", {}),
    )
    for lane_name, payload in invalid_payloads:
        with pytest.raises(BaselineLaneValidationError):
            payload_from_input(lane_name, payload)

    plus_bucket = payload_from_input(
        "clones.functions",
        {"items": [f"{'a' * 64}|10+"]},
    )
    assert isinstance(plus_bucket, CloneObservationPayload)
    assert plus_bucket.items == (f"{'a' * 64}|10+",)

    document = _document(container)
    lanes = _object_dict(document["lanes"])
    raw_lane = BaselineLaneInput.model_validate_json(
        orjson.dumps(lanes["clones.functions"])
    )
    with pytest.raises(BaselineLaneValidationError, match="lane key"):
        lane_from_input("clones.blocks", raw_lane)

    module_lane = _object_dict(lanes["module_identity"])
    module_lane["required"] = False
    raw_module_lane = BaselineLaneInput.model_validate_json(orjson.dumps(module_lane))
    with pytest.raises(BaselineLaneValidationError, match="remain required"):
        lane_from_input("module_identity", raw_module_lane)


def test_trust_is_reader_side_and_lane_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(monkeypatch)
    runtime = RuntimeContracts(
        python_tag="cp314",
        baseline_scope_id=_SCOPE_ID,
        lane_descriptors=container.observation_contract.descriptors,
    )
    trusted = evaluate_lane_trust(container, runtime)
    assert trusted.root_verified
    assert all(item.status == "trusted" for item in trusted.lanes)

    old_lane = container.lanes["api_surface"]
    new_descriptor = replace(old_lane.descriptor, payload_schema="9")
    new_lane = replace(old_lane, descriptor=new_descriptor)
    new_lane = replace(new_lane, digest=compute_lane_digest(new_lane))
    changed = _replace_lane(container, "api_surface", new_lane)
    changed_contract = replace(
        changed.observation_contract,
        descriptors=tuple(
            new_descriptor if item.name == "api_surface" else item
            for item in changed.observation_contract.descriptors
        ),
    )
    changed = replace(changed, observation_contract=changed_contract)
    changed = replace(
        changed,
        meta=replace(changed.meta, root_digest=compute_root_digest(changed)),
    )
    vector = evaluate_lane_trust(changed, runtime)
    states = {item.name: (item.status, item.reason) for item in vector.lanes}
    assert states["api_surface"] == ("unavailable", "payload_schema")
    assert states["clones.functions"] == ("trusted", "compatible")

    tampered = replace(
        container,
        meta=replace(
            container.meta,
            root_digest=replace(container.meta.root_digest, value="0" * 64),
        ),
    )
    invalid = evaluate_lane_trust(tampered, runtime)
    assert not invalid.root_verified
    assert all(item.reason == "root_digest_mismatch" for item in invalid.lanes)


def test_lane_trust_projects_each_compatibility_reason_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(monkeypatch)
    api_lane = container.lanes["api_surface"]
    descriptors = container.observation_contract.descriptors

    def api_reason(runtime: RuntimeContracts) -> str:
        vector = evaluate_lane_trust(container, runtime)
        return next(item.reason for item in vector.lanes if item.name == "api_surface")

    without_api = RuntimeContracts(
        python_tag="cp314",
        baseline_scope_id=_SCOPE_ID,
        lane_descriptors=tuple(
            item for item in descriptors if item.name != "api_surface"
        ),
    )
    assert api_reason(without_api) == "runtime_lane_unknown"

    variants = (
        ("descriptor_version", replace(api_lane.descriptor, descriptor_version="9")),
        ("payload_schema", replace(api_lane.descriptor, payload_schema="9")),
        ("algorithm_revision", replace(api_lane.descriptor, algorithm_revision="9")),
        (
            "canonicalization_version",
            replace(api_lane.descriptor, canonicalization_version="9"),
        ),
        ("required_contract", replace(api_lane.descriptor, required_contracts=())),
    )
    for expected_reason, runtime_descriptor in variants:
        runtime = RuntimeContracts(
            python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
            lane_descriptors=tuple(
                runtime_descriptor if item.name == "api_surface" else item
                for item in descriptors
            ),
        )
        assert api_reason(runtime) == expected_reason

    wrong_python = RuntimeContracts(
        python_tag="cp313",
        baseline_scope_id=_SCOPE_ID,
        lane_descriptors=descriptors,
    )
    assert api_reason(wrong_python) == "python_tag"

    bad_digest_lane = replace(
        api_lane,
        digest=_different_digest(api_lane.digest, "5"),
    )
    bad_digest = _replace_lane(container, "api_surface", bad_digest_lane)
    bad_digest = replace(
        bad_digest,
        meta=replace(
            bad_digest.meta,
            root_digest=compute_root_digest(bad_digest),
        ),
    )
    vector = evaluate_lane_trust(
        bad_digest,
        RuntimeContracts(
            python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
            lane_descriptors=descriptors,
        ),
    )
    state = next(item for item in vector.lanes if item.name == "api_surface")
    assert state.reason == "lane_digest_mismatch"


def test_container_domain_models_reject_invalid_closed_invariants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(monkeypatch)
    lane = container.lanes["clones.functions"]
    legacy_digest = DigestObject(
        domain="codeclone.baseline.legacy-evidence.v1",
        algorithm="sha256",
        value="9" * 64,
    )

    with pytest.raises(ValueError):
        replace(container.meta, python_tag="")
    with pytest.raises(ValueError):
        replace(container.meta, created_at="not-utc")
    with pytest.raises(ValueError):
        replace(
            container.meta,
            root_digest=replace(
                container.meta.root_digest,
                domain="codeclone.baseline.lane.v1",
            ),
        )

    with pytest.raises(ValueError):
        replace(
            container.source,
            module_identity_manifest_digest=replace(
                container.source.module_identity_manifest_digest,
                domain="codeclone.baseline.lane.v1",
            ),
        )

    with pytest.raises(ValueError):
        EpochTransitionEvidence(
            kind="baseline_epoch_transition",
            from_schema="",
            from_fingerprint="2",
            to_schema="3.0",
            to_fingerprint="2",
            imported_lanes=(),
            regenerated_lanes=(),
            source_legacy_digest=DigestObject(
                domain="codeclone.baseline.legacy-evidence.v1",
                algorithm="sha256",
                value="9" * 64,
            ),
        )
    with pytest.raises(ValueError):
        EpochTransitionEvidence(
            kind="baseline_epoch_transition",
            from_schema="2.1",
            from_fingerprint="2",
            to_schema="3.0",
            to_fingerprint="2",
            imported_lanes=("clones",),
            regenerated_lanes=(),
            source_legacy_digest=DigestObject(
                domain="codeclone.baseline.legacy-evidence.v1",
                algorithm="sha256",
                value="9" * 64,
            ),
        )
    with pytest.raises(ValueError):
        EpochTransitionEvidence(
            kind="baseline_epoch_transition",
            from_schema=None,
            from_fingerprint=None,
            to_schema="3.0",
            to_fingerprint="2",
            imported_lanes=(),
            regenerated_lanes=("risk_observations", "api_surface"),
            source_legacy_digest=None,
        )
    with pytest.raises(ValueError, match="all-or-none"):
        EpochTransitionEvidence(
            kind="baseline_epoch_transition",
            from_schema="2.1",
            from_fingerprint=None,
            to_schema="3.0",
            to_fingerprint="2",
            imported_lanes=(),
            regenerated_lanes=(),
            source_legacy_digest=legacy_digest,
        )
    with pytest.raises(ValueError, match="fingerprint must be non-empty"):
        EpochTransitionEvidence(
            kind="baseline_epoch_transition",
            from_schema="2.1",
            from_fingerprint="",
            to_schema="3.0",
            to_fingerprint="2",
            imported_lanes=(),
            regenerated_lanes=(),
            source_legacy_digest=legacy_digest,
        )
    with pytest.raises(ValueError, match="wrong legacy digest domain"):
        EpochTransitionEvidence(
            kind="baseline_epoch_transition",
            from_schema="2.1",
            from_fingerprint="2",
            to_schema="3.0",
            to_fingerprint="2",
            imported_lanes=(),
            regenerated_lanes=(),
            source_legacy_digest=replace(
                legacy_digest,
                domain="codeclone.baseline.root.v1",
            ),
        )

    valid_function_id = f"{'a' * 64}|0-19"
    with pytest.raises(ValueError, match="entity populations must be non-negative"):
        StructuralObservationFacts(
            function_clone_keys=(),
            block_clone_keys=(),
            dependencies=(),
            api_surface=(),
            dead_code=(),
            risk_observations=(),
            risk_entity_population=-1,
            adoption_counts=(),
            coupling_cohesion_observations=(),
            coupling_cohesion_entity_population=0,
        )
    with pytest.raises(ValueError, match="sorted and unique"):
        StructuralObservationFacts(
            function_clone_keys=(valid_function_id, valid_function_id),
            block_clone_keys=(),
            dependencies=(),
            api_surface=(),
            dead_code=(),
            risk_observations=(),
            risk_entity_population=0,
            adoption_counts=(),
            coupling_cohesion_observations=(),
            coupling_cohesion_entity_population=0,
        )

    with pytest.raises(ValueError):
        ContractIndex(rows=(("z", "1"), ("a", "1")))
    with pytest.raises(ValueError):
        ContractIndex(rows=(("", "1"),))
    with pytest.raises(KeyError):
        container.contracts["missing"]

    with pytest.raises(ValueError):
        replace(lane, name="clones.blocks")
    with pytest.raises(ValueError):
        replace(
            lane,
            observation_digest=replace(
                lane.observation_digest,
                domain="ccmi2:manifest",
            ),
        )
    with pytest.raises(ValueError):
        replace(
            lane,
            digest=replace(lane.digest, domain="codeclone.baseline.root.v1"),
        )

    with pytest.raises(ValueError):
        BaselineLaneIndex(rows=(*container.lanes.rows, container.lanes.rows[-1]))
    with pytest.raises(ValueError):
        BaselineLaneIndex(rows=(("clones.blocks", lane),))
    with pytest.raises(KeyError):
        container.lanes["semantic_authority"]

    without_api = BaselineLaneIndex(
        rows=tuple(row for row in container.lanes.rows if row[0] != "api_surface")
    )
    with pytest.raises(ValueError):
        replace(container, lanes=without_api)

    with pytest.raises(ValueError, match="module_identity is required"):
        replace(
            container.observation_contract,
            enabled_lanes=tuple(
                name
                for name in container.observation_contract.enabled_lanes
                if name != "module_identity"
            ),
            descriptors=tuple(
                item
                for item in container.observation_contract.descriptors
                if item.name != "module_identity"
            ),
        )

    with pytest.raises(ValueError):
        RuntimeContracts(
            python_tag="cp314",
            baseline_scope_id=_SCOPE_ID,
            lane_descriptors=(lane.descriptor, lane.descriptor),
        )

    with pytest.raises(ValueError, match="lock fields must be non-empty"):
        BaselinePublishLock(
            token="",
            pid=1,
            hostname="host",
            process_start="start",
            created_at="2026-07-21T00:00:00Z",
        )


def test_analysis_scope_digest_uses_only_sorted_analyzed_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(monkeypatch)
    payload = container.lanes["module_identity"].payload
    assert isinstance(payload, ModuleIdentityColumnarPayload)
    entries = decode_module_identity_lane(payload).module_registry

    assert compute_analysis_scope_digest(entries) == compute_analysis_scope_digest(
        tuple(reversed(entries))
    )
    analyzed = next(entry for entry in entries if entry.analyzed)
    changed = tuple(
        replace(
            entry,
            analyzed=False,
            internality="known_internal_not_analyzed",
        )
        if entry is analyzed
        else entry
        for entry in entries
    )
    assert (
        compute_analysis_scope_digest(changed) != container.source.analysis_scope_digest
    )
    with pytest.raises(ValueError, match="must be unique"):
        compute_analysis_scope_digest((*entries, analyzed))


def test_container_observer_on_off_byte_equality(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "container.json"

    def exercise(*, enabled: bool) -> tuple[bytes, object, object]:
        bootstrap(ObservabilityConfig(enabled=enabled), root=tmp_path)
        try:
            with operation(name="test.baseline.container", surface="test"):
                container = _container(monkeypatch)
                raw = canonical_container_bytes(container)
                target.write_bytes(raw)
                read_result = read_container_v3(
                    target,
                    limit_bytes=target.stat().st_size,
                )
                trust = evaluate_lane_trust(
                    container,
                    RuntimeContracts(
                        python_tag="cp314",
                        baseline_scope_id=_SCOPE_ID,
                        lane_descriptors=container.observation_contract.descriptors,
                    ),
                )
                return raw, read_result, trust
        finally:
            shutdown()

    assert exercise(enabled=False) == exercise(enabled=True)


def test_reader_has_no_legacy_or_persisted_trust_path() -> None:
    root = Path(container_mod.__file__).parent
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (
            root / "container.py",
            root / "container_digest.py",
            root / "container_trust.py",
            root / "lanes.py",
        )
    }
    combined = "\n".join(sources.values())
    assert "payload_sha256" not in combined
    assert "legacy_v2" not in combined
    assert "persisted_trust" not in combined
    assert "hashlib" not in sources["container.py"]
    assert "hashlib" not in sources["container_trust.py"]
    assert "hashlib" not in sources["lanes.py"]
    assert sources["container_digest.py"].count("import hashlib") == 1


def test_outdated_lane_stays_opaque_trusted_bytes_and_still_fails_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The B+ chain: outdated schema → opaque → unavailable → exit 2."""

    container = _container(monkeypatch)
    old_lane = container.lanes["risk_observations"]
    outdated_descriptor = replace(old_lane.descriptor, payload_schema="1")
    outdated_lane = replace(old_lane, descriptor=outdated_descriptor, payload={})
    outdated_lane = replace(outdated_lane, digest=compute_lane_digest(outdated_lane))
    changed = _replace_lane(container, "risk_observations", outdated_lane)
    changed = replace(
        changed,
        meta=replace(changed.meta, root_digest=compute_root_digest(changed)),
    )
    runtime = RuntimeContracts(
        python_tag="cp314",
        baseline_scope_id=_SCOPE_ID,
        lane_descriptors=container.observation_contract.descriptors,
    )

    # The lane is opaque, its bytes still authenticate, and the root holds.
    assert lane_payload_is_opaque(changed.lanes["risk_observations"])
    vector = evaluate_lane_trust(changed, runtime)
    assert vector.root_verified
    states = {item.name: (item.status, item.reason) for item in vector.lanes}
    assert states["risk_observations"] == ("unavailable", "payload_schema_outdated")
    # Every other lane keeps comparing.
    assert all(
        state == ("trusted", "compatible")
        for name, state in states.items()
        if name != "risk_observations"
    )

    # A requested gate that needs the opaque lane still exits 2 — no weakening.
    result = evaluate_gate_state(
        state=GateState(),
        config=MetricGateConfig(
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=True,
            fail_on_new=False,
        ),
        lane_trust={name: status for name, (status, _reason) in states.items()},
        enabled_lanes=tuple(changed.lanes),
    )
    assert result.exit_code == 2
    assert "risk_observations" in result.unavailable_lanes
    assert "lane:unavailable:risk_observations" in result.reasons


def test_outdated_module_identity_lane_is_opaque_not_a_container_defect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B+ holds for the lane the consistency check depends on."""

    container = _container(monkeypatch)
    document = _document(container)
    _set_lane_nested_fields(
        document, "module_identity", "descriptor", {"payload_schema": "2"}
    )
    descriptor = _object_dict(
        _object_dict(_object_dict(document["lanes"])["module_identity"])["descriptor"]
    )
    contract = _object_dict(document["observation_contract"])
    contract["descriptors"] = [
        descriptor if _object_dict(item)["name"] == "module_identity" else item
        for item in _object_list(contract["descriptors"])
    ]
    document["observation_contract"] = contract
    _rehash_lane(document, "module_identity")

    result = _write_and_read(tmp_path, name="outdated.json", document=document)

    assert isinstance(result, ContainerReadSuccess)
    assert lane_payload_is_opaque(result.container.lanes["module_identity"])


def test_outdated_lane_payload_must_still_be_a_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _container(monkeypatch)
    document = _document(container)
    lane = _object_dict(_object_dict(document["lanes"])["module_identity"])
    descriptor = _object_dict(lane["descriptor"])
    descriptor["payload_schema"] = "2"
    lane["descriptor"] = descriptor
    lane["payload"] = ["not", "an", "object"]

    with pytest.raises(BaselineLaneValidationError, match="must be a JSON object"):
        lane_from_input(
            "module_identity",
            BaselineLaneInput.model_validate_json(orjson.dumps(lane)),
        )


def test_a_directory_is_unreadable_whatever_its_stat_size_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A path that is not a regular file is unreadable, never too_large.

    ``st_size`` on a directory is filesystem bookkeeping, not a container size:
    Linux reports 4096 where macOS reports a few dozen bytes. Comparing it
    against the limit made the verdict depend on the filesystem -- the same
    directory read as ``unreadable`` locally and ``too_large`` on CI -- and the
    ``too_large`` answer was the wrong one either way, because it tells an
    operator their baseline is oversized when the path is not a baseline at
    all.

    The precedence is therefore pinned here: what a path IS decides before how
    large it claims to be. The monkeypatch reproduces the Linux number so the
    contract is asserted on every platform rather than only where the number
    happens to be small.
    """

    real_stat = Path.stat

    def linux_sized_directory(path: Path, **kwargs: object) -> os.stat_result:
        result = real_stat(path, **kwargs)  # type: ignore[arg-type]
        if path == tmp_path:
            return _stat_with_size(result, 4096)
        return result

    monkeypatch.setattr(Path, "stat", linux_sized_directory)

    assert Path(tmp_path).stat().st_size == 4096
    _assert_read_failure(read_container_v3(tmp_path, limit_bytes=1024), "unreadable")

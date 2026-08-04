# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import socket
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import orjson
import pytest

import codeclone.baseline.container as container_mod
import codeclone.baseline.publish as publish_mod
from codeclone.baseline.container import build_container, read_container_v3
from codeclone.baseline.container_digest import canonical_container_bytes
from codeclone.baseline.publish import (
    BaselinePublicationError,
    publish_baseline,
    recover_publish_lock,
)
from codeclone.baseline.transition import (
    legacy_backup_path,
    preserve_legacy_backup,
    read_legacy_transition,
)
from codeclone.baseline.trust import _compute_payload_sha256
from codeclone.contracts import BASELINE_FINGERPRINT_VERSION
from codeclone.contracts.errors import BaselineValidationError
from codeclone.models import (
    BaselineContainerV3,
    BaselinePublishLock,
    BaselineTargetKind,
    ClassMetrics,
    CloneObservationPayload,
    ContainerReadSuccess,
    EpochTransitionEvidence,
    ObservabilityConfig,
    ObservationBundle,
)
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.observations.projection import build_observation_bundle
from tests._ast_metrics_helpers import (
    build_test_module_registry,
    module_registry_context,
)

_SCOPE_ID = UUID("019f7fa1-8866-7242-b0bf-0ff282cafbcb")
_OTHER_SCOPE_ID = UUID("018f4b8e-5a5f-7d35-9c21-4af5d18df420")
_FUNCTION_ID = f"{'a' * 64}|0-19"
_BLOCK_ID = "|".join(("b" * 64,) * 4)


def _bundle(*, function_id: str = _FUNCTION_ID) -> ObservationBundle:
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    return build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        function_clone_keys=(function_id,),
        block_clone_keys=(_BLOCK_ID,),
    )


@pytest.fixture(autouse=True)
def _stable_container_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(container_mod, "current_python_tag", lambda: "cp314")
    monkeypatch.setattr(
        container_mod,
        "_utc_now_z",
        lambda: "2026-07-20T00:00:00Z",
    )


def _legacy_bytes() -> bytes:
    payload_sha256 = _compute_payload_sha256(
        functions=(_FUNCTION_ID,),
        blocks=(_BLOCK_ID,),
        fingerprint_version="2",
        python_tag="cp314",
    )
    return orjson.dumps(
        {
            "meta": {
                "generator": {"name": "codeclone", "version": "2.1.0a2"},
                "schema_version": "2.1",
                "fingerprint_version": "2",
                "python_tag": "cp314",
                "created_at": "2026-07-19T00:00:00Z",
                "payload_sha256": payload_sha256,
            },
            "clones": {
                "functions": [_FUNCTION_ID],
                "blocks": [_BLOCK_ID],
            },
        },
        option=orjson.OPT_SORT_KEYS,
    )


def _write_legacy_target(
    tmp_path: Path,
) -> tuple[Path, bytes, EpochTransitionEvidence]:
    target = tmp_path / "baseline.json"
    raw = _legacy_bytes()
    target.write_bytes(raw)
    transition = read_legacy_transition(
        target,
        raw=raw,
        regenerated_lanes=_bundle().contract.enabled_lanes,
    )
    return target, raw, transition


def _read_published(path: Path) -> ContainerReadSuccess:
    result = read_container_v3(path, limit_bytes=path.stat().st_size)
    assert isinstance(result, ContainerReadSuccess)
    return result


def _checkout_bundle(root: Path) -> ObservationBundle:
    """Build a bundle from a real checkout, using that root's absolute unit paths."""

    package = root / "pkg"
    package.mkdir(parents=True)
    package.joinpath("__init__.py").write_text("", "utf-8")
    package.joinpath("mod.py").write_text(
        "class Thing:\n    def run(self, value: int) -> int:\n        return value\n",
        "utf-8",
    )
    absolute = str(package / "mod.py")
    return build_observation_bundle(
        scan_root=root,
        module_registry=build_test_module_registry(root=root),
        function_clone_keys=(_FUNCTION_ID,),
        block_clone_keys=(_BLOCK_ID,),
        units=(
            {
                "filepath": absolute,
                "qualname": "pkg.mod:Thing.run",
                "cyclomatic_complexity": 2,
                "nesting_depth": 1,
            },
        ),
        class_metrics=(
            ClassMetrics(
                qualname="pkg.mod:Thing",
                filepath=absolute,
                start_line=1,
                end_line=3,
                cbo=2,
                lcom4=1,
                method_count=1,
                instance_var_count=0,
                risk_coupling="low",
                risk_cohesion="low",
            ),
        ),
    )


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(
            item
            for key, nested in value.items()
            for item in (key, *_string_values(nested))
        )
    if isinstance(value, list):
        return tuple(item for nested in value for item in _string_values(nested))
    return ()


def test_publication_from_differently_named_checkouts_is_byte_identical(
    tmp_path: Path,
) -> None:
    first = canonical_container_bytes(
        build_container(_checkout_bundle(tmp_path / "alpha-checkout"), _SCOPE_ID)
    )
    second = canonical_container_bytes(
        build_container(_checkout_bundle(tmp_path / "b"), _SCOPE_ID)
    )

    assert first == second


def test_published_artifact_carries_no_machine_strings(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    payload = canonical_container_bytes(
        build_container(_checkout_bundle(root), _SCOPE_ID)
    )
    values = _string_values(orjson.loads(payload))

    for machine_string in (
        "/Users/",
        "/home/",
        str(Path.home()),
        Path.home().name,
        socket.gethostname(),
        str(tmp_path),
    ):
        assert not any(machine_string in value for value in values), machine_string
    assert not any(value.startswith(os.sep) for value in values)


def test_fresh_publication_has_no_fabricated_transition(tmp_path: Path) -> None:
    target = tmp_path / "baseline.json"

    receipt = publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
    )

    published = _read_published(target).container
    assert receipt.outcome == "published"
    assert receipt.observed_kind == "absent"
    assert receipt.backup_created is False
    assert published.transition is None
    assert published.baseline_scope_id == _SCOPE_ID
    assert target.read_bytes() == canonical_container_bytes(published) + b"\n"


def test_publish_carries_project_label_without_moving_the_root_digest(
    tmp_path: Path,
) -> None:
    """The label is descriptive meta: it reaches the file but not the digest."""

    labelled_path = tmp_path / "labelled.json"
    plain_path = tmp_path / "plain.json"
    publish_baseline(
        target=labelled_path,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
        project_label="Acme Payments",
    )
    publish_baseline(
        target=plain_path,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
    )

    labelled = _read_published(labelled_path).container
    plain = _read_published(plain_path).container

    assert labelled.meta.project_label == "Acme Payments"
    assert plain.meta.project_label is None
    assert labelled.meta.root_digest.value == plain.meta.root_digest.value


def test_relabelled_republication_is_not_a_noop(tmp_path: Path) -> None:
    """A rename changes no digest, so the noop check must compare it directly."""

    target = tmp_path / "baseline.json"
    publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
        project_label="Before",
    )
    renamed = publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
        project_label="After",
    )
    unchanged = publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
        project_label="After",
    )

    assert renamed.outcome == "published"
    assert unchanged.outcome == "noop"
    assert _read_published(target).container.meta.project_label == "After"


def test_legacy_transition_preserves_exact_backup_and_clone_ids(tmp_path: Path) -> None:
    target = tmp_path / "baseline.json"
    raw = _legacy_bytes()
    target.write_bytes(raw)

    receipt = publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
    )

    published = _read_published(target).container
    transition = published.transition
    assert transition is not None
    assert transition.from_schema == "2.1"
    assert transition.from_fingerprint == "2"
    assert transition.imported_lanes == ()
    assert transition.regenerated_lanes == published.observation_contract.enabled_lanes
    assert transition.source_legacy_digest is not None
    backup = legacy_backup_path(target, transition.source_legacy_digest)
    assert backup.read_bytes() == raw
    assert receipt.backup_created is True
    function_payload = published.lanes["clones.functions"].payload
    block_payload = published.lanes["clones.blocks"].payload
    assert isinstance(function_payload, CloneObservationPayload)
    assert isinstance(block_payload, CloneObservationPayload)
    assert function_payload.items == (_FUNCTION_ID,)
    assert block_payload.items == (_BLOCK_ID,)


def test_legacy_transition_targets_the_live_fingerprint_version(
    tmp_path: Path,
) -> None:
    """Migration evidence records the fingerprint the new epoch actually runs.

    The published container's clone lanes carry the live
    ``BASELINE_FINGERPRINT_VERSION`` as required contract and algorithm
    revision, so the transition's ``to_fingerprint`` must be that same
    constant — never a hardcoded historical value.
    """

    _target, _raw, transition = _write_legacy_target(tmp_path)
    assert transition.to_fingerprint == BASELINE_FINGERPRINT_VERSION


def test_republication_is_exact_byte_noop(tmp_path: Path) -> None:
    target = tmp_path / "baseline.json"
    publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
    )
    before = target.read_bytes()
    before_mtime = target.stat().st_mtime_ns

    receipt = publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
    )

    assert receipt.outcome == "noop"
    assert target.read_bytes() == before
    assert target.stat().st_mtime_ns == before_mtime


def test_observer_on_off_publication_is_byte_identical(tmp_path: Path) -> None:
    bundle = _bundle()
    disabled_target = tmp_path / "disabled.json"
    enabled_target = tmp_path / "enabled.json"

    shutdown()
    bootstrap(ObservabilityConfig(enabled=False), root=tmp_path)
    try:
        with operation(name="cli.analyze", surface="cli"):
            disabled_receipt = publish_baseline(
                target=disabled_target,
                bundle=bundle,
                scope_id=_SCOPE_ID,
                max_size_bytes=5_000_000,
            )
    finally:
        shutdown()

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="cli.analyze", surface="cli"):
            enabled_receipt = publish_baseline(
                target=enabled_target,
                bundle=bundle,
                scope_id=_SCOPE_ID,
                max_size_bytes=5_000_000,
            )
    finally:
        shutdown()

    assert enabled_target.read_bytes() == disabled_target.read_bytes()
    assert enabled_receipt == disabled_receipt


def test_cas_conflict_does_not_replace_target_or_leave_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "baseline.json"
    publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
    )
    before = target.read_bytes()
    observe_target = publish_mod._observe_target
    calls = 0

    def _changed_second_observation(
        target_path: Path,
        *,
        max_size_bytes: int,
        bundle: ObservationBundle,
    ) -> tuple[
        BaselineTargetKind,
        str,
        bytes | None,
        BaselineContainerV3 | None,
        EpochTransitionEvidence | None,
    ]:
        nonlocal calls
        calls += 1
        result = observe_target(
            target_path,
            max_size_bytes=max_size_bytes,
            bundle=bundle,
        )
        if calls == 2:
            return (result[0], f"{result[1]}:changed", *result[2:])
        return result

    monkeypatch.setattr(
        publish_mod,
        "_observe_target",
        _changed_second_observation,
    )

    with pytest.raises(BaselinePublicationError) as error:
        publish_baseline(
            target=target,
            bundle=_bundle(function_id=f"{'c' * 64}|20-39"),
            scope_id=_SCOPE_ID,
            max_size_bytes=5_000_000,
        )

    assert error.value.reason == "cas_conflict"
    assert target.read_bytes() == before
    assert not target.with_name(f"{target.name}.publish.lock").exists()


def test_scope_mismatch_and_oversize_leave_prior_bytes_unchanged(
    tmp_path: Path,
) -> None:
    target = tmp_path / "baseline.json"
    target.write_bytes(
        canonical_container_bytes(build_container(_bundle(), _OTHER_SCOPE_ID))
    )
    before = target.read_bytes()

    with pytest.raises(BaselinePublicationError) as mismatch:
        publish_baseline(
            target=target,
            bundle=_bundle(),
            scope_id=_SCOPE_ID,
            max_size_bytes=5_000_000,
        )
    assert mismatch.value.reason == "scope_mismatch"
    assert target.read_bytes() == before

    with pytest.raises(BaselinePublicationError) as oversize:
        publish_baseline(
            target=target,
            bundle=_bundle(),
            scope_id=_OTHER_SCOPE_ID,
            max_size_bytes=1,
        )
    assert oversize.value.reason == "oversize"
    assert target.read_bytes() == before


def test_symlink_target_is_rejected_without_touching_referent(tmp_path: Path) -> None:
    referent = tmp_path / "referent.json"
    referent.write_text("untouched", "utf-8")
    target = tmp_path / "baseline.json"
    target.symlink_to(referent)

    with pytest.raises((BaselinePublicationError, OSError)):
        publish_baseline(
            target=target,
            bundle=_bundle(),
            scope_id=_SCOPE_ID,
            max_size_bytes=5_000_000,
        )

    assert referent.read_text("utf-8") == "untouched"


def test_legacy_backup_symlink_is_rejected_without_touching_target_or_referent(
    tmp_path: Path,
) -> None:
    target, raw, transition = _write_legacy_target(tmp_path)
    assert transition.source_legacy_digest is not None
    referent = tmp_path / "backup-referent.json"
    referent.write_text("untouched", "utf-8")
    backup = legacy_backup_path(target, transition.source_legacy_digest)
    backup.symlink_to(referent)

    with pytest.raises((BaselinePublicationError, OSError)):
        publish_baseline(
            target=target,
            bundle=_bundle(),
            scope_id=_SCOPE_ID,
            max_size_bytes=5_000_000,
        )

    assert target.read_bytes() == raw
    assert referent.read_text("utf-8") == "untouched"
    assert not target.with_name(f"{target.name}.publish.lock").exists()


def _write_lock(target: Path, lock: BaselinePublishLock) -> Path:
    path = target.with_name(f"{target.name}.publish.lock")
    path.write_bytes(publish_mod._lock_bytes(lock))
    return path


def test_explicit_recovery_requires_expected_token_and_dead_owner(
    tmp_path: Path,
) -> None:
    target = tmp_path / "baseline.json"
    lock = BaselinePublishLock(
        token="expected",
        pid=999_999,
        hostname=socket.gethostname(),
        process_start="definitely-dead",
        created_at="2026-07-20T00:00:00Z",
    )
    lock_path = _write_lock(target, lock)

    with pytest.raises(BaselinePublicationError) as mismatch:
        recover_publish_lock(target=target, expected_token="wrong")
    assert mismatch.value.reason == "cas_conflict"

    receipt = recover_publish_lock(target=target, expected_token="expected")
    assert receipt.outcome == "recovered"
    assert not lock_path.exists()
    assert not target.with_name(f"{target.name}.publish.lock.recovery").exists()


def test_recovery_refuses_active_and_unforced_foreign_locks(tmp_path: Path) -> None:
    target = tmp_path / "baseline.json"
    active = BaselinePublishLock(
        token="active",
        pid=os.getpid(),
        hostname=socket.gethostname(),
        process_start=publish_mod._process_start(os.getpid()) or "unavailable",
        created_at="2026-07-20T00:00:00Z",
    )
    _write_lock(target, active)
    with pytest.raises(BaselinePublicationError) as active_error:
        recover_publish_lock(target=target, expected_token="active", force=True)
    assert active_error.value.reason == "active_lock"

    target.with_name(f"{target.name}.publish.lock").unlink()
    foreign = BaselinePublishLock(
        token="foreign",
        pid=12,
        hostname="other-host",
        process_start="unknown",
        created_at="2026-07-20T00:00:00Z",
    )
    _write_lock(target, foreign)
    with pytest.raises(BaselinePublicationError) as foreign_error:
        recover_publish_lock(target=target, expected_token="foreign")
    assert foreign_error.value.reason == "foreign_lock"
    recover_publish_lock(
        target=target,
        expected_token="foreign",
        force=True,
    )


def test_malformed_lock_requires_force_and_recovery_guard_is_exclusive(
    tmp_path: Path,
) -> None:
    target = tmp_path / "baseline.json"
    lock_path = target.with_name(f"{target.name}.publish.lock")
    lock_path.write_text("malformed", "utf-8")
    with pytest.raises(BaselinePublicationError) as malformed:
        recover_publish_lock(target=target, expected_token="operator")
    assert malformed.value.reason == "invalid_lock"

    guard = target.with_name(f"{target.name}.publish.lock.recovery")
    guard.write_text("busy", "utf-8")
    with pytest.raises(BaselinePublicationError) as busy:
        recover_publish_lock(
            target=target,
            expected_token="operator",
            force=True,
        )
    assert busy.value.reason == "active_lock"
    guard.unlink()
    recover_publish_lock(
        target=target,
        expected_token="operator",
        force=True,
    )
    assert not lock_path.exists()


def test_legacy_transition_rejects_each_untrusted_evidence_class(
    tmp_path: Path,
) -> None:
    target = tmp_path / "baseline.json"

    def _read(raw: bytes) -> None:
        read_legacy_transition(
            target,
            raw=raw,
            regenerated_lanes=_bundle().contract.enabled_lanes,
        )

    with pytest.raises(BaselineValidationError) as invalid_json:
        _read(b"not-json")
    assert invalid_json.value.status == "invalid_json"

    for field, value, expected_status in (
        ("generator", {"name": "other", "version": "2.1.0a2"}, "generator_mismatch"),
        ("schema_version", "2.0", "mismatch_schema_version"),
        # The declared generation is no longer refused for differing from the
        # runtime -- it is provenance, and any prior generation is legitimate.
        # Rewriting it is still refused, and by the stronger check: the field
        # is covered by payload_sha256, so tampering fails authentication
        # instead of a contract comparison.
        ("fingerprint_version", "1", "integrity_failed"),
    ):
        document = orjson.loads(_legacy_bytes())
        assert isinstance(document, dict)
        meta = document["meta"]
        assert isinstance(meta, dict)
        meta[field] = value
        with pytest.raises(BaselineValidationError) as error:
            _read(orjson.dumps(document, option=orjson.OPT_SORT_KEYS))
        assert error.value.status == expected_status

    for lane_name, invalid_items in (
        ("functions", ["fp-v1"]),
        ("blocks", ["|".join(("f" * 64,) * 4), _BLOCK_ID]),
    ):
        invalid_clones = orjson.loads(_legacy_bytes())
        assert isinstance(invalid_clones, dict)
        clone_payload = invalid_clones["clones"]
        assert isinstance(clone_payload, dict)
        clone_payload[lane_name] = invalid_items
        with pytest.raises(BaselineValidationError) as clone_error:
            _read(orjson.dumps(invalid_clones, option=orjson.OPT_SORT_KEYS))
        assert clone_error.value.status == "invalid_type"

    invalid_digest = orjson.loads(_legacy_bytes())
    assert isinstance(invalid_digest, dict)
    digest_meta = invalid_digest["meta"]
    assert isinstance(digest_meta, dict)
    digest_meta["payload_sha256"] = "0" * 64
    with pytest.raises(BaselineValidationError) as digest_error:
        _read(orjson.dumps(invalid_digest, option=orjson.OPT_SORT_KEYS))
    assert digest_error.value.status == "integrity_failed"


def test_legacy_backup_is_idempotent_and_rejects_digest_collision(
    tmp_path: Path,
) -> None:
    target = tmp_path / "baseline.json"
    raw = _legacy_bytes()
    transition = read_legacy_transition(
        target,
        raw=raw,
        regenerated_lanes=_bundle().contract.enabled_lanes,
    )
    digest = transition.source_legacy_digest
    assert digest is not None

    assert preserve_legacy_backup(target, raw=raw, digest=digest) is True
    assert preserve_legacy_backup(target, raw=raw, digest=digest) is False
    with pytest.raises(OSError, match="digest collision"):
        preserve_legacy_backup(target, raw=b"different", digest=digest)


def test_legacy_backup_write_failure_removes_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "baseline.json"
    raw = _legacy_bytes()
    transition = read_legacy_transition(
        target,
        raw=raw,
        regenerated_lanes=_bundle().contract.enabled_lanes,
    )
    digest = transition.source_legacy_digest
    assert digest is not None
    backup = legacy_backup_path(target, digest)

    def _fail_fsync(_fd: int) -> None:
        raise OSError("fsync")

    monkeypatch.setattr("codeclone.baseline.transition.os.fsync", _fail_fsync)

    with pytest.raises(OSError, match="fsync"):
        preserve_legacy_backup(target, raw=raw, digest=digest)

    assert not backup.exists()


def test_publisher_internal_failure_paths_are_typed_and_cleanup_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "baseline.json"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("ps")),
    )
    assert publish_mod._process_start(1) is None
    lock = publish_mod._new_lock()
    assert lock.process_start.startswith("unavailable:")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=""),
    )
    assert publish_mod._process_start(1) is None

    monkeypatch.undo()
    target.write_text("old", "utf-8")
    monkeypatch.delattr(os, "fchmod")
    publish_mod._replace_target(target, b"portable")
    assert target.read_bytes() == b"portable"

    monkeypatch.undo()
    monkeypatch.setattr(
        os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace")),
    )
    with pytest.raises(OSError, match="replace"):
        publish_mod._replace_target(target, b"new")
    assert target.read_text("utf-8") == "portable"
    assert tuple(tmp_path.glob("*.publish.tmp")) == ()


def test_publisher_lock_and_target_failures_are_typed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "baseline.json"
    lock = publish_mod._acquire_lock(target)
    with pytest.raises(BaselinePublicationError) as active:
        publish_mod._acquire_lock(target)
    assert active.value.reason == "active_lock"

    other_lock = replace(lock, token="other")
    with pytest.raises(BaselinePublicationError) as ownership:
        publish_mod._release_lock(target, other_lock)
    assert ownership.value.reason == "cas_conflict"
    publish_mod._release_lock(target, lock)
    publish_mod._release_lock(target, lock)

    target.mkdir()
    with pytest.raises(BaselinePublicationError) as invalid_target:
        publish_mod._read_target_bytes(target, max_size_bytes=1024)
    assert invalid_target.value.reason == "invalid_target"


def test_fresh_generated_oversize_is_rejected_before_lock(tmp_path: Path) -> None:
    target = tmp_path / "baseline.json"

    with pytest.raises(BaselinePublicationError) as error:
        publish_baseline(
            target=target,
            bundle=_bundle(),
            scope_id=_SCOPE_ID,
            max_size_bytes=1,
        )

    assert error.value.reason == "oversize"
    assert not target.exists()
    assert not target.with_name(f"{target.name}.publish.lock").exists()


def test_acquire_lock_write_failure_removes_partial_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "baseline.json"

    def _fail_parent_fsync(_path: Path) -> None:
        raise OSError("fsync")

    monkeypatch.setattr(publish_mod, "_fsync_parent", _fail_parent_fsync)
    with pytest.raises(OSError, match="fsync"):
        publish_mod._acquire_lock(target)
    assert not target.with_name(f"{target.name}.publish.lock").exists()


def test_observe_legacy_requires_source_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, _raw, transition = _write_legacy_target(tmp_path)
    fresh_transition = replace(
        transition,
        from_schema=None,
        from_fingerprint=None,
        source_legacy_digest=None,
    )
    monkeypatch.setattr(
        publish_mod,
        "read_legacy_transition",
        lambda *_args, **_kwargs: fresh_transition,
    )

    with pytest.raises(BaselinePublicationError) as error:
        publish_mod._observe_target(
            target,
            max_size_bytes=5_000_000,
            bundle=_bundle(),
        )
    assert error.value.reason == "invalid_target"


def test_observed_legacy_without_evidence_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "baseline.json"
    monkeypatch.setattr(
        publish_mod,
        "_observe_target",
        lambda *_args, **_kwargs: ("legacy", "legacy:lost", None, None, None),
    )

    with pytest.raises(BaselinePublicationError) as error:
        publish_baseline(
            target=target,
            bundle=_bundle(),
            scope_id=_SCOPE_ID,
            max_size_bytes=5_000_000,
        )

    assert error.value.reason == "invalid_target"
    assert not target.with_name(f"{target.name}.publish.lock").exists()


def test_recovery_missing_lock_and_changed_lock_are_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "baseline.json"
    with pytest.raises(BaselinePublicationError) as missing:
        recover_publish_lock(target=target, expected_token="missing")
    assert missing.value.reason == "invalid_lock"

    lock = BaselinePublishLock(
        token="expected",
        pid=999_999,
        hostname=socket.gethostname(),
        process_start="definitely-dead",
        created_at="2026-07-20T00:00:00Z",
    )
    lock_path = _write_lock(target, lock)
    original_fsync_parent = publish_mod._fsync_parent

    def _change_lock_after_guard(path: Path) -> None:
        original_fsync_parent(path)
        if path.name.endswith(".recovery"):
            lock_path.write_bytes(b"changed")

    monkeypatch.setattr(publish_mod, "_fsync_parent", _change_lock_after_guard)
    with pytest.raises(BaselinePublicationError) as changed:
        recover_publish_lock(target=target, expected_token="expected")
    assert changed.value.reason == "cas_conflict"
    assert not target.with_name(f"{target.name}.publish.lock.recovery").exists()


def test_legacy_transition_accepts_a_prior_fingerprint_generation(
    tmp_path: Path,
) -> None:
    """A legacy artifact from an older fingerprint generation still transitions.

    The legacy fixture declares fingerprint "2" because a schema-2.1 artifact
    can only ever carry the generation that wrote it. Requiring it to equal the
    runtime constant made the upgrade path impossible the moment that constant
    moved -- and would do so again at every future cutover -- while proving
    nothing, because the transition imports no lane: it records the prior
    fingerprint as provenance and regenerates every lane from the current run.

    Refusing a legacy artifact as comparison TRUTH is a different question with
    its own owner, ``Baseline.verify_compatibility``, which still raises
    MISMATCH_FINGERPRINT_VERSION. This test pins the split.
    """

    raw = _legacy_bytes()
    legacy_meta = orjson.loads(raw)["meta"]
    # The premise: the fixture really is from an older generation. Read from
    # the fixture bytes rather than compared against a literal, so this stays a
    # runtime check that keeps its meaning at the next cutover instead of a
    # comparison the type checker can settle statically.
    assert legacy_meta["fingerprint_version"] != BASELINE_FINGERPRINT_VERSION, (
        "this test is only meaningful while the runtime generation differs "
        "from the one the legacy fixture declares"
    )
    target = tmp_path / "baseline.json"
    target.write_bytes(raw)

    receipt = publish_baseline(
        target=target,
        bundle=_bundle(),
        scope_id=_SCOPE_ID,
        max_size_bytes=5_000_000,
    )

    assert receipt.backup_created is True
    transition = _read_published(target).container.transition
    assert transition is not None
    # Provenance, not truth: the prior generation is recorded and nothing from
    # the legacy artifact is imported.
    assert transition.from_fingerprint == "2"
    assert transition.imported_lanes == ()

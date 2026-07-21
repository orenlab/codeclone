# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The sole baseline target, CAS, lock, recovery, and receipt owner."""

from __future__ import annotations

import os
import secrets
import socket
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import orjson

from ..contracts.errors import BaselineValidationError
from ..models import (
    BaselineContainerV3,
    BaselinePublicationReceipt,
    BaselinePublishFailureReason,
    BaselinePublishLock,
    BaselinePublishLockInput,
    BaselineTargetKind,
    ContainerReadSuccess,
    EpochTransitionEvidence,
    ObservationBundle,
)
from ..observability import span
from ..utils.atomic_write import validate_atomic_target
from .container import build_container, read_container_v3_bytes
from .container_digest import canonical_container_bytes
from .transition import preserve_legacy_backup, read_legacy_transition


class BaselinePublicationError(RuntimeError):
    def __init__(self, reason: BaselinePublishFailureReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def _lock_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.publish.lock")


def _recovery_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.publish.lock.recovery")


def _process_start(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ("ps", "-o", "lstart=", "-p", str(pid)),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def _new_lock() -> BaselinePublishLock:
    pid = os.getpid()
    process_start = _process_start(pid)
    if process_start is None:
        process_start = f"unavailable:{pid}"
    return BaselinePublishLock(
        token=secrets.token_hex(32),
        pid=pid,
        hostname=socket.gethostname(),
        process_start=process_start,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _lock_bytes(lock: BaselinePublishLock) -> bytes:
    return orjson.dumps(lock, option=orjson.OPT_SORT_KEYS)


def _parse_lock(raw: bytes) -> BaselinePublishLock:
    try:
        value = BaselinePublishLockInput.model_validate_json(raw)
    except ValueError as exc:
        raise BaselinePublicationError("invalid_lock", str(exc)) from exc
    return BaselinePublishLock(
        token=value.token,
        pid=value.pid,
        hostname=value.hostname,
        process_start=value.process_start,
        created_at=value.created_at,
    )


def _target_mode(path: Path) -> int:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        current_umask = os.umask(0)
        try:
            return 0o666 & ~current_umask
        finally:
            os.umask(current_umask)


def _replace_target(target: Path, payload: bytes) -> None:
    """Strongly replace the baseline target; this is the sole target writer."""

    validate_atomic_target(target)
    fd, raw_tmp = tempfile.mkstemp(dir=target.parent, suffix=".publish.tmp")
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), _target_mode(target))
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        _fsync_parent(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _fsync_parent(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path.parent, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _acquire_lock(target: Path) -> BaselinePublishLock:
    path = _lock_path(target)
    validate_atomic_target(path)
    lock = _new_lock()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise BaselinePublicationError(
            "active_lock",
            f"Baseline publication lock already exists: {path}",
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_lock_bytes(lock))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_parent(path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return lock


def _release_lock(target: Path, lock: BaselinePublishLock) -> None:
    path = _lock_path(target)
    try:
        actual = _parse_lock(path.read_bytes())
    except OSError:
        return
    if actual.token != lock.token:
        raise BaselinePublicationError(
            "cas_conflict",
            "Baseline publication lock ownership changed before release.",
        )
    path.unlink()
    _fsync_parent(path)


def _read_target_bytes(target: Path, *, max_size_bytes: int) -> bytes | None:
    try:
        with target.open("rb") as handle:
            raw = handle.read(max_size_bytes + 1)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise BaselinePublicationError("invalid_target", str(exc)) from exc
    if len(raw) > max_size_bytes:
        raise BaselinePublicationError("oversize", "Baseline target exceeds limit.")
    return raw


def _observe_target(
    target: Path,
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
    raw = _read_target_bytes(target, max_size_bytes=max_size_bytes)
    if raw is None:
        return "absent", "absent", None, None, None
    result = read_container_v3_bytes(raw, limit_bytes=max_size_bytes)
    if isinstance(result, ContainerReadSuccess):
        root = result.container.meta.root_digest.value
        return "v3", f"v3:{root}", raw, result.container, result.container.transition
    try:
        transition = read_legacy_transition(
            target,
            raw=raw,
            regenerated_lanes=bundle.contract.enabled_lanes,
        )
    except BaselineValidationError as exc:
        raise BaselinePublicationError("invalid_target", str(exc)) from exc
    legacy_digest = transition.source_legacy_digest
    if legacy_digest is None:
        raise BaselinePublicationError(
            "invalid_target",
            "Authenticated legacy transition lacks its source digest.",
        )
    return "legacy", f"legacy:{legacy_digest.value}", raw, None, transition


def publish_baseline(
    *,
    target: Path,
    bundle: ObservationBundle,
    scope_id: UUID,
    max_size_bytes: int,
) -> BaselinePublicationReceipt:
    """Build and CAS-publish one complete container under one observer span."""

    with span(name="baseline.container.publish") as publish_span:
        try:
            observed_kind, observed_identity, raw, current, transition = (
                _observe_target(
                    target,
                    max_size_bytes=max_size_bytes,
                    bundle=bundle,
                )
            )
            if current is not None and current.baseline_scope_id != scope_id:
                raise BaselinePublicationError(
                    "scope_mismatch",
                    "Existing baseline_scope_id does not match configured scope.",
                )
            container = build_container(bundle, scope_id, transition=transition)
            # Published JSON includes the repository-canonical final newline.
            payload = canonical_container_bytes(container) + b"\n"
            if len(payload) > max_size_bytes:
                raise BaselinePublicationError(
                    "oversize",
                    "Generated baseline container exceeds configured limit.",
                )
            if current is not None and (
                current.meta.root_digest == container.meta.root_digest
            ):
                publish_span.set_counter("baseline_publish_noop", 1)
                return BaselinePublicationReceipt(
                    outcome="noop",
                    observed_kind=observed_kind,
                    observed_identity=observed_identity,
                    published_root_digest=current.meta.root_digest,
                    backup_created=False,
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            lock = _acquire_lock(target)
            backup_created = False
            try:
                reobserved = _observe_target(
                    target,
                    max_size_bytes=max_size_bytes,
                    bundle=bundle,
                )
                if reobserved[1] != observed_identity:
                    publish_span.set_counter("baseline_publish_conflict", 1)
                    raise BaselinePublicationError(
                        "cas_conflict",
                        "Baseline target changed after observation.",
                    )
                if observed_kind == "legacy":
                    legacy_digest = (
                        transition.source_legacy_digest if transition else None
                    )
                    if raw is None or legacy_digest is None:
                        raise BaselinePublicationError(
                            "invalid_target",
                            "Legacy publication lost authenticated evidence.",
                        )
                    backup_created = preserve_legacy_backup(
                        target,
                        raw=raw,
                        digest=legacy_digest,
                    )
                _replace_target(target, payload)
            finally:
                _release_lock(target, lock)
            publish_span.set_counter("baseline_publish_bytes", len(payload))
            publish_span.set_counter("baseline_publish_lanes", len(container.lanes))
            publish_span.set_counter("baseline_publish_fsyncs", 2)
            publish_span.set_counter("baseline_publish_replaced", 1)
            if backup_created:
                publish_span.set_counter("baseline_publish_backups", 1)
            if transition is not None:
                publish_span.set_counter("baseline_publish_transitions", 1)
            return BaselinePublicationReceipt(
                outcome="published",
                observed_kind=observed_kind,
                observed_identity=observed_identity,
                published_root_digest=container.meta.root_digest,
                backup_created=backup_created,
            )
        except BaselinePublicationError:
            publish_span.set_counter("baseline_publish_failure", 1)
            raise


def recover_publish_lock(
    *,
    target: Path,
    expected_token: str,
    force: bool = False,
) -> BaselinePublicationReceipt:
    """Explicitly recover one stale lock; never called by publication itself."""

    path = _lock_path(target)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BaselinePublicationError("invalid_lock", str(exc)) from exc
    try:
        lock = _parse_lock(raw)
    except BaselinePublicationError:
        if not force:
            raise
        lock = None
    if lock is not None:
        if not secrets.compare_digest(lock.token, expected_token):
            raise BaselinePublicationError(
                "cas_conflict",
                "Publication lock token does not match the expected token.",
            )
        local = lock.hostname == socket.gethostname()
        actual_start = _process_start(lock.pid) if local else None
        active = local and actual_start == lock.process_start
        if active:
            raise BaselinePublicationError("active_lock", "Lock owner is still active.")
        if not local and not force:
            raise BaselinePublicationError(
                "foreign_lock",
                "Foreign-host lock recovery requires explicit force.",
            )
    recovery = _recovery_path(target)
    validate_atomic_target(recovery)
    try:
        guard_fd = os.open(
            recovery,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as exc:
        raise BaselinePublicationError(
            "active_lock",
            "Another lock recovery operation is active.",
        ) from exc
    try:
        with os.fdopen(guard_fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_parent(recovery)
        if path.read_bytes() != raw:
            raise BaselinePublicationError(
                "cas_conflict",
                "Publication lock changed during recovery.",
            )
        path.unlink()
        _fsync_parent(path)
    finally:
        recovery.unlink(missing_ok=True)
        _fsync_parent(recovery)
    return BaselinePublicationReceipt(
        outcome="recovered",
        observed_kind="absent",
        observed_identity="lock",
        published_root_digest=None,
        backup_created=False,
    )


__all__ = [
    "BaselinePublicationError",
    "publish_baseline",
    "recover_publish_lock",
]

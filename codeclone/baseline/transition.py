# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Authenticated legacy evidence and immutable backup ownership for 39N."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Sequence
from pathlib import Path

from ..contracts import BASELINE_FINGERPRINT_VERSION
from ..contracts.errors import BaselineValidationError
from ..models import (
    DigestObject,
    EpochTransitionEvidence,
    LegacyBaselineEvidenceInput,
    ObservationLaneName,
)
from ..utils.atomic_write import validate_atomic_target
from .trust import BASELINE_GENERATOR, _compute_payload_sha256

_LEGACY_EVIDENCE_DOMAIN = b"codeclone.baseline.legacy-evidence.v1\0"
_FUNCTION_ID_RE = re.compile(r"^[0-9a-f]{64}\|(?:\d+-\d+|\d+\+)$")
_BLOCK_ID_RE = re.compile(r"^[0-9a-f]{64}\|[0-9a-f]{64}\|[0-9a-f]{64}\|[0-9a-f]{64}$")


def _legacy_digest(raw: bytes) -> DigestObject:
    digest = hashlib.sha256()
    digest.update(_LEGACY_EVIDENCE_DOMAIN)
    digest.update(raw)
    return DigestObject(
        domain="codeclone.baseline.legacy-evidence.v1",
        algorithm="sha256",
        value=digest.hexdigest(),
    )


def read_legacy_transition(
    path: Path,
    *,
    raw: bytes,
    regenerated_lanes: Sequence[ObservationLaneName],
) -> EpochTransitionEvidence:
    """Authenticate exact legacy bytes and project transition-only evidence."""

    try:
        payload = LegacyBaselineEvidenceInput.model_validate_json(raw)
    except ValueError as exc:
        raise BaselineValidationError(
            f"Invalid legacy baseline JSON at {path}: {exc}",
            status="invalid_json",
        ) from exc
    meta = payload.meta
    clones = payload.clones
    if meta.generator.name != BASELINE_GENERATOR:
        raise BaselineValidationError(
            "Legacy baseline generator mismatch.",
            status="generator_mismatch",
        )
    if meta.schema_version != "2.1":
        raise BaselineValidationError(
            "Legacy transition requires authenticated schema 2.1.",
            status="mismatch_schema_version",
        )
    # No fingerprint equality check here, deliberately. A schema-2.1 artifact
    # carries the generation that wrote it, so requiring it to equal the
    # runtime constant made the upgrade path impossible the moment that
    # constant moved, and would do so again at every future cutover. It also
    # proved nothing: this function imports no lane. It authenticates bytes,
    # records the prior fingerprint as provenance and hands back evidence; the
    # caller regenerates every lane from the current run, which is the
    # mandatory-regeneration behaviour a generation change is supposed to have.
    #
    # Refusing a legacy artifact as comparison TRUTH is the other question and
    # keeps its own owner: Baseline.verify_compatibility raises
    # MISMATCH_FINGERPRINT_VERSION before any stored identity is believed.
    if clones.functions != tuple(sorted(set(clones.functions))) or any(
        _FUNCTION_ID_RE.fullmatch(value) is None for value in clones.functions
    ):
        raise BaselineValidationError(
            "Legacy function clone identities are not canonical.",
            status="invalid_type",
        )
    if clones.blocks != tuple(sorted(set(clones.blocks))) or any(
        _BLOCK_ID_RE.fullmatch(value) is None for value in clones.blocks
    ):
        raise BaselineValidationError(
            "Legacy block clone identities are not canonical.",
            status="invalid_type",
        )
    expected_payload = _compute_payload_sha256(
        functions=clones.functions,
        blocks=clones.blocks,
        fingerprint_version=meta.fingerprint_version,
        python_tag=meta.python_tag,
    )
    if not hmac.compare_digest(meta.payload_sha256, expected_payload):
        raise BaselineValidationError(
            "Legacy baseline payload digest mismatch.",
            status="integrity_failed",
        )
    return EpochTransitionEvidence(
        kind="baseline_epoch_transition",
        from_schema=meta.schema_version,
        from_fingerprint=meta.fingerprint_version,
        to_schema="3.0",
        # The migration target is whatever fingerprint generation the current
        # epoch runs: the caller regenerates every lane from the current run,
        # and the published container pins the same constant in its clone-lane
        # contracts. Recording anything else would be false evidence.
        to_fingerprint=BASELINE_FINGERPRINT_VERSION,
        imported_lanes=(),
        regenerated_lanes=tuple(sorted(regenerated_lanes)),
        source_legacy_digest=_legacy_digest(raw),
    )


def legacy_backup_path(target: Path, digest: DigestObject) -> Path:
    return target.with_name(f"{target.name}.v2.{digest.value}.json")


def preserve_legacy_backup(
    target: Path,
    *,
    raw: bytes,
    digest: DigestObject,
) -> bool:
    """Create the immutable transition backup once; never overwrite it."""

    backup = legacy_backup_path(target, digest)
    validate_atomic_target(target)
    validate_atomic_target(backup)
    backup.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        if backup.read_bytes() != raw:
            raise OSError(f"Legacy backup digest collision at {backup}") from exc
        return False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    _fsync_parent(backup)
    return True


def _fsync_parent(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path.parent, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "legacy_backup_path",
    "preserve_legacy_backup",
    "read_legacy_transition",
]

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Clone-lane projection over the sole native BaselineContainer v3 reader."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from ..contracts import BASELINE_FINGERPRINT_VERSION, BASELINE_SCHEMA_VERSION
from ..contracts.errors import BaselineValidationError
from ..models import (
    BaselineContainerV3,
    CloneObservationPayload,
    ContainerReadFailure,
    ContainerReadSuccess,
)
from .container import read_container_v3
from .container_trust import map_container_read_failure, unavailable_container_lanes
from .diff import diff_clone_groups
from .trust import MAX_BASELINE_SIZE_BYTES, BaselineStatus


class Baseline:
    """Read-only clone projection; publication is owned only by publish.py."""

    __slots__ = (
        "blocks",
        "container",
        "created_at",
        "fingerprint_version",
        "functions",
        "generator",
        "generator_version",
        "path",
        "payload_sha256",
        "python_tag",
        "schema_version",
    )

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.functions: set[str] = set()
        self.blocks: set[str] = set()
        self.container: BaselineContainerV3 | None = None
        self.generator: str | None = None
        self.schema_version: str | None = None
        self.fingerprint_version: str | None = None
        self.python_tag: str | None = None
        self.created_at: str | None = None
        self.payload_sha256: str | None = None
        self.generator_version: str | None = None

    def load(self, *, max_size_bytes: int | None = None) -> None:
        if not self.path.exists():
            return
        result = read_container_v3(
            self.path,
            limit_bytes=(
                MAX_BASELINE_SIZE_BYTES if max_size_bytes is None else max_size_bytes
            ),
        )
        if isinstance(result, ContainerReadFailure):
            raise BaselineValidationError(
                result.detail,
                status=map_container_read_failure(
                    result.reason,
                    too_large=BaselineStatus.TOO_LARGE,
                    invalid_json=BaselineStatus.INVALID_JSON,
                    integrity_failed=BaselineStatus.INTEGRITY_FAILED,
                    schema_mismatch=BaselineStatus.MISMATCH_SCHEMA_VERSION,
                    invalid_type=BaselineStatus.INVALID_TYPE,
                ),
            )
        if not isinstance(result, ContainerReadSuccess):
            raise BaselineValidationError(
                "Baseline contains unknown optional lanes and is inspection-only.",
                status=BaselineStatus.INVALID_TYPE,
            )
        container = result.container
        functions = container.lanes["clones.functions"].payload
        blocks = container.lanes["clones.blocks"].payload
        if not isinstance(functions, CloneObservationPayload) or not isinstance(
            blocks, CloneObservationPayload
        ):
            raise BaselineValidationError(
                "Clone lanes have invalid payload types.",
                status=BaselineStatus.INVALID_TYPE,
            )
        self.container = container
        self.functions = set(functions.items)
        self.blocks = set(blocks.items)
        self.generator = container.meta.generator.name
        self.generator_version = container.meta.generator.version
        self.schema_version = container.meta.container_version
        self.fingerprint_version = container.contracts.get(
            "BASELINE_FINGERPRINT_VERSION"
        )
        self.python_tag = container.meta.python_tag
        self.created_at = container.meta.created_at
        self.payload_sha256 = container.meta.root_digest.value

    def verify_compatibility(
        self,
        *,
        current_python_tag: str,
        baseline_scope_id: UUID,
    ) -> None:
        unavailable = unavailable_container_lanes(
            self.container,
            python_tag=current_python_tag,
            baseline_scope_id=baseline_scope_id,
            missing_message="Baseline container is not loaded.",
            missing_status=BaselineStatus.MISSING_FIELDS,
            root_message="Baseline root digest mismatch.",
            integrity_status=BaselineStatus.INTEGRITY_FAILED,
        )
        if unavailable:
            if any(item.reason == "baseline_scope_id" for item in unavailable):
                status = BaselineStatus.MISMATCH_SCOPE_ID
            elif any(item.reason == "python_tag" for item in unavailable):
                status = BaselineStatus.MISMATCH_PYTHON_VERSION
            elif any(item.reason == "required_contract" for item in unavailable):
                status = BaselineStatus.MISMATCH_FINGERPRINT_VERSION
            else:
                status = BaselineStatus.MISMATCH_SCHEMA_VERSION
            reasons = ", ".join(f"{item.name}:{item.reason}" for item in unavailable)
            raise BaselineValidationError(
                f"Baseline lane compatibility failed: {reasons}",
                status=status,
            )
        if self.schema_version != BASELINE_SCHEMA_VERSION:
            raise BaselineValidationError(
                "Baseline schema version mismatch.",
                status=BaselineStatus.MISMATCH_SCHEMA_VERSION,
            )
        if self.fingerprint_version != BASELINE_FINGERPRINT_VERSION:
            raise BaselineValidationError(
                "Baseline fingerprint version mismatch.",
                status=BaselineStatus.MISMATCH_FINGERPRINT_VERSION,
            )

    def diff(
        self,
        func_groups: Mapping[str, object],
        block_groups: Mapping[str, object],
    ) -> tuple[set[str], set[str]]:
        return diff_clone_groups(
            known_functions=self.functions,
            known_blocks=self.blocks,
            func_groups=func_groups,
            block_groups=block_groups,
        )


__all__ = ["Baseline"]

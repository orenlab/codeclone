# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Pure, artifact-neutral contract compatibility decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from ..models import (
    CompatibilityPolicy,
    CompatibilityStatus,
    CompatibilityVerdict,
    ContractVerdict,
)

LEGACY_COMPATIBILITY_OWNERS: Final[tuple[tuple[str, str], ...]] = (
    ("codeclone.cache.store.Cache._load_and_validate", "39J"),
    ("codeclone.baseline.clone_baseline.CloneBaseline.verify_compatibility", "39M"),
    ("codeclone.baseline.metrics_baseline.MetricsBaseline.verify_compatibility", "39O"),
    ("codeclone.memory.schema.ensure_schema/validate_schema_readonly", "39Q"),
)

_STATUS_PRIORITY: Final[dict[CompatibilityStatus, int]] = {
    "compatible": 0,
    "migration_required": 1,
    "incompatible": 2,
    "unknown_contract": 3,
}


def _contract_verdict(
    *,
    contract: str,
    required: str,
    actual: str | None,
    policy: CompatibilityPolicy | None,
) -> ContractVerdict:
    if policy is None:
        status: CompatibilityStatus = "unknown_contract"
    elif actual is None:
        status = "incompatible"
    elif policy.kind == "exact":
        status = "compatible" if actual == required else "incompatible"
    elif policy.kind == "supported_versions":
        status = "compatible" if actual in policy.supported else "incompatible"
    elif actual == required:
        status = "compatible"
    elif actual in policy.supported:
        status = "migration_required"
    else:
        status = "incompatible"
    return ContractVerdict(
        contract=contract,
        required=required,
        actual=actual,
        status=status,
        compatible=status == "compatible",
    )


def check_contract_compatibility(
    required: Mapping[str, str],
    actual: Mapping[str, str],
    policies: Mapping[str, CompatibilityPolicy],
) -> CompatibilityVerdict:
    """Return a sorted, fail-closed compatibility verdict without IO."""

    per_contract = tuple(
        _contract_verdict(
            contract=contract,
            required=required[contract],
            actual=actual.get(contract),
            policy=policies.get(contract),
        )
        for contract in sorted(required)
    )
    status: CompatibilityStatus = "compatible"
    for item in per_contract:
        if _STATUS_PRIORITY[item.status] > _STATUS_PRIORITY[status]:
            status = item.status
    return CompatibilityVerdict(
        status=status,
        compatible=status == "compatible",
        per_contract=per_contract,
    )


__all__ = [
    "LEGACY_COMPATIBILITY_OWNERS",
    "CompatibilityPolicy",
    "CompatibilityVerdict",
    "ContractVerdict",
    "check_contract_compatibility",
]

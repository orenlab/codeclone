# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import sys
from enum import Enum
from typing import TYPE_CHECKING, Final

import orjson

from ..contracts import DEFAULT_MAX_BASELINE_SIZE_MB

if TYPE_CHECKING:
    from collections.abc import Collection

BASELINE_GENERATOR = "codeclone"
MAX_BASELINE_SIZE_BYTES = DEFAULT_MAX_BASELINE_SIZE_MB * 1024 * 1024


class BaselineStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    TOO_LARGE = "too_large"
    INVALID_JSON = "invalid_json"
    INVALID_TYPE = "invalid_type"
    MISSING_FIELDS = "missing_fields"
    MISMATCH_SCHEMA_VERSION = "mismatch_schema_version"
    MISMATCH_FINGERPRINT_VERSION = "mismatch_fingerprint_version"
    MISMATCH_PYTHON_VERSION = "mismatch_python_version"
    MISMATCH_SCOPE_ID = "mismatch_scope_id"
    GENERATOR_MISMATCH = "generator_mismatch"
    INTEGRITY_MISSING = "integrity_missing"
    INTEGRITY_FAILED = "integrity_failed"


BASELINE_UNTRUSTED_STATUSES: Final[frozenset[BaselineStatus]] = frozenset(
    {
        BaselineStatus.MISSING,
        BaselineStatus.TOO_LARGE,
        BaselineStatus.INVALID_JSON,
        BaselineStatus.INVALID_TYPE,
        BaselineStatus.MISSING_FIELDS,
        BaselineStatus.MISMATCH_SCHEMA_VERSION,
        BaselineStatus.MISMATCH_FINGERPRINT_VERSION,
        BaselineStatus.MISMATCH_PYTHON_VERSION,
        BaselineStatus.MISMATCH_SCOPE_ID,
        BaselineStatus.GENERATOR_MISMATCH,
        BaselineStatus.INTEGRITY_MISSING,
        BaselineStatus.INTEGRITY_FAILED,
    }
)


def coerce_baseline_status(
    raw_status: str | BaselineStatus | None,
) -> BaselineStatus:
    if isinstance(raw_status, BaselineStatus):
        return raw_status
    if isinstance(raw_status, str):
        try:
            return BaselineStatus(raw_status)
        except ValueError:
            return BaselineStatus.INVALID_TYPE
    return BaselineStatus.INVALID_TYPE


def _compute_payload_sha256(
    *,
    functions: Collection[str],
    blocks: Collection[str],
    fingerprint_version: str,
    python_tag: str,
) -> str:
    canonical = {
        "blocks": sorted(blocks),
        "fingerprint_version": fingerprint_version,
        "functions": sorted(functions),
        "python_tag": python_tag,
    }
    serialized = orjson.dumps(canonical, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(serialized).hexdigest()


def current_python_tag() -> str:
    """Return the interpreter compatibility tag as an immutable string."""
    impl = sys.implementation.name
    major, minor = sys.version_info[:2]
    prefix = "cp" if impl == "cpython" else impl[:2]
    return f"{prefix}{major}{minor}"


__all__ = [
    "BASELINE_GENERATOR",
    "BASELINE_UNTRUSTED_STATUSES",
    "MAX_BASELINE_SIZE_BYTES",
    "BaselineStatus",
    "_compute_payload_sha256",
    "coerce_baseline_status",
    "current_python_tag",
]

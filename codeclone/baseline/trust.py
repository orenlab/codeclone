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
from ..contracts import trust_vocabulary as trust_words

if TYPE_CHECKING:
    from collections.abc import Collection

BASELINE_GENERATOR = "codeclone"
MAX_BASELINE_SIZE_BYTES = DEFAULT_MAX_BASELINE_SIZE_MB * 1024 * 1024


class BaselineStatus(str, Enum):
    """The clone-baseline file status; its words are the shared trust owner's."""

    OK = trust_words.BASELINE_STATUS_OK
    MISSING = trust_words.BASELINE_STATUS_MISSING
    TOO_LARGE = trust_words.BASELINE_STATUS_TOO_LARGE
    INVALID_JSON = trust_words.BASELINE_STATUS_INVALID_JSON
    INVALID_TYPE = trust_words.BASELINE_STATUS_INVALID_TYPE
    MISSING_FIELDS = trust_words.BASELINE_STATUS_MISSING_FIELDS
    MISMATCH_SCHEMA_VERSION = trust_words.BASELINE_STATUS_MISMATCH_SCHEMA_VERSION
    MISMATCH_FINGERPRINT_VERSION = (
        trust_words.BASELINE_STATUS_MISMATCH_FINGERPRINT_VERSION
    )
    MISMATCH_PYTHON_VERSION = trust_words.BASELINE_STATUS_MISMATCH_PYTHON_VERSION
    MISMATCH_SCOPE_ID = trust_words.BASELINE_STATUS_MISMATCH_SCOPE_ID
    GENERATOR_MISMATCH = trust_words.BASELINE_STATUS_GENERATOR_MISMATCH
    INTEGRITY_MISSING = trust_words.BASELINE_STATUS_INTEGRITY_MISSING
    INTEGRITY_FAILED = trust_words.BASELINE_STATUS_INTEGRITY_FAILED


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

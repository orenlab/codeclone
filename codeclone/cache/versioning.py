# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TypedDict

from ..contracts import CACHE_VERSION, DEFAULT_MAX_CACHE_SIZE_MB
from ..models import CacheEntryV3

MAX_CACHE_SIZE_BYTES = DEFAULT_MAX_CACHE_SIZE_MB * 1024 * 1024
LEGACY_CACHE_SECRET_FILENAME = ".cache_secret"
_DEFAULT_WIRE_UNIT_FLOW_PROFILES = (
    0,
    "none",
    False,
    "fallthrough",
    "none",
    "none",
)


class CacheStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    TOO_LARGE = "too_large"
    UNREADABLE = "unreadable"
    INVALID_JSON = "invalid_json"
    INVALID_TYPE = "invalid_type"
    VERSION_MISMATCH = "version_mismatch"
    PYTHON_TAG_MISMATCH = "python_tag_mismatch"
    FINGERPRINT_MISMATCH = "mismatch_fingerprint_version"
    INTEGRITY_FAILED = "integrity_failed"


class CacheData(TypedDict):
    version: str
    python_tag: str
    fingerprint_version: str
    files: dict[str, CacheEntryV3]


def _empty_cache_data(
    *,
    version: str = CACHE_VERSION,
    python_tag: str,
    fingerprint_version: str,
) -> CacheData:
    return CacheData(
        version=version,
        python_tag=python_tag,
        fingerprint_version=fingerprint_version,
        files={},
    )


def _resolve_root(root: str | Path | None) -> Path | None:
    if root is None:
        return None
    try:
        return Path(root).resolve(strict=False)
    except OSError:
        return None


__all__ = [
    "CACHE_VERSION",
    "LEGACY_CACHE_SECRET_FILENAME",
    "MAX_CACHE_SIZE_BYTES",
    "_DEFAULT_WIRE_UNIT_FLOW_PROFILES",
    "CacheData",
    "CacheStatus",
    "_empty_cache_data",
    "_resolve_root",
]

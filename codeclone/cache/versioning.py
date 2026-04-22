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
from ..contracts.schemas import AnalysisProfile
from .entries import CacheEntry
from .integrity import as_int_or_none, as_str_dict

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
    ANALYSIS_PROFILE_MISMATCH = "analysis_profile_mismatch"
    INTEGRITY_FAILED = "integrity_failed"


class CacheData(TypedDict):
    version: str
    python_tag: str
    fingerprint_version: str
    analysis_profile: AnalysisProfile
    files: dict[str, CacheEntry]


def _empty_cache_data(
    *,
    version: str = CACHE_VERSION,
    python_tag: str,
    fingerprint_version: str,
    analysis_profile: AnalysisProfile,
) -> CacheData:
    return CacheData(
        version=version,
        python_tag=python_tag,
        fingerprint_version=fingerprint_version,
        analysis_profile=analysis_profile,
        files={},
    )


def _as_analysis_profile(value: object) -> AnalysisProfile | None:
    obj = as_str_dict(value)
    if obj is None:
        return None

    required = {
        "min_loc",
        "min_stmt",
        "block_min_loc",
        "block_min_stmt",
        "segment_min_loc",
        "segment_min_stmt",
    }
    if set(obj.keys()) < required:
        return None

    min_loc = as_int_or_none(obj.get("min_loc"))
    min_stmt = as_int_or_none(obj.get("min_stmt"))
    block_min_loc = as_int_or_none(obj.get("block_min_loc"))
    block_min_stmt = as_int_or_none(obj.get("block_min_stmt"))
    segment_min_loc = as_int_or_none(obj.get("segment_min_loc"))
    segment_min_stmt = as_int_or_none(obj.get("segment_min_stmt"))
    collect_api_surface_raw = obj.get("collect_api_surface", False)
    collect_api_surface = (
        collect_api_surface_raw if isinstance(collect_api_surface_raw, bool) else None
    )
    if (
        min_loc is None
        or min_stmt is None
        or block_min_loc is None
        or block_min_stmt is None
        or segment_min_loc is None
        or segment_min_stmt is None
        or collect_api_surface is None
    ):
        return None

    return AnalysisProfile(
        min_loc=min_loc,
        min_stmt=min_stmt,
        block_min_loc=block_min_loc,
        block_min_stmt=block_min_stmt,
        segment_min_loc=segment_min_loc,
        segment_min_stmt=segment_min_stmt,
        collect_api_surface=collect_api_surface,
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
    "AnalysisProfile",
    "CacheData",
    "CacheStatus",
    "_as_analysis_profile",
    "_empty_cache_data",
    "_resolve_root",
]

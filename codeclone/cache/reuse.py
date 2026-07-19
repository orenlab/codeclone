# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Single source-content hit authority for cache reuse."""

from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter_ns
from typing import Literal

import orjson

from ..baseline.trust import current_python_tag
from ..contracts import API_SURFACE_SIGNATURE_VERSION
from ..models import (
    CacheEntryV3,
    CacheLaneVerdict,
    CacheReuseDecision,
    ContentIdentityVerdict,
    DigestObject,
    FileStat,
    GitBlobIdentity,
    GitContentSnapshot,
)

_NEUTRAL_PROFILE_DOMAIN = b"codeclone.cache.profile.neutral.v1\x00"
_DEPENDENT_PROFILE_DOMAIN = b"codeclone.cache.profile.dependent.v1\x00"


def _profile_digest(
    *,
    domain: Literal[
        "codeclone.cache.profile.neutral.v1",
        "codeclone.cache.profile.dependent.v1",
    ],
    tag: bytes,
    payload: object,
) -> DigestObject:
    canonical = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return DigestObject(
        domain=domain,
        algorithm="sha256",
        value=hashlib.sha256(tag + canonical).hexdigest(),
    )


def build_module_neutral_profile(
    *,
    fingerprint_version: str,
    min_loc: int,
    min_stmt: int,
    block_min_loc: int,
    block_min_stmt: int,
    segment_min_loc: int,
    segment_min_stmt: int,
) -> DigestObject:
    return _profile_digest(
        domain="codeclone.cache.profile.neutral.v1",
        tag=_NEUTRAL_PROFILE_DOMAIN,
        payload={
            "fingerprint_version": fingerprint_version,
            "block_min_loc": block_min_loc,
            "block_min_stmt": block_min_stmt,
            "min_loc": min_loc,
            "min_stmt": min_stmt,
            "normalization": "ast-normalizer-v2",
            "parser": "python-ast",
            "python_tag": current_python_tag(),
            "segment_algorithm": "stmt-window-v1",
            "segment_min_loc": segment_min_loc,
            "segment_min_stmt": segment_min_stmt,
            "unit_algorithm": "cfg-fingerprint-v2",
        },
    )


def build_module_dependent_profile(
    *,
    neutral_profile: DigestObject,
    module_manifest_digest: DigestObject,
    collect_api_surface: bool,
) -> DigestObject:
    return _profile_digest(
        domain="codeclone.cache.profile.dependent.v1",
        tag=_DEPENDENT_PROFILE_DOMAIN,
        payload={
            "api_surface": collect_api_surface,
            "api_surface_signature_version": API_SURFACE_SIGNATURE_VERSION,
            "call_resolution_version": "1",
            "module_manifest_digest": module_manifest_digest.value,
            "neutral_profile": neutral_profile.value,
            "resolver_version": "2",
        },
    )


def cache_reuse_decision(
    *,
    content: ContentIdentityVerdict,
    entry: CacheEntryV3,
    neutral_profile: DigestObject,
    dependent_profile: DigestObject,
) -> CacheReuseDecision:
    if not content.hit:
        miss = CacheLaneVerdict(hit=False, reason="content_miss")
        return CacheReuseDecision(neutral=miss, dependent=miss)
    neutral_hit = entry.module_neutral_profile == neutral_profile
    dependent_hit = entry.module_dependent_profile == dependent_profile
    return CacheReuseDecision(
        neutral=CacheLaneVerdict(
            hit=neutral_hit,
            reason="hit" if neutral_hit else "neutral_profile_mismatch",
        ),
        dependent=CacheLaneVerdict(
            hit=dependent_hit,
            reason="hit" if dependent_hit else "dependent_profile_mismatch",
        ),
    )


def source_content_digest(raw_source: bytes) -> DigestObject:
    return DigestObject(
        domain="codeclone.source-content.v1",
        algorithm="sha256",
        value=hashlib.sha256(raw_source).hexdigest(),
    )


def git_blob_identity_for_parsed_source(
    *,
    path: Path,
    source_digest: DigestObject,
    git_snapshot: GitContentSnapshot,
) -> GitBlobIdentity | None:
    tracked = git_snapshot.tracked_content(path)
    if tracked is None or git_snapshot.fallback_reason(path) is not None:
        return None
    if tracked.source_content_digest != source_digest:
        return None
    return tracked.blob


def prove_cached_source_identity(
    *,
    path: Path,
    entry: CacheEntryV3,
    current_stat: FileStat,
    git_snapshot: GitContentSnapshot,
) -> ContentIdentityVerdict:
    """Prove one hit from current bytes; envelope/stat alone never authorize it."""

    if current_stat != entry.stat:
        return ContentIdentityVerdict(
            hit=False,
            reason="stat_mismatch",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=True,
        )

    fallback_reason = git_snapshot.fallback_reason(path)
    tracked = git_snapshot.tracked_content(path)
    expected_blob = entry.git_blob_id_at_write
    if (
        fallback_reason is None
        and tracked is not None
        and expected_blob is not None
        and tracked.blob == expected_blob
    ):
        return ContentIdentityVerdict(
            hit=True,
            reason="blob_hit",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=False,
        )

    started = perf_counter_ns()
    try:
        current_digest = source_content_digest(path.read_bytes())
    except OSError:
        current_digest = None
    elapsed_us = max(0, (perf_counter_ns() - started) // 1_000)
    hit = current_digest is not None and current_digest == entry.source_content_digest
    return ContentIdentityVerdict(
        hit=hit,
        reason="digest_hit" if hit else "digest_miss",
        git_fallback_reason=fallback_reason,
        digest_verify_cost_us=elapsed_us,
        stat_fast_reject=False,
    )


__all__ = [
    "build_module_dependent_profile",
    "build_module_neutral_profile",
    "cache_reuse_decision",
    "git_blob_identity_for_parsed_source",
    "prove_cached_source_identity",
    "source_content_digest",
]

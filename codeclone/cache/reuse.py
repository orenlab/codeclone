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
from ..contracts import API_SURFACE_SIGNATURE_VERSION, LIVENESS_POLICY_VERSION
from ..models import (
    CacheEntryV3,
    CacheLaneReuseReason,
    CacheLaneVerdict,
    CacheReuseDecision,
    ContentIdentityVerdict,
    DigestObject,
    FileStat,
    GitBlobIdentity,
    GitContentSnapshot,
    PythonModuleIdentity,
)

_BINDING_CONTEXT_DOMAIN = b"codeclone.cache.binding-context.v1\x00"
_NEUTRAL_PROFILE_DOMAIN = b"codeclone.cache.profile.neutral.v1\x00"
_DEPENDENT_PROFILE_DOMAIN = b"codeclone.cache.profile.dependent.v1\x00"
_DEPENDENCY_OBSERVATION_REVISION = "2"


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
            # v3 (39Y Y5): unit facts are emitted for every defined function
            # instead of only clone-eligible ones. Entries written by v2 carry
            # the smaller population, so they must not be reused as-is.
            "unit_algorithm": "cfg-fingerprint-v3",
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
            "dependency_observation_revision": _DEPENDENCY_OBSERVATION_REVISION,
            # The dependent lane carries referenced_qualnames, dead candidates
            # and live-root reasons - everything the liveness verdict reads -
            # so a liveness policy bump must miss exactly this lane, never the
            # neutral fingerprint lane.
            "liveness_policy_version": LIVENESS_POLICY_VERSION,
            "module_manifest_digest": module_manifest_digest.value,
            "neutral_profile": neutral_profile.value,
            "resolver_version": "2",
        },
    )


def binding_context_digest(module: PythonModuleIdentity | None) -> DigestObject:
    """Digest the binding-context inputs that are not in the file's own bytes.

    Every binding fact the scope graph needs is read from the source itself,
    with one exception: a relative import resolves through the importing
    module's package position. Move the same bytes to a different mount and the
    resolved identity changes, so the fingerprint changes while the content
    digest does not. That difference has to be part of the cache key, or a warm
    run answers with the other mount's fingerprint (39Y-FP section 3a).
    """

    payload: object = (
        None
        if module is None
        else {
            "is_package": module.is_package,
            "module": module.module,
            "mount_path": module.mount_path,
            "package": module.package,
        }
    )
    canonical = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return DigestObject(
        domain="codeclone.cache.binding-context.v1",
        algorithm="sha256",
        value=hashlib.sha256(_BINDING_CONTEXT_DOMAIN + canonical).hexdigest(),
    )


def cache_reuse_decision(
    *,
    content: ContentIdentityVerdict,
    entry: CacheEntryV3,
    neutral_profile: DigestObject,
    dependent_profile: DigestObject,
    binding_context: DigestObject,
) -> CacheReuseDecision:
    if not content.hit:
        miss = CacheLaneVerdict(hit=False, reason="content_miss")
        return CacheReuseDecision(neutral=miss, dependent=miss)
    # The neutral lane carries the units, and a unit's fingerprint is a
    # function of (AST x binding context). The same bytes under a moved mount
    # describe a different function, so the binding context gates this lane
    # beside the profile. The dependent lane already keys on the whole module
    # manifest, which moves whenever any module identity does.
    binding_hit = entry.binding_context_digest == binding_context
    neutral_hit = entry.module_neutral_profile == neutral_profile and binding_hit
    dependent_hit = entry.module_dependent_profile == dependent_profile
    neutral_reason: CacheLaneReuseReason = "hit"
    if not binding_hit:
        neutral_reason = "binding_context_mismatch"
    elif not neutral_hit:
        neutral_reason = "neutral_profile_mismatch"
    return CacheReuseDecision(
        neutral=CacheLaneVerdict(hit=neutral_hit, reason=neutral_reason),
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
    "binding_context_digest",
    "build_module_dependent_profile",
    "build_module_neutral_profile",
    "cache_reuse_decision",
    "git_blob_identity_for_parsed_source",
    "prove_cached_source_identity",
    "source_content_digest",
]

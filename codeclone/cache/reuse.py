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

from ..models import (
    ContentIdentityVerdict,
    DigestObject,
    GitBlobIdentity,
    GitContentSnapshot,
)
from .entries import CacheEntry, FileStat


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
    entry: CacheEntry,
    current_stat: FileStat,
    git_snapshot: GitContentSnapshot,
) -> ContentIdentityVerdict:
    """Prove one hit from current bytes; envelope/stat alone never authorize it."""

    if current_stat != entry["stat"]:
        return ContentIdentityVerdict(
            hit=False,
            reason="stat_mismatch",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=True,
        )

    fallback_reason = git_snapshot.fallback_reason(path)
    tracked = git_snapshot.tracked_content(path)
    expected_blob = entry["git_blob_id_at_write"]
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
    hit = (
        current_digest is not None and current_digest == entry["source_content_digest"]
    )
    return ContentIdentityVerdict(
        hit=hit,
        reason="digest_hit" if hit else "digest_miss",
        git_fallback_reason=fallback_reason,
        digest_verify_cost_us=elapsed_us,
        stat_fast_reject=False,
    )


__all__ = [
    "git_blob_identity_for_parsed_source",
    "prove_cached_source_identity",
    "source_content_digest",
]

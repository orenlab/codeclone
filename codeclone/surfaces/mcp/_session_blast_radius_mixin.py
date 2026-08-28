# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from ...api.memory import blast_radius_cache_limit
from . import _session_helpers as _helpers
from ._blast_radius import (
    DEFAULT_BLAST_RADIUS_INCLUDE,
    DEFAULT_DO_NOT_TOUCH_PATTERNS,
    VALID_BLAST_RADIUS_DEPTHS,
    VALID_BLAST_RADIUS_INCLUDE,
    BlastRadiusDepth,
    BlastRadiusResult,
    blast_radius_to_payload,
    compute_blast_radius,
)
from ._session_finding_mixin import _MCPSessionFindingMixin, _StateLock
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunRecord,
    MCPServiceContractError,
)

#: Identity of one cached blast-radius answer:
#: ``(root, run_id, files, depth, forbidden, allowed_scope)``.
#:
#: ``root`` leads for the same reason ``run_store_key`` puts it in the store
#: key: run ids are content-addressed, so two checkouts at one commit present
#: the same id to one session, and the store already refuses to resolve such
#: an id without a root. A cache keyed on the bare id has no such refusal --
#: it simply answers one root's question with the other root's dependency
#: graph. Root is a correctness boundary here first, and the quota partition
#: second. It is stored resolved, matching ``run_store_key``: one checkout
#: reached under an alias is one partition, not two.
BlastRadiusCacheKey = tuple[
    str,
    str,
    tuple[str, ...],
    str,
    tuple[str, ...],
    tuple[str, ...],
]
BlastRadiusCache = dict[BlastRadiusCacheKey, BlastRadiusResult]

#: Every consumer names the slot it reads through these, never a bare index.
#: A bare index is how the previous shape broke: the pruner read slot 0 as a
#: run id, and it kept reading slot 0 after the meaning of slot 0 changed.
BLAST_RADIUS_CACHE_KEY_ROOT = 0
BLAST_RADIUS_CACHE_KEY_RUN_ID = 1


def _finding_session(
    session: _MCPSessionBlastRadiusMixin,
) -> _MCPSessionFindingMixin:
    return cast(_MCPSessionFindingMixin, session)


class _MCPSessionBlastRadiusMixin:
    _runs: CodeCloneMCPRunStore
    _state_lock: _StateLock
    _blast_radius_cache: BlastRadiusCache

    def get_blast_radius(
        self,
        *,
        files: Sequence[str],
        run_id: str | None = None,
        depth: str = "direct",
        include: Sequence[str] | None = None,
    ) -> dict[str, object]:
        record = self._runs.resolve_any_root(run_id)
        normalized_depth = self._validated_blast_radius_depth(depth)
        normalized_files = _finding_session(self)._normalize_changed_paths(
            root_path=record.root,
            paths=files,
        )
        if not normalized_files:
            raise MCPServiceContractError(
                "get_blast_radius requires at least one file."
            )
        normalized_include = self._validated_blast_radius_include(include)
        result = self._blast_radius_result(
            record=record,
            files=normalized_files,
            depth=normalized_depth,
        )
        return blast_radius_to_payload(result, include=normalized_include)

    def _blast_radius_result(
        self,
        *,
        record: MCPRunRecord,
        files: Sequence[str],
        depth: BlastRadiusDepth,
        forbidden_patterns: Sequence[str] = DEFAULT_DO_NOT_TOUCH_PATTERNS,
        allowed_scope: Sequence[str] = (),
    ) -> BlastRadiusResult:
        normalized_files = tuple(sorted(set(files)))
        default_forbidden = set(DEFAULT_DO_NOT_TOUCH_PATTERNS)
        normalized_forbidden = tuple(
            sorted(set(forbidden_patterns).difference(default_forbidden))
        )
        normalized_allowed_scope = tuple(sorted(set(allowed_scope)))
        cache_key: BlastRadiusCacheKey = (
            str(record.root.resolve()),
            record.run_id,
            normalized_files,
            depth,
            normalized_forbidden,
            normalized_allowed_scope,
        )
        with self._state_lock:
            cached = self._blast_radius_cache.get(cache_key)
            if cached is not None:
                self._blast_radius_cache.pop(cache_key, None)
                self._blast_radius_cache[cache_key] = cached
        if cached is not None:
            return cached
        result = compute_blast_radius(
            run_id=_helpers._short_run_id(record.run_id),
            report_document=record.report_document,
            files=normalized_files,
            depth=depth,
            forbidden_patterns=normalized_forbidden,
            allowed_scope=normalized_allowed_scope,
        )
        limit = blast_radius_cache_limit(root_path=record.root)
        with self._state_lock:
            self._retain_in_partition(cache_key, result, limit=limit)
        return result

    def _retain_in_partition(
        self,
        cache_key: BlastRadiusCacheKey,
        result: BlastRadiusResult,
        *,
        limit: int,
    ) -> None:
        """Retain *result* within this root's own quota. Call under the lock.

        Insertion order is the LRU order, so filtering it by root yields this
        root's partition oldest-first. Entries belonging to other roots are
        never candidates for eviction. A non-positive bound is a configured
        refusal to retain: the partition is emptied and nothing is stored.
        """

        root = cache_key[BLAST_RADIUS_CACHE_KEY_ROOT]
        partition = [
            key
            for key in self._blast_radius_cache
            if key[BLAST_RADIUS_CACHE_KEY_ROOT] == root
        ]
        while partition and len(partition) >= limit:
            self._blast_radius_cache.pop(partition.pop(0), None)
        if limit > 0:
            self._blast_radius_cache[cache_key] = result

    def _validated_blast_radius_depth(self, depth: str) -> BlastRadiusDepth:
        if depth not in VALID_BLAST_RADIUS_DEPTHS:
            expected = ", ".join(sorted(VALID_BLAST_RADIUS_DEPTHS))
            raise MCPServiceContractError(
                f"Invalid value for depth: {depth!r}. Expected one of: {expected}."
            )
        return "transitive" if depth == "transitive" else "direct"

    def _validated_blast_radius_include(
        self,
        include: Sequence[str] | None,
    ) -> tuple[str, ...]:
        if include is None:
            return DEFAULT_BLAST_RADIUS_INCLUDE
        invalid = sorted(
            {item for item in include if item not in VALID_BLAST_RADIUS_INCLUDE}
        )
        if invalid:
            expected = ", ".join(sorted(VALID_BLAST_RADIUS_INCLUDE))
            raise MCPServiceContractError(
                "Invalid value for include: "
                f"{', '.join(invalid)}. Expected values: {expected}."
            )
        return tuple(sorted(set(include)))


__all__ = [
    "BLAST_RADIUS_CACHE_KEY_ROOT",
    "BLAST_RADIUS_CACHE_KEY_RUN_ID",
    "BlastRadiusCache",
    "BlastRadiusCacheKey",
    "_MCPSessionBlastRadiusMixin",
]

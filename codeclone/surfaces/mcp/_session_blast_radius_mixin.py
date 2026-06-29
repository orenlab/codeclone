# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence

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
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunRecord,
    MCPServiceContractError,
)

MAX_BLAST_RADIUS_CACHE_ENTRIES = 64


class _MCPSessionBlastRadiusMixin:
    _runs: CodeCloneMCPRunStore
    _blast_radius_cache: dict[
        tuple[str, tuple[str, ...], str, tuple[str, ...], tuple[str, ...]],
        BlastRadiusResult,
    ]

    def get_blast_radius(
        self,
        *,
        files: Sequence[str],
        run_id: str | None = None,
        depth: str = "direct",
        include: Sequence[str] | None = None,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        normalized_depth = self._validated_blast_radius_depth(depth)
        normalized_files = self._normalize_changed_paths(
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
        cache_key = (
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
        with self._state_lock:
            while len(self._blast_radius_cache) >= MAX_BLAST_RADIUS_CACHE_ENTRIES:
                self._blast_radius_cache.pop(next(iter(self._blast_radius_cache)))
            self._blast_radius_cache[cache_key] = result
        return result

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


__all__ = ["_MCPSessionBlastRadiusMixin"]

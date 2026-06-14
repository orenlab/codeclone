# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""MCP implementation-context query surface."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

from ...utils.repo_paths import RepoPathError, resolve_repo_relative_path
from . import _session_helpers as _helpers
from ._blast_radius import BlastRadiusResult, blast_radius_to_payload
from ._implementation_context import (
    DEFAULT_IMPLEMENTATION_FACETS,
    build_implementation_context,
)
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunRecord,
    MCPServiceContractError,
)
from .messages.params import VALID_FACETS, Facet

_VALID_CONTEXT_MODES = frozenset({"implementation", "impact", "contract"})
_VALID_CONTEXT_DETAIL_LEVELS = frozenset({"compact", "normal", "full"})
_MAX_CONTEXT_BUDGET = 200
_MAX_CONTEXT_DEPTH = 3


class _ContextSessionDependencies(Protocol):
    def _blast_radius_result(
        self,
        *,
        record: MCPRunRecord,
        files: Sequence[str],
        depth: str,
    ) -> BlastRadiusResult: ...

    def _latest_run_for_root(self, root_path: Path) -> MCPRunRecord | None: ...


class _MCPSessionContextMixin:
    _runs: CodeCloneMCPRunStore

    def get_implementation_context(
        self,
        *,
        root: str,
        paths: Sequence[str] | None = None,
        symbols: Sequence[str] | None = None,
        intent_id: str | None = None,
        changed_scope: bool = False,
        mode: str = "implementation",
        include: Sequence[str] | None = None,
        depth: int = 1,
        detail_level: str = "compact",
        budget: int = 50,
        run_id: str | None = None,
    ) -> dict[str, object]:
        root_path = _helpers._resolve_root(root)
        record = self._context_record(root_path=root_path, run_id=run_id)
        if record is None:
            return {
                "status": "needs_analysis",
                "root": str(root_path),
                "message": (
                    "No MCP analysis run exists for this repository root. "
                    "Run analyze_repository first."
                ),
                "next_tool": "analyze_repository",
            }
        self._validate_context_request(
            paths=paths,
            symbols=symbols,
            intent_id=intent_id,
            changed_scope=changed_scope,
            mode=mode,
            include=include,
            depth=depth,
            detail_level=detail_level,
            budget=budget,
        )
        normalized_paths = self._normalize_context_paths(
            root_path=root_path,
            paths=paths or (),
        )
        if not normalized_paths:
            return {
                "status": "no_current_work",
                "root": str(root_path),
                "analysis": {
                    "run_id": record.run_id,
                    "report_digest": record.run_id,
                },
                "message": (
                    "Step 2 requires explicit paths. Subject inference, symbols, "
                    "intent scope, and changed_scope ship in later steps."
                ),
            }
        normalized_include = self._validated_context_include(include)
        session = cast("_ContextSessionDependencies", self)
        blast_result = session._blast_radius_result(
            record=record,
            files=normalized_paths,
            depth="transitive" if depth > 1 else "direct",
        )
        return build_implementation_context(
            record=record,
            paths=normalized_paths,
            include=normalized_include,
            depth=depth,
            detail_level=detail_level,
            budget=budget,
            blast_radius=blast_radius_to_payload(blast_result),
        )

    def _context_record(
        self,
        *,
        root_path: Path,
        run_id: str | None,
    ) -> MCPRunRecord | None:
        if run_id is None:
            session = cast("_ContextSessionDependencies", self)
            return session._latest_run_for_root(root_path)
        record = self._runs.get(run_id)
        if record.root.resolve() != root_path.resolve():
            raise MCPServiceContractError(
                "Selected MCP run does not belong to the supplied root. "
                f"Run root: {record.root}; requested root: {root_path}."
            )
        return record

    def _validate_context_request(
        self,
        *,
        paths: Sequence[str] | None,
        symbols: Sequence[str] | None,
        intent_id: str | None,
        changed_scope: bool,
        mode: str,
        include: Sequence[str] | None,
        depth: int,
        detail_level: str,
        budget: int,
    ) -> None:
        if changed_scope and (paths or symbols):
            raise MCPServiceContractError(
                "changed_scope=true is mutually exclusive with explicit "
                "paths or symbols."
            )
        for field_name, value, choices in (
            ("mode", mode, _VALID_CONTEXT_MODES),
            ("detail_level", detail_level, _VALID_CONTEXT_DETAIL_LEVELS),
        ):
            if value in choices:
                continue
            expected = ", ".join(sorted(choices))
            raise MCPServiceContractError(
                f"Invalid context {field_name} {value!r}. Expected one of: {expected}."
            )
        if mode != "implementation":
            raise MCPServiceContractError(
                f"Context mode {mode!r} is not available until its owning phase."
            )
        if symbols:
            raise MCPServiceContractError(
                "Symbol subjects are not available until Phase 30 Step 4."
            )
        if intent_id is not None:
            raise MCPServiceContractError(
                "Intent-bounded context is not available until Phase 30 Step 3."
            )
        if changed_scope:
            raise MCPServiceContractError(
                "changed_scope context is not available until Phase 30 Step 5."
            )
        if isinstance(depth, bool) or not 0 <= depth <= _MAX_CONTEXT_DEPTH:
            raise MCPServiceContractError(
                f"Context depth must be between 0 and {_MAX_CONTEXT_DEPTH}."
            )
        if isinstance(budget, bool) or not 1 <= budget <= _MAX_CONTEXT_BUDGET:
            raise MCPServiceContractError(
                f"Context budget must be between 1 and {_MAX_CONTEXT_BUDGET}."
            )
        self._validated_context_include(include)

    def _validated_context_include(
        self,
        include: Sequence[str] | None,
    ) -> tuple[Facet, ...]:
        if include is None:
            return DEFAULT_IMPLEMENTATION_FACETS
        requested = frozenset(include)
        invalid = sorted(requested.difference(VALID_FACETS))
        if invalid:
            expected = ", ".join(sorted(VALID_FACETS))
            raise MCPServiceContractError(
                "Invalid implementation-context facet(s): "
                f"{', '.join(invalid)}. Expected values: {expected}."
            )
        return cast("tuple[Facet, ...]", tuple(sorted(requested)))

    def _normalize_context_paths(
        self,
        *,
        root_path: Path,
        paths: Sequence[str],
    ) -> tuple[str, ...]:
        normalized: set[str] = set()
        resolved_root = root_path.resolve()
        for raw_path in paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise MCPServiceContractError(
                    "Implementation-context paths must be non-empty strings."
                )
            try:
                absolute_path = resolve_repo_relative_path(resolved_root, raw_path)
                relative_path = absolute_path.relative_to(resolved_root).as_posix()
            except (RepoPathError, ValueError) as exc:
                raise MCPServiceContractError(
                    "Implementation-context paths must be repo-relative and "
                    f"contained under {resolved_root}: {raw_path!r}."
                ) from exc
            if not relative_path or relative_path == ".":
                raise MCPServiceContractError(
                    "Repository root is not a valid implementation-context path."
                )
            normalized.add(relative_path)
        return tuple(sorted(normalized))


__all__ = ["_MCPSessionContextMixin"]

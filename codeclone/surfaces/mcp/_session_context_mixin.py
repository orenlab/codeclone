# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""MCP implementation-context query surface."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from ...utils.repo_paths import RepoPathError, resolve_repo_relative_path
from . import _session_helpers as _helpers
from ._blast_radius import BlastRadiusResult, blast_radius_to_payload
from ._implementation_context import (
    DEFAULT_IMPACT_FACETS,
    DEFAULT_IMPLEMENTATION_FACETS,
    MAX_CONTEXT_TOTAL_ITEMS,
    build_implementation_context,
    resolve_context_symbols,
)
from ._intent import IntentRecord, IntentStatus
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
)
from ._workspace_hygiene import collect_dirty_snapshot
from .messages.params import VALID_FACETS, Facet

_VALID_CONTEXT_MODES = frozenset({"implementation", "impact", "contract"})
_VALID_CONTEXT_DETAIL_LEVELS = frozenset({"compact", "normal", "full"})
_MAX_CONTEXT_BUDGET = MAX_CONTEXT_TOTAL_ITEMS
_MAX_CONTEXT_DEPTH = 3


@dataclass(frozen=True, slots=True)
class _ContextSubject:
    paths: tuple[str, ...]
    symbols: tuple[str, ...]
    resolved_symbols: tuple[dict[str, object], ...]
    unresolved_symbols: tuple[str, ...]
    resolved_from: str
    source_summary: dict[str, object]


class _ContextSessionDependencies(Protocol):
    def _blast_radius_result(
        self,
        *,
        record: MCPRunRecord,
        files: Sequence[str],
        depth: str,
        forbidden_patterns: Sequence[str] = (),
        allowed_scope: Sequence[str] = (),
    ) -> BlastRadiusResult: ...

    def _latest_run_for_root(self, root_path: Path) -> MCPRunRecord | None: ...

    def get_relevant_memory(self, **params: object) -> dict[str, object]: ...


class _MCPSessionContextMixin:
    _runs: CodeCloneMCPRunStore
    _active_intents: dict[str, IntentRecord]

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
        intent = self._context_intent(intent_id)
        record = self._context_record(
            root_path=root_path,
            run_id=run_id,
            intent=intent,
        )
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
        subject = self._resolve_context_subject(
            root_path=root_path,
            record=record,
            paths=paths,
            symbols=symbols,
            intent=intent,
            changed_scope=changed_scope,
        )
        if subject is None:
            return {
                "status": "no_current_work",
                "root": str(root_path),
                "analysis": {
                    "run_id": record.run_id,
                    "report_digest": record.run_id,
                },
                "message": (
                    "No explicit subject, active intent scope, or live git-dirty "
                    "path is available. Whole-repository context is never inferred."
                ),
            }
        normalized_include = self._validated_context_include(
            include,
            mode=mode,
            has_intent=intent is not None,
        )
        session = cast("_ContextSessionDependencies", self)
        transitive = depth > 1 or mode == "impact"
        if subject.paths:
            blast_result = session._blast_radius_result(
                record=record,
                files=subject.paths,
                depth="transitive" if transitive else "direct",
                forbidden_patterns=(
                    intent.scope.forbidden if intent is not None else ()
                ),
                allowed_scope=(
                    intent.scope.allowed_paths if intent is not None else ()
                ),
            )
            blast_payload = blast_radius_to_payload(blast_result)
        else:
            blast_payload = {}
        memory_result = None
        if {"docs", "memory"}.intersection(normalized_include):
            memory_result = session.get_relevant_memory(
                root=str(root_path),
                scope=subject.paths or None,
                symbols=subject.symbols or None,
                max_records=min(budget, 20),
                include_drafts=True,
                detail_level=detail_level,
            )
        return build_implementation_context(
            record=record,
            paths=subject.paths,
            symbols=subject.symbols,
            subject_resolved_from=subject.resolved_from,
            subject_source_summary=subject.source_summary,
            resolved_symbols=subject.resolved_symbols,
            unresolved_symbols=subject.unresolved_symbols,
            mode=mode,
            include=normalized_include,
            depth=depth,
            detail_level=detail_level,
            budget=budget,
            blast_radius=blast_payload,
            memory_result=memory_result,
            change_control=(
                self._context_change_control(intent, blast_payload)
                if intent is not None
                else None
            ),
        )

    def _context_record(
        self,
        *,
        root_path: Path,
        run_id: str | None,
        intent: IntentRecord | None,
    ) -> MCPRunRecord | None:
        if intent is not None:
            if run_id is not None and run_id not in {
                intent.run_id,
                _helpers._short_run_id(intent.run_id),
            }:
                raise MCPServiceContractError(
                    "Selected run_id does not match the active intent run."
                )
            try:
                record = self._runs.get(intent.run_id)
            except MCPRunNotFoundError as exc:
                raise MCPServiceContractError(
                    "The active intent's analysis run is no longer available. "
                    "Analyze again and declare a new intent."
                ) from exc
            if record.root.resolve() != root_path.resolve():
                raise MCPServiceContractError(
                    "Active intent does not belong to the supplied root."
                )
            return record
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

    def _context_intent(self, intent_id: str | None) -> IntentRecord | None:
        if intent_id is None:
            return None
        intent = self._active_intents.get(intent_id)
        if intent is None:
            raise MCPServiceContractError(
                f"Unknown implementation-context intent_id: {intent_id!r}."
            )
        if intent.status is not IntentStatus.ACTIVE:
            raise MCPServiceContractError(
                "Implementation context requires an active intent; "
                f"{intent_id!r} is {intent.status.value}."
            )
        return intent

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
        if mode == "contract":
            raise MCPServiceContractError(
                f"Context mode {mode!r} is not available until its owning phase."
            )
        if isinstance(depth, bool) or not 0 <= depth <= _MAX_CONTEXT_DEPTH:
            raise MCPServiceContractError(
                f"Context depth must be between 0 and {_MAX_CONTEXT_DEPTH}."
            )
        if isinstance(budget, bool) or not 1 <= budget <= _MAX_CONTEXT_BUDGET:
            raise MCPServiceContractError(
                f"Context budget must be between 1 and {_MAX_CONTEXT_BUDGET}."
            )
        self._validated_context_include(
            include,
            mode=mode,
            has_intent=intent_id is not None,
        )

    def _validated_context_include(
        self,
        include: Sequence[str] | None,
        *,
        mode: str,
        has_intent: bool,
    ) -> tuple[Facet, ...]:
        if include is None:
            defaults = (
                DEFAULT_IMPACT_FACETS
                if mode == "impact"
                else DEFAULT_IMPLEMENTATION_FACETS
            )
            if has_intent:
                return (*defaults, "scope")
            return defaults
        requested = frozenset(include)
        invalid = sorted(requested.difference(VALID_FACETS))
        if invalid:
            expected = ", ".join(sorted(VALID_FACETS))
            raise MCPServiceContractError(
                "Invalid implementation-context facet(s): "
                f"{', '.join(invalid)}. Expected values: {expected}."
            )
        return cast("tuple[Facet, ...]", tuple(sorted(requested)))

    def _resolve_context_subject(
        self,
        *,
        root_path: Path,
        record: MCPRunRecord,
        paths: Sequence[str] | None,
        symbols: Sequence[str] | None,
        intent: IntentRecord | None,
        changed_scope: bool,
    ) -> _ContextSubject | None:
        explicit_paths = self._normalize_context_paths(
            root_path=root_path,
            paths=paths or (),
        )
        explicit_symbols = tuple(
            sorted({symbol.strip() for symbol in symbols or () if symbol.strip()})
        )
        if explicit_paths or explicit_symbols:
            return self._context_subject_from_explicit(
                record=record,
                paths=explicit_paths,
                symbols=explicit_symbols,
            )
        if intent is not None and not changed_scope and intent.scope.allowed_files:
            intent_paths = self._normalize_context_paths(
                root_path=root_path,
                paths=intent.scope.allowed_files,
            )
            return _ContextSubject(
                paths=intent_paths,
                symbols=(),
                resolved_symbols=(),
                unresolved_symbols=(),
                resolved_from="intent_scope",
                source_summary=_subject_source_summary(intent_paths),
            )
        snapshot = collect_dirty_snapshot(root_path)
        if not snapshot.paths:
            return None
        ranked_paths = self._rank_dirty_context_paths(
            snapshot.paths,
            intent=intent,
        )
        shown_paths = ranked_paths[:MAX_CONTEXT_TOTAL_ITEMS]
        normalized_paths = self._normalize_context_paths(
            root_path=root_path,
            paths=shown_paths,
        )
        return _ContextSubject(
            paths=normalized_paths,
            symbols=(),
            resolved_symbols=(),
            unresolved_symbols=(),
            resolved_from="changed_scope",
            source_summary={
                "total": len(ranked_paths),
                "shown": len(normalized_paths),
                "truncated": len(normalized_paths) < len(ranked_paths),
                "omitted": max(0, len(ranked_paths) - len(normalized_paths)),
                "git_available": snapshot.git_available,
            },
        )

    @staticmethod
    def _context_subject_from_explicit(
        *,
        record: MCPRunRecord,
        paths: tuple[str, ...],
        symbols: tuple[str, ...],
    ) -> _ContextSubject:
        resolved_symbols, unresolved_symbols = resolve_context_symbols(
            record,
            symbols,
        )
        symbol_paths = {
            str(item["path"])
            for item in resolved_symbols
            if str(item.get("path", "")).strip()
        }
        effective_paths = tuple(sorted({*paths, *symbol_paths}))
        resolved_from = (
            "explicit_mixed"
            if paths and symbols
            else "explicit_symbols"
            if symbols
            else "explicit_paths"
        )
        return _ContextSubject(
            paths=effective_paths,
            symbols=symbols,
            resolved_symbols=resolved_symbols,
            unresolved_symbols=unresolved_symbols,
            resolved_from=resolved_from,
            source_summary=_subject_source_summary(effective_paths),
        )

    @staticmethod
    def _rank_dirty_context_paths(
        paths: Sequence[str],
        *,
        intent: IntentRecord | None,
    ) -> tuple[str, ...]:
        intent_paths = (
            frozenset(intent.scope.allowed_paths) if intent is not None else frozenset()
        )
        return tuple(
            sorted(
                set(paths),
                key=lambda path: (0 if path in intent_paths else 1, path),
            )
        )

    def _context_change_control(
        self,
        intent: IntentRecord,
        blast_payload: dict[str, object],
    ) -> dict[str, object]:
        review_context = blast_payload.get("review_context")
        do_not_touch = blast_payload.get("do_not_touch")
        review_context_summary = blast_payload.get("review_context_summary")
        do_not_touch_summary = blast_payload.get("do_not_touch_summary")
        return {
            "intent_id": intent.intent_id,
            "intent_status": intent.status.value,
            "edit_allowed": intent.status is IntentStatus.ACTIVE,
            "authorization_source": "start_controlled_change",
            "allowed_files": list(intent.scope.allowed_files),
            "allowed_related": list(intent.scope.allowed_related),
            "review_context": (
                list(review_context) if isinstance(review_context, list) else []
            ),
            "review_context_summary": (
                dict(review_context_summary)
                if isinstance(review_context_summary, dict)
                else {}
            ),
            "do_not_touch": (
                list(do_not_touch) if isinstance(do_not_touch, list) else []
            ),
            "do_not_touch_summary": (
                dict(do_not_touch_summary)
                if isinstance(do_not_touch_summary, dict)
                else {}
            ),
            "guards": list(intent.guards),
        }

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


def _subject_source_summary(paths: Sequence[str]) -> dict[str, object]:
    return {
        "total": len(paths),
        "shown": len(paths),
        "truncated": False,
        "omitted": 0,
    }

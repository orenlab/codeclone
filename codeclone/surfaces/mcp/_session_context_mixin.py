# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""MCP implementation-context query surface."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

from ...utils.repo_paths import RepoPathError, resolve_repo_relative_path
from . import _session_helpers as _helpers
from ._blast_radius import BlastRadiusResult, blast_radius_to_payload
from ._context_governance import (
    IMPLEMENTATION_CONTEXT_PAGE_RESPONSE_PROJECTION_KIND,
    IMPLEMENTATION_CONTEXT_RESPONSE_CONTEXT_UNIT_LIMIT,
    IMPLEMENTATION_CONTEXT_RESPONSE_PROJECTION_KIND,
    attach_implementation_context_governance,
    attach_passive_context_governance,
    estimate_response_context_units,
)
from ._graph_search import search_graph
from ._implementation_context import (
    DEFAULT_CONTRACT_FACETS,
    DEFAULT_IMPACT_FACETS,
    DEFAULT_IMPLEMENTATION_FACETS,
    MAX_CONTEXT_TOTAL_ITEMS,
    MEMORY_BACKED_FACETS,
    build_implementation_context,
    resolve_context_symbols,
)
from ._implementation_context_pages import (
    DEFAULT_IMPLEMENTATION_CONTEXT_PAGE_SIZE,
    ContextProjectionArtifact,
    context_projection_page,
)
from ._intent import IntentRecord, IntentStatus
from ._session_finding_mixin import _StateLock
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
_DEFAULT_FACETS_BY_MODE: dict[str, tuple[Facet, ...]] = {
    "implementation": DEFAULT_IMPLEMENTATION_FACETS,
    "impact": DEFAULT_IMPACT_FACETS,
    "contract": DEFAULT_CONTRACT_FACETS,
}
_ContextLaneRef = tuple[tuple[str, ...], str]
_IMPLEMENTATION_CONTEXT_LANES: Final[tuple[_ContextLaneRef, ...]] = (
    (("implementation_evidence",), "experiences"),
    (("implementation_evidence",), "trajectories"),
    (("implementation_evidence",), "memory"),
    (("implementation_evidence",), "doc_anchors"),
    (("implementation_evidence",), "test_anchors"),
    (("structural_context",), "review_context"),
    (("structural_context",), "baseline_sensitive_findings"),
    (("structural_context",), "related_modules"),
    (("structural_context",), "public_surface"),
    (("call_context",), "callers"),
    (("call_context",), "test_callers"),
    (("call_context",), "callees"),
    (("call_context",), "references"),
    (("call_context",), "unresolved"),
    (("contracts",), "memory_conflicts"),
    (("contracts",), "contract_tests"),
    (("contracts",), "definition_sites"),
    (("contracts",), "version_constants"),
    (("contracts",), "persistence_path_callers"),
    (("contracts",), "serialization_path_callers"),
    (("contracts",), "deserialization_path_callers"),
    (("contracts",), "store_api_consumers"),
    (("structural_context", "blast_radius"), "dependency_cycles"),
    (("structural_context", "blast_radius"), "clone_cohorts"),
    (("structural_context", "blast_radius"), "transitive"),
    (("structural_context", "blast_radius"), "direct"),
    (("structural_context",), "module_role"),
)


def _implementation_context_response(
    payload: Mapping[str, object],
) -> dict[str, object]:
    return attach_passive_context_governance(
        payload,
        limit=IMPLEMENTATION_CONTEXT_RESPONSE_CONTEXT_UNIT_LIMIT,
        projection_kind=IMPLEMENTATION_CONTEXT_RESPONSE_PROJECTION_KIND,
        response={
            "tool": "get_implementation_context",
            "budget_scope": "whole_response",
            "evidence_policy": "observe_only_no_omission",
            "item_budget": "budget_summary",
        },
    )


def _budgeted_implementation_context_response(
    payload: Mapping[str, object],
    *,
    detail_level: str,
    budget: int,
) -> dict[str, object]:
    if detail_level == "full" or not _context_page_retrieval_available(payload):
        return _implementation_context_response(payload)
    packed = deepcopy(dict(payload))
    response_budget_lanes: set[_ContextLaneRef] = set()
    omitted = _implementation_context_omitted(
        packed,
        response_budget_lanes=response_budget_lanes,
    )
    governed = _attach_implementation_context_response(
        packed,
        detail_level=detail_level,
        budget=budget,
        evidence_omitted=omitted,
    )
    while (
        estimate_response_context_units(governed)
        > IMPLEMENTATION_CONTEXT_RESPONSE_CONTEXT_UNIT_LIMIT
    ):
        lane = _next_reducible_context_lane(packed)
        if lane is None:
            break
        _shrink_context_lane(packed, lane)
        response_budget_lanes.add(lane)
        omitted = _implementation_context_omitted(
            packed,
            response_budget_lanes=response_budget_lanes,
        )
        governed = _attach_implementation_context_response(
            packed,
            detail_level=detail_level,
            budget=budget,
            evidence_omitted=omitted,
        )
    return governed


def _attach_implementation_context_response(
    payload: Mapping[str, object],
    *,
    detail_level: str,
    budget: int,
    evidence_omitted: Mapping[str, object] | None,
) -> dict[str, object]:
    return attach_implementation_context_governance(
        payload,
        detail_level=detail_level,
        budget=budget,
        evidence_omitted=evidence_omitted,
        limit=IMPLEMENTATION_CONTEXT_RESPONSE_CONTEXT_UNIT_LIMIT,
    )


def _context_page_retrieval_available(payload: Mapping[str, object]) -> bool:
    analysis = payload.get("analysis")
    if not isinstance(analysis, Mapping):
        return False
    retrieval = analysis.get("context_page_retrieval")
    if not isinstance(retrieval, Mapping):
        return False
    return (
        retrieval.get("retrieval_tool") == "get_implementation_context_page"
        and bool(str(analysis.get("context_projection_digest", "")).strip())
        and bool(str(analysis.get("context_artifact_digest", "")).strip())
    )


def _implementation_context_omitted(
    payload: Mapping[str, object],
    *,
    response_budget_lanes: set[_ContextLaneRef],
) -> dict[str, object] | None:
    analysis = payload.get("analysis")
    if not isinstance(analysis, Mapping):
        return None
    context_projection_digest = str(
        analysis.get("context_projection_digest", "")
    ).strip()
    context_artifact_digest = str(analysis.get("context_artifact_digest", "")).strip()
    if not context_projection_digest or not context_artifact_digest:
        return None
    omitted: dict[str, object] = {}
    for lane in _IMPLEMENTATION_CONTEXT_LANES:
        lane_omission = _context_lane_omission(
            payload,
            lane=lane,
            context_artifact_digest=context_artifact_digest,
            context_projection_digest=context_projection_digest,
            response_budget_lanes=response_budget_lanes,
        )
        if lane_omission is not None:
            omitted[_context_omitted_key(lane)] = lane_omission
    return omitted or None


def _context_lane_omission(
    payload: Mapping[str, object],
    *,
    lane: _ContextLaneRef,
    context_artifact_digest: str,
    context_projection_digest: str,
    response_budget_lanes: set[_ContextLaneRef],
) -> dict[str, object] | None:
    lane_name = lane[1]
    container = _context_lane_container(payload, lane)
    summary = container.get(f"{lane_name}_summary") if container is not None else None
    omission: dict[str, object] | None = None
    if isinstance(summary, Mapping):
        items = container.get(lane_name) if container is not None else None
        shown = (
            len(items)
            if isinstance(items, list)
            else _non_negative_int(summary.get("shown"))
        )
        total = max(_non_negative_int(summary.get("total")), shown)
        if shown < total:
            omission = {
                "evaluation": "complete",
                "facet": lane_name,
                "container": ".".join(lane[0]),
                "total": total,
                "shown": shown,
                "omitted": total - shown,
                "reason": (
                    "response_budget"
                    if lane in response_budget_lanes
                    else "item_budget"
                ),
                "retrieval": {
                    "tool": "get_implementation_context_page",
                    "route": (
                        "get_implementation_context_page(root=..., "
                        "context_projection_digest=..., "
                        f"facet={lane_name!r}, offset={shown})"
                    ),
                    "context_artifact_digest": context_artifact_digest,
                    "context_projection_digest": context_projection_digest,
                    "facet": lane_name,
                    "offset": shown,
                    "page_size": DEFAULT_IMPLEMENTATION_CONTEXT_PAGE_SIZE,
                    "retention": "mcp_session_run_history",
                    "snapshot_identity": (
                        "context_artifact_digest + context_projection_digest "
                        "+ facet_identity_digest"
                    ),
                },
            }
    return omission


def _next_reducible_context_lane(
    payload: Mapping[str, object],
) -> _ContextLaneRef | None:
    for minimum in (1, 0):
        for lane in _IMPLEMENTATION_CONTEXT_LANES:
            items = _context_lane_items(payload, lane)
            if items is not None and len(items) > minimum:
                return lane
    return None


def _shrink_context_lane(payload: dict[str, object], lane: _ContextLaneRef) -> None:
    items = _context_lane_items(payload, lane)
    if not items:
        return
    items.pop()
    container = _context_lane_container(payload, lane)
    if container is None:
        return
    lane_name = lane[1]
    raw_summary = container.get(f"{lane_name}_summary")
    total = len(items)
    if isinstance(raw_summary, Mapping):
        total = max(total + 1, _non_negative_int(raw_summary.get("total")))
    container[f"{lane_name}_summary"] = {
        "total": total,
        "shown": len(items),
        "truncated": len(items) < total,
        "omitted": max(0, total - len(items)),
    }


def _context_lane_container(
    payload: Mapping[str, object],
    lane: _ContextLaneRef,
) -> dict[str, object] | None:
    current: object = payload
    for key in lane[0]:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, dict) else None


def _context_lane_items(
    payload: Mapping[str, object],
    lane: _ContextLaneRef,
) -> list[object] | None:
    container = _context_lane_container(payload, lane)
    if container is None:
        return None
    items = container.get(lane[1])
    return items if isinstance(items, list) else None


def _context_omitted_key(lane: _ContextLaneRef) -> str:
    return ".".join((*lane[0], lane[1]))


def _non_negative_int(value: object) -> int:
    try:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            number = value
        elif isinstance(value, str):
            number = int(value)
        else:
            return 0
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _implementation_context_page_response(
    payload: Mapping[str, object],
) -> dict[str, object]:
    return attach_passive_context_governance(
        payload,
        limit=IMPLEMENTATION_CONTEXT_RESPONSE_CONTEXT_UNIT_LIMIT,
        projection_kind=IMPLEMENTATION_CONTEXT_PAGE_RESPONSE_PROJECTION_KIND,
        response={
            "tool": "get_implementation_context_page",
            "budget_scope": "page_response",
            "evidence_policy": "exact_session_projection_page",
        },
    )


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
    _context_projection_pages: dict[str, ContextProjectionArtifact]
    _state_lock: _StateLock

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
        query: str | None = None,
    ) -> dict[str, object]:
        root_path = _helpers._resolve_root(root)
        intent = self._context_intent(intent_id)
        record = self._context_record(
            root_path=root_path,
            run_id=run_id,
            intent=intent,
        )
        if record is None:
            return _implementation_context_response(
                {
                    "status": "needs_analysis",
                    "root": str(root_path),
                    "message": (
                        "No MCP analysis run exists for this repository root. "
                        "Run analyze_repository first."
                    ),
                    "next_tool": "analyze_repository",
                }
            )
        if query is not None:
            if paths or symbols or changed_scope:
                raise MCPServiceContractError(
                    "query is mutually exclusive with paths, symbols, and "
                    "changed_scope."
                )
            return _implementation_context_response(
                search_graph(
                    record=record,
                    root=root_path,
                    query=query,
                    budget=budget,
                )
            )
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
            return _implementation_context_response(
                {
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
            )
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
        if MEMORY_BACKED_FACETS.intersection(normalized_include):
            memory_result = session.get_relevant_memory(
                root=str(root_path),
                scope=subject.paths or None,
                symbols=subject.symbols or None,
                max_records=min(budget, 20),
                include_drafts=True,
                detail_level=detail_level,
            )
        artifact: ContextProjectionArtifact | None = None

        def capture_projection(value: ContextProjectionArtifact) -> None:
            nonlocal artifact
            artifact = value

        payload = build_implementation_context(
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
            projection_sink=capture_projection,
        )
        if artifact is not None:
            with self._state_lock:
                self._context_projection_pages[artifact.context_projection_digest] = (
                    artifact
                )
        return _budgeted_implementation_context_response(
            payload,
            detail_level=detail_level,
            budget=budget,
        )

    def get_implementation_context_page(
        self,
        *,
        root: str,
        context_projection_digest: str,
        facet: str,
        offset: int = 0,
        page_size: int = DEFAULT_IMPLEMENTATION_CONTEXT_PAGE_SIZE,
        run_id: str | None = None,
    ) -> dict[str, object]:
        root_path = _helpers._resolve_root(root)
        if not context_projection_digest.strip():
            raise MCPServiceContractError(
                "get_implementation_context_page requires context_projection_digest."
            )
        if not facet.strip():
            raise MCPServiceContractError(
                "get_implementation_context_page requires facet."
            )
        with self._state_lock:
            artifact = self._context_projection_pages.get(context_projection_digest)
        if artifact is None:
            return _implementation_context_page_response(
                {
                    "status": "not_found",
                    "context_projection_digest": context_projection_digest,
                    "facet": facet,
                    "source": "mcp_session_context_projection",
                    "retention": "mcp_session_run_history",
                }
            )
        if artifact.root != root_path.resolve():
            return _implementation_context_page_response(
                {
                    "status": "root_mismatch",
                    "context_projection_digest": context_projection_digest,
                    "facet": facet,
                    "source": "mcp_session_context_projection",
                    "retention": "mcp_session_run_history",
                }
            )
        if run_id is not None:
            try:
                requested_run_id = self._runs.get(run_id).run_id
            except MCPRunNotFoundError:
                return _implementation_context_page_response(
                    {
                        "status": "run_not_found",
                        "run_id": run_id,
                        "context_projection_digest": context_projection_digest,
                        "facet": facet,
                        "source": "mcp_session_context_projection",
                        "retention": "mcp_session_run_history",
                    }
                )
        else:
            requested_run_id = None
        if requested_run_id is not None and artifact.run_id != requested_run_id:
            return _implementation_context_page_response(
                {
                    "status": "run_mismatch",
                    "run_id": run_id,
                    "artifact_run_id": artifact.run_id,
                    "context_projection_digest": context_projection_digest,
                    "facet": facet,
                    "source": "mcp_session_context_projection",
                    "retention": "mcp_session_run_history",
                }
            )
        return _implementation_context_page_response(
            context_projection_page(
                artifact=artifact,
                facet=facet,
                offset=offset,
                page_size=page_size,
            )
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
            defaults = _DEFAULT_FACETS_BY_MODE.get(mode, DEFAULT_IMPLEMENTATION_FACETS)
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

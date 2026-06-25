# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from ...config.memory import MemoryConfig, resolve_memory_config
from ...memory.embedding import resolve_embedding_provider
from ...memory.exceptions import (
    MemoryCapacityError,
    MemoryContractError,
    MemorySemanticUnavailableError,
)
from ...memory.ide_governance import (
    IdeGovernanceSessionState,
    _governance_rejected,
    commit_governance,
    prepare_governance,
    register_ide_governance,
)
from ...memory.ingest.mcp_sync import execute_mcp_memory_sync
from ...memory.models import MemoryProject
from ...memory.paths import normalize_memory_scope_path
from ...memory.project import resolve_memory_db_path, resolve_project_identity
from ...memory.retrieval import (
    get_memory_projection_page,
    get_relevant_memory,
    query_engineering_memory,
)
from ...memory.retrieval.continuation import rebase_memory_continuation_cursor
from ...memory.semantic import (
    close_semantic_index,
    execute_semantic_index_rebuild,
    resolve_semantic_index,
)
from ...memory.sqlite_store import SqliteEngineeringMemoryStore
from . import _session_helpers as _helpers
from ._context_governance import (
    DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT,
    MEMORY_CONTINUATION_RESPONSE_PROJECTION_KIND,
    attach_memory_retrieval_context_governance,
    attach_passive_context_governance,
)
from ._intent import IntentRecord
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
)

_MEMORY_RESPONSE_LANES: tuple[tuple[str, str], ...] = (
    ("records", "record_count"),
    ("trajectories", "trajectory_count"),
    ("experiences", "experience_count"),
)
_MEMORY_RESPONSE_REDUCTION_ORDER: tuple[str, ...] = (
    "experiences",
    "trajectories",
    "records",
)


class _MCPSessionMemoryMixin:
    _runs: CodeCloneMCPRunStore
    _active_intents: dict[str, IntentRecord]
    _ide_governance: IdeGovernanceSessionState

    def get_relevant_memory(
        self,
        *,
        root: str,
        scope: Sequence[str] | None = None,
        intent_id: str | None = None,
        symbols: Sequence[str] | None = None,
        max_records: int = 20,
        include_stale: bool = False,
        include_drafts: bool = False,
        include_routine: bool = False,
        detail_level: str = "compact",
    ) -> dict[str, object]:
        root_path = _helpers._resolve_root(root)
        memory_sync = self._maybe_auto_sync_memory(root_path)
        if not scope and not intent_id and not symbols:
            raise MCPServiceContractError(
                "get_relevant_memory requires scope, intent_id, or symbols. "
                "Use query_engineering_memory(mode=status|search) for project "
                "orientation."
            )
        if scope or intent_id:
            scope_paths, scope_resolved_from = self._resolve_memory_scope_paths(
                scope=scope,
                intent_id=intent_id,
            )
        else:
            scope_paths, scope_resolved_from = (), "symbols"
        effective_include_drafts = include_drafts or bool(scope_paths)
        store, _db_path, _config, project = self._open_memory_store(root_path)
        try:
            blast_dependents = self._memory_blast_dependents(root_path, scope_paths)
            result = get_relevant_memory(
                store,
                project_id=project.id,
                scope_paths=scope_paths,
                symbols=symbols,
                blast_dependents=tuple(blast_dependents),
                scope_resolved_from=scope_resolved_from,
                max_records=max_records,
                include_stale=include_stale,
                include_drafts=effective_include_drafts,
                include_routine=include_routine,
                detail_level=detail_level,
            )
            if memory_sync is not None:
                result = dict(result)
                result["memory_sync"] = memory_sync
            return _attach_budgeted_memory_retrieval_context(
                result,
                detail_level=detail_level,
                max_records=max_records,
            )
        except MemoryContractError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        finally:
            store.close()

    def query_engineering_memory(
        self,
        *,
        root: str,
        mode: str,
        record_id: str | None = None,
        path: str | None = None,
        symbol: str | None = None,
        query: str | None = None,
        scope: Sequence[str] | None = None,
        filters: Mapping[str, object] | None = None,
        max_results: int = 20,
        include_stale: bool = False,
        include_drafts: bool = False,
        detail_level: str = "compact",
        semantic: bool = False,
    ) -> dict[str, object]:
        root_path = _helpers._resolve_root(root)
        store, db_path, config, project = self._open_memory_store(root_path)
        index = resolve_semantic_index(config.semantic) if semantic else None
        provider = None
        semantic_reason = None
        if semantic:
            try:
                provider = resolve_embedding_provider(config.semantic)
            except MemorySemanticUnavailableError as exc:
                semantic_reason = str(exc)
        audit_path = (
            resolve_audit_path(root_path=root_path, value=DEFAULT_AUDIT_PATH)
            if semantic
            else None
        )
        try:
            return query_engineering_memory(
                store,
                project_id=project.id,
                root_path=root_path,
                backend=config.backend,
                db_path=db_path,
                mode=mode,
                record_id=record_id,
                path=path,
                symbol=symbol,
                query=query,
                scope=scope,
                filters=filters,
                max_results=max_results,
                include_stale=include_stale,
                include_drafts=include_drafts,
                detail_level=detail_level,
                semantic=semantic,
                semantic_index=index,
                embedding_provider=provider,
                provider_label=config.semantic.embedding_provider,
                semantic_reason=semantic_reason,
                audit_db_path=audit_path,
            )
        except MemoryContractError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        finally:
            close_semantic_index(index)
            store.close()

    def get_memory_projection_page(
        self,
        *,
        root: str,
        cursor: str,
        page_size: int = 20,
    ) -> dict[str, object]:
        root_path = _helpers._resolve_root(root)
        store, _db_path, _config, project = self._open_memory_store(root_path)
        try:
            result = get_memory_projection_page(
                store,
                project_id=project.id,
                cursor=cursor,
                page_size=page_size,
            )
            return attach_passive_context_governance(
                result,
                projection_kind=MEMORY_CONTINUATION_RESPONSE_PROJECTION_KIND,
                response={
                    "tool": "get_memory_projection_page",
                    "budget_scope": "whole_response",
                    "evidence_policy": "digest_bound_continuation_page",
                    "page_size": page_size,
                },
            )
        except MemoryContractError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        finally:
            store.close()

    def manage_engineering_memory(
        self,
        *,
        root: str,
        action: str,
        record_type: str | None = None,
        statement: str | None = None,
        subject_path: str | None = None,
        text: str | None = None,
        intent_id: str | None = None,
        run_id: str | None = None,
        record_id: str | None = None,
        experience_id: str | None = None,
        decision: str | None = None,
        ide_governance_key: str | None = None,
        client_name: str | None = None,
        client_version: str | None = None,
        governance_ticket: str | None = None,
        confirmation_nonce: str | None = None,
        proof: str | None = None,
        actor: str | None = None,
        protocol: int | None = None,
        reject_reason: str | None = None,
    ) -> dict[str, object]:
        from ...memory.exceptions import MemoryContractError

        root_path = _helpers._resolve_root(root)
        try:
            normalized = action.strip().lower()
            if normalized in {"approve", "reject", "archive"}:
                return _governance_rejected(normalized)
            if normalized == "register_ide_governance":
                if not ide_governance_key or not client_name:
                    raise MCPServiceContractError(
                        "register_ide_governance requires ide_governance_key and "
                        "client_name."
                    )
                return register_ide_governance(
                    self._ide_governance,
                    ide_governance_key=ide_governance_key,
                    client_name=client_name,
                    client_version=client_version,
                )
            if normalized == "prepare_governance":
                if not record_id or not decision:
                    raise MCPServiceContractError(
                        "prepare_governance requires record_id and decision."
                    )
                store, _db_path, _config, project = self._open_memory_store(root_path)
                try:
                    return prepare_governance(
                        self._ide_governance,
                        store,
                        project_id=project.id,
                        root_path=str(root_path),
                        record_id=record_id,
                        decision=decision,
                    )
                finally:
                    store.close()
            if normalized == "commit_governance":
                if (
                    not record_id
                    or not decision
                    or not governance_ticket
                    or not confirmation_nonce
                    or not proof
                    or protocol is None
                ):
                    raise MCPServiceContractError(
                        "commit_governance requires record_id, decision, "
                        "governance_ticket, confirmation_nonce, proof, and protocol."
                    )
                store, _db_path, _config, project = self._open_memory_store(root_path)
                try:
                    return commit_governance(
                        self._ide_governance,
                        store,
                        project_id=project.id,
                        root_path=str(root_path),
                        record_id=record_id,
                        decision=decision,
                        governance_ticket=governance_ticket,
                        confirmation_nonce=confirmation_nonce,
                        proof=proof,
                        actor=actor or "",
                        protocol=protocol,
                    )
                finally:
                    store.close()
            if normalized == "rebuild_semantic_index":
                config = resolve_memory_config(root_path)
                return cast(
                    dict[str, object],
                    execute_semantic_index_rebuild(
                        root_path=root_path,
                        config=config,
                    ),
                )
            if normalized == "rebuild_trajectories":
                config = resolve_memory_config(root_path)
                from ...memory.trajectory.rebuild_workflow import (
                    execute_trajectory_rebuild,
                )

                return cast(
                    dict[str, object],
                    execute_trajectory_rebuild(
                        root_path=root_path,
                        config=config,
                    ),
                )
            if normalized == "enqueue_projection_rebuild":
                from ...memory.jobs import execute_enqueue_projection_rebuild

                return execute_enqueue_projection_rebuild(
                    root_path=root_path,
                    trigger="explicit",
                )
            if normalized == "projection_rebuild_status":
                from ...memory.jobs import execute_projection_rebuild_status

                return execute_projection_rebuild_status(root_path=root_path)
            if normalized == "run_projection_jobs_once":
                from ...memory.jobs import execute_run_projection_jobs_once

                return execute_run_projection_jobs_once(root_path=root_path)
            if normalized == "refresh_from_run":
                return self._manage_memory_refresh_from_run(
                    root_path,
                    run_id=run_id,
                )
            if normalized == "record_candidate":
                store, _db_path, config, project = self._open_memory_store(root_path)
                try:
                    return self._manage_memory_record_candidate(
                        store,
                        project=project,
                        config=config,
                        record_type=record_type,
                        statement=statement,
                        subject_path=subject_path,
                    )
                finally:
                    store.close()
            if normalized == "promote_experience":
                store, _db_path, config, project = self._open_memory_store(root_path)
                try:
                    return self._manage_memory_promote_experience(
                        store,
                        project=project,
                        config=config,
                        experience_id=experience_id,
                    )
                finally:
                    store.close()
            if normalized == "validate_claims":
                store, _db_path, _config, project = self._open_memory_store(root_path)
                try:
                    return self._manage_memory_validate_claims(
                        store,
                        project=project,
                        text=text,
                    )
                finally:
                    store.close()
            if normalized == "propose_from_receipt":
                store, _db_path, config, project = self._open_memory_store(root_path)
                try:
                    return self._manage_memory_propose_from_receipt(
                        store,
                        project=project,
                        config=config,
                        text=text,
                        intent_id=intent_id,
                    )
                finally:
                    store.close()
            allowed = (
                "record_candidate",
                "promote_experience",
                "validate_claims",
                "propose_from_receipt",
                "refresh_from_run",
                "rebuild_semantic_index",
                "rebuild_trajectories",
                "enqueue_projection_rebuild",
                "projection_rebuild_status",
                "run_projection_jobs_once",
                "register_ide_governance",
                "prepare_governance",
                "commit_governance",
            )
            raise MCPServiceContractError(
                f"Unknown manage_engineering_memory action: {action!r}. "
                f"Allowed: {', '.join(allowed)}"
            )
        except MemoryCapacityError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        except MemoryContractError as exc:
            raise MCPServiceContractError(str(exc)) from exc

    def _manage_memory_record_candidate(
        self,
        store: SqliteEngineeringMemoryStore,
        *,
        project: MemoryProject,
        config: MemoryConfig,
        record_type: str | None,
        statement: str | None,
        subject_path: str | None,
    ) -> dict[str, object]:
        from ...memory.governance import record_candidate

        if not record_type or not statement:
            raise MCPServiceContractError(
                "record_candidate requires record_type and statement."
            )
        record = record_candidate(
            store,
            project=project,
            record_type=record_type,  # type: ignore[arg-type]
            statement=statement,
            subject_path=subject_path,
            max_candidates=config.max_candidates,
            max_statement_chars=config.max_statement_chars,
        )
        return {
            "action": "record_candidate",
            "record_id": record.id,
            "status": record.status,
            "type": record.type,
        }

    def _manage_memory_promote_experience(
        self,
        store: SqliteEngineeringMemoryStore,
        *,
        project: MemoryProject,
        config: MemoryConfig,
        experience_id: str | None,
    ) -> dict[str, object]:
        from ...memory.governance import promote_experience

        if not experience_id:
            raise MCPServiceContractError("promote_experience requires experience_id.")
        record = promote_experience(
            store,
            project=project,
            experience_id=experience_id,
            max_candidates=config.max_candidates,
        )
        return {
            "action": "promote_experience",
            "record_id": record.id,
            "status": record.status,
            "type": record.type,
            "promoted_from_experience": experience_id,
        }

    def _manage_memory_validate_claims(
        self,
        store: SqliteEngineeringMemoryStore,
        *,
        project: MemoryProject,
        text: str | None,
    ) -> dict[str, object]:
        from ...memory.governance import validate_memory_claims

        if not text:
            raise MCPServiceContractError("validate_claims requires text.")
        result = validate_memory_claims(
            store,
            project_id=project.id,
            text=text,
        )
        return {
            "action": "validate_claims",
            "valid": result.valid,
            "warnings": list(result.warnings),
            "errors": list(result.errors),
        }

    def _manage_memory_propose_from_receipt(
        self,
        store: SqliteEngineeringMemoryStore,
        *,
        project: MemoryProject,
        config: MemoryConfig,
        text: str | None,
        intent_id: str | None,
    ) -> dict[str, object]:
        from ...memory.ingest.receipts import propose_memory_from_finish_payload

        payload: dict[str, object] = {
            "claims_text": text,
            "scope_check": {},
        }
        if intent_id:
            intent = self._active_intents.get(intent_id)
            if intent is not None:
                payload["scope_check"] = {
                    "declared_scope": list(intent.scope.allowed_files),
                }
        candidates = propose_memory_from_finish_payload(
            store,
            project=project,
            finish_payload=payload,
            max_candidates=config.max_candidates,
            max_statement_chars=config.max_statement_chars,
        )
        return {"action": "propose_from_receipt", "memory_candidates": candidates}

    def _manage_memory_refresh_from_run(
        self,
        root_path: Path,
        *,
        run_id: str | None,
    ) -> dict[str, object]:
        record = self._memory_run_record(root_path, run_id)
        config = resolve_memory_config(root_path)
        sync_payload = execute_mcp_memory_sync(
            root_path=root_path,
            report_document=record.report_document,
            config=config,
            trigger="explicit",
            run_id=record.run_id,
            force=True,
        )
        return {"action": "refresh_from_run", **sync_payload}

    def _maybe_auto_sync_memory(
        self,
        root_path: Path,
        *,
        run_id: str | None = None,
    ) -> dict[str, object] | None:
        config = resolve_memory_config(root_path)
        if config.mcp_sync_policy == "off":
            return None
        try:
            record = self._memory_run_record(root_path, run_id)
        except MCPServiceContractError:
            return None
        sync_payload = execute_mcp_memory_sync(
            root_path=root_path,
            report_document=record.report_document,
            config=config,
            trigger="auto",
            run_id=record.run_id,
            force=False,
        )
        if sync_payload["status"] == "unchanged":
            return None
        return sync_payload

    def _memory_run_record(
        self,
        root_path: Path,
        run_id: str | None = None,
    ) -> MCPRunRecord:
        try:
            record = self._runs.get(run_id)
        except MCPRunNotFoundError as exc:
            raise MCPServiceContractError(
                "No MCP analysis run available for this repository. "
                "Call analyze_repository first."
            ) from exc
        if record.root.resolve() != root_path.resolve():
            raise MCPServiceContractError(
                "The selected MCP run belongs to a different repository root."
            )
        return record

    def finish_propose_memory(
        self,
        *,
        root_path: Path,
        changed_files: Sequence[str],
        claims_text: str | None,
        review_text: str | None,
        verification_profile: str | None,
    ) -> dict[str, object]:
        from ...memory.coverage import compute_scope_coverage, coverage_delta
        from ...memory.ingest.receipts import propose_memory_from_changed_paths
        from ...memory.staleness import apply_scope_staleness

        try:
            store, _db_path, config, project = self._open_memory_store(root_path)
        except MCPServiceContractError:
            return {}
        try:
            before = compute_scope_coverage(
                store,
                project_id=project.id,
                scope_paths=changed_files,
            )
            candidates = propose_memory_from_changed_paths(
                store,
                project=project,
                changed_paths=changed_files,
                claims_text=claims_text,
                review_text=review_text,
                verification_profile=verification_profile,
                max_candidates=config.max_candidates,
                max_statement_chars=config.max_statement_chars,
            )
            stale_report = apply_scope_staleness(
                store,
                project_id=project.id,
                changed_paths=changed_files,
            )
            after = compute_scope_coverage(
                store,
                project_id=project.id,
                scope_paths=changed_files,
            )
            delta = coverage_delta(before, after)
            return {
                "memory_candidates": candidates,
                "memory_staleness": {
                    "records_marked_stale": stale_report.records_marked_stale,
                    "reasons": stale_report.reasons,
                },
                "memory_coverage_delta": delta,
            }
        finally:
            store.close()

    def maybe_auto_enqueue_projection_rebuild(
        self,
        *,
        root_path: Path,
    ) -> dict[str, object] | None:
        from ...memory.jobs import maybe_auto_enqueue_projection_rebuild

        return maybe_auto_enqueue_projection_rebuild(
            root_path=root_path,
            trigger="mcp_finish",
        )

    def _open_memory_store(
        self,
        root_path: Path,
    ) -> tuple[SqliteEngineeringMemoryStore, Path, MemoryConfig, MemoryProject]:
        config = resolve_memory_config(root_path)
        db_path = resolve_memory_db_path(root_path, config)
        if not db_path.exists():
            self._maybe_auto_sync_memory(root_path)
        if not db_path.exists():
            raise MCPServiceContractError(
                "Engineering memory database not found. "
                "Call manage_engineering_memory(action='refresh_from_run') after "
                "analyze_repository, or run `codeclone memory init`."
            )
        project = resolve_project_identity(root_path)
        return SqliteEngineeringMemoryStore(db_path), db_path, config, project

    def _resolve_memory_scope_paths(
        self,
        *,
        scope: Sequence[str] | None,
        intent_id: str | None,
    ) -> tuple[tuple[str, ...], str]:
        if scope:
            return (
                tuple(normalize_memory_scope_path(path) for path in scope),
                "explicit",
            )
        if intent_id:
            intent = self._active_intents.get(intent_id)
            if intent is None:
                raise MCPServiceContractError(
                    f"Intent '{intent_id}' is not active in this MCP session. "
                    "Pass explicit scope or re-run start_controlled_change."
                )
            return (
                tuple(
                    normalize_memory_scope_path(path)
                    for path in intent.scope.allowed_files
                ),
                "intent",
            )
        raise MCPServiceContractError(
            "get_relevant_memory requires scope or intent_id. "
            "Use query_engineering_memory(mode=status|search) for project "
            "orientation."
        )

    def _memory_blast_dependents(
        self,
        root_path: Path,
        scope_paths: Sequence[str],
    ) -> frozenset[str]:
        if not scope_paths:
            return frozenset()
        try:
            record = self._runs.get()
        except MCPRunNotFoundError:
            return frozenset()
        if record.root.resolve() != root_path.resolve():
            return frozenset()
        try:
            result = self._blast_radius_result(
                record=record,
                files=list(scope_paths),
                depth="direct",
            )
        except MCPServiceContractError:
            return frozenset()
        return frozenset(result.direct_dependents)


def _attach_budgeted_memory_retrieval_context(
    payload: Mapping[str, object],
    *,
    detail_level: str,
    max_records: int,
    limit: int | None = None,
) -> dict[str, object]:
    effective_limit = DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT if limit is None else limit
    normalized_detail = "full" if detail_level == "full" else "compact"
    if normalized_detail == "full":
        return attach_memory_retrieval_context_governance(
            payload,
            detail_level=detail_level,
            max_records=max_records,
            limit=effective_limit,
        )
    packed, omitted = _pack_compact_memory_response(
        payload,
        detail_level=detail_level,
        max_records=max_records,
        limit=effective_limit,
    )
    return attach_memory_retrieval_context_governance(
        packed,
        detail_level=detail_level,
        max_records=max_records,
        evidence_omitted=omitted,
        limit=effective_limit,
    )


def _pack_compact_memory_response(
    payload: Mapping[str, object],
    *,
    detail_level: str,
    max_records: int,
    limit: int,
) -> tuple[dict[str, object], dict[str, object] | None]:
    lane_items = _memory_lane_items(payload)
    totals = _memory_lane_totals(payload, lane_items)
    original_shown = {lane: len(items) for lane, items in lane_items.items()}
    shown = dict(original_shown)
    original_continuation = _memory_continuation_lanes(payload)
    packed = _memory_response_with_shown_counts(
        payload,
        lane_items=lane_items,
        totals=totals,
        shown=shown,
        original_continuation=original_continuation,
    )
    omitted = _memory_governance_omitted(packed, original_shown=original_shown)
    if (
        _memory_governed_estimate(
            packed,
            detail_level=detail_level,
            max_records=max_records,
            omitted=omitted,
            limit=limit,
        )
        <= limit
    ):
        return packed, omitted
    for floor in (1, 0):
        while True:
            lane = _next_reducible_memory_lane(
                shown,
                floor=floor,
                original_continuation=original_continuation,
            )
            if lane is None:
                break
            shown[lane] -= 1
            packed = _memory_response_with_shown_counts(
                payload,
                lane_items=lane_items,
                totals=totals,
                shown=shown,
                original_continuation=original_continuation,
            )
            omitted = _memory_governance_omitted(
                packed,
                original_shown=original_shown,
            )
            if (
                _memory_governed_estimate(
                    packed,
                    detail_level=detail_level,
                    max_records=max_records,
                    omitted=omitted,
                    limit=limit,
                )
                <= limit
            ):
                return packed, omitted
    return packed, omitted


def _memory_governed_estimate(
    payload: Mapping[str, object],
    *,
    detail_level: str,
    max_records: int,
    omitted: Mapping[str, object] | None,
    limit: int,
) -> int:
    governed = attach_memory_retrieval_context_governance(
        payload,
        detail_level=detail_level,
        max_records=max_records,
        evidence_omitted=omitted,
        limit=limit,
    )
    envelope = cast("dict[str, object]", governed["context_governance"])
    estimated = envelope.get("estimated")
    if not isinstance(estimated, int):
        raise MCPServiceContractError("context governance estimate is invalid")
    return estimated


def _memory_lane_items(
    payload: Mapping[str, object],
) -> dict[str, list[dict[str, object]]]:
    lanes: dict[str, list[dict[str, object]]] = {}
    for lane, _count_key in _MEMORY_RESPONSE_LANES:
        value = payload.get(lane)
        items = value if isinstance(value, list) else []
        lanes[lane] = [dict(item) for item in items if isinstance(item, Mapping)]
    return lanes


def _memory_lane_totals(
    payload: Mapping[str, object],
    lane_items: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, int]:
    continuation_lanes = _memory_continuation_lanes(payload)
    totals: dict[str, int] = {}
    for lane, items in lane_items.items():
        lane_payload = continuation_lanes.get(lane, {})
        total = lane_payload.get("total")
        totals[lane] = total if isinstance(total, int) else len(items)
    return totals


def _memory_response_with_shown_counts(
    payload: Mapping[str, object],
    *,
    lane_items: Mapping[str, Sequence[Mapping[str, object]]],
    totals: Mapping[str, int],
    shown: Mapping[str, int],
    original_continuation: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    result = dict(payload)
    for lane, count_key in _MEMORY_RESPONSE_LANES:
        shown_count = shown[lane]
        result[lane] = list(lane_items[lane][:shown_count])
        result[count_key] = shown_count
    result["truncated"] = totals["records"] > shown["records"]
    result["trajectories_truncated"] = totals["trajectories"] > shown["trajectories"]
    continuation = _rebuilt_memory_continuation(
        totals=totals,
        shown=shown,
        original_continuation=original_continuation,
    )
    if continuation:
        result["continuation"] = continuation
    else:
        result.pop("continuation", None)
    return result


def _rebuilt_memory_continuation(
    *,
    totals: Mapping[str, int],
    shown: Mapping[str, int],
    original_continuation: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    lanes: dict[str, object] = {}
    for lane, _count_key in _MEMORY_RESPONSE_LANES:
        shown_count = shown[lane]
        total = totals[lane]
        omitted = max(0, total - shown_count)
        if omitted > 0:
            page = _rebased_memory_lane_page(
                lane,
                offset=shown_count,
                original_continuation=original_continuation,
            )
            if page is not None:
                lanes[lane] = {
                    "status": "available",
                    "total": total,
                    "shown": shown_count,
                    "omitted": omitted,
                    "page": page,
                }
    if not lanes:
        return {}
    return {
        "projection_kind": "memory_retrieval_lane_projection_v1",
        "ordering_version": "memory_retrieval_lane_order_v1",
        "cursor_policy": "digest_bound_recompute_or_fail_closed",
        "lanes": lanes,
    }


def _rebased_memory_lane_page(
    lane: str,
    *,
    offset: int,
    original_continuation: Mapping[str, Mapping[str, object]],
) -> dict[str, object] | None:
    original_lane = original_continuation.get(lane)
    page = original_lane.get("page") if original_lane is not None else None
    cursor = page.get("cursor") if isinstance(page, Mapping) else None
    if not isinstance(cursor, str):
        return None
    return rebase_memory_continuation_cursor(cursor, offset=offset)


def _memory_continuation_lanes(
    payload: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    continuation = payload.get("continuation")
    if not isinstance(continuation, Mapping):
        return {}
    lanes = continuation.get("lanes")
    if not isinstance(lanes, Mapping):
        return {}
    return {
        str(lane): dict(lane_payload)
        for lane, lane_payload in lanes.items()
        if isinstance(lane_payload, Mapping)
    }


def _memory_governance_omitted(
    payload: Mapping[str, object],
    *,
    original_shown: Mapping[str, int],
) -> dict[str, object] | None:
    omitted: dict[str, object] = {}
    for lane, lane_payload in _memory_continuation_lanes(payload).items():
        shown = lane_payload.get("shown")
        total = lane_payload.get("total")
        omitted_count = lane_payload.get("omitted")
        if not isinstance(shown, int) or not isinstance(total, int):
            continue
        if not isinstance(omitted_count, int) or omitted_count <= 0:
            continue
        reason = (
            "response_budget" if shown < original_shown.get(lane, 0) else "lane_cap"
        )
        omitted[lane] = {
            "evaluation": "complete",
            "total": total,
            "shown": shown,
            "omitted": omitted_count,
            "truncated": True,
            "reason": reason,
            "drill_down": {
                "tool": "get_memory_projection_page",
                "cursor_path": f"continuation.lanes.{lane}.page.cursor",
            },
        }
    return omitted or None


def _next_reducible_memory_lane(
    shown: Mapping[str, int],
    *,
    floor: int,
    original_continuation: Mapping[str, Mapping[str, object]],
) -> str | None:
    for lane in _MEMORY_RESPONSE_REDUCTION_ORDER:
        if shown[lane] > floor and lane in original_continuation:
            return lane
    return None


__all__ = ["_MCPSessionMemoryMixin"]

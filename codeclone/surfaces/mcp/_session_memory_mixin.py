# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, cast

from ...api.memory import rebuild_semantic_index
from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from ...config.memory import MemoryConfig, resolve_memory_config
from ...memory.application import (
    MemoryApplicationContext,
    execute_memory_query,
    resolve_memory_application_context,
)
from ...memory.embedding import resolve_embedding_provider
from ...memory.enums import MemoryRecordType, validate_memory_record_type
from ...memory.exceptions import (
    MemoryCapacityError,
    MemoryContractError,
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
from ...memory.retrieval.continuation import (
    build_memory_continuation_cursor,
    memory_projection_request_digest,
    rebase_memory_continuation_cursor,
)
from ...memory.semantic import (
    close_semantic_index,
    resolve_semantic_index,
)
from ...memory.sqlite_store import SqliteEngineeringMemoryStore
from ...utils.payload_narrow import is_payload_dict, is_record_mapping
from . import _session_helpers as _helpers
from ._context_governance import (
    DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT,
    MEMORY_CONTINUATION_RESPONSE_PROJECTION_KIND,
    attach_memory_query_context_governance,
    attach_memory_retrieval_context_governance,
    attach_passive_context_governance,
    passive_drill_down_reachability,
)
from ._intent import IntentRecord
from ._session_blast_radius_mixin import _MCPSessionBlastRadiusMixin
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPRunRootMismatchError,
    MCPServiceContractError,
)

_STORE_RESOLUTION_WARNING: Final = (
    "git state present but the main checkout could not be resolved; "
    "falling back to a per-root store — shared repository knowledge "
    "may be invisible from this root"
)


def _store_provenance_payload(
    *,
    config: MemoryConfig,
    store: SqliteEngineeringMemoryStore,
    project_id: str,
) -> dict[str, object]:
    """Result-derived witness of which store this response actually read.

    ``approved_records_total`` distinguishes a hollow fresh bootstrap
    (always 0) from a knowledge-bearing store in the response itself.
    ``per_root_git_unresolvable`` is degraded, never neutral: it always
    carries ``resolution_warning``. Deliberately compact (no db_path —
    ``memory_sync`` and ``mode=status`` already expose it) so scoped
    retrieval stays inside its response budget.
    """

    payload: dict[str, object] = {
        "store_resolution": config.store_resolution,
        "approved_records_total": store.count_approved_records(project_id=project_id),
    }
    if config.store_resolution == "per_root_git_unresolvable":
        payload["resolution_warning"] = _STORE_RESOLUTION_WARNING
    return payload


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
_MEMORY_LANE_DRILL_DOWN_KEYS: Final[dict[str, str]] = {
    "records": "memory_record",
    "trajectories": "trajectory",
    "experiences": "experience",
}


def _blast_session(session: _MCPSessionMemoryMixin) -> _MCPSessionBlastRadiusMixin:
    return cast(_MCPSessionBlastRadiusMixin, session)


def _candidate_batch_warnings(
    candidates: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    """Average-size gate over a propose batch of candidate statements."""
    from ...memory.governance import batch_statement_length_warnings

    return batch_statement_length_warnings(
        [len(str(item.get("statement", ""))) for item in candidates]
    )


def _enrich_attested_evidence(
    attested_evidence: Mapping[str, object] | None,
    project: MemoryProject,
) -> Mapping[str, object] | None:
    """Add the project's git head/branch to an attested-evidence bundle.

    The finish flow supplies the receipt/patch-trail digests and run id; commit
    and branch are the project's git provenance, resolved where the store is
    opened. Returns ``None`` when no bundle was supplied so the propose flow
    stays evidence-free for callers without a finished change.
    """
    if not attested_evidence:
        return None
    return {
        **attested_evidence,
        "commit": project.git_head or "",
        "branch": project.git_branch or "",
    }


class _MCPSessionMemoryMixin:
    _runs: CodeCloneMCPRunStore
    _active_intents: dict[str, IntentRecord]
    _ide_governance: IdeGovernanceSessionState
    _memory_continuation_requests: dict[str, dict[str, object]]

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
        store, _db_path, config, project = self._open_memory_store(root_path)
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
            result = dict(result)
            result["store_provenance"] = _store_provenance_payload(
                config=config,
                store=store,
                project_id=project.id,
            )
            if memory_sync is not None:
                result["memory_sync"] = memory_sync
            self._register_memory_continuation_request(result)
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
        audit_path = (
            resolve_audit_path(root_path=root_path, value=DEFAULT_AUDIT_PATH)
            if semantic
            else None
        )
        try:
            payload = execute_memory_query(
                store,
                context=MemoryApplicationContext(
                    config=config,
                    db_path=db_path,
                    project=project,
                ),
                root_path=root_path,
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
                audit_db_path=audit_path,
                query_executor=query_engineering_memory,
                semantic_index_resolver=resolve_semantic_index,
                embedding_provider_resolver=resolve_embedding_provider,
                semantic_index_closer=close_semantic_index,
            )
            payload = dict(payload)
            payload["store_provenance"] = _store_provenance_payload(
                config=config,
                store=store,
                project_id=project.id,
            )
            return _attach_memory_query_context(
                payload,
                mode=mode,
                max_results=max_results,
            )
        except MemoryContractError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        finally:
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
                resolve_request=lambda digest_value: (
                    self._resolve_memory_continuation_request(
                        project.id,
                        digest_value,
                    )
                ),
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
        record_type: MemoryRecordType | None = None,
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
                return rebuild_semantic_index(root_path=root_path).to_payload()
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
        record_type: MemoryRecordType | None,
        statement: str | None,
        subject_path: str | None,
    ) -> dict[str, object]:
        from ...memory.governance import record_candidate

        if not record_type or not statement:
            raise MCPServiceContractError(
                "record_candidate requires record_type and statement."
            )
        try:
            canonical_type = validate_memory_record_type(record_type)
        except ValueError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        record = record_candidate(
            store,
            project=project,
            record_type=canonical_type,
            statement=statement,
            subject_path=subject_path,
            max_candidates=config.max_candidates,
            max_statement_chars=config.max_statement_chars,
        )
        payload: dict[str, object] = {
            "action": "record_candidate",
            "record_id": record.id,
            "status": record.status,
            "type": record.type,
        }
        from ...memory.governance import statement_markdown_warnings

        markdown_warnings = statement_markdown_warnings(statement)
        if markdown_warnings:
            payload["warnings"] = list(markdown_warnings)
        return payload

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
        result: dict[str, object] = {
            "action": "propose_from_receipt",
            "memory_candidates": candidates,
        }
        batch_warnings = _candidate_batch_warnings(candidates)
        if batch_warnings:
            result["warnings"] = list(batch_warnings)
        return result

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
        # The memory action names its root; bind the lookup to it. Resolving
        # globally and post-checking the root leaked multi-root ambiguity for
        # ids shared with same-commit sibling checkouts.
        try:
            return self._runs.get_for_root(run_id, root=root_path)
        except MCPRunRootMismatchError as exc:
            raise MCPServiceContractError(
                "The selected MCP run belongs to a different repository root."
            ) from exc
        except MCPRunNotFoundError as exc:
            raise MCPServiceContractError(
                "No MCP analysis run available for this repository. "
                "Call analyze_repository first."
            ) from exc

    def finish_propose_memory(
        self,
        *,
        root_path: Path,
        changed_files: Sequence[str],
        claims_text: str | None,
        review_text: str | None,
        verification_profile: str | None,
        attested_evidence: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Propose draft memory candidates on an accepted finish.

        ``attested_evidence`` carries the finished change's receipt/patch-trail
        digests and run id; the controller's finish path supplies it so proposed
        candidates carry durable evidence. Commit and branch are enriched here
        from the project's git head. Callers without a finished change omit it and
        propose evidence-free.
        """
        from ...memory.finish_workflow import execute_finish_memory_workflow

        try:
            store, _db_path, config, project = self._open_memory_store(root_path)
        except MCPServiceContractError:
            return {}
        try:
            workflow = execute_finish_memory_workflow(
                store,
                project=project,
                changed_paths=changed_files,
                claims_text=claims_text,
                review_text=review_text,
                verification_profile=verification_profile,
                max_candidates=config.max_candidates,
                max_statement_chars=config.max_statement_chars,
                attested_evidence=_enrich_attested_evidence(attested_evidence, project),
            )
            hook_payload: dict[str, object] = {
                "memory_candidates": workflow.candidates,
                "memory_staleness": {
                    "records_marked_stale": workflow.staleness.records_marked_stale,
                    "reasons": workflow.staleness.reasons,
                },
                "memory_coverage_delta": workflow.coverage_delta,
            }
            batch_warnings = _candidate_batch_warnings(workflow.candidates)
            if batch_warnings:
                hook_payload["memory_candidate_warnings"] = list(batch_warnings)
            return hook_payload
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
        context = resolve_memory_application_context(
            root_path,
            config_resolver=resolve_memory_config,
            db_path_resolver=resolve_memory_db_path,
            project_resolver=resolve_project_identity,
        )
        if not context.db_path.exists():
            self._maybe_auto_sync_memory(root_path)
        if not context.db_path.exists():
            raise MCPServiceContractError(
                "Engineering memory database not found. "
                "Call manage_engineering_memory(action='refresh_from_run') after "
                "analyze_repository, or run `codeclone memory init`."
            )
        return (
            SqliteEngineeringMemoryStore(context.db_path),
            context.db_path,
            context.config,
            context.project,
        )

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
        # This root's own latest run, not the store-wide latest: bailing on a
        # root mismatch silently dropped dependents whenever another checkout
        # analyzed more recently.
        try:
            record = self._runs.get_for_root(None, root=root_path)
        except MCPRunNotFoundError:
            return frozenset()
        try:
            result = _blast_session(self)._blast_radius_result(
                record=record,
                files=list(scope_paths),
                depth="direct",
            )
        except MCPServiceContractError:
            return frozenset()
        return frozenset(result.direct_dependents)

    def _register_memory_continuation_request(
        self,
        payload: Mapping[str, object],
    ) -> None:
        """Register the projection request so continuation cursors can resolve.

        The request stays on the payload: the response packer needs it to mint
        a cursor for a lane it decides to shed, and the packer is the stage
        that removes the internal key before the response is published.
        """
        internal = payload.get("_memory_projection_request")
        project_id = payload.get("project_id")
        if isinstance(project_id, str) and is_record_mapping(internal):
            internal_mapping = internal
            digest = memory_projection_request_digest(internal_mapping)
            digest_value = digest.get("value")
            if isinstance(digest_value, str) and is_payload_dict(internal_mapping):
                self._memory_continuation_requests[
                    self._memory_continuation_request_key(project_id, digest_value)
                ] = dict(internal_mapping)

    def _resolve_memory_continuation_request(
        self,
        project_id: str,
        digest_value: str,
    ) -> dict[str, object] | None:
        return self._memory_continuation_requests.get(
            self._memory_continuation_request_key(project_id, digest_value)
        )

    @staticmethod
    def _memory_continuation_request_key(project_id: str, digest_value: str) -> str:
        return f"{project_id}:{digest_value}"


#: The count key each capped lane publishes beside its own ``truncated`` flag.
#: The router names exactly one of these per answer, which is what lets the
#: envelope attribute the cap to a lane without a fallback nobody can reach.
_MEMORY_QUERY_LANE_BY_COUNT_KEY: Final[tuple[tuple[str, str], ...]] = (
    ("record_count", "records"),
    ("trajectory_count", "trajectories"),
)
_MEMORY_QUERY_OMISSION_REASON: Final = "max_results_cap"


def _attach_memory_query_context(
    payload: Mapping[str, object],
    *,
    mode: str,
    max_results: int,
) -> dict[str, object]:
    """Publish the governance envelope for one ``query_engineering_memory`` answer."""

    body = payload.get("payload")
    detail_level = payload.get("detail_level")
    return attach_memory_query_context_governance(
        payload,
        mode=mode,
        max_results=max_results,
        detail_level=detail_level if isinstance(detail_level, str) else None,
        evidence_omitted=_memory_query_omitted(
            body if is_record_mapping(body) else None,
            mode=mode,
            max_results=max_results,
        ),
    )


def _memory_query_omitted(
    body: Mapping[str, object] | None,
    *,
    mode: str,
    max_results: int,
) -> dict[str, object]:
    """Name the capped lane, its shown count, and the route to the rest.

    The router fetches one item past the cap to learn that a tail exists; it
    never counts that tail. So the omission record states ``shown`` and stops:
    publishing a ``total`` here would be arithmetic nobody performed. The only
    route out of this surface is a wider re-query -- it mints no cursor, and
    naming a continuation cursor it cannot honour is the defect next door.

    Lanes are selected, never defaulted: an answer carrying no count key for a
    lane simply does not produce one, so there is no fallback branch waiting
    for an input the router cannot send it.
    """

    if body is None or body.get("truncated") is not True:
        return {}
    return {
        lane: {
            "evaluation": "unmeasured",
            "shown": body[count_key],
            "truncated": True,
            "reason": _MEMORY_QUERY_OMISSION_REASON,
            "drill_down": {
                "tool": "query_engineering_memory",
                "route": (
                    "query_engineering_memory(root=..., "
                    f"mode={mode!r}, max_results=<greater than {max_results}>)"
                ),
            },
        }
        for count_key, lane in _MEMORY_QUERY_LANE_BY_COUNT_KEY
        if isinstance(body.get(count_key), int)
    }


def _attach_budgeted_memory_retrieval_context(
    payload: Mapping[str, object],
    *,
    detail_level: str,
    max_records: int,
    limit: int | None = None,
) -> dict[str, object]:
    effective_limit = DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT if limit is None else limit
    # The envelope describes the response, so it publishes the level the
    # response actually carries. Echoing the raw request here made one message
    # say `normal` in the envelope and `compact` in the payload under the same
    # field name; the request is preserved by detail_level_resolution instead.
    normalized_detail = "full" if detail_level == "full" else "compact"
    publishable = dict(payload)
    projection_request = publishable.pop("_memory_projection_request", None)
    if normalized_detail == "full":
        return attach_memory_retrieval_context_governance(
            publishable,
            detail_level=normalized_detail,
            max_records=max_records,
            limit=effective_limit,
        )
    packed, omitted = _pack_compact_memory_response(
        publishable,
        detail_level=normalized_detail,
        max_records=max_records,
        limit=effective_limit,
        projection_request=projection_request,
    )
    return attach_memory_retrieval_context_governance(
        packed,
        detail_level=normalized_detail,
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
    projection_request: object = None,
) -> tuple[dict[str, object], dict[str, object] | None]:
    lane_items = _memory_lane_items(payload)
    totals = _memory_lane_totals(payload, lane_items)
    original_shown = {lane: len(items) for lane, items in lane_items.items()}
    shown = dict(original_shown)
    lane_cursors = _memory_lane_base_cursors(
        payload,
        lane_items=lane_items,
        projection_request=projection_request,
    )
    packed = _memory_response_with_shown_counts(
        payload,
        lane_items=lane_items,
        totals=totals,
        shown=shown,
        lane_cursors=lane_cursors,
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
                shown, floor=floor, lane_cursors=lane_cursors
            )
            if lane is None:
                break
            shown[lane] -= 1
            packed = _memory_response_with_shown_counts(
                payload,
                lane_items=lane_items,
                totals=totals,
                shown=shown,
                lane_cursors=lane_cursors,
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
        lanes[lane] = [dict(item) for item in items if is_payload_dict(item)]
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
    lane_cursors: Mapping[str, str],
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
        lane_cursors=lane_cursors,
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
    lane_cursors: Mapping[str, str],
) -> dict[str, object]:
    lanes: dict[str, object] = {}
    for lane, _count_key in _MEMORY_RESPONSE_LANES:
        shown_count = shown[lane]
        total = totals[lane]
        omitted = max(0, total - shown_count)
        cursor = lane_cursors.get(lane)
        if omitted > 0 and cursor is not None:
            page = rebase_memory_continuation_cursor(cursor, offset=shown_count)
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
        if is_payload_dict(lane_payload)
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
                "route": _memory_lane_continuation_route(lane),
                "cursor_path": f"continuation.lanes.{lane}.page.cursor",
            },
        }
    return omitted or None


def _memory_lane_continuation_route(lane: str) -> str:
    """Project the declared continuation route for one omitted lane.

    The drill-down table is a contract fact, invariant across responses, so it
    is no longer restated in every envelope. It is still the single owner of
    the routes: a lane that omits evidence carries the route from here, where
    the consumer actually needs it.
    """
    reachability = passive_drill_down_reachability()
    entry = reachability.get(_MEMORY_LANE_DRILL_DOWN_KEYS.get(lane, ""), {})
    route = entry.get("continuation_route")
    return route if isinstance(route, str) else ""


def _next_reducible_memory_lane(
    shown: Mapping[str, int],
    *,
    floor: int,
    lane_cursors: Mapping[str, str],
) -> str | None:
    """A lane may be shed only while its tail stays reachable by cursor."""
    for lane in _MEMORY_RESPONSE_REDUCTION_ORDER:
        if shown[lane] > floor and lane in lane_cursors:
            return lane
    return None


def _memory_lane_base_cursors(
    payload: Mapping[str, object],
    *,
    lane_items: Mapping[str, Sequence[Mapping[str, object]]],
    projection_request: object,
) -> dict[str, str]:
    """Return one rebasable cursor per lane the response packer may shed.

    A lane the retrieval returned in full carries no cursor, because nothing
    was omitted at retrieval time. The response packer answers to a different
    limit and may still have to shed such a lane, so it mints that lane's
    cursor from the same projection request the retrieval registered. Without
    it a full lane is incompressible by accident and the whole response
    overflows instead of paging.
    """
    original_continuation = _memory_continuation_lanes(payload)
    project_id = payload.get("project_id")
    mintable = isinstance(project_id, str) and bool(project_id)
    cursors: dict[str, str] = {}
    for lane, _count_key in _MEMORY_RESPONSE_LANES:
        original_lane = original_continuation.get(lane)
        page = original_lane.get("page") if original_lane is not None else None
        cursor = page.get("cursor") if isinstance(page, Mapping) else None
        if isinstance(cursor, str):
            cursors[lane] = cursor
        elif mintable and is_record_mapping(projection_request):
            minted = build_memory_continuation_cursor(
                project_id=cast("str", project_id),
                lane=lane,
                request=projection_request,
                items=lane_items.get(lane, ()),
                offset=0,
            )["cursor"]
            cursors[lane] = cast("str", minted)
    return cursors


__all__ = ["_MCPSessionMemoryMixin"]

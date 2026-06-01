# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ...config.memory import MemoryConfig, resolve_memory_config
from ...memory.exceptions import MemoryContractError
from ...memory.ide_governance import (
    IdeGovernanceSessionState,
    _governance_rejected,
    commit_governance,
    prepare_governance,
    register_ide_governance,
)
from ...memory.ingest.mcp_sync import execute_mcp_memory_sync
from ...memory.models import MemoryProject
from ...memory.project import resolve_memory_db_path, resolve_project_identity
from ...memory.retrieval import get_relevant_memory, query_engineering_memory
from ...memory.sqlite_store import SqliteEngineeringMemoryStore
from . import _session_helpers as _helpers
from ._intent import IntentRecord
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
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
    ) -> dict[str, object]:
        root_path = _helpers._resolve_root(root)
        memory_sync = self._maybe_auto_sync_memory(root_path)
        scope_paths, scope_resolved_from = self._resolve_memory_scope_paths(
            scope=scope,
            intent_id=intent_id,
        )
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
            )
            if memory_sync is not None:
                result = dict(result)
                result["memory_sync"] = memory_sync
            return result
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
    ) -> dict[str, object]:
        root_path = _helpers._resolve_root(root)
        store, db_path, config, project = self._open_memory_store(root_path)
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
        from ...memory.exceptions import MemoryCapacityError, MemoryContractError

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
                "validate_claims",
                "propose_from_receipt",
                "refresh_from_run",
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
        )
        return {
            "action": "record_candidate",
            "record_id": record.id,
            "status": record.status,
            "type": record.type,
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
            return tuple(scope), "explicit"
        if intent_id:
            intent = self._active_intents.get(intent_id)
            if intent is None:
                raise MCPServiceContractError(
                    f"Intent '{intent_id}' is not active in this MCP session. "
                    "Pass explicit scope or re-run start_controlled_change."
                )
            return intent.scope.allowed_files, "intent"
        return (), "project_summary"

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


__all__ = ["_MCPSessionMemoryMixin"]

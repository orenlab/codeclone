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
from ...memory.models import MemoryProject
from ...memory.project import resolve_memory_db_path, resolve_project_identity
from ...memory.retrieval import get_relevant_memory, query_engineering_memory
from ...memory.sqlite_store import SqliteEngineeringMemoryStore
from . import _session_helpers as _helpers
from ._intent import IntentRecord
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunNotFoundError,
    MCPServiceContractError,
)


class _MCPSessionMemoryMixin:
    _runs: CodeCloneMCPRunStore
    _active_intents: dict[str, IntentRecord]

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
        scope_paths, scope_resolved_from = self._resolve_memory_scope_paths(
            scope=scope,
            intent_id=intent_id,
        )
        store, _db_path, _config, project = self._open_memory_store(root_path)
        try:
            blast_dependents = self._memory_blast_dependents(root_path, scope_paths)
            return get_relevant_memory(
                store,
                project_id=project.id,
                scope_paths=scope_paths,
                symbols=symbols,
                blast_dependents=tuple(blast_dependents),
                scope_resolved_from=scope_resolved_from,
                max_records=max_records,
                include_stale=include_stale,
                include_drafts=include_drafts,
            )
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
    ) -> dict[str, object]:
        from ...memory.exceptions import MemoryCapacityError, MemoryContractError
        from ...memory.governance import (
            record_candidate,
            validate_memory_claims,
        )
        from ...memory.ingest.receipts import propose_memory_from_finish_payload

        root_path = _helpers._resolve_root(root)
        store, _db_path, config, project = self._open_memory_store(root_path)
        try:
            normalized = action.strip().lower()
            if normalized == "record_candidate":
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
                    "action": normalized,
                    "record_id": record.id,
                    "status": record.status,
                    "type": record.type,
                }
            if normalized == "validate_claims":
                if not text:
                    raise MCPServiceContractError("validate_claims requires text.")
                result = validate_memory_claims(
                    store,
                    project_id=project.id,
                    text=text,
                )
                return {
                    "action": normalized,
                    "valid": result.valid,
                    "warnings": list(result.warnings),
                    "errors": list(result.errors),
                }
            if normalized == "propose_from_receipt":
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
                return {"action": normalized, "memory_candidates": candidates}
            allowed = (
                "record_candidate",
                "validate_claims",
                "propose_from_receipt",
            )
            raise MCPServiceContractError(
                f"Unknown manage_engineering_memory action: {action!r}. "
                f"Allowed: {', '.join(allowed)}"
            )
        except MemoryCapacityError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        except MemoryContractError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        finally:
            store.close()

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
            raise MCPServiceContractError(
                "Engineering memory database not found. "
                "Run `codeclone memory init` first."
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

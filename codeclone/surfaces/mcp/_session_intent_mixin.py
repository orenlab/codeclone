# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path

from . import _session_helpers as _helpers
from ._intent import (
    DEFAULT_INTENT_GUARDS,
    IntentCheckResult,
    IntentRecord,
    IntentScope,
    IntentStatus,
    forbidden_touched,
    normalize_expected_effects,
    normalize_intent_scope,
)
from ._session_blast_radius_mixin import _MCPSessionBlastRadiusMixin
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
)
from ._workspace_intents import (
    WorkspaceIntentRecord,
    WorkspaceIntentStatus,
    compute_scope_digest,
    detect_conflicts,
    expires_at,
    find_workspace_intent,
    format_utc,
    gc_workspace,
    is_orphaned,
    list_workspace_intents,
    remove_workspace_intent,
    remove_workspace_record,
    resolved_ttl_seconds,
    stale_reason,
    update_workspace_intent_status,
    utc_now,
    workspace_status_counts,
    write_workspace_intent,
)


class _MCPSessionIntentMixin(_MCPSessionBlastRadiusMixin):
    _runs: CodeCloneMCPRunStore
    _active_intents: dict[str, IntentRecord]
    _intent_sequence: int
    _agent_pid: int
    _agent_start_epoch: int
    _agent_label: str

    def manage_change_intent(
        self,
        *,
        action: str,
        run_id: str | None = None,
        intent_id: str | None = None,
        scope: dict[str, object] | None = None,
        intent: str | None = None,
        expected_effects: Sequence[str] | None = None,
        diff_ref: str | None = None,
        changed_files: Sequence[str] | None = None,
        root: str | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, object]:
        match action:
            case "declare":
                return self._declare_change_intent(
                    run_id=run_id,
                    scope=scope,
                    intent=intent,
                    expected_effects=expected_effects,
                    ttl_seconds=ttl_seconds,
                )
            case "get":
                record, active_intent = self._resolve_intent(
                    run_id=run_id,
                    intent_id=intent_id,
                )
                return self._intent_payload_with_expiry(
                    record=record,
                    intent=active_intent,
                )
            case "check":
                return self._check_change_intent(
                    run_id=run_id,
                    intent_id=intent_id,
                    diff_ref=diff_ref,
                    changed_files=changed_files,
                )
            case "clear":
                return self._clear_change_intent(intent_id=intent_id)
            case "list_workspace":
                return self._list_workspace_intents(root=root)
            case "gc_workspace":
                return self._gc_workspace_intents(root=root)
            case "reset_workspace":
                return self._reset_workspace_intent(
                    root=root,
                    intent_id=intent_id,
                    ttl_seconds=ttl_seconds,
                )
            case _:
                raise MCPServiceContractError(
                    "Invalid value for action: "
                    f"{action!r}. Expected one of: check, clear, declare, "
                    "gc_workspace, get, list_workspace, reset_workspace."
                )

    def _declare_change_intent(
        self,
        *,
        run_id: str | None,
        scope: dict[str, object] | None,
        intent: str | None,
        expected_effects: Sequence[str] | None,
        ttl_seconds: int | None,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        try:
            normalized_scope = normalize_intent_scope(scope)
            normalized_expected_effects = normalize_expected_effects(expected_effects)
        except ValueError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        description = str(intent or "").strip()
        if not description:
            raise MCPServiceContractError("action='declare' requires intent text.")
        blast = self._blast_radius_result(
            record=record,
            files=normalized_scope.allowed_paths,
            depth="direct",
            forbidden_patterns=normalized_scope.forbidden,
        )
        blast_payload = blast.to_payload()
        blast_summary = self._blast_radius_summary(
            blast_payload=blast_payload,
            scope=normalized_scope,
        )
        ttl = resolved_ttl_seconds(
            ttl_seconds,
            env_value=os.environ.get("CODECLONE_INTENT_TTL_SECONDS"),
        )
        replaced_intents: list[IntentRecord] = []
        with self._state_lock:
            for existing_id, existing in tuple(self._active_intents.items()):
                if existing.run_id == record.run_id:
                    self._active_intents.pop(existing_id, None)
                    replaced_intents.append(existing)
            self._intent_sequence += 1
            intent_id = (
                f"intent-{_helpers._short_run_id(record.run_id)}-"
                f"{self._intent_sequence:03d}"
            )
            declared_at = _utc_now()
            record_payload = IntentRecord(
                intent_id=intent_id,
                run_id=record.run_id,
                report_digest=self._report_digest_value(record),
                status=IntentStatus.ACTIVE,
                declared_at_utc=declared_at,
                scope=normalized_scope,
                intent_description=description,
                expected_effects=normalized_expected_effects,
                guards=DEFAULT_INTENT_GUARDS,
                blast_radius_summary=blast_summary,
            )
            self._active_intents[intent_id] = record_payload
            self._runs.pin(record.run_id)
        workspace_record = self._workspace_record_from_intent(
            record=record,
            intent=record_payload,
            ttl_seconds=ttl,
        )
        for replaced_intent in replaced_intents:
            remove_workspace_intent(
                root=record.root,
                pid=self._agent_pid,
                start_epoch=self._agent_start_epoch,
                intent_id=replaced_intent.intent_id,
            )
        workspace_existing = list_workspace_intents(root=record.root)
        workspace_registered = write_workspace_intent(
            root=record.root,
            record=workspace_record,
        )
        concurrent_intents = detect_conflicts(
            new_scope=normalized_scope.to_payload(),
            existing=workspace_existing,
            own_pid=self._agent_pid,
        )
        payload = record_payload.to_payload(
            short_run_id=_helpers._short_run_id(record.run_id)
        )
        payload["do_not_touch"] = blast_payload["do_not_touch"]
        payload["do_not_touch_summary"] = blast_payload["do_not_touch_summary"]
        payload["review_context"] = blast_payload["review_context"]
        payload["review_context_summary"] = blast_payload["review_context_summary"]
        payload["workspace_registered"] = workspace_registered
        payload["concurrent_intents"] = concurrent_intents
        payload["ttl_seconds"] = ttl
        return payload

    def _check_change_intent(
        self,
        *,
        run_id: str | None,
        intent_id: str | None,
        diff_ref: str | None,
        changed_files: Sequence[str] | None,
    ) -> dict[str, object]:
        if diff_ref is None and not changed_files:
            raise MCPServiceContractError(
                "action='check' requires diff_ref or changed_files."
            )
        record, active_intent = self._resolve_intent(
            run_id=run_id,
            intent_id=intent_id,
        )
        if self._is_intent_expired(record=record, intent=active_intent):
            expired = replace(active_intent, status=IntentStatus.EXPIRED)
            with self._state_lock:
                self._active_intents[expired.intent_id] = expired
            self._sync_workspace_intent_status(record=record, intent=expired)
            return expired.to_payload(
                short_run_id=_helpers._short_run_id(record.run_id)
            )
        actual = (
            self._normalize_changed_paths(root_path=record.root, paths=changed_files)
            if changed_files
            else self._git_diff_paths(root_path=record.root, git_diff_ref=str(diff_ref))
        )
        check_result = self._intent_check_result(intent=active_intent, actual=actual)
        updated = replace(
            active_intent,
            status=check_result.status,
            check_result=check_result,
        )
        with self._state_lock:
            self._active_intents[updated.intent_id] = updated
        self._sync_workspace_intent_status(record=record, intent=updated)
        payload = check_result.to_payload()
        payload["intent_id"] = updated.intent_id
        return payload

    def _clear_change_intent(self, *, intent_id: str | None) -> dict[str, object]:
        with self._state_lock:
            removed_ids: tuple[str, ...]
            removed_intents: tuple[IntentRecord, ...]
            if intent_id is not None:
                if intent_id not in self._active_intents:
                    raise MCPServiceContractError(
                        f"Unknown change intent id: {intent_id}"
                    )
                removed_ids = (intent_id,)
                removed = self._active_intents.pop(intent_id)
                removed_intents = (removed,)
            else:
                removed_ids = tuple(self._active_intents)
                removed_intents = tuple(self._active_intents.values())
                self._active_intents.clear()
            workspace_targets: tuple[tuple[Path, str], ...] = tuple(
                (record.root, removed_intent.intent_id)
                for removed_intent in removed_intents
                for record in (self._optional_run_record(removed_intent.run_id),)
                if record is not None
            )
            for removed_intent in removed_intents:
                self._runs.unpin(removed_intent.run_id)
        workspace_cleared = True
        for root_path, removed_intent_id in workspace_targets:
            workspace_cleared = (
                remove_workspace_intent(
                    root=root_path,
                    pid=self._agent_pid,
                    start_epoch=self._agent_start_epoch,
                    intent_id=removed_intent_id,
                )
                and workspace_cleared
            )
        return {
            "cleared": len(removed_ids),
            "cleared_intent_ids": list(removed_ids),
            "workspace_cleared": workspace_cleared,
        }

    def _resolve_intent(
        self,
        *,
        run_id: str | None,
        intent_id: str | None,
    ) -> tuple[MCPRunRecord, IntentRecord]:
        if intent_id is not None:
            with self._state_lock:
                active_intent = self._active_intents.get(intent_id)
            if active_intent is None:
                raise MCPServiceContractError(f"Unknown change intent id: {intent_id}")
            return self._runs.get(active_intent.run_id), active_intent
        record = self._runs.get(run_id)
        with self._state_lock:
            matching = [
                intent
                for intent in self._active_intents.values()
                if intent.run_id == record.run_id
            ]
        if not matching:
            raise MCPServiceContractError("No active change intent is available.")
        return record, matching[-1]

    def _intent_payload_with_expiry(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord,
    ) -> dict[str, object]:
        if self._is_intent_expired(record=record, intent=intent):
            intent = replace(intent, status=IntentStatus.EXPIRED)
            with self._state_lock:
                self._active_intents[intent.intent_id] = intent
            self._sync_workspace_intent_status(record=record, intent=intent)
        return intent.to_payload(short_run_id=_helpers._short_run_id(record.run_id))

    def _is_intent_expired(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord,
    ) -> bool:
        return intent.report_digest != self._report_digest_value(record)

    def _report_digest_value(self, record: MCPRunRecord) -> str:
        integrity = _as_mapping(record.report_document.get("integrity"))
        digest = _as_mapping(integrity.get("digest"))
        value = str(digest.get("value", "")).strip()
        if value:
            return value
        return record.run_id

    def _workspace_record_from_intent(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord,
        ttl_seconds: int,
    ) -> WorkspaceIntentRecord:
        scope_payload = intent.scope.to_payload()
        declared_at = _parse_utc(intent.declared_at_utc) or utc_now()
        return WorkspaceIntentRecord(
            intent_id=intent.intent_id,
            agent_pid=self._agent_pid,
            agent_start_epoch=self._agent_start_epoch,
            agent_label=self._agent_label,
            run_id=record.run_id,
            declared_at_utc=format_utc(declared_at),
            expires_at_utc=expires_at(
                declared_at=declared_at,
                ttl_seconds=ttl_seconds,
            ),
            ttl_seconds=ttl_seconds,
            status=intent.status.value,
            intent=intent.intent_description,
            scope=scope_payload,
            scope_digest=compute_scope_digest(scope_payload),
            blast_radius_summary=dict(intent.blast_radius_summary or {}),
        )

    def _sync_workspace_intent_status(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord,
    ) -> None:
        update_workspace_intent_status(
            root=record.root,
            pid=self._agent_pid,
            start_epoch=self._agent_start_epoch,
            intent_id=intent.intent_id,
            new_status=intent.status.value,
        )

    def _list_workspace_intents(self, *, root: str | None) -> dict[str, object]:
        root_path = self._resolve_workspace_root(root)
        counts = workspace_status_counts(root=root_path)
        records = list_workspace_intents(root=root_path)
        return {
            "workspace_intents": [
                item.to_payload(
                    own_pid=self._agent_pid,
                    own_start_epoch=self._agent_start_epoch,
                )
                for item in records
            ],
            "stale_count": counts["stale_count"],
            "orphaned_count": counts["orphaned_count"],
            "total_agents": len({item.agent_pid for item in records}),
            "own_pid": self._agent_pid,
            "own_start_epoch": self._agent_start_epoch,
        }

    def _gc_workspace_intents(self, *, root: str | None) -> dict[str, object]:
        return gc_workspace(root=self._resolve_workspace_root(root))

    def _reset_workspace_intent(
        self,
        *,
        root: str | None,
        intent_id: str | None,
        ttl_seconds: int | None,
    ) -> dict[str, object]:
        if intent_id is None:
            raise MCPServiceContractError(
                "action='reset_workspace' requires intent_id."
            )
        root_path = self._resolve_workspace_root(root)
        found = find_workspace_intent(root=root_path, intent_id=intent_id)
        if found is None:
            raise MCPServiceContractError(f"Unknown workspace intent id: {intent_id}")
        _, workspace_record = found
        reason = stale_reason(workspace_record)
        is_own = (
            workspace_record.agent_pid == self._agent_pid
            and workspace_record.agent_start_epoch == self._agent_start_epoch
        )
        if reason in {"expired", "orphaned"}:
            removed = remove_workspace_record(root=root_path, record=workspace_record)
            return {
                "intent_id": workspace_record.intent_id,
                "action_taken": "removed" if removed else "failed",
                "reason": reason,
            }
        if not is_own and not is_orphaned(workspace_record):
            return {
                "intent_id": workspace_record.intent_id,
                "action_taken": "rejected",
                "reason": "foreign_live_intent",
                "agent_pid": workspace_record.agent_pid,
                "agent_start_epoch": workspace_record.agent_start_epoch,
                "agent_label": workspace_record.agent_label,
                "message": (
                    "Intent belongs to a live agent. Coordinate with the owning "
                    "agent or user before resetting it."
                ),
            }
        ttl = resolved_ttl_seconds(
            ttl_seconds,
            env_value=os.environ.get("CODECLONE_INTENT_TTL_SECONDS"),
        )
        updated = update_workspace_intent_status(
            root=root_path,
            pid=workspace_record.agent_pid,
            start_epoch=workspace_record.agent_start_epoch,
            intent_id=workspace_record.intent_id,
            new_status=WorkspaceIntentStatus.ACTIVE.value,
            ttl_seconds=ttl,
        )
        latest = find_workspace_intent(root=root_path, intent_id=intent_id)
        latest_record = latest[1] if latest is not None else workspace_record
        return {
            "intent_id": workspace_record.intent_id,
            "action_taken": "reset" if updated else "failed",
            "new_status": latest_record.status,
            "new_expires_at_utc": latest_record.expires_at_utc,
        }

    def _resolve_workspace_root(self, root: str | None) -> Path:
        if root is not None:
            return _helpers._resolve_root(root)
        try:
            return self._runs.get(None).root
        except MCPRunNotFoundError as exc:
            raise MCPServiceContractError(
                "Workspace intent actions require root or a latest MCP run."
            ) from exc

    def _optional_run_record(self, run_id: str) -> MCPRunRecord | None:
        try:
            return self._runs.get(run_id)
        except MCPRunNotFoundError:
            return None

    def _blast_radius_summary(
        self,
        *,
        blast_payload: Mapping[str, object],
        scope: IntentScope,
    ) -> dict[str, object]:
        affected = tuple(
            sorted(
                {
                    *(
                        str(item)
                        for item in _as_sequence(blast_payload.get("direct_dependents"))
                    ),
                    *(
                        str(item)
                        for item in _as_sequence(
                            blast_payload.get("transitive_dependents")
                        )
                    ),
                    *(
                        str(item)
                        for item in _as_sequence(
                            blast_payload.get("clone_cohort_members")
                        )
                    ),
                }
            )
        )
        return {
            "radius_level": str(blast_payload.get("radius_level", "low")),
            "direct_dependents_count": len(
                _as_sequence(blast_payload.get("direct_dependents"))
            ),
            "clone_cohort_members_count": len(
                _as_sequence(blast_payload.get("clone_cohort_members"))
            ),
            "affected_but_forbidden": list(
                forbidden_touched(
                    changed_files=affected,
                    forbidden_patterns=scope.forbidden,
                )
            ),
            "do_not_touch_count": len(_as_sequence(blast_payload.get("do_not_touch"))),
            "review_context_count": len(
                _as_sequence(blast_payload.get("review_context"))
            ),
        }

    def _intent_check_result(
        self,
        *,
        intent: IntentRecord,
        actual: Sequence[str],
    ) -> IntentCheckResult:
        actual_files = tuple(sorted(set(actual)))
        declared_scope = intent.scope.allowed_files
        allowed = set(intent.scope.allowed_files)
        related = set(intent.scope.allowed_related)
        forbidden = forbidden_touched(
            changed_files=actual_files,
            forbidden_patterns=intent.scope.forbidden,
        )
        unexpected = tuple(
            path
            for path in actual_files
            if path not in allowed
            and path not in related
            and not any(
                fnmatchcase(path, pattern) for pattern in intent.scope.forbidden
            )
        )
        expanded = tuple(path for path in actual_files if path in related)
        if forbidden or unexpected:
            status = IntentStatus.VIOLATED
            required_action = "human_approval"
            message = "Patch touched forbidden or out-of-scope files."
        elif expanded:
            status = IntentStatus.EXPANDED
            required_action = None
            message = "Patch touched allowed related files outside primary scope."
        else:
            status = IntentStatus.CLEAN
            required_action = None
            message = "Patch stayed inside declared scope."
        return IntentCheckResult(
            status=status,
            declared_scope=declared_scope,
            actual_changed_files=actual_files,
            unexpected_files=unexpected,
            forbidden_touched=forbidden,
            required_action=required_action,
            message=message,
        )


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


__all__ = ["_MCPSessionIntentMixin"]

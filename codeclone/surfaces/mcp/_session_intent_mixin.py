# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
from pathlib import Path

from ...audit import (
    EVENT_BLAST_RADIUS,
    EVENT_INTENT_CHECKED,
    EVENT_INTENT_CLEARED,
    EVENT_INTENT_DECLARED,
    EVENT_INTENT_EXPANDED,
    EVENT_INTENT_EXPIRED,
    EVENT_INTENT_RENEWED,
    EVENT_INTENT_VIOLATED,
    EVENT_WORKSPACE_CONFLICT,
    EVENT_WORKSPACE_GC,
)
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
    DEFAULT_LEASE_SECONDS,
    MAX_LEASE_SECONDS,
    MIN_LEASE_SECONDS,
    IntentOwnership,
    WorkspaceIntentRecord,
    WorkspaceIntentStatus,
    classify_intent_ownership,
    compute_scope_digest,
    detect_conflicts,
    expires_at,
    find_workspace_intent,
    format_utc,
    gc_workspace,
    list_workspace_intents,
    remove_workspace_intent,
    remove_workspace_record,
    renew_workspace_intent_lease,
    resolved_lease_seconds,
    resolved_ttl_seconds,
    stale_reason,
    update_workspace_intent_status,
    utc_now,
    workspace_status_counts,
    write_workspace_intent,
)


@dataclass(frozen=True, slots=True)
class _RecoveryTarget:
    root_path: Path
    workspace_record: WorkspaceIntentRecord
    now: datetime


@dataclass(frozen=True, slots=True)
class _RecoveryRun:
    record: MCPRunRecord
    report_digest: str


class _MCPSessionIntentMixin(_MCPSessionBlastRadiusMixin):
    _runs: CodeCloneMCPRunStore
    _active_intents: dict[str, IntentRecord]
    _intent_sequence: int
    _agent_pid: int
    _agent_start_epoch: int
    _agent_label: str

    def _audit_emit(
        self,
        *,
        root: Path,
        event_type: str,
        severity: str,
        run_id: str | None = None,
        intent_id: str | None = None,
        report_digest: str | None = None,
        status: str | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> None:
        raise NotImplementedError

    def get_blast_radius(
        self,
        *,
        files: Sequence[str],
        run_id: str | None = None,
        depth: str = "direct",
        include: Sequence[str] | None = None,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        payload = super().get_blast_radius(
            files=files,
            run_id=record.run_id,
            depth=depth,
            include=include,
        )
        self._renew_lease_for_run(record=record)
        self._audit_emit(
            root=record.root,
            event_type=EVENT_BLAST_RADIUS,
            severity="info",
            run_id=_helpers._short_run_id(record.run_id),
            report_digest=self._report_digest_value(record),
            status=str(payload.get("radius_level", "")),
            payload=payload,
        )
        return payload

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
        lease_seconds: int | None = None,
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
            case "renew":
                return self._renew_change_intent(
                    intent_id=intent_id,
                    lease_seconds=lease_seconds,
                )
            case "list_workspace":
                return self._list_workspace_intents(root=root)
            case "gc_workspace":
                return self._gc_workspace_intents(root=root)
            case "recover":
                return self._recover_change_intent(
                    root=root,
                    run_id=run_id,
                    intent_id=intent_id,
                )
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
                    "gc_workspace, get, list_workspace, recover, renew, "
                    "reset_workspace."
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
            own_start_epoch=self._agent_start_epoch,
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
        self._audit_emit(
            root=record.root,
            event_type=EVENT_INTENT_DECLARED,
            severity="warn" if concurrent_intents else "info",
            run_id=_helpers._short_run_id(record.run_id),
            intent_id=record_payload.intent_id,
            report_digest=record_payload.report_digest,
            status=record_payload.status.value,
            payload=payload,
        )
        if concurrent_intents:
            self._audit_emit(
                root=record.root,
                event_type=EVENT_WORKSPACE_CONFLICT,
                severity="warn",
                run_id=_helpers._short_run_id(record.run_id),
                intent_id=record_payload.intent_id,
                report_digest=record_payload.report_digest,
                status="conflict",
                payload={"concurrent_intents": concurrent_intents},
            )
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
        self._renew_lease_if_active(record=record, intent=active_intent)
        if self._is_intent_expired(record=record, intent=active_intent):
            expired = replace(active_intent, status=IntentStatus.EXPIRED)
            with self._state_lock:
                self._active_intents[expired.intent_id] = expired
            self._sync_workspace_intent_status(record=record, intent=expired)
            payload = expired.to_payload(
                short_run_id=_helpers._short_run_id(record.run_id)
            )
            self._audit_emit(
                root=record.root,
                event_type=EVENT_INTENT_EXPIRED,
                severity="warn",
                run_id=_helpers._short_run_id(record.run_id),
                intent_id=expired.intent_id,
                report_digest=expired.report_digest,
                status=expired.status.value,
                payload=payload,
            )
            return payload
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
        event_type = {
            IntentStatus.EXPANDED: EVENT_INTENT_EXPANDED,
            IntentStatus.VIOLATED: EVENT_INTENT_VIOLATED,
        }.get(check_result.status, EVENT_INTENT_CHECKED)
        self._audit_emit(
            root=record.root,
            event_type=event_type,
            severity="warn" if check_result.status != IntentStatus.CLEAN else "info",
            run_id=_helpers._short_run_id(record.run_id),
            intent_id=updated.intent_id,
            report_digest=updated.report_digest,
            status=check_result.status.value,
            payload=payload,
        )
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
            workspace_targets: tuple[tuple[Path, IntentRecord, str], ...] = tuple(
                (record.root, removed_intent, self._report_digest_value(record))
                for removed_intent in removed_intents
                for record in (self._optional_run_record(removed_intent.run_id),)
                if record is not None
            )
            for removed_intent in removed_intents:
                self._runs.unpin(removed_intent.run_id)
        workspace_cleared = True
        for root_path, removed_intent, _report_digest in workspace_targets:
            workspace_cleared = (
                remove_workspace_intent(
                    root=root_path,
                    pid=self._agent_pid,
                    start_epoch=self._agent_start_epoch,
                    intent_id=removed_intent.intent_id,
                )
                and workspace_cleared
            )
        payload = {
            "cleared": len(removed_ids),
            "cleared_intent_ids": list(removed_ids),
            "workspace_cleared": workspace_cleared,
        }
        for root_path, removed_intent, report_digest in workspace_targets:
            self._audit_emit(
                root=root_path,
                event_type=EVENT_INTENT_CLEARED,
                severity="info",
                run_id=_helpers._short_run_id(removed_intent.run_id),
                intent_id=removed_intent.intent_id,
                report_digest=report_digest,
                status="cleared",
                payload=payload,
            )
        return payload

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
        else:
            self._renew_lease_if_active(record=record, intent=intent)
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
            lease_renewed_at_utc=format_utc(declared_at),
            lease_seconds=resolved_lease_seconds(
                env_value=os.environ.get("CODECLONE_INTENT_LEASE_SECONDS"),
            ),
            report_digest=intent.report_digest,
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

    def _renew_lease_if_active(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord,
    ) -> None:
        try:
            renew_workspace_intent_lease(
                root=record.root,
                pid=self._agent_pid,
                start_epoch=self._agent_start_epoch,
                intent_id=intent.intent_id,
            )
        except Exception:
            return

    def _renew_lease_for_run(self, *, record: MCPRunRecord) -> None:
        with self._state_lock:
            intents = tuple(
                intent
                for intent in self._active_intents.values()
                if intent.run_id == record.run_id
            )
        for intent in intents:
            self._renew_lease_if_active(record=record, intent=intent)

    def _renew_change_intent(
        self,
        *,
        intent_id: str | None,
        lease_seconds: int | None,
    ) -> dict[str, object]:
        if intent_id is None:
            with self._state_lock:
                all_intents = list(self._active_intents.values())
            if not all_intents:
                raise MCPServiceContractError(
                    "action='renew' requires intent_id or an active intent."
                )
            active_intent = all_intents[-1]
            intent_id = active_intent.intent_id
        record, active_intent = self._resolve_intent(
            run_id=None,
            intent_id=intent_id,
        )
        renewed = renew_workspace_intent_lease(
            root=record.root,
            pid=self._agent_pid,
            start_epoch=self._agent_start_epoch,
            intent_id=active_intent.intent_id,
            lease_seconds=lease_seconds,
        )
        latest = (
            find_workspace_intent(root=record.root, intent_id=active_intent.intent_id)
            if renewed
            else None
        )
        latest_record = latest[1] if latest is not None else None
        effective_lease = (
            latest_record.lease_seconds
            if latest_record is not None
            else resolved_lease_seconds(lease_seconds)
        )
        payload: dict[str, object] = {
            "intent_id": active_intent.intent_id,
            "status": active_intent.status.value,
            "lease_renewed": renewed,
            "lease_seconds": effective_lease,
            "lease_expires_at_utc": (
                self._lease_expired_at_utc(latest_record)
                if latest_record is not None
                else None
            ),
            "lease_policy": {
                "min_seconds": MIN_LEASE_SECONDS,
                "default_seconds": DEFAULT_LEASE_SECONDS,
                "max_seconds": MAX_LEASE_SECONDS,
            },
        }
        self._audit_emit(
            root=record.root,
            event_type=EVENT_INTENT_RENEWED,
            severity="info" if renewed else "warn",
            run_id=_helpers._short_run_id(record.run_id),
            intent_id=active_intent.intent_id,
            report_digest=active_intent.report_digest,
            status=active_intent.status.value,
            payload=payload,
        )
        return payload

    def _list_workspace_intents(self, *, root: str | None) -> dict[str, object]:
        root_path = self._resolve_workspace_root(root)
        counts = workspace_status_counts(root=root_path)
        records = list_workspace_intents(root=root_path, exclude_stale=False)
        now = utc_now()
        return {
            "workspace_intents": [
                item.to_payload(
                    own_pid=self._agent_pid,
                    own_start_epoch=self._agent_start_epoch,
                    now=now,
                )
                for item in records
            ],
            "recovery_available": self._recovery_available_payload(
                records=records,
                now=now,
            ),
            "stale_count": counts["stale_count"],
            "orphaned_count": counts["orphaned_count"],
            "total_agents": len({item.agent_pid for item in records}),
            "own_pid": self._agent_pid,
            "own_start_epoch": self._agent_start_epoch,
        }

    def _gc_workspace_intents(self, *, root: str | None) -> dict[str, object]:
        root_path = self._resolve_workspace_root(root)
        payload = gc_workspace(root=root_path)
        self._audit_emit(
            root=root_path,
            event_type=EVENT_WORKSPACE_GC,
            severity="info",
            status="completed",
            payload=payload,
        )
        return payload

    def _recover_change_intent(
        self,
        *,
        root: str | None,
        run_id: str | None,
        intent_id: str | None,
    ) -> dict[str, object]:
        request_error = self._recovery_required_fields_error(
            root=root,
            run_id=run_id,
            intent_id=intent_id,
        )
        if request_error is not None:
            return request_error
        assert root is not None
        assert run_id is not None
        assert intent_id is not None
        target = self._recovery_target(root=root, intent_id=intent_id)
        if isinstance(target, dict):
            return target
        recovery_run = self._recovery_run(run_id=run_id, target=target)
        if isinstance(recovery_run, dict):
            return recovery_run
        recovered = self._activate_recovered_intent(
            target=target,
            recovery_run=recovery_run,
        )
        if isinstance(recovered, dict):
            return recovered
        workspace_update = self._rewrite_recovered_workspace_record(
            target=target,
            recovery_run=recovery_run,
            recovered=recovered,
        )
        if isinstance(workspace_update, dict):
            return workspace_update
        recovered_at, previous_removed = workspace_update
        return self._recovered_payload(
            target=target,
            recovery_run=recovery_run,
            recovered=recovered,
            recovered_at=recovered_at,
            previous_removed=previous_removed,
        )

    def _recovery_required_fields_error(
        self,
        *,
        root: str | None,
        run_id: str | None,
        intent_id: str | None,
    ) -> dict[str, object] | None:
        if intent_id is None:
            return self._recovery_rejected(
                intent_id=None,
                reason="missing_intent_id",
                message="action='recover' requires intent_id.",
            )
        if run_id is None:
            return self._recovery_rejected(
                intent_id=intent_id,
                reason="missing_run_id",
                message="action='recover' requires run_id.",
            )
        if root is None:
            return self._recovery_rejected(
                intent_id=intent_id,
                reason="missing_root",
                message="action='recover' requires root.",
            )
        return None

    def _recovery_target(
        self,
        *,
        root: str,
        intent_id: str,
    ) -> _RecoveryTarget | dict[str, object]:
        root_path = self._resolve_workspace_root(root)
        found = find_workspace_intent(root=root_path, intent_id=intent_id)
        if found is None:
            return self._recovery_rejected(
                intent_id=intent_id,
                reason="not_found",
                message=f"No workspace intent found for intent_id: {intent_id}.",
            )
        _, workspace_record = found
        now = utc_now()
        ownership = classify_intent_ownership(
            workspace_record,
            own_pid=self._agent_pid,
            own_start_epoch=self._agent_start_epoch,
            now=now,
        )
        if ownership not in {IntentOwnership.RECOVERABLE, IntentOwnership.OWN_STALE}:
            return self._recovery_rejected(
                intent_id=intent_id,
                reason="not_recoverable",
                message=self._recovery_rejection_message(ownership),
                details={"ownership": ownership.value},
            )
        return _RecoveryTarget(
            root_path=root_path,
            workspace_record=workspace_record,
            now=now,
        )

    def _recovery_run(
        self,
        *,
        run_id: str,
        target: _RecoveryTarget,
    ) -> _RecoveryRun | dict[str, object]:
        workspace_record = target.workspace_record
        try:
            record = self._runs.get(run_id)
        except MCPRunNotFoundError:
            return self._recovery_rejected(
                intent_id=workspace_record.intent_id,
                reason="run_not_available",
                message=(
                    f"Run {run_id} is not available in this session. "
                    "Run analyze_repository first."
                ),
            )
        report_digest = self._report_digest_value(record)
        if report_digest != workspace_record.report_digest:
            return self._recovery_rejected(
                intent_id=workspace_record.intent_id,
                reason="report_digest_mismatch",
                message=(
                    "Report digest does not match. The analysis run may have "
                    "changed since the intent was declared."
                ),
                details={
                    "expected": workspace_record.report_digest,
                    "actual": report_digest,
                },
            )
        if (
            compute_scope_digest(workspace_record.scope)
            != workspace_record.scope_digest
        ):
            return self._recovery_rejected(
                intent_id=workspace_record.intent_id,
                reason="scope_digest_mismatch",
                message="Workspace intent scope digest does not match.",
            )
        return _RecoveryRun(record=record, report_digest=report_digest)

    def _activate_recovered_intent(
        self,
        *,
        target: _RecoveryTarget,
        recovery_run: _RecoveryRun,
    ) -> IntentRecord | dict[str, object]:
        workspace_record = target.workspace_record
        with self._state_lock:
            if workspace_record.intent_id in self._active_intents:
                return self._recovery_rejected(
                    intent_id=workspace_record.intent_id,
                    reason="already_active",
                    message=(
                        f"Intent {workspace_record.intent_id} is already active "
                        "in this session."
                    ),
                )
            try:
                scope = normalize_intent_scope(workspace_record.scope)
            except ValueError as exc:
                return self._recovery_rejected(
                    intent_id=workspace_record.intent_id,
                    reason="invalid_scope",
                    message=str(exc),
                )
            recovered = IntentRecord(
                intent_id=workspace_record.intent_id,
                run_id=recovery_run.record.run_id,
                report_digest=recovery_run.report_digest,
                status=IntentStatus.ACTIVE,
                declared_at_utc=workspace_record.declared_at_utc,
                scope=scope,
                intent_description=workspace_record.intent,
                expected_effects=(),
                guards=DEFAULT_INTENT_GUARDS,
                blast_radius_summary=dict(workspace_record.blast_radius_summary),
            )
            self._active_intents[workspace_record.intent_id] = recovered
            self._runs.pin(recovery_run.record.run_id)
        return recovered

    def _rewrite_recovered_workspace_record(
        self,
        *,
        target: _RecoveryTarget,
        recovery_run: _RecoveryRun,
        recovered: IntentRecord,
    ) -> tuple[str, bool] | dict[str, object]:
        workspace_record = target.workspace_record
        recovered_at = format_utc(target.now)
        updated_workspace_record = replace(
            workspace_record,
            agent_pid=self._agent_pid,
            agent_start_epoch=self._agent_start_epoch,
            agent_label=self._agent_label,
            status=WorkspaceIntentStatus.ACTIVE.value,
            lease_renewed_at_utc=recovered_at,
            report_digest=recovery_run.report_digest,
        )
        if not write_workspace_intent(
            root=target.root_path,
            record=updated_workspace_record,
        ):
            self._rollback_recovered_intent(recovered)
            return self._recovery_rejected(
                intent_id=workspace_record.intent_id,
                reason="workspace_rewrite_failed",
                message="Failed to rewrite workspace intent owner.",
            )
        previous_removed = True
        if (
            workspace_record.agent_pid != self._agent_pid
            or workspace_record.agent_start_epoch != self._agent_start_epoch
        ):
            previous_removed = remove_workspace_record(
                root=target.root_path,
                record=workspace_record,
            )
        return recovered_at, previous_removed

    def _rollback_recovered_intent(self, recovered: IntentRecord) -> None:
        with self._state_lock:
            self._active_intents.pop(recovered.intent_id, None)
            self._runs.unpin(recovered.run_id)

    def _recovered_payload(
        self,
        *,
        target: _RecoveryTarget,
        recovery_run: _RecoveryRun,
        recovered: IntentRecord,
        recovered_at: str,
        previous_removed: bool,
    ) -> dict[str, object]:
        workspace_record = target.workspace_record
        return {
            "intent_id": recovered.intent_id,
            "action_taken": "recovered",
            "run_id": _helpers._short_run_id(recovery_run.record.run_id),
            "scope": recovered.scope.to_payload(),
            "previous_owner": {
                "agent_pid": workspace_record.agent_pid,
                "agent_start_epoch": workspace_record.agent_start_epoch,
                "agent_label": workspace_record.agent_label,
                "lease_renewed_at_utc": workspace_record.lease_renewed_at_utc,
            },
            "new_owner": {
                "agent_pid": self._agent_pid,
                "agent_start_epoch": self._agent_start_epoch,
                "agent_label": self._agent_label,
            },
            "recovered_at_utc": recovered_at,
            "previous_workspace_record_removed": previous_removed,
            "next_steps": [
                "Run manage_change_intent(action='get') to inspect recovered state.",
                "Run check_patch_contract(mode='budget') to verify patch budget.",
                "Continue editing within declared scope.",
            ],
        }

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
        now = utc_now()
        ownership = classify_intent_ownership(
            workspace_record,
            own_pid=self._agent_pid,
            own_start_epoch=self._agent_start_epoch,
            now=now,
        )
        if ownership in {IntentOwnership.EXPIRED, IntentOwnership.RECOVERABLE}:
            removed = remove_workspace_record(root=root_path, record=workspace_record)
            reason = (
                "expired"
                if ownership == IntentOwnership.EXPIRED
                else stale_reason(workspace_record) or "recoverable"
            )
            return {
                "intent_id": workspace_record.intent_id,
                "action_taken": "removed" if removed else "failed",
                "reason": reason,
            }
        if ownership in {IntentOwnership.FOREIGN_ACTIVE, IntentOwnership.FOREIGN_STALE}:
            hint = (
                (
                    "This intent belongs to a live process with a valid lease. "
                    "Do NOT kill the process. Ask the user to confirm whether "
                    "this is an abandoned session or a parallel agent."
                )
                if ownership == IntentOwnership.FOREIGN_ACTIVE
                else (
                    "This intent belongs to a live process whose lease has expired. "
                    "The owner may still be working. Coordinate with the user "
                    "before resetting."
                )
            )
            return {
                "intent_id": workspace_record.intent_id,
                "action_taken": "rejected",
                "reason": ownership.value,
                "ownership": ownership.value,
                "agent_pid": workspace_record.agent_pid,
                "agent_start_epoch": workspace_record.agent_start_epoch,
                "agent_label": workspace_record.agent_label,
                "escalation_hint": hint,
                "message": (
                    "Intent belongs to a live process. Coordinate "
                    "with the owning agent or user before resetting it."
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

    def _recovery_available_payload(
        self,
        *,
        records: Sequence[WorkspaceIntentRecord],
        now: datetime,
    ) -> list[dict[str, object]]:
        available: list[dict[str, object]] = []
        for record in records:
            ownership = classify_intent_ownership(
                record,
                own_pid=self._agent_pid,
                own_start_epoch=self._agent_start_epoch,
                now=now,
            )
            if ownership != IntentOwnership.RECOVERABLE:
                continue
            if self._optional_run_record(record.run_id) is None:
                continue
            available.append(
                {
                    "intent_id": record.intent_id,
                    "run_id": _helpers._short_run_id(record.run_id),
                    "scope_digest": record.scope_digest,
                    "previous_agent_label": record.agent_label,
                    "lease_expired_at_utc": self._lease_expired_at_utc(record),
                    "hint": ("Use action='recover' with matching run_id to reclaim."),
                }
            )
        return sorted(
            available,
            key=lambda item: (
                str(item["previous_agent_label"]),
                str(item["intent_id"]),
            ),
        )

    def _lease_expired_at_utc(self, record: WorkspaceIntentRecord) -> str | None:
        renewed_at = _parse_utc(record.lease_renewed_at_utc)
        if renewed_at is None:
            return None
        return format_utc(renewed_at + timedelta(seconds=record.lease_seconds))

    def _recovery_rejected(
        self,
        *,
        intent_id: str | None,
        reason: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "intent_id": intent_id,
            "action_taken": "recovery_rejected",
            "reason": reason,
            "message": message,
            "details": dict(details or {}),
        }

    def _recovery_rejection_message(self, ownership: IntentOwnership) -> str:
        if ownership == IntentOwnership.FOREIGN_ACTIVE:
            return (
                "Intent has a valid lease from a live process. Cannot recover. "
                "Use action='list_workspace' to inspect, then coordinate with "
                "the user."
            )
        if ownership == IntentOwnership.FOREIGN_STALE:
            return (
                "Intent belongs to a live process with an expired lease. "
                "The owner may still be working. Coordinate with the user "
                "before recovering."
            )
        if ownership == IntentOwnership.EXPIRED:
            return "Intent has expired (TTL). Declare a new intent instead."
        if ownership == IntentOwnership.OWN_ACTIVE:
            return "Intent is already actively owned by this session."
        return "Intent is not recoverable."

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

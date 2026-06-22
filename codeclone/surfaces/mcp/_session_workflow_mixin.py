# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Workflow-level orchestration for agent change control.

``start_controlled_change`` and ``finish_controlled_change`` aggregate
atomic change-control steps into two workflow calls.  They call existing
internal methods only — no new engine logic.

Design invariants (phase-16 spec):
- No implicit ``analyze_repository``.
- No hidden boundary decisions.
- ``check`` before ``verify`` is mandatory (check writes state).
- Changed files resolved once from exactly one source.
- ``auto_clear`` only on ``accepted`` / ``accepted_with_external_changes``.
- Audit events are emitted by the internal methods, not duplicated here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from ...audit.events import EVENT_PATCH_TRAIL_COMPUTED
from ...memory.trajectory.patch_trail import compute_patch_trail
from . import _session_helpers as _helpers
from ._blast_radius import BlastRadiusResult, blast_radius_to_payload
from ._context_governance import attach_passive_context_governance
from ._intent import IntentRecord, IntentStatus
from ._patch_contract import PatchContractStatus
from ._patch_trail_bridge import build_patch_trail_inputs
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunRecord,
    MCPServiceContractError,
)
from ._workspace_hygiene import WorkspaceHygieneResult
from .messages import errors as err_msgs
from .messages import workflow as workflow_msgs

TRANSITIVE_SUMMARY_LIMIT: Final[int] = 10

VALID_BLAST_RADIUS_DEPTHS: Final[frozenset[str]] = frozenset(
    {"direct", "transitive", "auto"}
)

_ACCEPTED_STATUSES: Final[frozenset[str]] = frozenset(
    {
        PatchContractStatus.ACCEPTED.value,
        PatchContractStatus.ACCEPTED_EXTERNAL.value,
    }
)


class _MCPSessionWorkflowMixin:
    """Workflow orchestration over atomic change-control primitives."""

    _runs: CodeCloneMCPRunStore
    _active_intents: dict[str, IntentRecord]

    # ------------------------------------------------------------------
    # start_controlled_change
    # ------------------------------------------------------------------

    def start_controlled_change(
        self,
        *,
        root: str,
        scope: dict[str, object],
        intent: str,
        expected_effects: Sequence[str] | None = None,
        on_conflict: str | None = None,
        strictness: str = "ci",
        ttl_seconds: int | None = None,
        blast_radius_depth: str = "auto",
        dirty_scope_policy: str = "block",
    ) -> dict[str, object]:
        validated_depth = _validated_blast_radius_depth(blast_radius_depth)
        validated_dirty_scope_policy = _validated_dirty_scope_policy(dirty_scope_policy)
        root_path = _helpers._resolve_root(root)

        # 1. Workspace check (lazy close inside list_workspace)
        self._list_workspace_intents(root=root)

        # 2. Root-aware run resolution (not _runs.get(None) — multi-repo safe)
        record = self._latest_run_for_root(root_path)
        if record is None:
            return _helpers.attach_workspace_hygiene_tips(
                {
                    "status": "needs_analysis",
                    "intent_id": None,
                    "edit_allowed": False,
                    "root": str(root_path),
                    "message": workflow_msgs.START_NEEDS_ANALYSIS,
                    "workspace": _workspace_summary_from_declare({}, {}),
                },
                root=root_path,
            )

        # 3. Declare intent
        declare_payload = self._declare_change_intent(
            run_id=record.run_id,
            scope=scope,
            intent=intent,
            expected_effects=expected_effects,
            ttl_seconds=ttl_seconds,
            on_conflict=on_conflict,
        )

        intent_id = str(declare_payload.get("intent_id", ""))
        declare_status = str(declare_payload.get("status", ""))

        # Queued: no blast radius or budget
        if declare_status == IntentStatus.QUEUED.value:
            workspace_after = self._list_workspace_intents(root=root)
            queued_payload: dict[str, object] = {
                "intent_id": intent_id,
                "status": "queued",
                "run_id": _helpers._short_run_id(record.run_id),
                "blocked_by": declare_payload.get("blocked_by", []),
                "queue_position": declare_payload.get("queue_position", 1),
                "before_run_pinned": declare_payload.get("before_run_pinned", False),
                "edit_allowed": False,
                "workspace": _workspace_summary_from_declare(
                    workspace_after,
                    declare_payload,
                ),
                "message": workflow_msgs.START_QUEUED,
            }
            dirty_snapshot = declare_payload.get("dirty_snapshot")
            if isinstance(dirty_snapshot, dict):
                queued_payload["dirty_snapshot"] = dirty_snapshot
            return _helpers.attach_workspace_hygiene_tips(
                queued_payload,
                root=root_path,
            )

        # 4. Fresh workspace snapshot after declare
        workspace_after = self._list_workspace_intents(root=root)

        with self._state_lock:
            active_intent = self._active_intents.get(intent_id)
        if active_intent is None:
            raise MCPServiceContractError(
                f"Intent {intent_id} not found after declare."
            )

        from ._workspace_hygiene import evaluate_scoped_hygiene
        from ._workspace_intent_store import get_workspace_intent_store

        hygiene = evaluate_scoped_hygiene(
            root=root_path,
            allowed_files=active_intent.scope.allowed_files,
            allowed_related=active_intent.scope.allowed_related,
            store=get_workspace_intent_store(root_path),
            own_pid=self._agent_pid,
            own_start_epoch=self._agent_start_epoch,
            own_intent_id=intent_id,
        )

        # 5. Blast radius (full payload, not just declare's subset)
        blast_result = self._blast_radius_result(
            record=record,
            files=active_intent.scope.allowed_paths,
            depth="direct",
            forbidden_patterns=active_intent.scope.forbidden,
        )
        blast_payload = blast_radius_to_payload(blast_result)

        # 6. Transitive summary (auto-escalated or explicit)
        transitive_summary = self._compute_transitive_summary(
            record=record,
            intent=active_intent,
            blast_result=blast_result,
            depth=validated_depth,
        )
        if transitive_summary is not None:
            blast_payload["transitive_summary"] = transitive_summary

        # 7. Budget
        budget_payload = self._patch_contract_budget(
            run_id=record.run_id,
            intent_id=intent_id,
            strictness=self._validated_strictness(strictness),
        )

        concurrent_intents = _as_conflict_list(
            declare_payload.get("concurrent_intents")
        )
        coordination_blocked = bool(concurrent_intents) and on_conflict != "queue"
        edit_allowed = _start_edit_allowed(
            declare_status=declare_status,
            concurrent_intents=concurrent_intents,
            on_conflict=on_conflict,
            hygiene=hygiene,
            dirty_scope_policy=validated_dirty_scope_policy,
        )
        workflow_status = _start_workflow_status(
            declare_status=declare_status,
            coordination_blocked=coordination_blocked,
            hygiene=hygiene,
            dirty_scope_policy=validated_dirty_scope_policy,
        )

        continuing_own_wip = (
            validated_dirty_scope_policy == "continue_own_wip"
            and hygiene.blocks_edit
            and not hygiene.foreign_dirty_overlaps
            and workflow_status == "active"
        )

        payload: dict[str, object] = {
            "intent_id": intent_id,
            "status": workflow_status,
            "run_id": _helpers._short_run_id(record.run_id),
            "dirty_scope_policy": validated_dirty_scope_policy,
            "workspace": _workspace_summary_from_declare(
                workspace_after,
                declare_payload,
            ),
            "blast_radius": blast_payload,
            "budget": _budget_summary(budget_payload),
            "scope": active_intent.scope.to_payload(),
            "edit_allowed": edit_allowed,
            "message": self._start_message(
                workflow_status=workflow_status,
                blast_payload=blast_payload,
                budget_payload=budget_payload,
                concurrent_intents=concurrent_intents,
                hygiene=hygiene,
                continuing_own_wip=continuing_own_wip,
            ),
        }
        dirty_snapshot = declare_payload.get("dirty_snapshot")
        if isinstance(dirty_snapshot, dict):
            payload["dirty_snapshot"] = dirty_snapshot
        if hygiene.git_available or hygiene.blocks_edit:
            hygiene_payload = hygiene.to_payload()
            if continuing_own_wip:
                hygiene_payload["continuing_own_wip"] = True
            payload["workspace_hygiene"] = hygiene_payload
        if not edit_allowed:
            payload["user_action_required"] = True
            payload["next_step"] = _start_next_step(
                concurrent_intents=concurrent_intents,
                hygiene=hygiene,
                dirty_scope_policy=validated_dirty_scope_policy,
            )
        return _helpers.attach_workspace_hygiene_tips(payload, root=root_path)

    # ------------------------------------------------------------------
    # finish_controlled_change
    # ------------------------------------------------------------------

    def finish_controlled_change(
        self,
        *,
        intent_id: str,
        changed_files: Sequence[str] | None = None,
        diff_ref: str | None = None,
        after_run_id: str | None = None,
        review_text: str | None = None,
        claims_text: str | None = None,
        create_receipt: bool = True,
        auto_clear: bool = True,
        strictness: str = "ci",
        propose_memory: bool = False,
        detail_level: str = "summary",
        patch_trail_detail: str = "summary",
    ) -> dict[str, object]:
        # 1. Resolve intent
        record, active_intent = self._resolve_intent(
            run_id=None,
            intent_id=intent_id,
        )

        # Queued intents cannot be verified
        if active_intent.status == IntentStatus.QUEUED:
            return attach_passive_context_governance(
                {
                    "intent_id": intent_id,
                    "status": "unverified",
                    "reason": "intent_not_active",
                    "scope_check": None,
                    "verification": None,
                    "claims": None,
                    "receipt": None,
                    "intent_cleared": False,
                    "user_action_required": False,
                    "next_step": workflow_msgs.FINISH_PROMOTE_BEFORE_VERIFY,
                    "message": workflow_msgs.FINISH_QUEUED_NOT_ACTIVE,
                }
            )

        # 2. Resolve changed files — exactly one source
        resolved_files = self._resolve_changed_files_once(
            root_path=record.root,
            changed_files=changed_files,
            diff_ref=diff_ref,
        )

        from ._workspace_hygiene import (
            dirty_snapshot_from_payload,
            finish_hygiene_check,
            workspace_dirty_summary,
        )
        from ._workspace_intent_store import get_workspace_intent_store

        intent_store = get_workspace_intent_store(record.root)
        workspace_record = intent_store.find_raw(intent_id)
        start_dirty_snapshot = dirty_snapshot_from_payload(
            workspace_record.dirty_snapshot if workspace_record is not None else None
        )
        finish_hygiene = finish_hygiene_check(
            root=record.root,
            allowed_files=active_intent.scope.allowed_files,
            allowed_related=active_intent.scope.allowed_related,
            resolved_files=resolved_files,
            store=intent_store,
            own_pid=self._agent_pid,
            own_start_epoch=self._agent_start_epoch,
            own_intent_id=intent_id,
            start_dirty_snapshot=start_dirty_snapshot,
        )
        workspace_hygiene_after = {
            **finish_hygiene.to_payload(detail_level=detail_level),
            "workspace_dirty_summary": workspace_dirty_summary(root=record.root),
        }
        if finish_hygiene.blocks_finish:
            block_reason = finish_hygiene.finish_block_reason or ""
            # Only proven patch/scope conflicts block finish: in-scope dirt
            # missing from evidence, or a live foreign intent overlapping the
            # declared scope. Out-of-scope unattributed dirt is advisory.
            detail_message = {
                "missing_evidence": workflow_msgs.FINISH_HYGIENE_MISSING_EVIDENCE,
                "foreign_dirty_overlap": workflow_msgs.FINISH_HYGIENE_FOREIGN_DIRTY,
            }.get(block_reason, workflow_msgs.FINISH_HYGIENE_BLOCKED)
            return attach_passive_context_governance(
                {
                    "intent_id": intent_id,
                    "status": "unverified",
                    "reason": "workspace_hygiene",
                    "scope_check": None,
                    "verification": None,
                    "claims": None,
                    "receipt": None,
                    "intent_cleared": False,
                    "user_action_required": True,
                    "next_step": workflow_msgs.FINISH_HYGIENE_NEXT,
                    "workspace_hygiene_after": workspace_hygiene_after,
                    "message": detail_message,
                }
            )

        scope_files = (
            finish_hygiene.files_for_scope_check
            if finish_hygiene.files_for_scope_check
            else resolved_files
        )

        # 3. Check (writes IntentRecord.check_result — required for receipt)
        check_payload = self._check_change_intent(
            run_id=None,
            intent_id=intent_id,
            diff_ref=None,
            changed_files=scope_files,
        )
        check_status = str(check_payload.get("status", ""))
        scope_check_audit_sequence = _pop_audit_sequence(check_payload)

        # Expired intent
        if check_status == IntentStatus.EXPIRED.value:
            return attach_passive_context_governance(
                {
                    "intent_id": intent_id,
                    "status": "expired",
                    "reason": "report_digest_mismatch",
                    "scope_check": check_payload,
                    "verification": None,
                    "claims": None,
                    "receipt": None,
                    "intent_cleared": False,
                    "user_action_required": True,
                    "next_step": workflow_msgs.FINISH_DIGEST_MISMATCH_NEXT,
                    "message": workflow_msgs.FINISH_DIGEST_MISMATCH,
                }
            )

        # 4. Scope violation — early exit
        if check_status == IntentStatus.VIOLATED.value:
            return attach_passive_context_governance(
                {
                    "intent_id": intent_id,
                    "status": "violated",
                    "reason": "scope_violation",
                    "scope_check": check_payload,
                    "verification": None,
                    "claims": None,
                    "receipt": None,
                    "patch_trail": self._finish_patch_trail(
                        record=record,
                        intent=active_intent,
                        check_payload=check_payload,
                        verify_payload=_NOT_REACHED_VERIFY_PAYLOAD,
                        finish_hygiene=finish_hygiene,
                        scope_check_audit_sequence=scope_check_audit_sequence,
                        patch_verify_audit_sequence=None,
                        patch_trail_detail=patch_trail_detail,
                    ),
                    "intent_cleared": False,
                    "user_action_required": True,
                    "next_step": workflow_msgs.FINISH_SCOPE_VIOLATION_NEXT,
                    "message": workflow_msgs.FINISH_SCOPE_VIOLATION,
                }
            )

        # 5. Verify (before_run_id auto-resolves from intent)
        verify_payload = self._patch_contract_verify(
            before_run_id=None,
            after_run_id=after_run_id,
            intent_id=intent_id,
            strictness=self._validated_strictness(strictness),
            diff_ref=None,
            changed_files=scope_files,
        )
        verify_status = str(verify_payload.get("status", ""))
        patch_verify_audit_sequence = _pop_audit_sequence(verify_payload)
        patch_trail_payload = self._finish_patch_trail(
            record=record,
            intent=active_intent,
            check_payload=check_payload,
            verify_payload=verify_payload,
            finish_hygiene=finish_hygiene,
            scope_check_audit_sequence=scope_check_audit_sequence,
            patch_verify_audit_sequence=patch_verify_audit_sequence,
            patch_trail_detail=patch_trail_detail,
        )

        # 6. Non-accepted verification — return without receipt/clear
        if verify_status not in _ACCEPTED_STATUSES:
            return attach_passive_context_governance(
                {
                    "intent_id": intent_id,
                    "status": verify_status,
                    "reason": str(verify_payload.get("reason", "")),
                    "scope_check": check_payload,
                    "verification": verify_payload,
                    "claims": None,
                    "receipt": None,
                    "patch_trail": patch_trail_payload,
                    "intent_cleared": False,
                    "workspace_hygiene_after": workspace_hygiene_after,
                    "summary": _finish_summary(
                        verify_status=verify_status,
                        intent_cleared=False,
                        check_payload=check_payload,
                        verify_payload=verify_payload,
                        claims_payload=None,
                        receipt_payload=None,
                        receipt_error=None,
                        workspace_hygiene_after=workspace_hygiene_after,
                        review_text_present=bool(review_text),
                        claims_text_present=bool(claims_text),
                    ),
                    "user_action_required": verify_status
                    == PatchContractStatus.VIOLATED.value,
                    "next_step": verify_payload.get("next_step"),
                    "message": str(verify_payload.get("message", "")),
                }
            )

        health_regression_advisory = verify_payload.get("health_regression_advisory")
        claims_payload = self._conditional_claim_validation(
            record=record,
            verify_payload=verify_payload,
            claims_text=claims_text,
        )

        # 8. Receipt (after claims, before clear)
        receipt_payload: dict[str, object] | None = None
        receipt_error: str | None = None
        if create_receipt:
            try:
                receipt_payload = self.create_review_receipt(
                    run_id=record.run_id,
                    intent_id=intent_id,
                )
            except MCPServiceContractError as exc:
                receipt_error = str(exc)

        # 9. Auto-clear (only on accepted, only if receipt didn't fail)
        intent_cleared = False
        if auto_clear and verify_status in _ACCEPTED_STATUSES and receipt_error is None:
            self._clear_change_intent(intent_id=intent_id)
            intent_cleared = True

        # External workspace changes (dirty outside the declared scope) are
        # advisory, never blocking; a clean accepted verdict is elevated to
        # accepted_with_external_changes. See _external_change_advisory.
        effective_status, external_advisory = _external_change_advisory(
            verify_status,
            finish_hygiene.dirty_paths_outside_scope,
        )

        # 10. Compose response
        result: dict[str, object] = {
            "intent_id": intent_id,
            "status": effective_status,
            "reason": verify_payload.get("reason"),
            "scope_check": check_payload,
            "verification": verify_payload,
            "claims": claims_payload,
            "receipt": receipt_payload,
            "patch_trail": patch_trail_payload,
            "intent_cleared": intent_cleared,
            "workspace_hygiene_after": workspace_hygiene_after,
            "summary": _finish_summary(
                verify_status=verify_status,
                intent_cleared=intent_cleared,
                check_payload=check_payload,
                verify_payload=verify_payload,
                claims_payload=claims_payload,
                receipt_payload=receipt_payload,
                receipt_error=receipt_error,
                workspace_hygiene_after=workspace_hygiene_after,
                review_text_present=bool(review_text),
                claims_text_present=bool(claims_text),
            ),
            "user_action_required": False,
            "message": self._finish_message(
                verify_status=verify_status,
                intent_cleared=intent_cleared,
                receipt_error=receipt_error,
            ),
        }
        if receipt_error is not None:
            result["receipt_error"] = receipt_error
        if external_advisory is not None:
            result["external_changes"] = external_advisory
        if isinstance(health_regression_advisory, dict):
            result["health_regression_advisory"] = health_regression_advisory
        if propose_memory and verify_status in _ACCEPTED_STATUSES:
            profile = verify_payload.get("verification_profile")
            memory_hook = self.finish_propose_memory(
                root_path=record.root,
                changed_files=resolved_files,
                claims_text=claims_text,
                review_text=review_text,
                verification_profile=(str(profile) if profile is not None else None),
            )
            if memory_hook:
                result.update(memory_hook)
        if verify_status in _ACCEPTED_STATUSES:
            projection_hook = self.maybe_auto_enqueue_projection_rebuild(
                root_path=record.root,
            )
            if projection_hook is not None:
                result["projection_rebuild"] = projection_hook
        return attach_passive_context_governance(result)

    def _finish_patch_trail(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord,
        check_payload: dict[str, object],
        verify_payload: dict[str, object],
        finish_hygiene: WorkspaceHygieneResult,
        scope_check_audit_sequence: int | None,
        patch_verify_audit_sequence: int | None,
        patch_trail_detail: str,
    ) -> dict[str, object]:
        detail = "full" if patch_trail_detail == "full" else "summary"
        inputs = build_patch_trail_inputs(
            root_path=record.root,
            intent=intent,
            check_payload=check_payload,
            verify_payload=verify_payload,
            hygiene=finish_hygiene,
            report_digest=intent.report_digest,
            scope_check_audit_sequence=scope_check_audit_sequence,
            patch_verify_audit_sequence=patch_verify_audit_sequence,
        )
        trail = compute_patch_trail(inputs)
        severity = (
            "warn"
            if trail.scope_check_status == IntentStatus.VIOLATED.value
            or trail.verification_status
            not in {
                *_ACCEPTED_STATUSES,
                "not_reached",
            }
            else "info"
        )
        patch_trail_audit_sequence = self._audit_emit(
            root=record.root,
            event_type=EVENT_PATCH_TRAIL_COMPUTED,
            severity=severity,
            run_id=_helpers._short_run_id(record.run_id),
            intent_id=intent.intent_id,
            report_digest=intent.report_digest,
            status=trail.scope_check_status,
            payload=trail.audit_payload(),
        )
        payload = trail.to_payload(detail_level=detail)
        if patch_trail_audit_sequence is not None:
            evidence_raw = payload.get("evidence", {})
            if isinstance(evidence_raw, Mapping):
                evidence = dict(evidence_raw)
                evidence["patch_trail_audit_sequence"] = patch_trail_audit_sequence
                payload["evidence"] = evidence
        return payload

    # ------------------------------------------------------------------
    # Internal helpers (no new engine logic)
    # ------------------------------------------------------------------

    def _latest_run_for_root(self, root_path: Path) -> MCPRunRecord | None:
        """Find the latest run matching the requested root (root-safe)."""
        resolved = root_path.resolve()
        latest: MCPRunRecord | None = None
        for record in self._runs.records():
            if record.root == resolved:
                latest = record
        return latest

    def _resolve_changed_files_once(
        self,
        *,
        root_path: Path,
        changed_files: Sequence[str] | None,
        diff_ref: str | None,
    ) -> tuple[str, ...]:
        """Resolve changed files from exactly one source.

        Contract: providing both or neither is a contract error.
        ``diff_ref`` is resolved here and never passed further.
        """
        has_files = changed_files is not None and len(changed_files) > 0
        has_ref = diff_ref is not None and str(diff_ref).strip() != ""
        if has_files and has_ref:
            raise MCPServiceContractError(workflow_msgs.FINISH_EVIDENCE_XOR)
        if has_ref:
            return _require_non_empty_changed_evidence(
                self._git_diff_paths(
                    root_path=root_path,
                    git_diff_ref=str(diff_ref),
                )
            )
        if has_files:
            assert changed_files is not None
            return _require_non_empty_changed_evidence(
                self._normalize_changed_paths(
                    root_path=root_path,
                    paths=changed_files,
                )
            )
        raise MCPServiceContractError(workflow_msgs.FINISH_EVIDENCE_REQUIRED)

    def _compute_transitive_summary(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord,
        blast_result: BlastRadiusResult,
        depth: str,
    ) -> dict[str, object] | None:
        """Compute bounded transitive summary when appropriate."""
        needs_transitive = depth == "transitive" or (
            depth == "auto" and blast_result.radius_level == "high"
        )
        if not needs_transitive:
            return None

        transitive_result = self._blast_radius_result(
            record=record,
            files=intent.scope.allowed_paths,
            depth="transitive",
            forbidden_patterns=intent.scope.forbidden,
        )
        all_transitive = transitive_result.transitive_dependents
        shown = min(len(all_transitive), TRANSITIVE_SUMMARY_LIMIT)
        return {
            "total": len(all_transitive),
            "shown": shown,
            "truncated": shown < len(all_transitive),
            "top_paths": list(all_transitive[:TRANSITIVE_SUMMARY_LIMIT]),
        }

    def _conditional_claim_validation(
        self,
        *,
        record: MCPRunRecord,
        verify_payload: dict[str, object],
        claims_text: str | None,
    ) -> dict[str, object] | None:
        """Run claim validation only when both conditions are met."""
        if not claims_text:
            return None
        if not verify_payload.get("claim_validation_recommended"):
            return None
        structural_delta = verify_payload.get("structural_delta")
        patch_health_delta: int | None = None
        if isinstance(structural_delta, dict):
            health_delta = structural_delta.get("health_delta")
            if isinstance(health_delta, int):
                patch_health_delta = health_delta
        return _helpers.coerce_object_dict(
            self.validate_review_claims(
                text=claims_text,
                run_id=record.run_id,
                patch_health_delta=patch_health_delta,
            )
        )

    @staticmethod
    def _start_message(
        *,
        workflow_status: str,
        blast_payload: dict[str, object],
        budget_payload: dict[str, object],
        concurrent_intents: list[dict[str, object]],
        hygiene: object,
        continuing_own_wip: bool = False,
    ) -> str:
        if workflow_status == "blocked":
            return _start_next_step(
                concurrent_intents=concurrent_intents,
                hygiene=hygiene,
                dirty_scope_policy="block",
            )
        gate = budget_payload.get("gate_preview")
        return workflow_msgs.start_controlled_change_message(
            radius_level=str(blast_payload.get("radius_level", "low")),
            budget_would_fail=(isinstance(gate, dict) and bool(gate.get("would_fail"))),
            continuing_own_wip=continuing_own_wip,
        )

    @staticmethod
    def _finish_message(
        *,
        verify_status: str,
        intent_cleared: bool,
        receipt_error: str | None,
    ) -> str:
        return workflow_msgs.finish_controlled_change_message(
            verify_status=verify_status,
            intent_cleared=intent_cleared,
            receipt_error=receipt_error,
        )


def _validated_blast_radius_depth(value: str) -> str:
    if value not in VALID_BLAST_RADIUS_DEPTHS:
        raise MCPServiceContractError(
            err_msgs.invalid_choice(
                "blast_radius_depth",
                value,
                VALID_BLAST_RADIUS_DEPTHS,
            )
        )
    return value


def _workspace_summary_from_declare(
    workspace: dict[str, object],
    declare_payload: dict[str, object],
) -> dict[str, object]:
    """Merge fresh workspace counts with declare conflict context."""
    concurrent_intents = declare_payload.get("concurrent_intents")
    if not concurrent_intents:
        blocked_by = declare_payload.get("blocked_by", [])
        if isinstance(blocked_by, list) and blocked_by:
            concurrent_intents = blocked_by
    return {
        "concurrent_intents": concurrent_intents or [],
        "workspace_relations": declare_payload.get("workspace_relations", []),
        "queued_context": declare_payload.get("queued_context", []),
        "total_agents": workspace.get("total_agents", 0),
        "stale_count": workspace.get("stale_count", 0),
    }


def _as_conflict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _require_non_empty_changed_evidence(paths: Sequence[str]) -> tuple[str, ...]:
    resolved = _helpers.coerce_repo_path_tuple(paths)
    if not resolved:
        raise MCPServiceContractError(workflow_msgs.FINISH_EVIDENCE_REQUIRED)
    return resolved


def _external_change_advisory(
    verify_status: str,
    external_paths: Sequence[str],
) -> tuple[str, dict[str, object] | None]:
    """Elevate a clean accepted verdict when external workspace dirt exists.

    ``external_paths`` are dirty paths outside the declared scope — advisory
    only, never blocking. Returns ``(effective_status, advisory_or_None)``: a
    plain ``accepted`` becomes ``accepted_with_external_changes`` and a compact
    advisory is produced; any other status is returned unchanged.
    """
    external = list(external_paths)
    if not external:
        return verify_status, None
    effective_status = verify_status
    if verify_status == PatchContractStatus.ACCEPTED.value:
        effective_status = PatchContractStatus.ACCEPTED_EXTERNAL.value
    advisory = {
        "count": len(external),
        "sample": external[:10],
        "truncated": len(external) > 10,
    }
    return effective_status, advisory


def _finish_summary(
    *,
    verify_status: str,
    intent_cleared: bool,
    check_payload: dict[str, object],
    verify_payload: dict[str, object],
    claims_payload: dict[str, object] | None,
    receipt_payload: dict[str, object] | None,
    receipt_error: str | None,
    workspace_hygiene_after: dict[str, object],
    review_text_present: bool,
    claims_text_present: bool,
) -> dict[str, object]:
    structural_delta = _helpers._as_mapping(verify_payload.get("structural_delta"))
    dirty_summary = _helpers._as_mapping(
        workspace_hygiene_after.get("workspace_dirty_summary")
    )
    return {
        "status": verify_status,
        "scope_status": str(check_payload.get("status", "")),
        "verification_profile": verify_payload.get("verification_profile"),
        "structural_verdict": structural_delta.get("verdict"),
        "health_delta": structural_delta.get("health_delta"),
        "regressions": len(_helpers._as_sequence(structural_delta.get("regressions"))),
        "worsened_symbols": len(_helpers._as_sequence(verify_payload.get("worsened"))),
        "claims": _finish_claim_status(
            claims_payload=claims_payload,
            claims_text_present=claims_text_present,
        ),
        "review_note_present": review_text_present,
        "receipt": _finish_receipt_status(
            receipt_payload=receipt_payload,
            receipt_error=receipt_error,
        ),
        "intent_cleared": intent_cleared,
        "workspace_dirty_paths": _helpers._as_int(
            dirty_summary.get("dirty_paths_count"),
            0,
        ),
        "workspace_hygiene_blocked": bool(workspace_hygiene_after.get("blocks_finish")),
    }


def _finish_claim_status(
    *,
    claims_payload: dict[str, object] | None,
    claims_text_present: bool,
) -> str:
    if not claims_text_present:
        return "skipped_no_claims_text"
    if claims_payload is None:
        return "skipped_not_recommended"
    return "valid" if claims_payload.get("valid") is True else "violated"


def _finish_receipt_status(
    *,
    receipt_payload: dict[str, object] | None,
    receipt_error: str | None,
) -> str:
    if receipt_error is not None:
        return "failed"
    if receipt_payload is None:
        return "skipped"
    return "created"


def _validated_dirty_scope_policy(value: str) -> str:
    from ._workspace_hygiene import VALID_DIRTY_SCOPE_POLICIES

    if value not in VALID_DIRTY_SCOPE_POLICIES:
        raise MCPServiceContractError(
            err_msgs.invalid_choice(
                "dirty_scope_policy",
                value,
                VALID_DIRTY_SCOPE_POLICIES,
            )
        )
    return value


def _start_edit_allowed(
    *,
    declare_status: str,
    concurrent_intents: list[dict[str, object]],
    on_conflict: str | None,
    hygiene: object,
    dirty_scope_policy: str,
) -> bool:
    from ._workspace_hygiene import WorkspaceHygieneResult, hygiene_blocks_start_edit

    if declare_status != IntentStatus.ACTIVE.value:
        return False
    if concurrent_intents and on_conflict != "queue":
        return False
    return not (
        isinstance(hygiene, WorkspaceHygieneResult)
        and hygiene_blocks_start_edit(
            hygiene,
            dirty_scope_policy=dirty_scope_policy,
        )
    )


def _start_workflow_status(
    *,
    declare_status: str,
    coordination_blocked: bool,
    hygiene: object,
    dirty_scope_policy: str,
) -> str:
    from ._workspace_hygiene import WorkspaceHygieneResult, hygiene_blocks_start_edit

    if declare_status == IntentStatus.QUEUED.value:
        return "queued"
    if coordination_blocked:
        return "blocked"
    if isinstance(hygiene, WorkspaceHygieneResult) and hygiene_blocks_start_edit(
        hygiene,
        dirty_scope_policy=dirty_scope_policy,
    ):
        return "blocked"
    return "active"


def _start_next_step(
    *,
    concurrent_intents: list[dict[str, object]],
    hygiene: object,
    dirty_scope_policy: str = "block",
) -> str:
    from ._workspace_hygiene import WorkspaceHygieneResult, hygiene_blocks_start_edit

    parts: list[str] = []
    if concurrent_intents:
        ownerships = {str(item.get("ownership", "")) for item in concurrent_intents}
        if "foreign_active" in ownerships:
            parts.append(workflow_msgs.START_FOREIGN_ACTIVE_OVERLAP)
        elif "foreign_stale" in ownerships:
            parts.append(workflow_msgs.START_FOREIGN_STALE_OVERLAP)
        else:
            parts.append(workflow_msgs.START_FOREIGN_ACTIVE_OVERLAP)
    if isinstance(hygiene, WorkspaceHygieneResult) and hygiene_blocks_start_edit(
        hygiene,
        dirty_scope_policy=dirty_scope_policy,
    ):
        if concurrent_intents:
            parts = [workflow_msgs.START_COMBINED_BLOCK]
        elif hygiene.foreign_dirty_overlaps:
            parts.append(workflow_msgs.START_FOREIGN_DIRTY_OVERLAP)
        elif dirty_scope_policy == "continue_own_wip":
            parts.append(workflow_msgs.START_CONTINUE_OWN_WIP)
        else:
            parts.append(workflow_msgs.START_DIRTY_SCOPE)
    return " ".join(parts)


_NOT_REACHED_VERIFY_PAYLOAD: Final[dict[str, object]] = {
    "status": "not_reached",
    "verification_profile": "unknown",
    "checks_not_applicable": [],
    "contract_violations": [],
}


def _pop_audit_sequence(payload: dict[str, object]) -> int | None:
    value = payload.pop("_audit_sequence", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _budget_summary(budget_payload: dict[str, object]) -> dict[str, object]:
    """Extract budget-relevant fields for the start response."""
    return {
        "strictness": budget_payload.get("strictness"),
        "budgets": budget_payload.get("budgets"),
        "current_state": budget_payload.get("current_state"),
        "headroom": budget_payload.get("headroom"),
        "gate_preview": budget_payload.get("gate_preview"),
        "message": budget_payload.get("message"),
    }


__all__ = ["_MCPSessionWorkflowMixin"]

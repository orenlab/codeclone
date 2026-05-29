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

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from . import _session_helpers as _helpers
from ._blast_radius import BlastRadiusResult
from ._intent import IntentRecord, IntentStatus
from ._patch_contract import PatchContractStatus
from ._session_claim_guard_mixin import _MCPSessionClaimGuardMixin
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunRecord,
    MCPServiceContractError,
)

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


class _MCPSessionWorkflowMixin(_MCPSessionClaimGuardMixin):
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
    ) -> dict[str, object]:
        validated_depth = _validated_blast_radius_depth(blast_radius_depth)
        root_path = _helpers._resolve_root(root)

        # 1. Workspace check
        workspace = self._list_workspace_intents(root=root)

        # 2. Root-aware run resolution (not _runs.get(None) — multi-repo safe)
        record = self._latest_run_for_root(root_path)
        if record is None:
            return {
                "status": "needs_analysis",
                "intent_id": None,
                "edit_allowed": False,
                "root": str(root_path),
                "message": (
                    "No analysis run available for this root. "
                    "Call analyze_repository first."
                ),
                "workspace": _workspace_summary(workspace),
            }

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
        status = str(declare_payload.get("status", ""))

        # Queued: no blast radius or budget
        if status == IntentStatus.QUEUED.value:
            return {
                "intent_id": intent_id,
                "status": "queued",
                "run_id": _helpers._short_run_id(record.run_id),
                "blocked_by": declare_payload.get("blocked_by", []),
                "queue_position": declare_payload.get("queue_position", 1),
                "before_run_pinned": declare_payload.get("before_run_pinned", False),
                "edit_allowed": False,
                "message": (
                    "Intent queued behind active workspace intent. "
                    "Do not edit until promoted."
                ),
            }

        # 4. Blast radius (full payload, not just declare's subset)
        with self._state_lock:
            active_intent = self._active_intents.get(intent_id)
        if active_intent is None:
            raise MCPServiceContractError(
                f"Intent {intent_id} not found after declare."
            )

        blast_result = self._blast_radius_result(
            record=record,
            files=active_intent.scope.allowed_paths,
            depth="direct",
            forbidden_patterns=active_intent.scope.forbidden,
        )
        blast_payload = blast_result.to_payload()

        # 5. Transitive summary (auto-escalated or explicit)
        transitive_summary = self._compute_transitive_summary(
            record=record,
            intent=active_intent,
            blast_result=blast_result,
            depth=validated_depth,
        )
        if transitive_summary is not None:
            blast_payload["transitive_summary"] = transitive_summary

        # 6. Budget
        budget_payload = self._patch_contract_budget(
            run_id=record.run_id,
            intent_id=intent_id,
            strictness=self._validated_strictness(strictness),
        )

        # 7. Compose response
        return {
            "intent_id": intent_id,
            "status": "active",
            "run_id": _helpers._short_run_id(record.run_id),
            "workspace": _workspace_summary(workspace),
            "blast_radius": blast_payload,
            "budget": _budget_summary(budget_payload),
            "scope": active_intent.scope.to_payload(),
            "edit_allowed": True,
            "message": self._start_message(blast_payload, budget_payload),
        }

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
        create_receipt: bool = True,
        auto_clear: bool = True,
        strictness: str = "ci",
    ) -> dict[str, object]:
        # 1. Resolve intent
        record, active_intent = self._resolve_intent(
            run_id=None,
            intent_id=intent_id,
        )

        # Queued intents cannot be verified
        if active_intent.status == IntentStatus.QUEUED:
            return {
                "intent_id": intent_id,
                "status": "unverified",
                "reason": "intent_not_active",
                "scope_check": None,
                "verification": None,
                "claims": None,
                "receipt": None,
                "intent_cleared": False,
                "user_action_required": False,
                "next_step": (
                    "Promote the queued intent before editing or verification."
                ),
                "message": ("Queued intent must be promoted before verification."),
            }

        # 2. Resolve changed files — exactly one source
        resolved_files = self._resolve_changed_files_once(
            root_path=record.root,
            changed_files=changed_files,
            diff_ref=diff_ref,
        )

        # 3. Check (writes IntentRecord.check_result — required for receipt)
        check_payload = self._check_change_intent(
            run_id=None,
            intent_id=intent_id,
            diff_ref=None,
            changed_files=resolved_files,
        )
        check_status = str(check_payload.get("status", ""))

        # Expired intent
        if check_status == IntentStatus.EXPIRED.value:
            return {
                "intent_id": intent_id,
                "status": "expired",
                "reason": "report_digest_mismatch",
                "scope_check": check_payload,
                "verification": None,
                "claims": None,
                "receipt": None,
                "intent_cleared": False,
                "user_action_required": False,
                "next_step": (
                    "Intent was declared against a different report. "
                    "Do not redeclare on the after-run — use the "
                    "original intent_id with the original before_run_id."
                ),
                "message": "Intent expired: report digest mismatch.",
            }

        # 4. Scope violation — early exit
        if check_status == IntentStatus.VIOLATED.value:
            return {
                "intent_id": intent_id,
                "status": "violated",
                "reason": "scope_violation",
                "scope_check": check_payload,
                "verification": None,
                "claims": None,
                "receipt": None,
                "intent_cleared": False,
                "user_action_required": True,
                "next_step": (
                    "Redeclare intent with expanded scope, or "
                    "remove the out-of-scope changes."
                ),
                "message": ("Patch touched files outside declared scope."),
            }

        # 5. Verify (before_run_id auto-resolves from intent)
        verify_payload = self._patch_contract_verify(
            before_run_id=None,
            after_run_id=after_run_id,
            intent_id=intent_id,
            strictness=self._validated_strictness(strictness),
            diff_ref=None,
            changed_files=resolved_files,
        )
        verify_status = str(verify_payload.get("status", ""))

        # 6. Non-accepted verification — return without receipt/clear
        if verify_status not in _ACCEPTED_STATUSES:
            verify_reason = str(verify_payload.get("reason", ""))
            return {
                "intent_id": intent_id,
                "status": verify_status,
                "reason": verify_reason,
                "scope_check": check_payload,
                "verification": verify_payload,
                "claims": None,
                "receipt": None,
                "intent_cleared": False,
                "user_action_required": verify_status
                == PatchContractStatus.VIOLATED.value,
                "next_step": verify_payload.get("next_step"),
                "message": str(verify_payload.get("message", "")),
            }

        # 7. Claim validation (conditional)
        claims_payload = self._conditional_claim_validation(
            record=record,
            verify_payload=verify_payload,
            review_text=review_text,
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

        # 10. Compose response
        result: dict[str, object] = {
            "intent_id": intent_id,
            "status": verify_status,
            "reason": verify_payload.get("reason"),
            "scope_check": check_payload,
            "verification": verify_payload,
            "claims": claims_payload,
            "receipt": receipt_payload,
            "intent_cleared": intent_cleared,
            "user_action_required": False,
            "message": self._finish_message(
                verify_status=verify_status,
                intent_cleared=intent_cleared,
                receipt_error=receipt_error,
            ),
        }
        if receipt_error is not None:
            result["receipt_error"] = receipt_error
        return result

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
            raise MCPServiceContractError(
                "finish_controlled_change requires exactly one of "
                "changed_files or diff_ref, not both."
            )
        if not has_files and not has_ref:
            raise MCPServiceContractError(
                "finish_controlled_change requires changed_files or diff_ref."
            )
        if has_ref:
            return self._git_diff_paths(root_path=root_path, git_diff_ref=str(diff_ref))
        assert changed_files is not None
        return self._normalize_changed_paths(root_path=root_path, paths=changed_files)

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
        review_text: str | None,
    ) -> dict[str, object] | None:
        """Run claim validation only when both conditions are met."""
        if not review_text:
            return None
        if not verify_payload.get("claim_validation_recommended"):
            return None
        return self.validate_review_claims(
            text=review_text,
            run_id=record.run_id,
        )

    @staticmethod
    def _start_message(
        blast_payload: dict[str, object],
        budget_payload: dict[str, object],
    ) -> str:
        parts: list[str] = ["Intent active."]
        radius_level = str(blast_payload.get("radius_level", "low"))
        if radius_level == "high":
            parts.append("Blast radius is high — review transitive summary.")
        gate = budget_payload.get("gate_preview")
        if isinstance(gate, dict) and gate.get("would_fail"):
            parts.append("Budget is already outside CI thresholds.")
        else:
            parts.append("Budget is within CI thresholds.")
        return " ".join(parts)

    @staticmethod
    def _finish_message(
        *,
        verify_status: str,
        intent_cleared: bool,
        receipt_error: str | None,
    ) -> str:
        if receipt_error is not None:
            return (
                "Change verified but receipt creation failed. "
                "Intent not cleared for retry."
            )
        if intent_cleared:
            return "Change verified and completed. Intent cleared."
        return f"Change verified (status: {verify_status}). Intent active."


def _validated_blast_radius_depth(value: str) -> str:
    if value not in VALID_BLAST_RADIUS_DEPTHS:
        expected = ", ".join(sorted(VALID_BLAST_RADIUS_DEPTHS))
        raise MCPServiceContractError(
            f"Invalid value for blast_radius_depth: {value!r}. "
            f"Expected one of: {expected}."
        )
    return value


def _workspace_summary(workspace: dict[str, object]) -> dict[str, object]:
    """Extract workspace summary for the start response."""
    return {
        "concurrent_intents": workspace.get("workspace_intents", []),
        "total_agents": workspace.get("total_agents", 0),
        "stale_count": workspace.get("stale_count", 0),
    }


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

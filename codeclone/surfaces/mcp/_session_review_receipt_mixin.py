# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from typing import cast

from ...audit import (
    EVENT_RECEIPT_CREATED,
)
from ...contracts import REPORT_SCHEMA_VERSION
from ...utils.coerce import as_int as _coerce_int
from . import _session_helpers as _helpers
from ._context_governance import (
    context_governance_digest,
)
from ._intent import IntentRecord
from ._review_receipt import (
    RECEIPT_VERSION,
    VALID_RECEIPT_FORMATS,
    derive_baseline_status,
    derive_claims_not_made,
    derive_human_decision_points,
    derive_patch_status,
    derive_verification_profile_section,
    receipt_verdict,
    render_receipt_markdown,
)
from ._session_finding_mixin import _MCPSessionFindingMixin, _StateLock
from ._session_intent_mixin import _MCPSessionIntentMixin
from ._session_patch_contract_mixin import _MCPSessionPatchContractMixin
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunRecord,
    MCPServiceContractError,
)
from ._session_state_mixin import _MCPSessionStateMixin


def _intent_session(
    session: _MCPSessionReviewReceiptMixin,
) -> _MCPSessionIntentMixin:
    return cast(_MCPSessionIntentMixin, session)


def _patch_session(
    session: _MCPSessionReviewReceiptMixin,
) -> _MCPSessionPatchContractMixin:
    return cast(_MCPSessionPatchContractMixin, session)


def _finding_session(
    session: _MCPSessionReviewReceiptMixin,
) -> _MCPSessionFindingMixin:
    return cast(_MCPSessionFindingMixin, session)


def _state_session(
    session: _MCPSessionReviewReceiptMixin,
) -> _MCPSessionStateMixin:
    return cast(_MCPSessionStateMixin, session)


class _MCPSessionReviewReceiptMixin:
    _runs: CodeCloneMCPRunStore
    _active_intents: dict[str, IntentRecord]
    _review_state: dict[str, OrderedDict[str, str | None]]
    _last_gate_results: dict[str, dict[str, object]]
    _state_lock: _StateLock

    def create_review_receipt(
        self,
        *,
        run_id: str | None = None,
        intent_id: str | None = None,
        format: str = "markdown",
        include_blast_radius: bool = True,
        include_patch_contract: bool = True,
        # Internal-only: the attested outcome of the finish that requested this
        # receipt (gh #57 family B).  The MCP tool wrapper does not expose it,
        # so standalone tool calls keep deriving the verdict from the contract.
        verification_accepted: bool | None = None,
    ) -> dict[str, object]:
        output_format = self._validated_receipt_format(format)
        # A known intent names the checkout this receipt attests; resolve the
        # run there. Content-addressed ids collide between same-commit
        # worktrees, and a finish-time receipt for a docs-only patch cites the
        # before-run id every sibling answers to.
        known_intent = _patch_session(self)._known_intent(intent_id)
        record = (
            self._runs.get_for_root(run_id, root=known_intent.root)
            if known_intent is not None
            else self._runs.resolve_any_root(run_id)
        )
        intent = self._receipt_intent(record=record, intent_id=intent_id)
        changed_paths = self._receipt_changed_paths(record=record, intent=intent)
        changed_findings = self._receipt_changed_findings(
            record=record,
            changed_paths=changed_paths,
        )
        verification_profile = derive_verification_profile_section(changed_paths)
        structural_delta = self._receipt_structural_delta(
            record,
            intent=intent,
            structural_checks_applicable=bool(
                verification_profile.get("structural_checks_applicable", True)
            ),
        )
        reviewed_evidence = self._reviewed_evidence(record)
        patch_contract = (
            self._receipt_patch_contract(
                record=record,
                intent=intent,
                structural_delta=structural_delta,
                changed_paths=changed_paths,
            )
            if include_patch_contract
            else None
        )
        human_decisions = derive_human_decision_points(
            changed_findings=changed_findings,
            intent_status=self._intent_status(intent),
        )
        patch_status = (
            str(patch_contract.get("status", "not_checked"))
            if patch_contract is not None
            else "not_checked"
        )
        receipt: dict[str, object] = {
            "receipt_version": RECEIPT_VERSION,
            "generated_at_utc": self._receipt_generated_at(record),
            "provenance": self._receipt_provenance(record),
            "verification_profile": verification_profile,
            "scope": self._receipt_scope(intent),
            "blast_radius": (
                self._receipt_blast_radius(intent) if include_blast_radius else None
            ),
            "reviewed_evidence": reviewed_evidence,
            "patch_contract": patch_contract,
            "structural_delta": structural_delta,
            "human_decision_points": human_decisions,
            "claims_not_made": derive_claims_not_made(record.report_document),
            "health": self._receipt_health(record),
            "verdict": receipt_verdict(
                reviewed_count=_coerce_int(reviewed_evidence.get("reviewed_count")),
                gate_relevant_count=_coerce_int(
                    reviewed_evidence.get("total_gate_relevant")
                ),
                patch_status=patch_status,
                human_decision_count=len(human_decisions),
                verification_accepted=verification_accepted,
            ),
        }
        if output_format == "json":
            _intent_session(self)._audit_emit(
                root=record.root,
                event_type=EVENT_RECEIPT_CREATED,
                severity="info",
                run_id=_helpers._short_run_id(record.run_id),
                intent_id=intent.intent_id if intent is not None else None,
                report_digest=self._receipt_digest(record),
                status=str(receipt.get("verdict", "")),
                payload={
                    "receipt": receipt,
                    "format": output_format,
                    # Persist the canonical digest so durable lookup by digest is
                    # uniform across markdown and json receipt events.
                    "receipt_digest": context_governance_digest("receipt_v1", receipt),
                },
            )
            return receipt
        digest = context_governance_digest("receipt_v1", receipt)
        short_run_id = _helpers._short_run_id(record.run_id)
        verdict = str(receipt.get("verdict", ""))
        content = render_receipt_markdown(receipt)
        # The audit event preserves the complete typed receipt (forensic-retention
        # policy) so it stays durably retrievable post-clear.
        audit_payload: dict[str, object] = {
            "run_id": short_run_id,
            "format": output_format,
            "receipt_version": RECEIPT_VERSION,
            "verdict": verdict,
            "receipt_digest": digest,
            "content": content,
            "receipt": receipt,
        }
        audit_sequence = _intent_session(self)._audit_emit(
            root=record.root,
            event_type=EVENT_RECEIPT_CREATED,
            severity="info",
            run_id=short_run_id,
            intent_id=intent.intent_id if intent is not None else None,
            report_digest=self._receipt_digest(record),
            status=verdict,
            payload=audit_payload,
        )
        # Default response dedup: keep the human-complete markdown receipt
        # content plus identity and omit the duplicate nested typed receipt.
        response: dict[str, object] = {
            "run_id": short_run_id,
            "format": output_format,
            "receipt_version": RECEIPT_VERSION,
            "verdict": verdict,
            "receipt_digest": digest,
            "content": content,
        }
        if audit_sequence is None:
            response["receipt_retrieval_unavailable"] = "audit_write_failed"
            return response
        response["receipt_retrieval"] = {
            "tool": "get_review_receipt",
            "run_id": short_run_id,
            "receipt_digest": digest["value"],
            "format": "structured",
        }
        return response

    def _validated_receipt_format(self, value: str) -> str:
        if value not in VALID_RECEIPT_FORMATS:
            expected = ", ".join(sorted(VALID_RECEIPT_FORMATS))
            raise MCPServiceContractError(
                f"Invalid value for format: {value!r}. Expected one of: {expected}."
            )
        return "json" if value == "json" else "markdown"

    def _receipt_intent(
        self,
        *,
        record: MCPRunRecord,
        intent_id: str | None,
    ) -> IntentRecord | None:
        intent_record: MCPRunRecord | None = None
        intent: IntentRecord | None
        if intent_id is not None:
            intent_record, intent = _intent_session(self)._resolve_intent(
                run_id=None,
                intent_id=intent_id,
            )
        else:
            intent = _patch_session(self)._optional_intent(
                record=record,
                intent_id=None,
            )
        if intent is not None and intent.run_id != record.run_id:
            intent_record = intent_record or self._runs.get_for_root(
                intent.run_id, root=intent.root
            )
            if intent_record.root != record.root:
                raise MCPServiceContractError(
                    "Receipt intent must belong to the selected run or the same root."
                )
        return intent

    def _receipt_changed_paths(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord | None,
    ) -> tuple[str, ...]:
        if intent is not None and intent.check_result is not None:
            return tuple(intent.check_result.actual_changed_files)
        return tuple(record.changed_paths)

    def _receipt_changed_findings(
        self,
        *,
        record: MCPRunRecord,
        changed_paths: tuple[str, ...],
    ) -> list[dict[str, object]]:
        if not changed_paths:
            return []
        finding_session = _finding_session(self)
        findings = finding_session._base_findings(record)
        return [
            finding
            for finding in findings
            if finding_session._finding_touches_paths(
                finding=finding,
                changed_paths=changed_paths,
            )
        ]

    def _receipt_provenance(self, record: MCPRunRecord) -> dict[str, object]:
        return {
            "report_digest": self._receipt_digest(record),
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "baseline_status": derive_baseline_status(record.report_document),
            "run_id": _helpers._short_run_id(record.run_id),
            "root": str(record.root),
        }

    def _receipt_digest(self, record: MCPRunRecord) -> str:
        integrity = _helpers._as_mapping(record.report_document.get("integrity"))
        digest = _helpers._as_mapping(integrity.get("digest"))
        algorithm = str(digest.get("algorithm", "sha256")).strip() or "sha256"
        return f"{algorithm}:{_helpers._report_digest(record.report_document)}"

    def _receipt_generated_at(self, record: MCPRunRecord) -> str:
        meta = _helpers._as_mapping(record.report_document.get("meta"))
        value = str(meta.get("report_generated_at_utc", "")).strip()
        if value:
            return value
        runtime = _helpers._as_mapping(meta.get("runtime"))
        value = str(runtime.get("report_generated_at_utc", "")).strip()
        if value:
            return value
        return str(record.summary.get("analysis_started_at_utc", "")).strip()

    def _receipt_scope(self, intent: IntentRecord | None) -> dict[str, object] | None:
        if intent is None:
            return None
        check = intent.check_result
        scope_payload: dict[str, object] = {
            "intent_id": intent.intent_id,
            "intent_status": self._intent_status(intent),
            "intent_description": intent.intent_description,
            "declared_files": list(intent.scope.allowed_files),
            "changed_files": list(check.actual_changed_files) if check else [],
            "unexpected_files": list(check.unexpected_files) if check else [],
            "forbidden_touched": list(check.forbidden_touched) if check else [],
            "untouched_files": list(check.untouched_in_declared) if check else [],
        }
        if check and intent.blast_radius_summary:
            summary = intent.blast_radius_summary
            changed = set(check.actual_changed_files)
            do_not_touch = _coerce_str_list(summary.get("do_not_touch_declared"))
            scope_payload["do_not_touch_held"] = [
                path for path in do_not_touch if path not in changed
            ]
        return scope_payload

    def _intent_status(self, intent: IntentRecord | None) -> str | None:
        if intent is None:
            return None
        if intent.check_result is not None:
            return intent.check_result.status.value
        return intent.status.value

    def _receipt_blast_radius(
        self,
        intent: IntentRecord | None,
    ) -> dict[str, object] | None:
        if intent is None or not intent.blast_radius_summary:
            return None
        summary = intent.blast_radius_summary
        return {
            "radius_level": summary.get("radius_level", "unknown"),
            "direct_dependents_count": _coerce_int(
                summary.get("direct_dependents_count")
            ),
            "clone_cohort_members_count": _coerce_int(
                summary.get("clone_cohort_members_count")
            ),
            "do_not_touch_count": _coerce_int(summary.get("do_not_touch_count")),
        }

    def _reviewed_evidence(self, record: MCPRunRecord) -> dict[str, object]:
        finding_session = _finding_session(self)
        findings = finding_session._base_findings(record)
        gate_relevant = [
            finding
            for finding in findings
            if str(finding.get("novelty", "")) == "new"
            or str(finding.get("severity", "")) in {"critical", "warning"}
        ]
        with self._state_lock:
            review_items = tuple(
                self._review_state.get(record.run_id, OrderedDict()).items()
            )
        items: list[dict[str, object]] = []
        for canonical_id, note in review_items:
            finding = self._finding_by_id(record=record, canonical_id=canonical_id)
            if finding is None:
                continue
            summary = finding_session._finding_summary_card(record, finding)
            items.append(
                {
                    "finding_id": finding_session._short_finding_id(
                        record,
                        canonical_id,
                    ),
                    "kind": str(summary.get("kind") or "finding"),
                    "severity": str(summary.get("severity") or "info"),
                    "note": note,
                }
            )
        return {
            "total_gate_relevant": len(gate_relevant),
            "reviewed_count": len(items),
            "items": items,
        }

    def _finding_by_id(
        self,
        *,
        record: MCPRunRecord,
        canonical_id: str,
    ) -> dict[str, object] | None:
        for finding in _finding_session(self)._base_findings(record):
            if isinstance(finding, dict) and str(finding.get("id", "")) == canonical_id:
                return finding
        return None

    def _attested_before_run(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord | None,
    ) -> MCPRunRecord | None:
        """Return the comparison base attested by the change intent, or ``None``.

        gh #57 family C: a receipt's structural delta may only ever describe the
        run pair the verification actually used — after = the receipt's own run,
        before = the intent's run.  An arbitrary same-root store neighbour
        (``_previous_run_for_root``) is not evidence about this patch: comparing
        against one fabricated ``structural_regressions`` violations in durable
        receipts for changes the controller had already accepted.
        """
        if intent is None or intent.run_id == record.run_id:
            return None
        return self._runs.get_for_root(intent.run_id, root=intent.root)

    def _receipt_structural_delta(
        self,
        record: MCPRunRecord,
        *,
        intent: IntentRecord | None,
        structural_checks_applicable: bool = True,
    ) -> dict[str, object]:
        if not structural_checks_applicable:
            return {
                "available": False,
                "regressions": 0,
                "improvements": 0,
                "health_delta": None,
                "verdict": "not_applicable",
            }
        previous = self._attested_before_run(record=record, intent=intent)
        if previous is None:
            # Same-id before/after is the analyzer-invariant case, not an
            # absent comparison — but only when the store shows this exact run
            # was recomputed after the intent went active. Additive verdict in
            # this section's existing non-numeric idiom (controller sanction
            # mem-d67159cc), so RECEIPT_VERSION stays "1".
            if intent is not None and _patch_session(self)._analyzer_invariance_proven(
                intent=intent,
                after=record,
                changed_files=self._receipt_changed_paths(
                    record=record,
                    intent=intent,
                ),
            ):
                from .messages import patch_contract as patch_msgs

                return {
                    "available": False,
                    "verdict": patch_msgs.ANALYZER_INVARIANT_REASON,
                    "reason": patch_msgs.ANALYZER_INVARIANT_EVIDENCE,
                }
            return {
                "available": False,
                "regressions": 0,
                "improvements": 0,
                "health_delta": None,
                "verdict": "not_available",
            }
        # Both records are already root-bound (the attested before-run at the
        # intent's own root); compare them directly instead of re-resolving
        # ids that same-commit sibling worktrees share.
        compare_payload = _state_session(self)._compare_run_records(
            before=previous,
            after=record,
            focus="all",
        )
        if not bool(compare_payload.get("comparable")):
            # Typed refusal rather than a numeric delta over a pair that cannot
            # be differenced.  Controller sanction mem-d67159cc: an additive
            # `not_comparable` verdict plus a stated reason inside this
            # section's existing non-numeric idiom (available:false /
            # not_applicable / not_available), so RECEIPT_VERSION stays "1".
            return {
                "available": False,
                "verdict": "not_comparable",
                "reason": str(compare_payload.get("reason", "")),
            }
        return {
            "available": bool(compare_payload.get("comparable")),
            "regressions": len(
                _helpers._as_sequence(compare_payload.get("regressions"))
            ),
            "improvements": len(
                _helpers._as_sequence(compare_payload.get("improvements"))
            ),
            "health_delta": compare_payload.get("health_delta"),
            "verdict": str(compare_payload.get("verdict", "stable")),
        }

    def _receipt_patch_contract(
        self,
        *,
        record: MCPRunRecord,
        intent: IntentRecord | None,
        structural_delta: Mapping[str, object],
        changed_paths: tuple[str, ...],
    ) -> dict[str, object]:
        with self._state_lock:
            gate_result = self._last_gate_results.get(record.run_id)
            gate_payload = dict(gate_result) if gate_result is not None else None
        regressions = _coerce_int(structural_delta.get("regressions"))
        intent_check_status = (
            intent.check_result.status.value
            if intent is not None and intent.check_result is not None
            else None
        )
        baseline_abuse = self._receipt_baseline_abuse_detected(
            record=record,
            regressions=regressions,
            changed_files=len(changed_paths),
        )
        contract_violations = self._receipt_contract_violations(
            gate_result=gate_payload,
            intent_check_status=intent_check_status,
            regressions=regressions,
            baseline_abuse=baseline_abuse,
        )
        return {
            "status": derive_patch_status(
                gate_result=gate_payload,
                intent_check_status=intent_check_status,
                regressions=regressions,
                has_structural_delta=bool(structural_delta.get("available")),
                patch_context_declared=intent is not None,
            ),
            "regressions": regressions,
            "improvements": _coerce_int(structural_delta.get("improvements")),
            "health_delta": structural_delta.get("health_delta"),
            "contract_violations": contract_violations,
            "baseline_abuse_detected": baseline_abuse,
        }

    def _receipt_baseline_abuse_detected(
        self,
        *,
        record: MCPRunRecord,
        regressions: int,
        changed_files: int,
    ) -> bool:
        meta = _helpers._as_mapping(record.report_document.get("meta"))
        baseline = _helpers._as_mapping(meta.get("baseline"))
        return str(baseline.get("status", "")).strip() == "updated" and (
            regressions > 0 or changed_files > 0
        )

    def _receipt_contract_violations(
        self,
        *,
        gate_result: Mapping[str, object] | None,
        intent_check_status: str | None,
        regressions: int,
        baseline_abuse: bool,
    ) -> list[str]:
        violations: list[str] = []
        if regressions > 0:
            violations.append("structural_regressions")
        if gate_result is not None and bool(gate_result.get("would_fail")):
            violations.append("gate_failures")
        if intent_check_status == "violated":
            violations.append("scope_violation")
        if baseline_abuse:
            violations.append("baseline_abuse")
        return violations

    def _receipt_health(self, record: MCPRunRecord) -> dict[str, object]:
        health = _helpers._summary_health_payload(record.summary)
        return {
            "score": health.get("score"),
            "grade": health.get("grade"),
            "delta": _helpers._summary_health_delta(record.summary),
        }


def _coerce_str_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if str(item).strip()]


__all__ = ["_MCPSessionReviewReceiptMixin"]

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fnmatch import fnmatchcase

from ...audit import (
    EVENT_BASELINE_ABUSE,
    EVENT_PATCH_BUDGET,
    EVENT_PATCH_EXPIRED,
    EVENT_PATCH_VERIFIED,
    EVENT_PATCH_VIOLATED,
)
from ...utils.coerce import as_int as _coerce_int
from . import _session_helpers as _helpers
from ._intent import IntentRecord, IntentScope, IntentStatus
from ._patch_contract import (
    VALID_PATCH_CONTRACT_MODES,
    VALID_STRICTNESS_PROFILES,
    PatchBudgets,
    PatchContractMode,
    PatchContractStatus,
    StrictnessProfile,
    baseline_status,
    budgets_for_strictness,
    detect_baseline_abuse,
)
from ._session_intent_mixin import _MCPSessionIntentMixin
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPGateRequest,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
)
from ._verification_profile import (
    ClassificationResult,
    VerificationProfile,
    classify_patch,
    profile_accepted_message,
    profile_limitations,
    profile_unverified_message,
)

MAX_WORSENED_ITEMS = 20


class _MCPSessionPatchContractMixin(_MCPSessionIntentMixin):
    _runs: CodeCloneMCPRunStore
    _active_intents: dict[str, IntentRecord]

    def check_patch_contract(
        self,
        *,
        mode: str,
        run_id: str | None = None,
        before_run_id: str | None = None,
        after_run_id: str | None = None,
        intent_id: str | None = None,
        strictness: str = "ci",
        diff_ref: str | None = None,
        changed_files: Sequence[str] | None = None,
    ) -> dict[str, object]:
        validated_mode = self._validated_patch_contract_mode(mode)
        validated_strictness = self._validated_strictness(strictness)
        if validated_mode == "budget":
            return self._patch_contract_budget(
                run_id=run_id,
                intent_id=intent_id,
                strictness=validated_strictness,
            )
        return self._patch_contract_verify(
            before_run_id=before_run_id,
            after_run_id=after_run_id,
            intent_id=intent_id,
            strictness=validated_strictness,
            diff_ref=diff_ref,
            changed_files=changed_files,
        )

    def _patch_contract_budget(
        self,
        *,
        run_id: str | None,
        intent_id: str | None,
        strictness: StrictnessProfile,
    ) -> dict[str, object]:
        record = self._runs.get(run_id)
        intent = self._optional_intent(record=record, intent_id=intent_id)
        if intent is not None:
            self._renew_lease_if_active(record=record, intent=intent)
        budgets = self._budgets_for_record(record=record, strictness=strictness)
        current_state = self._current_state(record)
        gate_preview = self._gate_preview(record=record, budgets=budgets)
        payload: dict[str, object] = {
            "mode": "budget",
            "run_id": _helpers._short_run_id(record.run_id),
            "strictness": strictness,
            "intent_id": intent.intent_id if intent is not None else None,
            "scope": "changed" if intent is not None else "full",
            "declared_scope": (
                intent.scope.to_payload() if intent is not None else None
            ),
            "blast_radius_summary": (
                intent.blast_radius_summary if intent is not None else None
            ),
            "budgets": budgets.to_payload(),
            "current_state": current_state,
            "headroom": self._headroom(budgets=budgets, current_state=current_state),
            "gate_preview": gate_preview,
            "message": self._budget_message(
                strictness=strictness,
                gate_preview=gate_preview,
            ),
        }
        self._audit_emit(
            root=record.root,
            event_type=EVENT_PATCH_BUDGET,
            severity="warn" if bool(gate_preview.get("would_fail")) else "info",
            run_id=_helpers._short_run_id(record.run_id),
            intent_id=intent.intent_id if intent is not None else None,
            report_digest=self._report_digest_value(record),
            status="budget",
            payload=payload,
        )
        return payload

    def _patch_contract_verify(
        self,
        *,
        before_run_id: str | None,
        after_run_id: str | None,
        intent_id: str | None,
        strictness: StrictnessProfile,
        diff_ref: str | None,
        changed_files: Sequence[str] | None,
    ) -> dict[str, object]:
        # ── 1. Resolve before-run (required for intent binding) ─────
        if before_run_id is None:
            return self._unverified_patch_contract(reason="no_before_run")
        try:
            before = self._runs.get(before_run_id)
        except MCPRunNotFoundError:
            return self._unverified_patch_contract(reason="no_before_run")

        # ── 2. Resolve intent ───────────────────────────────────────
        intent = self._optional_intent(record=before, intent_id=intent_id)
        if intent is not None:
            self._renew_lease_if_active(record=before, intent=intent)

        # ── 3. Compute actual changed files ─────────────────────────
        actual_changed_files = self._patch_changed_files_flexible(
            before=before,
            after_run_id=after_run_id,
            diff_ref=diff_ref,
            changed_files=changed_files,
        )

        # ── 4. Classify verification profile ────────────────────────
        classification = classify_patch(actual_changed_files)

        # ── 5. Scope/forbidden checks (always run) ──────────────────
        scope_check = (
            self._scope_check_payload(intent=intent, actual=actual_changed_files)
            if intent is not None
            else None
        )

        # ── 6. State artifact → violated early ──────────────────────
        if classification.profile == VerificationProfile.STATE_ARTIFACT_CHANGE:
            return self._state_artifact_violated(
                before=before,
                intent=intent,
                classification=classification,
                scope_check=scope_check,
            )

        # ── 7. Intent expiry check ──────────────────────────────────
        if intent is not None and self._is_intent_expired(record=before, intent=intent):
            after = self._optional_after_run(after_run_id)
            return self._expired_patch_contract(
                before=before,
                after=after or before,
                intent=intent,
            )

        # ── 8. Scope violation early exit ───────────────────────────
        scope_violated = (
            scope_check is not None
            and scope_check.get("status") == IntentStatus.VIOLATED.value
        )

        # ── 9. Profile-based fast path (no after_run needed) ────────
        #   Fast path requires explicit changed files evidence.  When
        #   neither changed_files nor diff_ref was provided, the caller
        #   has no diff evidence and must provide after_run_id.
        if after_run_id is None:
            has_diff_evidence = changed_files is not None or diff_ref is not None
            if not has_diff_evidence:
                return self._unverified_patch_contract(
                    reason="no_after_run",
                    before=before,
                )
            return self._profile_fast_path(
                before=before,
                intent=intent,
                strictness=strictness,
                classification=classification,
                scope_check=scope_check,
                scope_violated=scope_violated,
            )

        # ── 10. Full structural path (after_run available) ──────────
        try:
            after = self._runs.get(after_run_id)
        except MCPRunNotFoundError:
            return self._unverified_patch_contract(
                reason="no_after_run",
                before=before,
                classification=classification,
            )
        return self._full_structural_verify(
            before=before,
            after=after,
            intent=intent,
            strictness=strictness,
            classification=classification,
            scope_check=scope_check,
            actual_changed_files=actual_changed_files,
        )

    def _validated_patch_contract_mode(self, mode: str) -> PatchContractMode:
        if mode not in VALID_PATCH_CONTRACT_MODES:
            expected = ", ".join(sorted(VALID_PATCH_CONTRACT_MODES))
            raise MCPServiceContractError(
                f"Invalid value for mode: {mode!r}. Expected one of: {expected}."
            )
        return "verify" if mode == "verify" else "budget"

    def _validated_strictness(self, strictness: str) -> StrictnessProfile:
        if strictness not in VALID_STRICTNESS_PROFILES:
            expected = ", ".join(sorted(VALID_STRICTNESS_PROFILES))
            raise MCPServiceContractError(
                "Invalid value for strictness: "
                f"{strictness!r}. Expected one of: {expected}."
            )
        if strictness == "strict":
            return "strict"
        if strictness == "relaxed":
            return "relaxed"
        return "ci"

    def _optional_intent(
        self,
        *,
        record: MCPRunRecord,
        intent_id: str | None,
    ) -> IntentRecord | None:
        if intent_id is not None:
            _, intent = self._resolve_intent(run_id=None, intent_id=intent_id)
            return intent
        with self._state_lock:
            matching = [
                intent
                for intent in self._active_intents.values()
                if intent.run_id == record.run_id
            ]
        return matching[-1] if matching else None

    def _budgets_for_record(
        self,
        *,
        record: MCPRunRecord,
        strictness: StrictnessProfile,
    ) -> PatchBudgets:
        request = record.request
        return budgets_for_strictness(
            strictness=strictness,
            coverage_min=request.coverage_min,
            complexity_threshold=request.complexity_threshold,
            coupling_threshold=request.coupling_threshold,
            cohesion_threshold=request.cohesion_threshold,
        )

    def _gate_request(
        self, *, record: MCPRunRecord, budgets: PatchBudgets
    ) -> MCPGateRequest:
        clone_budget = budgets.clone_regression
        return MCPGateRequest(
            run_id=record.run_id,
            fail_on_new=clone_budget == 0,
            fail_threshold=-1,
            fail_complexity=budgets.complexity_delta,
            fail_coupling=budgets.coupling_delta,
            fail_cohesion=budgets.cohesion_delta,
            fail_cycles=budgets.dependency_cycle,
            fail_dead_code=budgets.dead_code_regression,
            fail_health=budgets.health_floor,
            fail_on_typing_regression=budgets.typing_regression,
            fail_on_docstring_regression=budgets.docstring_regression,
            fail_on_api_break=budgets.api_break,
            fail_on_untested_hotspots=budgets.coverage_hotspot,
            coverage_min=budgets.coverage_min,
        )

    def _gate_preview(
        self,
        *,
        record: MCPRunRecord,
        budgets: PatchBudgets,
    ) -> dict[str, object]:
        gate_result = self._evaluate_gate_snapshot(
            record=record,
            request=self._gate_request(record=record, budgets=budgets),
        )
        return {
            "would_fail": gate_result.exit_code != 0,
            "exit_code": gate_result.exit_code,
            "reasons": list(gate_result.reasons),
        }

    def _current_state(self, record: MCPRunRecord) -> dict[str, object]:
        report_document = record.report_document
        return {
            "health_score": _helpers._summary_health_score(record.summary),
            "complexity_max": self._family_max(
                report_document,
                family="complexity",
                keys=("cyclomatic_complexity", "complexity", "value"),
            ),
            "coupling_max": self._family_max(
                report_document,
                family="coupling",
                keys=("cbo", "coupling", "value"),
            ),
            "cohesion_max": self._family_max(
                report_document,
                family="cohesion",
                keys=("lcom4", "cohesion", "value"),
            ),
            "dependency_cycles": len(self._dependency_cycles(report_document)),
            "clone_groups": record.func_clones_count + record.block_clones_count,
            "dead_code_high_confidence": self._dead_code_high_confidence(
                report_document
            ),
        }

    def _headroom(
        self,
        *,
        budgets: PatchBudgets,
        current_state: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "complexity_headroom": self._threshold_headroom(
                budget=budgets.complexity_delta,
                current=_coerce_int(current_state.get("complexity_max")),
            ),
            "coupling_headroom": self._threshold_headroom(
                budget=budgets.coupling_delta,
                current=_coerce_int(current_state.get("coupling_max")),
            ),
            "cohesion_headroom": self._threshold_headroom(
                budget=budgets.cohesion_delta,
                current=_coerce_int(current_state.get("cohesion_max")),
            ),
            "health_headroom": (
                _coerce_int(current_state.get("health_score")) - budgets.health_floor
                if budgets.health_floor >= 0
                and current_state.get("health_score") is not None
                else None
            ),
        }

    def _patch_changed_files(
        self,
        *,
        after: MCPRunRecord,
        diff_ref: str | None,
        changed_files: Sequence[str] | None,
    ) -> tuple[str, ...]:
        if changed_files:
            return self._normalize_changed_paths(
                root_path=after.root, paths=changed_files
            )
        if diff_ref is not None:
            return self._git_diff_paths(root_path=after.root, git_diff_ref=diff_ref)
        return tuple(after.changed_paths)

    def _patch_changed_files_flexible(
        self,
        *,
        before: MCPRunRecord,
        after_run_id: str | None,
        diff_ref: str | None,
        changed_files: Sequence[str] | None,
    ) -> tuple[str, ...]:
        """Resolve changed files without requiring an after-run record.

        When *after_run_id* is available, delegates to
        ``_patch_changed_files``.  Otherwise falls back to explicit
        *changed_files* or *diff_ref* resolved against the before-run root.
        """
        if after_run_id is not None:
            try:
                after = self._runs.get(after_run_id)
                return self._patch_changed_files(
                    after=after,
                    diff_ref=diff_ref,
                    changed_files=changed_files,
                )
            except MCPRunNotFoundError:
                pass
        if changed_files:
            return self._normalize_changed_paths(
                root_path=before.root, paths=changed_files
            )
        if diff_ref is not None:
            return self._git_diff_paths(root_path=before.root, git_diff_ref=diff_ref)
        return ()

    def _optional_after_run(self, after_run_id: str | None) -> MCPRunRecord | None:
        if after_run_id is None:
            return None
        try:
            return self._runs.get(after_run_id)
        except MCPRunNotFoundError:
            return None

    # ── profile-aware verify paths ──────────────────────────────────

    def _state_artifact_violated(
        self,
        *,
        before: MCPRunRecord,
        intent: IntentRecord | None,
        classification: ClassificationResult,
        scope_check: dict[str, object] | None,
    ) -> dict[str, object]:
        """Return violated status for state artifact mutations."""
        profile_payload = classification.to_payload()
        violations = ["state_artifact_mutation"]
        if (
            scope_check is not None
            and scope_check.get("status") == IntentStatus.VIOLATED.value
        ):
            violations.append("scope_violation")
        payload: dict[str, object] = {
            "mode": "verify",
            "status": PatchContractStatus.VIOLATED.value,
            "reason": "state_artifact_mutation",
            "before": self._run_ref_payload(before),
            "after": None,
            "intent_id": intent.intent_id if intent is not None else None,
            "scope_check": scope_check,
            "contract_violations": violations,
            "blocking_violations": violations,
            **profile_payload,
            "message": (
                "Patch touched CodeClone generated state. "
                "This requires a separate explicit workflow."
            ),
        }
        self._audit_emit(
            root=before.root,
            event_type=EVENT_PATCH_VIOLATED,
            severity="warn",
            run_id=_helpers._short_run_id(before.run_id),
            intent_id=intent.intent_id if intent is not None else None,
            report_digest=self._report_digest_value(before),
            status=PatchContractStatus.VIOLATED.value,
            payload=payload,
        )
        return payload

    def _profile_fast_path(
        self,
        *,
        before: MCPRunRecord,
        intent: IntentRecord | None,
        strictness: StrictnessProfile,
        classification: ClassificationResult,
        scope_check: dict[str, object] | None,
        scope_violated: bool,
    ) -> dict[str, object]:
        """Handle verify when after_run_id is not provided.

        Returns accepted for documentation-only and non-python patches
        (with limitations), unverified for profiles that require an
        after-run.
        """
        profile = classification.profile
        profile_payload = classification.to_payload()

        # Scope violation is always blocking, regardless of profile.
        if scope_violated and strictness != "relaxed":
            violations = ["scope_violation"]
            payload: dict[str, object] = {
                "mode": "verify",
                "status": PatchContractStatus.VIOLATED.value,
                "reason": "scope_violation",
                "before": self._run_ref_payload(before),
                "after": None,
                "intent_id": (intent.intent_id if intent is not None else None),
                "scope_check": scope_check,
                "contract_violations": violations,
                "blocking_violations": violations,
                **profile_payload,
                "message": self._verify_message(
                    status=PatchContractStatus.VIOLATED.value,
                    violations=tuple(violations),
                ),
            }
            self._audit_emit(
                root=before.root,
                event_type=EVENT_PATCH_VIOLATED,
                severity="warn",
                run_id=_helpers._short_run_id(before.run_id),
                intent_id=(intent.intent_id if intent is not None else None),
                report_digest=self._report_digest_value(before),
                status=PatchContractStatus.VIOLATED.value,
                payload=payload,
            )
            return payload

        # Profiles that require after_run return unverified.
        matrix = classification.to_payload()
        if matrix["after_run_required"]:
            reason = (
                "after_run_required_for_governance"
                if profile == VerificationProfile.GOVERNANCE_CONFIG
                else "no_after_run"
            )
            return self._unverified_patch_contract(
                reason=reason,
                before=before,
                classification=classification,
                scope_check=scope_check,
            )

        # Documentation-only and non-python: accepted without after_run.
        limitations = list(profile_limitations(profile))
        status = PatchContractStatus.ACCEPTED.value
        payload = {
            "mode": "verify",
            "status": status,
            "reason": None,
            "before": self._run_ref_payload(before),
            "after": None,
            "intent_id": (intent.intent_id if intent is not None else None),
            "strictness": strictness,
            "scope_check": scope_check,
            "structural_delta": {
                "verdict": "not_applicable",
                "reason": "no_python_source_files_touched",
                "regressions": [],
                "improvements": [],
                "health_delta": None,
            },
            "contract_violations": [],
            "blocking_violations": [],
            **profile_payload,
            "limitations": limitations,
            "message": profile_accepted_message(profile),
        }
        self._audit_emit(
            root=before.root,
            event_type=EVENT_PATCH_VERIFIED,
            severity="info",
            run_id=_helpers._short_run_id(before.run_id),
            intent_id=(intent.intent_id if intent is not None else None),
            report_digest=self._report_digest_value(before),
            status=status,
            payload=payload,
        )
        return payload

    def _full_structural_verify(
        self,
        *,
        before: MCPRunRecord,
        after: MCPRunRecord,
        intent: IntentRecord | None,
        strictness: StrictnessProfile,
        classification: ClassificationResult,
        scope_check: dict[str, object] | None,
        actual_changed_files: tuple[str, ...],
    ) -> dict[str, object]:
        """Full structural verification path (before + after runs)."""
        compare_payload = self.compare_runs(
            run_id_before=before.run_id,
            run_id_after=after.run_id,
            focus="all",
        )
        if not bool(compare_payload.get("comparable")):
            return self._unverified_patch_contract(
                reason="incomparable_runs",
                before=before,
                after=after,
                structural_delta=self._structural_delta(compare_payload),
                classification=classification,
            )
        budgets = self._budgets_for_record(record=after, strictness=strictness)
        before_gate = self._gate_preview(record=before, budgets=budgets)
        after_gate = self._gate_preview(record=after, budgets=budgets)
        structural_delta = self._structural_delta(compare_payload)
        regressions = _as_sequence(structural_delta.get("regressions"))
        intent_regressions, external_regressions = self._partition_regressions(
            after=after,
            regressions=regressions,
            intent=intent,
        )
        worsened = self._worsened_symbols(before=before, after=after)
        intent_worsened, external_worsened = self._partition_worsened(
            worsened=worsened,
            intent=intent,
        )
        before_gate_fails = bool(before_gate["would_fail"])
        after_gate_fails = bool(after_gate["would_fail"])
        gate_worsened = not before_gate_fails and after_gate_fails
        intent_caused_gate_failure = (
            after_gate_fails
            if intent is None
            else bool(intent_regressions or intent_worsened)
        )
        gate_contract_failure = (
            after_gate_fails
            if intent is None
            else gate_worsened and intent_caused_gate_failure
        )
        external_gate_failure = (
            intent is not None and gate_worsened and not intent_caused_gate_failure
        )
        baseline_abuse = detect_baseline_abuse(
            before_gate_would_fail=before_gate_fails,
            after_gate_would_fail=after_gate_fails,
            after_baseline_status=baseline_status(after.report_document),
            regressions=len(regressions),
            changed_files=len(actual_changed_files),
            intent_available=intent is not None,
        )
        violations = self._contract_violations(
            intent_regressions=intent_regressions,
            gate_contract_failure=gate_contract_failure,
            scope_check=scope_check,
            baseline_abuse=baseline_abuse,
        )
        blocking_violations = () if strictness == "relaxed" else violations
        external_context = bool(external_regressions or external_gate_failure)
        if blocking_violations:
            status = PatchContractStatus.VIOLATED.value
        elif external_context:
            status = PatchContractStatus.ACCEPTED_EXTERNAL.value
        else:
            status = PatchContractStatus.ACCEPTED.value
        profile_payload = classification.to_payload()
        payload: dict[str, object] = {
            "mode": "verify",
            "status": status,
            "reason": None,
            "before": self._run_ref_payload(before),
            "after": self._run_ref_payload(after),
            "intent_id": (intent.intent_id if intent is not None else None),
            "strictness": strictness,
            "structural_delta": structural_delta,
            "intent_regressions": intent_regressions,
            "external_regressions": external_regressions,
            "worsened": worsened,
            "intent_worsened": intent_worsened,
            "external_worsened": external_worsened,
            "scope_check": scope_check,
            "before_gate": before_gate,
            "gate_preview": after_gate,
            "gate_worsened": gate_worsened,
            "intent_caused_gate_failure": intent_caused_gate_failure,
            "baseline_abuse": baseline_abuse,
            "contract_violations": list(violations),
            "blocking_violations": list(blocking_violations),
            **profile_payload,
            "message": self._verify_message(status=status, violations=violations),
        }
        event_type = (
            EVENT_PATCH_VIOLATED
            if status == PatchContractStatus.VIOLATED.value
            else EVENT_PATCH_VERIFIED
        )
        self._audit_emit(
            root=after.root,
            event_type=event_type,
            severity="warn" if blocking_violations else "info",
            run_id=_helpers._short_run_id(after.run_id),
            intent_id=(intent.intent_id if intent is not None else None),
            report_digest=self._report_digest_value(after),
            status=status,
            payload=payload,
        )
        if bool(baseline_abuse.get("detected")):
            self._audit_emit(
                root=after.root,
                event_type=EVENT_BASELINE_ABUSE,
                severity="error",
                run_id=_helpers._short_run_id(after.run_id),
                intent_id=(intent.intent_id if intent is not None else None),
                report_digest=self._report_digest_value(after),
                status="detected",
                payload=payload,
            )
        return payload

    def _scope_check_payload(
        self,
        *,
        intent: IntentRecord,
        actual: Sequence[str],
    ) -> dict[str, object]:
        check_result = self._intent_check_result(intent=intent, actual=actual)
        return check_result.to_payload()

    def _partition_regressions(
        self,
        *,
        after: MCPRunRecord,
        regressions: Sequence[object],
        intent: IntentRecord | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        if intent is None:
            return (
                [
                    self._regression_card_with_paths(regression, paths=frozenset())
                    for regression in regressions
                ],
                [],
            )
        path_index = self._finding_path_index(after)
        intent_regressions: list[dict[str, object]] = []
        external_regressions: list[dict[str, object]] = []
        for regression in regressions:
            regression_map = _as_mapping(regression)
            regression_id = str(regression_map.get("id", "")).strip()
            paths = path_index.get(regression_id, frozenset())
            card = self._regression_card_with_paths(regression_map, paths=paths)
            if self._paths_in_intent_scope(paths=paths, scope=intent.scope):
                intent_regressions.append(card)
            else:
                external_regressions.append(card)
        return intent_regressions, external_regressions

    def _finding_path_index(
        self,
        record: MCPRunRecord,
    ) -> dict[str, frozenset[str]]:
        index: dict[str, frozenset[str]] = {}
        for finding in self._base_findings(record):
            finding_id = str(finding.get("id", "")).strip()
            if not finding_id:
                continue
            paths = self._finding_paths(finding)
            index[finding_id] = paths
            index[self._short_finding_id(record, finding_id)] = paths
        return index

    def _finding_paths(self, finding: Mapping[str, object]) -> frozenset[str]:
        paths: set[str] = set()
        for key in ("locations", "items"):
            for item in _as_sequence(finding.get(key)):
                item_map = _as_mapping(item)
                for path_key in ("file", "relative_path", "path", "filepath"):
                    path = self._normalized_report_path(item_map.get(path_key))
                    if path:
                        paths.add(path)
        for path_key in ("file", "relative_path", "path", "filepath"):
            path = self._normalized_report_path(finding.get(path_key))
            if path:
                paths.add(path)
        return frozenset(sorted(paths))

    def _regression_card_with_paths(
        self,
        regression: object,
        *,
        paths: frozenset[str],
    ) -> dict[str, object]:
        card = dict(_as_mapping(regression))
        card["paths"] = sorted(paths)
        return card

    def _partition_worsened(
        self,
        *,
        worsened: Sequence[Mapping[str, object]],
        intent: IntentRecord | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        if intent is None:
            return ([dict(item) for item in worsened], [])
        intent_worsened: list[dict[str, object]] = []
        external_worsened: list[dict[str, object]] = []
        for item in worsened:
            item_copy = dict(item)
            path = self._normalized_report_path(item.get("path"))
            if not path or self._path_in_scope(path=path, scope=intent.scope):
                intent_worsened.append(item_copy)
            else:
                external_worsened.append(item_copy)
        return intent_worsened, external_worsened

    def _paths_in_intent_scope(
        self,
        *,
        paths: frozenset[str],
        scope: IntentScope,
    ) -> bool:
        if not paths:
            return True
        return any(self._path_in_scope(path=path, scope=scope) for path in paths)

    def _path_in_scope(self, *, path: str, scope: IntentScope) -> bool:
        patterns = (*scope.allowed_files, *scope.allowed_related)
        return any(
            path == pattern or fnmatchcase(path, pattern) for pattern in patterns
        )

    def _normalized_report_path(self, value: object) -> str:
        path = str(value or "").replace("\\", "/").strip()
        if path == ".":
            return ""
        if path.startswith("./"):
            path = path[2:]
        return path.rstrip("/")

    def _contract_violations(
        self,
        *,
        intent_regressions: Sequence[object],
        gate_contract_failure: bool,
        scope_check: Mapping[str, object] | None,
        baseline_abuse: Mapping[str, object],
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if intent_regressions:
            violations.append("structural_regressions")
        if gate_contract_failure:
            violations.append("gate_failures")
        if (
            scope_check is not None
            and scope_check.get("status") == IntentStatus.VIOLATED.value
        ):
            violations.append("scope_violation")
        violations.extend(
            f"baseline_abuse:{trigger}"
            for trigger in _as_sequence(baseline_abuse.get("triggers"))
        )
        return tuple(violations)

    def _structural_delta(
        self, compare_payload: Mapping[str, object]
    ) -> dict[str, object]:
        return {
            "regressions": list(_as_sequence(compare_payload.get("regressions"))),
            "improvements": list(_as_sequence(compare_payload.get("improvements"))),
            "health_delta": compare_payload.get("health_delta"),
            "verdict": str(compare_payload.get("verdict", "")),
        }

    def _worsened_symbols(
        self,
        *,
        before: MCPRunRecord,
        after: MCPRunRecord,
    ) -> list[dict[str, object]]:
        worsened: list[dict[str, object]] = []
        for family, value_keys in (
            ("complexity", ("cyclomatic_complexity", "complexity", "value")),
            ("coupling", ("cbo", "coupling", "value")),
            ("cohesion", ("lcom4", "cohesion", "value")),
        ):
            before_items = self._metric_item_index(
                before.report_document,
                family=family,
                value_keys=value_keys,
            )
            after_items = self._metric_item_index(
                after.report_document,
                family=family,
                value_keys=value_keys,
            )
            for key, after_value in after_items.items():
                before_value = before_items.get(key)
                if before_value is not None and after_value > before_value:
                    path, symbol = key
                    worsened.append(
                        {
                            "family": family,
                            "path": path,
                            "symbol": symbol,
                            "before": before_value,
                            "after": after_value,
                            "delta": after_value - before_value,
                        }
                    )
        return sorted(
            worsened,
            key=lambda item: (
                -_coerce_int(item.get("delta")),
                str(item.get("family", "")),
                str(item.get("path", "")),
                str(item.get("symbol", "")),
            ),
        )[:MAX_WORSENED_ITEMS]

    def _metric_item_index(
        self,
        report_document: Mapping[str, object],
        *,
        family: str,
        value_keys: Sequence[str],
    ) -> dict[tuple[str, str], int]:
        result: dict[tuple[str, str], int] = {}
        for item in self._metric_family_items(report_document, family=family):
            path = self._item_path(item)
            symbol = self._item_symbol(item)
            value = self._first_int(item, keys=value_keys)
            if path or symbol:
                result[(path, symbol)] = value
        return result

    def _metric_family_items(
        self,
        report_document: Mapping[str, object],
        *,
        family: str,
    ) -> tuple[Mapping[str, object], ...]:
        metrics = _as_mapping(report_document.get("metrics"))
        families = _as_mapping(metrics.get("families"))
        family_payload = _as_mapping(families.get(family))
        return tuple(
            _as_mapping(item) for item in _as_sequence(family_payload.get("items"))
        )

    def _family_max(
        self,
        report_document: Mapping[str, object],
        *,
        family: str,
        keys: Sequence[str],
    ) -> int:
        values = [
            self._first_int(item, keys=keys)
            for item in self._metric_family_items(report_document, family=family)
        ]
        return max(values, default=0)

    def _dead_code_high_confidence(self, report_document: Mapping[str, object]) -> int:
        return sum(
            1
            for item in self._metric_family_items(report_document, family="dead_code")
            if str(item.get("confidence", "")).strip().lower() == "high"
        )

    def _dependency_cycles(
        self,
        report_document: Mapping[str, object],
    ) -> tuple[object, ...]:
        metrics = _as_mapping(report_document.get("metrics"))
        families = _as_mapping(metrics.get("families"))
        dependencies = _as_mapping(families.get("dependencies"))
        return tuple(_as_sequence(dependencies.get("cycles")))

    def _first_int(self, item: Mapping[str, object], *, keys: Sequence[str]) -> int:
        for key in keys:
            if key in item:
                return _coerce_int(item.get(key))
        return 0

    def _item_path(self, item: Mapping[str, object]) -> str:
        for key in ("relative_path", "path", "filepath", "file"):
            value = str(item.get(key, "")).strip()
            if value:
                return value.replace("\\", "/")
        return ""

    def _item_symbol(self, item: Mapping[str, object]) -> str:
        for key in ("qualname", "symbol", "name", "class_name", "function"):
            value = str(item.get(key, "")).strip()
            if value:
                return value
        return ""

    def _threshold_headroom(self, *, budget: int, current: int) -> int | None:
        return budget - current if budget >= 0 else None

    def _run_ref_payload(self, record: MCPRunRecord) -> dict[str, object]:
        return {
            "run_id": _helpers._short_run_id(record.run_id),
            "health": _helpers._summary_health_score(record.summary),
        }

    def _unverified_patch_contract(
        self,
        *,
        reason: str,
        before: MCPRunRecord | None = None,
        after: MCPRunRecord | None = None,
        structural_delta: Mapping[str, object] | None = None,
        classification: ClassificationResult | None = None,
        scope_check: dict[str, object] | None = None,
    ) -> dict[str, object]:
        profile_fields: dict[str, object] = (
            classification.to_payload() if classification is not None else {}
        )
        message = (
            profile_unverified_message(classification.profile)
            if classification is not None
            else f"Patch contract unverified: {reason}."
        )
        return {
            "mode": "verify",
            "status": PatchContractStatus.UNVERIFIED.value,
            "reason": reason,
            "before": (self._run_ref_payload(before) if before is not None else None),
            "after": (self._run_ref_payload(after) if after is not None else None),
            "structural_delta": dict(structural_delta or {}),
            "scope_check": scope_check,
            "contract_violations": [],
            **profile_fields,
            "message": message,
        }

    def _expired_patch_contract(
        self,
        *,
        before: MCPRunRecord,
        after: MCPRunRecord,
        intent: IntentRecord,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": "verify",
            "status": PatchContractStatus.EXPIRED.value,
            "reason": "report_digest_mismatch",
            "before": self._run_ref_payload(before),
            "after": self._run_ref_payload(after),
            "intent_id": intent.intent_id,
            "contract_violations": ["intent_expired"],
            "message": (
                "Patch contract expired: intent was declared for another report digest."
            ),
        }
        self._audit_emit(
            root=after.root,
            event_type=EVENT_PATCH_EXPIRED,
            severity="warn",
            run_id=_helpers._short_run_id(after.run_id),
            intent_id=intent.intent_id,
            report_digest=self._report_digest_value(after),
            status=PatchContractStatus.EXPIRED.value,
            payload=payload,
        )
        return payload

    def _budget_message(
        self,
        *,
        strictness: StrictnessProfile,
        gate_preview: Mapping[str, object],
    ) -> str:
        if strictness == "relaxed":
            return "Relaxed patch budget is advisory; gate failures are not blocking."
        if gate_preview.get("would_fail"):
            return "Current run is already outside the selected patch budget."
        return "Current run is inside the selected patch budget."

    def _verify_message(self, *, status: str, violations: Sequence[str]) -> str:
        if status == PatchContractStatus.ACCEPTED.value:
            return "Patch contract accepted."
        if status == PatchContractStatus.ACCEPTED_EXTERNAL.value:
            return "Patch contract accepted; external workspace changes detected."
        return "Patch contract violated: " + ", ".join(violations)


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


__all__ = ["_MCPSessionPatchContractMixin"]

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ...utils.coerce import as_int as _coerce_int
from . import _session_helpers as _helpers
from ._intent import IntentRecord, IntentStatus
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
        budgets = self._budgets_for_record(record=record, strictness=strictness)
        current_state = self._current_state(record)
        gate_preview = self._gate_preview(record=record, budgets=budgets)
        return {
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
        if before_run_id is None:
            return self._unverified_patch_contract(reason="no_before_run")
        try:
            before = self._runs.get(before_run_id)
        except MCPRunNotFoundError:
            return self._unverified_patch_contract(reason="no_before_run")
        if after_run_id is None:
            return self._unverified_patch_contract(reason="no_after_run")
        try:
            after = self._runs.get(after_run_id)
        except MCPRunNotFoundError:
            return self._unverified_patch_contract(
                reason="no_after_run",
                before=before,
            )
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
            )
        intent = self._optional_intent(record=before, intent_id=intent_id)
        if intent is not None and self._is_intent_expired(record=before, intent=intent):
            return self._expired_patch_contract(
                before=before, after=after, intent=intent
            )
        actual_changed_files = self._patch_changed_files(
            after=after,
            diff_ref=diff_ref,
            changed_files=changed_files,
        )
        scope_check = (
            self._scope_check_payload(intent=intent, actual=actual_changed_files)
            if intent is not None
            else None
        )
        budgets = self._budgets_for_record(record=after, strictness=strictness)
        before_gate = self._gate_preview(record=before, budgets=budgets)
        after_gate = self._gate_preview(record=after, budgets=budgets)
        structural_delta = self._structural_delta(compare_payload)
        regressions = _as_sequence(structural_delta.get("regressions"))
        baseline_abuse = detect_baseline_abuse(
            before_gate_would_fail=bool(before_gate["would_fail"]),
            after_gate_would_fail=bool(after_gate["would_fail"]),
            after_baseline_status=baseline_status(after.report_document),
            regressions=len(regressions),
            changed_files=len(actual_changed_files),
            intent_available=intent is not None,
        )
        violations = self._contract_violations(
            structural_delta=structural_delta,
            gate_preview=after_gate,
            scope_check=scope_check,
            baseline_abuse=baseline_abuse,
        )
        blocking_violations = () if strictness == "relaxed" else violations
        status = (
            PatchContractStatus.VIOLATED.value
            if blocking_violations
            else PatchContractStatus.ACCEPTED.value
        )
        return {
            "mode": "verify",
            "status": status,
            "reason": None,
            "before": self._run_ref_payload(before),
            "after": self._run_ref_payload(after),
            "intent_id": intent.intent_id if intent is not None else None,
            "strictness": strictness,
            "structural_delta": structural_delta,
            "worsened": self._worsened_symbols(before=before, after=after),
            "scope_check": scope_check,
            "gate_preview": after_gate,
            "baseline_abuse": baseline_abuse,
            "contract_violations": list(violations),
            "blocking_violations": list(blocking_violations),
            "message": self._verify_message(status=status, violations=violations),
        }

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

    def _scope_check_payload(
        self,
        *,
        intent: IntentRecord,
        actual: Sequence[str],
    ) -> dict[str, object]:
        check_result = self._intent_check_result(intent=intent, actual=actual)
        return check_result.to_payload()

    def _contract_violations(
        self,
        *,
        structural_delta: Mapping[str, object],
        gate_preview: Mapping[str, object],
        scope_check: Mapping[str, object] | None,
        baseline_abuse: Mapping[str, object],
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _as_sequence(structural_delta.get("regressions")):
            violations.append("structural_regressions")
        if bool(gate_preview.get("would_fail")):
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
    ) -> dict[str, object]:
        return {
            "mode": "verify",
            "status": PatchContractStatus.UNVERIFIED.value,
            "reason": reason,
            "before": self._run_ref_payload(before) if before is not None else None,
            "after": self._run_ref_payload(after) if after is not None else None,
            "structural_delta": dict(structural_delta or {}),
            "contract_violations": [],
            "message": f"Patch contract unverified: {reason}.",
        }

    def _expired_patch_contract(
        self,
        *,
        before: MCPRunRecord,
        after: MCPRunRecord,
        intent: IntentRecord,
    ) -> dict[str, object]:
        return {
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
        return "Patch contract violated: " + ", ".join(violations)


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


__all__ = ["_MCPSessionPatchContractMixin"]

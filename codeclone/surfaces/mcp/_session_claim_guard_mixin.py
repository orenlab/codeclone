# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ...audit import EVENT_CLAIM_COMPLETED, EVENT_CLAIM_VIOLATED
from ...metrics.registry import METRIC_FAMILIES
from . import _session_helpers as _helpers
from ._claim_guard import (
    ReportContext,
    validate_claims,
    validate_text_input,
)
from ._session_review_receipt_mixin import _MCPSessionReviewReceiptMixin
from ._session_shared import MCPRunRecord, MCPServiceContractError
from ._verification_profile import classify_patch


class _MCPSessionClaimGuardMixin(_MCPSessionReviewReceiptMixin):
    def validate_review_claims(
        self,
        *,
        text: str,
        run_id: str | None = None,
        require_citations: bool = True,
        patch_health_delta: int | None = None,
    ) -> dict[str, object]:
        try:
            validated_text = validate_text_input(text)
        except ValueError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        record = self._runs.get(run_id)
        context = self._claim_guard_context(
            record,
            patch_health_delta=patch_health_delta,
        )
        payload = validate_claims(
            text=validated_text,
            report_context=context,
            require_citations=bool(require_citations),
        )
        result = {"run_id": _helpers._short_run_id(record.run_id), **payload}
        valid = bool(result.get("valid"))
        self._audit_emit(
            root=record.root,
            event_type=EVENT_CLAIM_COMPLETED if valid else EVENT_CLAIM_VIOLATED,
            severity="info" if valid else "warn",
            run_id=_helpers._short_run_id(record.run_id),
            report_digest=self._report_digest_value(record),
            status="valid" if valid else "violated",
            payload=result,
        )
        return result

    def _claim_guard_context(
        self,
        record: MCPRunRecord,
        *,
        patch_health_delta: int | None = None,
    ) -> ReportContext:
        _canonical_to_short, short_to_canonical = self._finding_id_maps(record)
        findings = {
            canonical_id: dict(finding)
            for finding in self._base_findings(record)
            if (canonical_id := str(finding.get("id", "")).strip())
        }
        changed_paths = list(record.changed_paths)
        profile_value = (
            classify_patch(changed_paths).profile.value if changed_paths else None
        )
        return ReportContext(
            findings=findings,
            short_to_canonical=short_to_canonical,
            reachable_qualnames=self._reachable_qualnames(record),
            report_only_families=frozenset(
                sorted(
                    family.name
                    for family in METRIC_FAMILIES.values()
                    if not family.gate_keys
                )
            ),
            has_comparison_run=self._previous_run_for_root(record) is not None,
            metric_families=frozenset(sorted(METRIC_FAMILIES)),
            verification_profile=profile_value,
            patch_health_delta=patch_health_delta,
        )

    def _reachable_qualnames(self, record: MCPRunRecord) -> frozenset[str]:
        project_metrics = record.project_metrics
        if project_metrics is None:
            return frozenset()
        return frozenset(
            sorted(
                str(getattr(fact, "target_qualname", "")).strip()
                for fact in getattr(project_metrics, "runtime_reachability", ())
                if str(getattr(fact, "target_qualname", "")).strip()
            )
        )

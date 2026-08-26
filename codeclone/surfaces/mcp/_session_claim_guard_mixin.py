# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import cast

from ...audit import EVENT_CLAIM_COMPLETED, EVENT_CLAIM_VIOLATED
from ...metrics.registry import METRIC_FAMILIES
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.payload_narrow import is_record_mapping
from . import _session_helpers as _helpers
from ._claim_guard import (
    ReportContext,
    validate_claims,
    validate_text_input,
)
from ._session_finding_mixin import _MCPSessionFindingMixin
from ._session_intent_mixin import _MCPSessionIntentMixin
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPRunRecord,
    MCPServiceContractError,
)
from ._verification_profile import classify_patch


def _intent_session(
    session: _MCPSessionClaimGuardMixin,
) -> _MCPSessionIntentMixin:
    return cast(_MCPSessionIntentMixin, session)


def _finding_session(
    session: _MCPSessionClaimGuardMixin,
) -> _MCPSessionFindingMixin:
    return cast(_MCPSessionFindingMixin, session)


def _tier_states_from_report_document(
    report_document: Mapping[str, object],
) -> Mapping[str, str]:
    """Read the advisory clone tiers and their execution states off the run.

    The tier vocabulary is derived here, never restated: every tier container
    declares its own ``tier`` name and its ``state`` witness (T1,
    2026-08-24), so a third tier that stamps the same two fields is covered
    the day it lands. A hardcoded second list would be a copy that rots
    against the producers while the guard kept validating claims about a
    vocabulary the report no longer uses.

    A document with no tier container yields an empty mapping: the guard then
    knows of no tier and checks no tier claim, which is the honest answer
    rather than rejecting a claim on evidence it does not hold.
    """

    groups = _as_mapping(_as_mapping(report_document.get("findings")).get("groups"))
    states: dict[str, str] = {}
    for container in groups.values():
        if not is_record_mapping(container):
            continue
        tier = str(container.get("tier", "")).strip()
        if tier:
            states[tier] = str(container.get("state", "")).strip()
    return MappingProxyType(dict(sorted(states.items())))


class _MCPSessionClaimGuardMixin:
    _runs: CodeCloneMCPRunStore

    def validate_review_claims(
        self,
        *,
        text: str,
        run_id: str | None = None,
        require_citations: bool = True,
        patch_health_delta: int | None = None,
    ) -> dict[str, object]:
        try:
            validate_text_input(text)
        except ValueError as exc:
            raise MCPServiceContractError(str(exc)) from exc
        record = self._runs.resolve_any_root(run_id)
        return self._validate_review_claims_for_record(
            record=record,
            text=text,
            require_citations=require_citations,
            patch_health_delta=patch_health_delta,
        )

    def _validate_review_claims_for_record(
        self,
        *,
        record: MCPRunRecord,
        text: str,
        require_citations: bool = True,
        patch_health_delta: int | None = None,
    ) -> dict[str, object]:
        """Validate claims against an already-resolved run record.

        Root-bound callers (the finish claims lane) pass the intent's own
        record; re-resolving its id would fall back to global resolution and
        fail on content-addressed ids shared by same-commit worktrees.
        """

        try:
            validated_text = validate_text_input(text)
        except ValueError as exc:
            raise MCPServiceContractError(str(exc)) from exc
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
        intent_session = _intent_session(self)
        intent_session._audit_emit(
            root=record.root,
            event_type=EVENT_CLAIM_COMPLETED if valid else EVENT_CLAIM_VIOLATED,
            severity="info" if valid else "warn",
            run_id=_helpers._short_run_id(record.run_id),
            report_digest=intent_session._report_digest_value(record),
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
        finding_session = _finding_session(self)
        _canonical_to_short, short_to_canonical = finding_session._finding_id_maps(
            record
        )
        findings = {
            canonical_id: dict(finding)
            for finding in finding_session._base_findings(record)
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
            has_comparison_run=finding_session._previous_run_for_root(record)
            is not None,
            metric_families=frozenset(sorted(METRIC_FAMILIES)),
            verification_profile=profile_value,
            patch_health_delta=patch_health_delta,
            tier_states=_tier_states_from_report_document(record.report_document),
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

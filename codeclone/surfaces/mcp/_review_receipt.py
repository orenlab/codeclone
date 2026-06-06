# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Final, Literal

from ...contracts import REPORT_SCHEMA_VERSION
from ._verification_profile import (
    check_matrix,
    classify_patch,
    profile_limitations,
)
from .messages import receipt as receipt_msgs

RECEIPT_VERSION: Final = "1"
ReceiptFormat = Literal["json", "markdown"]
VALID_RECEIPT_FORMATS: Final[frozenset[str]] = frozenset({"json", "markdown"})
MAX_HUMAN_DECISION_POINTS: Final = 10


class ReceiptVerdict(str, Enum):
    CLEAN = "clean"
    INCOMPLETE = "incomplete"
    NEEDS_ATTENTION = "needs_attention"


class ReceiptPatchStatus(str, Enum):
    ACCEPTED = "accepted"
    VIOLATED = "violated"
    NOT_CHECKED = "not_checked"


CLAIMS_NOT_MADE: Final[tuple[dict[str, str], ...]] = (
    {
        "claim_type": "security_vulnerability",
        "reason": receipt_msgs.CLAIM_REASON_SECURITY_NOT_VULNERABILITY,
    },
    {
        "claim_type": "baseline_regression",
        "reason": receipt_msgs.CLAIM_REASON_BASELINE_DEBT_NOT_REGRESSION,
    },
    {
        "claim_type": "report_only_ci_failure",
        "reason": receipt_msgs.CLAIM_REASON_REPORT_ONLY_NOT_CI_FAILURE,
    },
)


def derive_baseline_status(report_document: Mapping[str, object]) -> str:
    meta = _as_mapping(report_document.get("meta"))
    baseline = _as_mapping(meta.get("baseline"))
    if not bool(baseline.get("loaded", False)):
        return "not_loaded"
    status = str(baseline.get("status", "")).strip().lower()
    if bool(baseline.get("trusted_for_diff", False)) or status == "ok":
        return "trusted"
    return "untrusted"


def derive_patch_status(
    *,
    gate_result: Mapping[str, object] | None,
    intent_check_status: str | None,
    regressions: int,
    has_structural_delta: bool,
) -> str:
    if intent_check_status == "violated":
        return ReceiptPatchStatus.VIOLATED.value
    if gate_result is not None and bool(gate_result.get("would_fail")):
        return ReceiptPatchStatus.VIOLATED.value
    if regressions > 0:
        return ReceiptPatchStatus.VIOLATED.value
    if gate_result is None and intent_check_status is None and not has_structural_delta:
        return ReceiptPatchStatus.NOT_CHECKED.value
    return ReceiptPatchStatus.ACCEPTED.value


def derive_human_decision_points(
    *,
    changed_findings: Sequence[Mapping[str, object]],
    intent_status: str | None,
) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for finding in changed_findings:
        if str(finding.get("family", "")).strip() == "clone":
            points.append(
                _decision_point(
                    category="clone_divergence",
                    finding_id=str(finding.get("id", "")),
                    reason=receipt_msgs.DECISION_REASON_CLONE_DIVERGENCE,
                )
            )
        if str(finding.get("novelty", "")).strip() == "known":
            points.append(
                _decision_point(
                    category="baseline_debt_touched",
                    finding_id=str(finding.get("id", "")),
                    reason=receipt_msgs.DECISION_REASON_BASELINE_DEBT_TOUCHED,
                )
            )
    if intent_status == "expanded":
        points.append(
            _decision_point(
                category="scope_expansion",
                finding_id="",
                reason=receipt_msgs.DECISION_REASON_SCOPE_EXPANSION,
            )
        )
    return _numbered_decisions(points[:MAX_HUMAN_DECISION_POINTS])


def derive_claims_not_made(
    report_document: Mapping[str, object],
) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = [dict(item) for item in CLAIMS_NOT_MADE]
    if _suppressed_clone_count(report_document) > 0:
        claims.append(
            {
                "claim_type": "suppressed_clone_regression",
                "reason": receipt_msgs.CLAIM_REASON_SUPPRESSED_CLONE_NOT_REGRESSION,
            }
        )
    return claims


def receipt_verdict(
    *,
    reviewed_count: int,
    gate_relevant_count: int,
    patch_status: str,
    human_decision_count: int,
) -> str:
    if patch_status == ReceiptPatchStatus.VIOLATED.value:
        return ReceiptVerdict.NEEDS_ATTENTION.value
    if human_decision_count > 0:
        return ReceiptVerdict.NEEDS_ATTENTION.value
    if patch_status == ReceiptPatchStatus.NOT_CHECKED.value:
        return ReceiptVerdict.INCOMPLETE.value
    if gate_relevant_count > 0 and reviewed_count < gate_relevant_count:
        return ReceiptVerdict.INCOMPLETE.value
    return ReceiptVerdict.CLEAN.value


def derive_verification_profile_section(
    changed_files: Sequence[str],
) -> dict[str, object]:
    """Build the ``verification_profile`` section for a receipt.

    Pure function — delegates to :func:`classify_patch` and enriches the
    payload with human-readable limitations.
    """
    result = classify_patch(list(changed_files))
    matrix = check_matrix(result.profile)
    return {
        "profile": result.profile.value,
        "reason": result.reason,
        "python_source_touched": result.python_source_touched,
        "state_artifact_touched": result.state_artifact_touched,
        "governance_config_touched": result.governance_config_touched,
        "after_run_required": matrix.after_run_required,
        "structural_checks_applicable": matrix.structural_checks_applicable,
        "checks_performed": list(matrix.checks_performed),
        "checks_not_applicable": list(matrix.checks_not_applicable),
        "limitations": list(profile_limitations(result.profile)),
    }


def render_receipt_markdown(receipt: Mapping[str, object]) -> str:
    provenance = _as_mapping(receipt.get("provenance"))
    vp_section = _optional_mapping(receipt.get("verification_profile"))
    scope = _optional_mapping(receipt.get("scope"))
    blast_radius = _optional_mapping(receipt.get("blast_radius"))
    reviewed = _as_mapping(receipt.get("reviewed_evidence"))
    patch = _optional_mapping(receipt.get("patch_contract"))
    structural_delta = _as_mapping(receipt.get("structural_delta"))
    health = _as_mapping(receipt.get("health"))
    decisions = _mapping_rows(receipt.get("human_decision_points"))
    claims = _mapping_rows(receipt.get("claims_not_made"))

    lines = [
        receipt_msgs.RECEIPT_MD_TITLE,
        "",
        (
            f"**Report:** "
            f"`{provenance.get('report_digest', receipt_msgs.RECEIPT_MD_UNKNOWN)}`"
        ),
        (
            f"**Schema:** "
            f"`{provenance.get('report_schema_version', REPORT_SCHEMA_VERSION)}`"
        ),
        (
            f"**Baseline:** "
            f"{provenance.get('baseline_status', receipt_msgs.RECEIPT_MD_UNKNOWN)}"
        ),
        receipt_msgs.RECEIPT_MD_REVIEW_CONTRACT,
        "",
        "---",
    ]
    lines.extend(_render_verification_profile(vp_section))
    lines.extend(
        [
            "",
            receipt_msgs.RECEIPT_MD_SECTION_SCOPE,
        ]
    )
    if scope is None:
        lines.append(receipt_msgs.RECEIPT_MD_NO_INTENT)
    else:
        lines.extend(
            [
                f"**Intent:** {scope.get('intent_description') or 'none'}",
                f"**Status:** {scope.get('intent_status') or 'unknown'}",
                f"**Declared files:** {_inline_paths(scope.get('declared_files'))}",
                f"**Changed files:** {_inline_paths(scope.get('changed_files'))}",
                f"**Untouched in declared:** "
                f"{_inline_paths(scope.get('untouched_files'))}",
                f"**Unexpected files:** {_inline_paths(scope.get('unexpected_files'))}",
                f"**Forbidden touched:** "
                f"{_inline_paths(scope.get('forbidden_touched'))}",
            ]
        )
        held = scope.get("do_not_touch_held")
        if held:
            lines.append(f"**Do-not-touch held:** {_inline_paths(held)}")
    lines.extend(["", receipt_msgs.RECEIPT_MD_SECTION_BLAST_RADIUS])
    if blast_radius is None:
        lines.append(receipt_msgs.RECEIPT_MD_NOT_AVAILABLE)
    else:
        lines.extend(
            [
                f"**Level:** {blast_radius.get('radius_level', 'unknown')}",
                (
                    f"**Direct dependents:** "
                    f"{blast_radius.get('direct_dependents_count', 0)}"
                ),
                (
                    f"**Clone cohort members:** "
                    f"{blast_radius.get('clone_cohort_members_count', 0)}"
                ),
                (
                    f"**Do-not-touch entries:** "
                    f"{blast_radius.get('do_not_touch_count', 0)}"
                ),
            ]
        )
    lines.extend(["", receipt_msgs.RECEIPT_MD_SECTION_REVIEWED_EVIDENCE])
    lines.append(
        f"**Reviewed:** {reviewed.get('reviewed_count', 0)} / "
        f"{reviewed.get('total_gate_relevant', 0)} gate-relevant findings"
    )
    for item in _mapping_rows(reviewed.get("items")):
        note = item.get("note")
        suffix = f" - note: {note}" if note else ""
        lines.append(
            f"- `{item.get('finding_id', '')}`: {item.get('kind', 'finding')}"
            f" ({item.get('severity', 'info')}){suffix}"
        )
    if not _mapping_rows(reviewed.get("items")):
        lines.append(receipt_msgs.RECEIPT_MD_LIST_NONE)
    lines.extend(["", receipt_msgs.RECEIPT_MD_SECTION_PATCH_CONTRACT])
    if patch is None:
        lines.append(receipt_msgs.RECEIPT_MD_NOT_AVAILABLE)
    else:
        lines.extend(
            [
                f"**Status:** {patch.get('status', 'not_checked')}",
                f"**Regressions:** {patch.get('regressions', 0)}",
                f"**Improvements:** {patch.get('improvements', 0)}",
                f"**Health delta:** {_signed_delta(patch.get('health_delta'))}",
            ]
        )
    lines.extend(
        [
            "",
            receipt_msgs.RECEIPT_MD_SECTION_STRUCTURAL_DELTA,
            f"**Verdict:** {structural_delta.get('verdict', 'stable')}",
            f"**Health delta:** {_signed_delta(structural_delta.get('health_delta'))}",
            "",
            receipt_msgs.RECEIPT_MD_SECTION_HUMAN_DECISIONS,
        ]
    )
    if decisions:
        lines.extend(
            f"- **{decision.get('id', '')}:** {decision.get('reason', '')}"
            for decision in decisions
        )
    else:
        lines.append(receipt_msgs.RECEIPT_MD_LIST_NONE)
    lines.extend(["", receipt_msgs.RECEIPT_MD_SECTION_CLAIMS_NOT_MADE])
    lines.extend(f"- {claim.get('reason', '')}" for claim in claims)
    lines.extend(
        [
            "",
            f"**Health:** {health.get('score', 'n/a')}/100 "
            f"({health.get('grade', 'n/a')})",
            f"**Receipt verdict:** {receipt.get('verdict', 'incomplete')}",
            "",
            f"*Generated by CodeClone | run: `{provenance.get('run_id', 'unknown')}` | "
            f"{receipt.get('generated_at_utc', '')}*",
        ]
    )
    return "\n".join(lines)


def _render_verification_profile(
    vp_section: Mapping[str, object] | None,
) -> list[str]:
    lines = ["", "### Verification Profile"]
    if vp_section is None:
        lines.append("Not available.")
        return lines
    profile = str(vp_section.get("profile", "unknown"))
    reason = str(vp_section.get("reason", ""))
    structural = bool(vp_section.get("structural_checks_applicable", False))
    structural_label = "applicable" if structural else "not applicable"
    lines.extend(
        [
            f"**Profile:** {profile}",
            f"**Reason:** {reason}",
            f"**Structural checks:** {structural_label}",
            f"**After-run required:** {vp_section.get('after_run_required', False)}",
        ]
    )
    not_applicable = [
        str(c) for c in _as_sequence(vp_section.get("checks_not_applicable"))
    ]
    if not_applicable:
        lines.append(f"**Not applicable:** {', '.join(not_applicable)}")
    limitations = [str(lim) for lim in _as_sequence(vp_section.get("limitations"))]
    if limitations:
        lines.extend(f"- {lim}" for lim in limitations)
    return lines


def _decision_point(
    *,
    category: str,
    finding_id: str,
    reason: str,
) -> dict[str, object]:
    return {
        "id": "",
        "finding_id": finding_id,
        "reason": reason,
        "category": category,
    }


def _numbered_decisions(
    points: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "id": f"D-{index}",
            "finding_id": str(point.get("finding_id", "")),
            "reason": str(point.get("reason", "")),
            "category": str(point.get("category", "")),
        }
        for index, point in enumerate(points, start=1)
    ]


def _suppressed_clone_count(report_document: Mapping[str, object]) -> int:
    findings = _as_mapping(report_document.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    clones = _as_mapping(groups.get("clones"))
    suppressed = _as_mapping(clones.get("suppressed"))
    return sum(
        len(_as_sequence(suppressed.get(kind)))
        for kind in ("function", "block", "segment")
    )


def _inline_paths(value: object) -> str:
    paths = [str(item) for item in _as_sequence(value) if str(item)]
    if not paths:
        return "none"
    return ", ".join(f"`{path}`" for path in paths)


def _signed_delta(value: object) -> str:
    if isinstance(value, int):
        return f"{value:+d}"
    return "n/a"


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    return [_as_mapping(item) for item in _as_sequence(value)]


__all__ = [
    "CLAIMS_NOT_MADE",
    "MAX_HUMAN_DECISION_POINTS",
    "RECEIPT_VERSION",
    "VALID_RECEIPT_FORMATS",
    "ReceiptFormat",
    "ReceiptPatchStatus",
    "ReceiptVerdict",
    "derive_baseline_status",
    "derive_claims_not_made",
    "derive_human_decision_points",
    "derive_patch_status",
    "derive_verification_profile_section",
    "receipt_verdict",
    "render_receipt_markdown",
]

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Final, Literal

from ...api.execution_event import EXECUTION_PROVENANCE_KEY
from ...api.finding_groups import suppressed_clone_groups
from ...contracts import REPORT_SCHEMA_VERSION
from ...report.messages.projections import HEALTH_ABSENCE_TEXT, HEALTH_NOT_MEASURED
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ...utils.mapping_paths import section
from ...utils.payload_narrow import is_record_mapping
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


MAX_UNVERIFIED_RECEIPT_PATHS: Final = 10

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
    """Decide baseline trust from the two fields the report meta carries.

    ``trusted_for_diff`` used to be accepted here as a second route to
    ``"trusted"``. It is a CLI-side field on ``BaselineState`` that the report's
    ``meta.baseline`` block never projects, so the branch could not fire in any
    configuration and the status field was always the decider.
    """

    baseline = section(report_document, "meta.baseline")
    if not bool(baseline.get("loaded", False)):
        return "not_loaded"
    if str(baseline.get("status", "")).strip().lower() == "ok":
        return "trusted"
    return "untrusted"


def derive_patch_status(
    *,
    gate_result: Mapping[str, object] | None,
    intent_check_status: str | None,
    regressions: int,
    has_structural_delta: bool,
    patch_context_declared: bool = True,
) -> str:
    if not patch_context_declared:
        return ReceiptPatchStatus.NOT_CHECKED.value
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
    *,
    unverified_paths: Sequence[str] = (),
) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = [dict(item) for item in CLAIMS_NOT_MADE]
    if _suppressed_clone_count(report_document) > 0:
        claims.append(
            {
                "claim_type": "suppressed_clone_regression",
                "reason": receipt_msgs.CLAIM_REASON_SUPPRESSED_CLONE_NOT_REGRESSION,
            }
        )
    named = list(unverified_paths)
    if named:
        # The paths are named, not counted: a receipt that says "something was
        # not checked" without saying what is not an attestation, it is a mood.
        claims.append(
            {
                "claim_type": "unverified_workspace_paths",
                "reason": receipt_msgs.CLAIM_REASON_UNVERIFIED_WORKSPACE_PATHS,
                "paths": named[:MAX_UNVERIFIED_RECEIPT_PATHS],
                "count": len(named),
                "truncated": len(named) > MAX_UNVERIFIED_RECEIPT_PATHS,
            }
        )
    return claims


def receipt_verdict(
    *,
    reviewed_count: int,
    gate_relevant_count: int,
    patch_status: str,
    human_decision_count: int,
    verification_accepted: bool | None = None,
) -> str:
    """Derive the receipt verdict from reviewed evidence and the patch contract.

    ``verification_accepted`` carries the attested outcome of the finish that
    requested this receipt (gh #57 family B).  When the controller accepted a
    controlled change, its verification — not the receipt's own re-derivation
    from stored session state — is authoritative on the patch contract, so a
    contract-derived downgrade cannot contradict it.  Review completeness and
    human decision points stay live signals in every case, and standalone
    receipts (``None``) keep deriving the verdict from the contract alone.
    """
    contract_authoritative = verification_accepted is not True
    if contract_authoritative and patch_status == ReceiptPatchStatus.VIOLATED.value:
        return ReceiptVerdict.NEEDS_ATTENTION.value
    if human_decision_count > 0:
        return ReceiptVerdict.NEEDS_ATTENTION.value
    if contract_authoritative and patch_status == ReceiptPatchStatus.NOT_CHECKED.value:
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


def _engine_field(engine: Mapping[str, object], key: str) -> str:
    """Render one engine-provenance field, naming an unrecorded one.

    An execution that recorded no provenance carries an empty string, and empty
    backticks in a receipt read as a value rather than as its absence. The
    typed receipt keeps the raw value; only this rendering names it.
    """

    value = str(engine.get(key, "")).strip()
    return value or receipt_msgs.RECEIPT_MD_UNKNOWN


def render_receipt_markdown(receipt: Mapping[str, object]) -> str:
    provenance = _as_mapping(receipt.get("provenance"))
    engine = _as_mapping(provenance.get(EXECUTION_PROVENANCE_KEY))
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
        # Read, never re-derived: the engine block is produced once, where the
        # process identity is known, and this line only spends it. A renderer
        # that recomputed provenance would be a second owner of the fact.
        (
            f"**Engine:** `{_engine_field(engine, 'generation')}` "
            f"loaded from `{_engine_field(engine, 'loaded_package_root')}` "
            f"(execution `{_engine_field(engine, 'execution_event_id')}`)"
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
            *_structural_delta_evidence(structural_delta),
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
    for claim in claims:
        lines.append(f"- {claim.get('reason', '')}")
        # A claim that names paths renders them: the markdown receipt is what
        # a human reads, and "no claim about them" is empty without "them".
        lines.extend(f"  - `{path}`" for path in _as_sequence(claim.get("paths")))
    lines.extend(
        [
            "",
            f"**Health:** {_receipt_health_text(health)}",
            f"**Receipt verdict:** {receipt.get('verdict', 'incomplete')}",
            "",
            f"*Generated by CodeClone | run: `{provenance.get('run_id', 'unknown')}` | "
            f"{receipt.get('generated_at_utc', '')}*",
        ]
    )
    return "\n".join(lines)


def _structural_delta_evidence(
    structural_delta: Mapping[str, object],
) -> list[str]:
    """Render the stated reason behind a non-numeric structural verdict.

    Verdicts that carry no delta (``not_comparable``, ``analyzer_invariant``)
    are only honest when the receipt also says *why* no comparison was made.
    """

    reason = str(structural_delta.get("reason", "")).strip()
    return [f"**Evidence:** {reason}"] if reason else []


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
    """Count the suppressed clone groups the document actually publishes.

    Counted through the owner rather than by re-spelling the producer's bucket
    keys here: this counter spelled them in the singular against a container
    that spells them in the plural, so it returned zero for every document that
    had anything to count, and the receipt then declined to make a claim it had
    every reason to make.
    """

    return suppressed_clone_groups(report_document).count


def _inline_paths(value: object) -> str:
    paths = [str(item) for item in _as_sequence(value) if str(item)]
    if not paths:
        return "none"
    return ", ".join(f"`{path}`" for path in paths)


def _signed_delta(value: object) -> str:
    if isinstance(value, int):
        return f"{value:+d}"
    return "n/a"


def _receipt_health_text(health: Mapping[str, object]) -> str:
    """Render the receipt health line, or say that nothing was measured.

    A receipt is evidence, so "None/100 (None)" is worse here than anywhere
    else: it reads as a measured score of nothing rather than as the absence
    of a measurement. And evidence has to name *which* absence: a receipt
    saying "no file was read" about a scope that simply holds no Python would
    be a second, quieter falsehood in the same line.
    """

    if health.get("score") is None and "population" in health:
        return HEALTH_ABSENCE_TEXT.get(
            str(health.get("population", "")),
            HEALTH_NOT_MEASURED,
        )
    return f"{health.get('score', 'n/a')}/100 ({health.get('grade', 'n/a')})"


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    return value if is_record_mapping(value) else None


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

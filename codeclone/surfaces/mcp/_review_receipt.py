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
        "reason": (
            "Security Surfaces are report-only trust-boundary inventory, "
            "not vulnerability claims."
        ),
    },
    {
        "claim_type": "baseline_regression",
        "reason": (
            "Known baseline debt was not treated as a new regression; "
            "novelty='known' remains baseline context."
        ),
    },
    {
        "claim_type": "report_only_ci_failure",
        "reason": ("Report-only signals were not treated as CI gate failures."),
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
                    reason=(
                        "Clone cohort member was in changed scope; "
                        "confirm divergence is intentional."
                    ),
                )
            )
        if str(finding.get("novelty", "")).strip() == "known":
            points.append(
                _decision_point(
                    category="baseline_debt_touched",
                    finding_id=str(finding.get("id", "")),
                    reason=(
                        "Known baseline finding was in changed scope; "
                        "confirm whether the patch addresses or preserves it."
                    ),
                )
            )
    if intent_status == "expanded":
        points.append(
            _decision_point(
                category="scope_expansion",
                finding_id="",
                reason=(
                    "Edit scope expanded beyond declared files; "
                    "human confirmation is required."
                ),
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
                "reason": (
                    "Suppressed clone groups were not counted as active new "
                    "regressions."
                ),
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


def render_receipt_markdown(receipt: Mapping[str, object]) -> str:
    provenance = _as_mapping(receipt.get("provenance"))
    scope = _optional_mapping(receipt.get("scope"))
    blast_radius = _optional_mapping(receipt.get("blast_radius"))
    reviewed = _as_mapping(receipt.get("reviewed_evidence"))
    patch = _optional_mapping(receipt.get("patch_contract"))
    structural_delta = _as_mapping(receipt.get("structural_delta"))
    health = _as_mapping(receipt.get("health"))
    decisions = _mapping_rows(receipt.get("human_decision_points"))
    claims = _mapping_rows(receipt.get("claims_not_made"))

    lines = [
        "## CodeClone Agent Review Receipt",
        "",
        f"**Report:** `{provenance.get('report_digest', 'unknown')}`",
        (
            f"**Schema:** "
            f"`{provenance.get('report_schema_version', REPORT_SCHEMA_VERSION)}`"
        ),
        f"**Baseline:** {provenance.get('baseline_status', 'unknown')}",
        "**Review contract:** v1",
        "",
        "---",
        "",
        "### Scope",
    ]
    if scope is None:
        lines.append("No intent declared.")
    else:
        lines.extend(
            [
                f"**Intent:** {scope.get('intent_description') or 'none'}",
                f"**Status:** {scope.get('intent_status') or 'unknown'}",
                f"**Declared files:** {_inline_paths(scope.get('declared_files'))}",
                f"**Changed files:** {_inline_paths(scope.get('changed_files'))}",
                f"**Unexpected files:** {_inline_paths(scope.get('unexpected_files'))}",
            ]
        )
    lines.extend(["", "### Blast Radius"])
    if blast_radius is None:
        lines.append("Not available.")
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
    lines.extend(["", "### Reviewed Evidence"])
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
        lines.append("- none")
    lines.extend(["", "### Patch Contract"])
    if patch is None:
        lines.append("Not available.")
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
            "### Structural Delta",
            f"**Verdict:** {structural_delta.get('verdict', 'stable')}",
            f"**Health delta:** {_signed_delta(structural_delta.get('health_delta'))}",
            "",
            "### Human Decisions Requested",
        ]
    )
    if decisions:
        lines.extend(
            f"- **{decision.get('id', '')}:** {decision.get('reason', '')}"
            for decision in decisions
        )
    else:
        lines.append("- none")
    lines.extend(["", "### Claims Not Made"])
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
    "receipt_verdict",
    "render_receipt_markdown",
]

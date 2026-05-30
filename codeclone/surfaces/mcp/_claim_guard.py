# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from .messages import claims as claim_msgs

MAX_REVIEW_CLAIM_TEXT_CHARS: Final = 50_000
TEXT_WINDOW_RADIUS: Final = 80
SECURITY_SURFACES_FAMILY: Final = "security_surfaces"

CitationKind = Literal["finding", "metric_family"]

SECURITY_OVERCLAIM_KEYWORDS: Final = (
    "vulnerab",
    "exploit",
    "attack",
    "cve",
    "threat",
    "security flaw",
    "security bug",
    "security issue",
)
GATE_OVERCLAIM_KEYWORDS: Final = (
    "fail",
    "block",
    "gate",
    "ci ",
    "ci-",
    "pipeline",
    "break build",
    "must fix",
    "blocking",
)
REGRESSION_OVERCLAIM_KEYWORDS: Final = (
    "new ",
    "regress",
    "introduc",
    "just appeared",
    "added",
    "caused by",
    "broke",
)
DEAD_CODE_CERTAINTY_KEYWORDS: Final = (
    "dead",
    "unused",
    "unreachable",
    "remove",
    "delete",
    "safe to remove",
    "definitely dead",
)
FIX_OVERCLAIM_KEYWORDS: Final = (
    "fixed",
    "resolved",
    "eliminated",
    "removed the",
    "cleaned up",
    "refactored away",
    "no longer",
)
STRUCTURAL_SCOPE_KEYWORDS: Final = (
    "no structural regression",
    "no regressions",
    "regression-free",
    "structural verification",
    "structurally verified",
    "all checks passed",
    "code quality verified",
)

_STRUCTURAL_PROFILES: Final[frozenset[str]] = frozenset({"python_structural"})

_UNKNOWN_SHORT_FINDING_RE: Final = re.compile(r"\bF-\d+\b", re.IGNORECASE)
_LITERAL_BOUNDARY_CHARS: Final = r"A-Za-z0-9_:"
_SENTENCE_BOUNDARIES: Final = ".!?\n"


@dataclass(frozen=True, slots=True)
class Citation:
    cited_id: str
    kind: CitationKind
    text_window: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class Violation:
    pattern: str
    claim: str
    cited_id: str
    reason: str
    source_flag: str


@dataclass(frozen=True, slots=True)
class ReportContext:
    findings: Mapping[str, Mapping[str, object]]
    short_to_canonical: Mapping[str, str]
    reachable_qualnames: frozenset[str]
    report_only_families: frozenset[str]
    has_comparison_run: bool
    metric_families: frozenset[str]
    verification_profile: str | None = None
    patch_health_delta: int | None = None


def validate_claims(
    *,
    text: str,
    report_context: ReportContext,
    require_citations: bool = True,
) -> dict[str, object]:
    citations = extract_citations(text, report_context=report_context)
    violations = _violations_for_citations(
        citations=citations,
        report_context=report_context,
    )
    violations = (*violations, *_text_violations(text, report_context=report_context))
    warnings = _warnings_for_text(
        text=text,
        citations=citations,
        report_context=report_context,
        require_citations=require_citations,
    )
    violation_keys = {
        (violation.pattern, violation.cited_id, violation.claim)
        for violation in violations
    }
    return {
        "valid": len(violations) == 0,
        "citations_found": len(citations),
        "violations": [_violation_payload(violation) for violation in violations],
        "warnings": warnings,
        "validated_citations": [
            {
                "cited_id": citation.cited_id,
                "kind": citation.kind,
                "valid": not any(
                    key[1] == citation.cited_id and key[2] == citation.text_window
                    for key in violation_keys
                ),
            }
            for citation in citations
        ],
    }


def validate_text_input(text: object) -> str:
    if not isinstance(text, str):
        raise ValueError(claim_msgs.ERR_TEXT_NOT_STRING)
    cleaned = text.strip()
    if not cleaned:
        raise ValueError(claim_msgs.ERR_TEXT_EMPTY)
    if len(text) > MAX_REVIEW_CLAIM_TEXT_CHARS:
        raise ValueError(
            claim_msgs.ERR_TEXT_TOO_LONG.format(
                max_chars=MAX_REVIEW_CLAIM_TEXT_CHARS,
            )
        )
    return text


def extract_citations(
    text: str,
    *,
    report_context: ReportContext,
) -> tuple[Citation, ...]:
    citations: list[Citation] = []
    known_finding_ids = {
        *report_context.findings.keys(),
        *report_context.short_to_canonical.keys(),
    }
    for finding_id in sorted(known_finding_ids):
        canonical_id = report_context.short_to_canonical.get(finding_id, finding_id)
        if canonical_id not in report_context.findings:
            continue
        citations.extend(
            Citation(
                cited_id=canonical_id,
                kind="finding",
                text_window=text_window(text, match.start(), match.end()),
                start_offset=match.start(),
                end_offset=match.end(),
            )
            for match in _find_literal_matches(text, finding_id)
        )
    for family_name in sorted(report_context.metric_families):
        for variant in _metric_family_patterns(family_name):
            citations.extend(
                Citation(
                    cited_id=family_name,
                    kind="metric_family",
                    text_window=text_window(text, match.start(), match.end()),
                    start_offset=match.start(),
                    end_offset=match.end(),
                )
                for match in variant.finditer(text)
            )
    return tuple(
        sorted(
            _dedupe_citations(citations),
            key=lambda item: (
                item.start_offset,
                item.end_offset,
                item.kind,
                item.cited_id,
            ),
        )
    )


def text_window(
    text: str,
    start_offset: int,
    end_offset: int,
    *,
    radius: int = TEXT_WINDOW_RADIUS,
) -> str:
    bound_start = max(0, start_offset - radius)
    bound_end = min(len(text), end_offset + radius)
    sentence_start = max(
        (
            text.rfind(boundary, bound_start, start_offset)
            for boundary in _SENTENCE_BOUNDARIES
        ),
        default=-1,
    )
    start = max(bound_start, sentence_start + 1)
    sentence_ends = [
        candidate
        for boundary in _SENTENCE_BOUNDARIES
        if (candidate := text.find(boundary, end_offset, bound_end)) != -1
    ]
    end = min(sentence_ends) + 1 if sentence_ends else bound_end
    return text[start:end].strip()


def _violations_for_citations(
    *,
    citations: Sequence[Citation],
    report_context: ReportContext,
) -> tuple[Violation, ...]:
    checks = (
        _check_security_vulnerability_overclaim,
        _check_report_only_gate_overclaim,
        _check_known_debt_overclaim,
        _check_dead_code_reachability_overclaim,
        _check_fix_without_verification,
    )
    violations: list[Violation] = []
    for check in checks:
        violations.extend(check(citations=citations, report_context=report_context))
    return tuple(
        sorted(
            _dedupe_violations(violations),
            key=lambda item: (item.pattern, item.cited_id, item.claim),
        )
    )


def _check_security_vulnerability_overclaim(
    *,
    citations: Sequence[Citation],
    report_context: ReportContext,
) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    for citation in citations:
        if (
            citation.kind != "metric_family"
            or citation.cited_id != SECURITY_SURFACES_FAMILY
        ):
            continue
        if not _contains_keyword(citation.text_window, SECURITY_OVERCLAIM_KEYWORDS):
            continue
        violations.append(
            Violation(
                pattern="P-1",
                claim=citation.text_window,
                cited_id=citation.cited_id,
                reason=claim_msgs.VIOLATION_REASON_SECURITY_NOT_VULNERABILITY,
                source_flag="security_surfaces.gate_keys=()",
            )
        )
    return tuple(violations)


def _check_report_only_gate_overclaim(
    *,
    citations: Sequence[Citation],
    report_context: ReportContext,
) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    for citation in citations:
        if citation.kind != "metric_family":
            continue
        if citation.cited_id not in report_context.report_only_families:
            continue
        if not _contains_keyword(citation.text_window, GATE_OVERCLAIM_KEYWORDS):
            continue
        violations.append(
            Violation(
                pattern="P-2",
                claim=citation.text_window,
                cited_id=citation.cited_id,
                reason=claim_msgs.VIOLATION_REASON_REPORT_ONLY_GATE.format(
                    family=citation.cited_id,
                ),
                source_flag=f"{citation.cited_id}.gate_keys=()",
            )
        )
    return tuple(violations)


def _check_known_debt_overclaim(
    *,
    citations: Sequence[Citation],
    report_context: ReportContext,
) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    for citation in citations:
        if citation.kind != "finding":
            continue
        finding = report_context.findings.get(citation.cited_id)
        if finding is None or str(finding.get("novelty", "")) != "known":
            continue
        if not _contains_keyword(citation.text_window, REGRESSION_OVERCLAIM_KEYWORDS):
            continue
        violations.append(
            Violation(
                pattern="P-3",
                claim=citation.text_window,
                cited_id=citation.cited_id,
                reason=claim_msgs.VIOLATION_REASON_KNOWN_DEBT_OVERCLAIM,
                source_flag="finding.novelty='known'",
            )
        )
    return tuple(violations)


def _check_dead_code_reachability_overclaim(
    *,
    citations: Sequence[Citation],
    report_context: ReportContext,
) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    for citation in citations:
        if citation.kind != "finding":
            continue
        finding = report_context.findings.get(citation.cited_id)
        if finding is None or not _is_dead_code_finding(citation.cited_id, finding):
            continue
        if not _contains_keyword(citation.text_window, DEAD_CODE_CERTAINTY_KEYWORDS):
            continue
        reachable = sorted(
            qualname
            for qualname in _extract_qualnames_from_finding(citation.cited_id, finding)
            if qualname in report_context.reachable_qualnames
        )
        if not reachable:
            continue
        violations.append(
            Violation(
                pattern="P-4",
                claim=citation.text_window,
                cited_id=citation.cited_id,
                reason=claim_msgs.VIOLATION_REASON_DEAD_CODE_REACHABILITY.format(
                    qualname=reachable[0],
                ),
                source_flag="runtime_reachability.evidence_present",
            )
        )
    return tuple(violations)


def _check_fix_without_verification(
    *,
    citations: Sequence[Citation],
    report_context: ReportContext,
) -> tuple[Violation, ...]:
    if report_context.has_comparison_run:
        return ()
    violations: list[Violation] = []
    for citation in citations:
        if citation.kind != "finding" or not _contains_keyword(
            citation.text_window,
            FIX_OVERCLAIM_KEYWORDS,
        ):
            continue
        violations.append(
            Violation(
                pattern="P-5",
                claim=citation.text_window,
                cited_id=citation.cited_id,
                reason=claim_msgs.VIOLATION_REASON_FIX_WITHOUT_VERIFICATION,
                source_flag="session.comparison_run_available=false",
            )
        )
    return tuple(violations)


def _warnings_for_text(
    *,
    text: str,
    citations: Sequence[Citation],
    report_context: ReportContext,
    require_citations: bool,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if require_citations and not citations:
        warnings.append(
            {
                "type": "no_citations",
                "message": claim_msgs.WARN_NO_CITATIONS,
            }
        )
    for match in _UNKNOWN_SHORT_FINDING_RE.finditer(text):
        cited_id = match.group(0).upper()
        if cited_id not in report_context.short_to_canonical:
            warnings.append(
                {
                    "type": "unknown_finding",
                    "message": claim_msgs.WARN_UNKNOWN_FINDING.format(
                        cited_id=cited_id,
                    ),
                }
            )
    profile = report_context.verification_profile
    if (
        profile is not None
        and profile not in _STRUCTURAL_PROFILES
        and _contains_keyword(text, STRUCTURAL_SCOPE_KEYWORDS)
    ):
        warnings.append(
            {
                "type": "structural_checks_not_applicable",
                "message": claim_msgs.WARN_STRUCTURAL_CHECKS_NOT_APPLICABLE.format(
                    profile=profile,
                ),
            }
        )
    health_delta = report_context.patch_health_delta
    if (
        health_delta is not None
        and health_delta < 0
        and _contains_keyword(text, STRUCTURAL_SCOPE_KEYWORDS)
    ):
        warnings.append(
            {
                "type": "health_regression_overclaim",
                "message": claim_msgs.WARN_HEALTH_REGRESSION_OVERCLAIM.format(
                    health_delta=health_delta,
                ),
            }
        )
    return warnings


def _text_violations(
    text: str,
    *,
    report_context: ReportContext,
) -> tuple[Violation, ...]:
    health_delta = report_context.patch_health_delta
    if health_delta is None or health_delta >= 0:
        return ()
    if not _contains_keyword(text, STRUCTURAL_SCOPE_KEYWORDS):
        return ()
    return (
        Violation(
            pattern="health_regression_overclaim",
            claim=text.strip()[:TEXT_WINDOW_RADIUS],
            cited_id="",
            reason=claim_msgs.VIOLATION_REASON_HEALTH_REGRESSION_OVERCLAIM.format(
                health_delta=health_delta,
            ),
            source_flag=f"patch.health_delta={health_delta}",
        ),
    )


def _metric_family_patterns(family_name: str) -> tuple[re.Pattern[str], ...]:
    canonical = re.compile(rf"\b{re.escape(family_name)}\b", flags=re.IGNORECASE)
    if "_" not in family_name:
        return (canonical,)
    spaced_escaped = re.escape(family_name).replace("_", r"\s+")
    spaced = re.compile(rf"\b{spaced_escaped}\b", flags=re.IGNORECASE)
    return (canonical, spaced)


def _find_literal_matches(text: str, literal: str) -> tuple[re.Match[str], ...]:
    pattern = re.compile(
        rf"(?<![{_LITERAL_BOUNDARY_CHARS}])"
        rf"{re.escape(literal)}"
        rf"(?![{_LITERAL_BOUNDARY_CHARS}])",
        flags=re.IGNORECASE,
    )
    return tuple(pattern.finditer(text))


def _contains_keyword(text: str, keywords: Sequence[str]) -> bool:
    lowered = text.casefold()
    return any(keyword.casefold() in lowered for keyword in keywords)


def _dedupe_citations(citations: Sequence[Citation]) -> tuple[Citation, ...]:
    seen: set[tuple[str, str, int, int]] = set()
    deduped: list[Citation] = []
    for citation in citations:
        key = (
            citation.kind,
            citation.cited_id.casefold(),
            citation.start_offset,
            citation.end_offset,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return tuple(deduped)


def _dedupe_violations(violations: Sequence[Violation]) -> tuple[Violation, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[Violation] = []
    for violation in violations:
        key = (
            violation.pattern,
            violation.cited_id,
            violation.claim,
            violation.source_flag,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(violation)
    return tuple(deduped)


def _violation_payload(violation: Violation) -> dict[str, str]:
    return {
        "pattern": violation.pattern,
        "claim": violation.claim,
        "cited_id": violation.cited_id,
        "reason": violation.reason,
        "source_flag": violation.source_flag,
    }


def _is_dead_code_finding(
    finding_id: str,
    finding: Mapping[str, object],
) -> bool:
    return (
        finding_id.startswith("dead_code:")
        or str(finding.get("family", "")) == "dead_code"
        or str(finding.get("category", "")) == "dead_code"
    )


def _extract_qualnames_from_finding(
    finding_id: str,
    finding: Mapping[str, object],
) -> frozenset[str]:
    qualnames: set[str] = set()
    _collect_qualname_fields(finding, qualnames)
    for item in _as_sequence(finding.get("items")):
        if isinstance(item, Mapping):
            _collect_qualname_fields(item, qualnames)
    if finding_id.startswith("dead_code:"):
        _, _, remainder = finding_id.partition(":")
        if remainder:
            qualnames.add(remainder)
    return frozenset(sorted(qualnames))


def _collect_qualname_fields(
    payload: Mapping[str, object],
    qualnames: set[str],
) -> None:
    for field_name in (
        "qualname",
        "target_qualname",
        "symbol",
        "name",
        "subject_key",
    ):
        value = str(payload.get(field_name, "")).strip()
        if value:
            qualnames.add(value)


def _as_sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()

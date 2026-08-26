# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal

from ...contracts import TIER_STATE_COMPLETE
from ...utils import coerce as _coerce
from ...utils.payload_narrow import is_record_mapping
from .messages import claims as claim_msgs

MAX_REVIEW_CLAIM_TEXT_CHARS: Final = 50_000
TEXT_WINDOW_RADIUS: Final = 80
SECURITY_SURFACES_FAMILY: Final = "security_surfaces"
#: Metric families are read out as words ("security surfaces"); clone tiers
#: are habitually hyphenated ("near-miss"). Each vocabulary keeps its own
#: relaxed separator so widening one never silently widens the other.
METRIC_FAMILY_SEPARATOR: Final = r"\s+"
CLONE_TIER_SEPARATOR: Final = r"[\s\-]+"

CitationKind = Literal["finding", "metric_family", "clone_tier"]


def _as_sequence(value: object) -> Sequence[object]:
    return _coerce.as_sequence(value)


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
# A claim about an advisory clone tier is a measurement claim when it names
# an outcome AND the thing measured. Both halves are required: "the near_miss
# tier is disabled" names no outcome, and "renamed_structure has no gate
# relevance" names no measured subject — both are true sentences about the
# tier's standing, and a guard that rejected them would only teach reviewers
# to stop naming the tiers.
TIER_OUTCOME_TERMS: Final = (
    "absent",
    "clean",
    "clear",
    "detect",
    "detected",
    "detects",
    "find",
    "finds",
    "flagged",
    "found",
    "free",
    "never",
    "no",
    "none",
    "not",
    "nothing",
    "reported",
    "reports",
    "surfaced",
    "without",
    "zero",
)
TIER_SUBJECT_TERMS: Final = (
    "candidate",
    "candidates",
    "clone",
    "clones",
    "duplicate",
    "duplicates",
    "finding",
    "findings",
    "group",
    "groups",
    "hit",
    "hits",
    "match",
    "matches",
    "pair",
    "pairs",
    "result",
    "results",
)

_STRUCTURAL_PROFILES: Final[frozenset[str]] = frozenset({"python_structural"})

_UNKNOWN_SHORT_FINDING_RE: Final = re.compile(r"\bF-\d+\b", re.IGNORECASE)
_LITERAL_BOUNDARY_CHARS: Final = r"A-Za-z0-9_:"
_SENTENCE_BOUNDARIES: Final = ".!?\n"
_NEGATION_WINDOW: Final = re.compile(
    r"(?:cannot|can't|can not|does not|doesn't|do not|don't|never|not)\s+"
    r"(?:\w+\s+){0,4}$",
    re.IGNORECASE,
)


def _word_alternation(terms: Sequence[str]) -> re.Pattern[str]:
    return re.compile(
        r"\b(?:" + "|".join(re.escape(term) for term in terms) + r")\b",
        flags=re.IGNORECASE,
    )


_TIER_OUTCOME_RE: Final = _word_alternation(TIER_OUTCOME_TERMS)
_TIER_SUBJECT_RE: Final = _word_alternation(TIER_SUBJECT_TERMS)
# A bare count is an outcome on its own: "near_miss: 3 pairs" states a
# measurement without any of the outcome verbs above.
_TIER_COUNT_RE: Final = re.compile(r"\b\d+\b")


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
    #: Advisory clone tier -> its container's execution ``state`` for this
    #: run, exactly as the producers stamped it (T1, 2026-08-24). The guard
    #: never restates which tiers exist: the mapping IS the vocabulary, so a
    #: third tier container is covered the day the producers emit it. Empty
    #: means the run's document carried no tier container at all, and the
    #: guard then has nothing to check a tier claim against.
    tier_states: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}),
    )


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
    citations.extend(
        _name_citations(
            text,
            names=report_context.metric_families,
            kind="metric_family",
            relaxed_separator=METRIC_FAMILY_SEPARATOR,
        )
    )
    citations.extend(
        _name_citations(
            text,
            names=report_context.tier_states,
            kind="clone_tier",
            relaxed_separator=CLONE_TIER_SEPARATOR,
        )
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
        _check_tier_claim_without_measurement,
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


def _check_tier_claim_without_measurement(
    *,
    citations: Sequence[Citation],
    report_context: ReportContext,
) -> tuple[Violation, ...]:
    """P-6: a tier claim standing on a measurement that never happened.

    Same shape as P-5 one check up — a claim whose evidence does not exist —
    read off the tier container's own execution witness. At ``complete`` the
    producer ran, so ``count: 0`` is a real empty result and "no near-miss
    clones" is simply true; at every other state (today only ``disabled``)
    the container omits ``count`` entirely, and an absence that was never
    measured is not an absence.

    Matching here is deliberately negation-blind, unlike the sibling checks.
    Those exist to spare a reviewer who *denies* an overclaim ("not a
    vulnerability"). Here the negation IS the claim: "we did not find any
    near-miss clones" is precisely the sentence the sanction names, and
    routing it through :func:`_contains_keyword` would drop it as a denial.
    """

    violations: list[Violation] = []
    for citation in citations:
        state = str(report_context.tier_states.get(citation.cited_id, "")).strip()
        if not _is_unmeasured_tier_claim(citation, state=state):
            continue
        reported_state = state or "unknown"
        violations.append(
            Violation(
                pattern="P-6",
                claim=citation.text_window,
                cited_id=citation.cited_id,
                reason=claim_msgs.VIOLATION_REASON_TIER_NOT_MEASURED.format(
                    tier=citation.cited_id,
                    state=reported_state,
                ),
                source_flag=(
                    f"findings.groups.{citation.cited_id}.state={reported_state}"
                ),
            )
        )
    return tuple(violations)


def _is_unmeasured_tier_claim(citation: Citation, *, state: str) -> bool:
    return (
        citation.kind == "clone_tier"
        and state != TIER_STATE_COMPLETE
        and _states_a_tier_measurement(citation.text_window)
    )


def _states_a_tier_measurement(window: str) -> bool:
    if _TIER_SUBJECT_RE.search(window) is None:
        return False
    return (
        _TIER_OUTCOME_RE.search(window) is not None
        or _TIER_COUNT_RE.search(window) is not None
    )


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


def _name_patterns(
    name: str,
    *,
    relaxed_separator: str,
) -> tuple[re.Pattern[str], ...]:
    """Match a wire name and the prose spelling reviewers actually write.

    The separator is the caller's, because the two vocabularies are read in
    different registers: a metric family is written out as words
    ("security surfaces"), while a clone tier is habitually hyphenated
    ("near-miss"). A matcher that only knew the wire spelling would be
    escaped by ordinary English.
    """

    canonical = re.compile(rf"\b{re.escape(name)}\b", flags=re.IGNORECASE)
    if "_" not in name:
        return (canonical,)
    relaxed_escaped = re.escape(name).replace("_", relaxed_separator)
    relaxed = re.compile(rf"\b{relaxed_escaped}\b", flags=re.IGNORECASE)
    return (canonical, relaxed)


def _name_citations(
    text: str,
    *,
    names: Iterable[str],
    kind: CitationKind,
    relaxed_separator: str,
) -> list[Citation]:
    """Cite every mention of a closed vocabulary, in deterministic order."""

    citations: list[Citation] = []
    for name in sorted(names):
        for variant in _name_patterns(name, relaxed_separator=relaxed_separator):
            citations.extend(
                Citation(
                    cited_id=name,
                    kind=kind,
                    text_window=text_window(text, match.start(), match.end()),
                    start_offset=match.start(),
                    end_offset=match.end(),
                )
                for match in variant.finditer(text)
            )
    return citations


def _find_literal_matches(text: str, literal: str) -> tuple[re.Match[str], ...]:
    pattern = re.compile(
        rf"(?<![{_LITERAL_BOUNDARY_CHARS}])"
        rf"{re.escape(literal)}"
        rf"(?![{_LITERAL_BOUNDARY_CHARS}])",
        flags=re.IGNORECASE,
    )
    return tuple(pattern.finditer(text))


def _match_is_negated(text: str, *, start: int) -> bool:
    window = text[max(0, start - 48) : start]
    return _NEGATION_WINDOW.search(window) is not None


def _contains_keyword(text: str, keywords: Sequence[str]) -> bool:
    lowered = text.casefold()
    for keyword in keywords:
        needle = keyword.casefold()
        start = 0
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            if not _match_is_negated(text, start=index):
                return True
            start = index + len(needle)
    return False


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
        if is_record_mapping(item):
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

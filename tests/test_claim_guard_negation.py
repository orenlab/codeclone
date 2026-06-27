# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from typing import cast

from codeclone.surfaces.mcp import _claim_guard as mcp_claim_guard_mod


def _claim_guard_context(
    *, has_comparison_run: bool = False
) -> mcp_claim_guard_mod.ReportContext:
    findings: dict[str, dict[str, object]] = {
        "clone:function:g1": {
            "id": "clone:function:g1",
            "family": "clone",
            "category": "function",
            "novelty": "new",
        },
        "clone:function:g2": {
            "id": "clone:function:g2",
            "family": "clone",
            "category": "function",
            "novelty": "known",
        },
        "dead_code:pkg.routes:handler": {
            "id": "dead_code:pkg.routes:handler",
            "family": "dead_code",
            "category": "dead_code",
            "novelty": "new",
            "items": [{"qualname": "pkg.routes:handler"}],
        },
    }
    return mcp_claim_guard_mod.ReportContext(
        findings=findings,
        short_to_canonical={
            "F-1": "clone:function:g1",
            "F-2": "clone:function:g2",
            "F-3": "dead_code:pkg.routes:handler",
        },
        reachable_qualnames=frozenset({"pkg.routes:handler"}),
        report_only_families=frozenset({"overloaded_modules", "security_surfaces"}),
        has_comparison_run=has_comparison_run,
        metric_families=frozenset(
            {
                "api_surface",
                "cohesion",
                "complexity",
                "coupling",
                "coverage_adoption",
                "coverage_join",
                "dead_code",
                "dependencies",
                "health",
                "overloaded_modules",
                "security_surfaces",
            }
        ),
    )


def test_claim_guard_ignores_negated_security_overclaim() -> None:
    payload = mcp_claim_guard_mod.validate_claims(
        text=("security_surfaces is report-only inventory, not vulnerabilities."),
        report_context=_claim_guard_context(),
        require_citations=False,
    )
    assert payload["valid"] is True
    assert payload["violations"] == []


def test_claim_guard_still_flags_unnegated_security_overclaim() -> None:
    payload = mcp_claim_guard_mod.validate_claims(
        text="security_surfaces found vulnerabilities in auth routes.",
        report_context=_claim_guard_context(),
        require_citations=False,
    )
    violations = cast("list[dict[str, object]]", payload["violations"])
    assert payload["valid"] is False
    assert {str(item["pattern"]) for item in violations} == {"P-1"}


def test_claim_guard_ignores_negated_gate_and_regression_overclaims() -> None:
    payload = mcp_claim_guard_mod.validate_claims(
        text=(
            "overloaded_modules will not fail CI. "
            "F-2 is not a new regression. "
            "F-3 is not dead code."
        ),
        report_context=_claim_guard_context(),
        require_citations=False,
    )
    assert payload["valid"] is True
    assert payload["violations"] == []


def test_claim_guard_still_flags_unnegated_gate_and_regression_overclaims() -> None:
    payload = mcp_claim_guard_mod.validate_claims(
        text=("overloaded_modules will fail CI. F-2 is a new regression."),
        report_context=_claim_guard_context(),
        require_citations=False,
    )
    violations = cast("list[dict[str, object]]", payload["violations"])
    assert payload["valid"] is False
    assert {str(item["pattern"]) for item in violations} == {"P-2", "P-3"}


def test_claim_guard_negation_helpers() -> None:
    text = "report-only inventory, not vulnerabilities"
    vuln_start = text.casefold().find("vulnerab")
    assert vuln_start >= 0
    assert mcp_claim_guard_mod._match_is_negated(text, start=vuln_start)
    found_start = "found vulnerabilities".casefold().find("vulnerab")
    assert found_start >= 0
    assert not mcp_claim_guard_mod._match_is_negated(
        "found vulnerabilities",
        start=found_start,
    )
    assert not mcp_claim_guard_mod._contains_keyword(
        "not vulnerabilities",
        mcp_claim_guard_mod.SECURITY_OVERCLAIM_KEYWORDS,
    )
    assert mcp_claim_guard_mod._contains_keyword(
        "found vulnerabilities",
        mcp_claim_guard_mod.SECURITY_OVERCLAIM_KEYWORDS,
    )


def test_claim_guard_health_overclaim_still_detects_positive_denials() -> None:
    context = replace(
        _claim_guard_context(),
        verification_profile="documentation_only",
        patch_health_delta=-2,
    )
    payload = mcp_claim_guard_mod.validate_claims(
        text="No structural regressions were introduced in this docs patch.",
        report_context=context,
        require_citations=False,
    )
    violations = cast("list[dict[str, str]]", payload["violations"])
    assert any(item["pattern"] == "health_regression_overclaim" for item in violations)

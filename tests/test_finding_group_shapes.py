# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The document builders publish the pieces ``codeclone.findings.group_shapes``
owns -- pinned THROUGH the builders, against literals.

Every expectation below is an independent literal of what the document has
always published for the input, never a call to the owner: a pin that held
the builder's output to the owner's output would prove only that the builder
called the owner, and would stay green under a wrong owner.  Read through
the builders, a mutant in the owner reddens here; so does a builder that
stopped reading the owner and grew a spelling of its own.  Both threshold
boundaries of every design category are reached, because a predicate pinned
on one side of its boundary is pinned on neither, and the coverage flags are
read through the metrics payload, the second production reader of that
owner.
"""

from __future__ import annotations

from codeclone.contracts import STATEMENT_REACHABILITY_POLICY_VERSION
from codeclone.core.coverage_payload import _coverage_join_rows
from codeclone.findings.group_shapes import design_thresholds
from codeclone.metrics.coverage_join import permille
from codeclone.models import (
    CoverageJoinResult,
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    UnitCoverageFact,
)
from codeclone.report.document._design_groups import _build_design_groups
from codeclone.report.document._findings_groups import (
    _build_dead_code_groups,
    _build_structural_groups,
)
from codeclone.report.document.findings import _build_authority_groups

# -- structural --------------------------------------------------------------


def _occurrence(
    kind: str, key: str, path: str, qualname: str, start: int, end: int
) -> StructuralFindingOccurrence:
    return StructuralFindingOccurrence(
        finding_kind=kind,
        finding_key=key,
        file_path=path,
        qualname=qualname,
        start=start,
        end=end,
        signature={},
    )


def test_a_duplicated_branch_group_publishes_the_owners_signature_and_facts() -> None:
    signature = {
        "stmt_seq": "Return",
        "terminal": "return",
        "has_loop": "1",
        "has_try": "0",
        "nested_if": "0",
        "calls": "2",
        "raises": "0",
    }
    group = StructuralFindingGroup(
        finding_kind="duplicated_branches",
        finding_key="k1",
        signature=signature,
        items=(
            _occurrence("duplicated_branches", "k1", "pkg/a.py", "pkg.a:f", 1, 3),
            _occurrence("duplicated_branches", "k1", "pkg/a.py", "pkg.a:f", 10, 12),
        ),
    )
    (published,) = _build_structural_groups((group,), scan_root="")
    assert published["id"] == "structural:duplicated_branches:k1"
    assert published["signature"] == {
        "version": "1",
        "stable": {
            "family": "duplicated_branches",
            "stmt_shape": "Return",
            "terminal_kind": "return",
            "control_flow": {"has_loop": True, "has_try": False, "nested_if": False},
        },
        "debug": {
            "calls": "2",
            "has_loop": "1",
            "has_try": "0",
            "nested_if": "0",
            "raises": "0",
            "stmt_seq": "Return",
            "terminal": "return",
        },
    }
    assert published["facts"] == {
        "occurrence_count": 2,
        "non_overlapping": True,
        "call_bucket": 2,
        "raise_bucket": 0,
    }


def test_a_cohort_drift_group_publishes_the_owners_signature_and_facts() -> None:
    signature = {
        "cohort_id": "c9",
        "cohort_arity": "3",
        "drift_fields": "b,a,b",
        "majority_terminal_kind": "return",
        "majority_guard_exit_profile": "gx",
        "majority_try_finally_profile": "tf",
        "majority_side_effect_order_profile": "so",
    }
    group = StructuralFindingGroup(
        finding_kind="clone_cohort_drift",
        finding_key="d1",
        signature=signature,
        items=(_occurrence("clone_cohort_drift", "d1", "pkg/a.py", "pkg.a:f", 1, 3),),
    )
    (published,) = _build_structural_groups((group,), scan_root="")
    assert published["signature"] == {
        "version": "1",
        "stable": {
            "family": "clone_cohort_drift",
            "cohort_id": "c9",
            "drift_fields": ["a", "b"],
            "majority_profile": {
                "terminal_kind": "return",
                "guard_exit_profile": "gx",
                "try_finally_profile": "tf",
                "side_effect_order_profile": "so",
            },
        },
        "debug": {key: signature[key] for key in sorted(signature)},
    }
    assert published["facts"] == {
        "cohort_id": "c9",
        "cohort_arity": 3,
        # absent in the signature: the member count stands in
        "divergent_members": 1,
        "drift_fields": ["a", "b"],
        "stable_majority_profile": {
            "terminal_kind": "return",
            "guard_exit_profile": "gx",
            "try_finally_profile": "tf",
            "side_effect_order_profile": "so",
        },
    }


# -- dead code ---------------------------------------------------------------


def test_dead_code_groups_publish_the_owners_facts() -> None:
    payload = {
        "families": {
            "dead_code": {
                "items": [
                    {
                        "qualname": "pkg.a:f",
                        "relative_path": "pkg/a.py",
                        "start_line": 1,
                        "end_line": 2,
                        "kind": "function",
                        "confidence": "high",
                        "reason": "test_only_reference",
                        "test_reference_sources": ["t2", "t1", "t2", ""],
                    }
                ],
                "unreachable_statements": [
                    {
                        "qualname": "pkg.a:g",
                        "relative_path": "pkg/a.py",
                        "start_line": 5,
                        "end_line": 6,
                        "reason": "after_return",
                        "statement_count": 2,
                    }
                ],
            }
        }
    }
    symbol, statement = _build_dead_code_groups(payload, scan_root="")
    assert symbol["id"] == "dead_code:pkg.a:f"
    assert symbol["facts"] == {
        "kind": "function",
        "confidence": "high",
        "reason": "test_only_reference",
        "test_reference_sources": ["t1", "t2"],
    }
    assert statement["id"] == "dead_code:pkg.a:g#5-6"
    assert statement["facts"] == {
        "reason": "after_return",
        "confidence": "high",
        "statement_count": 2,
        "policy_version": STATEMENT_REACHABILITY_POLICY_VERSION,
    }


# -- design ------------------------------------------------------------------


def _design_payload() -> dict[str, object]:
    def unit(qualname: str, **fields: object) -> dict[str, object]:
        return {
            "qualname": qualname,
            "relative_path": "pkg/a.py",
            "start_line": 1,
            "end_line": 9,
            "risk": "medium",
            **fields,
        }

    return {
        "families": {
            "complexity": {
                "items": [
                    unit("pkg.a:over", cyclomatic_complexity=6, nesting_depth=2),
                    unit("pkg.a:on", cyclomatic_complexity=5, nesting_depth=2),
                ]
            },
            "coupling": {
                "items": [
                    unit("pkg.a:Over", cbo=4, risk="high", coupled_classes=["X", "Y"]),
                    unit("pkg.a:On", cbo=3, coupled_classes=["X"]),
                ]
            },
            "cohesion": {
                "items": [
                    unit("pkg.a:Loose", lcom4=2, method_count=4, instance_var_count=1),
                    unit("pkg.a:Tight", lcom4=1, method_count=4, instance_var_count=1),
                ]
            },
            "dependencies": {
                "cycle_details": [
                    {
                        "modules": ["pkg.a", "pkg.b"],
                        "kind": "deferred_cycle",
                        "member_paths": ["pkg/a.py", None],
                    }
                ]
            },
            "coverage_join": {
                "summary": {"hotspot_threshold_percent": 60},
                "items": [
                    unit(
                        "pkg.a:cold",
                        cyclomatic_complexity=7,
                        risk="high",
                        executable_lines=10,
                        covered_lines=2,
                        coverage_permille=200,
                        coverage_status="measured",
                        coverage_hotspot=True,
                        scope_gap_hotspot=False,
                    ),
                    unit(
                        "pkg.a:unmapped",
                        cyclomatic_complexity=7,
                        executable_lines=0,
                        covered_lines=0,
                        coverage_permille=0,
                        coverage_status="missing_from_report",
                        coverage_hotspot=False,
                        scope_gap_hotspot=True,
                    ),
                ],
            },
        }
    }


_THRESHOLDS = {
    "complexity": {"value": 5},
    "coupling": {"value": 3},
    "cohesion": {"value": 2},
}


def _design_groups() -> dict[str, dict[str, object]]:
    return {
        str(group["id"]): group
        for group in _build_design_groups(
            _design_payload(), design_thresholds=_THRESHOLDS, scan_root=""
        )
    }


def test_design_groups_select_exactly_the_over_threshold_units() -> None:
    """Both sides of every boundary: strict for complexity and coupling,
    inclusive for cohesion -- the producer's own three comparisons."""
    assert sorted(_design_groups()) == [
        "design:cohesion:pkg.a:Loose",
        "design:complexity:pkg.a:over",
        "design:coupling:pkg.a:Over",
        "design:coverage:pkg.a:cold",
        "design:coverage:pkg.a:unmapped",
        "design:dependency:pkg.a -> pkg.b",
    ]


def test_a_complexity_hotspot_publishes_the_owners_item_and_facts() -> None:
    complexity = _design_groups()["design:complexity:pkg.a:over"]
    assert complexity["kind"] == "function_hotspot"
    assert complexity["items"] == [
        {
            "relative_path": "pkg/a.py",
            "qualname": "pkg.a:over",
            "start_line": 1,
            "end_line": 9,
            "cyclomatic_complexity": 6,
            "nesting_depth": 2,
            "risk": "medium",
        }
    ]
    assert complexity["facts"] == {"cyclomatic_complexity": 6, "nesting_depth": 2}


def test_coupling_and_cohesion_hotspots_publish_the_owners_facts() -> None:
    groups = _design_groups()
    coupling = groups["design:coupling:pkg.a:Over"]
    assert coupling["kind"] == "class_hotspot"
    coupling_items = coupling["items"]
    assert isinstance(coupling_items, list)
    assert coupling_items[0]["cbo"] == 4
    assert coupling_items[0]["coupled_classes"] == ["X", "Y"]
    assert coupling["facts"] == {"cbo": 4, "coupled_classes": ["X", "Y"]}
    cohesion = groups["design:cohesion:pkg.a:Loose"]
    cohesion_items = cohesion["items"]
    assert isinstance(cohesion_items, list)
    assert cohesion_items[0] == {
        "relative_path": "pkg/a.py",
        "qualname": "pkg.a:Loose",
        "start_line": 1,
        "end_line": 9,
        "lcom4": 2,
        "risk": "medium",
        "method_count": 4,
        "instance_var_count": 1,
    }
    assert cohesion["facts"] == {"lcom4": 2, "method_count": 4, "instance_var_count": 1}


def test_a_deferred_cycle_publishes_the_owners_members_and_wording() -> None:
    dependency = _design_groups()["design:dependency:pkg.a -> pkg.b"]
    assert dependency["kind"] == "deferred_cycle"
    assert dependency["items"] == [
        {"module": "pkg.a", "source_kind": "production", "relative_path": "pkg/a.py"},
        {"module": "pkg.b", "source_kind": "production"},
    ]
    assert dependency["facts"] == {
        "cycle_length": 2,
        "measured": (
            "cycle only over deferred edges (function-scope, module "
            "__getattr__, or lazy imports)"
        ),
    }


def test_coverage_groups_publish_the_owners_kind_item_and_facts() -> None:
    groups = _design_groups()
    cold = groups["design:coverage:pkg.a:cold"]
    assert cold["kind"] == "coverage_hotspot"
    assert cold["items"] == [
        {
            "relative_path": "pkg/a.py",
            "qualname": "pkg.a:cold",
            "start_line": 1,
            "end_line": 9,
            "risk": "high",
            "cyclomatic_complexity": 7,
            "coverage_permille": 200,
            "coverage_status": "measured",
            "covered_lines": 2,
            "executable_lines": 10,
            "coverage_hotspot": True,
            "scope_gap_hotspot": False,
        }
    ]
    assert cold["facts"] == {
        "coverage_permille": 200,
        "hotspot_threshold_percent": 60,
        "coverage_status": "measured",
        "covered_lines": 2,
        "executable_lines": 10,
        "cyclomatic_complexity": 7,
        "coverage_hotspot": True,
        "scope_gap_hotspot": False,
        "detail": "Joined line coverage is below the configured hotspot threshold.",
    }
    unmapped = groups["design:coverage:pkg.a:unmapped"]
    assert unmapped["kind"] == "coverage_scope_gap"
    unmapped_facts = unmapped["facts"]
    assert isinstance(unmapped_facts, dict)
    assert (
        unmapped_facts["detail"]
        == "The supplied coverage.xml did not map to this function's file."
    )


def test_an_import_cycle_publishes_the_import_time_wording() -> None:
    payload = {
        "families": {
            "dependencies": {
                "cycle_details": [
                    {
                        "modules": ["pkg.a", "pkg.b"],
                        "kind": "import_cycle",
                        "member_paths": ["pkg/a.py", "pkg/b.py"],
                    }
                ]
            }
        }
    }
    (group,) = _build_design_groups(payload, design_thresholds=None, scan_root="")
    assert group["facts"] == {
        "cycle_length": 2,
        "measured": "cycle over import-time edges",
    }


def test_the_realized_thresholds_fall_to_the_defaults_below_zero() -> None:
    defaults = {"complexity": 20, "coupling": 10, "cohesion": 4}
    assert design_thresholds(None) == defaults
    assert design_thresholds(
        {
            "complexity": {"value": -1},
            "coupling": {"value": 0},
            "cohesion": {"value": 7},
        }
    ) == {"complexity": 20, "coupling": 0, "cohesion": 7}


# -- authority ---------------------------------------------------------------


def test_authority_groups_publish_the_owners_locations_and_facts() -> None:
    payload = {
        "families": {
            "semantic_authority": {
                "items": [
                    {
                        "item_kind": "violation",
                        "suppressed": False,
                        "contract_id": "c",
                        "violation_id": "v1",
                        "kind": "shadow_producer",
                        "sink_identity": "pkg.a:sink",
                        "canonical_owner": "pkg.a:owner",
                        "authority_status": "shadow",
                        "producer_root_ids": ["producer:pkg.a:p2", "producer:pkg.a:p1"],
                        "effect_signature": "e",
                        "resolution_state": "resolved",
                        "producers": ["pkg.a:p2", "pkg.a:p1"],
                        "algorithm_revision": "1",
                        "locations": [
                            {
                                "relative_path": "tests/test_x.py",
                                "qualname": "pkg.a:sink",
                                "start_line": 3,
                                "end_line": 3,
                            },
                            {
                                "relative_path": "pkg/a.py",
                                "qualname": "pkg.a:sink",
                                "start_line": 8,
                                "end_line": 8,
                            },
                        ],
                    }
                ]
            }
        }
    }
    groups, suppressed = _build_authority_groups(payload)
    assert suppressed == 0
    (group,) = groups
    assert group["id"] == "authority:c:v1"
    assert group["count"] == 2
    assert group["items"] == [
        {
            "relative_path": "tests/test_x.py",
            "qualname": "pkg.a:sink",
            "start_line": 3,
            "end_line": 3,
            "source_kind": "tests",
        },
        {
            "relative_path": "pkg/a.py",
            "qualname": "pkg.a:sink",
            "start_line": 8,
            "end_line": 8,
            "source_kind": "production",
        },
    ]
    assert group["facts"] == {
        "violation_id": "v1",
        "contract_id": "c",
        "violation_kind": "shadow_producer",
        "sink_identity": "pkg.a:sink",
        "canonical_owner": "pkg.a:owner",
        "authority_status": "shadow",
        "producer_root_ids": ["producer:pkg.a:p1", "producer:pkg.a:p2"],
        "effect_signature": "e",
        "resolution_state": "resolved",
        "producers": ["pkg.a:p1", "pkg.a:p2"],
        "algorithm_revision": "1",
    }


# -- coverage flags, read through the metrics payload -----------------------


def _fact(
    qualname: str, *, risk: str, permille_value: int, status: str
) -> UnitCoverageFact:
    return UnitCoverageFact(
        qualname=qualname,
        filepath="pkg/a.py",
        start_line=1,
        end_line=4,
        cyclomatic_complexity=7,
        risk=risk,  # type: ignore[arg-type]
        executable_lines=10,
        covered_lines=permille_value // 100,
        coverage_permille=permille_value,
        coverage_status=status,  # type: ignore[arg-type]
    )


def test_the_payload_rows_carry_the_owners_hotspot_flags_on_both_boundaries() -> None:
    join = CoverageJoinResult(
        coverage_xml="coverage.xml",
        status="ok",
        hotspot_threshold_percent=60,
        units=(
            _fact("pkg.a:cold", risk="high", permille_value=500, status="measured"),
            _fact("pkg.a:low", risk="low", permille_value=100, status="measured"),
            _fact(
                "pkg.a:gap",
                risk="medium",
                permille_value=0,
                status="missing_from_report",
            ),
            # exactly on the threshold: 600 permille is 60 percent, not below
            _fact("pkg.a:edge", risk="high", permille_value=600, status="measured"),
            # unmapped but low risk: neither flag, the risk gate holds
            _fact(
                "pkg.a:lowgap",
                risk="low",
                permille_value=0,
                status="missing_from_report",
            ),
        ),
    )
    flags = {
        str(row["qualname"]): (
            row["coverage_hotspot"],
            row["scope_gap_hotspot"],
            row["coverage_review_item"],
        )
        for row in _coverage_join_rows(join)
    }
    assert flags == {
        "pkg.a:cold": (True, False, True),
        "pkg.a:low": (False, False, False),
        "pkg.a:gap": (False, True, True),
        "pkg.a:edge": (False, False, False),
        "pkg.a:lowgap": (False, False, False),
    }


def test_the_coverage_ratio_rounds_per_thousand_and_survives_an_empty_base() -> None:
    assert permille(1, 3) == 333
    assert permille(2, 3) == 667
    assert permille(5, 0) == 0
    assert permille(10, 10) == 1000

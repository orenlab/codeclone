# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from codeclone.models import Suggestion
from codeclone.report.document.derived import _build_derived_module_map


def _payload(
    *,
    edges: Sequence[tuple[str, str]],
    cycles: Sequence[Sequence[str]] = (),
    chains: Sequence[Sequence[str]] = (),
    overloaded: Sequence[dict[str, object]] = (),
    population_status: str = "ok",
) -> dict[str, object]:
    modules = {node for edge in edges for node in edge}
    return {
        "families": {
            "dependencies": {
                "summary": {"modules": len(modules), "edges": len(edges)},
                "items": [
                    {
                        "source": source,
                        "target": target,
                        "import_type": "import",
                        "line": index + 1,
                    }
                    for index, (source, target) in enumerate(edges)
                ],
                "cycles": [list(cycle) for cycle in cycles],
                "longest_chains": [list(chain) for chain in chains],
            },
            "overloaded_modules": {
                "summary": {"population_status": population_status},
                "items": [dict(item) for item in overloaded],
            },
        }
    }


def _overloaded(
    module: str,
    *,
    fan_in: int = 0,
    fan_out: int = 0,
    score: float = 0.0,
    dependency_score: float = 0.0,
    candidate_status: str = "non_candidate",
    candidate_reasons: Sequence[str] = (),
    instability: float = 0.0,
    source_kind: str = "production",
) -> dict[str, object]:
    return {
        "module": module,
        "filepath": module.replace(".", "/") + ".py",
        "source_kind": source_kind,
        "fan_in": fan_in,
        "fan_out": fan_out,
        "score": score,
        "dependency_score": dependency_score,
        "candidate_status": candidate_status,
        "candidate_reasons": list(candidate_reasons),
        "instability": instability,
    }


def test_small_repo_default_zoom_modules_not_truncated() -> None:
    module_map: Any = _build_derived_module_map(
        _payload(edges=[("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")])
    )
    assert module_map["schema_version"] == "1"
    assert module_map["scope"] == "report_only"
    assert module_map["summary"]["available"] is True
    assert module_map["default_zoom"] == "modules"
    assert module_map["summary"]["module_count"] == 3
    assert module_map["graph_modules"]["truncation"]["truncated"] is False


def test_dependencies_skipped_shell() -> None:
    module_map: Any = _build_derived_module_map({"families": {}})
    assert module_map["summary"]["available"] is False
    assert module_map["summary"]["reason"] == "dependencies_skipped"
    assert module_map["graph_packages"]["nodes"] == []
    assert module_map["graph_modules"]["nodes"] == []
    assert module_map["unwind_candidates"] == []


def test_monolith_avoids_depth_one() -> None:
    mods = [f"app.m{index}" for index in range(50)]
    edges = [(mods[index], mods[index + 1]) for index in range(len(mods) - 1)]
    module_map: Any = _build_derived_module_map(_payload(edges=edges))
    assert module_map["summary"]["module_count"] == 50
    assert module_map["default_zoom"] == "packages"
    assert module_map["graph_packages"]["package_depth"] == 2


def test_overmerge_uses_depth_three() -> None:
    mods = [f"{root}.x.m{index}" for root in "abc" for index in range(30)]
    edges = [(mods[index], mods[index + 1]) for index in range(len(mods) - 1)]
    module_map: Any = _build_derived_module_map(_payload(edges=edges))
    assert module_map["summary"]["module_count"] == 90
    assert module_map["graph_packages"]["package_depth"] == 3


def test_medium_repo_full_package_graph_depth_two() -> None:
    mods = [f"p{pkg}.sub.m{index}" for pkg in range(10) for index in range(5)]
    edges = [(mods[index], mods[index + 1]) for index in range(len(mods) - 1)]
    module_map: Any = _build_derived_module_map(_payload(edges=edges))
    assert module_map["summary"]["module_count"] == 50
    assert module_map["default_zoom"] == "packages"
    assert module_map["graph_packages"]["package_depth"] == 2
    assert module_map["graph_packages"]["truncation"]["truncated"] is False


def test_flat_namespace_uses_depth_one() -> None:
    # >40 modules (past row B), 15 roots (P1<=28), 45 depth-2 prefixes (P2>28) -> row F.
    mods = [
        f"r{root}.s{sub}.x{leaf}"
        for root in range(15)
        for sub in range(3)
        for leaf in range(2)
    ]
    edges = [(mods[index], mods[index + 1]) for index in range(len(mods) - 1)]
    module_map: Any = _build_derived_module_map(_payload(edges=edges))
    assert module_map["summary"]["module_count"] == 90
    assert module_map["graph_packages"]["package_depth"] == 1


def test_edge_aggregation_weights() -> None:
    module_map: Any = _build_derived_module_map(
        _payload(edges=[("pkg.a", "pkg.b"), ("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")])
    )
    weights = {
        (edge["source"], edge["target"]): edge["weight"]
        for edge in module_map["graph_modules"]["edges"]
    }
    assert weights[("pkg.a", "pkg.b")] == 2
    assert weights[("pkg.b", "pkg.c")] == 1
    assert module_map["summary"]["edge_count"] == 2


def test_truncation_preserves_cycle_nodes_at_package_zoom() -> None:
    mods = [f"pkg.m{index}" for index in range(45)]
    edges = [(mods[0], mods[index]) for index in range(1, 43)]
    edges += [(mods[43], mods[44]), (mods[44], mods[43])]
    module_map: Any = _build_derived_module_map(
        _payload(edges=edges, cycles=[[mods[43], mods[44]]])
    )
    assert module_map["default_zoom"] == "packages"
    assert module_map["graph_packages"]["truncation"]["truncated"] is True
    package_nodes = {node["id"] for node in module_map["graph_packages"]["nodes"]}
    assert "pkg.m43" in package_nodes
    assert "pkg.m44" in package_nodes


def test_unwind_candidate_signals_and_ignore_graph_truncation() -> None:
    overloaded = [
        _overloaded(
            "a.b",
            fan_in=10,
            fan_out=5,
            dependency_score=0.9,
            candidate_status="candidate",
            candidate_reasons=["dependency_pressure", "hub_like_shape"],
        ),
        _overloaded("z.z", candidate_status="non_candidate"),
    ]
    module_map: Any = _build_derived_module_map(
        _payload(
            edges=[("a.b", "c.d")],
            chains=[["a.b", "c.d"]],
            overloaded=overloaded,
        )
    )
    rows = {row["module"]: row for row in module_map["unwind_candidates"]}
    assert "z.z" not in rows
    assert rows["a.b"]["signals"] == [
        "dependency_pressure",
        "hub_like_shape",
        "chain_bottleneck",
    ]


def test_payload_is_order_independent() -> None:
    edges = [("a.b", "c.d"), ("c.d", "e.f"), ("a.b", "e.f")]
    overloaded = [_overloaded(module, fan_in=2, fan_out=1) for module in "ab"]
    first = _build_derived_module_map(_payload(edges=edges, overloaded=overloaded))
    second = _build_derived_module_map(
        _payload(edges=list(reversed(edges)), overloaded=list(reversed(overloaded)))
    )
    assert first == second


def test_ranked_only_population_has_no_candidate_overlay() -> None:
    overloaded = [
        _overloaded("a.b", candidate_status="ranked_only"),
        _overloaded("c.d", candidate_status="ranked_only"),
    ]
    module_map: Any = _build_derived_module_map(
        _payload(
            edges=[("a.b", "c.d")],
            overloaded=overloaded,
            population_status="limited",
        )
    )
    assert module_map["summary"]["overloaded_population_status"] == "limited"
    assert module_map["summary"]["overloaded_candidate_count"] == 0
    statuses = {
        node["overloaded"]["candidate_status"]
        for node in module_map["graph_modules"]["nodes"]
    }
    assert "candidate" not in statuses


def _review_suggestion(
    *,
    severity: str,
    category: str,
    family: str,
    title: str,
    priority: float,
    effort: str,
    subject_key: str,
) -> Suggestion:
    return Suggestion(
        severity=cast("Any", severity),
        category=cast("Any", category),
        title=title,
        location=f"pkg/{subject_key}.py:1",
        steps=("do the thing",),
        effort=cast("Any", effort),
        priority=priority,
        finding_family=cast("Any", family),
        subject_key=subject_key,
        fact_summary=f"{title} summary",
    )


def _finding_group(
    *,
    gid: str,
    family: str,
    category: str,
    severity: str,
    priority: float,
    novelty: str = "known",
    count: int = 1,
    source_kind: str = "production",
    qualname: str = "pkg.mod:fn",
    path: str = "pkg/mod.py",
    line: int = 10,
) -> dict[str, Any]:
    return {
        "id": gid,
        "family": family,
        "category": category,
        "kind": category,
        "severity": severity,
        "priority": priority,
        "novelty": novelty,
        "count": count,
        "source_scope": {"dominant_kind": source_kind, "impact_scope": "runtime"},
        "spread": {"files": 1, "functions": 1},
        "items": [
            {
                "relative_path": path,
                "qualname": qualname,
                "start_line": line,
                "end_line": line + 3,
                "source_kind": source_kind,
            }
        ],
    }


def _findings_payload(
    *,
    clones: tuple[dict[str, Any], ...] = (),
    structural: tuple[dict[str, Any], ...] = (),
    dead_code: tuple[dict[str, Any], ...] = (),
    design: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    from codeclone.domain.findings import (
        FAMILY_CLONES,
        FAMILY_DEAD_CODE,
        FAMILY_STRUCTURAL,
    )

    return {
        "groups": {
            FAMILY_CLONES: {"functions": list(clones), "blocks": [], "segments": []},
            FAMILY_STRUCTURAL: {"groups": list(structural)},
            FAMILY_DEAD_CODE: {"groups": list(dead_code)},
            "design": {"groups": list(design)},
        }
    }


def test_build_derived_review_queue_projects_findings_across_families() -> None:
    from codeclone.domain.findings import (
        CLONE_KIND_FUNCTION,
        FAMILY_CLONE,
        FAMILY_DEAD_CODE,
        FAMILY_DESIGN,
        FAMILY_STRUCTURAL,
    )
    from codeclone.report.document.derived import _build_derived_review_queue

    findings = _findings_payload(
        clones=(
            _finding_group(
                gid="clone:a",
                family=FAMILY_CLONE,
                category=CLONE_KIND_FUNCTION,
                severity="critical",
                priority=0.9,
                count=3,
            ),
        ),
        structural=(
            _finding_group(
                gid="struct:b",
                family=FAMILY_STRUCTURAL,
                category="duplicated_branches",
                severity="info",
                priority=0.4,
                novelty="new",
            ),
        ),
        dead_code=(
            _finding_group(
                gid="dead:c",
                family=FAMILY_DEAD_CODE,
                category="function",
                severity="warning",
                priority=0.6,
            ),
        ),
        design=(
            _finding_group(
                gid="design:d",
                family=FAMILY_DESIGN,
                category="complexity",
                severity="warning",
                priority=0.5,
            ),
        ),
    )
    queue: Any = _build_derived_review_queue(findings, None)
    assert queue["schema_version"] == "2"
    assert queue["scope"] == "report_only"
    assert queue["summary"] == {
        "total": 4,
        "reviewed": 0,
        "actionable": 0,
        "by_severity": {"critical": 1, "warning": 2, "info": 1},
        "by_family": {"clones": 1, "dead_code": 1, "design": 1, "structural": 1},
        "by_novelty": {"new": 1, "known": 3},
        "top_priority": 0.9,
    }
    # priority-ordered: clone(0.9) -> dead(0.6) -> design(0.5) -> struct(0.4)
    assert [item["finding_id"] for item in queue["items"]] == [
        "clone:a",
        "dead:c",
        "design:d",
        "struct:b",
    ]
    clone_item = queue["items"][0]
    assert clone_item["family"] == "clones"
    assert clone_item["has_action"] is False
    assert clone_item["title"] == "Function clone group (3 occurrences)"
    assert str(clone_item["location"]).startswith("pkg/mod.py:10")
    struct_item = queue["items"][-1]
    assert struct_item["novelty"] == "new"
    assert struct_item["title"] == "Duplicated branches"


def test_build_derived_review_queue_enriches_with_matching_suggestion() -> None:
    from codeclone.domain.findings import FAMILY_STRUCTURAL
    from codeclone.findings.ids import structural_group_id
    from codeclone.report.document.derived import _build_derived_review_queue

    gid = structural_group_id("duplicated_branches", "b")
    findings = _findings_payload(
        structural=(
            _finding_group(
                gid=gid,
                family=FAMILY_STRUCTURAL,
                category="duplicated_branches",
                severity="warning",
                priority=0.5,
            ),
        )
    )
    suggestion = _review_suggestion(
        severity="warning",
        category="structural",
        family="structural",
        title="Refactor duplicated branches",
        priority=0.5,
        effort="moderate",
        subject_key="b",
    )
    queue: Any = _build_derived_review_queue(findings, [suggestion])
    assert queue["summary"]["total"] == 1
    assert queue["summary"]["actionable"] == 1
    item = queue["items"][0]
    assert item["finding_id"] == gid
    assert item["has_action"] is True
    # suggestion wins on title + carries remediation steps
    assert item["title"] == "Refactor duplicated branches"
    assert item["effort"] == "moderate"
    assert item["steps"] == ["do the thing"]


def test_build_derived_review_queue_empty_shell() -> None:
    from codeclone.report.document.derived import _build_derived_review_queue

    queue: Any = _build_derived_review_queue({}, None)
    assert queue["items"] == []
    assert queue["summary"]["total"] == 0
    assert queue["summary"]["top_priority"] == 0.0
    assert queue["summary"]["by_severity"] == {"critical": 0, "warning": 0, "info": 0}
    assert queue["summary"]["by_novelty"] == {"new": 0, "known": 0}
    assert queue["summary"]["by_family"] == {}

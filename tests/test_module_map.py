# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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

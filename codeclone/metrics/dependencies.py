# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

from ..models import (
    DependencyCycleDetail,
    DependencyCycleKind,
    DepGraph,
    ModuleDep,
    ModuleRegistryHandle,
)
from ..paths.module_identity.projection import module_path_from_registry
from ..utils import coerce

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

DepAdjacency = dict[str, set[str]]


def _registry_modules(registry: ModuleRegistryHandle) -> frozenset[str]:
    entry_modules = {
        module.module
        for entry in registry.entries_by_module.values()
        if entry.analyzed and (module := entry.identity.python_module) is not None
    }
    prefix_modules = {prefix.module for prefix in registry.package_prefixes}
    return frozenset(sorted(entry_modules | prefix_modules))


def _is_internal_target(
    target: str,
    *,
    registry: ModuleRegistryHandle,
) -> bool:
    return bool(target) and (
        target in registry.entries_by_module
        or any(prefix.module == target for prefix in registry.package_prefixes)
    )


def _unique_sorted_edges(deps: Sequence[ModuleDep]) -> tuple[ModuleDep, ...]:
    return tuple(
        sorted(
            {
                (dep.source, dep.target, dep.import_type, dep.line): dep for dep in deps
            }.values(),
            key=lambda dep: (dep.source, dep.target, dep.import_type, dep.line),
        )
    )


def build_import_graph(
    *,
    modules: Iterable[str],
    deps: Sequence[ModuleDep],
) -> DepAdjacency:
    graph: DepAdjacency = {module: set() for module in sorted(set(modules))}
    for dep in deps:
        graph.setdefault(dep.source, set()).add(dep.target)
        graph.setdefault(dep.target, set())
    return graph


def _tarjan_scc(graph: DepAdjacency) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    index_by_node: dict[str, int] = {}
    low_by_node: dict[str, int] = {}
    components: list[list[str]] = []

    def _strong_connect(node: str) -> None:
        nonlocal index
        index_by_node[node] = index
        low_by_node[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in sorted(graph.get(node, set())):
            if neighbor not in index_by_node:
                _strong_connect(neighbor)
                low_by_node[node] = min(low_by_node[node], low_by_node[neighbor])
            elif neighbor in on_stack:
                low_by_node[node] = min(low_by_node[node], index_by_node[neighbor])

        if low_by_node[node] == index_by_node[node]:
            component: list[str] = []
            while True:
                candidate = stack.pop()
                on_stack.remove(candidate)
                component.append(candidate)
                if candidate == node:
                    break
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in index_by_node:
            _strong_connect(node)

    return components


def find_cycles(graph: DepAdjacency) -> tuple[tuple[str, ...], ...]:
    return tuple(
        sorted(
            tuple(component) for component in _tarjan_scc(graph) if len(component) > 1
        )
    )


def _classify_cycle(
    cycle: tuple[str, ...],
    *,
    import_time_edges: Sequence[ModuleDep],
) -> DependencyCycleKind:
    """The cycle law, by construction: critical iff import-time edges still cycle.

    The subgraph is restricted to the cycle's own members AND to edges whose
    binding is ``import_time``; if any strongly connected component survives
    there, the crash-at-import risk is real and the cycle stays critical.
    Deferred, lazy, and typing edges cannot rescue or demote anything here —
    only genuine import-time structure decides.
    """

    members = set(cycle)
    subgraph: DepAdjacency = {module: set() for module in cycle}
    for dep in import_time_edges:
        if dep.source in members and dep.target in members:
            subgraph[dep.source].add(dep.target)
    return "import_cycle" if find_cycles(subgraph) else "deferred_cycle"


def _cycle_details(
    cycles: tuple[tuple[str, ...], ...],
    *,
    edges: Sequence[ModuleDep],
    registry: ModuleRegistryHandle,
) -> tuple[DependencyCycleDetail, ...]:
    import_time_edges = tuple(dep for dep in edges if dep.binding == "import_time")
    return tuple(
        DependencyCycleDetail(
            modules=cycle,
            kind=_classify_cycle(cycle, import_time_edges=import_time_edges),
            member_paths=tuple(
                module_path_from_registry(module, registry) for module in cycle
            ),
        )
        for cycle in cycles
    )


def _longest_path_from(
    node: str,
    *,
    graph: DepAdjacency,
    visiting: set[str],
    memo: dict[str, int],
) -> int:
    if node in memo:
        return memo[node]
    if node in visiting:
        return 0

    visiting.add(node)
    best = 1
    for neighbor in sorted(graph.get(node, set())):
        best = max(
            best,
            1
            + _longest_path_from(
                neighbor,
                graph=graph,
                visiting=visiting,
                memo=memo,
            ),
        )
    visiting.remove(node)
    memo[node] = best
    return best


def max_depth(graph: DepAdjacency) -> int:
    if not graph:
        return 0
    memo: dict[str, int] = {}
    best = 0
    for node in sorted(graph):
        best = max(
            best,
            _longest_path_from(node, graph=graph, visiting=set(), memo=memo),
        )
    return best


def depth_profile(graph: DepAdjacency) -> tuple[float, int]:
    if not graph:
        return 0.0, 0

    memo: dict[str, int] = {}
    depths = sorted(
        _longest_path_from(node, graph=graph, visiting=set(), memo=memo)
        for node in sorted(graph)
    )
    if not depths:
        return 0.0, 0

    avg_depth = sum(depths) / len(depths)
    percentile_index = max(0, ceil(len(depths) * 0.95) - 1)
    return avg_depth, int(depths[percentile_index])


def _longest_path_nodes_from(
    node: str,
    *,
    graph: DepAdjacency,
    visiting: set[str],
    memo: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    if node in memo:
        return memo[node]
    if node in visiting:
        return (node,)

    visiting.add(node)
    best_path: tuple[str, ...] = (node,)
    for neighbor in sorted(graph.get(node, set())):
        suffix = _longest_path_nodes_from(
            neighbor,
            graph=graph,
            visiting=visiting,
            memo=memo,
        )
        candidate = (node, *suffix)
        if len(candidate) > len(best_path) or (
            len(candidate) == len(best_path) and candidate < best_path
        ):
            best_path = candidate
    visiting.remove(node)
    memo[node] = best_path
    return best_path


def longest_chains(
    graph: DepAdjacency,
    *,
    limit: int = 5,
) -> tuple[tuple[str, ...], ...]:
    if not graph or limit <= 0:
        return ()

    memo: dict[str, tuple[str, ...]] = {}
    chains = {
        _longest_path_nodes_from(
            node,
            graph=graph,
            visiting=set(),
            memo=memo,
        )
        for node in sorted(graph)
    }
    sorted_chains = sorted(
        chains,
        key=lambda chain: (-len(chain), chain),
    )
    return tuple(sorted_chains[:limit])


def build_dep_graph(
    *,
    registry: ModuleRegistryHandle,
    deps: Sequence[ModuleDep],
) -> DepGraph:
    base_modules = _registry_modules(registry)
    internal_edges = _unique_sorted_edges(
        tuple(
            dep
            for dep in deps
            if dep.source and _is_internal_target(dep.target, registry=registry)
        )
    )
    graph_modules = frozenset(
        sorted(
            {
                *base_modules,
                *(dep.source for dep in internal_edges if dep.source),
                *(dep.target for dep in internal_edges if dep.target),
            }
        )
    )
    graph = build_import_graph(modules=graph_modules, deps=internal_edges)
    # Runtime cycles only: TYPE_CHECKING edges never execute, so a cycle they
    # close is not a runtime fact. They stay visible in ``edges`` untouched;
    # depth and chain metrics keep reading the full graph because layering is
    # a design question, not an import-order one.
    runtime_graph = build_import_graph(
        modules=graph_modules,
        deps=tuple(dep for dep in internal_edges if dep.binding != "type_checking"),
    )
    cycles = find_cycles(runtime_graph)
    depth = max_depth(graph)
    avg_depth, p95_depth = depth_profile(graph)
    chains = longest_chains(graph)
    return DepGraph(
        modules=frozenset(graph.keys()),
        edges=internal_edges,
        cycles=cycles,
        max_depth=depth,
        avg_depth=avg_depth,
        p95_depth=p95_depth,
        longest_chains=chains,
        cycle_details=_cycle_details(cycles, edges=internal_edges, registry=registry),
    )


def select_dependency_graph_nodes(
    edges: Sequence[tuple[str, str]],
    *,
    dep_cycles: Sequence[object],
    longest_chains: Sequence[object],
    max_nodes: int,
    max_edges: int,
    node_id_fn: Callable[[str], str] | None = None,
) -> tuple[list[str], list[tuple[str, str]], dict[str, object]]:
    """Deterministic subgraph sample over directed import edges.

    Seeds cycle members, then longest-chain members, then fills remaining slots
    by descending node degree (tie-break id ascending), so structurally
    important nodes survive downsampling. ``node_id_fn`` maps a module name to
    the active zoom id (package prefix or identity) before membership checks
    when seeding from cycles and chains. Returns the shown nodes, the induced
    (edge-capped) edges, and a truncation metadata mapping.
    """
    all_nodes = sorted({part for edge in edges for part in edge})
    node_universe_count = len(all_nodes)
    edge_universe_count = len(edges)
    if node_universe_count > max_nodes:
        degree_count: dict[str, int] = dict.fromkeys(all_nodes, 0)
        for source, target in edges:
            degree_count[source] = degree_count.get(source, 0) + 1
            degree_count[target] = degree_count.get(target, 0) + 1
        all_node_set = set(all_nodes)
        nodes: list[str] = []
        node_set: set[str] = set()

        def _seed_node(node: object) -> None:
            node_name = str(node).strip()
            if node_id_fn is not None:
                node_name = node_id_fn(node_name)
            if (
                not node_name
                or node_name not in all_node_set
                or node_name in node_set
                or len(nodes) >= max_nodes
            ):
                return
            nodes.append(node_name)
            node_set.add(node_name)

        for cycle in dep_cycles:
            for node in coerce.as_sequence(cycle):
                _seed_node(node)
        for chain in longest_chains:
            for node in coerce.as_sequence(chain):
                _seed_node(node)
        for node in sorted(
            all_nodes, key=lambda item: (-degree_count.get(item, 0), item)
        ):
            _seed_node(node)
            if len(nodes) >= max_nodes:
                break
        nodes.sort()
    else:
        nodes = list(all_nodes)
    node_set = set(nodes)
    filtered = [
        (source, target)
        for source, target in edges
        if source in node_set and target in node_set
    ][:max_edges]
    truncation: dict[str, object] = {
        "truncated": len(nodes) < node_universe_count
        or len(filtered) < edge_universe_count,
        "node_universe_count": node_universe_count,
        "node_shown_count": len(nodes),
        "edge_universe_count": edge_universe_count,
        "edge_shown_count": len(filtered),
        "seed_policy": "cycles_then_chains_then_degree",
    }
    return nodes, filtered, truncation

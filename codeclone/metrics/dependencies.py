"""Module dependency graph and deterministic cycle detection."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..models import DepGraph, ModuleDep

DepAdjacency = dict[str, set[str]]


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
    cycles: list[tuple[str, ...]] = []
    for component in _tarjan_scc(graph):
        if len(component) > 1:
            cycles.append(tuple(component))
            continue
        node = component[0]
        if node in graph and node in graph[node]:
            cycles.append((node,))
    return tuple(sorted(cycles))


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


def build_dep_graph(*, modules: Iterable[str], deps: Sequence[ModuleDep]) -> DepGraph:
    graph = build_import_graph(modules=modules, deps=deps)
    cycles = find_cycles(graph)
    depth = max_depth(graph)
    chains = longest_chains(graph)
    unique_edges = tuple(
        sorted(
            {
                (dep.source, dep.target, dep.import_type, dep.line): dep for dep in deps
            }.values(),
            key=lambda dep: (dep.source, dep.target, dep.import_type, dep.line),
        )
    )
    return DepGraph(
        modules=frozenset(graph.keys()),
        edges=unique_edges,
        cycles=cycles,
        max_depth=depth,
        longest_chains=chains,
    )
